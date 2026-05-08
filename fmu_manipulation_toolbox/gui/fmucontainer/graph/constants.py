"""Visual constants for the FMU container graph."""

from PySide6.QtGui import QColor, QFont

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

