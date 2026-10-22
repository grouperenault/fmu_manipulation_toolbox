"""Reset ports (`reset_ports`) in the Container Builder GUI.

The `configuration` node shows one `<fmu>.reset` port per FMU, or sub-container, of each container with
`reset_ports` checked. A wire ending on it is exported as a link to the reserved `container.reset` input of the FMU,
and a port checked "exposed" in the detail panel of the node as the container input `container.<id>.reset`.
"""
import json
import shutil
from pathlib import PureWindowsPath

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow
    from fmu_manipulation_toolbox.gui.fmucontainer.tree.model import TreeItemRoles
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"GUI dependencies not available: {exc}", allow_module_level=True)

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qapp):
    window = MainWindow()
    try:
        yield window
    finally:
        window._dirty = False
        window._graph.scene.blockSignals(True)
        window.close()
        window.deleteLater()
        QApplication.processEvents()


@pytest.fixture
def ball(data_dir, tmp_path):
    for name in ("bb_position.fmu", "bb_velocity.fmu"):
        shutil.copy(data_dir / "containers" / "bouncing_ball" / name, tmp_path / name)
    return tmp_path


def _base(reference: str) -> str:
    return PureWindowsPath(reference).name


def _set_reset_ports(window, item, checked: bool):
    """Check `reset_ports` on the container of *item*, as the container detail panel does."""
    TreeItemRoles.get_container_params(item).parameters["reset_ports"] = checked
    window._tree.refresh_reset_ports()


def _configuration(window):
    return window._graph.scene.configuration_node()


def _nodes(window):
    return {node.name: node for node in window._graph.scene.fmu_nodes()}


def _wire_to_reset(window, source, port, target_name):
    """Wire *source*/*port* to the reset port of *target_name* on the configuration node."""
    configuration = _configuration(window)
    wire = window._graph.scene.add_wire(source, configuration)
    wire.mappings = [(source.name, port, configuration.name, configuration.reset_port_name(target_name))]
    # Reload the detail panel of the wire, as the MCP bridge does: otherwise it writes its stale content back.
    if window._tree.wire_detail._wire is not None:
        window._tree.wire_detail._load_from_wire()
    return wire


def test_reset_ports_follow_the_checkbox(window, ball):
    """Checking `reset_ports` on the root adds a Boolean reset port per FMU; unchecking removes them."""
    scene = window._graph.scene
    scene.add_node(ball / "bb_position.fmu")
    scene.add_node(ball / "bb_velocity.fmu")
    assert _configuration(window) is None

    _set_reset_ports(window, window._tree.root, True)
    configuration = _configuration(window)
    assert configuration.reset_ports == {"bb_position.reset": True, "bb_velocity.reset": True}
    assert configuration.fmu_port_type["bb_velocity.reset"] == "Boolean"

    scene.add_node(ball / "bb_position.fmu")      # a new FMU of the container gets its port at once
    assert configuration.reset_ports["bb_position-1.reset"] is True

    _set_reset_ports(window, window._tree.root, False)
    assert _configuration(window) is None


def test_a_wired_reset_port_is_exported_as_a_link(window, ball, tmp_path):
    scene = window._graph.scene
    position = scene.add_node(ball / "bb_position.fmu")
    scene.add_node(ball / "bb_velocity.fmu")
    _set_reset_ports(window, window._tree.root, True)
    wire = _wire_to_reset(window, position, "is_ground", "bb_velocity.fmu")

    window.save_as_json(tmp_path / "reset.json")
    written = json.loads((tmp_path / "reset.json").read_text())
    assert written["reset_ports"] is True
    assert [[_base(link[0]), link[1], _base(link[2]), link[3]] for link in written["link"]] == [
        ["bb_position.fmu", "is_ground", "bb_velocity.fmu", "container.reset"]]

    # Unchecked: the port is kept for the wire, drawn in red, and the link is not exported.
    _set_reset_ports(window, window._tree.root, False)
    assert _configuration(window).reset_ports == {"bb_velocity.reset": False}
    assert wire.is_invalid()
    window.save_as_json(tmp_path / "unchecked.json")
    assert "link" not in json.loads((tmp_path / "unchecked.json").read_text())


def test_an_exposed_reset_port_is_exported_as_an_input(window, ball, tmp_path):
    scene = window._graph.scene
    scene.add_node(ball / "bb_position.fmu")
    scene.add_node(ball / "bb_velocity.fmu")
    _set_reset_ports(window, window._tree.root, True)

    configuration = _configuration(window)
    window._tree.configuration_detail.set_node(configuration)
    model = window._tree.configuration_detail._model
    row = next(r for r in range(model.rowCount()) if model.item(r, 0).text() == "bb_velocity.reset")
    model.item(row, 1).setCheckState(Qt.CheckState.Checked)
    assert configuration.reset_exposed == {"bb_velocity.reset": True}

    window.save_as_json(tmp_path / "reset.json")
    written = json.loads((tmp_path / "reset.json").read_text())
    assert [[name, _base(fmu), port] for name, fmu, port in written["input"]] == [
        ["container.bb_velocity.reset", "bb_velocity.fmu", "container.reset"]]


