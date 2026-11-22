# Export of an assembly to Simulink

**Status**: decisions 1 to 38 taken (22 November 2026), steps 1 to 6 done — **Branch**: `feature/simulink-export`,
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

## Validation on MATLAB (step 6, 22 November 2026)

Validation pack of 9 cases (FMI-2 CS, `reset_ports`, ME only, CS + ME, FMI-3, sub-container at another rate,
start value of a parameter, assembly read from an SSP file, unconnected input), run by the user on Windows:

- Every model is built, saved and readable (decision 38); every model simulates without error (decisions 34, 37).
- Verified: `PreLoadFcn` (a saved model opens and simulates after a restart of MATLAB, from another current folder),
  the resettable subsystem (`built-in/ResetPort`, `ResetTriggerType` = `level`, line to `…/Reset`), the value of a
  parameter (`set_param` with the name of the variable), the `Constant` block of an unconnected input.
- Limit found: the FMUs generated by MATLAB/Simulink cannot be reset; the general case works.
- Still `UNVERIFIED` (not covered by the pack): the start value of a connected input (`set_param` with the name of
  the input, decision 3), the names of variables that are not MATLAB identifiers (dots, brackets), the links of
  clocks (decision 24).
- Found during the validation, and fixed: the model shadowing the function (decisions 32, 33), the folders refused by
  MATLAB on its path (decision 36), the loops (decision 34), the atomic subsystems (decision 35), the numerical
  compensation (decision 37), the layout (decision 38).

## Decisions (2026-10-13)

1. **Output**: a `.zip` archive containing the generated `.m` script and the FMU files (strategy "1a": no MATLAB
   needed to export, no direct `.slx` writing). Replaced by decision 28: the `.m` script only.
2. **Entry points**: Python API, CLI and Container Builder GUI. Not exposed as an MCP tool. CLI and GUI amended by
   decision 29.
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
11. **Tests**: pytest only, on the generated `.m` (no MATLAB in the tests).
12. **Simulink API names**: based on the public MathWorks documentation, validated manually at the end.

## Decisions (2026-10-17)

13. **No `step_size` anywhere in the tree**: the solver step is the smallest `DefaultExperiment` `stepSize` of the
    embedded FMUs (as `make_fmu` does); the export fails with an error if no FMU defines one.
14. ~~**Zip layout**: `<name>.m` at the root of the archive, FMU files in a `fmus/` folder.~~ Replaced by decision
    28.
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
    folders of the FMUs to the MATLAB path (decision 28: relative to the `.slx`), so that the saved model opens and
    simulates without any action (`UNVERIFIED` on R2024b).
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

28. **A MATLAB script only** (replaces decisions 1 and 14, taken at step 1): the export writes the `.m` script,
    without archive. The script designates the FMUs in place: it adds their folders to the MATLAB path, relative to
    the folder of the script, and the `PreLoadFcn` of the model does the same (decision 20). The script holds no
    absolute path: an FMU on another drive than the script (Windows) is an error. Two different FMUs with the same file name are an error (the FMU block designates
    an FMU by its file name only). The script and the FMUs must keep their relative places.
29. **Entry points** (amends decision 2): CLI `fmucontainer -simulink FILE.m` (the FMU container is built too);
    in FMU Container Builder, a format of **Save** ("MATLAB script for Simulink (*.m)"), the extension decides; no
    check box.
30. ~~**Names** (amends decisions 15 and 16): MATLAB names a function after its file: the stem of the `.m` names
    the function and the model, and must be a valid MATLAB identifier (an error otherwise).~~ Replaced by decision
    32.
31. **Implicit links and ports in the CLI** (amends decision 5, taken at step 4): `fmucontainer -simulink` writes
    the script after the build: the implicit links and ports, made explicit by `make_fmu` (`implicit_resolved` of
    the node), are exported, so that the model matches the container; no warning then. The GUI, which exports
    without building, keeps decision 5. A parameter exposed as an input of the container, or a local variable
    exposed as an output (`auto_parameter`, `auto_local`), has no port on the FMU block: it is not exposed, with a
    warning. `-simulink` with several `-container` is a usage error (one script).

32. ~~**Name of the script** (replaces decision 30, after the first run on MATLAB): the model and the function cannot
    have the same name ("the model name '…' is shadowing a name in the MATLAB workspace"). The name given (CLI
    `-simulink model.m`, file chosen in **Save**) is the one of the model; the script is always `build_<model>.m`,
    whose function `build_<model>()` builds and saves `<model>.slx` (`build_` is not repeated when the name already
    starts with it). The name of the model must be a valid MATLAB identifier.~~ Replaced by decision 33.
33. **Name of the script and of the model** (replaces decision 32): the file created is the one chosen (CLI
    `-simulink toto.m`, `toto.m` in **Save**): its function `toto()` builds and saves the model `toto_model.slx`.
    The model and the function cannot have the same name ("the model name '…' is shadowing a name in the MATLAB
    workspace"). The stem of the script must be a valid MATLAB identifier, of at most 57 characters (63 with
    `_model`).

34. **Loops** (from the user, after the first run on MATLAB): Simulink sees an FMU block, and an atomic subsystem,
    as a block with direct feedthrough: a loop of them is an algebraic loop. A depth-first search of the blocks of
    each system, in the order of the assembly, finds the lines that close a loop; each one gets a *Unit Delay*
    (`built-in/UnitDelay`, sample time of the system), whose initial value is the start value of its source output,
    otherwise of its target input, otherwise 0.
