import json
import logging
import xml.parsers.expat
import zipfile

from collections import defaultdict
from typing import *
from pathlib import Path

from .container import EmbeddedFMUPort, ArrayAggregate
from .terminals import Terminals, Terminal

logger = logging.getLogger("fmu_manipulation_toolbox")


class FMUSplitterError(Exception):
    def __init__(self, message: str):
        self.message = message

    def __str__(self):
        return str(self.message)


class FMUSplitterPort:
    def __init__(self, fmu_filename: str, port_name, dim: int = 1):
        self.fmu_filename = fmu_filename
        self.port_name = port_name
        # Number of scalar elements represented by this port. `dim > 1` means
        # the port is a native FMI-3 array. `dim == 1` is a plain scalar
        # port (which may be part of an FMI-2 array-element family).
        self.dim = dim

    def __str__(self):
        return f"{self.fmu_filename}/{self.port_name}"


class FMUSplitterLink:
    def __init__(self):
        self.from_port: Optional[FMUSplitterPort] = None
        self.to_port: List[FMUSplitterPort] = []

    def __str__(self):
        to_str = ", ".join([f"{port}" for port in self.to_port])
        return f"{self.from_port} -> {to_str}"


class FMUSplitter:
    def __init__(self, fmu_filename: str):
        self.fmu_filename = Path(fmu_filename)
        self.directory = self.fmu_filename.with_suffix(".dir")
        self.zip = zipfile.ZipFile(self.fmu_filename)
        self.filenames_list = self.zip.namelist()
        self.dir_set = self.get_dir_set()

        if "resources/container.txt" not in self.filenames_list:
            raise FMUSplitterError(f"FMU file {self.fmu_filename} is not an FMU Container.")

        self.directory.mkdir(exist_ok=True)
        logger.info(f"Preparing to split '{self.fmu_filename}' into '{self.directory}'")

    def get_dir_set(self) -> Set[str]:
        dir_set = set()
        for filename in self.filenames_list:
            parent = "/".join(filename.split("/")[:-1])
            dir_set.add(parent+"/")
        return dir_set

    def __del__(self):
        if self.zip is not None:
            logger.debug("Closing zip file")
            self.zip.close()

    def split_fmu(self):
        logger.info(f"Splitting...")
        config = self._split_fmu(fmu_filename=str(self.fmu_filename), relative_path="")
        config_filename = self.directory / self.fmu_filename.with_suffix(".json").name
        with open(config_filename, "w") as file:
            json.dump(config, file, indent=2)
        logger.info(f"Container definition saved to '{config_filename}'")

    def _split_fmu(self, fmu_filename: str, relative_path: str) -> Union[Dict[str, Any], str]:
        txt_filename = f"{relative_path}resources/container.txt"

        if txt_filename in self.filenames_list:
            description = FMUSplitterDescription(self.zip)
            config = description.parse_txt_file(txt_filename)
            config["name"] = Path(fmu_filename).name
            for i, fmu_filename in enumerate(config["candidate_fmu"]):
                directory = f"{relative_path}resources/{i:02x}/"
                if directory not in self.dir_set:
                    directory = f"{relative_path}resources/{fmu_filename}/"
                    if directory not in self.dir_set:
                        raise FMUSplitterError(f"{directory} not found in FMU")
                sub_config = self._split_fmu(fmu_filename=fmu_filename, relative_path=directory)
                if isinstance(sub_config, str):
                    key = "fmu"
                else:
                    key = "container"
                try:
                    config[key].append(sub_config)
                except KeyError:
                    config[key] = [sub_config]
            config.pop("candidate_fmu")
        else:
            config = fmu_filename
            self.extract_fmu(relative_path, str(self.directory / fmu_filename))

        return config

    def extract_fmu(self, directory: str, filename: str):
        logger.debug(f"Extracting {directory} to {filename}")
        with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as fmu_file:
            for file in self.zip.namelist():
                if file.startswith(directory) and len(file) > len(directory):
                    data = self.zip.read(file)
                    fmu_file.writestr(file[len(directory):], data)
        logger.info(f"FMU Extraction of '{filename}'")

