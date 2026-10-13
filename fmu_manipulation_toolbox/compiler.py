"""Compilation of the sources embedded in an FMU for the host platform.

Some FMUs ship their C sources in `sources/` but no binary for the platform of the user. `SourceCompiler` reads
how to build them (FMI 2.0: `<SourceFiles>` of each interface; FMI 3.0: `sources/buildDescription.xml`).
"""
import logging
import platform
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .model_description import ModelDescription
from .operations import OperationError

logger = logging.getLogger("fmu_manipulation_toolbox")


@dataclass
class BuildConfiguration:
    """How to build the shared library of one model identifier.

    Attributes:
        model_identifier (str): Name of the shared library, without suffix.
        source_files (list[Path]): Source files to compile, in the order of the build description.
        include_directories (list[Path]): Include directories given by the build description (`sources/`
            itself is not listed).
        definitions (dict[str, str | None]): Preprocessor definitions (`None` for a definition without value).
    """
    model_identifier: str
    source_files: list[Path] = field(default_factory=list)
    include_directories: list[Path] = field(default_factory=list)
    definitions: dict[str, str | None] = field(default_factory=dict)


class SourceCompiler:
    """Compile the `sources/` of an extracted FMU for the host platform.

    Args:
        fmu_directory (Path | str): Directory where the FMU is extracted.
        fmi_version (int): FMI version of the FMU (`2` or `3`).
    """

    def __init__(self, fmu_directory: Path | str, fmi_version: int):
        self.fmu_directory = Path(fmu_directory)
        self.fmi_version = fmi_version
        self.sources_directory = self.fmu_directory / "sources"

    @staticmethod
    def host_platform(fmi_version: int) -> str:
        """Name of the `binaries/` sub-directory of the host platform.

        Raises:
            OperationError: If the host platform has no name in this FMI version.
        """
        system = platform.system()
        machine = platform.machine().lower()
        is_64bits = sys.maxsize > 2 ** 32

        if machine in ("x86_64", "amd64", "x86", "i386", "i686"):
            architecture = "x86_64" if is_64bits else "x86"
        elif machine in ("arm64", "aarch64"):
            architecture = "aarch64"
        else:
            raise OperationError(f"Unsupported host architecture '{platform.machine()}'.")

        if fmi_version == 2:
            # FMI 2.0 only names x86 platforms; `darwin64` is also used for Apple Silicon.
            names = {
                ("Windows", "x86_64"): "win64",
                ("Windows", "x86"): "win32",
                ("Linux", "x86_64"): "linux64",
                ("Linux", "x86"): "linux32",
                ("Darwin", "x86_64"): "darwin64",
                ("Darwin", "aarch64"): "darwin64",
            }
            try:
                return names[(system, architecture)]
            except KeyError:
                raise OperationError(f"FMI 2.0 has no platform name for {system} on '{platform.machine()}'.") \
                    from None

        systems = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}
        try:
            return f"{architecture}-{systems[system]}"
        except KeyError:
            raise OperationError(f"Unsupported host system '{system}'.") from None

    @staticmethod
    def library_suffix() -> str:
        """Suffix of a shared library on the host platform."""
        return {"Windows": ".dll", "Darwin": ".dylib"}.get(platform.system(), ".so")

    def binary_path(self, model_identifier: str) -> Path:
        """Path of the shared library of `model_identifier` for the host platform."""
        return (self.fmu_directory / "binaries" / self.host_platform(self.fmi_version) /
                f"{model_identifier}{self.library_suffix()}")

    def build_configurations(self, model_description: ModelDescription) -> list[BuildConfiguration]:
        """Read how to build the shared libraries of the FMU, one configuration per model identifier.

        Raises:
            OperationError: If the FMU embeds no sources, if the list of the sources is missing, or if a listed
                source file does not exist.
        """
        if not self.sources_directory.is_dir():
            raise OperationError("This FMU does not embed sources.")

        if self.fmi_version == 2:
            configurations = self._fmi2_configurations(model_description)
        else:
            configurations = self._fmi3_configurations()

        for configuration in configurations:
            if not configuration.source_files:
                raise OperationError(f"No source file is listed for '{configuration.model_identifier}'.")
            for path in configuration.source_files:
                if not path.is_file():
                    raise OperationError(f"Source file 'sources/{path.relative_to(self.sources_directory).as_posix()}' "
                                         f"of '{configuration.model_identifier}' does not exist.")
        return configurations

    def _fmi2_configurations(self, model_description: ModelDescription) -> list[BuildConfiguration]:
        configurations: dict[str, BuildConfiguration] = {}
        for interface_name, interface in model_description.interfaces.items():
            source_files = interface.find("SourceFiles")
            if source_files is None:
                raise OperationError(f"<{interface_name}> has no <SourceFiles>: the sources to compile are unknown.")
            model_identifier = interface.get("modelIdentifier")
            configuration = configurations.setdefault(model_identifier, BuildConfiguration(model_identifier))
            for file in source_files.findall("File"):
                path = self.sources_directory / file.get("name")
                if path not in configuration.source_files:
                    configuration.source_files.append(path)
        return list(configurations.values())

    def _fmi3_configurations(self) -> list[BuildConfiguration]:
        filename = self.sources_directory / "buildDescription.xml"
        if not filename.is_file():
            raise OperationError("sources/buildDescription.xml is missing: the sources to compile are unknown.")
        try:
            root = ET.parse(filename).getroot()
        except ET.ParseError as error:
            raise OperationError(f"sources/buildDescription.xml cannot be read: {error}") from None

        host_platform = self.host_platform(self.fmi_version)
        configurations: dict[str, BuildConfiguration] = {}
        for element in root.findall("BuildConfiguration"):
            target = element.get("platform")
            if target is not None and target != host_platform:
                continue
            model_identifier = element.get("modelIdentifier")
            # A configuration dedicated to the host platform wins over a generic one.
            if model_identifier in configurations and target is None:
                continue
            configurations[model_identifier] = self._fmi3_configuration(model_identifier, element)

        if not configurations:
            raise OperationError(f"sources/buildDescription.xml has no build configuration for '{host_platform}'.")
        return list(configurations.values())

    def _fmi3_configuration(self, model_identifier: str, element: ET.Element) -> BuildConfiguration:
        configuration = BuildConfiguration(model_identifier)
        for source_file_set in element.findall("SourceFileSet"):
            configuration.source_files += [self.sources_directory / source.get("name")
                                           for source in source_file_set.findall("SourceFile")]
            configuration.include_directories += [self.sources_directory / include.get("name")
                                                  for include in source_file_set.findall("IncludeDirectory")]
            for definition in source_file_set.findall("PreprocessorDefinition"):
                if definition.get("optional", "false") in ("true", "1"):
                    continue
                configuration.definitions[definition.get("name")] = definition.get("value")
        return configuration
