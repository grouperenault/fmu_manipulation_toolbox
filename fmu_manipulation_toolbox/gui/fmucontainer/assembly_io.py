"""
FMU Container Builder – Assembly I/O logic.

Mixin class handling conversion between the scene/tree representation
and Assembly objects (load, import, export, save).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyNode, AssemblyError
from fmu_manipulation_toolbox.container import FMUContainerError
from fmu_manipulation_toolbox.split import FMUSplitter, FMUSplitterError

from .graph import NodeItem
from .tree import _NodeTreeModel
from .details import ContainerParameters

if TYPE_CHECKING:
    from .graph import NodeGraphWidget
    from .tree import NodeTreePanel


logger = logging.getLogger("fmu_manipulation_toolbox")


class AssemblyIOMixin:
    """Mixin providing Assembly ↔ scene/tree conversion methods.

    Expects the host class to have:
        - self._graph: NodeGraphWidget
        - self._tree: NodeTreePanel
    """

    _graph: NodeGraphWidget
    _tree: NodeTreePanel
    _dirty: bool

    # ──────────────────────────────────────────────────────────────────
    # Import: Assembly → scene/tree
    # ──────────────────────────────────────────────────────────────────

    def _assembly_node_to_items(self, parent, assembly_node: AssemblyNode, folder: Path,
                                links_list: List[List[str]], start_values_list: List[List[str]],
                                output_ports_list: List[List[str]], x=0, y=0):
        """Recursively convert an AssemblyNode into tree items and graph nodes."""
        # Add FMU nodes
        self._tree.pending_parent = parent
        for fmu in assembly_node.fmu_names_list:
            logger.debug(f"ADD FMU: {folder} / {fmu}")
            self._graph.add_node(fmu_path=folder / fmu, x=x, y=y)
            x = x + 100
            y = y + 100
        self._tree.pending_parent = None

        # Add Container in tree View
        container_name = assembly_node.name
        container_parameters = ContainerParameters(
            name=assembly_node.name,
            step_size=assembly_node.step_size or "",
            mt=assembly_node.mt,
            profiling=assembly_node.profiling,
            sequential=assembly_node.sequential,
            auto_link=assembly_node.auto_link,
            auto_input=assembly_node.auto_input,
            auto_output=assembly_node.auto_output,
            auto_parameter=assembly_node.auto_parameter,
            auto_local=assembly_node.auto_local,
            ts_multiplier=assembly_node.ts_multiplier,
        )
        logger.debug(f"SET CONTAINER: {container_name}: {container_parameters}")
        parent.setData(container_parameters, _NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
        parent.setText(container_name)

        for connection in assembly_node.links:
            link = [connection.from_port.fmu_name, connection.from_port.port_name,
                    connection.to_port.fmu_name, connection.to_port.port_name]
            logger.debug(f"ADD LINK: {link}")
            links_list.append(link)

        for port, value in assembly_node.start_values.items():
            start = [port.fmu_name, port.port_name, value]
            logger.debug(f"ADD START VALUE: {start}")
            start_values_list.append(start)

        for port, target in assembly_node.output_ports.items():
            output = [port.fmu_name, port.port_name, target]
            logger.debug(f"ADD OUTPUT PORT: {output}")
            output_ports_list.append(output)

        for child_node in assembly_node.children.values():
            logger.debug(f"ADD CONTAINER: {child_node.name}")
            child = self._tree.make_container_item(child_node.name)
            parent.appendRow(child)
            self._assembly_node_to_items(child, child_node, folder, links_list,
                                         start_values_list, output_ports_list, x=x, y=y)

        for link in links_list:
            if link[2] == container_name:
                for port, input_name in assembly_node.input_ports.items():
                    if link[3] == input_name:
                        link[2] = port.fmu_name
                        link[3] = port.port_name
                        logger.debug(f"MODIFIED LINK: {link}")
                        break
            if link[0] == container_name:
                for port, output_name in assembly_node.output_ports.items():
                    if link[1] == output_name:
                        link[0] = port.fmu_name
                        link[1] = port.port_name
                        logger.debug(f"MODIFIED LINK: {link}")
                        break

    def _import_data(self, assembly: Assembly, fmu_directory: Path):
        """Populate the scene and tree from an Assembly object.

        Shared by *load_container_fmu* (from a split FMU) and
        *import_assembly_file* (from a raw JSON / CSV).
        """
        # Clear existing scene and tree
        self._graph.scene.clear_all()
        self._tree.root.removeRows(0, self._tree.root.rowCount())

        if assembly.root is None:
            logger.warning("Assembly has no root node, nothing to import.")
            return

        links_list: List[List[str]] = []
        start_values_list: List[List[str]] = []
        output_ports_list: List[List[str]] = []
        self._assembly_node_to_items(self._tree.root, assembly.root, fmu_directory,
                                     links_list, start_values_list, output_ports_list)

        # Build a map from FMU filename to its NodeItem
        nodes_by_name: Dict[str, NodeItem] = {}
        for node in self._graph.scene.nodes():
            nodes_by_name[str(node.fmu_path.resolve())] = node

        # Group links by (source_fmu, dest_fmu) pair to create one wire per pair
        wire_key_mappings: Dict[Tuple[str, str], List[Tuple[str, str, str, str]]] = {}
        for link in links_list:
            fmu_from = fmu_directory / link[0]
            port_from = link[1]
            fmu_to = fmu_directory / link[2]
            port_to = link[3]

            # Canonical key: sorted pair so A→B and B→A end up on the same wire
            key = tuple(sorted([str(fmu_from), str(fmu_to)]))
            wire_key_mappings.setdefault(key, []).append(
                (fmu_from.name, port_from, fmu_to.name, port_to))

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
        """Split a container FMU and import its contents."""
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

        try:
            assembly = Assembly(filename=json_filename.name, fmu_directory=folder)
        except AssemblyError as e:
            logger.fatal(f"{e}")
            return

        self._import_data(assembly, folder)

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

        self._import_data(assembly, fmu_directory)

    # ──────────────────────────────────────────────────────────────────
    # Export: scene/tree → Assembly
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _propagate_exposed_outputs(assembly_node: AssemblyNode):
        """Propagate user-exposed output ports from child nodes up to the root.

        For each child container that has output_ports, expose those ports
        at the current level as well, then recurse upward (called bottom-up).
        This must be called BEFORE _apply_links_on_assembly_node so that only
        user-exposed outputs are propagated (not routing outputs from links).
        """
        # First, recurse into children so their outputs are fully resolved
        for child in assembly_node.children.values():
            AssemblyIOMixin._propagate_exposed_outputs(child)

        # Now, for each child container, if it has exposed output ports,
        # also expose them at this level (so they bubble up to root)
        for child in assembly_node.children.values():
            for port, exposed_name in child.output_ports.items():
                assembly_node.add_output(child.name, exposed_name, exposed_name)
                logger.debug(f"PROPAGATE OUTPUT: {child.name}/{exposed_name} → {assembly_node.name}")

    @staticmethod
    def _apply_links_on_assembly_node(assembly_node: AssemblyNode,
                                      links_list: List[Tuple]) -> List[Tuple]:
        """Distribute links into the correct assembly nodes recursively."""
        for sub_assembly_node in assembly_node.children.values():
            links_list = AssemblyIOMixin._apply_links_on_assembly_node(
                sub_assembly_node, links_list)

        logger.debug(f"Links applied: {len(links_list)}")
        logger.debug(f"Assembly node: {assembly_node.name}")
        logger.debug(f"{assembly_node.fmu_names_list}")

        # An FMU "belongs" to this node if it is either a direct FMU or a child container
        known_names = set(assembly_node.fmu_names_list) | set(assembly_node.children.keys())

        remaining_links_list = []
        for link in links_list:
            logger.debug(f"{link}")
            from_is_local = link[0] in known_names
            to_is_local = link[2] in known_names

            if from_is_local and to_is_local:
                # Both ends are inside this node → internal link
                assembly_node.add_link(link[0], link[1], link[2], link[3])
            elif from_is_local and not to_is_local:
                # Source is local, destination is outside → expose as output
                assembly_node.add_output(link[0], link[1], link[1])
                remaining_links_list.append((assembly_node.name, link[1], link[2], link[3]))
            elif not from_is_local and to_is_local:
                # Source is outside, destination is local → expose as input
                assembly_node.add_input(link[3], link[2], link[3])
                remaining_links_list.append((link[0], link[1], assembly_node.name, link[3]))
            else:
                # Neither end belongs to this node → pass through
                remaining_links_list.append(link)

        return remaining_links_list

    def create_assembly(self) -> Optional[Assembly]:
        """Build an Assembly object from the current scene and tree state."""
        # Flush any in-progress edits from detail panels
        self._tree.wire_detail.sync_to_wire()
        self._tree.fmu_detail.sync_to_node()
        nodes_by_uid: Dict[str, NodeItem] = {
            node.uid: node for node in self._graph.scene.nodes()
        }

        def _item_to_assembly_node(parent_assembly_node: Optional[AssemblyNode],
                                   item) -> Optional[AssemblyNode]:
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
            return None

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
            # First propagate user-exposed outputs up through nested containers
            self._propagate_exposed_outputs(assembly.root)
            # Then distribute links into the correct assembly nodes
            self._apply_links_on_assembly_node(assembly.root, links_list)

        return assembly

    def save_as_json(self, output_path):
        """Export the current assembly as a JSON file."""
        assembly = self.create_assembly()
        if assembly:
            assembly.write_json(output_path)
            self._dirty = False

    def save_as_fmu(self, output_path, fmi_version=2, datalog=False):
        """Build and save the assembly as an FMU container."""
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
