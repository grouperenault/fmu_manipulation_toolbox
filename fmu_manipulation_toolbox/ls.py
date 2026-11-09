import logging
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET

from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("fmu_manipulation_toolbox")


#: Roles of the variables of an FMI-LS-XCP interface, with the type of their variable.
XCP_ROLES = {
    "XCPServiceTCPEnable": "Boolean",
    "XCPServiceTCPPort": "Port",
    "XCPServiceTCPListenAddress": "String",
    "XCPServiceUDPEnable": "Boolean",
    "XCPServiceUDPPort": "Port",
    "XCPServiceUDPListenAddress": "String",
}

#: FMI types of the variable of each kind of role (`XCP_ROLES`), for FMI 2.0 and FMI 3.0.
XCP_ROLE_TYPES = {
    "Boolean": {2: ("Boolean",), 3: ("Boolean",)},
    "Port": {2: ("Integer",), 3: ("UInt16",)},
    "String": {2: ("String",), 3: ("String",)},
}

#: Protocols of an XCP service, as named by the roles (`XCPService<protocol>Port`).
XCP_PROTOCOLS = ("TCP", "UDP")


@dataclass
class XcpInterface:
    """An `Interface` element of the manifest of FMI-LS-XCP: one A2L file and the XCP service it describes.

    Attributes:
        definition (str): Relative URI of the A2L file.
        types (list[str] | None): Interface types (`CoSimulation`, `ModelExchange`, `ScheduledExecution`) the
            interface applies to; `None` when it applies to all of them.
        description (str | None): Human-readable description.
        contains_xcp_service (bool): The FMU implements its own XCP slave.
        supports_direct_memory_access (bool): The A2L file allows an external XCP slave to access the memory of
            the FMU.
        variables (dict[str, str]): Name of the variable of each role (see `XCP_ROLES`).
        a2l (dict[str | None, str]): The A2L files found when the manifest was read, as paths in the FMU archive,
            by platform (see `a2l_files`).
        settings (dict[str, XcpSettings]): XCP settings of the first of these A2L files (see `read_xcp_settings`).
    """
    definition: str
    types: list[str] | None = None
    description: str | None = None
    contains_xcp_service: bool = False
    supports_direct_memory_access: bool = False
    variables: dict[str, str] = field(default_factory=dict)
    a2l: dict[str | None, str] = field(default_factory=dict)
    settings: dict[str, "XcpSettings"] = field(default_factory=dict)

    def applies_to(self, interface_type: str) -> bool:
        """Whether the interface applies to the interface type `interface_type` (e.g. `"CoSimulation"`)."""
        return self.types is None or interface_type in self.types

    def a2l_files(self, xcp_directory: Path) -> dict[str | None, Path]:
        """A2L files of the interface found in `xcp_directory` (`extra/org.fmi-standard.fmi-ls-xcp`).

        Returns:
            dict[str | None, Path]: The A2L file of each platform directory (named as in `binaries/`), and the one
                of the source code FMU under the key `None`.
        """
        files: dict[str | None, Path] = {}
        source = xcp_directory / self.definition
        if source.is_file():
            files[None] = source
        if xcp_directory.is_dir():
            for directory in sorted(xcp_directory.iterdir()):
                if directory.is_dir() and (directory / self.definition).is_file():
                    files[directory.name] = directory / self.definition
        return files


@dataclass
class XcpSettings:
    """Transport settings of an XCP service read in the `IF_DATA XCP` of an A2L file.

    Attributes:
        port (int | None): Port of the service.
        address (str | None): IP address or host name of the service.
    """
    port: int | None = None
    address: str | None = None


_A2L_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|/\*.*?\*/|//[^\n]*|\S+', re.DOTALL)
_A2L_ADDRESS_TAGS = ("ADDRESS", "HOST_NAME", "IPV6")


def a2l_tokens(text: str) -> list[str]:
    """Tokens of an A2L text, without its comments (strings kept whole, with their quotes)."""
    return [token for token in _A2L_TOKEN.findall(text) if not token.startswith(("/*", "//"))]


