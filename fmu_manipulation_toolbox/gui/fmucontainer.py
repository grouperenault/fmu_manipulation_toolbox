import logging
import json
import math
import sys
import uuid
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List

from PySide6.QtCore import Qt, QRectF, QPointF, QLineF, Signal, QItemSelectionModel, QSize
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont,
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
    QFileDialog, QMainWindow, QPushButton
)

from fmu_manipulation_toolbox.gui.helper import Application, StatusBar
from fmu_manipulation_toolbox.assembly import Assembly, AssemblyNode

logger = logging.getLogger("fmu_manipulation_toolbox")

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

COLOR_PORT_INPUT    = QColor("#68b86a")
COLOR_PORT_OUTPUT   = QColor("#e07040")
COLOR_PORT_BORDER   = QColor("#111111")

COLOR_WIRE          = QColor("#cccccc")
COLOR_WIRE_SELECTED = QColor("#f0a030")
COLOR_WIRE_DRAGGING = QColor("#88bbff")

# Dimensions
NODE_MIN_WIDTH      = 140
NODE_TITLE_HEIGHT   = 28
NODE_PORT_SPACING   = 26
NODE_CORNER_RADIUS  = 6
PORT_RADIUS         = 7
GRID_SIZE           = 20
GRID_SQUARES        = 5
WIRE_HANDLE_RADIUS  = 5

# Fonts
FONT_TITLE          = QFont("Verdana", 10, QFont.Weight.Bold)
FONT_PORT           = QFont("Verdana", 8)


class PortType(Enum):
    INPUT = auto()
    OUTPUT = auto()


class PortItem(QGraphicsEllipseItem):
    """Input or output port attached to a NodeItem."""

    def __init__(self, name: str, port_type: PortType, parent: "NodeItem"):
        r = PORT_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, parent)

        self.name = name
        self.port_type = port_type
        self.node: "NodeItem" = parent
        self.wires: List["WireItem"] = []

        color = COLOR_PORT_INPUT if port_type == PortType.INPUT else COLOR_PORT_OUTPUT
        self.setBrush(QBrush(color))
        self.setPen(QPen(COLOR_PORT_BORDER, 1.5))

        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(2)

        # Label
        self._label = QGraphicsTextItem(name, self)
        self._label.setDefaultTextColor(COLOR_TEXT)
        self._label.setFont(FONT_PORT)
        self._update_label_pos()

    def _update_label_pos(self):
        br = self._label.boundingRect()
        if self.port_type == PortType.INPUT:
            self._label.setPos(PORT_RADIUS + 4, -br.height() / 2)
        else:
            self._label.setPos(-PORT_RADIUS - 4 - br.width(), -br.height() / 2)

    def center_scene_pos(self) -> QPointF:
        """Port center position in scene coordinates."""
        return self.scenePos()

    # -- Hover feedback --------------------------------------------------------

    def hoverEnterEvent(self, event):
        self.setPen(QPen(QColor("#ffffff"), 2))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(QPen(COLOR_PORT_BORDER, 1.5))
        super().hoverLeaveEvent(event)

    # -- Highlight while dragging a wire --------------------------------

    def set_drop_highlight(self, on: bool):
        """Enable/disable highlight for a valid connection target."""
        if on:
            self.setPen(QPen(QColor("#ffffff"), 2))
        else:
            self.setPen(QPen(COLOR_PORT_BORDER, 1.5))


