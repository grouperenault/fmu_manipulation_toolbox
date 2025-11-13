import logging
import xml.etree.ElementTree as ET

from collections import Counter
from pathlib import Path
from typing import *

logger = logging.getLogger("fmu_manipulation_toolbox")

class Terminal:
    def __init__(self, name: str):
        self.name = name
        self.members:Dict[str, str] = {}

    def add_member(self, member_name, variable_name):
        self.members[member_name] = variable_name

    def __repr__(self):
        return f"{self.name} ({len(self.members)} signals)"

    def __eq__(self, other):
        return Counter(self.members.keys()) == Counter(other.members.keys())

    def __iter__(self):
        return self.members.__iter__()

    def __getitem__(self, item):
        return self.members[item]


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
        terminal = Terminal(name)
        self.add_member_from_terminal(terminal, element)

        self.terminals[name] = terminal

        return terminal

    def add_member_from_terminal(self, terminal, element):
            for child in element:
                if child.tag == "TerminalMemberVariable":
                    terminal.add_member(child.get("memberName"), child.get("variableName"))
                elif child.tag == "Terminal":
                    sub_terminal = self.add_terminal(child)
                    for member_name, variable_name in sub_terminal.members.items():
                        terminal.add_member(member_name, variable_name)

