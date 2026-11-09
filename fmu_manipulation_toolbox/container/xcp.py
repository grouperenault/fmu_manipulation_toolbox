"""FMI-LS-XCP in a container: the XCP services of the embedded FMUs are forwarded by the container.

The container is the importer of its embedded FMUs: the interfaces of the FMUs that implement their own XCP slave
(`containsXCPService`) are declared in the manifest of the container, with their A2L files, and the variables that
configure them are exposed on the container, so that its own importer configures them. Two services cannot listen on
the same port: this is checked at build time.
"""
import logging
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..ls import XCP_PROTOCOLS, XCP_ROLE_TYPES, XCP_ROLES, LayeredStandard, XcpInterface
from .embedded import PLATFORM_OS, EmbeddedFMU
from .errors import FMUContainerError
from .rules import ContainerPort
from .types import CONTAINER_TO_FMI

if TYPE_CHECKING:
    from .builder import FMUContainer, Platform

logger = logging.getLogger("fmu_manipulation_toolbox")

#: Causalities of the role variables that the importer of the FMU can set (FMI-LS-XCP, "Configuring the XCP
#: Protocol Settings"): they are exposed on the container. The others (`constant` output, `calculatedParameter`)
#: only announce the configuration.
CONFIGURABLE_CAUSALITIES = ("structuralParameter", "parameter")

MANIFEST_VERSION = "1.0.0"
MANIFEST_DESCRIPTION = ("Layered standard based on FMI 2.0 and FMI 3.0 for describing and implementing XCP support "
                        "for FMUs, which can either provide an XCP service or allow direct memory access via A2L "
                        "files.")


def interface_type(fmu: EmbeddedFMU) -> str:
    """Interface type under which the FMU is embedded."""
    return "ModelExchange" if fmu.is_me else "CoSimulation"


def forwarded_interfaces(fmu: EmbeddedFMU) -> list[XcpInterface]:
    """Interfaces of FMI-LS-XCP of the FMU forwarded by the container: those with an XCP service, applicable to the
    interface type under which the FMU is embedded. An interface with direct memory access only is not forwarded:
    the container provides no XCP slave, and the addresses of its A2L file are relative to the binary of the FMU."""
    interfaces = []
    for interface in fmu.ls.xcp_interfaces:
        if not interface.applies_to(interface_type(fmu)):
            logger.info(f"FMI-LS-XCP: interface '{interface.definition}' of '{fmu.name}' does not apply to "
                        f"{interface_type(fmu)}: not forwarded.")
        elif interface.contains_xcp_service:
            interfaces.append(interface)
        else:
            logger.warning(f"FMI-LS-XCP: interface '{interface.definition}' of '{fmu.name}' only supports direct "
                           f"memory access: the container provides no XCP service for it, it is not forwarded.")
    return interfaces


def role_ports(container: "FMUContainer", fmu: EmbeddedFMU, interface: XcpInterface) -> dict[str, ContainerPort]:
    """The variable of each role of the interface, when it exists."""
    cports = {}
    for role, name in interface.variables.items():
        if name in fmu.ports:
            cports[role] = ContainerPort(fmu, name)
        else:
            logger.warning(f"FMI-LS-XCP: variable '{name}' (role {role}) does not exist in '{fmu.name}'.")
    return cports


def expose_variables(container: "FMUContainer", auto_wired):
    """Expose on the container the role variables that configure the forwarded XCP services, as
    `<fmu id>.<variable>`. A variable already used by a rule, or of a type the container cannot expose, is not."""
    for fmu in container.involved_fmu.values():
        for interface in forwarded_interfaces(fmu):
            for role, cport in role_ports(container, fmu, interface).items():
                if cport in container.rules:
                    continue
                if cport.port.causality not in CONFIGURABLE_CAUSALITIES:
                    logger.info(f"FMI-LS-XCP: {cport} ({role}) only announces the configuration of the XCP service "
                                f"(it is a {cport.port.causality}): not exposed.")
                    continue
                fmi_type = CONTAINER_TO_FMI[container.fmi_version].get(cport.port.type_name)
                expected = XCP_ROLE_TYPES[XCP_ROLES[role]][container.fmi_version] if role in XCP_ROLES else ()
                if fmi_type not in expected:
                    logger.warning(f"FMI-LS-XCP: {cport} ({role}) is not exposed: an FMI-{container.fmi_version}.0 "
                                   f"container would expose it as {fmi_type or cport.port.type_name}, FMI-LS-XCP "
                                   f"needs {' or '.join(expected)}. Its value is its start value.")
                    continue
                name = f"{fmu.id}.{cport.port.name}"
                logger.info(f"FMI-LS-XCP: Expose {cport} ({role}) as {name}")
                container.add_input(name, fmu.name, cport.port.name)
                auto_wired.add_parameter(name, fmu.name, cport.port.name)


@dataclass
class XcpService:
    """An XCP service of an embedded FMU, on one protocol, with the configuration it has when the container is built."""
    fmu: EmbeddedFMU
    interface: XcpInterface
    protocol: str
    port: int | None


