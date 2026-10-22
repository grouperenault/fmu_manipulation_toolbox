# Plan: one log per GUI window

**Created**: 22 October 2026 — **Status**: in progress, decisions taken —
**Origin**: user report: "the windows opened by the toolbox launcher share the same logger, which is confusing when
two or more windows are open, especially FMU Tool"

---

## 1. Current state

The launcher (`gui/__main__.py`) opens FMU Tool, FMU Editor and FMU Container Builder windows **in the same process**.
Every module logs to the single logger `fmu_manipulation_toolbox`, so all the GUI views receive the records of all the
windows.

| # | Where | Behaviour | Problem |
|---|-------|-----------|---------|
| P1 | FMU Tool (`gui/fmutool/__main__.py:225-227`) | Each window adds its own `WidgetLogHandler` to the logger | With two FMU Tool windows, every operation is printed in **both** log areas |
| P2 | FMU Editor / Container Builder | Both use the singleton `GuiLogHandler.install()`; `LogStatusBar`, `LogWindow` and `RunTask` connect to its `record_emitted` signal | The status bar, the log window and the history of a window show the records of all the others; **Clear** clears the history of every window |
| P3 | Logger level | `logger.setLevel(INFO)` at the creation of each FMU Tool / FMU Editor / Container Builder window (`fmutool/__main__.py:227`, `fmueditor/__main__.py:455`, `fmucontainer/__main__.py:39`); Verbose Mode sets it to `DEBUG` | Opening a window silently turns off the Verbose Mode of an open Container Builder; Verbose Mode of one Container Builder makes every window receive DEBUG records |
| P4 | Verbose Mode stdout copy (`fmucontainer/__main__.py:37`, `_on_debug_mode_changed`) | A `StreamHandler(sys.stdout)` added to the logger | Copies the records of every window on stdout |
| P5 | Container Builder AI Assistant (`mcp_bridge.py`) | uvicorn runs in a `QThread`; FastMCP runs synchronous tools in worker threads; bridge operations are run on the main thread through `MainThreadInvoker` (queued signal) | Records are not emitted from a user action of the window: any routing must also cover these threads and the queued calls |

## 2. Decisions

| # | Question | Decision |
|---|----------|----------|
| D1 | How to isolate the logs | **Tag each record with its owner window**, one process kept. Each view shows only the records of its own window. "Exit" in the launcher still closes everything. (Rejected: one process per window.) |
| D2 | Record without owner (logged outside any window: import time, a thread without context…) | **Shown in every window** (nothing is lost) |
| D3 | Logger level / Verbose Mode | **Per window**: the logger level is the lowest level requested by the open windows; each window only keeps the records at or above its own level; the Verbose Mode stdout copy only prints the records of the windows in Verbose Mode (and the records without owner) |
| D4 | How a main-thread record finds its window | **Application event filter + pinning**: each user input event (mouse press, key press, drop) makes the top-level window owning the target widget the *current window*. `RunTask`, `busy_cursor`, FMU loading and the MCP threads **pin** their window explicitly, so that a click in another window during `processEvents()` does not redirect the end of a running task. No slot is modified. |
| D5 | **Clear** in the log window | **Clears the history of this window only (its own records and its copy of the records without owner); the other windows are not affected** |
| D6 | History size | **One bounded history (5000) **per window**, so that a verbose window does not evict the history of the others. A record without owner is copied in the history of every registered window; a window opened later does not receive the records without owner emitted before its opening** |
| D7 | A window not registered (the launcher itself) | **Its records have no owner (D2)** |

## 3. Design

```
     user event (press, key, drop) ──► AppEventFilter ──► implicit current window (main thread)
     RunTask / busy_cursor / load / MCP thread ──► window_log_context(window)  (pinned, ContextVar)

                logging "fmu_manipulation_toolbox"   (level = min of the registered window levels)
                                 │
                         GuiLogHandler.emit()
                         owner = pinned context  or  implicit current window (main thread only)  or  None
                         ├── drop if owner registered and levelno < owner level
                         ├── history[owner].append(...)   (or every history when owner is None)
                         └── record_emitted(owner_key, levelno, text)  ── queued ──► views
                                                                                  filter owner_key in (own key, None)
```

- **`window_log_context(window)`** (context manager, `gui/helper.py`): sets a `ContextVar` holding the owner key and
  resets it on exit. A pinned owner wins over the implicit one. `ContextVar` values are copied by asyncio tasks;
  the plan checks that FastMCP / anyio worker threads see the value set in the uvicorn thread (`anyio.to_thread`
  copies the context), and pins explicitly in the worker if not.
- **Owner resolution**: from the widget target of the event, walk `parentWidget()` / `window()` up to a window
  registered with the handler, so that a click in a `RunTask`, `LogWindow`, `QFileDialog` or `QMessageBox` belongs to
  its main window. No registered window found → no owner.
- **`AppEventFilter`**: installed on `QApplication.instance()` by `GuiLogHandler.install()`, so it works with both
  `Application` classes (the launcher's and `gui/helper.py`'s). It only reads the event type and returns `False`.
