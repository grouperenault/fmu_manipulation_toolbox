"""Headless assembly bridge, built on the public ``Assembly`` API.

This is the backend used when the MCP server runs **without** the Container
Builder GUI (``fmutool-mcp``). It keeps the requested topology in plain
Python structures and materialises it as an
[Assembly][fmu_manipulation_toolbox.assembly.Assembly] whenever the client asks
to review, export or build it.

Why not reuse the GUI bridge? Because driving a Qt scene to describe an
assembly requires Qt, a display and a main-thread event loop — three things a
command-line MCP server has no business requiring. Both bridges implement the
same :class:`~fmu_manipulation_toolbox.assistant.bridge.AssemblyBridge`
protocol, so the MCP tools are strictly identical either way.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any

from ..assembly import Assembly, AssemblyError, AssemblyNode
from ..operations import FMU, ModelVariable, OperationAbstract
from ..terminals import Terminals
from .bridge import SUPPORTED_FMI_VERSIONS

logger = logging.getLogger("fmu_manipulation_toolbox")

#: Container options, with the defaults of :class:`AssemblyNode`. Keeping the
#: list here (rather than reading it off ``AssemblyNode.__init__``) makes the
#: accepted keys explicit and their defaults reviewable.
DEFAULT_OPTIONS: dict[str, Any] = {
    "step_size": None,
    "mt": False,
    "profiling": False,
    "sequential": False,
    "auto_link": True,
    "auto_input": True,
    "auto_output": True,
    "auto_parameter": False,
    "auto_local": False,
    "ts_multiplier": False,
}

#: Default name of the container being described.
DEFAULT_CONTAINER_NAME = "container.fmu"


class _FmuDescriptor(OperationAbstract):
    """Reads an FMU descriptor and collects what the assistant needs.

    The same visitor the GUI uses to populate a node, minus the drawing: one
    pass over ``modelDescription.xml`` yields every variable with its
    causality, variability, type, unit, start value and description.
    """

    read_only = True

    def __init__(self):
        self.fmi_version: int | None = None
        self.generator: str = ""
        self.is_cosimulation = False
        self.is_model_exchange = False
        self.terminals: list[str] = []
        self.ports: list[dict[str, Any]] = []

    def fmi_attrs(self, attrs):
        self.generator = attrs.get("generationTool", "")
        version = attrs.get("fmiVersion", "")
        if version == "2.0":
            self.fmi_version = 2
        elif version.startswith("3."):
            self.fmi_version = 3

    def cosimulation_attrs(self, attrs):
        self.is_cosimulation = True

    def modelexchange_attrs(self, attrs):
        self.is_model_exchange = True

    def port_attrs(self, fmu_port: ModelVariable) -> int:
        self.ports.append({
            "name": fmu_port.get("name", ""),
            "type": fmu_port.fmi_type or "",
            "causality": fmu_port.get("causality", "local"),
            "variability": fmu_port.get("variability", None),
            "unit": fmu_port.get("unit", None),
            "start": fmu_port.get("start", None),
            "description": fmu_port.get("description", None),
        })
        return 0

    def closure(self):
        self.terminals = [terminal.name for terminal in Terminals(self.fmu.tmp_directory)]

    @property
    def kinds(self) -> list[str]:
        kinds = []
        if self.is_cosimulation:
            kinds.append("CoSimulation")
        if self.is_model_exchange:
            kinds.append("ModelExchange")
        return kinds


def describe_fmu(path: Path) -> dict[str, Any]:
    """Describe an ``.fmu`` file, in the shape the MCP server expects.

    Args:
        path: Path to an existing ``.fmu`` archive.

    Returns:
        A mapping with ``fmu``, ``path``, ``fmi_version``, ``generator``,
        ``kinds``, ``terminals`` and the **complete** ``ports`` list.

    Raises:
        FileNotFoundError: If the file does not exist.
        FMUError: If the file is not a readable FMU.
    """
    if not path.is_file():
        raise FileNotFoundError(f"FMU file not found: '{path}'")

    descriptor = _FmuDescriptor()
    # `FMU` unzips into a temporary directory, removed at the end of the `with`
    # block; the original archive is never modified.
    with FMU(str(path)) as fmu:
        fmu.apply_operation(descriptor)

    return {
        "fmu": path.name,
        "path": str(path),
        "fmi_version": descriptor.fmi_version,
        "generator": descriptor.generator,
        "kinds": descriptor.kinds,
        "terminals": descriptor.terminals,
        "ports": descriptor.ports,
    }


def _count_by_causality(ports: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for port in ports:
        key = port.get("causality") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


class HeadlessAssemblyBridge:
    """:class:`AssemblyBridge` implementation without any GUI.

    FMUs are designated by their **file name**, as everywhere else in the MCP
    interface; the bridge keeps the full path internally so the FMUs do not
    have to live in the same directory. Two files sharing a base name are
    refused, since the name would no longer identify one of them.
    """

    def __init__(self, name: str = DEFAULT_CONTAINER_NAME):
        self._name = name
        self._paths: dict[str, Path] = {}
        self._descriptions: dict[str, dict[str, Any]] = {}
        self._links: list[tuple[str, str, str, str]] = []
        self._exposed_inputs: list[tuple[str, str]] = []
        self._exposed_outputs: list[tuple[str, str]] = []
        self._start_values: dict[tuple[str, str], str] = {}
        self._options: dict[str, Any] = dict(DEFAULT_OPTIONS)

    # -- helpers -----------------------------------------------------------

    def _description(self, fmu: str) -> dict[str, Any]:
        """Return the cached description of an FMU of the assembly."""
        if fmu not in self._descriptions:
            known = ", ".join(sorted(self._descriptions)) or "none"
            raise ValueError(
                f"FMU '{fmu}' is not in the assembly (currently: {known}). "
                f"Use `inspect_fmu_file` to look at a file that has not been added."
            )
        return self._descriptions[fmu]

    def _port(self, fmu: str, port: str) -> dict[str, Any]:
        for candidate in self._description(fmu)["ports"]:
            if candidate["name"] == port:
                return candidate
        raise ValueError(f"'{port}' is not a port of '{fmu}'.")

    def _check_causality(self, fmu: str, port: str, expected: tuple[str, ...]) -> None:
        causality = self._port(fmu, port)["causality"]
        if causality not in expected:
            wanted = " or ".join(expected)
            raise ValueError(
                f"'{port}' is a {causality} of '{fmu}', not {'an' if wanted[0] in 'aeiou' else 'a'} "
                f"{wanted}."
            )

    # -- introspection -----------------------------------------------------

    def list_fmus(self) -> list[str]:
        return sorted(self._paths)

    def list_fmu_ports(self, fmu: str) -> dict[str, Any]:
        description = dict(self._description(fmu))
        # Report the start values the client has set, not only the declared
        # ones: otherwise `set_start_value` looks like it did nothing.
        description["ports"] = [
            {**port, "start": self._start_values.get((fmu, port["name"]), port["start"])}
            for port in description["ports"]
        ]
        return description

    def inspect_fmu_file(self, path: str) -> dict[str, Any]:
        return describe_fmu(Path(path))

    def get_assembly_json(self) -> dict[str, Any]:
        if not self._paths:
            return {}
        return self._assembly().json_encode()

    # -- mutations ---------------------------------------------------------

    def add_fmu(self, path: str) -> dict[str, Any]:
        fmu_path = Path(path)
        description = describe_fmu(fmu_path)
        name = description["fmu"]

        known = self._paths.get(name)
        if known is not None and known != fmu_path:
            raise ValueError(
                f"Another file is already embedded as '{name}' ('{known}'). "
                f"FMUs are designated by their file name, so two different "
                f"files cannot share one: rename one of them."
            )

        self._paths[name] = fmu_path
        self._descriptions[name] = description
        logger.info(f"[AI] Added FMU '{name}'")

        return {
            "fmu": name,
            "path": description["path"],
            "fmi_version": description["fmi_version"],
            "generator": description["generator"],
            "kinds": description["kinds"],
            "counts": _count_by_causality(description["ports"]),
            "terminals": description["terminals"],
        }

    def remove_fmu(self, name: str) -> dict[str, Any]:
        self._description(name)  # raises if unknown
        removed = [link for link in self._links if name in (link[0], link[2])]
        self._links = [link for link in self._links if link not in removed]
        self._exposed_inputs = [item for item in self._exposed_inputs if item[0] != name]
        self._exposed_outputs = [item for item in self._exposed_outputs if item[0] != name]
        self._start_values = {key: value for key, value in self._start_values.items()
                              if key[0] != name}
        del self._paths[name]
        del self._descriptions[name]
        logger.info(f"[AI] Removed FMU '{name}' ({len(removed)} link(s))")
        return {"fmu": name, "removed_links": len(removed)}

    def add_link(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        self._check_causality(from_fmu, from_port, ("output",))
        self._check_causality(to_fmu, to_port, ("input",))
        link = (from_fmu, from_port, to_fmu, to_port)
        if link not in self._links:
            self._links.append(link)
        description = f"{from_fmu}/{from_port} -> {to_fmu}/{to_port}"
        logger.info(f"[AI] Linked {description}")
        return description

    def remove_link(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        link = (from_fmu, from_port, to_fmu, to_port)
        if link not in self._links:
            raise ValueError(
                f"There is no link {from_fmu}/{from_port} -> {to_fmu}/{to_port}. "
                f"Use `get_assembly_json` to see the existing ones."
            )
        self._links.remove(link)
        description = f"{from_fmu}/{from_port} -> {to_fmu}/{to_port}"
        logger.info(f"[AI] Unlinked {description}")
        return description

    def expose_input(self, fmu: str, port: str) -> str:
        self._check_causality(fmu, port, ("input", "parameter"))
        if (fmu, port) not in self._exposed_inputs:
            self._exposed_inputs.append((fmu, port))
        logger.info(f"[AI] Exposed input {fmu}/{port}")
        return f"{fmu}/{port}"

    def expose_output(self, fmu: str, port: str) -> str:
        self._check_causality(fmu, port, ("output",))
        if (fmu, port) not in self._exposed_outputs:
            self._exposed_outputs.append((fmu, port))
        logger.info(f"[AI] Exposed output {fmu}/{port}")
        return f"{fmu}/{port}"

    def set_start_value(self, fmu: str, port: str, value: str) -> str:
        self._port(fmu, port)  # raises if unknown
        self._start_values[(fmu, port)] = str(value)
        logger.info(f"[AI] Start value {fmu}/{port} = {value}")
        return f"{fmu}/{port} = {value}"

    def unset_start_value(self, fmu: str, port: str) -> str:
        declared = self._port(fmu, port)["start"]
        if (fmu, port) not in self._start_values:
            raise ValueError(
                f"No start value was set on {fmu}/{port}"
                + (f" (the FMU declares '{declared}')." if declared is not None
                   else " and the FMU declares none.")
            )
        del self._start_values[(fmu, port)]
        logger.info(f"[AI] Start value cleared on {fmu}/{port}")
        return f"{fmu}/{port}"

    def set_container_options(self, options: dict[str, Any]) -> dict[str, Any]:
        unknown = set(options) - set(DEFAULT_OPTIONS)
        if unknown:
            raise ValueError(f"Unknown container option(s): {sorted(unknown)}. "
                             f"Allowed: {sorted(DEFAULT_OPTIONS)}")
        self._options.update(options)
        logger.info(f"[AI] Container options updated: {options}")
        return dict(self._options)

    # -- assembly ----------------------------------------------------------

    def _assembly(self) -> Assembly:
        """Materialise the requested topology as an :class:`Assembly`.

        Rebuilt on demand rather than maintained incrementally: ``make_fmu``
        mutates the node it builds (auto-link and auto-expose rules are written
        back into it), so a long-lived node would accumulate derived content
        and no longer reflect what the client actually asked for.
        """
        if not self._paths:
            raise AssemblyError("The assembly is empty: add at least one FMU first.")

        node = AssemblyNode(self._name, **self._options)
        # FMUs are referenced by absolute path, as the GUI does: the container
        # resolves them against `fmu_directory`, and an absolute path wins.
        for name in sorted(self._paths):
            node.add_fmu(str(self._paths[name]))
        for from_fmu, from_port, to_fmu, to_port in self._links:
            node.add_link(str(self._paths[from_fmu]), from_port,
                          str(self._paths[to_fmu]), to_port)
        for fmu, port in self._exposed_inputs:
            node.add_input(port, str(self._paths[fmu]), port)
        for fmu, port in self._exposed_outputs:
            node.add_output(str(self._paths[fmu]), port, port)
        for (fmu, port), value in self._start_values.items():
            node.add_start_value(str(self._paths[fmu]), port, value)

        assembly = Assembly()
        assembly.root = node
        return assembly

    # -- build / export ----------------------------------------------------

    def save_as_json(self, path: str) -> str:
        self._assembly().write_json(Path(path))
        logger.info(f"[AI] Exported assembly JSON to '{path}'")
        return path

    def save_as_fmu(self, path: str, fmi_version: int = 2, datalog: bool = False) -> str:
        if fmi_version not in SUPPORTED_FMI_VERSIONS:
            raise ValueError(
                f"Unsupported FMI version {fmi_version!r}: expected one of "
                f"{list(SUPPORTED_FMI_VERSIONS)}."
            )
        assembly = self._assembly()
        # The description is embedded in the built FMU for traceability; it is
        # written to a throw-away directory, hence `basenames_only`.
        with tempfile.TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "container.json"
            assembly.write_json(json_path, basenames_only=True)
            assembly.description_pathname = json_path
            assembly.make_fmu(filename=path, fmi_version=fmi_version, datalog=datalog)
        logger.info(f"[AI] Built container FMU '{path}' (FMI-{fmi_version})")
        return path




