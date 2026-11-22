# Plan: consistent log messages

**Created**: 13 October 2026 — **Status**: steps 1 to 4 done; decisions D1 to D6 taken (22 November 2026); D7 to D9 to be decided at
the start of their step — **Branch**: `feature/log-consistency`, from `integration` (`e8b1128`) — **Roadmap**: "log
consistency" — **Origin**: review of the logs of FMU Tool during `compile_sources.md` (decision D16)

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
`gui/fmucontainer/mcp_bridge.py` (19), `assembly.py` (13), `assistant/headless.py` (11). 25 calls of
`logger.fatal` / `logger.critical`.

### Reference style (already the majority)

`compiler.py` (after decision D16 of `compile_sources.md`), `checker.py` (semantic checks), `operations.py`
(`Port 'x' is removed.`), `OperationRemoveSources`: a sentence starting with a capital letter and ending with a period,
names and paths between single quotes, level carried by the logger (no prefix in the text), errors raised as
`OperationError` and reported once.

### Inconsistencies found in the scope of FMU Tool

Line numbers checked again on 22 November 2026.

| # | Where | Message / behaviour | Problem |
|---|---|---|---|
| 1 | `cli/fmutool.py:211` | `logger.info("INFO    Modified FMU is not saved. …")` | Level written in the text: `INFO     \| INFO    Modified …` |
| 2 | `cli/fmutool.py:213` | `logger.fatal(f"FATAL ERROR: {reason}")` | Double prefix: `CRITICAL \| FATAL ERROR: …` |
| 3 | `cli/fmutool.py:153,204,208` | `READING Input='…'`, `WRITING ModelDescriptor='…'`, `WRITING Output='…'` | Upper-case tags in the text, a style used nowhere else |
| 4 | `cli/fmutool.py:120-195` vs `gui/fmutool/__main__.py:538,688` | The CLI logs usage errors and refused operations as `CRITICAL`; the GUI logs the same `OperationError` as `ERROR` | Same failure, two levels (D3: `CRITICAL`, no result is produced) |
| 5 | `cli/fmutool.py:163-183` | `Applying operation for :`, `     - causality = …`, `     => …` | Space before the colon, ad-hoc indentation |
| 6 | `remoting.py:64` | `{bitness} already exists. Add front-end.` | No quotes; imperative instead of a statement |
| 7 | `remoting.py:75,82` | `logger.critical("Cannot add remoting client: …")` then the operation goes on | `CRITICAL` but the FMU is saved without its client/server (D6: `OperationError`) |
| 8 | `remoting.py:106` | `Remoting nb input port: 3` | Abbreviation, no period |
| 9 | `checker.py:86` | `Expected FMI 2.0,3.0 versions.` | Odd list formatting; spelling of the standard (D4) |
| 10 | `checker.py:110,112,201,203,431,688` | `FMI-3`, `FMI standard`, `FMI-{version} standard`, `FMI 3.0` | Several spellings of the standard (also `FMI-3.0` in `simulation.py:162`, `FMI-2.0` in `help.py:97`) |
| 11 | `checker.py:1098` | `Adding checker: {file}\|{name}` | `INFO` while loading; separator `\|` |
| 12 | `gui/fmutool/__main__.py:444` | `" " * 80 + f"Version {version}"` | Alignment by spaces (depends on the widget width) |
| 13 | `gui/fmutool/__main__.py:528` | `Modified version saved as {filename}.` | Path without quotes |
| 14 | `gui/fmutool/__main__.py:538,688` | `logger.error(f"{e}")` | Bare exception text; for an unexpected exception the type is lost (`KeyError: 'x'` shows `'x'`) |
| 15 | `operations.py:449` | `Remove tag <…> from modelDescription.xml` (`DEBUG`) | No period (minor) |
| 16 | `operations.py:472,489` | `Removed port '…' is involved in dependencies tree.`, `Removed port vr=… is involved in dependencies tree.` | Missing article; `vr=` jargon in the second form |

Outside FMU Tool (only sampled): `split.py` (`Splitting...`, `FMU Extraction of '…'`, messages without period),
`container/builder.py` and `assembly_io.py` (not reviewed yet). The inventory of the rest of the package is made at
the start of steps 4 and 5.

### Spelling of the standard (22 November 2026)

| Form | Package (`.py`) | User documentation | `CHANGELOG.md` |
|---|---|---|---|
| `FMI 2.0` / `FMI 3.0` | 121 | 62 | 37 |
| `FMI-2` / `FMI-3` | 108 | 35 | 21 |
| `FMI-2.0` / `FMI-3.0` | 18 | 16 | 2 |
| `FMI 2` / `FMI 3` | 7 | 4 | 5 |

Also precise versions: `FMI 2.0.1`, `2.0.2`, `2.0.4`, `2.0.5`, `FMI 3.0.1`, `3.0.2`, `FMI-3.0.1` (D7).

---

## 2. Goals

1. A written convention for the messages (wording, levels, prefixes, names, FMI spelling), in the developer
   documentation.
