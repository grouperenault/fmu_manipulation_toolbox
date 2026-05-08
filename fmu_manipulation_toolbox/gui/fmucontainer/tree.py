"""
Tree view and hierarchy management for FMU container builder.

Contains classes for displaying and managing the container hierarchy.
"""

import logging

from PySide6.QtCore import Qt, Signal, QItemSelectionModel, QSize
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon
from PySide6.QtWidgets import (QWidget, QTreeView, QVBoxLayout, QInputDialog, QFileDialog,
                               QMenu, QAbstractItemView)
from pathlib import Path
from typing import *

from fmu_manipulation_toolbox.gui.fmucontainer.details import ContainerParameters


logger = logging.getLogger("fmu_manipulation_toolbox")
tree_logger = logging.getLogger("fmu_manipulation_toolbox.gui.tree")


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
    def get_container_params(item: Optional[QStandardItem]) -> Optional[ContainerParameters]:
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

    def __init__(self, tree_view: QTreeView, scene):
        self._tree_view = tree_view
        self._scene = scene
        self._tree_signals_blocked = False
        self._scene_signals_blocked = False

    def __enter__(self):
        """Block signals at entry."""
        self._tree_signals_blocked = self._tree_view.selectionModel().blockSignals(True)
        self._scene_signals_blocked = self._scene.blockSignals(True)
        tree_logger.debug("Selection synchronizer entered - signals blocked")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Restore signals at exit."""
        self._tree_view.selectionModel().blockSignals(self._tree_signals_blocked)
        self._scene.blockSignals(self._scene_signals_blocked)
        tree_logger.debug("Selection synchronizer exited - signals restored")
        return False


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

    def __init__(self, graph_widget, parent=None):
        super().__init__(parent)
        self._graph = graph_widget
        self._pending_parent: Optional[QStandardItem] = None
        resources_dir = Path(__file__).resolve().parent.parent.parent / "resources"
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
        self._graph.scene.selectionChanged.connect(self.on_scene_selection_changed)
        self._tree.selectionModel().selectionChanged.connect(self.on_tree_selection_changed)
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
        from .details import ContainerParameters
        item.setData(ContainerParameters(name), _NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
        item.setData(is_root, _NodeTreeModel.ROLE_IS_ROOT)
        item.setEditable(True)
        item.setDropEnabled(True)
        item.setDragEnabled(not is_root)
        return item

    def _make_node_item(self, node) -> QStandardItem:
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

    def _on_scene_node_added(self, node):
        target = self._pending_parent or self._root
        node_item = self._make_node_item(node)
        target.appendRow(node_item)
        self._tree.expandAll()
        self._select_tree_item(node_item)

    def _on_scene_node_removed(self, node):
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

    # ── Selection synchronization ──────────────────────────────────────

    def on_scene_selection_changed(self):
        """Scene -> tree: select in tree when node is selected in graph.

        Only sync NodeItems to tree. WireItems are not represented in tree,
        so tree selection is cleared when only a Wire is selected.
        """
        from .graph import NodeItem
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

    def on_tree_selection_changed(self, _selected, _deselected):
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

    def __init__(self, graph_widget, parent=None):
        super().__init__(parent)
        from .details import DetailPanelStack
        self._graph = graph_widget

        # ── Create sub-components ───────────────────────────────────
        self._tree_widget = NodeTreeWidget(graph_widget)
        self._detail_panel = DetailPanelStack()

        # ── Connect tree widget to detail panel ──────────────────────
        self._graph.scene.selectionChanged.connect(self._on_scene_selection_changed)
        self._tree_widget.tree_view.selectionModel().selectionChanged.connect(self._on_tree_selection_changed)
        self._tree_widget.container_changed.connect(self._on_container_changed)

        # ── Layout ──────────────────────────────────────────────────
        from PySide6.QtWidgets import QSplitter
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

    # ── Selection synchronization ──────────────────────────────────

    def _on_scene_selection_changed(self):
        """Scene -> tree: select in tree when node is selected in graph.
        Also updates the details panel.

        NOTE: Expected behavior is SINGLE selection only.
        """
        from .graph import NodeItem
        tree_logger.debug("Panel: scene selection changed event received")
        # Flush any pending edits from detail panels
        self._detail_panel.sync_edits()

        # Let the tree widget sync its selection
        self._tree_widget.on_scene_selection_changed()

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

        from .graph import WireItem
        if isinstance(scene_item, WireItem):
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
        self._tree_widget.on_tree_selection_changed(_selected, _deselected)

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

    def _on_container_changed(self, container_parameters):
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

