import logging
import xml.etree.ElementTree as ET

from pathlib import Path

logger = logging.getLogger("fmu_manipulation_toolbox")

class LayeredStandard:
    MANIFEST_NAMESPACE = "http://fmi-standard.org/fmi-ls-manifest"

    def __init__(self, directory: Path | str):
        self.is_bus = False
        self.bus_version: str | None = None
        self.standards: list[str] = []

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
            self.is_bus = root.get("isBusSimulationFMU") == "true"
            self.bus_version = root.get(f"{{{self.MANIFEST_NAMESPACE}}}fmi-ls-version")

            self.standards.append("LS-BUS")

    def __len__(self):
        return len(self.standards)

    def __repr__(self):
        return ", ".join(self.standards)