class NodeItem(QGraphicsRectItem):
    """Rectangular box with a title and I/O ports."""

    def __init__(
        self,
        title: str = "Node",
        x: float = 0,
        y: float = 0,
        fmu_path: str = "",
    ):
        super().__init__()

        self.input_port = PortItem("in", PortType.INPUT, self)
        self.output_port = PortItem("out", PortType.OUTPUT, self)

        self.uid = str(uuid.uuid4())
        self._title = title
        self.fmu_path = fmu_path

        # Flags
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(1)

        # -- Size calculation -----------------------------------------------
        height = NODE_TITLE_HEIGHT + NODE_PORT_SPACING + 10

        fm_title = QFontMetrics(FONT_TITLE)
        fm_port = QFontMetrics(FONT_PORT)
        width = max(
            NODE_MIN_WIDTH,
            fm_port.horizontalAdvance("in") + fm_port.horizontalAdvance("out") + 4 * PORT_RADIUS + 40,
            fm_title.horizontalAdvance(title) + 20,
        )

        self.setRect(0, 0, width, height)
        self.setPos(x, y)

        # -- Title -------------------------------------------------------------
        self._title_item = QGraphicsTextItem(title, self)
        self._title_item.setDefaultTextColor(COLOR_TEXT)
        self._title_item.setFont(FONT_TITLE)
        tbr = self._title_item.boundingRect()
        self._title_item.setPos((width - tbr.width()) / 2, (NODE_TITLE_HEIGHT - tbr.height()) / 2)

        # -- Ports (exactly 1 input + 1 output) ---------------------------
        y_port = NODE_TITLE_HEIGHT + 0.5 * NODE_PORT_SPACING + 5

        self.input_port.setPos(0, y_port)
        self.output_port.setPos(width, y_port)

    # -- Title -----------------------------------------------------------------

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str):
        self._title = value
        self._title_item.setPlainText(value)
        tbr = self._title_item.boundingRect()
        w = self.rect().width()
        self._title_item.setPos((w - tbr.width()) / 2, (NODE_TITLE_HEIGHT - tbr.height()) / 2)

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
        painter.setBrush(QBrush(COLOR_NODE_TITLE_BG))
        painter.drawPath(path_title.simplified())

        # Border
        pen_border = QPen(COLOR_NODE_SELECTED if self.isSelected() else COLOR_NODE_BORDER)
        pen_border.setWidthF(2.0 if self.isSelected() else 1.5)
        painter.setPen(pen_border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(0, 0, w, h, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)

    # -- Move -> update wires ----------------------------------

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for port in (self.input_port, self.output_port):
                for wire in port.wires:
                    wire.update_path()
        return super().itemChange(change, value)

    # -- Double-click to rename ---------------------------------------------

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        if event.pos().y() < NODE_TITLE_HEIGHT:
            view = self.scene().views()[0] if self.scene().views() else None
            new_name, ok = QInputDialog.getText(
                view, "Renommer le nœud", "Nouveau nom :", text=self._title
            )
            if ok and new_name.strip():
                self.title = new_name.strip()
        else:
            super().mouseDoubleClickEvent(event)

    # -- Helpers ---------------------------------------------------------------

    def all_ports(self) -> List[PortItem]:
        return [self.input_port, self.output_port]

    def remove_wires(self):
        """Remove all wires connected to this node."""
        for port in self.all_ports():
            for wire in list(port.wires):
                wire.remove()


class _WireHandle(QGraphicsEllipseItem):
    """Small handle the user can drag to bend the wire.

    It is created as a child of WireItem (graphics parent).
    Double-click resets curvature.
    """

    def __init__(self, wire: "WireItem"):
        r = WIRE_HANDLE_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, wire)
        self._wire = wire
        self._updating = False          # avoids setPos <-> itemChange recursion

        self.setBrush(QBrush(QColor(136, 187, 255, 140)))
        self.setPen(QPen(QColor("#446688"), 1.0))
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(3)
        self.setVisible(False)          # hidden until the wire is selected

    # -- When user drags the handle ---------------------------------

    def itemChange(self, change, value):
        if (
            change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged
            and not self._updating
        ):
            self._wire._on_handle_dragged(value)
        return super().itemChange(change, value)

    # -- Visual feedback -------------------------------------------------------

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(170, 221, 255, 220)))
        self.setPen(QPen(QColor("#88bbff"), 1.5))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor(136, 187, 255, 140)))
        self.setPen(QPen(QColor("#446688"), 1.0))
        super().hoverLeaveEvent(event)

    # -- Double-click -> reset ---------------------------------------------------

    def mouseDoubleClickEvent(self, event):
        """Reset the control point to its default midpoint."""
        self._wire._ctrl_offset = QPointF(0, 0)
        self._wire.update_path()
        event.accept()


