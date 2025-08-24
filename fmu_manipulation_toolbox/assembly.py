import csv
import json
import logging
from typing import *
from pathlib import Path
import uuid
import xml.parsers.expat
import zipfile

from .container import FMUContainer, AutoWired

logger = logging.getLogger("fmu_manipulation_toolbox")


class Port:
    def __init__(self, fmu_name: str, port_name: str):
        self.fmu_name = fmu_name
        self.port_name = port_name

    def __hash__(self):
        return hash(f"{self.fmu_name}/{self.port_name}")

    def __eq__(self, other):
        return str(self) == str(other)

    def __str__(self):
        return f"{self.fmu_name}/{self.port_name}"


class Connection:
    def __init__(self, from_port: Port, to_port: Port):
        self.from_port = from_port
        self.to_port = to_port

    def __str__(self):
        return f"{self.from_port} -> {self.to_port}"


class AssemblyNode:
    def __init__(self, name: Optional[str], step_size: float = None, mt=False, profiling=False, sequential=False,
                 auto_link=True, auto_input=True, auto_output=True, auto_parameter=False, auto_local=False):
        self.name = name
        if step_size:
            try:
                self.step_size = float(step_size)
            except ValueError:
                logger.warning(f"Step size '{step_size}' is incorrect format.")
                self.step_size = None
        else:
            self.step_size = None
        self.mt = mt
        self.profiling = profiling
        self.sequential = sequential
        self.auto_link = auto_link
        self.auto_input = auto_input
        self.auto_output = auto_output
        self.auto_parameter = auto_parameter
        self.auto_local = auto_local

        self.parent: Optional[AssemblyNode] = None
        self.children: Dict[str, AssemblyNode] = {}     # sub-containers
        self.fmu_names_list: List[str] = []             # FMUs contained at this level (ordered list)
        self.input_ports: Dict[Port, str] = {}          # value is input port name, key is the source
        self.output_ports: Dict[Port, str] = {}         # value is output port name, key is the origin
        self.start_values: Dict[Port, str] = {}
        self.drop_ports: List[Port] = []
        self.links: List[Connection] = []

    def add_sub_node(self, sub_node):
        if sub_node.name is None:
            sub_node.name = str(uuid.uuid4())+".fmu"

        if sub_node.parent is not None:
            raise AssemblyError(f"Internal Error: AssemblyNode {sub_node.name} is already parented.")

        if sub_node.name in self.children:
            raise AssemblyError(f"Internal Error: AssemblyNode {sub_node.name} is already child of {self.name}")

        sub_node.parent = self
        if sub_node.name not in self.fmu_names_list:
            self.fmu_names_list.append(sub_node.name)
        self.children[sub_node.name] = sub_node

    def add_fmu(self, fmu_name: str):
        if fmu_name not in self.fmu_names_list:
            self.fmu_names_list.append(fmu_name)

    def add_input(self, from_port_name: str, to_fmu_filename: str, to_port_name: str):
        self.input_ports[Port(to_fmu_filename, to_port_name)] = from_port_name

    def add_output(self, from_fmu_filename: str, from_port_name: str, to_port_name: str):
        self.output_ports[Port(from_fmu_filename, from_port_name)] = to_port_name

    def add_drop_port(self, fmu_filename: str, port_name: str):
        self.drop_ports.append(Port(fmu_filename, port_name))

    def add_link(self, from_fmu_filename: str, from_port_name: str, to_fmu_filename: str, to_port_name: str):
        self.links.append(Connection(Port(from_fmu_filename, from_port_name),
                          Port(to_fmu_filename, to_port_name)))

    def add_start_value(self, fmu_filename: str, port_name: str, value: str):
        self.start_values[Port(fmu_filename, port_name)] = value

    def make_fmu(self, fmu_directory: Path, debug=False, description_pathname=None, fmi_version=2):
        for node in self.children.values():
            node.make_fmu(fmu_directory, debug=debug, fmi_version=fmi_version)

        identifier = str(Path(self.name).stem)
        container = FMUContainer(identifier, fmu_directory, description_pathname=description_pathname,
                                 fmi_version=fmi_version)

        for fmu_name in self.fmu_names_list:
            container.get_fmu(fmu_name)

        for port, source in self.input_ports.items():
            container.add_input(source, port.fmu_name, port.port_name)

        for port, target in self.output_ports.items():
            container.add_output(port.fmu_name, port.port_name, target)

        for link in self.links:
            container.add_link(link.from_port.fmu_name, link.from_port.port_name,
                               link.to_port.fmu_name, link.to_port.port_name)

        for drop in self.drop_ports:
            container.drop_port(drop.fmu_name, drop.port_name)

        for port, value in self.start_values.items():
            container.add_start_value(port.fmu_name, port.port_name, value)

        wired = container.add_implicit_rule(auto_input=self.auto_input,
                                            auto_output=self.auto_output,
                                            auto_link=self.auto_link,
                                            auto_parameter=self.auto_parameter,
                                            auto_local=self.auto_local)
        for input_rule in wired.rule_input:
            self.add_input(input_rule[0], input_rule[1], input_rule[2])
        for output_rule in wired.rule_output:
            self.add_output(output_rule[0], output_rule[1], output_rule[2])
        for link_rule in wired.rule_link:
            self.add_link(link_rule[0], link_rule[1], link_rule[2], link_rule[3])

        container.make_fmu(self.name, self.step_size, mt=self.mt, profiling=self.profiling, sequential=self.sequential,
                           debug=debug)

        for node in self.children.values():
            logger.info(f"Deleting transient FMU Container '{node.name}'")
            (fmu_directory / node.name).unlink()

    def get_final_from(self, port: Port) -> Port:
        if port in self.input_ports:
            ancestor = Port(self.name, self.input_ports[port])
            if self.parent:
                return self.parent.get_final_from(ancestor)  # input port
            else:
                return ancestor  # TOPLEVEL input port
        elif port.fmu_name in self.fmu_names_list:
            if port.fmu_name in self.children:
                child = self.children[port.fmu_name]
                ancestors = [key for key, val in child.output_ports.items() if val == port.port_name]
                if len(ancestors) == 1:
                    return child.get_final_from(ancestors[0])  # child output port
            else:
                return port  # embedded FMU

        raise AssemblyError(f"{self.name}: Port {port} is not connected upstream.")

    def get_final_to(self, port: Port) -> Port:
        if port in self.output_ports:
            successor = Port(self.name, self.output_ports[port])
            if self.parent:
                return self.parent.get_final_to(successor)  # Output port
            else:
                return successor  # TOLEVEL output port
        elif port.fmu_name in self.fmu_names_list:
            if port.fmu_name in self.children:
                child = self.children[port.fmu_name]
                successors = [key for key, val in child.input_ports.items() if val == port.port_name]
                if len(successors) == 1:
                    return child.get_final_to(successors[0])  # Child input port
            else:
                return port  # embedded FMU

        raise AssemblyError(f"Node {self.name}: Port {port} is not connected downstream.")

    def get_fmu_connections(self, fmu_name: str) -> List[Connection]:
        connections = []
        if fmu_name not in self.fmu_names_list:
            raise AssemblyError(f"Internal Error: FMU {fmu_name} is not embedded by {self.name}.")
        for link in self.links:
            if link.from_port.fmu_name == fmu_name:
                connections.append(Connection(link.from_port, self.get_final_to(link.to_port)))
            elif link.to_port.fmu_name == fmu_name:
                connections.append(Connection(self.get_final_from(link.from_port), link.to_port))

        for to_port, input_port_name in self.input_ports.items():
            if to_port.fmu_name == fmu_name:
                if self.parent:
                    connections.append(Connection(self.parent.get_final_from(Port(self.name, input_port_name)), to_port))
                else:
                    connections.append(Connection(Port(self.name, input_port_name), to_port))

        for from_port, output_port_name in self.output_ports.items():
            if from_port.fmu_name == fmu_name:
                if self.parent:
                    connections.append(Connection(from_port, self.parent.get_final_to(Port(self.name, output_port_name))))
                else:
                    connections.append(Connection(from_port, Port(self.name, output_port_name))) ###HERE

        return connections


