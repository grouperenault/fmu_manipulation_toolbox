"""Wiring rules of a container: ports of the embedded FMUs, container inputs, links, auto-wiring."""

import logging

from .embedded import EmbeddedFMU
from .errors import FMUContainerError
from .types import CONVERSION_FUNCTION, is_lossy


logger = logging.getLogger("fmu_manipulation_toolbox")


class ContainerPort:
    """References a specific port of an embedded FMU within a container.

    Wraps an [EmbeddedFMUPort][fmu_manipulation_toolbox.container.EmbeddedFMUPort]
    together with its parent
    [EmbeddedFMU][fmu_manipulation_toolbox.container.EmbeddedFMU]. The value
    references of the container are not stored on the rules: they are allocated
    at each build, see [ContainerLayout][fmu_manipulation_toolbox.container.ContainerLayout].

    Attributes:
        fmu (EmbeddedFMU): The embedded FMU owning this port.
        port (EmbeddedFMUPort): The port descriptor.

    Raises:
        FMUContainerError: If the port name does not exist in the FMU.
    """

    def __init__(self, fmu: EmbeddedFMU, port_name: str):
        self.fmu = fmu
        try:
            self.port = fmu.ports[port_name]
        except KeyError:
            raise FMUContainerError(f"Port '{fmu.name}/{port_name}' does not exist")

    def __repr__(self):
        return f"Port {self.fmu.name}/{self.port.name}"

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        return str(self) == str(other)


class ContainerInput:
    """Represents an input port exposed by the container.

    A single container input can fan out to multiple embedded FMU input ports,
    provided they share the same type and causality.

    Attributes:
        name (str): Exposed name of the container input.
        type_name (str): Container-internal type name (e.g. `"real64"`).
        causality (str): Port causality (`"input"` or `"parameter"`).
        cport_list (list[ContainerPort]): List of embedded FMU ports connected
            to this input.
    """

    def __init__(self, name: str, cport_to: ContainerPort):
        self.name = name
        self.type_name = cport_to.port.type_name
        self.causality = cport_to.port.causality
        self.cport_list = [cport_to]
        self.size = cport_to.port.size()

    def add_cport(self, cport_to: ContainerPort):
        """Connect an additional embedded FMU port to this container input.

        Args:
            cport_to (ContainerPort): The embedded FMU port to connect.

        Raises:
            FMUContainerError: If the port is already connected, or if types
                or causalities do not match.
        """
        if cport_to in self.cport_list: # Cannot be reached ! (Assembly prevent this to happen)
            raise FMUContainerError(f"Duplicate INPUT {cport_to} already connected to {self.name}")

        if cport_to.port.type_name != self.type_name:
            raise FMUContainerError(f"Cannot connect {self.name} of type {self.type_name} to "
                                    f"{cport_to} of type {cport_to.port.type_name}")

        if cport_to.port.size() != self.size:
            raise FMUContainerError(f"Cannot connect {self.name} with dimension {self.size} to "
                                    f"{cport_to} with dimension {cport_to.port.size()}")

        if cport_to.port.causality != self.causality:
            raise FMUContainerError(f"Cannot connect {self.causality.upper()} {self.name} to "
                                    f"{cport_to.port.causality.upper()} {cport_to}")

        self.cport_list.append(cport_to)


