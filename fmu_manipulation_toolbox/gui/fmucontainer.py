import logging
import json
import math
import sys
import uuid

from enum import Enum, auto
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
    QFileDialog, QMainWindow, QPushButton, QComboBox,
    QStyledItemDelegate, QAbstractItemView
)

from fmu_manipulation_toolbox.gui.helper import Application, StatusBar, RunTask
from fmu_manipulation_toolbox.assembly import Assembly, AssemblyNode
from fmu_manipulation_toolbox.operations import FMU, FMUPort, OperationAbstract

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


class NodeItem(QGraphicsRectItem, OperationAbstract):
    """Rectangular box with a title and I/O ports."""

    def __init__(self, fmu_path: Path, x: float = 0, y: float = 0):
        super().__init__()

        self.uid = str(uuid.uuid4())
        self._title = fmu_path.name
        self.fmu_path = fmu_path


        # -- Read FMU ports ---------------------------------------------------

        # Keep full port lists for serialization / logic
        self.fmu_input_names: List[str] = []
        self.fmu_output_names: List[str] = []
        self.fmu_step_size:Optional[str] = None
        self.fmu_generator:str = ""

        fmu = FMU(fmu_path)
        fmu.apply_operation(self)
        del fmu

        # -- Visual ports: at most one "in" and one "out" ---------------------
        self.input_port: Optional[PortItem] = None
        self.output_port: Optional[PortItem] = None

        if self.fmu_input_names:
            self.input_port = PortItem("in", PortType.INPUT, self)
        if self.fmu_output_names:
            self.output_port = PortItem("out", PortType.OUTPUT, self)

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
            fm_title.horizontalAdvance(self.title) + 20,
        )

        self.setRect(0, 0, width, height)
        self.setPos(x, y)

        # -- Title -------------------------------------------------------------
        self._title_item = QGraphicsTextItem(self.title, self)
        self._title_item.setDefaultTextColor(COLOR_TEXT)
        self._title_item.setFont(FONT_TITLE)
        tbr = self._title_item.boundingRect()
        self._title_item.setPos((width - tbr.width()) / 2, (NODE_TITLE_HEIGHT - tbr.height()) / 2)

        # -- Position ports ----------------------------------------------------
        y_port = NODE_TITLE_HEIGHT + 0.5 * NODE_PORT_SPACING + 5
        if self.input_port:
            self.input_port.setPos(0, y_port)
        if self.output_port:
            self.output_port.setPos(width, y_port)

    def __repr__(self):
        return "Collect I/O ports"

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
        return 0

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
            for port in self.all_ports():
                for wire in port.wires:
                    wire.update_path()
        return super().itemChange(change, value)

    # -- Double-click to rename ---------------------------------------------

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        if event.pos().y() < NODE_TITLE_HEIGHT:
            view = self.scene().views()[0] if self.scene().views() else None
            new_name, ok = QInputDialog.getText(
                view, "Rename Node", "New name:", text=self._title
            )
            if ok and new_name.strip():
                self.title = new_name.strip()
        else:
            super().mouseDoubleClickEvent(event)

    # -- Helpers ---------------------------------------------------------------

    def all_ports(self) -> List[PortItem]:
        """Return the list of visible PortItems."""
        ports = []
        if self.input_port:
            ports.append(self.input_port)
        if self.output_port:
            ports.append(self.output_port)
        return ports

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
        self.mappings: List[tuple] = []      # [(output_port, input_port), …]

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

    # -- Selection hit area ---------------------------------------------------

    def shape(self) -> QPainterPath:
        """Return a widened path so the wire is easier to click."""
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        return stroker.createStroke(self.path())

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

    def add_node(self, fmu_path: Path | str, x: float = 0, y: float = 0) -> NodeItem:
        """Create and add a node to the scene."""
        node = NodeItem(Path(fmu_path), x=x, y=y)
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
                    self._scene.add_node(fmu_path=path_obj, x=scene_pos.x(), y=scene_pos.y())
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # -- Context menu -------------------------------------------------------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        scene_pos = self.mapToScene(event.pos())

        # Under cursor?
        item = self._scene.itemAt(scene_pos, self.transform())

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
        x: float = 0,
        y: float = 0,
        fmu_path: str = "",
    ) -> NodeItem:
        return self.scene.add_node(fmu_path, x, y)

    def add_wire(self, source: PortItem, destination: PortItem) -> Optional[WireItem]:
        return self.scene.add_wire(source, destination)

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


