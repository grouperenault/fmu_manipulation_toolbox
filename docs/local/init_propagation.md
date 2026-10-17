# Propagation of the links during the initialization of a container

**Created**: 17 October 2026 — **Status**: draft, decisions to take before Step 1 — **Roadmap**: not listed

## Context

The importer comparison study (`docs/local/importer_comparison.md`, report
`docs/local/importer_comparison_report.md`, finding 3) showed that:

- the **container** does not propagate the links between its embedded FMUs during the initialization: every FMU
  goes through `fmuEnterInitializationMode` → start values → `fmuExitInitializationMode` with its inputs at their
  start values; the outputs are read after `fmuExitInitializationMode` and reach the inputs at the first step
  (`container/container.c:413-470`);
- **Simulink** (R2024b) initializes the FMU blocks one after the other in the sorted order: for each block,
  `fmi2EnterInitializationMode` → inputs set from the outputs already read upstream →
  `fmi2ExitInitializationMode` → outputs read. In the chain `A.y_init → B.u_cont → … → C`, `B` and `C` start from
  the values computed by `A` and `B`.

An FMU whose initial state or calculated parameters depend on its inputs therefore initializes differently in a
container and in Simulink, for the whole simulation. FMI 2.0 and 3.0 allow setting inputs and getting outputs with
`initial="calculated"` in Initialization Mode, precisely so that an importer solves the initialization of the
coupled system.

At its boundary the container is already transparent during the initialization: an importer `fmi2Set*` on an exposed
input reaches the embedded FMU at once, an `fmi2Get*` reads the embedded FMU directly (`container/fmi2.c:182-250`).
Only the internal links are concerned.

### What the runtime already has

- `fmu_set_inputs()` / `fmu_get_outputs()` (`container/fmu.c`): set the linked inputs of one FMU from the buffers of
  the container, read its outputs into them.
- The reset of an embedded FMU (`container_reset_fmu`, `container/container.c:820`) already initializes **one** FMU
  with its linked inputs set in Initialization Mode: Reset → SetupExperiment → start values → cached importer values
  → Enter → start values (`<RESET>`) → `fmu_set_inputs` → Exit → event iteration → step mode.
- The links are known by the builder (`fmu_manipulation_toolbox/container/builder.py`), which can compute an order
  of the FMUs and write it in `container.txt`.

## Goal

Optionally propagate the internal links during the initialization, so that each embedded FMU is initialized with
the values computed by the FMUs it depends on.

## Constraint

The container is itself in Initialization Mode between the `fmi2EnterInitializationMode` and the
`fmi2ExitInitializationMode` of its importer, which may set the exposed inputs meanwhile. The propagation therefore
happens in `container_exit_initialization_mode`, once the importer has set every input.

## Options

### Strategy

- **(a) Simulink-like, sequential**: all the FMUs enter Initialization Mode at the container `Enter` (as today); at
  the container `Exit`, in the order of the dependencies, for each FMU: `fmu_set_inputs` → `fmuExitInitializationMode`
  → `fmu_get_outputs`. No output is read in Initialization Mode (robust against the FMUs that handle it badly), the
  downstream FMUs see the outputs after the initialization of the upstream ones. A loop cannot be solved.
- **(b) FMI-style, in Initialization Mode**: at the container `Exit`, all the FMUs still in Initialization Mode, in
  the order of the dependencies: `fmu_get_outputs` of the upstream FMU (outputs `initial="calculated"`) →
  `fmu_set_inputs` of the downstream one; then `fmuExitInitializationMode` of every FMU. Closer to the intent of the
  standard; allows a fixed-point iteration on a loop; reads outputs in Initialization Mode.

### Order

- **Order of the links** (topological sort of the FMU graph built from the links), or **finer**, from the
  `InitialUnknowns` dependencies of each FMU (an output that does not depend on the inputs does not create an edge).
- Cycles: refuse (error at build time), cut with a warning (the FMU of the cycle that comes first in the
  configuration starts from its start values), or iterate (strategy (b) only: limit and tolerance).

## Decisions to take (before Step 1)

1. **Strategy**: (a) sequential Simulink-like, (b) FMI-style in Initialization Mode, or both behind the option?
2. **Order**: from the links only, or from the `InitialUnknowns` dependencies?
3. **Cycles**: error, cut with a warning, or iteration?
4. **Option**: name (e.g. `init_propagation`) and where it is given (JSON / CLI / GUI / MCP, as `mt` or
   `sequential`); **default**: off (no change for the existing containers) or on (closer to Simulink and to the
   standard, but the results at t=0, and sometimes beyond, change)?
5. **Scope**: FMI 2.0 and 3.0; Co-Simulation and Model Exchange FMUs (the ME FMUs are in Event Mode after
   `fmuExitInitializationMode`); nested containers (each level propagates its own links)?
6. **Reset of an embedded FMU**: keep its current initialization (inputs from the buffers), unchanged by the option?
7. **Branch** of the work.

## Steps (draft, to be refined after the decisions)

### Step 1 – Order of the initialization in the builder

Graph of the FMUs from the links (or the `InitialUnknowns`), topological sort, handling of the cycles per decision
3; the order written in `container.txt` (new line, new format version) when the option is on.
Unit tests on assemblies with a chain, a fork, a cycle.

Commit message: `Compute the initialization order of the embedded FMUs`

### Step 2 – Propagation in the runtime

`container_exit_initialization_mode` per decision 1; reading of the new line of `container.txt`; FMI 2.0 and 3.0
entry points unchanged.

Commit message: `Propagate the links during the initialization of the container`

### Step 3 – Option in the API, CLI, GUI and MCP

Option per decision 4 in the JSON description, the CLI, the GUI and the MCP assistant; `fmusplit` keeps it.

Commit message: `Add the init_propagation option to the container builder`

### Step 4 – Tests

Probe scenario S3 (`tools/probe_fmu/scenarios`) with the option: `B.y_init` / `C.y_init` as in Simulink; new REF
traces; existing REF results unchanged with the option off; ME and FMI 3.0 cases.

Commit message: `Test the propagation of the links during the initialization`

### Step 5 – User documentation

`docs/user-guide/fmucontainer/container.md` (option, behaviour, cycles), `docs/developer/init-fmi-sequence.md`
(sequence with the option), the migration page from Simulink (Step 5 of `docs/local/importer_comparison.md`),
`CHANGELOG.md`.

Commit message: `Document the propagation of the links during the initialization`
