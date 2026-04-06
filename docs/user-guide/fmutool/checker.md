# FMU Checker

FMU Manipulation Toolbox includes a built-in checker that validates FMUs against the official
FMI XSD schema (FMI 2.0 and 3.0). You can also write your own custom checkers.

## Running the Checker

=== "CLI"

    ```bash
    fmutool -input my_model.fmu -check
    ```

=== "GUI"

    In **fmutool-gui**, click the **Check FMU** button after loading an FMU.

=== "Python API"

    ```python
    from fmu_manipulation_toolbox.operations import FMU
    from fmu_manipulation_toolbox.checker import OperationGenericCheck

    fmu = FMU("my_model.fmu")
    check = OperationGenericCheck()
    fmu.apply_operation(check)

    if check.compliant_with_version:
        print(f"FMU is compliant with FMI {check.compliant_with_version}")
    else:
        print("FMU is NOT compliant")
    ```

## Writing a Custom Checker

A checker is a class derived from `OperationAbstract`. Override the callback methods
to inspect FMU attributes and ports:

```python
import logging
from fmu_manipulation_toolbox.operations import OperationAbstract, FMUPort

logger = logging.getLogger("fmu_manipulation_toolbox")


class CheckNamingConvention(OperationAbstract):
    """Check that all port names use snake_case."""

    def __repr__(self):
        return "Naming convention checker"

    def port_attrs(self, fmu_port: FMUPort) -> int:
        name = fmu_port["name"]
        if name != name.lower():
            logger.warning(f"Port '{name}' is not snake_case")
        return 0
```

Save this file (e.g., `my_checkers.py`) anywhere on your system.

## Registering Custom Checkers

### From a Python file

Use `add_from_file` to load checkers at runtime before running `fmutool`:

```python
from fmu_manipulation_toolbox.checker import add_from_file

add_from_file("path/to/my_checkers.py")
```

All classes that directly subclass `OperationAbstract` in the file will be
automatically registered and executed during checks.

### Via entry points

You can also register checkers as Python package entry points using the
`fmu_manipulation_toolbox.checkers` group in your `setup.py` or `pyproject.toml`:

```toml
[project.entry-points."fmu_manipulation_toolbox.checkers"]
my_checker = "my_package:get_checker_class"
```
