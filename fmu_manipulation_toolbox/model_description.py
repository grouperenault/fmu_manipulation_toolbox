"""In-memory model of `modelDescription.xml`, based on ElementTree.

This module is the core of the migration away from the hand-written expat/print
rewriting of `modelDescription.xml` (see `docs/refactoring.md`). It loads the
descriptor into an ElementTree, gives access to its variables and model
structure, and writes it back. Operations modify the tree **in place**, so
everything they do not touch (annotations, aliases, comments, namespaces,
type definitions, ...) is preserved, and escaping is done by the serializer.

Conformity with FMI 2.0.5 and FMI 3.0.2 (fmi-standard.org):

- The file is written in UTF-8 and starts with the XML declaration, as required
  by both standards (FMI-2 §2.2, FMI-3 §2.4: "The first line of an XML file
  [...] must contain the encoding scheme [...] always UTF-8").
- Element order is preserved: it is significant for both standards (e.g. the
  order of `<ScalarVariable>` defines the FMI-2 `index`, the order of
  `<ContinuousStateDerivative>` defines the FMI-3 state vector).
- FMI-2 type definitions (`<TypeDefinitions><SimpleType><Real/>`) share their
  tag names with variable types; only children of `<ModelVariables>` are
  considered as variables.

This module has no dependency on the rest of the package.
"""
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import Dict, IO, Iterator, List, MutableMapping, Optional, Tuple, Union

__all__ = ["ModelDescription", "ModelDescriptionError", "ModelVariable", "PrefixedAttributes"]

PathOrBytes = Union[str, Path, bytes]

XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>\n'


class ModelDescriptionError(Exception):
    """Raised when a `modelDescription.xml` cannot be loaded or is not an FMI 2.0/3.0 descriptor."""


class _TreeBuilder(ET.TreeBuilder):
    """`TreeBuilder` that also keeps what ElementTree drops by default.

    - namespace prefixes, to write vendor annotations back with their own
      prefixes instead of `ns0:`;
    - comments and processing instructions located before or after the root
      element (`TreeBuilder` only inserts those found inside the root).
    """

    def __init__(self):
        super().__init__(insert_comments=True, insert_pis=True)
        self.namespaces: List[Tuple[str, str]] = []
        self.prolog: List[ET.Element] = []
        self.epilog: List[ET.Element] = []
        self._depth = 0
        self._root_seen = False

    def start_ns(self, prefix: str, uri: str):
        self.namespaces.append((prefix, uri))

    def start(self, tag, attrs):
        self._depth += 1
        self._root_seen = True
        return super().start(tag, attrs)

    def end(self, tag):
        self._depth -= 1
        return super().end(tag)

    def comment(self, text):
        if self._depth:
            return super().comment(text)
        self._outside_root().append(ET.Comment(text))

    def pi(self, target, text=None):
        if self._depth:
            return super().pi(target, text)
        self._outside_root().append(ET.ProcessingInstruction(target, text))

    def _outside_root(self) -> List[ET.Element]:
        return self.epilog if self._root_seen else self.prolog


class _StartValue(MutableMapping):
    """FMI-3 `<Start value="..."/>` element seen as the `{"start": value}` mapping.

    `FMUPort` exposes the start values of `String`/`Binary` variables as an
    extra attribute level holding the key `start`; this proxy keeps that view
    while reading from and writing to the `<Start>` element itself.
    """

    KEY = "start"

    def __init__(self, element: ET.Element):
        self.element = element

    def __getitem__(self, key):
        if key != self.KEY:
            raise KeyError(key)
        return self.element.get("value", "")

    def __setitem__(self, key, value):
        if key != self.KEY:
            raise KeyError(key)
        self.element.set("value", value)

    def __delitem__(self, key):
        if key != self.KEY:
            raise KeyError(key)
        self.element.attrib.pop("value", None)

    def __iter__(self):
        return iter((self.KEY,))

    def __len__(self):
        return 1


