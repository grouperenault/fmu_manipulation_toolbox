import importlib.util
from importlib.metadata import entry_points
import inspect
import logging
import os
import xmlschema
from typing import *

from .model_description import ModelDescription, ModelVariable
from .operations import OperationAbstract

logger = logging.getLogger("fmu_manipulation_toolbox")


class OperationGenericCheck(OperationAbstract):
    """Check FMU compliance against the FMI standard XSD schema.

    Validates the `modelDescription.xml` file of an FMU against the official
    XSD schema for FMI 2.0 or 3.0. Reports validation errors via the logger
    and indicates whether the FMU is compliant.

    This checker is always included by default in the checkers list.

    Attributes:
        SUPPORTED_FMI_VERSIONS (tuple[str, ...]): FMI versions supported
            by this checker (`"2.0"`, `"3.0"`).
        compliant_with_version (str | None): The FMI version the FMU is
            compliant with after validation, or `None` if validation failed.
    """

    read_only = True

    SUPPORTED_FMI_VERSIONS = ('2.0', '3.0')

    def __init__(self):
        self.compliant_with_version = None

    def __repr__(self):
        return f"FMU Generic Conformity Checks"

    def fmi_attrs(self, attrs):
        """Validate the FMU descriptor against the appropriate FMI XSD schema.

        Called during FMU parsing when the root `fmiModelDescription` element
        is encountered.

        Args:
            attrs (dict[str, str]): XML attributes of the `fmiModelDescription`
                element. Must contain `fmiVersion`.
        """
        if attrs['fmiVersion'] not in self.SUPPORTED_FMI_VERSIONS:
            logger.error(f"Expected FMI {','.join(self.SUPPORTED_FMI_VERSIONS)} versions.")
            return

        fmi_name = f"fmi{attrs['fmiVersion'][0]}"
        xsd_filename = os.path.join(os.path.dirname(__file__), "resources", "fmi-" + attrs['fmiVersion'],
                                    f"{fmi_name}ModelDescription.xsd")
        xsd = xmlschema.XMLSchema(xsd_filename)
        # Report every violation, not only the first one as `validate()` does.
        errors = list(xsd.iter_errors(self.fmu.descriptor_filename))
        for error in errors:
            # NOTE: `logger.error(reason, msg)` would treat `msg` as a
            # printf-style argument for `reason`, which raises at formatting
            # time and loses the error entirely.
            logger.error(f"{error.reason} (at {error.path})" if error.path else f"{error.reason}")
        if not errors:
            self.compliant_with_version = attrs['fmiVersion']

    def closure(self):
        """Log the final compliance result.

        Called after the FMU descriptor has been fully parsed. Logs whether
        the FMU is compliant with the detected FMI version.
        """
        if self.compliant_with_version:
            logger.info(f"This FMU seems to be compliant with FMI-{self.compliant_with_version}.")
        else:
            logger.error(f"This FMU does not validate with FMI standard.")


