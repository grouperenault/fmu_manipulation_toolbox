# Plan: consistent log messages

**Created**: 13 October 2026 — **Status**: draft, decisions D1 to D6 open (to be reviewed by the user later) —
**Roadmap**: not listed — **Origin**: review of the logs of FMU Tool during `compile_sources.md` (decision D16)

The messages of the `fmu_manipulation_toolbox` logger are read in three places: the console of the CLI
(`cli/utils.py`, `LEVEL    | message`, coloured), the log widget of the GUIs (`gui/log.py`, `LogWidget`: colour
and `WARNING: ` / `ERROR: ` / `CRITICAL: ` prefix), and the MCP tools (captured text). Their wording, levels and
prefixes grew operation by operation and are not consistent. The goal is a short written convention, then the
alignment of the existing messages.

---

## 1. Current state

About 350 logging calls in the package; about 100 in the scope of FMU Tool (`operations.py` 42, `checker.py` 14,
`cli/fmutool.py` 14, `compiler.py` 8, `gui/fmutool/__main__.py` 7, `remoting.py` 6, `gui/helper.py` 6). The other
large modules are `container/builder.py` (44), `gui/fmucontainer/assembly_io.py` (44), `split.py` (34),
`gui/fmucontainer/mcp_bridge.py` (19), `assembly.py` (13), `assistant/headless.py` (11).

### Reference style (already the majority)

`compiler.py` (after decision D16 of `compile_sources.md`), `checker.py` (semantic checks), `operations.py`
(`Port 'x' is removed.`), `OperationRemoveSources`: a sentence starting with a capital letter and ending with a period,
names and paths between single quotes, level carried by the logger (no prefix in the text), errors raised as
`OperationError` and reported once.

### Inconsistencies found in the scope of FMU Tool

| # | Where | Message / behaviour | Problem |
|---|---|---|---|
| 1 | `cli/fmutool.py:142` | `logger.info("INFO    Modified FMU is not saved. …")` | Level written in the text: `INFO     \| INFO    Modified …` |
| 2 | `cli/fmutool.py:144` | `logger.fatal(f"FATAL ERROR: {reason}")` | Double prefix: `CRITICAL \| FATAL ERROR: …` |
| 3 | `cli/fmutool.py:88,135,139` | `READING Input='…'`, `WRITING Output='…'`, `WRITING ModelDescriptor='…'` | Upper-case tags in the text, a style used nowhere else |
| 4 | `cli/fmutool.py:84,92,122,126` | `logger.fatal(...)` for usage errors and refused operations | `CRITICAL` used for ordinary errors (the GUI uses `ERROR` for the same `OperationError`) |
| 5 | `cli/fmutool.py:98-115` | `Applying operation for :`, `     - causality = …`, `     => …` | Space before the colon, ad-hoc indentation |
| 6 | `remoting.py:64` | `{bitness} already exists. Add front-end.` | No quotes; imperative instead of a statement |
| 7 | `remoting.py:75,82` | `logger.critical("Cannot add remoting client: …")` then the operation goes on | `CRITICAL` but not fatal: the FMU is saved without its client/server. Should be an `OperationError` |
| 8 | `remoting.py:106-107` | `Remoting nb input port: 3` | Abbreviation, no period |
| 9 | `checker.py:51` | `Expected FMI 2,3 versions.` | Odd list formatting; `FMI 2.0` vs `FMI-2` elsewhere |
| 10 | `checker.py:75,77,163,165` | `FMI-3`, `FMI standard`, `FMI-{version} standard` | Three spellings of the standard (also `FMI 2.0` in `compiler.py`, `FMI-2.0` in `remoting.py`) |
| 11 | `checker.py:382` | `Adding checker: {file}\|{name}` | `INFO` while loading; separator `\|` |
| 12 | `gui/fmutool/__main__.py:180` | `" " * 80 + f"Version {version}"` | Alignment by spaces (depends on the widget width) |
| 13 | `gui/fmutool/__main__.py:216` | `Modified version saved as {filename}.` | Path without quotes (CLI: `Output='…'`) |
| 14 | `gui/fmutool/__main__.py:226,307` | `logger.error(f"{e}")` | Bare exception text; for an unexpected exception the type is lost (`KeyError: 'x'` shows `'x'`) |
| 15 | `operations.py:416` | `Remove tag <…> from modelDescription.xml` (`DEBUG`) | No period (minor) |
| 16 | `operations.py:439,456` | `Removed port vr=… is involved in dependencies tree.` | Missing article; `vr=` jargon |

