"""
Detail panels for FMU container builder.

Contains classes for displaying and editing details of nodes, wires, and containers.
"""

from typing import *

from PySide6.QtCore import Qt, Signal, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import (
    QStandardItemModel, QStandardItem, QColor,
)
from PySide6.QtWidgets import (
    QWidget, QTableView, QLabel, QHeaderView, QVBoxLayout, QHBoxLayout,
    QStyledItemDelegate, QAbstractItemView, QPushButton, QDialog, QLineEdit,
    QFrame, QListWidget, QListWidgetItem, QTabWidget,
)

from fmu_manipulation_toolbox.gui.fmucontainer.graph import NodeItem, WireItem
from fmu_manipulation_toolbox.gui.style import placeholder_color
from fmu_manipulation_toolbox.help import Help


def _unlock_column_resize(table: QTableView):
    """Switch from *Stretch* to *Interactive*, preserving the current widths.

    Call from ``showEvent`` so the columns start stretched (50 / 50) and
    then become user-resizable.  Runs only once (no-op after the switch).
    """
    header = table.horizontalHeader()
    if header.sectionResizeMode(0) != QHeaderView.ResizeMode.Stretch:
        return
    widths = [header.sectionSize(i) for i in range(header.count())]
    if not any(widths):
        return
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for i, w in enumerate(widths):
        header.resizeSection(i, w)


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
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.itemSelectionChanged.connect(self._on_item_selected)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)

        # -- Buttons --
        self._ok_btn = QPushButton("OK")
        self._cancel_btn = QPushButton("Cancel")
        self._ok_btn.clicked.connect(self.accept)
        self._cancel_btn.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self._ok_btn)
        btn_layout.addWidget(self._cancel_btn)

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
        self._causalities: Dict[str, str] = {}  # Maps port name to causality

    def set_items(self, items: List[str]):
        self._items = list(items)

    def set_causalities(self, causalities: Dict[str, str]):
        """Set the causality info for ports."""
        self._causalities = causalities

    def createEditor(self, parent, option, index):
        """Create a non-visible dummy editor; the actual dialog will be shown separately."""
        # Create a completely invisible dummy widget to satisfy Qt's delegate contract
        # We use QWidget instead of QLineEdit to avoid any rendering issues
        dummy_editor = QWidget(parent)
        dummy_editor.setVisible(False)
        dummy_editor.setMaximumSize(0, 0)

        # Show the dialog immediately
        current_value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        self._show_port_selector_dialog(current_value, parent, option, index, dummy_editor)

        return dummy_editor

    def _show_port_selector_dialog(self, current_value, parent, option, index, editor):
        """Show the port selector dialog and handle selection."""
        dialog = _PortListSelectorDialog(parent)
        dialog.set_items(self._items)
        dialog.set_causalities(self._causalities)
        dialog.set_selected(current_value)

        # Position dialog near the cell
        table = self.parent()
        if table and hasattr(table, 'mapToGlobal'):
            cell_pos = table.mapToGlobal(option.rect.bottomLeft())
            dialog.move(cell_pos)

        # Show dialog (blocking)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            selected_value = dialog.get_selected()
            # Store the value on the editor to retrieve in setModelData
            editor.setProperty("selected_value", selected_value)
            # Get the model from the table's proxy
            if table and hasattr(table, 'model'):
                model = table.model()
                # Call setModelData directly with the proxy model
                self.setModelData(editor, model, index)

        # Always close the editor when done
        self.closeEditor.emit(editor)

    def setEditorData(self, editor, index):
        """Initialize editor with current value (minimal for dummy editor)."""
        # The editor is a dummy QWidget used to store the selected value
        value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        editor.setProperty("current_value", value)

    def setModelData(self, editor, model, index):
        """Commit selected value to model."""
        # Retrieve the value stored by _show_port_selector_dialog
        selected_value = editor.property("selected_value")
        if selected_value:
            model.setData(index, selected_value, Qt.ItemDataRole.EditRole)
        else:
            # Keep the current value if dialog was canceled
            current = index.data(Qt.ItemDataRole.DisplayRole) or ""
            model.setData(index, current, Qt.ItemDataRole.EditRole)

        # Refresh table view after data change
        table = self.parent()
        if table:
            # Mark the table for repaint to reflect the data change
            table.update()

    def updateEditorGeometry(self, editor, option, index):
        """Hide the dummy editor since we use a dialog instead."""
        # Make absolutely sure the editor is never visible
        editor.hide()
        editor.setGeometry(0, 0, 0, 0)

    def paint(self, painter, option, index):
        """Display parameter ports in italics."""
        # Check if this port has "parameter" causality and apply italic formatting
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text and text in self._causalities and self._causalities[text] == "parameter":
            font = option.font
            font.setItalic(True)
            option.font = font

        # Let the default painting happen
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
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.CurrentChanged)
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
        _unlock_column_resize(self._table)

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
                # Store causality info for display formatting
                out_causality = self._from_node.fmu_port_causality.get(m[1], "output")
                in_causality = self._to_node.fmu_port_causality.get(m[3], "input")
                out_item.setData(out_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
                in_item.setData(in_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
                self._model.appendRow([out_item, in_item])
            elif len(m) == 2:
                # Legacy 2-tuple: only load in the first direction tab
                out_item = QStandardItem(m[0])
                in_item = QStandardItem(m[1])
                self._model.appendRow([out_item, in_item])

    def row_count(self) -> int:
        return self._model.rowCount()

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
                    # Store causality info
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
        # Store causality info
        out_causality = self._from_node.fmu_port_causality.get(self._from_node.fmu_output_names[0], "output")
        in_causality = self._to_node.fmu_port_causality.get(self._to_node.fmu_input_names[0], "input")
        out_item.setData(out_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
        in_item.setData(in_causality, _PortComboDelegate.ROLE_PORT_CAUSALITIES)
        self._model.appendRow([out_item, in_item])

        # Select and display the newly created row
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

        # -- Tabs (one per direction) --
        self._tab_ab = _WireDirectionTab()
        self._tab_ba = _WireDirectionTab()
        self._tab_ab.changed.connect(self._on_tab_changed)
        self._tab_ba.changed.connect(self._on_tab_changed)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._tab_ab, "A → B")
        self._tabs.addTab(self._tab_ba, "B → A")

        # -- Auto-Connect button --
        self._auto_btn = QPushButton("Auto-Connect")
        self._auto_btn.setProperty("class", "info")
        self._auto_btn.clicked.connect(self._on_auto_connect)

        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.addWidget(self._auto_btn)
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

        self._load_from_wire()

    # ── Internal sync helpers ─────────────────────────────────────

    def sync_to_wire(self):
        if self._wire is None:
            return
        self._wire.mappings = self._tab_ab.mappings() + self._tab_ba.mappings()

    def _load_from_wire(self):
        if self._wire is None:
            return
        all_mappings = list(self._wire.mappings)
        self._tab_ab.load_mappings(all_mappings)
        self._tab_ba.load_mappings(all_mappings)

    # ── Slots ────────────────────────────────────────────────────

    def _on_auto_connect(self):
        if self._wire is None:
            return
        existing = set(self._wire.mappings)
        self._tab_ab.auto_connect(existing)
        self._tab_ba.auto_connect(existing)
        self.sync_to_wire()
        self.changed.emit()

    def _on_tab_changed(self):
        self.sync_to_wire()
        self.changed.emit()


class _StartValueDelegate(QStyledItemDelegate):
    """Delegate that shows the FMU default start value as a gray placeholder
    when the user has not entered a value. Also displays parameter ports in italics."""

    ROLE_PLACEHOLDER = Qt.ItemDataRole.UserRole + 100
    ROLE_CAUSALITY = Qt.ItemDataRole.UserRole + 101

    def displayText(self, value, locale):
        # If there is actual text, show it normally
        if value:
            return str(value)
        return ""

    def paint(self, painter, option, index):
        # Check if this is a parameter port and apply italic formatting
        causality = index.data(self.ROLE_CAUSALITY)
        if causality == "parameter":
            # Get the default font from the option and make it italic
            font = option.font
            font.setItalic(True)
            option.font = font

        # Let the default painting happen first
        super().paint(painter, option, index)
        # If the cell is empty, draw the placeholder in gray
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

        # Apply delegate to display parameter ports in italics
        self._out_delegate = _StartValueDelegate(self._out_table)
        self._out_table.setItemDelegateForColumn(0, self._out_delegate)

        self._tabs.addTab(self._out_table, "Output Ports")

        # ── Layout ────────────────────────────────────────────────
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addWidget(self._tabs, 1)

        # Unlock column resize when each tab page gets its real geometry
        self._sv_table.installEventFilter(self)
        self._out_table.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == event.Type.Resize:
            if obj is self._sv_table or obj is self._out_table:
                _unlock_column_resize(obj)
        return super().eventFilter(obj, event)

    # -- Sync helpers ----------------------------------------------------------

    def sync_to_node(self):
        """Write the table content back into the current NodeItem."""
        if self._current_node is None:
            return
        # Sync start values
        self._current_node.user_start_values.clear()
        for row in range(self._sv_model.rowCount()):
            port_name = self._sv_model.item(row, 0).text()
            value_item = self._sv_model.item(row, 1)
            value = value_item.text().strip() if value_item else ""
            if value:
                self._current_node.user_start_values[port_name] = value

        # Sync exposed outputs
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
            # Store causality for display formatting
            causality = node.fmu_port_causality.get(port_name, "input")
            name_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)

            user_val = node.user_start_values.get(port_name, "")
            value_item = QStandardItem(user_val)
            default = node.fmu_start_values.get(port_name)
            if default is not None:
                value_item.setData(str(default), _StartValueDelegate.ROLE_PLACEHOLDER)
                value_item.setToolTip(f"FMU default: {default}")
            # Also store causality on value item for consistency
            value_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)

            self._sv_model.appendRow([name_item, value_item])

        # ── Populate Output Ports tab ─────────────────────────────
        self._out_model.removeRows(0, self._out_model.rowCount())
        for port_name in node.fmu_output_names:
            name_item = QStandardItem(port_name)
            name_item.setEditable(False)
            # Store causality for display formatting
            causality = node.fmu_port_causality.get(port_name, "output")
            name_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)

            check_item = QStandardItem("")
            check_item.setEditable(False)
            check_item.setCheckable(True)
            exposed = node.user_exposed_outputs.get(port_name, False)
            check_item.setCheckState(Qt.CheckState.Checked if exposed else Qt.CheckState.Unchecked)
            # Also store causality on check item for consistency
            check_item.setData(causality, _StartValueDelegate.ROLE_CAUSALITY)

            self._out_model.appendRow([name_item, check_item])


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
        return " ".join([ f"{k} = {v}\n" for k, v in self.parameters.items()])


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

        # -- Sync edits back to ContainerParameters --
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
            # Set tooltip from help.py if available
            tooltip = help_instance.usage(f'-{k}')
            if tooltip:
                key_item.setToolTip(tooltip)
                value_item.setToolTip(tooltip)
            self._model.appendRow([key_item, value_item])

        self._container_parameters = container_parameters

    def _on_table_data_changed(self):
        for r in range(self._model.rowCount()):
            key = self._model.item(r, 0).text()
            value_item = self._model.item(r, 1)
            if value_item.isCheckable():
                value = value_item.checkState() == Qt.CheckState.Checked
            else:
                value = value_item.text()
            self._container_parameters.parameters[key] = value
        self.changed.emit()


