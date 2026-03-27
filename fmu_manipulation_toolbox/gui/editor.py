"""
PySide6 – FMU Variable Editor
Drop zone to load an FMU + 5-column editable table.
"""

import logging
import os
import sys
from enum import Enum
from typing import List, Optional, Any, Dict

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import (
    QMainWindow, QTableView, QHeaderView, QPushButton,
    QVBoxLayout, QHBoxLayout, QWidget, QLabel, QFileDialog,
    QLineEdit, QGridLayout, QStatusBar, QMessageBox,
)

from fmu_manipulation_toolbox.gui.dropfile import DropZoneWidget
from fmu_manipulation_toolbox.operations import FMU, FMUPort, OperationAbstract
from fmu_manipulation_toolbox.gui.application import Application
from fmu_manipulation_toolbox.gui.style import log_color

logger = logging.getLogger("fmu_manipulation_toolbox")


class StatusBarLogHandler(logging.Handler):
    """Logging handler that displays messages in a QStatusBar with level-based colors."""

    LOG_COLORS = {
        logging.DEBUG: log_color["DEBUG"],
        logging.INFO: log_color["INFO"],
        logging.WARNING: log_color["WARNING"],
        logging.ERROR: log_color["ERROR"],
        logging.CRITICAL: log_color["CRITICAL"],
    }

    def __init__(self, status_bar: QStatusBar, level=logging.INFO):
        super().__init__(level)
        self._status_bar = status_bar
        logger.addHandler(self)
        logger.setLevel(level)

    def emit(self, record):
        color = self.LOG_COLORS.get(record.levelno, log_color["INFO"])
        self._status_bar.setStyleSheet(f"QStatusBar {{ color: {color}; }}")
        self._status_bar.showMessage(self.format(record), 10000)


class Causality(Enum):
    INPUT = "input"
    OUTPUT = "output"
    PARAMETER = "parameter"
    LOCAL = "local"
    INDEPENDENT = "independent"
    CALCULATED_PARAMETER = "calculatedParameter"
    STRUCTURAL_PARAMETER = "structuralParameter"



class FMUVariable:
    """Represents an FMU variable."""

    def __init__(self, name: str, causality: Causality,
                 fmi_type: str = "", description: str = ""):
        self.original_name = name
        self.name = name
        self.causality = causality
        self.fmi_type = fmi_type
        self.description = description
        self._original_description = description

    @property
    def is_modified(self) -> bool:
        """True if the user has modified at least one field."""
        return (self.name != self.original_name
                or self.description != self._original_description)


class OperationCollectPorts(OperationAbstract):
    """Collects variables, FMU info and the DefaultExperiment."""

    def __init__(self):
        self.variables: List[FMUVariable] = []
        # FMU metadata
        self.model_name: str = ""
        self.generation_tool: str = ""
        self.generation_date: str = ""
        # DefaultExperiment
        self.start_time: str = ""
        self.stop_time: str = ""
        self.step_size: str = ""

    def __repr__(self):
        return "Collect FMU ports"

    def fmi_attrs(self, attrs):
        self.model_name = attrs.get("modelName", "")
        self.generation_tool = attrs.get("generationTool", "")
        self.generation_date = attrs.get("generationDateAndTime", "")

    def experiment_attrs(self, attrs):
        self.start_time = attrs.get("startTime", "")
        self.stop_time = attrs.get("stopTime", "")
        self.step_size = attrs.get("stepSize", "")

    def port_attrs(self, fmu_port: FMUPort) -> int:
        causality_str = fmu_port.get("causality", "local")
        try:
            causality = Causality(causality_str)
        except ValueError:
            causality = Causality.LOCAL

        var = FMUVariable(
            name=fmu_port["name"],
            causality=causality,
            fmi_type=fmu_port.fmi_type or "",
            description=fmu_port.get("description", ""),
        )
        self.variables.append(var)
        return 0


