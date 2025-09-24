import csv
import html
import logging
import os
import re
import shutil
import tempfile
import xml.parsers.expat
import zipfile
import hashlib
from typing import *

logger = logging.getLogger("fmu_manipulation_toolbox")

class FMU:
    """Unpack and Repack facilities for FMU package. Once unpacked, we can process Operation on
    modelDescription.xml file."""

    FMI2_TYPES = ('Real', 'Integer', 'String', 'Boolean', 'Enumeration')
    FMI3_TYPES = ('Float64', 'Float32',
                  'Int8', 'UInt8', 'Int16', 'UInt16', 'Int32', 'UInt32', 'Int64', 'UInt64',
                  'String', 'Boolean', 'Enumeration')

    def __init__(self, fmu_filename):
        self.fmu_filename = fmu_filename
        self.tmp_directory = tempfile.mkdtemp()
        self.fmi_version = None

        try:
            with zipfile.ZipFile(self.fmu_filename) as zin:
                zin.extractall(self.tmp_directory)
        except FileNotFoundError:
            raise FMUError(f"'{fmu_filename}' does not exist")
        self.descriptor_filename = os.path.join(self.tmp_directory, "modelDescription.xml")
        if not os.path.isfile(self.descriptor_filename):
            raise FMUError(f"'{fmu_filename}' is not valid: {self.descriptor_filename} not found")

    def __del__(self):
        shutil.rmtree(self.tmp_directory)

    def save_descriptor(self, filename):
        shutil.copyfile(os.path.join(self.tmp_directory, "modelDescription.xml"), filename)

    def repack(self, filename):
        with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as zout:
            for root, dirs, files in os.walk(self.tmp_directory):
                for file in files:
                    zout.write(os.path.join(root, file),
                               os.path.relpath(os.path.join(root, file), self.tmp_directory))
        # TODO: Add check on output file

    def apply_operation(self, operation, apply_on=None):
        manipulation = Manipulation(operation, self)
        manipulation.manipulate(self.descriptor_filename, apply_on)


class FMUPort:
    def __init__(self):
        self.fmi_type = None
        self.attrs_list: List[Dict] = []
        self.dimension = None

    def dict_level(self, nb):
        return " ".join([f'{key}="{value}"' for key, value in self.attrs_list[nb].items()])

    def write_xml(self, fmi_version: int, file):
        if fmi_version == 2:
            print(f"    <ScalarVariable {self.dict_level(0)}>", file=file)
            print(f"      <{self.fmi_type} {self.dict_level(1)}/>", file=file)
            print(f"    </ScalarVariable>", file=file)
        elif fmi_version == 3:
            print(f"    <{self.fmi_type} {self.dict_level(0)}/>", file=file)
        else:
            raise FMUError(f"FMUPort writing: unsupported FMI version {fmi_version}")

    def __contains__(self, item):
        for attrs in self.attrs_list:
            if item in attrs:
                return True
        return False

    def __getitem__(self, item):
        for attrs in self.attrs_list:
            if item in attrs:
                return attrs[item]
        raise KeyError

    def __setitem__(self, key, value):
        for attrs in self.attrs_list:
            if key in attrs:
                attrs[key] = value
                return
        raise KeyError

    def get(self, item, default_value):
        try:
            return self[item]
        except KeyError:
            return default_value

    def push_attrs(self, attrs):
        self.attrs_list.append(attrs)


class FMUError(Exception):
    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return self.reason


