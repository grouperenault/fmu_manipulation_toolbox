# Robustness of the native runtime of the container

**Created**: 18 October 2026 — **Status**: planned — **Branch**: `robustness` (from `integration`) — **Roadmap**:
not listed

## Context

A review of the native runtime of the container (`container/*.c`, 18 October 2026) found the following weaknesses.

### Real bugs

1. **Thread shutdown after a failed configuration (MT mode).** `read_flags()` sets `container->mt = true`
   (`container/container.c:1360`) long before `container_start_threads()` initializes the barriers
   (`container.c:2159`). `container_new()` allocates the container with `malloc()`: the barriers hold garbage. If
   the configuration fails in between after the embedded FMUs are loaded (instantiation of an embedded FMU,
   reading error of a later section, allocation failure...), `container_free()` → `container_stop_threads()` waits
   on an uninitialized barrier (macOS: `dispatch_semaphore_wait(NULL)`). A missing library is not concerned:
   `read_conf_fmu()` then drops the FMU array and `container_stop_threads()` is not called. Same deadlock if
   `fmu_launch_thread()` fails for the k-th FMU: the threads
   already launched wait for `nb_cs + 1` participants that never come.
2. **The logger is a global state** (`container/logger.c`, `static logger_config`). Two instances of the container
   in one process overwrite each other's callback, environment, instance name and debug flag; after the
   `FreeInstance` of the last instantiated one, `instance_name` points to freed memory. `fmi2SetDebugLogging` /
   `fmi3SetDebugLogging` change the debug flag of every instance.
3. **FMI 3.0 `logMessage == NULL`**: allowed by the standard, called without check by `logger_log()`.
4. **`NULL` dereference in `fmi2Instantiate` / `fmi3InstantiateCoSimulation`**: `container->state = ...` is
   executed outside of `if (container)` (`container/fmi2.c:96`, `container/fmi3.c:94`). The `strdup()` of
   `container_new()` are not checked.

### Side effects on the host process

5. **`setlocale(LC_NUMERIC, "C")`** (`container.c:2253`) changes the locale of the whole importer, permanently, and
   `setlocale()` is not thread-safe. The datalog (`fprintf` of floats at each step) also depends on the locale: it
   relies today on this global change.
6. **Windows: `SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS)`** (`container/thread.c:13`) changes the
   priority class of the host process at each thread creation.

### Reading of `container.txt`

7. `READER_FMU_CLOCKED_IO` (`container.c:1748`): on a `sscanf` failure, `CONFIG_ERROR` without `return`, then
   `read` (uninitialized) is added to `offset`.
8. `READER_FMU_START_VALUES` (`container.c:1942`): `sscanf("%lu %lu") < 1` instead of `< 2` (`nb` uninitialized).
9. Start values (`container.c:1875`, `1922`, `1985`, readers of `booleans1`, `strings` and the numeric types): the
   bound `pos > nb` is checked **after** the write: one element is written past the end before the error.
10. `sscanf` formats that do not match the types: `%d` for `fmu_vr_t` (unsigned), `%ld` for `unsigned long`
    (`port.dimension`, `port.nb`, `fmu_id`, `translations_list.nb`): undefined behaviour.
11. The indexes read are not checked against the allocated sizes: local VR + dimension against `nb_local_<type>`,
    `fmu_id` against `nb_fmu`, clock VRs.
12. `strdup("")` of the local strings not checked (`container.c:567`, `1591`).

### Datalog

13. The time is written with `"%e"` (7 significant digits: at t = 1234.5678 s with a 1 ms step, several rows have
    the same time), the `reals64` with `"%lf"` (6 fixed decimals: 1e-8 is written `0.000000`), the `reals32` with
    `",%f"`.
14. The strings are written as is: a comma, a quote or a newline breaks the CSV.

### Quality

15. `container_set_fmu_start_values()` (`container.c:351`) returns `void` and ignores the status of the `fmuSet*`.
16. The macOS barrier (`container/thread.c`) is correct only because two barriers alternate (start / end); the
    comment of `thread.h` says it is "automatically reusable", which is wrong for two consecutive waits on the same
    barrier.
17. `container/library.c:21` uses `#ifdef WIN32`, the rest of the code `_WIN32`.
18. No native test: `container/build/test_units` is a leftover of a former configuration, absent from
    `container/CMakeLists.txt`. No sanitizer in the CI.

## Decisions (2026-10-18)

1. **Scope**: all the points above (§ real bugs, side effects, reading, datalog, quality).
2. **Branch**: `robustness`, from `integration`.
3. **Logger per instance**:
   - a `logger_t` structure (FMI version, callback, environment, instance name, debug flag) stored in
     `container_t`; the modules without a container (`config.c`, `library.c`, `convert.c`, `profile.c`...) get a
     `const logger_t *` (as a parameter, or a member of their own structure, e.g. `config_file_t`);
   - the levels are renamed `LOGGER_LEVEL_DEBUG`, `LOGGER_LEVEL_WARNING`, `LOGGER_LEVEL_ERROR`;
   - macros `LOGGER_DEBUG(...)`, `LOGGER_WARNING(...)`, `LOGGER_ERROR(...)` to keep the calls light;
   - the macros use an **implicit name in scope**: a variable `logger` of type `const logger_t *` (e.g.
     `const logger_t *logger = &container->logger;` at the beginning of a function).