class Link:
    """Represents an internal connection between embedded FMUs inside a container.

    A link routes one output port to one or more input ports. When the source
    and target types differ, automatic type conversion is applied if a
    conversion function exists.

    Attributes:
        CONVERSION_FUNCTION (dict[str, str]): Mapping from type pair strings
            (e.g. `"real32/real64"`) to conversion function identifiers (alias of
            `container.types.CONVERSION_FUNCTION`).
        name (str): Human-readable name derived from the source FMU and port.
        cport_from (ContainerPort | None): Source output port, or `None` for
            importer-generated clocks.
        cport_to_list (list[ContainerPort]): Destination input ports.
        conversions (dict[str, str]): Conversion function, keyed by the type of
            the targets that need a converted copy of the value.
    """

    CONVERSION_FUNCTION = CONVERSION_FUNCTION

    def __init__(self, cport_from: ContainerPort):
        self.name = cport_from.fmu.id + "." + cport_from.port.name  # strip .fmu suffix
        self.cport_from = cport_from
        self.cport_to_list: list[ContainerPort] = []
        self.size = cport_from.port.size()
        self.conversions: dict[str, str] = {}

        if not cport_from.port.causality == "output":
            if cport_from.port.type_name == "clock":
                # LS-BUS allows connected input clocks.
                self.cport_from = None
                self.add_target(cport_from)
            else:
                raise FMUContainerError(f"{cport_from} is {cport_from.port.causality} instead of OUTPUT")

    def add_target(self, cport_to: ContainerPort):
        """Add a destination input port to this link.

        Args:
            cport_to (ContainerPort): The input port to connect.

        Raises:
            FMUContainerError: If the port is not an input, or if types are
                incompatible and no conversion exists.
        """
        if not cport_to.port.causality == "input":
            raise FMUContainerError(f"{cport_to} is {cport_to.port.causality} instead of INPUT")

        if cport_to.port.type_name == "clock" and self.cport_from is None:
            self.cport_to_list.append(cport_to)
        elif cport_to.port.type_name == self.cport_from.port.type_name:
            if cport_to.port.dimensions == self.cport_from.port.dimensions:
                self.cport_to_list.append(cport_to)
            else:
                raise FMUContainerError(f"failed to connect {self.cport_from} to {cport_to} due dimensions mismatch.")
        else:
            conversion = self.get_conversion(cport_to)
            if conversion:
                if is_lossy(conversion):
                    logger.warning(f"Lossy conversion {conversion.lstrip('_')} applied "
                                   f"from {self.cport_from} to {cport_to}.")
                self.cport_to_list.append(cport_to)
                self.conversions[cport_to.port.type_name] = conversion
            else:
                raise FMUContainerError(f"failed to connect {self.cport_from} to {cport_to} due to type.")

    def get_conversion(self, cport_to: ContainerPort) -> str | None:
        """Look up the conversion function for connecting to a different type.

        Args:
            cport_to (ContainerPort): The target port with a potentially
                different type.

        Returns:
            str | None: Conversion function identifier, or `None` if no
                conversion is available.
        """
        try:
            conversion = f"{self.cport_from.port.type_name}/{cport_to.port.type_name}"
            return CONVERSION_FUNCTION[conversion]
        except KeyError:
            return None

    def nb_local(self) -> int:
        """Return the number of local variables needed for this link.

        Returns:
            int: `1` for the main value plus one per type-converted copy.
        """
        return 1+len(self.conversions)


class AutoWired:
    """Collects the rules automatically generated by implicit wiring.

    Used to report back to the
    [AssemblyNode][fmu_manipulation_toolbox.assembly.AssemblyNode] which
    inputs, outputs, and links were created by auto-wiring, so they
    can be recorded in the assembly topology.

    Attributes:
        rule_input (list[list[str]]): Auto-generated input rules
            `[exposed_name, fmu_name, port_name]`.
        rule_output (list[list[str]]): Auto-generated output rules
            `[fmu_name, port_name, exposed_name]`.
        rule_link (list[list[str]]): Auto-generated link rules
            `[from_fmu, from_port, to_fmu, to_port]`.
        nb_param (int): Number of auto-exposed parameters (subset of inputs).
    """

    def __init__(self):
        self.rule_input = []
        self.rule_output = []
        self.rule_link = []
        self.nb_param = 0

    def __repr__(self):
        return (f"{self.nb_param} parameters, {len(self.rule_input) - self.nb_param} inputs,"
                f" {len(self.rule_output)} outputs, {len(self.rule_link)} links.")

    def add_input(self, from_port, to_fmu, to_port):
        self.rule_input.append([from_port, to_fmu, to_port])

    def add_parameter(self, from_port, to_fmu, to_port):
        self.rule_input.append([from_port, to_fmu, to_port])
        self.nb_param += 1

    def add_output(self, from_fmu, from_port, to_port):
        self.rule_output.append([from_fmu, from_port, to_port])

    def add_link(self, from_fmu, from_port, to_fmu, to_port):
        self.rule_link.append([from_fmu, from_port, to_fmu, to_port])
