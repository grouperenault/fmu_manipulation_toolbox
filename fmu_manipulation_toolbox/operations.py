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
    """Unpack and repack facilities for FMU archives.

    Extracts an FMU (`.fmu` zip archive) into a temporary directory so that
    operations can be applied to its `modelDescription.xml` descriptor.
    After manipulation, the FMU can be repacked into a new archive.

    Attributes:
        FMI2_TYPES (tuple[str, ...]): FMI 2.0 scalar variable type names.
        FMI3_TYPES (tuple[str, ...]): FMI 3.0 variable type names.
        fmu_filename (str): Path to the original `.fmu` file.
        tmp_directory (str): Path to the temporary extraction directory.
        fmi_version (int | None): Detected FMI version (`2` or `3`), set
            during parsing.
        descriptor_filename (str): Path to the extracted `modelDescription.xml`.

    Raises:
        FMUError: If the file does not exist or is not a valid FMU.
    """

    FMI2_TYPES = ('Real', 'Integer', 'String', 'Boolean', 'Enumeration')
    FMI3_TYPES = ('Float64', 'Float32',
                  'Int8', 'UInt8', 'Int16', 'UInt16', 'Int32', 'UInt32', 'Int64', 'UInt64',
                  'String', 'Boolean', 'Enumeration', 'Clock', 'Binary')

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
        """Save a copy of the current `modelDescription.xml` to a file.

        Args:
            filename (str): Destination path for the descriptor copy.
        """
        shutil.copyfile(os.path.join(self.tmp_directory, "modelDescription.xml"), filename)

    def repack(self, filename):
        """Repack the (possibly modified) FMU into a new `.fmu` archive.

        Args:
            filename (str): Output path for the repacked FMU.
        """
        with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as zout:
            for root, dirs, files in os.walk(self.tmp_directory):
                for file in files:
                    zout.write(os.path.join(root, file),
                               os.path.relpath(os.path.join(root, file), self.tmp_directory))
        # TODO: Add check on output file

    def apply_operation(self, operation, apply_on=None):
        """Apply an operation to the FMU's `modelDescription.xml`.

        Parses the descriptor, invokes the operation's callbacks for each
        element, and writes back the modified descriptor.

        Args:
            operation (OperationAbstract): The operation to apply.
            apply_on (list[str] | None): If set, only apply the operation
                to ports with a causality in this list.
        """
        manipulation = Manipulation(operation, self)
        manipulation.manipulate(self.descriptor_filename, apply_on)


class FMUPort:
    """Represents a port (variable) parsed from `modelDescription.xml`.

    Stores the XML attributes from one or more levels of the port definition.
    For FMI 2.0, this includes the `<ScalarVariable>` attributes and the
    child type element (e.g. `<Real>`). For FMI 3.0, all attributes are
    on the type element itself.

    Supports dict-like access to attributes across all levels.

    Attributes:
        fmi_type (str | None): The FMI type name (e.g. `"Real"`, `"Float64"`).
        attrs_list (list[dict[str, str]]): Stacked attribute dictionaries,
            one per XML nesting level.
        dimension (int | None): Array dimension, if applicable.
    """

    def __init__(self):
        self.fmi_type = None
        self.attrs_list: List[Dict] = []
        self.dimension = None

    def dict_level(self, nb):
        """Format one level of attributes as an XML attribute string.

        Args:
            nb (int): Index into `attrs_list`.

        Returns:
            str: Space-separated `key="value"` pairs with HTML-escaped values.
        """
        return " ".join([f'{key}="{Manipulation.escape(value)}"' for key, value in self.attrs_list[nb].items()])

    def write_xml(self, fmi_version: int, file):
        """Write the port definition as XML to a file.

        Args:
            fmi_version (int): FMI version (`2` or `3`).
            file: Writable text file handle.

        Raises:
            FMUError: If the FMI version is not supported.
        """
        if fmi_version == 2:
            print(f"    <ScalarVariable {self.dict_level(0)}>", file=file)
            print(f"      <{self.fmi_type} {self.dict_level(1)}/>", file=file)
            print(f"    </ScalarVariable>", file=file)
        elif fmi_version == 3:
            start_value = self.get("start", "")
            if self.fmi_type in ("String", "Binary") and start_value:
                print(f"    <{self.fmi_type} {self.dict_level(0)}>", file=file)
                print(f'      <Start value="{start_value}"/>', file=file)
                print(f"    </{self.fmi_type}>", file=file)
            else:
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
        """Push a new attribute dictionary onto the stack.

        Args:
            attrs (dict[str, str]): XML attributes from a nested element.
        """
        self.attrs_list.append(attrs)


