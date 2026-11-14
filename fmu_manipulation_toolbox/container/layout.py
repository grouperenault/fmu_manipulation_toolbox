"""Value references of the container."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from .rules import ContainerInput, ContainerPort, Link
from .types import ALL_TYPES, CONTAINER_TO_FMI, CONVERSION_FUNCTION, OTHER_BOOLEAN

logger = logging.getLogger("fmu_manipulation_toolbox")


class ValueReferenceTable:
    """Allocates and tracks value references for the container's local variables.

    Value references are encoded with a type mask in the upper bits,
    allowing the container runtime to identify the type from the VR alone.

    Attributes:
        vr_table (dict[str, int]): Next available VR index per type.
        masks (dict[str, int]): Bit mask per type, shifted to the upper byte.
        nb_local_variable (dict[str, int]): Count of local variables per type.
        local_clock (dict): Mapping from `(EmbeddedFMU, fmu_vr)` to local
            clock VR.
    """

    def __init__(self):
        self.vr_table:dict[str, int] = {}
        self.masks: dict[str, int] = {}
        self.nb_local_variable:dict[str, int] = {}
        self.nb_local_storage: dict[str, int] = {}
        self.vr_to_local:dict[int, int] = {}

        self.local_clock = {}
        for i, type_name in enumerate(ALL_TYPES):
            self.vr_table[type_name] = 0
            self.masks[type_name] = i << 24
            self.nb_local_variable[type_name] = 0
            self.nb_local_storage[type_name] = 0

    def add_vr(self, port_or_type_name: ContainerPort | str, local: bool = False, port_size=1) -> int:
        """Allocate a new value reference.

        Args:
            port_or_type_name (ContainerPort | str): A port (type is inferred)
                or a type name string.
            local (bool): Whether this VR is for a local variable.
            port_size (int): Dimension of the local variable, when given by a type name.

        Returns:
            int: The allocated value reference with type mask applied.
        """
        if isinstance(port_or_type_name, ContainerPort):
            type_name, size = port_or_type_name.port.type_name, port_or_type_name.port.size()
        else:
            type_name, size = port_or_type_name, port_size

        vr = self.vr_table[type_name] | self.masks[type_name]
        self.vr_table[type_name] += 1

        if local:
            self.vr_to_local[vr] = self.nb_local_storage[type_name]
            self.nb_local_variable[type_name] += 1
            self.nb_local_storage[type_name] += size

        return vr

    def add_storage(self, type_name: str) -> int:
        """Allocate one slot of local storage without value reference.

        Args:
            type_name (str): Container type name.

        Returns:
            int: Offset of the slot in the local storage of its type.
        """
        offset = self.nb_local_storage[type_name]
        self.nb_local_storage[type_name] += 1
        return offset

    def add_link(self, link: Link) -> tuple[int, dict[str, int]]:
        """Allocate the local variables of a link: its value and its type-converted copies.

        Args:
            link (Link): The link.

        Returns:
            tuple[int, dict[str, int]]: The value reference of the link value, and the
                value references of the converted copies keyed by target type.
        """
        if link.cport_from is None:
            vr = self.add_vr("clock", local=True)
        else:
            vr = self.add_vr(link.cport_from, local=True)
            if link.cport_from.port.type_name == "clock":
                self.local_clock[(link.cport_from.fmu, link.cport_from.port.vr)] = vr

        for cport_to in link.cport_to_list:
            if cport_to.port.type_name == "clock":
                self.local_clock[(cport_to.fmu, cport_to.port.vr)] = vr

        converted = {type_name: self.add_vr(type_name, local=True, port_size=link.size)
                     for type_name in link.conversions}
        return vr, converted

    def get_local_clock(self, cport: ContainerPort) -> int:
        """Get the local VR for a clock associated with a clocked port.

        Args:
            cport (ContainerPort): The clocked port.

        Returns:
            int: The local value reference of the clock.
        """
        assert cport.port.clock is not None
        return self.local_clock[(cport.fmu, int(cport.port.clock))]


    def nb_local(self, type_name: str) -> int:
        """Return the number of local variables for a given type.

        Args:
            type_name (str): Container type name (e.g. `"real64"`).

        Returns:
            int: Number of local variables of this type.
        """
        return self.nb_local_variable[type_name]

    def nb_storage(self, type_name: str) -> int:
        return self.nb_local_storage[type_name]


@dataclass
class OutputConversion:
    """A container output whose embedded port is a boolean of the other FMI version, that the container cannot expose
    as it is: the value of the FMU goes to the local variable `local` (the one of the link of the port when it has
    one), converted by `conversion` into the local variable `vr` of type `type_name`, which is the container output.

    Attributes:
        cport (ContainerPort): The embedded port.
        local (int): Value reference of the local variable of the value of the FMU.
        type_name (str): Container type of the output (`boolean1` in an FMI-3.0 container, `boolean` in FMI 2.0).
        conversion (str): Conversion function of the runtime (`B_B1`, `B1_B`).
        vr (int): Value reference of the converted local variable, and of the container output.
        own_local (bool): `local` is allocated for the output (the port has no link).
        own_copy (bool): `vr` is allocated for the output (no link of the port converts to `type_name`).
    """
    cport: ContainerPort
    local: int
    type_name: str
    conversion: str
    vr: int
    own_local: bool
    own_copy: bool


@dataclass
class ContainerLayout:
    """Value references of a container, allocated from its rules before any file is written.

    The `modelDescription.xml`, `container.txt` and `datalog.txt` writers only read the layout, so a container can be
    built several times. The allocation order fixes the value references: the reserved variables first (time,
    `ts_multiplier`, solver, profiling), then the local variables of the links and of the converted outputs, then the
    container inputs and outputs.

    Attributes:
        table (ValueReferenceTable): The allocator, with the local storage of each type.
        time (int): Value reference of the time.
        ts_multiplier (int): Value reference of the `container.ts_multiplier` input (allocated even if not exposed).
        solver (int): Value reference of the `container.solver` input (allocated even if not exposed).
        profiling (list[int]): Value references of the `rt_ratio` of each embedded FMU, empty without profiling.
        links (dict[Link, int]): Value reference of the local variable of each link.
        converted (dict[Link, dict[str, int]]): Value references of the converted copies of each link, by target type.
        inputs (dict[str, int]): Value reference of each container input, by exposed name.
        outputs (dict[str, int]): Value reference of each container output, by exposed name.
        reset_inputs (dict[str, int]): Local storage offset of each container input feeding `container.reset`
            ports, by exposed name: the runtime reads the trigger there.
        output_conversions (dict[str, OutputConversion]): The container outputs exposed through a converted local
            variable, by exposed name.
        aggregate_outputs (dict[str, int]): Value reference of the local variable of each container output that is
            an FMI-2 array aggregate (not converted), by exposed name: the variable is the output, its elements are
            exchanged one by one with the FMU.
        aggregate_inputs (dict[str, int]): Value reference of the local variable of each container input feeding
            FMI-2 array aggregates, by exposed name: the input writes it, its elements go one by one to the FMUs.
    """
    table: ValueReferenceTable
    time: int
    ts_multiplier: int
    solver: int
    profiling: list[int]
    links: dict[Link, int]
    converted: dict[Link, dict[str, int]]
    inputs: dict[str, int]
    outputs: dict[str, int]
    reset_inputs: dict[str, int]
    output_conversions: dict[str, OutputConversion]
    aggregate_outputs: dict[str, int]
    aggregate_inputs: dict[str, int]

    @classmethod
    def allocate(cls, links: Iterable[Link], inputs: dict[str, ContainerInput], outputs: dict[str, ContainerPort],
                 nb_profiling: int = 0, fmi_version: int | None = None) -> "ContainerLayout":
        """Allocate the value references of a container.

        Args:
            links (Iterable[Link]): Links between the embedded FMUs, in order.
            inputs (dict[str, ContainerInput]): Container inputs, by exposed name.
            outputs (dict[str, ContainerPort]): Container outputs, by exposed name.
            nb_profiling (int): Number of profiling variables (one per embedded FMU), `0` without profiling.
            fmi_version (int | None): FMI version of the container: an output that is a boolean of the other FMI
                version is exposed through a converted local variable (`output_conversions`). `None`: no conversion.

        Returns:
            ContainerLayout: The value references.
        """
        table = ValueReferenceTable()
        time = table.add_vr("real64", local=True)
        ts_multiplier = table.add_vr("integer32", local=True)
        solver = table.add_vr("integer32", local=True)
        profiling = [table.add_vr("real64", local=True) for _ in range(nb_profiling)]

        # Local variables before the container ports, so that they get the lowest value references.
        link_vrs: dict[Link, int] = {}
        converted: dict[Link, dict[str, int]] = {}
        for link in links:
            link_vrs[link], converted[link] = table.add_link(link)
        output_conversions = cls._output_conversions(table, link_vrs, converted, outputs, fmi_version)
        # FMI-2 array aggregates: the runtime exchanges a port of an FMI-2 FMU as one scalar, their elements are
        # exchanged one by one through a local variable (once per port).
        aggregate_outputs: dict[str, int] = {}
        by_port: dict[ContainerPort, int] = {}
        for name, cport in outputs.items():
            if cport.port.is_fmi2_aggregate and name not in output_conversions:
                if cport not in by_port:
                    by_port[cport] = table.add_vr(cport, local=True)
                aggregate_outputs[name] = by_port[cport]
        aggregate_inputs = {name: table.add_vr(input_port.type_name, local=True, port_size=input_port.size)
                            for name, input_port in inputs.items()
                            if any(cport.port.is_fmi2_aggregate for cport in input_port.cport_list)}

        input_vrs = {name: table.add_vr(input_port.type_name) for name, input_port in inputs.items()}
        output_vrs = {name: output_conversions[name].vr if name in output_conversions else
                      aggregate_outputs[name] if name in aggregate_outputs else table.add_vr(output_port)
                      for name, output_port in outputs.items()}
        # Last: the other local variables are listed by value reference, their storage follows their order.
        reset_inputs = {name: table.add_storage(input_port.type_name) for name, input_port in inputs.items()
                        if input_port.has_reset}

        return cls(table, time, ts_multiplier, solver, profiling, link_vrs, converted, input_vrs, output_vrs,
                   reset_inputs, output_conversions, aggregate_outputs, aggregate_inputs)

    @staticmethod
    def _output_conversions(table: ValueReferenceTable, link_vrs: dict[Link, int],
                            converted: dict[Link, dict[str, int]], outputs: dict[str, ContainerPort],
                            fmi_version: int | None) -> dict[str, OutputConversion]:
        """The outputs that are booleans of the other FMI version, with their local variables: the one of the link
        of the port and its converted copy when they exist, allocated otherwise (once per port)."""
        if fmi_version is None:
            return {}
        exposable = CONTAINER_TO_FMI[fmi_version]
        link_of = {link.cport_from: link for link in link_vrs if link.cport_from is not None}
        conversions: dict[str, OutputConversion] = {}
        by_port: dict[ContainerPort, OutputConversion] = {}
        for name, cport in outputs.items():
            type_name = cport.port.type_name
            target = OTHER_BOOLEAN.get(type_name)
            if type_name in exposable or target not in exposable:
                continue
            if cport in by_port:            # the same port exposed under another name
                conversions[name] = by_port[cport]
                continue
            link = link_of.get(cport)
            if link is not None:
                local, own_local, vr = link_vrs[link], False, converted[link].get(target)
            else:
                local, own_local, vr = table.add_vr(cport, local=True), True, None
            own_copy = vr is None
            if own_copy:
                vr = table.add_vr(target, local=True, port_size=cport.port.size())
            assert vr is not None
            conversions[name] = by_port[cport] = OutputConversion(
                cport, local, target, CONVERSION_FUNCTION[f"{type_name}/{target}"], vr, own_local, own_copy)
        return conversions

    def local_offset(self, vr: int) -> int:
        """Index of a local variable in the storage of its type (`<FMU_VR>` of the local lines of `container.txt`)."""
        return self.table.vr_to_local[vr]
