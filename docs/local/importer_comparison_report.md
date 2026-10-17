# Report: FMU Container vs Simulink, seen by the probe FMU

**Date**: 17 October 2026 — **Plan**: `docs/local/importer_comparison.md` (Step 4) — **Branch**: `importer-comparison`

## TL;DR

| # | Topic | FMU Container | Simulink | Impact |
|---|---|---|---|---|
| 1 | **Initialization of linked FMUs** | Links **not propagated**: each FMU initializes with its inputs at their start values | Links **propagated**, block by block in sorted order (Enter → inputs from upstream → Exit → read outputs) | **Major**: FMUs computing initial state or parameters from inputs diverge for the whole run |
| 2 | **Unconnected inputs** | Keep their start value (FMU or `start` block) | Forced to **0**, at init and before every step | **Major**: silent value change; set `0` explicitly in the container to match |
| 3 | **Multi-rate** | **One step for all FMUs** (default: LCM of the fixed steps; e.g. 0.1 s for 10/20/50 ms FMUs) | Each block at **its own sample time**, outputs held between rates | **Major**: no exact container equivalent; fixed-step FMUs get a step size that is not theirs |
| 4 | **Slow → fast transfer (multi-tasking)** | No extra delay | Deterministic *Rate Transition* adds **one slow period** of delay | Medium: only with Simulink multi-tasking |
| 5 | **Delays / feedthrough** | Default (Jacobi): one step per feedthrough hop; `sequential` removes it along the FMU order | **Same as the container default** (outputs read before inputs are set; declared feedthrough not used) | Aligned, as long as `sequential` is not used |
| 6 | **Parallelism** | `mt`: FMUs of the same rate run in parallel (1.94 s → **0.90 s**) | Same-rate blocks share **one task** (2.03 s → 1.84 s) | Container faster; results unchanged |
| 7 | **Calls before init** | Only the given start values, after `SetupExperiment`; tolerance 1e-8 | **Every** parameter (defaults included), before `SetupExperiment`; tolerance 0.001 | Minor: only for FMUs sensitive to call order or tolerance |

**Bottom line:** points 1, 2 and 3 are what break a migration from Simulink. Point 1 justifies the
`init_propagation` plan (`docs/local/init_propagation.md`), point 2 has a simple workaround (explicit `start` = 0),
and point 3 is structural (single container step).

## Setup

- **Probe**: `tools/probe_fmu` (FMI 2.0 Co-Simulation, sources only), compiled on each platform with
  `fmutool -compile-sources`.
- **Container**: container runtime of the branch, simulated by fmpy 0.3.32 on macOS (`aarch64-darwin`),
  `tools/probe_fmu/scenarios/run_container.py`.
- **Simulink**: MATLAB R2024b Update 7, Windows 11, models built and run by
  `tools/probe_fmu/scenarios/simulink/` (fixed-step discrete solver, step 0.01 s, block reduction off, one root
  `Outport` per unconnected output). The probe version of this run measured `wall` per instance and quoted the trace
  file names; neither affects the results below.
- **Not done**: start values of the inputs set in the dialog of the FMU block (S2, S3) — the Simulink runs use the
  inputs as Simulink sets them (see 2).
- Detailed comparison: `python tools/compare_traces.py <results> -output report.md` (results not versioned,
  `tmp/importer_comparison/<scenario>/{container,simulink}/`).

## Findings

### 1. Call sequence before the initialization (S1, S2)

| | Container | Simulink |
|---|---|---|
| Instance name | `<container>.<instance>` (`S1.A.fmu`) | block path (`S1/A`) |
| Parameters | only the start values given in the assembly, **after** `fmi2SetupExperiment` | **every** parameter (defaults included), **before** `fmi2SetupExperiment` (with an empty `fmi2SetString` first) |
| `fmi2SetupExperiment` | tolerance 1e-8, stop time not defined | tolerance 0.001, stop time not defined |
| Start values flagged `<RESET>` | set again in Initialization Mode | — |

Both read every output after `fmi2ExitInitializationMode`, then step.

### 2. Inputs that are not connected (S1, S2)

- **Container**: never set (`auto_input: false`): the FMU keeps its start value, or the start value of the assembly
  (S2: `u_cont` = 2, `y_init` = 5).
- **Simulink**: set to **0** in Initialization Mode and before every step: the start value of the FMU is lost
  (S2: `u_cont` = 0, `y_init` = 3). Whether a start value entered in the dialog of the block replaces the 0 is not
  tested.

### 3. Initialization of linked FMUs (S3: `A.y_init → B.u_cont`, `B.y_cont → C.u_cont`)

- **Container**: the links are **not propagated** during the initialization: `B.y_init` = 1, `C.y_init` = 2 (start
  values of their inputs).
