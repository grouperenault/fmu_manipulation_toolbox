# Migrating an FMU assembly from Simulink to an FMU Container

**Created**: 17 October 2026 — **Status**: Steps 1–2 done (17 October 2026), Step 3 waiting for the Simulink traces — **Branch**:
`importer-comparison` — **Roadmap**: not listed

## Goal

**Deliverable**: a user documentation page explaining how to convert an assembly of FMUs made in Simulink (native
FMU blocks) into an equivalent FMU Container, and what to check so that both give the same results.

To write it from measured facts rather than assumptions, the two importers are first compared with a
**probe FMU**: an FMU that traces every FMI call it receives (function, time, step size, values). Both importers
are seen through the same lens, independently of their own logging. The study (Steps 1–4) is the means; the
documentation (Step 5) is the product.

## Relation with the Simulink export plan

This plan is **independent** of `docs/local/simulink_export.md` (export of a container assembly to Simulink, the
opposite direction): the Simulink models of the study are built by hand (or with a small MATLAB script) by the user.

Conversely, the study answers several `UNVERIFIED` points of the export plan, which can then rely on measured
behaviour:

- how and when Simulink applies the start values of FMU **inputs** and parameters;
- the order of the `Flat` ports of the FMU block (port indices used by `add_line`);
- the effect of `FMUSampleTime` and of the fixed-step solver (the "smallest `step_size`" rule, decision 6 of the
  export plan);
- the CS / ME mode chosen by the block.

The findings on these points are recorded in the report of Step 4 and referenced from `simulink_export.md`.

## Behaviour of the container runtime (expected differences)

| Topic | Container runtime | Where | Simulink (to be confirmed by the study) |
|---|---|---|---|
| Start values | set once after `fmuSetupExperiment` (all), set again after `fmuEnterInitializationMode` (only those flagged `<RESET>`) | `container/container.c:349-430` | set through block parameters; order unknown |
| Links during initialization | **not propagated**: outputs are read only after `fmuExitInitializationMode`, inputs are set at the first step | `container/container.c:420-470` | the block sorted order may propagate outputs to inputs during initialization |
| Time step | one internal step = **LCM** of the fixed steps (or largest variable step); every CS FMU gets `doStep(h = container step)` | `fmu_manipulation_toolbox/container/builder.py:572`, `container/container.c:930` | one sample time per block, fixed-step solver at the **GCD**; a block is stepped at its own rate |
| Data exchange | at each container step only | `container/container.c:596-750` | at each rate hit; rate transitions depend on the tasking mode (single/multi-tasking) |
| Ordering | CS FMUs: set inputs → doStep → get outputs, sequential or parallel (`mt`) | `container/container.c:596` | sorted by direct feedthrough (`ModelStructure` dependencies) |

## Follow-up: propagation of the links during initialization

At its boundary the container is transparent during initialization: an importer `fmi2Set*` on an exposed input is
forwarded at once to the embedded FMU (`container/fmi2.c:225-250`), and an `fmi2Get*` reads the embedded FMU
directly (`container/fmi2.c:182-211`). Only the **internal links** (FMU → FMU) are not propagated before
`ExitInitializationMode`.

- **Impact**: at best, only the values at t=0 differ (the downstream FMU uses the start value of its input). At
  worst, when the initial state of the downstream FMU depends on its input (steady-state initialization,
  parameters calculated from an input, "initial condition from input"), the whole simulation differs.
- **Standard**: FMI 2.0 and 3.0 allow setting inputs and getting `initial="calculated"` outputs in Initialization
  Mode, precisely so that the master solves the initialization of the coupled system.
- **What a propagation needs**: an order (topological sort from `ModelStructure/InitialUnknowns`, already read by
  `fmu_manipulation_toolbox/container/builder.py:854`; no declared dependency = depends on every input); detection
  of algebraic loops at initialization (fixed-point iteration with a limit, or loop cut with a warning); robustness
  against FMUs that handle `Get*` in Initialization Mode badly (read only the linked outputs; see
  `container/container.c:425-432` for ME FMUs); backward compatibility (an option, e.g. `init_propagation`, with a
  default to decide).

