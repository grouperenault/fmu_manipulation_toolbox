# Plan: conformity, performance and maintainability of the container runtime and the Python package

**Created**: 14 November 2026 — **Status**: draft, decisions pending — **Branch**: one branch per phase, from
`integration` — **Roadmap**: not listed

This plan comes from a review of the whole toolbox (14 November 2026, code reading, measurements of
`docs/local/done/container_perf.md`). It gathers the actions retained from that review, in the order in which they
are done. The discrete real inputs of the Model-Exchange FMUs set in Continuous Time Mode (found in
`container_perf.md`, §8) are **out of the scope** of this plan: they will have a plan of their own.

| Phase | Subject | Kind |
|---|---|---|
| 1 | `<InitialUnknowns>` / `<InitialUnknown>` of the container list the right outputs | FMI conformity |
| 2 | One Model-Exchange part for the three step loops of the runtime | maintainability |
| 3 | The getters of the container read the outputs of the embedded FMUs from the local variables | performance |
| 4 | `ruff` and `mypy` on the Python package | maintainability |
| 5 | Hybrid multi-thread mode | performance |
| 6 | Datalog: output buffer and decimation | performance |

Each phase ends with its tests, its documentation and a commit; the user documentation and `CHANGELOG.md` are
updated at the end of each phase that changes a behaviour (1, 3, 5, 6).

---

## 1. Current state

| Topic | Where | Notes |
|---|---|---|
| `<ModelStructure>` of the container | `container/builder.py`: `make_fmu_xml()` (the end) | FMI 2.0: `<Outputs>` and `<InitialUnknowns>` list **every** output, by index. FMI 3.0: `<Output>` and `<InitialUnknown>` list every output, by value reference |
| `initial` of an exposed output | `container/embedded.py`: `EmbeddedFMUPort.xml()` | Copied from the variable of the embedded FMU (`"initial": self.initial`), with its start value |
| Semantic checker | `checker.py`: `OperationSemanticCheck.check_model_structure()` | Checks `<Outputs>` / `<Output>` against the outputs; does not check `<InitialUnknowns>` / `<InitialUnknown>` |
| Step loops | `container/container.c`: `container_do_one_step_sequential()`, `_parallel()`, `_parallel_mt()` | The Model-Exchange part (continuous inputs, `solver_do_step()`, outputs) is the same ~30 lines in the three functions; `read_flags()` selects the function (`container->do_step`) |
| Getters of the container | `container/fmi2.c`: `FMI_GETTER`; `container/fmi3.c`: `FMI_GETTER`, `fmi3GetBinary`, `fmi3GetClock` | A port linked to an embedded FMU (`links[0].fmu_id >= 0`) and not set by the importer: `cache_sync_fmu_now()`, then **one FMI call per value reference** into the FMU. A port linked to a local variable (`fmu_id < 0`): read from `locals[]` |
| Exposed outputs in `container.txt` | `container/builder.py`: `make_fmu_txt()`; `docs/developer/container-txt-format.md`, section 6 | `<VR> <DIM> 1 <FMU_INDEX> <FMU_VR>`: the port is linked to the FMU variable. An output that also feeds a link has a local variable too (per-FMU Outputs section), read by `fmu_get_outputs()` after each step |
| `fmusplit` | `split.py`: `parse_txt_file()` | Tells an exposed input from an exposed output by the causality of `<FMU_VR>` in the `modelDescription.xml` of the embedded FMU |
| Lint and types | `pyproject.toml` | No `[tool.ruff]`, no `[tool.mypy]`, no lint job in `.github/workflows/ci.yml`. The C code has `-Wall -Wextra` and `-Werror` (`FMUTOOL_WARNINGS_AS_ERRORS`). 80 % of the public functions are annotated |
| Multi-thread mode | `container/container.c`: `container_start_threads()`, `container_do_one_step_parallel_mt()`; `container/fmu.c`: `fmu_do_step_thread()`; `container/thread.c` | One thread per Co-Simulation FMU, started at configuration; two barriers per internal step (`barrier_start`, `barrier_end`); the worker only runs `fmuDoStep()`, the exchanges run in the main thread |
| Profiling | `container/profile.c` | `GetTickCount()` / `CLOCK_REALTIME` in **milliseconds**; output `container.<fmu>.rt_ratio` |
| Datalog | `container/datalog.c`: `datalog_log()`, `datalog_configure()` | `fopen(..., "wt")` with the default buffer of the C library; one `fprintf()` per value; the values are read with `fmi2Get*` / `fmi3Get*` of the container (hence the FMI calls of the getters, see above); one row per internal step and per event iteration |
| Benchmark | `tools/bench_container.py`, `tests/integration/test_container_perf.py` | Cases A to E, A/B method and digests of the results (`container_perf.md`, §7) |

