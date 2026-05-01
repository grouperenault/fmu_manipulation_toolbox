import json
import logging
import math
import sys
import uuid
import tempfile

from pathlib import Path
from typing import *

from PySide6.QtCore import Qt, QRectF, QPointF, QLineF, Signal, QItemSelectionModel, QSize, QSortFilterProxyModel, QModelIndex
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QPainterPathStroker, QFont,
    QFontMetrics, QKeyEvent, QIcon,
    QStandardItemModel, QStandardItem
)
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsPathItem,
    QGraphicsEllipseItem,
    QMenu, QInputDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QGraphicsSceneMouseEvent, QStyleOptionGraphicsItem,
    QTreeView, QSplitter,
    QStackedWidget, QTableView, QLabel, QHeaderView,
    QFileDialog, QMainWindow, QPushButton, QComboBox, QCheckBox,
    QStyledItemDelegate, QAbstractItemView,
    QWidgetAction, QRadioButton, QButtonGroup, QFrame, QMessageBox,
    QTabWidget, QLineEdit, QListWidget, QListWidgetItem, QDialog
)

from fmu_manipulation_toolbox.gui.helper import Application, RunTask
from fmu_manipulation_toolbox.gui.style import placeholder_color
from fmu_manipulation_toolbox.assembly import Assembly, AssemblyNode, AssemblyError
from fmu_manipulation_toolbox.operations import FMU, FMUPort, OperationAbstract
from fmu_manipulation_toolbox.container import FMUContainerError
from fmu_manipulation_toolbox.split import FMUSplitter, FMUSplitterError
from fmu_manipulation_toolbox.help import Help

logger = logging.getLogger("fmu_manipulation_toolbox")
tree_logger = logging.getLogger("fmu_manipulation_toolbox.gui.tree")

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
            self._wire._on_handle_moved(self._index, value)
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

    def _on_handle_moved(self, index: int, new_pos: QPointF):
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
            tree_logger.warning(f"Multi-selection detected ({len(selected)} items), correcting to single selection")
            # Keep only the first selected item
            self.clearSelection()
            if selected:
                selected[0].setSelected(True)
                tree_logger.debug(f"Single selection enforced: {selected[0]}")
        elif len(selected) == 1:
            # Single selection is okay, just log for debugging
            if isinstance(selected[0], (NodeItem, WireItem)):
                item_type = "Node" if isinstance(selected[0], NodeItem) else "Wire"
                tree_logger.debug(f"Scene selection: 1 {item_type}")

    # -- Public API ----------------------------------------------------------

    def add_node(self, fmu_path: Union[Path, str], x: float = 0, y: float = 0) -> Optional[NodeItem]:
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
                    tree_logger.debug(f"Dragging from node: {node.title}")
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
        if self._scene.selectedItems():
            delete_action = menu.addAction("Delete Selection")
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
        elif chosen == fit_action:
            self.fit_all()

    def fit_all(self):
        rect = self._scene.itemsBoundingRect()
        if not rect.isNull():
            rect.adjust(-40, -40, 40, 40)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)


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
        fmu_path: str = "",
    ) -> Optional[NodeItem]:
        return self.scene.add_node(fmu_path, x, y)

    def add_wire(self, node_a: NodeItem, node_b: NodeItem) -> Optional[WireItem]:
        return self.scene.add_wire(node_a, node_b)

    def clear(self):
        self.scene.clear_all()


class _NodeTreeModel(QStandardItemModel):
    """Model that only allows drop on "Container" items."""
    # Custom data roles stored on column 0 items
    ROLE_CONTAINER_PARAMETERS = Qt.ItemDataRole.UserRole + 1
    ROLE_NODE_UID = Qt.ItemDataRole.UserRole + 2
    ROLE_IS_ROOT = Qt.ItemDataRole.UserRole + 3

    def canDropMimeData(self, data, action, row, column, parent):
        if not parent.isValid():
            return False                        # not at invisible root level
        item = self.itemFromIndex(parent)
        if item is None or not item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS):
            return False                        # only on a Container
        return super().canDropMimeData(data, action, row, column, parent)


class TreeItemRoles:
    """Centralizes tree item roles and provides type-safe accessors.

    This class provides:
    • Centralized role constants
    • Type-safe getters for item data
    • Reduced risk of typos and inconsistencies
    """

    CONTAINER_PARAMETERS = _NodeTreeModel.ROLE_CONTAINER_PARAMETERS
    NODE_UID = _NodeTreeModel.ROLE_NODE_UID
    IS_ROOT = _NodeTreeModel.ROLE_IS_ROOT

    @staticmethod
    def get_container_params(item: Optional[QStandardItem]) -> Optional["ContainerParameters"]:
        """Get ContainerParameters from item (type-safe)."""
        if item is None:
            return None
        return item.data(TreeItemRoles.CONTAINER_PARAMETERS)

    @staticmethod
    def get_node_uid(item: Optional[QStandardItem]) -> Optional[str]:
        """Get NODE_UID from item (type-safe)."""
        if item is None:
            return None
        return item.data(TreeItemRoles.NODE_UID)

    @staticmethod
    def is_root(item: Optional[QStandardItem]) -> bool:
        """Check if item is a root node (type-safe)."""
        if item is None:
            return False
        return bool(item.data(TreeItemRoles.IS_ROOT))

    @staticmethod
    def is_container(item: Optional[QStandardItem]) -> bool:
        """Check if item is a container (type-safe)."""
        return TreeItemRoles.get_container_params(item) is not None

    @staticmethod
    def is_fmu_node(item: Optional[QStandardItem]) -> bool:
        """Check if item is an FMU node (type-safe)."""
        return (
            TreeItemRoles.get_node_uid(item) is not None
            and TreeItemRoles.get_container_params(item) is None
        )


