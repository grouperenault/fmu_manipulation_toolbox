"""
FMU detail panel for FMU container builder.

Contains classes for displaying and editing FMU node details (start values, output ports).
"""

from typing import *

from PySide6.QtCore import Qt, Signal, QSortFilterProxyModel
from PySide6.QtGui import QStandardItemModel, QStandardItem, QColor
from PySide6.QtWidgets import (
    QWidget, QTableView, QLabel, QHeaderView, QVBoxLayout,
    QStyledItemDelegate, QAbstractItemView, QTabWidget,
)

from fmu_manipulation_toolbox.gui.fmucontainer.graph import NodeItem
from fmu_manipulation_toolbox.gui.helper import unlock_column_resize
from fmu_manipulation_toolbox.gui.style import placeholder_color


class _StartValueDelegate(QStyledItemDelegate):
    """Delegate that shows the FMU default start value as a gray placeholder
    when the user has not entered a value. Also displays parameter ports in italics."""

    ROLE_PLACEHOLDER = Qt.ItemDataRole.UserRole + 100
    ROLE_CAUSALITY = Qt.ItemDataRole.UserRole + 101

    def displayText(self, value, locale):
        if value:
            return str(value)
        return ""

    def paint(self, painter, option, index):
        causality = index.data(self.ROLE_CAUSALITY)
        if causality == "parameter":
            font = option.font
            font.setItalic(True)
            option.font = font

        super().paint(painter, option, index)
        value = index.data(Qt.ItemDataRole.DisplayRole)
        if not value:
            placeholder = index.data(self.ROLE_PLACEHOLDER)
            if placeholder:
                painter.save()
                painter.setPen(QColor(placeholder_color))
                rect = option.rect.adjusted(4, 0, -4, 0)
                painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 str(placeholder))
                painter.restore()


class _CheckableSortProxy(QSortFilterProxyModel):
    """Proxy that sorts checkable columns by check-state instead of display text."""

    def lessThan(self, left, right):
        left_data = self.sourceModel().itemFromIndex(left)
        right_data = self.sourceModel().itemFromIndex(right)
        if left_data and left_data.isCheckable():
            return int(left_data.checkState()) < int(right_data.checkState())
        return super().lessThan(left, right)


class FMUDetailWidget(QWidget):
    """NodeItem (FMU) details with tabs for start values and output port exposure."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_node: Optional[NodeItem] = None

        self._name_label = QLabel()
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)
        self._name_label.setWordWrap(True)

        # ── Tab widget ────────────────────────────────────────────
        self._tabs = QTabWidget()

        # ── Tab 1: Start Values ───────────────────────────────────
        self._sv_model = QStandardItemModel(0, 2)
        self._sv_model.setHorizontalHeaderLabels(["Input Port", "Start Value"])
        self._sv_model.dataChanged.connect(lambda *_: self.changed.emit())

        self._sv_proxy = QSortFilterProxyModel(self)
        self._sv_proxy.setSourceModel(self._sv_model)

        self._sv_table = QTableView()
        self._sv_table.setModel(self._sv_proxy)
        self._sv_table.setSortingEnabled(True)
        self._sv_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._sv_table.horizontalHeader().setStretchLastSection(True)
        self._sv_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._sv_table.verticalHeader().setVisible(False)

        self._sv_delegate = _StartValueDelegate(self._sv_table)
        self._sv_table.setItemDelegateForColumn(0, self._sv_delegate)
        self._sv_table.setItemDelegateForColumn(1, self._sv_delegate)

        self._tabs.addTab(self._sv_table, "Start Values")

        # ── Tab 2: Output Ports ───────────────────────────────────
        self._out_model = QStandardItemModel(0, 2)
        self._out_model.setHorizontalHeaderLabels(["Output Port", "Exposed"])
        self._out_model.dataChanged.connect(lambda *_: self.changed.emit())

        self._out_proxy = _CheckableSortProxy(self)
        self._out_proxy.setSourceModel(self._out_model)

        self._out_table = QTableView()
        self._out_table.setModel(self._out_proxy)
        self._out_table.setSortingEnabled(True)
        self._out_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._out_table.horizontalHeader().setStretchLastSection(True)
        self._out_table.setAlternatingRowColors(True)
        self._out_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._out_table.verticalHeader().setVisible(False)

        self._out_delegate = _StartValueDelegate(self._out_table)
        self._out_table.setItemDelegateForColumn(0, self._out_delegate)

        self._tabs.addTab(self._out_table, "Output Ports")

        # ── Layout ────────────────────────────────────────────────
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addWidget(self._tabs, 1)

        self._sv_table.installEventFilter(self)
        self._out_table.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == event.Type.Resize:
            if obj is self._sv_table or obj is self._out_table:
                unlock_column_resize(obj)
        return super().eventFilter(obj, event)

    # -- Sync helpers ----------------------------------------------------------

    def sync_to_node(self):
        """Write the table content back into the current NodeItem."""
        if self._current_node is None:
            return
        self._current_node.user_start_values.clear()
        for row in range(self._sv_model.rowCount()):
            port_name = self._sv_model.item(row, 0).text()
            value_item = self._sv_model.item(row, 1)
            value = value_item.text().strip() if value_item else ""
            if value:
                self._current_node.user_start_values[port_name] = value

        self._current_node.user_exposed_outputs.clear()
        for row in range(self._out_model.rowCount()):
            port_name = self._out_model.item(row, 0).text()
            check_item = self._out_model.item(row, 1)
            exposed = check_item.checkState() == Qt.CheckState.Checked
            self._current_node.user_exposed_outputs[port_name] = exposed

    def set_node(self, node):
        """Persist edits on the previous node, then populate with *node*."""
        self.sync_to_node()

        self._current_node = node
        fmu_step_size = f"{node.fmu_step_size}s" if node.fmu_step_size else "unknown"
        self._name_label.setText(
            f"{node.title} (generated by {node.fmu_generator}, step size = {fmu_step_size})"
        )

        # ── Populate Start Values tab ─────────────────────────────
        self._sv_model.removeRows(0, self._sv_model.rowCount())
        for port_name in node.fmu_input_names:
            name_item = QStandardItem(port_name)
            name_item.setEditable(False)
            causality = node.fmu_port_causality.get(port_name, "input")
            name_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)

            user_val = node.user_start_values.get(port_name, "")
            value_item = QStandardItem(user_val)
            default = node.fmu_start_values.get(port_name)
            if default is not None:
                value_item.setData(str(default), _StartValueDelegate.ROLE_PLACEHOLDER)
                value_item.setToolTip(f"FMU default: {default}")
            value_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)

            self._sv_model.appendRow([name_item, value_item])

        # ── Populate Output Ports tab ─────────────────────────────
        self._out_model.removeRows(0, self._out_model.rowCount())
        for port_name in node.fmu_output_names:
            name_item = QStandardItem(port_name)
            name_item.setEditable(False)
            causality = node.fmu_port_causality.get(port_name, "output")
            name_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)

            check_item = QStandardItem("")
            check_item.setEditable(False)
            check_item.setCheckable(True)
            exposed = node.user_exposed_outputs.get(port_name, False)
            check_item.setCheckState(Qt.CheckState.Checked if exposed else Qt.CheckState.Unchecked)
            check_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)

            self._out_model.appendRow([name_item, check_item])

