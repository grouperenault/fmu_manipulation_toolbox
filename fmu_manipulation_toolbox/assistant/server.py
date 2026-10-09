"""MCP (Model Context Protocol) server exposing FMU assembly capabilities.

The server is built on top of an :class:`~fmu_manipulation_toolbox.assistant.bridge.AssemblyBridge`
implementation, so the very same tools can drive either the live Container
Builder GUI or a headless assembly.

The FastMCP SDK requires Python >= 3.10; it is therefore imported lazily by
:func:`build_server` so that importing this package keeps working on Python 3.9
(and without the optional ``mcp`` extra installed).
"""

import functools
import inspect
import json
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional

from .bridge import AssemblyBridge
from .knowledge import (
    FMI_CONVENTIONS, USAGE_GUIDE, build_container_prompt,
    container_options_reference, diagnose_assembly_prompt, inspect_fmu_prompt,
)
from .paths import PathPolicy

logger = logging.getLogger("fmu_manipulation_toolbox")

#: Default interface the HTTP transport binds to. Loopback only.
DEFAULT_HOST = "127.0.0.1"
#: Default TCP port for the HTTP transport.
DEFAULT_PORT = 8765
#: Environment variable overriding :data:`DEFAULT_PORT`.
PORT_ENV_VAR = "FMUCONTAINER_MCP_PORT"

#: How long a tool waits for the backend to apply one operation, in seconds.
#: Generous on purpose: the backend may be a GUI busy with a modal dialog.
DEFAULT_TIMEOUT = 60.0
#: Environment variable overriding :data:`DEFAULT_TIMEOUT`.
TIMEOUT_ENV_VAR = "FMUCONTAINER_MCP_TIMEOUT"
#: Building a container is orders of magnitude slower than editing it (it
#: unzips, rewrites and re-zips every embedded FMU), so build operations get a
#: proportionally longer budget rather than a second knob to tune.
BUILD_TIMEOUT_FACTOR = 10


class McpUnavailableError(RuntimeError):
    """Raised when the optional ``fastmcp`` dependency cannot be imported."""


def resolve_port() -> int:
    """Return the TCP port to listen on, honouring :data:`PORT_ENV_VAR`.

    Called when the server starts rather than when the module is imported, so
    a malformed value cannot break an unrelated ``import`` of the package.

    Raises:
        ValueError: If the environment variable is set to something that is
            not a valid TCP port.
    """
    raw = os.environ.get(PORT_ENV_VAR)
    if raw is None:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(
            f"{PORT_ENV_VAR} must be a TCP port number, got '{raw}'."
        ) from None
    if not 1 <= port <= 65535:
        raise ValueError(f"{PORT_ENV_VAR} must be between 1 and 65535, got {port}.")
    return port


def resolve_timeout() -> float:
    """Return the per-operation timeout, honouring :data:`TIMEOUT_ENV_VAR`.

    A fixed 60 s budget is wrong in both directions: too short for a large
    assembly on a slow machine, too long for an interactive session where the
    user would rather be told quickly that the GUI is not answering. Hence the
    knob — resolved at startup, like the port, so a malformed value surfaces
    where it can be reported.

    Raises:
        ValueError: If the environment variable is not a positive number.
    """
    raw = os.environ.get(TIMEOUT_ENV_VAR)
    if raw is None:
        return DEFAULT_TIMEOUT
    try:
        timeout = float(raw)
    except ValueError:
        raise ValueError(
            f"{TIMEOUT_ENV_VAR} must be a number of seconds, got '{raw}'."
        ) from None
    if timeout <= 0:
        raise ValueError(f"{TIMEOUT_ENV_VAR} must be positive, got {timeout}.")
    return timeout



# ---------------------------------------------------------------------------
# Error reporting
# ---------------------------------------------------------------------------

#: Exceptions carrying a message the client (and the model) can act upon.
#: Anything raised by the toolbox itself is considered actionable too, which
#: avoids importing (and therefore loading) the heavy core modules here.
_ACTIONABLE_ERRORS = (ValueError, FileNotFoundError, OSError, LookupError)
_TOOLBOX_PACKAGE = "fmu_manipulation_toolbox"


