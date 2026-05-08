"""
Selection synchronization utilities for the tree/scene coordination.
"""

import logging

from PySide6.QtWidgets import QTreeView

tree_logger = logging.getLogger("fmu_manipulation_toolbox.gui.tree")


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