def read_xcp_settings(a2l_filename: Path) -> dict[str, XcpSettings]:
    """Transport settings of the XCP service described by an A2L file.

    Reads the first `XCP_ON_TCP_IP` and `XCP_ON_UDP_IP` blocks of the `IF_DATA XCP` sections (`XCP`, `XCPplus`):
    `<version> <port>` followed by an optional `ADDRESS`, `HOST_NAME` or `IPV6`. This is not a parser of A2L: the
    rest of the file is ignored.

    Returns:
        dict[str, XcpSettings]: The settings of each protocol found (`"TCP"`, `"UDP"`).
    """
    tokens = a2l_tokens(Path(a2l_filename).read_text(encoding="latin-1"))
    settings: dict[str, XcpSettings] = {}
    in_xcp = False
    for i, token in enumerate(tokens):
        if token == "/begin" and i + 2 < len(tokens) and tokens[i + 1] == "IF_DATA":
            in_xcp = tokens[i + 2].upper().startswith("XCP")
        elif token == "/end" and i + 1 < len(tokens) and tokens[i + 1] == "IF_DATA":
            in_xcp = False
        elif in_xcp and token == "/begin" and i + 1 < len(tokens):
            match = re.fullmatch(r"XCP_ON_(TCP|UDP)_IP", tokens[i + 1])
            if match and match.group(1) not in settings:
                settings[match.group(1)] = _read_transport(tokens[i + 2:])
    return settings


def _read_transport(tokens: list[str]) -> XcpSettings:
    """Settings of the `XCP_ON_<protocol>_IP` block starting with `tokens` (after its name)."""
    settings = XcpSettings()
    if len(tokens) > 1:
        try:
            settings.port = int(tokens[1], 0)
        except ValueError:
            pass
    for i, token in enumerate(tokens):
        if token == "/end":
            break
        if token in _A2L_ADDRESS_TAGS and i + 1 < len(tokens) and tokens[i + 1].startswith('"'):
            settings.address = tokens[i + 1][1:-1]
            break
    return settings


#: Experiment sub-roles of FMI-LS-REF; an experiment without sub-role is a smoke test.
REF_EXPERIMENT_SUB_ROLES = ("smoke-test", "validation", "uncertainty-analysis")

#: MIME type of the experiment files of FMI-LS-REF (MA-HS-Experiments).
REF_EXPERIMENTS_TYPE = "application/x-ma-hs-experiments"


def resolve_uri(uri: str, base: Path, root: Path) -> tuple[Path | None, str | None]:
    """File designated by a relative URI of a layered standard, resolved against the directory `base`.

    The URI may hold dot segments, as long as the resolved path stays inside the extracted FMU `root`.

    Returns:
        tuple[Path | None, str | None]: The path of the file and `None`; or `None` and the reason why the URI does
            not designate a file of the FMU: `"absolute URI"` (scheme, authority or path starting with `/`),
            `"outside of the FMU"` or `"missing file"`.
    """
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
        return None, "absolute URI"
    path = Path(os.path.normpath(Path(base) / urllib.parse.unquote(parsed.path)))
    try:
        path.relative_to(os.path.normpath(root))
    except ValueError:
        return None, "outside of the FMU"
    if not path.is_file():
        return None, "missing file"
    return path, None


@dataclass
class RefLabel:
    """A `Label` of a related file of FMI-LS-REF, to categorize and filter the related files.

    Attributes:
        name (str): Name of the label (e.g. `"os:Win64"`).
        description (str | None): Human-readable description.
    """
    name: str
    description: str | None = None


@dataclass
class RefRelated:
    """A `Related` element of the manifest of FMI-LS-REF: a file related to the FMU.

    Attributes:
        type (str): MIME type of the file (e.g. `"application/x-ma-hs-experiments"`).
        source (str): URI of the file, relative to the manifest.
        role (str): Main role and sub-roles, separated by `/` (e.g. `"experiment/validation"`).
        description (str | None): Human-readable description.
        labels (list[RefLabel]): Labels of the file.
        path (str | None): The file in the FMU archive (POSIX path relative to its root), when it was found.
        problem (str | None): Why the file was not found (see `resolve_uri`).
    """
    type: str
    source: str
    role: str
    description: str | None = None
    labels: list[RefLabel] = field(default_factory=list)
    path: str | None = None
    problem: str | None = None

    @property
    def main_role(self) -> str:
        """Main role of the file (`"experiment"` for `"experiment/validation"`)."""
        return self.role.split("/")[0]

    @property
    def sub_roles(self) -> list[str]:
        """Sub-roles of the file (`["validation"]` for `"experiment/validation"`)."""
        return self.role.split("/")[1:]

    @property
    def is_experiment(self) -> bool:
        """The file holds experiments."""
        return self.main_role == "experiment"

    @property
    def sub_role(self) -> str:
        """First sub-role of an experiment file, `"smoke-test"` when it has none."""
        sub_roles = self.sub_roles
        return sub_roles[0] if sub_roles else "smoke-test"


