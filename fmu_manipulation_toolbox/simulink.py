"""Export of an assembly to Simulink.

The export produces a MATLAB script that builds a Simulink model with native FMU blocks (library *Simulink Extras /
FMU Import*). This module first analyses the assembly into an intermediate model: systems (the root and one subsystem
per sub-container), blocks and lines with their port indices, in pure Python, so that it can be tested without
MATLAB. See `docs/local/simulink_export.md` (decisions 1 to 26).
"""
import logging
import math
import os
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .assembly import Assembly, AssemblyError, AssemblyNode, Port
from .container import FMUContainerError
from .container.builder import FMUContainer, deduce_step_size
from .container.embedded import EmbeddedFMU, EmbeddedFMUPort
from .terminals import TerminalError

logger = logging.getLogger("fmu_manipulation_toolbox")

#: Types of the ports that get no `Constant` block when they are not connected: they have no constant value.
NO_CONSTANT_TYPES = ("clock", "binary")

#: Longest MATLAB identifier (`namelengthmax`).
MATLAB_NAME_LENGTH = 63


# ----------------------------------------------------------------------------------------------- intermediate model
@dataclass
class SimulinkLine:
    """A line from an output port of a block to an input port of another block of the same system.

    The ports are numbered from 1, in the order of the block; `target_port` is `"Reset"` for the reset port of a
    resettable subsystem (decision 23).
    """
    source: str
    source_port: int | str
    target: str
    target_port: int | str


@dataclass
class StartValue:
    """A start value of the assembly (text, as stored by the assembly) and the type of its port."""
    value: str
    type_name: str


@dataclass
class FmuBlock:
    """An FMU block (`FMUInputMapping` / `FMUOutputMapping` = `Flat`): one port per input and per output variable,
    in the order of `modelDescription.xml`."""
    name: str
    fmu_file: str                       # file name: its folder is added to the MATLAB path (decision 28)
    fmi_version: int
    model_exchange: bool                # Model Exchange mode, otherwise Co-Simulation (decision 8)
    sample_time: float                  # `FMUSampleTime`: the step of its node (decision 17)
    inputs: list[str]
    outputs: list[str]
    parameters: dict[str, StartValue] = field(default_factory=dict)     # values of the block parameters
    input_starts: dict[str, StartValue] = field(default_factory=dict)   # start values of connected inputs
    resettable: bool = False            # placed in a resettable subsystem (decision 23)


@dataclass
class SubsystemBlock:
    """A subsystem: a sub-container of the assembly (decision 4)."""
    name: str
    system: "SimulinkSystem"


@dataclass
class InportBlock:
    name: str
    index: int


@dataclass
class OutportBlock:
    name: str
    index: int


@dataclass
class ConstantBlock:
    """The start value of an input that is not connected (decision 21)."""
    name: str
    value: StartValue


@dataclass
class TerminatorBlock:
    """The end of an output that is not connected, or of a dropped port (decision 22)."""
    name: str


Block = FmuBlock | SubsystemBlock | InportBlock | OutportBlock | ConstantBlock | TerminatorBlock


@dataclass
class SimulinkSystem:
    """The model or a subsystem: its blocks, its lines, and the names of its `Inport` and `Outport` blocks."""
    name: str
    sample_time: float
    blocks: dict[str, Block] = field(default_factory=dict)
    lines: list[SimulinkLine] = field(default_factory=list)
    inports: list[str] = field(default_factory=list)
    outports: list[str] = field(default_factory=list)
    #: Start value given to an `Inport` that is not connected in the parent: the one of its first target.
    inport_starts: dict[str, StartValue | None] = field(default_factory=dict)

    def unique_name(self, name: str) -> str:
        """`name`, or `name 2`, `name 3`... when a block of the system already has it."""
        candidate, rank = name, 1
        while candidate in self.blocks:
            rank += 1
            candidate = f"{name} {rank}"
        return candidate

    def add(self, block: Block) -> Block:
        self.blocks[block.name] = block
        return block


@dataclass
class SimulinkModel:
    """The Simulink model of an assembly."""
    name: str
    root: SimulinkSystem
    fixed_step: float                   # the exact GCD of the sample times of the FMU blocks (decision 18)
    start_time: float | None
    stop_time: float | None
    fmu_files: dict[str, Path]          # file name -> FMU file

    def systems(self):
        """The systems of the model, the root first, then the subsystems (depth first)."""
        stack = [self.root]
        while stack:
            system = stack.pop(0)
            yield system
            stack[:0] = [block.system for block in system.blocks.values() if isinstance(block, SubsystemBlock)]


# ------------------------------------------------------------------------------------------------------- helpers
def _exact(value: float) -> Fraction:
    """A step as a fraction, from its shortest decimal representation (`0.3` is 3/10)."""
    return Fraction(repr(float(value)))


