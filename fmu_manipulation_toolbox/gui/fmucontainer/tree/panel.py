"""
NodeTreePanel: composite panel combining tree view and detail panels.
"""
import logging
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QWidget, QTreeView, QVBoxLayout, QSplitter
from typing import *

from fmu_manipulation_toolbox.gui.fmucontainer.details import DetailPanelStack
from fmu_manipulation_toolbox.gui.fmucontainer.graph import NodeItem, WireItem
from .model import _NodeTreeModel, TreeItemRoles
from .widget import NodeTreeWidget

tree_logger = logging.getLogger("fmu_manipulation_toolbox.gui.tree")


class NodeTreePanel(QWidget):
    """Side panel showing nodes as a hierarchical tree.
    Combines NodeTreeWidget and DetailPanelStack to provide a complete
    tree-based interface for managing the FMU container structure.
    """
    def __init__(self, graph_widget, parent=None):
        super().__init__(parent)
        self._graph = graph_widget
        self._tree_widget = NodeTreeWidget(graph_widget)
        self._detail_panel = DetailPanelStack()
        self._graph.scene.selectionChanged.connect(self._on_scene_selection_changed)
        self._tree_widget.tree_view.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
        self._tree_widget.container_changed.connect(self._on_container_changed)
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
    def wire_detail(self):
        return self._detail_panel.wire_detail

    @property
    def fmu_detail(self):
        return self._detail_panel.fmu_detail

    @property
    def container_detail(self):
        return self._detail_panel.container_detail

    @property
    def pending_parent(self) -> Optional[QStandardItem]:
        return self._tree_widget.pending_parent

    @pending_parent.setter
    def pending_parent(self, value: Optional[QStandardItem]):
        self._tree_widget.pending_parent = value

    def make_container_item(self, name: str, is_root: bool = False) -> QStandardItem:
        return self._tree_widget.make_container_item(name, is_root)

    def _on_scene_selection_changed(self):
        """Scene -> tree: select in tree when node is selected in graph."""
        tree_logger.debug("Panel: scene selection changed event received")
        try:
            self._detail_panel.sync_edits()
        except RuntimeError:
            tree_logger.debug("Detail panel sync failed during shutdown")
        self._tree_widget.on_scene_selection_changed()
        try:
            selected = self._graph.scene.selectedItems()
        except RuntimeError:
            tree_logger.warning("Scene already deleted during selection change")
            self._detail_panel.show_empty()
            return
        if len(selected) > 1:
            tree_logger.warning(f"Multiple scene selections detected ({len(selected)}), expected max 1")
            return
        if not selected:
            tree_logger.debug("Scene selection cleared")
            self._detail_panel.show_empty()
            return
        scene_item = selected[0]
        if isinstance(scene_item, NodeItem):
            tree_logger.debug(f"Scene selection: Node '{scene_item.title}'")
            self._detail_panel.show_fmu(scene_item)
            return

        if isinstance(scene_item, WireItem):
            tree_logger.debug(f"Scene selection: Wire (between nodes)")
            self._detail_panel.show_wire(scene_item)
            return
        tree_logger.debug(f"Unknown selection type: {type(scene_item)}")
        self._detail_panel.show_empty()

    def _on_tree_selection_changed(self, _selected, _deselected):
        """Tree -> scene: select in graph when node is selected in tree."""
        tree_logger.debug("Panel: tree selection changed event received")
        self._tree_widget.on_tree_selection_changed(_selected, _deselected)
        try:
            selected_rows = list(self._tree_widget.tree_view.selectionModel().selectedRows(0))
        except RuntimeError as e:
            tree_logger.error(f"Error getting tree selection: {e}")
            self._detail_panel.show_empty()
            return
        if len(selected_rows) > 1:
            tree_logger.warning(f"Multiple tree selections detected ({len(selected_rows)}), expected max 1")
            return
        if not selected_rows:
            tree_logger.debug("Tree selection cleared")
            self._detail_panel.show_empty()
            return
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
        tree_logger.warning(f"Tree item selected but no matching scene node found (uid={uid})")
        self._detail_panel.show_empty()

    def _on_container_changed(self, container_parameters):
        """Called when a container item is edited (e.g. renamed)."""
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
