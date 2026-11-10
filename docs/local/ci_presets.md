# Native builds of the CI through CMake presets

## Context

The root `CMakeLists.txt` (see `docs/local/done/cmake_superbuild.md`) builds both native components in one build
tree, but the CI still builds each component on its own: 7 entries in the `build-native` matrix of
`.github/workflows/ci.yml`, one per component and platform. This has several costs:

- win64 and linux64 are configured and built twice (`container`, then `remoting`).
- Two artifacts end up in the same folder (`container-win64` and `remoting-win64` both go to `resources/win64/`), so
  the test jobs need one `download-artifact` step per artifact (7 in `tests-linux`).
- The configure arguments are repeated in the matrix, some of them useless: `-DCMAKE_CXX_COMPILER` (the projects are
  C only), `-DCMAKE_BUILD_TYPE` with the multi-config Visual Studio generator, the default compilers given explicitly.
- `build-native.yml` decides whether to run CTest from the component name (`if: inputs.source_dir == 'container'`).
- The `sanitizers` job has its own `cmake` commands on `container/`.

A CMake build tree targets one architecture only (`-A x64` or `-A Win32` with Visual Studio, `-m32` through
`BUILD_32` on Linux), so the 64-bit and 32-bit binaries of an OS need two build trees. They can still be built from
the same root project, on the same runner, one after the other.

Goal: one CMake preset per platform, used the same way by the CI and locally; one native build job and one artifact
per OS (3 jobs instead of 7); the standalone component projects are removed.

## Decisions (2026-11-10)

| # | Question | Decision |
|---|----------|----------|
| 1 | Grouping of the CI builds | One job per OS (Windows: win64 + win32, Linux: linux64 + linux32, macOS: darwin64), each building its platforms from the root project in separate build trees |
| 2 | Description of the builds | `CMakePresets.json` at the repository root: one configure, build, test and workflow preset per platform |
| 3 | Standalone projects `container/` and `remoting/` | No longer built by the CI, then removed in a dedicated step: they become plain subdirectories of the root project |
| 4 | Remoting on macOS | Not built (`FMUTOOL_BUILD_REMOTING=OFF` in `darwin64`): the CI produces exactly what the wheel ships |
| 5 | `sanitizers` job | Dedicated preset `linux64-sanitize`, also usable locally |
| 6 | Build folders of the presets | `build-native/<preset>` (`build-native/` is already ignored by git) |
| 7 | Minimum CMake version | 3.25 everywhere (needed by the workflow presets, presets schema version 6) |
| 8 | Documented build commands | Presets only (`cmake --workflow --preset <platform>`); the manual `cmake -B build-native` is no longer documented |

Note: a workflow preset can only use one configure preset, so it cannot chain win64 and win32. The CI job runs the
workflow presets of its OS one after the other (`cmake --workflow --preset win64`, then `--preset win32`).

## Step 1 — `CMakePresets.json`

- `cmake_minimum_required(VERSION 3.25)` in the root `CMakeLists.txt`, `container/CMakeLists.txt` and
  `remoting/CMakeLists.txt`.
- `CMakePresets.json`, schema version 6:
  - hidden configure preset `base`: `binaryDir` = `${sourceDir}/build-native/${presetName}`;
  - hidden configure presets per OS, with a `condition` on `${hostSystemName}` (`Windows`, `Linux`, `Darwin`), so
    that `cmake --list-presets` only shows the configure presets of the host (the other ones are refused);
  - configure presets (no `generator`: the default one of the host, Visual Studio on Windows):

    | Preset | OS | Settings |
    |--------|----|----------|
    | `win64` | Windows | `architecture` `x64` |
    | `win32` | Windows | `architecture` `Win32`, `FMUTOOL_BUILD_CONTAINER=OFF` |
    | `linux64` | Linux | — |
    | `linux32` | Linux | `BUILD_32=ON`, `FMUTOOL_BUILD_CONTAINER=OFF` |
    | `darwin64` | macOS | `FMUTOOL_BUILD_REMOTING=OFF` |
    | `linux64-sanitize` | Linux | `CMAKE_BUILD_TYPE=RelWithDebInfo`, `FMUTOOL_SANITIZE=ON`, `FMUTOOL_BUILD_REMOTING=OFF` |

  - one build preset per configure preset (`configuration` `Release`, `RelWithDebInfo` for `linux64-sanitize`);
  - one test preset per configure preset that builds the container (`win64`, `linux64`, `darwin64`,
    `linux64-sanitize`), with `output.outputOnFailure`;
  - one workflow preset per configure preset: configure, build and, when it exists, test.
- `.gitignore`: unchanged (`build-native` already covers the subfolders).

Verification (macOS): `cmake --list-presets` lists the `darwin64` configure preset only; `cmake --workflow --preset darwin64` from a clean
`build-native/` builds `resources/darwin64/container.dylib` and runs `container_tests`; no `client_sm.dylib` is built.
The Windows and Linux presets are checked by the CI in step 2.

