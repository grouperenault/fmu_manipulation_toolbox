"""Placement of the nodes of an SSP file in the Container Builder GUI, after the geometry of their components.

The SSP coordinates (y upwards) are scaled so that the nodes do not overlap; a file without geometry keeps the
staggered placement.
"""
import shutil
import zipfile

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
        window._dirty = False
        window._graph.scene.blockSignals(True)
        window.close()
        window.deleteLater()
        QApplication.processEvents()


def _nodes(window) -> dict:
    return {node.name: node for node in window._graph.scene.nodes()}


def test_nodes_follow_the_ssp_geometry(window, data_dir, tmp_path):
    shutil.copy(data_dir / "containers" / "ssp" / "bouncing.ssp", tmp_path / "bouncing.ssp")
    window.import_assembly_file(str(tmp_path / "bouncing.ssp"))
    nodes = _nodes(window)
    velocity, position = nodes["bb_velocity.fmu"], nodes["bb_position.fmu"]

    # Side by side, as in the SSP file (bb_velocity on the left), without overlapping.
    assert velocity.sceneBoundingRect().right() <= position.sceneBoundingRect().left()
    assert velocity.pos().y() == pytest.approx(position.pos().y(), abs=velocity.rect().height() / 10)


def test_nodes_without_geometry_are_staggered(window, data_dir, tmp_path):
    with zipfile.ZipFile(data_dir / "containers" / "ssp" / "bouncing.ssp") as source, \
            zipfile.ZipFile(tmp_path / "bouncing.ssp", "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "SystemStructure.ssd":
                ssd = content.decode("utf-8")
                while "<ssd:ElementGeometry " in ssd:
                    start = ssd.index("<ssd:ElementGeometry ")
                    ssd = ssd[:start] + ssd[ssd.index("/>", start) + 2:]
                content = ssd.encode("utf-8")
            target.writestr(name, content)
    window.import_assembly_file(str(tmp_path / "bouncing.ssp"))
    nodes = _nodes(window)

    assert (nodes["bb_velocity.fmu"].pos().x(), nodes["bb_velocity.fmu"].pos().y()) == (0, 0)
    assert (nodes["bb_position.fmu"].pos().x(), nodes["bb_position.fmu"].pos().y()) == (100, 100)
