"""
Graph visualization for FMU container builder.

Contains classes for rendering nodes (FMU), wires (connections), and the interactive scene.
"""

import math
import uuid

from pathlib import Path
from typing import *

from PySide6.QtCore import Qt, QRectF, QPointF, QLineF, Signal
from PySide6.QtGui import ( QPainter, QPen, QBrush, QColor, QPainterPath, QPainterPathStroker,
                            QFont, QFontMetrics, QKeyEvent)
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsPathItem,
    QGraphicsEllipseItem,
    QMenu, QWidget, QVBoxLayout, QFileDialog,
    QGraphicsSceneMouseEvent, QStyleOptionGraphicsItem,
    QMessageBox,
)

from fmu_manipulation_toolbox.operations import FMU, FMUPort, OperationAbstract

# Try to import FMPy GUI
try:
    from fmpy.gui.MainWindow import MainWindow as FMPyMainWindow
    FMPY_AVAILABLE = True
except ImportError:
    FMPY_AVAILABLE = False

# Internal tool windows
from fmu_manipulation_toolbox.gui.fmueditor.__main__ import MainWindow as FMUEditorMainWindow
from fmu_manipulation_toolbox.gui.fmutool.__main__ import MainWindow as FMUToolMainWindow


# ─────────────────────────── Visual constants ──────────────────────────

# Colors
COLOR_BACKGROUND    = QColor("#2b2b2b")
COLOR_GRID_LIGHT    = QColor("#333333")
COLOR_GRID_DARK     = QColor("#292929")

COLOR_NODE_BG       = QColor("#3a3a44")
COLOR_NODE_TITLE_BG = QColor("#4571a4")
COLOR_NODE_BORDER   = QColor("#222222")
COLOR_NODE_SELECTED = QColor("#f0a030")
COLOR_TEXT          = QColor("#dddddd")

COLOR_WIRE          = QColor("#cccccc")
COLOR_WIRE_SELECTED = QColor("#f0a030")
COLOR_WIRE_DRAGGING = QColor("#88bbff")

# Dimensions
NODE_MIN_WIDTH      = 140
NODE_TITLE_HEIGHT   = 28
NODE_PORT_SPACING   = 26
NODE_CORNER_RADIUS  = 6
GRID_SIZE           = 20
GRID_SQUARES        = 5
ARROW_SIZE          = 10
WAYPOINT_RADIUS     = 5

# Fonts
FONT_TITLE          = QFont("Verdana", 10, QFont.Weight.Bold)
FONT_PORT           = QFont("Verdana", 8)
FONT_PORT_PARAMETER = QFont("Verdana", 8)
FONT_PORT_PARAMETER.setItalic(True)


