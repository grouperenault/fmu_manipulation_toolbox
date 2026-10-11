"""Several instances of the same FMU in the Container Builder GUI.

A node is designated by its name, unique in the scene, and distinct from its FMU file: adding a file again gives an
instance named `<stem>-<n>.fmu`. Wires, start values and exposed ports follow the node by its name, and the JSON
keeps the file of each instance in its `path` block.
"""
import json
import shutil

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"GUI dependencies not available: {exc}", allow_module_level=True)

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qapp):
    window = MainWindow()
    try:
        yield window
    finally:
        # A dirty window would pop a modal "save your changes?" dialog on close, which never returns under the
        # offscreen platform; the scene signals are blocked so that the teardown does not touch deleted items.
        window._dirty = False
        window._graph.scene.blockSignals(True)
        window.close()
        window.deleteLater()
        QApplication.processEvents()


@pytest.fixture
def ball(data_dir):
    return data_dir / "containers" / "bouncing_ball"


def _two_balls(window, ball):
    """Two bouncing balls: two instances of each FMU, each pair linked on its own wire."""
    scene = window._graph.scene
    position, velocity = scene.add_node(ball / "bb_position.fmu"), scene.add_node(ball / "bb_velocity.fmu")
    position_1, velocity_1 = scene.add_node(ball / "bb_position.fmu"), scene.add_node(ball / "bb_velocity.fmu")
    for source, target in ((velocity, position), (velocity_1, position_1)):
        wire = scene.add_wire(source, target)
        wire.mappings = [(source.name, "velocity", target.name, "velocity")]
        _refresh_details(window)
    position_1.user_start_values["position1"] = "2"
    position_1.user_exposed_outputs["position1"] = True
    _refresh_details(window)
    return position, velocity, position_1, velocity_1


def _refresh_details(window):
    """Reload the detail panels after a programmatic change, as the MCP bridge does: otherwise they write their
    stale content back into the selected node or wire."""
    details = window._tree
    if details.wire_detail._wire is not None:
        details.wire_detail._load_from_wire()
    if details.fmu_detail._current_node is not None:
        details.fmu_detail._load_from_node(details.fmu_detail._current_node)


def _nodes(window):
    return {node.name: node for node in window._graph.scene.fmu_nodes()}


def test_adding_a_file_again_gives_an_instance(window, ball):
    position, velocity, position_1, velocity_1 = _two_balls(window, ball)

    assert (position.name, position_1.name) == ("bb_position.fmu", "bb_position-1.fmu")
    assert (velocity.name, velocity_1.name) == ("bb_velocity.fmu", "bb_velocity-1.fmu")
    assert position_1.fmu_path == position.fmu_path
    assert position_1.title == "bb_position-1.fmu"


def test_the_assembly_keeps_the_file_of_each_instance(window, ball, tmp_path):
    _two_balls(window, ball)
    window.save_as_json(tmp_path / "two.json")
    written = json.loads((tmp_path / "two.json").read_text())

    files = {name: written["path"].get(name, name) for name in written["fmu"]}
    assert {name.rsplit("/", 1)[-1]: path.rsplit("/", 1)[-1] for name, path in files.items()} == {
        "bb_position.fmu": "bb_position.fmu", "bb_velocity.fmu": "bb_velocity.fmu",
        "bb_position-1.fmu": "bb_position.fmu", "bb_velocity-1.fmu": "bb_velocity.fmu"}
    links = sorted([link[0].rsplit("/", 1)[-1], link[2].rsplit("/", 1)[-1]] for link in written["link"])
    assert links == [["bb_velocity-1.fmu", "bb_position-1.fmu"], ["bb_velocity.fmu", "bb_position.fmu"]]
    assert [start[0].rsplit("/", 1)[-1] for start in written["start"]] == ["bb_position-1.fmu"]


def test_saving_then_loading_keeps_the_instances(window, ball, tmp_path):
    _two_balls(window, ball)
    window.save_as_json(tmp_path / "two.json")

    window.import_assembly_file(str(tmp_path / "two.json"))
    nodes = _nodes(window)

    assert sorted(nodes) == ["bb_position-1.fmu", "bb_position.fmu", "bb_velocity-1.fmu", "bb_velocity.fmu"]
    assert nodes["bb_position-1.fmu"].fmu_path.resolve() == (ball / "bb_position.fmu").resolve()
    assert nodes["bb_position-1.fmu"].user_start_values == {"position1": "2"}
    assert [port for port, exposed in nodes["bb_position-1.fmu"].user_exposed_outputs.items() if exposed] == [
        "position1"]
    mappings = sorted(mapping for wire in window._graph.scene.wires() for mapping in wire.mappings)
    assert mappings == [("bb_velocity-1.fmu", "velocity", "bb_position-1.fmu", "velocity"),
                        ("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")]


def test_replacing_the_fmu_of_an_instance(window, ball):
    position, velocity, position_1, velocity_1 = _two_balls(window, ball)
    scene = window._graph.scene

    scene.replace_node_fmu(position_1, ball / "bb_velocity.fmu")

    assert position_1.name == "bb_velocity-2.fmu"   # smallest free name for the new file
    assert position.name == "bb_position.fmu" and position.fmu_path == ball / "bb_position.fmu"
    wire = next(wire for wire in position_1.wires)
    assert wire.mappings == [("bb_velocity-1.fmu", "velocity", "bb_velocity-2.fmu", "velocity")]


def test_a_removed_instance_frees_its_name(window, ball):
    scene = window._graph.scene
    first, second, third = (scene.add_node(ball / "bb_position.fmu") for _ in range(3))
    assert third.name == "bb_position-2.fmu"

    scene.clearSelection()
    second.setSelected(True)
    scene.remove_selected()

    assert scene.add_node(ball / "bb_position.fmu").name == "bb_position-1.fmu"


def test_another_file_with_the_same_name_is_an_instance(window, ball, tmp_path):
    twin = tmp_path / "bb_position.fmu"
    shutil.copy(ball / "bb_position.fmu", twin)
    scene = window._graph.scene

    scene.add_node(ball / "bb_position.fmu")
    node = scene.add_node(twin)

    assert node.name == "bb_position-1.fmu" and node.fmu_path == twin


def test_the_same_fmu_in_two_sub_containers(window, ball, tmp_path):
    """Names are unique per container in the JSON, but unique in the scene in the GUI."""
    for name in ("bb_position.fmu", "bb_velocity.fmu"):
        shutil.copy(ball / name, tmp_path / name)
    container = {"auto_link": False, "fmu": ["bb_position.fmu", "bb_velocity.fmu"],
                 "link": [["bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"]],
                 "start": [["bb_position.fmu", "position1", "1"]]}
    (tmp_path / "nested.json").write_text(json.dumps({
        "name": "nested.fmu",
        "container": [{"name": "first.fmu", **container},
                      {"name": "second.fmu", **container, "start": [["bb_position.fmu", "position1", "2"]]}]}))

    window.import_assembly_file(str(tmp_path / "nested.json"))
    nodes = _nodes(window)

    assert sorted(nodes) == ["bb_position-1.fmu", "bb_position.fmu", "bb_velocity-1.fmu", "bb_velocity.fmu"]
    assert {nodes["bb_position.fmu"].user_start_values["position1"],
            nodes["bb_position-1.fmu"].user_start_values["position1"]} == {"1", "2"}
    mappings = sorted(mapping for wire in window._graph.scene.wires() for mapping in wire.mappings)
    assert mappings == [("bb_velocity-1.fmu", "velocity", "bb_position-1.fmu", "velocity"),
                        ("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")]