Measurements of `container_perf.md` (macOS, Apple silicon, time of the `doStep` loop, seconds): `A-sequential`
0.92, `A-parallel` 0.78, `A-mt` 1.29. The multi-thread mode is the slowest on FMUs whose `doStep` costs a few
microseconds.

---

## 2. Goals

1. The `modelDescription.xml` of a container passes the semantic checker for its initial unknowns, and the checker
   catches the error on any FMU.
2. A change of the Model-Exchange coupling is made once, for the three modes.
3. A `fmi*Get*` of the importer on an output of the container costs a memory read, whatever the number of outputs,
   and the datalog no longer calls the embedded FMUs.
4. `ruff` and `mypy` pass on the package, in the CI.
5. The multi-thread mode is never slower than the mono-thread mode, and the exchanges of a costly FMU (remoting,
   tool-generated FMUs) run in parallel.
6. The datalog costs less and can be decimated.

Non-goals: the discrete inputs of the ME FMUs (own plan); the performance of the ME solver (sub-step, RK4); the
grouping of the FMI calls (abandoned, `container_perf.md` D10).

---

## 3. Decisions

Taken on 14 November 2026 when writing the plan:

- **D1 — Order**: the phases are done in the order of the table above; phase 3 after phase 2 (the getters touch
  `fmu_get_outputs()`, which the step loops call); phase 6 after phase 3 (the datalog benefits from the getters).
- **D2 — Measure first** (as `container_perf.md` D4): phases 3, 5 and 6 start with an A/B run of
  `tools/bench_container.py`, before and after, same session; a phase without measurable gain is reverted (D10 of
  `container_perf.md` is the precedent).
- **D3 — Results**: the results of the reference containers (`REF-*.txt` of `tests/data/containers`,
  `tests/integration/test_container_perf.py`) and the digests of the benchmark do not change in phases 2, 3, 5 and 6.
- **D4 — One branch per phase**, from `integration`, merged before the next phase starts: `fix/initial-unknowns`,
  `refactor/step-loops`, `perf/getters-from-locals`, `chore/ruff-mypy`, `perf/mt-hybrid`, `perf/datalog`.

### Open points, to decide before the phase starts

