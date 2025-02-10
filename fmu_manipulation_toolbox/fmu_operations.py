import csv
import html
import os
import re
import shutil
import tempfile
import xml.parsers.expat
import zipfile
import hashlib
from pathlib import Path


class FMU:
    """Unpack and Repack facilities for FMU package. Once unpacked, we can process Operation on
    modelDescription.xml file."""
    def __init__(self, fmu_filename):
        self.fmu_filename = fmu_filename
        self.tmp_directory = tempfile.mkdtemp()

        try:
            with zipfile.ZipFile(self.fmu_filename) as zin:
                zin.extractall(self.tmp_directory)
        except FileNotFoundError:
            raise FMUException(f"'{fmu_filename}' does not exist")
        self.descriptor_filename = os.path.join(self.tmp_directory, "modelDescription.xml")
        if not os.path.isfile(self.descriptor_filename):
            raise FMUException(f"'{fmu_filename}' is not valid: {self.descriptor_filename} not found")

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


class FMUException(Exception):
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
        self.skip_until = None
        self.operation.set_fmu(fmu)

        self.current_port = 0
        self.port_translation = []
        self.port_name = []
        self.apply_on = None

    @staticmethod
    def escape(value):
        if isinstance(value, str):
            return html.escape(html.unescape(value))
        else:
            return value

    def start_element(self, name, attrs):
        if self.skip_until:
            return
        try:
            if name == 'ScalarVariable':
                causality = OperationAbstract.scalar_get_causality(attrs)
                if not self.apply_on or causality in self.apply_on:
                    if self.operation.scalar_attrs(attrs):
                        self.remove_port(attrs['name'])
                    else:
                        self.keep_port(attrs['name'])
                else:  # Keep ScalarVariable as it is.
                    self.keep_port(attrs['name'])
            elif name == 'CoSimulation':
                self.operation.cosimulation_attrs(attrs)
            elif name == 'DefaultExperiment':
                self.operation.experiment_attrs(attrs)
            elif name == 'fmiModelDescription':
                self.operation.fmi_attrs(attrs)
            elif name == 'Unknown':
                self.unknown_attrs(attrs)
            elif name in ('Real', 'Integer', 'String', 'Boolean', 'Enumeration'):
                self.operation.scalar_type(name, attrs)

        except ManipulationSkipTag:
            self.skip_until = name
            return

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
            print(f"</{name}>", end='', file=self.out)

    def char_data(self, data):
        if not self.skip_until:
            print(data, end='', file=self.out)

    def remove_port(self, name):
        self.port_name.append(name)
        self.port_translation.append(None)
        raise ManipulationSkipTag

    def keep_port(self, name):
        self.port_name.append(name)
        self.current_port += 1
        self.port_translation.append(self.current_port)

    def unknown_attrs(self, attrs):
        index = int(attrs['index']) - 1
        new_index = self.port_translation[index]
        if new_index:
            attrs['index'] = self.port_translation[int(attrs['index']) - 1]
        else:
            print(f"WARNING: Removed port '{self.port_name[index]}' is involved in dependencies tree.")
            raise ManipulationSkipTag

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

    def scalar_attrs(self, attrs) -> int:
        """ return 0 to keep port, otherwise remove it"""
        return 0

    def cosimulation_attrs(self, attrs):
        pass

    def experiment_attrs(self, attrs):
        pass

    def scalar_type(self, type_name, attrs):
        pass

    def closure(self):
        pass

    @staticmethod
    def scalar_get_causality(attrs) -> str:
        try:
            causality = attrs['causality']
        except KeyError:
            causality = 'local'  # Default value according to FMI Specifications.

        return causality


