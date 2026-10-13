# Plan: compile the sources of an FMU for the host platform

**Created**: 13 October 2026 — **Status**: done (13 October 2026); MSVC path to be checked on Windows — **Roadmap**: not listed

Some FMUs embed their C sources (`sources/`) but no binary for the platform of the user (for example
`tests/data/remoting/bouncing_ball-win32.fmu`: FMI 2.0, `win32` binary only). The goal is a Python class that
compiles these sources into `binaries/<host platform>/<modelIdentifier>.<ext>`, usable from the Python API and
from a new button in the `fmutool` GUI.

---

## 1. Current state

| Topic | Where | Notes |
|---|---|---|
| Operations | `operations.py` (`OperationAbstract`) | `closure()` runs once after the descriptor walk; `self.fmu.tmp_directory` is the extracted FMU, saved by `FMU.repack()` |
| Operations outside `operations.py` | `remoting.py` | Same pattern: a module holding its operations, imported by the GUI and the CLI |
| GUI buttons | `gui/fmutool/__main__.py:89` (`operations_list`) | 15 buttons, 5 per row; tooltip taken from `help.py` (usage key) |
| CLI | `cli/fmutool.py` | e.g. `-remove-sources` (`append_const`) |
| MCP | `assistant/fmutools.py:44`, `assistant/server.py:739` | `remove_sources` is exposed |
| Sources list | FMI 2.0: `<SourceFiles><File name=…/>` in each interface (optional); FMI 3.0: `sources/buildDescription.xml` (`BuildConfiguration modelIdentifier`, `SourceFileSet` with `language`, `compiler`, `compilerOptions`, `SourceFile`, `PreprocessorDefinition`, `IncludeDirectory`) |
| Platform names | `container/builder.py:978` | FMI 2.0: `win32`, `win64`, `linux64`, `darwin64`; FMI 3.0: `x86_64-windows`, `x86-windows`, `x86_64-linux`, `aarch64-linux`, `x86_64-darwin`, `aarch64-darwin` |
| FMI headers | `fmi/*.h` at the repository root | Not packaged; `resources/fmi-2.0` and `resources/fmi-3.0` only hold the XSD |
| Test FMUs with sources | `tests/data/compile/{2.0,3.0}/BouncingBall.fmu` (Reference FMUs v0.0.41, unmodified) | Added for this plan, see §6 |

---

## 2. Goals

1. A reusable class compiling the embedded sources for the **host platform only** (OS and architecture of the
   running Python interpreter). No cross-compilation.
2. **Own implementation**: direct call of the C compiler through `subprocess`, no new dependency (neither fmpy
   nor CMake).
3. If the binary of the host platform **already exists, nothing is done** (informative log message).
4. A new button in the `fmutool` GUI; the compiler output is shown in the log widget.
5. Clear errors (`OperationError`): no `sources/`, no sources list, no compiler found, compilation failure (with
   the compiler output in the log).

---

## 3. Decisions

Taken on 13 October 2026:

- **D1 — Backend**: own implementation (direct compiler call through `subprocess`), no fmpy, no CMake.
- **D2 — Target**: host platform only.
- **D3 — Existing binary**: do nothing, log an informative message. The check is the presence of the file only:
  a binary of another architecture (e.g. the `darwin64` binary of the FMI 2.0 Reference FMU is x86_64 only and
  does not load on Apple Silicon) is kept; this limit is documented.
- **D4 — Other integrations**: CLI option `-compile-sources`. No MCP tool. Automated tests based on the
  Reference FMUs (§6).
- **D5 — FMI headers**: move `fmi/` (repository root) to `fmu_manipulation_toolbox/resources/fmi/`, declare the
  headers in `package-data`, update `cmake/fmutool.cmake:114` and `container/CMakeLists.txt:11` (and the comment
  of `MANIFEST.in`). This directory is appended to the include path, after `sources/` and the include directories
  of the build description.
- **D6 — Compiler on Windows**: MSVC discovered with `vswhere.exe` + `vcvarsall.bat` (environment captured once),
  fallback on `cl.exe` from `PATH`. On Linux/macOS: `$CC` if set, else `cc`.
- **D7 — Missing sources list** (FMI 2.0 without `<SourceFiles>`, FMI 3.0 without `buildDescription.xml`):
  `OperationError`, no guess. (Compiling every `*.c` was rejected: it fails on both Reference FMUs — FMI 2.0
  `all.c` includes the other `.c` files, FMI 3.0 needs `FMI_VERSION` from the build description.)
