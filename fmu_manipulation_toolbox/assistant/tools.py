"""What each tool of the assistant does, in plain Python.

The MCP server (`server.py`) and the JSON command line (`fmutool-agent`) offer
the same tools. The work of each tool — resolving the paths, filtering and
paging the ports, applying links one by one, formatting the values — is done
here, once, on top of an
:class:`~fmu_manipulation_toolbox.assistant.bridge.AssemblyBridge`. The server
adds the typed signatures, the descriptions and the schemas that MCP clients
need; the command line adds its own argument checks. Neither re-implements a
tool.

This module imports neither ``fastmcp`` nor Pydantic: the command line must
work with the base installation of the package.
"""

import logging
import re
from pathlib import Path
from typing import Any, Literal

from . import analysis
from .bridge import AssemblyBridge
from .paths import PathPolicy

logger = logging.getLogger("fmu_manipulation_toolbox")

#: Maximum number of ports returned by a single call, to keep the answer
#: readable and the context small on industrial FMUs.
DEFAULT_PORT_LIMIT = 50

#: Largest page of ports a client may ask for: about 31k characters (~9k tokens) of compact ports.
MAX_PORT_LIMIT = 200

#: Descriptions of the ports longer than this are cut (with `…`): they help to match ports by meaning, but some
#: generators write whole paragraphs, which would fill the context window of the model.
MAX_DESCRIPTION_LENGTH = 80

#: Container options and the type of their value (`None` leaves `step_size` to the toolbox).
CONTAINER_OPTION_TYPES: dict[str, tuple[type, ...]] = {
    "step_size": (float, int, type(None)),
    "mt": (bool,), "profiling": (bool,), "sequential": (bool,),
    "auto_link": (bool,), "auto_input": (bool,), "auto_output": (bool,),
    "auto_parameter": (bool,), "auto_local": (bool,),
    "ts_multiplier": (bool,), "reset_ports": (bool,),
}

#: Sections of a container that `get_assembly_json` can page through.
AssemblySection = Literal["input", "output", "link", "start", "drop"]

#: Exceptions carrying a message the client (and the model) can act upon.
#: Anything raised by the toolbox itself is considered actionable too, which
#: avoids importing (and therefore loading) the heavy core modules here.
_ACTIONABLE_ERRORS = (ValueError, FileNotFoundError, OSError, LookupError)
_TOOLBOX_PACKAGE = "fmu_manipulation_toolbox"


def is_actionable(exc: BaseException) -> bool:
    """Whether the message of `exc` tells the caller what to fix (rather than revealing a bug)."""
    return (isinstance(exc, _ACTIONABLE_ERRORS)
            or type(exc).__module__.startswith(_TOOLBOX_PACKAGE))