| # | Phase | Question | Recommendation |
|---|---|---|---|
| Q1 | 1 | An exposed output with `initial="exact"` keeps its `initial` and `start` (today), or loses its `initial` (becomes `calculated`, listed as initial unknown)? | **Keep them**: the container only passes the variable through; the importer may rely on the start value |
| Q2 | 3 | The `fmi*Get*` of an output in Initialization Mode (before the first step): **A** read-through to the FMU, as today, locals served in Step Mode only; or **B** the outputs are fetched into the locals when the container enters and leaves its Initialization Mode, and always served from the locals | **A**: no new fetch, no stale value; the hot path (Step Mode) is the one that matters |
| Q3 | 3 | Format of `container.txt`: **A** version 10, every exposed output has a local variable (written by the builder, read back by `fmusplit`); or **B** the runtime allocates the locals itself when the container is loaded | **A**: the runtime cannot tell an exposed input from an exposed output (both are `<VR> <DIM> 1 <FMU_INDEX> <FMU_VR>`); B would need a causality in the file anyway |
| Q4 | 4 | Rule set and line length of `ruff` | `E, F, W, I, UP, B` with `line-length = 120` (the current code); `ruff format` **not** applied to the existing code (a whole-repository diff), lint only |
| Q5 | 4 | Scope of `mypy` | `fmu_manipulation_toolbox` without `gui/` and `assistant/` at first (`exclude`), `ignore_missing_imports` for `fmpy`; `gui/` and `assistant/` in a later phase |
| Q6 | 4 | The lint job of the CI blocks the merge, or only reports? | **Blocks**, once the baseline is at zero (step 4.2) |
| Q7 | 4 | `pre-commit` hooks in the repository? | **No** for now: the CI job is enough, a hook is a developer choice |
| Q8 | 5 | Threshold above which an FMU gets a thread, and where it is set | Default **50 µs** of mean `doStep` time over the first 20 internal steps, measured by the runtime; overridable at build time (`-mt-threshold <seconds>`, `container.txt` flags line, version 10 of Q3) |
| Q9 | 5 | Number of worker threads | `min(number of heavy FMUs, number of cores - 1)`, the main thread steps the light FMUs meanwhile; the current one-thread-per-FMU stays when the count is lower |
| Q10 | 5 | The exchanges (`fmu_set_inputs()`, `fmu_get_outputs()`) of a heavy FMU run in its worker | **Yes**: it is the only gain for the FMUs whose FMI calls are costly (remoting, D10 of `container_perf.md`); needs per-FMU scratch buffers for the strings and binaries (`container->strings_tmp`, `binaries_tmp` are shared today) |
| Q11 | 6 | Decimation: one row every N internal steps; are the event rows (`container_proceed_event()`) always written? | **Always written**: the datalog is a debugging tool, an event must not be missed; N applies to the rows of the regular steps |
| Q12 | 6 | Naming of the option | CLI `-datalog-every N`, JSON `"datalog_every": N`, API `make_fmu(..., datalog_every=N)`; written as a second line of `resources/datalog.txt` (`# Decimation` / `N`), optional for the reader |
| Q13 | 6 | Size of the output buffer | `setvbuf(file, NULL, _IOFBF, 1 << 20)` (1 MiB) |

---

## 4. Design

### 4.1 Phase 1 — Initial unknowns

FMI 2.0.5 §2.2.8 and FMI 3.0.2 §2.4.8: `<InitialUnknowns>` / `<InitialUnknown>` list the variables with
`causality="output"` and `initial="approx"` or `"calculated"` (default of an output: `calculated`), the
`calculatedParameter` variables, and the continuous states and their derivatives with `initial="approx"` or
`"calculated"`. An output with `initial="exact"` is **not** an initial unknown: it has a start value.

- `make_fmu_xml()`: the `<Outputs>` / `<Output>` section is unchanged; `<InitialUnknowns>` / `<InitialUnknown>` list
  the outputs whose `initial` attribute (of the generated element) is not `exact`. The container has no states and no
  calculated parameters; the profiling variables `container.<fmu>.rt_ratio` are `local` (no causality given to
  `EmbeddedFMUPort`), hence listed in neither section.
- `OperationSemanticCheck.check_model_structure()`: new rule, both versions: an output with `initial` in
  (`calculated`, `approx`) or absent must be listed as initial unknown; a listed variable must be an output (or a
  `calculatedParameter`, or a state or derivative) with such an `initial`; an output with `initial="exact"` must not
  be listed. The messages quote the section (`FMI-2 §2.2.8`, `FMI-3 §2.4.8`).
- Q1: an exposed output keeps the `initial` and `start` of the embedded variable.

### 4.2 Phase 2 — One Model-Exchange part

- `container.c`: `static fmu_status_t container_step_me(container_t *container)`: the continuous inputs of every ME
  FMU (`fmu_set_continuous_inputs()`), `solver_do_step()`, the outputs (`fmu_get_outputs()`), with the error
  messages of today. The three `container_do_one_step_*()` keep their Co-Simulation part and call it.
- No change of behaviour: the order (CS first, then ME) and the messages are kept; the comments on the discrete
  inputs are kept once, on `container_step_me()`.

### 4.3 Phase 3 — Getters from the local variables

- **Builder** (`make_fmu_txt()`, `layout.py`): every exposed output gets a local variable of its type (an output
  that already feeds a link reuses the local variable of the link). The port line of the output becomes
  `<VR> <DIM> 1 -1 <LOCAL_OFFSET>`; the output is added to the per-FMU Outputs section
  (`<LOCAL_OFFSET> <DIM> <FMU_VR>`) if it is not there yet. `CONTAINER_TXT_VERSION` 10 in `types.py` and
  `container.h` (Q3 A).
