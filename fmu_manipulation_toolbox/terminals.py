import logging
import xml.etree.ElementTree as ET

from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from collections import OrderedDict

logger = logging.getLogger("fmu_manipulation_toolbox")

CONFIGURATION_KIND = "org.fmi-ls-bus.network-terminal.configuration"
TRANSCEIVER_RULE = "org.fmi-ls-bus.transceiver"
TRANSCEIVER_MEMBERS = ("Tx_Data", "Tx_Clock", "Rx_Data", "Rx_Clock")


class TerminalError(Exception):
    """Two terminals cannot be connected."""


class Terminal:
    def __init__(self, name: str, kind: str, matching: str, path: str | None = None):
        self.name = name
        self.path = path or name  # Names of the parent terminals and of this one, separated by dots.
        self.kind = kind
        self.matching = matching
        self.members:dict[str, str] = {}
        self.sub_terminals: dict[str, Terminal] = {}

    def add_member(self, member_name, variable_name):
        self.members[member_name] = variable_name

    def __repr__(self):
        return f"{self.path} ({len(self.members)} signals, {self.kind})"

    def __eq__(self, other):
        if isinstance(other, Terminal):
            return self.kind == other.kind and self.matching == other.matching
        else:
            return False

    def connect(self, other) -> list[tuple[str, str]]:
        if not isinstance(other, Terminal):
            logger.error(f"Cannot connect Terminal '{self.path}' to '{other}'.")
            return []

        if self.matching == "plug":
            links = self.connect_plug(other)
        elif self.matching == "bus":
            links = self.connect_bus(other)
        elif self.matching == "sequence":
            links = self.connect_sequence(other)
        elif self.matching == TRANSCEIVER_RULE:
            links = self.connect_transceiver(other)
        elif self.matching == "none":
            links = []  # A grouping terminal has no link of its own, only those of its sub-terminals.
        else:
            logger.error(f"Rule '{self.matching}' not defined to connect Terminal '{self.path}'")
            return []

        return links + self.connect_sub_terminals(other)

    def connect_sub_terminals(self, other) -> list[tuple[str, str]]:
        links = []
        for name in [*self.sub_terminals, *(name for name in other.sub_terminals if name not in self.sub_terminals)]:
            sub_terminal = self.sub_terminals.get(name)
            other_sub_terminal = other.sub_terminals.get(name)

            if sub_terminal is None or other_sub_terminal is None:
                present, absent = (other_sub_terminal, self) if sub_terminal is None else (sub_terminal, other)
                if self.matching == "bus" or present.kind == CONFIGURATION_KIND:
                    logger.debug(f"Sub-terminal '{present.path}' has no peer in Terminal '{absent.path}'")
                else:
                    raise TerminalError(f"Sub-terminal '{present.path}' has no peer in Terminal '{absent.path}'")
            elif sub_terminal.kind == CONFIGURATION_KIND:
                logger.debug(f"Sub-terminal '{sub_terminal.path}' holds parameters: no link")
            elif sub_terminal == other_sub_terminal:
                links += sub_terminal.connect(other_sub_terminal)
            else:
                raise TerminalError(f"Incompatible sub-terminals: {sub_terminal} <-> {other_sub_terminal}")

        return links

    def connect_plug(self, other) -> list[tuple[str, str]]:
        links = []
        if Counter(self.members.keys()) == Counter(other.members.keys()):
            for member_name, member in self.members.items():
                other_member = other.members[member_name]
                links.append((member, other_member))
        else:
            logger.error(f"PLUG Terminal '{self.name}' does not exactly fit Terminal '{other.name}'")

        return links

    def connect_bus(self, other) -> list[tuple[str, str]]:
        links = []
        for member_name, member in self.members.items():
            if member_name in other.members:
                other_member = other.members[member_name]
                links.append((member, other_member))
        return links

    def connect_sequence(self, other) -> list[tuple[str, str]]:
        links = []
        if len(self.members) == len(other.members):
            for member, other_member in zip(self.members.values(), other.members.values()):
                links.append((member, other_member))
        else:
            logger.error(f"SEQUENCE Terminal '{self.name}' does not exactly fit Terminal '{other.name}'")
        return links

    def connect_transceiver(self, other) -> list[tuple[str, str]]:
        for terminal in (self, other):
            missing = [member for member in TRANSCEIVER_MEMBERS if member not in terminal.members]
            if missing:
                raise TerminalError(f"Terminal '{terminal.path}' has no member {', '.join(missing)}")

        return [(self.members["Tx_Data"], other.members["Rx_Data"]),
                (self.members["Tx_Clock"], other.members["Rx_Clock"]),
                (self.members["Rx_Data"], other.members["Tx_Data"]),
                (self.members["Rx_Clock"], other.members["Tx_Clock"])]


class Terminals:
    FILENAME = "terminalsAndIcons.xml"
    def __init__(self, directory: Path | str):
        self.terminals: OrderedDict[str, Terminal] = OrderedDict()

        if isinstance(directory, str):
            directory = Path(directory)

        filename = directory / "terminalsAndIcons" / self.FILENAME
        if filename.exists():
            self._parse_source(filename, str(filename))

    @classmethod
    def from_xml_source(cls, source, label: str = "<xml>") -> "Terminals":
        """Build a Terminals instance from an already-open file-like object
        (or path) containing a terminalsAndIcons.xml document.

        Useful when the XML is embedded inside a zip archive (e.g. an FMU
        container) and cannot be resolved via a plain filesystem path.
        """
        instance = cls.__new__(cls)
        instance.terminals = OrderedDict()
        instance._parse_source(source, label)
        return instance

    def _parse_source(self, source, label: str):
        try:
            xml = ET.parse(source)
            # The schema allows GraphicalRepresentation before Terminals, and no Terminals at all.
            for element in xml.getroot().findall("Terminals/Terminal"):
                terminal = self.add_terminal(element)
                logger.debug(f"Terminal '{terminal.name}' defined with {len(terminal.members)} signals")
        except ET.ParseError as e:
            logger.error(f"Cannot parse {label}: {e}")

    def __iter__(self):
        return iter(self.terminals.values())

    def __len__(self):
        return len(self.terminals)

    def __contains__(self, item):
        return item in self.terminals

    def __getitem__(self, item):
        return self.terminals[item]

    def walk(self) -> Iterator[Terminal]:
        """Yield every terminal, including the Configuration terminals that cannot be connected on their own."""
        for terminal in self:
            yield terminal
            for sub_terminal in terminal.sub_terminals.values():
                if sub_terminal.kind == CONFIGURATION_KIND:
                    yield sub_terminal

    def paths_of(self, name: str) -> list[str]:
        """Full paths of the nested terminals called `name`."""
        return [terminal.path for terminal in self if terminal.name == name and terminal.path != name]

    def add_terminal(self, element, parent: Terminal | None = None) -> Terminal:
        name = element.get("name")
        matching = element.get("matchingRule")
        kind = element.get("terminalKind")

        terminal = Terminal(name, kind, matching, f"{parent.path}.{name}" if parent else name)
        if kind != CONFIGURATION_KIND:  # Its parameters come with the Bus Terminal.
            self.terminals[terminal.path] = terminal
        self.add_member_from_terminal(terminal, element)

        return terminal

    def add_member_from_terminal(self, terminal: Terminal, element):
            for child in element:
                if child.tag == "TerminalMemberVariable":
                    terminal.add_member(child.get("memberName"), child.get("variableName"))
                elif child.tag == "Terminal":
                    sub_terminal = self.add_terminal(child, terminal)
                    terminal.sub_terminals[sub_terminal.name] = sub_terminal
