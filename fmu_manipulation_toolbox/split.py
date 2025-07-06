import logging
import zipfile
import json
import xml.parsers.expat

from typing import *
from pathlib import Path

logger = logging.getLogger("fmu_manipulation_toolbox")


class FMUSplitterError(Exception):
    def __init__(self, message: str):
        self.message = message

    def __str__(self):
        return str(self.message)


class FMUSplitterPort:
    def __init__(self, fmu_filename: str, port_name):
        self.fmu_filename = fmu_filename
        self.port_name = port_name

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
        self.zip = None # to handle error
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
        config_filename = self.directory / self.fmu_filename.with_suffix(".json")
        with open(config_filename, "w") as file:
            json.dump(config, file, indent=2)
        logger.info(f"Container definition saved to '{config_filename}'")

    def _split_fmu(self, fmu_filename: str, relative_path: str) -> Dict[str, Any]:
        txt_filename = f"{relative_path}resources/container.txt"

        if txt_filename in self.filenames_list:
            description = FMUSplitterDescription(self.zip)
            config = description.parse_txt_file(txt_filename)
            config["name"] = fmu_filename
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
                if file.startswith(directory):
                    data = self.zip.read(file)
                    fmu_file.writestr(file[len(directory):], data)
        logger.info(f"FMU Extraction of '{filename}'")


