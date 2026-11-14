# Plan: conformity, performance and maintainability of the container runtime and the Python package

**Created**: 14 November 2026 — **Status**: in progress (phases 1, 2 and 4 done on 14 November 2026; phase 3
abandoned on 14 November 2026, D7) — **Branch**: `feature/perf-maintainability`, from `integration` — **Roadmap**:
not listed

This plan comes from a review of the whole toolbox (14 November 2026, code reading, measurements of
`docs/local/done/container_perf.md`). It gathers the actions retained from that review, in the order in which they
are done. The discrete real inputs of the Model-Exchange FMUs set in Continuous Time Mode (found in
`container_perf.md`, §8) are **out of the scope** of this plan: they will have a plan of their own.

| Phase | Subject | Kind |
|---|---|---|
| 1 | `<InitialUnknowns>` / `<InitialUnknown>` of the container list the right outputs | FMI conformity |
| 2 | One Model-Exchange part for the three step loops of the runtime | maintainability |
| 3 | The getters of the container read the outputs of the embedded FMUs from the local variables — **abandoned** (D7) | performance |
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
3. ~~A `fmi*Get*` of the importer on an output of the container costs a memory read, whatever the number of outputs,
   and the datalog no longer calls the embedded FMUs.~~ Abandoned (D7).
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
- **D4 — One branch for the whole plan** (decided on 14 November 2026, replacing one branch per phase):
  `feature/perf-maintainability`, from `integration`, one commit per step; the phases follow one another on it.
- **D5 — Decisions of the phases 1 to 3** (14 November 2026): Q1 keep `initial` and `start`; Q2 option A
  (read-through in Initialization Mode); Q3 option A (`container.txt` version 10 written by the builder). Q4 to Q13
  are asked before their phase starts.
- **D6 — Clocked outputs** (14 November 2026): the rule "an output with `initial` `calculated` or `approx` must be
  listed as initial unknown" exempts the `Clock` variables and the clocked variables (attribute `clocks`): they have
  no value in Initialization Mode, and neither the Reference FMUs (`Clocks`) nor the LS-BUS FMUs list them. The rule
  "an output with `initial="exact"` must not be listed" applies to every variable.
- **D7 — Phase 3 abandoned** (14 November 2026, D2): implemented as described in 4.3 (steps 3.2 to 3.4, not
  committed), then reverted: no measurable gain (§7), for a runtime made more complex (state of the container, stale
  FMUs, pairing of the ports with the local variables, grouped reads) and value references of the container ports
  that change. The gain would only show with FMUs whose FMI calls are costly, never measured (as D10 of
  `container_perf.md`). The bench case F-outputs (step 3.1) is kept. The changes are kept in a local `git stash`
  (`phase 3 of perf_maintainability (getters from locals), abandoned by D2`). Consequences: the datalog keeps reading
  the outputs through the getters (phase 6); version 10 of `container.txt` is left to phase 5 (Q8).
- **D8 — Decisions of the phase 4** (14 November 2026): Q4 as recommended (`E, F, W, I, UP, B`, 120, lint only);
  Q5 as recommended, with `follow_imports = "skip"` on `gui/` and `assistant/` (otherwise mypy reports their errors
  through the imports of the other modules) and `ignore_missing_imports` on `fmpy` only (the only package without
  types); Q6 **report only**: the `lint` job does not fail the CI (`continue-on-error`); Q7 no `pre-commit`. Found
  when applying `I` (step 4.2): ruff writes a wrapped import one name per line and cannot keep the aligned
  continuation of the code; accepted (18 imports in 15 files). `_helpers` and `conftest` are first-party for the
  sorting. The mypy errors on optional values (14 November 2026): the annotation corrected when it is wrong;
  `assert x is not None` where None cannot occur by construction; a case where None (or a wrong type) can really
  occur is **not fixed**, it is reported (§6), and its mypy error left. Three cases decided: `split.py` skips a port
  without type element explicitly (same behaviour); `layout.py` uses `link.size`; `AssemblyNode(name: str)` kept
  (the JSON nodes are named after their creation), its error left.
