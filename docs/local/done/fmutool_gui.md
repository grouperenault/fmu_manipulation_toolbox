# FMUTool GUI: button states, link to the extraction directory, alternative actions

## Goal

1. Disable the buttons that have nothing to do.
2. In the log of `Summary`, make the extraction directory a link that opens it.
3. Add alternative actions to the operation buttons. While Option (macOS) or Alt (Windows, Linux) is held, a button
   with an alternative action shows the alternative label, and a click runs the alternative action:
   - "Check" → "Selected Check": choose the checkers (and the settings of FMI-LS-REF), then check;
   - "Compile sources" → "Advanced Compile": set the compilation options, then compile.

   More alternative actions will come later.

## Decisions

1. **Disabled buttons, without an FMU**: the 16 operation buttons, `Reload` and `Save modified FMU as` are disabled
   until an FMU is loaded. `Save log as` and `Exit` stay enabled.
2. **The "modified" state**: `Save modified FMU as` stays disabled until an operation modifies the loaded FMU.
3. **What counts as a modification** is decided by the operation's category, not by the content of the FMU. These
   operations set the FMU to "modified" when they end without an exception, even if they changed nothing:
   - Add Win32/Win64 remoting and frontend;
   - Compile sources (when the compilation succeeds);
   - Rename from CSV, Trim Until, Remove/Merge Toplevel, Remove/Keep only Regexp, Remove all;
   - Remove sources.

   Check, Summary, Save description.xml and Save port names do not modify the FMU. Loading an FMU or reloading it
   clears the state.
4. **The link**: only the `| temporary directory = …` line of `Summary` becomes a link. A click opens the directory in
   the file manager (Finder, Explorer…). The log message itself does not change, so the CLI is not affected.
5. **"Selected Check"** opens a dialog with:
   - one checkbox per checker (the built-in ones and the add-ons);
   - the `rtol`, `atol` and `timeout` settings of FMI-LS-REF.

   The selection and the settings are kept for the session.
6. **The settings of FMI-LS-REF** can also be set on the command line: `fmutool -check -ref-rtol R -ref-atol A
   -ref-timeout T`. The class constants `RTOL`, `ATOL` and `TIMEOUT` stay the defaults.
7. **"Advanced Compile"** opens the existing `CompileOptionsDialog` before the compilation:
   - prefilled with the options of the session;
   - with a `Compile` button instead of `Retry`.

   Then the compilation goes on as today: after a failure, the dialog opens again.
8. **While Option/Alt is held**, the buttons without an alternative action keep their label and their normal action.
9. **Discovery**: the tooltip of a button with an alternative action mentions it, e.g. "Option-click: Selected Check"
   (macOS) or "Alt-click: Selected Check" (Windows, Linux).

## Confirmed points

- The `Apply only on` filter is disabled together with the operation buttons when no FMU is loaded. It is listed in
  step 1.
- The labels "Selected Check" and "Advanced Compile" are used as the user gave them.
- The names of the command-line options are `-ref-rtol`, `-ref-atol` and `-ref-timeout`. They need `-check`, as
  `-compile-options` needs `-compile-sources`. They must be positive: `rtol >= 0`, `atol >= 0`, `timeout > 0`.

## Steps

### Step 1: button states

- `MainWindow.update_buttons()`: the operation buttons, `Reload` and the filter are enabled when an FMU is loaded.
  `Save modified FMU as` is enabled when the FMU is loaded and `self.fmu_modified` is set.
- The table of operations gets a `modifies` flag (decision 3). `_apply_operation` returns whether the operation ended
  without an exception. The handler then sets `fmu_modified` and calls `update_buttons()`.
- `compile_sources` sets `fmu_modified` only when the compilation succeeds.
- `update_fmu` and `reload_fmu` clear `fmu_modified`.
- The buttons stay disabled at start, until an FMU is dropped.
- Tests (qtbot):
  - the buttons are disabled at start and enabled after loading;
  - `Save modified FMU as` is enabled after `Remove all` but not after `Check`;
  - Reload disables it again.

Commit: `FMUTool GUI: disable the buttons without action`

### Step 2: link to the extraction directory