def gcd_of_steps(steps: list[float]) -> float:
    """Greatest common divisor of steps, computed exactly: `0.02` and `0.05` give `0.01` (decision 18)."""
    fractions = [_exact(step) for step in steps]
    # gcd(a/b, c/d) = gcd(a, c) / lcm(b, d)
    return float(Fraction(math.gcd(*(f.numerator for f in fractions)), math.lcm(*(f.denominator for f in fractions))))


def matlab_name(name: str) -> str:
    """A valid MATLAB identifier made from `name` (decision 15): a letter first, then letters, digits or `_`, at most
    63 characters. `bouncing-ball.fmu` gives `bouncing_ball`."""
    identifier = re.sub(r"\W", "_", Path(name).stem, flags=re.ASCII)
    if not identifier or not identifier[0].isalpha():
        identifier = "model_" + identifier
    return identifier[:MATLAB_NAME_LENGTH]


def reset_input_name(fmu_name: str) -> str:
    """Name of the exposed reset of an FMU without explicit name, as the builder names it
    (`FMUContainer.reset_input_name`)."""
    return f"container.{Path(fmu_name).stem.lower()}.reset"


def block_name(name: str) -> str:
    """Name of the block of an embedded FMU or of a sub-container: its name without `.fmu`."""
    return name[:-4] if name.lower().endswith(".fmu") else name


# ------------------------------------------------------------------------------------------------------ analysis
class _NotAPort(AssemblyError):
    """A variable that the FMU block of Simulink has no port for: a parameter exposed as an input of the container,
    a local variable exposed as an output (decision 31)."""


@dataclass
class _Endpoint:
    """One end of a connection in a system: a block, the index of its port, and what the port is."""
    block: str
    port: int | str
    name: str                           # name of the port, for the messages
    type_name: str | None               # type of an FMU port, None for a subsystem port
    start: StartValue | None            # start value of an input, for a `Constant` block


