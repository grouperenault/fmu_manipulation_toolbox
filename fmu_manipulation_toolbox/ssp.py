"""SSP (System Structure and Parameterization) files: reading `SystemStructure.ssd` into an assembly.

[Assembly.read_ssp][fmu_manipulation_toolbox.assembly.Assembly.read_ssp] extracts the FMUs of an SSP archive, then
uses this module: `validate_ssd` checks the SSD against the SSP 2.0.1 schema shipped in `resources/ssp-2.0/`, and
[SSDParser][fmu_manipulation_toolbox.ssp.SSDParser] builds the
[AssemblyNode][fmu_manipulation_toolbox.assembly.AssemblyNode] tree. SSP 1.0 and 2.0 share one namespace.
"""
import functools
import logging
import xml.etree.ElementTree as ET
import zipfile
from difflib import get_close_matches
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from .assembly import ArchitectureWire, AssemblyError, AssemblyNode, instance_name
from .model_description import ModelDescription, ModelDescriptionError, ModelVariable

logger = logging.getLogger("fmu_manipulation_toolbox")


#: Validation errors of an SSD reported one by one; the others are counted.
MAX_SSD_VALIDATION_WARNINGS = 20


@functools.cache
def _ssd_schema():
    """The SSP 2.0.1 schema of SSD files, loaded once: it takes about a second."""
    import xmlschema

    return xmlschema.XMLSchema(Path(__file__).parent / "resources" / "ssp-2.0" / "SystemStructureDescription.xsd")


def validate_ssd(content: bytes, label: str) -> int:
    """Validate an SSD against the SSP 2.0.1 schema (which accepts SSP 1.0 files: same namespace, version 1.0 or
    2.0), reporting each error as a warning: a file the parser understands is read anyway (D10 of the SSP beta
    plan).

    Returns:
        int: The number of validation errors.
    """
    import xmlschema

    schema = _ssd_schema()
    try:
        errors = list(schema.iter_errors(content.decode("utf-8")))
    except (UnicodeDecodeError, xmlschema.XMLSchemaException, ET.ParseError) as error:
        logger.warning(f"'{label}' cannot be validated against the SSP schema: {error}")
        return 1
    for error in errors[:MAX_SSD_VALIDATION_WARNINGS]:
        where = f" (at {error.path})" if error.path else ""
        logger.warning(f"'{label}' is not valid against the SSP schema{where}: {error.reason}")
    if len(errors) > MAX_SSD_VALIDATION_WARNINGS:
        logger.warning(f"'{label}': {len(errors) - MAX_SSD_VALIDATION_WARNINGS} more validation error(s).")
    return len(errors)


