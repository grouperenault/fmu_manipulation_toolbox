import os.path
import sys
from .version import __version__ as version
from PyQt5.QtCore import Qt, QObject, QUrl, pyqtSignal, QDir
from PyQt5.QtWidgets import (QApplication, QWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QFileDialog,
                             QTextBrowser, QInputDialog, QMenu, QAction)
from PyQt5.QtGui import QPixmap, QImage, QFont, QTextCursor, QIcon, QColor, QPainter, QBrush, QDesktopServices
import textwrap
from functools import partial
from typing import Optional

from .fmu_operations import *
from .checker import checker_list
from .help import Help


class DropZoneWidget(QLabel):
    WIDTH = 150
    HEIGHT = 150
    fmu = None
    last_directory = None
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.set_image(None)
        self.setProperty("class", "dropped_fmu")
        self.setFixedSize(self.WIDTH, self.HEIGHT)

    def dragEnterEvent(self, event):
        if event.mimeData().hasImage:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasImage:
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasImage:
            event.setDropAction(Qt.CopyAction)
            try:
                file_path = event.mimeData().urls()[0].toLocalFile()
            except IndexError:
                print("Please select a regular file.")
                return
            self.set_fmu(file_path)
            event.accept()
        else:
            event.ignore()

    def mousePressEvent(self, event):
        if self.last_directory:
            default_directory = self.last_directory
        else:
            default_directory = os.path.expanduser('~')

        fmu_filename, _ = QFileDialog.getOpenFileName(self, 'Select FMU to Manipulate',
                                                      default_directory, "FMU files (*.fmu)")
        if fmu_filename:
            self.set_fmu(fmu_filename)

    def set_image(self, filename=None):
        if not filename:
            filename = os.path.join(os.path.dirname(__file__), "resources", "drop_fmu.png")
        elif not os.path.isfile(filename):
            filename = os.path.join(os.path.dirname(__file__), "resources", "fmu.png")

        image = QImage(filename).scaled(self.WIDTH-4, self.HEIGHT-4, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        pixmap = QPixmap.fromImage(image)
        rounded = self.make_pixmap_rounded(pixmap)
        self.setPixmap(rounded)

    def make_pixmap_rounded(self, pixmap):
        rounded = QPixmap(pixmap.size())
        rounded.fill(QColor("transparent"))

        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(pixmap))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(pixmap.rect(), 20, 20)
        del painter    # Mandatory to avoid a crash
        self.update()  # Mandatory to avoid a crash
        return rounded

    def set_fmu(self, filename):
        try:
            self.last_directory = os.path.dirname(filename)
            self.fmu = FMU(filename)
            self.set_image(os.path.join(self.fmu.tmp_directory, "model.png"))
        except Exception as e:
            print(f"ERROR: Cannot load this FMU: {e}")
            self.set_image(None)
            self.fmu = None
        self.clicked.emit()


class LogWidget(QTextBrowser):
    class XStream(QObject):
        _stdout = None
        _stderr = None
        messageWritten = pyqtSignal(str)

        def flush(self):
            pass

        @staticmethod
        def fileno():
            return -1

        def write(self, msg):
            if not self.signalsBlocked():
                self.messageWritten.emit(msg)

        @staticmethod
        def stdout():
            if not LogWidget.XStream._stdout:
                LogWidget.XStream._stdout = LogWidget.XStream()
                sys.stdout = LogWidget.XStream._stdout
            return LogWidget.XStream._stdout

        @staticmethod
        def stderr():
            if not LogWidget.XStream._stderr:
                LogWidget.XStream._stderr = LogWidget.XStream()
                sys.stderr = LogWidget.XStream._stderr
            return LogWidget.XStream._stderr

    def __init__(self):
        super().__init__()
        if os.name == 'nt':
            font = QFont('Consolas')
            font.setPointSize(10)
        else:
            font = QFont('Courier New')
            font.setPointSize(12)
        self.setFont(font)
        self.setMinimumWidth(800)
        self.setMinimumHeight(480)

        self.insertHtml('<center><img src="fmu_manipulation_toolbox.png"/></center><br>')
        LogWidget.XStream.stdout().messageWritten.connect(self.insertPlainText)
        LogWidget.XStream.stderr().messageWritten.connect(self.insertPlainText)

    def loadResource(self, type, name):
        image_path = os.path.join(os.path.dirname(__file__), "resources", name.toString())
        return QPixmap(image_path)


