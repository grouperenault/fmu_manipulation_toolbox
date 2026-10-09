import csv
import logging
import os
import re
import shutil
import tempfile
import warnings
import weakref
import xml.etree.ElementTree as ET
import zipfile
import hashlib
from typing import *

from .model_description import ModelDescription, ModelDescriptionError, ModelVariable
from .terminals import Terminals

logger = logging.getLogger("fmu_manipulation_toolbox")

class FMU:
    """Unpack and repack facilities for FMU archives.

    Extracts an FMU (`.fmu` zip archive) into a temporary directory so that
    operations can be applied to its `modelDescription.xml` descriptor.
    After manipulation, the FMU can be repacked into a new archive.

    The temporary directory is removed by `close()`, at the end of a `with`
    block, or at the latest when the object is garbage-collected or the
    interpreter exits:

        with FMU("module.fmu") as fmu:
            fmu.apply_operation(OperationStripTopLevel())
            fmu.repack("module-stripped.fmu")

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
        # Unlike `__del__`, a finalizer also runs at interpreter exit, and never on a half-built object.
        self._finalizer = weakref.finalize(self, shutil.rmtree, self.tmp_directory, ignore_errors=True)
        self.descriptor_filename = os.path.join(self.tmp_directory, "modelDescription.xml")

        try:
            self._extract()
        except FMUError:
            self.close()
            raise

    def _extract(self):
        try:
            with zipfile.ZipFile(self.fmu_filename) as zin:
                zin.extractall(self.tmp_directory)
        except FileNotFoundError:
            raise FMUError(f"'{self.fmu_filename}' does not exist") from None
        except (IsADirectoryError, PermissionError) as error:
            raise FMUError(f"'{self.fmu_filename}' cannot be read: {error.strerror}") from None
        except zipfile.BadZipFile:
            raise FMUError(f"'{self.fmu_filename}' is not valid: not a ZIP archive") from None
        if not os.path.isfile(self.descriptor_filename):
            raise FMUError(f"'{self.fmu_filename}' is not valid: modelDescription.xml not found")

    def close(self):
        """Remove the temporary directory. The FMU can no longer be used afterwards."""
        self._finalizer()

    @property
    def closed(self) -> bool:
        return not self._finalizer.alive

    def _check_open(self):
        if self.closed:
            raise FMUError(f"'{self.fmu_filename}' is closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def save_descriptor(self, filename):
        """Save a copy of the current `modelDescription.xml` to a file.

        Args:
            filename (str): Destination path for the descriptor copy.
        """
        self._check_open()
        shutil.copyfile(self.descriptor_filename, filename)

    def repack(self, filename):
        """Repack the (possibly modified) FMU into a new `.fmu` archive.

        Args:
            filename (str): Output path for the repacked FMU.
        """
        self._check_open()
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
        self._check_open()
        manipulation = Manipulation(operation, self)
        manipulation.manipulate(self.descriptor_filename, apply_on)


class FMUPort(ModelVariable):
    """Represents a port (variable) of `modelDescription.xml`.

    This is the object given to
    [OperationAbstract.port_attrs][fmu_manipulation_toolbox.operations.OperationAbstract.port_attrs]:
    a view on one variable of the descriptor tree (see
    [ModelVariable][fmu_manipulation_toolbox.model_description.ModelVariable]).
    Reading or changing an attribute through `[]` reads or changes the
    descriptor itself.

    Supports dict-like access to attributes across all levels: for FMI 2.0, the
    `<ScalarVariable>` attributes and those of its type element (e.g. `<Real>`);
    for FMI 3.0, the attributes of the variable element and the values of its
    `<Start>` elements (`String` and `Binary` variables), under the key `start`.

    Attributes:
        fmi_type (str | None): The FMI type name (e.g. `"Real"`, `"Float64"`).
            Setting it renames the type element.
        attrs_list (list[dict[str, str]]): Attribute dictionaries, one per
            XML nesting level.
        dimensions (list[tuple[str, int]]): Array dimensions (FMI 3.0).

    Note:
        `FMUPort()` without element builds a *detached* port, filled with
        `push_attrs()`. This was the only way to build a port before the
        ElementTree implementation; it is deprecated.
    """

    def __init__(self, element: Optional[ET.Element] = None, fmi_version: int = 0):
        super().__init__(element, fmi_version)
        self._detached_levels: Optional[List[Dict[str, str]]] = None
        self._detached_type: Optional[str] = None
        self._detached_dimensions: List[Tuple[str, int]] = []
        if element is None:
            warnings.warn("FMUPort() without element is deprecated: ports are views on the descriptor tree",
                          DeprecationWarning, stacklevel=2)
            self._detached_levels = []

    @property
    def detached(self) -> bool:
        """True for a port built with `FMUPort()`, not attached to a descriptor."""
        return self._detached_levels is not None

    @property
    def fmi_type(self) -> Optional[str]:
        return self._detached_type if self.detached else ModelVariable.fmi_type.fget(self)

    @fmi_type.setter
    def fmi_type(self, fmi_type: str):
        if self.detached:
            self._detached_type = fmi_type
        else:
            ModelVariable.fmi_type.fset(self, fmi_type)

    @property
    def attrs_list(self) -> List[MutableMapping[str, str]]:
        return self._detached_levels if self.detached else ModelVariable.attrs_list.fget(self)

    @property
    def dimensions(self) -> List[Tuple[str, int]]:
        if self.detached:
            return [] if self._detached_dimensions == [("start", 1)] else self._detached_dimensions
        return ModelVariable.dimensions.fget(self)

    @dimensions.setter
    def dimensions(self, attrs: Dict[str, str]):
        """Deprecated: add the attributes of one `<Dimension>` element."""
        warnings.warn("Setting FMUPort.dimensions is deprecated", DeprecationWarning, stacklevel=2)
        if self.detached:
            for key, value in attrs.items():
                self._detached_dimensions.append((key, int(value)))
        else:
            existing = self.element.findall("Dimension")
            position = list(self.element).index(existing[-1]) + 1 if existing else 0
            self.element.insert(position, ET.Element("Dimension", dict(attrs)))

    def push_attrs(self, attrs: Dict[str, str]):
        """Deprecated: add an attribute level to a detached port.

        Args:
            attrs (dict[str, str]): XML attributes of a nested element.

        Raises:
            FMUError: If the port is attached to a descriptor.
        """
        warnings.warn("FMUPort.push_attrs() is deprecated: ports are views on the descriptor tree",
                      DeprecationWarning, stacklevel=2)
        if not self.detached:
            raise FMUError("push_attrs() is only available on a detached FMUPort")
        self._detached_levels.append(attrs)

    def __repr__(self):
        return f"<FMUPort {self.fmi_type} '{self.get('name')}'>"


class FMUError(Exception):
    """Exception raised for FMU-related errors.

    Attributes:
        reason (str): Human-readable description of the error.
    """

    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return self.reason


class ModelStructureCounter:
    """Counts Model-Exchange sizes declared in `<ModelStructure>`.

    Computes the number of continuous states (`nx`) and the number of event
    indicators (`nz`) of an FMU, for both FMI 2.0 and FMI 3.0.

    - **FMI 2.0**: continuous states are the `<Unknown>` entries of the
      `<Derivatives>` section (FMI-2 variables are always scalar); event
      indicators are given by the `numberOfEventIndicators` attribute of
      `<fmiModelDescription>`.
    - **FMI 3.0**: continuous states are the `<ContinuousStateDerivative>`
      entries and event indicators the `<EventIndicator>` entries; array
      variables count for their number of elements.

    When the size of an FMI-3 entry cannot be resolved (unknown value reference
    or dimension depending on a structural parameter), the entry is counted as a
    single scalar and a warning is emitted.

    Attributes:
        fmu_name (str): Name of the FMU, used in log messages.
        number_of_continuous_states (int): Computed `nx`.
        number_of_event_indicators (int): Computed `nz`.
    """

    def __init__(self, fmu_name: str = ""):
        self.fmu_name = fmu_name
        self.number_of_continuous_states = 0
        self.number_of_event_indicators = 0
        self._ports: Dict[str, Tuple[List[Tuple[str, int]], Optional[str]]] = {}

    def register_port(self, vr: Union[str, int], dimensions: List[Tuple[str, int]],
                      start: Optional[str] = None):
        """Record a port, by value reference, for later size resolution.

        Args:
            vr (str | int): Value reference of the port.
            dimensions (list[tuple[str, int]]): Dimensions of the port as parsed
                from the `<Dimension>` elements: `("start", n)` for a fixed size,
                `("valueReference", vr)` when the size is given by a structural
                parameter.
            start (str | None): Start value of the port, used when this port is a
                structural parameter defining the size of an array.
        """
        self._ports[str(vr)] = (list(dimensions), start)

    def fmi_attrs(self, fmi_version: int, attrs: Dict[str, str]):
        """Read `numberOfEventIndicators` (FMI-2 only) from the root element."""
        if fmi_version == 2:
            self.number_of_event_indicators = int(attrs.get("numberOfEventIndicators", 0))

    def model_structure_attrs(self, fmi_version: int, section: str, attrs: Dict[str, str]):
        """Account for one `<ModelStructure>` entry.

        Args:
            fmi_version (int): FMI version (`2` or `3`).
            section (str): Section (FMI-2) or element name (FMI-3).
            attrs (dict[str, str]): Attributes of the entry.
        """
        if fmi_version == 2:
            if section == "Derivatives":
                self.number_of_continuous_states += 1
        else:
            if section == "ContinuousStateDerivative":
                self.number_of_continuous_states += self._size_of(section, attrs)
            elif section == "EventIndicator":
                self.number_of_event_indicators += self._size_of(section, attrs)

    def _size_of(self, section: str, attrs: Dict[str, str]) -> int:
        vr = attrs.get("valueReference", None)
        if vr is None:
            logger.warning(f"'{self.fmu_name}': <{section}> without valueReference. Assuming 1 element.")
            return 1

        try:
            dimensions, _ = self._ports[str(vr)]
        except KeyError:
            logger.warning(f"'{self.fmu_name}': <{section}> refers to unknown variable vr={vr}. "
                           f"Assuming 1 element.")
            return 1

        size = 1
        for kind, value in dimensions:
            if kind == "start":
                size *= value
            else:  # dimension given by a structural parameter: use its start value
                dimension = self._structural_parameter_value(value)
                if dimension is None:
                    logger.warning(f"'{self.fmu_name}': <{section}> vr={vr} has a dimension given by "
                                   f"structuralParameter vr={value} whose value cannot be resolved. "
                                   f"Assuming 1 element.")
                    return 1
                size *= dimension

        return size

    def _structural_parameter_value(self, vr: Union[str, int]) -> Optional[int]:
        try:
            _, start = self._ports[str(vr)]
        except KeyError:
            return None

        if start is None:
            return None

        try:
            return int(start)
        except ValueError:
            return None


class Manipulation:
    """Applies an operation to `modelDescription.xml`, on its ElementTree.

    Loads the descriptor as a
    [ModelDescription][fmu_manipulation_toolbox.model_description.ModelDescription],
    invokes the operation's callbacks in document order, modifies the tree in
    place and writes it back. Everything the operation does not touch is kept
    as is (annotations, aliases, comments, namespaces...).

    When ports are removed, the references to them are updated: FMI 2.0
    `<ModelStructure>` indexes and `derivative` attributes are renumbered,
    entries and dependencies of `<ModelStructure>` that refer to removed ports
    are dropped.

    The operation is refused (`OperationError`, descriptor left unchanged) when
    it would produce an FMU that breaks the FMI standard:

    - every variable removed (empty `<ModelVariables>`, forbidden by the XSD);
    - a removed variable still referenced by a kept one (`derivative`,
      `previous`, `clocks`, `<Dimension valueReference>`);
    - several variables (or FMI 3.0 aliases) with the same name.

    Attributes:
        operation (OperationAbstract): The operation being applied.
        fmu (FMU): The FMU being manipulated.
        model_description (ModelDescription | None): The descriptor tree, once loaded.
        port_translation (list[int | None]): Maps original port indices (0-based)
            to new 1-based indices, or `None` for removed ports.
        port_names_list (list[str]): Original names of all encountered ports.
        port_removed_vr (set[str]): Value references of removed ports.
    """

    def __init__(self, operation, fmu):
        self.operation = operation
        self.fmu = fmu
        self.model_description: Optional[ModelDescription] = None
        self.apply_on = None

        self.current_port_number: int = 0
        self.port_translation: List[Optional[int]] = []
        self.port_names_list: List[str] = []
        self.port_removed_vr: Set[str] = set()

        self.operation.set_fmu(fmu)

    def manipulate(self, descriptor_filename, apply_on=None):
        """Apply the operation and rewrite the descriptor file.

        Args:
            descriptor_filename (str): Path to the `modelDescription.xml` file.
                The file is modified in place.
            apply_on (list[str] | None): If set, only process ports with a
                causality in this list.

        Raises:
            FMUError: If the descriptor cannot be loaded.
            OperationError: If the result would break the FMI standard. The
                descriptor file is then left unchanged.
        """
        self.apply_on = apply_on
        try:
            md = ModelDescription.load(descriptor_filename)
        except ModelDescriptionError as error:
            raise FMUError(f"'{self.fmu.fmu_filename}': {error}") from error
        self.model_description = md
        self.fmu.fmi_version = md.fmi_version
        self.operation.model_description = md

        self.operation.fmi_attrs(md.attributes(md.root))
        self.handle_toplevel_elements(md)
        names_before = self.duplicate_names(md)
        variables = md.variables()
        removed = self.handle_ports(md)
        self.check_result(md, variables, removed, names_before)
        self.remove_children(md.model_variables, removed)
        self.renumber_derivatives(md)
        self.handle_model_structure(md)
        self.operation.closure()
        md.save(descriptor_filename)

    # ---------------------------------------------------------------- Callbacks
    def handle_toplevel_elements(self, md: ModelDescription):
        callbacks = {
            "CoSimulation": self.operation.cosimulation_attrs,
            "ModelExchange": self.operation.modelexchange_attrs,
            "DefaultExperiment": self.operation.experiment_attrs,
        }
        for element in list(md.root):
            callback = callbacks.get(element.tag)
            if callback:
                try:
                    callback(md.attributes(element))
                except ManipulationSkipTag:
                    md.root.remove(element)

    def handle_ports(self, md: ModelDescription) -> List[ET.Element]:
        """Call `port_attrs` on every port. Returns the elements to remove."""
        removed = []
        for element in md.variables():
            port = FMUPort(element, md.fmi_version)
            # name, valueReference and causality are attributes of <ScalarVariable> (FMI-2) or of
            # the variable element (FMI-3): read them directly, before the operation renames the port.
            name = element.get("name")
            vr = element.get("valueReference")
            remove = False
            if not self.apply_on or element.get("causality", "local") in self.apply_on:
                try:
                    remove = bool(self.operation.port_attrs(port))
                except ManipulationSkipTag:
                    remove = True

            self.port_names_list.append(name)
            if remove:
                logger.info(f"Port '{name}' is removed.")
                self.port_translation.append(None)
                self.port_removed_vr.add(vr)
                removed.append(element)
            else:
                self.current_port_number += 1
                self.port_translation.append(self.current_port_number)
        return removed

    # ------------------------------------------------------- Conformity checks
    @staticmethod
    def all_names(md: ModelDescription) -> List[str]:
        """Names of variables and FMI 3.0 aliases, which must all be unique."""
        names = [variable.get("name") for variable in md.variables()]
        if md.fmi_version == 3:
            names += [alias.get("name") for alias in md.model_variables.iter("Alias")]
        return names

    @classmethod
    def duplicate_names(cls, md: ModelDescription) -> Set[str]:
        seen, duplicates = set(), set()
        for name in cls.all_names(md):
            if name in seen:
                duplicates.add(name)
            seen.add(name)
        return duplicates

    def check_result(self, md: ModelDescription, variables: List[ET.Element], removed: List[ET.Element],
                     names_before: Set[str]):
        """Refuse a result that breaks the FMI standard (only for what the operation changed)."""
        if variables and len(removed) == len(variables):
            raise OperationError("The operation would remove every variable: <ModelVariables> cannot be empty.")

        broken = self.broken_references(md, variables, removed)
        if broken:
            raise OperationError("The operation would remove variables that are still referenced: " +
                                 "; ".join(broken[:10]) + (" ..." if len(broken) > 10 else ""))

        removed_ids = {id(element) for element in removed}
        kept_names = [variable.get("name") for variable in variables if id(variable) not in removed_ids]
        if md.fmi_version == 3:
            kept_names += [alias.get("name") for variable in variables if id(variable) not in removed_ids
                           for alias in variable.iter("Alias")]
        seen, duplicates = set(), []
        for name in kept_names:
            if name in seen and name not in names_before and name not in duplicates:
                duplicates.append(name)
            seen.add(name)
        if duplicates:
            raise OperationError("The operation would give the same name to several variables: " +
                                 ", ".join(f"'{name}'" for name in duplicates[:10]) +
                                 (" ..." if len(duplicates) > 10 else ""))

    @staticmethod
    def broken_references(md: ModelDescription, variables: List[ET.Element],
                          removed: List[ET.Element]) -> List[str]:
        """References from kept variables to removed ones, as human-readable strings."""
        if not removed:
            return []
        removed_ids = {id(element) for element in removed}
        kept = [variable for variable in variables if id(variable) not in removed_ids]
        broken = []
        if md.fmi_version == 2:
            removed_indexes = {index for index, variable in enumerate(variables, start=1)
                               if id(variable) in removed_ids}
            for variable in kept:
                port = ModelVariable(variable, 2)
                derivative = port.typed_element.get("derivative") if port.typed_element is not None else None
                if derivative and derivative.isdigit() and int(derivative) in removed_indexes:
                    state = variables[int(derivative) - 1].get("name")
                    broken.append(f"'{state}' is referenced by '{variable.get('name')}' (derivative)")
        else:
            removed_vrs = {variable.get("valueReference"): variable.get("name") for variable in removed}
            for variable in kept:
                references = [("derivative", variable.get("derivative")), ("previous", variable.get("previous"))]
                references += [("clocks", vr) for vr in (variable.get("clocks") or "").split()]
                references += [("Dimension", dimension.get("valueReference"))
                               for dimension in variable.findall("Dimension")]
                for kind, vr in references:
                    if vr in removed_vrs:
                        broken.append(f"'{removed_vrs[vr]}' is referenced by '{variable.get('name')}' ({kind})")
        return list(dict.fromkeys(broken))  # a variable can refer twice to the same one (e.g. two dimensions)

    # -------------------------------------------------------------- References
    def renumber_derivatives(self, md: ModelDescription):
        """FMI 2.0: `derivative` is the 1-based index of the state variable."""
        if md.fmi_version != 2 or self.current_port_number == len(self.port_translation):
            return  # nothing removed
        for variable in md.variables():
            typed = ModelVariable(variable, 2).typed_element
            derivative = typed.get("derivative") if typed is not None else None
            if derivative and derivative.isdigit() and 0 < int(derivative) <= len(self.port_translation):
                typed.set("derivative", str(self.port_translation[int(derivative) - 1]))

    def handle_model_structure(self, md: ModelDescription):
        structure = md.model_structure
        if structure is None:
            return
        if md.fmi_version == 2:
            for section in list(structure):
                if section.tag not in ModelDescription.FMI2_STRUCTURE_SECTIONS:
                    continue
                skipped = []
                for unknown in [child for child in section if child.tag == "Unknown"]:
                    try:
                        self.operation.model_structure_attrs(section.tag, unknown.attrib)
                        self.unknown_attrs(unknown.attrib)
                    except ManipulationSkipTag:
                        skipped.append(unknown)
                self.remove_children(section, skipped)
                if not any(child.tag == "Unknown" for child in section):
                    logger.debug(f"Remove tag <{section.tag}> from modelDescription.xml")
                    structure.remove(section)
        else:
            skipped = []
            for section, entry in md.model_structure_entries():
                try:
                    self.handle_structure(section, entry.attrib)
                except ManipulationSkipTag:
                    skipped.append(entry)
            self.remove_children(structure, skipped)

    @staticmethod
    def remove_children(parent: ET.Element, children: List[ET.Element]):
        """Remove several children at once (`Element.remove` is linear: one call per child is quadratic)."""
        if children:
            removed = {id(child) for child in children}
            parent[:] = [child for child in parent if id(child) not in removed]

    def unknown_attrs(self, attrs):
        """FMI 2.0: renumber an `<Unknown>` entry. Raises `ManipulationSkipTag` if its port is removed."""
        index = int(attrs['index'])
        new_index = self.port_translation[index-1]
        if new_index is None:
            logger.warning(f"Removed port '{self.port_names_list[index-1]}' is involved in dependencies tree.")
            raise ManipulationSkipTag

        attrs['index'] = str(new_index)
        if attrs.get('dependencies', ""):
            kept = [(str(self.port_translation[int(dependency)-1]), kind)
                    for dependency, kind in self.dependency_pairs(attrs)
                    if self.port_translation[int(dependency)-1] is not None]
            self.set_dependencies(attrs, kept)

    def handle_structure(self, section, attrs):
        """FMI 3.0: filter a `<ModelStructure>` entry. Raises `ManipulationSkipTag` if its port is removed."""
        self.operation.model_structure_attrs(section, attrs)

        try:
            vr = attrs['valueReference']
            if vr in self.port_removed_vr:
                logger.warning(f"Removed port vr={vr} is involved in dependencies tree.")
                raise ManipulationSkipTag
        except KeyError:
            return

        if attrs.get('dependencies', ""):
            kept = [(dependency, kind) for dependency, kind in self.dependency_pairs(attrs)
                    if dependency not in self.port_removed_vr]
            self.set_dependencies(attrs, kept)

    @staticmethod
    def dependency_pairs(attrs) -> List[Tuple[str, Optional[str]]]:
        """`(dependency, dependencyKind)` pairs; the kind is `None` without `dependenciesKind`."""
        dependencies = attrs['dependencies'].split(' ')
        if 'dependenciesKind' in attrs:
            return list(zip(dependencies, attrs['dependenciesKind'].split(' ')))
        return [(dependency, None) for dependency in dependencies]

    @staticmethod
    def set_dependencies(attrs, kept: List[Tuple[str, Optional[str]]]):
        """Write back filtered `dependencies` (and `dependenciesKind`), or drop them if empty."""
        if kept:
            attrs['dependencies'] = " ".join(dependency for dependency, _ in kept)
            if 'dependenciesKind' in attrs:
                attrs['dependenciesKind'] = " ".join(kind for _, kind in kept)
        else:
            attrs.pop('dependencies')
            attrs.pop('dependenciesKind', None)


class ManipulationSkipTag(Exception):
    """Internal exception used to skip XML content until a matching closing tag.

    Raised during SAX parsing to signal that the current element and all
    its children should be omitted from the output.
    """


class OperationAbstract:
    """Base class for all FMU manipulation operations.

    Subclass this to implement custom operations on FMU descriptors. The
    methods act as callbacks invoked, in document order, while
    `modelDescription.xml` is walked: `fmi_attrs`, then `cosimulation_attrs`,
    `modelexchange_attrs` and `experiment_attrs`, then `port_attrs` for each
    variable, then `model_structure_attrs`, and finally `closure`.

    The `attrs` dictionaries given to the callbacks are those of the descriptor
    tree: changing them changes the descriptor.

    Attributes:
        fmu (FMU | None): The FMU being processed, set via `set_fmu`.
        model_description (ModelDescription | None): The whole descriptor tree,
            set before the first callback. Use it for changes that the
            callbacks cannot express (e.g. removing an element).
    """

    fmu: FMU = None
    model_description: Optional[ModelDescription] = None

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

    def modelexchange_attrs(self, attrs):
        """Called when the `<ModelExchange>` element is encountered.

        Args:
            attrs (dict[str, str]): XML attributes of the model-exchange element.
        """
        pass

    def experiment_attrs(self, attrs):
        """Called when the `<DefaultExperiment>` element is encountered.

        Args:
            attrs (dict[str, str]): XML attributes of the default experiment.
        """
        pass

    def model_structure_attrs(self, section: str, attrs: Dict[str, str]):
        """Called for each entry of the `<ModelStructure>` section.

        For FMI 2.0, `section` is the name of the enclosing sub-section
        (`"Outputs"`, `"Derivatives"`, `"InitialUnknowns"`) and `attrs` holds the
        attributes of an `<Unknown>` element (1-based `index` of the variable).

        For FMI 3.0, `section` is the name of the element itself
        (`"Output"`, `"ContinuousStateDerivative"`, `"InitialUnknown"`,
        `"EventIndicator"`, `"ClockedState"`) and `attrs` holds its attributes
        (including `valueReference`).

        Args:
            section (str): Name of the model-structure section or element.
            attrs (dict[str, str]): XML attributes of the entry.
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
        except IndexError:
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
        structure (ModelStructureCounter): Model-Exchange sizes (nx/nz), only
            reported when the FMU declares a `<ModelExchange>` section.
    """

    def __init__(self):
        self.nb_port_per_causality = {}
        self.fmi_version = 2
        self.has_model_exchange = False
        self.structure = ModelStructureCounter()

    def __repr__(self):
        return f"FMU Summary"

    def fmi_attrs(self, attrs):
        logger.info(f"| fmu filename = {self.fmu.fmu_filename}")
        self.structure.fmu_name = os.path.basename(self.fmu.fmu_filename)
        self.fmi_version = int(float(attrs.get("fmiVersion", "2.0")))
        self.structure.fmi_attrs(self.fmi_version, attrs)
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

    def modelexchange_attrs(self, attrs):
        self.has_model_exchange = True
        logger.info("| Model Exchange capabilities: ")
        for (k, v) in attrs.items():
            logger.info(f"|  - {k} = {v}")
        logger.info(f"|")

    def model_structure_attrs(self, section: str, attrs: Dict[str, str]):
        self.structure.model_structure_attrs(self.fmi_version, section, attrs)

    def experiment_attrs(self, attrs):
        logger.info("| Default Experiment values: ")
        for (k, v) in attrs.items():
            logger.info(f"|  - {k} = {v}")
        logger.info(f"|")

    def port_attrs(self, fmu_port) -> int:
        causality = fmu_port.get("causality", "local")

        try:
            self.structure.register_port(fmu_port["valueReference"], fmu_port.dimensions,
                                         fmu_port.get("start", None))
        except KeyError:
            pass  # port without valueReference: nothing to register.

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

        if self.has_model_exchange:
            logger.info("|")
            logger.info("| Model Exchange sizes")
            logger.info(f"|  continuous states : {self.structure.number_of_continuous_states}")
            logger.info(f"|  event indicators : {self.structure.number_of_event_indicators}")

        terminals = Terminals(self.fmu.tmp_directory)
        if terminals:
            logger.info("|")
            logger.info("| Terminals:")
            for terminal in terminals:
                logger.info(f"|  - {terminal}")

        logger.info("|")
        logger.info("| [End of report]")


class OperationRemoveSources(OperationAbstract):
    """Remove the `sources/` directory from the FMU.

    Strips the embedded C/C++ source files that some FMUs include for
    recompilation on the target platform, and the `<SourceFiles>` elements
    (FMI 2.0) that list them. For FMI 3.0, the list of sources is
    `sources/buildDescription.xml`, removed with the directory.
    """

    def __repr__(self):
        return f"Remove sources"

    def closure(self):
        try:
            shutil.rmtree(os.path.join(self.fmu.tmp_directory, "sources"))
        except FileNotFoundError:
            logger.info("This FMU does not embed sources.")

        for interface in self.model_description.interfaces.values():
            for source_files in interface.findall("SourceFiles"):
                interface.remove(source_files)


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
            fmu_port['name'] = name[name.index(self.separator)+len(self.separator):]
        except ValueError:
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
