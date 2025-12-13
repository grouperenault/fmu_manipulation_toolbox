import logging
import xml.etree.ElementTree as ET

from collections import Counter
from pathlib import Path
from typing import *

logger = logging.getLogger("fmu_manipulation_toolbox")

class Terminal:
    def __init__(self, name: str, kind: str, matching: str):
        self.name = name
        self.kind = str
        self.matching = matching
        self.members:Dict[str, str] = {}
        self.sub_terminals: Dict[str, Terminal] = {}

    def add_member(self, member_name, variable_name):
        self.members[member_name] = variable_name

    def __repr__(self):
        return f"{self.name} ({len(self.members)} signals)"

    def __eq__(self, other):
        if isinstance(other, Terminal):
            return self.kind == other.kind and self.matching == other.matching
        else:
            return False

    def connect(self, other) -> List[Tuple[str, str]]:
        links = []

        for sub_terminal in self.sub_terminals.values():
            other_sub_terminal = other.sub_terminals[sub_terminal.name]
            links += sub_terminal.connect(other_sub_terminal)


        if isinstance(other, Terminal):
            if self.matching == "plug":
                return self.connect_plug(other)
            elif self.matching == "bus":
                return self.connect_bus(other)
            elif self.matching == "sequence":
                return self.connect_sequence(other)
            elif self.matching == "org.fmi-ls-bus.transceiver":
                return self.connect_transceiver(other)
            else:
                logger.error(f"Rule '{self.matching}' not defined to connect Terminal '{self.name}'")
        else:
            logger.error(f"Cannot connect Terminal '{self.name}' to '{other}'.")

        return links

    def connect_plug(self, other) -> List[Tuple[str, str]]:
        links = []
        if Counter(self.members.keys()) == Counter(other.members.keys()):
            for member_name, member in self.members.items():
                other_member = other.members[member_name]
                links.append((member, other_member))
        else:
            logger.error(f"PLUG Terminal '{self.name}' does not exactly fit Terminal '{other.name}'")

        return links

    def connect_bus(self, other) -> List[Tuple[str, str]]:
        links = []
        for member_name, member in self.members.items():
            if member_name in other.members:
                other_member = other.members[member_name]
                links.append((member, other_member))
        return links

    def connect_sequence(self, other) -> List[Tuple[str, str]]:
        links = []
        if len(self.members) == len(other.members):
            for member, other_member in zip(self.members.values(), other.members.values()):
                links.append((member, other_member))
        else:
            logger.error(f"SEQUENCE Terminal '{self.name}' does not exactly fit Terminal '{other.name}'")
        return links

    def connect_transceiver(self, other) -> List[Tuple[str, str]]:
        return [(self.members["Tx_Data"], other.members["Rx_Data"]),
                (self.members["Tx_Clock"], other.members["Rx_Clock"]),
                (self.members["Rx_Data"], other.members["Tx_Data"]),
                (self.members["Rx_Clock"], other.members["Tx_Clock"])]


class Terminals:
    FILENAME = "terminalsAndIcons.xml"
    def __init__(self, directory: Union[Path, str]):
        self.terminals: OrderedDict[str, Terminal] = OrderedDict()

        if isinstance(directory, str):
            directory = Path(directory)

        filename = directory / "terminalsAndIcons" / self.FILENAME
        if filename.exists():

            xml = ET.parse(filename)

            try:
                for element in xml.getroot()[0]:
                    if element.tag == "Terminal":
                        terminal = self.add_terminal(element)
                        logger.debug(f"Terminal '{terminal.name}' defined with {len(terminal.members)} signals")
            except IndexError:
                logger.error(f"{filename} is wrongly formated.")

    def __len__(self):
        return len(self.terminals)

    def __contains__(self, item):
        return item in self.terminals

    def __getitem__(self, item):
        return self.terminals[item]

    def add_terminal(self, element) -> Terminal:
        name = element.get("name")
        matching = element.get("matchingRule")
        kind = element.get("terminalKind")

        terminal = Terminal(name, kind, matching)
        self.add_member_from_terminal(terminal, element)

        self.terminals[name] = terminal

        return terminal

    def add_member_from_terminal(self, terminal, element):
            for child in element:
                if child.tag == "TerminalMemberVariable":
                    terminal.add_member(child.get("memberName"), child.get("variableName"))
                elif child.tag == "Terminal":
                    sub_terminal = self.add_terminal(child)
                    terminal.subterminals[sub_terminal.name] = sub_terminal
