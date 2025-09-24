import os.path
import sys
import textwrap

from PySide6.QtCore import Qt, QUrl, QDir, Signal, QPoint, QModelIndex
from PySide6.QtWidgets import (QApplication, QWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QFileDialog,
                               QTextBrowser, QInputDialog, QMenu, QTreeView, QAbstractItemView, QTabWidget, QTableView,
                               QCheckBox)
from PySide6.QtGui import (QPixmap, QTextCursor, QStandardItem, QIcon, QDesktopServices, QAction,
                           QPainter, QColor, QImage, QStandardItemModel)
from functools import partial


from .gui_style import gui_style, log_color
from .operations import *
from .remoting import (OperationAddRemotingWin32, OperationAddRemotingWin64, OperationAddFrontendWin32,
                       OperationAddFrontendWin64)
from .assembly import Assembly, AssemblyNode
from .checker import checker_list
from .help import Help
from .version import __version__ as version

logger = logging.getLogger("fmu_manipulation_toolbox")


class DropZoneWidget(QLabel):
    WIDTH = 150
    HEIGHT = 150
    fmu = None
    last_directory = None
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.set_image(None)
        self.setProperty("class", "dropped_fmu")
        self.setFixedSize(self.WIDTH, self.HEIGHT)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            try:
                file_path = event.mimeData().urls()[0].toLocalFile()
            except IndexError:
                logger.error("Please select a regular file.")
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

        fmu_filename, _ = QFileDialog.getOpenFileName(parent=self, caption='Select FMU to Manipulate',
                                                      dir=default_directory, filter="FMU files (*.fmu)")
        if fmu_filename:
            self.set_fmu(fmu_filename)

    def set_image(self, filename=None):
        if not filename:
            filename = os.path.join(os.path.dirname(__file__), "resources", "drop_fmu.png")
        elif not os.path.isfile(filename):
            filename = os.path.join(os.path.dirname(__file__), "resources", "fmu.png")

        base_image = QImage(filename).scaled(self.WIDTH, self.HEIGHT, Qt.AspectRatioMode.IgnoreAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
        mask_filename = os.path.join(os.path.dirname(__file__), "resources", "mask.png")
        mask_image = QImage(mask_filename).scaled(self.WIDTH, self.HEIGHT, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation)
        rounded_image = QImage(self.WIDTH, self.HEIGHT, QImage.Format.Format_ARGB32)
        rounded_image.fill(QColor(0, 0, 0, 0))
        painter = QPainter()
        painter.begin(rounded_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(QPoint(0, 0), base_image)
        painter.drawImage(QPoint(0, 0), mask_image)
        painter.end()
        pixmap = QPixmap.fromImage(rounded_image)

        self.setPixmap(pixmap)

    def set_fmu(self, filename: str):
        try:
            self.last_directory = os.path.dirname(filename)
            self.fmu = FMU(filename)
            self.set_image(os.path.join(self.fmu.tmp_directory, "model.png"))
        except Exception as e:
            logger.error(f"Cannot load this FMU: {e}")
            self.set_image(None)
            self.fmu = None
        self.clicked.emit()


class LogHandler(logging.Handler):
    LOG_COLOR = {
        logging.DEBUG: QColor(log_color["DEBUG"]),
        logging.INFO: QColor(log_color["INFO"]),
        logging.WARNING: QColor(log_color["WARNING"]),
        logging.ERROR: QColor(log_color["ERROR"]),
        logging.CRITICAL: QColor(log_color["CRITICAL"]),
    }

    def __init__(self, text_browser, level):
        super().__init__(level)
        self.text_browser: QTextBrowser = text_browser
        logger.addHandler(self)
        logger.setLevel(level)

    def emit(self, record) -> None:
        self.text_browser.setTextColor(self.LOG_COLOR[record.levelno])
        self.text_browser.insertPlainText(record.msg+"\n")


class LogWidget(QTextBrowser):
    def __init__(self, parent=None, level=logging.INFO):
        super().__init__(parent)

        self.setMinimumWidth(900)
        self.setMinimumHeight(500)
        self.setSearchPaths([os.path.join(os.path.dirname(__file__), "resources")])
        self.insertHtml('<center><img src="fmu_manipulation_toolbox.png"/></center><br/>')
        self.log_handler = LogHandler(self, logging.DEBUG)

    def loadResource(self, _, name):
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
        self.setAlignment(Qt.AlignmentFlag.AlignRight)

    def mousePressEvent(self, event):
        QDesktopServices.openUrl(QUrl(self.HELP_URL))


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


class AssemblyTreeWidget(QTreeView):
    class AssemblyTreeModel(QStandardItemModel):

        def __init__(self, assembly: Assembly, parent=None):
            super().__init__(parent)

            self.lastDroppedItems = []
            self.pendingRemoveRowsAfterDrop = False
            self.setHorizontalHeaderLabels(['col1'])
            self.dnd_target_node: Optional[AssemblyNode] = None

            self.icon_container = QIcon(os.path.join(os.path.dirname(__file__), 'resources', 'container.png'))
            self.icon_fmu = QIcon(os.path.join(os.path.dirname(__file__), 'resources', 'icon_fmu.png'))

            if assembly:
                self.add_node(assembly.root, self)

        def add_node(self, node: AssemblyNode, parent_item):
            # Add Container
            item = QStandardItem(self.icon_container, node.name)
            parent_item.appendRow(item)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled |
                          Qt.ItemFlag.ItemIsDropEnabled)
            item.setData(node, role=Qt.ItemDataRole.UserRole + 1)
            item.setData("container", role=Qt.ItemDataRole.UserRole + 2)

            # Add FMU's
            children_name = node.children.keys()
            for fmu_name in node.fmu_names_list:
                if fmu_name not in children_name:
                    fmu_node = QStandardItem(self.icon_fmu, fmu_name)
                    fmu_node.setData(node, role=Qt.ItemDataRole.UserRole + 1)
                    fmu_node.setData("fmu", role=Qt.ItemDataRole.UserRole + 2)
                    fmu_node.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                                      Qt.ItemFlag.ItemIsDragEnabled)
                    item.appendRow(fmu_node)

            # Add Sub-Containers
            for child in node.children.values():
                self.add_node(child, item)

        def insertRows(self, row, count, parent=QModelIndex()):
            self.dnd_target_node = parent.data(role=Qt.ItemDataRole.UserRole + 1)
            return super().insertRows(row, count, parent=parent)

        def removeRows(self, row, count, parent=QModelIndex()):
            if not self.dnd_target_node:
                logger.error("NO DROP NODE!?")

            source_index = self.itemFromIndex(parent).child(row, 0).data(role=Qt.ItemDataRole.UserRole+1)
            logger.debug(f"{source_index} ==> {self.dnd_target_node.name}")

            self.dnd_target_node = None
            return super().removeRows(row, count, parent)

        def dropMimeData(self, data, action, row, column, parent: QModelIndex):
            if parent.column() < 0:  # Avoid to drop item as a sibling of the root.
                return False
            return super().dropMimeData(data, action, row, column, parent)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.model = self.AssemblyTreeModel(None)
        self.setModel(self.model)

        self.expandAll()
        self.setDropIndicatorShown(True)
        self.setDragDropOverwriteMode(False)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setRootIsDecorated(True)
        self.setHeaderHidden(True)

    def load_container(self, filename):
        assembly = Assembly(filename)
        self.model = self.AssemblyTreeModel(assembly)
        self.setModel(self.model)

    def setTopIndex(self):
        topIndex = self.model.index(0, 0, self.rootIndex())
        logger.debug(topIndex.isValid(), topIndex.model())
        if topIndex.isValid():
            self.setCurrentIndex(topIndex)
            if self.layoutCheck:
                self.model.layoutChanged.disconnect(self.setTopIndex)
        else:
            if not self.layoutCheck:
                self.model.layoutChanged.connect(self.setTopIndex)
                self.layoutCheck = True


    def dragEnterEvent2(self, event):
        if event.mimeData().hasImage:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent2(self, event):
        if event.mimeData().hasImage:
            event.accept()
        else:
            event.ignore()

    def dropEvent2(self, event):
        if event.mimeData().hasImage:
            event.setDropAction(Qt.DropAction.CopyAction)
            try:
                file_path = event.mimeData().urls()[0].toLocalFile()
            except IndexError:
                logger.error("Please select a regular file.")
                return
            logger.debug(f"DROP: {file_path}")
            event.accept()
        else:
            event.ignore()


class AssemblPropertiesWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = QGridLayout()
        self.layout.setVerticalSpacing(4)
        self.layout.setHorizontalSpacing(4)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.setLayout(self.layout)

        mt_check = QCheckBox("Multi-Threaded", self)
        self.layout.addWidget(mt_check, 1, 0)

        profiling_check = QCheckBox("Profiling", self)
        self.layout.addWidget(profiling_check, 1, 1)

        auto_inputs_check = QCheckBox("Auto Inputs", self)
        self.layout.addWidget(auto_inputs_check, 0, 0)

        auto_outputs_check = QCheckBox("Auto Outputs", self)
        self.layout.addWidget(auto_outputs_check, 0, 1)

        auto_links_check = QCheckBox("Auto Links", self)
        self.layout.addWidget(auto_links_check, 0, 2)


class AssemblyTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        table = AssemblPropertiesWidget(parent=self)
        self.addTab(table, "Properties")
        table = QTableView()
        self.addTab(table, "Links")
        table = QTableView()
        self.addTab(table, "Inputs")
        table = QTableView()
        self.addTab(table, "Outputs")
        table = QTableView()
        self.addTab(table, "Start values")

        self.tabBar().setDocumentMode(True)
        self.tabBar().setExpanding(True)


class WindowWithLayout(QWidget):
    def __init__(self, title: str):
        super().__init__(None)  # Do not set parent to have a separated window
        self.setWindowTitle(title)

        self.layout = QGridLayout()
        self.layout.setVerticalSpacing(4)
        self.layout.setHorizontalSpacing(4)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.setLayout(self.layout)


