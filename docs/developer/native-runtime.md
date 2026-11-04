# Native runtime of the container

The runtime of a container FMU (`container/*.c`) is a C library that implements the FMI 2.0 and 3.0 APIs of the
container and drives its embedded FMUs. This page describes its conventions.

## Numeric types

The twelve numeric types of the runtime are listed once, by the X-macro `FOR_ALL_NUMERIC_TYPES` of `fmu.h`:
`X(variable, fmi_type, c_type)`, e.g. `X(uintegers16, UInteger16, uint16_t)`. A per-type list is an expansion of it,
the other types (`strings`, `binaries`, `clocks`) being written explicitly:

```c
#define FREE(variable, fmi_type, c_type) \
    free(container->vr_ ## variable);    \
    free(container-> variable);

    FOR_ALL_NUMERIC_TYPES(FREE)
    FREE(strings, String, char *)
#undef FREE
```

No separator is inserted between the expansions: each one must be a complete statement or declaration.

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
(`ctest -C Release --output-on-failure` from the build folder, or `container_tests <test name>` for one test). The
sources of the runtime are compiled again with the tests, so that the internal functions can be called.

- `test.h`: assertion macros (`TEST_ASSERT`, `TEST_ASSERT_EQUAL_INT`); a test is a function that returns 0 on
  success, registered in the table of `test_main.c`.
- `stub_fmu.c`: an FMI 2.0 Co-Simulation FMU built with the tests. Its behaviour depends on the GUID given to
  `fmi2Instantiate` (e.g. `{stub-fail-instantiate}`); each type has 16 variables, any other VR is an error.
- Fixtures: `tests/data/one_fmu/container.txt.in` is turned by CMake (`container_fixture()`) into
  `<build folder>/fixtures/<name>/container.txt`, with the stub FMU in `00/binaries/<platform>/`. The tests of
  malformed files (`test_malformed.c`) rewrite one line of the fixture `one_fmu` into the fixture `malformed`.

## Sanitizers

With `-DFMUTOOL_SANITIZE=ON` (GCC, Clang), the runtime and its tests are built with AddressSanitizer and
UndefinedBehaviorSanitizer; any undefined behaviour aborts. The CI job `sanitizers` (Linux) runs the C tests with
the leak detection, then the integration tests with the instrumented `linux64` runtime, the ASan runtime being
loaded first in Python (`LD_PRELOAD`).