class OperationSemanticCheck(OperationAbstract):
    """Check the rules of the FMI standard that the XSD schema cannot express.

    Rules are those of FMI 2.0.5 (§2.2.7, §2.2.8) and FMI 3.0.2 (§2.4,
    §2.4.7, §2.4.8). Each violation is logged as an error and kept in
    `errors`:

    - variable names (and FMI 3.0 alias names) are unique;
    - FMI 3.0 value references are unique;
    - allowed combinations of `causality` and `variability`; only `Real`
      (FMI 2.0) or `Float32`/`Float64` (FMI 3.0) variables are continuous;
    - allowed values of `initial` for each combination;
    - presence or absence of a `start` value;
    - references between variables: `derivative`, `<ModelStructure>` entries
      and their `dependencies`;
    - `<Outputs>` (FMI 2.0) / `<Output>` (FMI 3.0) lists exactly the variables
      with `causality="output"`; state derivatives have a `derivative`
      attribute.

    Attributes:
        errors (list[str]): Violations found.
    """

    read_only = True

    # Allowed variabilities per causality (FMI 2.0 §2.2.7 and FMI 3.0 §2.4.7.4 tables).
    VARIABILITIES = {
        "structuralParameter": ("fixed", "tunable"),
        "parameter": ("fixed", "tunable"),
        "calculatedParameter": ("fixed", "tunable"),
        "input": ("discrete", "continuous"),
        "output": ("constant", "discrete", "continuous"),
        "local": ("constant", "fixed", "tunable", "discrete", "continuous"),
        "independent": ("continuous",),
    }
    # Allowed values of `initial`, default first, per (causality, variability); missing: `initial` not allowed.
    INITIAL_2 = {
        ("parameter", "fixed"): ("exact",), ("parameter", "tunable"): ("exact",),
        ("calculatedParameter", "fixed"): ("calculated", "approx"),
        ("calculatedParameter", "tunable"): ("calculated", "approx"),
        ("output", "constant"): ("exact",), ("local", "constant"): ("exact",),
        ("local", "fixed"): ("calculated", "approx"), ("local", "tunable"): ("calculated", "approx"),
        ("output", "discrete"): ("calculated", "exact", "approx"),
        ("output", "continuous"): ("calculated", "exact", "approx"),
        ("local", "discrete"): ("calculated", "exact", "approx"),
        ("local", "continuous"): ("calculated", "exact", "approx"),
    }
    INITIAL_3 = {
        **INITIAL_2,
        ("structuralParameter", "fixed"): ("exact",), ("structuralParameter", "tunable"): ("exact",),
        ("input", "discrete"): ("exact",), ("input", "continuous"): ("exact",),
    }
    CONTINUOUS_TYPES = {2: ("Real",), 3: ("Float32", "Float64")}
    PARAMETERS = ("parameter", "structuralParameter", "calculatedParameter")

    def __init__(self):
        self.errors: List[str] = []

    def __repr__(self):
        return "FMU Semantic Checks"

    def error(self, message: str):
        self.errors.append(message)
        logger.error(message)

    def closure(self):
        md = self.model_description
        section = "FMI-2 §2.2.7" if md.fmi_version == 2 else "FMI-3 §2.4.7"
        ports = list(md.iter_ports())

        self.check_unique_names(md, ports)
        if md.fmi_version == 3:
            self.check_unique_value_references(ports)
        for port in ports:
            if port.fmi_type is None:
                continue
            causality, variability = self.causality_variability(md.fmi_version, port)
            self.check_variability(md.fmi_version, port, causality, variability, section)
            if port.fmi_type != "Clock":  # Clocks have neither `start` nor `initial`
                self.check_initial_and_start(md.fmi_version, port, causality, variability, section)
        self.check_model_structure(md, ports)

        if self.errors:
            logger.error(f"{len(self.errors)} semantic error(s) against the FMI-{md.fmi_version} standard.")
        else:
            logger.info(f"No semantic error against the FMI-{md.fmi_version} standard.")

    # --------------------------------------------------------------- Variables
    def causality_variability(self, fmi_version: int, port: ModelVariable) -> Tuple[str, str]:
        causality = port.get("causality", "local")
        variability = port.get("variability", None)
        if variability is None:  # defaults: FMI-2 §2.2.7, FMI-3 §2.4.7.4
            if fmi_version == 2:
                variability = "continuous"
            elif causality in self.PARAMETERS:
                variability = "fixed"
            else:
                variability = "continuous" if port.fmi_type in self.CONTINUOUS_TYPES[3] else "discrete"
        return causality, variability

    def check_unique_names(self, md: ModelDescription, ports: List[ModelVariable]):
        names = [port.get("name") for port in ports]
        if md.fmi_version == 3:
            names += [alias.get("name") for alias in md.model_variables.iter("Alias")]
        seen = set()
        for name in names:
            if name in seen:
                self.error(f"Name '{name}' is used by several variables"
                           f"{' or aliases' if md.fmi_version == 3 else ''} "
                           f"({'FMI-2 §2.2.7' if md.fmi_version == 2 else 'FMI-3 §2.4'}).")
            seen.add(name)

    def check_unique_value_references(self, ports: List[ModelVariable]):
        seen: Dict[str, str] = {}
        for port in ports:
            vr = port.get("valueReference")
            if vr in seen:
                self.error(f"valueReference {vr} is used by '{seen[vr]}' and '{port.get('name')}' (FMI-3 §2.4.7.4).")
            else:
                seen[vr] = port.get("name")

    def check_variability(self, fmi_version: int, port: ModelVariable, causality: str, variability: str,
                          section: str):
        name = port.get("name")
        allowed = self.VARIABILITIES.get(causality)
        if allowed is None or (causality == "structuralParameter" and fmi_version == 2):
            self.error(f"Variable '{name}': unknown causality '{causality}' ({section}).")
        elif variability not in allowed:
            self.error(f"Variable '{name}': causality='{causality}' and variability='{variability}' "
                       f"cannot be combined ({section}).")
        if variability == "continuous" and port.fmi_type not in self.CONTINUOUS_TYPES[fmi_version]:
            self.error(f"Variable '{name}': a {port.fmi_type} variable cannot be continuous ({section}"
                       f"{'; the default variability is continuous' if 'variability' not in port else ''}).")

    def check_initial_and_start(self, fmi_version: int, port: ModelVariable, causality: str, variability: str,
                                section: str):
        name = port.get("name")
        table = self.INITIAL_2 if fmi_version == 2 else self.INITIAL_3
        allowed = table.get((causality, variability), ())
        initial = port.get("initial", None)
        if initial is not None and initial not in allowed:
            if allowed:
                self.error(f"Variable '{name}': initial='{initial}' is not allowed with causality='{causality}' "
                           f"and variability='{variability}' (allowed: {', '.join(allowed)}) ({section}).")
            else:
                self.error(f"Variable '{name}': initial must not be set with causality='{causality}' "
                           f"and variability='{variability}' ({section}).")
        if initial is None and allowed:
            initial = allowed[0]

        has_start = "start" in port
        start_required = initial in ("exact", "approx") or causality == "input"
        if fmi_version == 3:
            start_required = start_required or causality in ("parameter", "structuralParameter") \
                             or variability == "constant"
        if initial == "calculated" or causality == "independent":
            if has_start:
                self.error(f"Variable '{name}': a start value is not allowed "
                           f"({'causality=independent' if causality == 'independent' else 'initial=calculated'}) "
                           f"({section}).")
        elif start_required and not has_start:
            self.error(f"Variable '{name}': a start value is required ({section}).")

    # --------------------------------------------------------- Model structure
    def check_model_structure(self, md: ModelDescription, ports: List[ModelVariable]):
        names = [port.get("name") for port in ports]
        outputs = [index for index, port in enumerate(ports) if port.get("causality", "local") == "output"]
        derivatives = [index for index, port in enumerate(ports) if "derivative" in port]
        listed_outputs, listed_derivatives = [], []

        if md.fmi_version == 2:
            section = "FMI-2 §2.2.8"

            def resolve(reference: str) -> Optional[int]:
                index = int(reference) - 1 if reference.isdigit() else -1
                return index if 0 <= index < len(ports) else None

            for index in derivatives:
                if resolve(ports[index].get("derivative")) is None:
                    self.error(f"Variable '{names[index]}': derivative='{ports[index].get('derivative')}' "
                               f"is not a variable index (FMI-2 §2.2.7).")
            for kind, entry in md.model_structure_entries():
                index = resolve(entry.get("index", ""))
                if index is None:
                    self.error(f"<{kind}><Unknown index='{entry.get('index')}'> is not a variable index ({section}).")
                    continue
                self.check_dependencies(entry, resolve, f"<{kind}> entry of '{names[index]}'", section)
                if kind == "Outputs":
                    listed_outputs.append(index)
                elif kind == "Derivatives":
                    listed_derivatives.append(index)
            output_section, derivative_section = "<Outputs>", "<Derivatives>"
        else:
            section = "FMI-3 §2.4.8"
            by_vr = {port.get("valueReference"): index for index, port in enumerate(ports)}

            def resolve(reference: str) -> Optional[int]:
                return by_vr.get(reference)

            for index in derivatives:
                if resolve(ports[index].get("derivative")) is None:
                    self.error(f"Variable '{names[index]}': derivative='{ports[index].get('derivative')}' "
                               f"is not a valueReference (FMI-3 §2.4.7.5).")
            for kind, entry in md.model_structure_entries():
                index = resolve(entry.get("valueReference"))
                if index is None:
                    self.error(f"<{kind} valueReference='{entry.get('valueReference')}'> "
                               f"is not a valueReference ({section}).")
                    continue
                self.check_dependencies(entry, resolve, f"<{kind}> entry of '{names[index]}'", section)
                if kind == "Output":
                    listed_outputs.append(index)
                elif kind == "ContinuousStateDerivative":
                    listed_derivatives.append(index)
            output_section, derivative_section = "<Output>", "<ContinuousStateDerivative>"

        for index in sorted(set(outputs) - set(listed_outputs)):
            self.error(f"Output '{names[index]}' is not listed in {output_section} ({section}).")
        for index in sorted(set(listed_outputs) - set(outputs)):
            self.error(f"{output_section} lists '{names[index]}', which is not an output ({section}).")
        for index in sorted(set(listed_derivatives) - set(derivatives)):
            self.error(f"{derivative_section} lists '{names[index]}', which has no derivative attribute "
                       f"({section}).")

    def check_dependencies(self, entry, resolve, what: str, section: str):
        dependencies = entry.get("dependencies", "").split()
        for dependency in dependencies:
            if resolve(dependency) is None:
                self.error(f"{what}: dependency '{dependency}' does not refer to a variable ({section}).")
        kinds = entry.get("dependenciesKind")
        if kinds is not None and len(kinds.split()) != len(dependencies):
            self.error(f"{what}: dependencies and dependenciesKind have different lengths ({section}).")