class PrefixedAttributes(MutableMapping):
    """Attributes of an element, with namespaced names written `prefix:name`.

    ElementTree names a namespaced attribute `{uri}name`. Callbacks written for
    the former expat implementation expect the name found in the file, e.g.
    `xsi:noNamespaceSchemaLocation`; this view translates names both ways and
    reads from / writes to the element's `attrib`.
    """

    def __init__(self, attrib: Dict[str, str], namespaces: List[Tuple[str, str]]):
        self.attrib = attrib
        self._prefixes = {uri: prefix for prefix, uri in namespaces if prefix}
        self._uris = {prefix: uri for prefix, uri in namespaces if prefix}

    def _prefixed(self, key: str) -> str:
        if key.startswith("{"):
            uri, name = key[1:].split("}", 1)
            if uri in self._prefixes:
                return f"{self._prefixes[uri]}:{name}"
        return key

    def _qualified(self, key: str) -> str:
        prefix, separator, name = key.partition(":")
        if separator and prefix in self._uris:
            return f"{{{self._uris[prefix]}}}{name}"
        return key

    def __getitem__(self, key):
        return self.attrib[self._qualified(key)]

    def __setitem__(self, key, value):
        self.attrib[self._qualified(key)] = value

    def __delitem__(self, key):
        del self.attrib[self._qualified(key)]

    def __iter__(self):
        return (self._prefixed(key) for key in list(self.attrib))

    def __len__(self):
        return len(self.attrib)

    def __repr__(self):
        return repr(dict(self.items()))


class ModelVariable:
    """View on one variable of `<ModelVariables>`, compatible with `FMUPort`.

    It offers the same interface as `operations.FMUPort` (`[]`, `get()`, `in`,
    `fmi_type`, `attrs_list`, `dimensions`), but reads and writes the tree
    directly: `attrs_list` holds the `attrib` dictionaries of the underlying
    elements, so a change made through this view is a change of the document.

    Attributes:
        element (ET.Element): `<ScalarVariable>` (FMI-2) or the typed variable
            element, e.g. `<Float64>` (FMI-3).
        fmi_version (int): `2` or `3`.
    """

    def __init__(self, element: ET.Element, fmi_version: int):
        self.element = element
        self.fmi_version = fmi_version

    @property
    def typed_element(self) -> Optional[ET.Element]:
        """Element carrying the type: the child `<Real>`, `<Integer>`... (FMI-2) or the variable itself (FMI-3)."""
        if self.fmi_version == 3:
            return self.element
        for child in self.element:
            if child.tag in ModelDescription.FMI2_VARIABLE_TYPES:
                return child
        return None

    @property
    def fmi_type(self) -> Optional[str]:
        typed = self.typed_element
        return typed.tag if typed is not None else None

    @fmi_type.setter
    def fmi_type(self, fmi_type: str):
        typed = self.typed_element
        if typed is None:
            raise ModelDescriptionError(f"Variable '{self.element.get('name')}' has no type element")
        typed.tag = fmi_type

    @property
    def attrs_list(self) -> List[MutableMapping[str, str]]:
        """Attribute dictionaries, outermost element first.

        FMI-2: `[<ScalarVariable> attributes, <Real>/<Integer>/... attributes]`.
        FMI-3: `[<Float64>/... attributes]`, followed by one `{"start": value}`
        mapping per `<Start>` element (`String` and `Binary` variables).
        """
        if self.fmi_version == 2:
            typed = self.typed_element
            return [self.element.attrib] + ([typed.attrib] if typed is not None else [])
        return [self.element.attrib] + [_StartValue(start) for start in self.element.findall("Start")]

    @property
    def dimensions(self) -> List[Tuple[str, int]]:
        """FMI-3 `<Dimension>` elements as `("start", size)` or `("valueReference", vr)`.

        A single dimension of size 1 is reported as a scalar (`[]`), as
        `FMUPort.dimensions` does.
        """
        if self.fmi_version == 2:
            return []
        dimensions = [(key, int(value))
                      for dimension in self.element.findall("Dimension")
                      for key, value in dimension.attrib.items()]
        return [] if dimensions == [("start", 1)] else dimensions

    def __contains__(self, item) -> bool:
        return any(item in attrs for attrs in self.attrs_list)

    def __getitem__(self, item) -> str:
        for attrs in self.attrs_list:
            if item in attrs:
                return attrs[item]
        raise KeyError(item)

    def __setitem__(self, key, value):
        """Change an existing attribute. Raises `KeyError` if no level holds `key` (as `FMUPort`)."""
        for attrs in self.attrs_list:
            if key in attrs:
                attrs[key] = value
                return
        raise KeyError(key)

    def get(self, item, default_value=None):
        try:
            return self[item]
        except KeyError:
            return default_value

    def __repr__(self):
        return f"<ModelVariable {self.fmi_type} '{self.element.get('name')}'>"


