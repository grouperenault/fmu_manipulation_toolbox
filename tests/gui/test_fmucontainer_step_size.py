"""Step size column of the tree of the Container Builder GUI.

The second column shows, read-only, the step size of each FMU, and of each container: its `step_size` parameter, or
when empty the step size the builder deduces from its content (in italics).
"""
import shutil

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.container.builder import deduce_step_size
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow
    from fmu_manipulation_toolbox.gui.fmucontainer.tree.model import TreeItemRoles, _NodeTreeModel
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
    for name in ("bb_position.fmu", "bb_velocity.fmu", "velocity_cs2_multiple.fmu"):
        shutil.copy(data_dir / "containers" / "bouncing_ball" / name, tmp_path / name)
    return tmp_path


def _cell(window, item):
    """Step size cell of the row of *item*, once the pending refresh is done."""
    QApplication.processEvents()
    parent = item.parent() or window._tree.model.invisibleRootItem()
    return parent.child(item.row(), _NodeTreeModel.COLUMN_STEP_SIZE)


def _item(window, node):
    return window._tree._tree_widget._find_tree_item_by_uid(window._tree.model.invisibleRootItem(), node.uid)


def _set_step_size(window, item, value: str):
    """Set `step_size` on the container of *item*, as the container detail panel does."""
    TreeItemRoles.get_container_params(item).parameters["step_size"] = value
    window._tree.refresh_step_sizes()


def test_deduce_step_size():
    assert deduce_step_size([(0.1, False), (0.25, False), (2.0, True)]) == 0.5
    assert deduce_step_size([(0.1, True), (0.25, True)]) == 0.25
    assert deduce_step_size([(-1.0, False), (0.0, False)]) is None
    assert deduce_step_size([]) is None


def test_fmu_and_deduced_container_step_sizes(window, ball):
    scene = window._graph.scene
    root = window._tree.root
    assert _cell(window, root).text() == "0.1 s"           # empty container: default step size
    assert _cell(window, root).font().italic()

    position = scene.add_node(ball / "bb_position.fmu")
    assert _cell(window, _item(window, position)).text() == "0.001 s"
    assert not _cell(window, _item(window, position)).font().italic()
    assert _cell(window, root).text() == "0.001 s"
    assert _cell(window, root).font().italic()


def test_explicit_container_step_size(window, ball):
    window._graph.scene.add_node(ball / "bb_position.fmu")
    root = window._tree.root

    _set_step_size(window, root, "0.01")
    assert _cell(window, root).text() == "0.01 s"
    assert not _cell(window, root).font().italic()

    _set_step_size(window, root, "")
    assert _cell(window, root).text() == "0.001 s"
    assert _cell(window, root).font().italic()


def test_sub_container_step_size(window, ball):
    """A sub-container is seen by its parent as an FMU with a variable step size."""
    scene = window._graph.scene
    root = window._tree.root
    sub = window._tree.make_container_item("sub.fmu")
    root.appendRow(sub)                                     # as on load: the cell is created by the refresh
    window._tree.pending_parent = sub
    scene.add_node(ball / "velocity_cs2_multiple.fmu")
    window._tree.pending_parent = None
    scene.add_node(ball / "bb_position.fmu")

    assert _cell(window, sub).text() == "0.1 s"
    assert _cell(window, root).text() == "0.001 s"          # not lcm(0.001, 0.1): the sub-container is variable

    _set_step_size(window, sub, "0.5")
    assert _cell(window, sub).text() == "0.5 s"
    assert _cell(window, root).text() == "0.001 s"


def test_step_size_cells_are_read_only(window, ball):
    node = window._graph.scene.add_node(ball / "bb_position.fmu")
    for item in (window._tree.root, _item(window, node)):
        flags = _cell(window, item).flags()
        assert not flags & Qt.ItemFlag.ItemIsEditable
        assert not flags & Qt.ItemFlag.ItemIsDragEnabled


def test_drop_over_the_step_size_column(window, ball):
    """A drop over the step size cell of a container drops into the container, and refreshes the step sizes."""
    scene = window._graph.scene
    model = window._tree.model
    root = window._tree.root
    sub = window._tree.make_container_item("sub.fmu")
    window._tree._tree_widget._append_row(root, sub)
    node = scene.add_node(ball / "bb_position.fmu")
    item = _item(window, node)
    assert _cell(window, sub).text() == "0.1 s"             # empty

    data = model.mimeData([model.indexFromItem(item)])
    target = model.indexFromItem(_cell(window, sub))
    assert model.canDropMimeData(data, Qt.DropAction.MoveAction, -1, -1, target)
    assert model.dropMimeData(data, Qt.DropAction.MoveAction, -1, -1, target)
    root.removeRow(item.row())                               # what the view does at the end of a move

    moved = sub.child(0, _NodeTreeModel.COLUMN_NAME)
    assert TreeItemRoles.get_node_uid(moved) == node.uid
    assert _cell(window, moved).text() == "0.001 s"
    assert _cell(window, sub).text() == "0.001 s"
