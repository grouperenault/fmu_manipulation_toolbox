# Propagation of the links during the initialization of a container

**Created**: 17 October 2026 — **Status**: Steps 1–2 done (17 October 2026), Step 3 to start — **Branch**: `feature/init-propagation` — **Roadmap**: not listed

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

The user documentation *From Simulink to an FMU Container* (`docs/examples/simulink-to-container.md`, section
*Initialization*, and item 6 of its *Validation checklist*) describes this difference today and its only workaround:
give the downstream inputs a start value equal to the value the upstream FMU produces at the initialization. The
TL;DR of the report lists it as the first point that breaks a migration from Simulink.

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

Propagate the internal links during the initialization, so that each embedded FMU is initialized with
the values computed by the FMUs it depends on, and so that a Simulink assembly migrated per
`docs/examples/simulink-to-container.md` initializes as in Simulink without the start value workaround.

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

## Decisions (2026-10-17)

1. **Strategy (b), FMI-style**: all the embedded FMUs stay in Initialization Mode while the linked values are
   propagated: for each FMU in the initialization order, `fmu_set_inputs` (from the buffers of the container) then
   `fmu_get_outputs` (outputs read in Initialization Mode); then `fmuExitInitializationMode` of every FMU.
2. **Order**: from the links only: topological sort of the graph of the FMUs (an edge per FMU → FMU link), computed
   by the builder.
3. **Cycles**: iteration. The sweep of decision 1 is repeated (Gauss-Seidel, in the initialization order) until the
   linked values do not change any more (tolerance of the container for the reals, equality otherwise), at most
   `CONTAINER_MAX_EVENT_ITER` sweeps; without convergence, a **warning** is logged and the initialization goes on.
4. **No option**: the propagation is always done. The results of the existing containers change (at t=0, and beyond
   for the FMUs that compute their initial state from their inputs): the REF files concerned are regenerated.
5. **Fidelity to Simulink**: for an acyclic chain, the values are those of Simulink when the outputs of an FMU do
   not change at its `fmuExitInitializationMode` (Simulink reads them after it); Simulink does not solve the loops,
   the container does. The migration page describes this remaining difference.
6. **Scope**: FMI 2.0 and 3.0 embedded FMUs, Co-Simulation and Model Exchange, nested containers (each level
   propagates its own links; a sub-container is an embedded FMU). The clocks and the clocked variables are **not**
   propagated (FMI 3.0 activates no clock in Initialization Mode).
7. **Reset of an embedded FMU**: unchanged (it is initialized with its inputs read from the buffers, without
   propagation to the other FMUs).
8. **Branch**: `feature/init-propagation`, from `importer-comparison`.
9. **Outputs read by the importer in Initialization Mode**: an `fmi2Get*` / `fmi3Get*` of the container in
   Initialization Mode first runs the propagation when it is pending (a value set by the importer since the last
   propagation, or none done yet); `container_exit_initialization_mode` runs it when it is pending too.

## Steps

### Step 1 – Initialization order in the builder

- `fmu_manipulation_toolbox/container/builder.py`: graph of the embedded FMUs from the links (clocked links
  excluded), topological sort; inside a cycle, the order of the configuration. Written in `container.txt` as a new
  section `# Initialization order` (list of FMU indexes) after the embedded FMU declarations: format **version 8**.
- `container/container.c`: the runtime reads the section (`read_conf_init_order`, `container->init_order`), used
  by Step 2. Like the other sections, without compatibility with the older versions: the runtime is always shipped
  with the `container.txt` of its builder.
- `fmu_manipulation_toolbox/split.py` (`fmusplit`) reads version 8 (the section is ignored).
- The REF `container.txt` of the tests: `# Version 8` and the new section only.
- `docs/developer/container-txt-format.md`: version 8.
- Unit tests: chain, fork, cycle, links to/from the container ports only (no edge), clocked links (no edge).

Commit message: `Compute the initialization order of the embedded FMUs`

### Step 2 – Propagation in the runtime

- `container_exit_initialization_mode`: before the `fmuExitInitializationMode` of the FMUs, the propagation sweeps
  of decisions 1 and 3 (non-clocked inputs and outputs only), with a snapshot of the linked local buffers to detect
  the convergence; warning without convergence.
- Decision 9: a "propagation pending" flag, set by `container_enter_initialization_mode` and by the setters of the
  container in Initialization Mode (`container/fmi2.c`, `container/fmi3.c`), cleared by the propagation; the
  getters of the container run the propagation first when it is set, in Initialization Mode only.
- The rest of the sequence is unchanged (`fmuExitInitializationMode`, outputs read, event iteration, step mode);
  the reset of an FMU is unchanged.

Done with the commit: the REF traces of `tests/data/probe` regenerated (S3: `B.y_init` = 6, `C.y_init` = 7), the
REF logs of `tests/data/ls-bus` get the new debug message `Initialization: links propagated in <n> sweep(s).`; the
other REF results of the test suite are unchanged.

Commit message: `Propagate the links during the initialization of the container`

### Step 3 – Tests

- Probe scenario S3 (`tools/probe_fmu/scenarios`): `B.y_init` = 6, `C.y_init` = 7 (A: `p_real` 3, `u_cont` 2);
  REF traces of `tests/data/probe` regenerated and reviewed; comparison with the Simulink traces of S3
  (`tools/compare_traces.py`).
- New probe scenario with a loop (`A.y_cont → B.u_cont`, `B.y_cont → A.u_cont`: convergence, and a divergent case
  for the warning).
- ME FMU and FMI 3.0 container cases; nested container.
- The other REF results of the test suite: regenerated where the propagation changes them, each change reviewed.

Commit message: `Test the propagation of the links during the initialization`

### Step 4 – User documentation

- `docs/user-guide/fmucontainer/container.md`: the propagation (behaviour, order, loops).
- `docs/developer/init-fmi-sequence.md`: the FMI sequence with the propagation.
- `docs/examples/simulink-to-container.md`:
  - *Behaviour differences > Initialization*: the container propagates the links like Simulink; remaining
    difference (outputs read in Initialization Mode vs after it; loops solved by the container, not by Simulink);
    the start value workaround removed;
  - *Validation checklist*: item 6 updated.
- `docs/local/importer_comparison_report.md`: TL;DR point 1 and the *Follow-up* section updated.
- `CHANGELOG.md`: 🔵 **CHANGED** entry (FMU Container): the links are propagated during the initialization (results
  at t=0 may change), linking the container guide and the migration page.

Commit message: `Document the propagation of the links during the initialization`