def _is_actionable(exc: BaseException) -> bool:
    return (isinstance(exc, _ACTIONABLE_ERRORS)
            or type(exc).__module__.startswith(_TOOLBOX_PACKAGE))


def _schema_node(schema: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
    """Follow `$ref` and pick the object branch of `anyOf` (optional fields) in a JSON schema."""
    while True:
        if "$ref" in node:
            node = schema.get("$defs", {}).get(node["$ref"].rsplit("/", 1)[-1], {})
        elif "anyOf" in node:
            node = next((branch for branch in node["anyOf"]
                         if "properties" in branch or "$ref" in branch), {})
        else:
            return node


def _allowed_keys(schema: Dict[str, Any], path: List[str]) -> List[str]:
    """Keys accepted at `path` (e.g. `["options"]`) of a tool input schema."""
    node = _schema_node(schema, schema)
    for key in path:
        node = _schema_node(schema, node.get("properties", {}).get(key, {}))
    return sorted(node.get("properties", {}))


def describe_argument_errors(tool: str, errors: List[Dict[str, Any]], schema: Dict[str, Any]) -> str:
    """Turn Pydantic argument errors into one short, actionable message.

    FastMCP validates the arguments before the tool runs and reports the raw
    Pydantic text ("1 validation error for call[...]", error codes, a link to
    the Pydantic documentation). A model can act on what is wrong and what is
    accepted instead: the allowed keys come from the tool's own input schema,
    so they cannot drift from what the tool accepts.

    Args:
        tool: Name of the tool.
        errors: `pydantic.ValidationError.errors()`.
        schema: Input JSON schema of the tool.
    """
    problems = []
    for error in errors:
        location = [str(part) for part in error.get("loc", ())]
        kind = error.get("type", "")
        if kind in ("extra_forbidden", "unexpected_keyword_argument"):
            allowed = _allowed_keys(schema, location[:-1])
            what = "option" if location[:-1] else "argument"
            problem = f"unknown {what} '{location[-1]}'"
            if allowed:
                problem += f" (allowed: {', '.join(allowed)})"
        elif kind in ("missing", "missing_argument"):
            problem = f"missing required argument '{'.'.join(location)}'"
        else:
            given = repr(error.get("input"))
            given = given if len(given) <= 60 else given[:57] + "..."
            problem = f"'{'.'.join(location)}': {error.get('msg', 'invalid value')} (got {given})"
        problems.append(problem)
    return (f"Invalid arguments for '{tool}': {'; '.join(problems)}. "
            f"Fix the arguments and call the tool again.")


def _guard(fn):
    """Turn backend exceptions into actionable MCP errors.

    Without this, a plain ``AttributeError`` from an internal bug reaches the
    client verbatim ("'NoneType' object has no attribute ..."), which tells the
    model nothing it can act upon, and the full traceback is dumped by FastMCP.
    Expected failures keep their message; unexpected ones are logged with their
    traceback on the server and reported as a short, honest summary.

    Works on both plain and ``async`` tools: the progress-reporting ones are
    coroutines, and they need the same protection.
    """
    from fastmcp.exceptions import ToolError

    def translate(exc: BaseException) -> ToolError:
        if _is_actionable(exc):
            return ToolError(str(exc))
        logger.exception(f"Unexpected error in MCP tool '{fn.__name__}'")
        return ToolError(
            f"'{fn.__name__}' failed unexpectedly ({type(exc).__name__}). "
            f"This is a bug in the FMU Manipulation Toolbox, not something "
            f"you can fix by retrying; the server log has the details."
        )

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except ToolError:
                raise
            except Exception as exc:  # noqa: BLE001 - converted for the client
                raise translate(exc) from None

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - converted for the client
            raise translate(exc) from None

    return wrapper


#: Tool behaviour advertised to clients, so they can decide what needs
#: confirmation and what can be retried safely.
READ_ONLY = {"readOnlyHint": True, "idempotentHint": True}
IDEMPOTENT_WRITE = {"readOnlyHint": False, "idempotentHint": True}
DESTRUCTIVE_WRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False}


