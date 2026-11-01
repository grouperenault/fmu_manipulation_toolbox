"""Open… and Save as… of the Container Builder (plan `container_builder_actions`).

One action opens every file the builder reads (the extension decides: an FMU container is loaded, an assembly file
imported), one saves in every format it writes (the filter or the extension decides). Opening over unsaved changes
asks first, as Exit does.
"""
import shutil

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtWidgets import QApplication, QMessageBox

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow
    from fmu_manipulation_toolbox.gui.helper import LastDirectory
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
def bouncing(data_dir, tmp_path):
    shutil.copy(data_dir / "containers" / "ssp" / "bouncing.ssp", tmp_path / "bouncing.ssp")
    return tmp_path / "bouncing.ssp"


def _answer(monkeypatch, button):
    """Answer *button* to the next unsaved changes dialog, and record that it was shown."""
    shown = []

    def exec_(box):
        shown.append(box.text())
        return button

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    return shown


def _choose(monkeypatch, path):
    """The open dialog returns *path*; the calls are recorded."""
    calls = []

    def get_open_file_name(parent=None, caption="", filter=""):
        calls.append((caption, filter))
        return str(path) if path else ""

    monkeypatch.setattr(LastDirectory, "get_open_file_name", get_open_file_name)
    return calls


# --------------------------------------------------------------------------- #
#                                    Open…                                    #
# --------------------------------------------------------------------------- #
def test_open_is_a_button_with_its_shortcut(window):
    assert window._open_button.text() == "Open…"
    assert window._open_button.shortcut().toString() in ("Ctrl+O", "Meta+O")


def test_open_offers_every_format_first(window, monkeypatch):
    calls = _choose(monkeypatch, None)

    window._on_open_clicked()

    assert calls[0][1].startswith("FMU containers and assembly files (*.fmu *.json *.csv *.ssp)")


def test_open_imports_an_assembly_file(window, monkeypatch, bouncing):
    _choose(monkeypatch, bouncing)

    window._on_open_clicked()

    assert {node.name for node in window._graph.scene.fmu_nodes()} == {"bb_velocity.fmu", "bb_position.fmu"}


def test_open_loads_an_fmu_container(window, monkeypatch, tmp_path):
    container = tmp_path / "container.fmu"
    container.write_bytes(b"")
    loaded = []
    monkeypatch.setattr(window, "load_file", loaded.append)
    _choose(monkeypatch, container)

    window._on_open_clicked()

    assert loaded == [str(container)]


def test_open_over_unsaved_changes_asks_and_may_be_cancelled(window, monkeypatch, bouncing):
    window._dirty = True
    shown = _answer(monkeypatch, QMessageBox.StandardButton.No)
    calls = _choose(monkeypatch, bouncing)

    window._on_open_clicked()

    assert shown == ["You have unsaved changes. Are you sure you want to open another file?"]
    assert calls == []  # cancelled before the file dialog
    assert window._graph.scene.fmu_nodes() == []


def test_open_over_unsaved_changes_goes_on_when_confirmed(window, monkeypatch, bouncing):
    window._dirty = True
    _answer(monkeypatch, QMessageBox.StandardButton.Yes)
    _choose(monkeypatch, bouncing)

    window._on_open_clicked()

    assert len(window._graph.scene.fmu_nodes()) == 2


def test_open_without_changes_does_not_ask(window, monkeypatch, bouncing):
    shown = _answer(monkeypatch, QMessageBox.StandardButton.No)
    _choose(monkeypatch, bouncing)

    window._on_open_clicked()

    assert shown == []
    assert len(window._graph.scene.fmu_nodes()) == 2


def test_exit_still_asks(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    window._dirty = True
    shown = _answer(monkeypatch, QMessageBox.StandardButton.No)
    event = QCloseEvent()

    window.closeEvent(event)

    assert shown == ["You have unsaved changes. Are you sure you want to quit?"]
    assert not event.isAccepted()