2. The messages of the whole package follow it (D1).
3. One spelling of the standard, `FMI-2` / `FMI-3`, in the messages, the documentation and the code (D4).
4. `ERROR` and above are still counted by `ErrorCounter` (`-check`), and the CLI exit codes (`ExitCode`) do not
   change.
5. Tests asserting on log texts are updated, not weakened.

---

## 3. Convention (D2, D3, D4)

- **Sentence**: capital letter, ends with a period (also for messages ending with a name or a number).
- **Names**: FMU file names, ports, model identifiers, paths, options between single quotes: `'bouncing.fmu'`.
- **Paths**: relative to the FMU (`sources/model.c`) or to the working directory when possible.
- **No level in the text**: no `INFO`, `ERROR:`, `FATAL ERROR:`, `READING`, `WRITING` tags; the handlers add the
  level.
- **Levels** (D3):
  - `DEBUG`: optional message, to help understand the internal mechanisms.
  - `INFO`: general messages, to follow the progress of the tool.
  - `WARNING`: important message.
  - `ERROR`: an error that is not fatal: a result is produced, but it may differ from the expected one. A checker
    that finds a non-compliance logs an `ERROR`.
  - `CRITICAL`: an error that prevents producing a result (e.g. a usage error of the CLI, a failed operation).
- **Errors of an operation**: raised as `OperationError` (or `FMUError`), logged once by the caller (CLI / GUI /
  MCP) as `CRITICAL`, never logged then ignored.
- **FMI spelling** (D4): `FMI-2` / `FMI-3`, also with a section: `FMI-3 §2.4.7`. Layered standards keep their
  name (`FMI-LS-BUS`).

---

## 4. Decisions

Taken on 22 November 2026:

