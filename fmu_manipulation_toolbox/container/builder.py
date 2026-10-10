"""Builder of FMU Containers."""

import getpass
import logging
import math
import os
import shutil
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from collections import defaultdict
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import Any

from ..model_description import ModelDescription
from ..operations import FMUError
from ..textfiles import ENCODING
from ..version import __version__ as tool_version
from .embedded import EmbeddedFMU, EmbeddedFMUPort
from .errors import FMUContainerError
from .layout import ContainerLayout
from .rules import AutoWired, ContainerInput, ContainerPort, Link
from .txt import ClockList, FMUIOList, InvolvedFMU, LocalVariable, Port
from .types import ALL_TYPES


logger = logging.getLogger("fmu_manipulation_toolbox")


@dataclass
class Platform:
    """Binary of the container runtime for one OS: directory in the toolbox resources, library suffix, directory in
    the container."""
    origin_bindir: str
    suffixe: str
    target_bindir: str


class FMUContainer:
    """Builds an FMU Container that embeds multiple FMUs into a single FMU.

    An `FMUContainer` acts as both an FMI co-simulation FMU and an FMI importer.
    It loads embedded FMUs, wires their ports together, and generates the
    `modelDescription.xml`, the runtime configuration (`container.txt`), and the
    final `.fmu` archive.

    Examples:
        ```python
        from pathlib import Path
        from fmu_manipulation_toolbox.container import FMUContainer

        container = FMUContainer("bouncing", Path("fmus"), fmi_version=2)
        container.get_fmu("bb_position.fmu")
        container.get_fmu("bb_velocity.fmu")
        container.add_link("bb_position.fmu", "is_ground",
                           "bb_velocity.fmu", "reset")
        container.add_implicit_rule(auto_input=True, auto_output=True)
        container.make_fmu("bouncing.fmu", step_size=0.1)
        ```

    Attributes:
        fmu_directory (Path): Directory containing the source FMUs.
        identifier (str): Model identifier for the container.
        fmi_version (int): FMI version of the container interface (`2` or `3`).
        involved_fmu (OrderedDict[str, EmbeddedFMU]): Embedded FMUs, keyed
            by filename, in insertion order.
        inputs (dict[str, ContainerInput]): Container input ports, keyed by
            exposed name.
        outputs (dict[str, ContainerPort]): Container output ports, keyed by
            exposed name.
        links (dict[ContainerPort, Link]): Internal links between embedded FMUs.
        start_values (dict[ContainerPort, str]): Start values for embedded FMU ports.
        start_time (float | None): Start time of the default experiment; `None` to take
            the one of the first embedded FMU.
        stop_time (float | None): Stop time of the default experiment; `None` to take
            the one of the first embedded FMU.

    Raises:
        FMUContainerError: If the FMU directory is invalid.
    """

    def __init__(self, identifier: str, fmu_directory: str | Path, description_pathname=None, fmi_version=2):
        self.fmu_directory = Path(fmu_directory)
        self.identifier = identifier
        if not self.fmu_directory.is_dir():
            raise FMUContainerError(f"{self.fmu_directory} is not a valid directory")
        self.involved_fmu = InvolvedFMU()

        self.description_pathname = description_pathname
        self.fmi_version = fmi_version

        self.start_time = None
        self.stop_time = None

        self.have_me = False

        # Rules
        self.inputs: dict[str, ContainerInput] = {}
        self.outputs: dict[str, ContainerPort] = {}
        self.links: dict[ContainerPort, Link] = {}

        self.rules: dict[ContainerPort, str] = {}
        self.start_values: dict[ContainerPort, str] = {}

    def get_fmu(self, fmu_filename: str) -> EmbeddedFMU:
        """Load an embedded FMU from the FMU directory.

        If the FMU has already been loaded, returns the cached instance.

        Args:
            fmu_filename (str): Filename of the FMU (e.g. `"model.fmu"`).

        Returns:
            EmbeddedFMU: The loaded and analysed FMU.

        Raises:
            FMUContainerError: If the FMU cannot be loaded.
        """
        fmu_name = Path(fmu_filename).name
        if fmu_name in self.involved_fmu:
            return self.involved_fmu[fmu_name]
        
        try:
            fmu = EmbeddedFMU(self.fmu_directory / fmu_filename)
        except (FMUContainerError, FMUError) as e:
            raise FMUContainerError(f"Cannot load '{fmu_filename}': {e}")

        if not fmu.fmi_version == self.fmi_version:
            logger.warning(f"Try to embed FMU-{fmu.fmi_version} into container FMI-{self.fmi_version}.")
        self.involved_fmu[fmu.name] = fmu

        if fmu.is_me:
            fmu_type = "ME"
            self.have_me = True
        else:
            fmu_type = "CS"

        logger.info(f"Involved FMU #{len(self.involved_fmu)}: {fmu} ({fmu_type})")

        return fmu

    def mark_ruled(self, cport: ContainerPort, rule: str):
        if cport in self.rules:
            previous_rule = self.rules[cport]
            if rule not in ("OUTPUT", "LINK") and previous_rule not in ("OUTPUT", "LINK"):
                raise FMUContainerError(f"try to {rule} port {cport} which is already {previous_rule}")

        self.rules[cport] = rule

    def get_all_cports(self):
        cport_list = []
        for fmu in self.involved_fmu.values():
            for port_name in fmu.ports:
                try:
                    cport = ContainerPort(fmu, port_name)
                    cport_list.append(cport)
                except FMUContainerError:
                    pass

        return cport_list

    def add_input(self, container_port_name: str, to_fmu_filename: str, to_port_name: str):
        """Expose a port of an embedded FMU as a container input.

        Multiple embedded FMU ports can be connected to the same container
        input (fan-out), provided they share the same type and causality.

        Args:
            container_port_name (str): Exposed name on the container. If empty,
                defaults to `to_port_name`.
            to_fmu_filename (str): Filename of the embedded FMU.
            to_port_name (str): Name of the input port on the embedded FMU.

        Raises:
            FMUContainerError: If the FMU or the port does not exist, if the port
                causality is not `"input"` or `"parameter"`, or if types do not
                match an existing input with the same name.
        """
        if not container_port_name:
            container_port_name = to_port_name

        try:
            cport_to = ContainerPort(self.get_fmu(to_fmu_filename), to_port_name)
        except FMUContainerError as e:
            raise FMUContainerError(f"Cannot add input '{container_port_name}': {e.reason}") from e

        if cport_to.port.causality not in ("input", "parameter"):  # check causality
            raise FMUContainerError(f"Tried to use '{cport_to}' as INPUT of the container but FMU causality is "
                                    f"'{cport_to.port.causality}'.")

        try:
            input_port = self.inputs[container_port_name]
            input_port.add_cport(cport_to)
        except KeyError:
            self.inputs[container_port_name] = ContainerInput(container_port_name, cport_to)

        logger.debug(f"INPUT: {to_fmu_filename}:{to_port_name}")
        self.mark_ruled(cport_to, 'INPUT')

    def add_output(self, from_fmu_filename: str, from_port_name: str, container_port_name: str):
        """Expose a port of an embedded FMU as a container output.

        Args:
            from_fmu_filename (str): Filename of the embedded FMU.
            from_port_name (str): Name of the output port on the embedded FMU.
            container_port_name (str): Exposed name on the container. If empty,
                defaults to `from_port_name`.

        Raises:
            FMUContainerError: If the FMU or the port does not exist, if the port
                causality is not `"output"` or `"local"`, or if the exposed name is
                already used.
        """
        if not container_port_name:  # empty is allowed
            container_port_name = from_port_name

        try:
            cport_from = ContainerPort(self.get_fmu(from_fmu_filename), from_port_name)
        except FMUContainerError as e:
            raise FMUContainerError(f"Cannot add output '{container_port_name}': {e.reason}") from e

        if cport_from.port.causality not in ("output", "local"):  # check causality
            raise FMUContainerError(f"Tried to use '{cport_from}' as OUTPUT of the container but FMU causality is "
                                    f"'{cport_from.port.causality}'.")

        if container_port_name in self.outputs:
            raise FMUContainerError(f"Duplicate OUTPUT {container_port_name} already connected to {cport_from}")

        logger.debug(f"OUTPUT: {from_fmu_filename}:{from_port_name}")
        self.mark_ruled(cport_from, 'OUTPUT')
        self.outputs[container_port_name] = cport_from

    def drop_port(self, from_fmu_filename: str, from_port_name: str):
        """Explicitly ignore an output port of an embedded FMU.

        Prevents the port from being auto-exposed or flagged as unconnected.

        Args:
            from_fmu_filename (str): Filename of the embedded FMU.
            from_port_name (str): Name of the output port to drop.

        Raises:
            FMUContainerError: If the FMU or the port does not exist, or if the
                port causality is not `"output"`.
        """

        try:
            cport_from = ContainerPort(self.get_fmu(from_fmu_filename), from_port_name)
        except FMUContainerError as e:
            raise FMUContainerError(f"Cannot drop port: {e.reason}") from e

        if not cport_from.port.causality == "output":  # check causality
            raise FMUContainerError(f"{cport_from}: trying to DROP {cport_from.port.causality}")

        logger.debug(f"DROP: {from_fmu_filename}:{from_port_name}")
        self.mark_ruled(cport_from, 'DROP')

    def add_link(self, from_fmu_filename: str, from_port_name: str, to_fmu_filename: str, to_port_name: str):
        """Connect an output of one embedded FMU to an input of another.

        If both port names match FMI Terminal definitions, a terminal-level
        connection is made (connecting all member ports). Otherwise, a regular
        port-to-port link is created.

        Args:
            from_fmu_filename (str): Filename of the source FMU.
            from_port_name (str): Output port name (or terminal name).
            to_fmu_filename (str): Filename of the destination FMU.
            to_port_name (str): Input port name (or terminal name).

        Raises:
            FMUContainerError: If an FMU or a port does not exist, if port
                causalities are invalid or types
                are incompatible.
        """
        fmu_from = self.get_fmu(from_fmu_filename)
        fmu_to = self.get_fmu(to_fmu_filename)

        if from_port_name in fmu_from.terminals and to_port_name in fmu_to.terminals:
            # TERMINAL Connection
            terminal1 = fmu_from.terminals[from_port_name]
            terminal2 = fmu_to.terminals[to_port_name]
            if terminal1 == terminal2:
                logger.debug(f"Plugging terminals: {terminal1} <-> {terminal2}")
                for terminal1_port_name, terminal2_port_name in terminal1.connect(terminal2):
                    self.add_link_regular(fmu_from, terminal1_port_name, fmu_to, terminal2_port_name)
            else:
                logger.error(f"Cannot plug incompatible terminals: {terminal1} <-> {terminal2}")
        else:
            # REGULAR port connection
            self.add_link_regular(fmu_from, from_port_name, fmu_to, to_port_name)

    def add_link_regular(self, fmu_from: EmbeddedFMU, from_port_name: str, fmu_to: EmbeddedFMU, to_port_name: str):

        try:
            cport_from = ContainerPort(fmu_from, from_port_name)
            cport_to = ContainerPort(fmu_to, to_port_name)
        except FMUContainerError as e:
            raise FMUContainerError(f"Cannot link {from_port_name} -> {to_port_name}: {e.reason}") from e

        if cport_to.port.causality == "output" and cport_from.port.causality == "input":
            logger.debug("Invert link orientation")
            tmp = cport_to
            cport_to = cport_from
            cport_from = tmp

        try:
            local = self.links[cport_from]
        except KeyError:
            local = Link(cport_from)
            self.links[cport_from] = local

        local.add_target(cport_to)  # Causality is check in the add() function

        logger.debug(f"LINK: {cport_from} -> {cport_to}")
        self.mark_ruled(cport_from, 'LINK')
        self.mark_ruled(cport_to, 'LINK')

        # If either side is an FMI-2 array aggregate, also mark each
        # underlying scalar element port as LINK so it is not reported
        # as unconnected.
        for cport in (cport_from, cport_to):
            for elt_name in cport.port.element_names:
                try:
                    self.mark_ruled(ContainerPort(cport.fmu, elt_name), 'LINK')
                except FMUContainerError:
                    pass

    def add_start_value(self, fmu_filename: str, port_name: str, value: str):
        """Set a start value for a port of an embedded FMU.

        The value is automatically converted to the appropriate type
        (float, int, bool, or string).

        Args:
            fmu_filename (str): Filename of the embedded FMU.
            port_name (str): Name of the port.
            value (str): Start value as a string.

        Raises:
            FMUContainerError: If the FMU or the port does not exist, if the port
                type has no start value (binary, clock), or if the value cannot be
                converted to the port's type.
        """

        try:
            cport = ContainerPort(self.get_fmu(fmu_filename), port_name)
        except FMUContainerError as e:
            raise FMUContainerError(f"Cannot set start value: {e.reason}") from e

        # Check dimensions
        value_tokens = str(value).split(' ')
        if not len(value_tokens) == cport.port.size():
            raise FMUContainerError(f"Start value missmatch for {cport.port.type_name} which is dimension {cport.port.size()}")

        # Check type
        for token in value_tokens:
            try:
                if cport.port.type_name.startswith('real'):
                    float(token)
                elif cport.port.type_name.startswith('integer') or  cport.port.type_name.startswith('uinteger'):
                    int(token)
                elif cport.port.type_name.startswith('boolean'):
                    if token not in ("true", "false", "0", "1"):
                        raise ValueError(f"Invalid boolean value: '{token}'")
                elif cport.port.type_name == 'string':
                    pass
                else:
                    raise FMUContainerError(f"Start value cannot be set on {cport} of type '{cport.port.type_name}'.")
            except ValueError:
                raise FMUContainerError(f"Start value is not conforming to {cport.port.type_name} format.")

        # Format is different for string
        if cport.port.type_name == 'string':
            value = "\n" + "\n".join(value_tokens)

        self.start_values[cport] = value

    def find_inputs(self, port_to_connect: EmbeddedFMUPort) -> list[ContainerPort]:
        candidates = []
        for cport in self.get_all_cports():
            if (cport.port.causality == 'input' and cport not in self.rules and cport.port.name == port_to_connect.name
                    and cport.port.type_name == port_to_connect.type_name):
                candidates.append(cport)
        return candidates

    def add_implicit_rule(self, auto_input=True, auto_output=True, auto_link=True, auto_parameter=False,
                          auto_local=False) -> AutoWired:
        """Automatically wire unconnected ports of embedded FMUs.

        Processes all ports in the following order:

        1. **auto_link**: Connect outputs to inputs with matching names and types.
        2. **auto_output**: Expose remaining unconnected outputs.
        3. **auto_local**: Expose local variables.
        4. **auto_input**: Expose remaining unconnected inputs.
        5. **auto_parameter**: Expose parameters.

        Args:
            auto_input (bool): Expose unconnected input ports.
            auto_output (bool): Expose unconnected output ports.
            auto_link (bool): Link matching output/input ports automatically.
            auto_parameter (bool): Expose parameter ports.
            auto_local (bool): Expose local variables.

        Returns:
            AutoWired: Record of all automatically created rules.
        """
        auto_wired = AutoWired()
        all_cports = self.get_all_cports()
        # Candidates of the auto-links, by (name, type), in the order of `all_cports`: same result as `find_inputs`,
        # without going through every port for each output.
        inputs_by_signature: dict[tuple[str, str], list[ContainerPort]] = defaultdict(list)
        for cport in all_cports:
            if cport.port.causality == 'input':
                inputs_by_signature[(cport.port.name, cport.port.type_name)].append(cport)

        # Auto Link outputs
        for cport in all_cports:
            if cport.port.causality == 'output':
                candidates_cport_list = [candidate for candidate in
                                         inputs_by_signature[(cport.port.name, cport.port.type_name)]
                                         if candidate not in self.rules]
                if auto_link and candidates_cport_list:
                    for candidate_cport in candidates_cport_list:
                        logger.info(f"AUTO LINK: {cport} -> {candidate_cport}")
                        self.add_link(cport.fmu.name, cport.port.name,
                                      candidate_cport.fmu.name, candidate_cport.port.name)
                        auto_wired.add_link(cport.fmu.name, cport.port.name,
                                            candidate_cport.fmu.name, candidate_cport.port.name)
                elif auto_output and cport not in self.rules:
                    logger.info(f"AUTO OUTPUT: Expose {cport}")
                    self.add_output(cport.fmu.name, cport.port.name, cport.port.name)
                    auto_wired.add_output(cport.fmu.name, cport.port.name, cport.port.name)
            elif cport.port.causality == 'local':
                local_portname = None
                if cport.port.name.startswith("container."):
                    local_portname = "container." + cport.fmu.id + "." + cport.port.name[10:]
                    logger.info(f"PROFILING: Expose {cport}")
                elif auto_local:
                    local_portname = cport.fmu.id + "." + cport.port.name
                    logger.info(f"AUTO LOCAL: Expose {cport}")
                if local_portname:
                    self.add_output(cport.fmu.name, cport.port.name, local_portname)
                    auto_wired.add_output(cport.fmu.name, cport.port.name, local_portname)

        # Auto link inputs
        for cport in all_cports:
            if cport not in self.rules:
                if auto_parameter and cport.port.causality == 'parameter':
                    parameter_name = cport.fmu.id + "." + cport.port.name
                    logger.info(f"AUTO PARAMETER: {cport} as {parameter_name}")
                    self.add_input(parameter_name, cport.fmu.name, cport.port.name)
                    auto_wired.add_parameter(parameter_name, cport.fmu.name, cport.port.name)
                elif auto_input and cport.port.causality == 'input' :
                    logger.info(f"AUTO INPUT: Expose {cport}")
                    self.add_input(cport.port.name, cport.fmu.name, cport.port.name)
                    auto_wired.add_input(cport.port.name, cport.fmu.name, cport.port.name)

        logger.info(f"Auto-wiring: {auto_wired}")

        return auto_wired

    def default_step_size(self) -> float:
        """Compute the default step size from embedded FMUs.

        Uses the GCD of the frequencies of FMUs that cannot handle variable
        step sizes. If all FMUs support variable steps, returns the largest
        step size.

        Returns:
            float: Computed step size in seconds.
        """
        default_step_size = 0.1
        freq_set = set()
        for fmu in self.involved_fmu.values():
            if fmu.step_size and fmu.capabilities["canHandleVariableCommunicationStepSize"] == "false":
                freq_set.add(int(1.0/fmu.step_size))

        if not freq_set:
            # all involved FMUs can Handle Variable Communication StepSize
            try:
                step_size_max = 0
                for fmu in self.involved_fmu.values():
                    if fmu.step_size > step_size_max:
                        step_size_max = fmu.step_size
                return step_size_max
            except TypeError:
                # all involved FMUs do not specify step_size
                logger.warning(f"Defaulting to step_size={default_step_size}")
                step_size = default_step_size
        else:
            common_freq = math.gcd(*freq_set)
            try:
                step_size = 1.0 / float(common_freq)
            except ZeroDivisionError:
                logger.warning(f"Defaulting to step_size={default_step_size}")
                step_size = default_step_size

        return step_size

    def sanity_check(self, step_size: float | None):
        """Validate the container configuration before building.

        Warns about step size mismatches and unconnected ports.

        Args:
            step_size (float | None): The container's internal step size.
        """
        for fmu in self.involved_fmu.values():
            if fmu.step_size and fmu.capabilities["canHandleVariableCommunicationStepSize"] == "false":
                ts_ratio = step_size / fmu.step_size
                logger.debug(f"container step_size: {step_size} = {fmu.step_size} x {ts_ratio} for {fmu.name}")
                if ts_ratio < 1.0:
                    logger.warning(f"Container step_size={step_size}s is lower than FMU '{fmu.name}' "
                                   f"step_size={fmu.step_size}s.")
                if ts_ratio != int(ts_ratio):
                    logger.warning(f"Container step_size={step_size}s should divisible by FMU '{fmu.name}' "
                                   f"step_size={fmu.step_size}s.")
            for port_name, fmu_port in fmu.ports.items():
                if fmu_port.is_fmi2_aggregate:
                    continue
                cport = ContainerPort(fmu, port_name)
                if cport not in self.rules:
                    if cport.port.causality == 'input':
                        logger.error(f"Input '{cport}' is not connected")
                    if cport.port.causality == 'output':
                        logger.warning(f"Output '{cport}' is not connected")

    def make_fmu(self, fmu_filename: str | Path, step_size: float | None = None, debug=False, mt=False,
                 profiling=False, sequential=False, ts_multiplier=False, datalog=False):
        """Build the FMU Container archive.

        Generates the `modelDescription.xml`, the `container.txt` runtime
        configuration, and packages everything into a `.fmu` zip archive.

        Args:
            fmu_filename (str | Path): Output filename for the container.
            step_size (float | None): Internal time step in seconds. If `None`,
                deduced from the embedded FMUs.
            debug (bool): Keep intermediate build artifacts.
            mt (bool): Enable multithreaded mode.
            profiling (bool): Enable profiling mode.
            sequential (bool): Use sequential scheduling.
            ts_multiplier (bool): Add a `TS_MULTIPLIER` input port.
            datalog (bool): Generate a datalog configuration.
        """
        if isinstance(fmu_filename, str):
            fmu_filename = Path(fmu_filename)

        if step_size is None:
            logger.info("step_size  will be deduced from the embedded FMU's")
            step_size = self.default_step_size()
        self.sanity_check(step_size)

        if mt and len(self.involved_fmu) < 2:
            logger.error("Requesting Multi-threaded mode with to few FMUs. Back to Mono-threaded mode.")
            mt = False

        logger.info(f"Building FMU '{fmu_filename}', step_size={step_size}")

        base_directory = self.fmu_directory / fmu_filename.with_suffix('')
        resources_directory = self.make_fmu_skeleton(base_directory)

        # Allocated again at each build: the rules are never modified by a build.
        layout = ContainerLayout.allocate(self.links.values(), self.inputs, self.outputs,
                                          nb_profiling=len(self.involved_fmu) if profiling else 0)

        self.make_fmu_xml(base_directory / "modelDescription.xml", step_size, profiling, ts_multiplier, layout)
        with open(resources_directory / "container.txt", "wt", encoding=ENCODING) as txt_file:
            self.make_fmu_txt(txt_file, step_size, mt, profiling, sequential, layout)

        if datalog:
            with open(resources_directory / "datalog.txt", "wt", encoding=ENCODING) as datalog_file:
                self.make_datalog(datalog_file, layout)

        self.make_fmu_package(base_directory, fmu_filename)
        if not debug:
            self.make_fmu_cleanup(base_directory)

    def make_fmu_xml(self, xml_filename: Path, step_size: float, profiling: bool, ts_multiplier: bool,
                     layout: ContainerLayout):
        """Build the container `modelDescription.xml` and write it (UTF-8, see `ModelDescription.save`).

        The document is built as an ElementTree, so that names and descriptions
        coming from the embedded FMUs are escaped. FMI 2.0 `<Unknown index>`
        entries are computed from the actual position of the output variables.
        The value references come from `layout`.
        """
        timestamp = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        guid = str(uuid.uuid4())
        embedded_fmu = ", ".join([fmu_name for fmu_name in self.involved_fmu])
        try:
            author = getpass.getuser()
        except OSError:
            author = "Unspecified"

        capabilities = {}
        for capability in EmbeddedFMU.capability_list:
            capabilities[capability] = "false"
            for fmu in self.involved_fmu.values():
                if fmu.capabilities[capability] == "true":
                    capabilities[capability] = "true"

        first_fmu = next(iter(self.involved_fmu.values()))
        start_time = self.start_time
        if start_time is None:
            start_time = first_fmu.start_time
            logger.info(f"start_time={start_time} (deduced from '{first_fmu.name}')")
        else:
            logger.info(f"start_time={start_time}")

        stop_time = self.stop_time
        if stop_time is None:
            stop_time = first_fmu.stop_time
            logger.info(f"stop_time={stop_time} (deduced from '{first_fmu.name}')")
        else:
            logger.info(f"stop_time={stop_time}")

        root = ET.Element("fmiModelDescription", {
            "fmiVersion": f"{self.fmi_version}.0",
            "modelName": self.identifier,
            "generationTool": f"FMUContainer-{tool_version}",
            "generationDateAndTime": timestamp,
            "guid" if self.fmi_version == 2 else "instantiationToken": guid,
            "description": f"FMUContainer with {embedded_fmu}",
            "author": author,
            "license": "Proprietary",
            "copyright": "See Embedded FMU's copyrights.",
            "variableNamingConvention": "structured",
        })

        if self.fmi_version == 2:
            cosimulation = {
                "modelIdentifier": self.identifier,
                "canHandleVariableCommunicationStepSize": "true",
                "canBeInstantiatedOnlyOncePerProcess": capabilities['canBeInstantiatedOnlyOncePerProcess'],
                "canNotUseMemoryManagementFunctions": "true",
                "canGetAndSetFMUstate": "false",
                "canSerializeFMUstate": "false",
                "providesDirectionalDerivative": "false",
                "needsExecutionTool": capabilities['needsExecutionTool'],
            }
        else:
            cosimulation = {
                "modelIdentifier": self.identifier,
                "canHandleVariableCommunicationStepSize": "true",
                "canBeInstantiatedOnlyOncePerProcess": capabilities['canBeInstantiatedOnlyOncePerProcess'],
                "canNotUseMemoryManagementFunctions": "true",
                "canGetAndSetFMUState": "false",
                "canSerializeFMUState": "false",
                "providesDirectionalDerivatives": "false",
                "providesAdjointDerivatives": "false",
                "providesPerElementDependencies": "false",
                "providesEvaluateDiscreteStates": "false",
                "hasEventMode": "false",
                "needsExecutionTool": capabilities['needsExecutionTool'],
            }
        ET.SubElement(root, "CoSimulation", cosimulation)

        log_categories = ET.SubElement(root, "LogCategories")
        ET.SubElement(log_categories, "Category", {"name": "Info", "description": "Info log messages."})
        ET.SubElement(log_categories, "Category", {"name": "Error", "description": "Error log messages."})

        default_experiment = {"stepSize": str(step_size)}
        if start_time is not None:
            default_experiment["startTime"] = str(start_time)
        if stop_time is not None:
            default_experiment["stopTime"] = str(stop_time)
        ET.SubElement(root, "DefaultExperiment", default_experiment)

        model_variables = ET.SubElement(root, "ModelVariables")
        if self.fmi_version == 2:
            time = ET.SubElement(model_variables, "ScalarVariable",
                                 {"valueReference": str(layout.time), "name": "time", "causality": "independent"})
            ET.SubElement(time, "Real")
        else:
            ET.SubElement(model_variables, "Float64",
                          {"valueReference": str(layout.time), "name": "time", "causality": "independent"})

        def add_variable(variable: ET.Element | None) -> ET.Element | None:
            if variable is not None:
                model_variables.append(variable)
            return variable

        logger.debug(f"Time vr = {layout.time}")

        vr_ts_multiplier = layout.ts_multiplier
        if ts_multiplier:
            logger.debug(f"TS Multiplier vr = {vr_ts_multiplier}")
            port = EmbeddedFMUPort("integer32", {"valueReference": vr_ts_multiplier,
                                                 "name": "container.ts_multiplier",
                                                 "causality": "input",
                                                 "description": "Timestep multiplier",
                                                 "variability": "discrete",
                                                 "start": 1,
                                                 "initial": "exact"})
            add_variable(port.xml(vr_ts_multiplier, fmi_version=self.fmi_version))

        vr_solver = layout.solver
        if self.have_me:
            logger.debug(f"Solver config vr = {vr_solver}")
            port = EmbeddedFMUPort("integer32", {"valueReference": vr_solver,
                                                 "name": "container.solver",
                                                 "causality": "input",
                                                 "description": "0:Euler, 1: RK4",
                                                 "variability": "discrete",
                                                 "start": 0,
                                                 "initial": "exact"})
            add_variable(port.xml(vr_solver, fmi_version=self.fmi_version))

        if profiling:
            for fmu, vr in zip(self.involved_fmu.values(), layout.profiling):
                port = EmbeddedFMUPort("real64", {"valueReference": vr,
                                        "name": f"container.{fmu.id}.rt_ratio",
                                        "description": f"RT ratio for embedded FMU '{fmu.name}'"})
                add_variable(port.xml(vr, fmi_version=self.fmi_version))

        nb_clocks = 0
        for link in self.links.values():
            if link.cport_from:
                add_variable(link.cport_from.port.xml(layout.links[link], name=link.name, causality='local',
                                                      fmi_version=self.fmi_version))
            else:
                # LS-BUS allow Clock generated by fmi-importer
                port = EmbeddedFMUPort("Clock",
                                       {"name": "", "valueReference": -1, "intervalVariability": "triggered"},
                                       fmi_version=3)
                add_variable(port.xml(layout.links[link], name=f"container.clock{nb_clocks}", causality='local',
                                      fmi_version=self.fmi_version))
                nb_clocks += 1

        for input_port_name, input_port in self.inputs.items():
            # Get Start and XML from first connected input
            start = self.start_values.get(input_port.cport_list[0], None)
            add_variable(input_port.cport_list[0].port.xml(layout.inputs[input_port_name], name=input_port_name,
                                                           start=start, fmi_version=self.fmi_version))

        outputs = []    # (value reference of a container output, its variable element), for <ModelStructure>
        for output_port_name, output_port in self.outputs.items():
            variable = add_variable(output_port.port.xml(layout.outputs[output_port_name], name=output_port_name,
                                                         fmi_version=self.fmi_version))
            if variable is not None:
                outputs.append((layout.outputs[output_port_name], variable))

        model_structure = ET.SubElement(root, "ModelStructure")
        if self.fmi_version == 2:
            # FMI-2 §2.2.8: <Unknown index> is the 1-based position of the variable in <ModelVariables>.
            positions = {id(variable): index for index, variable in enumerate(model_variables, start=1)}
            if outputs:
                for section in ("Outputs", "InitialUnknowns"):
                    unknowns = ET.SubElement(model_structure, section)
                    for _, variable in outputs:
                        ET.SubElement(unknowns, "Unknown", {"index": str(positions[id(variable)])})
        else:
            for tag in ("Output", "InitialUnknown"):
                for output_vr, _ in outputs:
                    ET.SubElement(model_structure, tag, {"valueReference": str(output_vr)})

        ModelDescription(root).save(xml_filename)

    def make_fmu_txt(self, txt_file, step_size: float, mt: bool, profiling: bool, sequential: bool,
                     layout: ContainerLayout):
        print("# Version 6", file=txt_file)
        print("# Container flags <MT> <Profiling> <Sequential>", file=txt_file)
        flags = [str(int(bool(flag))) for flag in (mt, profiling, sequential)]
        print(" ".join(flags), file=txt_file)

        print("# Internal time step in seconds", file=txt_file)
        print(f"{step_size}", file=txt_file)

        print("# NB of embedded FMU's", file=txt_file)
        fmu_rank = self.involved_fmu.write_txt(txt_file)


        # Prepare data structure
        inputs_per_type: dict[str, list[ContainerInput]] = defaultdict(list) # Container's INPUT
        outputs_per_type: dict[str, list[tuple[str, ContainerPort]]] = defaultdict(list) # Container's OUTPUT

        fmu_io_list = FMUIOList(layout.table)
        clock_list = ClockList(self.involved_fmu)

        local_per_type: dict[str, list[LocalVariable]] = defaultdict(list)
        links_per_fmu: dict[str, list[Link]] = defaultdict(list)

        # Fill data structure
        # Inputs
        for input_port_name, input_port in self.inputs.items():
            inputs_per_type[input_port.type_name].append(input_port)

        # Start values
        for input_port, value in self.start_values.items():
            fmu_io_list.add_start_value(input_port, value)

        # Outputs
        for output_port_name, output_port in self.outputs.items():
            outputs_per_type[output_port.port.type_name].append((output_port_name, output_port))

        # Links
        for link in self.links.values():
            # FMU Outputs
            if link.cport_from:
                local_per_type[link.cport_from.port.type_name].append(LocalVariable(layout.links[link], link.size))
                fmu_io_list.add_output(link.cport_from, layout.links[link])
            else:
                local_per_type["clock"].append(LocalVariable(layout.links[link], link.size))
                for cport_to in link.cport_to_list:
                    if cport_to.port.interval_variability == "countdown":
                        logger.info(f"LS-BUS: importer scheduling for '{cport_to.fmu.name}' '{cport_to.port.name}' (clock={cport_to.port.vr}, vr={layout.links[link]})")
                        clock_list.append(cport_to, layout.links[link])
                        break

            # Converted copies: one local variable per target type, whatever the number of targets of that type.
            for type_name in link.conversions:
                local_per_type[type_name].append(LocalVariable(layout.converted[link][type_name], link.size))
            if link.conversions:
                links_per_fmu[link.cport_from.fmu.name].append(link)

            # FMU Inputs
            for cport_to in link.cport_to_list:
                if link.cport_from is not None or not cport_to.fmu.ls.is_bus:
                    # LS-BUS allows, importer to feed clock signal. In this case, cport_from is None
                    # FMU will be fed directly by importer, no need to add input link!
                    if link.cport_from is None or cport_to.port.type_name == link.cport_from.port.type_name:
                        local_vr = layout.links[link]
                    else:
                        local_vr = layout.converted[link][cport_to.port.type_name]
                    fmu_io_list.add_input(cport_to, local_vr)

        print("# NB local variables:", ", ".join(ALL_TYPES), file=txt_file)
        nb_storage = [f"{layout.table.nb_storage(type_name)}" for type_name in ALL_TYPES]
        print(" ".join(nb_storage), file=txt_file, end='')
        print("", file=txt_file)

        print("# CONTAINER I/O: <VR> <DIM> <NB> <FMU_INDEX> <FMU_VR> [<FMU_INDEX> <FMU_VR>]", file=txt_file)
        for type_name in ALL_TYPES:
            print(f"# {type_name}" , file=txt_file)
            nb_local = (len(inputs_per_type[type_name]) +
                        len(outputs_per_type[type_name]) +
                        layout.table.nb_local(type_name))
            nb_input_link = 0
            for input_port in inputs_per_type[type_name]:
                nb_input_link += len(input_port.cport_list) - 1
            print(f"{nb_local} {nb_local + nb_input_link}", file=txt_file)
            # Reserved variables, stored locally: <FMU_INDEX> is -1 (-2 for profiling) and <FMU_VR> the local offset.
            if type_name == "real64":
                print(f"{layout.time} 1 1 -1 {layout.local_offset(layout.time)}", file=txt_file)
                for vr in layout.profiling:
                    print(f"{vr} 1 1 -2 {layout.local_offset(vr)}", file=txt_file)
            elif type_name == "integer32":
                for vr in (layout.ts_multiplier, layout.solver):
                    print(f"{vr} 1 1 -1 {layout.local_offset(vr)}", file=txt_file)

            for input_port in inputs_per_type[type_name]:
                cport_string = [f"{fmu_rank[cport.fmu.name]} {cport.port.vr}" for cport in input_port.cport_list]
                print(f"{layout.inputs[input_port.name]} {input_port.size} {len(input_port.cport_list)}",
                      " ".join(cport_string), file=txt_file)
            for output_port_name, output_port in outputs_per_type[type_name]:
                print(f"{layout.outputs[output_port_name]} {output_port.port.size()} 1 {fmu_rank[output_port.fmu.name]} "
                      f"{output_port.port.vr}", file=txt_file)
            offset_storage = 0
            for local_variable in local_per_type[type_name]:
                print(f"{local_variable.vr} {local_variable.dimension} 1 -1 "
                      f"{(local_variable.vr & 0xFFFFFF) + offset_storage}", file=txt_file)
                offset_storage += local_variable.dimension - 1
        # LINKS
        for fmu in self.involved_fmu.values():
            fmu_io_list.write_txt(fmu.name, txt_file)

            print(f"# Conversion table of {fmu.name}: <VR_FROM> <VR_TO> <CONVERSION>", file=txt_file)
            print(sum(len(link.conversions) for link in links_per_fmu[fmu.name]), file=txt_file)
            for link in links_per_fmu[fmu.name]:
                for type_name, conversion in link.conversions.items():
                    print(f"{layout.links[link]} {layout.converted[link][type_name]} {conversion}", file=txt_file)

        # CLOCKS
        clock_list.write_txt(txt_file)

    def make_datalog(self, datalog_file, layout: ContainerLayout):
        print("# Datalog filename", file=datalog_file)
        print(f"{self.identifier}-datalog.csv", file=datalog_file)

        ports = defaultdict(list)
        for input_port_name, input_port in self.inputs.items():
            ports[input_port.type_name].append(Port(layout.inputs[input_port_name], input_port_name))
        for output_port_name, output_port in self.outputs.items():
            ports[output_port.port.type_name].append(Port(layout.outputs[output_port_name], output_port_name))
        for link in self.links.values():
            if link.cport_from is None:
                # LS-BUS allows connected input clocks.
                ports[link.cport_to_list[0].port.type_name].append(Port(layout.links[link], link.name))
            else:
                ports[link.cport_from.port.type_name].append(Port(layout.links[link], link.name))

        for type_name in ALL_TYPES:
            print(f"# {type_name}: <VR> <NAME>" , file=datalog_file)
            print(f"{len(ports[type_name])}", file=datalog_file)
            for port in ports[type_name]:
                print(f"{port.vr} {port.name}", file=datalog_file)

    @staticmethod
    def long_path(path: str | Path) -> str:
        # https://stackoverflow.com/questions/14075465/copy-a-file-with-a-too-long-path-to-another-directory-in-python
        if os.name == 'nt':
            return "\\\\?\\" + os.path.abspath(str(path))
        else:
            return path

    @staticmethod
    def copyfile(origin, destination):
        logger.debug(f"Copying {origin} in {destination}")
        shutil.copy(origin, destination)

    def get_platforms(self) -> Generator[Platform, Any, None]:
        fmu_iter = iter(self.involved_fmu.values())
        try:
            fmu = next(fmu_iter)
        except StopIteration:
            raise FMUContainerError("No fmu declared in this container.")

        os_list = fmu.platforms
        logger.debug(f"FMU '{fmu.name}' OS support: {', '.join(fmu.platforms)}.")

        for fmu in fmu_iter:
            logger.debug(f"FMU '{fmu.name}' OS support: {', '.join(fmu.platforms)}.")
            os_list &= fmu.platforms

        suffixes = {
            "Windows": "dll",
            "Linux": "so",
            "Darwin": "dylib"
        }

        origin_bindirs = {
            "Windows": "win64",
            "Linux": "linux64",
            "Darwin": "darwin64"
        }

        if self.fmi_version == 3:
            target_bindirs = {
                "Windows": "x86_64-windows",
                "Linux": "x86_64-linux",
                "Darwin": "aarch64-darwin"
            }
        else:
            target_bindirs = origin_bindirs

        if os_list:
            logger.info(f"Container will be built for {', '.join(os_list)}.")
        else:
            logger.critical("No common OS found for embedded FMU. Try to re-run with '-debug'. Container won't be runnable.")

        for os_name in os_list:
            try:
                yield Platform(origin_bindirs[os_name], suffixes[os_name], target_bindirs[os_name])
            except KeyError:
                raise FMUContainerError(f"OS '{os_name}' is not supported.")

    def make_fmu_skeleton(self, base_directory: Path) -> Path:
        logger.debug(f"Initialize directory '{base_directory}'")

        origin = Path(__file__).parent.parent / "resources"  # resources of the toolbox package
        resources_directory = base_directory / "resources"
        documentation_directory = base_directory / "documentation"
        binaries_directory = base_directory / "binaries"

        base_directory.mkdir(exist_ok=True)
        resources_directory.mkdir(exist_ok=True)
        binaries_directory.mkdir(exist_ok=True)
        documentation_directory.mkdir(exist_ok=True)

        if self.description_pathname:
            self.copyfile(self.description_pathname, documentation_directory)

        # Model icon location depends on the FMI version:
        #   - FMI 3.0: terminalsAndIcons/icon.png
        #   - FMI 2.0: model.png at the FMU root
        if self.fmi_version == 3:
            terminals_and_icons_directory = base_directory / "terminalsAndIcons"
            terminals_and_icons_directory.mkdir(exist_ok=True)
            self.copyfile(origin / "fmucontainer.png", terminals_and_icons_directory / "icon.png")
        else:
            self.copyfile(origin / "fmucontainer.png", base_directory / "model.png")

        for platform in self.get_platforms():
            library_filename = origin / platform.origin_bindir / f"container.{platform.suffixe}"
            if library_filename.is_file():
                binary_directory = binaries_directory / platform.target_bindir
                binary_directory.mkdir(exist_ok=True)
                self.copyfile(library_filename, binary_directory / f"{self.identifier}.{platform.suffixe}")
            else:
                logger.critical(f"File {library_filename} not found.")

        for i, fmu in enumerate(self.involved_fmu.values()):
            with zipfile.ZipFile(fmu.fmu.fmu_filename) as zin:
                zin.extractall(self.long_path(resources_directory / f"{i:02x}"))

        return resources_directory

    def make_fmu_package(self, base_directory: Path, fmu_filename: Path):
        logger.debug(f"Zipping directory '{base_directory}' => '{fmu_filename}'")
        zip_directory = self.long_path(str(base_directory.absolute()))
        offset = len(zip_directory) + 1
        with zipfile.ZipFile(self.fmu_directory / fmu_filename, "w", zipfile.ZIP_DEFLATED) as zip_file:
            def add_file(directory: Path):
                for entry in directory.iterdir():
                    if entry.is_dir():
                        add_file(directory / entry)
                    elif entry.is_file():
                        zip_file.write(str(entry), str(entry)[offset:])

            add_file(Path(zip_directory))
        logger.info(f"'{fmu_filename}' is available.")

    def make_fmu_cleanup(self, base_directory: Path):
        logger.debug(f"Delete directory '{base_directory}'")
        shutil.rmtree(self.long_path(base_directory))