**Decision rule**: scenario S3 measures whether Simulink propagates the links during initialization, and in which
order. If it does, a dedicated plan (`docs/local/init_propagation.md`) is opened after Step 4 (option and default,
algebraic loops, FMI 2.0 / 3.0, ME FMUs). Until it is implemented, the migration documentation describes the
difference and its workaround.

## Decisions (2026-10-17)

1. **Branch**: `importer-comparison` (main checkout).
2. **FMI**: FMI 2.0 Co-Simulation only.
3. **Implementation**: own minimal FMI 2.0 implementation, tracing built into every function, no dependency.
4. **Three step sizes**: three FMUs built from the same source, differing by `modelIdentifier`, GUID and
   `DefaultExperiment stepSize`: `Probe10ms` (0.01 s), `Probe20ms` (0.02 s), `Probe50ms` (0.05 s) — GCD 0.01 s,
   LCM 0.1 s.
5. **`h` different from the step size**: Boolean parameter `strict_step` (default `false`: trace + logger warning,
   step done with `h`; `true`: `fmi2Error`).
6. **Computation time**: Real parameter `compute_time` (s) and Boolean parameter `compute_sleep` (default `false`:
   busy wait on the wall clock; `true`: sleep).
7. **Trace**: String parameter `trace_file`; empty (default) = `<instanceName>.csv` in the current directory of the
   process.
8. **Build on every OS**: the FMUs ship **sources only** (`<SourceFiles>`), compiled on each OS with the
   *compile sources* operation of `fmutool`. No CI job.
9. **Location**: `tools/probe_fmu/` (C source, generation script, the three generated `.fmu`, committed).
10. **Probe FMU**: internal to the study, not documented for the users.
11. **Comparison**: `tools/compare_traces.py`, plus integration tests freezing the reference traces of the
    container scenarios (regression of the runtime).
12. **Documentation**: new page *Examples > From Simulink to an FMU Container*; `Examples` becomes a group in
    `mkdocs.yml` (*Common Use Cases* + the new page).
13. **MATLAB**: R2024b; the user builds and runs the Simulink models and shares the traces and logs.
14. **Results**: not versioned, in `tmp/importer_comparison/<scenario>/{container,simulink}/`; only the report
    (Step 4) is committed.
15. **Simulink models**: built by MATLAB functions (`tools/probe_fmu/scenarios/simulink/`: `build_scenarios.m`,
    `run_scenarios.m`, the definitions in `probe_scenarios.m` and the undocumented Simulink names in
    `probe_simulink_api.m`), run by the user on R2024b. S4m: explicit *Rate Transition* blocks on the lines
    between different rates (S4s, single-tasking: none), "Ensure deterministic data transfer" off between rates
    that are not integer multiples (required by Simulink). One root `Outport` per unconnected output (as
    `auto_output`) and block reduction off: otherwise Simulink removes the FMU blocks and simulates nothing.

## Probe FMU specification

### Files (`tools/probe_fmu/`)

| File | Content |
|---|---|
| `probe.c` | the whole FMI 2.0 CS implementation; includes `fmi2Functions.h` (provided by the compiler of the toolbox) and `probe_config.h` |
| `make_probe.py` | generates the three FMUs: `modelDescription.xml` and `sources/probe_config.h` (`PROBE_GUID`, `PROBE_STEP_SIZE`) per FMU, `sources/probe.c` copied |
| `Probe10ms.fmu`, `Probe20ms.fmu`, `Probe50ms.fmu` | generated, sources only |
| `README.md` | variables, trace format, how to compile (`fmutool -input Probe10ms.fmu -compile-sources ...`) |

### Variables