class NodeItem(QGraphicsRectItem, OperationAbstract):
    """Rectangular node representing an FMU. No visual ports — wires
    connect directly to the node edges."""

    def __init__(self, fmu_path: Path, x: float = 0, y: float = 0):
        super().__init__()

        self.uid = str(uuid.uuid4())
        self._title = fmu_path.name
        self.fmu_path = fmu_path

        # Title bar highlight (for selected container)
        self._title_highlighted = False

        # -- Read FMU ports ---------------------------------------------------
        self.fmu_input_names: List[str] = []
        self.fmu_output_names: List[str] = []
        self.fmu_port_causality: Dict[str, str] = {}  # Maps port name to causality
        self.fmu_start_values: Dict[str, str] = {}
        self.user_start_values: Dict[str, str] = {}
        self.user_exposed_outputs: Dict[str, bool] = {}
        self.fmu_step_size: Optional[str] = None
        self.fmu_generator: str = ""

        fmu = FMU(fmu_path)
        fmu.apply_operation(self)
        del fmu

        # -- Wires attached to this node --------------------------------------
        self.wires: List["WireItem"] = []

        # Flags
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(1)

        # -- Size calculation -------------------------------------------------
        height = NODE_TITLE_HEIGHT + NODE_PORT_SPACING + 10

        fm_title = QFontMetrics(FONT_TITLE)
        width = max(NODE_MIN_WIDTH, fm_title.horizontalAdvance(self.title) + 20)

        self.setRect(0, 0, width, height)
        self.setPos(x, y)

        # -- Title ------------------------------------------------------------
        self._title_item = QGraphicsTextItem(self.title, self)
        self._title_item.setDefaultTextColor(COLOR_TEXT)
        self._title_item.setFont(FONT_TITLE)
        self._title_item.setAcceptHoverEvents(False)
        self._title_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        tbr = self._title_item.boundingRect()
        self._title_item.setPos((width - tbr.width()) / 2, (NODE_TITLE_HEIGHT - tbr.height()) / 2)

    def __repr__(self):
        return "Collect I/O ports"

    def set_title_highlighted(self, highlighted: bool):
        if self._title_highlighted != highlighted:
            self._title_highlighted = highlighted
            self.update()

    def fmi_attrs(self, attrs):
        self.fmu_generator = attrs.get("generationTool", "-")

    def experiment_attrs(self, attrs):
        self.fmu_step_size = attrs.get("stepSize", "")

    def port_attrs(self, fmu_port: FMUPort) -> int:
        causality = fmu_port.get("causality", "local")
        name = fmu_port.get("name", "")
        if causality in ("input", "parameter"):
            self.fmu_input_names.append(name)
        elif causality == "output":
            self.fmu_output_names.append(name)
        # Store causality for later use
        self.fmu_port_causality[name] = causality
        start = fmu_port.get("start", None)
        if start is not None:
            self.fmu_start_values[name] = start
        return 0

    # -- Title -----------------------------------------------------------------

    @property
    def title(self) -> str:
        return self._title


    # -- Edge anchor -----------------------------------------------------------

    def edge_point(self, other_center: QPointF) -> QPointF:
        """Return the point on the node border closest to *other_center*.

        The anchor is the intersection of the line from this node's center
        to *other_center* with the node rectangle (in scene coords).
        """
        r = self.sceneBoundingRect()
        cx, cy = r.center().x(), r.center().y()
        dx = other_center.x() - cx
        dy = other_center.y() - cy
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return QPointF(cx, cy)

        hw, hh = r.width() / 2.0, r.height() / 2.0
        # Determine which edge the line crosses first
        if abs(dx) * hh > abs(dy) * hw:
            # Hits left or right edge
            t = hw / abs(dx)
        else:
            # Hits top or bottom edge
            t = hh / abs(dy)
        return QPointF(cx + dx * t, cy + dy * t)

    def center_scene_pos(self) -> QPointF:
        return self.sceneBoundingRect().center()

    # -- Rendering ----------------------------------------------------------------

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None):
        rect = self.rect()
        w, h = rect.width(), rect.height()

        # Body
        path_body = QPainterPath()
        path_body.addRoundedRect(0, 0, w, h, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(COLOR_NODE_BG))
        painter.drawPath(path_body)

        # Title bar
        path_title = QPainterPath()
        path_title.setFillRule(Qt.FillRule.WindingFill)
        path_title.addRoundedRect(0, 0, w, NODE_TITLE_HEIGHT, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)
        path_title.addRect(0, NODE_TITLE_HEIGHT - NODE_CORNER_RADIUS, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)
        path_title.addRect(w - NODE_CORNER_RADIUS, NODE_TITLE_HEIGHT - NODE_CORNER_RADIUS,
                           NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)

        color = QColor(COLOR_NODE_TITLE_BG)
        # Lighter color if highlighted
        if self._title_highlighted:
            color = color.lighter(150)  # 50% lighter
        painter.setBrush(QBrush(color))

        painter.drawPath(path_title.simplified())

        # Border
        pen_border = QPen(COLOR_NODE_SELECTED if self.isSelected() else COLOR_NODE_BORDER)
        pen_border.setWidthF(2.0 if self.isSelected() else 1.5)
        painter.setPen(pen_border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, w, h, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)

    # -- Move -> update wires --------------------------------------------------

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for wire in self.wires:
                wire.update_path()
        return super().itemChange(change, value)


    # -- Hover cursor feedback -------------------------------------------------

    def hoverMoveEvent(self, event):
        if event.pos().y() < NODE_TITLE_HEIGHT:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    # -- Helpers ---------------------------------------------------------------

    def remove_wires(self):
        """Remove all wires connected to this node."""
        for wire in list(self.wires):
            wire.remove()