35. **Atomic subsystems** (from the user): every generated subsystem (sub-container, resettable subsystem of
    decision 23) is atomic (`TreatAsAtomicUnit` = `on`).

36. **Folders refused by MATLAB** (after the second run on MATLAB: "Adding folders named 'resources' to the path is
    not supported"): the FMUs of a folder named `resources` or `private`, or of a class or package folder (`@…`,
    `+…`), typically the FMUs extracted from an SSP file (`<ssp>.dir/resources`), are copied into `<script>_fmus/`
    next to the script, designated relatively; the other FMUs stay in place. A script written in such a folder is an
    error.

37. **No numerical compensation** (from the user): the numerical compensation of the co-simulation signals is
    disabled on each input port of the Co-Simulation FMU blocks (`CoSimSignalCompensationMode` = `Auto_Off`, set on
    the handles of `get_param(block, 'PortHandles').Inport`; documented by MathWorks, there is no setting for a whole
    block or model). The FMU blocks get the inputs of the container, not extrapolated values.

38. **Layout by Simulink** (from the user, replaces the grid layout of the design): each system (model,
    subsystems, resettable subsystems) is laid out by `Simulink.BlockDiagram.arrangeSystem` once its lines are added
    (documented since R2018a). It also resizes the blocks: a local function of the script gives back their default
    size to the `Inport`, `Outport`, `Constant`, `Terminator` and `UnitDelay` blocks, around their center (workaround
    of MATLAB Answers 2032409); they are also created at their default size. The FMU blocks keep the size of the
    layout.

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
               └── writes <name>.m: addpath of the folders of the FMUs, relative to the script (decision 28)
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
  with `fileparts(mfilename('fullpath'))`, adds the folders of the FMUs, relative to it, to the MATLAB path
  (`addpath`), and gives the FMU blocks the file names only (decision 28). The `PreLoadFcn` of the model adds the
  same folders, relative to the `.slx` (decision 20).
- **Layout**: simple grid placement (`Position`) so that the generated model is readable; no routing.
- **Model settings**: fixed-step solver (`FixedStep` = GCD of the sample times), `EnableMultiTasking` = `off`,
  `BlockReduction` = `off`, `StartTime` / `StopTime` when the assembly gives them, `PreLoadFcn` adding the
  folders of the FMUs to the path.
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

### Step 3 – Script file and Python API

- `SimulinkExporter.export(script_path)` writes the MATLAB script (decision 28). Its stem must be a valid MATLAB
  identifier (`AssemblyError` otherwise): it names the function and the model (decision 30).
- Public API: `Assembly.make_simulink(filename)`, mirroring `write_ssp`.
- Tests `tests/integration/test_simulink_export.py`: the script is written, its function and model names follow the
  file name, the folders of the FMUs are relative to the script (another drive is an error), an invalid file name
  is refused.

Commit message: `Export an assembly as a MATLAB script building its Simulink model`

### Step 4 – CLI

- `cli/fmucontainer.py`: option `-simulink FILE.m` (help: "Also export the container as a MATLAB script building
  its Simulink model"); after `make_fmu` (as `-dump-ssp`), call `make_simulink(FILE.m)`; `AssemblyError` →
  `ExitCode.OPERATION_FAILED`.
- Tests in `tests/integration/test_cli.py` and `test_cli_errors.py` (`ts_multiplier` → error exit code).

Commit message: `Add the -simulink option to fmucontainer`

### Step 5 – Container Builder GUI

- `gui/fmucontainer/__main__.py`: a format "MATLAB script for Simulink (*.m)" in the filters of **Save** (decision
  29): the chosen filter or extension decides, as for JSON, CSV and SSP.
- `gui/fmucontainer/assembly_io.py`: the save of a `.m` builds the assembly and calls `make_simulink`. The MCP
  bridge is not changed (decision 2: no MCP tool).
- GUI test in `tests/gui/`.

Commit message: `Add the Simulink export to the Save action of FMU Container Builder`

### Step 6 – Manual validation on MATLAB R2024a+ (user)

- Run the generated script of a few reference assemblies (flat, nested, multi-instances, multi-rate, ME, FMI-3,
  start values on parameters and on inputs, `reset_ports`, LS-BUS) in MATLAB R2024a or newer; check the model builds,
  opens again after a restart of MATLAB (`PreLoadFcn`), the start values are applied, the FMUs are reset, and the
  simulation runs; compare with the container on one assembly.
- Correct the `UNVERIFIED` constants and remove the `% UNVERIFIED` comments that are confirmed; update the snapshot.

Commit message: `Fix the Simulink block parameters after validation on MATLAB`

### Step 7 – User documentation

- `docs/user-guide/fmucontainer/container.md`: `-simulink` in *Command Line Options*, `make_simulink` in *Python
  API*, new section *Simulink export* (the script and where the FMUs must stay, how to run it, what is not exported:
  implicit links, `ts_multiplier`, `mt`/`profiling`/`sequential`; sample times and solver step; unconnected inputs
  and outputs; `reset_ports`; Simulink version).
- `docs/user-guide/fmucontainer/gui-usage.md`: the new format of **Save** (decision 29).
- `CHANGELOG.md` entry.

Commit message: `Document the Simulink export`
