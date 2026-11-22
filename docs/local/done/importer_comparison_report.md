# Report: FMU Container vs Simulink, seen by the probe FMU

**Date**: 18 October 2026 — **Plan**: `docs/local/done/importer_comparison.md` (Step 4) — **Branch**:
`feature/container-substep`

## TL;DR

| # | Topic | FMU Container | Simulink | Impact |
|---|---|---|---|---|
| 1 | **Initialization of linked FMUs** | Links **propagated**, FMU after FMU in the order of the links (inputs from upstream → Exit → read outputs); loops cut | Links **propagated**, block by block in sorted order (Enter → inputs from upstream → Exit → read outputs) | **Aligned**: identical traces on a chain of three FMUs (once the unconnected inputs match, see 2) |
| 2 | **Unconnected inputs** | Keep their start value (FMU or `start` block) | Forced to **0**, at init and before every step | **Major**: silent value change; set `0` explicitly in the container to match |
| 3 | **Multi-rate** | One step per container: **one sub-container per rate** (parent at the fastest rate) gives every FMU its own step size, inputs of the beginning of each step, outputs held | Each block at **its own sample time**, outputs held between rates | **Aligned** with one sub-container per rate: identical inputs at every step (single-tasking) |
| 4 | **Slow → fast transfer (multi-tasking)** | No extra delay | Deterministic *Rate Transition* adds **one slow period** of delay | Medium: only with Simulink multi-tasking |
| 5 | **Delays / feedthrough** | Default (Jacobi): one step per feedthrough hop; `sequential` removes it along the FMU order | **Same as the container default** (outputs read before inputs are set; declared feedthrough not used) | **Aligned** (identical traces), as long as `sequential` is not used |
| 6 | **Parallelism** | `mt`: FMUs of the same rate run in parallel (1.96 s → **0.92 s**) | Same-rate blocks share **one task** (1.89 s → 1.84 s) | Container faster; results unchanged |
| 7 | **Calls before init** | Only the given start values, after `SetupExperiment`; tolerance 1e-8 | **Every** parameter (defaults included), before `SetupExperiment`; tolerance 0.001 | Minor: only for FMUs sensitive to call order or tolerance |

**Bottom line:** the initialization (1), the rates (3, one sub-container per rate) and the delays (5) are aligned.
What still separates the two importers is the treatment of the unconnected inputs (2, simple workaround: explicit
`start` = 0) and the delay of the Simulink multi-tasking (4).

## Setup

- **Probe**: `tools/probe_fmu` (FMI 2.0 Co-Simulation, sources only), compiled on each platform with
  `fmutool -compile-sources`; the trace gives every FMI call with a clock shared by the instances of a process.
- **Container**: runtime of the branch (links propagated during the initialization,
  `docs/local/done/init_propagation.md`), simulated by fmpy 0.3.32 on macOS (`aarch64-darwin`),
  `tools/probe_fmu/scenarios/run_container.py`.
- **Simulink**: MATLAB R2024b Update 7, Windows 11, models built and run by
  `tools/probe_fmu/scenarios/simulink/` (fixed-step discrete solver, step 0.01 s, block reduction off, one root
  `Outport` per unconnected output).
- **Reproducibility**: the container traces of the scenarios are frozen in `tests/data/probe` and checked by the
  test suite, on macOS and in the Windows CI (green). The values are the same on both platforms; only the last
  digits of the times and step sizes differ (MSVC compiles the runtime with `/fp:fast`), within a relative 1e-9.
- Detailed comparison: `python tools/compare_traces.py <results> -output report.md` (results not versioned,
  `<results>/<scenario>/{container,simulink}/`).

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
  (S2: `u_cont` = 0, `y_init` = 3).

### 3. Initialization of linked FMUs (S3: `A.y_init → B.u_cont`, `B.y_cont → C.u_cont`)

- **Both propagate the links.** Container: `A / B / C.y_init` = 5 / 6 / 7; Simulink: 3 / 4 / 5. The offset comes only
  from the unconnected input `A.u_cont` (finding 2: 2 in the container, 0 in Simulink): with `A.u_cont` = 0 in the
  container, the traces of A, B and C are **identical** to Simulink (snapshots and inputs of every step).
