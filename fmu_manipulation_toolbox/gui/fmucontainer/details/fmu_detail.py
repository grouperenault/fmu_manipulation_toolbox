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
    when the user has not entered a value. Also displays parameter ports in italics
    and invalid (orphan) ports in red."""

    ROLE_PLACEHOLDER = Qt.ItemDataRole.UserRole + 100
    ROLE_CAUSALITY = Qt.ItemDataRole.UserRole + 101
    ROLE_INVALID = Qt.ItemDataRole.UserRole + 102
    ROLE_AGGREGATE = Qt.ItemDataRole.UserRole + 103

    def displayText(self, value, locale):
        if value:
            return str(value)
        return ""

    def paint(self, painter, option, index):
        causality = index.data(self.ROLE_CAUSALITY)
        aggregate = index.data(self.ROLE_AGGREGATE)
        if causality == "parameter" or aggregate:
            font = option.font
            if causality == "parameter":
                font.setItalic(True)
            if aggregate:
                font.setBold(True)
            option.font = font

        invalid = index.data(self.ROLE_INVALID)
        if invalid:
            option.palette.setColor(option.palette.ColorRole.Text, QColor("#F54927"))

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
    """NodeItem (FMU) details with tabs for start values, input and output port exposure."""

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

        # ── Tab 2: Input Ports ────────────────────────────────────
        self._in_model = QStandardItemModel(0, 2)
        self._in_model.setHorizontalHeaderLabels(["Input Port", "Exposed"])
        self._in_model.dataChanged.connect(lambda *_: self.changed.emit())

        self._in_proxy = _CheckableSortProxy(self)
        self._in_proxy.setSourceModel(self._in_model)

        self._in_table = QTableView()
        self._in_table.setModel(self._in_proxy)
        self._in_table.setSortingEnabled(True)
        self._in_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._in_table.horizontalHeader().setStretchLastSection(True)
        self._in_table.setAlternatingRowColors(True)
        self._in_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._in_table.verticalHeader().setVisible(False)

        self._in_delegate = _StartValueDelegate(self._in_table)
        self._in_table.setItemDelegateForColumn(0, self._in_delegate)

        self._tabs.addTab(self._in_table, "Input Ports")

        # ── Tab 3: Output Ports ───────────────────────────────────
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
        self._in_table.installEventFilter(self)
        self._out_table.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == event.Type.Resize:
            if obj is self._sv_table or obj is self._in_table or obj is self._out_table:
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

        self._current_node.user_exposed_inputs.clear()
        for row in range(self._in_model.rowCount()):
            port_name = self._in_model.item(row, 0).text()
            check_item = self._in_model.item(row, 1)
            exposed = check_item.checkState() == Qt.CheckState.Checked
            self._current_node.user_exposed_inputs[port_name] = exposed

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
        shown_ports = set()
        for port_name in node.fmu_input_names:
            # Skip clock and binary ports – they don't have meaningful start values
            port_type = node.fmu_port_type.get(port_name, "").lower()
            if port_type in ("clock", "binary"):
                continue
            # Skip virtual FMI-2 array aggregates – start values are set on
            # their individual scalar elements, not on the aggregate itself.
            if port_name in node.fmu_array_aggregate_elements:
                continue

            shown_ports.add(port_name)
            name_item = QStandardItem(port_name)
            name_item.setEditable(False)
            causality = node.fmu_port_causality.get(port_name, "input")
            name_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)
            is_aggregate = port_name in node.fmu_array_aggregate_elements
            if is_aggregate:
                name_item.setData(True, _StartValueDelegate.ROLE_AGGREGATE)

            user_val = node.user_start_values.get(port_name, "")
            value_item = QStandardItem(user_val)
            default = node.fmu_start_values.get(port_name)
            if default is not None:
                value_item.setData(str(default), _StartValueDelegate.ROLE_PLACEHOLDER)
                value_item.setToolTip(f"FMU default: {default}")
            value_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)
            if is_aggregate:
                value_item.setData(True, _StartValueDelegate.ROLE_AGGREGATE)

            self._sv_model.appendRow([name_item, value_item])

        # Orphan start values: ports with user values that no longer exist in the FMU
        for port_name, value in node.user_start_values.items():
            if port_name not in shown_ports:
                name_item = QStandardItem(port_name)
                name_item.setEditable(False)
                name_item.setData(True, _StartValueDelegate.ROLE_INVALID)
                name_item.setToolTip("Port no longer exists in this FMU")

                value_item = QStandardItem(value)
                value_item.setData(True, _StartValueDelegate.ROLE_INVALID)

                self._sv_model.appendRow([name_item, value_item])

        # ── Populate Input Ports tab ───────────────────────────────
        self._in_model.removeRows(0, self._in_model.rowCount())
        shown_inputs = set()
        for port_name in node.fmu_input_names:
            shown_inputs.add(port_name)
            name_item = QStandardItem(port_name)
            name_item.setEditable(False)
            causality = node.fmu_port_causality.get(port_name, "input")
            name_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)
            is_aggregate = port_name in node.fmu_array_aggregate_elements
            if is_aggregate:
                name_item.setData(True, _StartValueDelegate.ROLE_AGGREGATE)

            check_item = QStandardItem("")
            check_item.setEditable(False)
            check_item.setCheckable(True)
            exposed = node.user_exposed_inputs.get(port_name, False)
            check_item.setCheckState(Qt.CheckState.Checked if exposed else Qt.CheckState.Unchecked)
            check_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)
            if is_aggregate:
                check_item.setData(True, _StartValueDelegate.ROLE_AGGREGATE)

            self._in_model.appendRow([name_item, check_item])

        # Orphan exposed inputs: ports that no longer exist in the FMU
        for port_name, exposed in node.user_exposed_inputs.items():
            if exposed and port_name not in shown_inputs:
                name_item = QStandardItem(port_name)
                name_item.setEditable(False)
                name_item.setData(True, _StartValueDelegate.ROLE_INVALID)
                name_item.setToolTip("Port no longer exists in this FMU")

                check_item = QStandardItem("")
                check_item.setEditable(False)
                check_item.setCheckable(True)
                check_item.setCheckState(Qt.CheckState.Checked)
                check_item.setData(True, _StartValueDelegate.ROLE_INVALID)

                self._in_model.appendRow([name_item, check_item])

        # ── Populate Output Ports tab ─────────────────────────────
        self._out_model.removeRows(0, self._out_model.rowCount())
        shown_outputs = set()
        for port_name in node.fmu_output_names:
            shown_outputs.add(port_name)
            name_item = QStandardItem(port_name)
            name_item.setEditable(False)
            causality = node.fmu_port_causality.get(port_name, "output")
            name_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)
            is_aggregate = port_name in node.fmu_array_aggregate_elements
            if is_aggregate:
                name_item.setData(True, _StartValueDelegate.ROLE_AGGREGATE)

            check_item = QStandardItem("")
            check_item.setEditable(False)
            check_item.setCheckable(True)
            exposed = node.user_exposed_outputs.get(port_name, False)
            check_item.setCheckState(Qt.CheckState.Checked if exposed else Qt.CheckState.Unchecked)
            check_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)
            if is_aggregate:
                check_item.setData(True, _StartValueDelegate.ROLE_AGGREGATE)

            self._out_model.appendRow([name_item, check_item])

        # Orphan exposed outputs: ports that no longer exist in the FMU
        for port_name, exposed in node.user_exposed_outputs.items():
            if exposed and port_name not in shown_outputs:
                name_item = QStandardItem(port_name)
                name_item.setEditable(False)
                name_item.setData(True, _StartValueDelegate.ROLE_INVALID)
                name_item.setToolTip("Port no longer exists in this FMU")

                check_item = QStandardItem("")
                check_item.setEditable(False)
                check_item.setCheckable(True)
                check_item.setCheckState(Qt.CheckState.Checked)
                check_item.setData(True, _StartValueDelegate.ROLE_INVALID)

                self._out_model.appendRow([name_item, check_item])