class _WaypointHandle(QGraphicsEllipseItem):
    """Small draggable handle sitting on a wire waypoint.

    * **Drag** to move the waypoint.
    * **Double-click** to remove it.
    """

    def __init__(self, wire: "WireItem", index: int):
        r = WAYPOINT_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, wire)
        self._wire = wire
        self._index = index
        self._updating = False

        self.setBrush(QBrush(QColor(136, 187, 255, 140)))
        self.setPen(QPen(QColor("#446688"), 1.0))
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(3)
        self.setVisible(False)

    def itemChange(self, change, value):
        if (
            change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged
            and not self._updating
        ):
            self._wire.on_handle_moved(self._index, value)
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(170, 221, 255, 220)))
        self.setPen(QPen(QColor("#88bbff"), 1.5))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor(136, 187, 255, 140)))
        self.setPen(QPen(QColor("#446688"), 1.0))
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._wire.remove_waypoint(self._index)
        event.accept()


class WireItem(QGraphicsPathItem):
    """Wire connecting two NodeItems as a polyline (broken line).

    Arrowheads indicate data-flow direction, derived from the per-variable
    mappings:

    * Arrow on node_b side → data flows from node_a to node_b
    * Arrow on node_a side → data flows from node_b to node_a
    * Arrows on both sides → bidirectional

    Waypoints:

    * **Double-click** on the wire to add a waypoint.
    * **Drag** a handle to move a waypoint.
    * **Double-click** a handle to remove it.
    """

    def __init__(self, node_a: NodeItem, node_b: NodeItem, parent=None):
        super().__init__(parent)

        self.node_a = node_a
        self.node_b = node_b

        node_a.wires.append(self)
        node_b.wires.append(self)

        self._waypoints: List[QPointF] = []
        self._handles: List[_WaypointHandle] = []
        self.mappings: List[tuple] = []

        self.setPen(QPen(COLOR_WIRE, 2.0))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(0)

        self.update_path()

    # -- Direction helpers ----------------------------------------------------

    def _directions(self) -> tuple:
        """Return (a_to_b, b_to_a) booleans from mappings."""
        a_name = self.node_a.fmu_path.name
        b_name = self.node_b.fmu_path.name
        a_to_b = any(m[0] == a_name and m[2] == b_name for m in self.mappings)
        b_to_a = any(m[0] == b_name and m[2] == a_name for m in self.mappings)
        return a_to_b, b_to_a

    # -- All points of the polyline -------------------------------------------

    def _all_points(self) -> List[QPointF]:
        """Return [anchor_a, wp0, wp1, …, anchor_b] in scene coords."""
        cb = self.node_b.center_scene_pos()
        ca = self.node_a.center_scene_pos()
        target_a = self._waypoints[0] if self._waypoints else cb
        target_b = self._waypoints[-1] if self._waypoints else ca
        pa = self.node_a.edge_point(target_a)
        pb = self.node_b.edge_point(target_b)
        return [pa] + list(self._waypoints) + [pb]

    # -- Path update -----------------------------------------------------------

    def update_path(self):
        points = self._all_points()
        path = QPainterPath(points[0])
        for pt in points[1:]:
            path.lineTo(pt)
        self.setPath(path)

        for i, handle in enumerate(self._handles):
            handle._updating = True
            handle.setPos(self._waypoints[i])
            handle._updating = False

    def on_handle_moved(self, index: int, new_pos: QPointF):
        if 0 <= index < len(self._waypoints):
            self._waypoints[index] = QPointF(new_pos)
            points = self._all_points()
            path = QPainterPath(points[0])
            for pt in points[1:]:
                path.lineTo(pt)
            self.setPath(path)

    # -- Waypoint management ---------------------------------------------------

    def _sync_handles(self):
        """Create / destroy handles to match the waypoint list."""
        while len(self._handles) > len(self._waypoints):
            h = self._handles.pop()
            if h.scene():
                h.scene().removeItem(h)
        while len(self._handles) < len(self._waypoints):
            idx = len(self._handles)
            h = _WaypointHandle(self, idx)
            h.setVisible(self.isSelected())
            self._handles.append(h)
        for i, h in enumerate(self._handles):
            h._index = i

    @staticmethod
    def _point_to_segment_dist(p: QPointF, a: QPointF, b: QPointF) -> float:
        dx, dy = b.x() - a.x(), b.y() - a.y()
        len_sq = dx * dx + dy * dy
        if len_sq < 1e-10:
            return math.hypot(p.x() - a.x(), p.y() - a.y())
        t = max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / len_sq))
        proj_x = a.x() + t * dx
        proj_y = a.y() + t * dy
        return math.hypot(p.x() - proj_x, p.y() - proj_y)

    def add_waypoint(self, scene_pos: QPointF):
        """Insert a waypoint at *scene_pos* in the closest segment."""
        points = self._all_points()
        best_idx, best_dist = 0, float("inf")
        for i in range(len(points) - 1):
            d = self._point_to_segment_dist(scene_pos, points[i], points[i + 1])
            if d < best_dist:
                best_dist = d
                best_idx = i
        self._waypoints.insert(best_idx, QPointF(scene_pos))
        self._sync_handles()
        self.update_path()

    def remove_waypoint(self, index: int):
        if 0 <= index < len(self._waypoints):
            del self._waypoints[index]
            self._sync_handles()
            self.update_path()

    # -- Double-click → add waypoint ------------------------------------------

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        self.add_waypoint(event.scenePos())
        event.accept()

    # -- Selection hit area ---------------------------------------------------

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return stroker.createStroke(self.path())

    # -- Rendering (with arrowheads) -------------------------------------------

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            visible = bool(value)
            for h in self._handles:
                h.setVisible(visible)
        return super().itemChange(change, value)

    @staticmethod
    def _draw_arrow(painter: QPainter, tip: QPointF, direction: QPointF, size: float):
        """Draw a filled arrowhead at *tip* pointing in *direction*."""
        length = math.hypot(direction.x(), direction.y())
        if length < 1e-6:
            return
        dx, dy = direction.x() / length, direction.y() / length
        nx, ny = -dy, dx
        base = QPointF(tip.x() - dx * size, tip.y() - dy * size)
        left  = QPointF(base.x() + nx * size * 0.45, base.y() + ny * size * 0.45)
        right = QPointF(base.x() - nx * size * 0.45, base.y() - ny * size * 0.45)
        arrow = QPainterPath()
        arrow.moveTo(tip)
        arrow.lineTo(left)
        arrow.lineTo(right)
        arrow.closeSubpath()
        painter.drawPath(arrow)

    def paint(self, painter: QPainter, option, widget=None):
        color = COLOR_WIRE_SELECTED if self.isSelected() else COLOR_WIRE
        pen = QPen(color, 2.5 if self.isSelected() else 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())

        # -- Arrowheads --------------------------------------------------------
        a_to_b, b_to_a = self._directions()
        if not a_to_b and not b_to_a and not self.mappings:
            return

        points = self._all_points()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))

        if a_to_b or (not a_to_b and not b_to_a):
            tip = points[-1]
            prev = points[-2] if len(points) >= 2 else points[0]
            self._draw_arrow(painter, tip, QPointF(tip.x() - prev.x(), tip.y() - prev.y()), ARROW_SIZE)
        if b_to_a:
            tip = points[0]
            prev = points[1] if len(points) >= 2 else points[-1]
            self._draw_arrow(painter, tip, QPointF(tip.x() - prev.x(), tip.y() - prev.y()), ARROW_SIZE)

    # -- Deletion -----------------------------------------------------------

    def remove(self):
        if self.node_a and self in self.node_a.wires:
            self.node_a.wires.remove(self)
        if self.node_b and self in self.node_b.wires:
            self.node_b.wires.remove(self)
        if self.scene():
            self.scene().removeItem(self)


