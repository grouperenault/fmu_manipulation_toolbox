# Shared logger, log status bar and log window in FMU Container Builder

## Context

### Loggers in use today

| Logger | Where | Handlers / level |
|--------|-------|------------------|
| `fmu_manipulation_toolbox` | Every library module (`assembly.py`, `container/*`, `operations.py`, `checker.py`, …), `gui/helper.py`, `gui/fmucontainer/__main__.py`, `assembly_io.py`, `mcp_bridge.py`, `assistant/*` | No permanent handler in Container Builder. A handler exists only while a `RunTask` dialog runs (`LogWidget.LogHandler`). Outside of it, `INFO` messages are lost (`"Load cancelled"`, `"AI Assistant enabled — connect your MCP client to …"`, the MCP bearer token in `mcp_bridge.py:650-652`) and `WARNING`+ end up on stderr through `logging.lastResort`. |
| `fmu_manipulation_toolbox.gui.tree` (`tree_logger`) | `gui/fmucontainer/tree/{panel,widget,sync}.py`, `mcp_bridge.py` (`[AI] …` messages), `__main__.py` | `propagate = False`, own `StreamHandler(sys.stdout)` installed by `MainWindow._setup_tree_logger()`; level toggled INFO/DEBUG by **Verbose Mode**. Its messages never reach the `RunTask` dialogs; the `[AI]` change journal is only visible on stdout. |

Other GUIs sharing `gui/helper.py`:

- **FMU Editor** (`gui/fmueditor/__main__.py:454`) uses `helper.StatusBar` in its bottom button bar.
- **FMU Tool** (`gui/fmutool/__main__.py:141`) embeds a `helper.LogWidget` in its main window.

### Existing helpers (`gui/helper.py`)

- `StatusBar(QStatusBar)` + nested `StatusBarLogHandler`: shows each record for 10 s, colour by level through a
  stylesheet (`style.log_color`). The handler is added in `__init__` and is supposed to be removed in `__exit__`, but
  `StatusBar` is not used as a context manager, so the handler is never removed. Not clickable, no history.
- `LogWidget(QTextBrowser)` + nested `LogHandler`: colour + `WARNING:`/`ERROR:` prefix per level, calls
  `QApplication.processEvents()` in `emit` to stay responsive during synchronous tasks. `stop_logging()` removes the
  handler.
- `RunTask(QDialog)`: runs a task synchronously on the main thread, with a `LogWidget` and a **Save Logs…** button.
  Used by Container Builder for Load / Import / Export JSON / Save FMU.

### Problems found

1. **Two loggers** in Container Builder, with different destinations (stdout vs dialog) and different level control.
2. **Level management is scattered**: each handler constructor calls `logger.setLevel(level)` on the shared logger
   (`StatusBarLogHandler`, `LogHandler`), `stop_logging()` does not restore it, and `assistant/fmutools._captured_logs`
   also changes the level temporarily. The last one to set it wins.
3. **No permanent log sink** in Container Builder: messages logged outside a `RunTask` are invisible.
4. **Thread safety**: in the GUI, FastMCP runs synchronous tools (`check_fmu`, `summarize_fmu`, `apply_operation`,
   … via `assistant/fmutools.py`) in worker threads, and they log to `fmu_manipulation_toolbox`. A handler that writes
   directly into a Qt widget (as `LogWidget.LogHandler` / `StatusBarLogHandler` do) would touch the GUI from a
   non-main thread. The bridge operations (`mcp_bridge.py`) are already marshalled onto the main thread.
5. `QApplication.processEvents()` inside `emit` is re-entrant: any GUI event can run in the middle of a log call.

## Proposed design

One logger, one GUI handler, several views.

```
          logging "fmu_manipulation_toolbox"   (single logger, level = INFO or DEBUG from Verbose Mode)
                         │
                 GuiLogHandler  (installed once at startup; thread-safe)
                 ├── keeps a bounded history of (levelno, text) records (deque, 5000)
                 └── Qt signal record_emitted(levelno, text)  ── queued to main thread ──┐
                                                                                          │
              ┌───────────────────────────────┬──────────────────────────────────────────┤
        LogStatusBar                     LogWindow (non-modal)                      RunTask dialog
   last INFO+ line, persistent,    LogWidget filled from history +            (kept, live view)
   click → opens LogWindow         live records, level filter, search,
                                   Save / Clear / Close
```

- **`GuiLogHandler(logging.Handler)`** with a companion `QObject` emitting a signal. `emit()` only formats, appends to
  the history and emits the signal; it never touches a widget. The signal is connected with the default
  (auto / queued across threads) connection, so views are always updated on the main thread, whatever thread logged.
  It is installed once by the application (`Application` or `MainWindow`) and removed on exit.
- **`LogWidget`** is refactored into a pure view: `append_record(levelno, text)` (colour + prefix as today), no own
  handler. FMU Tool keeps its current behaviour (D7) through a small handler adapter feeding its `LogWidget`.
- **`LogStatusBar(QStatusBar)`** replaces `StatusBar`: shows the last `INFO`+ record (colour by level) until the next
  one, clickable (`mousePressEvent` → `clicked` signal), tooltip "Click to show the log".
  Container Builder installs it with `QMainWindow.setStatusBar` (strip under the button bar).