| VR | Name | Type | Causality | Variability | Start / initial | Behaviour |
|---|---|---|---|---|---|---|
| 0 | `p_real` | Real | parameter | fixed | 1.0 | used by `y_init` |
| 1 | `p_tunable` | Real | parameter | tunable | 0.0 | offset of `y_cont` |
| 2 | `compute_time` | Real | parameter | fixed | 0.0 | wall time spent in each `doStep` (s) |
| 3 | `compute_sleep` | Boolean | parameter | fixed | false | sleep instead of busy wait |
| 4 | `strict_step` | Boolean | parameter | fixed | false | reject `h` ≠ step size |
| 5 | `trace_file` | String | parameter | fixed | "" | path of the trace |
| 10 | `u_cont` | Real | input | continuous | 0.0 | |
| 11 | `u_disc` | Real | input | discrete | 0.0 | |
| 12 | `u_int` | Integer | input | discrete | 0 | |
| 13 | `u_bool` | Boolean | input | discrete | false | |
| 20 | `y_cont` | Real | output | continuous | calculated | `u_cont + p_tunable` (direct feedthrough) |
| 21 | `y_disc` | Real | output | discrete | calculated | `u_disc` latched at the start of the last `doStep` (no feedthrough) |
| 22 | `y_int` | Integer | output | discrete | calculated | number of `doStep` done, plus `u_int` latched like `y_disc` × 1000 (shows the delay of an Integer link) |
| 23 | `y_bool` | Boolean | output | discrete | calculated | `u_bool` latched like `y_disc` |
| 24 | `y_init` | Real | output | discrete | calculated | `p_real + u_cont`, computed on each get in Initialization Mode, frozen at `ExitInitializationMode` |
| 25 | `y_time` | Real | output | continuous | calculated | time of the FMU |

`ModelStructure`: `<Outputs>` — `y_cont` depends on `u_cont`; the others have `dependencies=""`.
`<InitialUnknowns>` — `y_cont` depends on `p_tunable` and `u_cont`, `y_init` on `p_real` and `u_cont`; the others on nothing.

Capabilities: `canHandleVariableCommunicationStepSize="false"`, `canGetAndSetFMUstate="false"`,
`canBeInstantiatedOnlyOncePerProcess="false"`, `needsExecutionTool="false"`. The FMI functions not supported
(FMU state, directional derivatives, real input derivatives) return `fmi2Error` and are traced.

### Trace (CSV)

Header `seq,wall,function,status,time,h,vr,name,value,note`, one line per FMI call, and one line per value for
`fmi2Get*`/`fmi2Set*` (same `seq`):

- `seq`: call number; `wall`: seconds since `fmi2Instantiate` (monotonic, `timespec_get`); `time`: time of the FMU
  at the call; `h`: communication step of `fmi2DoStep`; `note`: e.g. `h != step_size`, error reason.
- **Snapshots** of every variable, `function` = `SNAPSHOT`, `note` = `before_setup_experiment`,
  `before_initialization` (at `fmi2EnterInitializationMode`), `after_initialization` (at
  `fmi2ExitInitializationMode`), `terminate`.
- The lines written before `fmi2EnterInitializationMode` (when `trace_file` is still unknown) are buffered, then
  flushed when the file is opened; the file is closed by `fmi2FreeInstance` (flushed even when initialization is
  never reached).
- When debug logging is on (`fmi2SetDebugLogging`), each line is also sent to the FMI logger callback (category
  `probe`); the warnings (`h` ≠ step size) are always sent.

`fmi2Reset` restores the start values and keeps the trace file open.

## Study scenarios

### Common rules

- **Instances**: `A`, `B`, `C`. In the container they are instances (`path` block) of the probe FMUs compiled for
  the host; in Simulink one FMU block per instance, named `A`, `B`, `C`.
- **Traces**: `trace_file` is set on every instance to `<instance>.csv` (the default `<instanceName>.csv` would
  depend on the importer naming: `<container instance>.<instance>` in the container, block path in Simulink).
  Each importer runs a scenario in its own folder: `<scenario>/container/` and `<scenario>/simulink/`.
