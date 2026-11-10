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
- `OperationLsRefCheck` checks the reference material of FMI-LS-REF, for an FMU that declares it (manifest
  `extra/org.fmi-standard.fmi-ls-ref/fmi-ls-manifest.xml`), and **replays its experiments** to compare the results
  with the references: see [Validation of the results (FMI-LS-REF)](#validation-of-the-results-fmi-ls-ref).

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

## Validation of the results (FMI-LS-REF)

[FMI-LS-REF](https://modelica.github.io/fmi-ls-ref/main) (1.0.0-alpha.1, a draft) lists the files related to an FMU
in its manifest. The experiment files (role `experiment`, type `application/x-ma-hs-experiments`) follow the draft
[MA-HS-Experiments](https://modelica.github.io/ma-hs-experiments/main/): each `TransientExperiment` gives its start
and stop times, its step size, and its parameters (SSV file), stimuli and references (CSV files). The
[Reference FMUs](https://github.com/modelica/Reference-FMUs) give instead the output of their default experiment
(role `result`, a CSV file).

### Static checks

- The manifest and the experiment files are valid against their XSD (shipped with the toolbox). A missing or
  different `fmi-ls-description` is a warning (the Reference FMUs have none).
- A related file that is not in the FMU (missing file, absolute URI, relative URI leaving the FMU) is a warning. The
  relative URIs may hold `..` while they stay inside the FMU (e.g. `../../resources/stimuli.csv`).
- Experiments: `startTime` before `stopTime`, a positive `stepSize`. The files of an experiment that is replayed must
  be in the FMU (error); the stimuli and references of a type other than `text/csv`, the parameters of a type other
  than `application/x-ssp-parameter-set`, are not supported (warning, the experiment is not replayed).
- The columns of the stimuli are `input` variables, those of the references `output` variables; the parameters of the
  SSV file are `parameter` or `structuralParameter` variables, or `input` variables with a start value. A `result`
  file of the Reference FMUs may have columns that are not outputs of the FMU, or binaries: they are ignored
  (warning).

### Replay and comparison

The experiments of sub-role `smoke-test` (the default) and `validation`, and the `result` files, are replayed on the
host platform with the runtime of the FMU Container: the FMU is embedded in a temporary FMI 3.0 container, then
simulated. Each experiment is simulated in a **dedicated process**: a crash of the FMU (e.g. a segmentation fault)
or a simulation that does not end within **60 s** (`-ref-timeout`) fails this experiment only (error, with the signal or the exit
code of the process), the check and the other experiments go on.

- **Times**: those of the experiment, else those of the `DefaultExperiment` of the FMU, else the first and last
  instants of the references. Without `stepSize`, the step size is deduced from the FMU as `fmucontainer` does. The
  `tolerance` of the experiment is not used.
- **Stimuli** are interpolated at each communication point: linearly for the continuous real inputs, previous value
  for the others. The outputs are recorded at each communication point, after the stimuli of this instant.
- **Comparison** at the instants of the references, the simulation being interpolated as the stimuli: a number
  (booleans as `0`/`1`) matches when `|simulated - reference| <= atol + rtol * |reference|`, with `rtol = 1e-3` and
  `atol = 1e-6` by default (`-ref-rtol`, `-ref-atol`, or **Selected Check** in `fmutool-gui`); a string must be equal. At an event of the references (two rows with the same time), the value
  after the event is compared. Each output that differs is an error, with the first instant of the difference.
- An experiment without references is simulated only. A simulation that fails, crashes or exceeds its time limit
  is an error.
- Not replayed (warning): the experiments of sub-role `uncertainty-analysis`, when the runtime of the container or the
  binary of the FMU is not available for the host platform, and the experiments with a stimulus on a `Boolean` input
  of an FMI 2.0 FMU (the FMI 3.0 container cannot expose it).

The CSV files follow the convention of the FMI cross-check: comma separator, a first column `time`, one column per
variable named after it:

```text
time,Float64_continuous_input,Int32_input,Boolean_input
0,0,0,false
1,10,5,true
2,0,7,false
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
