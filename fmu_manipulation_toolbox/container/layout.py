"""Value references of the container."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from .rules import ContainerInput, ContainerPort, Link
from .types import ALL_TYPES


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

        Returns:
            int: The allocated value reference with type mask applied.
        """
        if isinstance(port_or_type_name, ContainerPort):
            type_name = port_or_type_name.port.type_name
        else:
            type_name = port_or_type_name

        if isinstance(port_or_type_name, ContainerPort):
            size = port_or_type_name.port.size()
        else:
            size = port_size

        vr = self.vr_table[type_name] | self.masks[type_name]
        self.vr_table[type_name] += 1

        if local:
            self.vr_to_local[vr] = self.nb_local_storage[type_name]
            self.nb_local_variable[type_name] += 1
            self.nb_local_storage[type_name] += size

        return vr

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

        converted = {type_name: self.add_vr(type_name, local=True, port_size=link.cport_from.port.size())
                     for type_name in link.conversions}
        return vr, converted

    def get_local_clock(self, cport: ContainerPort) -> int:
        """Get the local VR for a clock associated with a clocked port.

        Args:
            cport (ContainerPort): The clocked port.

        Returns:
            int: The local value reference of the clock.
        """
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
class ContainerLayout:
    """Value references of a container, allocated from its rules before any file is written.

    The `modelDescription.xml`, `container.txt` and `datalog.txt` writers only read the layout, so a container can be
    built several times. The allocation order fixes the value references: the reserved variables first (time,
    `ts_multiplier`, solver, profiling), then the local variables of the links, then the container inputs and outputs.

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

    @classmethod
    def allocate(cls, links: Iterable[Link], inputs: dict[str, ContainerInput], outputs: dict[str, ContainerPort],
                 nb_profiling: int = 0) -> "ContainerLayout":
        """Allocate the value references of a container.

        Args:
            links (Iterable[Link]): Links between the embedded FMUs, in order.
            inputs (dict[str, ContainerInput]): Container inputs, by exposed name.
            outputs (dict[str, ContainerPort]): Container outputs, by exposed name.
            nb_profiling (int): Number of profiling variables (one per embedded FMU), `0` without profiling.

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

        input_vrs = {name: table.add_vr(input_port.type_name) for name, input_port in inputs.items()}
        output_vrs = {name: table.add_vr(output_port) for name, output_port in outputs.items()}

        return cls(table, time, ts_multiplier, solver, profiling, link_vrs, converted, input_vrs, output_vrs)

    def local_offset(self, vr: int) -> int:
        """Index of a local variable in the storage of its type (`<FMU_VR>` of the local lines of `container.txt`)."""
        return self.table.vr_to_local[vr]