- **D9 — Workflow of the phase 4** (14 November 2026): the long lines of `tests/` and the mypy errors of two groups
  of files were fixed by sub-agents in parallel, on disjoint files, then reviewed; the full test suite ran after
  each ruff commit, the tests related to the files after each mypy commit.
- **D10 — Decisions of the phase 5** (14 November 2026): Q8 as recommended (50 µs, mean of 20 steps, `-mt-threshold`,
  `container.txt` version 10); Q9 a **pool** of `min(heavy, cores - 1)` workers, the heavy FMUs assigned once, the
  longest first; Q10 **`doStep` only** in the workers: the recommendation (the exchanges in the worker) races on the
  local variables (a worker writing the outputs of its FMU while another reads its inputs) and breaks the Jacobi
  semantics, and its gain (costly FMI calls) cannot be measured here (as D7). `mt_threshold` is exposed in the API,
  the JSON, the CLI, `fmusplit` and the SSP container options; not in the GUI nor the MCP assistant (later).

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
| Q8 | 5 | Threshold above which an FMU gets a thread, and where it is set | Default **50 µs** of mean `doStep` time over the first 20 internal steps, measured by the runtime; overridable at build time (`-mt-threshold <seconds>`, `container.txt` flags line, version 10) |
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
  (`calculated`, `approx`), given or by default, must be listed as initial unknown, unless it is a `Clock` or a
  clocked variable (D6); an output with `initial="exact"` must not be listed. The messages quote the section
  (`FMI-2 §2.2.8`, `FMI-3 §2.4.8`). The other entries of the list (calculated parameters, states, derivatives) are
  not checked: out of the scope.
- Q1: an exposed output keeps the `initial` and `start` of the embedded variable.
- Found by running the checker on the generated descriptors (step 1.2): the inputs `container.ts_multiplier` and
  `container.solver` of an FMI 2.0 container had `initial="exact"`, which FMI 2.0 does not allow on an input
  (§2.2.7). Fixed in the same step: `EmbeddedFMUPort.xml()` writes no `initial` on an input of an FMI 2.0 container.

### 4.2 Phase 2 — One Model-Exchange part

- `container.c`: `static fmu_status_t container_step_me(container_t *container)`: the continuous inputs of every ME
  FMU (`fmu_set_continuous_inputs()`), `solver_do_step()`, the outputs (`fmu_get_outputs()`), with the error
  messages of today. The three `container_do_one_step_*()` keep their Co-Simulation part and call it.
- No change of behaviour: the order (CS first, then ME) and the messages are kept; the comments on the discrete
  inputs are kept once, on `container_step_me()`.

### 4.3 Phase 3 — Getters from the local variables

**Abandoned** (D7): implemented as below on 14 November 2026, then reverted; kept as a record. The design written
before the phase is replaced.

- **Builder** (`layout.py`, `make_fmu_txt()`): every exposed output (not converted, not an FMI-2 aggregate: those
  already go through a local variable) gets a local variable of its type, the one of its link when the output also
  feeds another FMU. The port line of the output is **unchanged** (`<VR> <DIM> 1 <FMU_INDEX> <FMU_VR>`); the output is
  added to the Outputs section of its FMU (`<LOCAL_OFFSET> <DIM> <FMU_VR>`). `CONTAINER_TXT_VERSION` 10 (Q3 A).
  The local variables are allocated **FMU by FMU** (in the order of `container.txt`, `fmu_order`): the values of the
  links and the other outputs of the FMU first, its converted copies after, so that the local variables of the
  outputs of an FMU are contiguous for each type; the local lines of the I/O table are written by value reference
  with `layout.local_offset()` (the offset trick is gone). The value references of the container ports change.
