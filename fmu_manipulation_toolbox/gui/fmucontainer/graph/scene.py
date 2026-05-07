"""NodeGraphScene — manages nodes and wires in the graph."""

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtWidgets import QGraphicsScene, QGraphicsSceneMouseEvent, QMessageBox
from PySide6.QtGui import QBrush


from .constants import NODE_TITLE_HEIGHT, COLOR_BACKGROUND
from .node import NodeItem
from .wire import WireItem, _DragWireItem


class NodeGraphScene(QGraphicsScene):
    """Graphics scene managing nodes and wires.

    Features:
    • Single selection enforcement (no multi-select)
    • Automatic sync with tree view
    • Wire drag-and-drop
    """

    node_added = Signal(object)
    node_removed = Signal(object)
    wire_added = Signal(object)
    wire_removed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setBackgroundBrush(QBrush(COLOR_BACKGROUND))

        self._drag_wire: Optional[_DragWireItem] = None
        self._drag_start_node: Optional[NodeItem] = None
        self._drag_target_node: Optional[NodeItem] = None

        self.selectionChanged.connect(self._enforce_single_selection)

    def _enforce_single_selection(self):
        """Ensure only ONE item is selected at a time."""
        selected = self.selectedItems()
        if len(selected) > 1:
            self.clearSelection()
            if selected:
                selected[0].setSelected(True)

    # -- Public API ----------------------------------------------------------

    def add_node(self, fmu_path: Path, x: float = 0, y: float = 0) -> Optional[NodeItem]:
        fmu_path = Path(fmu_path)
        # Check for duplicate FMU (same resolved path)
        resolved = fmu_path.resolve()
        for existing in self.nodes():
            if existing.fmu_path.resolve() == resolved:
                parent_widget = None
                for view in self.views():
                    parent_widget = view
                    break
                msg = QMessageBox(parent_widget)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("Duplicate FMU")
                msg.setText(
                    f"'{fmu_path.name}' is already present in the assembly.\n"
                    "It is not yet possible to include the same FMU more than once."
                )
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                btn_ok = msg.button(QMessageBox.StandardButton.Ok)
                btn_ok.setProperty("class", "info")
                btn_ok.setMinimumWidth(150)
                msg.exec()
                return None
        node = NodeItem(fmu_path, x=x, y=y)
        self.addItem(node)
        self.clearSelection()
        node.setSelected(True)
        self.node_added.emit(node)
        return node

    def add_wire(self, node_a: NodeItem, node_b: NodeItem) -> Optional[WireItem]:
        """Connect two nodes with a wire. Returns None if invalid."""
        if node_a is node_b:
            return None
        # No duplicate wire between the same pair
        for w in node_a.wires:
            other = w.node_b if w.node_a is node_a else w.node_a
            if other is node_b:
                return None
        wire = WireItem(node_a, node_b)
        self.addItem(wire)
        self.clearSelection()
        wire.setSelected(True)
        self.wire_added.emit(wire)
        return wire

    def remove_selected(self):
        for item in list(self.selectedItems()):
            if isinstance(item, WireItem):
                self.wire_removed.emit(item)
                item.remove()
        for item in list(self.selectedItems()):
            if isinstance(item, NodeItem):
                self.node_removed.emit(item)
                item.remove_wires()
                self.removeItem(item)

    def nodes(self) -> List[NodeItem]:
        return [it for it in self.items() if isinstance(it, NodeItem)]

    def wires(self) -> List[WireItem]:
        return [it for it in self.items() if isinstance(it, WireItem)]

    def clear_all(self):
        for wire in self.wires():
            wire.remove()
        for node in self.nodes():
            self.removeItem(node)

    # -- Interaction: wire drag from node body ---------------------------------

    def _node_at(self, scene_pos: QPointF) -> Optional[NodeItem]:
        for item in self.items(scene_pos, Qt.ItemSelectionMode.IntersectsItemBoundingRect):
            if isinstance(item, NodeItem):
                return item
        return None

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            node = self._node_at(event.scenePos())
            if node:
                local_pos = node.mapFromScene(event.scenePos())
                if local_pos.y() >= NODE_TITLE_HEIGHT:
                    self._drag_start_node = node
                    start = node.edge_point(event.scenePos())
                    self._drag_wire = _DragWireItem(start)
                    self.addItem(self._drag_wire)
                    self.clearSelection()
                    node.setSelected(True)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.accept()
            return

        if self._drag_wire:
            self._drag_wire.update_destination(event.scenePos())
            node = self._node_at(event.scenePos())
            if node is self._drag_start_node:
                node = None
            if node is not self._drag_target_node:
                if self._drag_target_node:
                    self._drag_target_node.setZValue(1)
                self._drag_target_node = node
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.accept()
            return

        if self._drag_wire:
            if self._drag_target_node:
                self._drag_target_node.setZValue(1)
                self._drag_target_node = None
            target = self._node_at(event.scenePos())
            if target and target is not self._drag_start_node:
                self.add_wire(self._drag_start_node, target)
            self.removeItem(self._drag_wire)
            self._drag_wire = None
            self._drag_start_node = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