class AssemblyError(Exception):
    def __init__(self, reason: str):
        self.reason = reason

    def __repr__(self):
        return f"{self.reason}"


class Assembly:
    def __init__(self, filename: str, step_size=None, auto_link=True,  auto_input=True, debug=False, sequential=False,
                 auto_output=True, mt=False, profiling=False, fmu_directory: Path = Path("."), auto_parameter=False,
                 auto_local=False):
        self.filename = Path(filename)
        self.default_auto_input = auto_input
        self.debug = debug
        self.default_auto_output = auto_output
        self.default_step_size = step_size
        self.default_auto_link = auto_link
        self.default_auto_parameter = auto_parameter
        self.default_auto_local = auto_local
        self.default_mt = mt
        self.default_sequential = sequential
        self.default_profiling = profiling
        self.fmu_directory = fmu_directory
        self.transient_filenames: List[Path] = []
        self.transient_dirnames: Set[Path] = set()

        if not fmu_directory.is_dir():
            raise AssemblyError(f"FMU directory is not valid: '{fmu_directory}'")

        self.input_pathname = fmu_directory / self.filename
        self.description_pathname = self.input_pathname   # For inclusion in FMU
        self.root: Optional[AssemblyNode] = None
        self.read()

    def add_transient_file(self, filename: str):
        self.transient_filenames.append(self.fmu_directory / filename)
        self.transient_dirnames.add(Path(filename).parent)

    def __del__(self):
        if not self.debug:
            for filename in self.transient_filenames:
                try:
                    filename.unlink()
                except FileNotFoundError:
                    pass
            for dirname in self.transient_dirnames:
                while not str(dirname) == ".":
                    try:
                        (self.fmu_directory / dirname).rmdir()
                    except FileNotFoundError:
                        pass
                    dirname = dirname.parent

    def read(self):
        logger.info(f"Reading '{self.filename}'")
        if self.filename.suffix == ".json":
            self.read_json()
        elif self.filename.suffix == ".ssp":
            self.read_ssp()
        elif self.filename.suffix == ".csv":
            self.read_csv()
        else:
            raise AssemblyError(f"Not supported file format '{self.filename}")

    def write(self, filename: str):
        if filename.endswith(".csv"):
            return self.write_csv(filename)
        elif filename.endswith(".json"):
            return self.write_json(filename)
        else:
            logger.critical(f"Unable to write to '{filename}': format unsupported.")

    def read_csv(self):
        name = str(self.filename.with_suffix(".fmu"))
        self.root = AssemblyNode(name, step_size=self.default_step_size, auto_link=self.default_auto_link,
                                 mt=self.default_mt, profiling=self.default_profiling,
                                 sequential=self.default_sequential, auto_input=self.default_auto_input,
                                 auto_output=self.default_auto_output, auto_parameter=self.default_auto_parameter,
                                 auto_local=self.default_auto_local)

        with open(self.input_pathname) as file:
            reader = csv.reader(file, delimiter=';')
            self._check_csv_headers(reader)
            for i, row in enumerate(reader):
                if not row or row[0][0] == '#':  # skip blank line of comment
                    continue

                try:
                    rule, from_fmu_filename, from_port_name, to_fmu_filename, to_port_name = row
                except ValueError:
                    logger.error(f"Line #{i+2}: expecting 5 columns. Line skipped.")
                    continue

                try:
                    self._read_csv_rule(self.root, rule.upper(),
                                        from_fmu_filename, from_port_name, to_fmu_filename, to_port_name)
                except AssemblyError as e:
                    logger.error(f"Line #{i+2}: {e}. Line skipped.")
                    continue

    @staticmethod
    def _check_csv_headers(reader):
        headers = next(reader)
        headers_lowered = [h.lower() for h in headers]
        if not headers_lowered == ["rule", "from_fmu", "from_port", "to_fmu", "to_port"]:
            raise AssemblyError("Header (1st line of the file) is not well formatted.")

    @staticmethod
    def _read_csv_rule(node: AssemblyNode, rule: str, from_fmu_filename: str, from_port_name: str,
                       to_fmu_filename: str, to_port_name: str):
        if rule == "FMU":
            if not from_fmu_filename:
                raise AssemblyError("Missing FMU information.")
            node.add_fmu(from_fmu_filename)

        elif rule == "INPUT":
            if not to_fmu_filename or not to_port_name:
                raise AssemblyError("Missing INPUT ports information.")
            if not from_port_name:
                from_port_name = to_port_name
            node.add_input(from_port_name, to_fmu_filename, to_port_name)

        elif rule == "OUTPUT":
            if not from_fmu_filename or not from_port_name:
                raise AssemblyError("Missing OUTPUT ports information.")
            if not to_port_name:
                to_port_name = from_port_name
            node.add_output(from_fmu_filename, from_port_name, to_port_name)

        elif rule == "DROP":
            if not from_fmu_filename or not from_port_name:
                raise AssemblyError("Missing DROP ports information.")
            node.add_drop_port(from_fmu_filename, from_port_name)

        elif rule == "LINK":
            node.add_link(from_fmu_filename, from_port_name, to_fmu_filename, to_port_name)

        elif rule == "START":
            if not from_fmu_filename or not from_port_name or not to_fmu_filename:
                raise AssemblyError("Missing START ports information.")

            node.add_start_value(from_fmu_filename, from_port_name, to_fmu_filename)
        else:
            raise AssemblyError(f"unexpected rule '{rule}'. Line skipped.")

    def write_csv(self, filename: Union[str, Path]):
        if self.root.children:
            raise AssemblyError("This assembly is not flat. Cannot export to CSV file.")

        with open(self.fmu_directory / filename, "wt") as outfile:
            outfile.write("rule;from_fmu;from_port;to_fmu;to_port\n")
            for fmu in self.root.fmu_names_list:
                outfile.write(f"FMU;{fmu};;;\n")
            for port, source in self.root.input_ports.items():
                outfile.write(f"INPUT;;{source};{port.fmu_name};{port.port_name}\n")
            for port, target in self.root.output_ports.items():
                outfile.write(f"OUTPUT;{port.fmu_name};{port.port_name};;{target}\n")
            for link in self.root.links:
                outfile.write(f"LINK;{link.from_port.fmu_name};{link.from_port.port_name};"
                              f"{link.to_port.fmu_name};{link.to_port.port_name}\n")
            for port, value in self.root.start_values.items():
                outfile.write(f"START;{port.fmu_name};{port.port_name};{value};\n")
            for port in self.root.drop_ports:
                outfile.write(f"DROP;{port.fmu_name};{port.port_name};;\n")

    def read_json(self):
        with open(self.input_pathname) as file:
            try:
                data = json.load(file)
            except json.decoder.JSONDecodeError as e:
                raise AssemblyError(f"Cannot read json: {e}")
        self.root = self._json_decode_node(data)
        if not self.root.name:
            self.root.name = str(self.filename.with_suffix(".fmu").name)

    def _json_decode_node(self, data: Dict) -> AssemblyNode:
        name = data.get("name", None)                                                       # 1
        mt = data.get("mt", self.default_mt)                                                # 2
        profiling = data.get("profiling", self.default_profiling)                           # 3
        sequential = data.get("sequential", self.default_sequential)                        # 3b
        auto_link = data.get("auto_link", self.default_auto_link)                           # 4
        auto_input = data.get("auto_input", self.default_auto_input)                        # 5
        auto_output = data.get("auto_output", self.default_auto_output)                     # 6
        auto_parameter = data.get("auto_parameter", self.default_auto_parameter)            # 6b
        auto_local = data.get("auto_local", self.default_auto_local)                        # 6c
        step_size = data.get("step_size", self.default_step_size)                           # 7

        node = AssemblyNode(name, step_size=step_size, auto_link=auto_link, mt=mt, profiling=profiling,
                            sequential=sequential,
                            auto_input=auto_input, auto_output=auto_output, auto_parameter=auto_parameter,
                            auto_local=auto_local)

        for key, value in data.items():
            if key in ('name', 'step_size', 'auto_link', 'auto_input', 'auto_output', 'mt', 'profiling', 'sequential',
                       'auto_parameter', 'auto_local'):
                continue  # Already read

            elif key == "container":  # 8
                if not isinstance(value, list):
                    raise AssemblyError("JSON: 'container' keyword should define a list.")
                for sub_data in value:
                    node.add_sub_node(self._json_decode_node(sub_data))

            elif key == "fmu":  # 9
                if not isinstance(value, list):
                    raise AssemblyError("JSON: 'fmu' keyword should define a list.")
                for fmu in value:
                    node.add_fmu(fmu)

            elif key == "input":  # 10
                self._json_decode_keyword('input', value, node.add_input)

            elif key == "output":  # 11
                self._json_decode_keyword('output', value, node.add_output)

            elif key == "link":  # 12
                self._json_decode_keyword('link', value, node.add_link)

            elif key == "start":  # 13
                self._json_decode_keyword('start', value, node.add_start_value)

            elif key == "drop":  # 14
                self._json_decode_keyword('drop', value, node.add_drop_port)

            else:
                logger.error(f"JSON: unexpected keyword {key}. Skipped.")

        return node

    @staticmethod
    def _json_decode_keyword(keyword: str, value, function):
        if not isinstance(value, list):
            raise AssemblyError(f"JSON: '{keyword}' keyword should define a list.")
        for line in value:
            if not isinstance(line, list):
                raise AssemblyError(f"JSON: unexpected '{keyword}' value: {line}.")
            try:
                function(*line)
            except TypeError:
                raise AssemblyError(f"JSON: '{keyword}' value does not contain right number of fields: {line}.")

    def write_json(self, filename: Union[str, Path]):
        with open(self.fmu_directory / filename, "wt") as file:
            data = self._json_encode_node(self.root)
            json.dump(data, file, indent=2)

    def _json_encode_node(self, node: AssemblyNode) -> Dict[str, Any]:
        json_node = dict()
        json_node["name"] = node.name                      # 1
        json_node["mt"] = node.mt                          # 2
        json_node["profiling"] = node.profiling            # 3
        json_node["sequential"] = node.sequential          # 3b
        json_node["auto_link"] = node.auto_link            # 4
        json_node["auto_input"] = node.auto_input          # 5
        json_node["auto_output"] = node.auto_output        # 6
        json_node["auto_parameter"] = node.auto_parameter  # 6b
        json_node["auto_local"] = node.auto_local          # 6c

        if node.step_size:
            json_node["step_size"] = node.step_size        # 7

        if node.children:
            json_node["container"] = [self._json_encode_node(child) for child in node.children.values()]  # 8

        if node.fmu_names_list:
            json_node["fmu"] = [f"{fmu_name}" for fmu_name in sorted(node.fmu_names_list)]          # 9

        if node.input_ports:
            json_node["input"] = [[f"{source}", f"{port.fmu_name}", f"{port.port_name}"]            # 10
                                  for port, source in node.input_ports.items()]

        if node.output_ports:
            json_node["output"] = [[f"{port.fmu_name}", f"{port.port_name}", f"{target}"]           # 11
                                   for port, target in node.output_ports.items()]

        if node.links:
            json_node["link"] = [[f"{link.from_port.fmu_name}", f"{link.from_port.port_name}",      # 12
                                  f"{link.to_port.fmu_name}", f"{link.to_port.port_name}"]
                                 for link in node.links]

        if node.start_values:
            json_node["start"] = [[f"{port.fmu_name}", f"{port.port_name}", value]                  # 13
                                  for port, value in node.start_values.items()]

        if node.drop_ports:
            json_node["drop"] = [[f"{port.fmu_name}", f"{port.port_name}"] for port in node.drop_ports]  # 14

        return json_node

    def read_ssp(self):
        logger.warning("This feature is ALPHA stage.")

        with zipfile.ZipFile(self.fmu_directory / self.filename) as zin:
            for file in zin.filelist:
                if file.filename.endswith(".fmu") or file.filename.endswith(".ssd"):
                    zin.extract(file, path=self.fmu_directory)
                    logger.debug(f"Extracted: {file.filename}")
                    self.add_transient_file(file.filename)

        self.description_pathname = self.fmu_directory / "SystemStructure.ssd"
        if self.description_pathname.is_file():
            sdd = SSDParser(step_size=self.default_step_size, auto_link=False,
                            mt=self.default_mt, profiling=self.default_profiling,
                            auto_input=False, auto_output=False)
            self.root = sdd.parse(self.description_pathname)
            self.root.name = str(self.filename.with_suffix(".fmu"))

    def make_fmu(self, dump_json=False, fmi_version=2):
        self.root.make_fmu(self.fmu_directory, debug=self.debug, description_pathname=self.description_pathname,
                           fmi_version=fmi_version)
        if dump_json:
            dump_file = Path(self.input_pathname.stem + "-dump").with_suffix(".json")
            logger.info(f"Dump Json '{dump_file}'")
            self.write_json(dump_file)


