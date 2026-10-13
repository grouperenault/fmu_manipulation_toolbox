"""Compilation of the sources embedded in an FMU for the host platform.

Some FMUs ship their C or C++ sources in `sources/` but no binary for the platform of the user.
`SourceCompiler` reads how to build them (FMI 2.0: `<SourceFiles>` of each interface; FMI 3.0:
`sources/buildDescription.xml`) and calls the C compiler of the host (`Toolchain`) to build the shared library
into `binaries/<platform>/`.
"""
import functools
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .model_description import ModelDescription
from .operations import OperationAbstract, OperationError

logger = logging.getLogger("fmu_manipulation_toolbox")

#: FMI headers shipped with the package, appended to the include path.
FMI_HEADERS_DIRECTORY = Path(__file__).parent / "resources" / "fmi"

#: Suffixes of the C++ sources, when the language of their `SourceFileSet` is not given.
CXX_SUFFIXES = (".cpp", ".cc", ".cxx", ".c++")


def _host_architecture() -> str:
    """Architecture of the running interpreter, as named by FMI 3.0 (`x86_64`, `x86` or `aarch64`)."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64", "x86", "i386", "i686"):
        return "x86_64" if sys.maxsize > 2 ** 32 else "x86"
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    raise OperationError(f"Unsupported host architecture '{platform.machine()}'.")


@dataclass
class SourceFileSet:
    """Sources compiled with the same settings (a `<SourceFileSet>` of FMI 3.0, all the sources for FMI 2.0).

    Attributes:
        source_files (list[Path]): Source files, in the order of the build description.
        language (str | None): Language, e.g. `C99` or `C++11`.
        compiler (str | None): Compiler for which `compiler_options` are written, e.g. `gcc`.
        compiler_options (str | None): Options for `compiler`, as a command line.
        definitions (dict[str, str | None]): Preprocessor definitions (`None` for a definition without value).
        include_directories (list[Path]): Include directories (`sources/` itself is not listed).
    """
    source_files: list[Path] = field(default_factory=list)
    language: str | None = None
    compiler: str | None = None
    compiler_options: str | None = None
    definitions: dict[str, str | None] = field(default_factory=dict)
    include_directories: list[Path] = field(default_factory=list)

    def is_cxx(self, source_file: Path) -> bool:
        """True if `source_file` is C++: given by the language of the set, else by the suffix of the file."""
        if self.language:
            return self.language.strip().upper().startswith("C++")
        return source_file.suffix.lower() in CXX_SUFFIXES


@dataclass
class BuildConfiguration:
    """How to build the shared library of one model identifier.

    Attributes:
        model_identifier (str): Name of the shared library, without suffix.
        source_file_sets (list[SourceFileSet]): Sources and their settings.
        libraries (list[str]): Libraries to link with, by name.
    """
    model_identifier: str
    source_file_sets: list[SourceFileSet] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)

    @property
    def source_files(self) -> list[Path]:
        """Source files of every set."""
        return [path for source_file_set in self.source_file_sets for path in source_file_set.source_files]

    @property
    def include_directories(self) -> list[Path]:
        """Include directories of every set."""
        return [path for source_file_set in self.source_file_sets for path in source_file_set.include_directories]

    @property
    def definitions(self) -> dict[str, str | None]:
        """Preprocessor definitions of every set."""
        definitions = {}
        for source_file_set in self.source_file_sets:
            definitions.update(source_file_set.definitions)
        return definitions


@dataclass
class Toolchain:
    """Compilers of the host platform.

    Attributes:
        family (str): `gcc`, `clang` or `msvc`.
        c_compiler (list[str]): Command of the C compiler.
        cxx_compiler (list[str]): Command of the C++ compiler.
        environment (dict[str, str] | None): Environment of the compilers (MSVC), `None` for the current one.
    """
    family: str
    c_compiler: list[str]
    cxx_compiler: list[str]
    environment: dict[str, str] | None = None

    #: Values of the `compiler` attribute of a `SourceFileSet` that designate each family.
    COMPILER_NAMES = {"gcc": ("gcc", "g++"), "clang": ("clang", "clang++"), "msvc": ("cl", "cl.exe", "msvc")}

    def matches(self, compiler: str | None) -> bool:
        """True if `compiler` (the attribute of a `SourceFileSet`) designates this toolchain."""
        return compiler is not None and compiler.strip().lower() in self.COMPILER_NAMES[self.family]

    @property
    def object_suffix(self) -> str:
        return ".obj" if self.family == "msvc" else ".o"

    def compile_command(self, source_file: Path, object_file: Path, cxx: bool, include_directories: list[Path],
                        definitions: dict[str, str | None], options: list[str]) -> list[str]:
        """Command line compiling `source_file` into `object_file`."""
        compiler = self.cxx_compiler if cxx else self.c_compiler
        if self.family == "msvc":
            command = compiler + ["/nologo", "/c", "/O2", "/MT", "/TP" if cxx else "/TC"]
            command += [f"/I{directory}" for directory in include_directories]
            command += [f"/D{name}" if value is None else f"/D{name}={value}" for name, value in definitions.items()]
            return command + options + [str(source_file), f"/Fo{object_file}"]

        command = compiler + ["-c", "-O2", "-fPIC"]
        command += [f"-I{directory}" for directory in include_directories]
        command += [f"-D{name}" if value is None else f"-D{name}={value}" for name, value in definitions.items()]
        return command + options + [str(source_file), "-o", str(object_file)]

    def link_command(self, object_files: list[Path], library: Path, cxx: bool, libraries: list[str]) -> list[str]:
        """Command line linking `object_files` into the shared library `library`."""
        linker = self.cxx_compiler if cxx else self.c_compiler
        if self.family == "msvc":
            command = linker + ["/nologo", "/LD", "/MT"] + [str(path) for path in object_files] + [f"/Fe{library}"]
            if libraries:
                command += ["/link"] + [name if name.lower().endswith(".lib") else f"{name}.lib"
                                        for name in libraries]
            return command

        command = linker + ["-dynamiclib" if platform.system() == "Darwin" else "-shared"]
        command += [str(path) for path in object_files] + ["-o", str(library)]
        command += [f"-l{name}" for name in libraries]
        if platform.system() == "Linux":
            command.append("-lm")
        return command

    @staticmethod
    @functools.cache
    def find() -> "Toolchain":
        """Compilers of the host platform, searched once.

        Windows: MSVC found by `vswhere.exe` (its environment is set by `vcvarsall.bat`), else `cl.exe` from
        `PATH`. Elsewhere: `$CC` (default `cc`) and `$CXX` (default `c++`).

        Raises:
            OperationError: If no C compiler is found.
        """
        if platform.system() == "Windows":
            return Toolchain._find_msvc()

        c_compiler = shlex.split(os.environ.get("CC", "cc"))
        if not c_compiler or shutil.which(c_compiler[0]) is None:
            raise OperationError(f"No C compiler found ('{os.environ.get('CC', 'cc')}'): install one, "
                                 f"or set the CC environment variable.")
        cxx_compiler = shlex.split(os.environ.get("CXX", "c++"))
        try:
            version = subprocess.run(c_compiler + ["--version"], capture_output=True, text=True,
                                     errors="replace").stdout
        except OSError:
            version = ""
        return Toolchain("clang" if "clang" in version.lower() else "gcc", c_compiler, cxx_compiler)

    @staticmethod
    def _find_msvc() -> "Toolchain":
        program_files = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        vswhere = Path(program_files) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if vswhere.is_file():
            installations = subprocess.run([str(vswhere), "-latest", "-products", "*", "-property",
                                            "installationPath"], capture_output=True, text=True,
                                           errors="replace").stdout.splitlines()
            for installation in installations:
                vcvarsall = Path(installation.strip()) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
                if not vcvarsall.is_file():
                    continue
                target = {"x86_64": "x64", "x86": "x86", "aarch64": "arm64"}[_host_architecture()]
                output = subprocess.run(f'"{vcvarsall}" {target} >nul && set', shell=True, capture_output=True,
                                        text=True, errors="replace").stdout
                environment = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
                path = next((value for name, value in environment.items() if name.upper() == "PATH"), None)
                cl = shutil.which("cl", path=path)
                if cl:
                    logger.debug(f"MSVC found with '{vcvarsall}'.")
                    return Toolchain("msvc", [cl], [cl], environment)

        cl = shutil.which("cl")
        if cl:
            return Toolchain("msvc", [cl], [cl])
        raise OperationError("No C compiler found: install Visual Studio (or its Build Tools) with the C++ "
                             "workload, or run from a Developer Command Prompt.")


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
        architecture = _host_architecture()

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

    # ----------------------------------------------------------------------- #
    #                            Build description                            #
    # ----------------------------------------------------------------------- #
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
            if model_identifier not in configurations:
                configurations[model_identifier] = BuildConfiguration(model_identifier, [SourceFileSet()])
            sources = configurations[model_identifier].source_file_sets[0].source_files
            for file in source_files.findall("File"):
                path = self.sources_directory / file.get("name")
                if path not in sources:
                    sources.append(path)
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
        for set_element in element.findall("SourceFileSet"):
            source_file_set = SourceFileSet(
                source_files=[self.sources_directory / source.get("name")
                              for source in set_element.findall("SourceFile")],
                language=set_element.get("language"),
                compiler=set_element.get("compiler"),
                compiler_options=set_element.get("compilerOptions"),
                include_directories=[self.sources_directory / include.get("name")
                                     for include in set_element.findall("IncludeDirectory")])
            for definition in set_element.findall("PreprocessorDefinition"):
                if definition.get("optional", "false") in ("true", "1"):
                    continue
                source_file_set.definitions[definition.get("name")] = definition.get("value")
            configuration.source_file_sets.append(source_file_set)
        configuration.libraries = [library.get("name") for library in element.findall("Library")]
        return configuration

    # ----------------------------------------------------------------------- #
    #                               Compilation                               #
    # ----------------------------------------------------------------------- #
    def build_commands(self, configuration: BuildConfiguration, toolchain: Toolchain, build_directory: Path,
                       library: Path) -> list[list[str]]:
        """Command lines building `configuration` into `library`: one compilation per source, then the link.

        Object files are written in `build_directory`.
        """
        commands = []
        object_files = []
        has_cxx = False
        for source_file_set in configuration.source_file_sets:
            include_directories = ([self.sources_directory] + source_file_set.include_directories +
                                   [FMI_HEADERS_DIRECTORY])
            definitions = dict(source_file_set.definitions)
            # Sources written for static linking prefix the FMI functions: a shared library needs plain names.
            definitions.setdefault("DISABLE_PREFIX", None)
            if self.fmi_version == 3:
                definitions.setdefault("FMI3_OVERRIDE_FUNCTION_PREFIX", None)
            options = self._compiler_options(source_file_set, toolchain)

            for source_file in source_file_set.source_files:
                cxx = source_file_set.is_cxx(source_file)
                has_cxx |= cxx
                object_file = build_directory / f"{len(object_files)}_{source_file.stem}{toolchain.object_suffix}"
                object_files.append(object_file)
                commands.append(toolchain.compile_command(source_file, object_file, cxx, include_directories,
                                                          definitions, options))

        commands.append(toolchain.link_command(object_files, library, has_cxx, configuration.libraries))
        return commands

    @staticmethod
    def _compiler_options(source_file_set: SourceFileSet, toolchain: Toolchain) -> list[str]:
        if not source_file_set.compiler_options:
            return []
        if toolchain.matches(source_file_set.compiler):
            return shlex.split(source_file_set.compiler_options, posix=toolchain.family != "msvc")
        logger.warning(f"Compiler options '{source_file_set.compiler_options}' are written for "
                       f"'{source_file_set.compiler}', not for {toolchain.family}: they are ignored.")
        return []

    def compile(self, configuration: BuildConfiguration, toolchain: Toolchain | None = None) -> Path:
        """Build the shared library of `configuration` into `binaries/<host platform>/`.

        The compiler output is forwarded to the logger. Nothing is written into the FMU if the build fails.

        Args:
            configuration (BuildConfiguration): What to build (see `build_configurations()`).
            toolchain (Toolchain | None): Compilers to use; by default, those of the host (`Toolchain.find()`).

        Returns:
            Path: Path of the shared library.

        Raises:
            OperationError: If no compiler is found or if the build fails.
        """
        toolchain = toolchain or Toolchain.find()
        destination = self.binary_path(configuration.model_identifier)
        logger.info(f"Compiling '{configuration.model_identifier}' for {self.host_platform(self.fmi_version)} "
                    f"with {toolchain.family}.")
        with tempfile.TemporaryDirectory() as build_directory:
            build_directory = Path(build_directory)
            library = build_directory / destination.name
            steps = [f"Compiling '{self._display(path)}'." for path in configuration.source_files]
            steps.append(f"Linking '{library.name}'.")
            commands = self.build_commands(configuration, toolchain, build_directory, library)
            for step, command in zip(steps, commands):
                logger.info(step)
                self._run(command, toolchain, build_directory, configuration.model_identifier)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(library, destination)
        logger.info(f"Binary 'binaries/{destination.parent.name}/{destination.name}' is built.")
        return destination

    def _display(self, path: Path | str) -> str:
        """`path` relative to the extracted FMU (e.g. `sources/model.c`), for the log."""
        try:
            return Path(path).relative_to(self.fmu_directory).as_posix()
        except ValueError:
            return str(path)

    def _run(self, command: list[str], toolchain: Toolchain, build_directory: Path, model_identifier: str):
        """Run `command`. Its output is logged as warnings on success, as errors on failure."""
        logger.debug(" ".join(shlex.quote(argument) for argument in command))
        try:
            process = subprocess.run(command, cwd=build_directory, env=toolchain.environment, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, errors="replace")
        except OSError as error:
            raise OperationError(f"Cannot run '{command[0]}': {error.strerror}.") from None

        # Shorten the temporary paths: `sources/model.c` rather than `/tmp/tmpXXXX/sources/model.c`.
        prefixes = [f"{directory}{separator}" for directory in (self.fmu_directory, build_directory)
                    for separator in {os.sep, "/"}]
        level = logging.WARNING if process.returncode == 0 else logging.ERROR
        for line in process.stdout.splitlines():
            if toolchain.family == "msvc" and self._is_msvc_banner(line, command):
                continue
            for prefix in prefixes:
                line = line.replace(prefix, "")
            if line.strip():
                logger.log(level, line.rstrip())

        if process.returncode != 0:
            raise OperationError(f"Compilation of '{model_identifier}' failed.")

    @staticmethod
    def _is_msvc_banner(line: str, command: list[str]) -> bool:
        """Lines that MSVC always prints: the name of the compiled source, the import library of a DLL."""
        line = line.strip()
        return line in {Path(argument).name for argument in command} or line.startswith("Creating library ")


class OperationCompileSources(OperationAbstract):
    """Compile the embedded sources when the binary of the host platform is missing.

    For each model identifier of the FMU, the shared library of the host platform is built from `sources/` into
    `binaries/<host platform>/`, unless it already exists. The descriptor is not changed.

    Raises:
        OperationError: If a binary is missing and cannot be built (no sources, no list of the sources, no
            compiler, compilation failure).
    """

    read_only = True

    def __repr__(self):
        return "Compile sources"

    def closure(self):
        source_compiler = SourceCompiler(self.fmu.tmp_directory, self.model_description.fmi_version)
        missing = []
        for model_identifier in dict.fromkeys(interface.get("modelIdentifier")
                                              for interface in self.model_description.interfaces.values()):
            binary = source_compiler.binary_path(model_identifier)
            if binary.is_file():
                logger.info(f"Binary 'binaries/{binary.parent.name}/{binary.name}' already exists: "
                            f"nothing to compile.")
            else:
                missing.append(model_identifier)
        if not missing:
            return

        for configuration in source_compiler.build_configurations(self.model_description):
            if configuration.model_identifier in missing:
                source_compiler.compile(configuration)