async def _offload(fn, *args):
    """Run a blocking backend call without freezing the event loop.

    FastMCP runs *synchronous* tools in a worker thread already, but an
    ``async`` tool runs on the event loop itself: calling the bridge directly
    from one would block every other client exchange — including the progress
    notifications the tool is trying to send.
    """
    import anyio

    return await anyio.to_thread.run_sync(functools.partial(fn, *args))


def build_server(bridge: AssemblyBridge, name: str = "fmutool",
                 policy: Optional[PathPolicy] = None):
    """Create the FastMCP server exposing ``bridge`` to an MCP client.

    Args:
        bridge: Backend applying the requested assembly operations.
        name: Server name advertised to MCP clients.
        policy: Filesystem guard-rails applied to every path the client
            provides. Defaults to :meth:`PathPolicy.from_environment`.

    Returns:
        fastmcp.FastMCP: The configured server.

    Raises:
        McpUnavailableError: If the optional ``fastmcp`` package is missing.
    """
    try:
        from fastmcp import Context, FastMCP
        from fastmcp.exceptions import ToolError, ValidationError as FastMcpValidationError
        from fastmcp.server.middleware import Middleware
        from pydantic import Field, ValidationError as PydanticValidationError
        from typing_extensions import Annotated
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise McpUnavailableError(
            "The 'fastmcp' package is required for the AI assistant "
            "(pip install 'fmu_manipulation_toolbox[mcp]', Python >= 3.10)."
        ) from exc

    # Imported here (rather than at module level) because it needs Pydantic,
    # which ships with fastmcp: importing this package must stay possible
    # without the optional `mcp` extra.
    from .models import (
        DEFAULT_PORT_LIMIT, ContainerOptions, FmuPorts, FmuSummary, Link, Port,
        RemovalReport, StartValue, format_start_value, option_reference,
    )
    # Same reasoning, different cost: `fmutools` pulls in the XSD validator and
    # the whole operations module, which importing this package must not do.
    from . import fmutools

    if policy is None:
        policy = PathPolicy.from_environment()

    mcp = FastMCP(name)

    class ArgumentErrors(Middleware):
        """Report invalid arguments with `describe_argument_errors` instead of the raw Pydantic text."""

        async def on_call_tool(self, context, call_next):
            try:
                return await call_next(context)
            except FastMcpValidationError as error:
                cause = error.__cause__
                if not isinstance(cause, PydanticValidationError):
                    raise
                tool_name = context.message.name
                tool = await mcp.get_tool(tool_name)
                schema = tool.parameters if tool is not None else {}
                raise ToolError(describe_argument_errors(tool_name, cause.errors(), schema)) from None

    mcp.add_middleware(ArgumentErrors())

    FmuName = Annotated[str, Field(
        description="File name of an FMU already in the assembly, e.g. "
                    "'controller.fmu'. Use `list_fmus` if unsure.")]
    PortName = Annotated[str, Field(
        description="Port name exactly as reported by `list_fmu_ports`.")]
    CausalityFilter = Annotated[Optional[List[str]], Field(
        description="Keep only these causalities, e.g. ['input', 'output']. "
                    "Omit to get them all.")]
    PatternFilter = Annotated[Optional[str], Field(
        description="Keep only the ports whose name matches this regular "
                    "expression, e.g. '^engine_'.")]
    Offset = Annotated[int, Field(
        ge=0, description="Index of the first port to return, for paging "
                          "through a large FMU.")]
    Limit = Annotated[int, Field(
        ge=1, le=1000, description="Maximum number of ports to return.")]

    def _as_ports_page(description: Dict[str, Any], causality, pattern,
                       offset: int, limit: int) -> FmuPorts:
        """Filter, count and paginate a raw bridge description."""
        ports = description.get("ports", [])
        counts: Dict[str, int] = {}
        for port in ports:
            key = port.get("causality") or "unknown"
            counts[key] = counts.get(key, 0) + 1

        selected = ports
        if causality:
            wanted = set(causality)
            selected = [port for port in selected if port.get("causality") in wanted]
        if pattern:
            try:
                matcher = re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid regular expression '{pattern}': {exc}") from None
            selected = [port for port in selected if matcher.search(port["name"])]

        page = selected[offset:offset + limit]
        return FmuPorts(
            fmu=description["fmu"],
            fmi_version=description.get("fmi_version"),
            generator=description.get("generator", ""),
            kinds=description.get("kinds", []),
            terminals=description.get("terminals", []),
            counts=counts,
            total=len(selected),
            returned=len(page),
            offset=offset,
            truncated=offset + len(page) < len(selected),
            ports=[Port(**port) for port in page],
        )

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def list_fmus() -> List[str]:
        """List the FMUs currently in the assembly, by file name.

        Call this first: the canvas may already contain FMUs the user added
        through the GUI. The returned names are what every other tool expects.
        """
        return bridge.list_fmus()

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def list_fmu_ports(
        fmu: FmuName,
        causality: CausalityFilter = None,
        name_pattern: PatternFilter = None,
        offset: Offset = 0,
        limit: Limit = DEFAULT_PORT_LIMIT,
    ) -> FmuPorts:
        """List the ports of an FMU **already in the assembly**.

        Always call this before `add_link`, `expose_input`, `expose_output` or
        `set_start_value`: never guess a port name.

        Large FMUs are paginated. Narrow the result with `causality` (for
        instance `['output']` before wiring) or `name_pattern` rather than
        paging blindly; check `truncated` to know whether ports are missing.

        To look at a file that has not been added yet, use `inspect_fmu_file`.
        """
        return _as_ports_page(bridge.list_fmu_ports(fmu), causality, name_pattern,
                              offset, limit)

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def inspect_fmu_file(
        path: Annotated[str, Field(
            description="Path to an existing .fmu file, e.g. "
                        "'/home/me/models/controller.fmu'.")],
        causality: CausalityFilter = None,
        name_pattern: PatternFilter = None,
        offset: Offset = 0,
        limit: Limit = DEFAULT_PORT_LIMIT,
    ) -> FmuPorts:
        """Inspect an `.fmu` file **without** adding it to the assembly.

        Use it to check what an FMU offers before committing to it, or to
        compare a candidate with what is already on the canvas.
        """
        description = bridge.inspect_fmu_file(str(policy.resolve_input(path)))
        return _as_ports_page(description, causality, name_pattern, offset, limit)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def add_fmu(
        path: Annotated[str, Field(
            description="Path to an existing .fmu file, e.g. "
                        "'/home/me/models/controller.fmu'.")],
    ) -> FmuSummary:
        """Add an FMU to the assembly and summarise what it brings.

        The returned `fmu` name is what every other tool expects afterwards,
        and `counts` tells you how many inputs/outputs/parameters it has, so
        you often do not need a separate `list_fmu_ports` call to decide what
        to do next.

        Adding two files with the same base name is ambiguous: ask the user to
        rename one.
        """
        return FmuSummary(**bridge.add_fmu(str(policy.resolve_input(path))))

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def remove_fmu(name: FmuName) -> RemovalReport:
        """Remove an FMU from the assembly, along with its links.

        Reports how many links were discarded, so you can tell the user what
        was lost. This cannot be undone from here: confirm before calling it.
        """
        return RemovalReport(**bridge.remove_fmu(name))

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def add_link(
        from_fmu: FmuName,
        from_port: Annotated[str, Field(
            description="OUTPUT port of the source FMU, e.g. 'velocity'.")],
        to_fmu: FmuName,
        to_port: Annotated[str, Field(
            description="INPUT port of the destination FMU, e.g. 'velocity'.")],
    ) -> str:
        """Connect an OUTPUT port of one FMU to an INPUT port of another.

        Direction matters: `from_port` must be an output and `to_port` an
        input. Types should be compatible; numeric conversions are applied but
        may lose precision, and a real-to-boolean link is worth confirming with
        the user.

        `auto_link` is enabled by default and already connects ports sharing
        the same name and type, so you usually only need this for ports whose
        names differ.
        """
        return bridge.add_link(from_fmu, from_port, to_fmu, to_port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def add_links(
        links: Annotated[List[Link], Field(
            description="Links to create, applied in order.", min_length=1)],
    ) -> Dict[str, Any]:
        """Create several links in one call.

        Wiring two FMUs port by port costs one round-trip per link; this takes
        them all at once. Links are applied **in order and independently**: a
        rejected link does not undo the previous ones, so read `failed` before
        telling the user the wiring is done.
        """
        created, failed = [], []
        for link in links:
            try:
                created.append(bridge.add_link(link.from_fmu, link.from_port,
                                               link.to_fmu, link.to_port))
            except Exception as exc:  # noqa: BLE001 - reported per link
                if not _is_actionable(exc):
                    raise
                failed.append({"link": str(link), "reason": str(exc)})
        return {"created": created, "failed": failed}

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def remove_link(
        from_fmu: FmuName,
        from_port: Annotated[str, Field(
            description="OUTPUT port of the source FMU.")],
        to_fmu: FmuName,
        to_port: Annotated[str, Field(
            description="INPUT port of the destination FMU.")],
    ) -> str:
        """Disconnect a link created by `add_link`.

        Only explicit links can be removed: those created by `auto_link` are
        derived at build time, so disable the option instead of trying to undo
        them one by one.
        """
        return bridge.remove_link(from_fmu, from_port, to_fmu, to_port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def expose_input(fmu: FmuName, port: PortName) -> str:
        """Surface an input port of an embedded FMU on the container boundary.

        Only needed when `auto_input` is disabled, or when the user asks for a
        specific container interface: unconnected inputs are exposed
        automatically otherwise.
        """
        return bridge.expose_input(fmu, port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def expose_output(fmu: FmuName, port: PortName) -> str:
        """Surface an output port of an embedded FMU on the container boundary.

        Only needed when `auto_output` is disabled, or when the user asks for a
        specific container interface.
        """
        return bridge.expose_output(fmu, port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def set_start_value(
        fmu: FmuName,
        port: PortName,
        value: Annotated[StartValue, Field(
            description="Initial value, typed: 0.01, 3, true or 'text'. "
                        "Booleans are converted to the FMI spelling "
                        "('true'/'false').")],
    ) -> str:
        """Set the initial value of a port, or the value of a parameter.

        Use the natural type of the port as reported by `list_fmu_ports`.
        """
        return bridge.set_start_value(fmu, port, format_start_value(value))

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def unset_start_value(fmu: FmuName, port: PortName) -> str:
        """Drop a start value previously set with `set_start_value`.

        The port falls back to the value declared by the FMU itself — which
        may be none at all, in which case the solver uses the FMI default for
        the type. Only values *you* set can be dropped: this cannot override
        what the FMU declares.
        """
        return bridge.unset_start_value(fmu, port)

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @_guard
    def set_container_options(options: ContainerOptions) -> Dict[str, Any]:
        """Update the runtime options of the root container.

        Only the options you provide are changed. Prefer leaving `step_size`
        unset so the toolbox derives it from the embedded FMUs, rather than
        inventing a value. Returns every option after the update.
        """
        return bridge.set_container_options(options.changes())

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def get_assembly_json() -> Dict[str, Any]:
        """Return the whole assembly: FMUs, links, exposed ports and options.

        Use it to review the result with the user before building anything.
        Note that FMUs are referenced here by *path*, whereas the other tools
        designate them by name.
        """
        return bridge.get_assembly_json()

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def save_as_json(
        path: Annotated[str, Field(
            description="Destination file, must end with '.json'.")],
        overwrite: Annotated[bool, Field(
            description="Replace the file if it already exists. Ask the user "
                        "first.")] = False,
    ) -> str:
        """Export the assembly description as a JSON file.

        This writes the *description*, not a usable FMU; use `save_as_fmu` to
        build the container itself.
        """
        return bridge.save_as_json(str(policy.resolve_output(path, (".json",), overwrite)))

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    async def save_as_fmu(
        ctx: Context,
        path: Annotated[str, Field(
            description="Destination file, must end with '.fmu'.")],
        fmi_version: Annotated[Literal[2, 3], Field(
            description="FMI version of the *container* interface: 2 for "
                        "FMI 2.0, 3 for FMI 3.0.")] = 2,
        datalog: Annotated[bool, Field(
            description="Record the inputs/outputs of every embedded FMU to a "
                        "CSV log at each step.")] = False,
        overwrite: Annotated[bool, Field(
            description="Replace the file if it already exists. Ask the user "
                        "first.")] = False,
    ) -> str:
        """Build the container and write it as an .fmu archive.

        Review the assembly with `get_assembly_json` and confirm the output
        path with the user before calling this: it is the final step and it
        writes to disk.

        This is by far the slowest tool — every embedded FMU is unzipped,
        rewritten and re-zipped — so it reports progress as it goes. Do not
        start a second build while one is running.
        """
        destination = policy.resolve_output(path, (".fmu",), overwrite)
        # Progress notifications carry the status message rather than
        # `ctx.info()`: the MCP logging capability is deprecated since
        # SEP-2577, while progress is the mechanism meant for exactly this.
        await ctx.report_progress(
            0, 2, f"Building the FMI-{fmi_version} container into '{destination.name}'...")
        # The backend call is blocking (it may even wait on a GUI main thread):
        # running it in a worker thread keeps the event loop free, so progress
        # notifications and client pings are still served meanwhile.
        result = await _offload(bridge.save_as_fmu, str(destination), fmi_version, datalog)
        await ctx.report_progress(2, 2, f"Container written to '{destination}'.")
        return result

    # -- single-FMU tools (fmutool / checker) ------------------------------
    # These never touch the assembly: they read or rewrite one `.fmu` file.

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def summarize_fmu(
        path: Annotated[str, Field(description="Path to an existing .fmu file.")],
    ) -> Dict[str, Any]:
        """Summarise an FMU: identity, capabilities, platforms, port counts.

        Use it to answer "what is this FMU?" without adding it anywhere. For
        the port list itself, prefer `inspect_fmu_file`, which is filterable
        and paginated.
        """
        return fmutools.summarize_fmu(policy.resolve_input(path))

    @mcp.tool(annotations=READ_ONLY)
    @_guard
    def check_fmu(
        path: Annotated[str, Field(description="Path to an existing .fmu file.")],
    ) -> Dict[str, Any]:
        """Validate an FMU against the FMI schema and the registered checkers.

        `compliant` reports the schema verdict only: always read `errors` as
        well, and quote them to the user rather than summarising them away.
        A non-compliant FMU may still load in some tools, so do not promise
        that fixing it is required — report what was found.
        """
        return fmutools.check_fmu(policy.resolve_input(path))

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def dump_ports_csv(
        fmu: Annotated[str, Field(description="Path to an existing .fmu file.")],
        path: Annotated[str, Field(
            description="Destination file, must end with '.csv'.")],
        overwrite: Annotated[bool, Field(
            description="Replace the file if it already exists.")] = False,
    ) -> Dict[str, Any]:
        """Export every port of an FMU to a CSV file, for bulk renaming.

        The `newName` column is the one to edit before feeding the file back
        to `rename_ports_from_csv`.
        """
        return fmutools.dump_ports_csv(policy.resolve_input(fmu),
                                       policy.resolve_output(path, (".csv",), overwrite))

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def rename_ports_from_csv(
        fmu: Annotated[str, Field(description="Path to the .fmu file to read.")],
        csv: Annotated[str, Field(
            description="CSV mapping, as produced by `dump_ports_csv`.")],
        output: Annotated[str, Field(
            description="Destination .fmu file. The source is left untouched.")],
        overwrite: Annotated[bool, Field(
            description="Replace the output if it already exists.")] = False,
    ) -> Dict[str, Any]:
        """Rename — or drop — the ports of an FMU from a CSV mapping.

        An **empty** `newName` **removes** the port: say so explicitly when
        reporting the result, since `removed` is rarely what the user meant
        when they only asked for renaming.

        Renaming ports changes the FMU interface: anything already connected
        to the old names will break.
        """
        return fmutools.rename_ports_from_csv(
            policy.resolve_input(fmu),
            policy.resolve_input(csv, (".csv",)),
            policy.resolve_output(output, (".fmu",), overwrite))

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @_guard
    def apply_operation(
        fmu: Annotated[str, Field(description="Path to the .fmu file to read.")],
        output: Annotated[str, Field(
            description="Destination .fmu file. The source is left untouched.")],
        operation: Annotated[Literal["strip_toplevel", "merge_toplevel", "trim_until",
                                     "remove_regexp", "keep_only_regexp",
                                     "remove_sources"], Field(
            description="strip_toplevel: drop the 'Bus.' prefix; merge_toplevel: "
                        "turn 'Bus.sig' into 'Bus_sig'; trim_until: cut up to a "
                        "separator; remove_regexp/keep_only_regexp: filter ports "
                        "by name; remove_sources: drop the embedded sources.")],
        argument: Annotated[Optional[str], Field(
            description="The separator or regular expression, for the "
                        "operations that need one.")] = None,
        causality: Annotated[Optional[List[str]], Field(
            description="Restrict the operation to these causalities, e.g. "
                        "['input', 'output'].")] = None,
        overwrite: Annotated[bool, Field(
            description="Replace the output if it already exists.")] = False,
    ) -> Dict[str, Any]:
        """Rewrite the port names of an FMU with one descriptor operation.

        These operations change the FMU **interface**: every consumer bound to
        the old names breaks. Confirm with the user, and never write over the
        source file — the output is a separate FMU on purpose.
        """
        return fmutools.apply_operation(
            policy.resolve_input(fmu),
            policy.resolve_output(output, (".fmu",), overwrite),
            operation, argument, causality)

    @mcp.resource("guide://usage")
    def usage_guide() -> str:
        """How to drive the Container Builder to assemble FMUs."""
        return USAGE_GUIDE

    @mcp.resource("fmi://conventions")
    def fmi_conventions() -> str:
        """What causality, variability, types and units imply when wiring FMUs."""
        return FMI_CONVENTIONS

    @mcp.resource("container://options")
    def container_options() -> str:
        """Every container option, its type, its meaning and its default."""
        return container_options_reference(option_reference())

    @mcp.resource("assembly://current")
    @_guard
    def current_assembly() -> str:
        """The current assembly description (JSON)."""
        return json.dumps(bridge.get_assembly_json(), indent=2)

    @mcp.resource("fmu://{name}/ports")
    @_guard
    def fmu_ports_resource(name: str) -> str:
        """The ports of one FMU of the assembly, as JSON."""
        page = _as_ports_page(bridge.list_fmu_ports(name), None, None,
                              0, DEFAULT_PORT_LIMIT)
        return page.model_dump_json(indent=2)

    # -- prompts -----------------------------------------------------------
    # The procedures live here rather than in a repository file: they must
    # reach whichever client connects, not only the ones reading this repo.

    @mcp.prompt
    def build_container(
        fmus: Annotated[str, Field(
            description="Optional list of the FMU files to combine.")] = "",
        output: Annotated[str, Field(
            description="Optional path of the container to produce.")] = "",
    ) -> str:
        """Assemble several FMUs into a valid FMU Container, step by step."""
        return build_container_prompt(fmus or None, output or None)

    @mcp.prompt
    def diagnose_assembly(
        symptom: Annotated[str, Field(
            description="Optional description of what goes wrong.")] = "",
    ) -> str:
        """Investigate a container that fails to build or misbehaves."""
        return diagnose_assembly_prompt(symptom or None)

    @mcp.prompt
    def inspect_fmu(
        fmu: Annotated[str, Field(
            description="Optional FMU name on the canvas, or path to a file.")] = "",
    ) -> str:
        """Produce a readable identity card for an FMU."""
        return inspect_fmu_prompt(fmu or None)

    return mcp

