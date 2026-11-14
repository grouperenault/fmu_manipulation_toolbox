import argparse
import logging
import os.path
import re
import shlex
import sys
import textwrap
from functools import partial

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fmu_manipulation_toolbox.checker import OperationLsRefCheck, get_checkers
from fmu_manipulation_toolbox.compiler import OperationCompileSources, Toolchain
from fmu_manipulation_toolbox.gui.helper import Application, DropZoneWidget, LastDirectory, get_fmu_icon_path
from fmu_manipulation_toolbox.gui.log import GuiLogHandler, LogWidget, busy_cursor, window_log_context
from fmu_manipulation_toolbox.help import Help
from fmu_manipulation_toolbox.operations import *
from fmu_manipulation_toolbox.remoting import (
    OperationAddFrontendWin32,
    OperationAddFrontendWin64,
    OperationAddRemotingWin32,
    OperationAddRemotingWin64,
)
from fmu_manipulation_toolbox.version import __version__ as version

logger = logging.getLogger("fmu_manipulation_toolbox")


class FilterWidget(QPushButton):
    def __init__(self, items: list[str] | None = (), parent=None):
        super().__init__(parent)
        self.items_selected = set(items)
        self.nb_items = len(items)
        self.update_filter_text()
        if items:
            self.menu = QMenu()
            for item in items:
                action = QAction(item, self)
                action.setCheckable(True)
                action.setChecked(True)
                action.triggered.connect(partial(self.toggle_item, action))
                self.menu.addAction(action)
            self.setMenu(self.menu)

    def toggle_item(self, action: QAction):
        if not action.isChecked() and len(self.items_selected) == 1:
            action.setChecked(True)

        if action.isChecked():
            self.items_selected.add(action.text())
        else:
            self.items_selected.remove(action.text())

        self.update_filter_text()

    def update_filter_text(self):
        if len(self.items_selected) == self.nb_items:
            self.setText("All causalities")
        else:
            self.setText(", ".join(sorted(self.items_selected)))

    def get(self):
        if len(self.items_selected) == self.nb_items:
            return []
        else:
            return sorted(self.items_selected)


class OperationButton(QPushButton):
    """Button of an operation, with an optional alternative action: while the alternative is shown (Option or Alt
    held, see `MainWindow.eventFilter`), the button shows the alternative label and a click runs the alternative
    action.

    Args:
        label (str): Label of the normal action.
        action (Callable[[], None]): Normal action.
        alternative (tuple[str, Callable[[], None]] | None): Label and alternative action.
    """

    #: How to reach the alternative action, in the tooltips.
    ALTERNATIVE_CLICK = "Option-click" if sys.platform == "darwin" else "Alt-click"

    def __init__(self, label: str, action, alternative=None, parent=None):
        super().__init__(label, parent)
        self.label = label
        self.action = action
        self.alternative = alternative
        self.alternative_shown = False
        self.clicked.connect(self.run)

    def setToolTip(self, text: str):
        if self.alternative:
            text += f"\n\n{self.ALTERNATIVE_CLICK}: {self.alternative[0]}"
        super().setToolTip(text)

    def show_alternative(self, shown: bool):
        """Shows the alternative label (`shown`) or the normal one. Without alternative, nothing changes."""
        if self.alternative and shown != self.alternative_shown:
            self.alternative_shown = shown
            self.setText(self.alternative[0] if shown else self.label)

    def run(self):
        """Runs the action of the label shown."""
        if self.alternative_shown:
            self.alternative[1]()
        else:
            self.action()


