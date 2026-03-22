"""
PySide6 – Éditeur de variables FMU
Drop zone pour charger un FMU + tableau 5 colonnes éditables.
"""

import logging
import os
import sys
from enum import Enum
from typing import List, Optional, Any, Dict

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTableView, QHeaderView,
    QStyledItemDelegate, QComboBox, QPushButton,
    QVBoxLayout, QHBoxLayout, QWidget, QLabel, QFileDialog,
    QLineEdit, QGridLayout,
)

from fmu_manipulation_toolbox.gui.dropfile import DropZoneWidget
from fmu_manipulation_toolbox.gui.gui_style import gui_style
from fmu_manipulation_toolbox.operations import FMU, FMUPort, FMUError, OperationAbstract

logger = logging.getLogger("fmu_manipulation_toolbox")


# ---------------------------------------------------------------------------
#  Données
# ---------------------------------------------------------------------------

class Causality(Enum):
    INPUT = "input"
    OUTPUT = "output"
    PARAMETER = "parameter"
    LOCAL = "local"
    INDEPENDENT = "independent"
    CALCULATED_PARAMETER = "calculatedParameter"
    STRUCTURAL_PARAMETER = "structuralParameter"


AVAILABLE_UNITS = [
    "", "m", "m/s", "m/s²", "kg", "N", "Pa", "K", "°C",
    "rad", "rad/s", "s", "V", "A", "W",
]

COLUMNS = ["", "Causality", "Nom", "Unité", "Description"]
COL_ICON = 0
COL_CAUSALITY = 1
COL_NAME = 2
COL_UNIT = 3
COL_DESCRIPTION = 4


class FMUVariable:
    """Représente une variable d'un FMU."""

    def __init__(self, name: str, causality: Causality,
                 unit: str = "", description: str = ""):
        self.original_name = name
        self.name = name
        self.causality = causality
        self.unit = unit
        self.description = description
        self._original_unit = unit
        self._original_description = description

    @property
    def is_modified(self) -> bool:
        """True si l'utilisateur a modifié au moins un champ."""
        return (self.name != self.original_name
                or self.unit != self._original_unit
                or self.description != self._original_description)


# ---------------------------------------------------------------------------
#  Collecteur de ports + méta-données FMU
# ---------------------------------------------------------------------------

class OperationCollectPorts(OperationAbstract):
    """Collecte les variables, les infos FMU et le DefaultExperiment."""

    def __init__(self):
        self.variables: List[FMUVariable] = []
        # Méta-données FMU
        self.model_name: str = ""
        self.generation_tool: str = ""
        self.generation_date: str = ""
        # DefaultExperiment
        self.start_time: str = ""
        self.stop_time: str = ""

    def __repr__(self):
        return "Collect FMU ports"

    def fmi_attrs(self, attrs):
        self.model_name = attrs.get("modelName", "")
        self.generation_tool = attrs.get("generationTool", "")
        self.generation_date = attrs.get("generationDateAndTime", "")

    def experiment_attrs(self, attrs):
        self.start_time = attrs.get("startTime", "")
        self.stop_time = attrs.get("stopTime", "")

    def port_attrs(self, fmu_port: FMUPort) -> int:
        causality_str = fmu_port.get("causality", "local")
        try:
            causality = Causality(causality_str)
        except ValueError:
            causality = Causality.LOCAL

        var = FMUVariable(
            name=fmu_port["name"],
            causality=causality,
            unit=fmu_port.get("unit", ""),
            description=fmu_port.get("description", ""),
        )
        self.variables.append(var)
        return 0


# ---------------------------------------------------------------------------
#  Opération pour appliquer les modifications au modelDescription.xml
# ---------------------------------------------------------------------------

class OperationApplyEdits(OperationAbstract):
    """Applique les modifications (nom, unité, description, experiment) au FMU."""

    def __init__(self, edits: Dict[str, FMUVariable],
                 start_time: Optional[str] = None,
                 stop_time: Optional[str] = None):
        """
        Args:
            edits: dictionnaire {nom_original: FMUVariable modifiée}
            start_time: nouvelle valeur startTime (None = pas de modif)
            stop_time: nouvelle valeur stopTime (None = pas de modif)
        """
        self.edits = edits
        self.start_time = start_time
        self.stop_time = stop_time

    def __repr__(self):
        return f"Apply {len(self.edits)} edit(s)"

    def experiment_attrs(self, attrs):
        if self.start_time is not None:
            attrs["startTime"] = self.start_time
        if self.stop_time is not None:
            attrs["stopTime"] = self.stop_time

    @staticmethod
    def _set_port_attr(fmu_port: FMUPort, key: str, value: str):
        """Modifie un attribut du port, en le créant s'il n'existe pas."""
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

        if var.unit != var._original_unit:
            if var.unit:
                self._set_port_attr(fmu_port, "unit", var.unit)
            elif "unit" in fmu_port:
                for attrs in fmu_port.attrs_list:
                    attrs.pop("unit", None)

        return 0