class ModelDescription:
    """`modelDescription.xml` loaded as an ElementTree.

    Attributes:
        root (ET.Element): The `<fmiModelDescription>` element.
        fmi_version (int): Major FMI version, `2` or `3`.
        namespaces (list[tuple[str, str]]): `(prefix, uri)` declarations found
            in the document, restored when saving.
        prolog (list[ET.Element]): Comments and processing instructions before
            the root element.
        epilog (list[ET.Element]): Comments and processing instructions after
            the root element.
    """

    FMI2_VARIABLE_TYPES = ("Real", "Integer", "Boolean", "String", "Enumeration")
    FMI3_VARIABLE_TYPES = ("Float32", "Float64",
                           "Int8", "UInt8", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64",
                           "Boolean", "String", "Binary", "Enumeration", "Clock")
    INTERFACE_TYPES = ("ModelExchange", "CoSimulation", "ScheduledExecution")  # ScheduledExecution: FMI-3 only
    FMI2_STRUCTURE_SECTIONS = ("Outputs", "Derivatives", "InitialUnknowns")
    FMI3_STRUCTURE_ELEMENTS = ("Output", "ContinuousStateDerivative", "ClockedState", "InitialUnknown",
                               "EventIndicator")

    def __init__(self, root: ET.Element, namespaces=(), prolog=(), epilog=()):
        if root.tag != "fmiModelDescription":
            raise ModelDescriptionError(f"Root element is <{root.tag}>, expected <fmiModelDescription>")
        self.root = root
        self.namespaces: List[Tuple[str, str]] = list(namespaces)
        self.prolog: List[ET.Element] = list(prolog)
        self.epilog: List[ET.Element] = list(epilog)
        self.fmi_version = self._major_version(root.get("fmiVersion"))
        self._parents: Dict[ET.Element, ET.Element] = {}

    @staticmethod
    def _major_version(fmi_version: Optional[str]) -> int:
        try:
            major = int(fmi_version.split(".", 1)[0])
        except (AttributeError, ValueError):
            raise ModelDescriptionError(f"Invalid fmiVersion '{fmi_version}'")
        if major not in (2, 3):
            raise ModelDescriptionError(f"Unsupported fmiVersion '{fmi_version}': expected FMI 2.0 or 3.0")
        return major

    # ------------------------------------------------------------------ I/O
    @classmethod
    def load(cls, source: PathOrBytes) -> "ModelDescription":
        """Parse a descriptor from a file path or from its raw bytes.

        Raises:
            ModelDescriptionError: If the document is not well-formed or is not
                an FMI 2.0/3.0 model description.
        """
        builder = _TreeBuilder()
        parser = ET.XMLParser(target=builder)
        try:
            if isinstance(source, bytes):
                parser.feed(source)
            else:
                with open(source, "rb") as file:
                    for chunk in iter(lambda: file.read(1 << 16), b""):
                        parser.feed(chunk)
            root = parser.close()
        except ET.ParseError as error:
            raise ModelDescriptionError(f"'{source if not isinstance(source, bytes) else '<bytes>'}' "
                                        f"is not well-formed XML: {error}") from error
        return cls(root, builder.namespaces, builder.prolog, builder.epilog)

    def save(self, destination: Union[str, Path, IO[bytes]]) -> None:
        """Write the descriptor in UTF-8, with the XML declaration on the first line."""
        if isinstance(destination, (str, Path)):
            with open(destination, "wb") as file:
                self._write(file)
        else:
            self._write(destination)

    def to_bytes(self) -> bytes:
        buffer = BytesIO()
        self._write(buffer)
        return buffer.getvalue()

    def _write(self, file: IO[bytes]) -> None:
        self._register_namespaces()
        file.write(XML_DECLARATION)
        for node in self.prolog:
            file.write(ET.tostring(node, encoding="utf-8") + b"\n")
        ET.ElementTree(self.root).write(file, encoding="utf-8", xml_declaration=False, short_empty_elements=True)
        for node in self.epilog:
            file.write(b"\n" + ET.tostring(node, encoding="utf-8"))
        file.write(b"\n")

    def _register_namespaces(self) -> None:
        # ElementTree only knows a global prefix registry: (re-)register just
        # before writing so that another document cannot steal a prefix.
        for prefix, uri in self.namespaces:
            if prefix:  # a default namespace cannot be registered: ElementTree writes it with a generated prefix
                try:
                    ET.register_namespace(prefix, uri)
                except ValueError:  # reserved "ns<digits>" prefixes
                    pass

    # ------------------------------------------------------------ Structure
    @property
    def variable_types(self) -> Tuple[str, ...]:
        return self.FMI2_VARIABLE_TYPES if self.fmi_version == 2 else self.FMI3_VARIABLE_TYPES

    @property
    def model_variables(self) -> ET.Element:
        model_variables = self.root.find("ModelVariables")
        if model_variables is None:
            raise ModelDescriptionError("<ModelVariables> is missing")
        return model_variables

    @property
    def model_structure(self) -> Optional[ET.Element]:
        return self.root.find("ModelStructure")

    @property
    def default_experiment(self) -> Optional[ET.Element]:
        return self.root.find("DefaultExperiment")

    @property
    def interfaces(self) -> Dict[str, ET.Element]:
        """Interface type elements present in the document, e.g. `{"CoSimulation": <element>}`."""
        return {child.tag: child for child in self.root if child.tag in self.INTERFACE_TYPES}

    def variables(self) -> List[ET.Element]:
        """Variable elements, in document order (comments excluded).

        For FMI-2, the position in this list plus one is the `index` used by
        `<ModelStructure>` and by the `derivative` attribute.
        """
        tags = ("ScalarVariable",) if self.fmi_version == 2 else self.FMI3_VARIABLE_TYPES
        return [element for element in self.model_variables if element.tag in tags]

    def iter_ports(self) -> Iterator[ModelVariable]:
        """`FMUPort`-compatible views on the variables, in document order."""
        for element in self.variables():
            yield ModelVariable(element, self.fmi_version)

    def model_structure_entries(self) -> List[Tuple[str, ET.Element]]:
        """Entries of `<ModelStructure>` as `(section, element)`, in document order.

        FMI-2: `section` is the enclosing list (`"Outputs"`, `"Derivatives"`,
        `"InitialUnknowns"`) and `element` an `<Unknown>` (1-based `index`).
        FMI-3: `section` is the tag of the entry itself (`"Output"`,
        `"ContinuousStateDerivative"`, ...) which refers to a `valueReference`.
        This is the convention of `OperationAbstract.model_structure_attrs`.
        """
        structure = self.model_structure
        if structure is None:
            return []
        if self.fmi_version == 2:
            return [(section.tag, unknown)
                    for section in structure if section.tag in self.FMI2_STRUCTURE_SECTIONS
                    for unknown in section if unknown.tag == "Unknown"]
        return [(entry.tag, entry) for entry in structure if entry.tag in self.FMI3_STRUCTURE_ELEMENTS]

    def attributes(self, element: ET.Element) -> PrefixedAttributes:
        """Attributes of `element`, namespaced ones named `prefix:name` as in the file."""
        return PrefixedAttributes(element.attrib, self.namespaces)

    def parent_of(self, element: ET.Element) -> Optional[ET.Element]:
        """Parent of `element`, or `None` for the root. Raises `KeyError` if not in the document."""
        if element is self.root:
            return None
        parent = self._parents.get(element)
        if parent is None or not any(child is element for child in parent):
            self._parents = {child: parent for parent in self.root.iter() for child in parent}
            parent = self._parents[element]
        return parent
