import csv
import json
import logging
from typing import *
from pathlib import Path
import uuid
import xml.parsers.expat
import zipfile

from .container import FMUContainer

logger = logging.getLogger("fmu_manipulation_toolbox")


class Port:
    """Represents a port of an embedded FMU, identified by its FMU name and port name.

    Attributes:
        fmu_name (str): Filename of the FMU containing this port.
        port_name (str): Name of the port within the FMU.
    """

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
    """Represents a directional connection between two ports.

    Attributes:
        from_port (Port): Source port of the connection.
        to_port (Port): Destination port of the connection.
    """

    def __init__(self, from_port: Port, to_port: Port):
        self.from_port = from_port
        self.to_port = to_port

    def __str__(self):
        return f"{self.from_port} -> {self.to_port}"


class AssemblyNode:
    """Represents a node in the assembly tree, defining a container and its topology.

    An `AssemblyNode` describes how to build a single FMU Container: which FMUs it
    embeds, how their ports are connected (links), which ports are exposed as container
    inputs/outputs, and which runtime options (multi-threading, profiling, etc.) are enabled.

    Nodes can be nested via `add_sub_node` to create hierarchical containers.

    Attributes:
        name (str | None): Output filename for the container (e.g. `"container.fmu"`).
        step_size (float | None): Internal fixed time step in seconds, or `None` to deduce
            from embedded FMUs.
        mt (bool): Whether multithreaded mode is enabled.
        profiling (bool): Whether profiling mode is enabled.
        sequential (bool): Whether sequential scheduling is used.
        auto_link (bool): Automatically link ports with matching names and types.
        auto_input (bool): Automatically expose unconnected input ports.
        auto_output (bool): Automatically expose unconnected output ports.
        auto_parameter (bool): Automatically expose parameters of embedded FMUs.
        auto_local (bool): Automatically expose local variables of embedded FMUs.
        ts_multiplier (bool): Add a `TS_MULTIPLIER` input port to control step size dynamically.
        parent (AssemblyNode | None): Parent node in a hierarchical assembly, or `None` for root.
        children (dict[str, AssemblyNode]): Sub-container nodes, keyed by name.
        fmu_names_list (list[str]): Ordered list of embedded FMU filenames.
        input_ports (dict[Port, str]): Mapping from destination port to exposed input name.
        output_ports (dict[Port, str]): Mapping from source port to exposed output name.
        start_values (dict[Port, str]): Mapping from port to its start value.
        drop_ports (list[Port]): List of output ports to explicitly ignore.
        links (list[Connection]): List of connections between embedded FMUs.
    """

    def __init__(self, name: str, step_size: float = None, mt=False, profiling=False, sequential=False,
                 auto_link=True, auto_input=True, auto_output=True, auto_parameter=False, auto_local=False,
                 ts_multiplier=False):
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
        self.ts_multiplier = ts_multiplier

        self.parent: Optional[AssemblyNode] = None
        self.children: Dict[str, AssemblyNode] = {}     # sub-containers
        self.fmu_names_list: List[str] = []             # FMUs contained at this level (ordered list)
        self.input_ports: Dict[Port, str] = {}          # value is input port name, key is the source
        self.output_ports: Dict[Port, str] = {}         # value is output port name, key is the origin
        self.start_values: Dict[Port, str] = {}
        self.drop_ports: List[Port] = []
        self.links: List[Connection] = []

    def add_sub_node(self, sub_node):
        """Add a child `AssemblyNode` to create a hierarchical (nested) container.

        Args:
            sub_node (AssemblyNode): The child node to add. Its name will be
                auto-generated if `None`.

        Raises:
            AssemblyError: If the sub-node is already parented or already a child
                of this node.
        """
        if sub_node.name is None:
            sub_node.name = str(uuid.uuid4())+".fmu"

        if sub_node.parent is not None:
            raise AssemblyError(f"Internal Error: AssemblyNode {sub_node.name} is already parented.")

        if sub_node.name in self.children:
            raise AssemblyError(f"Internal Error: AssemblyNode {sub_node.name} is already child of {self.name}")

        sub_node.parent = self
        self.children[sub_node.name] = sub_node

    def add_fmu(self, fmu_name: str):
        """Declare an embedded FMU by filename.

        Args:
            fmu_name (str): Filename of the FMU to embed (e.g. `"model.fmu"`).
        """
        if fmu_name not in self.fmu_names_list:
            self.fmu_names_list.append(fmu_name)

    def add_input(self, from_port_name: str, to_fmu_filename: str, to_port_name: str):
        """Expose a port of an embedded FMU as a container input.

        Args:
            from_port_name (str): Name of the exposed input on the container.
            to_fmu_filename (str): Filename of the embedded FMU.
            to_port_name (str): Name of the input port on the embedded FMU.
        """
        self.input_ports[Port(to_fmu_filename, to_port_name)] = from_port_name

    def add_output(self, from_fmu_filename: str, from_port_name: str, to_port_name: str):
        """Expose a port of an embedded FMU as a container output.

        Args:
            from_fmu_filename (str): Filename of the embedded FMU.
            from_port_name (str): Name of the output port on the embedded FMU.
            to_port_name (str): Name of the exposed output on the container.
        """
        self.output_ports[Port(from_fmu_filename, from_port_name)] = to_port_name

    def add_drop_port(self, fmu_filename: str, port_name: str):
        """Mark an output port to be explicitly ignored.

        Args:
            fmu_filename (str): Filename of the embedded FMU.
            port_name (str): Name of the output port to drop.
        """
        self.drop_ports.append(Port(fmu_filename, port_name))

    def add_link(self, from_fmu_filename: str, from_port_name: str, to_fmu_filename: str, to_port_name: str):
        """Connect an output port of one embedded FMU to an input port of another.

        Args:
            from_fmu_filename (str): Filename of the source FMU.
            from_port_name (str): Name of the output port on the source FMU.
            to_fmu_filename (str): Filename of the destination FMU.
            to_port_name (str): Name of the input port on the destination FMU.
        """
        self.links.append(Connection(Port(from_fmu_filename, from_port_name),
                          Port(to_fmu_filename, to_port_name)))

    def add_start_value(self, fmu_filename: str, port_name: str, value: str):
        """Set a start value for a port of an embedded FMU.

        Args:
            fmu_filename (str): Filename of the embedded FMU.
            port_name (str): Name of the port.
            value (str): Start value as a string.
        """
        self.start_values[Port(fmu_filename, port_name)] = value

    def make_fmu(self, fmu_directory: Path, debug=False, description_pathname=None, fmi_version=2, datalog=False,
                 filename=None):
        """Build the FMU Container.

        Recursively builds any child containers first, then creates the container FMU
        by delegating to
        [FMUContainer][fmu_manipulation_toolbox.container.FMUContainer].

        Args:
            fmu_directory (Path): Directory containing the source FMUs and where the
                container will be generated.
            debug (bool): If `True`, keep intermediate build artifacts and enable
                verbose logging.
            description_pathname (Path | None): Path to the original description file
                to embed in the FMU.
            fmi_version (int): FMI version for the container interface (`2` or `3`).
            datalog (bool): If `True`, generate a datalog configuration file inside
                the container.
            filename (str | None): Override the output filename. Defaults to `name`.
        """
        for node in self.children.values():
            node.make_fmu(fmu_directory, debug=debug, fmi_version=fmi_version)

        identifier = str(Path(self.name).stem)
        container = FMUContainer(identifier, fmu_directory, description_pathname=description_pathname,
                                 fmi_version=fmi_version)

        for node in self.children.values():
            container.get_fmu(node.name)

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

        if filename is None:
            filename = self.name

        container.make_fmu(filename, self.step_size, mt=self.mt, profiling=self.profiling, sequential=self.sequential,
                           debug=debug, ts_multiplier=self.ts_multiplier, datalog=datalog)

        for node in self.children.values():
            logger.info(f"Deleting transient FMU Container '{node.name}'")
            (fmu_directory / node.name).unlink()

    def get_final_from(self, port: Port) -> Port:
        """Resolve the ultimate source port by traversing the assembly hierarchy upward.

        Args:
            port (Port): The port to trace back to its origin.

        Returns:
            Port: The resolved source port (either a top-level input or an
                embedded FMU port).

        Raises:
            AssemblyError: If the port is not connected upstream.
        """
        if port in self.input_ports:
            ancestor = Port(self.name, self.input_ports[port])
            if self.parent:
                return self.parent.get_final_from(ancestor)  # input port
            else:
                return ancestor  # TOPLEVEL input port
        elif port.fmu_name in self.fmu_names_list:
            return port  # embedded FMU
        elif port.fmu_name in self.children:
                child = self.children[port.fmu_name]
                ancestors = [key for key, val in child.output_ports.items() if val == port.port_name]
                if len(ancestors) == 1:
                    return child.get_final_from(ancestors[0])  # child output port

        raise AssemblyError(f"{self.name}: Port {port} is not connected upstream.")

    def get_final_to(self, port: Port) -> Port:
        """Resolve the ultimate destination port by traversing the assembly hierarchy downward.

        Args:
            port (Port): The port to trace forward to its destination.

        Returns:
            Port: The resolved destination port (either a top-level output or an
                embedded FMU port).

        Raises:
            AssemblyError: If the port is not connected downstream.
        """
        if port in self.output_ports:
            successor = Port(self.name, self.output_ports[port])
            if self.parent:
                return self.parent.get_final_to(successor)  # Output port
            else:
                return successor  # TOPLEVEL output port
        elif port.fmu_name in self.fmu_names_list:
            return port  # embedded FMU
        elif port.fmu_name in self.children:
                child = self.children[port.fmu_name]
                successors = [key for key, val in child.input_ports.items() if val == port.port_name]
                if len(successors) == 1:
                    return child.get_final_to(successors[0])  # Child input port

        raise AssemblyError(f"Node {self.name}: Port {port} is not connected downstream.")

    def get_fmu_connections(self, fmu_name: str) -> List[Connection]:
        """Get all resolved connections involving a specific embedded FMU.

        Returns connections where the given FMU is either source or destination,
        with ports resolved through the full assembly hierarchy.

        Args:
            fmu_name (str): Filename of the embedded FMU.

        Returns:
            list[Connection]: List of connections involving the specified FMU.

        Raises:
            AssemblyError: If the FMU is not embedded in this node.
        """
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
    """Exception raised for errors during assembly parsing or container building.

    Attributes:
        reason (str): Human-readable description of the error.
    """

    def __init__(self, reason: str):
        self.reason = reason

    def __repr__(self):
        return f"{self.reason}"