class WireItem(QGraphicsPathItem):
    """Wire connecting a source port (output) to a destination port (input).

    A central control point (_WireHandle) allows users to adjust curvature.
    Double-click the handle to reset it.
    """

    def __init__(
        self,
        source: PortItem,
        destination: PortItem,
        parent=None,
    ):
        super().__init__(parent)

        self.source = source
        self.destination = destination

        source.wires.append(self)
        destination.wires.append(self)

        self._ctrl_offset = QPointF(0, 0)   # user offset

        self.setPen(QPen(COLOR_WIRE, 2.0))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(0)

        self._handle = _WireHandle(self)
        self.update_path()

    # -- Curve calculations --------------------------------------------------

    @staticmethod
    def _default_controls(p1: QPointF, p2: QPointF):
        """Default C1/C2 control points (horizontal tangents)."""
        dist = max(abs(p2.x() - p1.x()) * 0.5, 50)
        c1 = QPointF(p1.x() + dist, p1.y())
        c2 = QPointF(p2.x() - dist, p2.y())
        return c1, c2

    @staticmethod
    def _midpoint(p0: QPointF, c1: QPointF, c2: QPointF, p3: QPointF) -> QPointF:
        """Point on the cubic Bezier at t = 0.5."""
        # B(0.5) = (P0 + 3*C1 + 3*C2 + P3) / 8
        return QPointF(
            (p0.x() + 3 * c1.x() + 3 * c2.x() + p3.x()) / 8.0,
            (p0.y() + 3 * c1.y() + 3 * c2.y() + p3.y()) / 8.0,
        )

    @staticmethod
    def _bezier(p1: QPointF, p2: QPointF) -> QPainterPath:
        """Default Bezier (without offset), also used by _DragWireItem."""
        dist = max(abs(p2.x() - p1.x()) * 0.5, 50)
        path = QPainterPath(p1)
        path.cubicTo(
            p1.x() + dist, p1.y(),
            p2.x() - dist, p2.y(),
            p2.x(), p2.y(),
        )
        return path

    # -- Path update -------------------------------------------------

    def update_path(self):
        """Recompute the curve and reposition the handle."""
        p1 = self.source.center_scene_pos()
        p2 = self.destination.center_scene_pos()
        c1, c2 = self._default_controls(p1, p2)

        # Apply user offset to control points.
        # 4/3 factor keeps the handle exactly on B(0.5).
        adj = self._ctrl_offset * (4.0 / 3.0)
        ac1 = c1 + adj
        ac2 = c2 + adj

        path = QPainterPath(p1)
        path.cubicTo(ac1, ac2, p2)
        self.setPath(path)

        # Reposition the handle (without triggering _on_handle_dragged)
        mid = self._midpoint(p1, c1, c2, p2) + self._ctrl_offset
        self._handle._updating = True
        self._handle.setPos(mid)
        self._handle._updating = False

    def _on_handle_dragged(self, new_pos: QPointF):
        """Called by the handle when the user drags it."""
        p1 = self.source.center_scene_pos()
        p2 = self.destination.center_scene_pos()
        c1, c2 = self._default_controls(p1, p2)
        default_mid = self._midpoint(p1, c1, c2, p2)
        self._ctrl_offset = new_pos - default_mid

        # Rebuild path without moving the handle (user is dragging it)
        adj = self._ctrl_offset * (4.0 / 3.0)
        path = QPainterPath(p1)
        path.cubicTo(c1 + adj, c2 + adj, p2)
        self.setPath(path)

    # -- Rendering ----------------------------------------------------------------

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._handle.setVisible(bool(value))
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None):
        color = COLOR_WIRE_SELECTED if self.isSelected() else COLOR_WIRE
        pen = QPen(color, 2.5 if self.isSelected() else 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())

    # -- Deletion -----------------------------------------------------------

    def remove(self):
        """Remove the wire from scene and ports lists."""
        if self.source and self in self.source.wires:
            self.source.wires.remove(self)
        if self.destination and self in self.destination.wires:
            self.destination.wires.remove(self)
        if self.scene():
            self.scene().removeItem(self)


