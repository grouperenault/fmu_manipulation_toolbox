"""Tests for the 3 GUI interfaces (FMU Tool, FMU Editor, FMU Container Builder).

These tests verify that the windows
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


def test_fmutool_logs_into_its_log_widget(qtbot):
    import logging
    window = FMUToolWindow()
    qtbot.addWidget(window)
    logging.getLogger("fmu_manipulation_toolbox").warning("tool warning")
    assert "WARNING: tool warning" in window.log_widget.toPlainText()


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


def test_fmueditor_status_bar_shows_the_log_and_opens_the_log_window(qtbot):
    import logging
    from PySide6.QtCore import Qt
    window = FMUEditorWindow()
    qtbot.addWidget(window)
    logging.getLogger("fmu_manipulation_toolbox").info("FMU saved as 'out.fmu'.")
    assert window._status_bar.text() == "FMU saved as 'out.fmu'."

    qtbot.mouseClick(window._status_bar, Qt.MouseButton.LeftButton)
    log_window = window._status_bar._log_window
    assert log_window.isVisible()
    assert "FMU saved as 'out.fmu'." in log_window.view.toPlainText()


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



def test_fmucontainer_verbose_mode_drives_the_shared_logger(qtbot, capsys):
    import logging
    logger = logging.getLogger("fmu_manipulation_toolbox")
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert logger.level == logging.INFO

    window._debug_checkbox.setChecked(True)
    assert logger.level == logging.DEBUG
    logger.debug("verbose line")
    assert "DEBUG    | verbose line" in capsys.readouterr().out

    window._debug_checkbox.setChecked(False)
    assert logger.level == logging.INFO
    logger.info("quiet line")
    assert "quiet line" not in capsys.readouterr().out


def test_fmucontainer_status_bar_shows_the_log_and_opens_the_log_window(qtbot):
    import logging
    from PySide6.QtCore import Qt
    logger = logging.getLogger("fmu_manipulation_toolbox")
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert window.statusBar() is window._status_bar

    logger.info("AI Assistant enabled")
    assert window._status_bar.text() == "AI Assistant enabled"

    qtbot.mouseClick(window._status_bar, Qt.MouseButton.LeftButton)
    log_window = window._status_bar._log_window
    assert log_window.isVisible()
    assert "AI Assistant enabled" in log_window.view.toPlainText()
