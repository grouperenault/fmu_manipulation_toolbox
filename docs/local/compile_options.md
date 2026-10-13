# Plan: additional compiler options, linker options and libraries for "Compile sources"

**Created**: 13 October 2026 — **Status**: steps 1 to 3 done — **Roadmap**: not listed —
**Origin**: follow-up of `done/compile_sources.md`

FMI 2.0 `<SourceFiles>` only lists file names: nothing tells which libraries to link, nor which definitions or
flags the sources need (FMI 2.0.4 and FMI 3.0 `sources/buildDescription.xml` are out of scope of this plan). When
the compilation fails, the user must be able to give additional compiler options, linker options and libraries.

---

## 1. Current state

| Topic | Where | Notes |
|---|---|---|
| Compilation | `compiler.py`: `SourceCompiler.build_commands()`, `SourceCompiler.compile()`, `Toolchain.compile_command()` / `link_command()` | Options come only from the build description (`compilerOptions` when the compiler matches, D13 of `done/compile_sources.md`; `<Library>`, D14) |
| Operation | `compiler.py`: `OperationCompileSources` | No parameter |
| Errors | `OperationError` for every error (D11 of `done/compile_sources.md`): no sources, no list of sources, no compiler, compilation failure | The GUI cannot tell a compilation failure from the other errors |
| CLI | `cli/fmutool.py`: `-compile-sources` (`append_const` of an `OperationCompileSources()` instance) | |
| GUI | `gui/fmutool/__main__.py`: button `Compile sources` → `apply_operation(OperationCompileSources())`, which logs the error and returns | No prompt, no retry |
| Prompts | `gui/fmutool/__main__.py`: `prompt_string()` (`QInputDialog`, one line) | Not suited to three fields |

---

## 2. Goals

1. The Python API, the CLI and the GUI can add compiler options, linker options and libraries to the compilation.
2. In the GUI, the user is asked for them **only after a compilation failure** (option "b"), and can retry until
   the compilation succeeds or he cancels.
3. Nothing changes when no additional option is given.

---

## 3. Decisions

Taken on 13 October 2026:

- **D1 — API parameters**: `OperationCompileSources(compiler_options=(), linker_options=(), libraries=())`,
  forwarded to `SourceCompiler.compile()` / `build_commands()`:
  - `compiler_options`: raw options added to every compilation command (after those of the build description);
  - `linker_options`: raw options added to the link command;
  - `libraries`: library names, translated by the toolchain (`-l<name>`, `<name>.lib` with MSVC), as `<Library>`
    (D14 of `done/compile_sources.md`).
- **D2 — CLI**: dedicated options, parameters of `-compile-sources`: `-compile-options "…"`, `-link-options "…"`
  (split as a command line), `-link-libraries "foo,bar"` (comma-separated). Given without `-compile-sources`: usage
  error (exit code 2). No environment variable (`CFLAGS`, `LDFLAGS`) is read.
- **D3 — GUI: when to ask**: after a compilation failure only (the compiler ran and failed), not when the FMU has
  no sources, no list of sources, or when no compiler is found.
- **D4 — GUI: retry**: the dialog opens again after each failure, until the compilation succeeds or the user
  cancels.
- **D5 — GUI: memory**: the values are pre-filled for the rest of the session (kept by the window), forgotten when
  the application closes.
- **D6 — Detection of a compilation failure**: `OperationError` is unchanged (no new exception class); the operation
  exposes an attribute, `compilation_failed`, set to `True` when the compiler (or the linker) returned an error. The
  GUI reads it after the operation.
- **D7 — GUI dialog**: three fields (compiler options, linker options, libraries), the detected toolchain (family
  and command, e.g. `clang (cc)`), **Retry** and **Cancel** buttons. The compiler output stays in the log area.
  Look of the dialogs of FMU Container Builder (`NodeInfoDialog`, chosen by the user): captions (`caption` class)
  above the fields, **Retry** purple (`save`), **Cancel** blue (`quit`), buttons of the same width (at least 150).

---

## 4. Design

```python
class OperationCompileSources(OperationAbstract):
    def __init__(self, compiler_options: Sequence[str] = (), linker_options: Sequence[str] = (),
                 libraries: Sequence[str] = ()): ...
    compilation_failed: bool          # D6, reset at each application

class SourceCompiler:
    def build_commands(self, configuration, toolchain, build_directory, library,
                       compiler_options=(), linker_options=(), libraries=()) -> list[list[str]]
    def compile(self, configuration, toolchain=None, compiler_options=(), linker_options=(), libraries=()) -> Path
```