class FMUError(Exception):
    """Exception raised for FMU-related errors.

    Attributes:
        reason (str): Human-readable description of the error.
    """

    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return self.reason


class Manipulation:
    """SAX-based parser that applies an operation to `modelDescription.xml`.

    Parses the XML descriptor using `xml.parsers.expat`, invokes the
    operation's callbacks for each relevant element, and writes back
    the modified XML. Handles port renumbering and dependency tree
    updates when ports are removed.

    Attributes:
        output_filename (str): Path to the temporary output file.
        operation (OperationAbstract): The operation being applied.
        fmu (FMU): The FMU being manipulated.
        current_port (FMUPort | None): The port currently being parsed.
        current_port_number (int): Running count of kept ports (1-based).
        port_translation (list[int | None]): Maps original port indices to
            new indices, or `None` for removed ports.
        port_names_list (list[str]): Names of all encountered ports.
        port_removed_vr (set[str]): Value references of removed ports.
    """

    TAGS_MODEL_STRUCTURE = ("InitialUnknowns", "Derivatives", "Outputs")

    def __init__(self, operation, fmu):
        (fd, self.output_filename) = tempfile.mkstemp()
        os.close(fd)  # File will be re-opened later
        self.out = None
        self.operation = operation
        self.parser = xml.parsers.expat.ParserCreate()
        self.parser.StartElementHandler = self.start_element
        self.parser.EndElementHandler = self.end_element
        self.parser.CharacterDataHandler = self.char_data

        # used for filter
        self.skip_until: Optional[str] = None

        # used to remove empty sections
        self.delayed_tag = None
        self.delayed_tag_open = False

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
        """HTML-escape a string value for safe XML output.

        Args:
            value (str): The value to escape.

        Returns:
            str: The escaped value. Non-string values are returned unchanged.
        """
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
                if self.current_port: # <Enumeration> can be found before port definition. Ignored.
                    self.current_port.fmi_type = name
                    self.current_port.push_attrs(attrs)
            elif self.fmu.fmi_version == 3 and name in self.fmu.FMI3_TYPES:
                self.current_port = FMUPort()
                self.current_port.fmi_type = name
                self.current_port.push_attrs(attrs)
            elif self.fmu.fmi_version == 3 and name == "Start":
                self.current_port.push_attrs({"start": attrs.get("value", "")})
            elif name == 'CoSimulation':
                self.operation.cosimulation_attrs(attrs)
            elif name == 'DefaultExperiment':
                self.operation.experiment_attrs(attrs)
            elif name == 'fmiModelDescription':
                self.fmu.fmi_version = int(float(attrs["fmiVersion"]))
                self.operation.fmi_attrs(attrs)
            elif name == 'Unknown': # FMI-2.0 only
                self.unknown_attrs(attrs)
            elif name == 'Output' or name == "ContinuousStateDerivative" or "InitialUnknown": #  FMI-3.0 only
                self.handle_structure(attrs)

        except ManipulationSkipTag:
            self.skip_until = name
            return

        if self.current_port is None:
            if self.delayed_tag and not self.delayed_tag_open:
                print(f"<{self.delayed_tag}>", end='', file=self.out)
                self.delayed_tag_open = True

            if attrs:
                attrs_list = [f'{key}="{self.escape(value)}"' for (key, value) in attrs.items()]
                print(f"<{name}", " ".join(attrs_list), ">", end='', file=self.out)
            else:
                if name in self.TAGS_MODEL_STRUCTURE:
                    self.delayed_tag = name
                    self.delayed_tag_open = False
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
                if self.delayed_tag and name == self.delayed_tag:
                    if self.delayed_tag_open:
                        print(f"</{self.delayed_tag}>", end='', file=self.out)
                    else:
                        logger.debug(f"Remove tag <{self.delayed_tag}> from modelDescription.xml")
                    self.delayed_tag = None
                else:
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
        index = int(attrs['index'])
        new_index = self.port_translation[index-1]
        if new_index is not None:
            attrs['index'] = str(new_index)
            if attrs.get('dependencies', ""):
                if 'dependenciesKind' in attrs:
                    new_dependencies = []
                    new_kinds = []
                    for dependency, kind in zip(attrs['dependencies'].split(' '), attrs['dependenciesKind'].split(' ')):
                        new_dependency = self.port_translation[int(dependency)-1]
                        if new_dependency is not None:
                            new_dependencies.append(str(new_dependency))
                            new_kinds.append(kind)
                    if new_dependencies:
                        attrs['dependencies'] = " ".join(new_dependencies)
                        attrs['dependenciesKind'] = " ".join(new_kinds)
                    else:
                        attrs.pop('dependencies')
                        attrs.pop('dependenciesKind')
                else:
                    new_dependencies = []
                    for dependency in attrs['dependencies'].split(' '):
                        new_dependency = self.port_translation[int(dependency)-1]
                        if new_dependency is not None:
                            new_dependencies.append(str(new_dependency))
                    if new_dependencies:
                        attrs['dependencies'] = " ".join(new_dependencies)
                    else:
                        attrs.pop('dependencies')
        else:
            logger.warning(f"Removed port '{self.port_names_list[index-1]}' is involved in dependencies tree.")
            raise ManipulationSkipTag

    def handle_structure(self, attrs):
        try:
            vr = attrs['valueReference']
            if vr in self.port_removed_vr:
                logger.warning(f"Removed port vr={vr} is involved in dependencies tree.")
                raise ManipulationSkipTag
        except KeyError:
            return

        if attrs.get('dependencies', ""):
            if 'dependenciesKind' in attrs:
                new_dependencies = []
                new_kinds = []
                for dependency, kind in zip(attrs['dependencies'].split(' '), attrs['dependenciesKind'].split(' ')):
                    if dependency not in self.port_removed_vr:
                        new_dependencies.append(dependency)
                        new_kinds.append(kind)
                if new_dependencies:
                    attrs['dependencies'] = " ".join(new_dependencies)
                    attrs['dependenciesKind'] = " ".join(new_kinds)
                else:
                    attrs.pop('dependencies')
                    attrs.pop('dependenciesKind')
            else:
                new_dependencies = []
                for dependency in attrs['dependencies'].split(' '):
                    if dependency not in self.port_removed_vr:
                        new_dependencies.append(dependency)
                if new_dependencies:
                    attrs['dependencies'] = " ".join(new_dependencies)
                else:
                    attrs.pop('dependencies')

    def manipulate(self, descriptor_filename, apply_on=None):
        """Parse and rewrite the descriptor file.

        Args:
            descriptor_filename (str): Path to the `modelDescription.xml` file.
                The file is modified in place.
            apply_on (list[str] | None): If set, only process ports with a
                causality in this list.
        """
        self.apply_on = apply_on
        with open(self.output_filename, "w", encoding="utf-8") as self.out, open(descriptor_filename, "rb") as file:
            self.parser.ParseFile(file)
        self.operation.closure()
        os.replace(self.output_filename, descriptor_filename)