def format_start_value(value: bool | int | float | str) -> str:
    """Render ``value`` the way ``modelDescription.xml`` expects it.

    Booleans are the trap here: ``str(True)`` yields ``"True"``, which FMI
    does not accept.

    Examples:
        >>> format_start_value(True)
        'true'
        >>> format_start_value(0.01)
        '0.01'
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def compact_port(port: dict[str, Any]) -> dict[str, Any]:
    """A port of a bridge description as the tools return it.

    The attributes the FMU does not declare are left out (a `null` costs tokens
    and says nothing), and the description is cut to `MAX_DESCRIPTION_LENGTH`
    characters.
    """
    compact = {key: port.get(key) for key in ("name", "type", "causality", "variability", "unit", "start",
                                              "description")}
    description = compact["description"]
    if description and len(description) > MAX_DESCRIPTION_LENGTH:
        compact["description"] = description[:MAX_DESCRIPTION_LENGTH - 1].rstrip() + "…"
    return {key: value for key, value in compact.items() if value is not None}


def ports_page(description: dict[str, Any], causality=None, name_pattern=None, offset: int = 0,
               limit: int = DEFAULT_PORT_LIMIT, types=None, variabilities=None) -> dict[str, Any]:
    """Filter, count and paginate the ports of a bridge description.

    ``counts`` describes the whole FMU; ``total`` counts the ports matching the
    filters, ``returned`` those of the page.
    """
    from . import fmutools  # the operations module, loaded on first use

    if offset < 0:
        raise ValueError(f"`offset` must be 0 or more, got {offset}.")
    if not 1 <= limit <= MAX_PORT_LIMIT:
        raise ValueError(f"`limit` must be between 1 and {MAX_PORT_LIMIT}, got {limit}.")

    ports = description.get("ports", [])
    counts: dict[str, int] = {}
    for port in ports:
        key = port.get("causality") or "unknown"
        counts[key] = counts.get(key, 0) + 1

    selected = fmutools.select_ports(ports, description.get("fmi_version"), causality, types, variabilities)
    if name_pattern:
        try:
            matcher = re.compile(name_pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression '{name_pattern}': {exc}") from None
        selected = [port for port in selected if matcher.search(port["name"])]

    page = selected[offset:offset + limit]
    return {
        "fmu": description["fmu"],
        "fmi_version": description.get("fmi_version"),
        "generator": description.get("generator", ""),
        "kinds": description.get("kinds", []),
        "terminals": description.get("terminals", []),
        "counts": counts,
        "total": len(selected),
        "returned": len(page),
        "offset": offset,
        "truncated": offset + len(page) < len(selected),
        "ports": [compact_port(port) for port in page],
    }


class Toolbox:
    """The tools, on one bridge, within one path policy.

    Each public method is a tool: same name, same parameters (in the same
    order) and same result as the MCP tool. Results are plain JSON values.
    """

    def __init__(self, bridge: AssemblyBridge, policy: PathPolicy | None = None):
        self.bridge = bridge
        self.policy = policy if policy is not None else PathPolicy.from_environment()

    # -- introspection -----------------------------------------------------

    def list_fmus(self) -> list[str]:
        """List the FMUs of the assembly, by name."""
        return self.bridge.list_fmus()

    def list_fmu_ports(self, fmu: str, causality: list[str] | None = None, type: list[str] | None = None,
                       variability: list[str] | None = None, name_pattern: str | None = None,
                       offset: int = 0, limit: int = DEFAULT_PORT_LIMIT) -> dict[str, Any]:
        """List the ports of an FMU of the assembly, filtered and paginated."""
        return ports_page(self.bridge.list_fmu_ports(fmu), causality, name_pattern, offset, limit,
                          type, variability)

    def inspect_fmu_file(self, path: str, causality: list[str] | None = None, type: list[str] | None = None,
                         variability: list[str] | None = None, name_pattern: str | None = None,
                         offset: int = 0, limit: int = DEFAULT_PORT_LIMIT) -> dict[str, Any]:
        """List the ports of an .fmu file without adding it to the assembly."""
        description = self.bridge.inspect_fmu_file(str(self.policy.resolve_input(path)))
        return ports_page(description, causality, name_pattern, offset, limit, type, variability)

    # -- assembly ----------------------------------------------------------

    def add_fmu(self, path: str) -> dict[str, Any]:
        """Add an FMU to the assembly and summarise it."""
        added = self.bridge.add_fmu(str(self.policy.resolve_input(path)))
        return {"fmu": added["fmu"], "path": added["path"], "fmi_version": added.get("fmi_version"),
                "generator": added.get("generator", ""), "kinds": added.get("kinds", []),
                "counts": added.get("counts", {}), "terminals": added.get("terminals", [])}

    def remove_fmu(self, name: str) -> dict[str, Any]:
        """Remove an FMU from the assembly, along with its links."""
        removed = self.bridge.remove_fmu(name)
        return {"fmu": removed["fmu"], "removed_links": removed["removed_links"]}

    def import_assembly(self, path: str, replace: bool = False) -> dict[str, Any]:
        """Replace the assembly by the one of a JSON, CSV or SSP file, and summarise it."""
        from ..assembly import Assembly, AssemblyError
        from . import fmutools

        source = self.policy.resolve_input(path, (".json", ".csv", ".ssp"))
        current = self.bridge.list_fmus()
        if current and not replace:
            raise ValueError(f"The assembly already holds {len(current)} FMU(s). Confirm with the user, then call the "
                             f"tool again with replace=True to replace it.")
        result: dict[str, Any] = {"file": source.name}
        with fmutools.reader_warnings(result):
            assembly = Assembly(source.name, fmu_directory=source.parent)
        if assembly.root is None:
            raise AssemblyError(f"'{source.name}' describes no container.")
        self._check_embedded_fmus(assembly.root, source.parent)
        self.bridge.import_assembly(assembly, str(source.parent))
        result.update(analysis.summarize_assembly(self.bridge.get_assembly_json()))
        return result

    def _check_embedded_fmus(self, node, directory: Path) -> None:
        """A description cannot bring in FMUs that the path policy would not let a client add."""
        for fmu_name in node.fmu_names_list:
            self.policy.resolve_input(str(directory / node.fmu_path(fmu_name)))
        for child in node.children.values():
            self._check_embedded_fmus(child, directory)

    def inspect_ssp(self, path: str, node: str | None = None, section: AssemblySection | None = None,
                    offset: int = 0, limit: int = DEFAULT_PORT_LIMIT) -> dict[str, Any]:
        """Describe an SSP file without importing it: what it holds, or why it is refused."""
        from . import fmutools
        return fmutools.inspect_ssp(self.policy.resolve_input(path, (".ssp",)), node, section, offset, limit)

    def add_links(self, links: list[dict[str, str]]) -> dict[str, Any]:
        """Create several links, independently: read `failed`."""
        if not links:
            raise ValueError("`links` must hold at least one link.")
        created, failed = [], []
        for link in links:
            try:
                created.append(self.bridge.add_link(link["from_fmu"], link["from_port"],
                                                    link["to_fmu"], link["to_port"]))
            except Exception as exc:  # noqa: BLE001 - reported per link
                if not is_actionable(exc):
                    raise
                failed.append({"link": f"{link['from_fmu']}/{link['from_port']} -> "
                                       f"{link['to_fmu']}/{link['to_port']}",
                               "reason": str(exc)})
        return {"created": created, "failed": failed}

    def remove_link(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        """Disconnect a link created by `add_link`."""
        return self.bridge.remove_link(from_fmu, from_port, to_fmu, to_port)

    def expose_input(self, fmu: str, port: str) -> str:
        """Expose an input of an embedded FMU as an input of the container."""
        return self.bridge.expose_input(fmu, port)

    def expose_output(self, fmu: str, port: str) -> str:
        """Expose an output of an embedded FMU as an output of the container."""
        return self.bridge.expose_output(fmu, port)

    def set_start_value(self, fmu: str, port: str, value: bool | int | float | str) -> str:
        """Set the initial value of a port, or the value of a parameter."""
        return self.bridge.set_start_value(fmu, port, format_start_value(value))

    def unset_start_value(self, fmu: str, port: str) -> str:
        """Drop a start value set with `set_start_value`."""
        return self.bridge.unset_start_value(fmu, port)

    def set_container_options(self, options: dict[str, Any]) -> dict[str, Any]:
        """Change some options of the container; returns every option."""
        for name, value in options.items():
            if name not in CONTAINER_OPTION_TYPES:
                raise ValueError(f"Unknown container option '{name}'. Allowed: {sorted(CONTAINER_OPTION_TYPES)}.")
            accepted = CONTAINER_OPTION_TYPES[name]
            if not isinstance(value, accepted) or (bool not in accepted and isinstance(value, bool)):
                raise ValueError(f"Option '{name}' expects {' or '.join(t.__name__ for t in accepted)}, "
                                 f"got {value!r}.")
            if name == "step_size" and value is not None and value <= 0:
                raise ValueError(f"Option 'step_size' must be positive, got {value}.")
        return self.bridge.set_container_options(dict(options))

    def get_assembly_json(self, node: str | None = None, section: AssemblySection | None = None,
                          offset: int = 0, limit: int = DEFAULT_PORT_LIMIT) -> dict[str, Any]:
        """The assembly description, one container at a time, its sections paginated."""
        return analysis.assembly_page(self.bridge.get_assembly_json(), node, section, offset, limit)

    def analyze_assembly(self, mode: Literal["summary", "lint"] = "summary",
                         node: str | None = None) -> dict[str, Any]:
        """Describe (`summary`) or lint (`lint`) the assembly, without building it."""
        assembly = self.bridge.get_assembly_json()
        if mode == "summary":
            return analysis.summarize_assembly(
                assembly if node is None or not assembly else analysis.find_container(assembly, node))
        return analysis.lint_assembly(assembly, node, self.bridge.list_fmu_ports)

    def save_assembly(self, path: str, overwrite: bool = False, ssp_version: Literal["1.0", "2.0"] = "2.0") -> str:
        """Write the assembly description to a file: JSON or SSP, by its extension."""
        destination = self.policy.resolve_output(path, (".json", ".ssp"), overwrite)
        if destination.suffix.lower() == ".ssp":
            return self.bridge.save_as_ssp(str(destination), ssp_version)
        return self.bridge.save_as_json(str(destination))

    def save_as_fmu(self, path: str, fmi_version: Literal[2, 3] = 2, datalog: bool = False,
                    overwrite: bool = False) -> str:
        """Build the container into an .fmu file."""
        return self.bridge.save_as_fmu(str(self.fmu_destination(path, overwrite)), fmi_version, datalog)

    def fmu_destination(self, path: str, overwrite: bool) -> Path:
        """Where `save_as_fmu` writes, once checked against the policy."""
        return self.policy.resolve_output(path, (".fmu",), overwrite)

    # -- single FMU --------------------------------------------------------

    def summarize_fmu(self, path: str) -> dict[str, Any]:
        """Summarise an FMU: identity, capabilities, platforms, port counts."""
        from . import fmutools
        return fmutools.summarize_fmu(self.policy.resolve_input(path))

    def check_fmu(self, path: str) -> dict[str, Any]:
        """Check an FMU against the FMI schema and the registered checkers."""
        from . import fmutools
        return fmutools.check_fmu(self.policy.resolve_input(path))

    def describe_port(self, fmu: str, port: str) -> dict[str, Any]:
        """Everything an FMU of the assembly, or an .fmu file, declares about one port."""
        from . import fmutools
        if fmu in self.bridge.list_fmus():
            path = Path(self.bridge.list_fmu_ports(fmu)["path"])
        else:
            path = self.policy.resolve_input(fmu)
        return fmutools.describe_port(path, port)

    def dump_ports_csv(self, fmu: str, path: str, overwrite: bool = False) -> dict[str, Any]:
        """Export every port of an FMU to a CSV file, for bulk renaming."""
        from . import fmutools
        return fmutools.dump_ports_csv(self.policy.resolve_input(fmu),
                                       self.policy.resolve_output(path, (".csv",), overwrite))

    def rename_ports(self, fmu: str, output: str, mapping: dict[str, str] | None = None,
                     csv: str | None = None, overwrite: bool = False) -> dict[str, Any]:
        """Rename, or drop, ports of an FMU from a mapping or a CSV file."""
        from . import fmutools
        return fmutools.rename_ports(
            self.policy.resolve_input(fmu),
            self.policy.resolve_output(output, (".fmu",), overwrite),
            mapping, self.policy.resolve_input(csv, (".csv",)) if csv is not None else None)

    def apply_operation(self, fmu: str, output: str,
                        operation: Literal["strip_toplevel", "merge_toplevel", "trim_until", "remove_regexp",
                                           "keep_only_regexp", "remove_sources"],
                        argument: str | None = None, causality: list[str] | None = None,
                        type: list[str] | None = None, variability: list[str] | None = None,
                        overwrite: bool = False) -> dict[str, Any]:
        """Rewrite the port names of an FMU with one descriptor operation."""
        from . import fmutools
        return fmutools.apply_operation(
            self.policy.resolve_input(fmu),
            self.policy.resolve_output(output, (".fmu",), overwrite),
            operation, argument, causality, type, variability)


#: Tools of `Toolbox`, in the order the MCP server declares them.
TOOLS = ("list_fmus", "list_fmu_ports", "inspect_fmu_file", "import_assembly", "inspect_ssp", "add_fmu", "remove_fmu",
         "add_links", "remove_link", "expose_input", "expose_output", "set_start_value", "unset_start_value",
         "set_container_options", "get_assembly_json", "analyze_assembly", "save_assembly", "save_as_fmu",
         "summarize_fmu", "check_fmu", "describe_port", "dump_ports_csv", "rename_ports", "apply_operation")
