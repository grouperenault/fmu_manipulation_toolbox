"""WireItem and helpers — connections between nodes in the graph."""

import math
from typing import List

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsItem,
    QGraphicsSceneMouseEvent,
)

from .constants import (
    COLOR_WIRE, COLOR_WIRE_SELECTED, COLOR_WIRE_DRAGGING,
    COLOR_BACKGROUND, ARROW_SIZE, WAYPOINT_RADIUS,
)
from .node import NodeItem


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
        self.terminal_mappings: List[tuple] = []

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

        if self.terminal_mappings:
            # Double line for terminal connections
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            outer_pen = QPen(color, 5.0 if self.isSelected() else 4.0)
            outer_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            outer_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(outer_pen)
            painter.drawPath(self.path())

            inner_pen = QPen(COLOR_BACKGROUND, 2.0 if self.isSelected() else 1.5)
            inner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            inner_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(inner_pen)
            painter.drawPath(self.path())
        else:
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

