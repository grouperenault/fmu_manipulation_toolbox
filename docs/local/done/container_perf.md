# Plan: performance of the container runtime — grouped FMI calls and targeted ME coupling

**Created**: 17 October 2026 — **Status**: done (17 October 2026) on `feature/optimize-fmi-calls`, point 1
abandoned (D10) — **Roadmap**: not listed

A review of the runtime (17 October 2026, code reading, no measurement) found two costs in the path of each
internal step:

1. **One FMI call per port.** The input and output exchanges call `fmi*Set*` / `fmi*Get*` with one value reference
   per call: an FMU with 300 inputs and 200 outputs costs about 500 FMI calls per internal step, where one call per
   type would do. Many FMUs (e.g. Simulink ones) have a fixed cost per call, and the Link Assistant targets FMUs
   with hundreds of ports.
2. **The ME solver refreshes every coupling at each evaluation.** `solver_propagate()` sets every continuous input
   and gets every continuous output of every ME FMU, 2 times per Euler step and 5 times per RK4 step, although only
   the ME → ME couplings change during the step (the inputs fed by Co-Simulation FMUs are constant).

---

## 1. Current state

| Topic | Where | Notes |
|---|---|---|
| Exchange of the inputs / outputs of an FMU | `container/fmu.c`: `SET_INPUT`, `GET_OUTPUT`, `fmu_set_inputs()`, `fmu_get_outputs()` | One `fmuSet<Type>` / `fmuGet<Type>` per translation (`nvr = 1`, `nvalues` = dimension) |
| Continuous exchanges (ME, Continuous Time Mode) | `container/fmu.c`: `fmu_set_continuous_inputs()`, `fmu_get_continuous_outputs()` | Same macros, `real64` and `real32` only; `fmu_get_continuous_outputs()` runs the conversions of the FMU |
| Translations | `container/fmu.h`: `fmu_io_t` (`<type>.in` / `.out`: `nb`, `translations[]` of `{vr, fmu_vr, dimension}`) | Read from `container.txt`; FMI-2 array aggregates already expanded into scalar translations |
| Typed calls | `container/fmu.c`: `GETTER_*`, `SETTER_*` | Already take arrays (`vr[]`, `nvr`, `value[]`, `nvalues`) |
| Coupling sweep | `container/solver.c`: `solver_propagate()`, called by `solver_eval_f()`, after each integration step and at the end of `solver_do_step()` | Gauss-Seidel in registration order, all continuous inputs and outputs of every ME FMU |
| Conversions | `container/convert.c`: `convert_proceed()` | Run by the FMU producing the value, after its outputs are read |
| Test FMUs with sources | `tests/data/compile` (Reference FMUs v0.0.41, `BouncingBall.fmu`) | No cross-platform ME FMU with inputs in the test data |

---

## 2. Goals

1. The exchanges of an embedded FMU make one FMI call per type and per direction, instead of one per port.
2. During the ME integration, only the ME → ME couplings are refreshed; nothing is exchanged when there is none.
3. The simulation results are identical (same values, bit for bit) before and after.
4. The gain is measured on reproducible cases.

---

## 3. Decisions

Taken on 17 October 2026:

- **D1 — Scope of point 1**: the exchanges of the embedded FMUs at each step: `fmu_set_inputs()`,
  `fmu_get_outputs()` and their continuous variants. Not concerned: the clocked exchanges
  (`fmu_set_clocked_inputs()`, `fmu_get_clocked_outputs()`), the getters and setters of the container called by the
  importer, the strings and binaries (kept one call per port).
- **D2 — Method of point 1**: in the runtime, without change of the builder nor of `container.txt`: when
  `container.txt` is read, the runtime builds, for each FMU, type and direction, the array of the FMU value
  references and a buffer of values; each exchange gathers (set) or scatters (get) the local values and makes a
  single call.
- **D3 — ME → ME couplings**: deduced by the runtime at configuration: a continuous input of an ME FMU is an ME → ME
  coupling when its local slot is written by an output of an ME FMU, or by a conversion whose source is written by
  an output of an ME FMU. No change of format; the sweep is skipped when there is no such coupling.
- **D4 — Measure first**: the first step is a benchmark script (not a test) on reproducible cases, run before and
  after each change.