class Manipulation:
    """Parse modelDescription.xml file and create a modified version"""
    def __init__(self, operation, fmu):
        self.output_filename = tempfile.mktemp()
        self.out = None
        self.operation = operation
        self.parser = xml.parsers.expat.ParserCreate()
        self.parser.StartElementHandler = self.start_element
        self.parser.EndElementHandler = self.end_element
        self.parser.CharacterDataHandler = self.char_data
        self.skip_until: Optional[str] = None
        self.operation.set_fmu(fmu)
        self.fmu = fmu

        self.current_port: Optional[FMUPort] = None

        self.current_port_number: int = 0
        self.port_translation: List[Optional[int]] = []
        self.port_names_list: List[str] = []
        self.port_removed_vr: Set[str] = set()
        self.apply_on = None

    @staticmethod
    def escape(value):
        if isinstance(value, str):
            return html.escape(html.unescape(value))
        else:
            return value

    def handle_port(self):
        causality = self.current_port.get('causality', 'local')
        port_name = self.current_port['name']
        vr = self.current_port['valueReference']
        if not self.apply_on or causality in self.apply_on:
            if self.operation.port_attrs(self.current_port):
                self.remove_port(port_name, vr)
                # Exception is raised by remove port !
            else:
                self.keep_port(port_name)
        else:  # Keep ScalarVariable as it is.
            self.keep_port(port_name)

    def start_element(self, name, attrs):
        if self.skip_until:
            return
        try:
            if name == 'ScalarVariable': # FMI 2.0 only
                self.current_port = FMUPort()
                self.current_port.push_attrs(attrs)
            elif self.fmu.fmi_version == 2 and name in self.fmu.FMI2_TYPES:
                self.current_port.fmi_type = name
                self.current_port.push_attrs(attrs)
            elif self.fmu.fmi_version == 3 and name in self.fmu.FMI3_TYPES:
                self.current_port = FMUPort()
                self.current_port.fmi_type = name
                self.current_port.push_attrs(attrs)
            elif name == 'CoSimulation':
                self.operation.cosimulation_attrs(attrs)
            elif name == 'DefaultExperiment':
                self.operation.experiment_attrs(attrs)
            elif name == 'fmiModelDescription':
                self.fmu.fmi_version = int(float(attrs["fmiVersion"]))
                self.operation.fmi_attrs(attrs)
            elif name == 'Unknown': # FMI-2.0 only
                self.unknown_attrs(attrs)
            elif name == 'Output' or name == "ContinuousStateDerivative" or "InitialUnknown":
                self.handle_structure(attrs)

        except ManipulationSkipTag:
            self.skip_until = name
            return

        if self.current_port is None:
            if attrs:
                attrs_list = [f'{key}="{self.escape(value)}"' for (key, value) in attrs.items()]
                print(f"<{name}", " ".join(attrs_list), ">", end='', file=self.out)
            else:
                print(f"<{name}>", end='', file=self.out)

    def end_element(self, name):
        if self.skip_until:
            if self.skip_until == name:
                self.skip_until = None
            return
        else:
            if name == "ScalarVariable" or (self.fmu.fmi_version == 3 and name in FMU.FMI3_TYPES):
                try:
                    self.handle_port()
                    self.current_port.write_xml(self.fmu.fmi_version, self.out)
                except ManipulationSkipTag:
                    logger.info(f"Port '{self.current_port['name']}' is removed.")
                self.current_port = None

            elif self.current_port is None:
                print(f"</{name}>", end='', file=self.out)

    def char_data(self, data):
        if not self.skip_until:
            print(data, end='', file=self.out)

    def remove_port(self, name, vr):
        self.port_names_list.append(name)
        self.port_translation.append(None)
        self.port_removed_vr.add(vr)
        raise ManipulationSkipTag

    def keep_port(self, name):
        self.port_names_list.append(name)
        self.current_port_number += 1
        self.port_translation.append(self.current_port_number)

    def unknown_attrs(self, attrs):
        index = int(attrs['index']) - 1
        new_index = self.port_translation[index]
        if new_index:
            attrs['index'] = self.port_translation[int(attrs['index']) - 1]
        else:
            logger.warning(f"Removed port '{self.port_names_list[index]}' is involved in dependencies tree.")
            raise ManipulationSkipTag

    def handle_structure(self, attrs):
        try:
            vr = attrs['valueReference']
            if vr in self.port_removed_vr:
                raise ManipulationSkipTag
        except KeyError:
            return

        try:
            dependencies = attrs['dependencies']
            new_dependencies = []
            for dependency in dependencies.split(" "):
                if dependency in self.port_removed_vr:
                    logger.warning(f"Removed port 'vr={dependency}' was involved in dependencies tree.")
                else:
                    new_dependencies.append(dependency)
            attrs['dependencies'] = " ".join(new_dependencies)
        except KeyError:
            return

    def manipulate(self, descriptor_filename, apply_on=None):
        self.apply_on = apply_on
        with open(self.output_filename, "w", encoding="utf-8") as self.out, open(descriptor_filename, "rb") as file:
            self.parser.ParseFile(file)
        self.operation.closure()
        os.replace(self.output_filename, descriptor_filename)