4. **Windows priority**: `SetPriorityClass` removed; the threads keep a high priority (`THREAD_PRIORITY_HIGHEST`,
   `THREAD_PRIORITY_TIME_CRITICAL` removed).
5. **Locale**: per thread — `newlocale()` / `uselocale()` on POSIX, `_configthreadlocale()` + `setlocale()` on
   Windows — around the reading of the configuration and the writing of the datalog; the locale of the host is never
   changed.
6. **Datalog**: time and `reals64` in `%.17g`, `reals32` in `%.9g`; a string that contains a comma, a quote or a
   newline is quoted (RFC 4180, quotes doubled). `datalog2pcap` reads the CSV with the `csv` module: compatible.
7. **Native tests**: a CTest target of C tests, and a Linux CI job that builds the runtime with ASan / UBSan and runs
   the C tests and the Python tests of the container with it.

8. **Name of the logging function**: `logger_message()`; the macros call
   `logger_message(logger, LOGGER_LEVEL_x, ...)` with the implicit variable `logger`.
9. **Status of the start values (point 15)**: an `fmuSet*` that returns an error makes the call that sets the start
   values fail (Enter Initialization Mode, reset of an FMU...); a warning is only logged.
10. **Order of the steps**: the C test target first, the sanitizer job right after it (to see at once what it
    reports), then the fixes.
11. **macOS barrier (point 16)**: a generation counter makes it reusable for consecutive waits; its impact on the
    performance is measured (`tests/integration/test_container_perf.py` / benchmarks, MT mode) before and after.

12. **Locale of the datalog** (2026-10-18, after step 6): the datalog keeps writing its rows with the C numeric
    locale, so that a decimal comma never breaks the columns of the CSV. POSIX: `uselocale()` around each row
    (measured: 15 ns for enter + leave, against 535 ns for the `fprintf` of 3 doubles). Windows: the switch of
    `_configthreadlocale()` + `setlocale()` at each row is replaced at step 9 by a `_locale_t` created once
    (`_create_locale(LC_NUMERIC, "C")`) and `_fprintf_l()`.

## Steps

### Step 1 – Native test target

- `container/CMakeLists.txt`: `include(CTest)`; under `BUILD_TESTING`, an executable `container_tests` (new
  directory `container/tests/`) linked with the sources of the runtime (static library or object library shared
  with the `container` shared library, so that the internal functions can be tested), `add_test()`.
- A minimal test harness (no dependency): assertion macros, one function per test, exit code.
- First tests: reading of a valid `container.txt` (fixture of `tests/data`), the barrier (N threads, many phases).
- `.github/workflows`: run `ctest` after the native build on the 3 platforms.
- Remove the leftover `container/build/test_units` from the local build (not tracked).

Commit message: `Add a CTest target for the native runtime of the container`

### Step 2 – Sanitizer CI job (point 18)

- `.github/workflows/ci.yml`: a Linux job that builds the runtime with `-fsanitize=address,undefined`
  (`fmutool.cmake` option, e.g. `FMUTOOL_SANITIZE`), runs `ctest`, then the Python tests of the container with the
  sanitized runtime (`LD_PRELOAD` of the ASan runtime for the Python process).
- What the job reports is fixed by the following steps; until then the job may be allowed to fail
  (`continue-on-error`), removed at the last fix.

Commit message: `Run the native runtime under ASan and UBSan in the CI`

### Step 3 – Thread lifecycle (points 1, 6, 16)

- `container_t`: `threads_started` (number of worker threads launched) and a flag for the initialized barriers,
  set by `container_new()` and `container_start_threads()`.
- `container_start_threads()`: on a failure, stop the threads already launched (cancel + release of the barrier
  with the right number of participants) and destroy the barriers.
- `container_stop_threads()`: does nothing when no barrier is initialized; waits only for the launched threads.
- `container/thread.c`: decision 4.
- macOS barrier: generation counter (decision 11), comment of `container/thread.h` updated; C test with
  consecutive waits on the same barrier; performance of the MT mode measured before and after.
- Tests: configuration that fails after `read_flags()` in MT mode (instantiation of the embedded FMU refused): no
  hang, no crash (C test, with a stub FMI 2.0 FMU built by the tests, `container/tests/stub_fmu.c`).

Done: the worker threads wait on a gate (`thread_gate_t`) until all of them are launched and the barriers are
initialized; on a failure the gate is opened without `barriers_ready` and the launched threads end. The macOS barrier
parks the threads of a phase on the semaphore of its parity. `clocks_list.buffer_previous` is now initialized and
freed. Performance of the MT mode unchanged (`tools/bench_container.py A-mt`, 10 runs: 1.329 / 1.344 s min / mean
before, 1.327 / 1.359 s after, same digest).

Commit message: `Stop the worker threads cleanly when the configuration of the container fails`

### Step 4 – Logger per instance (points 2, 3)