class SimulinkExporter:
    """Analyse an assembly into a `SimulinkModel` (step 1 of `docs/local/simulink_export.md`).

    Args:
        assembly (Assembly): The assembly; its FMUs are read from `assembly.fmu_directory`.

    Raises:
        AssemblyError: If the assembly cannot be exported (see `analyse`).
    """

    def __init__(self, assembly: Assembly):
        if assembly.root is None:
            raise AssemblyError("The assembly is empty: nothing to export to Simulink.")
        self.assembly = assembly
        self.fmu_directory = Path(assembly.fmu_directory)
        self._analysed: dict[Path, EmbeddedFMU] = {}    # one analysis per FMU file, shared by its instances
        self.fmu_files: dict[str, Path] = {}
        self.sample_times: list[float] = []

    # --------------------------------------------------------------------------------------------- public API
    def analyse(self, name: str | None = None) -> SimulinkModel:
        """Build the intermediate model of the assembly.

        Args:
            name (str | None): Name of the model, by default made from the name of the container.

        Raises:
            AssemblyError: If a node uses `ts_multiplier` (decision 7), if a step cannot be found (decision 13), if a
                port does not exist or is used against its causality, or if an FMU cannot be read.
        """
        root = self.assembly.root
        assert root is not None     # checked by the constructor
        system = self._system(root)
        return SimulinkModel(name=name or matlab_name(root.name), root=system,
                             fixed_step=gcd_of_steps(self.sample_times),
                             start_time=root.start_time, stop_time=root.stop_time, fmu_files=self.fmu_files)

    def export(self, filename: str | Path) -> Path:
        """Write the MATLAB script that builds and saves the Simulink model (decisions 28, 30).

        Args:
            filename (str | Path): The `.m` script. Its stem names the MATLAB function and the model.

        Returns:
            Path: The script.

        Raises:
            AssemblyError: If the stem of `filename` is not a valid MATLAB identifier, if an FMU cannot be designated
                relatively to the script (another drive), or if the assembly cannot be exported (see `analyse`).
        """
        filename = Path(filename)
        if filename.suffix.lower() != ".m":
            filename = filename.with_suffix(".m")
        if not _identifier(filename.stem) or len(filename.stem) > MATLAB_NAME_LENGTH:
            raise AssemblyError(f"'{filename.name}': the name of a MATLAB script must be a valid MATLAB identifier "
                                f"(a letter, then letters, digits or '_', at most {MATLAB_NAME_LENGTH} characters).")
        model = self.analyse(filename.stem)
        directory = filename.resolve().parent
        folders = []
        for path in model.fmu_files.values():
            try:
                folder = Path(os.path.relpath(path.parent, directory)).as_posix()
            except ValueError:      # another drive (Windows): no relative path
                raise AssemblyError(f"'{path}' cannot be designated relatively to '{filename.name}' (another "
                                    f"drive): write the script on the drive of the FMUs.") from None
            if folder not in folders:
                folders.append(folder)
        assert self.assembly.root is not None
        filename.write_text(MatlabWriter(model, folders, self.assembly.root.name).render(), encoding="utf-8")
        logger.info(f"Simulink model '{model.name}': MATLAB script '{filename}' written.")
        return filename

    # ------------------------------------------------------------------------------------------------- nodes
    def _check_options(self, node: AssemblyNode):
        """Refuse `ts_multiplier`, warn about the options that the export ignores (decisions 5, 7, 10, 26)."""
        if node.ts_multiplier:
            raise AssemblyError(f"'{node.name}': the option ts_multiplier cannot be exported to Simulink.")
        for option in ("mt", "profiling", "sequential"):
            if getattr(node, option):
                logger.warning(f"'{node.name}': the option {option} is ignored by the Simulink export.")
        implicit = [option for option in ("auto_link", "auto_input", "auto_output", "auto_parameter", "auto_local")
                    if getattr(node, option)]
        if implicit and not node.implicit_resolved:
            logger.warning(f"'{node.name}': the implicit links and ports ({', '.join(implicit)}) are not exported to "
                           f"Simulink: only the explicit ones are.")

    def _embedded(self, node: AssemblyNode, fmu_name: str) -> EmbeddedFMU:
        """The analysis of an embedded FMU, shared by the instances of its file; its file is added to the archive."""
        path = (self.fmu_directory / node.fmu_path(fmu_name)).resolve()
        if path not in self._analysed:
            try:
                self._analysed[path] = EmbeddedFMU(path)
            except (FMUContainerError, OSError) as error:
                raise AssemblyError(f"Cannot read '{node.fmu_path(fmu_name)}': {error}") from error
            if path.name in self.fmu_files:
                raise AssemblyError(f"'{self.fmu_files[path.name]}' and '{path}' have the same file name: the FMU "
                                    f"block of Simulink designates an FMU by its file name only (decision 28).")
            self.fmu_files[path.name] = path
        return self._analysed[path]

    @staticmethod
    def _file_name(fmu: EmbeddedFMU) -> str:
        return Path(fmu.fmu.fmu_filename).name

    def _step(self, node: AssemblyNode, fmus: dict[str, EmbeddedFMU], children: dict[str, SimulinkSystem]) -> float:
        """Step of the node (decision 17): its `step_size`, otherwise deduced as `make_fmu` does (decision 13)."""
        if node.step_size:
            return node.step_size
        steps = [(fmu.step_size, not fmu.imposes_step_size) for fmu in fmus.values() if fmu.step_size]
        steps += [(child.sample_time, True) for child in children.values()]
        step = deduce_step_size(steps)
        if step is None:
            raise AssemblyError(f"'{node.name}': no step size, neither in the assembly nor in its FMUs.")
        return step

    def _system(self, node: AssemblyNode) -> SimulinkSystem:
        """The system of a node, its sub-containers first."""
        self._check_options(node)
        children = {name: self._system(child) for name, child in node.children.items()}
        fmus = {name: self._embedded(node, name) for name in node.fmu_names_list}
        system = SimulinkSystem(block_name(node.name), self._step(node, fmus, children))
        self.sample_times.append(system.sample_time)

        # Blocks of the embedded FMUs and of the sub-containers
        names: dict[str, str] = {}      # name in the assembly -> name of the block
        for name, fmu in fmus.items():
            ports = [port for port in fmu.ports.values() if not port.is_fmi2_aggregate]
            names[name] = system.unique_name(block_name(name))
            system.add(FmuBlock(names[name], self._file_name(fmu), fmu.fmi_version or 0, fmu.is_me, system.sample_time,
                                inputs=[port.name for port in ports if port.causality == "input"],
                                outputs=[port.name for port in ports if port.causality == "output"]))
        for name, child in children.items():
            names[name] = system.unique_name(block_name(name))
            system.add(SubsystemBlock(names[name], child))

        connected_inputs: set[tuple[str, int | str]] = set()
        connected_outputs: set[tuple[str, int | str]] = set()

        def endpoint(port: Port, direction: str) -> _Endpoint:
            return self._endpoint(node, fmus, children, names, port, direction)

        def connect(source: _Endpoint, target: _Endpoint):
            system.lines.append(SimulinkLine(source.block, source.port, target.block, target.port))
            connected_outputs.add((source.block, source.port))
            connected_inputs.add((target.block, target.port))

        # Exposed inputs: one Inport per name, a line to each of its targets (decision 4)
        inports: dict[str, str] = {}
        for port, exposed in node.input_ports.items():
            try:
                target = endpoint(port, "input")
            except _NotAPort as error:
                logger.warning(str(error))
                continue
            exposed = exposed or (reset_input_name(port.fmu_name) if target.port == "Reset" else port.port_name)
            if exposed not in inports:
                inports[exposed] = system.unique_name(exposed)
                system.add(InportBlock(inports[exposed], len(system.inports) + 1))
                system.inports.append(exposed)
                system.inport_starts[exposed] = target.start
            system.lines.append(SimulinkLine(inports[exposed], 1, target.block, target.port))
            connected_inputs.add((target.block, target.port))

        # Links, the terminals expanded as the builder does (decision 24)
        for link in node.links:
            for from_port, to_port in self._expand(node, fmus, link.from_port, link.to_port):
                self._check_input_clocks(node, fmus, from_port, to_port)
                source, target = endpoint(from_port, "output"), endpoint(to_port, "input")
                connect(source, target)

        # Exposed outputs
        for port, exposed in node.output_ports.items():
            try:
                source = endpoint(port, "output")
            except _NotAPort as error:
                logger.warning(str(error))
                continue
            exposed = exposed or port.port_name
            name = system.unique_name(exposed)
            system.add(OutportBlock(name, len(system.outports) + 1))
            system.outports.append(exposed)
            system.lines.append(SimulinkLine(source.block, source.port, name, 1))
            connected_outputs.add((source.block, source.port))

        # Dropped ports: a Terminator (decision 22)
        for port in node.drop_ports:
            source = endpoint(port, "output")
            if (source.block, source.port) not in connected_outputs:
                self._terminate(system, source, connected_outputs)

        self._start_values(node, fmus, children, names, system, endpoint, connected_inputs)
        self._resets(node, fmus, names, system, connected_inputs)
        self._unconnected(node, fmus, children, names, system, connected_inputs, connected_outputs)
        return system

    # ------------------------------------------------------------------------------------------------- ports
    def _endpoint(self, node: AssemblyNode, fmus: dict[str, EmbeddedFMU], children: dict[str, SimulinkSystem],
                  names: dict[str, str], port: Port, direction: str) -> _Endpoint:
        """The block and the port index of `port`, used as an `input` or an `output` of a connection."""
        if port.fmu_name in fmus:
            fmu = fmus[port.fmu_name]
            node_block = names[port.fmu_name]
            if direction == "input" and node.reset_ports and port.port_name == FMUContainer.RESET_PORT:
                return _Endpoint(node_block, "Reset", port.port_name, "boolean", None)
            fmu_port = fmu.ports.get(port.port_name)
            if fmu_port is None or fmu_port.is_fmi2_aggregate:
                raise AssemblyError(f"'{node.name}': port '{port}' does not exist.")
            if fmu_port.causality != direction and \
                    fmu_port.causality in ("parameter", "structuralParameter", "local", "calculatedParameter"):
                raise _NotAPort(f"'{node.name}': '{port}' is a {fmu_port.causality}: the FMU block of Simulink has no "
                                f"port for it, it is not exposed.")
            if fmu_port.causality != direction:
                raise AssemblyError(f"'{node.name}': port '{port}' has the causality '{fmu_port.causality}': it "
                                    f"cannot be used as an {direction}.")
            ports = [p for p in fmu.ports.values() if not p.is_fmi2_aggregate and p.causality == direction]
            index = next(i for i, p in enumerate(ports, start=1) if p.name == port.port_name)
            start = self._fmu_start(node, port, fmu_port) if direction == "input" else None
            return _Endpoint(node_block, index, str(port), fmu_port.type_name, start)
        if port.fmu_name in children:
            child = children[port.fmu_name]
            exposed = child.inports if direction == "input" else child.outports
            if port.port_name not in exposed:
                raise AssemblyError(f"'{node.name}': port '{port}' is not an {direction} of the sub-container.")
            start = child.inport_starts.get(port.port_name) if direction == "input" else None
            return _Endpoint(names[port.fmu_name], exposed.index(port.port_name) + 1, str(port), None, start)
        raise AssemblyError(f"'{node.name}': '{port.fmu_name}' is neither an FMU nor a sub-container of the node.")

    @staticmethod
    def _fmu_start(node: AssemblyNode, port: Port, fmu_port: EmbeddedFMUPort) -> StartValue | None:
        """Start value of an FMU input: the one of the assembly, otherwise the one of the FMU."""
        value = node.start_values.get(port, fmu_port.start_value)
        return None if value is None else StartValue(str(value), fmu_port.type_name)

    def _expand(self, node: AssemblyNode, fmus: dict[str, EmbeddedFMU], from_port: Port, to_port: Port):
        """The port-to-port links of a link: itself, or the links of two connected terminals (decision 24)."""
        fmu_from, fmu_to = fmus.get(from_port.fmu_name), fmus.get(to_port.fmu_name)
        if fmu_from is None or fmu_to is None or from_port.port_name not in fmu_from.terminals \
                or to_port.port_name not in fmu_to.terminals:
            return [self._oriented(fmus, from_port, to_port)]
        terminal1, terminal2 = fmu_from.terminals[from_port.port_name], fmu_to.terminals[to_port.port_name]
        if not terminal1 == terminal2:
            raise AssemblyError(f"'{node.name}': the terminals '{from_port}' and '{to_port}' are not compatible.")
        try:
            pairs = terminal1.connect(terminal2)
        except TerminalError as error:
            raise AssemblyError(f"'{node.name}': cannot plug the terminals '{from_port}' and '{to_port}': "
                                f"{error}") from error
        self._terminal_parameters(node, fmus, from_port.fmu_name, to_port.fmu_name,
                                  terminal1.connected_parameters(terminal2))
        return [self._oriented(fmus, Port(from_port.fmu_name, a), Port(to_port.fmu_name, b)) for a, b in pairs]

    @staticmethod
    def _oriented(fmus: dict[str, EmbeddedFMU], from_port: Port, to_port: Port) -> tuple[Port, Port]:
        """A link from an output to an input: inverted when it goes from an input to an output, as the builder
        accepts."""
        def causality(port: Port) -> str | None:
            fmu = fmus.get(port.fmu_name)
            fmu_port = fmu.ports.get(port.port_name) if fmu else None
            return fmu_port.causality if fmu_port else None
        if causality(from_port) == "input" and causality(to_port) == "output":
            return to_port, from_port
        return from_port, to_port

    @staticmethod
    def _check_input_clocks(node: AssemblyNode, fmus: dict[str, EmbeddedFMU], from_port: Port, to_port: Port):
        """Refuse a link between two input clocks (FMI-LS-BUS): the container schedules them without source, a line
        of Simulink goes from an output to an input (decision 27)."""
        ports = [fmus[port.fmu_name].ports.get(port.port_name) if port.fmu_name in fmus else None
                 for port in (from_port, to_port)]
        if all(port is not None and port.causality == "input" and port.type_name == "clock" for port in ports):
            raise AssemblyError(f"'{node.name}': the input clocks '{from_port}' and '{to_port}' are linked together: "
                                f"such a link cannot be exported to Simulink.")

    @staticmethod
    def _terminal_parameters(node: AssemblyNode, fmus: dict[str, EmbeddedFMU], fmu1: str, fmu2: str, pairs):
        """The parameters of a Configuration terminal take the value of the connected Bus Simulation, as the
        builder does (`apply_terminal_parameters`), unless the assembly gives them a start value."""
        for name1, name2 in pairs:
            port1, port2 = fmus[fmu1].ports[name1], fmus[fmu2].ports[name2]
            if port1.causality == "parameter" and port2.causality != "parameter":
                target, source = Port(fmu1, name1), port2
            elif port2.causality == "parameter" and port1.causality != "parameter":
                target, source = Port(fmu2, name2), port1
            else:
                continue
            if target not in node.start_values and source.start_value is not None:
                node.start_values[target] = source.start_value

    # ---------------------------------------------------------------------------------------- extra blocks
    @staticmethod
    def _terminate(system: SimulinkSystem, source: _Endpoint, connected_outputs: set):
        name = system.unique_name(f"{source.block}.{source.name.split('/', 1)[-1]} end")
        system.add(TerminatorBlock(name))
        system.lines.append(SimulinkLine(source.block, source.port, name, 1))
        connected_outputs.add((source.block, source.port))

    def _start_values(self, node: AssemblyNode, fmus: dict[str, EmbeddedFMU], children: dict[str, SimulinkSystem],
                      names: dict[str, str], system: SimulinkSystem, endpoint, connected_inputs: set):
        """Start values of the assembly: values of the block parameters, start values of the connected inputs; those
        of the unconnected inputs go to their `Constant` block (decision 21)."""
        for port, value in node.start_values.items():
            if port.fmu_name in children:
                continue    # an input of a sub-container: its Constant block, when it is not connected
            fmu = fmus.get(port.fmu_name)
            fmu_port = fmu.ports.get(port.port_name) if fmu else None
            if fmu_port is None:
                raise AssemblyError(f"'{node.name}': the start value of '{port}' is given to a port that does not "
                                    f"exist.")
            block = system.blocks[names[port.fmu_name]]
            assert isinstance(block, FmuBlock)
            if fmu_port.causality in ("parameter", "structuralParameter"):
                block.parameters[port.port_name] = StartValue(str(value), fmu_port.type_name)
            elif fmu_port.causality == "input":
                target = endpoint(port, "input")
                if (target.block, target.port) in connected_inputs:
                    block.input_starts[port.port_name] = StartValue(str(value), fmu_port.type_name)
            else:
                logger.warning(f"'{node.name}': the start value of '{port}' ({fmu_port.causality}) is not exported "
                               f"to Simulink.")

    @staticmethod
    def _resets(node: AssemblyNode, fmus: dict[str, EmbeddedFMU], names: dict[str, str], system: SimulinkSystem,
                connected_inputs: set):
        """`reset_ports`: an FMU whose reset is driven is placed in a resettable subsystem (decision 23)."""
        if not node.reset_ports:
            return
        for name in fmus:
            block = system.blocks[names[name]]
            assert isinstance(block, FmuBlock)
            if (block.name, "Reset") in connected_inputs:
                block.resettable = True
            else:
                logger.warning(f"Reset of FMU '{name}' is neither linked nor exposed: the FMU will never be reset.")

    def _unconnected(self, node: AssemblyNode, fmus: dict[str, EmbeddedFMU], children: dict[str, SimulinkSystem],
                     names: dict[str, str], system: SimulinkSystem, connected_inputs: set, connected_outputs: set):
        """A `Constant` block on each unconnected input, a `Terminator` on each unconnected output (decisions 21,
        22)."""
        for name in [*fmus, *children]:
            block = system.blocks[names[name]]
            if isinstance(block, FmuBlock):
                fmu = fmus[name]
                inputs = [(index, fmu.ports[port]) for index, port in enumerate(block.inputs, start=1)]
                for index, fmu_port in inputs:
                    if (block.name, index) in connected_inputs or fmu_port.type_name in NO_CONSTANT_TYPES:
                        continue
                    start = self._fmu_start(node, Port(name, fmu_port.name), fmu_port)
                    self._constant(system, block.name, index, fmu_port.name,
                                   start or StartValue("0", fmu_port.type_name))
                outputs = block.outputs
            else:
                assert isinstance(block, SubsystemBlock)
                child = block.system
                for index, exposed in enumerate(child.inports, start=1):
                    if (block.name, index) in connected_inputs:
                        continue
                    inner = child.inport_starts.get(exposed)
                    given = node.start_values.get(Port(name, exposed))
                    value = inner if given is None else StartValue(str(given), inner.type_name if inner else "real64")
                    if value is not None and value.type_name not in NO_CONSTANT_TYPES:
                        self._constant(system, block.name, index, exposed, value)
                outputs = child.outports
            for index, port_name in enumerate(outputs, start=1):
                if (block.name, index) not in connected_outputs:
                    self._terminate(system, _Endpoint(block.name, index, port_name, None, None), connected_outputs)

    @staticmethod
    def _constant(system: SimulinkSystem, block: str, index: int, port_name: str, value: StartValue):
        name = system.unique_name(f"{block}.{port_name} start")
        system.add(ConstantBlock(name, value))
        system.lines.append(SimulinkLine(name, 1, block, index))


