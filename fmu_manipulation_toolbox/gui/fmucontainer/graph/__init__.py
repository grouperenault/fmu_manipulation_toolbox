"""Graph visualization package for the FMU container builder.

Re-exports all public classes so existing imports continue to work:
    from .graph import NodeItem, WireItem, NodeGraphWidget, ...
"""

from .constants import (
    COLOR_BACKGROUND, COLOR_GRID_LIGHT, COLOR_GRID_DARK,
    COLOR_NODE_BG, COLOR_NODE_TITLE_BG, COLOR_NODE_BORDER,
    COLOR_NODE_SELECTED, COLOR_TEXT,
    COLOR_WIRE, COLOR_WIRE_SELECTED, COLOR_WIRE_DRAGGING,
    NODE_MIN_WIDTH, NODE_TITLE_HEIGHT, NODE_PORT_SPACING,
    NODE_CORNER_RADIUS, GRID_SIZE, GRID_SQUARES,
    ARROW_SIZE, WAYPOINT_RADIUS,
    FONT_TITLE, FONT_PORT, FONT_PORT_PARAMETER,
)
from .node import NodeItem
from .wire import WireItem, _DragWireItem
from .scene import NodeGraphScene
from .view import NodeGraphView
from .widget import NodeGraphWidget

__all__ = [
    # Constants
    "COLOR_BACKGROUND", "COLOR_GRID_LIGHT", "COLOR_GRID_DARK",
    "COLOR_NODE_BG", "COLOR_NODE_TITLE_BG", "COLOR_NODE_BORDER",
    "COLOR_NODE_SELECTED", "COLOR_TEXT",
    "COLOR_WIRE", "COLOR_WIRE_SELECTED", "COLOR_WIRE_DRAGGING",
    "NODE_MIN_WIDTH", "NODE_TITLE_HEIGHT", "NODE_PORT_SPACING",
    "NODE_CORNER_RADIUS", "GRID_SIZE", "GRID_SQUARES",
    "ARROW_SIZE", "WAYPOINT_RADIUS",
    "FONT_TITLE", "FONT_PORT", "FONT_PORT_PARAMETER",
    # Classes
    "NodeItem",
    "WireItem",
    "NodeGraphScene",
    "NodeGraphView",
    "NodeGraphWidget",
]