_checkers_list: List[type[OperationAbstract]] = [OperationGenericCheck, OperationSemanticCheck]


def get_checkers() -> List[type[OperationAbstract]]:
    """Collect all registered FMU checkers.

    Returns the built-in checkers combined with any additional checkers
    discovered via the `fmu_manipulation_toolbox.checkers`
    [entry point](https://packaging.python.org/en/latest/specifications/entry-points/)
    group.

    Returns:
        list[type[OperationAbstract]]: List of checker classes, each being a
            subclass of
            [OperationAbstract][fmu_manipulation_toolbox.operations.OperationAbstract].
    """
    checkers: List[type[OperationAbstract]] = list(_checkers_list)  # a copy: repeated calls must not pile up
    discovered_checkers = entry_points(group='fmu_manipulation_toolbox.checkers')

    for checker in discovered_checkers:
        entry = checker.load()
        checker_class = entry()
        if issubclass(checker_class, OperationAbstract):
            logger.debug(f"Addon checker: {checker.name}")
            checkers.append(checker_class)

    return checkers


def add_from_file(checker_filename: str):
    """Dynamically load checker classes from a Python file.

    Imports the given Python file and registers any class that directly
    subclasses
    [OperationAbstract][fmu_manipulation_toolbox.operations.OperationAbstract]
    into the global checkers list.

    Args:
        checker_filename (str): Path to the Python file containing checker
            class(es).
    """
    spec = importlib.util.spec_from_file_location(checker_filename, checker_filename)
    if not spec:
        logger.error(f"Cannot load '{checker_filename}'. Is this a python file?")
        return
    try:
        checker_module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(checker_module)
        except (ModuleNotFoundError, SyntaxError) as error:
            logger.error(f"Cannot load '{checker_filename}': {error})")
            return

        for checker_name, checker_class in inspect.getmembers(checker_module, inspect.isclass):
            if OperationAbstract in checker_class.__bases__:
                _checkers_list.append(checker_class)
                logger.info(f"Adding checker: {checker_filename}|{checker_name}")

    except AttributeError:
        logger.error(f"'{checker_filename}' should implement class 'OperationCheck'")