# --------------------------------------------------------------------------------------------- MATLAB script
#: Names of the Simulink API. Those that the MathWorks documentation does not give, or that were not seen on R2024b,
#: are marked `UNVERIFIED`: the statements that use them carry a `% UNVERIFIED` comment in the script, to be checked
#: by the manual validation (step 6).
FMU_LIBRARY = "simulink_extras/FMU Import/FMU"     # verified on R2024b, after load_system('simulink_extras')
FMU_LIBRARY_SYSTEM = "simulink_extras"
RESET_PORT_BLOCK = "built-in/ResetPort"             # UNVERIFIED
RESET_TRIGGER = ("ResetTriggerType", "level")       # UNVERIFIED (decision 23)
PRELOAD_CALLBACK = "PreLoadFcn"                     # UNVERIFIED in this use (decision 20)

#: Simulink data type of the `Constant` blocks, by container type.
SIMULINK_TYPES = {
    "real64": "double", "real32": "single",
    "integer8": "int8", "uinteger8": "uint8", "integer16": "int16", "uinteger16": "uint16",
    "integer32": "int32", "uinteger32": "uint32", "integer64": "int64", "uinteger64": "uint64",
    "boolean": "boolean", "boolean1": "boolean",
    "string": "string",
}

UNVERIFIED = "  % UNVERIFIED"


