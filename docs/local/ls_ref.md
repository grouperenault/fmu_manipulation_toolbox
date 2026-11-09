# FMI-LS-REF support

## Context

`fmutool -check` only performs static checks (XSD, semantic rules, LS-BUS, LS-XCP). The goal is to validate the
numerical results of an FMU when it carries the reference material of FMI-LS-REF: replay its experiments and compare
the outputs with the references.

State of the standards (checked 2026-11-09):

- [FMI-LS-REF](https://modelica.github.io/fmi-ls-ref/main), `fmi-ls-version="1.0.0-alpha.1"` (draft):
  - manifest `extra/org.fmi-standard.fmi-ls-ref/fmi-ls-manifest.xml`, root `fmiReferences`, attributes
    `fmi-ls:fmi-ls-name="org.fmi-standard.fmi-ls-ref"`, `fmi-ls:fmi-ls-version`, `fmi-ls:fmi-ls-description` (namespace
    `http://fmi-standard.org/fmi-ls-manifest`); schema `fmi3LayeredStandardReferenceManifest.xsd` (2-Clause BSD);
  - one `<Related type="<MIME>" source="<URI>" role="<role>" description="...">` per related file, with optional
    `<Label name description>` and `<Annotations>`;
  - role `experiment[/<sub-role>]`, sub-roles `smoke-test` (default when absent), `validation`,
    `uncertainty-analysis`; experiment files of type `application/x-ma-hs-experiments`;
  - a related file may be missing from the archive; absolute URIs are left to the importer; relative URIs (inside the
    FMU) are always supported; "the set of experiments defined in the file can be performed on the FMU just using the
    resources present in the FMU".
- [MA-HS-Experiments](https://modelica.github.io/ma-hs-experiments/main/) (draft, no version), schema
  `maHarmonizedSpecificationExperiments.xsd` (2-Clause BSD):
  - root `<Experiments name description>` (namespace `http://modelica.org/HSExperiments1/HSExperiments`), one or more
    `<TransientExperiment name description startTime stopTime stepSize tolerance>` (all times optional);
  - children `<Parameters source type>` (default `application/x-ssp-parameter-set`, SSV), `<Stimuli source type>` and
    `<References source type>` (default `text/csv`; `application/hdf5` named in the example), sources relative to the
    experiments file;
  - the CSV format is not specified (the schema says "as specified in XXX"), nor the mapping of the columns to the
    variables, the interpolation of the stimuli, or any comparison criterion.
- `modelica/fmi-ls-ref` and `modelica/ma-hs-experiments` only hold the specification, the XSD and one example XML
  file each. But the Reference-FMUs (v0.0.41, `tests/data/compile`) implement LS-REF (found at step 3): their manifest
  has one `<Related type="text/csv" source="<model>_out.csv" role="result" description="Output of the default
  experiment"/>`, no experiment file, and no `fmi-ls-description` (required by the XSD of alpha.1). The result of the
  FMI-2.0 Feedthrough has the columns of the FMI-3.0 one (variables it does not have), and columns of binaries (hex),
  strings, booleans (`false`).

Existing material: `fmu_manipulation_toolbox/ls.py` (`LayeredStandard`: LS-BUS, LS-XCP), `checker.py` (checkers of
`-check`, `get_checkers()`), `ssp.py` (reading of SSV parameter sets), the container builder
(`container/builder.py`: inputs, outputs, start values, step size, Model-Exchange FMUs through the solver of the
runtime), the source FMUs of the tests (`tests/data/compile/{2.0,3.0}/{BouncingBall,Feedthrough}.fmu`, Reference-FMUs
v0.0.41, with `REF-BouncingBall.csv`) and the compiler of the toolbox (`compiler.py`, `fmutool -compile-sources`).
There is no FMI driver in Python and no simulation engine besides the container runtime.

## Decisions (2026-11-09)

| # | Question | Decision |
|---|----------|----------|
| 1 | Simulation engine | The **container runtime**: no new dependency |
| 2 | Driving the runtime | A **Python driver (ctypes)**: the checker builds a temporary container around the FMU with the existing builder, then calls the FMI API of the container library (stimuli before each step, outputs after it). No change of `container.txt`, no new binary |
| 3 | Comparison criterion | Simulated output interpolated (linearly) at the instants of the reference; `abs(sim - ref) <= atol + rtol * abs(ref)` |
| 4 | Tolerances | **Fixed defaults**: `rtol = 1e-3`, `atol = 1e-6`, no option for now |
| 5 | CSV format | **Convention of the FMI cross-check** (Reference-FMUs, fmpy): comma separator, first column `time`, headers are the names of the FMI variables (quotes allowed). HDF5 and other types: not supported, warning |
| 6 | Trigger | **Automatic** with `fmutool -check` when the FMU has an LS-REF manifest: static validation and replay of the experiments. If the container runtime is not available for the host platform: warning, replay skipped, the rest of the check passes |
| 7 | Interpolation of the stimuli | Linear for the continuous real variables, previous value (zero-order hold) for the discrete reals, integers, booleans and strings |
| 8 | Experiments replayed | Sub-roles `smoke-test` (or none) and `validation`; `uncertainty-analysis`: static validation only, information message |
| 9 | Variables of the references | **Outputs only** (causality `output`); any other column: error of the check |
| 10 | Test FMUs | **Source FMUs compiled at test time**: copies of `tests/data/compile/*/{BouncingBall,Feedthrough}.fmu` with an LS-REF manifest, experiment files and CSV fabricated by the tests, compiled for the host platform with the compiler of the toolbox |
| 11 | Missing related file, absolute URI | **Warning**, the entry is ignored. Error only when a replayed experiment needs a file (parameters, stimuli, references) that cannot be found |
| 12 | Attribute `tolerance` of an experiment | **Ignored** (information message when present): the container runtime also uses the tolerance of `SetupExperiment` as its tolerance on time (see the pending step issue found during the cache benchmark) |
| 13 | Experiment without `stepSize` | Step size **deduced** by the builder from the FMU (as `fmucontainer` does), information message |
| 14 | Targets of the stimuli and of the SSV parameters | **Strict**: stimuli on variables of causality `input`; SSV parameters on `parameter` / `structuralParameter` variables (and `input` with a start value); any other variable or unknown name: error of the check |
| 15 | Dot segments in the relative URIs (manifest, experiment files) | **Allowed** while the resolved path stays inside the FMU (e.g. `../../resources/x.csv`, as the specification supports every relative URI inside the FMU); a path leaving the FMU is reported as an absolute URI (decision 11). Decided 2026-11-09, step 1 |
| 16 | `fmi-ls-description` of the manifest missing or different from the XSD | **Warning** (the Reference-FMUs have none); the other deviations from the XSD stay errors. Decided 2026-11-09, step 3 |
| 17 | CSV file of role `result` (Reference-FMUs) | **Replayed** with the `DefaultExperiment` of the FMU (no stimuli, no parameters) and compared with the file. Decided 2026-11-09, step 3 |
| 18 | Columns of a `result` file that are not outputs of the FMU, or binaries | **Warning**, column ignored; decisions 9 and 14 stay strict for the experiment files. Decided 2026-11-09, step 3 |
| 19 | Reference-FMUs in the tests of the replay | **Yes**, BouncingBall and Feedthrough (2.0 and 3.0) compiled at test time and replayed with their `result`, besides the fabricated FMUs. Decided 2026-11-09, step 3 |
| 20 | `startTime` / `stopTime` absent | The `DefaultExperiment` of the FMU, else the first / last instant of the references (information message). Decided 2026-11-09, step 5 |
| 21 | Instant of the recorded outputs | At `t_k`, after the stimuli of `t_k` and before the step to `t_k+1` (convention of fmpy and of the results of the Reference-FMUs: an output fed through follows its input at the same instant). Decided 2026-11-09, step 5 |

## Open questions (to be asked at the step that needs them)

- Comparison of non-real outputs (integers, booleans, strings, enumerations): criterion of decision 3 for the numbers,
  exact equality for the strings? (step 6)
- Events: an output that jumps between two instants of the reference (e.g. bounce of BouncingBall) may fail the
  criterion of decision 3 when the step of the simulation and the instants of the reference differ. (step 6)

## Step 0 — Plan

This document.

Commit message:
```
Plan: FMI-LS-REF support
```

## Step 1 — Reading of the LS-REF manifest and of the experiments

- `fmu_manipulation_toolbox/ls.py`: `LayeredStandard` detects LS-REF (`standards` lists `"LS-REF"`, `ref_version`).
  Dataclass `RefRelated` (`type`, `source`, `role`, `sub_roles`, `description`, `labels`) and reader of the manifest;
  `RefRelated.is_experiment`, `RefRelated.sub_role` (default `smoke-test`).
- New module `fmu_manipulation_toolbox/experiments.py`: reader of MA-HS-Experiments. Dataclasses `Experiment`
  (`name`, `description`, `start_time`, `stop_time`, `step_size`, `tolerance`, `parameters`, `stimuli`,
  `references`) and `ExperimentSource` (`source`, `type`), sources resolved relative to the experiments file.
- Resolution of the URIs (`ls.resolve_uri`): relative URI, percent-decoded, dot segments allowed inside the FMU
  (decision 15); absolute URIs, paths leaving the FMU and missing files reported (decision 11).
- Unit tests with fabricated manifests and experiment files (`tests/data/ls-ref/`).

Commit message:
```
LS-REF: read the manifest and the experiment files
```

## Step 2 — Time series (CSV)

- New module `fmu_manipulation_toolbox/timeseries.py`, pure Python (no numpy, which is not a dependency of the
  package):
  - reader of the CSV of decision 5: `TimeSeries` (`times`, `columns: dict[name, list[str]]`), checks: header with a
    first column `time`, numbers, non-decreasing times (equal times allowed: events), same number of fields per row;
  - interpolation of decision 7 (linear / zero-order hold), the kind of each column given by the caller; at an event
    (two rows with the same time), the value after the event;
  - comparison of decision 3: per variable, the maximal error, the first instant where the criterion fails.
- Unit tests.

Commit message:
```
LS-REF: CSV time series, interpolation and comparison
```

## Step 3 — Checker `OperationLsRefCheck`, static part

- The XSDs (`fmi3LayeredStandardReferenceManifest.xsd`, `maHarmonizedSpecificationExperiments.xsd`, 2-Clause BSD) are
  shipped in `fmu_manipulation_toolbox/resources/fmi-ls-ref/` with their license.
- Checks, each violation logged as an error unless stated (model of `OperationLsXcpCheck`):
  - manifest valid against its XSD, `fmi-ls-name`, `fmi-ls-version`;
  - `Related`: role and sub-roles (unknown experiment sub-role: error); missing file, absolute URI or path leaving
    the FMU: warning (decision 11);
  - experiment files of type `application/x-ma-hs-experiments`: valid against their XSD; for each experiment:
    `startTime < stopTime` when both given, `stepSize > 0`; sources of type `text/csv` (stimuli, references) and
    `application/x-ssp-parameter-set` (parameters); other types: warning (decision 5);
  - CSV files: format of step 2; stimuli columns are `input` variables, reference columns are `output` variables
    (decisions 9 and 14);
  - SSV parameters: variables of decision 14 (`experiments.read_parameter_set`: the reader of `ssp.py` is bound to
    the assembly of SSP);
  - `result` files (decisions 17 and 18): CSV readable; replayed with the `DefaultExperiment`, the outputs of a
    comparable type compared;
  - `fmi-ls-description`: warning (decision 16).
- The checker keeps the experiments to replay (`RefReplay`: related file, experiment, outputs to compare) for step 6.
- Registered in `get_checkers()`; unit tests with fabricated FMUs (no binary needed).

Commit message:
```
Checker: static rules of FMI-LS-REF

fmutool -check validates the manifest of FMI-LS-REF and its experiment files
against their XSD, and the stimuli, references and parameters they refer to.
```

## Step 4 — Test FMUs

- Test helper (`tests/conftest.py` or `tests/ls_ref.py`): builds an LS-REF FMU from a copy of
  `tests/data/compile/<version>/<model>.fmu`: manifest, experiment files, CSV and SSV written by the test, `binaries/`
  compiled for the host platform with `compiler.py`; skipped when no compiler is available (same rule as
  `tests/integration/test_compile_sources.py`).
- Experiments: BouncingBall (`REF-BouncingBall.csv`, outputs `h`, `v`; a parameter set changing `e`), Feedthrough
  (stimuli on its inputs, references on its outputs); and the Reference-FMUs as they are, with their `result`
  (decision 19).

Commit message:
```
Tests: FMUs implementing FMI-LS-REF, compiled at test time
```

## Step 5 — Replay of an experiment with the container runtime

- New module `fmu_manipulation_toolbox/simulation.py`:
  - temporary container (FMI version of the FMU) built with `FMUContainer`: one input per stimulus column, one output
    per reference column, the SSV parameters as start values, step size of the experiment or deduced (decision 13);
    built in a temporary directory, removed afterwards;
  - ctypes driver of the container library of the host platform (FMI 2.0 or FMI 3.0 API): instantiate, setup /
    initialization (`tolerance` not given, decision 12), then for each communication point `t_k = start + k * h`
    (computed, not accumulated): stimuli interpolated at `t_k` (step 2), outputs read and recorded at `t_k`
    (decision 21), `DoStep`; terminate, free; messages of the container forwarded to the logger (debug), the last
    ones given with a failure;
  - start and stop times of decision 20; the messages of the builder of the temporary container are debug messages
    (its errors on the inputs without stimulus would fail `-check`);
  - result: a `TimeSeries` of the outputs.
- No container library for the host platform: `SimulationUnavailable`, turned into a warning by the checker
  (decision 6).
- Tests with the FMUs of step 4.

Commit message:
```
LS-REF: replay an experiment with the container runtime
```

## Step 6 — Checker `OperationLsRefCheck`, numerical validation

- For each experiment of sub-role `smoke-test` / `validation` (decision 8): replay (step 5), comparison with the
  references (step 2, decisions 3 and 4); per failing variable an error with its maximal error and the first instant
  of failure; a summary per experiment (information). `uncertainty-analysis`: information message, not replayed.
- An experiment that cannot be replayed (missing file, failure of the simulation): error.
- Tests: references that match, a reference altered beyond the tolerance (error), runtime unavailable (warning).

Commit message:
```
Checker: replay the experiments of FMI-LS-REF and compare the results

fmutool -check replays the smoke-test and validation experiments of an FMU
implementing FMI-LS-REF with the container runtime and compares its outputs
with the references (rtol 1e-3, atol 1e-6).
```

## Step 7 — User documentation

- `docs/user-guide/fmutool/checker.md`: the LS-REF checker (static rules, replay, CSV convention, interpolation,
  tolerances, what is not supported: HDF5, `uncertainty-analysis`, `tolerance`).
- `docs/whats-new.md`, `CHANGELOG.md`.
- Move this plan to `docs/local/done/`.

Commit message:
```
Doc: FMI-LS-REF checker
```