class HelpWidget(QLabel):
    HELP_URL = "https://github.com/grouperenault/fmu_manipulation_toolbox/blob/main/README.md"

    def __init__(self):
        super().__init__()
        self.setProperty("class", "help")

        filename = os.path.join(os.path.dirname(__file__), "resources", "help.png")
        image = QPixmap(filename)
        self.setPixmap(image)
        self.setAlignment(Qt.AlignRight)

    def mousePressEvent(self, event):
        QDesktopServices.openUrl(QUrl(self.HELP_URL))


class FilterWidget(QPushButton):
    def __init__(self, items: Optional[list[str]] = (), parent=None):
        super().__init__(parent)
        self.items_selected = set(items)
        self.nb_items = len(items)
        self.update_filter_text()
        if items:
            menu = QMenu()
            for item in items:
                action = QAction(item, self)
                action.setCheckable(True)
                action.setChecked(True)
                action.triggered.connect(partial(self.toggle_item, action))
                menu.addAction(action)
            self.setMenu(menu)

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


class FMUManipulationToolboxlMainWindow(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setWindowTitle('FMU Manipulation Toolbox')

        # set the grid layout
        self.layout = QGridLayout()
        self.setLayout(self.layout)

        self.dropped_fmu = DropZoneWidget()
        self.dropped_fmu.clicked.connect(self.update_fmu)
        self.layout.addWidget(self.dropped_fmu, 0, 0, 4, 1)

        font = QFont('Verdana')
        font.setPointSize(14)
        font.setBold(True)
        self.fmu_title = QLabel()
        self.fmu_title.setFont(font)
        self.layout.addWidget(self.fmu_title, 0, 1, 1, 4)

        help_widget = HelpWidget()
        self.layout.addWidget(help_widget, 0, 5, 1, 1)

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
            ("Check",                 '-check',              'info',    checker_list),
        ]

        width = 5
        line = 1
        for i, operation in enumerate(operations_list):
            col = i % width + 1
            line = int(i / width) + 1

            if len(operation) < 5:
                self.add_operation(operation[0], operation[1], operation[2], operation[3], line, col)
            else:
                self.add_operation(operation[0], operation[1], operation[2], operation[3], line, col, **operation[4])

        line += 1
        self.apply_filter_label = QLabel("Apply modification only on: ")
        self.layout.addWidget(self.apply_filter_label, line, 1, 1, 2, alignment=Qt.AlignRight)
        self.set_tooltip(self.apply_filter_label, 'gui-apply-only')

        causality = ["parameter", "calculatedParameter", "input", "output", "local", "independent"]
        self.filter_list = FilterWidget(items=causality)
        self.layout.addWidget(self.filter_list, line, 3, 1, 3)
        self.filter_list.setProperty("class", "quit")

        # Text
        line += 1
        self.log_widget = LogWidget()
        self.layout.addWidget(self.log_widget, line, 0, 1, width + 1)

        # buttons
        line += 1

        reload_button = QPushButton('Reload')
        self.layout.addWidget(reload_button, 4, 0, 1, 1)
        reload_button.clicked.connect(self.reload_fmu)
        reload_button.setProperty("class", "quit")

        exit_button = QPushButton('Exit')
        self.layout.addWidget(exit_button, line, 0, 1, 2)
        exit_button.clicked.connect(self.close)
        exit_button.setProperty("class", "quit")

        save_log_button = QPushButton('Save log as')
        self.layout.addWidget(save_log_button, line, 2, 1, 2)
        save_log_button.clicked.connect(self.save_log)
        save_log_button.setProperty("class", "save")

        save_fmu_button = QPushButton('Save modified FMU as')
        self.layout.addWidget(save_fmu_button, line, 4, 1, 2)
        save_fmu_button.clicked.connect(self.save_fmu)
        save_fmu_button.setProperty("class", "save")
        self.set_tooltip(save_fmu_button, '-output')

        # show the window
        self.show()

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
                print(f"Modified version saved as {filename}.")

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
                print(f"ERROR: {e}")

    def add_operation(self, name, usage, severity, operation, x, y, prompt=None, prompt_file=None, arg=None,
                      func=None):
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
        self.layout.addWidget(button, x, y)

    def prompt_string(self, message):
        text, ok = QInputDialog().getText(self, "Enter value", f"{message}:", QLineEdit.Normal, "")

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
            self.log_widget.moveCursor(QTextCursor.End)
            fmu_filename = os.path.basename(self.dropped_fmu.fmu.fmu_filename)
            print('-' * 100)
            self.log_widget.insertHtml(f"<strong>{fmu_filename}: {operation}</strong><br>")

            apply_on = self.filter_list.get()
            if apply_on:
                self.log_widget.insertHtml(f"<i>Applied only for ports with  causality = " +
                                           ", ".join(apply_on) + "</i><br>")
            print('-' * 100)
            try:
                self.dropped_fmu.fmu.apply_operation(operation, apply_on=apply_on)
            except Exception as e:
                print(f"ERROR: {e}")

            scroll_bar = self.log_widget.verticalScrollBar()
            scroll_bar.setValue(scroll_bar.maximum())