- **D5 — Test FMU for the ME couplings**: `Feedthrough.fmu` of the Reference FMUs, same release as `BouncingBall.fmu`
  (v0.0.41, 2-Clause BSD), with its sources, added to `tests/data/compile`. Amended at step 1: the FMI-3.0 one ships
  binaries for every platform (`aarch64-darwin` included) and is used as is: ME → ME couplings tested on every
  platform; the FMI-2.0 one (macOS binary for `x86_64` only) is compiled for the host by `OperationCompileSources`
  (`needs_compiler`), for the FMI-2.0 calls of point 1.

---

## 4. Design

### 4.1 Grouped exchanges (point 1)

New per-FMU tables, built at the end of `read_conf_fmu_io()` (or by a dedicated `fmu_build_exchanges()` called by
`container_configure()`), for each numeric type and each direction (`in`, `out`):

```c
typedef struct {
    unsigned long   nb_vr;          /* number of FMU value references (one per translation) */
    unsigned long   nb_values;      /* sum of the dimensions */
    fmu_vr_t        *fmu_vr;        /* [nb_vr] */
    unsigned long   *local;         /* [nb_vr] offset of each translation in the local storage */
    unsigned long   *dimension;     /* [nb_vr] */
    <type>          *buffer;        /* [nb_values] contiguous values of one call */
} fmu_exchange_<type>_t;
```

- `fmu_set_inputs()`: for each type with `nb_vr > 0`, copy `container-><type>[local + k]` into `buffer`, then one
  `fmuSet<Type>(fmu, fmu_vr, nb_vr, buffer, nb_values)`.
- `fmu_get_outputs()`: one `fmuGet<Type>(fmu, fmu_vr, nb_vr, buffer, nb_values)`, then copy `buffer` into the local
  slots; the conversions run afterwards as today.
- Continuous variants: the same tables of `real64` and `real32`.
- FMI 2.0: `nvalues` is ignored by the FMI 2.0 API and every translation has a dimension of 1 (the array aggregates
  are expanded by the builder): `nb_vr == nb_values`.
- Errors: a grouped call that fails does not tell which variable is wrong. On failure only, the runtime replays the
  exchange port by port to log the failing variable (as today), then returns the error. *(To confirm, see 6.1.)*
- The buffers are owned by the FMU: the exchanges of two FMUs never share one (multi-threaded mode safe).
- Strings, binaries and the clocked exchanges keep their current code.

### 4.2 Targeted ME coupling (point 2)

At the end of `solver_configure()` (FMU pointers resolved):

- for each ME FMU, select the continuous input translations whose local slot is **produced by an ME FMU**: written by
  a continuous output translation of an ME FMU, or the destination of a conversion of an ME FMU (the conversions are
  listed per producing FMU);
- build for each ME FMU a grouped table (4.1) of these **coupled inputs** only, and a flag **feeds an ME FMU** (one of
  its continuous outputs is read by a coupled input);
- `solver_propagate()` becomes: for each ME FMU in registration order, set its coupled inputs (if any), then get its
  continuous outputs and run its conversions if it feeds an ME FMU; nothing at all when no coupling exists.

The other continuous inputs of the ME FMUs are set once per step, before the integration, by the step functions
(unchanged), and the outputs of every ME FMU are read after the integration (unchanged): the values seen by every
FMU are the same as today, in the same order.

Implementation (step 3): each entry of a conversion table knows the real type of its destination (`to_real`: 64, 32
or 0, from the suffix of the name of the conversion, `convert_destination_real()`), so that a coupling through a
conversion (e.g. a `Float64` output to a `Float32` input) is found; the couplings are computed again at each
`solver_configure()` (each `ExitInitializationMode`, after a reset too); a debug message states, for each ME FMU, its
number of coupled inputs and whether it feeds an ME FMU.

### 4.3 Benchmark

`tools/bench_container.py` (not shipped, not run by the tests, as `tools/screenshots.py`): builds the containers of
the cases below in a temporary directory, simulates each one 5 times with fmpy (internal step 1 ms, communication
step 10 ms, stop time per case for about 1 s of computation), and prints the time of the loop of `doStep` only (the
extraction and the instantiation of the container, which dominate a whole simulation, are not timed), the number of
FMI exchange calls of the CS exchanges of one internal step (computed from the translations of `container.txt`: the
`fmiCallLogger` of fmpy only sees the calls to the container), and a digest of the outputs read at each communication
point, to check that they do not change.