class _DragWireItem(QGraphicsPathItem):
    """Ghost wire shown while dragging from a node."""

    def __init__(self, start: QPointF):
        super().__init__()
        self._start = start
        pen = QPen(COLOR_WIRE_DRAGGING, 2.0, Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(10)

    def update_destination(self, end: QPointF):
        path = QPainterPath(self._start)
        path.lineTo(end)
        self.setPath(path)


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

        # Enforce single selection by validating after selection changes
        self.selectionChanged.connect(self._enforce_single_selection)

    def _enforce_single_selection(self):
        """Ensure only ONE item is selected at a time.

        This prevents Ctrl+Click multi-selection which is not supported
        in this application's single-selection-only workflow.
        """
        selected = self.selectedItems()
        if len(selected) > 1:
            # Keep only the first selected item
            self.clearSelection()
            if selected:
                selected[0].setSelected(True)

    # -- Public API ----------------------------------------------------------

    def add_node(self, fmu_path: Path, x: float = 0, y: float = 0) -> Optional[NodeItem]:
        from pathlib import Path as PathlibPath
        fmu_path = PathlibPath(fmu_path)
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
        # Ignore Ctrl+Click completely
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            node = self._node_at(event.scenePos())
            if node:
                local_pos = node.mapFromScene(event.scenePos())
                if local_pos.y() >= NODE_TITLE_HEIGHT:
                    # Clicked on the node body → start wire creation
                    self._drag_start_node = node
                    start = node.edge_point(event.scenePos())
                    self._drag_wire = _DragWireItem(start)
                    self.addItem(self._drag_wire)
                    # Select ONLY the source node (ensure single selection)
                    self.clearSelection()
                    node.setSelected(True)
                    event.accept()
                    return
                # Clicked on the title bar → normal move / select (handled by super)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        # Ignore Ctrl+Move completely
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.accept()
            return

        if self._drag_wire:
            self._drag_wire.update_destination(event.scenePos())
            # Highlight target node
            node = self._node_at(event.scenePos())
            if node is self._drag_start_node:
                node = None
            if node is not self._drag_target_node:
                if self._drag_target_node:
                    self._drag_target_node.setZValue(1)  # reset
                self._drag_target_node = node
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        # Ignore Ctrl+Release completely
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


class NodeGraphView(QGraphicsView):
    """Graph view with grid, wheel zoom, and middle-button pan."""

    def __init__(self, scene: NodeGraphScene, parent=None):
        super().__init__(scene, parent)
        self._scene = scene

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setAcceptDrops(True)

        self._zoom = 1.0
        self._pan_active = False
        self._pan_start = QPointF()

        # Zoom limits: smallest node (height=64) should remain >= 10 px
        node_min_dim = NODE_TITLE_HEIGHT + NODE_PORT_SPACING + 10  # 64
        self._zoom_min = 10.0 / node_min_dim   # ≈ 0.156
        self._zoom_max = 5.0

    # -- Grid ----------------------------------------------------------------

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)

        left = int(math.floor(rect.left()))
        right = int(math.ceil(rect.right()))
        top = int(math.floor(rect.top()))
        bottom = int(math.ceil(rect.bottom()))

        first_left = left - (left % GRID_SIZE)
        first_top = top - (top % GRID_SIZE)

        # Thin lines
        lines_light = []
        for x in range(first_left, right, GRID_SIZE):
            lines_light.append(QLineF(x, top, x, bottom))
        for y in range(first_top, bottom, GRID_SIZE):
            lines_light.append(QLineF(left, y, right, y))
        painter.setPen(QPen(COLOR_GRID_LIGHT, 0.5))
        painter.drawLines(lines_light)

        # Thick lines
        big = GRID_SIZE * GRID_SQUARES
        first_left_big = left - (left % big)
        first_top_big = top - (top % big)
        lines_dark = []
        for x in range(first_left_big, right, big):
            lines_dark.append(QLineF(x, top, x, bottom))
        for y in range(first_top_big, bottom, big):
            lines_dark.append(QLineF(left, y, right, y))
        painter.setPen(QPen(COLOR_GRID_DARK, 1.0))
        painter.drawLines(lines_dark)

    # -- Mouse wheel zoom ----------------------------------------------------------

    def wheelEvent(self, event):
        factor = 1.15
        if event.angleDelta().y() > 0:
            new_zoom = self._zoom * factor
            if new_zoom > self._zoom_max:
                return
            self._zoom = new_zoom
            self.scale(factor, factor)
        else:
            new_zoom = self._zoom / factor
            if new_zoom < self._zoom_min:
                return
            self._zoom = new_zoom
            self.scale(1 / factor, 1 / factor)

    # -- Pan (middle button or Alt+click) ---------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            self._pan_active = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_active:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton) and self._pan_active:
            self._pan_active = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- Keyboard ---------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._scene.remove_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- Drag and drop .fmu files --------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".fmu"):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                path_obj = Path(path)
                if path_obj.suffix.lower() == ".fmu":
                    scene_pos = self.mapToScene(event.position().toPoint())
                    self._scene.add_node(fmu_path=path_obj, x=scene_pos.x(), y=scene_pos.y())
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # -- Context menu -------------------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        scene_pos = self.mapToScene(event.pos())

        add_fmu_action = menu.addAction("Add FMU…")
        delete_action = None
        simulate_action = None
        fmueditor_action = None
        fmutool_action = None

        selected_items = self._scene.selectedItems()
        if selected_items:
            delete_action = menu.addAction("Delete Selection")
            # Check if a single NodeItem is selected for external tools
            if len(selected_items) == 1 and isinstance(selected_items[0], NodeItem):
                menu.addSeparator()
                fmueditor_action = menu.addAction("Open in FMU Editor")
                fmutool_action = menu.addAction("Open in FMU Tool")
                if FMPY_AVAILABLE:
                    simulate_action = menu.addAction("Simulate (with FMPy)")

        menu.addSeparator()
        fit_action = menu.addAction("Fit View")

        chosen = menu.exec(event.globalPos())
        if chosen == add_fmu_action:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Select FMU files", "", "FMU (*.fmu)"
            )
            for path in paths:
                self._scene.add_node(fmu_path=Path(path), x=scene_pos.x(), y=scene_pos.y())
                scene_pos += QPointF(20, 20)  # offset subsequent nodes
        elif chosen == delete_action:
            self._scene.remove_selected()
        elif chosen == simulate_action:
            self._launch_fmpy_simulation(selected_items[0])
        elif chosen == fmueditor_action:
            self._launch_tool_window(selected_items[0], FMUEditorMainWindow)
        elif chosen == fmutool_action:
            self._launch_tool_window(selected_items[0], FMUToolMainWindow)
        elif chosen == fit_action:
            self.fit_all()

    def fit_all(self):
        rect = self._scene.itemsBoundingRect()
        if not rect.isNull():
            rect.adjust(-40, -40, 40, 40)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _launch_fmpy_simulation(self, node: NodeItem):
        """Launch FMPy GUI with the selected FMU."""
        if not FMPY_AVAILABLE:
            return
        try:
            fmu_path = str(node.fmu_path.resolve())
            window = FMPyMainWindow()
            window.show()
            window.load(fmu_path)
            self._keep_window_ref(window)
        except Exception as e:
            QMessageBox.critical(
                self,
                "FMPy Simulation Error",
                f"Failed to launch FMPy simulation:\n{str(e)}"
            )

    def _launch_tool_window(self, node: NodeItem, window_class):
        """Launch an internal tool window (FMU Editor or FMU Tool) with the selected FMU."""
        try:
            fmu_path = str(node.fmu_path.resolve())
            window = window_class()
            window.load(fmu_path)
            self._keep_window_ref(window)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open tool:\n{str(e)}"
            )

    def _keep_window_ref(self, window):
        """Keep a reference to prevent garbage collection."""
        if not hasattr(self, '_tool_windows'):
            self._tool_windows = []
        self._tool_windows.append(window)


class NodeGraphWidget(QWidget):
    """Reusable widget containing the mini editor (scene + view).

    Public attributes:
        scene  : NodeGraphScene   - programmatic access to nodes and wires.
        view   : NodeGraphView    - view control.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.scene = NodeGraphScene()
        self.scene.setSceneRect(-2000, -2000, 4000, 4000)

        self.view = NodeGraphView(self.scene)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    # -- API shortcuts --------------------------------------------------------

    def add_node(
        self,
        x: float = 0,
        y: float = 0,
        fmu_path: Path = Path(""),
    ) -> Optional[NodeItem]:
        return self.scene.add_node(fmu_path, x, y)

    def add_wire(self, node_a: NodeItem, node_b: NodeItem) -> Optional[WireItem]:
        return self.scene.add_wire(node_a, node_b)

    def clear(self):
        self.scene.clear_all()

