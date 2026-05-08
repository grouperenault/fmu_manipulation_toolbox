"""
FMU Container Builder – Main window.

Main application interface for building FMU containers composing multiple FMUs.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QCheckBox, QRadioButton, QButtonGroup, QFrame,
    QFileDialog, QMenu, QWidgetAction, QMainWindow
)

from fmu_manipulation_toolbox.gui.helper import Application, RunTask, UnsavedChangesWindowMixin

from .graph import NodeGraphWidget, NodeItem
from .tree import NodeTreePanel
from .assembly_io import AssemblyIOMixin


logger = logging.getLogger("fmu_manipulation_toolbox")
tree_logger = logging.getLogger("fmu_manipulation_toolbox.gui.tree")


class MainWindow(AssemblyIOMixin, UnsavedChangesWindowMixin, QMainWindow):
    def __init__(self):
        super().__init__()

        self._last_directory: Optional[Path] = None
        self._dirty = False
        self._check_unsaved_changes = lambda: self._dirty  # Use the mixin

        # Setup tree logger with stdout handler
        self._setup_tree_logger()

        splitter = QSplitter()
        self._graph = NodeGraphWidget()
        self._tree = NodeTreePanel(self._graph)
        splitter.addWidget(self._graph)
        splitter.addWidget(self._tree)
        splitter.setSizes([600, 400])

        self._load_button = QPushButton("Load FMU Container")
        self._import_button = QPushButton("Import")
        self._export_button = QPushButton("Export as JSON")
        self._save_button = QPushButton("Save as FMU Container")
        self._exit_button = QPushButton("Exit")
        self._save_button.setProperty("class", "save")
        self._export_button.setProperty("class", "save")
        self._load_button.setProperty("class", "quit")
        self._import_button.setProperty("class", "quit")
        self._exit_button.setProperty("class", "quit")

        btn_width = max(
            self._load_button.sizeHint().width(),
            self._import_button.sizeHint().width(),
            self._export_button.sizeHint().width(),
            self._save_button.sizeHint().width(),
            self._exit_button.sizeHint().width(),
            150,
        )
        for button in (
            self._load_button,
            self._import_button,
            self._export_button,
            self._save_button,
            self._exit_button,
        ):
            button.setMinimumWidth(btn_width)

        self._load_button.clicked.connect(self._on_load_clicked)
        self._import_button.clicked.connect(self._on_import_clicked)
        self._export_button.clicked.connect(self._on_export_clicked)
        self._save_button.clicked.connect(self._on_save_clicked)
        self._exit_button.clicked.connect(self.close)

        # Debug checkbox
        self._debug_checkbox = QCheckBox("Verbose Mode")
        self._debug_checkbox.setToolTip("Keep intermediate build artifacts and enable verbose logging")
        self._debug_checkbox.stateChanged.connect(self._on_debug_mode_changed)

        # Datalog checkbox
        self._datalog_checkbox = QCheckBox("Enable Datalog")
        self._datalog_checkbox.setToolTip("Generate Containers with DATALOG support")

        # FMI version radio buttons
        self._fmi2_radio = QRadioButton("Generate FMI-2")
        self._fmi3_radio = QRadioButton("Generate FMI-3")
        self._fmi2_radio.setChecked(True)

        self._fmi_group = QButtonGroup(self)
        self._fmi_group.addButton(self._fmi2_radio, 2)
        self._fmi_group.addButton(self._fmi3_radio, 3)

        # "Configuration" popup menu grouping FMI version + debug
        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)
        config_layout.setContentsMargins(8, 4, 8, 4)
        config_layout.addWidget(self._fmi2_radio)
        config_layout.addWidget(self._fmi3_radio)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        config_layout.addWidget(separator)
        config_layout.addWidget(self._debug_checkbox)
        config_layout.addWidget(self._datalog_checkbox)

        config_action = QWidgetAction(self)
        config_action.setDefaultWidget(config_widget)

        config_menu = QMenu(self)
        config_menu.addAction(config_action)

        self._config_button = QPushButton("Configuration")
        self._config_button.setProperty("class", "quit")
        self._config_button.setMinimumWidth(btn_width)
        self._config_button.setMenu(config_menu)

        button_bar = QHBoxLayout()
        button_bar.addWidget(self._config_button)
        button_bar.addStretch(1)
        button_bar.addWidget(self._load_button)
        button_bar.addWidget(self._import_button)
        button_bar.addWidget(self._exit_button)
        button_bar.addWidget(self._export_button)
        button_bar.addWidget(self._save_button)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.addWidget(splitter, 1)
        main_layout.addLayout(button_bar)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        self.setWindowTitle("FMU Container Builder")
        self.resize(1600, 900)

        self._graph.scene.node_added.connect(self._on_node_added_update_dir)
        self._graph.scene.node_added.connect(lambda _: self._mark_dirty())
        self._graph.scene.node_removed.connect(lambda _: self._mark_dirty())
        self._graph.scene.wire_added.connect(lambda _: self._mark_dirty())
        self._graph.scene.wire_removed.connect(lambda _: self._mark_dirty())

        # Detail panels edits
        self._tree.wire_detail.changed.connect(self._mark_dirty)
        self._tree.fmu_detail.changed.connect(self._mark_dirty)
        self._tree.container_detail.changed.connect(self._mark_dirty)

        # Tree model structural changes (drag-drop, rename, add/remove rows)
        self._tree.model.dataChanged.connect(lambda *_: self._mark_dirty())
        self._tree.model.rowsInserted.connect(lambda *_: self._mark_dirty())
        self._tree.model.rowsRemoved.connect(lambda *_: self._mark_dirty())
        self._tree.model.rowsMoved.connect(lambda *_: self._mark_dirty())

        self.show()

    def _mark_dirty(self):
        self._dirty = True

    @staticmethod
    def _setup_tree_logger():
        """Configure tree logger with stdout handler."""
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))
        tree_logger.addHandler(handler)
        tree_logger.setLevel(logging.INFO)
        tree_logger.propagate = False

    @staticmethod
    def _on_debug_mode_changed(state):
        """Update tree logger level when debug checkbox changes."""
        if state:
            tree_logger.setLevel(logging.DEBUG)
            tree_logger.debug("Debug mode enabled - tree logger set to DEBUG level")
        else:
            tree_logger.setLevel(logging.INFO)

    def _on_node_added_update_dir(self, node: NodeItem):
        """Track the directory of the last FMU added to the scene."""
        if node.fmu_path and node.fmu_path.parent.exists():
            self._last_directory = node.fmu_path.parent

    # ──────────────────────────────────────────────────────────────────
    # UI event handlers
    # ──────────────────────────────────────────────────────────────────

    def _on_load_clicked(self):
        default_dir = str(self._last_directory) if self._last_directory else ""
        input_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load FMU Container",
            default_dir,
            "FMU (*.fmu)",
        )
        if not input_path:
            logger.info("Load cancelled")
            return

        self._last_directory = Path(input_path).parent
        log_level = logging.DEBUG if self._debug_checkbox.isChecked() else logging.INFO
        RunTask(self.load_container_fmu, input_path, parent=self, title="Loading FMU Container", level=log_level)
        self._dirty = False

    def _on_import_clicked(self):
        default_dir = str(self._last_directory) if self._last_directory else ""
        input_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Assembly",
            default_dir,
            "Assembly files (*.json *.csv *.ssp);;JSON (*.json);;CSV (*.csv);;SSP (*.ssp)",
        )
        if not input_path:
            logger.info("Import cancelled")
            return

        self._last_directory = Path(input_path).parent
        log_level = logging.DEBUG if self._debug_checkbox.isChecked() else logging.INFO
        RunTask(self.import_assembly_file, input_path, parent=self, title="Importing Assembly", level=log_level)
        self._dirty = True

    def _on_export_clicked(self):
        root_name = Path(self._tree.root.text()).with_suffix(".json").name
        default_dir = str(self._last_directory / root_name) if self._last_directory else root_name
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save container configuration",
            default_dir,
            "JSON (*.json)",
        )
        if not output_path:
            logger.info("Save cancelled")
            return

        log_level = logging.DEBUG if self._debug_checkbox.isChecked() else logging.INFO
        self._last_directory = Path(output_path).parent
        RunTask(self.save_as_json, output_path, parent=self, title="Saving as JSON", level=log_level)

    def _on_save_clicked(self):
        root_name = Path(self._tree.root.text()).with_suffix(".fmu").name
        default_dir = str(self._last_directory / root_name) if self._last_directory else root_name
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save FMU container",
            default_dir,
            "FMU (*.fmu)",
        )
        if not output_path:
            logger.info("Save cancelled")
            return

        self._last_directory = Path(output_path).parent
        fmi_version = self._fmi_group.checkedId()
        datalog = self._datalog_checkbox.isChecked()
        log_level = logging.DEBUG if self._debug_checkbox.isChecked() else logging.INFO
        RunTask(self.save_as_fmu, output_path, fmi_version, datalog,
                parent=self, title="Saving as FMU", level=log_level)


def main():
    application = Application(sys.argv)
    application.window = MainWindow()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()