- **Runtime**: `container_link_output_locals()` pairs each port linked to an FMU with the entry of the Outputs
  section of that FMU with the same value reference and dimension (`container_port_t.output_local`,
  `CONTAINER_NO_LOCAL` otherwise). The getters (`fmi2.c`, `fmi3.c`, binaries included) read the local variable when
  `CONTAINER_OUTPUTS_IN_LOCALS(state)` (Step, Event or Terminated state) and the FMU is not **stale**; otherwise they
  synchronize the FMU and read it, as before (Q2 A, read-through in Initialization Mode).
- **Stale FMU** (`fmu_t.outputs_stale`): set when the importer sets a value on a port linked to the FMU
  (`cache_port_set()`), cleared by `fmu_get_outputs()` unless values still wait for the FMU in the cache
  (`cache_fmu_has_values()`, a step was pending). The read-after-write semantics are kept: an FMU that computes its
  outputs from the inputs set at the current communication point (direct feedthrough, e.g. `Feedthrough.fmu` of the
  Reference FMUs, replayed by the LS-REF checker) gives the same values as before. Without this flag, the LS-REF
  replay tests failed (`expected 5, simulated 4.0`).
- **Grouped reads** (asked on 14 November 2026): `fmu_group_outputs()` sorts a copy of the Outputs list of each
  numeric type by local variable and, when each entry starts where the previous one ends, keeps the FMU value
  references in that order (`fmu_translation_list_t.grouped_vrs`, `grouped_offset`, `grouped_nvalues`): `GET_OUTPUT`
  then makes **one FMI call per type**, straight into the local variables, no copy. On a failure, the outputs are
  read one by one to report the failing variable (D6 of `container_perf.md`). Strings and binaries keep one call per
  output (they are copied anyway). A list of one output is not grouped (same single call).
- **`fmusplit`**: unchanged. An exposed output appears in the Outputs section as a writer without reader, which the
  link reconstruction ignores; the round trip builder → `container.txt` → `fmusplit` → builder gives the same file
  (`fmu_order` makes the allocation independent of the order of the links).
- **Probe traces** (`tests/data/probe/REF-*.csv`): regenerated; the only changes are `fmi2Get*` rows (the exposed
  outputs are now read after each step of the FMU, the read-through calls of the getters are gone), the other calls
  are identical in every trace.
- **Behaviour change**: a `fmi*Get*` on an output while no value was set on the FMU since its last step returns the
  value at the end of that step without calling the FMU; an FMU that recomputes its outputs on `Get` without any new
  input (none known) would not be seen.

### 4.4 Phase 4 — ruff and mypy

- `pyproject.toml`: `[tool.ruff]` (Q4), `[tool.ruff.lint]`, `[tool.mypy]` (Q5), a `lint` extra (`ruff`, `mypy`,
  and the stubs: `types-colorama`); `all` includes it.
- Baseline: `ruff check fmu_manipulation_toolbox tests tools` and `mypy fmu_manipulation_toolbox`, counted by rule
  and by file, kept in this plan (§7); the rules whose fixes are mechanical (`I`, `UP`, unused imports) are applied
  with `--fix`, the others by hand, file by file, without changing a behaviour; a rule that does not fit the code is
  ignored with a reason in `pyproject.toml`.
- CI: a `lint` job in `ci.yml` (Ubuntu, newest Python), in parallel with the test jobs, report only (Q6, D8).
- `CONTRIBUTING.md`: how to run them.

### 4.5 Phase 5 — Hybrid multi-thread mode

Decided on 14 November 2026 (D10); replaces the design written with the plan.

- **Prerequisite**: `profile.c` in nanoseconds (`clock_gettime(CLOCK_MONOTONIC)`, `QueryPerformanceCounter()`),
  used by the profiling output (unchanged values, better resolution) and by the measurement below.
- **Measurement**: with `mt`, the first `MT_WARMUP` (20) internal steps run in the mono-thread parallel mode, the
  time of each `fmuDoStep()` of the CS FMUs measured; then each CS FMU is **heavy** (mean above the threshold, Q8) or
  **light**.