Outside FMU Tool (only sampled): `split.py` (`Splitting...`, `FMU Extraction of '…'`, messages without period),
`container/builder.py` and `assembly_io.py` (not reviewed yet).

---

## 2. Goals

1. A written convention for the messages (wording, levels, prefixes, names, FMI spelling), in the developer
   documentation.
2. The messages of the chosen scope (D1) follow it.
3. No change of the meaning of the levels for the tests and the exit codes: `ERROR` and above are still counted by
   `ErrorCounter` (`-check`), and the CLI exit codes (`ExitCode`) do not change.
4. Tests asserting on log texts are updated, not weakened.

---

## 3. Proposed convention (to be validated, D2 to D5)

- **Sentence**: capital letter, ends with a period (also for messages ending with a name or a number).
- **Names**: FMU file names, ports, model identifiers, paths, options between single quotes: `'bouncing.fmu'`.
- **Paths**: relative to the FMU (`sources/model.c`) or to the working directory when possible.
- **No level in the text**: no `INFO`, `ERROR:`, `FATAL ERROR:`, `READING`, `WRITING` tags; the handlers add the
  level.
- **Levels**:
  - `DEBUG`: details for developers (command lines, internal steps).
  - `INFO`: progress and results.
  - `WARNING`: the result is produced but may not be what the user expects.
  - `ERROR`: the requested action failed, or (checkers) the FMU is not compliant.
  - `CRITICAL`: not used, or only for an unexpected internal error (D3).
- **Errors of an operation**: raised as `OperationError` (or `FMUError`), logged once by the caller (CLI / GUI /
  MCP), never logged then ignored.
- **FMI spelling**: one form for the standard (D4).

---

## 4. Decisions (open)

- **D1 — Scope**: (a) FMU Tool only (CLI `fmutool`, GUI FMU Tool, `operations.py`, `checker.py`, `remoting.py`,
  `compiler.py`); (b) (a) plus `split.py`, `assembly.py`, `container/`, FMU Container Builder; (c) the whole
  package, in several phases.
- **D2 — Convention**: adopt §3 as is, or amend it.
- **D3 — `CRITICAL`**: (a) never used (`logger.fatal` → `logger.error`); (b) kept for unexpected internal errors
  only.
- **D4 — FMI spelling**: (a) `FMI 2.0` / `FMI 3.0` (as in the standard documents); (b) `FMI-2` / `FMI-3` (as in
  the checker and most of the CHANGELOG: 18 of 23, which also has `FMI 2.0`, `FMI-2.0`, `FMI-3.0`); (c) `FMI 2` / `FMI 3`.
- **D5 — CLI reading/writing messages** (#3): (a) sentences: `Reading 'module.fmu'.`, `Writing
  'module-modified.fmu'.`; (b) keep the upper-case tags as a CLI-specific layout (and document them).
- **D6 — Remoting binaries missing** (#7): (a) `OperationError` (the FMU is not modified); (b) keep going with an
  `ERROR` (counted, exit code unchanged).

---

## 5. Steps

### Step 1 — Convention

- Write the convention (D2 to D4) in `docs/developer/` (new page `logging.md`, linked from `mkdocs.yml`).

Commit message: `Document the conventions of the log messages`

### Step 2 — FMU Tool: CLI and GUI

- Items #1 to #5, #12 to #14 (D3, D5); update the tests of `tests/integration/test_cli*.py` and `tests/gui/`
  asserting on these texts.

Commit message: `Align the log messages of fmutool and FMU Tool with the conventions`

### Step 3 — Operations, remoting, checkers

- Items #6 to #11, #15, #16 (D4, D6); update `tests/unit/test_checker*.py`, `tests/unit/test_operations*.py` and the
  remoting test if needed.

Commit message: `Align the log messages of the operations and the checkers with the conventions`

### Step 4 — Other tools (according to D1)

- Inventory then alignment of `split.py`, `assembly.py`, `container/`, FMU Container Builder, assistant.

Commit message: `Align the log messages of the container tools with the conventions`

### Step 5 — User documentation

- Update the examples of log output in `docs/user-guide/` (CLI usage of `fmutool`, `fmucontainer`, `fmusplit`,
  GUI usage, checker), and `CHANGELOG.md` (🔵 **CHANGED**: wording of the messages; 🔴 **BREAKING** only if scripts
  parsing the CLI output are known to rely on `READING` / `WRITING`).

Commit message: `Document the new log messages`
