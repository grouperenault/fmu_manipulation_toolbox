# Export of an assembly to Simulink

**Status**: decisions 1 to 27 taken (22 November 2026), step 1 done — **Branch**: `feature/simulink-export`,
rebased on `integration` (`0f8db8e`) — **Roadmap**: "Export to Simulink"

## Context

An assembly built with FMU Container Builder (`Assembly` / `AssemblyNode` in `fmu_manipulation_toolbox/assembly.py`)
describes FMUs (possibly several instances of the same file), links between them, exposed inputs/outputs, start values,
dropped ports and nested sub-containers. Today it can only be turned into an FMU Container (`make_fmu`).

Goal: also export it as a Simulink model (MATLAB R2024a or newer) built with native **FMU blocks** (library
*Simulink Extras / FMU Import*), configured with the start values of the assembly.

The `.slx` format is not documented, so it is not written directly: the export produces a **MATLAB script** that
builds and saves the model when run in MATLAB.

### What the public MathWorks documentation gives

Source: [FMU block reference](https://www.mathworks.com/help/simulink/ref_extras/fmu.html),
[Implement an FMU Block](https://www.mathworks.com/help/simulink/ug/implement-an-fmi-block.html),
[MATLAB Answers 2128526](https://uk.mathworks.com/matlabcentral/answers/2128526-how-to-set-parameters-in-an-fmu-from-matlab-simulink).

| Need | Documented? | Programmatic name |
|------|-------------|-------------------|
| FMU file | yes | `FMUName` (path, `.fmu` optional) |
| Sample time (CS only) | yes | `FMUSampleTime` (`-1` = inherited) |
| Port/parameter layout | yes | `FMUInputMapping`, `FMUOutputMapping`, `FMUParamMapping` (`Inherit`/`Flat`/`Structured`) |
| Parameter value | community answer only | `set_param(h, '<variable_name>', '<value>')`, only for `fixed`/`tunable` variables |
| Input start value | **no** | unknown (Input tab of the dialog) |
| CS / ME mode | **no** | unknown; the block chooses automatically, and asks when the FMU provides both |
| Library path for `add_block` | **no** | the documentation only gives *Simulink Extras / FMU Import / FMU* |
| Naming of structured / dotted variables | **no** | unknown |

Every undocumented item is isolated in one place of the generator (see Step 2) and marked `UNVERIFIED` in the
generated script, so that the final manual validation (Step 6) only has to correct that place.

### What MATLAB R2024b showed (2026-10-17)

Source: the Simulink models of the importer comparison study (`docs/local/done/importer_comparison.md`, scripts
`tools/probe_fmu/scenarios/simulink/`), built with `add_block` /
`set_param` on MATLAB R2024b (Windows) with FMI 2.0 Co-Simulation probe FMUs.

| Item | Result |
|------|--------|
| Library path for `add_block` | **verified**: `simulink_extras/FMU Import/FMU` (after `load_system('simulink_extras')`) |
| `FMUName` | **a path is refused**: "The path specification for FMU file '…' is not supported. Use 'addpath' to add the folder to the MATLAB path, then edit the path specification to contain only the FMU file name." Only the file name is accepted, its folder must be on the MATLAB path — also when the model is simulated (the model only stores the file name) |
| CS / ME mode | Co-Simulation chosen by the block for a CS-only FMU (mask shown as `<model> [Co-Simulation, v2.0]`); FMUs with both interfaces not tested |
| `FMUInputMapping` / `FMUOutputMapping` = `Flat`, `FMUSampleTime` | accepted |
| Parameter value | **verified** by the traces: `set_param(h, '<variable_name>', '<value>')` for `Real` parameters (`fixed` and `tunable`, value as a MATLAB expression, e.g. `'3'`) and `String` parameters (**raw text**, e.g. `'A.csv'`: a quoted `'''A.csv'''` reaches the FMU with its quotes) |
| `Boolean` parameter value | `'false'` is **refused** ("Invalid setting in … block (mask) … for parameter '…'"); `'off'` is accepted (probably a check box of the mask): `'on'` / `'off'` |
| `Integer` parameter value | not tested |
| Input start value | still no programmatic name. An **unconnected input is set to 0** by Simulink (in Initialization Mode and before every step): the start value of the FMU is lost. Whether a start value entered in the dialog replaces the 0 is not tested |
| Order of the `Flat` ports | **verified**: order of the variables in `modelDescription.xml` (Real and Integer inputs and outputs, FMI 2.0) |
| FMU block without destination | **removed by the block reduction**: nothing is simulated ("All blocks … have been removed by block reduction optimization"). Root `Outport` blocks keep the FMU blocks; `BlockReduction` = `off` too. A `Terminator` is not tested |
| Initialization | the links are **propagated**: Simulink initializes the blocks one after the other in the sorted order (`fmi2EnterInitializationMode`, inputs set from the outputs read upstream, `fmi2ExitInitializationMode`, outputs read); the container does not propagate them |
| Calls before the initialization | every parameter (defaults included) is set before `fmi2SetupExperiment`; `fmi2SetupExperiment` with tolerance 0.001 |
| Several rates | Simulink defaults (not specific to the FMU block): single-tasking accepts lines between different rates; multi-tasking ("Treat each discrete rate as a separate task", `EnableMultiTasking`) refuses them without a *Rate Transition* block (`MultiTaskRateTransMsg` = `error`). The models of the study run in both modes; with multi-tasking, a deterministic *Rate Transition* ("Ensure deterministic data transfer") needs rates that are integer multiples ("Illegal rate transition … must be integer multiples"): off otherwise (`Deterministic` = `off`), and it delays the slow → fast transfers by one slow period |

## Decisions (2026-10-13)

1. **Output**: a `.zip` archive containing the generated `.m` script and the FMU files (strategy "1a": no MATLAB
   needed to export, no direct `.slx` writing).
2. **Entry points**: Python API, CLI and Container Builder GUI. Not exposed as an MCP tool.
   - CLI: new option `fmucontainer -container a.json -simulink` produces `a.zip` **in addition** to `a.fmu`.
   - GUI: a check box in the *Configuration* menu (like *Enable Datalog*); when checked, *Save as FMU Container*
     also produces the `.zip`.
3. **Start values on FMU inputs**: set in the FMU block configuration.
4. **Sub-containers**: exported as Simulink subsystems (one `Subsystem` per nested `AssemblyNode`, with
   `Inport`/`Outport` blocks for its exposed ports).
5. **Implicit links and ports** (`auto_link`, `auto_input`, `auto_output`, `auto_parameter`, `auto_local`): not
   resolved, only explicit items are exported. A warning is logged for each node where such a flag is active (even
   by default).
6. ~~**Time step**: handled by the solver configuration: fixed-step solver whose step is the **smallest**
   `step_size` found in the assembly tree.~~ Replaced by decisions 17 and 18.
7. **`ts_multiplier`**: not supported, the export fails with an error.
8. **FMU block mode**: according to the FMU, Co-Simulation when available, Model Exchange otherwise (same rule as
   `EmbeddedFMU.is_me`).
9. **FMI versions**: FMI 2.0 and 3.0.
10. **`mt`, `profiling`, `sequential`**: ignored with a warning. **Dropped ports**: connected to a `Terminator`
    block (amended by decision 22).
11. **Tests**: pytest only, on the content of the `.zip` and of the generated `.m` (no MATLAB in the tests).
12. **Simulink API names**: based on the public MathWorks documentation, validated manually at the end.

## Decisions (2026-10-17)

13. **No `step_size` anywhere in the tree**: the solver step is the smallest `DefaultExperiment` `stepSize` of the
    embedded FMUs (as `make_fmu` does); the export fails with an error if no FMU defines one.
14. **Zip layout**: `<name>.m` at the root of the archive, FMU files in a `fmus/` folder.
15. **Model name**: the container name (`a.fmu` → model `a`, saved as `a.slx`), made a valid MATLAB identifier.
16. **Script form**: a MATLAB function `<name>()` that builds and saves the model and returns its name.

## Decisions (2026-11-22)

Taken when the work resumed, on `feature/simulink-export` rebased on `integration` (`0f8db8e`). They close the open
points of 2026-10-17, with the results of the importer comparison study
(`docs/local/done/importer_comparison_report.md`) and the features added to the assembly since.

17. **Sample time of the FMU blocks** (`FMUSampleTime`): the step of the node that contains the FMU (its
    `step_size`, otherwise deduced as `make_fmu` does). The model reproduces the container: with one sub-container
    per rate, the study found the same inputs at every step as Simulink in single-tasking (finding 4).
18. **Fixed step of the solver** (replaces decision 6): the exact greatest common divisor of the sample times of the
    blocks (computed with fractions, as the builder does): the smallest step when the rates are multiples of one
    another, still valid otherwise (0.02 s and 0.05 s give 0.01 s).
19. **Tasking**: single-tasking (`EnableMultiTasking` = `off`), no *Rate Transition* block.
20. **MATLAB path of the FMUs**: the generated function sets a `PreLoadFcn` callback on the model that adds the
    `fmus/` folder next to the `.slx` to the MATLAB path, so that the saved model opens and simulates without any
    action (`UNVERIFIED` on R2024b).
21. **Unconnected inputs of the FMUs**: a `Constant` block with the start value (of the assembly, otherwise of the
    FMU) on each of them, to keep the behaviour of the container (Simulink sets them to 0, finding 2).
22. **Unconnected outputs and dropped ports** (amends decision 10): `BlockReduction` = `off` on the model (verified
    on R2024b) and a `Terminator` block on each of them.
23. **`reset_ports`**: each FMU whose reset is linked or exposed is placed in a *Resettable Subsystem* (a `Reset`
    block, trigger `level`) driven by the source of its reset port. Same behaviour as the container for a pulse of
    one step (the documented use); a source held `true` resets at every step (the container: every other step).
    `UNVERIFIED`: the MathWorks documentation does not say whether the FMU block calls `fmi*Reset` in a resettable
    subsystem; all the blocks of such a subsystem must have the same sample time, which holds with one FMU per
    subsystem.
24. **Links of terminals (FMI-LS-BUS) and clocks**: exported as plain port-to-port links, the terminals expanded as
    the builder does (`Terminal.connect`); `UNVERIFIED` (support of the clocks of FMI-3 by the FMU block unknown).
25. **Start and stop time**: `start_time` / `stop_time` of the assembly → `StartTime` / `StopTime` of the model.
    The geometry read from SSP files (`fmu_geometry`) and the architecture wires are not exported (grid layout).
26. **`mt_threshold`**: ignored with `mt` (decision 10). The messages of the export follow
    `docs/developer/logging.md`.

27. **Input clocks linked together** (FMI-LS-BUS, taken at step 1): the container schedules them without
    source, and a line of Simulink goes from an output to an input: the export fails with an error naming the two
    ports.

### Closed open points (2026-10-17)

| Open point | Closed by |
|---|---|
| MATLAB path when the saved model is opened or simulated later | decision 20 |
| Sample time of the FMU blocks | decisions 17, 18 |
| Multi-tasking | decision 19 |
| Dropped ports and unconnected outputs | decision 22 |
| Unconnected inputs | decision 21 |
| Initialization | no longer a difference: the container propagates the links during the initialization since `done/init_propagation.md`, and the traces of the study are identical |

## Design

```
Assembly ──► SimulinkExporter (fmu_manipulation_toolbox/simulink.py)
               ├── checks: ts_multiplier → AssemblyError ; mt/mt_threshold/profiling/sequential/auto_* → warnings
               ├── reads each distinct FMU file once with EmbeddedFMU (ports order, causality, variability, FMI, CS/ME)
               ├── computes the sample time of each node (its step, or deduced as make_fmu) and the solver
               │   step = exact GCD of the sample times (decisions 17, 18)
               ├── builds an intermediate model (systems, blocks, lines) — pure Python, easy to test
               ├── renders it as MATLAB code (MatlabWriter, one method per kind of statement)
               └── writes <name>.zip = <name>.m + fmus/*.fmu (one copy per file, shared by its instances)
```

- **Port numbers**: `add_line` needs port indices. The FMU blocks are forced to `FMUInputMapping` /
  `FMUOutputMapping` = `Flat`, and indices are computed from the order of the input/output variables in
  `modelDescription.xml` (`EmbeddedFMU.ports`). For subsystems, indices follow the creation order of the
  `Inport`/`Outport` blocks. (`UNVERIFIED` for FMI 3.0 arrays and for the ordering rule itself.)
- **Exposed input feeding several FMU inputs**: one `Inport`, several lines (branches).
- **Start values**: the assembly stores them as text. The port causality decides the target: parameter →
  block parameter value (verified on R2024b), input → input start value (`UNVERIFIED`). The value is rendered
  according to the port type (`Real`/`Float64` as number, `Integer` as number (not tested), `Boolean` as `'on'` /
  `'off'` (R2024b refuses `'false'`), `String` as raw text, not quoted). An unknown port is an error.
- **FMU paths**: `FMUName` only accepts a file name on the MATLAB path (R2024b). The script finds its own folder
  with `fileparts(mfilename('fullpath'))`, adds `<folder>/fmus` to the MATLAB path (`addpath`) and gives the FMU
  blocks the file names only, so the extracted archive can still be moved. The path is also needed to simulate the
  saved model: see the open points (2026-10-17).
- **Layout**: simple grid placement (`Position`) so that the generated model is readable; no routing.
- **Model settings**: fixed-step solver (`FixedStep` = GCD of the sample times), `EnableMultiTasking` = `off`,
  `BlockReduction` = `off`, `StartTime` / `StopTime` when the assembly gives them, `PreLoadFcn` adding `fmus/` to
  the path.
- **Extra blocks**: `Constant` on each unconnected input (start value), `Terminator` on each unconnected output and
  dropped port, *Resettable Subsystem* (`Reset`, trigger `level`) around each FMU with a reset port.
- All undocumented Simulink names live in one table of constants in `simulink.py`.

## Steps

### Step 1 – Analysis of the assembly

- New module `fmu_manipulation_toolbox/simulink.py` with `SimulinkExporter(assembly)`:
  - walk the tree; raise `AssemblyError` if any node has `ts_multiplier`;
  - log warnings for `mt` (and `mt_threshold`), `profiling`, `sequential` and active `auto_*` flags (node name in
    the message);
  - load each distinct FMU file once (`EmbeddedFMU`), map instance names to it;
  - compute the sample time of each node (decision 17: its `step_size`, otherwise deduced as `make_fmu` does,
    otherwise `AssemblyError`) and the fixed step of the solver (decision 18: exact GCD);
  - derive the model name from the container name (valid MATLAB identifier: letter first, `[A-Za-z0-9_]`,
    at most `namelengthmax` = 63 characters);
  - build the intermediate model: systems (root + subsystems), FMU blocks with mode, sample time and start values,
    `Inport`/`Outport`, `Constant` on the unconnected inputs, `Terminator` on the unconnected outputs and dropped
    ports, resettable subsystems for `reset_ports`, links of terminals expanded; raise `AssemblyError` for unknown
    ports.
- Unit tests `tests/unit/test_simulink_model.py`: on assemblies from `tests/data/containers` (flat, nested,
  multi-instances, ME, FMI-3, multi-rate, `reset_ports`, LS-BUS): errors, warnings (`caplog`), sample times and
  solver step, port indices, start value targets, extra blocks.

Commit message: `Add the analysis of an assembly for the Simulink export`

### Step 2 – Generation of the MATLAB script

- `MatlabWriter`: renders the intermediate model as a MATLAB function `function model = <name>()` (function name =
  file name = model name): `new_system`, `add_block` (FMU,
  `built-in/Subsystem`, resettable subsystem and `Reset`, `Inport`, `Outport`, `Constant`, `Terminator`), `set_param`
  (`FMUName`, mappings, `FMUSampleTime`, start values, solver `SolverType` / `FixedStep`, `EnableMultiTasking`,
  `BlockReduction`, `StartTime` / `StopTime`, `PreLoadFcn`), `add_line`, `save_system`. Identifier and string
  escaping for MATLAB.
- Constants table for the `UNVERIFIED` names; each such statement carries a `% UNVERIFIED` comment in the script.
- Unit tests `tests/unit/test_simulink_writer.py`: escaping, rendering of each statement, snapshot of the script for
  a reference assembly.

Commit message: `Generate the MATLAB script building the Simulink model of an assembly`

### Step 3 – Zip archive and Python API

- `SimulinkExporter.export(zip_path)` writes `<name>.m` at the root of the archive and the FMU files in `fmus/`
  (distinct file names; a collision between two different files with the same name is resolved by a suffix).
- Public API: `Assembly.make_simulink(filename=None)` (default: container name with `.zip`), mirroring `make_fmu`.
- Tests `tests/integration/test_simulink_export.py`: archive listing, FMUs shared between instances stored once,
  script references matching the archive paths.

Commit message: `Export an assembly as a zip archive with a Simulink build script`

### Step 4 – CLI

- `cli/fmucontainer.py`: option `-simulink` (help: "Also export the container as a Simulink model build script
  (.zip)"); after `make_fmu`, call `make_simulink`; `AssemblyError` → `ExitCode.INVALID_INPUT`.
- Tests in `tests/integration/test_cli.py` and `test_cli_errors.py` (`ts_multiplier` → error exit code).

Commit message: `Add the -simulink option to fmucontainer`

### Step 5 – Container Builder GUI

- `gui/fmucontainer/__main__.py`: check box *Export to Simulink* in the Configuration menu, next to *Enable
  Datalog*, with a tooltip; passed to `save_as_fmu`.
- `gui/fmucontainer/assembly_io.py`: `save_as_fmu(..., simulink=False)` calls `make_simulink` with the same base
  name as the `.fmu`. The MCP bridge keeps its current signature (default `False`).
- GUI test in `tests/gui/`.

Commit message: `Add the Simulink export option to FMU Container Builder`

### Step 6 – Manual validation on MATLAB R2024a+ (user)

- Run the generated script of a few reference assemblies (flat, nested, multi-instances, multi-rate, ME, FMI-3,
  start values on parameters and on inputs, `reset_ports`, LS-BUS) in MATLAB R2024a or newer; check the model builds,
  opens again after a restart of MATLAB (`PreLoadFcn`), the start values are applied, the FMUs are reset, and the
  simulation runs; compare with the container on one assembly.
- Correct the `UNVERIFIED` constants and remove the `% UNVERIFIED` comments that are confirmed; update the snapshot.

Commit message: `Fix the Simulink block parameters after validation on MATLAB`

### Step 7 – User documentation

- `docs/user-guide/fmucontainer/container.md`: `-simulink` in *Command Line Options*, `make_simulink` in *Python
  API*, new section *Simulink export* (content of the archive, how to run the script, what is not exported:
  implicit links, `ts_multiplier`, `mt`/`profiling`/`sequential`; sample times and solver step; unconnected inputs
  and outputs; `reset_ports`; Simulink version).
- `docs/user-guide/fmucontainer/gui-usage.md`: the new Configuration check box.
- `CHANGELOG.md` entry.

Commit message: `Document the Simulink export`