- **Workers** (Q9): `min(number of heavy FMUs, number of cores - 1)` threads, started at the end of the warm-up;
  the heavy FMUs are assigned once, the longest first, each to the least loaded worker (LPT). No heavy FMU, or a
  single core: no thread, the steps go on in the mono-thread parallel mode.
- **Scheduling** of an internal step (Jacobi, as the parallel modes): the main thread sets the inputs of every CS FMU,
  releases the workers, which run `fmuDoStep()` of their FMUs one after the other (Q10: `doStep` only), steps the
  light FMUs meanwhile, waits for the workers, gets the outputs of every CS FMU, then runs the ME part. The exchanges
  stay on the main thread: a worker running `fmu_set_inputs()` and `fmu_get_outputs()` of its FMU would write local
  variables that another worker may still be reading (Q10).
- **Synchronization**: `barrier_start` and `barrier_end` as today, sized `workers + 1`.
- **Threshold** (Q8): `MT_THRESHOLD` seconds, default 50 µs. Flags line of `container.txt`:
  `<MT> <Profiling> <Sequential> <MT_THRESHOLD>`, version 10. Exposed as `make_fmu(..., mt_threshold=...)`,
  `AssemblyNode(mt_threshold=...)`, JSON `"mt_threshold"`, CLI `-mt-threshold <seconds>`, read back by `fmusplit` and
  kept by the SSP container options (D10). A threshold of 0 makes every CS FMU heavy.
- The mode is reported once at the end of the warm-up (`LOGGER_WARNING`, as the mode today), with the heavy FMUs and
  their worker.

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

### Phase 3 — Getters from the local variables (`perf/getters-from-locals`) — abandoned (D7)

Step 3.1 is done (commit `29b616e`); steps 3.2 to 3.4 were implemented, not committed, then reverted (D7).

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
Lint: pycodestyle and pyflakes fixes (ruff E, F, W)
Types: mypy on model_description, operations, checker
Types: mypy on compiler, remoting, simulation, cli
Types: mypy on container, assembly, ssp, split
```

#### Step 4.3 — CI and documentation

- `ci.yml`: the `lint` job (Q6, report only: `continue-on-error`); `CONTRIBUTING.md` (section *Static checks*) and
  `docs/installation.md` (the `lint` extra); `CHANGELOG.md` (Upstream, new section *Development*).

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

- `tools/bench_container.py`: the `mt` cases (`A-mt`) and a new case **G-heavy**: a chain of light `Feedthrough`
  instances and a few slow ones, compiled at bench time from the sources of `compile/3.0/Feedthrough.fmu` with a
  loop of a fixed number of iterations in `doStep` (a fixed amount of work, whatever the threads), with and without
  `mt`; results in §7.

Commit message:
```
Bench: case G-heavy, one slow FMU among light ones, mono and multi-thread
```

#### Step 5.3 — Scheduling

- `container.c`, `container.h`, `fmu.c`, `fmu.h`: 4.5; flags line of `container.txt` (Q8, version 10),
  `types.py`, `builder.py`, `cli/fmucontainer.py`, `assembly.py` (JSON, API), `split.py`, `ssp.py`.
- C tests: `test_threads_lifecycle.c` (start after the warm-up, stop), a step with heavy and light FMUs, no heavy
  FMU; `linux64-sanitize`; a `linux64-tsan` preset (`-fsanitize=thread`, GCC/Clang) run by hand, in the CI if
  stable.
- Python tests: `test_container.py` (mt), the `mt_threshold` option (JSON, CLI, `fmusplit`, SSP round trip); the
  results unchanged (D3); the `REF-*` container files change by their version and flags lines only.

Commit message:
```
Container runtime: hybrid multi-thread mode

