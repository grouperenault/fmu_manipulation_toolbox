import importlib.util
import inspect
import os
import xmlschema
from xmlschema.validators.exceptions import XMLSchemaValidationError
from .fmu_operations import OperationAbstract


class OperationGenericCheck(OperationAbstract):
    SUPPORTED_FMI_VERSIONS = ('2.0', '3.0')

    def __init__(self):
        self.compliant_with_version = None

    def __repr__(self):
        return f"FMU Generic Conformity Checks"

    def fmi_attrs(self, attrs):
        if attrs['fmiVersion'] not in self.SUPPORTED_FMI_VERSIONS:
            print(f"ERROR: Expected FMI {','.join(self.SUPPORTED_FMI_VERSIONS)} versions.")
            return

        fmi_name = f"fmi{attrs['fmiVersion'][0]}"

        xsd_filename = os.path.join(os.path.dirname(__file__), "resources", "fmi-" + attrs['fmiVersion'],
                                    f"{fmi_name}ModelDescription.xsd")
        try:
            xmlschema.validate(self.fmu.descriptor_filename, schema=xsd_filename)
        except XMLSchemaValidationError as error:
            print(error.reason, error.msg)
        else:
            self.compliant_with_version = attrs['fmiVersion']

    def closure(self):
        if self.compliant_with_version:
            print(f"INFO: This FMU seems to be compliant with FMI-{self.compliant_with_version}.")
        else:
            print(f"ERROR: This FMU does not validate with FMI standard.")


checker_list = [OperationGenericCheck]


def add_from_file(checker_filename: str):
    spec = importlib.util.spec_from_file_location(checker_filename, checker_filename)
    if not spec:
        print(f"ERROR: Cannot load {checker_filename}. Is this a python file?")
        return
    try:
        checker_module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(checker_module)
        except (ModuleNotFoundError, SyntaxError) as error:
            print(f"ERROR: Cannot load {checker_filename}: {error})")
            return

        for checker_name, checker_class in inspect.getmembers(checker_module, inspect.isclass):
            if OperationAbstract in checker_class.__bases__:
                checker_list.append(checker_class)
                print(f"Adding checker: {checker_filename}|{checker_name}")

    except AttributeError:
        print(f"ERROR: {checker_filename} should implement class 'OperationCheck'")