class ManipulationSkipTag(Exception):
    """Exception: We need to skip every thing until matching closing tag"""


class OperationAbstract:
    """This class hold hooks called during parsing"""
    fmu: FMU = None

    def set_fmu(self, fmu):
        self.fmu = fmu

    def fmi_attrs(self, attrs):
        pass

    def cosimulation_attrs(self, attrs):
        pass

    def experiment_attrs(self, attrs):
        pass

    def port_attrs(self, fmu_port: FMUPort) -> int:
        """ return 0 to keep port, otherwise remove it"""
        return 0

    def closure(self):
        pass


class OperationSaveNamesToCSV(OperationAbstract):
    def __repr__(self):
        return f"Dump names into '{self.output_filename}'"

    def __init__(self, filename):
        self.output_filename = filename
        self.csvfile = open(filename, 'w', newline='')
        self.writer = csv.writer(self.csvfile, delimiter=';', quotechar="'", quoting=csv.QUOTE_MINIMAL)
        self.writer.writerow(['name', 'newName', 'valueReference', 'causality', 'variability', 'scalarType',
                              'startValue'])

    def closure(self):
        self.csvfile.close()

    def port_attrs(self, fmu_port: FMUPort) -> int:
        self.writer.writerow([fmu_port["name"],
                              fmu_port["name"],
                              fmu_port["valueReference"],
                              fmu_port.get("causality", "local"),
                              fmu_port.get("variability", "continuous"),
                              fmu_port.fmi_type,
                              fmu_port.get("start", "")])

        return 0


class OperationStripTopLevel(OperationAbstract):
    def __repr__(self):
        return "Remove Top Level Bus"

    def port_attrs(self, fmu_port):
        new_name = fmu_port['name'].split('.', 1)[-1]
        fmu_port['name'] = new_name
        return 0


class OperationMergeTopLevel(OperationAbstract):
    def __repr__(self):
        return "Merge Top Level Bus with signal names"

    def port_attrs(self, fmu_port):
        old = fmu_port['name']
        fmu_port['name'] = old.replace('.', '_', 1)
        return 0


class OperationRenameFromCSV(OperationAbstract):
    def __repr__(self):
        return f"Rename according to '{self.csv_filename}'"

    def __init__(self, csv_filename):
        self.csv_filename = csv_filename
        self.translations = {}

        try:
            with open(csv_filename, newline='') as csvfile:
                reader = csv.reader(csvfile, delimiter=';', quotechar="'")
                for row in reader:
                    self.translations[row[0]] = row[1]
        except FileNotFoundError:
            raise OperationError(f"file '{csv_filename}' is not found")
        except KeyError:
            raise OperationError(f"file '{csv_filename}' should contain two columns")

    def port_attrs(self, fmu_port):
        name = fmu_port['name']
        try:
            new_name = self.translations[fmu_port['name']]
        except KeyError:
            new_name = name  # if port is not in CSV file, keep old name

        if new_name:
            fmu_port['name'] = new_name
            return 0
        else:
            # we want to delete this name!
            return 1


