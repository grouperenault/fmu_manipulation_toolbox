"""
Tree model and role accessors for FMU container builder.

Contains _NodeTreeModel and TreeItemRoles.
"""

from typing import *

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem

from fmu_manipulation_toolbox.gui.fmucontainer.details import ContainerParameters


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

