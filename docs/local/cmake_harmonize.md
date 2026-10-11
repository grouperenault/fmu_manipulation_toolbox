# Harmonization of the native CMake projects

## Context

The two native components, `container/` and `remoting/`, are built by two independent `CMakeLists.txt` that drifted
apart:

- `container/CMakeLists.txt` is the more complete one: build type defaulting to Release, an interface target carrying
  the warning flags (`container_flags`), release-time optimizations, IPO/LTO, PGO, an FMI sanity check, a build-time
  `version.h` and a build summary. It is also long (260 lines), with mixed tabs/spaces and inconsistent casing.
- `remoting/CMakeLists.txt` has no warning flags, no default build type, C99, and dead code: `CMAKE_C_STANDARD` set
  twice, `VERSION "1.0"` / `REMOTING_VERSION` never used, `BUILD_TESTER` option never used, `version.h` generated both
  at configure time (with a `set(GIT_TAG, ...)` typo) and at build time, `-m32` passed through the `COMPILE_OPTIONS`
  property.
- Duplicated in both projects: `FMI_PLATFORM` detection, the build-time `version.h` target, and the identical files
  `cmake/gen_version.cmake` and `version.h.in`.

Goal: both `CMakeLists.txt` stay simple and readable, the common logic lives in one place.

## Decisions (2026-10-11)

| # | Question | Decision |
|---|----------|----------|
| 1 | Sharing of the common logic | A `cmake/` directory at the repository root, included by both `CMakeLists.txt` |
| 2 | Build settings applied to `remoting` | All of the `container` ones: warnings, Release by default, release optimizations, IPO/LTO, PGO |
| 3 | C standard of `remoting` | C23 (same as `container`) |
| 4 | Clean-up of `container/CMakeLists.txt` | Shorter build summary; PGO moved to its own module; details fixed (indentation, casing, `message(STATUS)`, trailing spaces) |
| 5 | Warnings raised in `remoting` by the new flags (71 with Clang, mostly unused parameters of FMI stubs) | Fix them in the C code (dedicated step), same idiom as `container`: `(void)x; /* unused parameter */` |
| 6 | Name of the build options | `FMUTOOL_` prefix: `FMUTOOL_WARNINGS_AS_ERRORS`, `FMUTOOL_STRICT_CONVERSION`, `FMUTOOL_PGO` |

Kept as is: the `BUILD_32` option of `remoting` (used by the CI and the documentation), the output directory
`fmu_manipulation_toolbox/resources/<FMI_PLATFORM>`, the target names (`container`, `server_sm`, `client_sm`), the
`build.bat` helpers.

Verification rule for every step: both projects configure and build on macOS (Clang) from a clean build directory,
the produced binaries land in `fmu_manipulation_toolbox/resources/darwin64/`, and the exported symbols of
`container.dylib` and `client_sm.dylib` are unchanged. MSVC, GCC and the 32-bit builds are checked by the CI
(`.github/workflows/ci.yml`, `build-native` job).

## Step 0 — Plan

This document.

Commit message:

```
Plan the harmonization of the native CMake projects (cmake_harmonize step 0)
```

## Step 1 — Shared CMake module, used by `container`

Create `cmake/` at the repository root:

- `cmake/fmutool.cmake`, included right after `project()`:
  - options `FMUTOOL_WARNINGS_AS_ERRORS`, `FMUTOOL_STRICT_CONVERSION`;
  - C23, build type defaulting to Release;
  - `FMI_PLATFORM` detection (from `WIN32`/`APPLE` and `CMAKE_SIZEOF_VOID_P`, so a `-m32` build yields `linux32`),
    `Threads` on non-Windows;
  - interface target `fmutool_flags` (the warning flags and release optimizations of today's `container_flags`);
  - build-time `version_h` target (uses `cmake/gen_version.cmake` and `cmake/version.h.in`);
  - function `fmutool_native_target(<target>)`: links `fmutool_flags`, adds the `fmi/` and binary include
    directories, hidden visibility, no `lib` prefix, output in `resources/<FMI_PLATFORM>`, IPO when supported, PGO,
    dependency on `version_h`;
  - function `fmutool_summary()`: a few `message(STATUS)` lines (build type, compiler, platform, options).
- `cmake/pgo.cmake`: the `FMUTOOL_PGO` cache variable (`OFF`/`GENERATE`/`USE`), its workflow comment, and the function
  applying it to a target.
- `cmake/gen_version.cmake` and `cmake/version.h.in`: moved from `container/` (`git mv`).

Rewrite `container/CMakeLists.txt` on top of it: project, include, FMI sanity check, `add_library`, platform libraries
(`Threads`, `Imagehlp`), `fmutool_native_target(container)`, `fmutool_summary()`.

Note: the output directory is now the same for every configuration. With Visual Studio, a Debug build also writes into
`resources/<FMI_PLATFORM>` (it already did on Linux and macOS); before, only the Release build did.

Result: compile flags and exported symbols of `container.dylib` identical to the previous build; `container/CMakeLists.txt`
goes from 260 to 44 lines.

Commit message:

```
Move the common CMake logic to a shared cmake/ module (cmake_harmonize step 1)
```

## Step 2 — `remoting` on the shared module

Rewrite `remoting/CMakeLists.txt` on top of `cmake/fmutool.cmake`:

- `BUILD_32` adds `-m32` before `project()` so that `CMAKE_SIZEOF_VOID_P` and `FMI_PLATFORM` follow;
- `config.h` is still generated (`HAVE_SEMTIMEDOP`);
- `fmutool_native_target()` on `server_sm` and `client_sm`, platform libraries (`dl`, `rt`, `Threads`) kept;
- dead code removed: duplicated `CMAKE_C_STANDARD`, `VERSION` and `REMOTING_VERSION` (`config.h.in`), `BUILD_TESTER`,
  configure-time `version.h`;
- `remoting/cmake/` and `remoting/version.h.in` deleted.

The new warning flags are active from this step on; the warnings are fixed in step 3.

Result: `client_sm.dylib` exports the same 44 `fmi2*` functions; the 14 internal `communication_*` / `process_*`
symbols are no longer exported (hidden visibility). 69 warnings with Clang.

Commit message:

```
Build remoting with the shared CMake module, in C23 (cmake_harmonize step 2)
```

## Step 3 — Fix the warnings of `remoting`

Fix the warnings raised by the shared flags in `remoting/*.c` (unused parameters, prototypes without `(void)`, and
any other one reported). No behaviour change. Target: 0 warning with Clang, like `container`.

Commit message:

```
Fix the compiler warnings of remoting (cmake_harmonize step 3)
```

## Step 4 — User documentation

- `docs/installation.md`, "Compile C Components": both components require a C23 compiler; the build options
  (`FMUTOOL_WARNINGS_AS_ERRORS`, `FMUTOOL_STRICT_CONVERSION`, `FMUTOOL_PGO`, `BUILD_32`) and the PGO workflow.
- `CHANGELOG.md`: one entry.
- Move this plan to `docs/local/done/`.

Commit message:

```
Document the native build options (cmake_harmonize step 4)
```