class SSDParser:
    def __init__(self, **kwargs):
        self.node_stack: List[AssemblyNode] = []
        self.root = None
        self.fmu_filenames: Dict[str, str] = {}  # Component name => FMU filename
        self.node_attrs = kwargs

    def parse(self, ssd_filepath: Path) -> AssemblyNode:
        logger.debug(f"Analysing {ssd_filepath}")
        with open(ssd_filepath, "rb") as file:
            parser = xml.parsers.expat.ParserCreate()
            parser.StartElementHandler = self.start_element
            parser.EndElementHandler = self.end_element
            parser.ParseFile(file)

        return self.root

    def start_element(self, tag_name, attrs):
        if tag_name == 'ssd:Connection':
            if 'startElement' in attrs:
                if 'endElement' in attrs:
                    fmu_start = self.fmu_filenames[attrs['startElement']]
                    fmu_end = self.fmu_filenames[attrs['endElement']]
                    self.node_stack[-1].add_link(fmu_start, attrs['startConnector'],
                                                 fmu_end, attrs['endConnector'])
                else:
                    fmu_start = self.fmu_filenames[attrs['startElement']]
                    self.node_stack[-1].add_output(fmu_start, attrs['startConnector'],
                                                   attrs['endConnector'])
            else:
                fmu_end = self.fmu_filenames[attrs['endElement']]
                self.node_stack[-1].add_input(attrs['startConnector'],
                                              fmu_end, attrs['endConnector'])

        elif tag_name == 'ssd:System':
            logger.info(f"SSP System: {attrs['name']}")
            filename = attrs['name'] + ".fmu"
            self.fmu_filenames[attrs['name']] = filename
            node = AssemblyNode(filename, **self.node_attrs)
            if self.node_stack:
                self.node_stack[-1].add_sub_node(node)
            else:
                self.root = node

            self.node_stack.append(node)

        elif tag_name == 'ssd:Component':
            filename = attrs['source']
            name = attrs['name']
            self.fmu_filenames[name] = filename
            self.node_stack[-1].add_fmu(filename)
            logger.debug(f"Component {name} => {filename}")

    def end_element(self, tag_name):
        if tag_name == 'ssd:System':
            self.node_stack.pop()
