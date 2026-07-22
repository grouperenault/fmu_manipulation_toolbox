"""WireItem and helpers — connections between nodes in the graph."""

import math
from typing import List, Optional

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsItem,
    QGraphicsSceneMouseEvent,
)

from .constants import (
    COLOR_WIRE, COLOR_WIRE_SELECTED, COLOR_WIRE_DRAGGING,
    COLOR_BACKGROUND, ARROW_SIZE, WAYPOINT_RADIUS,
    COLOR_WIRE_HIGHLIGHT, HIGHLIGHT_ARROW_SIZE,
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
        # Direction highlight from WireDetails tab: None, 'a_to_b', 'b_to_a', 'terminals'
        self._highlight_mode: Optional[str] = None

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

    # -- Highlight (from WireDetails tab selection) ---------------------------

    def set_highlight_mode(self, mode: Optional[str]):
        """Set direction indicator shown on the wire.

        *mode* is one of: None, 'a_to_b', 'b_to_a', 'terminals'.
        """
        if mode not in (None, "a_to_b", "b_to_a", "terminals"):
            mode = None
        if self._highlight_mode != mode:
            self._highlight_mode = mode
            self.update()

    def _midpoint_and_tangent(self) -> tuple:
        """Return (mid_point, tangent_a_to_b) along the polyline (halfway by length)."""
        points = self._all_points()
        seg_lens = []
        total = 0.0
        for i in range(len(points) - 1):
            dl = math.hypot(points[i + 1].x() - points[i].x(),
                            points[i + 1].y() - points[i].y())
            seg_lens.append(dl)
            total += dl
        if total < 1e-6:
            return points[0], QPointF(1.0, 0.0)
        target = total / 2.0
        acc = 0.0
        for i, dl in enumerate(seg_lens):
            if acc + dl >= target:
                t = (target - acc) / dl if dl > 1e-9 else 0.0
                a, b = points[i], points[i + 1]
                mid = QPointF(a.x() + t * (b.x() - a.x()),
                              a.y() + t * (b.y() - a.y()))
                tangent = QPointF(b.x() - a.x(), b.y() - a.y())
                return mid, tangent
            acc += dl
        a, b = points[-2], points[-1]
        return b, QPointF(b.x() - a.x(), b.y() - a.y())

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

    @staticmethod
    def _shorten_point(tip: QPointF, prev: QPointF, amount: float) -> QPointF:
        """Return a point moved back from *tip* towards *prev* by *amount* pixels."""
        dx = tip.x() - prev.x()
        dy = tip.y() - prev.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return QPointF(tip)
        return QPointF(tip.x() - dx / length * amount, tip.y() - dy / length * amount)

    def paint(self, painter: QPainter, option, widget=None):
        color = COLOR_WIRE_SELECTED if self.isSelected() else COLOR_WIRE
        pen = QPen(color, 2.5 if self.isSelected() else 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        # -- Determine arrow presence to shorten the path ----------------------
        a_to_b, b_to_a = self._directions()
        points = self._all_points()
        has_dir = a_to_b or b_to_a or bool(self.mappings)
        arrow_at_b = has_dir and (a_to_b or (not a_to_b and not b_to_a))
        arrow_at_a = has_dir and b_to_a

        # Compute shorten amount: use the largest arrow drawn at each end
        shorten_b = 0.0
        shorten_a = 0.0
        if arrow_at_b:
            shorten_b = ARROW_SIZE * 0.7
        if arrow_at_a:
            shorten_a = ARROW_SIZE * 0.7
        # Highlight arrows are larger — use their size if active
        if self._highlight_mode == "a_to_b":
            shorten_b = max(shorten_b, HIGHLIGHT_ARROW_SIZE * 0.7)
        elif self._highlight_mode == "b_to_a":
            shorten_a = max(shorten_a, HIGHLIGHT_ARROW_SIZE * 0.7)

        # Build a draw path shortened at ends where arrows will be drawn
        draw_points = list(points)
        if shorten_b > 0 and len(draw_points) >= 2:
            draw_points[-1] = self._shorten_point(
                draw_points[-1], draw_points[-2], shorten_b)
        if shorten_a > 0 and len(draw_points) >= 2:
            draw_points[0] = self._shorten_point(
                draw_points[0], draw_points[1], shorten_a)

        draw_path = QPainterPath(draw_points[0])
        for pt in draw_points[1:]:
            draw_path.lineTo(pt)

        if self.terminal_mappings:
            # Double line for terminal connections
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            outer_pen = QPen(color, 5.0 if self.isSelected() else 4.0)
            outer_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            outer_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(outer_pen)
            painter.drawPath(draw_path)

            inner_pen = QPen(COLOR_BACKGROUND, 2.0 if self.isSelected() else 1.5)
            inner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            inner_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(inner_pen)
            painter.drawPath(draw_path)
        else:
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(draw_path)

        # -- Arrowheads --------------------------------------------------------
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))

        if has_dir:
            if arrow_at_b:
                tip = points[-1]
                prev = points[-2] if len(points) >= 2 else points[0]
                self._draw_arrow(painter, tip, QPointF(tip.x() - prev.x(), tip.y() - prev.y()), ARROW_SIZE)
            if arrow_at_a:
                tip = points[0]
                prev = points[1] if len(points) >= 2 else points[-1]
                self._draw_arrow(painter, tip, QPointF(tip.x() - prev.x(), tip.y() - prev.y()), ARROW_SIZE)

        # -- Direction highlight from WireDetails tab -----------------------
        if self._highlight_mode is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(COLOR_WIRE_HIGHLIGHT))
            if self._highlight_mode == "a_to_b":
                # Arrow at the B extremity, pointing outward (A → B)
                tip = points[-1]
                prev = points[-2] if len(points) >= 2 else points[0]
                self._draw_arrow(
                    painter, tip,
                    QPointF(tip.x() - prev.x(), tip.y() - prev.y()),
                    HIGHLIGHT_ARROW_SIZE,
                )
            elif self._highlight_mode == "b_to_a":
                # Arrow at the A extremity, pointing outward (B → A)
                tip = points[0]
                prev = points[1] if len(points) >= 2 else points[-1]
                self._draw_arrow(
                    painter, tip,
                    QPointF(tip.x() - prev.x(), tip.y() - prev.y()),
                    HIGHLIGHT_ARROW_SIZE,
                )
            elif self._highlight_mode == "terminals":
                # Two triangles forming a divergent pattern ◀▶ at midpoint:
                # bases near the middle (with a small gap), tips pointing
                # outward towards A and B.
                mid, tangent = self._midpoint_and_tangent()
                length = math.hypot(tangent.x(), tangent.y())
                if length > 1e-6:
                    ux, uy = tangent.x() / length, tangent.y() / length
                    gap = HIGHLIGHT_ARROW_SIZE * 0.1
                    # Tip on the B side (base is at mid + gap*u, tip at base + size*u)
                    tip_b = QPointF(mid.x() + ux * (gap + HIGHLIGHT_ARROW_SIZE),
                                    mid.y() + uy * (gap + HIGHLIGHT_ARROW_SIZE))
                    # Tip on the A side (base at mid - gap*u, tip at base - size*u)
                    tip_a = QPointF(mid.x() - ux * (gap + HIGHLIGHT_ARROW_SIZE),
                                    mid.y() - uy * (gap + HIGHLIGHT_ARROW_SIZE))
                    self._draw_arrow(painter, tip_b, tangent, HIGHLIGHT_ARROW_SIZE)
                    self._draw_arrow(
                        painter, tip_a,
                        QPointF(-tangent.x(), -tangent.y()),
                        HIGHLIGHT_ARROW_SIZE,
                    )

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

