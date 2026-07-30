"""NodeItem — rectangular node representing an FMU in the graph."""

import uuid
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QBrush, QColor, QFontMetrics
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem, QGraphicsItem, QStyleOptionGraphicsItem

from fmu_manipulation_toolbox.operations import FMU, FMUPort, OperationAbstract
from fmu_manipulation_toolbox.terminals import Terminals
from fmu_manipulation_toolbox.container import ArrayAggregate

from .constants import (
    NODE_MIN_WIDTH, NODE_TITLE_HEIGHT, NODE_PORT_SPACING, NODE_CORNER_RADIUS,
    COLOR_NODE_BG, COLOR_NODE_TITLE_BG, COLOR_NODE_SIGNAL_TITLE_BG, COLOR_NODE_BORDER,
    COLOR_NODE_SELECTED, COLOR_TEXT, FONT_TITLE,
)


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
        self._title_bg_color = COLOR_NODE_TITLE_BG

        # Whether this node can be removed by the user (regular FMU nodes: yes;
        # virtual ConfigurationNode: no, as long as it is still relevant).
        self.deletable = True
        # True only for the virtual ConfigurationNode subclass below.
        self.is_container_signal = False

        # -- Read FMU ports ---------------------------------------------------
        self.fmu_input_names: List[str] = []
        self.fmu_output_names: List[str] = []
        self.fmu_terminal_names: List[str] = []
        self.fmu_port_causality: Dict[str, str] = {}
        self.fmu_port_type: Dict[str, str] = {}
        self.fmu_start_values: Dict[str, str] = {}
        self.user_start_values: Dict[str, str] = {}
        self.user_exposed_outputs: Dict[str, bool] = {}
        self.user_exposed_inputs: Dict[str, bool] = {}
        self.fmu_step_size: Optional[str] = None
        self.fmu_generator: str = ""
        self.fmu_fmi_version: Optional[int] = None
        # Names of the underlying scalar element ports for each FMI-2 array
        # aggregate detected on this node (e.g. `myVector` -> `[myVector[1],
        # myVector[2], myVector[3]]`). Used to hide/mark the elements when
        # the aggregate is used in a wire.
        self.fmu_array_aggregate_elements: Dict[str, List[str]] = {}

        fmu = FMU(fmu_path)
        fmu.apply_operation(self)
        del fmu

        # -- Wires attached to this node --------------------------------------
        self.wires: List = []  # List["WireItem"] — avoids circular import

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
        version = attrs.get("fmiVersion", "")
        if version == "2.0":
            self.fmu_fmi_version = 2
        elif version.startswith("3."):
            self.fmu_fmi_version = 3

    def experiment_attrs(self, attrs):
        self.fmu_step_size = attrs.get("stepSize", "")

    def port_attrs(self, fmu_port: FMUPort) -> int:
        causality = fmu_port.get("causality", "local")
        name = fmu_port.get("name", "")
        if causality in ("input", "parameter"):
            self.fmu_input_names.append(name)
        elif causality == "output":
            self.fmu_output_names.append(name)
        self.fmu_port_causality[name] = causality
        self.fmu_port_type[name] = fmu_port.fmi_type or ""
        start = fmu_port.get("start", None)
        if start is not None:
            self.fmu_start_values[name] = start
        return 0

    def closure(self):
        for terminal in Terminals(self.fmu.tmp_directory):
            self.fmu_terminal_names.append(terminal.name)

        # For FMI-2 FMUs, expose contiguous families of scalar ports named
        # `basename[k]` or `basename[i,j,...]` (Modelica-style comma notation)
        # as virtual aggregated ports named `basename`, so the user can select
        # them in wires and connect them to FMI-3 array ports of matching shape.
        if self.fmu_fmi_version == 2:
            self._add_array_aggregates()

    def _add_array_aggregates(self):
        existing = set(self.fmu_port_causality.keys())
        for agg in ArrayAggregate.detect_all(
                list(self.fmu_port_causality.keys()),
                existing_names=existing,
                log_prefix=self.title,
        ):
            first = agg.ordered_element_names[0]
            causality = self.fmu_port_causality.get(first, "local")
            type_name = self.fmu_port_type.get(first, "")

            # All elements must share the same type and causality.
            if not all(self.fmu_port_causality.get(n) == causality
                       and self.fmu_port_type.get(n) == type_name
                       for n in agg.ordered_element_names):
                continue

            self.fmu_port_causality[agg.basename] = causality
            self.fmu_port_type[agg.basename] = type_name
            self.fmu_array_aggregate_elements[agg.basename] = list(agg.ordered_element_names)
            if causality in ("input", "parameter"):
                self.fmu_input_names.append(agg.basename)
            elif causality == "output":
                self.fmu_output_names.append(agg.basename)

    # -- Title -----------------------------------------------------------------

    @property
    def title(self) -> str:
        return self._title

    # -- Edge anchor -----------------------------------------------------------

    def edge_point(self, other_center: QPointF) -> QPointF:
        """Return the point on the node border closest to *other_center*."""
        r = self.sceneBoundingRect()
        cx, cy = r.center().x(), r.center().y()
        dx = other_center.x() - cx
        dy = other_center.y() - cy
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return QPointF(cx, cy)

        hw, hh = r.width() / 2.0, r.height() / 2.0
        if abs(dx) * hh > abs(dy) * hw:
            t = hw / abs(dx)
        else:
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

        color = QColor(self._title_bg_color)
        if self._title_highlighted:
            color = color.lighter(150)
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

    def replace_fmu(self, new_fmu_path: Path):
        """Replace the underlying FMU file while keeping wires, start values and exposed ports."""
        old_name = self.fmu_path.name
        new_name = new_fmu_path.name

        self.fmu_path = new_fmu_path
        self._title = new_name

        # Re-read ports from the new FMU
        self.fmu_input_names.clear()
        self.fmu_output_names.clear()
        self.fmu_terminal_names.clear()
        self.fmu_port_causality.clear()
        self.fmu_port_type.clear()
        self.fmu_start_values.clear()
        self.fmu_array_aggregate_elements.clear()
        self.fmu_step_size = None
        self.fmu_generator = ""
        self.fmu_fmi_version = None

        fmu = FMU(new_fmu_path)
        fmu.apply_operation(self)
        del fmu


        # Update FMU name in wire mappings
        if old_name != new_name:
            for wire in self.wires:
                wire.mappings = [
                    (new_name if m[0] == old_name else m[0], m[1],
                     new_name if m[2] == old_name else m[2], m[3])
                    for m in wire.mappings
                ]
                wire.terminal_mappings = [
                    (new_name if t[0] == old_name else t[0], t[1],
                     new_name if t[2] == old_name else t[2], t[3])
                    for t in wire.terminal_mappings
                ]

        # Update visual: title text and node width
        self._title_item.setPlainText(self._title)
        fm_title = QFontMetrics(FONT_TITLE)
        width = max(NODE_MIN_WIDTH, fm_title.horizontalAdvance(self._title) + 20)
        height = self.rect().height()
        self.setRect(0, 0, width, height)
        tbr = self._title_item.boundingRect()
        self._title_item.setPos((width - tbr.width()) / 2, (NODE_TITLE_HEIGHT - tbr.height()) / 2)

        # Refresh wires paths (node size may have changed)
        for wire in self.wires:
            wire.update_path()

        self.update()

    def remove_wires(self):
        """Remove all wires connected to this node."""
        for wire in list(self.wires):
            wire.remove()