Commit message:
```
CMake: add presets for every native platform

CMakePresets.json describes the builds of win64, win32, linux64, linux32,
darwin64 and the sanitized linux64 runtime, each in build-native/<preset>.
cmake --workflow --preset <platform> configures, builds and tests. The
minimum CMake version is raised to 3.25 (workflow presets).
```

## Step 2 — CI: one native build job per OS

- `.github/workflows/build-native.yml`:
  - inputs: `os`, `presets` (the workflow presets to run, separated by spaces), `artifact_name`, `resource_subdirs`
    (the `resources/<platform>` folders to upload), `install_multilib`; `source_dir`, `configure_args` and
    `build_args` are removed;
  - one step runs `cmake --workflow --preset <p>` for each preset (`shell: bash`, so the same loop works on
    Windows); the tests run through the workflow presets, the `if: inputs.source_dir == 'container'` step goes away;
  - the artifact holds the `resources/<platform>` folders of the OS (`win64/` and `win32/` for Windows...).
- `.github/workflows/ci.yml`, `build-native` matrix reduced to 3 entries:

  | OS | Runner | Presets | Artifact |
  |----|--------|---------|----------|
  | Windows | `windows-latest` | `win64 win32` | `native-windows` |
  | Linux | `ubuntu-22.04` (glibc 2.35, unchanged) | `linux64 linux32` (`install_multilib`) | `native-linux` |
  | macOS | `macos-latest` | `darwin64` | `native-macos` |

- Downloads in the test jobs, into `fmu_manipulation_toolbox/resources/`:
  - `tests-win64`: `native-windows`;
  - `tests-linux`: every artifact, in one step (`pattern: native-*`, `merge-multiple: true`);
  - `tests-macos`: `native-macos`;
  - `sanitizers`: every artifact, in one step, then `cmake --workflow --preset linux64-sanitize` replaces
    `resources/linux64/container.so` with the instrumented runtime and runs the native tests (`UBSAN_OPTIONS` kept).
    The integration test step is unchanged.
- `release.yml`: unchanged (it calls `ci.yml`).
- Comment at the top of the root `CMakeLists.txt`: the CI builds the root project through the presets.

Verification: the CI of the pull request is green; the `package` artifact passes `tools/dist_inventory.py --check`
(same binaries as before, `tests/data/packaging` unchanged); `smoke-wheel` passes on the 3 OS.

Commit message:
```
CI: build the native binaries through the CMake presets

One job per OS builds every platform of this OS from the root project
(Windows: win64 + win32, Linux: linux64 + linux32, macOS: darwin64) and
uploads one artifact. The test jobs download them in one step. The
sanitizers job uses the linux64-sanitize preset.
```

## Step 3 — Remove the standalone component projects

- `container/CMakeLists.txt`: remove `cmake_minimum_required()`, `include(../cmake/fmutool.cmake)` and
  `include(CTest)` (done by the root project); `project(container C)` and `if(BUILD_TESTING)` are kept.
- `remoting/CMakeLists.txt`: remove `cmake_minimum_required()`, the `BUILD_32` block (handled by the root project)
  and `include(../cmake/fmutool.cmake)`; `project(remoting C)` is kept.
- `cmake/fmutool.cmake`: header comment updated (included once, by the root project); `include_guard(GLOBAL)` kept as
  a safety.
- Root `CMakeLists.txt`: header comment, the components are no longer standalone projects.
- `tools/bench_container.py`: the docstring gives the preset of the host instead of `cmake -B build -S container`.

Verification (macOS): `cmake --workflow --preset darwin64` from a clean `build-native/`; a plain
`cmake -B <folder>` with both options `ON` still builds `container` and `remoting` (the remoting code compiles on
macOS even though it is not shipped); `cmake -S container -B <folder>` now fails (expected). The CI of the pull
request is green.

Commit message:
```
CMake: remove the standalone container and remoting projects

The components are only built from the root project: their CMakeLists.txt
no longer declare a minimum version, include the common settings or handle
BUILD_32 on their own.
```

## Step 4 — Documentation

- `docs/installation.md`, step 3:
  - CMake 3.25 or higher in the requirements;
  - the presets table (platform, OS, components built) and the commands: `cmake --workflow --preset <platform>`,
    `cmake --list-presets`; the build options given with `cmake --preset <platform> -D<option>=<value>` followed by
    `cmake --build --preset <platform>`;
  - the options table: `BUILD_32` and the `FMUTOOL_BUILD_*` options no longer mention "root project only" or
    "remoting"; `BUILD_32` and the 32-bit Windows build are covered by the `linux32` and `win32` presets;
  - the sections "Container code only" and "Remoting code only" are removed;
  - the sanitized runtime: the `linux64-sanitize` preset.
- `README.md`: CMake 3.25 in both requirement lists; the build commands with the presets; the sentence on the
  standalone component builds is removed.
- `CHANGELOG.md`: CMake presets, CMake 3.25 minimum, standalone component projects removed.

Verification: `mkdocs build --strict`.

Commit message:
```
Doc: build the native components with the CMake presets
```