class LayeredStandard:
    """The FMI Layered Standards declared by an extracted FMU (manifests of its `extra/` directory).

    Attributes:
        is_bus (bool): The FMU is an LS-BUS Bus Simulation FMU.
        bus_version (str | None): Version of LS-BUS.
        xcp_version (str | None): Version of LS-XCP.
        xcp_interfaces (list[XcpInterface]): Interfaces of LS-XCP.
        ref_version (str | None): Version of LS-REF.
        ref_related (list[RefRelated]): Related files of LS-REF.
        standards (list[str]): Names of the layered standards (`"LS-BUS"`, `"LS-XCP"`, `"LS-REF"`).
    """
    MANIFEST_NAMESPACE = "http://fmi-standard.org/fmi-ls-manifest"
    XCP_NAME = "org.fmi-standard.fmi-ls-xcp"
    REF_NAME = "org.fmi-standard.fmi-ls-ref"

    def __init__(self, directory: Path | str):
        self.is_bus = False
        self.bus_version: str | None = None
        self.xcp_version: str | None = None
        self.xcp_interfaces: list[XcpInterface] = []
        self.ref_version: str | None = None
        self.ref_related: list[RefRelated] = []
        self.standards: list[str] = []

        if isinstance(directory, Path):
            self.directory = directory
        else:
            self.directory = Path(directory)

        self.parse_lsbus()
        self.parse_lsxcp()
        self.parse_lsref()

    @property
    def xcp_directory(self) -> Path:
        """Directory of the files of LS-XCP: `extra/org.fmi-standard.fmi-ls-xcp`."""
        return self.directory / "extra" / self.XCP_NAME

    @property
    def ref_directory(self) -> Path:
        """Directory of the manifest of LS-REF: `extra/org.fmi-standard.fmi-ls-ref`."""
        return self.directory / "extra" / self.REF_NAME

    def parse_lsbus(self):
        filename = self.directory / "extra" / "org.fmi-standard.fmi-ls-bus" / "fmi-ls-manifest.xml"
        if filename.exists():
            xml = ET.parse(filename)
            root = xml.getroot()
            self.is_bus = root.get("isBusSimulationFMU") == "true"
            self.bus_version = root.get(f"{{{self.MANIFEST_NAMESPACE}}}fmi-ls-version")

            self.standards.append("LS-BUS")

    def parse_lsxcp(self):
        filename = self.xcp_directory / "fmi-ls-manifest.xml"
        if not filename.exists():
            return
        self.standards.append("LS-XCP")
        try:
            root = ET.parse(filename).getroot()
        except ET.ParseError as error:
            logger.error(f"Cannot parse the manifest of LS-XCP: {error}")
            return
        self.xcp_version = root.get(f"{{{self.MANIFEST_NAMESPACE}}}fmi-ls-version")
        for element in root.iter("Interface"):
            types = element.get("types")
            interface = XcpInterface(
                definition=element.get("definition", ""),
                types=types.split() if types is not None else None,
                description=element.get("description"),
                contains_xcp_service=element.get("containsXCPService") == "true",
                supports_direct_memory_access=element.get("supportsDirectMemoryAccess") == "true",
            )
            for variable in element.iter("Variable"):
                interface.variables[variable.get("role", "")] = variable.get("name", "")
            files = interface.a2l_files(self.xcp_directory) if interface.definition else {}
            interface.a2l = {platform: path.relative_to(self.directory).as_posix() for platform, path in files.items()}
            if files:
                interface.settings = read_xcp_settings(next(iter(files.values())))
            self.xcp_interfaces.append(interface)

    def parse_lsref(self):
        filename = self.ref_directory / "fmi-ls-manifest.xml"
        if not filename.exists():
            return
        self.standards.append("LS-REF")
        try:
            root = ET.parse(filename).getroot()
        except ET.ParseError as error:
            logger.error(f"Cannot parse the manifest of LS-REF: {error}")
            return
        self.ref_version = root.get(f"{{{self.MANIFEST_NAMESPACE}}}fmi-ls-version")
        for element in root.iter("Related"):
            related = RefRelated(
                type=element.get("type", ""),
                source=element.get("source", ""),
                role=element.get("role", ""),
                description=element.get("description"),
                labels=[RefLabel(label.get("name", ""), label.get("description")) for label in element.iter("Label")],
            )
            path, related.problem = resolve_uri(related.source, self.ref_directory, self.directory)
            if path is not None:
                related.path = path.relative_to(os.path.normpath(self.directory)).as_posix()
            self.ref_related.append(related)

    def __len__(self):
        return len(self.standards)

    def __repr__(self):
        return ", ".join(self.standards)