# ---------------------------------------------------------------------------
#  Icônes programmatiques
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
#  Modèle
# ---------------------------------------------------------------------------

class FMUVariableModel(QAbstractTableModel):
    def __init__(self, variables: Optional[List[FMUVariable]] = None, parent=None):
        super().__init__(parent)
        self._variables: List[FMUVariable] = variables or []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._variables)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        var = self._variables[index.row()]
        col = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == COL_CAUSALITY:
                return var.causality.value
            if col == COL_NAME:
                return var.name
            if col == COL_UNIT:
                return var.unit
            if col == COL_DESCRIPTION:
                return var.description

        if role == Qt.ItemDataRole.DecorationRole and col == COL_ICON:
            return causality_icon(var.causality)

        if role == Qt.ItemDataRole.TextAlignmentRole and col == COL_ICON:
            return Qt.AlignmentFlag.AlignCenter

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.column() in (COL_NAME, COL_UNIT, COL_DESCRIPTION):
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value: Any,
                role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        var = self._variables[index.row()]
        col = index.column()
        if col == COL_NAME:
            var.name = value
        elif col == COL_UNIT:
            var.unit = value
        elif col == COL_DESCRIPTION:
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
        """Accès direct à la liste des variables."""
        return self._variables


# ---------------------------------------------------------------------------
#  Délégué pour la colonne « Unité » (QComboBox)
# ---------------------------------------------------------------------------

class UnitComboDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.addItems(AVAILABLE_UNITS)
        return combo

    def setEditorData(self, editor: QComboBox, index: QModelIndex):
        current = index.data(Qt.ItemDataRole.EditRole)
        idx = editor.findText(current)
        if idx >= 0:
            editor.setCurrentIndex(idx)
        else:
            editor.setCurrentText(current)

    def setModelData(self, editor: QComboBox, model, index: QModelIndex):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)



