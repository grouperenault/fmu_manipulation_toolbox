# Native runtime of the container

The runtime of a container FMU (`container/*.c`) is a C library that implements the FMI 2.0 and 3.0 APIs of the
container and drives its embedded FMUs. This page describes its conventions.

## Numeric types

The twelve numeric types of the runtime are listed once, by the X-macro `FOR_ALL_NUMERIC_TYPES` of `fmu.h`:
`X(variable, fmi_type, c_type)`, e.g. `X(uintegers16, UInteger16, uint16_t)`. A per-type list is an expansion of it,
the other types (`strings`, `binaries`, `clocks`) being written explicitly:

```c
#define FREE(variable, fmi_type, c_type)       \
    free(container-> variable .links);         \
    free(container-> variable .ports);         \
    free(container-> variable .locals);

    FOR_ALL_NUMERIC_TYPES(FREE)
    FREE(strings, String, fmu_string_t)
#undef FREE
```

No separator is inserted between the expansions: each one must be a complete statement or declaration.

The container stores each type in one structure, `container_<type>_t`, named by the type in `container_t`: its local
variables (`container->reals64.locals`, `.nb_locals`: the values conveyed from one FMU to another and the variables
of the container), its ports (`.ports`, `.nb_ports`, by value reference) and the storage of their links (`.links`).

## Modules