class OperationRemoveRegexp(OperationAbstract):
    def __repr__(self):
        return f"Remove ports matching '{self.regex_string}'"

    def __init__(self, regex_string):
        self.regex_string = regex_string
        self.regex = re.compile(regex_string)
        self.current_port_number = 0
        self.port_translation = []

    def port_attrs(self, fmu_port):
        name = fmu_port['name']
        if self.regex.match(name):
            return 1  # Remove port
        else:
            return 0


class OperationKeepOnlyRegexp(OperationAbstract):
    def __repr__(self):
        return f"Keep only ports matching '{self.regex_string}'"

    def __init__(self, regex_string):
        self.regex_string = regex_string
        self.regex = re.compile(regex_string)

    def port_attrs(self, fmu_port):
        name = fmu_port['name']
        if self.regex.match(name):
            return 0
        else:
            return 1  # Remove port


class OperationSummary(OperationAbstract):
    def __init__(self):
        self.nb_port_per_causality = {}

    def __repr__(self):
        return f"FMU Summary"

    def fmi_attrs(self, attrs):
        logger.info(f"| fmu filename = {self.fmu.fmu_filename}")
        logger.info(f"| temporary directory = {self.fmu.tmp_directory}")
        hash_md5 = hashlib.md5()
        with open(self.fmu.fmu_filename, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        digest = hash_md5.hexdigest()
        logger.info(f"| MD5Sum = {digest}")

        logger.info(f"|\n| FMI properties: ")
        for (k, v) in attrs.items():
            logger.info(f"|  - {k} = {v}")
        logger.info(f"|")

    def cosimulation_attrs(self, attrs):
        logger.info("| Co-Simulation capabilities: ")
        for (k, v) in attrs.items():
            logger.info(f"|  - {k} = {v}")
        logger.info(f"|")

    def experiment_attrs(self, attrs):
        logger.info("| Default Experiment values: ")
        for (k, v) in attrs.items():
            logger.info(f"|  - {k} = {v}")
        logger.info(f"|")

    def port_attrs(self, fmu_port) -> int:
        causality = fmu_port.get("causality", "local")

        try:
            self.nb_port_per_causality[causality] += 1
        except KeyError:
            self.nb_port_per_causality[causality] = 1

        return 0

    def closure(self):
        logger.info("| Supported platforms: ")
        try:
            for platform in os.listdir(os.path.join(self.fmu.tmp_directory, "binaries")):
                logger.info(f"|  - {platform}")
        except FileNotFoundError:
            pass  # no binaries

        if os.path.isdir(os.path.join(self.fmu.tmp_directory, "sources")):
            logger.info(f"|  - RT (sources available)")

        resource_dir = os.path.join(self.fmu.tmp_directory, "resources")
        if os.path.isdir(resource_dir):
            logger.info("|\n| Embedded resources:")
            for resource in os.listdir(resource_dir):
                logger.info(f"|  - {resource}")

        extra_dir = os.path.join(self.fmu.tmp_directory, "extra")
        if os.path.isdir(extra_dir):
            logger.info("|\n| Additional (meta-)data:")
            for extra in os.listdir(extra_dir):
                logger.info(f"|  - {extra}")

        logger.info("|\n| Number of ports")
        for causality, nb_ports in self.nb_port_per_causality.items():
            logger.info(f"|  {causality} : {nb_ports}")

        logger.info("|\n| [End of report]")


class OperationRemoveSources(OperationAbstract):
    def __repr__(self):
        return f"Remove sources"

    def cosimulation_attrs(self, attrs):
        try:
            shutil.rmtree(os.path.join(self.fmu.tmp_directory, "sources"))
        except FileNotFoundError:
            logger.info("This FMU does not embed sources.")


class OperationTrimUntil(OperationAbstract):
    def __init__(self, separator):
        self.separator = separator

    def __repr__(self):
        return f"Trim names until (and including) '{self.separator}'"

    def port_attrs(self, fmu_port) -> int:
        name = fmu_port['name']
        try:
            fmu_port['name'] = name[name.index(self.separator)+len(self.separator):-1]
        except KeyError:
            pass  # no separator

        return 0


class OperationError(Exception):
    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return self.reason