# ---------------------------------------------------------------------------
#  Fenêtre principale
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FMU Variable Editor")
        self.resize(1000, 650)

        # --- Widgets ---
        self._drop_zone = DropZoneWidget()
        self._drop_zone.fmu_loaded.connect(self._on_fmu_loaded)

        # Infos FMU (lecture seule)
        self._fmu_title = QLabel()
        self._fmu_title.setProperty("class", "title")

        self._generation_tool_label = QLabel()
        self._generation_tool_label.setProperty("class", "info")

        self._generation_date_label = QLabel()
        self._generation_date_label.setProperty("class", "info")

        self._info_label = QLabel()
        self._info_label.setProperty("class", "info")

        # DefaultExperiment (éditable)
        self._start_time_edit = QLineEdit()
        self._start_time_edit.setPlaceholderText("startTime")
        self._start_time_edit.setMaximumWidth(120)

        self._stop_time_edit = QLineEdit()
        self._stop_time_edit.setPlaceholderText("stopTime")
        self._stop_time_edit.setMaximumWidth(120)

        # Modèle & proxy
        self._model = FMUVariableModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        # Table
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self._table.setItemDelegateForColumn(COL_UNIT, UnitComboDelegate(self._table))

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(COL_ICON, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_CAUSALITY, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_UNIT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_DESCRIPTION, QHeaderView.ResizeMode.Stretch)

        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setDefaultSectionSize(28)

        # --- Boutons ---
        self._save_button = QPushButton("Sauvegarder sous…")
        self._save_button.setProperty("class", "save")
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self._save_fmu_as)

        self._quit_button = QPushButton("Quitter")
        self._quit_button.setProperty("class", "quit")
        self._quit_button.clicked.connect(self.close)

        # --- Layout ---
        # Bandeau supérieur : drop zone | infos + experiment
        top_bar = QHBoxLayout()
        top_bar.addWidget(self._drop_zone)

        # Bloc droit : infos FMU + champs experiment
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(12)
        info_grid.setVerticalSpacing(4)

        # Ligne 0 : nom du FMU (occupe toute la largeur)
        info_grid.addWidget(self._fmu_title, 0, 0, 1, 4)

        # Ligne 1 : outil de génération + date
        tool_caption = QLabel("Outil :")
        tool_caption.setProperty("class", "caption")
        info_grid.addWidget(tool_caption, 1, 0)
        info_grid.addWidget(self._generation_tool_label, 1, 1)

        date_caption = QLabel("Date :")
        date_caption.setProperty("class", "caption")
        info_grid.addWidget(date_caption, 1, 2)
        info_grid.addWidget(self._generation_date_label, 1, 3)

        # Ligne 2 : startTime / stopTime
        start_caption = QLabel("Start time :")
        start_caption.setProperty("class", "caption")
        info_grid.addWidget(start_caption, 2, 0)
        info_grid.addWidget(self._start_time_edit, 2, 1)

        stop_caption = QLabel("Stop time :")
        stop_caption.setProperty("class", "caption")
        info_grid.addWidget(stop_caption, 2, 2)
        info_grid.addWidget(self._stop_time_edit, 2, 3)

        # Ligne 3 : nb variables
        info_grid.addWidget(self._info_label, 3, 0, 1, 4)

        # Stretch pour pousser vers le haut
        info_grid.setRowStretch(4, 1)

        top_bar.addLayout(info_grid, 1)

        # Barre de boutons en bas
        button_bar = QHBoxLayout()
        button_bar.addStretch()
        button_bar.addWidget(self._save_button)
        button_bar.addWidget(self._quit_button)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.addLayout(top_bar)
        main_layout.addWidget(self._table, 1)
        main_layout.addLayout(button_bar)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # Valeurs initiales pour détecter les changements experiment
        self._original_start_time: str = ""
        self._original_stop_time: str = ""

    # -- Slot : FMU chargé -----------------------------------------------------

    def _on_fmu_loaded(self, fmu: Optional[FMU]):
        if fmu is None:
            self._fmu_title.setText("")
            self._generation_tool_label.setText("")
            self._generation_date_label.setText("")
            self._start_time_edit.clear()
            self._stop_time_edit.clear()
            self._info_label.setText("")
            self._model.set_variables([])
            self._save_button.setEnabled(False)
            return

        # Collecte des variables et méta-données
        collector = OperationCollectPorts()
        fmu.apply_operation(collector)

        # Affichage des infos FMU
        self._fmu_title.setText(os.path.basename(fmu.fmu_filename))
        self._generation_tool_label.setText(collector.generation_tool or "—")
        self._generation_date_label.setText(collector.generation_date or "—")

        # DefaultExperiment
        self._start_time_edit.setText(collector.start_time)
        self._stop_time_edit.setText(collector.stop_time)
        self._original_start_time = collector.start_time
        self._original_stop_time = collector.stop_time

        # Variables
        variables = collector.variables
        self._info_label.setText(f"{len(variables)} variable(s)")
        self._model.set_variables(variables)
        self._table.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self._save_button.setEnabled(True)

    # -- Slot : Sauvegarder sous… ----------------------------------------------

    def _save_fmu_as(self):
        fmu = self._drop_zone.fmu
        if fmu is None:
            return

        default_dir = os.path.dirname(fmu.fmu_filename)
        filename, ok = QFileDialog.getSaveFileName(
            self, "Sauvegarder le FMU sous…", default_dir, "FMU files (*.fmu)",
        )
        if not ok or not filename:
            return

        # Modifications des variables
        edits: Dict[str, FMUVariable] = {}
        for var in self._model.variables:
            if var.is_modified:
                edits[var.original_name] = var

        # Modifications du DefaultExperiment
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
                logger.info(f"{len(edits)} variable(s) modifiée(s).")
            if start_changed or stop_changed:
                logger.info(f"DefaultExperiment mis à jour"
                            f" (startTime={new_start}, stopTime={new_stop}).")

        fmu.repack(filename)
        logger.info(f"FMU sauvegardé sous '{filename}'.")


# ---------------------------------------------------------------------------
#  Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from PySide6.QtCore import QDir
    from PySide6.QtGui import QIcon

    app = QApplication(sys.argv)
    QDir.addSearchPath('images', os.path.join(os.path.dirname(__file__), "../resources"))
    app.setStyleSheet(gui_style)

    if os.name == 'nt':
        app.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), '../resources', 'icon-round.png')))
    else:
        app.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), '../resources', 'icon.png')))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

