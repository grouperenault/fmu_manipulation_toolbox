"""
Configuration detail panel for FMU container builder.

Lists the reset ports of the (GUI-only) ConfigurationNode, and lets the user expose them as container inputs.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget, QTableView, QLabel, QHeaderView, QVBoxLayout,
    QAbstractItemView,
)


class ConfigurationDetailWidget(QWidget):
    """Reset ports of the ConfigurationNode: one row per active port, with an "exposed" checkbox.

    An exposed port becomes the container input `container.<id>.reset` of the container of the FMU (see
    `ConfigurationNode.reset_exposed`). The ports are exposed anyway by the `auto_input` parameter of the container.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._node = None

        self._name_label = QLabel("configuration")
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)

        self._model = QStandardItemModel(0, 2)
        self._model.setHorizontalHeaderLabels(["Reset port", "Exposed"])
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        self._model.itemChanged.connect(self._on_item_changed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addWidget(self._table, 1)

    def set_node(self, node):
        """Show the reset ports of *node* (ConfigurationNode)."""
        self._node = None   # no write back while loading
        self._model.removeRows(0, self._model.rowCount())
        for port, active in node.reset_ports.items():
            if not active:
                continue
            port_item = QStandardItem(port)
            port_item.setEditable(False)
            port_item.setToolTip(f"Exposed as '{node.reset_input_name(node.fmu_name_from_reset_port(port))}'")
            exposed_item = QStandardItem("")
            exposed_item.setCheckable(True)
            exposed_item.setEditable(False)
            exposed_item.setCheckState(Qt.CheckState.Checked if node.reset_exposed.get(port, False)
                                       else Qt.CheckState.Unchecked)
            self._model.appendRow([port_item, exposed_item])
        self._node = node

    def _on_item_changed(self, item: QStandardItem):
        if self._node is None or item.column() != 1:
            return
        port = self._model.item(item.row(), 0).text()
        self._node.reset_exposed[port] = item.checkState() == Qt.CheckState.Checked
        self.changed.emit()