class _PortComboDelegate(QStyledItemDelegate):
    """Delegate that presents a QComboBox populated with port names."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[str] = []

    def set_items(self, items: List[str]):
        self._items = list(items)

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems(self._items)
        return combo

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        idx = editor.findText(value)
        if idx >= 0:
            editor.setCurrentIndex(idx)
        elif self._items:
            editor.setCurrentIndex(0)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class WireDetailWidget(QWidget):
    """WireItem details: title label + 2-column port-mapping table.

    Columns:
        0 – Output port  (from the source node's FMU outputs)
        1 – Input port   (from the destination node's FMU inputs)

    Each cell uses a combo-box delegate so the user picks port names
    from drop-down menus.  *Add* / *Remove* buttons manage rows.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wire: Optional[WireItem] = None

        # -- Title --
        self._name_label = QLabel()
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)

        # -- Table model (2 columns) --
        self._table_model = QStandardItemModel(0, 2)
        self._table_model.setHorizontalHeaderLabels(["From", "To"])

        # -- Sort proxy (avoids editor invalidation on sort) --
        self._proxy_model = QSortFilterProxyModel(self)
        self._proxy_model.setSourceModel(self._table_model)

        # -- Table view --
        self._table = QTableView()
        self._table.setSortingEnabled(True)
        self._table.setModel(self._proxy_model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.CurrentChanged)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch,
        )
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        # -- Combo-box delegates (one per column) --
        self._source_delegate = _PortComboDelegate(self._table)
        self._dest_delegate = _PortComboDelegate(self._table)
        self._table.setItemDelegateForColumn(0, self._source_delegate)
        self._table.setItemDelegateForColumn(1, self._dest_delegate)

        # -- Sync edits back to WireItem --
        self._table_model.dataChanged.connect(self._on_table_data_changed)

        # -- Buttons --
        self._add_btn = QPushButton("Add link")
        self._remove_btn = QPushButton("Remove link")
        self._auto_btn = QPushButton("Auto-Connect")

        self._add_btn.setProperty("class", "info")
        self._remove_btn.setProperty("class", "removal")
        self._auto_btn.setProperty("class", "info")

        self._add_btn.clicked.connect(self._on_add)
        self._remove_btn.clicked.connect(self._on_remove)
        self._auto_btn.clicked.connect(self._on_auto_connect)

        btn_width = max(
            self._add_btn.sizeHint().width(),
            self._remove_btn.sizeHint().width(),
            self._auto_btn.sizeHint().width(),
        )
        self._add_btn.setMinimumWidth(btn_width)
        self._remove_btn.setMinimumWidth(btn_width)
        self._auto_btn.setMinimumWidth(btn_width)

        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.addWidget(self._auto_btn)
        btn_lay.addWidget(self._add_btn)
        btn_lay.addWidget(self._remove_btn)
        btn_lay.addStretch()

        # -- Layout --
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addWidget(self._table, 1)
        lay.addLayout(btn_lay)

    # ── Public API ──────────────────────────────────────────────

    def set_wire(self, wire: WireItem):
        """Bind to a wire and refresh delegates / table."""
        # Save current table to the previous wire before switching
        self.sync_to_wire()

        self._wire = wire
        src, dst = wire.source, wire.destination
        self._name_label.setText(f"{src.node.title}  →  {dst.node.title}")

        # Refresh available port names in delegates
        self._source_delegate.set_items(src.node.fmu_output_names)
        self._dest_delegate.set_items(dst.node.fmu_input_names)

        # Reload mappings stored on the wire
        self._load_from_wire()

    # ── Internal sync helpers ─────────────────────────────────────

    def sync_to_wire(self):
        """Write the current table content back to self._wire.mappings."""
        if self._wire is None:
            return
        mappings = []
        for r in range(self._table_model.rowCount()):
            out_item = self._table_model.item(r, 0)
            in_item = self._table_model.item(r, 1)
            if out_item and in_item:
                out_name = out_item.text()
                in_name = in_item.text()
                if out_name and in_name:
                    mappings.append((out_name, in_name))
        self._wire.mappings = mappings

    def _load_from_wire(self):
        """Populate the table from self._wire.mappings."""
        self._table_model.removeRows(0, self._table_model.rowCount())
        if self._wire is None:
            return
        for out_name, in_name in self._wire.mappings:
            self._table_model.appendRow(
                [QStandardItem(out_name), QStandardItem(in_name)]
            )

    # ── Slots ────────────────────────────────────────────────────

    def _on_add(self):
        """Add a new mapping row with default first port names."""
        if self._wire is None:
            return
        out_names = self._wire.source.node.fmu_output_names
        in_names = self._wire.destination.node.fmu_input_names
        if not out_names or not in_names:
            return

        src_item = QStandardItem(out_names[0])
        dst_item = QStandardItem(in_names[0])
        self._table_model.appendRow([src_item, dst_item])
        self.sync_to_wire()

    def _on_remove(self):
        """Remove selected rows from the mapping table."""
        source_rows = sorted(
            {self._proxy_model.mapToSource(idx).row()
             for idx in self._table.selectionModel().selectedRows()},
            reverse=True,
        )
        # Close any active editor before removing rows
        self._table.setCurrentIndex(QModelIndex())
        for r in source_rows:
            self._table_model.removeRow(r)
        self.sync_to_wire()

    def _on_auto_connect(self):
        """Automatically map ports that share the same name."""
        if self._wire is None:
            return
        out_names = self._wire.source.node.fmu_output_names
        in_names = self._wire.destination.node.fmu_input_names
        in_set = set(in_names)

        # Collect already-mapped pairs to avoid duplicates
        existing = set(self._wire.mappings)

        for name in out_names:
            if name in in_set and (name, name) not in existing:
                self._table_model.appendRow(
                    [QStandardItem(name), QStandardItem(name)]
                )
        self.sync_to_wire()

    def _on_table_data_changed(self, _top_left, _bottom_right, _roles):
        """Sync to wire whenever a cell is edited via combo box."""
        self.sync_to_wire()


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
        self._name_label.setText(f"{node.title} ({node.fmu_generator}, {node.fmu_step_size}s)")


