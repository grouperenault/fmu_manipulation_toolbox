"""File given on the command line of the Container Builder GUI (`fmucontainer-gui <file>`).

An FMU container is loaded as with *Load FMU Container*, an assembly file (JSON, CSV, SSP) is imported as with
*Import*; any other file is reported in the log.
"""
import shutil

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow, parse_arguments
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


def test_command_line_without_file():
    assert parse_arguments([]).file is None


def test_command_line_with_file():
    assert parse_arguments(["assembly.ssp"]).file == "assembly.ssp"


def test_assembly_file_is_imported(window, data_dir, tmp_path):
    shutil.copy(data_dir / "containers" / "ssp" / "bouncing.ssp", tmp_path / "bouncing.ssp")

    window.open_file(str(tmp_path / "bouncing.ssp"))

    assert sorted(node.name for node in window._graph.scene.nodes()) == ["bb_position.fmu", "bb_velocity.fmu"]
    assert window._dirty


def test_container_is_loaded(window, data_dir, tmp_path, monkeypatch):
    shutil.copy(data_dir / "containers" / "ssp" / "bouncing.ssp", tmp_path / "bouncing.ssp")
    monkeypatch.chdir(tmp_path)
    from fmu_manipulation_toolbox.assembly import Assembly
    Assembly("bouncing.ssp").make_fmu()

    window.open_file(str(tmp_path / "bouncing.fmu"))

    assert sorted(node.name for node in window._graph.scene.nodes()) == ["bb_position.fmu", "bb_velocity.fmu"]
    assert not window._dirty


@pytest.mark.parametrize("name, message", [
    ("missing.ssp", "file not found"),
    ("notes.txt", "expected an FMU container (.fmu) or an assembly file"),
])
def test_other_files_are_reported(window, tmp_path, caplog, name, message):
    (tmp_path / "notes.txt").write_text("not an assembly")

    window.open_file(str(tmp_path / name))

    assert window._graph.scene.nodes() == []
    assert message in caplog.text
