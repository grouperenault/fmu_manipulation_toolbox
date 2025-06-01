import logging
import zipfile
import json

from typing import *
from pathlib import Path

logger = logging.getLogger("fmu_manipulation_toolbox")

class UNcontainerError(Exception):
    def __init__(self, message: str):
        self.message = message

def __str__(self):
    return str(self.message)


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
            config = self.parse_txt_file(txt_filename)
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
                    logger.debug(f"Extracted {file} to {filename}")
        logger.info(f"FMU Extraction of '{filename}'")

    @staticmethod
    def get_line(file):
        for line in file:
            line = line.decode('utf-8').strip()
            if line and not line.startswith("#"):
                return line
        raise StopIteration


    def parse_txt_file(self, txt_filename: str) -> Dict[str, Any]:
        logger.debug(f"Parsing container file {txt_filename}")
        config = {}
        with self.zip.open(txt_filename) as file:
            config["mt"] = self.get_line(file) == "1"
            config["profiling"] = self.get_line(file) == "1"
            config["time_step"] = float(self.get_line(file))
            nb_fmu = int(self.get_line(file))
            logger.debug(f"Number of FMUs: {nb_fmu}")
            config["candidate_fmu"] = []
            for i in range(nb_fmu):
                config["candidate_fmu"].append(self.get_line(file))
                _library = self.get_line(file)
                _uuid = self.get_line(file)
            _nb_local_variables = self.get_line(file)
            for _fmi_type in ("Real", "Integer", "Boolean", "String"):
                nb_port_variables, _ = self.get_line(file).split(" ")
                for i in range(int(nb_port_variables)):
                    _port_name = self.get_line(file) # TODO: create input/output port names
            for fmu_name in config["candidate_fmu"]:
                for _fmi_type in ("Real", "Integer", "Boolean", "String"):
                    nb_input = int(self.get_line(file))
                    for i in range(nb_input):
                        _port_name = self.get_line(file) # TODO: create link
                for _fmi_type in ("Real", "Integer", "Boolean", "String"):
                    nb_start = int(self.get_line(file))
                    for i in range(nb_start):
                        _port_name = self.get_line(file) # TODO: create start value
                for _fmi_type in ("Real", "Integer", "Boolean", "String"):
                    nb_output = int(self.get_line(file))
                    for i in range(nb_output):
                        _port_name = self.get_line(file) # TODO: create link
            logger.debug("End of parsing.")

        return config