With mt, the runtime measures the doStep of each Co-Simulation FMU over the
first internal steps; the FMUs above a threshold are stepped by a pool of
worker threads (at most one per core but one), the main thread steps the
others meanwhile. The threshold is set at build time (-mt-threshold,
container.txt version 10).
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
- Found by mypy (phase 4, D8): inputs that the FMI schemas forbid but that the package does not refuse, and that make
  it fail or misbehave; their mypy errors are left (28 at the end of the phase):
  - `compiler.py:310-359`: a `buildDescription.xml` without `modelIdentifier` builds a library named `None`; a
    `<File>`, `<SourceFile>` or `<IncludeDirectory>` without `name` raises a `TypeError` (`Path / None`); a
    `<PreprocessorDefinition>` or `<Library>` without `name` gives `-DNone` / `-lNone` (a crash with MSVC).
  - `container/embedded.py:380`: an `fmiVersion` accepted by `ModelDescription` but neither `"2.0"` nor `"3.*"`
    (e.g. `"2"`, `"3"`) leaves `fmi_version` None (`TypeError` in `EmbeddedFMUPort`); an FMI 2.0 variable without
    type element raises a `KeyError`.
  - `container/rules.py:203-205`: a link from an input clock to an input that is not a clock raises an
    `AttributeError` instead of an `FMUContainerError`.
  - `assembly.py:774-793`: `Assembly()` without a file, then `write("x.csv")`: `AttributeError` (`root` is None);
    `json_encode` handles this case. `assembly.py:825`: `AssemblyNode(name: str)` built with `name=None` (D8).
  - `ssp.py:480`: an FMU variable without `name` gives a `None` key (a crash in `get_close_matches` when a connector
    is not found); `ssp.py:721`: an `<Item>` without `name` or `value` gives a `None` start value or a `TypeError`;
    an `ssv:Parameter` without `name` crashes (untyped code, not reported by mypy).
  - `cli/fmutool_agent.py:152`: under `python -OO` the docstrings are removed and `list-tools` crashes.
- `assembly.py`: `_get_flat_links_recursive()` overwrites its parameters `left_candidates` and `right_candidates`
  at once: the candidates given by the recursive call are never used (`#TODO` in the code).

---

## 7. Measurements

Filled during the phases (D2): host, method, A/B tables as in `container_perf.md` §7, baseline counts of phase 4.

### Phase 3

`python tools/bench_container.py F-outputs A-parallel E-same-type --runs 3` on macOS (Apple silicon), 14 November
2026, time of the `doStep` loop in seconds (min / mean). Not an A/B in one session: the runtime before the phase reads
`container.txt` version 9 only, so the two runs are a few minutes apart (the differences between sessions are 5 to
10 %, `container_perf.md` §7). *Calls* is the number of FMI exchange calls of one internal step (per port / grouped,
from `container.txt`).

| Case | Before | After | Calls before | Calls after | Digest |
|---|---|---|---|---|---|
| F-outputs (100 outputs read at each communication step) | 1.026 / 1.033 | 0.999 / 1.018 | 190 / 38 | 195 / 39 | identical |
| E-same-type (same container, one output read) | 0.604 / 0.617 | 0.604 / 0.620 | 190 / 38 | 191 / 39 | identical |
| A-parallel | 0.784 / 0.825 | 0.823 / 0.837 | 507 / 468 | 508 / 469 | identical |

Reading: the loop of F-outputs costs 0.4 s more than E-same-type for the 100 outputs read at each of the 40 000
communication steps, and the phase removes less than 3 % of it: with fmpy, the time goes to the Python call of
`getFloat64` with 100 value references, not to the 100 FMI calls into `1.fmu` that the getters made (a few tens of
nanoseconds each, as `container_perf.md` D10 found). What the phase changes is the number of FMI calls into the
embedded FMUs per communication step of F-outputs: 100 getter calls plus 95 link reads before, 20 grouped reads
after (one per FMU and type). The gain shows with FMUs whose calls are costly (remoting, tool-generated FMUs), which
this benchmark does not have. **Decision D2 applied** on 14 November 2026: the phase is reverted (D7).

### Phase 5