class ConfigurationNode(NodeItem):
    """Singleton virtual node representing the `ts_multiplier` configuration.

    This node is *not* backed by a real FMU file: it is a purely graphical
    (GUI-only) representation, never exported to the `Assembly`/`AssemblyNode`
    model. It is titled "configuration" (no `.fmu` suffix) and appears in the
    scene as soon as at least one (non-root) container has its
    `ts_multiplier` checkbox checked. It exposes one virtual input port per
    such container, named `<container_without_.fmu_suffix>.ts_multiplier`,
    that ANY FMU in the assembly may be wired to.

    Unchecking a container's `ts_multiplier` does not remove its port nor an
    existing wire: the port becomes inactive and any wire referencing it is
    painted in red (invalid) — see `WireItem.is_invalid`. It becomes valid
    again automatically if the checkbox is rechecked. The node itself is
    only removed from the scene once ALL its ports are inactive AND no wire
    (valid or invalid) references it anymore (see `is_empty`/`cleanup_if_empty`).

    It behaves like a regular node (movable, selectable) but cannot be
    deleted by the user while it is still relevant (see `deletable`).
    """

    TITLE = "configuration"

    def __init__(self, x: float = 0, y: float = 0):
        # Do NOT call NodeItem.__init__ (it loads a real FMU file from disk).
        QGraphicsRectItem.__init__(self)

        self.uid = str(uuid.uuid4())
        self._title = self.TITLE
        self.fmu_path = Path(self.TITLE)

        self._title_highlighted = False
        self._title_bg_color = COLOR_NODE_SIGNAL_TITLE_BG

        # port_name -> active (bool). `active` mirrors the owning container's
        # current `ts_multiplier` checkbox state.
        self.ts_multiplier_ports: Dict[str, bool] = {}

        self.fmu_input_names: List[str] = []
        self.fmu_output_names: List[str] = []
        self.fmu_terminal_names: List[str] = []
        self.fmu_port_causality: Dict[str, str] = {}
        self.fmu_port_type: Dict[str, str] = {}
        self.fmu_start_values: Dict[str, str] = {}
        self.user_start_values: Dict[str, str] = {}
        self.user_exposed_outputs: Dict[str, bool] = {}
        self.user_exposed_inputs: Dict[str, bool] = {}
        self.fmu_step_size: Optional[str] = None
        self.fmu_generator: str = ""
        self.fmu_fmi_version: Optional[int] = None
        self.fmu_array_aggregate_elements: Dict[str, List[str]] = {}

        self.wires: List = []
        self.deletable = False
        self.is_container_signal = True

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(1)

        height = NODE_TITLE_HEIGHT + NODE_PORT_SPACING + 10
        fm_title = QFontMetrics(FONT_TITLE)
        width = max(NODE_MIN_WIDTH, fm_title.horizontalAdvance(self.title) + 20)
        self.setRect(0, 0, width, height)
        self.setPos(x, y)

        self._title_item = QGraphicsTextItem(self.title, self)
        self._title_item.setDefaultTextColor(COLOR_TEXT)
        self._title_item.setFont(FONT_TITLE)
        self._title_item.setAcceptHoverEvents(False)
        self._title_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        tbr = self._title_item.boundingRect()
        self._title_item.setPos((width - tbr.width()) / 2, (NODE_TITLE_HEIGHT - tbr.height()) / 2)

    def __repr__(self):
        return "ConfigurationNode()"

    # -- Port naming ------------------------------------------------------

    @staticmethod
    def port_name(container_name: str) -> str:
        """Return the static input port name for *container_name*.

        `<container_without_.fmu_suffix>.ts_multiplier`
        """
        base = container_name[:-4] if container_name.lower().endswith(".fmu") else container_name
        return f"{base}.ts_multiplier"

    def _port_in_use(self, port: str) -> bool:
        my_name = self.fmu_path.name
        for wire in self.wires:
            for m in wire.mappings:
                if len(m) < 4:
                    continue
                fmu_from, port_from, fmu_to, port_to = m
                if (fmu_from == my_name and port_from == port) or (fmu_to == my_name and port_to == port):
                    return True
        return False

    def _rebuild_ports(self):
        self.fmu_input_names = list(self.ts_multiplier_ports.keys())
        self.fmu_port_causality = {p: "input" for p in self.ts_multiplier_ports}
        self.fmu_port_type = {p: "Integer" for p in self.ts_multiplier_ports}
        for wire in self.wires:
            wire.update()
        self.update()

    # -- Lifecycle ----------------------------------------------------------

    def set_port_active(self, container_name: str, active: bool):
        """Activate/deactivate the port for *container_name*.

        Deactivating never deletes a port that is still referenced by a wire
        (so that wire can be shown in red and possibly re-validated later);
        an unused inactive port is dropped immediately.
        """
        port = self.port_name(container_name)
        if active:
            self.ts_multiplier_ports[port] = True
        else:
            if self._port_in_use(port):
                self.ts_multiplier_ports[port] = False
            else:
                self.ts_multiplier_ports.pop(port, None)
        self._rebuild_ports()

    def rename_port(self, old_container_name: str, new_container_name: str):
        """Update the port name (and any wire mapping referencing it) when
        the owning container is renamed."""
        old_port = self.port_name(old_container_name)
        new_port = self.port_name(new_container_name)
        if old_port == new_port or old_port not in self.ts_multiplier_ports:
            return
        active = self.ts_multiplier_ports.pop(old_port)
        self.ts_multiplier_ports[new_port] = active

        my_name = self.fmu_path.name
        for wire in self.wires:
            new_mappings = []
            for m in wire.mappings:
                if len(m) < 4:
                    new_mappings.append(m)
                    continue
                fmu_from, port_from, fmu_to, port_to = m
                if fmu_from == my_name and port_from == old_port:
                    port_from = new_port
                if fmu_to == my_name and port_to == old_port:
                    port_to = new_port
                new_mappings.append((fmu_from, port_from, fmu_to, port_to))
            wire.mappings = new_mappings
        self._rebuild_ports()

    def has_active_ports(self) -> bool:
        return any(self.ts_multiplier_ports.values())

    def is_empty(self) -> bool:
        """True when this node has no active port and no residual wire
        (valid or invalid) referencing it: it can be safely removed."""
        return not self.has_active_ports() and not self.wires

    def prune_inactive_unused_ports(self):
        """Drop inactive ports that are no longer referenced by any wire."""
        for port in list(self.ts_multiplier_ports.keys()):
            if not self.ts_multiplier_ports[port] and not self._port_in_use(port):
                del self.ts_multiplier_ports[port]
        self._rebuild_ports()

    def cleanup_if_empty(self):
        """Called after a wire attached to this node is removed: drop now
        orphaned inactive ports and, if nothing remains, delete the node
        entirely from the scene."""
        self.prune_inactive_unused_ports()
        if self.is_empty():
            scene = self.scene()
            if scene is not None:
                if hasattr(scene, "node_removed"):
                    scene.node_removed.emit(self)
                scene.removeItem(self)

    def replace_fmu(self, new_fmu_path: Path):
        raise NotImplementedError("ConfigurationNode is virtual and cannot be replaced.")


