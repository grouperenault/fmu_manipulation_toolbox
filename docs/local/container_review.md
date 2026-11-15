# Plan: fixes and cleanup from the review of container.c

**Created**: 15 November 2026 — **Status**: in progress — **Branch**: `container-review`, from `feature/perf-maintainability` (`d79cbb7`) — **Roadmap**: not listed

A review of `container/container.c` (15 November 2026, after its functions were grouped by themes) found three
defects, two points of the multi-thread mode, and cleanups. This plan fixes them, and investigates a doubt on the
clocks raised by a comment of `container_update_discrete_state()`.

---

## 1. Findings

| # | Kind | Where | Finding |
|---|---|---|---|
| 1 | defect | `container_free()` | `binaries.locals[i].data` is freed for `i < binaries.nb_locals` without checking `binaries.locals`: after an allocation failure in `config_read_local()` (the counts are read before the allocations), `NULL` is dereferenced. The loop of the strings checks it |
| 2 | defect | `container_exit_initialization_mode()` | Returns `-9`, not a `fmu_status_t`, when `solver_configure()` fails |
| 3 | defect | `container_init_values()` | The status of `fmu_get_outputs()` / `fmu_get_clocked_outputs()` is ignored: a failure at the end of the initialization goes unnoticed |
| 4 | dead code | `container_set_start_values()` | Only called with `START_VALUES_INITIALIZATION`: the branch of `START_VALUES_EARLY` is never run |
| 5 | dead code | `container_update_discrete_state()` | A block of commented code ("paranoid"), with a comment partly wrong (see 13) |
| 6 | dead code | `container_do_one_step_parallel()`, `_sequential()` | Orphan comments `/* STEP MODE */`, `/* COMPUTATION */` |
| 7 | multi-thread | `container_worker()`, `container_do_one_step_hybrid()` | A failed step of a heavy FMU is logged twice; the worker logs it from its thread, through the logger callback of the importer, which an importer may not expect from another thread |
| 8 | multi-thread | `container_reset()` | `fmi*Reset` keeps the workers and the dispatch of the FMUs: no new warm-up, whereas the reset is documented as "the state right after the instantiation" |
| 9 | consistency | `container_enter_event_mode()`, `_enter_step_mode()`, `container_reset_fmu()` | Two consecutive `#ifdef DEBUG`; a `"[DEBUG] ..."` message logged outside `#ifdef DEBUG` |
| 10 | naming | `is_close()`; `fmu_t.need_event_udpate` | No `container_` prefix and an `int` result; a typo in the field (8 uses in `fmu.h`, `fmu.c`, `container.c`) |
| 11 | consistency | `container_setup_experiment()` | Typo "Disbale"; `stop_time_defined = 0` on a `bool`; `stopTimeDefined` ignored (on purpose: the stop time is disabled for rounding issues) |
| 12 | style | `container_do_step()` | A line of a `DEBUG` block longer than 120 characters |
| 13 | doubt | `container_update_discrete_state()` | The comment of 5 says "All clocks have been transmitted by now". An output clock read `true` in the last pass of the sweep reaches only the FMUs after its emitter in the order of `fmu[]`, and stays `true` in `clocks.locals` until the next `fmu_get_clocked_outputs()` of its FMU: a stale tick, e.g. for `container_reset_fmu()`, which calls `fmu_set_clocks()`. Not verified by a test |

---

## 2. Goals

1. The defects 1 to 3 are fixed, each with a C test when it can be reproduced.
2. The multi-thread mode logs from the main thread only (7) and has a defined behaviour after `fmi*Reset` (8).
3. The cleanups 4, 5, 6, 9 to 12, without change of behaviour.
4. The doubt 13 is settled by a test: fixed if it is a defect, the comment corrected otherwise.

Non-goals: the other modules (`config.c`; `fmu.c` apart from the renamed field).

---

## 3. Decisions

- **D1 — Branch** (15 November 2026): `container-review`; the reordering of `container.c` (step 0) is committed on it.

- **D2 — Decisions** (15 November 2026): Q2 a failure to read the outputs at the end of the initialization is an
  error; Q3 the main thread logs the failed step of a heavy FMU, the worker logs nothing; Q4 **the dispatch is kept**
  after `fmi*Reset` (no new warm-up), and documented; Q5 the reset of an FMU logged by `LOGGER_DEBUG("Reset FMU '%s'
  at time=%e.")`; Q6 `is_close()` becomes `container_is_close()` returning `bool`, `need_event_udpate` becomes
  `need_event_update`. Q7 is decided after the test of the step 4.

---

## 4. Steps

Each step: `cmake --workflow --preset darwin64` (no warning), the C tests, the tests of the container of the Python
suite (`pytest -k "container or datalog or clock or lsbus or reset"`), the `REF-*` files unchanged unless said.

### Step 0 — Reordering of container.c

- The functions grouped by themes (clocks, event mode, configuration, initialization, reset, step, multi-thread,
  constructor), two section headers added; no line of code changed. With the comments added by the user on
  `container_worker()` and `container_stop_threads()`.

Commit message:
```
Container runtime: the functions of container.c grouped by themes
```

### Step 1 — Defects (1, 2, 3)

- `container_free()`: the loop of the binaries checks `binaries.locals` (1). C test: a container whose
  `binaries.nb_locals` is set without its locals, freed.
- `container_exit_initialization_mode()`: `FMU_STATUS_ERROR` (2).
- `container_init_values()` returns a status, checked by its caller (Q2).

Commit message:
```
Container runtime: three defects found by the review of container.c

container_free() no longer dereferences the local binaries when their
allocation failed; container_exit_initialization_mode() returns a status of
the FMUs when the ME solver cannot be built; a failure to read the outputs of
an FMU at the end of the initialization is an error.
```

### Step 2 — Multi-thread mode (7, 8)

- `container_worker()` logs nothing (Q3).
- `container_reset()`: the dispatch kept (Q4), said in a comment. C test (`test_threads_lifecycle.c`): after
  `fmi2Reset`, the simulation goes on with the same workers.

Commit message:
```
Container runtime: the failed step of a heavy FMU logged once, by the main thread
```

### Step 3 — Cleanup (4, 6, 9, 10, 11, 12)

- 4: the branch of `START_VALUES_EARLY` removed from `container_set_start_values()`; 6; 9 (Q5); 10 (Q6); 11; 12.

Commit message:
```
Container runtime: cleanup of container.c (dead code, names, debug messages)
```

### Step 4 — Clocks after the event iteration (5, 13)

- C test with two stub FMUs of FMI 3.0 (an output clock, an input clock), the emitter after the receiver in the
  order of `fmu[]`: is the tick delivered? does `clocks.locals` stay `true` after the iteration?
- Then Q7: a fix (e.g. one more pass when an output clock ticked, the output clocks reset at the end of the
  iteration) or the comment corrected; the commented code of 5 removed in both cases.

Commit message: written once Q7 is decided.

### Step 5 — Documentation

- `docs/developer/native-runtime.md` (the multi-thread mode after a reset),
  `docs/user-guide/fmucontainer/multi-threading.md` (the dispatch kept after a reset, Q4), `CHANGELOG.md` (FIXED: 1, 3; 13 if fixed).

Commit message:
```
Doc: the multi-thread mode after a reset, fixes of the review of container.c
```

---

## 5. Found during the work (not in the scope)

---

## 6. Measurements

None: no change of performance expected.