- **Container**: `auto_input: false` (no exposed input: the probe inputs only receive links and start values),
  `auto_output: true`; the container is simulated by fmpy with `step_size` = `output_interval` = the container
  step, without start values from the importer.
- **Simulink**: fixed-step solver `FixedStepDiscrete`, fixed step 0.01 s; FMU block `FMUSampleTime` = step size of
  the probe (0.01, 0.02, 0.05 s); single-tasking ("Treat each discrete rate as a separate task" off) unless stated;
  unconnected inputs left unconnected (Simulink feeds them with 0: compare with the start value seen in the
  container); `trace_file` and the other parameters set in the block dialog.
- **Stop time**: 0.2 s, except S6 (1 s).

| Scenario | Instances | Links (`from → to`) | Start values / parameters | Container variants | Simulink variants | What is compared |
|---|---|---|---|---|---|---|
| **S1** single probe | `A` = Probe10ms | none | `trace_file` only | default | default | call sequence of each importer (order of `Set`/`Get`, `SetupExperiment` arguments, number of `doStep`, `Terminate`/`FreeInstance`) |
| **S2** start values | `A` = Probe10ms | none | `p_real` = 3, `p_tunable` = 0.5, `compute_time` = 0, `u_cont` = 2, `u_disc` = 4, `u_int` = 7, `u_bool` = true | default | default | which start values are set, when (before `EnterInitializationMode` / in Initialization Mode), and the snapshots `before_initialization` / `after_initialization`; behaviour of unconnected inputs |
| **S3** initialization chain | `A`, `B`, `C` = Probe10ms | `A.y_init → B.u_cont`, `B.y_cont → C.u_cont` | `A`: `p_real` = 3, `u_cont` = 2; `C`: `p_real` = 2 | default | default | `B.y_init`, `C.y_init` after initialization: 1 / 2 if the links are not propagated, 6 / 7 if they are, 6 / 2 if only the first level is (`A.y_init` = 5, `B.y_cont` = `B.u_cont`) |
| **S4** three rates | `A` = Probe10ms, `B` = Probe20ms, `C` = Probe50ms | fast → slow: `A.y_time → B.u_cont`, `A.y_int → B.u_int`, `B.y_time → C.u_cont`; slow → fast: `C.y_time → A.u_disc`, `C.y_int → A.u_int` | none | **S4a**: default step (LCM 0.1 s); **S4b**: `step_size` 0.01 s (GCD) | **S4s** single-tasking; **S4m** multi-tasking | `doStep` times and `h` per instance (`h != step_size` notes), input value seen by each step vs producer time (delay in steps) |
| **S5** feedthrough and ordering | `A`, `B`, `C` = Probe10ms | `A.y_time → B.u_cont`, `B.y_cont → C.u_cont` (feedthrough); `A.y_time → B.u_disc`, `B.y_disc → C.u_disc` (delayed) | none | **S5j** default (Jacobi); **S5s** `sequential`, order `A, B, C`; **S5r** `sequential`, order `C, B, A` | default | `C.u_cont` and `C.u_disc` seen at each step vs `A.y_time`: delay of a feedthrough path vs a delayed path, effect of the order |
| **S6** computation time | `A`, `B`, `C` = Probe10ms | none | `compute_time` = 0.005 s on each, `compute_sleep` = false | **S6s** default; **S6m** `mt` | **S6s** single-tasking; **S6m** multi-tasking | total wall time (expected 1.5 s sequential, 0.5 s parallel) and the `wall` column of the `doStep` lines (overlap) |

### Container side (Step 2)