- `LogWidget`:
  - `setOpenLinks(False)`;
  - `anchorClicked` opens the URL with `QDesktopServices.openUrl`;
  - a new method `append_link(levelno, text, path)` writes the text, then the path as an anchor `file://…`.
- `MainWindow._on_record` recognizes the line `| temporary directory = <path>` and calls `append_link`.
- Tests:
  - after loading, the log contains an anchor to `fmu.tmp_directory`;
  - a click calls `QDesktopServices.openUrl` (monkeypatched) with that directory.

Commit: `FMUTool GUI: link to the extraction directory in the summary`

### Step 3: settings of FMI-LS-REF

- `OperationLsRefCheck.__init__(rtol=RTOL, atol=ATOL, timeout=TIMEOUT)`. The checker uses `self.rtol`, `self.atol` and
  `self.timeout`, including in the INFO log of each experiment.
- CLI `fmutool`:
  - `-ref-rtol`, `-ref-atol` and `-ref-timeout` (float), set on the instance of `OperationLsRefCheck` among the
    checkers;
  - without `-check`, or with an invalid value, the exit code is `USAGE_ERROR`;
  - help entries in `help.py`.
- Tests:
  - unit: the values are taken by the checker;
  - CLI: an option without `-check` and an invalid value give `USAGE_ERROR`;
  - an experiment replayed with a tolerance that makes it fail.

Commit: `LS-REF: rtol, atol and timeout as settings of the checker and options of fmutool`

### Step 4: alternative actions (mechanism)

- The table of operations gets an optional alternative, as `(label, func)`.
- `OperationButton(QPushButton)` holds the normal and the alternative labels and actions:
  - `set_alternative(active)` switches the label;
  - a click runs the action of the label shown.
- `MainWindow` installs an event filter on the application:
  - on `KeyPress` or `KeyRelease` of `Qt.Key_Alt`, and when the window is activated or deactivated, it reads
    `QApplication.queryKeyboardModifiers()` and switches the buttons;
  - on macOS, Option is `Qt.Key_Alt` / `AltModifier`.

  Reading the modifiers on activation avoids a button stuck on its alternative label when Alt is released in another
  window.
- Tooltip (decision 9): "Option-click: <alternative label>" on macOS, "Alt-click: …" elsewhere.
- Tests:
  - switching labels with simulated key events;
  - the action matches the label shown;
  - the buttons without an alternative do not change;
  - the tooltip.

Commit: `FMUTool GUI: alternative actions of the buttons with Option/Alt`

### Step 5: "Selected Check"

- `CheckSelectionDialog`:
  - one checkbox per checker of `get_checkers()`, labelled by its `repr` ("FMU LS-REF Checks"…);
  - fields `rtol`, `atol` and `timeout`, enabled only when the LS-REF checker is checked;
  - `Check` and `Cancel` buttons;
  - the same look as `CompileOptionsDialog`.
- The selection and the values are kept in `MainWindow` for the session. At least one checker must be checked, and
  the values are validated as in step 3.
- Tests:
  - only the selected checkers run;
  - the values reach `OperationLsRefCheck`;
  - Cancel runs nothing.

Commit: `FMUTool GUI: Selected Check`

### Step 6: "Advanced Compile"

- `CompileOptionsDialog(values, toolchain, failed=True)`:
  - with `failed=False`, it shows a neutral message ("Options of the compilation with …") and a `Compile` button;
  - with `failed=True`, it behaves as today.
- `compile_sources(ask_first=False)`: with `ask_first`, the dialog opens before the first attempt. Cancel compiles
  nothing.
- Tests: the dialog opens first and its options are used; Cancel compiles nothing.

Commit: `FMUTool GUI: Advanced Compile`

### Step 7: user documentation

- `docs/user-guide/fmutool/gui-usage.md`: disabled buttons, link to the extraction directory, Option/Alt with
  "Selected Check" and "Advanced Compile".
- `docs/user-guide/fmutool/cli-usage.md` and `checker.md`: `-ref-rtol`, `-ref-atol` and `-ref-timeout`.
- `CHANGELOG.md`.
- The screenshots are not updated: I cannot take them.

Commit: `Doc: FMUTool GUI button states and alternative actions`