class DetailPanelStack(QWidget):
    """Manages the detail panels (WireDetail, FMUDetail, ContainerDetail).

    Responsibilities:
    • Stack widget containing all detail panel types
    • Switching between panels based on selection
    • Coordinating detail panel updates
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── Detail panels ────────────────────────────────────────────
        self._empty_widget = QWidget()  # page 0
        self._wire_detail = WireDetailWidget()  # page 1
        self._fmu_detail = FMUDetailWidget()  # page 2
        self._container_detail = ContainerDetailWidget()  # page 3

        from PySide6.QtWidgets import QStackedWidget
        self._stack = QStackedWidget()
        self._stack.addWidget(self._empty_widget)
        self._stack.addWidget(self._wire_detail)
        self._stack.addWidget(self._fmu_detail)
        self._stack.addWidget(self._container_detail)
        self._stack.setCurrentIndex(0)

        # ── Layout ──────────────────────────────────────────────────
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stack)

    # ── Public API ──────────────────────────────────────────────────

    @property
    def wire_detail(self) -> WireDetailWidget:
        return self._wire_detail

    @property
    def fmu_detail(self) -> FMUDetailWidget:
        return self._fmu_detail

    @property
    def container_detail(self) -> ContainerDetailWidget:
        return self._container_detail

    def sync_edits(self):
        """Flush any pending edits from detail panels."""
        self._wire_detail.sync_to_wire()
        self._fmu_detail.sync_to_node()

    def show_empty(self):
        """Show empty panel."""
        self._stack.setCurrentWidget(self._empty_widget)

    def show_wire(self, wire):
        """Show wire detail panel."""
        self._wire_detail.set_wire(wire)
        self._stack.setCurrentWidget(self._wire_detail)

    def show_fmu(self, node):
        """Show FMU detail panel."""
        self._fmu_detail.set_node(node)
        self._stack.setCurrentWidget(self._fmu_detail)

    def show_container(self, container_parameters: ContainerParameters):
        """Show container detail panel."""
        self._container_detail.set_container(container_parameters)
        self._stack.setCurrentWidget(self._container_detail)



