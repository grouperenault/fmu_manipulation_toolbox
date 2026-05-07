"""
Detail panels for FMU container builder.

This module re-exports all detail panel classes for backward compatibility.
The actual implementations live in separate modules:
- wire_detail.py: WireDetailWidget and related classes
- fmu_detail.py: FMUDetailWidget and related classes
- container_detail.py: ContainerDetailWidget and ContainerParameters
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget

from fmu_manipulation_toolbox.gui.fmucontainer.wire_detail import WireDetailWidget
from fmu_manipulation_toolbox.gui.fmucontainer.fmu_detail import FMUDetailWidget
from fmu_manipulation_toolbox.gui.fmucontainer.container_detail import (
    ContainerParameters,
    ContainerDetailWidget,
)


class DetailPanelStack(QWidget):
    """Manages the detail panels (WireDetail, FMUDetail, ContainerDetail).

    Responsibilities:
    • Stack widget containing all detail panel types
    • Switching between panels based on selection
    • Coordinating detail panel updates
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── Detail panels ────────────────────────────────────────────
        self._empty_widget = QWidget()  # page 0
        self._wire_detail = WireDetailWidget()  # page 1
        self._fmu_detail = FMUDetailWidget()  # page 2
        self._container_detail = ContainerDetailWidget()  # page 3

        self._stack = QStackedWidget()
        self._stack.addWidget(self._empty_widget)
        self._stack.addWidget(self._wire_detail)
        self._stack.addWidget(self._fmu_detail)
        self._stack.addWidget(self._container_detail)
        self._stack.setCurrentIndex(0)

        # ── Layout ──────────────────────────────────────────────────
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stack)

    # ── Public API ──────────────────────────────────────────────────

    @property
    def wire_detail(self) -> WireDetailWidget:
        return self._wire_detail

    @property
    def fmu_detail(self) -> FMUDetailWidget:
        return self._fmu_detail

    @property
    def container_detail(self) -> ContainerDetailWidget:
        return self._container_detail

    def sync_edits(self):
        """Flush any pending edits from detail panels."""
        self._wire_detail.sync_to_wire()
        self._fmu_detail.sync_to_node()

    def show_empty(self):
        """Show empty panel."""
        self._stack.setCurrentWidget(self._empty_widget)

    def show_wire(self, wire):
        """Show wire detail panel."""
        self._wire_detail.set_wire(wire)
        self._stack.setCurrentWidget(self._wire_detail)

    def show_fmu(self, node):
        """Show FMU detail panel."""
        self._fmu_detail.set_node(node)
        self._stack.setCurrentWidget(self._fmu_detail)

    def show_container(self, container_parameters: ContainerParameters):
        """Show container detail panel."""
        self._container_detail.set_container(container_parameters)
        self._stack.setCurrentWidget(self._container_detail)