| Case | FMUs | What it exercises |
|---|---|---|
| A — every type, CS | `VanDerPol.fmu` → 20 chained instances of `Feedthrough.fmu` (CS), 13 ports of 12 types in and out each, parallel, sequential and multi-threaded | point 1 (one port per type: small gain) |
| B — ME uncoupled | 4 instances of `VanDerPol.fmu` reduced to Model-Exchange | point 2: sweep skipped |
| C — ME coupled | `VanDerPol.fmu` (ME) → 4 chained instances of `Feedthrough.fmu` (ME), Euler and RK4 | point 2: targeted sweep |
| D — mixed | `VanDerPol.fmu` (CS) feeding 4 instances of `Feedthrough.fmu` (ME) | point 2: CS inputs set once per step |
| E — same type, CS | 20 chained instances of `containers/mt/1.fmu` (5 `Float64` in, 5 out) | point 1: calls divided by 5 |

---

## 5. Steps

Each step ends with the tests of the project passing, and a prepared commit message.

### Step 1 — Test FMU and benchmark

- `tests/data/compile/{2.0,3.0}/Feedthrough.fmu` from the Reference FMUs v0.0.41, unmodified; `README.md` of the
  directory completed.
- `tools/bench_container.py` (cases A to D); a first run gives the reference timings, recorded in this plan
  (section 7), and the digests of the results.
- Integration tests of the results of cases B, C and D (compiled `Feedthrough.fmu`, `needs_compiler`), against REF
  files made with the current runtime: they must not change in the next steps.

Commit message: `Benchmark of the container runtime and Feedthrough test FMU`

### Step 2 — Grouped exchanges (point 1) — abandoned (D10)

- Section 4.1: tables built at configuration, `fmu_set_inputs()`, `fmu_get_outputs()` and their continuous variants
  rewritten, port-by-port replay on error.
- Unit test of the C side through a container: an FMU with ports of several types and an array, results identical;
  an error names the failing variable.
- Benchmark run: timings recorded in section 7.

Commit message: `Container runtime: one FMI call per type for the exchanges of an FMU`

### Step 3 — Targeted ME coupling (point 2)

- Section 4.2: coupled inputs deduced by `solver_configure()`, `solver_propagate()` restricted to them.
- The REF results of step 1 are unchanged; a debug log of the container states, at configuration, the ME → ME
  couplings found (tested).
- Benchmark run: timings recorded in section 7.

Commit message: `Container runtime: refresh only the ME to ME couplings during the integration`

### Step 4 — Documentation

- `CHANGELOG.md` (section *Upstream*, *FMU Container*): 🔵 **CHANGED** ME integration, with the measured gains
  (as a reduction of the time, and as a speed-up factor).
- `docs/user-guide/fmucontainer/container.md`: one sentence in *Model-Exchange support* (only the ME → ME
  couplings are exchanged during the integration), no figures (decided on 17 October 2026).
- `docs/help/contributing.md`: section *Benchmark of the container runtime* (decided on 17 October 2026).
- Move this plan to `docs/local/done`.

Commit message: `Document the performance work on the container runtime`

---

## 6. Decisions on the open points

Taken on 17 October 2026:

- **D6 — Error of a grouped call**: on failure only, the exchange is replayed port by port to log the failing
  variable, then the error is returned (4.1).
- **D7 — Benchmark**: a case with a few hundred ports is generated from N chained instances of `Feedthrough.fmu`
  (and of the `mt` FMUs); 5 runs per case, step size 1 ms, stop time chosen for about 1 s of computation per case.
- **D8 — Acceptance**: the results are identical bit for bit to the REF files of step 1. Amended on 17 October 2026:
  identical bit for bit on one machine (A/B digests of the benchmark); the tests compare with the REF files (made on
  macOS) within a tolerance of `1e-12` (relative and absolute), since the embedded FMUs run other binaries on another
  platform (Linux CI: `x1` of `VanDerPol.fmu` differs by one unit of the last digit).
- **D9 — Workflow**: steps 1 to 3 on `feature/optimize-fmi-calls`, in the main checkout, one commit per step without
  pause; step 4 (documentation) on request, once the gains are measured.