Each module of the runtime prefixes its functions and its types with its name: `cache_` (`cache.c`: the values set by
the importer and their synchronization with the embedded FMUs, see [DoStep FMI
Sequence](dostep-fmi-sequence.md#values-set-by-the-importer)), `datalog_`, `fmu_`/`fmu` (embedded FMUs), `logger_`,
`path_` (`path.c`: the paths of the file system and the `file` URIs of RFC 3986), `solver_`, `thread_`...
`container_` is the container itself (`container.c`), whose FMI APIs are in `fmi2.c` and `fmi3.c`.

The resource locations follow the FMI version of each embedded FMU: a `file` URI for FMI 2.0
(`file:///C:/…/resources`, separators `/`, percent-encoded octets, `path_to_uri()`), a native path with a trailing
separator for FMI 3.0, or `NULL` when the FMU has no `resources` folder. The builder gives an empty `resources` folder
to every embedded FMU that has none, since some FMUs do not expect a `NULL` `resourcePath` (`strdup(resourcePath)`):
`NULL` only remains for the containers built before. The resource location of the container itself, given by its
importer, is decoded by `path_from_uri()`.

## Logger

Each instance of the container has its own logger, `container_t.logger` (`logger_t`: FMI version, callback and
environment given by the importer, instance name, debug flag). Several instances in one process do not share
anything, and `fmi2SetDebugLogging` / `fmi3SetDebugLogging` only change their own instance.

The messages are written with the macros `LOGGER_DEBUG(...)`, `LOGGER_WARNING(...)` and `LOGGER_ERROR(...)` of
`logger.h`. They log through the variable `logger` (`const logger_t *`) of the calling scope:

```c
fmu_status_t container_do_something(container_t *container) {
    const logger_t *logger = &container->logger;

    LOGGER_ERROR("Container: cannot do something (time=%e).", container->time);
    ...
}
```

The modules without a container get the logger as a parameter (`library_load()`, `convert_new()`,
`profile_new()`, `datalog_new()`) or through `config_file_t.logger`; an embedded FMU uses the one of its container
(`fmu->container->logger`). A `NULL` logger, or a `NULL` callback (allowed by FMI 3.0), sends no message. The
debug messages are sent only when the debug flag is set.

## Locale

The configuration files are read with a decimal dot whatever the locale of the importer. An FMU must not change the
global settings of its importer (FMI 3.0, 2.2.1), so the locale is never changed, even for a thread: in a line of numbers,
the dots are replaced by the decimal point of the locale before `sscanf()` (`config_line_to_host_decimal_point()`).

The configuration is refused if the decimal point of the locale has several bytes (`fa_IR.UTF-8`, for instance):
`sscanf()` may not read it (macOS), and it would misread the values.

The datalog follows the locale: its reals use its decimal point, and its columns are separated by a semicolon with a
decimal comma.

The embedded FMUs follow the locale of the importer too, in their logs for instance.

## Native tests

`container/tests` holds the C tests of the runtime, built by CMake as `container_tests` and run by CTest
(`cmake --workflow --preset <preset>` or `ctest --preset <preset>` from the root of the repository, see
[Compile C Components](../installation.md#step-3-compile-c-components), or `container_tests <test name>` for one test). The
sources of the runtime are compiled again with the tests, so that the internal functions can be called.

- `test.h`: assertion macros (`TEST_ASSERT`, `TEST_ASSERT_EQUAL_INT`); a test is a function that returns 0 on
  success, registered in the table of `test_main.c`.
- `stub_fmu.c`: an FMI 2.0 Co-Simulation FMU built with the tests. Its behaviour depends on the GUID given to
  `fmi2Instantiate` (e.g. `{stub-fail-instantiate}`, or `{stub-slow}`, whose steps last 2 ms); each type has 16
  variables, any other VR is an error.
- `stub_xcp_fmi2.c`, `stub_xcp_fmi3.c`: FMUs of FMI-LS-XCP (descriptors in `tests/data/ls-xcp` of the repository).
  Their XCP service only writes a journal, `<resources>/xcp.log`, of the configuration they receive and of when the
  service starts; the fixtures `xcp_fmi2` and `xcp_fmi3` (`tests/data/xcp/container_fmi<2|3>.txt`) check the
  Configuration Mode, the order of the start values and the cache of the values set by the importer (`cache_*`
  tests: nothing reaches the FMU before its synchronization, read after write, refused value).
- Fixtures: `tests/data/one_fmu/container.txt.in` is turned by CMake (`container_fixture()`) into
  `<build folder>/fixtures/<name>/container.txt`, with the stub FMU in `00/binaries/<platform>/`. The tests of
  malformed files (`test_malformed.c`) rewrite one line of the fixture `one_fmu` into the fixture `malformed`.
  `tests/data/two_fmus/container.txt.in` (`two_fmus_fixture()`) embeds a light stub and a slow one in the
  multi-thread mode, with a threshold that makes the slow one heavy (`mt_hybrid`), both (`mt_all_heavy`) or none
  (`mt_no_heavy`): `test_threads_lifecycle.c` checks the warm-up, the dispatch of the FMUs to the workers and the stop
  of the threads.

## Threads

The multi-thread mode (see [DoStep FMI Sequence](dostep-fmi-sequence.md#notes)) starts its worker threads at the end
of its warm-up (`container_dispatch()`), one per worker of the pool, and stops them in `container_free()`.
`thread.c` gives the portable primitives: the threads, `thread_nb_cores()`, the barriers (`SYNCHRONIZATION_BARRIER`
on Windows, `pthread_barrier_t` on Linux, a barrier on `dispatch_semaphore` on macOS, which has none) and a gate that
holds the workers until they are all launched. The steps are timed by `profile_now()` (`profile.c`: a monotonic clock
in ns, `QueryPerformanceCounter` or `CLOCK_MONOTONIC`), the clock of the profiling too.

## Sanitizers

With `-DFMUTOOL_SANITIZE=ON` (GCC, Clang), the runtime and its tests are built with AddressSanitizer and
UndefinedBehaviorSanitizer; any undefined behaviour aborts. The preset `linux64-sanitize` builds and tests the
instrumented runtime: `cmake --workflow --preset linux64-sanitize`. The CI job `sanitizers` (Linux) runs the C tests with
the leak detection, then the integration tests with the instrumented `linux64` runtime, the ASan runtime being
loaded first in Python (`LD_PRELOAD`).

ThreadSanitizer has no preset: on Linux or macOS (Clang), configure a build folder with
`-DCMAKE_C_FLAGS=-fsanitize=thread` and the same flag for the linker (`CMAKE_EXE_LINKER_FLAGS`,
`CMAKE_SHARED_LINKER_FLAGS`, `CMAKE_MODULE_LINKER_FLAGS`), then build and run `container_tests` only (the target
`container` would replace the runtime of the package).