- **Runtime**: no change of the getters for Step Mode: the port is a local one (`fmu_id < 0`), served from
  `locals[]`, which `fmu_get_outputs()` fills after each step of the FMU. Q2 A: in Initialization Mode
  (`CONTAINER_STATE_INITIALIZATION_MODE`), a getter on a port whose local variable is fed by an FMU output reads
  through to the FMU, as today: the port keeps, besides its local link, the `<FMU_INDEX> <FMU_VR>` of its source
  (format: `<VR> <DIM> 2 -1 <LOCAL_OFFSET> <FMU_INDEX> <FMU_VR>`, the getters using the first link in Step Mode and
  the second in Initialization Mode). Verified: the local variables of every output are filled when the container
  leaves its Initialization Mode (`container_exit_fmus_initialization()` and `container_init_values()` call
  `fmu_get_outputs()` for each FMU, which now covers every exposed output) and after the reset of an FMU
  (`container_reset_fmu()`), so the first getter of Step Mode reads a value of the FMU.
- **Behaviour change**: a `fmi*Get*` of an output between two steps returns the value at the end of the last step
  (FMI 2.0 §4.2.4, FMI 3.0 §4.2: the outputs of a Co-Simulation FMU are those of the current communication point),
  no longer a value an FMU may compute lazily on `Get`. The traces of the probe FMU (`tests/data/probe/REF-*.csv`)
  lose the `Get` calls made by the getters of the container: regenerated and reviewed.
- **`fmusplit`** (`split.py`): version 10: an exposed output is a port linked to a local variable that an FMU
  writes (its Outputs section); the FMU and the value reference come from there (or from the second link).
- **Datalog**: unchanged in this phase; it benefits from the getters (no more FMI call per logged output).
- Pending step: "the outputs read by the getters are those of T" (`dostep-fmi-sequence.md`) is now true by
  construction.

### 4.4 Phase 4 — ruff and mypy

- `pyproject.toml`: `[tool.ruff]` (Q4), `[tool.ruff.lint]`, `[tool.mypy]` (Q5), a `lint` extra (`ruff`, `mypy`,
  and the stubs: `types-colorama`); `all` includes it.
- Baseline: `ruff check fmu_manipulation_toolbox tests tools` and `mypy fmu_manipulation_toolbox`, counted by rule
  and by file, kept in this plan (§7); the rules whose fixes are mechanical (`I`, `UP`, unused imports) are applied
  with `--fix`, the others by hand, file by file, without changing a behaviour; a rule that does not fit the code is
  ignored with a reason in `pyproject.toml`.
- CI: a `lint` job in `ci.yml` (Ubuntu, newest Python), before the test jobs, blocking (Q6).
- `CONTRIBUTING.md`: how to run them.

### 4.5 Phase 5 — Hybrid multi-thread mode

- **Prerequisite**: `profile.c` in nanoseconds (`clock_gettime(CLOCK_MONOTONIC)`, `QueryPerformanceCounter()`),
  used by the profiling output (unchanged values, better resolution) and by the measurement below.
- **Measurement**: with `mt`, the first `MT_WARMUP` (20) internal steps run in the mono-thread parallel mode, the
  time of each `fmuDoStep()` measured; then each CS FMU is **heavy** (mean above the threshold, Q8) or **light**.
- **Scheduling** of an internal step: the heavy FMUs are stepped by the workers (Q9), the light ones by the main
  thread meanwhile, then one synchronization. A worker runs `fmu_set_inputs()`, `fmuDoStep()`, `fmu_get_outputs()`
  of its FMU (Q10): the cache sets of an FMU are its own (`cache_fmu_t`), the local variables it writes are its own
  (its outputs and their conversions), the scratch buffers of the strings and binaries become per FMU. The importer
  cannot call the container during `fmi*DoStep`, so no concurrent `fmi*Set*`.
- **Synchronization**: one counter of running workers and a condition variable (or the Windows event), the main
  thread spinning a few microseconds before blocking; `thread_barrier_*` kept for the stop of the threads or
  removed if unused.
- **No heavy FMU**: the step runs as the mono-thread parallel mode; the threads are stopped (or never started: the
  threads are started after the warm-up).