def _value(container: "FMUContainer", cport: ContainerPort | None) -> str | None:
    """Value of a role variable when the container is built: the one of the description, else its start value."""
    if cport is None:
        return None
    value = container.start_values.get(cport, cport.port.start_value)
    return None if value is None else str(value).strip()


def services(container: "FMUContainer") -> list[XcpService]:
    """The enabled XCP services of the forwarded interfaces, with their port: the value of the role variable,
    otherwise the one of the `IF_DATA XCP` of the A2L file."""
    result = []
    for fmu in container.involved_fmu.values():
        for interface in forwarded_interfaces(fmu):
            cports = role_ports(container, fmu, interface)
            a2l = interface.settings
            for protocol in XCP_PROTOCOLS:
                roles = {role[len(f"XCPService{protocol}"):]: cport for role, cport in cports.items()
                         if role.startswith(f"XCPService{protocol}")}
                if not roles and protocol not in a2l:
                    continue                                    # protocol not used by the service
                if _value(container, roles.get("Enable")) in ("false", "0"):
                    continue
                port = _value(container, roles.get("Port"))
                if port is None and protocol in a2l:
                    port = a2l[protocol].port
                result.append(XcpService(fmu, interface, protocol, int(port) if port is not None else None))
    return result


def check_ports(container: "FMUContainer"):
    """Two enabled XCP services cannot use the same port of the same protocol, whatever their listen addresses.

    Raises:
        FMUContainerError: If a port is used by two services.
    """
    used: dict[tuple[str, int], XcpService] = {}
    for service in services(container):
        label = f"'{service.fmu.name}' (interface '{service.interface.definition}')"
        if service.port is None:
            logger.warning(f"FMI-LS-XCP: the {service.protocol} port of the XCP service of {label} is unknown: "
                           f"it cannot be checked.")
            continue
        other = used.get((service.protocol, service.port))
        if other is not None:
            raise FMUContainerError(f"FMI-LS-XCP: the XCP services of '{other.fmu.name}' and {label} use the same "
                                    f"{service.protocol} port {service.port}: set another port (start value of its "
                                    f"variable) for one of them.")
        used[(service.protocol, service.port)] = service


def _exposed_names(container: "FMUContainer") -> dict[ContainerPort, str]:
    return {cport: name for name, container_input in container.inputs.items()
            for cport in container_input.cport_list}


def write_manifest(container: "FMUContainer", base_directory: Path, platforms: list["Platform"]):
    """Manifest of FMI-LS-XCP of the container, and the A2L files of the forwarded interfaces, in
    `extra/org.fmi-standard.fmi-ls-xcp/<platform>/<fmu id>/` for the platforms of the container (or in
    `extra/org.fmi-standard.fmi-ls-xcp/<fmu id>/` for a source code FMU). The A2L files are read from the archive of
    the FMU: its temporary directory is removed once it is analysed."""
    namespace = LayeredStandard.MANIFEST_NAMESPACE
    root = ET.Element("fmiLayeredStandardManifest", {
        f"{{{namespace}}}fmi-ls-name": LayeredStandard.XCP_NAME,
        f"{{{namespace}}}fmi-ls-version": MANIFEST_VERSION,
        f"{{{namespace}}}fmi-ls-description": MANIFEST_DESCRIPTION,
    })
    xcp_directory = base_directory / "extra" / LayeredStandard.XCP_NAME
    exposed = _exposed_names(container)
    target_of_os = {PLATFORM_OS[platform.origin_bindir]: platform.target_bindir for platform in platforms}

    for fmu in container.involved_fmu.values():
        for interface in forwarded_interfaces(fmu):
            definition = Path(fmu.id) / urllib.parse.unquote(interface.definition)
            copied = False
            with zipfile.ZipFile(fmu.fmu.fmu_filename) as archive:
                for platform, entry in interface.a2l.items():
                    if platform is None:
                        target = xcp_directory / definition
                    elif PLATFORM_OS.get(platform) in target_of_os:
                        target = xcp_directory / target_of_os[PLATFORM_OS[platform]] / definition
                    else:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(entry))
                    copied = True
            if not copied:
                logger.warning(f"FMI-LS-XCP: no A2L file of interface '{interface.definition}' of '{fmu.name}' for "
                               f"the platforms of the container.")

            attrs = {"definition": urllib.parse.quote(definition.as_posix()), "containsXCPService": "true"}
            attrs["description"] = f"{fmu.name}: {interface.description}" if interface.description else fmu.name
            element = ET.SubElement(root, "Interface", attrs)
            for role, cport in role_ports(container, fmu, interface).items():
                if cport in exposed:
                    ET.SubElement(element, "Variable", {"name": exposed[cport], "role": role})

    if len(root) == 0:
        return
    ET.register_namespace("fmi-ls", namespace)
    xcp_directory.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree)
    tree.write(xcp_directory / "fmi-ls-manifest.xml", encoding="UTF-8", xml_declaration=True)
    logger.info(f"FMI-LS-XCP: {len(root)} XCP service(s) forwarded by the container.")