class FMUSplitterDescription:
    def __init__(self, zip):
        self.zip = zip
        self.links: Dict[str, Dict[int, FMUSplitterLink]] = {
            "Real": {},
            "Integer": {},
            "Boolean": {},
            "String": {}
        }
        self.vr_to_name: Dict[str, Dict[str, Dict[int, Dict[str, str]]]] = {} # name, fmi_type, vr <-> {name, causality}
        self.config: Dict[str, Any] = {
            "auto_input": False,
            "auto_output": False,
            "auto_parameter": False,
            "auto_local": False,
            "auto_link": False,
        }
        self.fmu_filename_list = []

        # used for modelDescription.xml parsing
        self.current_fmu_filename = None
        self.current_vr = None
        self.current_name = None
        self.current_causality = None

    @staticmethod
    def get_line(file):
        for line in file:
            line = line.decode('utf-8').strip()
            if line and not line.startswith("#"):
                return line
        raise StopIteration

    def start_element(self, name, attrs):
        if name == "ScalarVariable":
            self.current_name = attrs["name"]
            self.current_vr = int(attrs["valueReference"])
            self.current_causality = attrs["causality"]
        elif name in self.vr_to_name[self.current_fmu_filename]:
            self.vr_to_name[self.current_fmu_filename][name][self.current_vr] = {"name": self.current_name,
                                                                                 "causality": self.current_causality}
        else:
            self.current_vr = None
            self.current_name = None
            self.current_causality = None

    def parse_model_description(self, directory: str, fmu_filename: str):

        if directory == ".":
            filename = "modelDescription.xml"
        else:
            filename = f"{directory}/modelDescription.xml"

        self.vr_to_name[fmu_filename] = {
            "Real": {},
            "Integer": {},
            "Boolean": {},
            "String": {}
        }
        parser = xml.parsers.expat.ParserCreate()
        self.current_fmu_filename = fmu_filename
        self.current_vr = None
        self.current_name = None
        self.current_causality = None
        parser.StartElementHandler = self.start_element
        with (self.zip.open(filename) as file):
            logger.debug(f"Parsing '{filename}' ({fmu_filename})")
            parser.ParseFile(file)

    def parse_txt_file_header(self, file, txt_filename):
        flags = self.get_line(file).split(" ")
        if len(flags) == 1:
            self.config["mt"] = flags[0] == "1"
            self.config["profiling"] = self.get_line(file) == "1"
            self.config["sequential"] = False
        elif len(flags) == 3:
            self.config["mt"] = flags[0] == "1"
            self.config["profiling"] = flags[1] == "1"
            self.config["sequential"] = flags[2] == "1"
        else:
            raise FMUSplitterError(f"Cannot interpret flags '{flags}'")

        self.config["step_size"] = float(self.get_line(file))
        nb_fmu = int(self.get_line(file))
        logger.debug(f"Number of FMUs: {nb_fmu}")
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
                    print(self.zip.namelist())
                    raise FMUSplitterError(f"Cannot find in FMU directory in {directory}.")

            self.parse_model_description(directory, fmu_filename)
            self.config["candidate_fmu"].append(fmu_filename)
            _library = self.get_line(file)
            _uuid = self.get_line(file)
        _nb_local_variables = self.get_line(file)

    def add_port(self, fmi_type: str, fmu_id: int, fmu_vr: int, container_vr: int):
        if fmu_id >= 0:
            fmu_filename = self.config["candidate_fmu"][fmu_id]
            causality = self.vr_to_name[fmu_filename][fmi_type][fmu_vr]["causality"]
            fmu_port_name = self.vr_to_name[fmu_filename][fmi_type][fmu_vr]["name"]
            container_port = self.vr_to_name["."][fmi_type][container_vr]["name"]
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
        for fmi_type in ("Real", "Integer", "Boolean", "String"):
            nb_port_variables = self.get_line(file).split(" ")[0]
            for i in range(int(nb_port_variables)):
                tokens = self.get_line(file).split(" ")
                if len(tokens) > 3:
                    container_vr = int(tokens[0])
                    for j in range(int(tokens[1])):
                        fmu_id = int(tokens[2 + 2 * j])
                        fmu_vr = int(tokens[2 + 2 * j + 1])
                        self.add_port(fmi_type, fmu_id, fmu_vr, container_vr)
                else:  # For FMUContainer <= 1.8.4
                    container_vr = int(tokens[0])
                    fmu_id = int(tokens[1])
                    fmu_vr = int(tokens[2])
                    self.add_port(fmi_type, fmu_id, fmu_vr, container_vr)

    def parse_txt_file(self, txt_filename: str):
        self.parse_model_description(str(Path(txt_filename).parent.parent), ".")
        logger.debug(f"Parsing container file '{txt_filename}'")

        with (self.zip.open(txt_filename) as file):
            self.parse_txt_file_header(file, txt_filename)
            self.parse_txt_file_ports(file)

            for fmu_filename in self.config["candidate_fmu"]:
                # Inputs per FMUs
                for fmi_type in ("Real", "Integer", "Boolean", "String"):
                    nb_input = int(self.get_line(file))
                    for i in range(nb_input):
                        local, vr = self.get_line(file).split(" ")
                        try:
                            link = self.links[fmi_type][local]
                        except KeyError:
                            link = FMUSplitterLink()
                            self.links[fmi_type][local] = link
                        link.to_port.append(FMUSplitterPort(fmu_filename,
                                                            self.vr_to_name[fmu_filename][fmi_type][int(vr)]["name"]))

                for fmi_type in ("Real", "Integer", "Boolean", "String"):
                    nb_start = int(self.get_line(file))
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
                for fmi_type in ("Real", "Integer", "Boolean", "String"):
                    nb_output = int(self.get_line(file))

                    for i in range(nb_output):
                        local, vr = self.get_line(file).split(" ")
                        try:
                            link = self.links[fmi_type][local]
                        except KeyError:
                            link = FMUSplitterLink()
                            self.links[fmi_type][local] = link
                        link.from_port = FMUSplitterPort(fmu_filename,
                                                         self.vr_to_name[fmu_filename][fmi_type][int(vr)]["name"])

            logger.debug("End of parsing.")

        for fmi_type, links in self.links.items():
            for link in links.values():
                for to_port in link.to_port:
                    definition = [ link.from_port.fmu_filename, link.from_port.port_name,
                                   to_port.fmu_filename, to_port.port_name]
                    try:
                        self.config["link"].append(definition)
                    except KeyError:
                        self.config["link"] = [definition]

        return self.config
