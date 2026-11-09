# FMU Checker

FMU Manipulation Toolbox includes built-in checkers (FMI 2.0 and 3.0). You can also write your own
custom checkers.

- `OperationGenericCheck` validates `modelDescription.xml` against the official FMI XSD schema and reports
  every violation.
- `OperationSemanticCheck` checks the rules of the standard that the schema cannot express (FMI 2.0.5
  §2.2.7–2.2.8, FMI 3.0.2 §2.4.7–2.4.8). Each message cites the section of the standard:
    - variable names (and FMI 3.0 aliases) are unique; FMI 3.0 value references are unique;
    - allowed combinations of `causality` and `variability`; only `Real` / `Float32` / `Float64` variables
      can be `continuous`;
    - allowed values of `initial`, and presence or absence of a `start` value;
    - `derivative` attributes and `<ModelStructure>` entries refer to existing variables;
    - `<Outputs>` / `<Output>` lists exactly the outputs; state derivatives have a `derivative` attribute.
- `OperationLsBusCheck` checks the rules of [FMI-LS-BUS](../fmucontainer/ls-bus.md), for an FMU that declares it.
- `OperationLsXcpCheck` checks the rules of [FMI-LS-XCP](../fmucontainer/ls-xcp.md) 1.0.0, for an FMU that declares
  it (manifest `extra/org.fmi-standard.fmi-ls-xcp/fmi-ls-manifest.xml`):
    - the manifest is valid against the XSD of FMI-LS-XCP;
    - the A2L file of each interface exists, in the directory of the manifest (source code FMU) or in at least one
      of its platform directories, and does not use `/include`; an A2L file for a platform without binaries is a
      warning;
    - each interface has `containsXCPService` or `supportsDirectMemoryAccess`;
    - each `Variable` refers to an existing scalar variable of the type of its role (`Boolean`, `UInt16` in FMI 3.0
      or `Integer` in FMI 2.0, `String`), declared as a fixed `structuralParameter` (FMI 3.0), a fixed `parameter`,
      a `constant` output or a fixed or tunable `calculatedParameter`; a variable is used once, a role once per
      interface.

With `fmutool -check`, any error logged by a checker makes the command exit with status `7`.

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
from fmu_manipulation_toolbox.operations import OperationAbstract, ModelVariable

logger = logging.getLogger("fmu_manipulation_toolbox")


class CheckNamingConvention(OperationAbstract):
    """Check that all port names use snake_case."""

    def __repr__(self):
        return "Naming convention checker"

    def port_attrs(self, fmu_port: ModelVariable) -> int:
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

A checker that cannot be imported, from a file or through an entry point, is reported as an error and skipped:
the other checkers still run. This is the case of a checker written for version 1.x that still imports
`FMUPort`, removed in 2.0: replace it by `ModelVariable` (see
[Writing Custom Operations](python-api.md#writing-custom-operations)).
