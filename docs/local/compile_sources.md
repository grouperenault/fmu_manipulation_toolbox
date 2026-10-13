# Plan: compile the sources of an FMU for the host platform

**Created**: 13 October 2026 — **Status**: decisions taken, not started — **Roadmap**: not listed

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
| Test FMUs with sources | `tests/data/remoting/bouncing_ball-win32.fmu` (FMI 2.0, `all.c`), `tests/data/array/StateSpace.fmu` and `tests/data/ls-bus/*.fmu` (FMI 3.0, `buildDescription.xml`) | |

---

## 2. Goals

1. A reusable class compiling the embedded sources for the **host platform only** (OS and architecture of the
   running Python interpreter). No cross-compilation.
2. **Own implementation**: direct call of the C compiler through `subprocess`, no new dependency (neither fmpy
   nor CMake).
3. If the binary of the host platform **already exists, nothing is done** (informative log message).
4. A new button in the `fmutool` GUI; the compiler output is shown in the log widget.
5. Clear errors: no `sources/`, no compiler found, compilation failure (with the compiler output).

---

## 3. Decisions

Taken on 13 October 2026:

- **D1 — Backend**: own implementation (direct compiler call through `subprocess`), no fmpy, no CMake.
- **D2 — Target**: host platform only.
- **D3 — Existing binary**: do nothing, log an informative message.
- **D4 — Other integrations**: CLI option `-compile-sources` only. No MCP tool. No automated test was requested:
  the steps below only keep the existing test suite green (to be revisited if tests are wanted).
- **D5 — FMI headers**: move `fmi/` (repository root) to `fmu_manipulation_toolbox/resources/fmi/`, declare the
  headers in `package-data`, update `cmake/fmutool.cmake:114` and `container/CMakeLists.txt:11` (and the comment
  of `MANIFEST.in`). This directory is appended to the include path, after `sources/` and the include directories
  of the build description.
- **D6 — Compiler on Windows**: MSVC discovered with `vswhere.exe` + `vcvarsall.bat` (environment captured once),
  fallback on `cl.exe` from `PATH`. On Linux/macOS: `$CC` if set, else `cc`.
- **D7 — Missing sources list**: compile every `*.c` file at the top level of `sources/`, with a warning.
- **D8 — GUI button**: `Compile sources`, colour class `modify`, inserted right after `Remove sources` (the
  following buttons shift; a 4th row appears).
- **D9 — GUI responsiveness**: synchronous, as the other operations; the compiler output is streamed to the log.

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
    def compile(self, configuration) -> Path             # raises CompilationError with the compiler output


class BuildConfiguration:     # dataclass
    model_identifier: str
    source_files: list[Path]
    include_directories: list[Path]
    definitions: dict[str, str | None]


class CompilationError(Exception): ...


class OperationCompileSources(OperationAbstract):
    """Compile the embedded sources when the binary of the host platform is missing."""
    # closure(): for each configuration, skip if binary_path() exists (D3), else compile.
```

Compiler command lines (built in one place, logged at `INFO` before execution):

- Linux: `cc -shared -fPIC -O2 -fvisibility=hidden -I<inc>… -D<def>… <sources> -o <id>.so` (+ `-lm`).
- macOS: `cc -dynamiclib -O2 -I<inc>… -D<def>… <sources> -o <id>.dylib` (host architecture by default).
- Windows (MSVC): `cl /nologo /LD /O2 /I<inc>… /D<def>… <sources> /Fe<id>.dll`, object files in a temporary
  directory.

Compilation happens in a temporary build directory; only the final library is copied into
`binaries/<platform>/`. Compiler `stdout`/`stderr` is forwarded line by line to the logger.

---

## 5. Steps

### Step 0 — Move the FMI headers (D5)

- `git mv fmi fmu_manipulation_toolbox/resources/fmi`; update `cmake/fmutool.cmake`, `container/CMakeLists.txt`,
  `MANIFEST.in`, `pyproject.toml` (`package-data`: `resources/fmi/*.h`).
- Check: native build of `container/` and `remoting/` still configures; `python -m build` wheel contains the headers.

Commit message: `Move the FMI headers into the package resources`

### Step 1 — `SourceCompiler` and build-description parsing

- `compiler.py`: `BuildConfiguration`, `CompilationError`, platform helpers, FMI 2.0 / FMI 3.0 parsing, D7.

Commit message: `Add SourceCompiler to read the build description of an FMU`

### Step 2 — Compilation

- Compiler discovery (D6), command lines, temporary build directory, output forwarding, `CompilationError`.
- Include path: `sources/`, build-description include directories, then `resources/fmi/` (D5).
- Manual check: `bouncing_ball-win32.fmu` (FMI 2.0) and an FMI 3.0 FMU whose host binary was removed.

Commit message: `Compile the embedded sources of an FMU for the host platform`

### Step 3 — `OperationCompileSources`

- Operation with D3 behaviour, summary in the log; `Summary` operation unchanged.
- Manual check through `FMU.apply_operation()` + `repack()`, result loaded by fmpy.

Commit message: `Add OperationCompileSources`

### Step 4 — GUI button and CLI option

- `gui/fmutool/__main__.py`: `("Compile sources", '-compile-sources', 'modify', OperationCompileSources)` right
  after `Remove sources` (D8, D9).
- `help.py`: usage of `-compile-sources`; `cli/fmutool.py`: `-compile-sources` (`append_const`) (D4).
- Existing test suite (`pytest`) still green.

Commit message: `Add a "Compile sources" button to FMU Tool and a -compile-sources option`

### Step 5 — User documentation

- `docs/user-guide/fmutool/gui-usage.md` (button table, colour), `python-api.md` (`SourceCompiler`,
  `OperationCompileSources`), `cli-usage.md` (`-compile-sources`), prerequisites (C compiler per OS) in `installation.md`.
- `CHANGELOG.md`.

Commit message: `Document the compilation of FMU sources`