- **D8 — GUI button**: `Compile sources`, colour class `modify`, inserted right after `Remove sources` (the
  following buttons shift; a 4th row appears).
- **D9 — GUI responsiveness**: synchronous, as the other operations; the compiler output is streamed to the log.
- **D10 — Function prefix**: sources written for static linking prefix the FMI functions with the model
  identifier (the Reference FMUs do it unless `DISABLE_PREFIX` is defined), which gives an unusable shared
  library. Always define `DISABLE_PREFIX`, plus `FMI3_OVERRIDE_FUNCTION_PREFIX` for FMI 3.0 (mechanism of the
  standard headers; the FMI 2.0 headers have none). Checked on both Reference FMUs.
- **D11 — Errors**: every error is an `OperationError` (no dedicated exception class).
- **D12 — C++** (taken on 13 October 2026): supported. A source is C++ when its `SourceFileSet` has a `language`
  starting with `C++`, or (no `language`) when its suffix is `.cpp`, `.cc`, `.cxx` or `.c++`. C++ sources are
  compiled with `$CXX` (default `c++`) on Linux/macOS, `cl /TP` on Windows; the link uses the C++ compiler as soon as
  one source is C++.
- **D13 — `compilerOptions`**: applied (split as a shell command line) only when the `compiler` attribute of the
  `SourceFileSet` matches the compiler used (`gcc`, `clang`, `cl`, compared with the name of the executable);
  otherwise ignored with a warning (also when `compiler` is absent).
- **D14 — `<Library>`**: linked by name (`-l<name>`, `<name>.lib` with MSVC); `version` and `external` ignored.
- **D15 — MSVC runtime**: static (`/MT`), so that the DLL does not need the Visual C++ redistributable.
- **D16 — Logs of the compilation** (taken on 13 October 2026, homogeneity with the other operations): one short
  `INFO` line per step (`Compiling 'sources/model.c'.`, `Linking 'BouncingBall.dylib'.`), the full command line in
  `DEBUG`. The compiler output of a step is kept and logged once the step ends: as `WARNING` if it succeeds, as
  `ERROR` if it fails, nothing if it is silent; the temporary paths are shortened (`sources/model.c`) and the
  banner lines of MSVC (name of the source, `Creating library …`) are dropped. This replaces the line-by-line
  streaming of D9 (the progress is given by the `INFO` steps).

---

## 4. Design

New module `fmu_manipulation_toolbox/compiler.py` (same pattern as `remoting.py`):

```python
class SourceCompiler:
    """Compile the `sources/` of an extracted FMU for the host platform."""

    def __init__(self, fmu_directory: Path, fmi_version: int): ...

    @staticmethod
    def host_platform(fmi_version: int) -> str          # e.g. "darwin64" / "aarch64-darwin"
    @staticmethod
    def library_suffix() -> str                          # ".dll" / ".so" / ".dylib"
    def binary_path(self, model_identifier: str) -> Path # binaries/<platform>/<id><suffix>
    def build_configurations(self, model_description) -> list[BuildConfiguration]
        # FMI 2.0: one per distinct modelIdentifier of the interfaces (<SourceFiles>)
        # FMI 3.0: parsed from sources/buildDescription.xml
    def compile(self, configuration) -> Path             # raises OperationError; compiler output in the log


class BuildConfiguration:     # dataclass
    model_identifier: str
    source_files: list[Path]
    include_directories: list[Path]
    definitions: dict[str, str | None]


class OperationCompileSources(OperationAbstract):
    """Compile the embedded sources when the binary of the host platform is missing."""
    # closure(): for each configuration, skip if binary_path() exists (D3), else compile.
```

Compiler command lines (built in one place, logged at `INFO` before execution):

- Linux: `cc -shared -fPIC -O2 -fvisibility=hidden -I<inc>… -D<def>… <sources> -o <id>.so` (+ `-lm`).
- Definitions of D10 (`DISABLE_PREFIX`, `FMI3_OVERRIDE_FUNCTION_PREFIX`) are added to those of the build description.
- macOS: `cc -dynamiclib -O2 -I<inc>… -D<def>… <sources> -o <id>.dylib` (host architecture by default).
- Windows (MSVC): `cl /nologo /LD /O2 /I<inc>… /D<def>… <sources> /Fe<id>.dll`, object files in a temporary
  directory.