class FMUSplitterDescription:
    # Reverse mapping from conversion function name to (source_type, target_type)
    REVERSE_CONVERSION = {
        "F32_F64": ("real32", "real64"),
        "D8_D16": ("integer8", "integer16"),
        "D8_U16": ("integer8", "uinteger16"),
        "D8_D32": ("integer8", "integer32"),
        "D8_U32": ("integer8", "uinteger32"),
        "D8_D64": ("integer8", "integer64"),
        "D8_U64": ("integer8", "uinteger64"),
        "U8_D16": ("uinteger8", "integer16"),
        "U8_U16": ("uinteger8", "uinteger16"),
        "U8_D32": ("uinteger8", "integer32"),
        "U8_U32": ("uinteger8", "uinteger32"),
        "U8_D64": ("uinteger8", "integer64"),
        "U8_U64": ("uinteger8", "uinteger64"),
        "D16_D32": ("integer16", "integer32"),
        "D16_U32": ("integer16", "uinteger32"),
        "D16_D64": ("integer16", "integer64"),
        "D16_U64": ("integer16", "uinteger64"),
        "U16_D32": ("uinteger16", "integer32"),
        "U16_U32": ("uinteger16", "uinteger32"),
        "U16_D64": ("uinteger16", "integer64"),
        "U16_U64": ("uinteger16", "uinteger64"),
        "D32_D64": ("integer32", "integer64"),
        "D32_U64": ("integer32", "uinteger64"),
        "U32_D64": ("uinteger32", "integer64"),
        "U32_U64": ("uinteger32", "uinteger64"),
        "B_B1": ("boolean", "boolean1"),
        "B1_B": ("boolean1", "boolean"),
    }

    def __init__(self, handle):
        self.zip = handle
        self.links: Dict[str, Dict[int, FMUSplitterLink]] = dict((el, {}) for el in EmbeddedFMUPort.ALL_TYPES)
        self.vr_to_name: Dict[str, Dict[str, Dict[int, Dict[str, str]]]] = {} # name, fmi_type, vr <-> {name, causality}
        # Terminals declared by each candidate FMU (loaded from its
        # embedded terminalsAndIcons.xml inside the outer container zip).
        # `None` means no such file was present.
        self.terminals_by_fmu: Dict[str, Optional[Terminals]] = {}
        self.config: Dict[str, Any] = {
            "auto_input": False,
            "auto_output": False,
            "auto_parameter": False,
            "auto_local": False,
            "auto_link": False,
        }
        self.file_format = 1
        self.fmu_filename_list = []
        self.pending_conversions: List[tuple] = []  # (vr_from, vr_to, conversion_name)

        # used for modelDescription.xml parsing
        self.current_fmu_filename: Optional[str] = None
        self.current_fmi_version: Optional[str] = None
        self.current_vr: Optional[int] = None
        self.current_name: Optional[str] = None
        self.current_causality: Optional[str] = None
        #self.supported_fmi_types: Tuple = tuple()

    @staticmethod
    def get_line(file):
        for line in file:
            line = line.decode('utf-8').strip()
            logger.debug(f"Read: {line}")
            if not line.startswith("#"):
                return line
        raise StopIteration

    def start_element(self, tag, attrs):
        if tag == "Enumeration":
            if self.current_fmi_version == "2.0":
                tag = "Integer"
            else:
                tag = "Int32"

        if tag == "fmiModelDescription":
            self.current_fmi_version = attrs["fmiVersion"]
        elif tag == "ScalarVariable":
            self.current_name = attrs["name"]
            self.current_vr = int(attrs["valueReference"])
            self.current_causality = attrs.get("causality", "local")
        elif self.current_fmi_version == "2.0" and tag in EmbeddedFMUPort.FMI_TO_CONTAINER[2]:
            fmi_type = EmbeddedFMUPort.FMI_TO_CONTAINER[2][tag]
            self.vr_to_name[self.current_fmu_filename][fmi_type][self.current_vr] = {
                "name": self.current_name,
                "causality": self.current_causality}
        elif self.current_fmi_version == "3.0" and tag in EmbeddedFMUPort.FMI_TO_CONTAINER[3]:
            fmi_type = EmbeddedFMUPort.FMI_TO_CONTAINER[3][tag]
            self.vr_to_name[self.current_fmu_filename][fmi_type][int(attrs["valueReference"])] = {
                "name": attrs["name"],
                "causality": attrs["causality"]}
        else:
            self.current_vr = None
            self.current_name = None
            self.current_causality = None

    def parse_model_description(self, directory: str, fmu_filename: str):

        if directory == ".":
            filename = "modelDescription.xml"
        else:
            filename = f"{directory}/modelDescription.xml"

        self.vr_to_name[fmu_filename] = dict((el, {}) for el in EmbeddedFMUPort.ALL_TYPES)
        parser = xml.parsers.expat.ParserCreate()
        self.current_fmu_filename = fmu_filename
        self.current_fmi_version = None
        self.current_vr = None
        self.current_name = None
        self.current_causality = None
        parser.StartElementHandler = self.start_element
        with (self.zip.open(filename) as file):
            logger.debug(f"Parsing '{filename}' ({fmu_filename})")
            parser.ParseFile(file)

        # Also load terminalsAndIcons.xml, if any, so that later we can
        # aggregate multiple port-to-port links into a single terminal link.
        if directory == ".":
            term_filename = "terminalsAndIcons/terminalsAndIcons.xml"
        else:
            term_filename = f"{directory}/terminalsAndIcons/terminalsAndIcons.xml"
        if term_filename in self.zip.namelist():
            with self.zip.open(term_filename) as term_file:
                self.terminals_by_fmu[fmu_filename] = Terminals.from_xml_source(
                    term_file, label=term_filename)
        else:
            self.terminals_by_fmu[fmu_filename] = None

    @property
    def supported_fmi_types(self) -> Tuple[str]:
        if self.file_format == 0 or self.file_format == 1:
            return tuple(EmbeddedFMUPort.CONTAINER_TO_FMI[2].keys())
        elif self.file_format == 2:
            # no binary, no clock
            return EmbeddedFMUPort.ALL_TYPES[:-2]
        else: #self.file_format >= 3:
            return EmbeddedFMUPort.ALL_TYPES

    @property
    def supported_fmi_types_start(self) -> Tuple[str]:
        if self.file_format == 0 or self.file_format == 1:
            return tuple(EmbeddedFMUPort.CONTAINER_TO_FMI[2].keys())
        elif self.file_format == 2:
            # no binary, no clock
            return EmbeddedFMUPort.ALL_TYPES[:-2]
        else: #self.file_format >= 3:
            # no binary, no clock
            return EmbeddedFMUPort.ALL_TYPES[:-2]

    def parse_txt_file_header(self, file, txt_filename):
        logger.debug(f"*** HEADER ***")
        header = file.readline().decode('utf-8').strip()
        if "Version " in header:
            self.file_format = int(header[header.index("Version ")+8:])
            logger.debug(f"File format: {self.file_format}")

        flags = self.get_line(file).split(" ")
        if len(flags) == 1:
            #self.supported_fmi_types = tuple(EmbeddedFMUPort.CONTAINER_TO_FMI[2].keys())
            self.config["mt"] = flags[0] == "1"
            self.config["profiling"] = self.get_line(file) == "1"
            self.config["sequential"] = False
            self.file_format = 1
            logger.debug(f"File format: {self.file_format}")
        elif len(flags) >= 3:
            #self.supported_fmi_types = EmbeddedFMUPort.ALL_TYPES
            self.config["mt"] = flags[0] == "1"
            self.config["profiling"] = flags[1] == "1"
            self.config["sequential"] = flags[2] == "1"
            if self.file_format == 1:
                self.file_format = 2
            logger.debug(f"File format: {self.file_format}")
        else:
            raise FMUSplitterError(f"Cannot interpret flags '{flags}'")

        self.config["step_size"] = float(self.get_line(file))
        nb_fmu = int(self.get_line(file))

        logger.debug(f'mt             : {self.config["mt"]}')
        logger.debug(f'profiling      : {self.config["profiling"]}')
        logger.debug(f'sequential     : {self.config["sequential"]}')
        logger.debug(f"Number of FMUs : {nb_fmu}")

        self.config["candidate_fmu"] = []

        for i in range(nb_fmu):
            # format is
            #    filename.fmu
            # or
            #    filename.fmu fmi_version
            fmu_filename = self.get_line(file)
            if ' ' in fmu_filename:
                fmu_filename = fmu_filename.split(' ')[0]
                # fmi version is not needed for further operations
            base_directory = "/".join(txt_filename.split("/")[0:-1])
            directory = f"{base_directory}/{fmu_filename}"
            if f"{directory}/modelDescription.xml" not in self.zip.namelist():
                directory = f"{base_directory}/{i:02x}"
                if f"{directory}/modelDescription.xml" not in self.zip.namelist():
                    raise FMUSplitterError(f"Cannot find in FMU directory in {directory}.")
            self.parse_model_description(directory, fmu_filename)
            self.config["candidate_fmu"].append(fmu_filename)
            _library = self.get_line(file)
            _uuid = self.get_line(file)
            logger.debug(f"FMU {i}/{nb_fmu} analysed.")

        _nb_local_variables = self.get_line(file)
        logger.debug(f"*** END OF HEADER ***")

    def add_port(self, fmi_type: str, fmu_id: int, fmu_vr: int, container_vr: int):
        if fmu_id >= 0:
            fmu_filename = self.config["candidate_fmu"][fmu_id]
            causality = self.vr_to_name[fmu_filename][fmi_type][fmu_vr]["causality"]
            fmu_port_name = self.vr_to_name[fmu_filename][fmi_type][fmu_vr]["name"]
            try:
                container_port = self.vr_to_name["."][fmi_type][container_vr]["name"]
            except KeyError:
                # This container VR is not in the container's modelDescription.xml
                # (e.g. FMI3-only types in an FMI2 container). It's an internal link
                # variable, not an exposed container port — skip it.
                logger.debug(f"Skipping container I/O entry: VR {container_vr} not found "
                             f"in container's modelDescription.xml for type {fmi_type}")
                return
            if not causality == "output":
                causality = "input"
                definition = [container_port, fmu_filename, fmu_port_name]
            else:
                definition = [fmu_filename, fmu_port_name, container_port]

            try:
                self.config[causality].append(definition)
            except KeyError:
                self.config[causality] = [definition]

            logger.debug(f"Adding container port {causality}: {definition}")

    def parse_txt_file_ports(self, file):
        for fmi_type in self.supported_fmi_types:
            logger.debug(f"*** container port {fmi_type} ***")
            nb_port_variables = self.get_line(file).split(" ")[0]
            for i in range(int(nb_port_variables)):
                tokens = self.get_line(file).split(" ")
                if len(tokens) == 3:
                    self.file_format = 0
                if self.file_format == 4:
                    container_vr = int(tokens[0])
                    nb = int(tokens[2])
                    for j in range(nb):
                        fmu_id = int(tokens[3 + 2 * j])
                        fmu_vr = int(tokens[3 + 2 * j + 1])
                        self.add_port(fmi_type, fmu_id, fmu_vr, container_vr)
                elif self.file_format == 3 or self.file_format == 2 or self.file_format == 1:
                    container_vr = int(tokens[0])
                    nb = int(tokens[1])
                    for j in range(nb):
                        fmu_id = int(tokens[2 + 2 * j])
                        fmu_vr = int(tokens[2 + 2 * j + 1])
                        self.add_port(fmi_type, fmu_id, fmu_vr, container_vr)
                else:  # For FMUContainer <= 1.8.4
                    container_vr = int(tokens[0])
                    fmu_id = int(tokens[1])
                    fmu_vr = int(tokens[2])
                    self.add_port(fmi_type, fmu_id, fmu_vr, container_vr)

    @staticmethod
    def get_nb(line):
        try:
            (nb_str, _) = line.split(" ")
            nb = int(nb_str)
        except ValueError:
            nb = int(line)

        return nb

    def add_input(self, fmi_type, fmu_filename, local, vr):
        try:
            link = self.links[fmi_type][local]
        except KeyError:
            link = FMUSplitterLink()
            self.links[fmi_type][local] = link
        link.to_port.append(FMUSplitterPort(fmu_filename,
                                            self.vr_to_name[fmu_filename][fmi_type][int(vr)]["name"]))

    def add_output(self, fmi_type, fmu_filename, local, vr):
        try:
            link = self.links[fmi_type][local]
        except KeyError:
            link = FMUSplitterLink()
            self.links[fmi_type][local] = link
        link.from_port = FMUSplitterPort(fmu_filename,
                                         self.vr_to_name[fmu_filename][fmi_type][int(vr)]["name"])

    def add_input_slots(self, fmi_type, fmu_filename, local, dim, vr):
        """Register an input port that spans `dim` consecutive local slots
        starting at `local` (format 4)."""
        port_name = self.vr_to_name[fmu_filename][fmi_type][int(vr)]["name"]
        port = FMUSplitterPort(fmu_filename, port_name, dim=int(dim))
        base = int(local)
        for k in range(int(dim)):
            slot = base + k
            try:
                link = self.links[fmi_type][slot]
            except KeyError:
                link = FMUSplitterLink()
                self.links[fmi_type][slot] = link
            link.to_port.append(port)

    def add_output_slots(self, fmi_type, fmu_filename, local, dim, vr):
        """Register an output port that spans `dim` consecutive local slots
        starting at `local` (format 4)."""
        port_name = self.vr_to_name[fmu_filename][fmi_type][int(vr)]["name"]
        port = FMUSplitterPort(fmu_filename, port_name, dim=int(dim))
        base = int(local)
        for k in range(int(dim)):
            slot = base + k
            try:
                link = self.links[fmi_type][slot]
            except KeyError:
                link = FMUSplitterLink()
                self.links[fmi_type][slot] = link
            link.from_port = port

    def parse_txt_file(self, txt_filename: str):
        self.parse_model_description(str(Path(txt_filename).parent.parent).replace("\\", "/"), ".")
        logger.debug(f"Parsing container file '{txt_filename}'")
        with (self.zip.open(txt_filename) as file):
            self.parse_txt_file_header(file, txt_filename)
            self.parse_txt_file_ports(file)

            for fmu_filename in self.config["candidate_fmu"]:
                # Inputs per FMUs

                for fmi_type in self.supported_fmi_types:
                    tokens = self.get_line(file).split(" ")
                    nb_input = int(tokens[0])
                    logger.debug(f"INPUT of {fmu_filename} {fmi_type} : {nb_input}")

                    for i in range(nb_input):
                        if self.file_format == 4:
                            local, dim, vr = self.get_line(file).split(" ")
                            self.add_input_slots(fmi_type, fmu_filename, local, dim, vr)
                        else:
                            local, vr = self.get_line(file).split(" ")
                            try:
                                link = self.links[fmi_type][local]
                            except KeyError:
                                link = FMUSplitterLink()
                                self.links[fmi_type][local] = link
                            link.to_port.append(FMUSplitterPort(fmu_filename,
                                                                self.vr_to_name[fmu_filename][fmi_type][int(vr)]["name"]))

                    #clocked
                    if self.file_format >= 3 and not fmi_type == "clock":
                        nb_input = self.get_nb(self.get_line(file))
                        logger.debug(f"INPUT of {fmu_filename} {fmi_type} : CLOCKED {nb_input}")
                        for i in range(nb_input):
                            if self.file_format == 4:
                                # Line format:
                                #   <FMU_VR_CLOCK> <n> [<VR> <DIM> <FMU_VR>] × n
                                tokens = self.get_line(file).split(" ")
                                _clock, n = tokens[0], int(tokens[1])
                                for j in range(n):
                                    local = tokens[2 + 3 * j]
                                    dim = tokens[3 + 3 * j]
                                    vr = tokens[4 + 3 * j]
                                    self.add_input_slots(fmi_type, fmu_filename, local, dim, vr)
                            else:
                                local, _clock, vr = self.get_line(file).split(" ")
                                self.add_input(fmi_type, fmu_filename, local, vr)

                for fmi_type in self.supported_fmi_types_start:
                    nb_start_as_string = self.get_line(file).split(" ")[0]
                    nb_start = int(nb_start_as_string)
                    logger.debug(f"nb start for {fmu_filename} {fmi_type} : {nb_start}")
                    for i in range(nb_start):
                        tokens = self.get_line(file).split(" ")
                        vr = int(tokens[0])
                        value = tokens[-1]
                        start_definition = [fmu_filename, self.vr_to_name[fmu_filename][fmi_type][vr]["name"],
                                            value]
                        try:
                            self.config["start"].append(start_definition)
                        except KeyError:
                            self.config["start"] = [start_definition]

                # Output per FMUs
                for fmi_type in self.supported_fmi_types:
                    nb_output = int(self.get_line(file))
                    logger.debug(f"OUTPUT of {fmu_filename} {fmi_type} : {nb_output}")

                    for i in range(nb_output):
                        if self.file_format == 4:
                            local, dim, vr = self.get_line(file).split(" ")
                            self.add_output_slots(fmi_type, fmu_filename, local, dim, vr)
                        else:
                            local, vr = self.get_line(file).split(" ")
                            try:
                                link = self.links[fmi_type][local]
                            except KeyError:
                                link = FMUSplitterLink()
                                self.links[fmi_type][local] = link
                            link.from_port = FMUSplitterPort(fmu_filename,
                                                             self.vr_to_name[fmu_filename][fmi_type][int(vr)]["name"])

                    if self.file_format >=3 and not fmi_type == "clock":
                        nb_output = self.get_nb(self.get_line(file))
                        logger.debug(f"OUTPUT {fmi_type} : CLOCKED {nb_output}")

                        for i in range(nb_output):
                            if self.file_format == 4:
                                # Line format:
                                #   <FMU_VR_CLOCK> <n> [<VR> <DIM> <FMU_VR>] × n
                                tokens = self.get_line(file).split(" ")
                                _clock, n = tokens[0], int(tokens[1])
                                for j in range(n):
                                    local = tokens[2 + 3 * j]
                                    dim = tokens[3 + 3 * j]
                                    vr = tokens[4 + 3 * j]
                                    self.add_output_slots(fmi_type, fmu_filename, local, dim, vr)
                            else:
                                local, _clock, vr = self.get_line(file).split(" ")
                                self.add_output(fmi_type, fmu_filename, local, vr)

                #conversion
                if self.file_format > 1:
                    nb_conversion = int(self.get_line(file))
                    for i in range(nb_conversion):
                        tokens = self.get_line(file).split(" ")
                        vr_from = tokens[0]
                        vr_to = tokens[1]
                        conversion_name = tokens[2]
                        self.pending_conversions.append((vr_from, vr_to, conversion_name))

            logger.debug("End of parsing.")

        # Apply pending conversions now that all FMU inputs/outputs have been parsed
        for vr_from, vr_to, conversion_name in self.pending_conversions:
            if conversion_name in self.REVERSE_CONVERSION:
                source_type, target_type = self.REVERSE_CONVERSION[conversion_name]
                # The output was stored in links[source_type][vr_from]
                # The input was stored in links[target_type][vr_to]
                # Merge: move to_port entries from vr_to link into vr_from link
                if vr_to in self.links[target_type]:
                    target_link = self.links[target_type][vr_to]
                    try:
                        source_link = self.links[source_type][vr_from]
                    except KeyError:
                        source_link = FMUSplitterLink()
                        self.links[source_type][vr_from] = source_link
                    source_link.to_port.extend(target_link.to_port)
                    del self.links[target_type][vr_to]
            else:
                logger.warning(f"Unknown conversion function: {conversion_name}")

        for fmi_type, links in self.links.items():
            # Collect unique (from_port, to_port) pairs. Ports registered by
            # `add_{input,output}_slots` may span several local slots but are
            # the *same* object across those slots, so identity-based dedup
            # is what we need here.
            pair_set: Set[Tuple[int, int]] = set()
            unique_pairs: List[Tuple[FMUSplitterPort, FMUSplitterPort]] = []
            orphan_to_ports: List[FMUSplitterPort] = []
            for link in links.values():
                if link.from_port is None:
                    # Reader slot with no writer. Two known causes:
                    #  * LS-BUS clock-to-clock connections (fmi_type == "clock")
                    #    – not representable in the JSON assembly format.
                    #  * A container slot from an FMI-2 array-element family
                    #    that is fully covered by an aggregate link emitted
                    #    below (silently ignored after the aggregation pass).
                    orphan_to_ports.extend(link.to_port)
                    continue
                for to_port in link.to_port:
                    key = (id(link.from_port), id(to_port))
                    if key in pair_set:
                        continue
                    pair_set.add(key)
                    unique_pairs.append((link.from_port, to_port))

            # Detect FMI-2 array-element families used as aggregates:
            # - array target port (dim > 1) fed by N scalar sources whose
            #   names form a contiguous `basename[k]` family → emit a single
            #   link using the aggregate basename.
            # - array source port fanning out to N scalar targets that form
            #   an aggregate family → same, in the other direction.
            sources_by_target: Dict[int, List[FMUSplitterPort]] = defaultdict(list)
            targets_by_source: Dict[int, List[FMUSplitterPort]] = defaultdict(list)
            port_by_id: Dict[int, FMUSplitterPort] = {}
            for from_p, to_p in unique_pairs:
                port_by_id[id(from_p)] = from_p
                port_by_id[id(to_p)] = to_p
                if to_p.dim > 1 and from_p.dim == 1:
                    sources_by_target[id(to_p)].append(from_p)
                if from_p.dim > 1 and to_p.dim == 1:
                    targets_by_source[id(from_p)].append(to_p)

            aggregated_target_ids: Set[int] = set()
            aggregated_source_ids: Set[int] = set()
            aggregate_definitions: List[List[str]] = []
            # Names covered by an aggregate emitted below, used to silence
            # spurious "orphan" warnings for element ports already grouped.
            covered_names: Set[Tuple[str, str]] = set()  # (fmu_filename, port_name)

            for tid, sources in sources_by_target.items():
                to_p = port_by_id[tid]
                if len(sources) != to_p.dim:
                    continue
                fmus = {s.fmu_filename for s in sources}
                if len(fmus) != 1:
                    continue
                names = [s.port_name for s in sources]
                aggs = ArrayAggregate.detect_all(names)
                if len(aggs) == 1 and aggs[0].size == to_p.dim:
                    src_fmu = next(iter(fmus))
                    aggregate_definitions.append(
                        [src_fmu, aggs[0].basename,
                         to_p.fmu_filename, to_p.port_name])
                    aggregated_target_ids.add(tid)
                    for n in aggs[0].ordered_element_names:
                        covered_names.add((src_fmu, n))

            for sid, targets in targets_by_source.items():
                from_p = port_by_id[sid]
                if len(targets) != from_p.dim:
                    continue
                fmus = {t.fmu_filename for t in targets}
                if len(fmus) != 1:
                    continue
                names = [t.port_name for t in targets]
                aggs = ArrayAggregate.detect_all(names)
                if len(aggs) == 1 and aggs[0].size == from_p.dim:
                    dst_fmu = next(iter(fmus))
                    aggregate_definitions.append(
                        [from_p.fmu_filename, from_p.port_name,
                         dst_fmu, aggs[0].basename])
                    aggregated_source_ids.add(sid)
                    for n in aggs[0].ordered_element_names:
                        covered_names.add((dst_fmu, n))

            for definition in aggregate_definitions:
                try:
                    self.config["link"].append(definition)
                except KeyError:
                    self.config["link"] = [definition]

            for from_p, to_p in unique_pairs:
                # Skip individual scalar links already covered by an aggregate.
                if to_p.dim > 1 and from_p.dim == 1 and id(to_p) in aggregated_target_ids:
                    continue
                if from_p.dim > 1 and to_p.dim == 1 and id(from_p) in aggregated_source_ids:
                    continue
                definition = [from_p.fmu_filename, from_p.port_name,
                              to_p.fmu_filename, to_p.port_name]
                try:
                    self.config["link"].append(definition)
                except KeyError:
                    self.config["link"] = [definition]

            # Report remaining truly-orphan readers (no matching writer and
            # not covered by an aggregate). LS-BUS clock-to-clock connections
            # are the historical reason for this branch; other unresolved
            # readers are logged as generic warnings. Readers whose variable
            # belongs to a declared terminal are silently skipped: the
            # terminal-level link emitted by `_aggregate_terminal_links`
            # already carries the connection at a higher level of abstraction.
            covered_by_terminal = self._terminal_variables()
            for to_port in orphan_to_ports:
                if (to_port.fmu_filename, to_port.port_name) in covered_names:
                    logger.debug(f"Orphan reader silenced (covered by aggregate): "
                                 f"{to_port.fmu_filename}/{to_port.port_name}")
                    continue
                if (to_port.fmu_filename, to_port.port_name) in covered_by_terminal:
                    logger.debug(f"Orphan reader silenced (covered by terminal): "
                                 f"{to_port.fmu_filename}/{to_port.port_name}")
                    continue
                if fmi_type == "clock":
                    logger.error(f"LS-BUS clocks connection are not supported in GUI. "
                                 f"{to_port.fmu_filename}/{to_port.port_name} is skipped")
                else:
                    logger.warning(f"Unresolved {fmi_type} input port "
                                   f"{to_port.fmu_filename}/{to_port.port_name} "
                                   f"(no matching writer); skipped")

        # Collapse groups of port-to-port links that together realise a
        # complete terminal-to-terminal connection into a single link entry.
        self._aggregate_terminal_links()

        return self.config

    def _aggregate_terminal_links(self):
        """Detect groups of port-to-port links between two FMUs that
        realise a terminal-to-terminal connection, and replace them by a
        single link entry referring to the terminals.

        Strategy: for each link whose *both* endpoints are member
        variables of two compatible terminals (same ``kind`` and
        ``matchingRule``) on their respective FMUs, group it under the
        unordered terminal-pair. All grouped links are then removed and
        replaced by a single ``[fmu_a, term_a, fmu_b, term_b]`` entry.

        This is deliberately permissive: it does not require every
        variable pair returned by ``Terminal.connect`` to be present,
        because some FMU containers omit half-duplex members (typical
        LS-BUS setups where the bus does not emit clocks). The presence
        of at least one qualifying link between two compatible terminals
        is enough to conclude that the two terminals are wired together.
        """
        if not self.config.get("link"):
            return

        # Map (fmu_filename, variable_name) → owning terminal object.
        var_to_terminal: Dict[Tuple[str, str], Terminal] = {}
        for fmu_filename, terms in self.terminals_by_fmu.items():
            if not terms:
                continue
            for term in terms:
                for var in self._terminal_variable_names(term):
                    var_to_terminal[(fmu_filename, var)] = term

        if not var_to_terminal:
            return

        links: List[List[str]] = self.config["link"]
        # Group link indices by unordered (fmu, terminal_name) pair.
        # Keep the canonical order stable for deterministic output.
        grouped: Dict[Tuple[str, str, str, str], List[int]] = {}
        for idx, link in enumerate(links):
            fmu_from, port_from, fmu_to, port_to = link
            if fmu_from == fmu_to:
                continue
            term_a = var_to_terminal.get((fmu_from, port_from))
            term_b = var_to_terminal.get((fmu_to, port_to))
            if term_a is None or term_b is None:
                continue
            # `Terminal.__eq__` compares kind and matchingRule.
            if term_a != term_b:
                continue
            a = (fmu_from, term_a.name)
            b = (fmu_to, term_b.name)
            key = (a[0], a[1], b[0], b[1]) if a <= b else (b[0], b[1], a[0], a[1])
            grouped.setdefault(key, []).append(idx)

        if not grouped:
            return

        removed: Set[int] = set()
        added: List[List[str]] = []
        for key, idx_list in grouped.items():
            for idx in idx_list:
                removed.add(idx)
            added.append([key[0], key[1], key[2], key[3]])
            logger.info(
                f"Aggregated {len(idx_list)} port-links into terminal "
                f"connection: {key[0]}/{key[1]} ↔ {key[2]}/{key[3]}")

        self.config["link"] = [l for i, l in enumerate(links) if i not in removed]
        self.config["link"].extend(added)

    def _terminal_variables(self) -> Set[Tuple[str, str]]:
        """Return the set of ``(fmu_filename, variable_name)`` pairs that
        are declared as members (direct or through sub-terminals) of some
        terminal in any candidate FMU."""
        result: Set[Tuple[str, str]] = set()
        for fmu_filename, terms in self.terminals_by_fmu.items():
            if not terms:
                continue
            for term in terms:
                for var in self._terminal_variable_names(term):
                    result.add((fmu_filename, var))
        return result

    @staticmethod
    def _terminal_variable_names(term: Terminal) -> Iterator[str]:
        """Yield every leaf variable name reachable from ``term`` (direct
        members and members of sub-terminals, recursively)."""
        for var in term.members.values():
            yield var
        for sub in term.sub_terminals.values():
            yield from FMUSplitterDescription._terminal_variable_names(sub)