def matlab_string(text: str) -> str:
    """A MATLAB character vector: `it's` gives `'it''s'`."""
    return "'" + text.replace("'", "''") + "'"


def block_path_part(name: str) -> str:
    """A block name in a Simulink path: `/` is written `//`."""
    return name.replace("/", "//")


def matlab_number(value: float) -> str:
    """A number as MATLAB reads it: the shortest representation, `0.1` stays `0.1`."""
    return repr(float(value))


def render_value(start: StartValue, context: str) -> str:
    """The text of a start value for `set_param`, according to the type of its port.

    `context` is `"parameter"` (value of a block parameter: a Boolean is `on` / `off`, as R2024b requires, a String is
    raw text) or `"constant"` (value of a `Constant` block: a MATLAB expression).

    Raises:
        AssemblyError: If the value does not match the type of its port.
    """
    value, type_name = start.value.strip(), start.type_name
    if type_name in ("boolean", "boolean1"):
        truth = value.lower()
        if truth in ("1", "true", "on"):
            flag = True
        elif truth in ("0", "false", "off"):
            flag = False
        else:
            raise AssemblyError(f"'{start.value}' is not a Boolean value.")
        if context == "parameter":
            return "on" if flag else "off"
        return "true" if flag else "false"
    if type_name == "string":
        return start.value if context == "parameter" else '"' + start.value.replace('"', '""') + '"'
    try:
        number = float(value)
    except ValueError:
        raise AssemblyError(f"'{start.value}' is not a number.") from None
    if type_name.startswith(("integer", "uinteger")):
        if number != int(number):
            raise AssemblyError(f"'{start.value}' is not an integer.")
        return str(int(number))
    return matlab_number(number)