class SSDParser:
    """Parser for SSD (System Structure Description) files of SSP archives (SSP 1.0 and 2.0 share one namespace).

    Parses the XML structure of an `.ssd` file and builds the corresponding
    [AssemblyNode][fmu_manipulation_toolbox.assembly.AssemblyNode] tree, including
    embedded FMUs, connections, and hierarchical sub-systems.

    Elements are recognized by their namespace (`SSD_NAMESPACE`), whatever the
    prefix used in the file (`ssd:`, another one, or a default namespace).

    Each component is embedded as `<component name>.fmu`, in the directory of its `source` file. A component
    without `source` (SSP 2.0 component without implementation) is ignored, with the connections attached to it:
    an assembly whose FMUs are not all available (MIC modeler) can still be opened.

    A connection carrying an annotation of type `ARCHITECTURE_WIRE_TYPE` is an architecture wire (see
    `ArchitectureWire`), not a link.

    An SSP construction the container cannot honour raises an `AssemblyError` when it would change the result of
    the container — a component that is not an FMU, a connection transformation, a parameter mapping, a connection
    through a signal dictionary, connected connectors of different units — and is reported with a warning when it
    has no effect on it (a signal dictionary that no connection uses).

    Attributes:
        node_stack (list[AssemblyNode]): Stack of nodes used during XML parsing
            for tracking hierarchy.
        root (AssemblyNode | None): Root node after parsing is complete.
        fmu_filenames (dict[str, str]): Mapping from SSD component names to
            the names of the embedded FMUs.
        ignored_components (set[str]): Names of the components ignored because they have no `source`.
        connectors (dict[tuple[int, str | None], dict[str, SSDConnector]]): Connectors declared by each element,
            by (id of its system node, element name, `None` for the system itself), then by connector name.
        units (dict[str, dict[str, str]]): `ssc:Unit` definitions: the attributes of their `ssc:BaseUnit`.

    Each connection is checked against the FMUs it joins: the connector is a variable of the FMU (or an FMI 3.0
    alias), of a causality that fits its end (an output starts a link or an exposed output, an input ends a link,
    an input or a parameter is exposed as an input of the container). Not checked: architecture wires, whose
    connectors are not variables, the components without `source` (ignored) and the sub-systems (no FMU).

    The values of the parameter bindings (inline `ssv:ParameterSet`, an `.ssv` file of the archive or of the FMU of
    the component) become start values of the variables of the embedded FMUs, which are not exposed. As in the
    standard, a later binding takes priority over an earlier one of the same element, and a binding of a system
    over the bindings of its elements; a name is a variable of the component, or for a system a connector of the
    system (followed through its connections) or the hierarchical name of a variable (`element.variable`). A name
    that matches nothing is ignored with a warning; a value for a variable that cannot be parameterized raises an
    `AssemblyError`.
    """

    SSD_NAMESPACE = "http://ssp-standard.org/SSP1/SystemStructureDescription"
    SSC_NAMESPACE = "http://ssp-standard.org/SSP1/SystemStructureCommon"
    SSV_NAMESPACE = "http://ssp-standard.org/SSP1/SystemStructureParameterValues"
    #: The only parameter source understood (default `type` of `ParameterBinding`).
    PARAMETER_SET_TYPE = "application/x-ssp-parameter-set"
    #: Value elements of `ssv:Parameter`, giving their value as is.
    PARAMETER_TYPES = ("Real", "Float64", "Float32", "Integer", "Int8", "UInt8", "Int16", "UInt16", "Int32",
                       "UInt32", "Int64", "UInt64", "Boolean", "String", "Enumeration")
    ARCHITECTURE_WIRE_TYPE = "fmu_manipulation_toolbox.architecture-wire"
    ARCHITECTURE_WIRE_NAMESPACE = "urn:fmu_manipulation_toolbox:architecture-wire:1"
    #: Component type of an FMU, the default of the `type` attribute (SSP 1.0 §5.3.2).
    FMU_COMPONENT_TYPE = "application/x-fmu-sharedlibrary"
    #: Connection transformations (SSP 1.0 §5.3.6): the container cannot apply them.
    TRANSFORMATIONS = ("LinearTransformation", "BooleanMappingTransformation", "IntegerMappingTransformation",
                       "EnumerationMappingTransformation")
    #: Type elements of a connector: SSP 1.0, and the FMI 3.0 types of SSP 2.0.
    CONNECTOR_TYPES = ("Real", "Integer", "Boolean", "String", "Enumeration", "Binary", "Clock", "Float32",
                       "Float64", "Int8", "UInt8", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64")
    #: Causalities a connector may have, by its role in a connection.
    OUTPUT_ROLES = ("output",)
    INPUT_ROLES = ("input",)
    EXPOSED_INPUT_ROLES = ("input", "parameter")
    EXPOSED_OUTPUT_ROLES = ("output", "local")  # as the builder (`auto_local`)
    #: Attributes of `ssc:BaseUnit`, with their default value.
    BASE_UNIT_DEFAULTS = {"kg": "0", "m": "0", "s": "0", "A": "0", "K": "0", "mol": "0", "cd": "0", "rad": "0",
                          "factor": "1", "offset": "0"}

    def __init__(self, zin: zipfile.ZipFile, extract_folder_name: str, **kwargs):
        self.zin = zin
        self.extract_folder_name = extract_folder_name

        self.node_stack: list[AssemblyNode] = []
        self.root = None
        self.fmu_filenames: dict[str, str] = {}  # Component name => FMU name
        self.ignored_components: set[str] = set()
        self.node_attrs = kwargs
        self.connectors: dict[tuple[int, str | None], dict[str, SSDConnector]] = {}
        self.units: dict[str, dict[str, str]] = {}
        self.ssd_filename = ""
        self._sources: dict[tuple[int, str], str] = {}  # (system, component) => source in the archive
        self._variables: dict[str, dict[str, str]] = {}  # source => variable name => causality
        self._used_connectors: set[tuple[int, str]] = set()  # (system, connector) of the system used
        self._fmus: dict[str, tuple[ModelDescription, dict[str, ModelVariable]]] = {}  # source => description
        # Structure kept for the parameter bindings, resolved once the whole file is read.
        self._depth: dict[int, int] = {}  # system => depth (root: 0)
        self._elements: dict[int, dict[str, tuple[str, Any]]] = {}  # system => element => (kind, details)
        self._system_connections: dict[int, list[dict[str, str]]] = {}  # system => its connections
        self._bindings: list[dict[str, Any]] = []
        self._binding: dict[str, Any] | None = None  # binding being read
        self._default_experiment: dict[str, str] = {}  # attributes of the DefaultExperiment of the SSD

        # Name of the embedded FMU of the component being read, for its ElementGeometry.
        self._component_fmu: str | None = None
        # Connection being read: its attributes, and its orientation once an architecture wire annotation is found.
        self._connection_attrs: dict[str, str] | None = None
        self._in_architecture_annotation = False
        self._wire_orientation: str | None = None
        self._transformation: str | None = None  # transformation element of the connection being read
        # Owners of the connectors being read: ("system", node), ("component", name) or ("dictionary", name).
        self._owners: list[tuple[str, Any]] = []
        self._connector: SSDConnector | None = None
        self._unit: str | None = None  # name of the ssc:Unit being read
        # Signal dictionaries: references (elements of a system) and definitions, and those used by a connection.
        self._dictionary_references: dict[tuple[int, str], str] = {}  # (system, reference name) => dictionary
        self._dictionaries: set[str] = set()
        # Connections between two declared connectors, checked once the units are known (they follow the systems).
        self._unit_checks: list[tuple[str, SSDConnector, SSDConnector]] = []

    def parse(self, ssd_filename: str) -> AssemblyNode:
        """Parse an SSD file and return the root assembly node.

        Args:
            ssd_filename (str): filename to the `.ssd` file.

        Returns:
            AssemblyNode: The root node representing the parsed system structure.

        Raises:
            AssemblyError: If the file is not well-formed, is not an SSP 1.0
                system structure description, refers to unknown elements, or uses
                an SSP construction that would change the container (see the class).
        """
        logger.debug(f"Analysing {ssd_filename}")
        self.ssd_filename = ssd_filename
        prefix = f"{{{self.SSD_NAMESPACE}}}"
        common = f"{{{self.SSC_NAMESPACE}}}"
        try:
            with self.zin.open(ssd_filename) as file:
                root_checked = False
                for event, element in ET.iterparse(file, events=("start", "end")):
                    if not root_checked:
                        if element.tag != f"{prefix}SystemStructureDescription":
                            raise AssemblyError(f"'{ssd_filename}' is not an SSP 1.0 system structure description: "
                                                f"root element is <{element.tag}>, expected "
                                                f"<SystemStructureDescription> in namespace '{self.SSD_NAMESPACE}'")
                        root_checked = True
                    if self._connection_attrs is not None:
                        self._connection_child(event, element)
                    if element.tag.startswith(common):
                        if event == "start":
                            self._common_element(element.tag[len(common):], element.attrib)
                        continue
                    if element.tag.startswith(f"{{{CONTAINER_NAMESPACE}}}"):
                        if event == "start":
                            self._container_annotation(element.tag[len(CONTAINER_NAMESPACE) + 2:], element.attrib)
                        continue
                    if not element.tag.startswith(prefix):
                        continue  # other SSP namespaces (ssv:...) and vendor annotations
                    tag = element.tag[len(prefix):]
                    if event == "start":
                        self.start_element(tag, element.attrib)
                    else:
                        if tag == "ParameterValues" and self._binding is not None:
                            self._binding["values"] += self._parameter_values(element, "inline values")
                        self.end_element(tag)
        except ET.ParseError as error:
            raise AssemblyError(f"'{ssd_filename}' is not well-formed XML: {error}") from error
        except KeyError as error:
            raise AssemblyError(f"'{ssd_filename}': reference to an unknown element or missing attribute "
                                f"{error}") from error

        if self.root is None:
            raise AssemblyError(f"'{ssd_filename}': no <System> found in namespace '{self.SSD_NAMESPACE}'")
        self._check_units()
        self._warn_unused_dictionaries()
        self._apply_parameters()
        self._apply_default_experiment()
        return self.root

    def start_element(self, tag_name, attrs):
        """Handle the start of an SSD element (`tag_name` without namespace, e.g. `"Connection"`)."""
        if tag_name == 'Connection':
            # Decided on the end tag: an annotation (child element) may make it an architecture wire.
            self._connection_attrs = dict(attrs)
            self._in_architecture_annotation = False
            self._wire_orientation = None
            self._transformation = None

        elif tag_name == 'System':
            logger.info(f"SSP System: {attrs['name']}")
            filename = attrs['name'] + ".fmu"
            self.fmu_filenames[attrs['name']] = filename
            node = AssemblyNode(filename, **self.node_attrs)
            if self.node_stack:
                self.node_stack[-1].add_sub_node(node)
                self._elements[id(self.node_stack[-1])][attrs['name']] = ("system", node)
            else:
                self.root = node

            self.node_stack.append(node)
            self._owners.append(("system", attrs['name']))
            self._depth[id(node)] = len(self.node_stack) - 1
            self._elements[id(node)] = {}
            self._system_connections[id(node)] = []

        elif tag_name == 'Component':
            self._owners.append(("component", attrs['name']))
            if 'source' not in attrs:
                # Kept although it changes the container (D13 of the SSP beta plan): MIC modeler writes components
                # without source when the FMU of an instance is not available.
                logger.warning(f"Component '{attrs['name']}' has no source FMU. It is ignored, "
                               f"with its connections.")
                self.ignored_components.add(attrs['name'])
                self._elements[id(self.node_stack[-1])][attrs['name']] = ("ignored", None)
                return
            component_type = attrs.get('type', self.FMU_COMPONENT_TYPE)
            if component_type != self.FMU_COMPONENT_TYPE:
                raise AssemblyError(f"'{self.ssd_filename}': component '{attrs['name']}' is of type "
                                    f"'{component_type}': only FMUs ('{self.FMU_COMPONENT_TYPE}') can be embedded.")
            source = self._source_path(attrs['source'])
            filename = f"{self.extract_folder_name}/{source}"
            node = self.node_stack[-1]
            name = f"{self.extract_folder_name}/{source.parent / attrs['name']}.fmu"
            fmu_name = instance_name(name, node.fmu_names_list)
            self.fmu_filenames[attrs['name']] = fmu_name
            self._sources[(id(node), attrs['name'])] = str(source)
            self._elements[id(node)][attrs['name']] = ("component", (node, fmu_name, str(source)))
            node.add_fmu(fmu_name, filename)
            self._component_fmu = fmu_name
            logger.debug(f"Component {attrs['name']} => {fmu_name}")

        elif tag_name == 'SignalDictionaryReference':
            self._owners.append(("dictionary", attrs['name']))
            self._dictionary_references[(id(self.node_stack[-1]), attrs['name'])] = attrs.get('dictionary', '')

        elif tag_name == 'SignalDictionary':
            self._dictionaries.add(attrs.get('name', ''))

        elif tag_name == 'Connector' and self._owners:
            self._connector = SSDConnector(self._owners[-1][1], attrs['name'], attrs.get('kind'))

        elif tag_name == 'ParameterBinding':
            self._start_binding(attrs)

        elif tag_name == 'DefaultExperiment' and not self.node_stack:
            self._default_experiment = dict(attrs)

        elif tag_name == 'ParameterMapping':
            raise AssemblyError(f"'{self.ssd_filename}': {self._owner_label()} has a parameter mapping: parameter "
                                f"mappings are not supported (they rename and may transform the values).")

        elif tag_name == 'ElementGeometry' and self._component_fmu is not None:
            try:
                self.node_stack[-1].fmu_geometry[self._component_fmu] = \
                    tuple(float(attrs[corner]) for corner in ('x1', 'y1', 'x2', 'y2'))
            except ValueError:
                logger.debug(f"Geometry of '{self._component_fmu}' ignored: invalid coordinates.")

    def end_element(self, tag_name):
        """Handle the end of an SSD element (`tag_name` without namespace)."""
        if tag_name == 'System':
            node = self.node_stack.pop()
            self._owners.pop()
            for name in self.connectors.get((id(node), None), {}):
                if (id(node), name) not in self._used_connectors:
                    logger.debug(f"Connector '{name}' of system '{node.name}' is not exposed: no connection uses it.")
        elif tag_name in ('Component', 'SignalDictionaryReference'):
            self._component_fmu = None
            self._owners.pop()
        elif tag_name == 'Connector' and self._connector is not None:
            self._register_connector(self._connector)
            self._connector = None
        elif tag_name == 'ParameterBinding':
            if self._binding is not None:
                self._bindings.append(self._binding)
            self._binding = None
        elif tag_name == 'Connection':
            # An empty `startElement`/`endElement` (as OMSimulator writes them) is a connector of the system, as a
            # missing one.
            attrs = {key: value for key, value in self._connection_attrs.items()
                     if not (key in ('startElement', 'endElement') and value == "")}
            self._connection_attrs = None
            if self._wire_orientation is None:
                self._add_connection(attrs)
            else:
                self._add_architecture_wire(attrs, self._wire_orientation)

    def _common_element(self, tag_name: str, attrs):
        """Handle the start of an element of the SSC namespace: type of a connector, unit definitions."""
        if self._connector is not None and self._connector.type is None and tag_name in self.CONNECTOR_TYPES:
            self._connector.type = tag_name
            self._connector.unit = attrs.get('unit')
        elif tag_name == 'Unit':
            self._unit = attrs.get('name')
            self.units.setdefault(self._unit, {})
        elif tag_name == 'BaseUnit' and self._unit is not None:
            self.units[self._unit] = dict(attrs)

    def _register_connector(self, connector: "SSDConnector"):
        """Record a connector under its element; the connectors of a system are also those of its element in the
        parent system."""
        kind, _ = self._owners[-1]
        node = self.node_stack[-1]
        if kind == "system":
            self.connectors.setdefault((id(node), None), {})[connector.name] = connector
            if len(self.node_stack) > 1:
                self.connectors.setdefault((id(self.node_stack[-2]), connector.element), {})[connector.name] = \
                    connector
        else:
            self.connectors.setdefault((id(node), connector.element), {})[connector.name] = connector

    def _owner_label(self) -> str:
        if not self._owners:
            return "the system structure"
        kind, name = self._owners[-1]
        return f"{'system' if kind == 'system' else 'component'} '{name}'"

    def _connection_child(self, event: str, element: ET.Element):
        """Look for the architecture wire annotation and the transformations among the descendants of the
        connection being read."""
        local_name = element.tag.rsplit("}", 1)[-1]
        if element.tag == f"{{{self.SSC_NAMESPACE}}}Annotation":
            self._in_architecture_annotation = (event == "start" and
                                                element.get("type") == self.ARCHITECTURE_WIRE_TYPE)
        elif (self._in_architecture_annotation and event == "start" and
              element.tag == f"{{{self.ARCHITECTURE_WIRE_NAMESPACE}}}Wire"):
            orientation = element.get("orientation", "undirected")
            if orientation not in ArchitectureWire.ORIENTATIONS:
                logger.warning(f"Architecture wire with unknown orientation '{orientation}'. "
                               f"It is read as 'undirected'.")
                orientation = "undirected"
            self._wire_orientation = orientation
        elif (event == "start" and local_name in self.TRANSFORMATIONS and
              element.tag.startswith((f"{{{self.SSC_NAMESPACE}}}", f"{{{self.SSD_NAMESPACE}}}"))):
            self._transformation = local_name

    @staticmethod
    def _connection_label(attrs: dict[str, str]) -> str:
        start = f"{attrs['startElement']}." if 'startElement' in attrs else ""
        end = f"{attrs['endElement']}." if 'endElement' in attrs else ""
        return f"connection {start}{attrs['startConnector']} -> {end}{attrs['endConnector']}"

    def _add_connection(self, attrs: dict[str, str]):
        """Turn a connection into a link, an exposed input or an exposed output."""
        if attrs.get('startElement') in self.ignored_components or attrs.get('endElement') in self.ignored_components:
            logger.debug(f"Connection {attrs.get('startElement')}/{attrs['startConnector']} -> "
                         f"{attrs.get('endElement')}/{attrs['endConnector']} ignored: it involves an ignored "
                         f"component.")
            return
        if self._transformation is not None:
            raise AssemblyError(f"'{self.ssd_filename}': {self._connection_label(attrs)} has a "
                                f"{self._transformation}: connection transformations are not supported.")
        system = id(self.node_stack[-1])
        for side in ('startElement', 'endElement'):
            if (system, attrs.get(side)) in self._dictionary_references:
                raise AssemblyError(f"'{self.ssd_filename}': {self._connection_label(attrs)} goes through the signal "
                                    f"dictionary reference '{attrs[side]}': signal dictionaries are not supported.")
        self._check_fmu_connectors(attrs)
        self._system_connections[system].append(attrs)
        start = self.connectors.get((system, attrs.get('startElement')), {}).get(attrs['startConnector'])
        end = self.connectors.get((system, attrs.get('endElement')), {}).get(attrs['endConnector'])
        if start is not None and end is not None and attrs.get('suppressUnitConversion') != "true":
            self._unit_checks.append((self._connection_label(attrs), start, end))

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

    def _check_fmu_connectors(self, attrs: dict[str, str]):
        """Check both ends of a connection against the variables of their FMUs."""
        system = id(self.node_stack[-1])
        start, end = attrs.get('startElement'), attrs.get('endElement')
        if start is None:
            self._used_connectors.add((system, attrs['startConnector']))
        if end is None:
            self._used_connectors.add((system, attrs['endConnector']))
        if start is not None:
            self._check_fmu_connector(attrs, start, attrs['startConnector'],
                                      self.OUTPUT_ROLES if end is not None else self.EXPOSED_OUTPUT_ROLES)
        if end is not None:
            self._check_fmu_connector(attrs, end, attrs['endConnector'],
                                      self.INPUT_ROLES if start is not None else self.EXPOSED_INPUT_ROLES)

    def _check_fmu_connector(self, attrs: dict[str, str], element: str, connector: str, causalities: tuple[str, ...]):
        source = self._sources.get((id(self.node_stack[-1]), element))
        if source is None:
            return  # a sub-system: no FMU
        variables = self._fmu_variables(element, source)
        label = self._connection_label(attrs)
        if connector not in variables:
            close = get_close_matches(connector, list(variables), n=3)
            hint = f" Close names: {', '.join(repr(name) for name in close)}." if close else ""
            raise AssemblyError(f"'{self.ssd_filename}': {label}: component '{element}' ('{source}') has no variable "
                                f"'{connector}'.{hint}")
        if variables[connector] not in causalities:
            raise AssemblyError(f"'{self.ssd_filename}': {label}: '{connector}' of component '{element}' is "
                                f"{'an' if variables[connector][0] in 'aeiou' else 'a'} {variables[connector]}, "
                                f"not {' or '.join(f'an {c}' if c[0] in 'aeiou' else f'a {c}' for c in causalities)}.")

    def _fmu_variables(self, element: str, source: str) -> dict[str, str]:
        """Causality of each variable (and FMI 3.0 alias) of the FMU `source` of the archive."""
        if source not in self._variables:
            _, variables = self._fmu_description(element, source)
            self._variables[source] = {name: variable.causality for name, variable in variables.items()}
        return self._variables[source]

    def _fmu_description(self, element: str, source: str) -> tuple[ModelDescription, dict[str, ModelVariable]]:
        """Description of the FMU `source` of the archive, and its variables by name (FMI 3.0 aliases included)."""
        if source not in self._fmus:
            try:
                with zipfile.ZipFile(BytesIO(self.zin.read(source))) as fmu:
                    md = ModelDescription.load(fmu.read("modelDescription.xml"))
            except KeyError:
                raise AssemblyError(f"'{self.ssd_filename}': the FMU '{source}' of component '{element}' is not in "
                                    f"the SSP archive, or has no modelDescription.xml.") from None
            except (zipfile.BadZipFile, ModelDescriptionError) as error:
                raise AssemblyError(f"'{self.ssd_filename}': the FMU '{source}' of component '{element}' cannot be "
                                    f"read: {error}") from error
            variables = {}
            for element_ in md.variables():
                variable = ModelVariable(element_, md.fmi_version)
                variables[element_.get("name")] = variable
                for alias in element_.iter("Alias"):
                    variables[alias.get("name")] = variable
            self._fmus[source] = (md, variables)
        return self._fmus[source]

    def _container_annotation(self, tag_name: str, attrs):
        """The options annotation of a system written by `SSPWriter`: it prevails over the command line (E3)."""
        if not self.node_stack or not self._owners or self._owners[-1][0] != "system":
            return
        node = self.node_stack[-1]
        if tag_name == "Container":
            if attrs.get("formatVersion", CONTAINER_FORMAT_VERSION) != CONTAINER_FORMAT_VERSION:
                logger.warning(f"'{self.ssd_filename}': options annotation of '{node.name}' in format "
                               f"{attrs.get('formatVersion')}: read as format {CONTAINER_FORMAT_VERSION}.")
            for option, attribute in CONTAINER_OPTIONS.items():
                if attribute not in attrs:
                    continue
                value = attrs[attribute]
                if option == "step_size":
                    try:
                        node.step_size = float(value)
                    except ValueError:
                        logger.warning(f"'{self.ssd_filename}': step size '{value}' of '{node.name}' is not a number.")
                else:
                    setattr(node, option, value == "true")
            logger.info(f"'{self.ssd_filename}': options of '{node.name}' read from the SSP file (they prevail over "
                        f"the command line).")
        elif tag_name == "Drop":
            element, connector = attrs.get("element"), attrs.get("connector")
            if element in self.ignored_components:
                return
            if element not in self.fmu_filenames or not connector:
                raise AssemblyError(f"'{self.ssd_filename}': dropped port '{element}.{connector}' of '{node.name}' "
                                    f"refers to an unknown element.")
            node.add_drop_port(self.fmu_filenames[element], connector)

    def _apply_default_experiment(self):
        """`startTime` and `stopTime` of the `DefaultExperiment` become those of the container. SSP gives no step
        size: it comes from the command line or from the FMUs, as for any container."""
        for attribute, field in (('startTime', 'start_time'), ('stopTime', 'stop_time')):
            if attribute not in self._default_experiment:
                continue
            try:
                value = float(self._default_experiment[attribute])
            except ValueError:
                logger.warning(f"'{self.ssd_filename}': {attribute} '{self._default_experiment[attribute]}' of the "
                               f"default experiment is not a number: it is ignored.")
                continue
            setattr(self.root, field, value)
            logger.info(f"'{self.ssd_filename}': {attribute} of the container = {value} (SSP default experiment)")

    # ----------------------------------------------------------------------------------------- parameter values
    def _start_binding(self, attrs):
        """A `ParameterBinding` of the current component or system: its values, from its source if it has one."""
        kind, name = self._owners[-1] if self._owners else ("system", "")
        if kind == "component" and name in self.ignored_components:
            self._binding = None  # the component is ignored, so are its values
            return
        owner = f"{kind} '{name}'"
        binding_type = attrs.get('type', self.PARAMETER_SET_TYPE)
        if binding_type != self.PARAMETER_SET_TYPE:
            raise AssemblyError(f"'{self.ssd_filename}': a parameter binding of {owner} is of type '{binding_type}': "
                                f"only parameter sets ('{self.PARAMETER_SET_TYPE}') are supported.")
        node = self.node_stack[-1]
        self._binding = {"kind": kind, "name": name, "node": node, "prefix": attrs.get('prefix', ''),
                         "depth": self._depth[id(node)] + (1 if kind == "component" else 0),
                         "order": len(self._bindings), "values": []}
        if attrs.get('source'):
            self._binding["values"] += self._parameter_source(attrs['source'], attrs.get('sourceBase', 'SSD'),
                                                              kind, name, owner)

    def _parameter_source(self, source: str, base: str, kind: str, name: str, owner: str) -> list[tuple]:
        """The values of the `.ssv` file `source`, in the archive (`sourceBase="SSD"`) or in the FMU of the
        component (`sourceBase="component"`)."""
        path = PurePosixPath(source)
        if ":" in source or path.is_absolute() or ".." in path.parts:
            raise AssemblyError(f"'{self.ssd_filename}': the parameter source '{source}' of {owner} must be a relative "
                                f"path inside the SSP archive.")
        try:
            if base == "component":
                component_source = self._sources.get((id(self.node_stack[-1]), name)) if kind == "component" else None
                if component_source is None:
                    raise AssemblyError(f"'{self.ssd_filename}': the parameter source '{source}' of {owner} is relative "
                                        f"to a component, but {owner} is not an FMU component.")
                with zipfile.ZipFile(BytesIO(self.zin.read(component_source))) as fmu:
                    content = fmu.read(str(path))
            else:
                content = self.zin.read(str(path))
        except KeyError:
            raise AssemblyError(f"'{self.ssd_filename}': the parameter source '{source}' of {owner} is not in the "
                                f"{'FMU of the component' if base == 'component' else 'SSP archive'}.") from None
        try:
            root = ET.fromstring(content)
        except ET.ParseError as error:
            raise AssemblyError(f"'{self.ssd_filename}': the parameter source '{source}' of {owner} is not "
                                f"well-formed XML: {error}") from error
        return self._parameter_values(root, f"'{source}'")

    def _parameter_values(self, element: ET.Element, label: str) -> list[tuple[str, str, str, str | None]]:
        """(name, value type, value, unit) of each parameter of the `ssv:ParameterSet` found in `element` (itself
        or a descendant). The units it defines are added to `units`."""
        ssv, ssc = f"{{{self.SSV_NAMESPACE}}}", f"{{{self.SSC_NAMESPACE}}}"
        parameter_set = element if element.tag == f"{ssv}ParameterSet" else element.find(f".//{ssv}ParameterSet")
        if parameter_set is None:
            return []
        for unit in parameter_set.iter(f"{ssc}Unit"):
            base = unit.find(f"{ssc}BaseUnit")
            self.units.setdefault(unit.get("name"), dict(base.attrib) if base is not None else {})
        values = []
        for parameter in parameter_set.iter(f"{ssv}Parameter"):
            for child in parameter:
                local_name = child.tag.rsplit("}", 1)[-1]
                if not child.tag.startswith(ssv):
                    continue
                if local_name == "Binary":
                    raise AssemblyError(f"'{self.ssd_filename}': parameter '{parameter.get('name')}' of {label} is a "
                                        f"binary value: binary start values are not supported.")
                if local_name in self.PARAMETER_TYPES:
                    values.append((parameter.get("name"), local_name, child.get("value", ""), child.get("unit")))
                    break
        return values

    def _apply_parameters(self):
        """Resolve the values of the bindings, in the order of priority of the standard, and set them as start
        values of the variables of the embedded FMUs."""
        targets: dict[tuple[int, str, str], tuple[Any, str, str, tuple]] = {}
        # Deeper first, then in file order: what comes later takes priority, so a system overrides its elements.
        for binding in sorted(self._bindings, key=lambda b: (-b["depth"], b["order"])):
            for value in binding["values"]:
                name = binding["prefix"] + value[0]
                if binding["kind"] == "component":
                    found = self._component_targets(binding["node"], binding["name"], name)
                else:
                    found = self._system_targets(binding["node"], name)
                if found is None:
                    logger.warning(f"'{self.ssd_filename}': parameter '{name}' of {binding['kind']} "
                                   f"'{binding['name']}' matches no variable: it is ignored.")
                    continue
                for node, fmu_name, source, variable in found:
                    targets[(id(node), fmu_name, variable)] = (node, fmu_name, source, (variable,) + value[1:])
        for node, fmu_name, source, (variable, value_type, value, unit) in targets.values():
            node.add_start_value(fmu_name, variable, self._start_value(fmu_name, source, variable, value_type, value,
                                                                       unit))
            logger.debug(f"Start value of {fmu_name}/{variable} = {value} (SSP parameter binding)")

    def _component_targets(self, node, component: str, name: str):
        kind, details = self._elements.get(id(node), {}).get(component, (None, None))
        if kind != "component":
            return [] if kind == "ignored" else None
        node, fmu_name, source = details
        _, variables = self._fmu_description(component, source)
        return [(node, fmu_name, source, name)] if name in variables else None

    def _system_targets(self, node, name: str):
        """Variables of the FMUs that `name` designates in the system `node`: one of its connectors, followed
        through its connections, or `element.name` (D16)."""
        if name in self.connectors.get((id(node), None), {}):
            found = []
            for attrs in self._system_connections.get(id(node), []):
                if 'startElement' in attrs or attrs['startConnector'] != name:
                    continue
                kind, details = self._elements[id(node)].get(attrs['endElement'], (None, None))
                if kind == "component":
                    found += self._component_targets(node, attrs['endElement'], attrs['endConnector']) or []
                elif kind == "system":
                    found += self._system_targets(details, attrs['endConnector']) or []
            return found
        for element in sorted(self._elements.get(id(node), {}), key=len, reverse=True):
            if name.startswith(element + "."):
                kind, details = self._elements[id(node)][element]
                rest = name[len(element) + 1:]
                found = (self._component_targets(node, element, rest) if kind != "system"
                         else self._system_targets(details, rest))
                if found is not None:
                    return found
        return None

    def _start_value(self, fmu_name: str, source: str, variable: str, value_type: str, value: str,
                     unit: str | None) -> str:
        """The start value of `variable` for a parameter value, once checked that it can be set (D15)."""
        md, variables = self._fmus[source]
        port = variables[variable]
        label = f"'{self.ssd_filename}': parameter value for '{variable}' of '{fmu_name}'"
        causality, variability = port.causality, port.variability
        initial = port.get("initial") or ("exact" if causality in ("parameter", "structuralParameter")
                                          or variability == "constant" else "calculated")
        if variability == "constant":
            raise AssemblyError(f"{label}: the variable is a constant, it cannot be parameterized.")
        if causality != "input" and initial not in ("exact", "approx"):
            raise AssemblyError(f"{label}: the variable ({causality}, initial '{initial}') is computed by the FMU, "
                                f"it cannot be parameterized.")
        variable_unit = port.get("unit") or self._declared_attribute(md, port, "unit")
        if unit and variable_unit and not self._same_unit(unit, variable_unit):
            raise AssemblyError(f"{label}: the value is in '{unit}', the variable in '{variable_unit}': unit "
                                f"conversions are not supported.")
        if value_type == "Enumeration":
            items = self._enumeration_items(md, port)
            if value not in items:
                raise AssemblyError(f"{label}: '{value}' is not an item of its enumeration "
                                    f"({', '.join(items) or 'none found'}).")
            return items[value]
        return value

    @staticmethod
    def _declared_type(md: ModelDescription, port: ModelVariable) -> ET.Element | None:
        """The type definition of `port` (`<SimpleType>` child for FMI 2.0, `<…Type>` for FMI 3.0)."""
        name, definitions = port.get("declaredType"), md.root.find("TypeDefinitions")
        if not name or definitions is None:
            return None
        for definition in definitions:
            if definition.get("name") == name:
                return definition[0] if md.fmi_version == 2 and len(definition) else definition
        return None

    def _declared_attribute(self, md: ModelDescription, port: ModelVariable, attribute: str) -> str | None:
        definition = self._declared_type(md, port)
        return definition.get(attribute) if definition is not None else None

    def _enumeration_items(self, md: ModelDescription, port: ModelVariable) -> dict[str, str]:
        definition = self._declared_type(md, port)
        return {item.get("name"): item.get("value") for item in definition.iter("Item")} if definition is not None \
            else {}

    def _same_unit(self, first: str, second: str) -> bool:
        """Whether two units need no conversion: same name, or the same definition in `ssc:Units`."""
        if first == second:
            return True
        if first in self.units and second in self.units:
            return ({**self.BASE_UNIT_DEFAULTS, **self.units[first]} ==
                    {**self.BASE_UNIT_DEFAULTS, **self.units[second]})
        return False

    def _check_units(self):
        """Refuse a connection between connectors of different units: SSP implies a conversion (D8)."""
        for label, start, end in self._unit_checks:
            if start.unit and end.unit and not self._same_unit(start.unit, end.unit):
                raise AssemblyError(f"'{self.ssd_filename}': {label} joins connectors of different units "
                                    f"('{start.unit}' and '{end.unit}'): unit conversions are not supported.")

    def _warn_unused_dictionaries(self):
        """A signal dictionary no connection goes through changes nothing: warn only (D7)."""
        names = sorted(self._dictionaries | {name for name in self._dictionary_references.values() if name})
        references = sorted(reference for _, reference in self._dictionary_references)
        if names or references:
            logger.warning(f"'{self.ssd_filename}': signal dictionaries are not supported; "
                           f"{', '.join(repr(name) for name in names + references)} ignored (no connection uses them).")

    def _add_architecture_wire(self, attrs: dict[str, str], orientation: str):
        """Record an architecture wire between two components of the current system."""
        start, end = attrs.get('startElement'), attrs.get('endElement')
        if start is None or end is None:
            logger.warning(f"Architecture wire on connector '{attrs['startConnector']}' -> "
                           f"'{attrs['endConnector']}' is ignored: it must join two components.")
            return
        if start in self.ignored_components or end in self.ignored_components:
            logger.debug(f"Architecture wire {start} -> {end} ignored: it involves an ignored component.")
            return
        self.node_stack[-1].add_architecture_wire(self.fmu_filenames[start], self.fmu_filenames[end],
                                                  orientation, attrs.get('description'))

    @staticmethod
    def _source_path(source: str) -> PurePosixPath:
        """Path of a component source inside the archive, refused if it leaves the archive."""
        path = PurePosixPath(source)
        if path.is_absolute() or ".." in path.parts:
            raise AssemblyError(f"Component source '{source}' must be a relative path inside the SSP archive.")
        return path


class SSDConnector:
    """A connector declared in an SSD file: its element, name, kind, type and unit.

    Attributes:
        element (str): Name of the component, signal dictionary reference or system that declares it.
        name (str): Name of the connector.
        kind (str | None): `input`, `output`, `parameter`, `calculatedParameter`... as declared.
        type (str | None): Its SSC type element (`Real`, `Float64`...), `None` when it declares none.
        unit (str | None): The `unit` of its type element.
    """

    def __init__(self, element: str, name: str, kind: str | None):
        self.element = element
        self.name = name
        self.kind = kind
        self.type: str | None = None
        self.unit: str | None = None

    def __repr__(self):
        return f"SSDConnector({self.element}.{self.name}, {self.kind}, {self.type}, {self.unit})"


# --------------------------------------------------------------------------------------------------------------- #
#                                                    SSP writer                                                   #
# --------------------------------------------------------------------------------------------------------------- #
#: Annotation of a system holding the options of its container (plan `ssp_export`, E2, E8).
CONTAINER_ANNOTATION_TYPE = "fmu_manipulation_toolbox.container"
CONTAINER_NAMESPACE = "urn:fmu_manipulation_toolbox:container:1"
CONTAINER_FORMAT_VERSION = "1"

#: Options of an `AssemblyNode`, and their attribute in the annotation.
CONTAINER_OPTIONS = {"step_size": "stepSize", "mt": "mt", "profiling": "profiling", "sequential": "sequential",
                     "auto_link": "autoLink", "auto_input": "autoInput", "auto_output": "autoOutput",
                     "auto_parameter": "autoParameter", "auto_local": "autoLocal", "ts_multiplier": "tsMultiplier",
                     "reset_ports": "resetPorts"}

#: SSP 1.0 knows the FMI 2.0 types only.
SSP1_TYPES = {"Float32": "Real", "Float64": "Real", "Int8": "Integer", "UInt8": "Integer", "Int16": "Integer",
              "UInt16": "Integer", "Int32": "Integer", "UInt32": "Integer", "Int64": "Integer", "UInt64": "Integer"}


class SSPWriter:
    """Write an [Assembly][fmu_manipulation_toolbox.assembly.Assembly] as an SSP archive.

    The archive holds `SystemStructure.ssd` and the embedded FMUs, under `resources/`. Each node of the assembly is a
    system, each FMU a component, named after its file without extension. The routing is **resolved**: the links
    and exposed ports added by the `auto_*` rules of a node are computed by the container builder (without building)
    and written as connections, so that another tool sees the whole routing; the options annotation of the system
    then says `auto_*="false"`, and the file read back gives the same container.

    Also written: the start values (`ParameterBindings` with an inline parameter set), the architecture wires, the
    geometry, the units of the connectors (`suppressUnitConversion="true"` on a connection between different units:
    the container does not convert), the options and the dropped ports of each node (annotation of type
    `CONTAINER_ANNOTATION_TYPE`), and the start and stop times (`DefaultExperiment`).

    Args:
        assembly (Assembly): The assembly to write; its FMUs must be readable from its `fmu_directory`.
        ssp_version (str): `"2.0"` (default) or `"1.0"`, which writes the FMI 3.0 types as FMI 2.0 ones.
    """

    def __init__(self, assembly, ssp_version: str = "2.0"):
        if ssp_version not in ("1.0", "2.0"):
            raise AssemblyError(f"SSP version '{ssp_version}' is not supported: '1.0' or '2.0'.")
        if assembly.root is None:
            raise AssemblyError("The assembly is empty: nothing to write as SSP.")
        self.assembly = assembly
        self.ssp_version = ssp_version
        self.fmu_directory = Path(assembly.fmu_directory)
        self._sources: dict[Path, str] = {}  # FMU file => member of the archive
        self._descriptions: dict[Path, tuple[ModelDescription, dict[str, ModelVariable]]] = {}

    # ----------------------------------------------------------------------------------------------------- write
    def write(self, filename: str | Path) -> Path:
        """Write the SSP archive `filename` and return its path."""
        import tempfile

        filename = Path(filename)
        with tempfile.TemporaryDirectory() as tmp:
            system = self._system(self.assembly.root, Path(tmp))
            root = ET.Element(f"{{{SSDParser.SSD_NAMESPACE}}}SystemStructureDescription",
                              {"version": self.ssp_version, "name": Path(self.assembly.root.name).stem,
                               "generationTool": f"fmu_manipulation_toolbox {_version()}"})
            root.append(system)
            experiment = {key: repr(float(value)) for key, value in (("startTime", self.assembly.root.start_time),
                                                                     ("stopTime", self.assembly.root.stop_time))
                          if value is not None}
            if experiment:
                ET.SubElement(root, f"{{{SSDParser.SSD_NAMESPACE}}}DefaultExperiment", experiment)
            ET.register_namespace("ssd", SSDParser.SSD_NAMESPACE)
            ET.register_namespace("ssc", SSDParser.SSC_NAMESPACE)
            ET.register_namespace("ssv", SSDParser.SSV_NAMESPACE)
            ET.register_namespace("aw", SSDParser.ARCHITECTURE_WIRE_NAMESPACE)
            ET.register_namespace("fc", CONTAINER_NAMESPACE)
            ET.indent(root)
            ssd = ET.tostring(root, encoding="UTF-8", xml_declaration=True)

        with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("SystemStructure.ssd", ssd)
            for path, member in self._sources.items():
                archive.write(path, member)
        logger.info(f"SSP file '{filename}' written (SSP {self.ssp_version}, {len(self._sources)} FMU(s)).")
        return filename

    # ---------------------------------------------------------------------------------------------------- system
    def _system(self, node, tmp: Path) -> ET.Element:
        """The `ssd:System` of `node`; its sub-systems first, their interface written in `tmp`."""
        ssd = f"{{{SSDParser.SSD_NAMESPACE}}}"
        children = {name: (self._system(child, tmp), self._interface(child, tmp))
                    for name, child in node.children.items()}
        container = self._resolved(node, {name: interface for name, (_, interface) in children.items()})

        # Element of each FMU of the builder (named after the file name of the FMU, see `FMUContainer.get_fmu`).
        elements: dict[str, str] = {}  # name in the builder => element
        files: dict[str, Path] = {}  # element => file of its FMU
        for name in node.children:
            elements[Path(name).name] = Path(name).stem
            files[Path(name).stem] = children[name][1]
        for fmu_name in node.fmu_names_list:
            element = _unique(Path(fmu_name).stem, set(elements.values()))
            elements[Path(fmu_name).name] = element
            files[element] = self.fmu_directory / node.fmu_path(fmu_name)

        system = ET.Element(f"{ssd}System", {"name": Path(node.name).stem})
        connectors: dict[str, dict[str, ET.Element]] = {element: {} for element in files}
        system_connectors: dict[str, ET.Element] = {}
        connections: list[ET.Element] = []

        def connector(element: str, port: str, kind: str | None = None) -> ET.Element:
            if port not in connectors[element]:
                connectors[element][port] = self._connector(files[element], port, kind)
            return connectors[element][port]

        def connection(start_element, start, end_element, end, start_connector, end_connector):
            attrs = {}
            if start_element is not None:
                attrs["startElement"] = start_element
            attrs["startConnector"] = start
            if end_element is not None:
                attrs["endElement"] = end_element
            attrs["endConnector"] = end
            if _unit(start_connector) and _unit(end_connector) and _unit(start_connector) != _unit(end_connector):
                attrs["suppressUnitConversion"] = "true"  # the container does not convert (E10)
            connections.append(ET.Element(f"{ssd}Connection", attrs))

        for name, container_input in container.inputs.items():
            for cport in container_input.cport_list:
                if cport.port.is_reset:
                    continue  # `container.reset`: added again by `reset_ports` when read back
                element = elements[cport.fmu.name]
                end = connector(element, cport.port.name)
                if name not in system_connectors:
                    system_connectors[name] = self._system_connector(name, end, "input")
                connection(None, name, element, cport.port.name, system_connectors[name], end)
        for name, cport in container.outputs.items():
            element = elements[cport.fmu.name]
            start = connector(element, cport.port.name)
            system_connectors[name] = self._system_connector(name, start, "output")
            connection(element, cport.port.name, None, name, start, system_connectors[name])
        for link in container.links.values():
            if link.cport_from is None:
                logger.debug(f"Link '{link.name}' without source (clock of the importer) is not written.")
                continue
            start_element = elements[link.cport_from.fmu.name]
            start = connector(start_element, link.cport_from.port.name)
            for cport in link.cport_to_list:
                end_element = elements[cport.fmu.name]
                connection(start_element, link.cport_from.port.name, end_element, cport.port.name, start,
                           connector(end_element, cport.port.name))

        # Architecture wires: synthetic connectors `aw.<peer>` (container.md#architecture-wires).
        by_fmu = {fmu_name: elements[Path(fmu_name).name] for fmu_name in list(node.fmu_names_list) + list(node.children)}
        for wire in node.architecture_wires:
            start, end = by_fmu.get(wire.start_fmu), by_fmu.get(wire.end_fmu)
            if start is None or end is None:
                continue
            directed = wire.orientation == "directed"
            connectors[start][f"aw.{end}"] = ET.Element(f"{ssd}Connector", {"name": f"aw.{end}", "kind":
                                                       "output" if directed else "unspecified"})
            connectors[end][f"aw.{start}"] = ET.Element(f"{ssd}Connector", {"name": f"aw.{start}", "kind":
                                                       "input" if directed else "unspecified"})
            attrs = {"startElement": start, "startConnector": f"aw.{end}", "endElement": end,
                     "endConnector": f"aw.{start}"}
            if wire.description:
                attrs["description"] = wire.description
            wire_connection = ET.Element(f"{ssd}Connection", attrs)
            annotation = ET.SubElement(ET.SubElement(wire_connection, f"{ssd}Annotations"),
                                       f"{{{SSDParser.SSC_NAMESPACE}}}Annotation",
                                       {"type": SSDParser.ARCHITECTURE_WIRE_TYPE})
            ET.SubElement(annotation, f"{{{SSDParser.ARCHITECTURE_WIRE_NAMESPACE}}}Wire",
                          {"formatVersion": "1", "orientation": wire.orientation})
            connections.append(wire_connection)

        # Start values: one binding per element, on the components (and on the sub-systems: their connectors).
        values: dict[str, list[tuple[str, str]]] = {}
        for port, value in node.start_values.items():
            values.setdefault(elements[Path(port.fmu_name).name], []).append((port.port_name, value))
            connector(elements[Path(port.fmu_name).name], port.port_name)

        if system_connectors:
            system.append(self._connectors(system_connectors.values()))
        element_list = ET.SubElement(system, f"{ssd}Elements")
        for element, path in files.items():
            if element in {Path(name).stem for name in node.children}:
                child = next(child_system for name, (child_system, _) in children.items()
                             if Path(name).stem == element)
                if values.get(element):
                    self._insert_bindings(child, self._bindings(path, values[element]))
                element_list.append(child)
                continue
            component = ET.SubElement(element_list, f"{ssd}Component",
                                      {"name": element, "type": SSDParser.FMU_COMPONENT_TYPE,
                                       "source": self._source(path)})
            if connectors[element]:
                component.append(self._connectors(connectors[element].values()))
            fmu_name = next(name for name in node.fmu_names_list if elements[Path(name).name] == element)
            if fmu_name in node.fmu_geometry:
                x1, y1, x2, y2 = node.fmu_geometry[fmu_name]
                ET.SubElement(component, f"{ssd}ElementGeometry",
                              {"x1": repr(x1), "y1": repr(y1), "x2": repr(x2), "y2": repr(y2)})
            if values.get(element):
                component.append(self._bindings(path, values[element]))
        connections_element = ET.SubElement(system, f"{ssd}Connections")
        connections_element.extend(connections)
        system.append(self._options_annotation(node, elements))
        return system

    def _resolved(self, node, interfaces: dict[str, Path]):
        """The container builder of `node`, its rules applied (explicit, then `auto_*`), without building."""
        from .container import FMUContainer

        container = FMUContainer(Path(node.name).stem, self.fmu_directory, fmi_version=self._fmi_version(node),
                                 reset_ports=node.reset_ports)
        for name, interface in interfaces.items():
            container.get_fmu(str(interface), name)
        for fmu_name in node.fmu_names_list:
            container.get_fmu(node.fmu_path(fmu_name), fmu_name)
        for port, source in node.input_ports.items():
            container.add_input(source, port.fmu_name, port.port_name)
        for port, target in node.output_ports.items():
            container.add_output(port.fmu_name, port.port_name, target)
        for link in node.links:
            container.add_link(link.from_port.fmu_name, link.from_port.port_name,
                               link.to_port.fmu_name, link.to_port.port_name)
        for drop in node.drop_ports:
            container.drop_port(drop.fmu_name, drop.port_name)
        container.add_implicit_rule(auto_input=node.auto_input, auto_output=node.auto_output,
                                    auto_link=node.auto_link, auto_parameter=node.auto_parameter,
                                    auto_local=node.auto_local)
        return container

    def _interface(self, node, tmp: Path) -> Path:
        """An FMU holding only the `modelDescription.xml` of the container of `node`: its interface, for its parent."""
        from .container.layout import ContainerLayout

        container = self._resolved(node, {name: self._interface(child, tmp) for name, child in node.children.items()})
        layout = ContainerLayout.allocate(container.links.values(), container.inputs, container.outputs,
                                          nb_profiling=0)
        directory = tmp / Path(node.name).stem
        directory.mkdir(parents=True, exist_ok=True)
        try:
            step_size = node.step_size or container.default_step_size()
        except Exception:  # noqa: BLE001 - the step size does not change the interface
            step_size = 1.0
        container.make_fmu_xml(directory / "modelDescription.xml", step_size, False, False, layout)
        interface = tmp / f"{Path(node.name).stem}.fmu"
        with zipfile.ZipFile(interface, "w") as fmu:
            fmu.write(directory / "modelDescription.xml", "modelDescription.xml")
        return interface

    def _fmi_version(self, node) -> int:
        """FMI version of the interface of a sub-container: 3 when one of its FMUs is FMI 3.0 (its types)."""
        versions = {self._description(self.fmu_directory / node.fmu_path(name))[0].fmi_version
                    for name in node.fmu_names_list}
        versions |= {self._fmi_version(child) for child in node.children.values()}
        return 3 if 3 in versions else 2

    # ------------------------------------------------------------------------------------------------ connectors
    def _description(self, path: Path) -> tuple[ModelDescription, dict[str, ModelVariable]]:
        if path not in self._descriptions:
            with zipfile.ZipFile(path) as fmu:
                md = ModelDescription.load(fmu.read("modelDescription.xml"))
            variables = {}
            for element in md.variables():
                variable = ModelVariable(element, md.fmi_version)
                variables[element.get("name")] = variable
                for alias in element.iter("Alias"):
                    variables[alias.get("name")] = variable
            self._descriptions[path] = (md, variables)
        return self._descriptions[path]

    def _type(self, fmi_type: str | None) -> str | None:
        if fmi_type is None or fmi_type == "Clock":
            return None
        return SSP1_TYPES.get(fmi_type, fmi_type) if self.ssp_version == "1.0" else fmi_type

    def _connector(self, path: Path, port: str, kind: str | None = None) -> ET.Element:
        """The `ssd:Connector` of the variable `port` of the FMU `path`: its causality, type and unit."""
        md, variables = self._description(path)
        variable = variables[port]
        causality = variable.causality
        kind = kind or (causality if causality in ("input", "output", "parameter", "calculatedParameter",
                                                   "structuralParameter") else "output")
        element = ET.Element(f"{{{SSDParser.SSD_NAMESPACE}}}Connector", {"name": port, "kind": kind})
        if variable.get("description"):
            element.set("description", variable.get("description"))
        ssp_type = self._type(variable.fmi_type)
        if ssp_type is not None:
            attrs = {}
            unit = variable.get("unit") or _declared_attribute(md, variable, "unit")
            if unit and ssp_type in ("Real", "Float32", "Float64"):
                attrs["unit"] = unit
            if ssp_type == "Enumeration":
                attrs["name"] = variable.get("declaredType") or ""
            element.append(ET.Element(f"{{{SSDParser.SSC_NAMESPACE}}}{ssp_type}", attrs))
        return element

    def _system_connector(self, name: str, inner: ET.Element, kind: str) -> ET.Element:
        """A connector of the system, of the type of the connector it is connected to."""
        if inner.get("kind") == "parameter" and kind == "input":
            kind = "parameter"
        element = ET.Element(f"{{{SSDParser.SSD_NAMESPACE}}}Connector", {"name": name, "kind": kind})
        for child in inner:
            element.append(ET.Element(child.tag, dict(child.attrib)))
        return element

    @staticmethod
    def _connectors(items) -> ET.Element:
        element = ET.Element(f"{{{SSDParser.SSD_NAMESPACE}}}Connectors")
        element.extend(items)
        return element

    # ------------------------------------------------------------------------------------------- values, options
    def _bindings(self, path: Path, values: list[tuple[str, str]]) -> ET.Element:
        """`ParameterBindings` with an inline parameter set: the start values of the element `path`."""
        ssd, ssv = f"{{{SSDParser.SSD_NAMESPACE}}}", f"{{{SSDParser.SSV_NAMESPACE}}}"
        md, variables = self._description(path)
        bindings = ET.Element(f"{ssd}ParameterBindings")
        parameter_values = ET.SubElement(ET.SubElement(bindings, f"{ssd}ParameterBinding"), f"{ssd}ParameterValues")
        parameter_set = ET.SubElement(parameter_values, f"{ssv}ParameterSet",
                                      {"version": self.ssp_version, "name": "start values"})
        parameters = ET.SubElement(parameter_set, f"{ssv}Parameters")
        for name, value in values:
            variable = variables.get(name)
            value_type = self._type(variable.fmi_type if variable is not None else None) or "String"
            value = "true" if value is True else "false" if value is False else str(value)
            if value_type == "Enumeration":
                items = {item_value: item for item, item_value in
                         SSDParser._enumeration_items(SSDParser, md, variable).items()}
                if value in items:
                    value = items[value]
                else:
                    value_type = "Integer"
            parameter = ET.SubElement(parameters, f"{ssv}Parameter", {"name": name})
            ET.SubElement(parameter, f"{ssv}{value_type}", {"value": value})
        return bindings

    @staticmethod
    def _insert_bindings(system: ET.Element, bindings: ET.Element):
        """`ParameterBindings` of a system go after its connectors (order of the SSD schema)."""
        position = 1 if len(system) and system[0].tag.endswith("}Connectors") else 0
        system.insert(position, bindings)

    @staticmethod
    def _options_annotation(node, elements: dict[str, str]) -> ET.Element:
        """The options of the container of `node` (resolved routing: `auto_*` false) and its dropped ports."""
        ssd = f"{{{SSDParser.SSD_NAMESPACE}}}"
        annotations = ET.Element(f"{ssd}Annotations")
        annotation = ET.SubElement(annotations, f"{{{SSDParser.SSC_NAMESPACE}}}Annotation",
                                   {"type": CONTAINER_ANNOTATION_TYPE})
        attrs = {"formatVersion": CONTAINER_FORMAT_VERSION}
        for option, attribute in CONTAINER_OPTIONS.items():
            value = getattr(node, option)
            if option.startswith("auto_"):
                value = False  # the routing is written resolved (E9)
            if option == "step_size":
                if value is not None:
                    attrs[attribute] = repr(float(value))
            else:
                attrs[attribute] = "true" if value else "false"
        container = ET.SubElement(annotation, f"{{{CONTAINER_NAMESPACE}}}Container", attrs)
        for drop in node.drop_ports:
            ET.SubElement(container, f"{{{CONTAINER_NAMESPACE}}}Drop",
                          {"element": elements[Path(drop.fmu_name).name], "connector": drop.port_name})
        return annotations

    def _source(self, path: Path) -> str:
        """Member of the archive for the FMU file `path`: `resources/...`, one member per file (E6)."""
        path = Path(path)
        if path not in self._sources:
            try:
                relative = path.resolve().relative_to(self.fmu_directory.resolve())
            except ValueError:
                relative = Path(path.name)
            parts = relative.parts
            # An FMU extracted from an SSP file (`<file>.dir/resources/...`) keeps its path inside the archive.
            if len(parts) > 2 and parts[0].endswith(".dir") and parts[1] == "resources":
                parts = parts[2:]
            member = PurePosixPath("resources", *parts).as_posix()
            used = set(self._sources.values())
            stem, index = member[:-len(".fmu")] if member.endswith(".fmu") else member, 1
            while member in used:
                member = f"{stem}-{index}.fmu"
                index += 1
            self._sources[path] = member
        return self._sources[path]


def _unique(name: str, used: set[str]) -> str:
    candidate, index = name, 1
    while candidate in used:
        candidate = f"{name}-{index}"
        index += 1
    return candidate


def _unit(connector: ET.Element) -> str | None:
    for child in connector:
        if child.get("unit"):
            return child.get("unit")
    return None


def _declared_attribute(md: ModelDescription, variable: ModelVariable, attribute: str) -> str | None:
    definition = SSDParser._declared_type(md, variable)
    return definition.get(attribute) if definition is not None else None


def _version() -> str:
    from .version import __version__
    return __version__