class OperationApplyEdits(OperationAbstract):
    """Applies edits (name, description, experiment) to the FMU."""

    def __init__(self, edits: Dict[str, FMUVariable],
                 start_time: Optional[str] = None,
                 stop_time: Optional[str] = None):
        """
        Args:
            edits: dictionary {original_name: modified FMUVariable}
            start_time: new startTime value (None = no change)
            stop_time: new stopTime value (None = no change)
        """
        self.edits = edits
        self.start_time = start_time
        self.stop_time = stop_time

    def __repr__(self):
        return f"Apply {len(self.edits)} edit(s)"

    def experiment_attrs(self, attrs):
        if self.start_time:
            attrs["startTime"] = self.start_time
        else:
            attrs.pop("startTime", None)

        if self.stop_time:
            attrs["stopTime"] = self.stop_time
        else:
            attrs.pop("stopTime", None)


    @staticmethod
    def _set_port_attr(fmu_port: FMUPort, key: str, value: str):
        """Modify a port attribute, creating it if it does not exist."""
        try:
            fmu_port[key] = value
        except KeyError:
            fmu_port.attrs_list[0][key] = value

    def port_attrs(self, fmu_port: FMUPort) -> int:
        original_name = fmu_port["name"]
        var = self.edits.get(original_name)
        if var is None:
            return 0

        if var.name != var.original_name:
            fmu_port["name"] = var.name

        if var.description != var._original_description:
            if var.description:
                self._set_port_attr(fmu_port, "description", var.description)
            elif "description" in fmu_port:
                for attrs in fmu_port.attrs_list:
                    attrs.pop("description", None)

        return 0


def _make_icon(letter: str, color: QColor) -> QIcon:
    size = 24
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(QPen(color.darker(120), 1))
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 5, 5)
    painter.setPen(Qt.GlobalColor.white)
    painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    return QIcon(pixmap)


_ICON_DEFS = {
    Causality.INPUT:                ("I", "#2196F3"),
    Causality.OUTPUT:               ("O", "#4CAF50"),
    Causality.PARAMETER:            ("P", "#FF9800"),
    Causality.LOCAL:                ("L", "#9E9E9E"),
    Causality.INDEPENDENT:          ("T", "#9C27B0"),
    Causality.CALCULATED_PARAMETER: ("C", "#795548"),
    Causality.STRUCTURAL_PARAMETER: ("S", "#607D8B"),
}
_icon_cache: dict[Causality, QIcon] = {}


def causality_icon(c: Causality) -> QIcon:
    if c not in _icon_cache:
        letter, color = _ICON_DEFS.get(c, ("?", "#000000"))
        _icon_cache[c] = _make_icon(letter, QColor(color))
    return _icon_cache[c]


