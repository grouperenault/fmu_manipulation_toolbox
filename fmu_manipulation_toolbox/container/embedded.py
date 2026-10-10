"""FMUs to embed in a container, and their ports."""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..ls import LayeredStandard
from ..operations import FMU, OperationAbstract, FMUError, FMUPort
from ..terminals import Terminals
from .arrays import ArrayAggregate
from .errors import FMUContainerError
from .types import ALL_TYPES, CONTAINER_TO_FMI, FMI_TO_CONTAINER


logger = logging.getLogger("fmu_manipulation_toolbox")


class EmbeddedFMUPort:
    """Represents a port of an FMU embedded inside a container.

    Handles the mapping between FMI-standard type names (e.g. `Real`, `Float64`)
    and internal container type names (e.g. `real64`), and generates the
    corresponding XML fragments for `modelDescription.xml`.

    Attributes:
        FMI_TO_CONTAINER (dict[int, dict[str, str]]): Mapping from FMI type names
            to container type names, keyed by FMI version (alias of
            `container.types.FMI_TO_CONTAINER`).
        CONTAINER_TO_FMI (dict[int, dict[str, str]]): Reverse mapping from container
            type names to FMI type names, keyed by FMI version (alias).
        ALL_TYPES (tuple[str, ...]): All container type names (alias).
        causality (str): Port causality (`"input"`, `"output"`, `"local"`,
            `"parameter"`).
        variability (str | None): Port variability (`"continuous"`, `"discrete"`, etc.).
        name (str): Port name.
        vr (int): Value reference in the original FMU.
        type_name (str): Container-internal type name (e.g. `"real64"`).
        start_value (str | None): Start value, if defined.
        initial (str | None): Initial value attribute.
        clock (str | None): Clock reference for clocked ports.
        description (str | None): Human-readable description of the port.
    """

    # Aliases of the tables of `container.types`, kept for compatibility.
    FMI_TO_CONTAINER = FMI_TO_CONTAINER

    CONTAINER_TO_FMI = CONTAINER_TO_FMI

    ALL_TYPES = ALL_TYPES

    def __init__(self, fmi_type, attrs: FMUPort | dict[str, Any], fmi_version=0):
        self.causality = attrs.get("causality", "local")
        self.variability = attrs.get("variability", None)
        self.interval_variability = attrs.get("intervalVariability", None)
        self.name = attrs["name"]
        self.vr = int(attrs["valueReference"])
        self.description = attrs.get("description", None)
        if isinstance(attrs, FMUPort):
            self.dimensions = attrs.dimensions
        else:
            self.dimensions = []

        # For FMI-2 aggregated arrays: flag marking this port as a virtual
        # array built from scalar element ports (vs a native FMI-3 array port).
        # Used by `xml()` to prevent incorrectly exposing such an aggregate as a
        # container port in an FMI-2 container.
        self.is_fmi2_aggregate: bool = False
        # Names of the underlying scalar element ports (e.g. `basename[1]`, ...),
        # used to mark each individual scalar port as LINK when the aggregate is
        # connected, so the checker does not report them as unconnected.
        self.element_names: list[str] = []

        if fmi_version > 0:
            self.type_name = FMI_TO_CONTAINER[fmi_version][fmi_type]
        else:
            self.type_name = fmi_type

        self.start_value = attrs.get("start", None)
        self.initial = attrs.get("initial", None)
        self.clock = attrs.get("clocks", None)

    def size(self) -> int:
        size = 1
        for dimension in self.dimensions:
            if dimension[0] == "start":
                size *= dimension[1]
            else:
                raise FMUError(f"Port '{self.name}' depends on structuralParameter '{dimension[1]}' "
                               f"which is not supported")
        return size

    def xml(self, vr: int, name=None, causality=None, start=None, fmi_version=2) -> ET.Element | None:
        """Generate the XML element for this port in `modelDescription.xml`.

        Produces a `<ScalarVariable>` element (FMI 2.0) or a typed element
        like `<Float64>` (FMI 3.0). Attribute values are escaped when the
        document is written.

        Args:
            vr (int): Value reference to use in the generated XML.
            name (str | None): Override port name. Defaults to `self.name`.
            causality (str | None): Override causality. Defaults to `self.causality`.
            start (str | None): Override start value. Defaults to `self.start_value`.
            fmi_version (int): FMI version (`2` or `3`).

        Returns:
            ET.Element | None: The variable element, or `None` if the type is
                not compatible with the requested FMI version.
        """
        if name is None:
            name = self.name
        if causality is None:
            causality = self.causality
        if start is None:
            start = self.start_value
            if start is None and self.type_name == "binary" and self.initial == "exact":
                start = ""
        variability = self.variability
        if variability is None:
            if self.causality == "parameter":
                variability = "fixed"
            else:
                variability = "continuous" if "real" in self.type_name else "discrete"

        try:
            fmi_type = CONTAINER_TO_FMI[fmi_version][self.type_name]
        except KeyError:
            logger.error(f"Cannot expose ({causality}) '{name}' because type '{self.type_name}' is not compatible "
                         f"with FMI-{fmi_version}.0")
            return None

        if fmi_version == 2 and self.is_fmi2_aggregate:
            logger.error(f"Cannot expose FMI-2 array aggregate '{name}' in an FMI-2 container "
                         f"(use the scalar elements '{name}[k]' individually).")
            return None

        attrs = {
            "name": name,
            "valueReference": vr,
            "causality": causality,
            "variability": variability,
            "initial": self.initial,
            "description": self.description,
        }

        if fmi_version == 2:
            variable = self._element("ScalarVariable", attrs)
            variable.append(self._element(fmi_type, {"start": start}))
            return variable

        elif fmi_version == 3:
            if self.dimensions or fmi_type in ('String', 'Binary'):
                variable = self._element(fmi_type, attrs)
                for dimension in self.dimensions:
                    variable.append(self._element("Dimension", {dimension[0]: dimension[1]}))
                if start is not None:
                    variable.append(self._element("Start", {"value": start}))
            else:
                variable = self._element(fmi_type, {**attrs, "start": start,
                                                    "intervalVariability": self.interval_variability})
            return variable

        else:
            logger.critical(f"Unknown version {fmi_version}. BUG?")
            return None

    @staticmethod
    def _element(tag: str, attrs: dict[str, Any]) -> ET.Element:
        """Element with the attributes whose value is not `None`, converted to strings."""
        return ET.Element(tag, {key: str(value) for key, value in attrs.items() if value is not None})