class ContainerParameters:
    def __init__(self, name: str, ):
        self.name = name
        self.parameters = {
            "step_size": "",
            "mt": False,
            "profiling": False,
            "sequential": False,
            "auto_link": True,
            "auto_input": True,
            "auto_output": True,
            "auto_parameter": False,
            "auto_local": False,
            "ts_multiplier": False,
        }


class ContainerDetailWidget(QWidget):
    """Container details - content to be defined later."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._container_parameters: Optional[ContainerParameters] = None

        self._name_label = QLabel()
        font = self._name_label.font()
        font.setBold(True)
        self._name_label.setFont(font)

        self._model = QStandardItemModel(0, 2)
        self._model.setHorizontalHeaderLabels(["Parameters", ""])
        self._table = QTableView()
        self._table.setModel(self._model)

        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch,
        )
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        # -- Sync edits back to WireItem --
        self._model.dataChanged.connect(self._on_table_data_changed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._name_label)
        lay.addWidget(self._table, 1)


    def set_container(self, container_parameters: ContainerParameters):
        self._name_label.setText(f"{container_parameters.name}")

        self._model.removeRows(0, self._model.rowCount())
        for k, v in container_parameters.parameters.items():
            if isinstance(v, bool):
                value_item = QStandardItem("")
                value_item.setCheckable(True)
                value_item.setCheckState(Qt.Checked if v else Qt.Unchecked)
                value_item.setEditable(False)
            else:
                value_item = QStandardItem(v)
                value_item.setEditable(True)
            key_item = QStandardItem(k)
            key_item.setEditable(False)
            self._model.appendRow([key_item, value_item])

            self._container_parameters = container_parameters

    def _on_table_data_changed(self):
        for r in range(self._model.rowCount()):
            key = self._model.item(r, 0).text()
            value_item = self._model.item(r, 1)
            if value_item.isCheckable():
                value = value_item.checkState() == Qt.Checked
            else:
                value = value_item.text()

            self._container_parameters.parameters[key] = value


class NodeTreePanel(QWidget):
    """Side panel showing nodes as a hierarchical tree.

    • Single column with icon (Container / FMU) and name.
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
        self._tree.setIconSize(QSize(30, 30))  # Larger icons
        self._tree.setUniformRowHeights(True)
        self._tree.expandAll()

        # Enforce .fmu extension when a container is renamed in-place
        self._model.itemChanged.connect(self._on_item_changed)

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
        self._tree_splitter.setSizes([250, 250])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._tree_splitter)

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _ensure_fmu_ext(name: str) -> str:
        """Ensure *name* ends with '.fmu'."""
        if not name.lower().endswith(".fmu"):
            return name + ".fmu"
        return name

    def _on_item_changed(self, item: QStandardItem):
        """Called when an item is edited in-place (e.g. double-click rename)."""
        if not item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS):
            return
        fixed = self._ensure_fmu_ext(item.text().strip())
        if fixed != item.text():
            # Block signals to avoid recursion
            self._model.blockSignals(True)
            item.setText(fixed)
            self._model.blockSignals(False)

    # ── Row builders ──────────────────────────────────────────────

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

    # ── Scene -> tree synchronization ────────────────────────────────────

    def _on_scene_node_added(self, node: NodeItem):
        target = self._pending_parent or self._root
        target.appendRow(self._make_node_item(node))
        self._tree.expandAll()

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
        Also updates the details panel."""
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            # Flush any pending edits from the wire detail table
            self._wire_detail.sync_to_wire()

            sel = self._tree.selectionModel()
            sel.clearSelection()

            try:
                selected = self._graph.scene.selectedItems()
            except RuntimeError:
                # C++ scene already deleted (e.g. during shutdown)
                return

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
            try:
                self._graph.scene.clearSelection()
            except RuntimeError:
                return

            for index in self._tree.selectionModel().selectedRows(0):
                item = self._model.itemFromIndex(index)
                if item is None:
                    continue

                container_parameters = item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
                if container_parameters is not None:
                    # Container selected -> Container panel
                    self._container_detail.set_container(container_parameters)
                    self._detail_stack.setCurrentWidget(self._container_detail)
                    return
                uid = item.data(_NodeTreeModel.ROLE_NODE_UID)
                if uid:
                    try:
                        scene_nodes = self._graph.scene.nodes()
                    except RuntimeError:
                        return
                    for node in scene_nodes:
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
        act_add_fmu  = menu.addAction("Add FMU…")
        act_add_ctn  = menu.addAction("Add Container")

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
                target.appendRow(self._make_container_item(self._ensure_fmu_ext(name.strip())))
                self._tree.expandAll()

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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        splitter = QSplitter()
        self._graph = NodeGraphWidget()
        self._tree = NodeTreePanel(self._graph)
        splitter.addWidget(self._graph)
        splitter.addWidget(self._tree)
        splitter.setSizes([600, 400])

        self._load_button = QPushButton("Load")
        self._export_button = QPushButton("Export")
        self._save_button = QPushButton("Save")
        self._exit_button = QPushButton("Exit")
        self._save_button.setProperty("class", "save")
        self._export_button.setProperty("class", "save")
        self._load_button.setProperty("class", "quit")
        self._exit_button.setProperty("class", "quit")

        btn_width = max(
            self._load_button.sizeHint().width(),
            self._export_button.sizeHint().width(),
            self._save_button.sizeHint().width(),
            self._exit_button.sizeHint().width(),
            150,
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
        RunTask(self.coucou, "message", parent=self, title="Export to JSON", level=logging.DEBUG)


    def save_as_fmu(self, output_path):
        logger.info("Save clicked")

        # Flush any in-progress edits from wire detail table
        self._tree._wire_detail.sync_to_wire()

        root_item: QStandardItem = self._tree._root
        nodes_by_uid = {node.uid: node for node in self._graph.scene.nodes()}

        for wire in self._graph.scene.wires():
            fmu_from = nodes_by_uid[wire.source.node.uid]
            fmu_to = nodes_by_uid[wire.destination.node.uid]
            logger.info(f"{fmu_from.fmu_path} {wire.source.name} -> {fmu_to.fmu_path} {wire.destination.name}")

        def _serialize_item(item: QStandardItem, level:int = 0):
            container_parameters = item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
            if container_parameters:
                logger.info(f"{'  ' * level}CONTAINER: {container_parameters.name}")
                for r in range(item.rowCount()):
                    child = item.child(r, 0)
                    if child is not None:
                        _serialize_item(child, level=level + 1)
                logger.info(f"{'  ' * level}.")
            else:
                uid = item.data(_NodeTreeModel.ROLE_NODE_UID)
                scene_node = nodes_by_uid.get(uid)
                logger.info(f"{'  ' * level}FMU: {scene_node.fmu_path}")

        _serialize_item(root_item)


    def _on_save_clicked(self):
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save container snapshot",
            "container_snapshot.json",
            "JSON (*.json)",
        )
        if not output_path:
            logger.info("Save cancelled")
            return

        RunTask(self.save_as_fmu, output_path, parent=self, title="Saving as FMU", level=logging.DEBUG)

    def closeEvent(self, event):
        super().closeEvent(event)


def main():
    application = Application(sys.argv)
    application.window = MainWindow()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()

