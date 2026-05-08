import os.path
import sys
import textwrap

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QFileDialog,
                               QInputDialog, QMenu)
from PySide6.QtGui import QTextCursor, QAction
from functools import partial

from fmu_manipulation_toolbox.gui.helper import Application, HelpWidget, DropZoneWidget, LogWidget
from fmu_manipulation_toolbox.operations import *
from fmu_manipulation_toolbox.remoting import (OperationAddRemotingWin32, OperationAddRemotingWin64, OperationAddFrontendWin32,
                                               OperationAddFrontendWin64)
from fmu_manipulation_toolbox.checker import get_checkers
from fmu_manipulation_toolbox.help import Help
from fmu_manipulation_toolbox.version import __version__ as version

logger = logging.getLogger("fmu_manipulation_toolbox")


class FilterWidget(QPushButton):
    def __init__(self, items: Optional[list[str]] = (), parent=None):
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

        line = 0
        self.dropped_fmu = DropZoneWidget()
        self.dropped_fmu.clicked.connect(self.update_fmu)
        self.layout.addWidget(self.dropped_fmu, line, 0, 4, 1)

        self.fmu_title = QLabel()
        self.fmu_title.setProperty("class", "title")
        self.layout.addWidget(self.fmu_title, line, 1, 1, 4)

        help_widget = HelpWidget()
        self.layout.addWidget(help_widget, line, 5, 1, 1)

        # Operations
        self.help = Help()
        operations_list = [
            ("Save port names",    '-dump-csv',           'save',    OperationSaveNamesToCSV, {"prompt_file": "write"}),
            ("Rename ports from CSV", '-rename-from-csv',   'modify',  OperationRenameFromCSV, {"prompt_file": "read"}),
            ("Remove Toplevel",       '-remove-toplevel',    'modify',  OperationStripTopLevel),
            ("Remove Regexp",         '-remove-regexp',      'removal', OperationRemoveRegexp, {"prompt": "regexp"}),
            ("Keep only Regexp",      '-keep-only-regexp',   'removal', OperationKeepOnlyRegexp, {"prompt": "regexp"}),
            ("Save description.xml",  '-extract-descriptor', 'save',    None, {"func": self.save_descriptor}),
            ("Trim Until",            '-trim-until',         'modify',  OperationTrimUntil, {"prompt": "Prefix"}),
            ("Merge Toplevel",        '-merge-toplevel',     'modify',  OperationMergeTopLevel),
            ("Remove all",            '-remove-all',         'removal', OperationRemoveRegexp, {"arg": ".*"}),
            ("Remove sources",        '-remove-sources',     'removal', OperationRemoveSources),
            ("Add Win32 remoting",    '-add-remoting-win32', 'info',    OperationAddRemotingWin32),
            ("Add Win64 remoting",    '-add-remoting-win64', 'info',    OperationAddRemotingWin64),
            ("Add Win32 frontend",    '-add-frontend-win32', 'info',    OperationAddFrontendWin32),
            ("Add Win64 frontend",    '-add-frontend-win64', 'info',    OperationAddFrontendWin64),
            ("Check",                 '-check',              'info',    get_checkers()),
        ]

        WIDTH = 5
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
        self.layout.addWidget(self.filter_list, line, 3, 1, 3)

        # Text
        line += 1
        self.log_widget = LogWidget()
        self.log_widget.insertHtml('<center><img src="fmu_manipulation_toolbox.png"/></center><br/>')
        self.layout.addWidget(self.log_widget, line, 0, 1, WIDTH + 1)

        # buttons
        line += 1
        self.exit_button = QPushButton('Exit')
        self.exit_button.clicked.connect(self.close)
        self.exit_button.setProperty("class", "quit")
        self.layout.addWidget(self.exit_button, line, 0, 1, 2)

        self.save_log_button = QPushButton('Save log as')
        self.save_log_button.clicked.connect(self.save_log)
        self.save_log_button.setProperty("class", "save")
        self.layout.addWidget(self.save_log_button, line, 2, 1, 2)

        self.save_fmu_button = QPushButton('Save modified FMU as')
        self.save_fmu_button.clicked.connect(self.save_fmu)
        self.save_fmu_button.setProperty("class", "save")
        self.set_tooltip(self.save_fmu_button, '-output')
        self.layout.addWidget(self.save_fmu_button, line, 4, 1, 2)

        # Fix the layout
        self.layout.setVerticalSpacing(4)
        self.layout.setHorizontalSpacing(4)
        self.layout.setContentsMargins(10, 10, 10, 10)
        for row in range(self.layout.rowCount()):
            self.layout.setRowMinimumHeight(row, 36)
        self.setLayout(self.layout)

        # show the window
        self.show()

        logger.info(" " * 80 + f"Version {version}")
        logger.info(self.__doc__)

    def load(self, fmu_path: str):
        """Load an FMU file programmatically."""
        from pathlib import Path
        self.dropped_fmu.set_fmu(Path(fmu_path))

    def closeEvent(self, event):
        event.accept()

    def set_tooltip(self, widget, usage):
        widget.setToolTip("\n".join(textwrap.wrap(self.help.usage(usage))))

    def reload_fmu(self):
        if self.dropped_fmu.fmu:
            filename = self.dropped_fmu.fmu.fmu_filename
            self.dropped_fmu.fmu = None
            self.dropped_fmu.set_fmu(filename)

    def save_descriptor(self):
        if self.dropped_fmu.fmu:
            fmu = self.dropped_fmu.fmu
            filename, ok = QFileDialog.getSaveFileName(self, "Select a file",
                                                       os.path.dirname(fmu.fmu_filename),
                                                       "XML files (*.xml)")
            if ok and filename:
                fmu.save_descriptor(filename)

    def save_fmu(self):
        if self.dropped_fmu.fmu:
            fmu = self.dropped_fmu.fmu
            filename, ok = QFileDialog.getSaveFileName(self, "Select a file",
                                                       os.path.dirname(fmu.fmu_filename),
                                                       "FMU files (*.fmu)")
            if ok and filename:
                fmu.repack(filename)
                logger.info(f"Modified version saved as {filename}.")

    def save_log(self):
        if self.dropped_fmu.fmu:
            default_dir = os.path.dirname(self.dropped_fmu.fmu.fmu_filename)
        else:
            default_dir = None
        filename, ok = QFileDialog.getSaveFileName(self, "Select a file",
                                                   default_dir,
                                                   "TXT files (*.txt)")
        if ok and filename:
            try:
                with open(filename, "wt") as file:
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

    def prompt_string(self, message):
        text, ok = QInputDialog().getText(self, "Enter value", f"{message}:", QLineEdit.EchoMode.Normal, "")

        if ok and text:
            return text
        else:
            return None

    def prompt_file(self, access):
        if self.dropped_fmu.fmu:
            default_dir = os.path.dirname(self.dropped_fmu.fmu.fmu_filename)

            if access == 'read':
                filename, ok = QFileDialog.getOpenFileName(self, "Select a file",
                                                           default_dir, "CSV files (*.csv)")
            else:
                filename, ok = QFileDialog.getSaveFileName(self, "Select a file",
                                                           default_dir, "CSV files (*.csv)")

            if ok and filename:
                return filename
        return None

    def update_fmu(self):
        if self.dropped_fmu.fmu:
            self.fmu_title.setText(os.path.basename(self.dropped_fmu.fmu.fmu_filename))
            self.log_widget.clear()
            self.apply_operation(OperationSummary())
        else:
            self.fmu_title.setText('')

    def apply_operation(self, operation):
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