- Flags line of `container.txt`: `<MT> <Profiling> <Sequential> <MT_THRESHOLD>` (version 10, Q8); `-mt-threshold`
  of the CLI, `mt_threshold` of the JSON and of the API.
- The mode is reported once (`LOGGER_WARNING` as today) with the list of the heavy FMUs.

### 4.6 Phase 6 — Datalog

- `datalog_configure()`: `setvbuf()` (Q13); the file is flushed at `container_terminate()` and freed at
  `container_free()` as today.
- Decimation (Q11, Q12): `datalog->every` (default 1), `datalog->countdown`; `datalog_log()` of the regular steps
  writes a row when the countdown reaches zero; the event rows and the first row (start time) are always written.
- `make_datalog()`: the second line; `datalog_configure()` reads it if present.

---

## 5. Steps

### Phase 1 — Initial unknowns (`fix/initial-unknowns`)

#### Step 1.1 — Checker

- `checker.py`: the rule of 4.1 in `check_model_structure()`; `tests/unit/test_checker_semantic.py`: an output
  `exact` listed (error), an output `calculated` not listed (error), a valid descriptor (no error), both versions.
- The Reference FMUs of `tests/data` (e.g. `Feedthrough.fmu`, `BouncingBall.fmu`) pass the checker.

Commit message:
```
Checker: the initial unknowns are checked against the outputs

An output with initial="exact" must not be listed in <InitialUnknowns> /
<InitialUnknown>; an output with initial="calculated" or "approx" must be
(FMI 2.0 §2.2.8, FMI 3.0 §2.4.8).
```

#### Step 1.2 — Builder

- `make_fmu_xml()`: the initial unknowns of 4.1; `tests/integration/test_container_xml.py`: the generated
  descriptor passes the semantic checker; an assembly exposing an output with `initial="exact"` (a Reference FMU of
  `tests/data`, or a descriptor rewritten by `_helpers.archive.rewrite_fmu`) gives a container whose
  `<InitialUnknowns>` leaves it out. `test_fmi2_outputs_index_the_output_variables` is split: `<Outputs>` lists
  every output, `<InitialUnknowns>` the calculated ones.
- `CHANGELOG.md` (Upstream, FMU Container, FIXED).

Commit message:
```
Container: the initial unknowns leave out the outputs with initial="exact"

<InitialUnknowns> (FMI 2.0) and <InitialUnknown> (FMI 3.0) listed every
output of the container, including the ones that copy initial="exact" and a
start value from the embedded FMU (FMI 2.0 §2.2.8, FMI 3.0 §2.4.8).
```

#### Step 1.3 — Documentation

- `docs/user-guide/fmutool/checker.md`: the new rule in the list of the semantic checks.

Commit message:
```
Doc: checker rule on the initial unknowns
```

### Phase 2 — One Model-Exchange part (`refactor/step-loops`)

#### Step 2.1 — Factorization

- `container.c`: `container_step_me()` (4.2); the three loops call it.
- Tests: `tests/integration/test_container.py` (`bouncing`, `bouncing-seq`, mt), `test_me.py`,
  `test_container_perf.py`, the C tests; `cmake --workflow --preset <platform>` with `FMUTOOL_WARNINGS_AS_ERRORS`,
  the `linux64-sanitize` preset in the CI.

Commit message:
```
Container runtime: one Model-Exchange part for the three step loops

The continuous inputs, the collective integration and the outputs of the ME
FMUs were written three times, in the sequential, parallel and multi-thread
loops.
```

#### Step 2.2 — Documentation

- `docs/developer/dostep-fmi-sequence.md`: the ME part named once in the notes.

Commit message:
```
Doc: the Model-Exchange part of the step loops
```

### Phase 3 — Getters from the local variables (`perf/getters-from-locals`)

#### Step 3.1 — Measurement before

- `python tools/bench_container.py` on the host, 3 rounds of 5 runs, digests kept in §7. A new case **F-outputs**
  exposes a few hundred outputs of chained `Feedthrough.fmu` instances and reads them all at each communication
  step (as an importer would): it is the case this phase targets.

Commit message:
```
Bench: case F-outputs, hundreds of outputs read at each communication step
```