class FMUVariableModel(QAbstractTableModel):
    COLUMNS = ["", "Causality", "Type", "Name", "Description"]
    COL_ICON = 0
    COL_CAUSALITY = 1
    COL_TYPE = 2
    COL_NAME = 3
    COL_DESCRIPTION = 4

    MODIFIED_COLOR = QColor("#FF9800")

    def __init__(self, variables: Optional[List[FMUVariable]] = None, parent=None):
        super().__init__(parent)
        self._variables: List[FMUVariable] = variables or []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._variables)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        var = self._variables[index.row()]
        col = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == self.COL_CAUSALITY:
                return var.causality.value
            if col == self.COL_NAME:
                return var.name
            if col == self.COL_TYPE:
                return var.fmi_type
            if col == self.COL_DESCRIPTION:
                return var.description

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == self.COL_NAME and var.name != var.original_name:
                return self.MODIFIED_COLOR
            if col == self.COL_DESCRIPTION and var.description != var._original_description:
                return self.MODIFIED_COLOR

        if role == Qt.ItemDataRole.DecorationRole and col == self.COL_ICON:
            return causality_icon(var.causality)

        if role == Qt.ItemDataRole.TextAlignmentRole and col == self.COL_ICON:
            return Qt.AlignmentFlag.AlignCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.column() in (self.COL_NAME, self.COL_DESCRIPTION):
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value: Any,
                role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        var = self._variables[index.row()]
        col = index.column()
        if col == self.COL_NAME:
            var.name = value
        elif col == self.COL_DESCRIPTION:
            var.description = value
        else:
            return False
        self.dataChanged.emit(index, index, [role])
        return True

    def set_variables(self, variables: List[FMUVariable]):
        self.beginResetModel()
        self._variables = variables
        self.endResetModel()

    @property
    def variables(self) -> List[FMUVariable]:
        """Direct access to the variable list."""
        return self._variables


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FMU Variable Editor")
        self.resize(1000, 650)

        self._drop_zone = DropZoneWidget()
        self._drop_zone.fmu_loaded.connect(self._on_fmu_loaded)

        # FMU info (read-only)
        self._fmu_title = QLabel()
        self._fmu_title.setProperty("class", "title")

        self._generation_tool_label = QLabel()
        self._generation_tool_label.setProperty("class", "info")

        self._generation_date_label = QLabel()
        self._generation_date_label.setProperty("class", "info")

        self._info_label = QLabel()
        self._info_label.setProperty("class", "info")

        self._step_size_label = QLabel()
        self._step_size_label.setProperty("class", "info")

        # DefaultExperiment (editable)
        self._start_time_edit = QLineEdit()
        self._start_time_edit.setPlaceholderText("startTime")
        self._start_time_edit.setMaximumWidth(120)

        self._stop_time_edit = QLineEdit()
        self._stop_time_edit.setPlaceholderText("stopTime")
        self._stop_time_edit.setMaximumWidth(120)

        # Model & proxy
        self._model = FMUVariableModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # filter across all columns

        # Search field
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Filter variables…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._proxy.setFilterFixedString)

        # Table
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(FMUVariableModel.COL_NAME, Qt.SortOrder.AscendingOrder)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.resizeSection(FMUVariableModel.COL_ICON, 30)
        header.resizeSection(FMUVariableModel.COL_CAUSALITY, 100)
        header.resizeSection(FMUVariableModel.COL_TYPE, 80)
        header.resizeSection(FMUVariableModel.COL_NAME, 350)

        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        # --- Buttons ---
        self._save_button = QPushButton("Save modified FMU as…")
        self._save_button.setProperty("class", "save")
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self._save_fmu_as)

        self._quit_button = QPushButton("Quit")
        self._quit_button.setProperty("class", "quit")
        self._quit_button.clicked.connect(self.close)

        # Equal button widths
        btn_width = max(self._save_button.sizeHint().width(),
                        self._quit_button.sizeHint().width())
        self._save_button.setMinimumWidth(btn_width)
        self._quit_button.setMinimumWidth(btn_width)

        # --- Layout ---
        # Top bar: drop zone | info + experiment
        top_bar = QHBoxLayout()
        top_bar.addWidget(self._drop_zone)

        # Right block: FMU info + experiment fields
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(12)
        info_grid.setVerticalSpacing(4)

        # Row 0: FMU name (spans full width)
        info_grid.addWidget(self._fmu_title, 0, 0, 1, 5)

        # Spacer column between col 1 and col 3
        info_grid.setColumnMinimumWidth(2, 100)

        # Row 1: spacer
        info_grid.setRowMinimumHeight(1, 10)

        # Row 2: generation tool + date
        tool_caption = QLabel("Generator Tool:")
        tool_caption.setProperty("class", "caption")
        info_grid.addWidget(tool_caption, 2, 0)
        info_grid.addWidget(self._generation_tool_label, 2, 1)

        date_caption = QLabel("Generation time:")
        date_caption.setProperty("class", "caption")
        info_grid.addWidget(date_caption, 2, 3)
        info_grid.addWidget(self._generation_date_label, 2, 4)

        # Row 3: startTime / stopTime
        start_caption = QLabel("Start time:")
        start_caption.setProperty("class", "caption")
        info_grid.addWidget(start_caption, 3, 0)
        info_grid.addWidget(self._start_time_edit, 3, 1)

        stop_caption = QLabel("Stop time:")
        stop_caption.setProperty("class", "caption")
        info_grid.addWidget(stop_caption, 3, 3)
        info_grid.addWidget(self._stop_time_edit, 3, 4)

        # Row 4: step size
        step_caption = QLabel("Preferred Step Size:")
        step_caption.setProperty("class", "caption")
        info_grid.addWidget(step_caption, 4, 0)
        info_grid.addWidget(self._step_size_label, 4, 1)

        # Row 5: spacer
        info_grid.setRowMinimumHeight(5, 10)

        # Row 6: variable count
        info_grid.addWidget(self._info_label, 6, 0, 1, 5)

        # Stretch to push content upward
        info_grid.setRowStretch(7, 1)

        top_bar.addLayout(info_grid, 1)

        # Bottom bar: status + buttons
        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)

        button_bar = QHBoxLayout()
        button_bar.addWidget(self._status_bar, 1)
        button_bar.addWidget(self._save_button)
        button_bar.addWidget(self._quit_button)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.addLayout(top_bar)
        main_layout.addWidget(self._search_edit)
        main_layout.addWidget(self._table, 1)
        main_layout.addLayout(button_bar)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # Initial values to detect experiment changes
        self._original_start_time: str = ""
        self._original_stop_time: str = ""

        # Log handler on status bar
        self._log_handler = StatusBarLogHandler(self._status_bar)

        self.show()

    # -- Unsaved changes detection -----------------------------------------------

    def _has_unsaved_changes(self) -> bool:
        """Return True if any variable or experiment field has been modified."""
        if any(var.is_modified for var in self._model.variables):
            return True
        if self._start_time_edit.text().strip() != self._original_start_time:
            return True
        if self._stop_time_edit.text().strip() != self._original_stop_time:
            return True
        return False

    def closeEvent(self, event):
        if self._has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Unsaved changes",
                "Some changes have not been saved.\nDo you really want to quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()

    # -- Slot: FMU loaded ------------------------------------------------------

    def _on_fmu_loaded(self, fmu: Optional[FMU]):
        if fmu is None:
            self._fmu_title.setText("")
            self._generation_tool_label.setText("")
            self._generation_date_label.setText("")
            self._start_time_edit.clear()
            self._stop_time_edit.clear()
            self._step_size_label.setText("")
            self._info_label.setText("")
            self._model.set_variables([])
            self._save_button.setEnabled(False)
            return

        # Collect variables and metadata
        collector = OperationCollectPorts()
        fmu.apply_operation(collector)

        # Display FMU info
        self._fmu_title.setText(os.path.basename(fmu.fmu_filename))
        self._generation_tool_label.setText(collector.generation_tool or "—")
        self._generation_date_label.setText(collector.generation_date or "—")

        # DefaultExperiment
        self._start_time_edit.setText(collector.start_time)
        self._stop_time_edit.setText(collector.stop_time)
        self._original_start_time = collector.start_time
        self._original_stop_time = collector.stop_time

        # Step size (read-only)
        if collector.step_size:
            self._step_size_label.setText(f"{float(collector.step_size):f} s")
        else:
            self._step_size_label.setText("—")

        # Variables
        variables = collector.variables
        self._info_label.setText(f"{len(variables)} variable(s)")
        self._model.set_variables(variables)
        self._table.sortByColumn(FMUVariableModel.COL_NAME, Qt.SortOrder.AscendingOrder)
        self._save_button.setEnabled(True)

    # -- Slot: Save as… --------------------------------------------------------

    def _save_fmu_as(self):
        fmu = self._drop_zone.fmu
        if fmu is None:
            return

        default_dir = os.path.dirname(fmu.fmu_filename)
        filename, ok = QFileDialog.getSaveFileName(
            self, "Save FMU as…", default_dir, "FMU files (*.fmu)",
        )
        if not ok or not filename:
            return

        # Variable modifications
        edits: Dict[str, FMUVariable] = {}
        for var in self._model.variables:
            if var.is_modified:
                edits[var.original_name] = var

        # DefaultExperiment modifications
        new_start = self._start_time_edit.text().strip()
        new_stop = self._stop_time_edit.text().strip()
        start_changed = new_start != self._original_start_time
        stop_changed = new_stop != self._original_stop_time

        has_changes = bool(edits) or start_changed or stop_changed

        if has_changes:
            operation = OperationApplyEdits(
                edits,
                start_time=new_start if start_changed else None,
                stop_time=new_stop if stop_changed else None,
            )
            fmu.apply_operation(operation)
            if edits:
                logger.info(f"{len(edits)} variable(s) modified.")
            if start_changed or stop_changed:
                logger.info(f"DefaultExperiment updated"
                            f" (startTime={new_start}, stopTime={new_stop}).")

        fmu.repack(filename)
        logger.info(f"FMU saved as '{filename}'.")


def main():
    application = Application(sys.argv)
    application.window = MainWindow()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()