def test_saving_then_loading_keeps_the_reset_ports(window, ball, tmp_path):
    scene = window._graph.scene
    position = scene.add_node(ball / "bb_position.fmu")
    scene.add_node(ball / "bb_velocity.fmu")
    _set_reset_ports(window, window._tree.root, True)
    _wire_to_reset(window, position, "is_ground", "bb_velocity.fmu")
    _configuration(window).reset_exposed["bb_position.reset"] = True
    window.save_as_json(tmp_path / "reset.json")

    window.import_assembly_file(str(tmp_path / "reset.json"))
    configuration = _configuration(window)
    assert configuration.reset_ports == {"bb_position.reset": True, "bb_velocity.reset": True}
    assert configuration.reset_exposed == {"bb_position.reset": True}
    mappings = sorted(mapping for wire in scene.wires() for mapping in wire.mappings)
    assert mappings == [("bb_position.fmu", "is_ground", "configuration", "bb_velocity.reset")]


def test_reset_of_an_fmu_of_a_sub_container(window, ball, tmp_path):
    """A wire from the root to the reset of an FMU of a sub-container crosses its boundary as the input
    `container.<id>.reset` of the sub-container; the round trip gives the same wire."""
    (tmp_path / "nested.json").write_text(json.dumps({
        "name": "nested.fmu", "auto_link": False, "fmu": ["bb_position.fmu"],
        "container": [{"name": "inner.fmu", "auto_link": False, "reset_ports": True, "fmu": ["bb_velocity.fmu"]}],
    }))
    window.import_assembly_file(str(tmp_path / "nested.json"))
    assert _configuration(window).reset_ports == {"bb_velocity.reset": True}   # not on the root

    _wire_to_reset(window, _nodes(window)["bb_position.fmu"], "is_ground", "bb_velocity.fmu")
    window.save_as_json(tmp_path / "saved.json")
    written = json.loads((tmp_path / "saved.json").read_text())
    inner = written["container"][0]
    assert [[name, _base(fmu), port] for name, fmu, port in inner["input"]] == [
        ["container.bb_velocity.reset", "bb_velocity.fmu", "container.reset"]]
    assert [[_base(link[0]), link[1], _base(link[2]), link[3]] for link in written["link"]] == [
        ["bb_position.fmu", "is_ground", "inner.fmu", "container.bb_velocity.reset"]]

    window.import_assembly_file(str(tmp_path / "saved.json"))
    mappings = sorted(mapping for wire in window._graph.scene.wires() for mapping in wire.mappings)
    assert mappings == [("bb_position.fmu", "is_ground", "configuration", "bb_velocity.reset")]


def test_reset_of_a_sub_container(window, ball, tmp_path):
    """With `reset_ports` on the root, a sub-container gets its own reset port."""
    (tmp_path / "nested.json").write_text(json.dumps({
        "name": "nested.fmu", "auto_link": False, "reset_ports": True, "fmu": ["bb_position.fmu"],
        "container": [{"name": "inner.fmu", "auto_link": False, "fmu": ["bb_velocity.fmu"]}],
    }))
    window.import_assembly_file(str(tmp_path / "nested.json"))
    configuration = _configuration(window)
    assert configuration.reset_ports == {"bb_position.reset": True, "inner.reset": True}

    _wire_to_reset(window, _nodes(window)["bb_position.fmu"], "is_ground", "inner.fmu")
    window.save_as_json(tmp_path / "saved.json")
    written = json.loads((tmp_path / "saved.json").read_text())
    assert [[_base(link[0]), link[1], _base(link[2]), link[3]] for link in written["link"]] == [
        ["bb_position.fmu", "is_ground", "inner.fmu", "container.reset"]]


def test_replacing_an_fmu_renames_its_reset_port(window, ball):
    scene = window._graph.scene
    position = scene.add_node(ball / "bb_position.fmu")
    velocity = scene.add_node(ball / "bb_velocity.fmu")
    _set_reset_ports(window, window._tree.root, True)
    wire = _wire_to_reset(window, position, "is_ground", "bb_velocity.fmu")

    scene.replace_node_fmu(velocity, ball / "bb_position.fmu")

    assert velocity.name == "bb_position-1.fmu"
    assert _configuration(window).reset_ports == {"bb_position.reset": True, "bb_position-1.reset": True}
    assert wire.mappings == [("bb_position.fmu", "is_ground", "configuration", "bb_position-1.reset")]
    assert not wire.is_invalid()
