"""
FMU Container Builder – Assembly I/O logic.

Mixin class handling conversion between the scene/tree representation
and Assembly objects (load, import, export, save).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyNode, AssemblyError
from fmu_manipulation_toolbox.container import FMUContainerError
from fmu_manipulation_toolbox.split import FMUSplitter, FMUSplitterError

from .graph import NodeItem, ConfigurationNode
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
                                links_list: list[list[str]], start_values_list: list[list[str]],
                                output_ports_list: list[list[str]], input_ports_list: list[list[str]],
                                x=0, y=0):
        """Recursively convert an AssemblyNode into tree items and graph nodes.

        The names of the FMUs are unique in a container only, but the nodes of the scene are designated by a name
        unique in the scene: each FMU of this level gets a scene name (`NodeGraphScene.free_name`), and the links,
        start values and exposed ports collected here refer to the nodes by these names.
        """
        # Add FMU nodes
        scene_names: dict[str, str] = {}  # name in the assembly node -> name of the node in the scene
        self._tree.pending_parent = parent
        for fmu in assembly_node.fmu_names_list:
            fmu_path = folder / assembly_node.fmu_path(fmu)
            logger.debug(f"ADD FMU: {fmu} ({fmu_path})")
            node = self._graph.add_node(fmu_path=fmu_path, x=x, y=y, name=Path(fmu).name)
            scene_names[fmu] = node.name
            x = x + 100
            y = y + 100
        self._tree.pending_parent = None

        def scene_name(name: str) -> str:
            """Name of the node of the FMU `name` of this level; sub-container names are kept."""
            return scene_names.get(name, name)

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
            reset_ports=assembly_node.reset_ports,
        )
        logger.debug(f"SET CONTAINER: {container_name}: {container_parameters}")
        parent.setData(container_parameters, _NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
        parent.setText(container_name)

        # GUI-only virtual "configuration" node port representing
        # `<container>.ts_multiplier`. Never persisted in the Assembly model;
        # only recreated here when already enabled on import, so the user
        # can (re)wire it visually. No effect for the root container.
        if assembly_node.ts_multiplier:
            self._tree.set_ts_multiplier(parent, True)

        for connection in assembly_node.links:
            link = [scene_name(connection.from_port.fmu_name), connection.from_port.port_name,
                    scene_name(connection.to_port.fmu_name), connection.to_port.port_name]
            logger.debug(f"ADD LINK: {link}")
            links_list.append(link)

        for port, value in assembly_node.start_values.items():
            start = [scene_name(port.fmu_name), port.port_name, value]
            logger.debug(f"ADD START VALUE: {start}")
            start_values_list.append(start)

        for port, target in assembly_node.output_ports.items():
            output = [scene_name(port.fmu_name), port.port_name, target]
            logger.debug(f"ADD OUTPUT PORT: {output}")
            output_ports_list.append(output)

        for port, source in assembly_node.input_ports.items():
            input_port = [source, scene_name(port.fmu_name), port.port_name]
            logger.debug(f"ADD INPUT PORT: {input_port}")
            input_ports_list.append(input_port)

        child_items_by_name: dict[str, object] = {}
        for child_node in assembly_node.children.values():
            logger.debug(f"ADD CONTAINER: {child_node.name}")
            child = self._tree.make_container_item(child_node.name)
            parent.appendRow(child)
            child_items_by_name[child_node.name] = child

            sub_output_ports_list = []
            sub_input_ports_list = []
            self._assembly_node_to_items(child, child_node, folder, links_list,
                                         start_values_list, sub_output_ports_list, sub_input_ports_list, x=x, y=y)

            for input in input_ports_list:
                if input[1] == child_node.name:
                    for sub_input in sub_input_ports_list:
                        if  input[2] == sub_input[0]:
                            input[1] = sub_input[1]
                            input[2] = sub_input[2]
                            logger.debug(f"MODIFIED INPUT PORT: {input}")
                            break

            for output in output_ports_list:
                if output[0] == child_node.name:
                    for sub_output in sub_output_ports_list:
                        if output[1] == sub_output[2]:
                            output[0] = sub_output[0]
                            output[1] = sub_output[2]
                            logger.debug(f"MODIFIED OUTPUT PORT: {output}")
                            break

        for link in links_list:
            # First, resolve any intermediate container boundary-crossing:
            # if this link targets *this* container's own exposed input/output
            # (via `input_ports`/`output_ports`, i.e. `add_input`/`add_output`),
            # rewrite it to point to the actual child (FMU or sub-container)
            # that owns the port. This must run BEFORE the `ts_multiplier`
            # special-case below, because a `container.ts_multiplier` link may
            # be exposed through one or more *intermediate* containers before
            # reaching the (grand-)child that actually has `ts_multiplier`
            # enabled (see tests/containers/VanDerPol/VanDerPol-vr3.json for a
            # 2-level-deep example: root -> inter.fmu -> nested.fmu).
            if link[2] == container_name:
                for port, input_name in assembly_node.input_ports.items():
                    if link[3] == input_name:
                        link[2] = scene_name(port.fmu_name)
                        link[3] = port.port_name
                        logger.debug(f"MODIFIED LINK: {link}")
                        break
            if link[0] == container_name:
                for port, output_name in assembly_node.output_ports.items():
                    if link[1] == output_name:
                        link[0] = scene_name(port.fmu_name)
                        link[1] = port.port_name
                        logger.debug(f"MODIFIED LINK: {link}")
                        break

            # Special case: the link's endpoint is a *child container* name
            # (not a real FMU) referencing the reserved `container.ts_multiplier`
            # runtime input exposed internally by that container when its
            # `ts_multiplier` parameter is enabled (see container/builder.py
            # `make_fmu_xml`). Visually, this corresponds to a wire ending on
            # the GUI-only `ConfigurationNode`'s dynamic port for that
            # sub-container (`<child_without_.fmu>.ts_multiplier`), never to a
            # regular FMU node. Thanks to the resolution above, `link[2]`/
            # `link[0]` here is always a *direct* child of the container
            # currently being processed, however many intermediate containers
            # the link was originally propagated through.
            if link[2] in assembly_node.children and link[3] == ConfigurationNode.RUNTIME_PORT_NAME:
                child_name = link[2]
                link[2] = ConfigurationNode.TITLE
                link[3] = ConfigurationNode.port_name(child_name)
                logger.debug(f"TS_MULTIPLIER LINK detected: -> {child_name} ({link[2]}/{link[3]})")
                # Defensive: a real link targeting this reserved port implies
                # the port must exist, regardless of whether the `ts_multiplier`
                # flag was correctly restored on the child (e.g. known
                # limitation of `fmusplit`, which does not re-emit it).
                child_item = child_items_by_name.get(child_name)
                if child_item is not None:
                    self._tree.set_ts_multiplier(child_item, True)
                    child_params = child_item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
                    if child_params is not None:
                        child_params.parameters["ts_multiplier"] = True
            # Same for the reserved `container.reset` input of an FMU or a sub-container of this level (option
            # `reset_ports`): a wire ending on the `<fmu_without_.fmu>.reset` port of the ConfigurationNode, created
            # by `refresh_reset_ports` once the whole tree is imported.
            if link[3] == ConfigurationNode.RESET_RUNTIME_PORT_NAME and \
                    (link[2] in assembly_node.children or link[2] in scene_names.values()):
                logger.debug(f"RESET LINK detected: -> {link[2]}")
                link[3] = ConfigurationNode.reset_port_name(link[2])
                link[2] = ConfigurationNode.TITLE
            if link[0] in assembly_node.children and link[1] == ConfigurationNode.RUNTIME_PORT_NAME:
                child_name = link[0]
                link[0] = ConfigurationNode.TITLE
                link[1] = ConfigurationNode.port_name(child_name)
                logger.debug(f"TS_MULTIPLIER LINK detected: {child_name} ({link[0]}/{link[1]}) ->")
                child_item = child_items_by_name.get(child_name)
                if child_item is not None:
                    self._tree.set_ts_multiplier(child_item, True)
                    child_params = child_item.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
                    if child_params is not None:
                        child_params.parameters["ts_multiplier"] = True


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

        links_list: list[list[str]] = []
        start_values_list: list[list[str]] = []
        output_ports_list: list[list[str]] = []
        input_ports_list: list[list[str]] = []
        self._assembly_node_to_items(self._tree.root, assembly.root, fmu_directory,
                                     links_list, start_values_list, output_ports_list, input_ports_list)

        # Map from node name (unique in the scene) to its NodeItem (real FMUs only, excludes
        # the virtual ConfigurationNode which is never part of the Assembly model)
        nodes_by_name: dict[str, NodeItem] = {node.name: node for node in self._graph.scene.fmu_nodes()}

        # The reset ports of the ConfigurationNode follow the `reset_ports` parameters, now all set.
        self._tree.refresh_reset_ports()

        # The GUI-only ConfigurationNode (ts_multiplier), if already created by
        # `_assembly_node_to_items` above (via `set_ts_multiplier`). Links may
        # reference it by its reserved bare name (see `_assembly_node_to_items`
        # TS_MULTIPLIER special-case) instead of a real FMU path.
        configuration_node = self._graph.scene.configuration_node()

        def _resolve_node(name: str) -> NodeItem | None:
            """Return the NodeItem (real FMU or the singleton ConfigurationNode)
            matching *name*."""
            if name == ConfigurationNode.TITLE:
                return configuration_node
            return nodes_by_name.get(name)

        # Group links by (source_fmu, dest_fmu) pair to create one wire per pair. The links refer to the nodes by
        # their name in the scene (see `_assembly_node_to_items`).
        wire_key_mappings: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
        for link in links_list:
            fmu_from_name, port_from, fmu_to_name, port_to = link[0], link[1], link[2], link[3]
            # Canonical key: sorted pair so A→B and B→A end up on the same wire
            key = tuple(sorted([fmu_from_name, fmu_to_name]))
            wire_key_mappings.setdefault(key, []).append((fmu_from_name, port_from, fmu_to_name, port_to))

        # Create wires with their port-level mappings
        self._graph.scene.blockSignals(True)
        try:
            for (name1, name2), mappings in wire_key_mappings.items():
                node1 = configuration_node if name1 == ConfigurationNode.TITLE else nodes_by_name.get(name1)
                node2 = configuration_node if name2 == ConfigurationNode.TITLE else nodes_by_name.get(name2)
                if not node1 or not node2:
                    logger.warning(f"Cannot create wire: node not found for {name1} ↔ {name2}")
                    continue

                # Split mappings into port-links and terminal-links. A link is
                # considered a terminal-link when *both* endpoints are declared
                # as terminals on their respective FMUs (see terminalsAndIcons).
                port_mappings: list[tuple[str, str, str, str]] = []
                terminal_mappings: list[tuple[str, str, str, str]] = []
                for m in mappings:
                    fmu_a, name_a, fmu_b, name_b = m
                    # Resolve which node hosts which endpoint (mappings preserve
                    # the original from→to direction, independent of node_a/b).
                    node_a = _resolve_node(fmu_a)
                    node_b = _resolve_node(fmu_b)
                    is_term_a = node_a is not None and name_a in node_a.fmu_terminal_names
                    is_term_b = node_b is not None and name_b in node_b.fmu_terminal_names
                    if is_term_a and is_term_b:
                        terminal_mappings.append(m)
                        logger.debug(f"TERMINAL LINK detected: {fmu_a}/{name_a} ↔ {fmu_b}/{name_b}")
                    else:
                        port_mappings.append(m)

                wire = self._graph.scene.add_wire(node1, node2)
                if wire:
                    wire.mappings = port_mappings
                    wire.terminal_mappings = terminal_mappings
                    logger.debug(f"Wire created: {name1} ↔ {name2} with "
                                 f"{len(port_mappings)} port mapping(s), "
                                 f"{len(terminal_mappings)} terminal mapping(s)")
                else:
                    # Wire already exists — append mappings
                    for w in node1.wires:
                        other = w.node_b if w.node_a is node1 else w.node_a
                        if other is node2:
                            w.mappings.extend(port_mappings)
                            w.terminal_mappings.extend(terminal_mappings)
                            break
        finally:
            self._graph.scene.blockSignals(False)
            self._graph.scene.clearSelection()

        # Apply start values to scene nodes
        for fmu_name, port_name, value in start_values_list:
            node = nodes_by_name.get(fmu_name)
            if node:
                node.user_start_values[port_name] = value
                logger.debug(f"Start value: {fmu_name}/{port_name} = {value}")
            else:
                logger.warning(f"Cannot apply start value: node not found for {fmu_name}")

        # Apply exposed output ports to scene nodes
        for fmu_name, port_name, _exposed_name in output_ports_list:
            node = nodes_by_name.get(fmu_name)
            if node:
                node.user_exposed_outputs[port_name] = True
                logger.debug(f"Exposed output: {fmu_name}/{port_name}")

        # Apply exposed input ports to scene nodes
        for _exposed_name, fmu_name, port_name in input_ports_list:
            if port_name == ConfigurationNode.RESET_RUNTIME_PORT_NAME:
                # Exposed reset of an FMU or a sub-container: checked in the detail panel of the ConfigurationNode
                if configuration_node is not None:
                    configuration_node.reset_exposed[ConfigurationNode.reset_port_name(fmu_name)] = True
                    logger.debug(f"Exposed reset: {fmu_name}")
                continue
            node = nodes_by_name.get(fmu_name)
            if node:
                node.user_exposed_inputs[port_name] = True
                logger.debug(f"Exposed input: {fmu_name}/{port_name}")

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
            with FMUSplitter(input_path) as splitter:
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
    def _propagate_exposed_inputs(assembly_node: AssemblyNode):
        """Propagate user-exposed input ports from child nodes up to the root.

        For each child container that has input_ports, expose those ports
        at the current level as well, then recurse upward (called bottom-up).
        This must be called BEFORE _apply_links_on_assembly_node so that only
        user-exposed inputs are propagated (not routing inputs from links).
        """
        # First, recurse into children so their inputs are fully resolved
        for child in assembly_node.children.values():
            AssemblyIOMixin._propagate_exposed_inputs(child)

        # Now, for each child container, if it has exposed input ports,
        # also expose them at this level (so they bubble up to root)
        for child in assembly_node.children.values():
            for port, exposed_name in child.input_ports.items():
                assembly_node.add_input(exposed_name, child.name, exposed_name)
                logger.debug(f"PROPAGATE INPUT: {assembly_node.name} → {child.name}/{exposed_name}")

    @staticmethod
    def _apply_links_on_assembly_node(assembly_node: AssemblyNode,
                                      links_list: list[tuple]) -> list[tuple]:
        """Distribute links into the correct assembly nodes recursively."""
        for sub_assembly_node in assembly_node.children.values():
            links_list = AssemblyIOMixin._apply_links_on_assembly_node(
                sub_assembly_node, links_list)

        logger.debug(f"Links applied: {len(links_list)}")
        logger.debug(f"Assembly node: {assembly_node.name}")

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
                # Source is outside, destination is local → expose as input. The reset inputs of the FMUs
                # share one port name: the input is named after the FMU.
                if link[3] == ConfigurationNode.RESET_RUNTIME_PORT_NAME:
                    input_name = ConfigurationNode.reset_input_name(link[2])
                else:
                    input_name = link[3]
                assembly_node.add_input(input_name, link[2], link[3])
                remaining_links_list.append((link[0], link[1], assembly_node.name, input_name))
            else:
                # Neither end belongs to this node → pass through
                remaining_links_list.append(link)

        return remaining_links_list

    def create_assembly(self) -> Assembly | None:
        """Build an Assembly object from the current scene and tree state."""
        # Flush any in-progress edits from detail panels
        self._tree.wire_detail.sync_to_wire()
        self._tree.fmu_detail.sync_to_node()
        # Only real FMU nodes are eligible: the virtual ConfigurationNode
        # (ts_multiplier, GUI-only) is never part of the Assembly model.
        nodes_by_uid: dict[str, NodeItem] = {
            node.uid: node for node in self._graph.scene.fmu_nodes()
        }
        configuration_node = self._graph.scene.configuration_node()

        def _reset_exposed(name: str) -> bool:
            """Whether the reset port of the FMU or sub-container *name* is checked "exposed"."""
            if configuration_node is None:
                return False
            port = ConfigurationNode.reset_port_name(name)
            return configuration_node.port_active(port) and configuration_node.reset_exposed.get(port, False)

        def _reference(node: NodeItem) -> str:
            """Name of `node` in the Assembly: its FMU file, or, for an instance, a sibling of the file named after
            the node (the `path` block of the assembly gives the file)."""
            return str(node.fmu_path.with_name(node.name))

        def _item_to_assembly_node(parent_assembly_node: AssemblyNode | None,
                                    item) -> AssemblyNode | None:
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
                            if assembly_node.reset_ports and _reset_exposed(sub_assembly_node.name):
                                assembly_node.add_input(ConfigurationNode.reset_input_name(sub_assembly_node.name),
                                                        sub_assembly_node.name,
                                                        ConfigurationNode.RESET_RUNTIME_PORT_NAME)
                return assembly_node
            else:
                uid = item.data(_NodeTreeModel.ROLE_NODE_UID)
                node = nodes_by_uid.get(uid)
                if node is None:
                    logger.warning(f"Node with uid {uid} not found in scene, skipping.")
                    return None
                reference = _reference(node)
                logger.info(f"ADD: FMU: {node.name} ({node.fmu_path})")
                parent_assembly_node.add_fmu(reference, str(node.fmu_path))
                # Apply user-defined start values
                for port_name, value in node.user_start_values.items():
                    logger.debug(f"START VALUE: {node.name}/{port_name} = {value}")
                    parent_assembly_node.add_start_value(reference, port_name, value)
                # Apply user-exposed output ports
                for port_name, exposed in node.user_exposed_outputs.items():
                    if exposed:
                        logger.debug(f"EXPOSE OUTPUT: {node.name}/{port_name}")
                        parent_assembly_node.add_output(reference, port_name, port_name)
                # Apply user-exposed input ports
                for port_name, exposed in node.user_exposed_inputs.items():
                    if exposed:
                        logger.debug(f"EXPOSE INPUT: {node.name}/{port_name}")
                        parent_assembly_node.add_input(port_name, reference, port_name)
                if parent_assembly_node.reset_ports and _reset_exposed(node.name):
                    parent_assembly_node.add_input(ConfigurationNode.reset_input_name(node.name), reference,
                                                   ConfigurationNode.RESET_RUNTIME_PORT_NAME)
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

        links_list: list[tuple[str, str, str, str]] = []
        # Name in the Assembly of each node, by node name (real FMUs only)
        path_by_name: dict[str, str] = {node.name: _reference(node) for node in self._graph.scene.fmu_nodes()}

        for wire in self._graph.scene.wires():
            is_cfg_a = isinstance(wire.node_a, ConfigurationNode)
            is_cfg_b = isinstance(wire.node_b, ConfigurationNode)
            for link in wire.mappings:
                if len(link) == 4:
                    fmu_from_name, port_from, fmu_to_name, port_to = link
                elif len(link) == 2:
                    # Legacy 2-tuple: assume node_a → node_b
                    fmu_from_name, fmu_to_name = wire.node_a.name, wire.node_b.name
                    port_from, port_to = link
                else:
                    continue

                # A mapping targeting the (GUI-only) ConfigurationNode's
                # `ts_multiplier` port is, in fact, a real link driving the
                # target sub-container's reserved `container.ts_multiplier`
                # runtime input (see container/builder.py `make_fmu_xml`). Reverse the
                # visual routing back to that real link so it round-trips
                # correctly on export. Inactive ports (checkbox unchecked,
                # shown in red) are skipped: the target port would not even
                # exist on the built container.
                # A reset port drives the reserved `container.reset` input of its FMU, or sub-container, in the
                # same way.
                if is_cfg_b and fmu_to_name == ConfigurationNode.TITLE:
                    if not wire.node_b.port_active(port_to):
                        logger.debug(f"SKIP inactive configuration link: {fmu_from_name}/{port_from} -> {port_to}")
                        continue
                    if wire.node_b.is_reset_port(port_to):
                        fmu_to_name = ConfigurationNode.fmu_name_from_reset_port(port_to)
                        fmu_to_path = path_by_name.get(fmu_to_name, fmu_to_name)   # a sub-container keeps its name
                        port_to = ConfigurationNode.RESET_RUNTIME_PORT_NAME
                    else:
                        fmu_to_path = ConfigurationNode.container_name_from_port(port_to)
                        port_to = ConfigurationNode.RUNTIME_PORT_NAME
                    fmu_from_path = path_by_name[fmu_from_name]
                elif is_cfg_a and fmu_from_name == ConfigurationNode.TITLE:
                    if not wire.node_a.port_active(port_from):
                        logger.debug(f"SKIP inactive configuration link: {port_from} -> {fmu_to_name}/{port_to}")
                        continue
                    if wire.node_a.is_reset_port(port_from):
                        fmu_from_name = ConfigurationNode.fmu_name_from_reset_port(port_from)
                        fmu_from_path = path_by_name.get(fmu_from_name, fmu_from_name)
                        port_from = ConfigurationNode.RESET_RUNTIME_PORT_NAME
                    else:
                        fmu_from_path = ConfigurationNode.container_name_from_port(port_from)
                        port_from = ConfigurationNode.RUNTIME_PORT_NAME
                    fmu_to_path = path_by_name[fmu_to_name]
                else:
                    fmu_from_path = path_by_name[fmu_from_name]
                    fmu_to_path = path_by_name[fmu_to_name]

                logger.info(f"{Path(fmu_from_path).name}/{port_from} → {Path(fmu_to_path).name}/{port_to}")
                links_list.append((fmu_from_path, port_from, fmu_to_path, port_to))

            # Terminal mappings are treated as regular links (terminals behave as ports)
            for tm in wire.terminal_mappings:
                if len(tm) == 4:
                    fmu_a_name, terminal_a, fmu_b_name, terminal_b = tm
                    fmu_a_path = path_by_name[fmu_a_name]
                    fmu_b_path = path_by_name[fmu_b_name]
                    logger.info(f"{fmu_a_name}/{terminal_a} ↔ {fmu_b_name}/{terminal_b} (terminal)")
                    links_list.append((fmu_a_path, terminal_a, fmu_b_path, terminal_b))

        if assembly.root:
            # First propagate user-exposed outputs/inputs up through nested containers
            self._propagate_exposed_outputs(assembly.root)
            self._propagate_exposed_inputs(assembly.root)
            # Then distribute links into the correct assembly nodes
            self._apply_links_on_assembly_node(assembly.root, links_list)

        return assembly

    def save_as_json(self, output_path):
        """Export the current assembly as a JSON file.

        Raises:
            AssemblyError: If the assembly cannot be built from the current
                scene/tree state.
        """
        assembly = self.create_assembly()
        if assembly is None:
            raise AssemblyError("Cannot build the assembly from the current content.")
        assembly.write_json(output_path)
        self._dirty = False

    def save_as_fmu(self, output_path, fmi_version=2, datalog=False):
        """Build and save the assembly as an FMU container.

        Raises:
            AssemblyError: If the assembly cannot be built from the current
                scene/tree state.
            FMUContainerError: If the container itself cannot be built. The
                error is propagated so that callers never mistake a failed
                build for a successful one.
        """
        assembly = self.create_assembly()
        if assembly is None:
            raise AssemblyError("Cannot build the assembly from the current content.")

        with tempfile.TemporaryDirectory() as tmp_dir:
            json_file_path = Path(tmp_dir) / "container.json"
            assembly.write_json(json_file_path, basenames_only=True)
            assembly.description_pathname = json_file_path
            assembly.make_fmu(filename=output_path, fmi_version=fmi_version, datalog=datalog)
            self._dirty = False