- **D1 — Scope**: (c) the whole package, in several phases (steps 2 to 5).
- **D2 — Convention**: §3 adopted as is, with the levels of D3 and the spelling of D4.
- **D3 — Levels**: as defined by the user (§3). `CRITICAL` is kept for the errors that prevent producing a result;
  `ERROR` is a non-fatal error. Consequence: the GUIs log a failed `OperationError` as `CRITICAL`, like the CLI
  (#4); the checkers keep `ERROR` for a non-compliance.
- **D4 — FMI spelling**: (b) `FMI-2` / `FMI-3`, in the messages, the user documentation and the code (comments,
  docstrings). The files copied from the standard (`resources/fmi*/`, FMI headers) are not changed.
- **D5 — CLI reading/writing messages** (#3): (a) sentences: `Reading 'module.fmu'.`, `Writing
  'module-modified.fmu'.`.
- **D6 — Remoting binaries missing** (#7): (a) `OperationError`: the FMU is not produced (logged `CRITICAL`).

Taken on 22 November 2026, at the start of step 2:

- **D10 — Filters and operations of `fmutool`** (#5): one sentence per filter, one per operation:
  `Operations restricted to causality 'parameter', 'input'.`, `Operations restricted to type 'Real'.`,
  `Operation: FMU Summary.`
- **D11 — Separators of FMU Tool**: the two lines of 100 dashes around the header of an operation (INFO records,
  also printed on the console) are replaced by a horizontal rule (`<hr>`) inserted in the log area, like the header.
- **D12 — Banner of FMU Tool** (#12): `FMU Tool version X.` (INFO); the welcome text (docstring of the window) is
  inserted in the log area instead of being logged.
- **D13 — Save FMU** of FMU Tool: the errors of `fmu.repack()` (`FMUError`, `OSError`) are logged as `CRITICAL`, like
  the CLI (`OUTPUT_ERROR`); the success message only when the file is written.

Taken on 22 November 2026, at the start of step 3:

- **D14 — Report of Summary**: it keeps its layout (lines starting with `| `), an exception documented in the
  convention.
- **D15 — Checker loaded from a file** (#11): `Checker 'X' loaded from 'file.py'.` (INFO: the user gave the file);
  the checkers of the extensions (entry points) stay in DEBUG: `Addon checker 'X' loaded.`

Taken on 22 November 2026, at the start of step 4:

- **D16 — Automatic wiring**: the prefix is kept, written as text: `Auto link: port 'a.fmu/y' to port 'b.fmu/u'.`,
  `Auto output: port 'a.fmu/y' exposed as 'y'.`, `Profiling: port 'a.fmu/container.p' exposed.`,
  `Automatic wiring: 2 parameters, 1 inputs, 3 outputs, 1 links.`
- **D17 — Actions of the AI Assistant** (FMU Container Builder): the prefix `[AI]` becomes a sentence:
  `AI Assistant: port 'a.fmu/y' linked to port 'b.fmu/u'.`
- **D18 — Internal inconsistencies of the GUI** (selection out of sync, scene deleted...): `DEBUG`.
- **D19 — Two commits for step 4**: 4a (builder, rules, terminals, assembly, split, CLI), 4b (FMU Container
  Builder, MCP bridge).

### To be decided at the start of the step concerned

| # | Question | Step |
|---|---|---|
| D7 | Precise versions (`FMI 2.0.4`, `FMI 3.0.2`): `FMI-2.0.4`, kept as they are, or another form | 6 |
| D8 | `CHANGELOG.md`: the entries of the released versions are rewritten with `FMI-2` / `FMI-3`, or only the new entries follow D4 | 7 |
| D9 | The messages of the C runtime (`container/*.c`, `remoting/*.c`, logged through the FMI logger of the importer): in the scope of this plan or not | 5 |

---

## 5. Steps

Each step ends with the tests of the project passing (`pytest`) and a prepared commit message.

### Step 1 — Convention

- Write the convention (§3) in `docs/developer/` (new page `logging.md`, linked from `mkdocs.yml`).

Commit message: `Doc: the conventions of the log messages`

### Step 2 — FMU Tool: CLI and GUI

- Items #1 to #5, #12 to #14 (D3, D5, D10 to D13); update the tests of `tests/integration/test_cli*.py` and
  `tests/gui/` asserting on these texts.
- Done: `logger.fatal` replaced by `logger.critical` in the CLI; in FMU Tool, a failed operation, a failed load
  (`gui/helper.py`), invalid compile options and a failed save logged as `CRITICAL`; `exception_message()`
  (`gui/helper.py`) gives the text of an error of the toolbox as is, and prefixes the others with their type (#14).
  It is to be reused by the other GUIs (step 4).

Commit message: `fmutool and FMU Tool: log messages aligned with the conventions`

### Step 3 — Operations, remoting, checkers

- Items #6 to #11, #15, #16 (D4, D6); update `tests/unit/test_checker*.py`, `tests/unit/test_operations*.py` and the
  remoting test if needed.
- The texts of `FMUError` (`operations.py:72-118, 275`) have no final period: `'x.fmu' does not exist`. They are
  logged as they are by the CLI and the GUIs.
- Done: also `model_description.py` (`ModelDescriptionError`, whose text is repeated by `FMUError`) and
  `compiler.py` (paths between quotes, `FMI-2`). The remoting checks its client and server binaries before changing
  the FMU (D6). New tests: `tests/unit/test_remoting_errors.py` (runs on every platform), exact texts in
  `test_operations_errors.py`, `test_model_description.py`, `test_checker.py`, `test_checker_loading.py`.

Commit message: `Operations, remoting and checkers: log messages aligned with the conventions`

### Step 4 — Container tools

- Inventory then alignment of `split.py`, `assembly.py`, `container/`, the CLI `fmucontainer` and `fmusplit`, FMU
  Container Builder (`gui/fmucontainer/`).
- 4a done: `container/` (builder, rules, embedded, txt, xcp), `terminals.py`, `assembly.py`, `split.py`, the CLI
  `fmucontainer` and `fmusplit` (`logger.fatal` replaced by `logger.critical`). `ContainerPort` gives its name
  between quotes (`Port 'a.fmu/y'`, `label`: `'a.fmu/y'`). By D3, two `CRITICAL` of the builder become `ERROR`, the
  container being produced: no common OS for the embedded FMUs, library of the runtime not found.
- 4b done: FMU Container Builder (`gui/fmucontainer/`: `__main__.py`, `assembly_io.py`, `mcp_bridge.py`, `tree/`)
  and `RunTask` (`gui/log.py`), with `exception_message()` (step 2) for the exceptions. A failure of the MCP server
  was logged twice (by the controller, then by the window): it is logged once, by the window, as `CRITICAL` (the AI
  Assistant is not enabled), like a file that cannot be opened. `❌ … failed.` ends with a period.

Commit messages: `Container tools: log messages aligned with the conventions` (4a), `FMU Container Builder: log
messages aligned with the conventions` (4b)

### Step 5 — Rest of the package

- Inventory then alignment of `ssp.py`, `assistant/` (MCP server, headless bridge, `fmutool-agent`),
  `simulation.py`, `cli/datalog2pcap.py`, the launcher and the remaining modules; the C runtime according to D9.

Commit message: `Log messages of the rest of the package aligned with the conventions`

### Step 6 — FMI spelling in the code

- `FMI-2` / `FMI-3` in the comments, docstrings and help texts of the package (and of the C runtime, D9), D7 for
  the precise versions; not in the files copied from the standard.

Commit message: `Code: FMI-2 and FMI-3 as the spelling of the standard`

### Step 7 — User documentation

- Update the examples of log output in `docs/user-guide/` (CLI usage of `fmutool`, `fmucontainer`, `fmusplit`,
  GUI usage, checker), the spelling `FMI-2` / `FMI-3` in `docs/` (not `docs/local/`), `README.md` and the agent
  skills.
- `CHANGELOG.md` (D8): 🔵 **CHANGED**: wording and levels of the messages (`READING` / `WRITING` replaced by
  sentences; failed operations logged as `CRITICAL` by the GUIs); 🔵 **CHANGED**: the remoting fails when its
  binaries are missing.
- `docs/local/ROADMAP.md`, then move this plan to `docs/local/done`.

Commit message: `Doc: the new log messages, FMI-2 and FMI-3 as the spelling of the standard`
