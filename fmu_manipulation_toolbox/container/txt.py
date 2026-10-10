"""Writers of `container.txt`, the configuration of the container runtime."""

import logging
from collections import OrderedDict, defaultdict
from typing import IO

from .embedded import EmbeddedFMU
from .layout import ValueReferenceTable
from .rules import ContainerPort
from .types import ALL_TYPES, START_VALUE_TYPES


logger = logging.getLogger("fmu_manipulation_toolbox")


class IOReference:
    def __init__(self, local_offset: int, dim: int, fmu_vr: int):
        self.local_offset = local_offset
        self.dim = dim
        self.fmu_vr = fmu_vr


class FMUIOList:
    """Tracks the I/O mapping between the container and its embedded FMUs.

    Organizes inputs, outputs, and start values by type and FMU, supporting
    both regular and clocked variables. Used to generate the `container.txt`
    runtime configuration file.

    Attributes:
        vr_table (ValueReferenceTable): Reference table for VR lookups.
        inputs: Nested mapping `[type][fmu_name][clock_vr]` → list of
            `(fmu_vr, local_vr)` tuples.
        outputs: Nested mapping `[type][fmu_name][clock_vr]` → list of
            `(fmu_vr, local_vr)` tuples.
        start_values: Mapping `[type][fmu_name]` → list of
            `(fmu_vr, reset, value)` tuples.
    """

    def __init__(self, vr_table: ValueReferenceTable):
        self.vr_table = vr_table
        self.inputs = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # [type][fmu][clock_vr][(fmu_vr, dim, vr])
        self.nb_clocked_inputs = defaultdict(lambda: defaultdict(lambda: 0))
        self.outputs = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # [type][fmu][clock_vr][(fmu_vr, dim, vr])
        self.nb_clocked_outputs = defaultdict(lambda: defaultdict(lambda: 0))
        self.start_values = defaultdict(lambda: defaultdict(list)) # [type][fmu][(cport, value)]

    def add_input(self, cport: ContainerPort, local_vr: int):
        """Register an input mapping for an embedded FMU port.

        Args:
            cport (ContainerPort): The embedded FMU input port.
            local_vr (int): The local value reference in the container.
        """
        if cport.port.clock is None:
            clock = None
        else:
            try:
                clock = self.vr_table.get_local_clock(cport)
            except KeyError:
                logger.error(f"Cannot expose clocked input: {cport}")
                return
            self.nb_clocked_inputs[cport.port.type_name][cport.fmu.name] += 1

        dim = cport.port.size()
        local_offset = self.vr_table.vr_to_local[local_vr]
        fmu_vr = cport.port.vr

        if dim > 1 and cport.fmu.fmi_version == 2:
            for k in range(dim):
                self.inputs[cport.port.type_name][cport.fmu.name][clock].append(
                    IOReference(local_offset + k, 1, fmu_vr + k))
        else:
            self.inputs[cport.port.type_name][cport.fmu.name][clock].append(
                IOReference(local_offset, dim, fmu_vr))

    def add_output(self, cport: ContainerPort, local_vr: int):
        """Register an output mapping for an embedded FMU port.

        Args:
            cport (ContainerPort): The embedded FMU output port.
            local_vr (int): The local value reference in the container.
        """
        if cport.port.clock is None:
            clock = None
        else:
            try:
                clock = self.vr_table.get_local_clock(cport)
            except KeyError:
                logger.error(f"Cannot expose clocked output: {cport}")
                return
            self.nb_clocked_outputs[cport.port.type_name][cport.fmu.name] += 1

        dim = cport.port.size()
        local_offset = self.vr_table.vr_to_local[local_vr]
        fmu_vr = cport.port.vr

        if dim > 1 and cport.fmu.fmi_version == 2:
            for k in range(dim):
                self.outputs[cport.port.type_name][cport.fmu.name][clock].append(
                    IOReference(local_offset + k, 1, fmu_vr + k))
        else:
            self.outputs[cport.port.type_name][cport.fmu.name][clock].append(
                IOReference(local_offset, dim, fmu_vr))


    def add_start_value(self, cport: ContainerPort, value: str):
        """Register a start value for an embedded FMU port.

        Args:
            cport (ContainerPort): The embedded FMU port.
            value (str): The start value.
        """
        reset = 1 if cport.port.causality == "input" else 0
        if cport.port.type_name.startswith("boolean"):
            if value == "true" or value == "1":
                value = "1"
            else:
                value = "0"

        fmu_vr = cport.port.vr
        dim = cport.port.size()
        if dim > 1 and cport.fmu.fmi_version == 2:
            tokens = str(value).split(' ')
            if len(tokens) == 1:
                tokens = tokens * dim
            for k, token in zip(range(dim), tokens):
                self.start_values[cport.port.type_name][cport.fmu.name].append(
                    (fmu_vr + k, 1, reset, token))
        else:
            self.start_values[cport.port.type_name][cport.fmu.name].append(
                (fmu_vr, cport.port.size(), reset, value))

    def write_txt(self, fmu_name: str, txt_file: IO) -> None:
        """Write the I/O mapping for one FMU to the `container.txt` file.

        Args:
            fmu_name (str): Name of the embedded FMU.
            txt_file (IO): Writable text file handle.
        """
        for type_name in ALL_TYPES:
            print(f"# Inputs of {fmu_name} - {type_name}: <LOCAL_OFFSET> <DIM> <FMU_VR>", file=txt_file)
            print(len(self.inputs[type_name][fmu_name][None]), file=txt_file)
            for io_ref in self.inputs[type_name][fmu_name][None]:
                print(f"{io_ref.local_offset} {io_ref.dim} {io_ref.fmu_vr}", file=txt_file)
            if not type_name == "clock":
                print(f"# Clocked Inputs of {fmu_name} - {type_name}: <FMU_VR_CLOCK> <n> <LOCAL_OFFSET> <DIM> <FMU_VR>", file=txt_file)
                print(f"{len(self.inputs[type_name][fmu_name])-1} {self.nb_clocked_inputs[type_name][fmu_name]}",
                      file=txt_file)
                for clock, translation in self.inputs[type_name][fmu_name].items():
                    if not clock is None:
                        s = " ".join([f"{io_ref.local_offset} {io_ref.dim} {io_ref.fmu_vr}" for io_ref in translation])
                        print(f"{clock} {len(translation)} {s}", file=txt_file)

        for type_name in START_VALUE_TYPES:
            print(f"# Start values of {fmu_name} - {type_name}: <FMU_VR> <DIM> <RESET> <VALUE>", file=txt_file)
            nb_start_lines = len(self.start_values[type_name][fmu_name])
            nb_start_values = 0
            for vr, dim, reset, value in self.start_values[type_name][fmu_name]:
                nb_start_values += dim
            print(f"{nb_start_lines} {nb_start_values}", file=txt_file)
            for vr, dim, reset, value in self.start_values[type_name][fmu_name]:
                print(f"{vr} {dim} {reset} {value}", file=txt_file)

        for type_name in ALL_TYPES:
            print(f"# Outputs of {fmu_name} - {type_name}: <LOCAL_OFFSET> <DIM> <FMU_VR>", file=txt_file)
            print(len(self.outputs[type_name][fmu_name][None]), file=txt_file)
            for io_ref in self.outputs[type_name][fmu_name][None]:
                print(f"{io_ref.local_offset} {io_ref.dim} {io_ref.fmu_vr}", file=txt_file)
            if not type_name == "clock":
                print(f"# Clocked Outputs of {fmu_name} - {type_name}: <FMU_VR_CLOCK> <n> <LOCAL_OFFSET> <DIM> <FMU_VR>", file=txt_file)
                print(f"{len(self.outputs[type_name][fmu_name])-1} {self.nb_clocked_outputs[type_name][fmu_name]}",
                      file=txt_file)
                for clock, translation in self.outputs[type_name][fmu_name].items():
                    if clock is not None:
                        s = " ".join([f"{io_ref.local_offset} {io_ref.dim} {io_ref.fmu_vr}" for io_ref in translation])
                        print(f"{clock} {len(translation)} {s}", file=txt_file)


