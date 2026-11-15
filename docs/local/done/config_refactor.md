# Plan: the reading of container.txt and the configuration of the container in config.c

**Created**: 15 November 2026 — **Status**: done (15 November 2026) — **Branch**: `config-refactor`, from `feature/perf-maintainability`
(`88036b9`) — **Roadmap**: not listed

`container/container.c` has 2 900 lines: about 1 400 of them read `container.txt` and configure the container, the
rest runs it (steps, events, clocks, threads). This plan moves the reading and the configuration to `config.c`, and
the generic reading of a text file, today in `config.c`, to a new module `file.c`, shared by `config.c` and
`datalog.c`. No change of behaviour, of format or of results: the code is moved and renamed only.

---

## 1. Current state

| Topic | Where | Notes |
|---|---|---|
| Reading of a text file | `config.c` / `config.h` (156 lines) | `config_file_t` (file, growing line buffer, line number, logger); `get_line()` (skips the comments), `config_file_open()`, `config_file_close()`, `config_file_version()` (`# Version <N>`), `config_line_to_host_decimal_point()`, `config_file_error()`; `CONFIG_FILE_SZ`, `STRLCPY` / `STRLCAT` |
| Users of the reader | `container.c`, `datalog.c` (`datalog_new()`, `datalog_configure()` read `datalog.txt`), `tests/test_config.c`, `tests/test_locale.c` | |
| Reading of `container.txt` | `container.c`, lines 1370 to 2364: `read_version()`, `read_flags()`, `read_conf_time_step()`, `read_conf_one_fmu()`, `read_conf_init_order()`, `read_conf_fmu()`, `read_conf_local()`, `read_conf_io()`, `read_conf_fmu_io*()`, `read_conf_fmu_start_values*()`, `read_conf_fmu_conversion()`, `read_conf_fmu_reset_trigger()`, `clock_kind_from_name()`, `read_conf_clocks()` | All `static`; macros `CONFIG_ERROR`, `CONFIG_GETLINE`, `CONFIG_ALLOC` (lines 1377 to 1390) used by them only |
| Configuration of the container | `container.c`, lines 2555 to 2760: `container_configure()` | Reads `container.txt` (the readers above), the datalog, instantiates the FMUs, allocates the buffers and the CS working set. Called by `fmi2Instantiate`, `fmi3Instantiate*` and the C tests (`test_configure.c`, `test_datalog.c`, `test_locale.c`, `test_malformed.c`, `test_threads_lifecycle.c`) |
| Dependencies | `read_conf_clocks()` calls `container_clock_needs_interval()`, a `static inline` of `container.c` (clocks) | The only static function of the rest of `container.c` used by the configuration |
| Between the two parts | `container.c`, lines 2365 to 2554: the threads of the multi-thread mode | Stays in `container.c` |
| Documentation | `docs/developer/native-runtime.md` (modules, prefixes), `docs/developer/container-txt-format.md` ("consumed by the C runtime (`container/container.c`)") | |

---

## 2. Goals

1. `container.c` holds the execution of the container only (about 1 500 lines).
2. `config.c` holds the reading of `container.txt` and the configuration of the container: `config_container()`.
3. `file.c` holds the reading of a text file, shared by `config.c` and `datalog.c`, with the prefix `file_`.
4. No change of behaviour: the C tests, the Python suite and the `REF-*` files are unchanged.

Non-goals: the other splits of `container.c` (clocks, threads); the reading of `datalog.txt` stays in `datalog.c`.

---

## 3. Decisions

Taken on 15 November 2026:

- **D1** — The reading of `container.txt` and the configuration of the container go to `config.c` (not a new module).
- **D2** — `container_configure()` becomes `config_container()`, declared in `config.h`.
- **D3** — Scope: the reading of `container.txt` and the configuration of the container only.
- **D4** — Branch `config-refactor`, one commit per step.
- **D5** — A new module `file.c` for the reading of a text file, shared by `config.c` and `datalog.c`.
- **D6 — Names** (Q1, Q2): in `file.c`, `file_t` (was `config_file_t`), `file_open()`, `file_close()`,
  `file_get_line()` (was `get_line()`), `file_version()`, `file_line_to_host_decimal_point()`, `file_error()`,
  `FILE_SZ` (was `CONFIG_FILE_SZ`), `STRLCPY` / `STRLCAT` unchanged in `file.h`. In `config.c`, the readers become
  `config_read_*()` (`static`); the macros `CONFIG_ERROR`, `CONFIG_GETLINE`, `CONFIG_ALLOC` unchanged, private to
  `config.c`.