class Assembly:
    """High-level interface for loading, manipulating, and building FMU Container assemblies.

    `Assembly` reads a description file (CSV, JSON, or SSP), constructs the corresponding
    [AssemblyNode][fmu_manipulation_toolbox.assembly.AssemblyNode] tree, and provides methods
    to build the container FMU or export the assembly to a different format.

    This is the main entry point for both the `fmucontainer` CLI and the Python API.

    Examples:
        ```python
        from pathlib import Path
        from fmu_manipulation_toolbox.assembly import Assembly

        assembly = Assembly("bouncing.csv",
                            fmu_directory=Path("containers/bouncing_ball"),
                            mt=True)
        assembly.make_fmu()
        ```

    Attributes:
        filename (Path): Path to the description file.
        fmu_directory (Path): Directory containing the source FMUs.
        debug (bool): Whether debug mode is enabled.
        root (AssemblyNode | None): Root node of the assembly tree.
    """

    def __init__(self, filename: Union[str, Path], default_step_size=None, default_auto_link=True,
                 default_auto_input=True, debug=False, default_sequential=False, default_auto_output=True,
                 default_mt=False, default_profiling=False, fmu_directory: Path = Path("."),
                 default_auto_parameter=False, default_auto_local=False, default_ts_multiplier=False):
        self.filename = Path(filename) if filename else None
        self.default_auto_input = default_auto_input
        self.debug = debug
        self.default_auto_output = default_auto_output
        self.default_step_size = default_step_size
        self.default_auto_link = default_auto_link
        self.default_auto_parameter = default_auto_parameter
        self.default_auto_local = default_auto_local
        self.default_mt = default_mt
        self.default_sequential = default_sequential
        self.default_profiling = default_profiling
        self.default_ts_multiplier = default_ts_multiplier
        self.fmu_directory = fmu_directory

        if not fmu_directory.is_dir():
            raise AssemblyError(f"FMU directory is not valid: '{fmu_directory.resolve()}'")

        self.root: Optional[AssemblyNode] = None

        if self.filename:
            self.input_pathname = fmu_directory / self.filename
            self.description_pathname = self.input_pathname  # For inclusion in FMU
            self.read()
        else:
            self.description_pathname = None

    def read(self):
        """Read and parse the description file.

        The format is determined by the file extension: `.json`, `.ssp`, or `.csv`.

        Raises:
            AssemblyError: If the file format is not supported.
        """
        if self.filename:
            logger.info(f"Reading '{self.filename}'")
            if self.filename.suffix == ".json":
                self.read_json()
            elif self.filename.suffix == ".ssp":
                self.read_ssp()
            elif self.filename.suffix == ".csv":
                self.read_csv()
            else:
                raise AssemblyError(f"Not supported file format '{self.filename}")
        else:
            raise AssemblyError(f"Filename should be specified for reading.")

    def write(self, filename: str):
        """Export the assembly to a file.

        Args:
            filename (str): Output filename. The format is determined by the
                extension (`.csv` or `.json`).

        Raises:
            AssemblyError: If the format is not supported.
        """
        if filename.endswith(".csv"):
            self.write_csv(filename)
        elif filename.endswith(".json"):
            self.write_json(filename)
        else:
            raise AssemblyError(f"Unable to write to '{filename}': format unsupported.")

    def read_csv(self):
        """Parse a CSV description file and populate the assembly tree."""
        name = str(self.filename.with_suffix(".fmu"))
        self.root = AssemblyNode(name, step_size=self.default_step_size, auto_link=self.default_auto_link,
                                 mt=self.default_mt, profiling=self.default_profiling,
                                 sequential=self.default_sequential, auto_input=self.default_auto_input,
                                 auto_output=self.default_auto_output, auto_parameter=self.default_auto_parameter,
                                 auto_local=self.default_auto_local, ts_multiplier=self.default_ts_multiplier)

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
        """Export the assembly as a CSV file.

        Args:
            filename (str | Path): Output filename, relative to `fmu_directory`.

        Raises:
            AssemblyError: If the assembly contains nested containers
                (not representable in CSV).
        """
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
        """Parse a JSON description file and populate the assembly tree.

        Raises:
            AssemblyError: If the JSON is malformed or contains invalid keywords.
        """
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
        ts_multiplier = data.get("ts_multiplier", self.default_ts_multiplier)               # 7b

        node = AssemblyNode(name, step_size=step_size, auto_link=auto_link, mt=mt, profiling=profiling,
                            sequential=sequential,
                            auto_input=auto_input, auto_output=auto_output, auto_parameter=auto_parameter,
                            auto_local=auto_local, ts_multiplier=ts_multiplier)

        for key, value in data.items():
            if key in ('name', 'step_size', 'auto_link', 'auto_input', 'auto_output', 'mt', 'profiling', 'sequential',
                       'auto_parameter', 'auto_local', 'ts_multiplier'):
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
        """Export the assembly as a JSON file.

        Args:
            filename (str | Path): Output filename, relative to `fmu_directory`.
        """
        with open(self.fmu_directory / filename, "wt") as file:
            data = self.json_encode()
            json.dump(data, file, indent=2)

    def json_encode(self) -> Dict[str, Any]:
        """Export the assembly as a JSON file."""
        if self.root:
            return self._json_encode_node(self.root)
        else:
            return {}

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

        if node.ts_multiplier:
            json_node["ts_multiplier"] = node.ts_multiplier # 7b

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
        """Parse an SSP (System Structure and Parameterization) archive.

        Extracts embedded FMUs and the `SystemStructure.ssd` file, then builds
        the assembly tree from the SSD connections.

        Warning:
            This feature is in alpha stage.
        """
        logger.warning("This feature is ALPHA stage.")


        with zipfile.ZipFile(self.fmu_directory / self.filename) as zin:
            extract_folder = self.fmu_directory / self.filename.with_suffix(".dir")
            extract_folder.mkdir(exist_ok=True)

            for file in zin.filelist:
                if file.filename.endswith(".fmu"):
                    # FMU are all stored in extract_folder without hierarchy
                    file.filename = str(Path(file.filename).name)
                    zin.extract(file, path=extract_folder)
                    logger.debug(f"Extracted: {file.filename} (into {extract_folder})")

            self.description_pathname = None
            if "SystemStructure.ssd" in zin.namelist():
                sdd = SSDParser(zin, Path(extract_folder.name), step_size=self.default_step_size, auto_link=False,
                                mt=self.default_mt, profiling=self.default_profiling,
                                auto_input=False, auto_output=False, auto_parameter=False)
                self.root = sdd.parse("SystemStructure.ssd")
                self.root.name = str(self.filename.with_suffix(".fmu"))
            else:
                raise AssemblyError(f"'SystemStructure.ssd' file not found in '{self.fmu_directory / self.filename}'")

    def make_fmu(self, dump_json=False, fmi_version=2, datalog=False, filename=None):
        """Build the FMU Container from the loaded assembly.

        Args:
            dump_json (bool): If `True`, also export a JSON dump of the assembly.
            fmi_version (int): FMI version for the container interface (`2` or `3`).
            datalog (bool): If `True`, enable data logging inside the container.
            filename (str | None): Override the output filename.
        """
        self.root.make_fmu(self.fmu_directory, debug=self.debug, description_pathname=self.description_pathname,
                           fmi_version=fmi_version, datalog=datalog, filename=filename)
        if dump_json:
            dump_file = Path(self.input_pathname.stem + "-dump").with_suffix(".json")
            logger.info(f"Dump Json '{dump_file}'")
            self.write_json(dump_file)