class InvolvedFMU:
    """Ordered collection of embedded FMUs behaving like a single mapping.

    Internally the FMUs are split between Co-Simulation (`fmu_cs`) and
    Model-Exchange (`fmu_me`) FMUs, but the object exposes a dict-like
    interface (`in`, `[]`, iteration, `len()`, `values()`, ...) that
    transparently combines both stores (CS first, then ME).
    """

    def __init__(self):
        self.fmu_cs: OrderedDict[str, EmbeddedFMU] = OrderedDict()
        self.fmu_me: OrderedDict[str, EmbeddedFMU] = OrderedDict()

    def __contains__(self, fmu_name: str) -> bool:
        return fmu_name in self.fmu_cs or fmu_name in self.fmu_me

    def __getitem__(self, fmu_name: str) -> EmbeddedFMU:
        if fmu_name in self.fmu_cs:
            return self.fmu_cs[fmu_name]
        return self.fmu_me[fmu_name]

    def __setitem__(self, fmu_name: str, fmu: EmbeddedFMU) -> None:
        if fmu.is_me:
            self.fmu_me[fmu_name] = fmu
        else:
            self.fmu_cs[fmu_name] = fmu

    def __delitem__(self, fmu_name: str) -> None:
        if fmu_name in self.fmu_cs:
            del self.fmu_cs[fmu_name]
        else:
            del self.fmu_me[fmu_name]

    def __iter__(self):
        yield from self.fmu_cs
        yield from self.fmu_me

    def __len__(self) -> int:
        return len(self.fmu_cs) + len(self.fmu_me)

    def keys(self):
        yield from self.fmu_cs.keys()
        yield from self.fmu_me.keys()

    def values(self):
        yield from self.fmu_cs.values()
        yield from self.fmu_me.values()

    def items(self):
        yield from self.fmu_cs.items()
        yield from self.fmu_me.items()

    def get(self, fmu_name: str, default=None):
        if fmu_name in self:
            return self[fmu_name]
        return default

    def write_txt(self, txt_file: IO) -> dict[str, int]:
        print(f"{len(self.fmu_cs)} {len(self.fmu_me)}", file=txt_file)
        fmu_rank: dict[str, int] = {}
        for i, fmu in enumerate(self.values()):
            if fmu.is_me:
                # ME entries: <filename> <fmi_version> <nx> <nz> / <identifier> / <guid>
                print(f"{fmu.name} {fmu.fmi_version} {fmu.number_of_continuous_states} {fmu.number_of_event_indicators}", file=txt_file)
            else:
                # CS entries: <filename> <fmi_version> <has_event_mode> / <identifier> / <guid>
                print(f"{fmu.name} {fmu.fmi_version} {int(fmu.has_event_mode)}", file=txt_file)

            print(f"{fmu.model_identifier}", file=txt_file)
            print(f"{fmu.guid}", file=txt_file)
            fmu_rank[fmu.name] = i

        return fmu_rank


