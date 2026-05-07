"""
Wire detail panel for FMU container builder.

Contains classes for displaying and editing wire connection mappings.
"""

from typing import *

from PySide6.QtCore import Qt, Signal, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget, QTableView, QLabel, QHeaderView, QVBoxLayout, QHBoxLayout,
    QStyledItemDelegate, QAbstractItemView, QPushButton, QDialog, QLineEdit,
    QFrame, QListWidget, QListWidgetItem, QTabWidget, QFileDialog,
)

from fmu_manipulation_toolbox.gui.fmucontainer.graph import NodeItem, WireItem
from fmu_manipulation_toolbox.gui.helper import unlock_column_resize


class _PortListSelectorDialog(QDialog):
    """Independent dialog window for selecting a port from a searchable list.

    Features:
    • Search bar for filtering items
    • Scrollable list view (independent of parent widget)
    • Display parameter ports in italics
    • Can be displayed anywhere on screen
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Port")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setGeometry(100, 100, 400, 400)

        self._items: List[str] = []
        self._causalities: Dict[str, str] = {}
        self._selected_text = ""

        # -- Search bar --
        self._search_input = QLineEdit()
        self._search_input.setObjectName("PortListSearchBar")
        self._search_input.setPlaceholderText("Search ports...")
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_input.setMaximumHeight(24)

        # -- Separator --
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setMaximumHeight(1)
        separator.setStyleSheet("QFrame { color: #3a3a44; }")

        # -- List widget --
        self._list_widget = QListWidget()
        self._list_widget.setObjectName("PortListView")
        self._list_widget.setAlternatingRowColors(False)
        self._list_widget.itemSelectionChanged.connect(self._on_item_selected)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)

        # -- Buttons --
        self._ok_btn = QPushButton("OK")
        self._cancel_btn = QPushButton("Cancel")
        self._ok_btn.clicked.connect(self.accept)
        self._cancel_btn.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addWidget(self._ok_btn)
        btn_width = max(self._ok_btn.sizeHint().width(), self._cancel_btn.sizeHint().width(), 150)
        self._ok_btn.setMinimumWidth(btn_width)
        self._cancel_btn.setMinimumWidth(btn_width)

        # -- Main layout --
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        lay.addWidget(self._search_input)
        lay.addWidget(separator)
        lay.addWidget(self._list_widget, 1)
        lay.addLayout(btn_layout)

    def set_items(self, items: List[str]):
        """Set the list of available items."""
        self._items = list(items)
        self._update_list_widget()

    def set_causalities(self, causalities: Dict[str, str]):
        """Set causality info for displaying parameter ports in italics."""
        self._causalities = causalities
        self._update_list_widget()

    def set_selected(self, text: str):
        """Set the currently selected item."""
        self._selected_text = text
        if text:
            self._search_input.setText(text)
            for i in range(self._list_widget.count()):
                item = self._list_widget.item(i)
                if item.text() == text:
                    self._list_widget.setCurrentItem(item)
                    break

    def get_selected(self) -> str:
        """Get the currently selected item text."""
        current = self._list_widget.currentItem()
        if current:
            return current.text()
        return self._selected_text

    def _on_search_text_changed(self, text: str):
        """Filter the list based on search text."""
        self._update_list_widget(text)

    def _on_item_selected(self):
        """When user selects an item in the list."""
        current = self._list_widget.currentItem()
        if current:
            self._selected_text = current.text()

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """When user double-clicks an item, accept and close."""
        self._selected_text = item.text()
        self.accept()

    def _update_list_widget(self, search_text: str = ""):
        """Repopulate the list widget with filtered items."""
        self._list_widget.clear()

        search_lower = search_text.lower()
        for port_name in self._items:
            if search_lower and search_lower not in port_name.lower():
                continue

            item = QListWidgetItem(port_name)

            # Apply italic formatting for parameter ports
            if port_name in self._causalities and self._causalities[port_name] == "parameter":
                font = item.font()
                font.setItalic(True)
                item.setFont(font)

            self._list_widget.addItem(item)

        # Select first item if available
        if self._list_widget.count() > 0:
            self._list_widget.setCurrentRow(0)


class _PortComboDelegate(QStyledItemDelegate):
    """Delegate that presents a searchable port list instead of a simple combo box.

    Opens an independent dialog with _PortListSelectorDialog to provide:
    • Search bar for filtering ports
    • Scrollable list
    • Parameter ports displayed in italics
    """

    ROLE_PORT_CAUSALITIES = Qt.ItemDataRole.UserRole + 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[str] = []
        self._causalities: Dict[str, str] = {}

    def set_items(self, items: List[str]):
        self._items = list(items)

    def set_causalities(self, causalities: Dict[str, str]):
        """Set the causality info for ports."""
        self._causalities = causalities

    def createEditor(self, parent, option, index):
        """Create a non-visible dummy editor; the actual dialog will be shown separately."""
        dummy_editor = QWidget(parent)
        dummy_editor.setVisible(False)
        dummy_editor.setMaximumSize(0, 0)

        current_value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        self._show_port_selector_dialog(current_value, parent, option, index, dummy_editor)

        return dummy_editor

    def _show_port_selector_dialog(self, current_value, parent, option, index, editor):
        """Show the port selector dialog and handle selection."""
        dialog = _PortListSelectorDialog(parent)
        dialog.set_items(self._items)
        dialog.set_causalities(self._causalities)
        dialog.set_selected(current_value)

        table = self.parent()
        if table and hasattr(table, 'mapToGlobal'):
            cell_pos = table.mapToGlobal(option.rect.bottomLeft())
            dialog.move(cell_pos)

        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            selected_value = dialog.get_selected()
            editor.setProperty("selected_value", selected_value)
            if table and hasattr(table, 'model'):
                model = table.model()
                self.setModelData(editor, model, index)

        self.closeEditor.emit(editor)

    def setEditorData(self, editor, index):
        """Initialize editor with current value (minimal for dummy editor)."""
        value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        editor.setProperty("current_value", value)

    def setModelData(self, editor, model, index):
        """Commit selected value to model."""
        selected_value = editor.property("selected_value")
        if selected_value:
            model.setData(index, selected_value, Qt.ItemDataRole.EditRole)
        else:
            current = index.data(Qt.ItemDataRole.DisplayRole) or ""
            model.setData(index, current, Qt.ItemDataRole.EditRole)

        table = self.parent()
        if table:
            table.update()

    def updateEditorGeometry(self, editor, option, index):
        """Hide the dummy editor since we use a dialog instead."""
        editor.hide()
        editor.setGeometry(0, 0, 0, 0)

    def paint(self, painter, option, index):
        """Display parameter ports in italics."""
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text and text in self._causalities and self._causalities[text] == "parameter":
            font = option.font
            font.setItalic(True)
            option.font = font

        super().paint(painter, option, index)


class _WireDirectionTab(QWidget):
    """One direction of a wire: 2-column table (Output Port → Input Port).

    *from_node* is the source node, *to_node* the destination.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._from_node: Optional[NodeItem] = None
        self._to_node: Optional[NodeItem] = None

        # -- Table model (2 columns) --
        self._model = QStandardItemModel(0, 2)
        self._model.setHorizontalHeaderLabels(["Output Port", "Input Port"])

        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setDynamicSortFilter(False)
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setSortingEnabled(True)
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        # -- Delegates --
        self._output_delegate = _PortComboDelegate(self._table)
        self._input_delegate = _PortComboDelegate(self._table)
        self._table.setItemDelegateForColumn(0, self._output_delegate)
        self._table.setItemDelegateForColumn(1, self._input_delegate)

        self._model.dataChanged.connect(lambda *_: self.changed.emit())

        # -- Buttons --
        self._add_btn = QPushButton("Add link")
        self._remove_btn = QPushButton("Remove link")
        self._add_btn.setProperty("class", "info")
        self._remove_btn.setProperty("class", "removal")
        self._add_btn.clicked.connect(self._on_add)
        self._remove_btn.clicked.connect(self._on_remove)
        btn_width = max(self._add_btn.sizeHint().width(),
                        self._remove_btn.sizeHint().width(),
                        150)
        self._add_btn.setMinimumWidth(btn_width)
        self._remove_btn.setMinimumWidth(btn_width)

        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.addWidget(self._add_btn)
        btn_lay.addWidget(self._remove_btn)
        btn_lay.addStretch()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._table, 1)
        lay.addLayout(btn_lay)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        unlock_column_resize(self._table)

    # ── Configuration ───────────────────────────────────────────

    def set_nodes(self, from_node, to_node):
        self._from_node = from_node
        self._to_node = to_node
        self._output_delegate.set_items(from_node.fmu_output_names)
        self._output_delegate.set_causalities(from_node.fmu_port_causality)
        self._input_delegate.set_items(to_node.fmu_input_names)
        self._input_delegate.set_causalities(to_node.fmu_port_causality)

    # ── Data access ─────────────────────────────────────────────

    def _close_editor(self):
        """Close any active cell editor to avoid commitData warnings."""
        self._table.setCurrentIndex(QModelIndex())

    def mappings(self) -> List[tuple]:
        """Return list of 4-tuples (from_fmu, output, to_fmu, input)."""
        if not self._from_node or not self._to_node:
            return []
        result = []
        from_name = self._from_node.fmu_path.name
        to_name = self._to_node.fmu_path.name
        for r in range(self._model.rowCount()):
            out_item = self._model.item(r, 0)
            in_item = self._model.item(r, 1)
            if out_item and in_item and out_item.text() and in_item.text():
                result.append((from_name, out_item.text(), to_name, in_item.text()))
        return result

    def load_mappings(self, mappings: List[tuple]):
        """Populate the table from 4-tuples (only keep rows matching this direction)."""
        self._close_editor()
        self._model.removeRows(0, self._model.rowCount())
        if not self._from_node or not self._to_node:
            return
        from_name = self._from_node.fmu_path.name
        to_name = self._to_node.fmu_path.name
        for m in mappings:
            if len(m) >= 4 and m[0] == from_name and m[2] == to_name:
                out_item = QStandardItem(m[1])
                in_item = QStandardItem(m[3])
                out_causality = self._from_node.fmu_port_causality.get(m[1], "output")
                in_causality = self._to_node.fmu_port_causality.get(m[3], "input")
                out_item.setData(out_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
                in_item.setData(in_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
                self._model.appendRow([out_item, in_item])
            elif len(m) == 2:
                out_item = QStandardItem(m[0])
                in_item = QStandardItem(m[1])
                self._model.appendRow([out_item, in_item])

    def row_count(self) -> int:
        return self._model.rowCount()

    def remove_all(self):
        """Remove all rows from this direction tab."""
        self._close_editor()
        self._model.removeRows(0, self._model.rowCount())

    # ── Auto-connect ────────────────────────────────────────────

    def auto_connect(self, existing: set):
        """Add rows for matching output/input port names not in *existing*."""
        if not self._from_node or not self._to_node:
            return
        self._close_editor()
        from_name = self._from_node.fmu_path.name
        to_name = self._to_node.fmu_path.name
        to_inputs = set(self._to_node.fmu_input_names)
        for name in self._from_node.fmu_output_names:
            if name in to_inputs:
                m = (from_name, name, to_name, name)
                if m not in existing:
                    out_item = QStandardItem(name)
                    in_item = QStandardItem(name)
                    out_causality = self._from_node.fmu_port_causality.get(name, "output")
                    in_causality = self._to_node.fmu_port_causality.get(name, "input")
                    out_item.setData(out_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
                    in_item.setData(in_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
                    self._model.appendRow([out_item, in_item])
                    existing.add(m)

    # ── Slots ───────────────────────────────────────────────────

    def _on_add(self):
        if not self._from_node or not self._to_node:
            return
        if not self._from_node.fmu_output_names or not self._to_node.fmu_input_names:
            return
        out_item = QStandardItem(self._from_node.fmu_output_names[0])
        in_item = QStandardItem(self._to_node.fmu_input_names[0])
        out_causality = self._from_node.fmu_port_causality.get(self._from_node.fmu_output_names[0], "output")
        in_causality = self._to_node.fmu_port_causality.get(self._to_node.fmu_input_names[0], "input")
        out_item.setData(out_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
        in_item.setData(in_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
        self._model.appendRow([out_item, in_item])

        new_row_index = self._model.rowCount() - 1
        proxy_index = self._proxy.mapFromSource(self._model.index(new_row_index, 0))
        self._table.setCurrentIndex(proxy_index)
        self._table.scrollTo(proxy_index, QAbstractItemView.ScrollHint.EnsureVisible)

        self.changed.emit()

    def _on_remove(self):
        source_rows = sorted(
            {self._proxy.mapToSource(idx).row()
             for idx in self._table.selectionModel().selectedRows()},
            reverse=True,
        )
        self._table.setCurrentIndex(QModelIndex())
        for r in source_rows:
            self._model.removeRow(r)
        self.changed.emit()


class _TerminalComboDelegate(QStyledItemDelegate):
    """Delegate that opens a _PortListSelectorDialog for terminal selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[str] = []

    def set_items(self, items: List[str]):
        self._items = list(items)

    def createEditor(self, parent, option, index):
        dummy_editor = QWidget(parent)
        dummy_editor.setVisible(False)
        dummy_editor.setMaximumSize(0, 0)

        current_value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        self._show_selector_dialog(current_value, parent, option, index, dummy_editor)

        return dummy_editor

    def _show_selector_dialog(self, current_value, parent, option, index, editor):
        dialog = _PortListSelectorDialog(parent)
        dialog.setWindowTitle("Select Terminal")
        dialog.set_items(self._items)
        dialog.set_selected(current_value)

        table = self.parent()
        if table and hasattr(table, 'mapToGlobal'):
            cell_pos = table.mapToGlobal(option.rect.bottomLeft())
            dialog.move(cell_pos)

        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            selected_value = dialog.get_selected()
            editor.setProperty("selected_value", selected_value)
            if table and hasattr(table, 'model'):
                model = table.model()
                self.setModelData(editor, model, index)

        self.closeEditor.emit(editor)

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        editor.setProperty("current_value", value)

    def setModelData(self, editor, model, index):
        selected_value = editor.property("selected_value")
        if selected_value:
            model.setData(index, selected_value, Qt.ItemDataRole.EditRole)
        else:
            current = index.data(Qt.ItemDataRole.DisplayRole) or ""
            model.setData(index, current, Qt.ItemDataRole.EditRole)

        table = self.parent()
        if table:
            table.update()

    def updateEditorGeometry(self, editor, option, index):
        editor.hide()
        editor.setGeometry(0, 0, 0, 0)


class _WireTerminalsTab(QWidget):
    """Tab for connecting two FMUs via their declared Terminals.

    Shows a 2-column table (Terminal A, Terminal B) where each cell
    allows selecting a terminal from the respective node.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._node_a: Optional[NodeItem] = None
        self._node_b: Optional[NodeItem] = None

        # -- Table model (2 columns) --
        self._model = QStandardItemModel(0, 2)
        self._model.setHorizontalHeaderLabels(["Terminal A", "Terminal B"])

        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setDynamicSortFilter(False)
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setSortingEnabled(True)
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        # -- Delegates --
        self._delegate_a = _TerminalComboDelegate(self._table)
        self._delegate_b = _TerminalComboDelegate(self._table)
        self._table.setItemDelegateForColumn(0, self._delegate_a)
        self._table.setItemDelegateForColumn(1, self._delegate_b)

        self._model.dataChanged.connect(lambda *_: self.changed.emit())

        # -- Buttons --
        self._add_btn = QPushButton("Add link")
        self._remove_btn = QPushButton("Remove link")
        self._add_btn.setProperty("class", "info")
        self._remove_btn.setProperty("class", "removal")
        self._add_btn.clicked.connect(self._on_add)
        self._remove_btn.clicked.connect(self._on_remove)

        btn_width = max(self._add_btn.sizeHint().width(),
                        self._remove_btn.sizeHint().width(),
                        150)
        self._add_btn.setMinimumWidth(btn_width)
        self._remove_btn.setMinimumWidth(btn_width)

        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.addWidget(self._add_btn)
        btn_lay.addWidget(self._remove_btn)
        btn_lay.addStretch()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._table, 1)
        lay.addLayout(btn_lay)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        unlock_column_resize(self._table)

    # ── Configuration ───────────────────────────────────────────

    def set_nodes(self, node_a: NodeItem, node_b: NodeItem):
        self._node_a = node_a
        self._node_b = node_b
        terminal_names_a = list(node_a.fmu_terminal_names)
        terminal_names_b = list(node_b.fmu_terminal_names)
        self._delegate_a.set_items(terminal_names_a)
        self._delegate_b.set_items(terminal_names_b)

    # ── Data access ─────────────────────────────────────────────

    def _close_editor(self):
        self._table.setCurrentIndex(QModelIndex())

    def terminal_mappings(self) -> List[tuple]:
        """Return list of 4-tuples (fmu_a_name, terminal_a, fmu_b_name, terminal_b)."""
        if not self._node_a or not self._node_b:
            return []
        result = []
        a_name = self._node_a.fmu_path.name
        b_name = self._node_b.fmu_path.name
        for r in range(self._model.rowCount()):
            item_a = self._model.item(r, 0)
            item_b = self._model.item(r, 1)
            if item_a and item_b and item_a.text() and item_b.text():
                result.append((a_name, item_a.text(), b_name, item_b.text()))
        return result

    def load_terminal_mappings(self, mappings: List[tuple]):
        """Populate from 4-tuples (fmu_a, terminal_a, fmu_b, terminal_b)."""
        self._close_editor()
        self._model.removeRows(0, self._model.rowCount())
        if not self._node_a or not self._node_b:
            return
        a_name = self._node_a.fmu_path.name
        b_name = self._node_b.fmu_path.name
        for m in mappings:
            if len(m) >= 4 and m[0] == a_name and m[2] == b_name:
                self._model.appendRow([QStandardItem(m[1]), QStandardItem(m[3])])

    def row_count(self) -> int:
        return self._model.rowCount()

    def remove_all(self):
        self._close_editor()
        self._model.removeRows(0, self._model.rowCount())

    # ── Slots ───────────────────────────────────────────────────

    def _on_add(self):
        if not self._node_a or not self._node_b:
            return
        terminal_names_a = self._node_a.fmu_terminal_names
        terminal_names_b = self._node_b.fmu_terminal_names
        default_a = terminal_names_a[0] if terminal_names_a else ""
        default_b = terminal_names_b[0] if terminal_names_b else ""
        self._model.appendRow([QStandardItem(default_a),
                               QStandardItem(default_b)])

        new_row_index = self._model.rowCount() - 1
        proxy_index = self._proxy.mapFromSource(self._model.index(new_row_index, 0))
        self._table.setCurrentIndex(proxy_index)
        self._table.scrollTo(proxy_index, QAbstractItemView.ScrollHint.EnsureVisible)

        self.changed.emit()

    def _on_remove(self):
        source_rows = sorted(
            {self._proxy.mapToSource(idx).row()
             for idx in self._table.selectionModel().selectedRows()},
            reverse=True,
        )
        self._table.setCurrentIndex(QModelIndex())
        for r in source_rows:
            self._model.removeRow(r)
        self.changed.emit()


class WireDetailWidget(QWidget):
    """WireItem details with two tabs – one per direction (A → B and B → A).

    Each tab shows a 2-column table (Output Port, Input Port).
    The *Auto-Connect* button populates **both** directions at once.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wire: Optional[WireItem] = None

        # -- Title --
        self._name_label = QLabel()
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)
        self._name_label.setWordWrap(True)
        self._name_label.setMinimumWidth(0)

        # -- Tabs (one per direction + terminals) --
        self._tab_ab = _WireDirectionTab()
        self._tab_ba = _WireDirectionTab()
        self._tab_terminals = _WireTerminalsTab()
        self._tab_ab.changed.connect(self._on_tab_changed)
        self._tab_ba.changed.connect(self._on_tab_changed)
        self._tab_terminals.changed.connect(self._on_tab_changed)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._tab_ab, "A → B")
        self._tabs.addTab(self._tab_ba, "B → A")
        self._tabs.addTab(self._tab_terminals, "Terminals")

        # -- Buttons --
        self._auto_btn = QPushButton("Auto-Connect")
        self._auto_btn.setProperty("class", "info")
        self._auto_btn.clicked.connect(self._on_auto_connect)

        self._remove_all_btn = QPushButton("Remove All")
        self._remove_all_btn.setProperty("class", "removal")
        self._remove_all_btn.clicked.connect(self._on_remove_all)

        self._export_btn = QPushButton("Export")
        self._export_btn.setProperty("class", "save")
        self._export_btn.clicked.connect(self._on_export)

        self._import_btn = QPushButton("Import")
        self._import_btn.setProperty("class", "removal")
        self._import_btn.clicked.connect(self._on_import)

        btn_width = max(
            self._auto_btn.sizeHint().width(),
            self._remove_all_btn.sizeHint().width(),
            self._export_btn.sizeHint().width(),
            self._import_btn.sizeHint().width(),
            150,
        )
        for btn in (self._auto_btn, self._remove_all_btn, self._export_btn, self._import_btn):
            btn.setMinimumWidth(btn_width)

        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.addWidget(self._auto_btn)
        btn_lay.addWidget(self._remove_all_btn)
        btn_lay.addWidget(self._import_btn)
        btn_lay.addWidget(self._export_btn)
        btn_lay.addStretch()

        # -- Layout --
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addWidget(self._tabs, 1)
        lay.addLayout(btn_lay)

    # ── Public API ──────────────────────────────────────────────

    def set_wire(self, wire):
        self.sync_to_wire()
        self._wire = wire
        na, nb = wire.node_a, wire.node_b
        self._name_label.setText(f"{na.title} (A) ↔ {nb.title} (B)")

        self._tab_ab.set_nodes(na, nb)
        self._tab_ba.set_nodes(nb, na)
        self._tab_terminals.set_nodes(na, nb)

        self._load_from_wire()

    # ── Internal sync helpers ─────────────────────────────────────

    def sync_to_wire(self):
        if self._wire is None:
            return
        self._wire.mappings = self._tab_ab.mappings() + self._tab_ba.mappings()
        self._wire.terminal_mappings = self._tab_terminals.terminal_mappings()

    def _load_from_wire(self):
        if self._wire is None:
            return
        all_mappings = list(self._wire.mappings)
        self._tab_ab.load_mappings(all_mappings)
        self._tab_ba.load_mappings(all_mappings)
        self._tab_terminals.load_terminal_mappings(list(self._wire.terminal_mappings))

    # ── Slots ────────────────────────────────────────────────────

    def _on_auto_connect(self):
        if self._wire is None:
            return
        existing = set(self._wire.mappings)
        self._tab_ab.auto_connect(existing)
        self._tab_ba.auto_connect(existing)
        self.sync_to_wire()
        self.changed.emit()

    def _on_remove_all(self):
        if self._wire is None:
            return
        self._tab_ab.remove_all()
        self._tab_ba.remove_all()
        self._tab_terminals.remove_all()
        self.sync_to_wire()
        self.changed.emit()

    def _on_export(self):
        if self._wire is None:
            return
        self.sync_to_wire()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export connections", "", "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        import csv
        all_mappings = list(self._wire.mappings)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["FMU From", "Port From", "FMU To", "Port To"])
            for m in all_mappings:
                if len(m) >= 4:
                    writer.writerow([m[0], m[1], m[2], m[3]])

    def _on_import(self):
        if self._wire is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import connections", "", "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        import csv
        mappings = []
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header or len(header) < 4:
                return
            for row in reader:
                if len(row) < 4:
                    continue
                fmu_from = row[0].strip()
                port_from = row[1].strip()
                fmu_to = row[2].strip()
                port_to = row[3].strip()
                if not fmu_from or not port_from or not fmu_to or not port_to:
                    continue
                mappings.append((fmu_from, port_from, fmu_to, port_to))
        self._wire.mappings = mappings
        self._load_from_wire()
        self.changed.emit()

    def _on_tab_changed(self):
        self.sync_to_wire()
        self.changed.emit()