class CompileOptionsDialog(QDialog):
    """Ask for additional compiler options, linker options and libraries: after a compilation failure, or before
    the compilation ("Advanced Compile").

    Args:
        values (dict[str, str]): Pre-filled values, keyed by `compiler_options`, `linker_options` and `libraries`.
        toolchain (Toolchain | None): Compilers in use (`None` if unknown): named in the message, and the examples
            of the fields are written for them.
        failed (bool): After a compilation failure (button `Retry`), or before the compilation (button `Compile`).
    """

    FIELDS = (("compiler_options", "Compiler options"), ("linker_options", "Linker options"),
              ("libraries", "Libraries"))

    #: Examples shown in the empty fields, for Visual Studio (`msvc`) and for the other compilers (gcc, clang).
    PLACEHOLDERS = {
        "msvc": {"compiler_options": "e.g. /DFOO=1 /IC:\\include",
                 "linker_options": "e.g. /LIBPATH:C:\\lib",
                 "libraries": "names separated by commas, e.g. foo,bar (foo.lib)"},
        "other": {"compiler_options": "e.g. -DFOO=1 -I/opt/include",
                  "linker_options": "e.g. -L/opt/lib",
                  "libraries": "names separated by commas, e.g. foo,bar"},
    }

    def __init__(self, values: dict[str, str], toolchain: Toolchain | None, parent=None, failed: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Compile sources")
        self.setMinimumWidth(500)
        if toolchain:
            # The name of the compiler only: MSVC is found with its full path.
            name = toolchain.c_compiler[0].replace("\\", "/").rsplit("/", 1)[-1]
            description = f"{toolchain.family} ({name})"
        else:
            description = "the C compiler"
        placeholders = self.PLACEHOLDERS["msvc" if toolchain and toolchain.family == "msvc" else "other"]

        # Same look as the dialogs of FMU Container Builder (`NodeInfoDialog`): captions above the fields.
        if failed:
            message = QLabel(f"The compilation with {description} failed: see the log. Add options and retry.")
        else:
            message = QLabel(f"Options of the compilation with {description}.")
        message.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(message)
        self.edits: dict[str, QLineEdit] = {}
        for key, label in self.FIELDS:
            caption = QLabel(label)
            caption.setProperty("class", "caption")
            edit = QLineEdit(values.get(key, ""))
            edit.setPlaceholderText(placeholders[key])
            layout.addSpacing(8)
            layout.addWidget(caption)
            layout.addWidget(edit)
            self.edits[key] = edit

        _dialog_buttons(layout, self, "Retry" if failed else "Compile")

    def values(self) -> dict[str, str]:
        return {key: edit.text().strip() for key, edit in self.edits.items()}


def _dialog_buttons(layout: QVBoxLayout, dialog: QDialog, accept_label: str) -> QPushButton:
    """Adds the Cancel and `accept_label` buttons at the bottom of `layout`. Returns the accept button."""
    accept_button = QPushButton(accept_label)
    accept_button.setProperty("class", "save")
    accept_button.setDefault(True)
    accept_button.clicked.connect(dialog.accept)

    cancel_button = QPushButton("Cancel")
    cancel_button.setProperty("class", "quit")
    cancel_button.clicked.connect(dialog.reject)

    width = max(accept_button.sizeHint().width(), cancel_button.sizeHint().width(), 150)
    accept_button.setMinimumWidth(width)
    cancel_button.setMinimumWidth(width)

    button_row = QHBoxLayout()
    button_row.addStretch()
    button_row.addWidget(cancel_button)
    button_row.addWidget(accept_button)
    layout.addSpacing(12)
    layout.addLayout(button_row)
    return accept_button


class CheckSelectionDialog(QDialog):
    """Choose the checkers to run, and the settings of the checker of FMI-LS-REF.

    Args:
        checkers (list[type]): The checkers that can be chosen, as returned by `get_checkers()`.
        selected (set[type]): The checkers checked at the opening.
        settings (dict[str, float]): Settings of `OperationLsRefCheck` at the opening: `rtol`, `atol`, `timeout`.
    """

    SETTINGS = (("rtol", "Relative tolerance (rtol)"), ("atol", "Absolute tolerance (atol)"),
                ("timeout", "Time limit of each experiment, in seconds"))

    def __init__(self, checkers: list[type], selected: set[type], settings: dict[str, float], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Selected Check")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        caption = QLabel("Checkers")
        caption.setProperty("class", "caption")
        layout.addWidget(caption)
        self.boxes: dict[type, QCheckBox] = {}
        for checker in checkers:
            box = QCheckBox(repr(checker()))
            box.setChecked(checker in selected)
            box.toggled.connect(self.update_state)
            layout.addWidget(box)
            self.boxes[checker] = box

        self.edits: dict[str, QLineEdit] = {}
        for key, label in self.SETTINGS:
            caption = QLabel(f"FMI-LS-REF: {label}")
            caption.setProperty("class", "caption")
            edit = QLineEdit(f"{settings[key]:g}")
            layout.addSpacing(8)
            layout.addWidget(caption)
            layout.addWidget(edit)
            self.edits[key] = edit

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setProperty("class", "status_error")
        layout.addWidget(self.message)
        self.check_button = _dialog_buttons(layout, self, "Check")
        self.update_state()

    def update_state(self):
        """The Check button needs a checker; the settings of FMI-LS-REF need its checker."""
        self.check_button.setEnabled(any(box.isChecked() for box in self.boxes.values()))
        ls_ref = any(box.isChecked() for checker, box in self.boxes.items() if issubclass(checker, OperationLsRefCheck))
        for edit in self.edits.values():
            edit.setEnabled(ls_ref)

    def accept(self):
        try:
            OperationLsRefCheck(**self.settings())
        except ValueError as error:
            self.message.setText(f"Invalid setting of FMI-LS-REF: {error}.")
            return
        super().accept()

    def selected(self) -> list[type]:
        return [checker for checker, box in self.boxes.items() if box.isChecked()]

    def settings(self) -> dict[str, float]:
        """The settings typed.

        Raises:
            ValueError: A setting is not a number.
        """
        settings = {}
        for key, edit in self.edits.items():
            try:
                settings[key] = float(edit.text())
            except ValueError:
                raise ValueError(f"{key} must be a number, not '{edit.text()}'") from None
        return settings


class MainWindow(QWidget):
    """
Analyze and modify your FMUs.

Note: modifying the modelDescription.xml can damage your FMU !
Communicating with the FMU-developer and adapting the way the FMU is generated, is preferable when possible.

    """

    #: The line of `Summary` giving the extraction directory, shown as a link.
    TEMPORARY_DIRECTORY = re.compile(r"(\| temporary directory = )(.+)")

    def __init__(self, debug: bool = False):
        super().__init__()
        self.setWindowTitle('FMU Manipulation Toolbox')
        self.layout = QGridLayout()

        WIDTH = 4  # number of columns of operation buttons
        line = 0
        self.dropped_fmu = DropZoneWidget()
        self.dropped_fmu.clicked.connect(self.update_fmu)

        self.fmu_title = QLabel()
        self.fmu_title.setProperty("class", "title")
        self.layout.addWidget(self.fmu_title, line, 0, 1, WIDTH + 1)

        # Options of `Compile sources`, typed after a compilation failure, kept for the session.
        self.compile_options: dict[str, str] = {}
        # An operation has modified the loaded FMU: it can be saved.
        self.fmu_modified = False
        # Checkers and settings of FMI-LS-REF chosen in `CheckSelectionDialog`, kept for the session.
        self.check_selection: set[type] = set(get_checkers())
        self.ls_ref_settings = {"rtol": OperationLsRefCheck.RTOL, "atol": OperationLsRefCheck.ATOL,
                                "timeout": OperationLsRefCheck.TIMEOUT}

        # Operations
        self.help = Help()
        # Grid of WIDTH columns, one line per theme: analysis and export, binary interfaces (green), name changes
        # (orange), removals (red). `modifies`: the operation modifies the FMU (when it ends without an exception).
        operations_list = [
            ("Check",                 '-check',              'info',    get_checkers(),
             {"alternative": ("Selected Check", self.selected_check)}),
            ("Save description.xml",  '-extract-descriptor', 'info',    None, {"func": self.save_descriptor}),
            ("Save port names",       '-dump-csv',           'info',    OperationSaveNamesToCSV, {"prompt_file": "write"}),
            ("Compile sources",       '-compile-sources',    'info',    None,
             {"func": self.compile_sources,
              "alternative": ("Advanced Compile", partial(self.compile_sources, ask_first=True))}),
            ("Add Win32 remoting",    '-add-remoting-win32', 'info',    OperationAddRemotingWin32, {"modifies": True}),
            ("Add Win32 frontend",    '-add-frontend-win32', 'info',    OperationAddFrontendWin32, {"modifies": True}),
            ("Add Win64 remoting",    '-add-remoting-win64', 'info',    OperationAddRemotingWin64, {"modifies": True}),
            ("Add Win64 frontend",    '-add-frontend-win64', 'info',    OperationAddFrontendWin64, {"modifies": True}),
            ("Rename ports from CSV", '-rename-from-csv',    'modify',  OperationRenameFromCSV, {"prompt_file": "read", "modifies": True}),
            ("Trim Until",            '-trim-until',         'modify',  OperationTrimUntil, {"prompt": "Prefix", "modifies": True}),
            ("Remove Toplevel",       '-remove-toplevel',    'modify',  OperationStripTopLevel, {"modifies": True}),
            ("Merge Toplevel",        '-merge-toplevel',     'modify',  OperationMergeTopLevel, {"modifies": True}),
            ("Remove Regexp",         '-remove-regexp',      'removal', OperationRemoveRegexp, {"prompt": "regexp", "modifies": True}),
            ("Keep only Regexp",      '-keep-only-regexp',   'removal', OperationKeepOnlyRegexp, {"prompt": "regexp", "modifies": True}),
            ("Remove all",            '-remove-all',         'removal', OperationRemoveRegexp, {"arg": ".*", "modifies": True}),
            ("Remove sources",        '-remove-sources',     'removal', OperationRemoveSources, {"modifies": True}),
        ]

        line = 1

        self.operations_button_list = []
        for i, operation in enumerate(operations_list):
            col = i % WIDTH + 1
            line = int(i / WIDTH) + 1

            if len(operation) < 5:
                button = self.add_operation(operation[0], operation[1], operation[2], operation[3])
            else:
                button = self.add_operation(operation[0], operation[1], operation[2], operation[3], **operation[4])

            self.operations_button_list.append(button)
            self.layout.addWidget(button, line, col)

        # The drop zone is aligned with the lines of buttons.
        self.layout.addWidget(self.dropped_fmu, 1, 0, line, 1)

        line += 1
        self.reload_button = QPushButton('Reload')
        self.reload_button.clicked.connect(self.reload_fmu)
        self.reload_button.setProperty("class", "quit")
        self.layout.addWidget(self.reload_button, line, 0, 1, 1)

        self.apply_filter_label = QLabel("Apply only on: ")
        self.set_tooltip(self.apply_filter_label, 'gui-apply-only')
        self.layout.addWidget(self.apply_filter_label, line, 2, 1, 1, alignment=Qt.AlignmentFlag.AlignRight)

        causality = ["parameter", "calculatedParameter", "input", "output", "local", "independent"]
        self.filter_list = FilterWidget(items=causality)
        self.filter_list.setProperty("class", "quit")
        self.layout.addWidget(self.filter_list, line, 3, 1, WIDTH - 2)

        # Text
        line += 1
        self.log_widget = LogWidget()
        self.log_handler = GuiLogHandler.install()
        self.log_handler.register_window(self, logging.DEBUG if debug else GuiLogHandler.DEFAULT_LEVEL)
        self.log_handler.record_emitted.connect(self._on_record)
        self.log_widget.insertHtml('<center><img src="fmu_manipulation_toolbox.png"/></center><br/>')
        self.layout.addWidget(self.log_widget, line, 0, 1, WIDTH + 1)

        # buttons
        line += 1
        self.exit_button = QPushButton('Exit')
        self.exit_button.clicked.connect(self.close)
        self.exit_button.setProperty("class", "quit")
        self.layout.addWidget(self.exit_button, line, 0, 1, 1)

        self.save_log_button = QPushButton('Save log as')
        self.save_log_button.clicked.connect(self.save_log)
        self.save_log_button.setProperty("class", "save")
        self.layout.addWidget(self.save_log_button, line, 1, 1, 2)

        self.save_fmu_button = QPushButton('Save modified FMU as')
        self.save_fmu_button.clicked.connect(self.save_fmu)
        self.save_fmu_button.setProperty("class", "save")
        self.set_tooltip(self.save_fmu_button, '-output')
        self.layout.addWidget(self.save_fmu_button, line, 3, 1, 2)

        # Fix the layout
        self.layout.setVerticalSpacing(4)
        self.layout.setHorizontalSpacing(4)
        self.layout.setContentsMargins(10, 10, 10, 10)
        for row in range(self.layout.rowCount()):
            self.layout.setRowMinimumHeight(row, 36)
        self.setLayout(self.layout)

        self.update_buttons()
        # Option (macOS) or Alt held: the buttons show their alternative action.
        QApplication.instance().installEventFilter(self)

        # show the window
        self.show()

        with window_log_context(self):
            logger.info(" " * 80 + f"Version {version}")
            logger.info(self.__doc__)

    def load(self, fmu_path: str):
        """Load an FMU file programmatically."""
        from pathlib import Path
        with window_log_context(self):
            self.dropped_fmu.set_fmu(Path(fmu_path))

    def _on_record(self, owner: int | None, levelno: int, text: str):
        """Show the records of this window (and the records without owner) in the log area."""
        if not self.log_handler.accepts(self, owner, levelno):
            return
        directory = self.TEMPORARY_DIRECTORY.fullmatch(text)
        if directory:
            self.log_widget.append_link(levelno, directory[1], directory[2])
        else:
            self.log_widget.append_record(levelno, text)
        # The operations block the main thread: repaint each record immediately.
        QApplication.processEvents()

    def eventFilter(self, watched, event) -> bool:
        """Switches the operation buttons to their alternative action while Option (macOS) or Alt is held. The
        modifiers are read again when the window is activated or deactivated: Alt may be released in another
        window."""
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.key() == Qt.Key.Key_Alt:
            self.show_alternatives(event.type() == QEvent.Type.KeyPress)
        elif watched is self and event.type() == QEvent.Type.WindowActivate:
            self.show_alternatives(bool(QApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.AltModifier))
        elif watched is self and event.type() == QEvent.Type.WindowDeactivate:
            self.show_alternatives(False)
        return False

    def show_alternatives(self, shown: bool):
        for button in self.operations_button_list:
            button.show_alternative(shown)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        if self.log_handler.is_registered(self):
            self.log_handler.record_emitted.disconnect(self._on_record)
            self.log_handler.unregister_window(self)
        event.accept()

    def set_tooltip(self, widget, usage):
        widget.setToolTip("\n".join(line for paragraph in self.help.usage(usage).splitlines()
                                     for line in textwrap.wrap(paragraph)))

    def update_buttons(self):
        """Enable the buttons that have something to do: the operations need an FMU, saving it needs a
        modification."""
        loaded = self.dropped_fmu.fmu is not None
        for button in self.operations_button_list:
            button.setEnabled(loaded)
        self.reload_button.setEnabled(loaded)
        self.filter_list.setEnabled(loaded)
        self.save_fmu_button.setEnabled(loaded and self.fmu_modified)

    def set_modified(self):
        self.fmu_modified = True
        self.update_buttons()

    def reload_fmu(self):
        if self.dropped_fmu.fmu:
            filename = self.dropped_fmu.fmu.fmu_filename
            self.dropped_fmu.fmu = None
            self.dropped_fmu.set_fmu(filename)

    def save_descriptor(self):
        if self.dropped_fmu.fmu:
            fmu = self.dropped_fmu.fmu
            filename = LastDirectory.get_save_file_name(self, "Select a file", "XML files (*.xml)",
                                                        default_name=os.path.basename(fmu.fmu_filename) + ".xml")
            if filename:
                fmu.save_descriptor(filename)

    def save_fmu(self):
        if self.dropped_fmu.fmu:
            fmu = self.dropped_fmu.fmu
            filename = LastDirectory.get_save_file_name(self, "Select a file", "FMU files (*.fmu)",
                                                        default_name=os.path.basename(fmu.fmu_filename))
            if filename:
                with busy_cursor(window=self):
                    fmu.repack(filename)
                    logger.info(f"Modified version saved as {filename}.")

    def save_log(self):
        filename = LastDirectory.get_save_file_name(self, "Select a file", "TXT files (*.txt)",
                                                     default_name="log.txt")
        if filename:
            try:
                with open(filename, "wt", encoding="utf-8") as file:
                    file.write(str(self.log_widget.toPlainText()))
            except Exception as e:
                logger.error(f"{e}")

    def add_operation(self, name, usage, severity, operation, prompt=None, prompt_file=None, arg=None,
                      func=None, modifies=False, alternative=None) -> OperationButton:
        def apply(instance):
            if self.apply_operation(instance) and modifies:
                self.set_modified()

        if prompt:
            def operation_handler():
                local_arg = self.prompt_string(prompt)
                if local_arg:
                    apply(operation(local_arg))
        elif prompt_file:
            def operation_handler():
                local_arg = self.prompt_file(prompt_file)
                if local_arg:
                    apply(operation(local_arg))
        elif arg:
            def operation_handler():
                apply(operation(arg))
        else:
            def operation_handler():
                # Checker can be a list of operations!
                if isinstance(operation, list):
                    for op in operation:
                        apply(op())
                else:
                    apply(operation())

        button = OperationButton(name, func or operation_handler, alternative)
        self.set_tooltip(button, usage)
        button.setProperty("class", severity)
        return button

    def selected_check(self):
        """Run the checkers chosen in `CheckSelectionDialog`, with its settings of FMI-LS-REF."""
        if not self.dropped_fmu.fmu:
            return
        checkers = get_checkers()
        dialog = CheckSelectionDialog(checkers, self.check_selection, self.ls_ref_settings, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.check_selection = set(dialog.selected())
        self.ls_ref_settings = dialog.settings()
        for checker in dialog.selected():
            if issubclass(checker, OperationLsRefCheck):
                self.apply_operation(checker(**self.ls_ref_settings))
            else:
                self.apply_operation(checker())

    def compile_sources(self, ask_first: bool = False):
        """Compile the sources; after a compilation failure, ask for additional options and retry (until success
        or Cancel). With `ask_first` ("Advanced Compile"), ask for the options before the first attempt. The options
        are kept for the rest of the session."""
        if not self.dropped_fmu.fmu:
            return
        if ask_first:
            dialog = CompileOptionsDialog(self.compile_options, self.host_toolchain(), parent=self, failed=False)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.compile_options = dialog.values()
        while True:
            try:
                operation = OperationCompileSources(**self.compile_parameters())
            except ValueError as error:                 # unbalanced quotes
                logger.error(f"Invalid options: {error}.")
            else:
                if self.apply_operation(operation):
                    self.set_modified()
                    return
                if not operation.compilation_failed:
                    return
            dialog = CompileOptionsDialog(self.compile_options, self.host_toolchain(), parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.compile_options = dialog.values()

    def compile_parameters(self) -> dict[str, list[str]]:
        """Parameters of `OperationCompileSources` from the options typed in `CompileOptionsDialog`."""
        posix = os.name != "nt"
        return {
            "compiler_options": shlex.split(self.compile_options.get("compiler_options", ""), posix=posix),
            "linker_options": shlex.split(self.compile_options.get("linker_options", ""), posix=posix),
            "libraries": [name.strip() for name in self.compile_options.get("libraries", "").split(",")
                          if name.strip()],
        }

    @staticmethod
    def host_toolchain() -> Toolchain | None:
        try:
            return Toolchain.find()
        except OperationError:
            return None

    def prompt_string(self, message):
        text, ok = QInputDialog().getText(self, "Enter value", f"{message}:", QLineEdit.EchoMode.Normal, "")

        if ok and text:
            return text
        else:
            return None

    def prompt_file(self, access):
        if self.dropped_fmu.fmu:
            if access == 'read':
                filename = LastDirectory.get_open_file_name(self, "Select a file", "CSV files (*.csv)")
            else:
                filename = LastDirectory.get_save_file_name(self, "Select a file", "CSV files (*.csv)")

            if filename:
                return filename
        return None

    def update_fmu(self):
        self.fmu_modified = False
        self.update_buttons()
        if self.dropped_fmu.fmu:
            self.fmu_title.setText(os.path.basename(self.dropped_fmu.fmu.fmu_filename))
            self.log_widget.clear()
            self.apply_operation(OperationSummary())
            # The FMI version is now known: refresh the icon so that FMI-3 FMUs
            # (icon stored in terminalsAndIcons/icon.png) display correctly.
            self.dropped_fmu.set_image(get_fmu_icon_path(self.dropped_fmu.fmu, self.dropped_fmu.fmu.fmi_version))
        else:
            self.fmu_title.setText('')

    def apply_operation(self, operation) -> bool:
        """Apply `operation` to the loaded FMU. Returns whether it ended without an exception."""
        with window_log_context(self):
            return self._apply_operation(operation)

    def _apply_operation(self, operation) -> bool:
        if not self.dropped_fmu.fmu:
            return False
        self.log_widget.moveCursor(QTextCursor.MoveOperation.End)
        fmu_filename = os.path.basename(self.dropped_fmu.fmu.fmu_filename)
        logger.info('-' * 100)
        self.log_widget.insertHtml(f"<strong>{fmu_filename}: {operation}</strong><br>")

        apply_on = self.filter_list.get()
        if apply_on:
            self.log_widget.insertHtml(f"<i>Applied only for ports with  causality = " +
                                       ", ".join(apply_on) + "</i><br>")
        logger.info('-' * 100)
        with busy_cursor():
            try:
                self.dropped_fmu.fmu.apply_operation(operation, apply_on=apply_on)
                succeeded = True
            except Exception as e:
                logger.error(f"{e}")
                succeeded = False

        scroll_bar = self.log_widget.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        return succeeded


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    """Command line of `fmutool-gui` (without the program name)."""
    parser = argparse.ArgumentParser(prog="fmutool-gui", description="Analyze and modify your FMUs.")
    parser.add_argument("-debug", action="store_true", dest="debug",
                        help="show the debug messages in the log area, e.g. the command lines of 'Compile sources'")
    return parser.parse_args(arguments)


def main():
    application = Application(sys.argv)
    # Qt has removed its own options from arguments().
    arguments = parse_arguments(application.arguments()[1:])
    application.window = MainWindow(debug=arguments.debug)
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
