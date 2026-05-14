"""Dialog showing FMU node information with the option to select an alternative FMU file."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout, QFileDialog,
)

from .node import NodeItem


class NodeInfoDialog(QDialog):
    """Modal dialog displaying node name and FMU file path.

    The user can select an alternative .fmu file. If accepted,
    the chosen path is available via :pyattr:`selected_path`.
    """

    def __init__(self, node: NodeItem, parent=None):
        super().__init__(parent)
        self._node = node
        self._selected_path: str = str(node.fmu_path)

        self.setWindowTitle("FMU Node Info")
        self.setMinimumWidth(500)

        # -- Node name --
        name_caption = QLabel("Name")
        name_caption.setProperty("class", "caption")
        self._name_label = QLabel(node.title)
        self._name_label.setProperty("class", "info")

        # -- FMU path --
        path_caption = QLabel("FMU File")
        path_caption.setProperty("class", "caption")

        self._path_edit = QLineEdit(str(node.fmu_path))
        self._path_edit.setReadOnly(True)

        browse_btn = QPushButton("Browse…")
        browse_btn.setProperty("class", "modify")
        browse_btn.clicked.connect(self._on_browse)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(browse_btn)

        # -- OK / Cancel --
        ok_btn = QPushButton("OK")
        ok_btn.setProperty("class", "save")
        ok_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("class", "quit")
        cancel_btn.clicked.connect(self.reject)

        btn_width = max(ok_btn.sizeHint().width(), cancel_btn.sizeHint().width(),
                        browse_btn.sizeHint().width(), 150)
        ok_btn.setMinimumWidth(btn_width)
        cancel_btn.setMinimumWidth(btn_width)
        browse_btn.setMinimumWidth(btn_width)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)

        # -- Layout --
        layout = QVBoxLayout(self)
        layout.addWidget(name_caption)
        layout.addWidget(self._name_label)
        layout.addSpacing(8)
        layout.addWidget(path_caption)
        layout.addLayout(path_row)
        layout.addSpacing(12)
        layout.addLayout(btn_row)

    # -- Slots ----------------------------------------------------------------

    def _on_browse(self):
        start_dir = str(Path(self._selected_path).parent)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select alternative FMU", start_dir, "FMU (*.fmu)"
        )
        if path:
            self._selected_path = path
            self._path_edit.setText(path)

    # -- Public API -----------------------------------------------------------

    @property
    def selected_path(self) -> str:
        """Return the (possibly updated) FMU file path."""
        return self._selected_path