#### Step 3.2 — Format version 10 and builder

- `layout.py`, `builder.py` (`make_fmu_txt()`), `types.py` (`CONTAINER_TXT_VERSION = 10`): 4.3.
- `split.py`: reads version 10 (4.3); `tests/integration/test_split.py`, `test_container_txt.py`: the round trip
  builder → `container.txt` → `fmusplit` gives the same assembly for the fixtures of `tests/data/containers`.
- `docs/developer/container-txt-format.md`: version 10 (section 6: the lines of the exposed outputs; the table of
  the versions).

Commit message:
```
Container: every exposed output has a local variable (container.txt v10)

The port of an exposed output is linked to a local variable that the embedded
FMU writes after each of its steps, like the outputs that feed a link. The FMU
and the value reference stay on the line, for the Initialization Mode and for
fmusplit.
```

#### Step 3.3 — Runtime

- `container.h` (`CONTAINER_TXT_VERSION 10`), `container.c` (`read_conf_io()`: the second link of an output port),
  `fmi2.c` / `fmi3.c` (`FMI_GETTER`, `fmi3GetBinary`, the strings: the read-through of Q2 A in Initialization Mode).
- C tests (`container/tests`, stub FMU): a getter in Step Mode does not call the stub; in Initialization Mode it
  does; the value after a step is the one of the step.
- Python tests: the suites, the traces of the probe FMU regenerated (`tests/data/probe/REF-*.csv`) and reviewed:
  only `Get` calls disappear.
- `cmake --workflow --preset linux64-sanitize`.

Commit message:
```
Container runtime: the getters read the exposed outputs from the local variables

A fmi*Get* of the importer on an output of the container was one FMI call per
value reference into the embedded FMU. The outputs are now read once after
each step of the FMU, with the ones that feed a link; the getters read the
local variables (the FMU is still read in Initialization Mode).
```

#### Step 3.4 — Measurement after and documentation

- A/B run (D2): F-outputs, A to E unchanged (digests identical); results in §7. Reverted if F-outputs shows no
  gain (D2).
- `docs/developer/dostep-fmi-sequence.md` (the getters, the pending step), `docs/developer/native-runtime.md`;
  `docs/user-guide/fmucontainer/container.md`: an output read between two steps is the value at the end of the last
  step; `CHANGELOG.md` (CHANGED).

Commit message:
```
Doc: the getters of the container read the local variables
```

### Phase 4 — ruff and mypy (`chore/ruff-mypy`)

#### Step 4.1 — Configuration and baseline

- `pyproject.toml`: 4.4 (Q4, Q5), the `lint` extra; the baseline counted and written in §7.

Commit message:
```
Lint: ruff and mypy configuration, lint extra
```

#### Step 4.2 — Fixes

- One commit per group of rules (imports, pyupgrade, bugbear, errors), then one per module for `mypy`, with
  `pytest` run after each one; a rule disabled has its reason in `pyproject.toml`.

Commit messages (one per commit):
```
Lint: imports sorted and unused imports removed (ruff I, F401)
Lint: pyupgrade fixes (ruff UP)
Lint: bugbear fixes (ruff B)
Types: mypy on model_description, operations, checker
Types: mypy on container, assembly, ssp
```

#### Step 4.3 — CI and documentation

- `ci.yml`: the `lint` job (Q6); `CONTRIBUTING.md` and `docs/installation.md` (development): the commands;
  `CHANGELOG.md` (Native code / development).

Commit message:
```
CI: lint job (ruff, mypy)
```

### Phase 5 — Hybrid multi-thread mode (`perf/mt-hybrid`)

#### Step 5.1 — Profiling in nanoseconds

- `profile.c`: 4.5; the profiling output unchanged; C test of the monotonic clock.

Commit message:
```
Container runtime: profiling with a monotonic clock in nanoseconds
```

#### Step 5.2 — Measurement before

- `tools/bench_container.py`: the `mt` cases (`A-mt`) and a new case **G-heavy** where one FMU of the chain is
  slow (a stub FMU of `container/tests` built with a busy loop of a configurable duration, or `1.fmu` of
  `tests/data/containers/mt` if it fits), with and without `mt`; results in §7.

Commit message:
```
Bench: case G-heavy, one slow FMU among light ones, mono and multi-thread
```

