import importlib.util
import inspect
import logging
import os
import sys
import xmlschema
from typing import *
from xmlschema.validators.exceptions import XMLSchemaValidationError

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
        try:
            xsd.validate(self.fmu.descriptor_filename)
        except XMLSchemaValidationError as error:
            logger.error(error.reason, error.msg)
        else:
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


_checkers_list: List[type[OperationAbstract]] = [OperationGenericCheck]


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
    if sys.version_info < (3, 10):
        from importlib_metadata import entry_points
    else:
        from importlib.metadata import entry_points
    checkers: List[type[OperationAbstract]] = _checkers_list
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
