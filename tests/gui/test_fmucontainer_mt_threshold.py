"""The threshold of the multi-threaded mode (`mt_threshold`) in the options of a container of the GUI."""
import json
import shutil

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
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


def test_the_threshold_is_an_option_of_the_container(window):
    assert TreeItemRoles.get_container_params(window._tree.root).parameters["mt_threshold"] == 5e-05


def test_the_threshold_is_saved_and_loaded(window, ball, tmp_path):
    window._graph.scene.add_node(ball / "bb_position.fmu")
    window._graph.scene.add_node(ball / "bb_velocity.fmu")
    parameters = TreeItemRoles.get_container_params(window._tree.root).parameters
    parameters["mt"] = True
    parameters["mt_threshold"] = "0.002"                # as typed in the table of the detail panel
    window.save_as_json(tmp_path / "threaded.json")
    assert json.loads((tmp_path / "threaded.json").read_text())["mt_threshold"] == 0.002

    window.import_assembly_file(str(tmp_path / "threaded.json"))
    assert TreeItemRoles.get_container_params(window._tree.root).parameters["mt_threshold"] == 0.002