class OperationSaveNamesToCSV(OperationAbstract):
    def __repr__(self):
        return f"Dump names into '{self.output_filename}'"

    def __init__(self, filename):
        self.output_filename = filename
        self.csvfile = open(filename, 'w', newline='')
        self.writer = csv.writer(self.csvfile, delimiter=';', quotechar="'", quoting=csv.QUOTE_MINIMAL)
        self.writer.writerow(['name', 'newName', 'valueReference', 'causality', 'variability', 'scalarType',
                              'startValue'])
        self.name = None
        self.vr = None
        self.variability = None
        self.causality = None

    def reset(self):
        self.name = None
        self.vr = None
        self.variability = None
        self.causality = None

    def closure(self):
        self.csvfile.close()

    def scalar_attrs(self, attrs):
        self.name = attrs['name']
        self.vr = attrs['valueReference']
        self.causality = self.scalar_get_causality(attrs)

        try:
            self.variability = attrs['variability']
        except KeyError:
            self.variability = 'continuous'   # Default value according to FMI Specifications.

        return 0

    def scalar_type(self, type_name, attrs):
        if "start" in attrs:
            start = attrs["start"]
        else:
            start = ""
        self.writer.writerow([self.name, self.name, self.vr, self.causality, self.variability, type_name, start])
        self.reset()


class OperationStripTopLevel(OperationAbstract):
    def __repr__(self):
        return "Remove Top Level Bus"

    def scalar_attrs(self, attrs):
        new_name = attrs['name'].split('.', 1)[-1]
        attrs['name'] = new_name
        return 0


class OperationMergeTopLevel(OperationAbstract):
    def __repr__(self):
        return "Merge Top Level Bus with signal names"

    def scalar_attrs(self, attrs):
        old = attrs['name']
        attrs['name'] = old.replace('.', '_', 1)
        return 0


class OperationRenameFromCSV(OperationAbstract):
    def __repr__(self):
        return f"Rename according to '{self.csv_filename}'"

    def __init__(self, csv_filename):
        self.csv_filename = csv_filename
        self.translations = {}
        self.current_port = 0
        self.port_translation = []
        try:
            with open(csv_filename, newline='') as csvfile:
                reader = csv.reader(csvfile, delimiter=';', quotechar="'")
                for row in reader:
                    self.translations[row[0]] = row[1]
        except FileNotFoundError:
            raise OperationException(f"file '{csv_filename}' is not found")
        except KeyError:
            raise OperationException(f"file '{csv_filename}' should contain two columns")

    def scalar_attrs(self, attrs):
        name = attrs['name']
        try:
            new_name = self.translations[attrs['name']]
        except KeyError:
            new_name = name  # if port is not in CSV file, keep old name

        if new_name:
            attrs['name'] = new_name
            return 0
        else:
            # we want to delete this name!
            return 1


class OperationAddRemotingWinAbstract(OperationAbstract):
    bitness_from = None
    bitness_to = None

    def __repr__(self):
        return f"Add '{self.bitness_to}' remoting on '{self.bitness_from}' FMU"

    def cosimulation_attrs(self, attrs):
        fmu_bin = {
            "win32":  os.path.join(self.fmu.tmp_directory, "binaries", f"win32"),
            "win64": os.path.join(self.fmu.tmp_directory, "binaries", f"win64"),
        }

        if not os.path.isdir(fmu_bin[self.bitness_from]):
            raise OperationException(f"{self.bitness_from} interface does not exist")

        if os.path.isdir(fmu_bin[self.bitness_to]):
            print(f"INFO: {self.bitness_to} already exists. Add front-end.")
            shutil.move(os.path.join(fmu_bin[self.bitness_to], attrs['modelIdentifier'] + ".dll"),
                        os.path.join(fmu_bin[self.bitness_to], attrs['modelIdentifier'] + "-remoted.dll"))
        else:
            os.mkdir(fmu_bin[self.bitness_to])

        from_path = Path(__file__).parent / "resources" / self.bitness_to
        shutil.copyfile(from_path / "client_sm.dll",
                        Path(fmu_bin[self.bitness_to]) / Path(attrs['modelIdentifier']).with_suffix(".dll"))

        shutil.copyfile(from_path / "server_sm.exe",
                        Path(fmu_bin[self.bitness_from]) / "server_sm.exe")

        shutil.copyfile(Path(__file__).parent / "resources" / "license.txt",
                        Path(fmu_bin[self.bitness_to]) / "license.txt")