#### Step 5.3 — Scheduling

- `container.c`, `fmu.c`, `thread.c`, `cache.c` (per-FMU scratch buffers): 4.5; flags line of `container.txt`
  (Q8), `builder.py`, `cli/fmucontainer.py`, `assembly.py` (JSON, API), `split.py`.
- C tests: `test_threads_lifecycle.c` (start after the warm-up, stop), a step with heavy and light FMUs, no heavy
  FMU; `linux64-sanitize`; a `linux64-tsan` preset (`-fsanitize=thread`, GCC/Clang) run by hand, in the CI if
  stable.
- Python tests: `test_container.py` (mt), the REF files unchanged.

Commit message:
```
Container runtime: hybrid multi-thread mode

With mt, the runtime measures the doStep of each Co-Simulation FMU over the
first internal steps and gives a thread to the FMUs above a threshold only;
the main thread steps the others meanwhile. A worker runs the exchanges of its
FMU too. The threshold is set at build time (-mt-threshold).
```

#### Step 5.4 — Measurement after and documentation

- A/B run (D2): `A-mt` must not be slower than `A-parallel` any more; `G-heavy` faster with `mt`; results in §7.
- `docs/user-guide/fmucontainer/container.md` (the options table: `-mt`, `-mt-threshold`; the description of the
  modes), the JSON description, `docs/developer/native-runtime.md` (threads), `dostep-fmi-sequence.md`,
  `container-txt-format.md` (flags line); `CHANGELOG.md` (CHANGED, ADDED).

Commit message:
```
Doc: hybrid multi-thread mode
```

### Phase 6 — Datalog (`perf/datalog`)

#### Step 6.1 — Measurement before

- `tools/bench_container.py`: case **H-datalog** (A-parallel with `datalog=True`); results in §7.

Commit message:
```
Bench: case H-datalog
```

#### Step 6.2 — Buffer and decimation

- `datalog.c` / `datalog.h`: 4.6; `builder.py` (`make_datalog()`), `cli/fmucontainer.py`, `assembly.py` (JSON,
  API), GUI (`gui/fmucontainer/details`: the configuration panel, next to **Enable Datalog**).
- C tests (`test_datalog.c`): decimation 3 on 10 steps gives the rows 0, 3, 6, 9 plus the event rows; a reader
  without the second line (datalog of a previous version) gets 1.
- Python tests: `tests/integration/test_datalog.py`, `test_datalog2pcap.py` (the LS-BUS rows are event rows: all
  kept), GUI test of the option.

Commit message:
```
Container datalog: output buffer and decimation (-datalog-every)

The datalog file gets a 1 MiB buffer, and an option writes one row every N
internal steps; the rows of the events and the first row are always written.
```

#### Step 6.3 — Measurement after and documentation

- A/B run (D2): H-datalog; results in §7.
- `docs/user-guide/fmucontainer/datalog.md`, `container.md` (options table, JSON), `CHANGELOG.md` (ADDED).

Commit message:
```
Doc: datalog buffer and decimation
```

---

## 6. Found during the review (not in the scope)

- Discrete real inputs of the ME FMUs set in Continuous Time Mode (`container_perf.md` §8): own plan.
- `fmuCompletedIntegratorStep()` is called on every ME FMU at every sub-step, whatever
  `completedIntegratorStepNotNeeded` (FMI 2.0) / `needsCompletedIntegratorStep` (FMI 3.0): the builder reads neither.
- The sub-step of the ME solver is bounded by the internal step of the container (`solver_do_step()`, `h_max`).
- `variableNamingConvention="structured"`, `license`, `copyright` of the container are hard-coded; no
  `fixedInternalStepSize` (FMI 3.0) nor `dependencies` of the outputs, which the builder could compute from the
  links.
- The embedded FMUs are extracted twice at build time (`FMU()` and `make_fmu_skeleton()`); the FMI schemas are
  loaded again at each check (`checker.py`, `OperationGenericCheck`).
- `tests/_helpers`: the C tests cover neither the solver (event location, RK4) nor the cache in isolation.

---

## 7. Measurements

Filled during the phases (D2): host, method, A/B tables as in `container_perf.md` §7, baseline counts of phase 4.