class SelectionSynchronizer:
    """Context manager for safe cross-widget selection synchronization.

    Prevents circular updates when synchronizing selection between
    scene and tree views by temporarily blocking signals.

    Usage:
    ```
    with SelectionSynchronizer(tree, scene):
        tree.setCurrentIndex(index)  # Won't trigger scene selection
    ```
    """

    def __init__(self, tree_view: QTreeView, scene: QGraphicsScene):
        self._tree_view = tree_view
        self._scene = scene
        self._tree_signals_blocked = False
        self._scene_signals_blocked = False

    def __enter__(self) -> "SelectionSynchronizer":
        """Block signals at entry."""
        self._tree_signals_blocked = self._tree_view.selectionModel().blockSignals(True)
        self._scene_signals_blocked = self._scene.blockSignals(True)
        tree_logger.debug("Selection synchronizer entered - signals blocked")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Restore signals at exit."""
        self._tree_view.selectionModel().blockSignals(self._tree_signals_blocked)
        self._scene.blockSignals(self._scene_signals_blocked)
        tree_logger.debug("Selection synchronizer exited - signals restored")
        return False


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

        # Dialog styling is now provided by gui_style from style.py


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
            # Keep the current value if dialog was cancelled
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

    def set_nodes(self, from_node: NodeItem, to_node: NodeItem):
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

    def set_wire(self, wire: WireItem):
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

    def set_node(self, node: NodeItem):
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


class NodeTreeWidget(QWidget):
    """Manages the tree view and synchronization with the scene.

    Responsibilities:
    • QTreeView display and interaction
    • Scene ↔ tree synchronization
    • Context menu for add/delete/rename
    • Drag-and-drop hierarchy management
    • Icon management and item builders

    Signals:
    • container_changed(ContainerParameters) - emitted when a container item is edited
    """

    container_changed = Signal(object)  # Emits ContainerParameters

    def __init__(self, graph_widget: NodeGraphWidget, parent=None):
        super().__init__(parent)
        self._graph = graph_widget
        self._pending_parent: Optional[QStandardItem] = None
        resources_dir = Path(__file__).resolve().parent.parent / "resources"
        self._icon_container = QIcon(str(resources_dir / "container.png"))
        self._icon_fmu = QIcon(str(resources_dir / "icon_fmu.png"))

        # ── Model ────────────────────────────────────────────────────────
        self._model = _NodeTreeModel()
        self._model.setHorizontalHeaderLabels(["Name"])

        root_item = self._make_container_item("container.fmu", is_root=True)
        self._model.appendRow(root_item)
        self._root: QStandardItem = root_item

        # ── View ───────────────────────────────────────────────────────────
        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        self._tree.setDragDropMode(QTreeView.DragDropMode.InternalMove)
        self._tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.setIconSize(QSize(30, 30))
        self._tree.setUniformRowHeights(True)
        self._tree.expandAll()

        # Enforce .fmu extension when a container is renamed in-place
        self._model.itemChanged.connect(self._on_item_changed)

        # ── Scene -> tree connections ──────────────────────────────────────
        self._synchronizer = SelectionSynchronizer(self._tree, self._graph.scene)
        self._graph.scene.node_added.connect(self._on_scene_node_added)
        self._graph.scene.node_removed.connect(self._on_scene_node_removed)
        self._graph.scene.selectionChanged.connect(self._on_scene_selection_changed)
        self._tree.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
        tree_logger.debug("NodeTreeWidget initialized")

        # ── Layout ──────────────────────────────────────────────────
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._tree)

    # ── Public API ──────────────────────────────────────────────────

    @property
    def model(self) -> '_NodeTreeModel':
        return self._model

    @property
    def root(self) -> QStandardItem:
        return self._root

    @property
    def tree_view(self) -> QTreeView:
        return self._tree

    @property
    def pending_parent(self) -> Optional[QStandardItem]:
        return self._pending_parent

    @pending_parent.setter
    def pending_parent(self, value: Optional[QStandardItem]):
        self._pending_parent = value

    def make_container_item(self, name: str, is_root: bool = False) -> QStandardItem:
        return self._make_container_item(name, is_root)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _ensure_fmu_ext(name: str) -> str:
        """Ensure *name* ends with '.fmu'."""
        if not name.lower().endswith(".fmu"):
            return name + ".fmu"
        return name

    # ── Row builders ──────────────────────────────────────────────────

    def _make_container_item(self, name: str, is_root: bool = False) -> QStandardItem:
        item = QStandardItem(name)
        item.setIcon(self._icon_container)
        item.setToolTip("Container")
        item.setData(ContainerParameters(name), _NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
        item.setData(is_root, _NodeTreeModel.ROLE_IS_ROOT)
        item.setEditable(True)
        item.setDropEnabled(True)
        item.setDragEnabled(not is_root)
        return item

    def _make_node_item(self, node: NodeItem) -> QStandardItem:
        item = QStandardItem(node.title)
        item.setIcon(self._icon_fmu)
        item.setToolTip("FMU")
        item.setData(None, _NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
        item.setData(node.uid, _NodeTreeModel.ROLE_NODE_UID)
        item.setEditable(False)
        item.setDropEnabled(False)
        item.setDragEnabled(True)
        return item

    # ── Item changed event ───────────────────────────────────────────

    def _on_item_changed(self, item: QStandardItem):
        """Called when an item is edited in-place (e.g. double-click rename)."""
        container_parameters = TreeItemRoles.get_container_params(item)
        if not container_parameters:
            return

        fixed = self._ensure_fmu_ext(item.text().strip())
        if fixed != item.text():
            # Block signals to avoid recursion
            self._model.blockSignals(True)
            item.setText(fixed)
            self._model.blockSignals(False)

        # Keep data model in sync with the visible name.
        container_parameters.name = fixed
        tree_logger.debug(f"Container renamed: {fixed}")

        # Signal that container has been changed
        self.container_changed.emit(container_parameters)

    # ── Scene -> tree synchronization ────────────────────────────────────────

    def _select_tree_item(self, item: QStandardItem):
        """Select *item* in the tree view and scroll to it."""
        idx = self._model.indexFromItem(item)
        sel = self._tree.selectionModel()
        sel.clearSelection()
        sel.select(
            idx,
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        self._tree.scrollTo(idx)

    def _on_scene_node_added(self, node: NodeItem):
        target = self._pending_parent or self._root
        node_item = self._make_node_item(node)
        target.appendRow(node_item)
        self._tree.expandAll()
        self._select_tree_item(node_item)

    def _on_scene_node_removed(self, node: NodeItem):
        self._remove_uid_from(self._model.invisibleRootItem(), node.uid)

    def _remove_uid_from(self, parent: QStandardItem, uid: str) -> bool:
        for r in range(parent.rowCount()):
            child = parent.child(r, 0)
            if child is None:
                continue
            if not child.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS) and child.data(_NodeTreeModel.ROLE_NODE_UID) == uid:
                parent.removeRow(r)
                return True
            if child.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS) and self._remove_uid_from(child, uid):
                return True
        return False

    def _find_tree_item_by_uid(self, parent: QStandardItem, uid: str) -> Optional[QStandardItem]:
        """Recursively find a Node item by UID."""
        for r in range(parent.rowCount()):
            child = parent.child(r, 0)
            if child is None:
                continue
            if not child.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS) and child.data(_NodeTreeModel.ROLE_NODE_UID) == uid:
                return child
            if child.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS):
                found = self._find_tree_item_by_uid(child, uid)
                if found is not None:
                    return found
        return None

    # ── Selection synchronization ──────────────────────────────────

    def _on_scene_selection_changed(self):
        """Scene -> tree: select in tree when node is selected in graph.
        
        Only sync NodeItems to tree. WireItems are not represented in tree,
        so tree selection is cleared when only a Wire is selected.
        """
        # Suppress scene signals while modifying tree (but allow tree signals to process normally)
        try:
            scene = self._graph.scene
            scene.blockSignals(True)
            
            try:
                selected = scene.selectedItems()
            except RuntimeError:
                # C++ scene already deleted
                scene.blockSignals(False)
                return
            
            # Find if a NodeItem is selected
            tree_node_found = False
            node_to_select = None
            for scene_item in selected:
                if isinstance(scene_item, NodeItem):
                    tree_item = self._find_tree_item_by_uid(
                        self._model.invisibleRootItem(), scene_item.uid
                    )
                    if tree_item is not None:
                        node_to_select = tree_item
                        tree_node_found = True
                        break  # Only one node can be selected
            
            # Allow scene signals again before updating tree
            scene.blockSignals(False)
            
            # Now update tree with normal signal processing
            sel = self._tree.selectionModel()
            sel.clearSelection()
            
            if tree_node_found and node_to_select is not None:
                idx = self._model.indexFromItem(node_to_select)
                self._tree.setCurrentIndex(idx)
                self._tree.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)
                tree_logger.debug(f"Tree item highlighted from scene (NodeItem: {node_to_select.text()})")
            else:
                if selected:
                    # There are items but not NodeItems (likely a WireItem)
                    tree_logger.debug(f"Scene selection is WireItem, tree selection cleared")
                else:
                    # No items selected in scene
                    tree_logger.debug("Scene selection cleared")
                    
        except Exception as e:
            tree_logger.error(f"Error during scene selection sync: {e}")

    def _on_tree_selection_changed(self, _selected, _deselected):
        """Tree -> scene: select in graph when node is selected in tree.
        Highlights first-level FMU nodes of the selected container.
        
        NOTE: Tree uses SingleSelection mode, so only one item can be selected.
        """
        with self._synchronizer:
            try:
                self._graph.scene.clearSelection()
            except RuntimeError:
                return

            # First, remove highlight from all nodes
            for node in self._graph.scene.nodes():
                node.set_title_highlighted(False)

            selected_rows = list(self._tree.selectionModel().selectedRows(0))
            
            # Validate single selection (should always be ≤1 due to SingleSelection mode)
            if len(selected_rows) > 1:
                tree_logger.warning(f"Multiple tree selections detected ({len(selected_rows)}), expected max 1")
                return
            
            if not selected_rows:
                tree_logger.debug("Tree selection cleared")
                return
            
            # Process the single selected item
            index = selected_rows[0]
            item = self._model.itemFromIndex(index)
            if item is None:
                return

            # Check if container
            container_parameters = TreeItemRoles.get_container_params(item)
            if container_parameters is not None:
                tree_logger.debug(f"Container selected in tree: {container_parameters.name}")
                # Container selected: highlight immediate FMU child nodes
                for r in range(item.rowCount()):
                    child = item.child(r, 0)
                    if child is not None and TreeItemRoles.is_fmu_node(child):
                        uid = TreeItemRoles.get_node_uid(child)
                        if uid:
                            for node in self._graph.scene.nodes():
                                if node.uid == uid:
                                    node.set_title_highlighted(True)
                return

            # Check if FMU node
            uid = TreeItemRoles.get_node_uid(item)
            if uid:
                tree_logger.debug(f"FMU node selected in tree: {uid}")
                try:
                    scene_nodes = self._graph.scene.nodes()
                except RuntimeError:
                    return
                for node in scene_nodes:
                    if node.uid == uid:
                        node.setSelected(True)
                        return

    # ── Context menu ──────────────────────────────────────────────────

    def _on_context_menu(self, pos):
        index = self._tree.indexAt(pos)
        target, item = self._resolve_target(index)

        menu = QMenu(self)
        act_add_fmu = menu.addAction("Add FMU…")
        act_add_ctn = menu.addAction("Add Container")

        act_rename = act_delete = None
        if item is not None:
            menu.addSeparator()
            if item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS):
                act_rename = menu.addAction("Rename")
            if item is not self._root:
                act_delete = menu.addAction("Delete")

        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen is act_add_fmu:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Select FMU files", "", "FMU (*.fmu)"
            )
            center = self._graph.view.mapToScene(
                self._graph.view.viewport().rect().center()
            )
            self._pending_parent = target
            for i, path in enumerate(paths):
                self._graph.add_node(center.x() + i * 20, center.y() + i * 20, path)
            self._pending_parent = None

        elif chosen is act_add_ctn:
            name, ok = QInputDialog.getText(self, "New Container", "Name:")
            if ok and name.strip():
                ctn_item = self._make_container_item(self._ensure_fmu_ext(name.strip()))
                target.appendRow(ctn_item)
                self._tree.expandAll()
                self._select_tree_item(ctn_item)

        elif chosen is act_rename and item is not None:
            new, ok = QInputDialog.getText(
                self, "Rename", "Name:", text=item.text()
            )
            if ok and new.strip():
                item.setText(self._ensure_fmu_ext(new.strip()))

        elif chosen is act_delete and item is not None:
            self._delete_item(item)

    def _resolve_target(self, index):
        """Return *(target_container, clicked_item)* or *(root, None)*."""
        if not index.isValid():
            return self._root, None
        item = self._model.itemFromIndex(index)
        if item is None:
            return self._root, None
        if item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS):
            return item, item
        return (item.parent() or self._root), item

    # ── Deletion ──────────────────────────────────────────────────────

    def _delete_item(self, item: QStandardItem):
        """Delete a node or container (+ all its content) from tree and scene."""
        if item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS):
            self._purge_container(item)
        else:
            self._remove_scene_node(item.data(_NodeTreeModel.ROLE_NODE_UID))
        parent = item.parent() or self._model.invisibleRootItem()
        parent.removeRow(item.row())

    def _purge_container(self, ctn: QStandardItem):
        """Recursively delete scene nodes contained in *ctn*."""
        for r in range(ctn.rowCount() - 1, -1, -1):
            child = ctn.child(r, 0)
            if child is None:
                continue
            if child.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS):
                self._purge_container(child)
            else:
                self._remove_scene_node(child.data(_NodeTreeModel.ROLE_NODE_UID))

    def _remove_scene_node(self, uid: Optional[str]):
        """Remove the matching node from the graphics scene."""
        if uid is None:
            return
        for node in self._graph.scene.nodes():
            if node.uid == uid:
                node.remove_wires()
                self._graph.scene.removeItem(node)
                return


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

    def show_wire(self, wire: WireItem):
        """Show wire detail panel."""
        self._wire_detail.set_wire(wire)
        self._stack.setCurrentWidget(self._wire_detail)

    def show_fmu(self, node: NodeItem):
        """Show FMU detail panel."""
        self._fmu_detail.set_node(node)
        self._stack.setCurrentWidget(self._fmu_detail)

    def show_container(self, container_parameters: ContainerParameters):
        """Show container detail panel."""
        self._container_detail.set_container(container_parameters)
        self._stack.setCurrentWidget(self._container_detail)


class NodeTreePanel(QWidget):
    """Side panel showing nodes as a hierarchical tree.

    Combines NodeTreeWidget and DetailPanelStack to provide a complete
    tree-based interface for managing the FMU container structure.

    • Single column with icon (Container / FMU) and name.
    • First level contains a root container (*Project*).
    • Right-click -> add node, add container, rename, delete.
    • Internal drag-and-drop to reorganize hierarchy.
    • Synchronized with scene: nodes added/removed in graph
      appear/disappear automatically in the tree.
    • Detail panels show information about selected items.