- **D7 — Clock helper** (Q3): `container_clock_needs_interval()` is used by the configuration only: it moves to
  `config.c` as `config_clock_needs_interval()` (`static inline`), without calling `container_clock_is_periodic()`
  (its test written again: a light duplication), which stays in `container.c` for the runtime.
- **D8 — Tests** (Q4): `tests/test_config.c` (the line reader) becomes `tests/test_file.c`, the tests `file_*`; the
  tests of the configuration keep their files and call `config_container()`.
- **D9 — Step mode** (found at the step 2): the reader of the flags selected the step function of the container
  (`container->do_step`), whose candidates are static in `container.c`. `container.c` gets one public function,
  `container_set_mode(container, sequential, mt)`, which sets it (and the warm-up of the multi-thread mode) and logs
  the mode; `config_read_flags()` calls it.

---

## 4. Design

- `file.h` / `file.c`: the current content of `config.h` / `config.c`, renamed (D6). `config.h` includes `file.h`.
- `config.h` / `config.c`: `config_container()` and its readers (D6), moved from `container.c` without change of
  their code but the names of the reader (`file_*`) and of the readers (`config_read_*`); the comments that document
  each section of `container.txt` move with them; `config_clock_needs_interval()` (D7).
- `container.c`: the readers, `container_configure()` and `container_clock_needs_interval()` removed; `container.h`:
  the prototype of `container_configure()` removed.
- `datalog.c` / `datalog.h`: `file_t` and `file_*()`.
- `fmi2.c`, `fmi3.c`, the C tests: `config_container()`.
- `CMakeLists.txt`: `file.c file.h` in `CONTAINER_SOURCES`; `tests/test_file.c` (D8).

---

## 5. Steps

Each step: `cmake --workflow --preset darwin64` (C tests, without warning with `FMUTOOL_WARNINGS_AS_ERRORS`), the
tests of the container of the Python suite (`pytest -k "container or split or datalog or ssp"`), the `REF-*` files
unchanged.

### Step 1 — Module file.c

- `file.c` / `file.h` from `config.c` / `config.h` (D6); `config.c` and `config.h` keep nothing of the reader;
  `container.c`, `datalog.c` / `datalog.h`, `tests/test_locale.c` use `file_*`; `tests/test_file.c` (D8).

Commit message:
```
Container runtime: module file, the reading of a text file

The reading of a text file (a growing line buffer, the comments skipped, the
version header, the decimal point of the host, the errors with their line)
moves from config.c to file.c, with the prefix file_. It is used by the
reading of container.txt and of datalog.txt.
```

### Step 2 — The reading of container.txt and the configuration in config.c

- The readers and `container_configure()` move from `container.c` to `config.c` (D6, D7), as `config_container()`
  (D2); `fmi2.c`, `fmi3.c` and the C tests call it.

Commit message:
```
Container runtime: the reading of container.txt and the configuration in config.c

The readers of the sections of container.txt and the configuration of the
container (container_configure(), now config_container()) move from
container.c to config.c: container.c keeps the execution of the container.
```

### Step 3 — Documentation

- `docs/developer/native-runtime.md`: the modules `file_` and `config_`; `docs/developer/container-txt-format.md`:
  the file is read by `config.c`. No user documentation (no change of behaviour); no `CHANGELOG.md` entry.

Commit message:
```
Doc: the modules file and config of the container runtime
```

---

## 6. Found during the work (not in the scope)

- Result: `container.c` 2 898 → 1 714 lines, `config.c` 1 218 lines, `file.c` 156 lines.

---

## 7. Measurements

None: no change of behaviour.
