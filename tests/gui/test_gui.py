"""Tests for the 3 GUI interfaces (FMU Tool, FMU Editor, FMU Container Builder).

Migrated from the legacy ``test_suite.py``. These tests verify that the windows
can be instantiated and that basic programmatic interactions work. They require
`PySide6` and `pytest-qt`; the whole module is skipped if the GUI stack (or a
usable Qt platform) is unavailable. Qt is forced to the offscreen platform in
``conftest.py``.
"""
import pytest

# Skip the whole module if the GUI dependencies are not importable.
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmutool.__main__ import MainWindow as FMUToolWindow
    from fmu_manipulation_toolbox.gui.fmueditor.__main__ import MainWindow as FMUEditorWindow
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow as FMUContainerWindow
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"GUI dependencies not available: {exc}", allow_module_level=True)

pytestmark = pytest.mark.gui


@pytest.fixture
def bouncing_ball(data_dir):
    """Absolute path to the sample FMU used by the load tests."""
    return str(data_dir / "operations" / "bouncing_ball.fmu")


# ── FMU Tool GUI ──────────────────────────────────────────────────────────
def test_fmutool_window_opens(qtbot):
    window = FMUToolWindow()
    qtbot.addWidget(window)
    assert window.isVisible()
    assert window.windowTitle() == "FMU Manipulation Toolbox"


def test_fmutool_load_fmu(qtbot, bouncing_ball):
    window = FMUToolWindow()
    qtbot.addWidget(window)
    window.load(bouncing_ball)
    assert "bouncing_ball.fmu" in window.fmu_title.text()


def test_fmutool_operations_buttons_exist(qtbot):
    window = FMUToolWindow()
    qtbot.addWidget(window)
    assert len(window.operations_button_list) == 15


# ── FMU Editor GUI ────────────────────────────────────────────────────────
def test_fmueditor_window_opens(qtbot):
    window = FMUEditorWindow()
    qtbot.addWidget(window)
    assert window.isVisible()
    assert window.windowTitle() == "FMU Variable Editor"


def test_fmueditor_load_fmu(qtbot, bouncing_ball):
    window = FMUEditorWindow()
    qtbot.addWidget(window)
    window.load(bouncing_ball)
    assert window._model.rowCount() > 0


def test_fmueditor_no_unsaved_changes_initially(qtbot, bouncing_ball):
    window = FMUEditorWindow()
    qtbot.addWidget(window)
    window.load(bouncing_ball)
    assert not window._has_unsaved_changes()


# ── FMU Container Builder GUI ─────────────────────────────────────────────
def test_fmucontainer_window_opens(qtbot):
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert window.isVisible()
    assert window.windowTitle() == "FMU Container Builder"


def test_fmucontainer_initially_clean(qtbot):
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert not window._dirty


def test_fmucontainer_buttons_exist(qtbot):
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert window._load_button is not None
    assert window._import_button is not None
    assert window._export_button is not None
    assert window._save_button is not None
    assert window._exit_button is not None

