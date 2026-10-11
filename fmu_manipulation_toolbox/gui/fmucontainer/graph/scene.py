"""NodeGraphScene — manages nodes and wires in the graph."""

from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtWidgets import QGraphicsScene, QGraphicsSceneMouseEvent
from PySide6.QtGui import QBrush


from fmu_manipulation_toolbox.assembly import instance_name

from .constants import NODE_TITLE_HEIGHT, COLOR_BACKGROUND
from .node import NodeItem, ConfigurationNode
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
    node_replaced = Signal(object)
    wire_added = Signal(object)
    wire_removed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setBackgroundBrush(QBrush(COLOR_BACKGROUND))

        self._drag_wire: _DragWireItem | None = None
        self._drag_start_node: NodeItem | None = None
        self._drag_target_node: NodeItem | None = None

        # Optional external validator: callable(node_a, node_b) -> bool.
        # Used by NodeTreeWidget to restrict wiring of the ConfigurationNode
        # (e.g. forbidding two ConfigurationNodes together). If None, all
        # wires are allowed.
        self.wire_validator: Callable[[NodeItem, NodeItem], bool] | None = None

        self.selectionChanged.connect(self._enforce_single_selection)

    def _enforce_single_selection(self):
        """Ensure only ONE item is selected at a time."""
        selected = self.selectedItems()
        if len(selected) > 1:
            self.clearSelection()
            if selected:
                selected[0].setSelected(True)

    # -- Public API ----------------------------------------------------------

    def add_node(self, fmu_path: Path, x: float = 0, y: float = 0, name: str | None = None) -> NodeItem:
        """Add a node for the FMU `fmu_path`.

        The node is named `name` (defaults to the file name), made unique in the scene: when the name is already
        used — the same file added again, or another file with the same name — the node is an instance named
        `<stem>-<n>.fmu`, with the smallest free `n`.
        """
        fmu_path = Path(fmu_path)
        node = NodeItem(fmu_path, x=x, y=y, name=self.free_name(name or fmu_path.name))
        self.addItem(node)
        self.clearSelection()
        node.setSelected(True)
        self.node_added.emit(node)
        return node

    def free_name(self, name: str, ignored: NodeItem | None = None) -> str:
        """`name`, or the first free instance name derived from it, given the names of the FMU nodes of the scene
        (except `ignored`)."""
        return instance_name(name, [node.name for node in self.fmu_nodes() if node is not ignored])

    def replace_node_fmu(self, node: NodeItem, fmu_path: Path):
        """Replace the FMU of `node` only; its name is recomputed from the new file (smallest free name)."""
        node.replace_fmu(fmu_path, self.free_name(fmu_path.name, ignored=node))
        self.node_replaced.emit(node)

    def configuration_node(self) -> ConfigurationNode | None:
        """Return the singleton ConfigurationNode currently in the scene, if any."""
        for it in self.items():
            if isinstance(it, ConfigurationNode):
                return it
        return None

    def get_or_create_configuration_node(self, x: float = 0, y: float = -150) -> ConfigurationNode:
        """Return the singleton `ts_multiplier` ConfigurationNode, creating it
        (GUI-only, never exported to the Assembly model) if it doesn't exist yet.
        """
        node = self.configuration_node()
        if node is None:
            node = ConfigurationNode(x=x, y=y)
            self.addItem(node)
            self.node_added.emit(node)
        return node

    def remove_configuration_node(self):
        """Explicitly remove the singleton ConfigurationNode (if present)."""
        node = self.configuration_node()
        if node is not None:
            node.remove_wires()
            self.node_removed.emit(node)
            self.removeItem(node)

    def add_wire(self, node_a: NodeItem, node_b: NodeItem) -> WireItem | None:
        """Connect two nodes with a wire. Returns None if invalid."""
        if node_a is node_b:
            return None
        # No duplicate wire between the same pair
        for w in node_a.wires:
            other = w.node_b if w.node_a is node_a else w.node_a
            if other is node_b:
                return None
        if self.wire_validator is not None and not self.wire_validator(node_a, node_b):
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
                if not getattr(item, "deletable", True):
                    continue
                self.node_removed.emit(item)
                item.remove_wires()
                self.removeItem(item)

    def nodes(self) -> list[NodeItem]:
        return [it for it in self.items() if isinstance(it, NodeItem)]

    def fmu_nodes(self) -> list[NodeItem]:
        """Return only nodes backed by a real FMU (excludes ConfigurationNode)."""
        return [it for it in self.items() if isinstance(it, NodeItem) and not isinstance(it, ConfigurationNode)]

    def wires(self) -> list[WireItem]:
        return [it for it in self.items() if isinstance(it, WireItem)]

    def clear_all(self):
        for wire in self.wires():
            wire.remove()
        for node in self.nodes():
            self.removeItem(node)

    # -- Interaction: wire drag from node body ---------------------------------

    def _node_at(self, scene_pos: QPointF) -> NodeItem | None:
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

