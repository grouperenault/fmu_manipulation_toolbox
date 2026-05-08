"""
Container detail panel for FMU container builder.

Contains classes for displaying and editing container parameters.
"""

from typing import *

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget, QTableView, QLabel, QHeaderView, QVBoxLayout,
    QAbstractItemView,
)

from fmu_manipulation_toolbox.help import Help


class ContainerParameters:
    def __init__(self, name: str, step_size="", mt=False, profiling=False, sequential=False, auto_link=True,
                 auto_input=True, auto_output=True, auto_parameter=False, auto_local=False, ts_multiplier=False,
                 **_):
        self.name = name
        self.parameters = {
            "step_size": step_size,
            "mt": mt,
            "profiling": profiling,
            "sequential": sequential,
            "auto_link": auto_link,
            "auto_input": auto_input,
            "auto_output": auto_output,
            "auto_parameter": auto_parameter,
            "auto_local": auto_local,
            "ts_multiplier": ts_multiplier,
        }

    def __repr__(self):
        return " ".join([f"{k} = {v}\n" for k, v in self.parameters.items()])


class ContainerDetailWidget(QWidget):
    """Container details: name label and editable parameter table."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._container_parameters: Optional[ContainerParameters] = None

        self._name_label = QLabel()
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)
        self._name_label.setWordWrap(True)

        self._model = QStandardItemModel(0, 2)
        self._model.setHorizontalHeaderLabels(["Parameters", ""])
        self._table = QTableView()
        self._table.setModel(self._model)

        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setVisible(False)
        self._table.verticalHeader().setVisible(False)

        self._model.dataChanged.connect(self._on_table_data_changed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addWidget(self._table, 1)

    def set_container(self, container_parameters: ContainerParameters):
        self._name_label.setText(f"{container_parameters.name}")

        self._model.removeRows(0, self._model.rowCount())
        help_instance = Help()
        for k, v in container_parameters.parameters.items():
            if isinstance(v, bool):
                value_item = QStandardItem("")
                value_item.setCheckable(True)
                value_item.setCheckState(Qt.CheckState.Checked if v else Qt.CheckState.Unchecked)
                value_item.setEditable(False)
            else:
                value_item = QStandardItem(str(v))
                value_item.setEditable(True)
            key_item = QStandardItem(k)
            key_item.setEditable(False)
            tooltip = help_instance.usage(f'-{k}')
            if tooltip:
                key_item.setToolTip(tooltip)
                value_item.setToolTip(tooltip)
            self._model.appendRow([key_item, value_item])

        self._container_parameters = container_parameters

    def _on_table_data_changed(self):
        if self._container_parameters is None:
            return
        for r in range(self._model.rowCount()):
            key = self._model.item(r, 0).text()
            value_item = self._model.item(r, 1)
            if value_item.isCheckable():
                value = value_item.checkState() == Qt.CheckState.Checked
            else:
                value = value_item.text()
            self._container_parameters.parameters[key] = value
        self.changed.emit()