class OperationAddRemotingWin64(OperationAddRemotingWinAbstract):
    bitness_from = "win32"
    bitness_to = "win64"


class OperationAddFrontendWin32(OperationAddRemotingWinAbstract):
    bitness_from = "win32"
    bitness_to = "win32"


class OperationAddFrontendWin64(OperationAddRemotingWinAbstract):
    bitness_from = "win64"
    bitness_to = "win64"


class OperationAddRemotingWin32(OperationAddRemotingWinAbstract):
    bitness_from = "win64"
    bitness_to = "win32"


class OperationRemoveRegexp(OperationAbstract):
    def __repr__(self):
        return f"Remove ports matching '{self.regex_string}'"

    def __init__(self, regex_string):
        self.regex_string = regex_string
        self.regex = re.compile(regex_string)
        self.current_port = 0
        self.port_translation = []

    def scalar_attrs(self, attrs):
        name = attrs['name']
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

    def scalar_attrs(self, attrs):
        name = attrs['name']
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
        print(f"| fmu filename = {self.fmu.fmu_filename}")
        print(f"| temporary directory = {self.fmu.tmp_directory}")
        hash_md5 = hashlib.md5()
        with open(self.fmu.fmu_filename, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        digest = hash_md5.hexdigest()
        print(f"| MD5Sum = {digest}")

        print(f"|\n| FMI properties: ")
        for (k, v) in attrs.items():
            print(f"|  - {k} = {v}")
        print(f"|")

    def cosimulation_attrs(self, attrs):
        print("| Co-Simulation capabilities: ")
        for (k, v) in attrs.items():
            print(f"|  - {k} = {v}")
        print(f"|")

    def experiment_attrs(self, attrs):
        print("| Default Experiment values: ")
        for (k, v) in attrs.items():
            print(f"|  - {k} = {v}")
        print(f"|")

    def scalar_attrs(self, attrs) -> int:
        causality = self.scalar_get_causality(attrs)

        try:
            self.nb_port_per_causality[causality] += 1
        except KeyError:
            self.nb_port_per_causality[causality] = 1

        return 0

    def closure(self):
        print("| Supported platforms: ")
        try:
            for platform in os.listdir(os.path.join(self.fmu.tmp_directory, "binaries")):
                print(f"|  - {platform}")
        except FileNotFoundError:
            pass  # no binaries

        if os.path.isdir(os.path.join(self.fmu.tmp_directory, "sources")):
            print(f"|  - RT (sources available)")

        resource_dir = os.path.join(self.fmu.tmp_directory, "resources")
        if os.path.isdir(resource_dir):
            print("|\n| Embedded resources:")
            for resource in os.listdir(resource_dir):
                print(f"|  - {resource}")

        extra_dir = os.path.join(self.fmu.tmp_directory, "extra")
        if os.path.isdir(extra_dir):
            print("|\n| Additional (meta-)data:")
            for extra in os.listdir(extra_dir):
                print(f"|  - {extra}")

        print("|\n| Number of signals")
        for causality, nb_ports in self.nb_port_per_causality.items():
            print(f"|  {causality} : {nb_ports}")

        print("|\n| [End of report]")


class OperationRemoveSources(OperationAbstract):
    def __repr__(self):
        return f"Remove sources"

    def cosimulation_attrs(self, attrs):
        try:
            shutil.rmtree(os.path.join(self.fmu.tmp_directory, "sources"))
        except FileNotFoundError:
            print("This FMU does not embed sources.")


class OperationTrimUntil(OperationAbstract):
    def __init__(self, separator):
        self.separator = separator

    def __repr__(self):
        return f"Trim names until (and including) '{self.separator}'"

    def scalar_attrs(self, attrs) -> int:
        name = attrs['name']
        try:
            attrs['name'] = name[name.index(self.separator)+len(self.separator):-1]
        except KeyError:
            pass  # no separator

        return 0


class OperationException(Exception):
    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return self.reason
