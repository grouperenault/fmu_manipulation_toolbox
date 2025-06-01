import logging
import zipfile
import json
import xml.parsers.expat

from typing import *
from pathlib import Path

logger = logging.getLogger("fmu_manipulation_toolbox")

class UNcontainerError(Exception):
    def __init__(self, message: str):
        self.message = message

def __str__(self):
    return str(self.message)


class UNcontainerPort:
    def __init__(self, fmu_filename: str, port_name):
        self.fmu_filename = fmu_filename
        self.port_name = port_name

    def __str__(self):
        return f"{self.fmu_filename}/{self.port_name}"


class UNcontainerLink:
    def __init__(self):
        self.from_port: Optional[UNcontainerPort] = None
        self.to_port: List[UNcontainerPort] = []

    def __str__(self):
        to_str = ", ".join([f"{port}" for port in self.to_port])
        return f"{self.from_port} -> {to_str}"


class UNcontainerStart:
    def __init__(self, fmu_filename: str, port_name: str, value: Any):
        self.port = UNcontainerPort(fmu_filename, port_name)
        self.value = value


class UNcontainer:
    """
    UNcontainer is a class that provides methods to uncontainer FMU Containers.
    It is used by the command line tool `uncontainer`.
    """

    def __init__(self, fmu_filename: str):
        self.fmu_filename = Path(fmu_filename)
        self.directory = self.fmu_filename.with_suffix(".dir")
        self.zip = zipfile.ZipFile(self.fmu_filename)
        self.filenames_list = self.zip.namelist()
        self.dir_set = self.get_dir_set()

        if "resources/container.txt" not in self.filenames_list:
                raise UNcontainerError(f"FMU file {self.fmu_filename} is not an FMU Container.")

        self.directory.mkdir(exist_ok=True)
        logger.info(f"UNcontainer '{self.fmu_filename}' into '{self.directory}'")

    def get_dir_set(self) -> Set[str]:
        dir_set = set()
        for filename in self.filenames_list:
            dir_set.add(str(Path(filename).parent)+"/")
        return dir_set

    def __del__(self):
        logger.debug("Closing zip file")
        self.zip.close()

    def split_fmu(self):
        logger.info(f"Splitting {self.fmu_filename}...")
        config = self._split_fmu(fmu_filename=str(self.fmu_filename), relative_path="")
        config_filename = self.directory / self.fmu_filename.with_suffix(".json")
        with open(config_filename, "w") as file:
            json.dump(config, file, indent=2)
        logger.info(f"Configuration saved to '{config_filename}'")

    def _split_fmu(self, fmu_filename: str, relative_path: str) -> Dict[str, Any]:
        txt_filename = f"{relative_path}resources/container.txt"

        if txt_filename in self.filenames_list:
            description = Description(self.zip)
            config = description.parse_txt_file(txt_filename)
            config["name"] = fmu_filename
            for i, fmu_filename in enumerate(config["candidate_fmu"]):
                directory = relative_path=f"{relative_path}resources/{i:02x}/"
                if directory in self.dir_set:
                    sub_config = self._split_fmu(fmu_filename=fmu_filename, relative_path=directory)
                else:
                    sub_config = self._split_fmu(fmu_filename=fmu_filename,
                                                 relative_path=str(self.directory / fmu_filename))
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


class Description:
    def __init__(self, zip):
        self.zip = zip
        self.links: Dict[str, Dict[int, UNcontainerLink]] = {
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
        self.config["mt"] = self.get_line(file) == "1"
        self.config["profiling"] = self.get_line(file) == "1"
        self.config["time_step"] = float(self.get_line(file))
        nb_fmu = int(self.get_line(file))
        logger.debug(f"Number of FMUs: {nb_fmu}")
        self.config["candidate_fmu"] = []

        for i in range(nb_fmu):
            fmu_filename = self.get_line(file)
            try:
                self.parse_model_description(str(Path(txt_filename).parent / fmu_filename), fmu_filename)
            except KeyError:
                self.parse_model_description(str(Path(txt_filename).parent / f"{i:02x}"), fmu_filename)
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
        self.config["candidate_port"] = []
        for fmi_type in ("Real", "Integer", "Boolean", "String"):
            nb_port_variables, _ = self.get_line(file).split(" ")
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
                            link = UNcontainerLink()
                            self.links[fmi_type][local] = link
                        link.to_port.append(UNcontainerPort(fmu_filename,
                                                            self.vr_to_name[fmu_filename][fmi_type][int(vr)]["name"]))

                for fmi_type in ("Real", "Integer", "Boolean", "String"):
                    nb_start = int(self.get_line(file))
                    for i in range(nb_start):
                        tokens = self.get_line(file).split(" ")
                        vr = tokens[0]
                        value = tokens[-1]
                        start = UNcontainerStart(fmu_filename,
                                                 self.vr_to_name[fmu_filename][fmi_type][vr]["name"],
                                                 value)
                        logger.error(start)

                # Output per FMUs
                for fmi_type in ("Real", "Integer", "Boolean", "String"):
                    nb_output = int(self.get_line(file))
                    for i in range(nb_output):
                        local, vr = self.get_line(file).split(" ")
                        try:
                            link = self.links[fmi_type][local]
                        except KeyError:
                            link = UNcontainerLink()
                            self.links[fmi_type][local] = link
                        link.from_port = UNcontainerPort(fmu_filename,
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
