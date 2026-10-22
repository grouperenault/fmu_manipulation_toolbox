import os.path
import shlex
import sys
import textwrap

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QWidget, QGridLayout, QLabel, QLineEdit, QPushButton,
                               QInputDialog, QMenu, QDialog, QHBoxLayout, QVBoxLayout)
from PySide6.QtGui import QTextCursor, QAction
from functools import partial

from fmu_manipulation_toolbox.gui.helper import Application, DropZoneWidget, LastDirectory, get_fmu_icon_path
from fmu_manipulation_toolbox.gui.log import GuiLogHandler, LogWidget, busy_cursor, window_log_context
from fmu_manipulation_toolbox.operations import *
from fmu_manipulation_toolbox.remoting import (OperationAddRemotingWin32, OperationAddRemotingWin64, OperationAddFrontendWin32,
                                               OperationAddFrontendWin64)
from fmu_manipulation_toolbox.checker import get_checkers
from fmu_manipulation_toolbox.compiler import OperationCompileSources, Toolchain
from fmu_manipulation_toolbox.help import Help
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


class CompileOptionsDialog(QDialog):
    """Ask for additional compiler options, linker options and libraries after a compilation failure.

    Args:
        values (dict[str, str]): Pre-filled values, keyed by `compiler_options`, `linker_options` and `libraries`.
        toolchain (Toolchain | None): Compilers in use (`None` if unknown): named in the message, and the examples
            of the fields are written for them.
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

    def __init__(self, values: dict[str, str], toolchain: Toolchain | None, parent=None):
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
        message = QLabel(f"The compilation with {description} failed: see the log. Add options and retry.")
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

        # -- Retry / Cancel --
        retry_button = QPushButton("Retry")
        retry_button.setProperty("class", "save")
        retry_button.setDefault(True)
        retry_button.clicked.connect(self.accept)

        cancel_button = QPushButton("Cancel")
        cancel_button.setProperty("class", "quit")
        cancel_button.clicked.connect(self.reject)

        width = max(retry_button.sizeHint().width(), cancel_button.sizeHint().width(), 150)
        retry_button.setMinimumWidth(width)
        cancel_button.setMinimumWidth(width)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(cancel_button)
        button_row.addWidget(retry_button)
        layout.addSpacing(12)
        layout.addLayout(button_row)

    def values(self) -> dict[str, str]:
        return {key: edit.text().strip() for key, edit in self.edits.items()}


class MainWindow(QWidget):
    """
Analyze and modify your FMUs.

Note: modifying the modelDescription.xml can damage your FMU !
Communicating with the FMU-developer and adapting the way the FMU is generated, is preferable when possible.

    """

    def __init__(self):
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

        # Operations
        self.help = Help()
        # Grid of WIDTH columns, one line per theme: analysis and export, binary interfaces (green), name changes
        # (orange), removals (red).
        operations_list = [
            ("Check",                 '-check',              'info',    get_checkers()),
            ("Save description.xml",  '-extract-descriptor', 'info',    None, {"func": self.save_descriptor}),
            ("Save port names",       '-dump-csv',           'info',    OperationSaveNamesToCSV, {"prompt_file": "write"}),
            ("Compile sources",       '-compile-sources',    'info',    None, {"func": self.compile_sources}),
            ("Add Win32 remoting",    '-add-remoting-win32', 'info',    OperationAddRemotingWin32),
            ("Add Win32 frontend",    '-add-frontend-win32', 'info',    OperationAddFrontendWin32),
            ("Add Win64 remoting",    '-add-remoting-win64', 'info',    OperationAddRemotingWin64),
            ("Add Win64 frontend",    '-add-frontend-win64', 'info',    OperationAddFrontendWin64),
            ("Rename ports from CSV", '-rename-from-csv',    'modify',  OperationRenameFromCSV, {"prompt_file": "read"}),
            ("Trim Until",            '-trim-until',         'modify',  OperationTrimUntil, {"prompt": "Prefix"}),
            ("Remove Toplevel",       '-remove-toplevel',    'modify',  OperationStripTopLevel),
            ("Merge Toplevel",        '-merge-toplevel',     'modify',  OperationMergeTopLevel),
            ("Remove Regexp",         '-remove-regexp',      'removal', OperationRemoveRegexp, {"prompt": "regexp"}),
            ("Keep only Regexp",      '-keep-only-regexp',   'removal', OperationKeepOnlyRegexp, {"prompt": "regexp"}),
            ("Remove all",            '-remove-all',         'removal', OperationRemoveRegexp, {"arg": ".*"}),
            ("Remove sources",        '-remove-sources',     'removal', OperationRemoveSources),
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
        self.log_handler.register_window(self)
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
        self.log_widget.append_record(levelno, text)
        # The operations block the main thread: repaint each record immediately.
        QApplication.processEvents()

    def closeEvent(self, event):
        if self.log_handler.is_registered(self):
            self.log_handler.record_emitted.disconnect(self._on_record)
            self.log_handler.unregister_window(self)
        event.accept()

    def set_tooltip(self, widget, usage):
        widget.setToolTip("\n".join(line for paragraph in self.help.usage(usage).splitlines()
                                     for line in textwrap.wrap(paragraph)))

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
                      func=None) -> QPushButton:
        if prompt:
            def operation_handler():
                local_arg = self.prompt_string(prompt)
                if local_arg:
                    self.apply_operation(operation(local_arg))
        elif prompt_file:
            def operation_handler():
                local_arg = self.prompt_file(prompt_file)
                if local_arg:
                    self.apply_operation(operation(local_arg))
        elif arg:
            def operation_handler():
                self.apply_operation(operation(arg))
        else:
            def operation_handler():
                # Checker can be a list of operations!
                if isinstance(operation, list):
                    for op in operation:
                        self.apply_operation(op())
                else:
                    self.apply_operation(operation())

        button = QPushButton(name)
        self.set_tooltip(button, usage)
        button.setProperty("class", severity)
        if func:
            button.clicked.connect(func)
        else:
            button.clicked.connect(operation_handler)

        return button

    def compile_sources(self):
        """Compile the sources; after a compilation failure, ask for additional options and retry (until success
        or Cancel). The options are kept for the rest of the session."""
        if not self.dropped_fmu.fmu:
            return
        while True:
            try:
                operation = OperationCompileSources(**self.compile_parameters())
            except ValueError as error:                 # unbalanced quotes
                logger.error(f"Invalid options: {error}.")
            else:
                self.apply_operation(operation)
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
        if self.dropped_fmu.fmu:
            self.fmu_title.setText(os.path.basename(self.dropped_fmu.fmu.fmu_filename))
            self.log_widget.clear()
            self.apply_operation(OperationSummary())
            # The FMI version is now known: refresh the icon so that FMI-3 FMUs
            # (icon stored in terminalsAndIcons/icon.png) display correctly.
            self.dropped_fmu.set_image(get_fmu_icon_path(self.dropped_fmu.fmu, self.dropped_fmu.fmu.fmi_version))
        else:
            self.fmu_title.setText('')

    def apply_operation(self, operation):
        with window_log_context(self):
            self._apply_operation(operation)

    def _apply_operation(self, operation):
        if self.dropped_fmu.fmu:
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
                except Exception as e:
                    logger.error(f"{e}")

            scroll_bar = self.log_widget.verticalScrollBar()
            scroll_bar.setValue(scroll_bar.maximum())


def main():
    application = Application(sys.argv)
    application.window = MainWindow()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
