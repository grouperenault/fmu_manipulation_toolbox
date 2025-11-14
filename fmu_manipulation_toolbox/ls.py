import logging
import xml.etree.ElementTree as ET

from pathlib import Path
from typing import *

logger = logging.getLogger("fmu_manipulation_toolbox")

class LayeredStandard:
    def __init__(self, directory: Union[Path, str]):
        self.is_bus = False
        self.standards: List[str] = []

        if isinstance(directory, Path):
            self.directory = directory
        else:
            self.directory = Path(directory)

        self.parse_lsbus()

    def parse_lsbus(self):
        filename = self.directory / "extra" / "org.fmi-standard.fmi-ls-bus" / "fmi-ls-manifest.xml"
        if filename.exists():
            xml = ET.parse(filename)
            root = xml.getroot()
            root.get("isBusSimulationFMU", "")
            self.is_bus = root.get("isBusSimulationFMU") == "true"

            self.standards.append("LS-BUS")

    def __len__(self):
        return len(self.standards)

    def __repr__(self):
        return ", ".join(self.standards)