class ManipulationSkipTag(Exception):
    """Internal exception used to skip XML content until a matching closing tag.

    Raised during SAX parsing to signal that the current element and all
    its children should be omitted from the output.
    """


class OperationAbstract:
    """Base class for all FMU manipulation operations.

    Subclass this to implement custom operations on FMU descriptors. The
    methods act as callbacks invoked during SAX parsing of
    `modelDescription.xml`.

    Attributes:
        fmu (FMU | None): The FMU being processed, set via `set_fmu`.
    """

    fmu: FMU = None

    def set_fmu(self, fmu):
        """Bind this operation to an FMU.

        Called automatically before parsing begins.

        Args:
            fmu (FMU): The FMU to operate on.
        """
        self.fmu = fmu

    def fmi_attrs(self, attrs):
        """Called when the `<fmiModelDescription>` element is encountered.

        Args:
            attrs (dict[str, str]): XML attributes of the root element.
        """
        pass

    def cosimulation_attrs(self, attrs):
        """Called when the `<CoSimulation>` element is encountered.

        Args:
            attrs (dict[str, str]): XML attributes of the co-simulation element.
        """
        pass

    def experiment_attrs(self, attrs):
        """Called when the `<DefaultExperiment>` element is encountered.

        Args:
            attrs (dict[str, str]): XML attributes of the default experiment.
        """
        pass

    def port_attrs(self, fmu_port: FMUPort) -> int:
        """Called for each port (variable) in the descriptor.

        Override this to inspect or modify port attributes.

        Args:
            fmu_port (FMUPort): The port being processed. Attributes can be
                modified in place.

        Returns:
            int: `0` to keep the port, non-zero to remove it.
        """
        return 0

    def closure(self):
        """Called after the descriptor has been fully parsed.

        Override this for post-processing or cleanup.
        """
        pass