class SSDParser:
    """SAX-based parser for SSD (System Structure Description) files.

    Parses the XML structure of an `.ssd` file and builds the corresponding
    [AssemblyNode][fmu_manipulation_toolbox.assembly.AssemblyNode] tree, including
    embedded FMUs, connections, and hierarchical sub-systems.

    Attributes:
        node_stack (list[AssemblyNode]): Stack of nodes used during XML parsing
            for tracking hierarchy.
        root (AssemblyNode | None): Root node after parsing is complete.
        fmu_filenames (dict[str, str]): Mapping from SSD component names to
            FMU filenames.
    """

    def __init__(self, zin: zipfile.ZipFile, extract_folder: Path, **kwargs):
        self.zin = zin
        self.extract_folder = extract_folder

        self.node_stack: List[AssemblyNode] = []
        self.root = None
        self.fmu_filenames: Dict[str, str] = {}  # Component name => FMU filename
        self.node_attrs = kwargs

    def parse(self, ssd_filename: str) -> AssemblyNode:
        """Parse an SSD file and return the root assembly node.

        Args:
            ssd_filename (str): filename to the `.ssd` file.

        Returns:
            AssemblyNode: The root node representing the parsed system structure.
        """
        logger.debug(f"Analysing {ssd_filename}")
        with self.zin.open(ssd_filename) as file:
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
            filename = str(self.extract_folder / Path(attrs['source']).name)
            name = attrs['name']
            self.fmu_filenames[name] = filename
            self.node_stack[-1].add_fmu(filename)
            logger.debug(f"Component {name} => {filename}")

    def end_element(self, tag_name):
        if tag_name == 'ssd:System':
            self.node_stack.pop()