`tools/probe_fmu/scenarios/`: one JSON description per scenario variant (`S1.json`, `S2.json`, `S3.json`,
`S4a.json`, `S4b.json`, `S5j.json`, `S5s.json`, `S5r.json`, `S6s.json`, `S6m.json`) referencing the host-compiled
probes (`Probe10ms-host.fmu`...), and `run_container.py`:
`python tools/probe_fmu/scenarios/run_container.py -output DIRECTORY [S1 S2 ...]` compiles the probes for the host
(once), builds each container, simulates it with fmpy, and leaves in `DIRECTORY/<scenario>/container/` the traces
`A.csv`, `B.csv`, `C.csv`, the results `results.csv`, the fmpy log `log.txt` and the wall time `wall.txt`.

### Simulink side (Step 3)

`tools/probe_fmu/scenarios/README.md` describes, for each scenario variant, the Simulink model to build on MATLAB
R2024b (blocks, sample times, block parameters, lines, solver, tasking mode, stop time) and where to put the
traces. The probes must first be compiled on the MATLAB machine:
`fmutool -input Probe10ms.fmu -compile-sources -output Probe10ms-host.fmu` (MSVC on Windows).

## Expected content of the user documentation

- **Mapping of concepts**: FMU block → embedded FMU (`fmu`, instance name); line → link; `Inport`/`Outport` →
  exposed input/output; `Terminator` → dropped port; subsystem → nested container; block parameter / input start
  value → `start`; `FMUSampleTime` and solver step → container `step_size`; several blocks on the same FMU file →
  instances.
- **Step-by-step conversion**: from a Simulink model to a JSON description (or a Container Builder session), with
  a worked example (the three-rate assembly of the study).
- **Behaviour differences and how to handle them** (from the report of Step 4): initialization, start values,
  rates and exchange delays, ordering / feedthrough, computation time and `mt`.
- **Validation checklist**: how to check that the container reproduces the Simulink results (compare logged
  signals, optionally with the probe FMU).

## Steps

### Step 1 – Probe FMU

`tools/probe_fmu/` per the specification: `probe.c`, `make_probe.py`, the three generated FMUs, `README.md`.
Checks: the three FMUs are compiled with `OperationCompileSources` on the host, pass the checker of the toolbox, and
a simulation with fmpy (`tests/_helpers/simulation.py`) produces a trace with the expected calls and values.
Unit tests `tests/integration/test_probe_fmu.py` (compile, simulate, trace content, `strict_step`,
`compute_time`).

Commit message: `Add the probe FMU tracing the FMI calls of its importer`

### Step 2 – Scenarios on the container side

JSON descriptions and `run_container.py` per *Study scenarios > Container side*; integration test running S1 (fast
check of the script).

Commit message: `Add the comparison scenarios built as FMU containers`

### Step 3 – Scenarios on the Simulink side (user)

`tools/probe_fmu/scenarios/README.md` per *Study scenarios > Simulink side*, and the MATLAB functions of
`tools/probe_fmu/scenarios/simulink/` building and running the models (decision 15). The user runs them on
MATLAB R2024b and shares the traces and logs; they are stored next to the container ones.

Commit message: `Add the traces of the comparison scenarios run in Simulink`

### Step 4 – Comparison script and report

`tools/compare_traces.py`: aligns the traces of both importers per instance (call sequence, values before/after
initialization, `doStep` times and `h`, producer → consumer delay, wall time). Integration tests freezing the
container traces of S1–S5 (wall clock excluded). Report of the differences in `docs/local`, including the
answers to the `UNVERIFIED` points of `docs/local/simulink_export.md` (referenced from that plan), and the
conclusion on the propagation of the links during initialization (S3): open `docs/local/init_propagation.md` or
not, see *Follow-up: propagation of the links during initialization*.

Commit message: `Compare the traces of the FMU container and Simulink`

### Step 5 – User documentation

New page `docs/examples/simulink-to-container.md` (content above); `Examples` becomes a group in `mkdocs.yml`
(*Common Use Cases*: `examples/examples.md`, *From Simulink to an FMU Container*); link from
`docs/user-guide/fmucontainer/container.md`; `CHANGELOG.md` entry. The probe FMU is not documented for the users.

Commit message: `Document the migration of a Simulink FMU assembly to an FMU Container`
