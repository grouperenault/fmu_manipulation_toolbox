"""The tools of the MCP server as a JSON command line (``fmutool-agent``).

An agent without an MCP client — a sandbox that only runs commands, a script —
calls the same tools here::

    fmutool-agent list-tools
    fmutool-agent inspect_fmu_file --args '{"path": "model.fmu", "causality": ["input"]}'
    fmutool-agent add_fmu --state assembly.json --args '{"path": "model.fmu"}'

The tools are those of
:class:`~fmu_manipulation_toolbox.assistant.tools.Toolbox`, which the MCP server
also calls: same names, same arguments, same results. The result is printed on
**stdout** as JSON — an object as is, any other value as ``{"result": ...}``,
as MCP clients receive it — and the logs go to stderr. A failure prints
``{"error": "..."}`` and exits with a non-zero code.

The assembly tools keep the assembly in the file given by ``--state``, read
before the tool runs and written back after a change: each call is a separate
process. This command needs neither ``fastmcp`` nor Pydantic.
"""

import argparse
import inspect
import json
import logging
import os
import sys
import tempfile
import types
import typing
from pathlib import Path
from typing import Any, Literal

from .utils import make_wide
from ..assistant.headless import DEFAULT_CONTAINER_NAME, HeadlessAssemblyBridge
from ..assistant.paths import PathPolicy, PathValidationError
from ..assistant.tools import TOOLS, Toolbox, is_actionable
from ..version import __version__ as version

#: Tools working on the assembly: they need `--state`.
ASSEMBLY_TOOLS = frozenset({
    "list_fmus", "list_fmu_ports", "add_fmu", "remove_fmu", "add_link", "add_links", "remove_link",
    "expose_input", "expose_output", "set_start_value", "unset_start_value", "set_container_options",
    "get_assembly_json", "analyze_assembly", "save_as_json", "save_as_fmu",
})

#: Assembly tools that change it: the state is written back after them.
CHANGING_TOOLS = frozenset({
    "add_fmu", "remove_fmu", "add_link", "add_links", "remove_link", "expose_input", "expose_output",
    "set_start_value", "unset_start_value", "set_container_options",
})

#: Exit codes.
EXIT_TOOL_ERROR = 1
EXIT_USAGE_ERROR = 2

logger = logging.getLogger("fmu_manipulation_toolbox")


class UsageError(ValueError):
    """The command line or the arguments of the tool are wrong."""


# --------------------------------------------------------------------------- #
#                               arguments                                     #
# --------------------------------------------------------------------------- #
def parameters(tool: str) -> list[inspect.Parameter]:
    """Parameters of a tool, in order."""
    return [parameter for name, parameter in inspect.signature(getattr(Toolbox, tool)).parameters.items()
            if name != "self"]


def _hints(tool: str) -> dict[str, Any]:
    return typing.get_type_hints(getattr(Toolbox, tool))


def type_name(annotation: Any) -> str:
    """Short, JSON-oriented name of a type annotation, for `list-tools` and the error messages."""
    origin = typing.get_origin(annotation)
    if origin is Literal:
        return " | ".join(json.dumps(value) for value in typing.get_args(annotation))
    if origin in (typing.Union, types.UnionType):
        return " | ".join(type_name(arg) for arg in typing.get_args(annotation) if arg is not type(None))
    if origin is list:
        return f"list[{type_name(typing.get_args(annotation)[0])}]"
    if origin is dict:
        return f"object of {type_name(typing.get_args(annotation)[1])}"
    return {str: "string", int: "integer", float: "number", bool: "boolean"}.get(annotation, "any")


def _matches(value: Any, annotation: Any) -> bool:
    """Whether a JSON value fits a type annotation of a `Toolbox` method."""
    if annotation is Any:
        return True
    origin = typing.get_origin(annotation)
    if origin is Literal:
        return any(value == choice and type(value) is type(choice) for choice in typing.get_args(annotation))
    if origin in (typing.Union, types.UnionType):
        return any(_matches(value, arg) for arg in typing.get_args(annotation))
    if annotation is type(None):
        return value is None
    if origin is list:
        (item,) = typing.get_args(annotation)
        return isinstance(value, list) and all(_matches(element, item) for element in value)
    if origin is dict:
        key, item = typing.get_args(annotation)
        return isinstance(value, dict) and all(_matches(k, key) and _matches(v, item) for k, v in value.items())
    if annotation is bool:
        return isinstance(value, bool)
    if annotation is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if annotation is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if annotation is str:
        return isinstance(value, str)
    return True


def check_arguments(tool: str, arguments: Any) -> dict[str, Any]:
    """The arguments of `tool`, checked against its signature.

    Raises:
        UsageError: Unknown, missing or ill-typed arguments; the message lists what is accepted.
    """
    if not isinstance(arguments, dict):
        raise UsageError(f"The arguments of '{tool}' must be a JSON object.")
    accepted = parameters(tool)
    names = [parameter.name for parameter in accepted]
    problems = [f"unknown argument '{name}' (allowed: {', '.join(names) or 'none'})"
                for name in arguments if name not in names]
    hints = _hints(tool)
    for parameter in accepted:
        if parameter.name not in arguments:
            if parameter.default is inspect.Parameter.empty:
                problems.append(f"missing required argument '{parameter.name}'")
        elif not _matches(arguments[parameter.name], hints[parameter.name]):
            given = json.dumps(arguments[parameter.name])
            given = given if len(given) <= 60 else given[:57] + "..."
            problems.append(f"'{parameter.name}' expects {type_name(hints[parameter.name])} (got {given})")
    if problems:
        raise UsageError(f"Invalid arguments for '{tool}': {'; '.join(problems)}.")
    return arguments