- **Simulink** sets the parameters of the three blocks together, then initializes them **one after the other** in
  the sorted order (measured with the shared clock): A: `fmi2EnterInitializationMode` → inputs →
  `fmi2ExitInitializationMode` → outputs read, then B, then C. No output is read in Initialization Mode: a loop of
  links at the initialization is not solved.
- **The container** follows the same rule when it leaves its Initialization Mode (all its FMUs entered it
  together): in the order of the links, each FMU gets its linked inputs, leaves its Initialization Mode, then its
  outputs are read. A loop of links is cut before its first FMU (warning at the build). Reading the outputs during
  the Initialization Mode was tried first: FMUs generated by Simulink return 0 before they leave it.

### 4. Several rates (S4: probes at 0.01 s, 0.02 s, 0.05 s)

| | Container, one container (default step = LCM 0.1 s) | Container, one container (step 0.01 s) | Container, one sub-container per rate (parent 0.01 s) | Simulink S4s (single-tasking) | Simulink S4m (multi-tasking) |
|---|---|---|---|---|---|
| Steps of A / B / C (0.2 s) | 2 / 2 / 2 | 20 / 20 / 20 | 20 / 10 / 4 | 20 / 10 / 4 | 20 / 10 / 4 |
| `h` | 0.1 for all | 0.01 for all | step size of each probe | step size of each probe | step size of each probe |
| Fast → slow (`B.u_cont` = `A.y_time` at t = 0.02, 0.04) | exchanged every 0.1 s | 0.02, 0.04 | 0.02, 0.04 | 0.02, 0.04 | 0.02, 0.04 |
| Slow → fast (`A.u_disc` = `C.y_time`) | exchanged every 0.1 s | value at the step time | held since the last step of C | held since the last step of C | **one period of C later** |

- A single container steps every FMU with the step of the container: an FMU with a fixed step
  (`canHandleVariableCommunicationStepSize = false`) receives a step size different from its own.
- **One sub-container per rate**, the parent at the fastest rate (scenario `S4c`), gives the **same inputs at every
  step as Simulink single-tasking** for the three FMUs: every FMU gets its own step size, a sub-container slower than
  its parent uses the inputs of the beginning of each of its steps and holds its outputs until the end of the step
  (`docs/local/done/container_substep.md`). With the parent at the slowest rate (0.05 s, its default, scenario `S4d`),
  the fast FMUs exchange their values only every 0.05 s. The same rule holds for any sub-container slower than its
  parent: in the test suite, a sub-container of 0.5 s in a parent of 0.01 s shows at t = 1.0 the value computed
  from its input at t = 0.5 (Windows CI).

### 5. Feedthrough and ordering (S5: chain `A → B → C`)

- **Simulink** gives **identical traces** to the **default (Jacobi) container** (S5j) and to the container
  `sequential` in the reverse order (S5r): each FMU reads its outputs, sets its inputs and steps; one step of delay
  per link, `C` sees `A.y_time` two steps later. The direct dependency declared for `y_cont` (`ModelStructure`)
  does not remove the delay: the outputs are read before the inputs are set.
- **Container `sequential`** in the order of the chain (S5s) has no delay, unlike Simulink.

### 6. Computation time (S6: 3 probes × 100 steps × 5 ms, same rate)

| | Sequential | Parallel |
|---|---|---|
| Container | 1.96 s (default) | **0.92 s** (`mt`) |
| Simulink | 1.89 s (single-tasking) | 1.84 s (multi-tasking) |

The traces are identical. Simulink runs the blocks of one rate in one task: multi-tasking gives no parallelism for
FMUs of the same rate.

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

1. **Unconnected inputs**: Simulink feeds them with 0, the container keeps their start values (finding 2): give
   them an explicit start value of 0 in the container description to reproduce Simulink, initialization included
   (finding 3).
2. **Rates**: group the FMUs of each Simulink sample time in a sub-container with that step, the parent at the
   fastest sample time (finding 4): the exchanges are those of Simulink single-tasking.
3. **Delays**: keep the default scheduling of the container (finding 5); `sequential` removes the delays along the
   order of the FMUs, which changes the results.
4. **Performance**: `mt` parallelizes FMUs of the same rate, which Simulink does not (finding 6).

User documentation: `docs/examples/simulink-to-container.md`.

## Still open

- Start value of an input entered in the dialog of the FMU block (S2, S3): not tested.
