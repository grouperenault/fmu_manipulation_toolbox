# Umbrella CMake project for the native components

## Context

The two native components, `container/` and `remoting/`, are two independent CMake projects sharing their build
settings through `cmake/fmutool.cmake`. This stays the way the CI builds them (one project per matrix entry, see
`.github/workflows/build-native.yml`), because the platform matrices differ (remoting: 32 and 64 bits; container:
64 bits and macOS).

Missing: a single entry point to build everything locally, and a unified view of the native code in an IDE. A
`CMakeLists.txt` that would `add_subdirectory()` both projects fails today, because `fmutool.cmake` defines the
targets `fmutool_flags` and `version_h` each time it is included ("target already exists").

## Decisions (2026-11-08)

| # | Question | Decision |
|---|----------|----------|
| 1 | Layout | Keep `container/`, `remoting/` and `cmake/` where they are (no `native/` folder) |
| 2 | Umbrella project | A `CMakeLists.txt` at the repository root, `add_subdirectory()` of both projects |
| 3 | Standalone projects | Still buildable on their own; the CI is unchanged |
| 4 | Selection | Options `FMUTOOL_BUILD_CONTAINER` and `FMUTOOL_BUILD_REMOTING`, both `ON` by default |

## Step 1 — Re-entrant `cmake/fmutool.cmake`

- `include_guard(GLOBAL)`: the common targets, options and functions are defined once.
- `version.h` generated in `${CMAKE_BINARY_DIR}` (unchanged for a standalone build), exposed as
  `FMUTOOL_GENERATED_DIR` and added to the include directories by `fmutool_native_target()`.
- `container/CMakeLists.txt`: the tests include `FMUTOOL_GENERATED_DIR` for `version.h`.
- `remoting/CMakeLists.txt`: the `-m32` flag of `BUILD_32` is only appended by the top-level project.

Verification: both projects configure and build standalone from a clean build folder, `ctest` passes for `container`.

Commit message:
```
CMake: make cmake/fmutool.cmake re-entrant

The common targets (fmutool_flags, version_h) are defined once, so that both
native projects can be added to the same build tree.
```

## Step 2 — Root `CMakeLists.txt`

- `project(fmutool_native C)`, handles `BUILD_32` before `project()` (same as `remoting`), includes
  `cmake/fmutool.cmake` (so that its variables are visible from both subdirectories) and `CTest`.
- `add_subdirectory(container)` / `add_subdirectory(remoting)` according to the two options.
- `.gitignore`: the build folder `build-native/`.

Verification: `cmake -B build-native && cmake --build build-native && ctest --test-dir build-native` from a clean
folder; same binaries in `fmu_manipulation_toolbox/resources/darwin64/`; each option `OFF` in turn.

Commit message:
```
CMake: add a root project building both native components

cmake -B build-native builds container and remoting in one build tree. The
options FMUTOOL_BUILD_CONTAINER and FMUTOOL_BUILD_REMOTING select them. The
standalone projects, used by the CI, are unchanged.
```

## Step 3 — Documentation

- `docs/installation.md` (step 3): the root project as the simplest way, the two new options; the standalone
  projects kept for a single component or a 32-bit build.
- `README.md`: the build commands.
- `CHANGELOG.md`.

Commit message:
```
Doc: build the native components from the root CMake project
```