class _DragWireItem(QGraphicsPathItem):
    """Ghost wire shown while dragging from a port."""

    def __init__(self, start: QPointF, from_output: bool):
        super().__init__()
        self._start = start
        self._from_output = from_output
        pen = QPen(COLOR_WIRE_DRAGGING, 2.0, Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(10)

    def update_destination(self, end: QPointF):
        if self._from_output:
            path = WireItem._bezier(self._start, end)
        else:
            path = WireItem._bezier(end, self._start)
        self.setPath(path)


class NodeGraphScene(QGraphicsScene):
    """Graphics scene managing nodes, ports, and wires."""

    # Public signals
    node_added = Signal(object)       # NodeItem
    node_removed = Signal(object)     # NodeItem
    wire_added = Signal(object)       # WireItem
    wire_removed = Signal(object)     # WireItem

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(COLOR_BACKGROUND))

        self._drag_wire: Optional[_DragWireItem] = None
        self._drag_start_port: Optional[PortItem] = None
        self._drag_target_port: Optional[PortItem] = None

    # -- Public API ----------------------------------------------------------

    def add_node(
        self,
        title: str = "Node",
        x: float = 0,
        y: float = 0,
        fmu_path: str = "",
    ) -> NodeItem:
        """Create and add a node to the scene."""
        node = NodeItem(title=title, x=x, y=y, fmu_path=fmu_path)
        self.addItem(node)
        self.node_added.emit(node)
        return node

    def add_wire(self, source: PortItem, destination: PortItem) -> Optional[WireItem]:
        """Connect two ports with a wire. Returns None if invalid."""
        # Validation
        if source.port_type == destination.port_type:
            return None
        if source.node is destination.node:
            return None
        # Enforce output -> input order
        if source.port_type == PortType.INPUT:
            source, destination = destination, source
        # No duplicates
        for w in source.wires:
            if w.destination is destination:
                return None
        wire = WireItem(source, destination)
        self.addItem(wire)
        self.wire_added.emit(wire)
        return wire

    def remove_selected(self):
        """Remove selected items (wires first, then nodes)."""
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
        """Remove all nodes and wires."""
        for wire in self.wires():
            wire.remove()
        for node in self.nodes():
            self.removeItem(node)

    # -- Interaction: wire drag ---------------------------------------------

    def _port_at(self, scene_pos: QPointF) -> Optional[PortItem]:
        """Return the nearest PortItem under the given position."""
        for item in self.items(scene_pos, Qt.ItemSelectionMode.IntersectsItemBoundingRect):
            if isinstance(item, PortItem):
                return item
        return None

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        port = self._port_at(event.scenePos())
        if port and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_port = port
            from_output = port.port_type == PortType.OUTPUT
            self._drag_wire = _DragWireItem(port.center_scene_pos(), from_output)
            self.addItem(self._drag_wire)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self._drag_wire:
            self._drag_wire.update_destination(event.scenePos())
            # Target port highlight
            port = self._port_at(event.scenePos())
            if port is self._drag_start_port:
                port = None
            if port is not self._drag_target_port:
                if self._drag_target_port:
                    self._drag_target_port.set_drop_highlight(False)
                self._drag_target_port = port
                if port:
                    port.set_drop_highlight(True)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self._drag_wire:
            # Clear highlight
            if self._drag_target_port:
                self._drag_target_port.set_drop_highlight(False)
                self._drag_target_port = None
            # Find a port under cursor
            target = self._port_at(event.scenePos())
            if target and target is not self._drag_start_port:
                self.add_wire(self._drag_start_port, target)
            # Cleanup
            self.removeItem(self._drag_wire)
            self._drag_wire = None
            self._drag_start_port = None
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
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
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
                    name = path_obj.stem
                    self._scene.add_node(
                        title=name,
                        x=scene_pos.x(),
                        y=scene_pos.y(),
                        fmu_path=path,
                    )
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # -- Context menu -------------------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        scene_pos = self.mapToScene(event.pos())

        # Under cursor?
        item = self._scene.itemAt(scene_pos, self.transform())

        add_fmu_action = menu.addAction("Ajouter FMU…")
        delete_action = None
        if self._scene.selectedItems():
            delete_action = menu.addAction("Supprimer la sélection")
        menu.addSeparator()
        fit_action = menu.addAction("Ajuster la vue")

        chosen = menu.exec(event.globalPos())
        if chosen == add_fmu_action:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Sélectionner des FMU", "", "FMU (*.fmu)"
            )
            for path in paths:
                name = Path(path).stem
                self._scene.add_node(
                    title=name,
                    x=scene_pos.x(),
                    y=scene_pos.y(),
                    fmu_path=path,
                )
                scene_pos += QPointF(20, 20)  # offset subsequent nodes
        elif chosen == delete_action:
            self._scene.remove_selected()
        elif chosen == fit_action:
            self._fit_all()

    def _fit_all(self):
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
        title: str = "Node",
        x: float = 0,
        y: float = 0,
        fmu_path: str = "",
    ) -> NodeItem:
        return self.scene.add_node(title, x, y, fmu_path=fmu_path)

    def add_wire(self, source: PortItem, destination: PortItem) -> Optional[WireItem]:
        return self.scene.add_wire(source, destination)

    def clear(self):
        self.scene.clear_all()

