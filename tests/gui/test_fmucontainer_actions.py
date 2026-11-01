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


# --------------------------------------------------------------------------- #
#                                  Save as…                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path, chosen, expected", [
    ("model.ssp", "FMU Container (*.fmu)", ("model.ssp", ".ssp")),  # the extension typed wins
    ("model.JSON", "SSP (*.ssp)", ("model.JSON", ".json")),
    ("model", "SSP (*.ssp)", ("model.ssp", ".ssp")),               # none: the filter, its extension appended
    ("model.v2", "JSON (*.json)", ("model.v2.json", ".json")),
    ("model.csv", "FMU Container (*.fmu)", ("model.csv.fmu", ".fmu")),  # CSV is not a format of Save as… (B5)
])
def test_the_format_follows_the_extension_or_the_filter(path, chosen, expected):
    assert MainWindow.save_target(path, chosen) == expected


def _save_dialog(monkeypatch, path, chosen):
    """The save dialog returns (*path*, *chosen*); its arguments are recorded."""
    calls = []

    def dialog(parent=None, caption="", filter="", selected_filter="", default_name=""):
        calls.append({"filter": filter, "selected": selected_filter, "default_name": default_name})
        return (str(path) if path else ""), chosen

    monkeypatch.setattr(LastDirectory, "get_save_file_name_and_filter", dialog)
    return calls


def _record_saves(monkeypatch, window):
    saves = []
    monkeypatch.setattr(window, "save_as_fmu", lambda path, fmi, datalog: saves.append(("fmu", path, fmi, datalog)))
    monkeypatch.setattr(window, "save_as_ssp", lambda path: saves.append(("ssp", path)))
    monkeypatch.setattr(window, "save_as_json", lambda path: saves.append(("json", path)))
    return saves


def test_save_as_is_a_button_with_its_shortcut(window):
    assert window._save_as_button.text() == "Save as…"
    assert window._save_as_button.shortcut().toString() in ("Ctrl+S", "Meta+S")


def test_save_as_offers_fmu_container_first_then_the_last_format(window, monkeypatch, tmp_path):
    """B2: FMU Container at first, then the format chosen last in the session."""
    saves = _record_saves(monkeypatch, window)
    first = _save_dialog(monkeypatch, tmp_path / "model.ssp", "SSP (*.ssp)")
    window._on_save_as_clicked()
    second = _save_dialog(monkeypatch, None, "")
    window._on_save_as_clicked()

    assert first[0]["filter"].split(";;") == ["FMU Container (*.fmu)", "SSP (*.ssp)", "JSON (*.json)"]
    assert first[0]["selected"] == "FMU Container (*.fmu)"
    assert first[0]["default_name"].endswith(".fmu")
    assert second[0]["selected"] == "SSP (*.ssp)"
    assert second[0]["default_name"].endswith(".ssp")
    assert saves == [("ssp", str(tmp_path / "model.ssp"))]


@pytest.mark.parametrize("name, chosen, kind", [
    ("model.fmu", "FMU Container (*.fmu)", "fmu"),
    ("model.ssp", "SSP (*.ssp)", "ssp"),
    ("model", "JSON (*.json)", "json"),
])
def test_save_as_writes_the_format_chosen(window, monkeypatch, tmp_path, name, chosen, kind):
    saves = _record_saves(monkeypatch, window)
    _save_dialog(monkeypatch, tmp_path / name, chosen)

    window._on_save_as_clicked()

    assert [save[0] for save in saves] == [kind]
    assert saves[0][1].endswith("." + kind)


def test_save_as_an_fmu_container_takes_the_configuration(window, monkeypatch, tmp_path):
    """The FMI version and the datalog stay in the Configuration menu."""
    saves = _record_saves(monkeypatch, window)
    window._fmi_group.button(3).setChecked(True)
    window._datalog_checkbox.setChecked(True)
    _save_dialog(monkeypatch, tmp_path / "model.fmu", "FMU Container (*.fmu)")

    window._on_save_as_clicked()

    assert saves == [("fmu", str(tmp_path / "model.fmu"), 3, True)]


def test_save_as_cancelled_writes_nothing(window, monkeypatch):
    saves = _record_saves(monkeypatch, window)
    _save_dialog(monkeypatch, None, "")

    window._on_save_as_clicked()

    assert saves == []
    assert window._save_format == ".fmu"


def test_save_as_ssp_clears_the_unsaved_changes(window, monkeypatch, bouncing, tmp_path):
    _choose(monkeypatch, bouncing)
    window._on_open_clicked()
    window._dirty = True
    (tmp_path / "out").mkdir()

    window.save_as_ssp(str(tmp_path / "out" / "bouncing.ssp"))

    assert window._dirty is False
