"""NodeGraphView — graph view with grid, zoom, pan, drag-and-drop, and context menu."""

import math
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, QLineF
from PySide6.QtGui import QPainter, QPen, QKeyEvent
from PySide6.QtWidgets import (
    QGraphicsView, QMenu, QFileDialog, QMessageBox,
)

from .constants import (
    COLOR_GRID_LIGHT, COLOR_GRID_DARK,
    NODE_TITLE_HEIGHT, NODE_PORT_SPACING, GRID_SIZE, GRID_SQUARES,
)
from .node import NodeItem
from .node_info_dialog import NodeInfoDialog
from .scene import NodeGraphScene

# Try to import FMPy GUI
try:
    from fmpy.gui.MainWindow import MainWindow as FMPyMainWindow
    FMPY_AVAILABLE = True
except ImportError:
    FMPY_AVAILABLE = False

# Internal tool windows
from fmu_manipulation_toolbox.gui.fmueditor.__main__ import MainWindow as FMUEditorMainWindow
from fmu_manipulation_toolbox.gui.fmutool.__main__ import MainWindow as FMUToolMainWindow


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

        node_min_dim = NODE_TITLE_HEIGHT + NODE_PORT_SPACING + 10  # 64
        self._zoom_min = 10.0 / node_min_dim
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

        lines_light = []
        for x in range(first_left, right, GRID_SIZE):
            lines_light.append(QLineF(x, top, x, bottom))
        for y in range(first_top, bottom, GRID_SIZE):
            lines_light.append(QLineF(left, y, right, y))
        painter.setPen(QPen(COLOR_GRID_LIGHT, 0.5))
        painter.drawLines(lines_light)

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
        info_action = None

        selected_items = self._scene.selectedItems()
        if selected_items:
            delete_action = menu.addAction("Delete Selection")
            if len(selected_items) == 1 and isinstance(selected_items[0], NodeItem):
                menu.addSeparator()
                info_action = menu.addAction("Info")
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
                scene_pos += QPointF(20, 20)
        elif chosen == delete_action:
            self._scene.remove_selected()
        elif chosen == info_action:
            self._show_node_info(selected_items[0])
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

    def _show_node_info(self, node: NodeItem):
        """Show the info dialog for *node* and replace the FMU in-place if changed."""
        dialog = NodeInfoDialog(node, self)
        if dialog.exec() != NodeInfoDialog.DialogCode.Accepted:
            return
        new_path = Path(dialog.selected_path)
        if new_path.resolve() == node.fmu_path.resolve():
            return  # nothing changed

        node.replace_fmu(new_path)
        self._scene.node_replaced.emit(node)

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