- **D10 — Point 1 abandoned** (17 October 2026, after step 2): the grouped exchanges were implemented (4.1, with a
  direct call for a list of one port) and gave the same results bit for bit, but no measurable gain: an FMI call to
  the test FMUs costs a few tens of nanoseconds, so the copies into the buffers balance the saved calls (A/B
  measurements below). The gain would only show with FMUs whose calls are costly (remoting, Windows only; some
  tool-generated FMUs), which cannot be measured here. The C changes are not kept; the benchmark and the reference
  tests of step 1 stay.

## 7. Measurements

`python tools/bench_container.py` on macOS (Apple silicon), time of the loop of `doStep` in seconds (min / mean of 5
runs); *calls*: FMI exchange calls of the CS exchanges of one internal step, port by port / grouped by type. The
measurements of separate sessions differ by 5 to 10 %: the changes are compared by an A/B run in one session (the old
and the new `container.dylib` alternately, 3 rounds of 5 runs, best time).

| Case | Step 1 (reference) | Calls |
|---|---|---|
| A-parallel | 0.777 / 0.809 | 507 / 468 |
| A-sequential | 0.920 / 0.958 | 507 / 468 |
| A-mt | 1.287 / 1.295 | 507 / 468 |
| B-uncoupled | 0.750 / 0.765 | 0 / 0 |
| C-euler | 0.719 / 0.739 | 16 / 15 |
| C-rk4 | 0.870 / 0.884 | 16 / 15 |
| D-mixed | 0.728 / 0.751 | 10 / 9 |
| E-same-type | 0.609 / 0.625 | 190 / 38 |

In the tables below, *gain* is the reduction of the time of the loop: (before − after) / before; a gain of 33 %
means 1.5 times faster.

Step 2 (grouped exchanges, abandoned, see D10), A/B against step 1, best time in seconds and gain:

| Case | Step 1 | Grouped | Gain | Grouped + direct call for one port | Gain |
|---|---|---|---|---|---|
| A-parallel | 0.821 | 0.900 | -9.6 % | 0.849 | -3.7 % |
| A-sequential | 0.907 | 0.994 | -9.6 % | 0.928 | -2.4 % |
| A-mt | 1.175 | 1.210 | -3.0 % | 1.202 | -0.6 % |
| B-uncoupled | 0.751 | 0.761 | -1.3 % | 0.751 | -0.4 % |
| C-euler | 0.728 | 0.763 | -4.8 % | 0.722 | +0.7 % |
| C-rk4 | 0.857 | 0.906 | -5.7 % | 0.866 | -0.1 % |
| D-mixed | 0.718 | 0.755 | -5.2 % | 0.723 | -0.8 % |
| E-same-type | 0.611 | 0.613 | -0.3 % | 0.616 | +0.8 % |

Step 3 (targeted ME coupling), A/B against step 1, best time in seconds and gain; same digests (results identical):

| Case | Step 1 | Step 3 | Gain |
|---|---|---|---|
| A-parallel | 0.821 | 0.841 | -2.4 % (noise: CS only) |
| A-sequential | 0.909 | 0.912 | -0.3 % (noise: CS only) |
| A-mt | 1.212 | 1.202 | +0.8 % (noise: CS only) |
| B-uncoupled | 0.749 | 0.710 | +5.2 % |
| C-euler | 0.720 | 0.706 | +1.9 % |
| C-rk4 | 0.859 | 0.849 | +1.2 % |
| D-mixed | 0.723 | 0.484 | **+33.1 %** (1.49 times faster) |
| E-same-type | 0.608 | 0.616 | -1.3 % (noise: CS only) |

The gain comes where the sweep exchanged values that do not change during the step: ME FMUs fed by Co-Simulation FMUs
(case D), or without coupling (case B). A chain of ME FMUs coupled to each other (case C) keeps its sweep.

## 8. Found during the work (not in the scope)

- The builder handles an FMI-3.0 `Enumeration` as an `Int32` (`EmbeddedFMU.port_attrs`), where FMI 3.0 accesses it as
  an `Int64`: `fmi3GetInt32` on an enumeration fails (e.g. `Feedthrough.fmu`, `Enumeration_output`).
- The continuous exchanges of the ME FMUs (`fmu_set_continuous_inputs`) select the inputs by type (`real64`,
  `real32`), not by variability: a discrete `Float64` input of an ME FMU fed by a link is set in Continuous Time
  Mode, which FMI forbids (e.g. `Feedthrough.fmu`, `Float64_discrete_input`: the step fails).