- **Simulink**: the links **are propagated**, block after block in the sorted order: for each block,
  `fmi2EnterInitializationMode` → inputs set from the outputs already read upstream → `fmi2ExitInitializationMode`
  → outputs read. `B.u_cont` receives `A.y_init` read after the initialization of `A`; `C.u_cont` receives `B.y_cont`
  read after the initialization of `B` (`B.y_init` = 1 + 3 = 4, `C.y_init` = 2 + 3 = 5, with `A.u_cont` = 0 per 2).
  No output is read in Initialization Mode: an algebraic loop at initialization would not be solved, only an
  acyclic chain.

### 4. Several rates (S4: probes at 0.01 s, 0.02 s, 0.05 s)

| | Container S4a (default step = LCM) | Container S4b (step 0.01 s) | Simulink S4s (single-tasking) | Simulink S4m (multi-tasking) |
|---|---|---|---|---|
| Steps of A / B / C (0.2 s) | 2 / 2 / 2 | 20 / 20 / 20 | 20 / 10 / 4 | 20 / 10 / 4 |
| `h` | 0.1 for all (≠ step size of every probe) | 0.01 for all (≠ 0.02 and 0.05) | step size of each probe | step size of each probe |
| Fast → slow (`A.y_time → B.u_cont`) | value at the step time, exchanged every 0.1 s | value at the step time | value at the step time | value at the step time |
| Slow → fast (`C.y_time → A.u_disc`) | exchanged every 0.1 s | value at the step time | held (zero-order hold) since the last step of C, no delay | **one period of C later** (deterministic *Rate Transition*) |

The container has one rate for every FMU: an FMU with a fixed step (`canHandleVariableCommunicationStepSize =
false`) receives a step size different from its own whatever the container step. Simulink steps each FMU at its
own sample time and holds the outputs between rates.

### 5. Feedthrough and ordering (S5: chain `A → B → C`)

- **Simulink** behaves exactly like the **default (Jacobi) container** (S5j): each block reads its outputs, sets its
  inputs and steps; one step of delay per link, `C` sees `A.y_time` two steps later. The direct dependency declared
  for `y_cont` (`ModelStructure`) does not remove the delay: the outputs are read before the inputs are set.
- **Container `sequential`** in the order of the chain (S5s) has no delay; in the reverse order (S5r) it is the same
  as Jacobi.

### 6. Computation time (S6: 3 probes × 100 steps × 5 ms)

| | Sequential | Parallel |
|---|---|---|
| Container | 1.94 s (default) | **0.90 s** (`mt`) |
| Simulink | 2.03 s (single-tasking) | 1.84 s (multi-tasking) |

Simulink runs the blocks of one rate in one task: multi-tasking gives no parallelism for FMUs of the same rate.

### 7. Simulink API (answers to the `UNVERIFIED` points of `docs/local/simulink_export.md`)

| Point | Result on R2024b |
|---|---|
| Library path of the FMU block | `simulink_extras/FMU Import/FMU` |
| `FMUName` | file name only, its folder on the MATLAB path (a path is refused) |
| CS / ME mode | Co-Simulation for a CS-only FMU |
| Order of the `Flat` ports | order of `modelDescription.xml` (checked on the Real and Integer links of S3–S5) |
| Parameter values | `set_param(block, '<name>', value)`: MATLAB expression for a Real, raw text for a String (a quoted value keeps its quotes), `'on'`/`'off'` for a Boolean |
| Input start values | no programmatic name found; unconnected inputs are set to 0 |
| FMU blocks without destination | removed by the block reduction (nothing simulated) |
| Rate transitions | multi-tasking needs *Rate Transition* blocks; deterministic transfer needs rates that are integer multiples |

## Consequences for a migration from Simulink to an FMU Container

1. **Initialization**: a Simulink assembly whose FMUs compute their initial state from their inputs initializes
   differently in a container (finding 3). See *Follow-up* below.
2. **Rates**: a Simulink assembly of FMUs with different sample times has no exact container equivalent: every FMU
   gets the container step (finding 4). The closest container uses the step of the fastest FMU (S4b) for FMUs that
   accept another step size.
3. **Delays**: the default container reproduces the delays of Simulink (finding 5); `sequential` removes them along
   the order of the FMUs, which changes the results.
4. **Unconnected inputs**: Simulink feeds them with 0, the container keeps their start values (finding 2): give
   them an explicit start value in the container description to reproduce Simulink.
5. **Performance**: `mt` parallelizes FMUs of the same rate, which Simulink does not (finding 6).

## Follow-up: propagation of the links during the initialization

Simulink propagates the links during the initialization (finding 3). Per the decision rule of the plan, a dedicated
plan `docs/local/init_propagation.md` is to be opened (option and default, order, algebraic loops, FMI 2.0 / 3.0,
ME FMUs). Simulink's rule — initialize the FMUs one after the other in the order of the dependencies, each with the
outputs read after the initialization of the upstream FMUs — is a candidate for the container.

## Still open

- Start value of an input entered in the dialog of the FMU block (S2, S3).
- Simulink run with the corrected probe (shared `wall` origin) to order the calls of several instances in time.
