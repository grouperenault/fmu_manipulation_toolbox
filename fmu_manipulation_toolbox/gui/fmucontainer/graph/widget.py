"""NodeGraphWidget — reusable composite widget (scene + view)."""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout

from .node import NodeItem
from .wire import WireItem
from .scene import NodeGraphScene
from .view import NodeGraphView


class NodeGraphWidget(QWidget):
    """Reusable widget containing the mini editor (scene + view).

    Public attributes:
        scene  : NodeGraphScene   - programmatic access to nodes and wires.
        view   : NodeGraphView    - view control.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.scene = NodeGraphScene()
        self.scene.setSceneRect(-2000, -2000, 4000, 4000)

        self.view = NodeGraphView(self.scene)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    # -- API shortcuts --------------------------------------------------------

    def add_node(
        self,
        x: float = 0,
        y: float = 0,
        fmu_path: Path = Path(""),
    ) -> Optional[NodeItem]:
        return self.scene.add_node(fmu_path, x, y)

    def add_wire(self, node_a: NodeItem, node_b: NodeItem) -> Optional[WireItem]:
        return self.scene.add_wire(node_a, node_b)

    def clear(self):
        self.scene.clear_all()