`python tools/bench_container.py A-parallel A-mt G-parallel G-mt --runs 5`, 3 rounds, on macOS (Apple M4, 4
performance and 6 efficiency cores, `hw.ncpu` 10), 14 November 2026; time of the `doStep` loop in seconds, best min
and best mean of the rounds. G: 8 light `Feedthrough` and 4 `Slow.fmu` (`Feedthrough` with a loop of 50 000
iterations in `fmi3DoStep`, about 100 µs) chained on their `Float64` ports, stop time 2.5 s (2 500 internal steps).
The digests of a mode do not change between the rounds; G-parallel and G-mt give the same digest (A-mt has another
stop time than A-parallel).

| Case | Before (step 5.2) | After (step 5.4) |
|---|---|---|
| A-parallel | 0.769 / 0.784 | |
| A-mt | 1.174 / 1.183 | |
| G-parallel | 1.051 / 1.060 | |
| G-mt | 0.394 / 0.399 | |

### Phase 4

Baseline of step 4.1 (14 November 2026, macOS, Python 3.14, `ruff` 0.17.5, `mypy` 2.4.1), with the configuration of
`pyproject.toml` (D8).

`ruff check fmu_manipulation_toolbox tests tools`: **344** errors (package 170, `tests` 140, `tools` 16), 190 fixable
with `--fix` (40 more with `--unsafe-fixes`).

| Rule | Count | Fix | Rule | Count | Fix |
|---|---|---|---|---|---|
| I001 unsorted-imports | 148 | auto | B017 assert-raises-exception | 2 | hand |
| E501 line-too-long | 76 | hand | W293 blank-line-with-whitespace | 2 | auto |
| B905 zip-without-explicit-strict | 23 | hand | B023 function-uses-loop-variable | 2 | hand |
| F541 f-string-missing-placeholders | 21 | auto | B006 mutable-argument-default | 2 | hand |
| B904 raise-without-from-inside-except | 11 | hand | W291 trailing-whitespace | 2 | hand |
| F405 undefined-local-with-import-star-usage | 11 | hand | F401 unused-import | 2 | auto |
| B007 unused-loop-control-variable | 11 | hand | UP028 yield-in-for-loop | 2 | hand |
| UP015 redundant-open-modes | 10 | auto | UP033 lru-cache-with-maxsize-none | 1 | auto |
| B008 function-call-in-default-argument | 8 | hand | E713 not-in-test | 1 | auto |
| UP012 unnecessary-encode-utf8 | 5 | auto | F403 undefined-local-with-import-star | 1 | hand |
| E741 ambiguous-variable-name | 2 | hand | B018 useless-expression | 1 | hand |

`mypy` (`fmu_manipulation_toolbox` without `gui/` and `assistant/`): **139** errors in 17 files (37 checked); by
code: `assignment` 49, `arg-type` 31, `union-attr` 18, `return-value` 10, `misc` 10, `var-annotated` 9, `operator` 6,
`index` 6. By file: `assembly.py` 26, `checker.py` 20, `ssp.py` 16, `compiler.py` 16, `split.py` 8, `remoting.py` 8,
`container/embedded.py` 8, `simulation.py` 7, `operations.py` 7, `container/txt.py` 7, `container/builder.py` 6,
`model_description.py` 3, `container/layout.py` 2, `cli/fmutool_agent.py` 2, `experiments.py` 1, `container/xcp.py` 1,
`container/rules.py` 1. The bodies of the functions without annotations are not checked (`check_untyped_defs` off,
the default: 92 notes). The whole package, `gui/` and `assistant/` included, gives 235 errors.

End of the phase (14 November 2026): `ruff check fmu_manipulation_toolbox tests tools` gives **0** error (10
`# noqa: E501` on strings that cannot be wrapped: Markdown and XML content); `mypy` gives **28** errors in 6 files
(139 before), all left on purpose: the inputs of §6 that the package does not refuse, and `AssemblyNode(name)` (D8).
The test suite: 2867 passed, 3 skipped, before and after the ruff fixes.