- `Toolchain.compile_command()`: the additional compiler options come after the definitions and the
  `compilerOptions` of the build description, before the source file.
- `Toolchain.link_command()`: the additional libraries are appended to those of the build description; the linker
  options come before the libraries (`-L…` before `-l…`); with MSVC, after `/link` (`/LIBPATH:…`).
- The additional options are logged (`INFO`) when they are not empty: `Additional compiler options: '-DFOO=1'.`
- `SourceCompiler._run()` raises the `OperationError` of a failed command; `OperationCompileSources.closure()` sets
  `compilation_failed` before re-raising it (the other errors leave it `False`).
- GUI: the `Compile sources` button gets its own handler (`func`, as `Save description.xml`):

```text
options = session values (D5)
loop:
    operation = OperationCompileSources(**options)
    apply_operation(operation)                 # logs as usual, busy cursor
    if not operation.compilation_failed: break
    options = CompileOptionsDialog(options, Toolchain.find()).exec()
    if cancelled: break
    remember options (D5)
```

---

## 5. Steps

### Step 1 — API — done

- `compiler.py`: parameters of D1, `compilation_failed` (D6), logging of the additional options.
- Unit tests (`tests/unit/test_compiler.py`): position of the additional options in the gcc and MSVC command lines,
  libraries translated by the toolchain. Integration test (`tests/integration/test_compile_sources.py`): a source
  that needs a definition (`#ifndef FOO #error #endif`) fails without `-DFOO` (`compilation_failed` is `True`) and
  succeeds with it; `compilation_failed` stays `False` for an FMU without sources.

- Done on 13 October 2026. `OperationCompileSources.closure()` searches the toolchain (`Toolchain.find()`) before
  compiling, so that "no compiler" never sets `compilation_failed`; a compiler that cannot be started (e.g. no
  `c++` for a C++ source) does set it. Tests: `test_additional_options` (unit), `test_compiler_options`,
  `test_no_sources`, `test_no_compiler` (integration).

Commit message: `Add compiler options, linker options and libraries to OperationCompileSources`

### Step 2 — CLI — done

- `cli/fmutool.py`: `-compile-options`, `-link-options`, `-link-libraries` (D2); the `OperationCompileSources` is
  built after parsing. `help.py`: usage texts.
- Tests: `fmutool -compile-sources -compile-options "-DFOO"` on the FMU of step 1; usage error without
  `-compile-sources`.

- Done on 13 October 2026. A single `OperationCompileSources` instance is given to `-compile-sources` and receives
  the options after parsing (`shlex.split`, POSIX rules except on Windows). Usage error without `-compile-sources`
  reported as the `-input`/`-output` check (`logger.fatal`, exit code 2). argparse refuses a value that starts with
  `-` and has no space (`-compile-options -DFOO`): `-compile-options=-DFOO` must be used; the help texts say so.

Commit message: `Add -compile-options, -link-options and -link-libraries to fmutool`

### Step 3 — GUI — done

- `gui/fmutool/__main__.py`: handler of `Compile sources`, `CompileOptionsDialog` (D3, D4, D5, D7).
- GUI test (`tests/gui/test_gui.py`, dialog patched): the dialog opens after a failure, not for an FMU without
  sources; Retry with the right option succeeds; Cancel stops; the values are pre-filled at the next click.

- Done on 13 October 2026: `CompileOptionsDialog` and `MainWindow.compile_sources()` in
  `gui/fmutool/__main__.py`; the button calls `compile_sources()` (`func`). The session values are also used for
  the first attempt of the next clicks (the log shows them: `Additional compiler options: …`). Unbalanced quotes in
  a field: logged as an error, the dialog opens again. Tests: `test_fmutool_compile_*` in `tests/gui/test_gui.py`
  (dialog replaced by a fake).

Commit message: `Ask for additional compiler options in FMU Tool after a compilation failure`

### Step 4 — User documentation

- `docs/user-guide/fmutool/cli-usage.md` (*Compile Sources*: the three options, an FMI 2.0 example),
  `gui-usage.md` (*Compile Sources*: the dialog after a failure; screenshot of the dialog with
  `tools/screenshots.py`), `python-api.md` (parameters), `CHANGELOG.md`.

Commit message: `Document the additional options of the compilation`