class MainWindow(WindowWithLayout):
    def __init__(self):
        super().__init__('FMU Manipulation Toolbox')

        self.dropped_fmu = DropZoneWidget()
        self.dropped_fmu.clicked.connect(self.update_fmu)

        self.layout.addWidget(self.dropped_fmu, 0, 0, 4, 1)

        self.fmu_title = QLabel()
        self.fmu_title.setProperty("class", "title")
        self.layout.addWidget(self.fmu_title, 0, 1, 1, 4)

        self.container_window = None
        #TODO: Container Window
        #container_button = QPushButton("Make a container")
        #container_button.setProperty("class", "quit")
        #container_button.clicked.connect(self.launch_container)
        #self.layout.addWidget(container_button, 4, 1, 1, 1)

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
        self.apply_filter_label = QLabel("Apply only on: ")
        self.layout.addWidget(self.apply_filter_label, line, 2, 1, 1, alignment=Qt.AlignmentFlag.AlignRight)
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

    def closeEvent(self, event):
        if self.container_window:
            self.container_window.close()
            self.container_window = None
        event.accept()

    def launch_container(self):
        if not self.container_window:
            self.container_window = ContainerWindow(self)

    def closing_container(self):
        self.container_window = None

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


class ContainerWindow(WindowWithLayout):
    def __init__(self, parent: MainWindow):
        super().__init__('FMU Manipulation Toolbox - Container')
        self.main_window = parent
        self.last_directory = None

        # ROW 0
        load_button = QPushButton("Load Description")
        load_button.clicked.connect(self.load_container)
        load_button.setProperty("class", "quit")
        self.layout.addWidget(load_button, 0, 0)

        self.container_label = QLabel()
        self.container_label.setProperty("class", "title")
        self.container_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.container_label, 0, 1, 1, 2)

        # ROW 1
        add_fmu_button = QPushButton("Add FMU")
        add_fmu_button.setProperty("class", "modify")
        add_fmu_button.setDisabled(True)
        self.layout.addWidget(add_fmu_button, 1, 1)

        add_sub_button = QPushButton("Add SubContainer")
        add_sub_button.setProperty("class", "modify")
        add_sub_button.setDisabled(True)
        self.layout.addWidget(add_sub_button, 1, 2)

        self.assembly_tree = AssemblyTreeWidget(parent=self)
        self.assembly_tree.setMinimumHeight(600)
        self.assembly_tree.setMinimumWidth(200)
        self.layout.addWidget(self.assembly_tree, 1, 0, 3, 1)

        # ROW 2
        del_fmu_button = QPushButton("Remove FMU")
        del_fmu_button.setProperty("class", "removal")
        del_fmu_button.setDisabled(True)
        self.layout.addWidget(del_fmu_button, 2, 1)

        del_sub_button = QPushButton("Remove SubContainer")
        del_sub_button.setProperty("class", "removal")
        del_sub_button.setDisabled(True)
        self.layout.addWidget(del_sub_button, 2, 2)

        # ROW 3
        self.assembly_tab = AssemblyTabWidget(parent=self)
        self.assembly_tab.setMinimumWidth(600)
        self.layout.addWidget(self.assembly_tab, 3, 1, 1, 2)

        # ROW 4
        close_button = QPushButton("Close")
        close_button.setProperty("class", "quit")
        close_button.clicked.connect(self.close)
        self.layout.addWidget(close_button, 4, 0)

        save_button = QPushButton("Save Container")
        save_button.setProperty("class", "save")
        self.layout.addWidget(save_button, 4, 2)

        self.assembly_tree.selectionModel().currentChanged.connect(self.item_selected)
        topIndex = self.assembly_tree.model.index(0, 0, self.assembly_tree.rootIndex())
        self.assembly_tree.setCurrentIndex(topIndex)

        self.show()

    def closeEvent(self, event):
        if self.main_window:
            self.main_window.closing_container()
        event.accept()

    def item_selected(self, current: QModelIndex, previous: QModelIndex):
        if current.isValid():
            node = current.data(role=Qt.ItemDataRole.UserRole + 1)
            node_type = current.data(role=Qt.ItemDataRole.UserRole + 2)
            self.container_label.setText(f"{node.name} ({node_type})")
        else:
            self.container_label.setText("")

    def load_container(self):
        if self.last_directory:
            default_directory = self.last_directory
        else:
            default_directory = os.path.expanduser('~')

        filename, _ = QFileDialog.getOpenFileName(parent=self, caption='Select FMU to Manipulate',
                                                  dir=default_directory,
                                                  filter="JSON files (*.json);;SSP files (*.ssp)")
        if filename:
            try:
                self.last_directory = os.path.dirname(filename)
                self.assembly_tree.load_container(filename)
            except Exception as e:
                logger.error(e)


class Application(QApplication):
    """
Analyse and modify your FMUs.

Note: modifying the modelDescription.xml can damage your FMU !
Communicating with the FMU-developer and adapting the way the FMU is generated, is preferable when possible.

    """
    def __init__(self, *args, **kwargs):
        self.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
        super().__init__(*args, **kwargs)


        QDir.addSearchPath('images', os.path.join(os.path.dirname(__file__), "resources"))
        self.setStyleSheet(gui_style)

        if os.name == 'nt':
            import ctypes
            self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), 'resources', 'icon-round.png')))

            # https://stackoverflow.com/questions/1551605/how-to-set-applications-taskbar-icon-in-windows-7/1552105#1552105

            application_id = 'FMU_Manipulation_Toolbox'  # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(application_id)
        else:
            self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), 'resources', 'icon.png')))

        self.window = MainWindow()


def main():
    application = Application(sys.argv)

    logger.info(" " * 80 + f"Version {version}")
    logger.info(application.__doc__)

    sys.exit(application.exec())


if __name__ == "__main__":
    main()