- **Registration**: `GuiLogHandler.register_window(window, level=INFO)`, `set_window_level(window, level)`,
  unregistration on `destroyed`. The logger level is recomputed from the registered levels (`INFO` when none).
  `assistant/fmutools._captured_logs` changes the level temporarily: its restore must go through the recompute
  (or keep its save/restore if it only runs headless — to check in step 5).
- **Views**: `LogStatusBar`, `LogWindow`, `RunTask` receive the window they belong to and keep only the records of that
  window or without owner. `LogWindow` is filled from `history[own key]`.
- **FMU Tool** stops using `WidgetLogHandler` (removed): it connects to `GuiLogHandler` like `RunTask`, with the
  immediate repaint (`processEvents()`) it has today.

## 4. Steps

### Step 1 — Owner of a record (`gui/helper.py`)

- `ContextVar` + `window_log_context`, implicit current window, `AppEventFilter`, owner resolution.
- `GuiLogHandler`: registry of windows and levels, logger level recompute, per-window histories (D6), owner in the
  signal `record_emitted(object, int, str)`.
- Unit tests (`tests/gui/test_gui_logging.py`): owner from a pinned context, from an event, nested pins, record
  without owner reaching every window, level filtering per window, logger level = min.

Commit message: `Tag the GUI log records with the window that emitted them`

**Done.** The views (`LogStatusBar`, `LogWindow`, `RunTask`) receive the owner but do not filter yet. A view bound to
no window shows every record (`GuiLogHandler.history`). `window_log_context` accepts a widget (resolved on the main
thread through the installed handler) or a key from `GuiLogHandler.window_key` (usable in any thread).

### Step 2 — Views filtered by window (FMU Editor, Container Builder)

- `LogStatusBar`, `LogWindow`, `RunTask` filter by owner; **Clear** per window (D5).
- FMU Editor and Container Builder register their window; the `logger.setLevel(INFO)` calls are removed.
- `RunTask` pins its parent window for the duration of the task.

Commit message: `Show only the records of their own window in the status bar and the log window`

**Done.** The windows are unregistered in `closeEvent` (the launcher keeps them alive after closing, so `destroyed`
is not enough).

### Step 3 — Verbose Mode per window (Container Builder)

- `_on_debug_mode_changed` calls `set_window_level(self, DEBUG / INFO)`.
- The stdout handler gets a filter: records of this window or without owner (one shared stdout handler, or one per
  window with the filter — the record without owner must not be printed twice when two windows are verbose).

Commit message: `Make the Verbose Mode of the Container Builder specific to its window`

**Done.** `GuiLogHandler.set_window_verbose` holds the verbose mode: one shared stdout handler, filtered on the windows
in verbose mode and the records without owner. A logger filter (`_OwnerFilter`) stores the owner in
`record.gui_owner`, so that the stdout filter and the GUI handler agree. The window of the last user event is an
application state (`GuiLogHandler.current_owner`, one application event filter). Step 2 tests fixed: a child dialog
was also given to `qtbot` ("shared QObject was deleted directly" at exit).

### Step 4 — FMU Tool

- Register the window, remove `WidgetLogHandler` and `logger.setLevel(INFO)`; feed `log_widget` from the
  `GuiLogHandler` signal filtered by owner, with the immediate repaint.
- Pin the window in `apply_operation`, `save_fmu`, the FMU load of the drop zone, and `busy_cursor` (new optional
  `window` argument).

Commit message: `Keep the log of each FMU Tool window to its own operations`

**Done.** The welcome messages of the window are pinned too: without it, opening FMU Tool from the launcher (an
unregistered window) would show them in every window.

### Step 5 — AI Assistant threads (Container Builder)

- Pin the window in `_UvicornThread.run` and in the tasks run by `MainThreadInvoker`.
- Check that the records of the FastMCP synchronous tools (`assistant/fmutools.py`) carry the owner; pin in the
  worker if not. Check `_captured_logs` against the level registry.
- Tests: two Container Builder windows, the `[AI] …` records of one do not reach the other.

Commit message: `Route the AI Assistant logs to the Container Builder window that runs the server`

### Step 6 — GUI tests with several windows

- Two FMU Tool windows: an operation in one is only logged in it.
- FMU Editor + Container Builder: status bars and log windows are independent; Verbose Mode of one does not change
  the other; opening a window does not turn Verbose Mode off.

Commit message: `Test the log isolation between several GUI windows`

### Step 7 — User documentation

- `docs/user-guide/fmutool/gui-usage.md` (Log Area), `docs/user-guide/fmutool/fmueditor.md` (Status Bar and Log
  Window), `docs/user-guide/fmucontainer/gui-usage.md` (status bar, log window, Verbose Mode): state that each window
  has its own log, and that the messages not related to a window are shown in all of them.
- `CHANGELOG.md`.

Commit message: `Document the per-window log of the GUI`