- `container/logger.h` / `logger.c`: `logger_t`, `logger_message()`, levels and macros of decision 3; no global
  state left.
- `container_t` holds its `logger_t`; `fmi2Instantiate` / `fmi3InstantiateCoSimulation` initialize it;
  `fmi2SetDebugLogging` / `fmi3SetDebugLogging` change the flag of their instance only.
- Embedded FMU loggers (`logger_embedded_fmu2`, `logger_embedded_fmu3`): through `fmu->container->logger`;
  `logger_get_debug()` replaced by the flag of the instance (`container/fmu.c:1305-1346`).
- `config_file_t`, `library_load()`, `convert`, `profile`, `solver`, `datalog`, `hash`: get the logger of their
  container.
- FMI 3.0 `logMessage == NULL`: no message is sent.
- All the calls (about 235) converted to the macros.
- Tests: two instances of a container in one process with different loggers and debug flags (Python test with
  `fmpy`), one freed before the other; FMI 3.0 instantiation with `logMessage = NULL` (C test).

Commit message: `Make the logger of the container per instance`

### Step 5 – FMI entry points (point 4)

- `fmi2Instantiate`, `fmi3InstantiateCoSimulation` (and the other `container->state = CONTAINER_STATE_INSTANTIATED`
  of `fmi2.c:175`, `fmi3.c:176`, `fmi3.c:666` reviewed): return `NULL` when `container_new()` fails.
- `container_new()`: check the `strdup()`; `calloc()` instead of `malloc()` so that every member starts at zero.

Commit message: `Handle the allocation failures of the instantiation of the container`

### Step 6 – Locale per thread (point 5)

- A small portable API (`container/config.c` or a new `locale.c`): switch the current thread to the C numeric
  locale and back.
- Used by `container_configure()` (instead of `setlocale(LC_NUMERIC, "C")`) and around the writing of a datalog
  row (`datalog_log()`).
- Test: the importer sets a locale with a decimal comma (`fr_FR.UTF-8` when available) before the instantiation;
  its locale is unchanged after it, the start values and the datalog are read / written with a dot.

Commit message: `Read the configuration in the C locale without changing the locale of the host`

### Step 7 – Reading of `container.txt` (points 7 to 12)

- `READER_FMU_CLOCKED_IO`: `return` after the error, `read` initialized.
- `READER_FMU_START_VALUES`: `< 2`; in the three start value readers, the bound checked before the write.
- `sscanf` formats matching the types (`%u` for `fmu_vr_t`, `%lu` for `unsigned long`; `fmu_id` read as a `long`
  where -1 means a local variable).
- Checks of the indexes read against the sizes allocated (local VRs + dimensions, `fmu_id`, clock VRs): a
  configuration error that names the line.
- `strdup("")` checked.
- `read_conf_clocks()`: its status is ignored by `container_configure()`, and the clock index `pos` is not checked
  against `nb_local_clocks` (found at step 3).
- `datalog_configure()`: the `READ` macro frees the datalog on an error, then `datalog_new()` frees it again (double
  free, found at step 6).
- C tests: one malformed `container.txt` per check (truncated line, too many start values, out of range VR or FMU
  index, missing value): an error, no crash (also run under the sanitizers of step 2).

Commit message: `Check the values read from container.txt by the runtime`

### Step 8 – Status of the start values (point 15)

- `container_set_fmu_start_values()` returns an `fmu_status_t`, per decision 9; its callers
  propagate it.
- Test: an FMU that refuses a start value (probe FMU, or a start value of a wrong VR in a test `container.txt`).

Commit message: `Report the failures to set the start values of the embedded FMUs`

### Step 9 – Datalog (points 13, 14) and cleanup (point 17)

- `container/datalog.c`: formats and quoting of decision 6; on Windows, rows written with `_fprintf_l()` and a C
  numeric `_locale_t` created once (decision 12), through a small printing macro shared with POSIX.
- `container/library.c`: `_WIN32`.
- Tests: `tests/integration/test_datalog.py` checks the precision of the time and of a real (e.g. 1e-8) and a string
  with a comma, read back with the `csv` module; `datalog2pcap` unchanged on its REF.

Commit message: `Write the datalog with full precision and quote its strings`

### Step 10 – Documentation

- `docs/user-guide/fmucontainer/datalog.md`: format of the CSV (precision, quoting of the strings).
- `docs/developer/`: the logger per instance and the macros (new short page, or a section of an existing one), the
  native tests and the sanitizer job.
- `CHANGELOG.md`: 🔴 **FIXED** entries (FMU Container): several instances in one process (logger), shutdown after a
  failed configuration in MT mode, locale and process priority of the host left unchanged, checks of
  `container.txt`; 🔵 **CHANGED**: precision and quoting of the datalog.
- Move this plan to `docs/local/done`.

Commit message: `Document the robustness fixes of the native runtime`

## Out of scope

- The remaining hand-written per-type lists (`container/datalog.c`, `container/fmi3.c`, `GETTER_3` / `SETTER_3` of
  `container/fmu.c`): a separate refactoring with `FOR_ALL_NUMERIC_TYPES`.
- Thread safety of the logging callback of the importer when worker threads log concurrently (MT mode).