def describe_tools() -> dict[str, Any]:
    """What `list-tools` prints."""
    described = []
    for tool in TOOLS:
        hints = _hints(tool)
        described.append({
            "name": tool,
            "description": inspect.getdoc(getattr(Toolbox, tool)).splitlines()[0],
            "parameters": [{"name": parameter.name, "type": type_name(hints[parameter.name]),
                            **({"default": parameter.default}
                               if parameter.default is not inspect.Parameter.empty else {"required": True})}
                           for parameter in parameters(tool)],
            "needs_state": tool in ASSEMBLY_TOOLS,
        })
    return {"tools": described}


# --------------------------------------------------------------------------- #
#                                  state                                      #
# --------------------------------------------------------------------------- #
def load_state(path: Path | None, name: str) -> HeadlessAssemblyBridge:
    """The bridge saved in `path`, or an empty one if the file does not exist yet."""
    if path is None or not path.exists():
        return HeadlessAssemblyBridge(name)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UsageError(f"'{path}' is not a JSON file: {exc}.") from None
    return HeadlessAssemblyBridge.from_state(state)


def save_state(path: Path, bridge: HeadlessAssemblyBridge) -> None:
    """Write the state through a temporary file, so that an interrupted call leaves the previous one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".tmp",
                                     delete=False) as file:
        json.dump(bridge.state(), file, indent=2)
    os.replace(file.name, path)


# --------------------------------------------------------------------------- #
#                               command line                                  #
# --------------------------------------------------------------------------- #
def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="fmutool-agent",
        description="Call one tool of the FMU Manipulation Toolbox assistant; the result is printed as JSON.",
        formatter_class=make_wide(argparse.ArgumentDefaultsHelpFormatter),
        add_help=False,
        epilog="'fmutool-agent list-tools' lists the tools and their arguments. See: "
               "https://grouperenault.github.io/fmu_manipulation_toolbox/user-guide/agent-skills/")
    parser.add_argument("-h", "-help", "--help", action="help")
    parser.add_argument("tool", metavar="TOOL", help="Name of the tool, or 'list-tools'.")
    parser.add_argument("-args", "--args", dest="arguments", default="{}", metavar="JSON",
                        help="Arguments of the tool, as a JSON object; '-' reads them from stdin.")
    parser.add_argument("-state", "--state", dest="state", default=None, metavar="FILE",
                        help="File keeping the assembly between calls: required by the assembly tools, created "
                             "by the first one.")
    parser.add_argument("-name", "--name", dest="name", default=DEFAULT_CONTAINER_NAME,
                        help="Name of the container, when the state is created.")
    parser.add_argument("-root", "--root", dest="root", default=None,
                        help="Confine the files read and written to this directory. Defaults to "
                             "FMUCONTAINER_MCP_ROOT, or no restriction.")
    parser.add_argument("-debug", "--debug", action="store_true", dest="debug",
                        help="Log the details of the operations on stderr.")
    return parser.parse_args(argv)


def _setup_logger(debug: bool) -> tuple[logging.Handler, int]:
    """Logs on stderr: stdout holds the JSON result only. Returns the handler and the previous level."""
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))
    handler.setLevel(logging.DEBUG if debug else logging.WARNING)
    logger.addHandler(handler)
    previous = logger.level
    if debug:
        logger.setLevel(logging.DEBUG)
    return handler, previous


def _print(value: Any) -> None:
    print(json.dumps(value if isinstance(value, dict) else {"result": value}, indent=2))


def run(argv=None) -> int:
    """Entry point of ``fmutool-agent``; returns the exit code."""
    options = _parse_args(argv)
    handler, previous_level = _setup_logger(options.debug)
    logger.debug(f"FMU Manipulation Toolbox agent command line version {version}")
    try:
        if options.tool == "list-tools":
            _print(describe_tools())
            return 0
        if options.tool not in TOOLS:
            raise UsageError(f"Unknown tool '{options.tool}'. Available: {', '.join(TOOLS)}.")

        raw = sys.stdin.read() if options.arguments == "-" else options.arguments
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UsageError(f"`--args` is not valid JSON: {exc}.") from None
        arguments = check_arguments(options.tool, arguments)

        state = Path(options.state) if options.state else None
        if options.tool in ASSEMBLY_TOOLS and state is None:
            raise UsageError(f"'{options.tool}' works on the assembly: give its state file with "
                             f"`--state FILE` (created by the first call).")

        policy = PathPolicy(Path(options.root)) if options.root else PathPolicy.from_environment()
        bridge = load_state(state, options.name)
        result = getattr(Toolbox(bridge, policy), options.tool)(**arguments)
        if options.tool in CHANGING_TOOLS:
            save_state(state, bridge)
        _print(result)
        return 0
    except UsageError as exc:
        _print({"error": str(exc)})
        return EXIT_USAGE_ERROR
    except PathValidationError as exc:
        _print({"error": str(exc)})
        return EXIT_TOOL_ERROR
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        if is_actionable(exc):
            _print({"error": str(exc)})
        else:
            logger.exception(f"Unexpected error in '{options.tool}'")
            _print({"error": f"'{options.tool}' failed unexpectedly ({type(exc).__name__}). This is a bug in the "
                             f"FMU Manipulation Toolbox; run again with --debug for the details."})
        return EXIT_TOOL_ERROR
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)


def main():  # pragma: no cover - console script shim
    sys.exit(run())


if __name__ == "__main__":  # pragma: no cover
    main()