class Clock:
    def __init__(self, container_vr: int, fmu_vr: int):
        self.container_vr = container_vr
        self.fmu_vr = fmu_vr


class ClockList:
    """Tracks clocks that need to be scheduled by the FMI importer.

    Used for LS-BUS support where the container runtime needs to trigger
    countdown clocks on embedded FMUs.

    Attributes:
        clocks_per_fmu (dict[int, list[tuple[int, int]]]): Clock entries
            per FMU index: `(fmu_vr, local_vr)` pairs.
        fmu_index (dict[str, int]): Mapping from FMU name to its index
            in the container.
    """

    def __init__(self, involved_fmu: InvolvedFMU):
        self.clocks_per_fmu: defaultdict[int, list[Clock]] = defaultdict(list)
        self.fmu_index: dict[str, int] = {}
        for i, fmu_name in enumerate(involved_fmu):
            self.fmu_index[fmu_name] = i

    def append(self, cport: ContainerPort, vr: int):
        """Register a clock for importer scheduling.

        Args:
            cport (ContainerPort): The clocked port on the embedded FMU.
            vr (int): The local value reference of the clock.
        """
        self.clocks_per_fmu[self.fmu_index[cport.fmu.name]].append(Clock(cport.port.vr, vr))

    def write_txt(self, txt_file: IO) -> None:
        """Write the clock scheduling table to the `container.txt` file.

        Args:
            txt_file (IO): Writable text file handle.
        """
        print(f"# importer CLOCKS: <FMU_INDEX> <NB> <FMU_VR> <VR> [<FMU_VR> <VR>]", file=txt_file)
        nb_total_clocks = 0
        for clocks in self.clocks_per_fmu.values():
            nb_total_clocks += len(clocks)

        print(f"{len(self.clocks_per_fmu)} {nb_total_clocks}", file=txt_file)
        for index, clocks in self.clocks_per_fmu.items():
            clocks_str = " ".join([f"{clock.container_vr} {clock.fmu_vr}" for clock in clocks])
            print(f"{index} {len(clocks)} {clocks_str}", file=txt_file)


class LocalVariable:
    def __init__(self, vr: int, dimension: int):
        self.vr: int = vr
        self.dimension: int = dimension


class Port:
    def __init__(self, vr: int, name: str):
        self.vr: int = vr
        self.name = name