Compilation happens in a temporary build directory; only the final library is copied into
`binaries/<platform>/`. Compiler `stdout`/`stderr` is forwarded line by line to the logger.

---

## 5. Steps

### Step 0 — Move the FMI headers (D5) — done

- `git mv fmi fmu_manipulation_toolbox/resources/fmi`; update `cmake/fmutool.cmake`, `container/CMakeLists.txt`,
  `MANIFEST.in`, `pyproject.toml` (`package-data`: `resources/fmi/*.h`).
- Check: native build of `container/` and `remoting/` still configures; `python -m build` wheel contains the headers.
- Done on 13 October 2026: `container/` and `remoting/` build; `tools/dist_inventory.py` only reports the 6 headers
  added to the wheel (reference `tests/data/packaging/wheel-data-files.txt` updated); test suite green.

Commit message: `Move the FMI headers into the package resources`

### Step 1 — `SourceCompiler` and build-description parsing — done

- `compiler.py`: `BuildConfiguration`, platform helpers, FMI 2.0 / FMI 3.0 parsing, D7.
- Remove the `importorskip` of `tests/unit/test_compiler.py`: these tests must pass.
- Done on 13 October 2026. Rules implemented beyond §4 (and tested):
  - FMI 3.0: a `BuildConfiguration` whose `platform` is the host platform wins over one without `platform`;
    those of other platforms are ignored; error if none is left.
  - FMI 3.0: `PreprocessorDefinition optional="true"` is not set.
  - FMI 2.0: the files of the interfaces sharing a model identifier are merged (no duplicate).
  - Error if a listed source file does not exist; FMI 2.0 has no name for Linux/Windows on ARM (error).
  - Not handled yet: `SourceFileSet` `language` / `compiler` / `compilerOptions` and `<Library>` (step 2, D12 to
    D14). `BuildConfiguration` gets one entry per `SourceFileSet` (sources, language, compiler, options,
    definitions, include directories) and a list of libraries; `source_files`, `definitions` and
    `include_directories` stay available (union of the sets) for the existing tests.

Commit message: `Add SourceCompiler to read the build description of an FMU`

### Step 2 — Compilation — done

- Compiler discovery (D6), command lines, D10 definitions, temporary build directory, output forwarding.
- C++ (D12), `compilerOptions` (D13), `<Library>` (D14), with unit tests on the generated command lines.
- Done on 13 October 2026:
  - `SourceFileSet` (one per FMI 3.0 `<SourceFileSet>`, a single one for FMI 2.0), `BuildConfiguration`
    (`source_file_sets`, `libraries`; `source_files` / `definitions` / `include_directories` are views on the sets).
  - `Toolchain` (`family` `gcc` / `clang` / `msvc`, `find()` cached for the session): on Linux/macOS, the family is
    read from `$CC --version` rather than from the executable name (`cc` is clang on macOS), which is what D13
    compares with. `SourceCompiler.build_commands()` (pure, unit-tested) and `SourceCompiler.compile()`.
  - One compilation per source file into a temporary directory, then the link; only the final library is copied
    into the FMU. Include path: `sources/`, include directories of the set, `resources/fmi/`.
  - Checked on macOS arm64: both Reference FMUs compiled without `binaries/` simulate as `REF-BouncingBall.csv`; a
    broken source gives an `OperationError`, the compiler output in the log and no binary. **MSVC path not run yet**
    (no Windows host here): to be checked on Windows / by the CI.
- Include path: `sources/`, build-description include directories, then `resources/fmi/` (D5).
- Manual check: `bouncing_ball-win32.fmu` (FMI 2.0) and an FMI 3.0 FMU whose host binary was removed.

Commit message: `Compile the embedded sources of an FMU for the host platform`

### Step 3 — `OperationCompileSources` — done

- Operation with D3 behaviour, summary in the log; `Summary` operation unchanged.
- Remove the `importorskip` / `skip` of `tests/integration/test_compile_sources.py`: every test but
  `test_cli_compile_sources` must pass (it needs step 4).

- Done on 13 October 2026: in `compiler.py` (as the remoting operations are in `remoting.py`), `read_only`
  (the descriptor is not written back). D3 is checked per model identifier before reading the build description:
  an FMU whose binaries all exist needs neither sources nor compiler. 7 of the 8 integration tests pass;
  `test_cli_compile_sources` waits for step 4.

Commit message: `Add OperationCompileSources`

### Step 4 — GUI button and CLI option — done