def _identifier(name: str) -> bool:
    return re.fullmatch(r"[A-Za-z]\w*", name, flags=re.ASCII) is not None


class MatlabWriter:
    """Render a `SimulinkModel` as a MATLAB function that builds and saves the model (step 2).

    Args:
        model (SimulinkModel): The model.
        fmu_folders (list[str]): Folders of the FMUs, relative to the folder of the script, added to the MATLAB path
            (decision 28).
        description (str): Name of the assembly, for the comment of the function.
    """

    #: Size of the blocks, and space between them, in pixels.
    WIDTH, ROW, GAP, COLUMN = 120, 20, 40, 220

    def __init__(self, model: SimulinkModel, fmu_folders: list[str], description: str = ""):
        self.model = model
        self.fmu_folders = fmu_folders
        self.description = description
        self.lines: list[str] = []

    def render(self) -> str:
        model = self.model
        self.lines = [
            f"function model = {model.name}()",
            f"%{model.name.upper()} Build and save the Simulink model of the assembly "
            f"'{self.description or model.name}'.",
            "%   Generated by the FMU Manipulation Toolbox. Run it in MATLAB R2024a or newer: it builds the model with",
            f"%   FMU blocks and saves it as {model.name}.slx next to this script. The FMUs stay in their folders,",
            "%   relative to this script.",
            "",
            "here = fileparts(mfilename('fullpath'));",
        ]
        for folder in self.fmu_folders:
            self.lines.append(f"addpath({self._folder('here', folder)});")
        self.lines += [
            f"load_system({matlab_string(FMU_LIBRARY_SYSTEM)});",
            f"model = {matlab_string(model.name)};",
            "if bdIsLoaded(model)",
            "    close_system(model, 0);",
            "end",
            "new_system(model);",
        ]
        settings = [("SolverType", "Fixed-step"), ("FixedStep", matlab_number(model.fixed_step)),
                    ("EnableMultiTasking", "off"), ("BlockReduction", "off")]
        if model.start_time is not None:
            settings.append(("StartTime", matlab_number(model.start_time)))
        if model.stop_time is not None:
            settings.append(("StopTime", matlab_number(model.stop_time)))
        self._set_param("model", settings)
        preload = " ".join(f"addpath({self._folder('here', folder)});" for folder in self.fmu_folders)
        if preload:
            callback = f"here = fileparts(get_param(bdroot, 'FileName')); {preload}"
            self.lines.append(f"set_param(model, {matlab_string(PRELOAD_CALLBACK)}, "
                              f"{matlab_string(callback)});{UNVERIFIED}")
        self._system(model.root, "model")
        self.lines += [
            "save_system(model, fullfile(here, [model '.slx']));",
            "end",
            "",
        ]
        return "\n".join(self.lines)

    # ---------------------------------------------------------------------------------------------- helpers
    @staticmethod
    def _folder(base: str, folder: str) -> str:
        """A folder relative to `base` (the folder of the script or of the model), as a MATLAB expression."""
        if folder in ("", "."):
            return base
        return f"fullfile({base}, {', '.join(matlab_string(part) for part in Path(folder).parts)})"

    def _set_param(self, path: str, settings: list[tuple[str, str]], comment: str = ""):
        if settings:
            arguments = ", ".join(f"{matlab_string(name)}, {matlab_string(value)}" for name, value in settings)
            self.lines.append(f"set_param({path}, {arguments});{comment}")

    @staticmethod
    def _path(system: str, name: str) -> str:
        return f"[{system} {matlab_string('/' + block_path_part(name))}]"

    def _add_block(self, library: str, system: str, name: str, position: list[int], comment: str = "") -> str:
        path = self._path(system, name)
        position_text = "[" + " ".join(str(value) for value in position) + "]"
        self.lines.append(f"add_block({matlab_string(library)}, {path}, 'Position', {position_text});{comment}")
        return path

    # ------------------------------------------------------------------------------------------------ systems
    def _system(self, system: SimulinkSystem, path: str):
        """The blocks and the lines of a system, `path` being a MATLAB expression of its path."""
        self.lines += ["", f"% System '{system.name}'"]
        rows = {"inport": 0, "constant": 0, "block": 0, "outport": 0, "terminator": 0}
        columns = {"inport": 0, "constant": 0, "block": 1, "outport": 2, "terminator": 2}
        subsystems = []
        for block in system.blocks.values():
            kind = ("inport" if isinstance(block, InportBlock) else "constant" if isinstance(block, ConstantBlock)
                    else "outport" if isinstance(block, OutportBlock) else "terminator"
                    if isinstance(block, TerminatorBlock) else "block")
            ports = max(len(block.inputs), len(block.outputs)) if isinstance(block, FmuBlock) else \
                max(len(block.system.inports), len(block.system.outports)) if isinstance(block, SubsystemBlock) else 1
            height = max(1, ports) * self.ROW + self.ROW
            x = self.GAP + columns[kind] * (self.WIDTH + self.COLUMN)
            y = self.GAP + rows[kind]
            rows[kind] += height + self.GAP
            position = [x, y, x + self.WIDTH, y + height]
            if isinstance(block, FmuBlock):
                self._fmu_block(block, path, position)
            elif isinstance(block, SubsystemBlock):
                subsystems.append((block, self._add_block("built-in/Subsystem", path, block.name, position)))
            elif isinstance(block, InportBlock):
                block_path = self._add_block("built-in/Inport", path, block.name, position)
                self._set_param(block_path, [("Port", str(block.index))])
            elif isinstance(block, OutportBlock):
                block_path = self._add_block("built-in/Outport", path, block.name, position)
                self._set_param(block_path, [("Port", str(block.index))])
            elif isinstance(block, ConstantBlock):
                block_path = self._add_block("built-in/Constant", path, block.name, position)
                try:
                    value = render_value(block.value, "constant")
                except AssemblyError as error:
                    raise AssemblyError(f"'{system.name}': '{block.name}': {error}") from error
                self._set_param(block_path, [("Value", value),
                                             ("OutDataTypeStr", SIMULINK_TYPES.get(block.value.type_name, "double")),
                                             ("SampleTime", "inf")])
            else:
                self._add_block("built-in/Terminator", path, block.name, position)
        # The ports of the subsystems exist before the lines of their parent
        for block, block_path in subsystems:
            self.lines.append(f"Simulink.SubSystem.deleteContents({block_path});")
            self._system(block.system, block_path)
        self.lines += ["", f"% Lines of '{system.name}'"]
        for line in system.lines:
            target = f"{block_path_part(line.target)}/{line.target_port}"
            comment = UNVERIFIED if line.target_port == "Reset" else ""
            source = f"{block_path_part(line.source)}/{line.source_port}"
            self.lines.append(f"add_line({path}, {matlab_string(source)}, {matlab_string(target)}, "
                              f"'autorouting', 'on');{comment}")

    def _fmu_block(self, block: FmuBlock, system: str, position: list[int]):
        """An FMU block; in a resettable subsystem when its reset is driven (decision 23)."""
        if block.resettable:
            wrapper = self._add_block("built-in/Subsystem", system, block.name, position)
            self.lines.append(f"Simulink.SubSystem.deleteContents({wrapper});")
            reset = self._add_block(RESET_PORT_BLOCK, wrapper, "Reset", [20, 20, 50, 40], UNVERIFIED)
            self._set_param(reset, [RESET_TRIGGER], UNVERIFIED)
            inner_position = [200, 60, 200 + self.WIDTH, position[3] - position[1] + 60]
            self._fmu("FMU", block, wrapper, inner_position)
            for index, name in enumerate(block.inputs, start=1):
                port = self._add_block("built-in/Inport", wrapper, name, [40, 60 + 40 * index, 70, 74 + 40 * index])
                self._set_param(port, [("Port", str(index))])
                self.lines.append(f"add_line({wrapper}, {matlab_string(f'{block_path_part(name)}/1')}, "
                                  f"{matlab_string(f'FMU/{index}')}, 'autorouting', 'on');")
            for index, name in enumerate(block.outputs, start=1):
                port = self._add_block("built-in/Outport", wrapper, name, [460, 60 + 40 * index, 490, 74 + 40 * index])
                self._set_param(port, [("Port", str(index))])
            for index, name in enumerate(block.outputs, start=1):
                self.lines.append(f"add_line({wrapper}, {matlab_string(f'FMU/{index}')}, "
                                  f"{matlab_string(f'{block_path_part(name)}/1')}, 'autorouting', 'on');")
        else:
            self._fmu(block.name, block, system, position)

    def _fmu(self, name: str, block: FmuBlock, system: str, position: list[int]):
        path = self._add_block(FMU_LIBRARY, system, name, position)
        self._set_param(path, [("FMUName", block.fmu_file), ("FMUInputMapping", "Flat"),
                               ("FMUOutputMapping", "Flat"), ("FMUSampleTime", matlab_number(block.sample_time))])
        for variable, start in block.parameters.items():
            self._variable(path, block, variable, start, "parameter")
        for variable, start in block.input_starts.items():
            self._variable(path, block, variable, start, "input")

    def _variable(self, path: str, block: FmuBlock, variable: str, start: StartValue, kind: str):
        """The value of a parameter (verified on R2024b for simple names), or the start value of a connected input
        (no programmatic name known: decision 3)."""
        try:
            value = render_value(start, "parameter")
        except AssemblyError as error:
            raise AssemblyError(f"'{block.name}': '{variable}': {error}") from error
        comment = UNVERIFIED if kind == "input" or not _identifier(variable) else ""
        self._set_param(path, [(variable, value)], comment)