# Custom data roles stored on column 0 items
ROLE_IS_CONTAINER = Qt.ItemDataRole.UserRole + 1
ROLE_NODE_UID     = Qt.ItemDataRole.UserRole + 2
ROLE_IS_ROOT      = Qt.ItemDataRole.UserRole + 3

class _NodeTreeModel(QStandardItemModel):
    """Model that only allows drop on "Container" items."""

    def canDropMimeData(self, data, action, row, column, parent):
        if not parent.isValid():
            return False                        # not at invisible root level
        col0 = parent.sibling(parent.row(), 0) if parent.column() != 0 else parent
        item = self.itemFromIndex(col0)
        if item is None or not item.data(ROLE_IS_CONTAINER):
            return False                        # only on a Container
        return super().canDropMimeData(data, action, row, column, parent)

    def dropMimeData(self, data, action, row, column, parent):
        # Redirect drops to column 0 so children are added under type_item
        if parent.isValid() and parent.column() != 0:
            parent = parent.sibling(parent.row(), 0)
        return super().dropMimeData(data, action, row, column, parent)


class WireDetailWidget(QWidget):
    """WireItem details: name + 4-column table."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._name_label = QLabel()
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)

        self._table_model = QStandardItemModel(0, 4)
        self._table_model.setHorizontalHeaderLabels(
            ["Col A", "Col B", "Col C", "Col D"],
        )

        self._table = QTableView()
        self._table.setModel(self._table_model)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch,
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addWidget(self._table)

    def set_wire(self, wire: WireItem):
        src, dst = wire.source, wire.destination
        self._name_label.setText(
            f"{src.node.title}.{src.name}  →  {dst.node.title}.{dst.name}"
        )
        self._table_model.removeRows(0, self._table_model.rowCount())


class FMUDetailWidget(QWidget):
    """NodeItem (FMU) details - content to be defined later."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._name_label = QLabel()
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addStretch()

    def set_node(self, node: NodeItem):
        self._name_label.setText(node.title)


class ContainerDetailWidget(QWidget):
    """Container details - content to be defined later."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._name_label = QLabel()
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addStretch()

    def set_container(self, name: str):
        self._name_label.setText(name)


class NodeTreePanel(QWidget):
    """Side panel showing nodes as a hierarchical tree.

    • Two columns: **Type** (Container / Node) | **Name**.
    • First level contains a root container (*Project*).
    • Right-click -> add node, add container, rename, delete.
    • Internal drag-and-drop to reorganize hierarchy.
    • Synchronized with scene: nodes added/removed in graph
      appear/disappear automatically in the tree.