- **`LogWindow(QDialog)`**, non-modal, single instance: a `LogWidget` pre-filled from the handler's history, then
  live; a level filter combo (DEBUG / INFO / WARNING / ERROR) and a search field, which re-render the view from
  the stored `(levelno, text)` records; buttons **Save Logs…** (code moved from `RunTask.save_logs`, saves what is
  displayed), **Clear**, **Close**.
- **Level**: only **Verbose Mode** sets the logger level (`DEBUG` when checked, `INFO` otherwise) and adds / removes
  a stdout handler. Handlers no longer call `logger.setLevel()`. `RunTask` no longer takes a `level`.
- **`tree_logger` removed**: all modules use `logging.getLogger("fmu_manipulation_toolbox")`.

## Decisions (2026-10-12)

| # | Question | Decision |
|---|----------|----------|
| D1 | `fmu_manipulation_toolbox.gui.tree` child logger | Removed: every module uses `fmu_manipulation_toolbox` |
| D2 | Copy of the logs on stdout | Only when Verbose Mode is checked (all records of the shared logger) |
| D3 | `RunTask` dialog (Load / Import / Export / Save) | Kept, fed by the shared handler |
| D4 | Status bar message lifetime | Persistent: the last line stays until the next record |
| D5 | Levels shown in the status bar | `INFO` and above; the log window shows everything the logger lets through |
| D6 | History kept by the handler | 5000 records (bounded `deque`) |
| D7 | Scope | Container Builder + FMU Editor (`StatusBar` → `LogStatusBar`). FMU Tool keeps its current behaviour |
| D8 | Status bar position in Container Builder | `QMainWindow.setStatusBar`: strip under the button bar |
| D9 | Selection-sync debug messages | The noisiest ones are removed (synchronizer enter/exit, "event received", …); warnings and errors are kept |
| D10 | Log window extras | Level filter (combo) + text search |

## Steps

### Step 1 – Thread-safe shared handler and views in `gui/helper.py`

- Add `GuiLogHandler` (handler + `QObject` signal + history of 5000 `(levelno, text)` records).
- Refactor `LogWidget` into a view (`append_record`), drop its nested handler and `processEvents` from `emit`
  (`RunTask` keeps the UI repainted by calling `processEvents` in its own slot).
- Add `LogStatusBar` (clickable, persistent last `INFO`+ line) and `LogWindow` (level filter + search, Save / Clear /
  Close).
- Keep a small handler adapter so that FMU Tool's embedded `LogWidget` behaves as today.
- Handlers stop calling `logger.setLevel()`.
- Unit tests (`tests/gui/test_gui_logging.py`): records reach the status bar and the window; `DEBUG` does not reach
  the status bar; a record emitted from a `threading.Thread` is delivered on the main thread; history is bounded;
  filter and search select the right lines; Save writes the displayed content.

Done. Notes:
- `WidgetLogHandler` is the adapter writing directly into a `LogWidget` (main thread only, repaints with
  `processEvents`); FMU Tool and `RunTask` use it. FMU Tool now sets the `INFO` level itself and detaches its handler
  when it closes.
- `RunTask` sets the logger level explicitly (no longer through the handler) until step 3 drops its `level` argument.
- The old `StatusBar` (removed in step 4) now detaches its handler when the widget is destroyed: its `__exit__` was
  never called, and a record logged after an FMU Editor window was deleted raised `RuntimeError` (seen in the tests).

Commit message:
```
Add a thread-safe shared GUI log handler, a clickable log status bar and a log window
```

### Step 2 – Single logger in Container Builder

- Replace `tree_logger` by `logger` in `tree/panel.py`, `tree/widget.py`, `tree/sync.py`, `mcp_bridge.py`,
  `__main__.py`; remove the noisiest selection-sync debug messages.
- Remove `_setup_tree_logger`; Verbose Mode sets the level of `fmu_manipulation_toolbox` and adds / removes the
  stdout handler.
- Check that `assistant/fmutools._captured_logs` still restores the level set by Verbose Mode.

Commit message:
```
Use a single logger in FMU Container Builder, its level driven by Verbose Mode
```

### Step 3 – Status bar and log window in Container Builder

- Install `GuiLogHandler` at startup, add `LogStatusBar` with `setStatusBar`, open `LogWindow` on click.
- `RunTask` is kept, fed by the shared handler; drop its `level` argument.
- GUI test: a `logger.info` in the main window shows in the status bar; click opens the window with the history.

Commit message:
```
Show the last log line in the FMU Container Builder status bar and the full log on click
```

### Step 4 – FMU Editor

- `StatusBar` → `LogStatusBar` (+ log window on click), shared handler installed at startup.
- Remove the old `StatusBar` class (no other user).
- Check that FMU Tool still logs into its embedded `LogWidget`.

Commit message:
```
Use the log status bar and the log window in FMU Editor
```

### Step 5 – User documentation

- `docs/user-guide/fmucontainer/gui-usage.md`: status bar, log window (open, filter, search, save, clear), Verbose
  Mode effect (DEBUG level + copy on stdout).
- `docs/user-guide/fmucontainer/ai-assistant.md`: the `[AI]` change journal and the MCP token are now visible in the
  log window (no longer only on stdout).
- `docs/user-guide/fmutool/fmueditor.md`: status bar and log window.

Commit message:
```
Document the status bar and the log window of the GUIs
```
