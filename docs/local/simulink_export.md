# Export of an assembly to Simulink

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

Source: the Simulink models of the importer comparison study (branch `importer-comparison`,
`docs/local/importer_comparison.md`, scripts `tools/probe_fmu/scenarios/simulink/`), built with `add_block` /
`set_param` on MATLAB R2024b (Windows) with FMI 2.0 Co-Simulation probe FMUs.

| Item | Result |
|------|--------|
| Library path for `add_block` | **verified**: `simulink_extras/FMU Import/FMU` (after `load_system('simulink_extras')`) |
| `FMUName` | **a path is refused**: "The path specification for FMU file '…' is not supported. Use 'addpath' to add the folder to the MATLAB path, then edit the path specification to contain only the FMU file name." Only the file name is accepted, its folder must be on the MATLAB path — also when the model is simulated (the model only stores the file name) |
| CS / ME mode | Co-Simulation chosen by the block for a CS-only FMU (mask shown as `<model> [Co-Simulation, v2.0]`); FMUs with both interfaces not tested |
| `FMUInputMapping` / `FMUOutputMapping` = `Flat`, `FMUSampleTime` | accepted |
| Parameter value | `set_param(h, '<variable_name>', '<value>')` **accepted** (no error) for `Real` parameters (`fixed` and `tunable`, value as a MATLAB expression, e.g. `'3'`) and `String` parameters (quoted MATLAB char, e.g. `'''A.csv'''`); the values actually received by the FMU are to be confirmed by the traces (pending) |
| `Boolean` parameter value | `'false'` is **refused** ("Invalid setting in … block (mask) … for parameter '…'"); `'off'` is accepted (probably a check box of the mask): `'on'` / `'off'` |
| `Integer` parameter value | not tested |
| Input start value | still no programmatic name; to be read from the dialog (pending) |
| Order of the `Flat` ports | pending (traces of the study) |
| Several rates | Simulink defaults (not specific to the FMU block): single-tasking accepts lines between different rates; multi-tasking ("Treat each discrete rate as a separate task", `EnableMultiTasking`) refuses them without a *Rate Transition* block (`MultiTaskRateTransMsg` = `error`). The models of the study build in both modes (multi-tasking with explicit *Rate Transition* blocks); simulation pending |

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
6. **Time step**: handled by the solver configuration: fixed-step solver whose step is the **smallest** `step_size`
   found in the assembly tree.
7. **`ts_multiplier`**: not supported, the export fails with an error.
8. **FMU block mode**: according to the FMU, Co-Simulation when available, Model Exchange otherwise (same rule as
   `EmbeddedFMU.is_me`).
9. **FMI versions**: FMI 2.0 and 3.0.
10. **`mt`, `profiling`, `sequential`**: ignored with a warning. **Dropped ports**: connected to a `Terminator`
    block.
11. **Tests**: pytest only, on the content of the `.zip` and of the generated `.m` (no MATLAB in the tests).
12. **Simulink API names**: based on the public MathWorks documentation, validated manually at the end.

## Decisions (2026-10-17)

13. **No `step_size` anywhere in the tree**: the solver step is the smallest `DefaultExperiment` `stepSize` of the
    embedded FMUs (as `make_fmu` does); the export fails with an error if no FMU defines one.
14. **Zip layout**: `<name>.m` at the root of the archive, FMU files in a `fmus/` folder.
15. **Model name**: the container name (`a.fmu` → model `a`, saved as `a.slx`), made a valid MATLAB identifier.
16. **Script form**: a MATLAB function `<name>()` that builds and saves the model and returns its name.

## Open points (2026-10-17, from the importer comparison study)

- **MATLAB path when the saved model is opened or simulated later**: the model only stores the FMU file names.
  Options: (a) the generated function only adds the path while building; the user runs `addpath` before
  simulating (documented); (b) the generated function also sets a model callback (e.g. `PreLoadFcn`) adding the
  `fmus/` folder (relative to the `.slx`) to the path; (c) other.
- **Sample time of the FMU blocks**: decision 6 sets the solver step to the smallest `step_size`, but not the
  `FMUSampleTime` of the blocks. The container steps every embedded CS FMU with the container step (LCM of the
  fixed steps by default), while Simulink steps each block at its own sample time: a block sample time equal to
  the container step reproduces the container, the FMU `stepSize` reproduces a native Simulink assembly. To be
  decided with the results of the study (scenario S4).