class EmbeddedFMU(OperationAbstract):
    """Represents an FMU loaded and analyzed for embedding inside a container.

    Parses the `modelDescription.xml` of an FMU to extract its ports,
    capabilities, step size, platform support, and co-simulation metadata.
    Implements
    [OperationAbstract][fmu_manipulation_toolbox.operations.OperationAbstract]
    to process the FMU descriptor via the visitor pattern.

    Attributes:
        capability_list (tuple[str, ...]): FMI capability flags tracked by the container.
        fmu (FMU): The underlying
            [FMU][fmu_manipulation_toolbox.operations.FMU] object.
        name (str): Filename of the FMU (e.g. `"model.fmu"`).
        id (str): Lowercase stem of the filename, used as an identifier.
        terminals (Terminals): FMI Terminals defined by this FMU.
        ls (LayeredStandard): LS-BUS layered standard information.
        step_size (float | None): Preferred step size in seconds, or `None`.
        start_time (float | None): Default experiment start time.
        stop_time (float | None): Default experiment stop time.
        model_identifier (str | None): Co-simulation model identifier.
        guid (str | None): GUID (FMI 2.0) or instantiation token (FMI 3.0).
        fmi_version (int | None): FMI version (`2` or `3`).
        platforms (set[str]): Supported operating systems (e.g. `{"Windows", "Linux"}`).
        ports (dict[str, EmbeddedFMUPort]): Ports of the FMU, keyed by name.
        has_event_mode (bool): Whether the FMU supports event mode (FMI 3.0).
        capabilities (dict[str, str]): FMI capability flags and their values.
        is_me (bool): Whether the FMU is embedded in Model-Exchange mode.
            Co-Simulation takes precedence when both modes are provided.
        number_of_continuous_states (int): Number of continuous states (`nx`).
        number_of_event_indicators (int): Number of event indicators (`nz`).

    Raises:
        FMUContainerError: If the FMU does not implement Co-Simulation mode.
    """

    # Not written back: Enumeration -> Integer is only needed in memory, and the container
    # embeds the original archive, not the extracted descriptor.
    read_only = True

    capability_list = ("needsExecutionTool",
                       "canBeInstantiatedOnlyOncePerProcess",
                       "canHandleVariableCommunicationStepSize")

    def __init__(self, filename):
        self.fmu = FMU(filename)
        self.name = Path(filename).name
        self.id = Path(filename).stem.lower()

        logger.debug(f"Analysing {self.name}")
        self.terminals = Terminals(self.fmu.tmp_directory)
        self.ls = LayeredStandard(self.fmu.tmp_directory)

        self.step_size = None
        self.start_time = None
        self.stop_time = None
        self.model_identifier = None
        self.guid = None
        self.fmi_version = None
        self.is_me = False
        self.number_of_continuous_states = 0
        self.number_of_event_indicators = 0
        self.platforms = set()
        self.ports: dict[str, EmbeddedFMUPort] = {}

        self.has_event_mode = False
        self.capabilities: dict[str, str] = {}
        self.current_port = None  # used during apply_operation()

        self.fmu.apply_operation(self)  # Should be the last command in constructor!
        if self.model_identifier is None:
            raise FMUContainerError(f"FMU '{self.name}' does not implement Co-Simulation mode.")

        if self.fmi_version == 2:
            self._detect_array_aggregates()


    def _detect_array_aggregates(self):
        """Detect FMI-2 array elements notated as `basename[k]` (1D) or
        `basename[i,j,...]` (N-D, Modelica-style comma notation) and expose
        them as a virtual aggregated port named `basename`.

        The aggregate port carries `dimensions=[("start", N0), ("start", N1), ...]`
        and stores the underlying scalar element VRs in `element_vrs`, flattened
        in **row-major** order (last index varies fastest), matching the FMI-3
        array memory layout. This allows the aggregate to be connected to an
        FMI-3 array port of matching shape.
        """
        candidates = ArrayAggregate.detect_all(
            [p.name for p in self.ports.values()],
            existing_names=set(self.ports.keys()),
            log_prefix=self.name,
        )

        for agg in candidates:
            elements = [self.ports[n] for n in agg.ordered_element_names]
            first = elements[0]

            # All elements must share the same type/causality/variability/clock.
            if not all(p.type_name == first.type_name
                       and p.causality == first.causality
                       and p.variability == first.variability
                       and p.clock == first.clock
                       for p in elements):
                logger.debug(f"'{self.name}': array elements for '{agg.basename}' have "
                             f"heterogeneous attributes, aggregate not created.")
                continue

            aggregate = EmbeddedFMUPort(first.type_name, {
                "name": agg.basename,
                "valueReference": first.vr,   # informational; not used for I/O
                "causality": first.causality,
                "variability": first.variability if first.variability else "continuous",
                "description": f"FMI-2 array aggregate of {agg.size} elements '{agg.basename}[]'",
            })
            aggregate.dimensions = [("start", d) for d in agg.dims]
            aggregate.is_fmi2_aggregate = True
            aggregate.element_names = [p.name for p in elements]
            aggregate.clock = first.clock
            self.ports[agg.basename] = aggregate
            logger.debug(f"'{self.name}': aggregated FMI-2 array '{agg.basename}' "
                         f"(shape={agg.shape_str}, {agg.size} elements).")

    def fmi_attrs(self, attrs):
        fmi_version = attrs['fmiVersion']
        if fmi_version == "2.0":
            self.guid = attrs['guid']
            self.fmi_version = 2
        if fmi_version.startswith("3."):
            self.guid = attrs['instantiationToken']
            self.fmi_version = 3


    def cosimulation_attrs(self, attrs: dict[str, str]):
        # Co-Simulation takes precedence over Model-Exchange for dual-mode FMUs.
        self.is_me = False
        self.model_identifier = attrs['modelIdentifier']
        if attrs.get("hasEventMode", "false") == "true":
            self.has_event_mode = True
        for capability in self.capability_list:
            self.capabilities[capability] = attrs.get(capability, "false")
        logger.debug(f"FMU '{self.name}' is embedded in Co-Simulation mode.")

    def modelexchange_attrs(self, attrs):
        self.is_me = True
        self.model_identifier = attrs['modelIdentifier']
        for capability in self.capability_list:
            self.capabilities[capability] = attrs.get(capability, "false")
        logger.debug(f"FMU '{self.name}' provides Model-Exchange mode.")

    def experiment_attrs(self, attrs: dict[str, str]):
        try:
            self.step_size = float(attrs['stepSize'])
        except KeyError:
            logger.warning(f"FMU '{self.name}' does not specify preferred step size")
        self.start_time = float(attrs.get("startTime", 0.0))
        self.stop_time = float(attrs.get("stopTime", self.start_time + 1.0))

    def port_attrs(self, fmu_port: FMUPort):
        # Container will manage Enumeration as Integer
        if fmu_port.fmi_type == "Enumeration":
            if self.fmi_version == 2:
                fmu_port.fmi_type = "Integer"
            else:
                fmu_port.fmi_type = "Int32"
        port = EmbeddedFMUPort(fmu_port.fmi_type, fmu_port, fmi_version=self.fmi_version)
        self.ports[port.name] = port

    def closure(self):
        self.number_of_continuous_states, self.number_of_event_indicators = \
            self.model_description.model_exchange_sizes(self.name)

        osname = {
            "win64": "Windows",
            "linux64": "Linux",
            "darwin64": "Darwin",
            "x86_64-windows": "Windows",
            "x86_64-linux": "Linux",
            "aarch64-darwin": "Darwin"
        }
        try:
            for directory in (Path(self.fmu.tmp_directory) / "binaries").iterdir():
                if directory.is_dir() and str(directory.stem) in osname:
                    self.platforms.add(osname[str(directory.stem)])
        except FileNotFoundError:
            pass  # no binaries

    def __repr__(self):
        properties = f"{len(self.ports)} variables, ts={self.step_size}s"
        if len(self.terminals) > 0:
            properties += f", {len(self.terminals)} terminals"
        if len(self.ls) > 0:
            properties += f", {self.ls}"
        return f"'{self.name}' ({properties})"
