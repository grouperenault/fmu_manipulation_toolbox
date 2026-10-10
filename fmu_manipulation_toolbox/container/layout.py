"""Value references of the container."""

import logging

from .rules import ContainerPort, Link
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

    def set_link_vr(self, link: Link):
        """Allocate value references for a link and its type-converted copies.

        Args:
            link (Link): The link to assign VRs to.
        """
        if link.cport_from is None:
            link.vr = self.add_vr("clock", local=True)
        else:
            link.vr = self.add_vr(link.cport_from, local=True)
            if link.cport_from.port.type_name == "clock":
                self.local_clock[(link.cport_from.fmu, link.cport_from.port.vr)] = link.vr

        for cport_to in link.cport_to_list:
            if cport_to.port.type_name == "clock":
                self.local_clock[(cport_to.fmu, cport_to.port.vr)] = link.vr

        for type_name in link.vr_converted.keys():
            link.vr_converted[type_name] = self.add_vr(type_name, local=True,
                                                       port_size=link.cport_from.port.size())

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