class Application(QApplication):
    """
Analyse and modify your FMUs.

Note: modifying the modelDescription.xml can damage your FMU ! Communicating with the FMU-developer and adapting the
way the FMU is generated, is preferable when possible.

    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        QDir.addSearchPath('images', os.path.join(os.path.dirname(__file__), "resources"))
        font = QFont("Verdana")
        font.setPointSize(10)
        self.setFont(font)
        css_dark = """
QWidget                  {background: #4b4e51; color: #b5bab9}
QPushButton           { min-height: 30px; padding: 1px 1px 0.2em 0.2em; border: 1px solid #282830; border-radius: 5px;}
QComboBox             { min-height: 30px; padding: 1px 1px 0.2em 0.2em; border: 1px solid #282830; border-radius: 5px;}
QPushButton:pressed      { border: 2px solid #282830; }
QPushButton.info         {background-color: #4e6749; color: #dddddd;}
QPushButton.info:hover   {background-color: #5f7850; color: #dddddd;}
QPushButton.info:hover   {background-color: #5f7850; color: #dddddd;}
QPushButton.modify       {background-color: #98763f; color: #dddddd;}
QPushButton.modify:hover {background-color: #a9874f; color: #dddddd;}
QPushButton.removal      {background-color: #692e2e; color: #dddddd;}
QPushButton.removal:hover{background-color: #7a3f3f; color: #dddddd;}
QPushButton.save         {background-color: #564967; color: #dddddd;}
QPushButton.save:hover   {background-color: #675a78; color: #dddddd;}
QPushButton.quit         {background-color: #4571a4; color: #dddddd;}
QPushButton.quit:hover   {background-color: #5682b5; color: #dddddd;}
QToolTip                 {color: black}
QLabel.dropped_fmu       {background-color: #b5bab9; border: 2px dashed #282830; border-radius: dashed 20px;}
QLabel.dropped_fmu:hover {background-color: #c6cbca; border: 2px dashed #282830; border-radius: dashed 20px;}
QTextBrowser             {background-color: #282830; color: #b5bab9;}
QMenu                               {font-size: 18px;}
QMenu::item                         {padding: 2px 250px 2px 20px; border: 1px solid transparent;}
QMenu::item::indicator              {width: 32px; height: 32px; }
QMenu::indicator:checked            {image: url(images:checkbox-checked.png);}
QMenu::indicator:checked:hover      {image: url(images:checkbox-checked-hover.png);}
QMenu::indicator:checked:disabled   {image: url(images:checkbox-checked-disabled.png);}
QMenu::indicator:unchecked          {IconWidth: 50px; image: url(images:checkbox-unchecked.png); }
QMenu::indicator:unchecked:hover    {width: 35px; image: url(images:checkbox-unchecked-hover.png); }
QMenu::indicator:unchecked:disabled {width: 35px; image: url(images:checkbox-unchecked-disabled.png); }
"""

        self.setStyleSheet(css_dark)


        if os.name == 'nt':
            self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), 'resources', 'icon-round.png')))

            # https://stackoverflow.com/questions/1551605/how-to-set-applications-taskbar-icon-in-windows-7/1552105#1552105
            import ctypes
            application_id = 'FMU_Manipulation_Toolbox'  # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(application_id)
        else:
            self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), 'resources', 'icon.png')))

        self.window = FMUManipulationToolboxlMainWindow()


def main():
    application = Application(sys.argv)

    print(" " * 80, f"Version {version}")
    print(application.__doc__)

    sys.exit(application.exec())