"""

    def __init__(self, graph_widget: NodeGraphWidget, parent=None):
        super().__init__(parent)
        self._graph = graph_widget

        # ── Create sub-components ───────────────────────────────────
        self._tree_widget = NodeTreeWidget(graph_widget)
        self._detail_panel = DetailPanelStack()

        # ── Connect tree widget to detail panel ──────────────────────
        self._graph.scene.selectionChanged.connect(self._on_scene_selection_changed)
        self._tree_widget.tree_view.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
        self._tree_widget.container_changed.connect(self._on_container_changed)

        # ── Layout ──────────────────────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(self._tree_widget)
        self._splitter.addWidget(self._detail_panel)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([250, 250])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._splitter)

    # ── Helpers ────────────────────────────────────────────────────

    @property
    def model(self) -> '_NodeTreeModel':
        return self._tree_widget.model

    @property
    def root(self) -> QStandardItem:
        return self._tree_widget.root

    @property
    def tree_view(self) -> QTreeView:
        return self._tree_widget.tree_view

    @property
    def wire_detail(self) -> WireDetailWidget:
        return self._detail_panel.wire_detail

    @property
    def fmu_detail(self) -> FMUDetailWidget:
        return self._detail_panel.fmu_detail

    @property
    def container_detail(self) -> ContainerDetailWidget:
        return self._detail_panel.container_detail

    @property
    def pending_parent(self) -> Optional[QStandardItem]:
        return self._tree_widget.pending_parent

    @pending_parent.setter
    def pending_parent(self, value: Optional[QStandardItem]):
        self._tree_widget.pending_parent = value

    def make_container_item(self, name: str, is_root: bool = False) -> QStandardItem:
        return self._tree_widget.make_container_item(name, is_root)

    # ── Selection synchronization ──────────────────────────────────

    def _on_scene_selection_changed(self):
        """Scene -> tree: select in tree when node is selected in graph.
        Also updates the details panel.

        NOTE: Expected behavior is SINGLE selection only.
        """
        tree_logger.debug("Panel: scene selection changed event received")
        # Flush any pending edits from detail panels
        self._detail_panel.sync_edits()

        # Let the tree widget sync its selection
        self._tree_widget._on_scene_selection_changed()

        # Show appropriate detail panel
        try:
            selected = self._graph.scene.selectedItems()
        except RuntimeError:
            # C++ scene already deleted
            tree_logger.warning("Scene already deleted during selection change")
            self._detail_panel.show_empty()
            return

        # Validate single selection
        if len(selected) > 1:
            tree_logger.warning(f"Multiple scene selections detected ({len(selected)}), expected max 1")
            # This shouldn't happen as _enforce_single_selection() should correct it
            return

        if not selected:
            tree_logger.debug("Scene selection cleared")
            self._detail_panel.show_empty()
            return

        # Process the single selected item
        scene_item = selected[0]
        if isinstance(scene_item, NodeItem):
            tree_logger.debug(f"Scene selection: Node '{scene_item.title}'")
            self._detail_panel.show_fmu(scene_item)
            return
        elif isinstance(scene_item, WireItem):
            tree_logger.debug(f"Scene selection: Wire (between nodes)")
            self._detail_panel.show_wire(scene_item)
            return

        # Unknown selection type
        tree_logger.debug(f"Unknown selection type: {type(scene_item)}")
        self._detail_panel.show_empty()

    def _on_tree_selection_changed(self, _selected, _deselected):
        """Tree -> scene: select in graph when node is selected in tree.

        NOTE: Tree uses SingleSelection mode, so only one item can be selected.
        """
        tree_logger.debug("Panel: tree selection changed event received")
        # Let the tree widget sync its selection
        self._tree_widget._on_tree_selection_changed(_selected, _deselected)

        # Show appropriate detail panel
        try:
            selected_rows = list(self._tree_widget.tree_view.selectionModel().selectedRows(0))
        except RuntimeError as e:
            tree_logger.error(f"Error getting tree selection: {e}")
            self._detail_panel.show_empty()
            return

        # Validate single selection (should always be ≤1 due to SingleSelection mode)
        if len(selected_rows) > 1:
            tree_logger.warning(f"Multiple tree selections detected ({len(selected_rows)}), expected max 1")
            return

        if not selected_rows:
            tree_logger.debug("Tree selection cleared")
            self._detail_panel.show_empty()
            return

        # Process the single selected item
        index = selected_rows[0]
        item = self._tree_widget.model.itemFromIndex(index)
        if item is None:
            tree_logger.error("Tree item is None for selected index")
            self._detail_panel.show_empty()
            return

        container_parameters = TreeItemRoles.get_container_params(item)
        if container_parameters is not None:
            tree_logger.debug(f"Tree selection: Container '{container_parameters.name}'")
            self._detail_panel.show_container(container_parameters)
            return

        # Check if it's a node item
        uid = TreeItemRoles.get_node_uid(item)
        if uid:
            try:
                scene_nodes = self._graph.scene.nodes()
            except RuntimeError as e:
                tree_logger.error(f"Error getting scene nodes: {e}")
                return
            for node in scene_nodes:
                if node.uid == uid:
                    tree_logger.debug(f"Tree selection: FMU Node '{node.title}'")
                    self._detail_panel.show_fmu(node)
                    return

        # No matching item found
        tree_logger.warning(f"Tree item selected but no matching scene node found (uid={uid})")
        self._detail_panel.show_empty()

    def _on_container_changed(self, container_parameters: ContainerParameters):
        """Called when a container item is edited (e.g. renamed).
        Refresh the detail panel if this container is currently selected."""
        tree_logger.debug(f"Container changed event: {container_parameters.name}")
        try:
            current = self._tree_widget.tree_view.currentIndex()
            if current.isValid():
                item = self._tree_widget.model.itemFromIndex(current)
                if item and TreeItemRoles.get_container_params(item) is container_parameters:
                    tree_logger.debug(f"Refreshing detail panel for changed container: {container_parameters.name}")
                    self._detail_panel.show_container(container_parameters)
        except RuntimeError as e:
            tree_logger.error(f"Error refreshing container detail panel: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self._last_directory: Optional[Path] = None

        splitter = QSplitter()
        self._graph = NodeGraphWidget()
        self._tree = NodeTreePanel(self._graph)
        splitter.addWidget(self._graph)
        splitter.addWidget(self._tree)
        splitter.setSizes([600, 400])

        self._load_button = QPushButton("Load FMU Container")
        self._import_button = QPushButton("Import")
        self._export_button = QPushButton("Export as JSON")
        self._save_button = QPushButton("Save as FMU Container")
        self._exit_button = QPushButton("Exit")
        self._save_button.setProperty("class", "save")
        self._export_button.setProperty("class", "save")
        self._load_button.setProperty("class", "quit")
        self._import_button.setProperty("class", "quit")
        self._exit_button.setProperty("class", "quit")

        btn_width = max(
            self._load_button.sizeHint().width(),
            self._import_button.sizeHint().width(),
            self._export_button.sizeHint().width(),
            self._save_button.sizeHint().width(),
            self._exit_button.sizeHint().width(),
            150,
        )
        for button in (
            self._load_button,
            self._import_button,
            self._export_button,
            self._save_button,
            self._exit_button,
        ):
            button.setMinimumWidth(btn_width)

        self._load_button.clicked.connect(self._on_load_clicked)
        self._import_button.clicked.connect(self._on_import_clicked)
        self._export_button.clicked.connect(self._on_export_clicked)
        self._save_button.clicked.connect(self._on_save_clicked)
        self._exit_button.clicked.connect(self.close)

        # Debug checkbox
        self._debug_checkbox = QCheckBox("Verbose Mode")
        self._debug_checkbox.setToolTip("Keep intermediate build artifacts and enable verbose logging")

        # Datalog checkbox
        self._datalog_checkbox = QCheckBox("Enable Datalog")
        self._datalog_checkbox.setToolTip("Generate datalog.txt in the FMU resources")

        # FMI version radio buttons
        self._fmi2_radio = QRadioButton("Generate FMI-2")
        self._fmi3_radio = QRadioButton("Generate FMI-3")
        self._fmi2_radio.setChecked(True)

        self._fmi_group = QButtonGroup(self)
        self._fmi_group.addButton(self._fmi2_radio, 2)
        self._fmi_group.addButton(self._fmi3_radio, 3)

        # "Configuration" popup menu grouping FMI version + debug
        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)
        config_layout.setContentsMargins(8, 4, 8, 4)
        config_layout.addWidget(self._fmi2_radio)
        config_layout.addWidget(self._fmi3_radio)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        config_layout.addWidget(separator)
        config_layout.addWidget(self._debug_checkbox)
        config_layout.addWidget(self._datalog_checkbox)

        config_action = QWidgetAction(self)
        config_action.setDefaultWidget(config_widget)

        config_menu = QMenu(self)
        config_menu.addAction(config_action)

        self._config_button = QPushButton("Configuration")
        self._config_button.setProperty("class", "quit")
        self._config_button.setMinimumWidth(btn_width)
        self._config_button.setMenu(config_menu)

        button_bar = QHBoxLayout()
        button_bar.addWidget(self._config_button)
        button_bar.addStretch(1)
        button_bar.addWidget(self._load_button)
        button_bar.addWidget(self._import_button)
        button_bar.addWidget(self._exit_button)
        button_bar.addWidget(self._export_button)
        button_bar.addWidget(self._save_button)


        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.addWidget(splitter, 1)
        main_layout.addLayout(button_bar)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        self.setWindowTitle("FMU Container Builder")
        self.resize(1600, 900)

        self._dirty = False
        self._graph.scene.node_added.connect(self._on_node_added_update_dir)
        self._graph.scene.node_added.connect(lambda _: self._mark_dirty())
        self._graph.scene.node_removed.connect(lambda _: self._mark_dirty())
        self._graph.scene.wire_added.connect(lambda _: self._mark_dirty())
        self._graph.scene.wire_removed.connect(lambda _: self._mark_dirty())

        # Detail panels edits
        self._tree.wire_detail.changed.connect(self._mark_dirty)
        self._tree.fmu_detail.changed.connect(self._mark_dirty)
        self._tree.container_detail.changed.connect(self._mark_dirty)

        # Tree model structural changes (drag-drop, rename, add/remove rows)
        self._tree.model.dataChanged.connect(lambda *_: self._mark_dirty())
        self._tree.model.rowsInserted.connect(lambda *_: self._mark_dirty())
        self._tree.model.rowsRemoved.connect(lambda *_: self._mark_dirty())
        self._tree.model.rowsMoved.connect(lambda *_: self._mark_dirty())

        self.show()

    def _mark_dirty(self):
        self._dirty = True

    def _on_node_added_update_dir(self, node: NodeItem):
        """Track the directory of the last FMU added to the scene."""
        if node.fmu_path and node.fmu_path.parent.exists():
            self._last_directory = node.fmu_path.parent

    def _data_to_items(self, parent, data_node, folder, links_list: List[List[str]], start_values_list: List[List[str]], output_ports_list: List[List[str]], x=0, y=0):
        self._tree.pending_parent = parent
        for fmu in data_node["fmu"]:
            logger.debug(f"ADD FMU: {fmu}")
            self._graph.add_node(fmu_path=folder / fmu, x=x, y=y)
            x = x + 100
            y = y + 100
        self._tree.pending_parent = None


        container_name = data_node["name"]
        container_parameters = ContainerParameters(**data_node)
        logger.debug(f"SET CONTAINER: {container_name}: {container_parameters}")
        parent.setData(container_parameters, _NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
        parent.setText(container_name)

        if "link" in data_node:
            for link in data_node["link"]:
                logger.debug(f"ADD LINK: {link}")
                links_list.append(link)

        if "start" in data_node:
            for start in data_node["start"]:
                logger.debug(f"ADD START VALUE: {start}")
                start_values_list.append(start)

        if "output" in data_node:
            for output in data_node["output"]:
                # output format: [fmu_name, port_name, exposed_name]
                logger.debug(f"ADD OUTPUT PORT: {output}")
                output_ports_list.append(output)

        if "container" in data_node:
            for container_fmu in data_node["container"]:
                logger.debug(f"ADD CONTAINER: {container_fmu['name']}")
                child = self._tree.make_container_item(container_fmu["name"])
                parent.appendRow(child)
                self._data_to_items(child, container_fmu, folder, links_list, start_values_list, output_ports_list, x=x, y=y)

        for link in links_list:
            if link[2] == container_name:
                for input_container in data_node["input"]:
                    if link[3] == input_container[0]:
                        link[2] = input_container[1]
                        link[3] = input_container[2]
                        break

        for link in links_list:
            if link[0] == container_name:
                for output_container in data_node["output"]:
                    if link[1] == output_container[2]:
                        link[0] = output_container[0]
                        link[1] = output_container[1]
                        break

    def _import_data(self, data: dict, fmu_directory: Path):
        """Populate the scene and tree from a JSON-style dict.

        Shared by *load_container_fmu* (from a split FMU) and
        *import_assembly_file* (from a raw JSON / CSV).
        """
        # Clear existing scene and tree
        self._graph.scene.clear_all()
        self._tree.root.removeRows(0, self._tree.root.rowCount())

        links_list: List[List[str]] = []
        start_values_list: List[List[str]] = []
        output_ports_list: List[List[str]] = []
        self._data_to_items(self._tree.root, data, fmu_directory,
                            links_list, start_values_list, output_ports_list)

        # Build a map from FMU filename to its NodeItem
        nodes_by_name: Dict[str, NodeItem] = {}
        for node in self._graph.scene.nodes():
            nodes_by_name[node.fmu_path.name] = node

        # Group links by (source_fmu, dest_fmu) pair to create one wire per pair
        # A wire between two nodes can carry mappings in both directions.
        wire_key_mappings: Dict[Tuple[str, str], List[Tuple[str, str, str, str]]] = {}
        for link in links_list:
            fmu_from, port_from, fmu_to, port_to = link[0], link[1], link[2], link[3]
            # Canonical key: sorted pair so A→B and B→A end up on the same wire
            key = tuple(sorted([fmu_from, fmu_to]))
            wire_key_mappings.setdefault(key, []).append((fmu_from, port_from, fmu_to, port_to))

        # Create wires with their port-level mappings
        self._graph.scene.blockSignals(True)
        try:
            for (name1, name2), mappings in wire_key_mappings.items():
                node1 = nodes_by_name.get(name1)
                node2 = nodes_by_name.get(name2)
                if not node1 or not node2:
                    logger.warning(f"Cannot create wire: node not found for {name1} ↔ {name2}")
                    continue

                wire = self._graph.scene.add_wire(node1, node2)
                if wire:
                    wire.mappings = mappings
                    logger.debug(f"Wire created: {name1} ↔ {name2} with {len(mappings)} mapping(s)")
                else:
                    # Wire already exists — append mappings
                    for w in node1.wires:
                        other = w.node_b if w.node_a is node1 else w.node_a
                        if other is node2:
                            w.mappings.extend(mappings)
                            break
        finally:
            self._graph.scene.blockSignals(False)
            self._graph.scene.clearSelection()

        # Apply start values to scene nodes
        for fmu_name, port_name, value in start_values_list:
            node = nodes_by_name.get(fmu_name)
            if node:
                node.user_start_values[port_name] = value
                logger.debug(f"Start value: {Path(fmu_name).name}/{port_name} = {value}")
            else:
                logger.warning(f"Cannot apply start value: node not found for {fmu_name}")

        # Apply exposed output ports to scene nodes
        for fmu_name, port_name, _exposed_name in output_ports_list:
            node = nodes_by_name.get(fmu_name)
            if node:
                node.user_exposed_outputs[port_name] = True
                logger.debug(f"Exposed output: {Path(fmu_name).name}/{port_name}")
            else:
                logger.warning(f"Cannot apply exposed output: node not found for {fmu_name}")

        # Reset the detail panels so that the next sync_to_node/sync_to_wire
        # does not overwrite the just-loaded data with stale empty table content.
        self._tree.fmu_detail._current_node = None
        self._tree.wire_detail._wire = None

        # Refresh views
        self._tree.tree_view.expandAll()
        self._graph.view.fit_all()

    def load_container_fmu(self, input_path: str):
        try:
            splitter = FMUSplitter(input_path)
            splitter.split_fmu()

        except FMUSplitterError as e:
            logger.fatal(f"{e}")
            return
        except FileNotFoundError as e:
            logger.fatal(f"Cannot read file: {e}")
            return

        folder = Path(input_path).with_suffix(".dir")
        json_filename = folder / Path(input_path).with_suffix(".json").name
        with open(json_filename, "rt") as file:
            data = json.load(file)

        self._import_data(data, folder)

    def _on_load_clicked(self):
        default_dir = str(self._last_directory) if self._last_directory else ""
        input_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load FMU Container",
            default_dir,
            "FMU (*.fmu)",
        )
        if not input_path:
            logger.info("Load cancelled")
            return

        self._last_directory = Path(input_path).parent
        log_level = logging.DEBUG if self._debug_checkbox.isChecked() else logging.INFO
        RunTask(self.load_container_fmu, input_path, parent=self, title="Loading FMU Container", level=log_level)
        self._dirty = False

    def import_assembly_file(self, input_path: str):
        """Read a JSON or CSV assembly file and populate the graph."""
        file_path = Path(input_path)
        fmu_directory = file_path.parent

        try:
            assembly = Assembly(filename=file_path.name, fmu_directory=fmu_directory)
        except AssemblyError as e:
            logger.fatal(f"{e}")
            return
        except Exception as e:
            logger.fatal(f"Cannot read file: {e}")
            return

        if assembly.root is None:
            logger.fatal("Failed to read assembly: no root node.")
            return

        data = assembly._json_encode_node(assembly.root)
        self._import_data(data, fmu_directory)

    def _on_import_clicked(self):
        default_dir = str(self._last_directory) if self._last_directory else ""
        input_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Assembly",
            default_dir,
            "Assembly files (*.json *.csv);;JSON (*.json);;CSV (*.csv)",
        )
        if not input_path:
            logger.info("Import cancelled")
            return

        self._last_directory = Path(input_path).parent
        log_level = logging.DEBUG if self._debug_checkbox.isChecked() else logging.INFO
        RunTask(self.import_assembly_file, input_path, parent=self, title="Importing Assembly", level=log_level)
        self._dirty = False

    def _on_export_clicked(self):
        root_name = Path(self._tree.root.text()).with_suffix(".json").name
        default_dir = str(self._last_directory / root_name) if self._last_directory else root_name
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save container configuration",
            default_dir,
            "JSON (*.json)",
        )
        if not output_path:
            logger.info("Save cancelled")
            return

        log_level = logging.DEBUG if self._debug_checkbox.isChecked() else logging.INFO

        self._last_directory = Path(output_path).parent
        RunTask(self.save_as_json, output_path, parent=self, title="Saving as JSON", level=log_level)

    def _apply_links_on_assembly_node(self, assembly_node: AssemblyNode, links_list: List[Tuple])-> List[Tuple]:
        for sub_assembly_node in assembly_node.children.values():
            links_list = self._apply_links_on_assembly_node(sub_assembly_node, links_list)

        logger.debug(f"Links applied: {len(links_list)}")
        logger.debug(f"Assembly node: {assembly_node.name}")
        logger.debug(f"{assembly_node.fmu_names_list}")

        remaining_links_list = []
        for link in links_list:
            logger.debug(f"{link}")
            if link[0] in assembly_node.fmu_names_list:
                if link[2] in assembly_node.fmu_names_list:
                    assembly_node.add_link(link[0], link[1], link[2], link[3])
                else:
                    assembly_node.add_output(link[0], link[1], link[1])
                    remaining_links_list.append((assembly_node.name, link[1], link[2], link[3]))
            else:
                if link[2] in assembly_node.fmu_names_list:
                    assembly_node.add_input(link[3], link[2], link[3])
                    remaining_links_list.append((link[0], link[1], assembly_node.name, link[3]))
                else:
                    remaining_links_list.append(link)

        return remaining_links_list

    def create_assembly(self) -> Optional[Assembly]:
        # Flush any in-progress edits from detail panels
        self._tree.wire_detail.sync_to_wire()
        self._tree.fmu_detail.sync_to_node()
        nodes_by_uid = {node.uid: node for node in self._graph.scene.nodes()}

        def _item_to_assembly_node(parent_assembly_node: Optional[AssemblyNode], item: QStandardItem) -> Optional[AssemblyNode]:
            container_parameters = item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
            if container_parameters:
                logger.debug(f"ADD Container: {container_parameters.name}")
                assembly_node = AssemblyNode(container_parameters.name,
                                             **container_parameters.parameters)
                for r in range(item.rowCount()):
                    child = item.child(r, 0)
                    if child is not None:
                        sub_assembly_node = _item_to_assembly_node(assembly_node, child)
                        if sub_assembly_node:
                            assembly_node.add_sub_node(sub_assembly_node)
                return assembly_node
            else:
                uid = item.data(_NodeTreeModel.ROLE_NODE_UID)
                node = nodes_by_uid.get(uid)
                if node is None:
                    logger.warning(f"Node with uid {uid} not found in scene, skipping.")
                    return None
                fmu_path = node.fmu_path
                logger.info(f"ADD: FMU: {fmu_path.name}")
                parent_assembly_node.add_fmu(str(fmu_path))
                # Apply user-defined start values
                for port_name, value in node.user_start_values.items():
                    logger.debug(f"START VALUE: {fmu_path.name}/{port_name} = {value}")
                    parent_assembly_node.add_start_value(str(fmu_path), port_name, value)
                # Apply user-exposed output ports
                for port_name, exposed in node.user_exposed_outputs.items():
                    if exposed:
                        logger.debug(f"EXPOSE OUTPUT: {fmu_path.name}/{port_name}")
                        parent_assembly_node.add_output(str(fmu_path), port_name, port_name)
                return None

        root_item: QStandardItem = self._tree.root
        assembly = None
        try:
            assembly = Assembly()
            assembly.root = _item_to_assembly_node(None, root_item)
        except FileNotFoundError as e:
            logger.fatal(f"Cannot read file: {e}")
        except (FMUContainerError, AssemblyError) as e:
            logger.fatal(f"{e}")

        links_list: List[Tuple[str, str, str, str]] = []
        # Build fmu_path lookup by fmu_path.name
        path_by_name: Dict[str, str] = {}
        for node in self._graph.scene.nodes():
            path_by_name[node.fmu_path.name] = str(node.fmu_path)

        for wire in self._graph.scene.wires():
            for link in wire.mappings:
                if len(link) == 4:
                    fmu_from_name, port_from, fmu_to_name, port_to = link
                    fmu_from_path = path_by_name[fmu_from_name]
                    fmu_to_path = path_by_name[fmu_to_name]
                elif len(link) == 2:
                    # Legacy 2-tuple: assume node_a → node_b
                    fmu_from_path = str(wire.node_a.fmu_path)
                    fmu_to_path = str(wire.node_b.fmu_path)
                    port_from, port_to = link
                else:
                    continue
                logger.info(f"{Path(fmu_from_path).name}/{port_from} → {Path(fmu_to_path).name}/{port_to}")
                links_list.append((fmu_from_path, port_from, fmu_to_path, port_to))

        self._apply_links_on_assembly_node(assembly.root, links_list)


        return assembly

    def save_as_json(self, output_path):
        assembly = self.create_assembly()
        if assembly:
            assembly.write_json(output_path)
            self._dirty = False

    def save_as_fmu(self, output_path, fmi_version=2, datalog=False):
        assembly = self.create_assembly()

        if assembly:
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    json_file_path = Path(tmp_dir) / "container.json"
                    assembly.write_json(json_file_path)
                    assembly.description_pathname = json_file_path
                    assembly.make_fmu(filename=output_path, fmi_version=fmi_version, datalog=datalog)
                    self._dirty = False

            except FMUContainerError as e:
                logger.fatal(f"{e}")

    def _on_save_clicked(self):
        root_name = Path(self._tree.root.text()).with_suffix(".fmu").name
        default_dir = str(self._last_directory / root_name) if self._last_directory else root_name
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save FMU container",
            default_dir,
            "FMU (*.fmu)",
        )
        if not output_path:
            logger.info("Save cancelled")
            return

        self._last_directory = Path(output_path).parent
        fmi_version = self._fmi_group.checkedId()
        datalog = self._datalog_checkbox.isChecked()
        log_level = logging.DEBUG if self._debug_checkbox.isChecked() else logging.INFO
        RunTask(self.save_as_fmu, output_path, fmi_version, datalog,
                parent=self, title="Saving as FMU", level=log_level)

    def closeEvent(self, event):
        if self._dirty:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Unsaved changes")
            msg.setText("You have unsaved changes. Are you sure you want to quit?")
            msg.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg.setDefaultButton(QMessageBox.StandardButton.No)

            btn_yes = msg.button(QMessageBox.StandardButton.Yes)
            btn_no = msg.button(QMessageBox.StandardButton.No)

            btn_yes.setProperty("class", "removal")
            btn_no.setProperty("class", "info")

            btn_width = max(btn_yes.sizeHint().width(), btn_no.sizeHint().width(), 150)
            btn_yes.setMinimumWidth(btn_width)
            btn_no.setMinimumWidth(btn_width)

            if msg.exec() == QMessageBox.StandardButton.No:
                event.ignore()
                return
        super().closeEvent(event)


def main():
    application = Application(sys.argv)
    application.window = MainWindow()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()