- **Multi-tasking**: the export keeps single-tasking (no *Rate Transition* block needed), or offers multi-tasking
  with *Rate Transition* blocks?
- Still pending from the study: input start values (dialog), order of the `Flat` ports, propagation of the links
  during the initialization (S3).

## Design

```
Assembly ──► SimulinkExporter (fmu_manipulation_toolbox/simulink.py)
               ├── checks: ts_multiplier → AssemblyError ; mt/profiling/sequential/auto_* → warnings
               ├── reads each distinct FMU file once with EmbeddedFMU (ports order, causality, variability, FMI, CS/ME)
               ├── computes the solver step = min(step_size) over the tree, else min(FMU DefaultExperiment)
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
  block parameter value (accepted on R2024b), input → input start value (`UNVERIFIED`). The value is rendered
  according to the port type (`Real`/`Float64` as number, `Integer` as number (not tested), `Boolean` as `'on'` /
  `'off'` (R2024b refuses `'false'`), `String` as a quoted MATLAB char). An unknown port is an error.
- **FMU paths**: `FMUName` only accepts a file name on the MATLAB path (R2024b). The script finds its own folder
  with `fileparts(mfilename('fullpath'))`, adds `<folder>/fmus` to the MATLAB path (`addpath`) and gives the FMU
  blocks the file names only, so the extracted archive can still be moved. The path is also needed to simulate the
  saved model: see the open points (2026-10-17).
- **Layout**: simple grid placement (`Position`) so that the generated model is readable; no routing.
- All undocumented Simulink names live in one table of constants in `simulink.py`.

## Steps

### Step 1 – Analysis of the assembly

- New module `fmu_manipulation_toolbox/simulink.py` with `SimulinkExporter(assembly)`:
  - walk the tree; raise `AssemblyError` if any node has `ts_multiplier`;
  - log warnings for `mt`, `profiling`, `sequential` and active `auto_*` flags (node name in the message);
  - load each distinct FMU file once (`EmbeddedFMU`), map instance names to it;
  - compute the solver step: smallest `step_size` of the tree, otherwise smallest FMU `DefaultExperiment`
    `stepSize`, otherwise `AssemblyError`;
  - derive the model name from the container name (valid MATLAB identifier: letter first, `[A-Za-z0-9_]`,
    at most `namelengthmax` = 63 characters);
  - build the intermediate model: systems (root + subsystems), FMU blocks with mode and start values,
    `Inport`/`Outport`, `Terminator`, lines with port indices; raise `AssemblyError` for unknown ports.
- Unit tests `tests/unit/test_simulink_model.py`: on assemblies from `tests/data/containers` (flat, nested,
  multi-instances, ME, FMI 3): errors, warnings (`caplog`), step size, port indices, start value targets.

Commit message: `Add the analysis of an assembly for the Simulink export`

### Step 2 – Generation of the MATLAB script

- `MatlabWriter`: renders the intermediate model as a MATLAB function `function model = <name>()` (function name =
  file name = model name): `new_system`, `add_block` (FMU,
  `built-in/Subsystem`, `Inport`, `Outport`, `Terminator`), `set_param` (`FMUName`, mappings, start values, solver
  `SolverType`/`FixedStep`), `add_line`, `save_system`. Identifier and string escaping for MATLAB.
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

- Run the generated script of a few reference assemblies (flat, nested, multi-instances, ME, FMI 3, start values on
  parameters and on inputs) in MATLAB R2024a or newer; check the model builds, the start values are applied and the
  simulation runs.
- Correct the `UNVERIFIED` constants and remove the `% UNVERIFIED` comments that are confirmed; update the snapshot.

Commit message: `Fix the Simulink block parameters after validation on MATLAB`

### Step 7 – User documentation

- `docs/user-guide/fmucontainer/container.md`: `-simulink` in *Command Line Options*, `make_simulink` in *Python
  API*, new section *Simulink export* (content of the archive, how to run the script, what is not exported:
  implicit links, `ts_multiplier`, `mt`/`profiling`/`sequential`; solver step rule; Simulink version).
- `docs/user-guide/fmucontainer/gui-usage.md`: the new Configuration check box.
- `CHANGELOG.md` entry.

Commit message: `Document the Simulink export`