class OperationSaveNamesToCSV(OperationAbstract):
    """Export all port names and metadata to a CSV file.

    Generates a semicolon-delimited CSV with columns: `name`, `newName`,
    `valueReference`, `causality`, `variability`, `scalarType`, `startValue`.

    The resulting file can be edited and used with
    [OperationRenameFromCSV][fmu_manipulation_toolbox.operations.OperationRenameFromCSV]
    to rename or remove ports.

    Attributes:
        output_filename (str): Path to the output CSV file.
    """

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
    """Remove the top-level bus prefix from all port names.

    Strips everything before and including the first `"."` separator.
    For example, `"Bus1.signal_name"` becomes `"signal_name"`.
    """

    def __repr__(self):
        return "Remove Top Level Bus"

    def port_attrs(self, fmu_port):
        new_name = fmu_port['name'].split('.', 1)[-1]
        fmu_port['name'] = new_name
        return 0


class OperationMergeTopLevel(OperationAbstract):
    """Merge the top-level bus prefix into port names by replacing `"."` with `"_"`.

    Only the first dot is replaced. For example, `"Bus1.signal_name"` becomes
    `"Bus1_signal_name"`.
    """

    def __repr__(self):
        return "Merge Top Level Bus with signal names"

    def port_attrs(self, fmu_port):
        old = fmu_port['name']
        fmu_port['name'] = old.replace('.', '_', 1)
        return 0


class OperationRenameFromCSV(OperationAbstract):
    """Rename or remove ports according to a CSV mapping file.

    Reads a semicolon-delimited CSV where column 0 is the original name
    and column 1 is the new name. If the new name is empty, the port is
    removed. Ports not listed in the CSV are kept unchanged.

    Attributes:
        csv_filename (str): Path to the CSV mapping file.
        translations (dict[str, str]): Mapping from original to new names.

    Raises:
        OperationError: If the CSV file is not found or malformed.
    """

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
    """Remove all ports whose names match a regular expression.

    Args:
        regex_string (str): Regular expression pattern. Ports with names
            matching this pattern (from the start) are removed.

    Attributes:
        regex_string (str): The original regex pattern string.
        regex (re.Pattern): Compiled regular expression.
    """

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
    """Keep only ports whose names match a regular expression; remove all others.

    Args:
        regex_string (str): Regular expression pattern. Only ports with names
            matching this pattern (from the start) are kept.

    Attributes:
        regex_string (str): The original regex pattern string.
        regex (re.Pattern): Compiled regular expression.
    """

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
    """Log a detailed summary of the FMU contents.

    Reports FMI properties, co-simulation capabilities, default experiment
    values, supported platforms, embedded resources, and port counts
    grouped by causality.

    Attributes:
        nb_port_per_causality (dict[str, int]): Count of ports per causality.
    """

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
        logger.info(f"|")
        logger.info(f"| FMI properties: ")
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
            logger.info("|")
            logger.info("| Embedded resources:")
            for resource in os.listdir(resource_dir):
                logger.info(f"|  - {resource}")

        extra_dir = os.path.join(self.fmu.tmp_directory, "extra")
        if os.path.isdir(extra_dir):
            logger.info("|")
            logger.info("| Additional (meta-)data:")
            for extra in os.listdir(extra_dir):
                logger.info(f"|  - {extra}")

        logger.info("|")
        logger.info("| Number of ports")
        for causality, nb_ports in self.nb_port_per_causality.items():
            logger.info(f"|  {causality} : {nb_ports}")

        logger.info("|")
        logger.info("| [End of report]")


class OperationRemoveSources(OperationAbstract):
    """Remove the `sources/` directory from the FMU.

    Strips the embedded C/C++ source files that some FMUs include for
    recompilation on the target platform.
    """

    def __repr__(self):
        return f"Remove sources"

    def cosimulation_attrs(self, attrs):
        try:
            shutil.rmtree(os.path.join(self.fmu.tmp_directory, "sources"))
        except FileNotFoundError:
            logger.info("This FMU does not embed sources.")


class OperationTrimUntil(OperationAbstract):
    """Trim port names up to and including a separator string.

    For example, with separator `"__"`, the name `"prefix__signal"` becomes
    `"signal"`.

    Args:
        separator (str): The separator string to search for in port names.

    Attributes:
        separator (str): The separator string.
    """

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
    """Exception raised for operation-related errors.

    Attributes:
        reason (str): Human-readable description of the error.
    """

    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return self.reason
