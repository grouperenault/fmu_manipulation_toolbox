"""
FMU Container Builder – Main window.

Main application interface for building FMU containers composing multiple FMUs.
"""

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QCheckBox, QRadioButton, QButtonGroup, QFrame,
    QFileDialog, QMenu, QWidgetAction, QMainWindow
)

from fmu_manipulation_toolbox.gui.helper import Application, RunTask, UnsavedChangesWindowMixin
from fmu_manipulation_toolbox.assembly import Assembly, AssemblyNode, AssemblyError
from fmu_manipulation_toolbox.container import FMUContainerError
from fmu_manipulation_toolbox.split import FMUSplitter, FMUSplitterError

from .graph import NodeGraphWidget, NodeItem
from .tree import NodeTreePanel
from .details import ContainerParameters


logger = logging.getLogger("fmu_manipulation_toolbox")
tree_logger = logging.getLogger("fmu_manipulation_toolbox.gui.tree")


class MainWindow(UnsavedChangesWindowMixin, QMainWindow):
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
        # Create a stdout handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))

        # Add handler to tree logger
        tree_logger.addHandler(handler)

        # Set initial level (INFO by default, DEBUG if checkbox is checked)
        tree_logger.setLevel(logging.INFO)
        tree_logger.propagate = False  # Don't propagate to parent logger

    @staticmethod
    def _on_debug_mode_changed(state):
        """Update tree logger level when debug checkbox changes."""
        if state:  # Qt.CheckState.Checked
            tree_logger.setLevel(logging.DEBUG)
            tree_logger.debug("Debug mode enabled - tree logger set to DEBUG level")
        else:  # Qt.CheckState.Unchecked
            tree_logger.setLevel(logging.INFO)
            tree_logger.debug("Debug mode disabled - tree logger set to INFO level")

    def _on_node_added_update_dir(self, node: NodeItem):
        """Track the directory of the last FMU added to the scene."""
        if node.fmu_path and node.fmu_path.parent.exists():
            self._last_directory = node.fmu_path.parent

    def _data_to_items(self, parent, data_node, folder, links_list: List[List[str]], start_values_list: List[List[str]], output_ports_list: List[List[str]], x=0, y=0):
        from .tree import _NodeTreeModel
        self._tree.pending_parent = parent
        for fmu in data_node["fmu"]:
                logger.debug(f"ADD FMU: {folder} / {fmu}")
                self._graph.add_node(fmu_path=folder / fmu, x=x, y=y)
                x = x + 100
                y = y + 100
        self._tree.pending_parent = None


        container_name = data_node["name"]
        container_parameters = ContainerParameters(**data_node)
        logger.debug(f"SET CONTAINER: {container_name}: {container_parameters}")
        parent.setData(container_parameters, _NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
        parent.setText(container_name)

        if "link" in data_node:
            for link in data_node["link"]:
                logger.debug(f"ADD LINK: {link}")
                links_list.append(link)

        if "start" in data_node:
            for start in data_node["start"]:
                logger.debug(f"ADD START VALUE: {start}")
                start_values_list.append(start)

        if "output" in data_node:
            for output in data_node["output"]:
                # output format: [fmu_name, port_name, exposed_name]
                logger.debug(f"ADD OUTPUT PORT: {output}")
                output_ports_list.append(output)

        if "container" in data_node:
            for container_fmu in data_node["container"]:
                logger.debug(f"ADD CONTAINER: {container_fmu['name']}")
                child = self._tree.make_container_item(container_fmu["name"])
                parent.appendRow(child)
                self._data_to_items(child, container_fmu, folder, links_list, start_values_list, output_ports_list, x=x, y=y)

        for link in links_list:
            if link[2] == container_name:
                for input_container in data_node["input"]:
                    if link[3] == input_container[0]:
                        link[2] = input_container[1]
                        link[3] = input_container[2]
                        break

        for link in links_list:
            if link[0] == container_name:
                for output_container in data_node["output"]:
                    if link[1] == output_container[2]:
                        link[0] = output_container[0]
                        link[1] = output_container[1]
                        break

    def _import_data(self, data: dict, fmu_directory: Path):
        """Populate the scene and tree from a JSON-style dict.

        Shared by *load_container_fmu* (from a split FMU) and
        *import_assembly_file* (from a raw JSON / CSV).
        """
        # Clear existing scene and tree
        self._graph.scene.clear_all()
        self._tree.root.removeRows(0, self._tree.root.rowCount())

        links_list: List[List[str]] = []
        start_values_list: List[List[str]] = []
        output_ports_list: List[List[str]] = []
        self._data_to_items(self._tree.root, data, fmu_directory,
                            links_list, start_values_list, output_ports_list)

        # Build a map from FMU filename to its NodeItem
        nodes_by_name: Dict[str, NodeItem] = {}
        for node in self._graph.scene.nodes():
            nodes_by_name[str(node.fmu_path.resolve())] = node

        # Group links by (source_fmu, dest_fmu) pair to create one wire per pair
        # A wire between two nodes can carry mappings in both directions.
        wire_key_mappings: Dict[Tuple[str, str], List[Tuple[str, str, str, str]]] = {}
        for link in links_list:
            fmu_from = fmu_directory / link[0]
            port_from = link[1]
            fmu_to = fmu_directory / link[2]
            port_to = link[3]

            # Canonical key: sorted pair so A→B and B→A end up on the same wire
            key = tuple(sorted([str(fmu_from), str(fmu_to)]))
            wire_key_mappings.setdefault(key, []).append((fmu_from.name, port_from, fmu_to.name, port_to))

        # Create wires with their port-level mappings
        self._graph.scene.blockSignals(True)
        try:
            for (name1, name2), mappings in wire_key_mappings.items():
                node1 = nodes_by_name.get(name1)
                node2 = nodes_by_name.get(name2)
                if not node1 or not node2:
                    logger.warning(f"Cannot create wire: node not found for {name1} ↔ {name2}")
                    continue

                wire = self._graph.scene.add_wire(node1, node2)
                if wire:
                    wire.mappings = mappings
                    logger.debug(f"Wire created: {name1} ↔ {name2} with {len(mappings)} mapping(s)")
                else:
                    # Wire already exists — append mappings
                    for w in node1.wires:
                        other = w.node_b if w.node_a is node1 else w.node_a
                        if other is node2:
                            w.mappings.extend(mappings)
                            break
        finally:
            self._graph.scene.blockSignals(False)
            self._graph.scene.clearSelection()

        # Apply start values to scene nodes
        for fmu_name, port_name, value in start_values_list:
            node = nodes_by_name.get(fmu_name)
            if node:
                node.user_start_values[port_name] = value
                logger.debug(f"Start value: {Path(fmu_name).name}/{port_name} = {value}")
            else:
                logger.warning(f"Cannot apply start value: node not found for {fmu_name}")

        # Apply exposed output ports to scene nodes
        for fmu_name, port_name, _exposed_name in output_ports_list:
            node = nodes_by_name.get(fmu_name)
            if node:
                node.user_exposed_outputs[port_name] = True
                logger.debug(f"Exposed output: {Path(fmu_name).name}/{port_name}")

        # Reset the detail panels so that the next sync_to_node/sync_to_wire
        # does not overwrite the just-loaded data with stale empty table content.
        self._tree.fmu_detail._current_node = None
        self._tree.wire_detail._wire = None

        # Refresh views
        self._tree.tree_view.expandAll()
        self._graph.view.fit_all()

    def load_container_fmu(self, input_path: str):
        try:
            splitter = FMUSplitter(input_path)
            splitter.split_fmu()

        except FMUSplitterError as e:
            logger.fatal(f"{e}")
            return
        except FileNotFoundError as e:
            logger.fatal(f"Cannot read file: {e}")
            return

        folder = Path(input_path).with_suffix(".dir")
        json_filename = folder / Path(input_path).with_suffix(".json").name
        with open(json_filename, "rt") as file:
            data = json.load(file)

        self._import_data(data, folder)

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

    def import_assembly_file(self, input_path: str):
        """Read a JSON, CSV or SSP assembly file and populate the graph."""
        file_path = Path(input_path)
        fmu_directory = file_path.parent

        try:
            assembly = Assembly(filename=file_path.name, fmu_directory=fmu_directory)
        except AssemblyError as e:
            logger.fatal(f"{e}")
            return
        except Exception as e:
            logger.fatal(f"Cannot read file: {e}")
            return

        if assembly.root is None:
            logger.fatal("Failed to read assembly: no root node.")
            return

        data = assembly.json_encode()
        self._import_data(data, fmu_directory)

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

    def _apply_links_on_assembly_node(self, assembly_node: AssemblyNode, links_list: List[Tuple])-> List[Tuple]:
        for sub_assembly_node in assembly_node.children.values():
            links_list = self._apply_links_on_assembly_node(sub_assembly_node, links_list)

        logger.debug(f"Links applied: {len(links_list)}")
        logger.debug(f"Assembly node: {assembly_node.name}")
        logger.debug(f"{assembly_node.fmu_names_list}")

        remaining_links_list = []
        for link in links_list:
            logger.debug(f"{link}")
            if link[0] in assembly_node.fmu_names_list:
                if link[2] in assembly_node.fmu_names_list:
                    assembly_node.add_link(link[0], link[1], link[2], link[3])
                else:
                    assembly_node.add_output(link[0], link[1], link[1])
                    remaining_links_list.append((assembly_node.name, link[1], link[2], link[3]))
            else:
                if link[2] in assembly_node.fmu_names_list:
                    assembly_node.add_input(link[3], link[2], link[3])
                    remaining_links_list.append((link[0], link[1], assembly_node.name, link[3]))
                else:
                    remaining_links_list.append(link)

        return remaining_links_list

    def create_assembly(self) -> Optional[Assembly]:
        # Flush any in-progress edits from detail panels
        self._tree.wire_detail.sync_to_wire()
        self._tree.fmu_detail.sync_to_node()
        nodes_by_uid: Dict[str, NodeItem] = {node.uid: node for node in self._graph.scene.nodes()}

        def _item_to_assembly_node(parent_assembly_node: Optional[AssemblyNode], item) -> Optional[AssemblyNode]:
            from .tree import _NodeTreeModel
            container_parameters = item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
            if container_parameters:
                logger.debug(f"ADD Container: {container_parameters.name}")
                assembly_node = AssemblyNode(container_parameters.name,
                                             **container_parameters.parameters)
                for r in range(item.rowCount()):
                    child = item.child(r, 0)
                    if child is not None:
                        sub_assembly_node = _item_to_assembly_node(assembly_node, child)
                        if sub_assembly_node:
                            assembly_node.add_sub_node(sub_assembly_node)
                return assembly_node
            else:
                uid = item.data(_NodeTreeModel.ROLE_NODE_UID)
                node = nodes_by_uid.get(uid)
                if node is None:
                    logger.warning(f"Node with uid {uid} not found in scene, skipping.")
                    return None
                fmu_path = node.fmu_path
                logger.info(f"ADD: FMU: {fmu_path.name}")
                parent_assembly_node.add_fmu(str(fmu_path))
                # Apply user-defined start values
                for port_name, value in node.user_start_values.items():
                    logger.debug(f"START VALUE: {fmu_path.name}/{port_name} = {value}")
                    parent_assembly_node.add_start_value(str(fmu_path), port_name, value)
                # Apply user-exposed output ports
                for port_name, exposed in node.user_exposed_outputs.items():
                    if exposed:
                        logger.debug(f"EXPOSE OUTPUT: {fmu_path.name}/{port_name}")
                        parent_assembly_node.add_output(str(fmu_path), port_name, port_name)
                return None

        root_item = self._tree.root
        assembly = None
        try:
            assembly = Assembly()
            assembly.root = _item_to_assembly_node(None, root_item)
        except FileNotFoundError as e:
            logger.fatal(f"Cannot read file: {e}")
        except (FMUContainerError, AssemblyError) as e:
            logger.fatal(f"{e}")
            return

        links_list: List[Tuple[str, str, str, str]] = []
        # Build fmu_path lookup by fmu_path.name
        path_by_name: Dict[str, str] = {}
        for node in self._graph.scene.nodes():
            path_by_name[node.fmu_path.name] = str(node.fmu_path)

        for wire in self._graph.scene.wires():
            for link in wire.mappings:
                if len(link) == 4:
                    fmu_from_name, port_from, fmu_to_name, port_to = link
                    fmu_from_path = path_by_name[fmu_from_name]
                    fmu_to_path = path_by_name[fmu_to_name]
                elif len(link) == 2:
                    # Legacy 2-tuple: assume node_a → node_b
                    fmu_from_path = str(wire.node_a.fmu_path)
                    fmu_to_path = str(wire.node_b.fmu_path)
                    port_from, port_to = link
                else:
                    continue
                logger.info(f"{Path(fmu_from_path).name}/{port_from} → {Path(fmu_to_path).name}/{port_to}")
                links_list.append((fmu_from_path, port_from, fmu_to_path, port_to))

        if assembly.root:
            self._apply_links_on_assembly_node(assembly.root, links_list)


        return assembly

    def save_as_json(self, output_path):
        assembly = self.create_assembly()
        if assembly:
            assembly.write_json(output_path)
            self._dirty = False

    def save_as_fmu(self, output_path, fmi_version=2, datalog=False):
        assembly = self.create_assembly()

        if assembly:
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    json_file_path = Path(tmp_dir) / "container.json"
                    assembly.write_json(json_file_path)
                    assembly.description_pathname = json_file_path
                    assembly.make_fmu(filename=output_path, fmi_version=fmi_version, datalog=datalog)
                    self._dirty = False

            except FMUContainerError as e:
                logger.fatal(f"{e}")

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