- `gui/fmutool/__main__.py`: `("Compile sources", '-compile-sources', 'modify', OperationCompileSources)` right
  after `Remove sources` (D8, D9).
- `help.py`: usage of `-compile-sources`; `cli/fmutool.py`: `-compile-sources` (`append_const`) (D4).
- The whole test suite is green, `test_cli_compile_sources` included.
- Done on 13 October 2026: 1840 passed; `tests/gui/test_gui.py` expects 16 buttons. D8 revised by the user: the
  grid is 4 x 4 (`WIDTH = 4`), order chosen by the user:
  `Check, Save description.xml, Save port names, Rename ports from CSV` /
  `Trim Until, Remove Toplevel, Merge Toplevel, Compile sources` /
  `Remove Regexp, Keep only Regexp, Remove all, Remove sources` /
  `Add Win32 remoting, Add Win32 frontend, Add Win64 remoting, Add Win64 frontend`
  (colours in blocks, `Compile sources` above `Remove sources`).
  The `?` help button of FMU Tool is removed (duplicate of the launcher); the drop zone is aligned with the 4 lines
  of buttons and the title spans the whole width. Help text says "available from version 2.0" (roadmap).

Commit message: `Add a "Compile sources" button to FMU Tool and a -compile-sources option`

### Step 5 — User documentation — done

- `docs/user-guide/fmutool/gui-usage.md` (button table, colour, new 4 x 4 grid; screenshot `fmutool-gui.png` to
  regenerate with `tools/screenshots.py`), `python-api.md` (`SourceCompiler`,
  `OperationCompileSources`), `cli-usage.md` (`-compile-sources`), limits (D3 architecture, D7), prerequisites (C compiler per OS) in `installation.md`.
- `CHANGELOG.md`.

- Done on 13 October 2026: `gui-usage.md` (grid, colour table, *Compile Sources* section, no more help icon),
  `cli-usage.md` (*Compile Sources*: example, prerequisites per OS, what is compiled, errors and exit code 5,
  limits), `python-api.md` (*Compile the Sources*), `installation.md` (optional dependencies), new API page
  `API/compiler.md` (in `mkdocs.yml`), `CHANGELOG.md` (fmutool and GUI sections). Screenshots `fmutool-gui.png`,
  `fmutool-filter.png`, `fmutool-check.png` regenerated, `fmutool-compile.png` added (new shot in
  `tools/screenshots.py`). `mkdocs build --strict` passes.

Commit message: `Document the compilation of FMU sources`

---

## 7. Open point

The MSVC path (`Toolchain._find_msvc()`, `cl` command lines, filtering of the MSVC banner lines of D16) is covered
by unit tests on the command lines only: it was never run. To be checked on Windows (or by the CI on
`windows-latest`, where `needs_compiler` tests run when Visual Studio is installed).

---

## 6. Test suite (done on 13 October 2026, before the implementation)

Written against the API of §4; validated with a throw-away POSIX prototype (23 tests pass on macOS arm64,
`test_cli_compile_sources` fails until step 4). Until `compiler.py` exists, both modules are skipped and the suite
stays green (1807 passed).

| File | Content |
|---|---|
| `tests/data/compile/` | `2.0/BouncingBall.fmu`, `3.0/BouncingBall.fmu` (Reference FMUs v0.0.41, unmodified), `LICENSE.txt`, `README.md`, `REF-BouncingBall.csv` (`time`, `h`, `v` of the FMI 3.0 original binary, `stop_time=3`, `output_interval=0.01`) |
| `tests/_helpers/archive.py` | `rewrite_fmu()` (copy an FMU without some entries / with replaced entries), `read_entry()` |
| `tests/conftest.py`, `tests/pytest.ini` | marker `needs_compiler` (MSVC through `vswhere.exe` or `cl` on Windows, `$CC`/`cc` elsewhere) |
| `tests/unit/test_compiler.py` | `host_platform()` (patching `platform.system()` / `platform.machine()`), `library_suffix()`, `build_configurations()` for FMI 2.0 and 3.0, D7 errors |
| `tests/integration/test_compile_sources.py` | compilation without `binaries/` (FMI 2.0, 3.0), simulation compared with the reference (`slow`, `needs_fmpy`), compilation failure (compiler output in the log, no binary left), D3 (no compiler needed), no `sources/`, CLI `-compile-sources` |

The implementation must call `platform.system()` / `platform.machine()` through the `platform` module (not
`from platform import …`) for the unit tests to patch them.

Commit message: `Add the test suite of the compilation of FMU sources`