"""

    def __init__(self, graph_widget: NodeGraphWidget, parent=None):
        super().__init__(parent)
        self._graph = graph_widget
        self._pending_parent: Optional[QStandardItem] = None
        resources_dir = Path(__file__).resolve().parent.parent / "resources"
        self._icon_container = QIcon(str(resources_dir / "container.png"))
        self._icon_fmu = QIcon(str(resources_dir / "icon_fmu.png"))

        # ── Model ────────────────────────────────────────────────────────
        self._model = _NodeTreeModel(0, 2)
        self._model.setHorizontalHeaderLabels(["", "Name"])

        root_row = self._make_container_row("container.fmu", is_root=True)
        self._model.appendRow(root_row)
        self._root: QStandardItem = root_row[0]

        # ── View ───────────────────────────────────────────────────────────
        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setDragDropMode(QTreeView.DragDropMode.InternalMove)
        self._tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.header().setStretchLastSection(True)
        self._tree.setColumnWidth(0, 80)
        self._tree.setIconSize(QSize(30, 30))  # Larger icons
        self._tree.setUniformRowHeights(True)
        self._tree.expandAll()

        # ── Scene -> tree connections ──────────────────────────────────────
        self._syncing_selection = False

        self._graph.scene.node_added.connect(self._on_scene_node_added)
        self._graph.scene.node_removed.connect(self._on_scene_node_removed)
        self._graph.scene.selectionChanged.connect(self._on_scene_selection_changed)
        self._tree.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)

        # ── Details panel ────────────────────────────────────────────
        self._empty_widget = QWidget()                          # page 0
        self._wire_detail = WireDetailWidget()                  # page 1
        self._fmu_detail = FMUDetailWidget()                    # page 2
        self._container_detail = ContainerDetailWidget()        # page 3

        self._detail_stack = QStackedWidget()
        self._detail_stack.addWidget(self._empty_widget)
        self._detail_stack.addWidget(self._wire_detail)
        self._detail_stack.addWidget(self._fmu_detail)
        self._detail_stack.addWidget(self._container_detail)
        self._detail_stack.setCurrentIndex(0)

        # ── Layout ──────────────────────────────────────────────────
        self._tree_splitter = QSplitter(Qt.Orientation.Vertical)
        self._tree_splitter.addWidget(self._tree)
        self._tree_splitter.addWidget(self._detail_stack)
        self._tree_splitter.setChildrenCollapsible(False)
        self._tree_splitter.setStretchFactor(0, 3)
        self._tree_splitter.setStretchFactor(1, 2)
        self._tree_splitter.setSizes([300, 200])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._tree_splitter)

    # ── Row builders ──────────────────────────────────────────────

    def _make_container_row(self, name: str, is_root: bool = False) -> List[QStandardItem]:
        type_item = QStandardItem()
        type_item.setIcon(self._icon_container)
        type_item.setToolTip("Container")
        type_item.setData(True, ROLE_IS_CONTAINER)
        type_item.setData(is_root, ROLE_IS_ROOT)
        type_item.setEditable(False)
        type_item.setDropEnabled(True)
        type_item.setDragEnabled(not is_root)

        name_item = QStandardItem(name)
        name_item.setEditable(True)
        name_item.setDropEnabled(True)
        name_item.setDragEnabled(not is_root)
        return [type_item, name_item]

    def _make_node_row(self, node: NodeItem) -> List[QStandardItem]:
        type_item = QStandardItem()
        type_item.setIcon(self._icon_fmu)
        type_item.setToolTip("FMU")
        type_item.setData(False, ROLE_IS_CONTAINER)
        type_item.setData(node.uid, ROLE_NODE_UID)
        type_item.setEditable(False)
        type_item.setDropEnabled(False)
        type_item.setDragEnabled(True)

        name_item = QStandardItem(node.title)
        name_item.setEditable(False)
        name_item.setDropEnabled(False)
        name_item.setDragEnabled(True)
        return [type_item, name_item]

    # ── Scene -> tree synchronization ────────────────────────────────────

    def _on_scene_node_added(self, node: NodeItem):
        target = self._pending_parent or self._root
        target.appendRow(self._make_node_row(node))
        self._tree.expandAll()

    def _on_scene_node_removed(self, node: NodeItem):
        self._remove_uid_from(self._model.invisibleRootItem(), node.uid)

    def _remove_uid_from(self, parent: QStandardItem, uid: str) -> bool:
        for r in range(parent.rowCount()):
            child = parent.child(r, 0)
            if child is None:
                continue
            if not child.data(ROLE_IS_CONTAINER) and child.data(ROLE_NODE_UID) == uid:
                parent.removeRow(r)
                return True
            if child.data(ROLE_IS_CONTAINER) and self._remove_uid_from(child, uid):
                return True
        return False

    def _find_tree_item_by_uid(self, parent: QStandardItem, uid: str) -> Optional[QStandardItem]:
        """Recursively find a Node item by UID."""
        for r in range(parent.rowCount()):
            child = parent.child(r, 0)
            if child is None:
                continue
            if not child.data(ROLE_IS_CONTAINER) and child.data(ROLE_NODE_UID) == uid:
                return child
            if child.data(ROLE_IS_CONTAINER):
                found = self._find_tree_item_by_uid(child, uid)
                if found is not None:
                    return found
        return None

    # ── Selection synchronization ──────────────────────────────────

    def _on_scene_selection_changed(self):
        """Scene -> tree: select in tree when node is selected in graph.
        Also updates the details panel."""
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            sel = self._tree.selectionModel()
            sel.clearSelection()

            selected = self._graph.scene.selectedItems()

            # Find a NodeItem
            for scene_item in selected:
                if isinstance(scene_item, NodeItem):
                    tree_item = self._find_tree_item_by_uid(
                        self._model.invisibleRootItem(), scene_item.uid
                    )
                    if tree_item is not None:
                        idx = self._model.indexFromItem(tree_item)
                        sel.select(
                            idx,
                            QItemSelectionModel.SelectionFlag.Select
                            | QItemSelectionModel.SelectionFlag.Rows,
                        )
                        self._tree.scrollTo(idx)
                    self._fmu_detail.set_node(scene_item)
                    self._detail_stack.setCurrentWidget(self._fmu_detail)
                    return  # handled
            # Find a WireItem
            for scene_item in selected:
                if isinstance(scene_item, WireItem):
                    self._wire_detail.set_wire(scene_item)
                    self._detail_stack.setCurrentWidget(self._wire_detail)
                    return  # handled
            # Nothing relevant
            self._detail_stack.setCurrentWidget(self._empty_widget)
        finally:
            self._syncing_selection = False

    def _on_tree_selection_changed(self, _selected, _deselected):
        """Tree -> scene: select in graph when node is selected in tree.
        Also updates the details panel."""
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            self._graph.scene.clearSelection()
            for index in self._tree.selectionModel().selectedRows(0):
                item = self._model.itemFromIndex(index)
                if item is None:
                    continue
                if item.data(ROLE_IS_CONTAINER):
                    # Container selected -> Container panel
                    parent_std = item.parent() or self._model.invisibleRootItem()
                    name_col = parent_std.child(item.row(), 1)
                    self._container_detail.set_container(
                        name_col.text() if name_col else ""
                    )
                    self._detail_stack.setCurrentWidget(self._container_detail)
                    return
                uid = item.data(ROLE_NODE_UID)
                if uid:
                    for node in self._graph.scene.nodes():
                        if node.uid == uid:
                            node.setSelected(True)
                            self._fmu_detail.set_node(node)
                            self._detail_stack.setCurrentWidget(self._fmu_detail)
                            return
            # Nothing relevant
            self._detail_stack.setCurrentWidget(self._empty_widget)
        finally:
            self._syncing_selection = False

    # ── Context menu ──────────────────────────────────────────────────

    def _on_context_menu(self, pos):
        index = self._tree.indexAt(pos)
        target, item = self._resolve_target(index)

        menu = QMenu(self)
        act_add_fmu  = menu.addAction("Ajouter FMU…")
        act_add_ctn  = menu.addAction("Ajouter un conteneur")

        act_rename = act_delete = None
        if item is not None and item is not self._root:
            menu.addSeparator()
            if item.data(ROLE_IS_CONTAINER):
                act_rename = menu.addAction("Renommer")
            act_delete = menu.addAction("Supprimer")

        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen is act_add_fmu:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Sélectionner des FMU", "", "FMU (*.fmu)"
            )
            center = self._graph.view.mapToScene(
                self._graph.view.viewport().rect().center()
            )
            self._pending_parent = target
            for i, path in enumerate(paths):
                name = Path(path).stem
                self._graph.add_node(
                    name,
                    x=center.x() + i * 20,
                    y=center.y() + i * 20,
                    fmu_path=path,
                )
            self._pending_parent = None

        elif chosen is act_add_ctn:
            name, ok = QInputDialog.getText(self, "Nouveau conteneur", "Nom :")
            if ok and name.strip():
                target.appendRow(self._make_container_row(name.strip()))
                self._tree.expandAll()

        elif chosen is act_rename and item is not None:
            parent_std = item.parent() or self._model.invisibleRootItem()
            name_col = parent_std.child(item.row(), 1)
            new, ok = QInputDialog.getText(
                self, "Renommer", "Nom :", text=name_col.text()
            )
            if ok and new.strip():
                name_col.setText(new.strip())

        elif chosen is act_delete and item is not None:
            self._delete_item(item)

    def _resolve_target(self, index):
        """Return *(target_container, clicked_item)* or *(root, None)*."""
        if not index.isValid():
            return self._root, None
        col0 = index.sibling(index.row(), 0) if index.column() != 0 else index
        item = self._model.itemFromIndex(col0)
        if item is None:
            return self._root, None
        if item.data(ROLE_IS_CONTAINER):
            return item, item
        return (item.parent() or self._root), item

    # ── Deletion ──────────────────────────────────────────────────────

    def _delete_item(self, item: QStandardItem):
        """Delete a node or container (+ all its content) from tree and scene."""
        if item.data(ROLE_IS_CONTAINER):
            self._purge_container(item)
        else:
            self._remove_scene_node(item.data(ROLE_NODE_UID))
        parent = item.parent() or self._model.invisibleRootItem()
        parent.removeRow(item.row())

    def _purge_container(self, ctn: QStandardItem):
        """Recursively delete scene nodes contained in *ctn*."""
        for r in range(ctn.rowCount() - 1, -1, -1):
            child = ctn.child(r, 0)
            if child is None:
                continue
            if child.data(ROLE_IS_CONTAINER):
                self._purge_container(child)
            else:
                self._remove_scene_node(child.data(ROLE_NODE_UID))

    def _remove_scene_node(self, uid: Optional[str]):
        """Remove the matching node from the graphics scene."""
        if uid is None:
            return
        for node in self._graph.scene.nodes():
            if node.uid == uid:
                node.remove_wires()
                self._graph.scene.removeItem(node)
                return


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        splitter = QSplitter()
        self._graph = NodeGraphWidget()
        self._tree = NodeTreePanel(self._graph)
        splitter.addWidget(self._graph)
        splitter.addWidget(self._tree)
        splitter.setSizes([700, 300])

        self._load_button = QPushButton("Load")
        self._export_button = QPushButton("Export")
        self._save_button = QPushButton("Save")
        self._exit_button = QPushButton("Exit")
        self._save_button.setProperty("class", "save")
        self._exit_button.setProperty("class", "quit")

        btn_width = max(
            self._load_button.sizeHint().width(),
            self._export_button.sizeHint().width(),
            self._save_button.sizeHint().width(),
            self._exit_button.sizeHint().width(),
        )
        for button in (
            self._load_button,
            self._export_button,
            self._save_button,
            self._exit_button,
        ):
            button.setMinimumWidth(btn_width)

        self._load_button.clicked.connect(self._on_load_clicked)
        self._export_button.clicked.connect(self._on_export_clicked)
        self._save_button.clicked.connect(self._on_save_clicked)
        self._exit_button.clicked.connect(self.close)

        self._status_bar = StatusBar()
        self._status_bar.setSizeGripEnabled(False)

        button_bar = QHBoxLayout()
        button_bar.addWidget(self._status_bar, 1)
        button_bar.addWidget(self._load_button)
        button_bar.addWidget(self._export_button)
        button_bar.addWidget(self._save_button)
        button_bar.addWidget(self._exit_button)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.addWidget(splitter, 1)
        main_layout.addLayout(button_bar)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        self.setWindowTitle("FMU Container Builder")
        self.resize(1200, 700)

        logger.info("FMU Container Builder ready")
        self.show()

    def _on_load_clicked(self):
        # Reserved hook for the Load action.
        logger.info("Load clicked")
        pass

    def _on_export_clicked(self):
        # Reserved hook for the Export action.
        logger.info("Export clicked")
        pass

    def _on_save_clicked(self):
        logger.info("Save clicked")

        model: _NodeTreeModel = self._tree._model
        root_item: QStandardItem = self._tree._root
        nodes_by_uid = {node.uid: node for node in self._graph.scene.nodes()}

        def _name_for(item: QStandardItem) -> str:
            parent_std = item.parent() or model.invisibleRootItem()
            name_col = parent_std.child(item.row(), 1)
            return name_col.text() if name_col is not None else ""

        def _serialize_item(item: QStandardItem) -> dict:
            if item.data(ROLE_IS_CONTAINER):
                children = []
                for r in range(item.rowCount()):
                    child = item.child(r, 0)
                    if child is not None:
                        children.append(_serialize_item(child))
                return {
                    "type": "container",
                    "name": _name_for(item),
                    "is_root": bool(item.data(ROLE_IS_ROOT)),
                    "children": children,
                }

            uid = item.data(ROLE_NODE_UID)
            scene_node = nodes_by_uid.get(uid)
            return {
                "type": "fmu",
                "uid": uid,
                "name": _name_for(item),
                "title": scene_node.title if scene_node is not None else "",
                "fmu_path": scene_node.fmu_path if scene_node is not None else "",
            }

        wires_payload = []
        for wire in self._graph.scene.wires():
            wires_payload.append(
                {
                    "source_uid": wire.source.node.uid,
                    "source_port": wire.source.name,
                    "target_uid": wire.destination.node.uid,
                    "target_port": wire.destination.name,
                }
            )

        payload = {
            "tree": _serialize_item(root_item),
            "wires": wires_payload,
            "summary": {
                "node_count": len(nodes_by_uid),
                "wire_count": len(wires_payload),
            },
        }

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save container snapshot",
            "container_snapshot.json",
            "JSON (*.json)",
        )
        if not output_path:
            logger.info("Save cancelled")
            return

        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

        logger.info(
            "Snapshot saved to %s (%d nodes, %d wires)",
            output_path,
            len(nodes_by_uid),
            len(wires_payload),
        )

    def closeEvent(self, event):
        super().closeEvent(event)


def main():
    application = Application(sys.argv)
    application.window = MainWindow()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
