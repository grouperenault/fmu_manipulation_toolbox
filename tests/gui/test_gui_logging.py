"""Tests for the GUI log components of ``gui/helper.py``.

``GuiLogHandler`` is the single GUI sink of the toolbox logger; ``LogStatusBar``
shows its last record and ``LogWindow`` its whole history, with a level filter
and a search. ``WidgetLogHandler`` writes directly into a ``LogWidget``.
"""
import logging
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtCore import QObject, Qt, QThread
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.helper import (GuiLogHandler, LastDirectory, LogStatusBar, LogWidget, LogWindow,
                                                     RunTask, WidgetLogHandler)
    from fmu_manipulation_toolbox.gui.style import log_color
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"GUI dependencies not available: {exc}", allow_module_level=True)

pytestmark = pytest.mark.gui

logger = logging.getLogger("fmu_manipulation_toolbox")


@pytest.fixture
def handler():
    """A ``GuiLogHandler`` attached to the toolbox logger, which is set to DEBUG."""
    gui_handler = GuiLogHandler()
    previous_level = logger.level
    logger.addHandler(gui_handler)
    logger.setLevel(logging.DEBUG)
    yield gui_handler
    logger.removeHandler(gui_handler)
    logger.setLevel(previous_level)


@pytest.fixture
def status_bar(qtbot, handler):
    bar = LogStatusBar(handler)
    qtbot.addWidget(bar)
    return bar


def _view_lines(window: LogWindow) -> list[str]:
    return window.view.toPlainText().splitlines()


# ── GuiLogHandler ─────────────────────────────────────────────────────────
def test_handler_keeps_a_bounded_history():
    gui_handler = GuiLogHandler(history_size=3)
    for i in range(5):
        gui_handler.handle(logging.makeLogRecord({"msg": f"line {i}", "levelno": logging.INFO}))
    assert [text for _, text in gui_handler.history] == ["line 2", "line 3", "line 4"]


def test_handler_does_not_set_the_logger_level():
    previous_level = logger.level
    gui_handler = GuiLogHandler()
    assert logger.level == previous_level
    gui_handler.close()


class _Receiver(QObject):
    """A main-thread view: records the thread its slot runs on."""

    def __init__(self):
        super().__init__()
        self.received = []

    def on_record(self, levelno, text):
        self.received.append((text, QThread.currentThread()))


def test_record_from_a_worker_thread_is_delivered_on_the_main_thread(qtbot, handler):
    receiver = _Receiver()
    handler.record_emitted.connect(receiver.on_record)

    worker = threading.Thread(target=lambda: logger.warning("from worker"))
    worker.start()
    worker.join()

    qtbot.waitUntil(lambda: bool(receiver.received))
    assert receiver.received == [("from worker", QApplication.instance().thread())]


# ── LogStatusBar ──────────────────────────────────────────────────────────
def test_status_bar_shows_ready_until_the_first_record(status_bar, handler):
    assert status_bar.text() == "Ready"
    assert log_color["INFO"] in status_bar._label.styleSheet()
    assert not handler.history                           # "Ready" is not a record
    logger.info("first")
    assert status_bar.text() == "first"


def test_status_bar_shows_the_last_info_record_with_its_colour(status_bar):
    logger.info("first")
    logger.warning("second")
    assert status_bar.text() == "second"
    assert log_color["WARNING"] in status_bar._label.styleSheet()


def test_status_bar_ignores_debug_records(status_bar):
    logger.info("visible")
    logger.debug("hidden")
    assert status_bar.text() == "visible"


def test_status_bar_shows_the_first_line_of_a_multiline_record(status_bar):
    logger.info("headline\nsecond line")
    assert status_bar.text() == "headline …"


def test_status_bar_click_opens_a_single_log_window(qtbot, status_bar):
    logger.info("before opening")
    qtbot.mouseClick(status_bar, Qt.MouseButton.LeftButton)
    window = status_bar._log_window
    assert window is not None and window.isVisible()
    assert "before opening" in _view_lines(window)

    qtbot.mouseClick(status_bar, Qt.MouseButton.LeftButton)
    assert status_bar._log_window is window


# ── LogWindow ─────────────────────────────────────────────────────────────
def test_log_window_shows_the_history_then_the_live_records(qtbot, handler):
    logger.debug("old debug")
    logger.info("old info")
    window = LogWindow(handler)
    qtbot.addWidget(window)
    logger.error("new error")
    assert _view_lines(window) == ["old debug", "old info", "ERROR: new error"]


def test_log_window_level_filter(qtbot, handler):
    window = LogWindow(handler)
    qtbot.addWidget(window)
    logger.debug("a debug")
    logger.info("an info")
    logger.warning("a warning")
    logger.critical("a critical")

    window.level_combo.setCurrentIndex(window.level_combo.findData(logging.WARNING))
    assert _view_lines(window) == ["WARNING: a warning", "CRITICAL: a critical"]

    logger.info("filtered out")
    logger.error("kept")
    assert _view_lines(window)[-1] == "ERROR: kept"
    assert "filtered out" not in window.view.toPlainText()

    window.level_combo.setCurrentIndex(window.level_combo.findData(logging.DEBUG))
    assert "filtered out" in _view_lines(window)


def test_log_window_search_is_case_insensitive(qtbot, handler):
    window = LogWindow(handler)
    qtbot.addWidget(window)
    logger.info("Loading model.fmu")
    logger.info("Saving container")
    window.search_edit.setText("MODEL")
    assert _view_lines(window) == ["Loading model.fmu"]
    window.search_edit.clear()
    assert len(_view_lines(window)) == 2


def test_log_window_clear_forgets_the_history(qtbot, handler):
    logger.info("to forget")
    window = LogWindow(handler)
    qtbot.addWidget(window)
    window.clear()
    assert window.view.toPlainText() == ""
    assert not handler.history

    reopened = LogWindow(handler)
    qtbot.addWidget(reopened)
    assert reopened.view.toPlainText() == ""


def test_log_window_saves_the_displayed_lines(qtbot, handler, tmp_path, monkeypatch):
    target = tmp_path / "logs.txt"
    monkeypatch.setattr(LastDirectory, "get_save_file_name", classmethod(lambda cls, *a, **k: str(target)))
    window = LogWindow(handler)
    qtbot.addWidget(window)
    logger.info("kept line")
    logger.info("other line")
    window.search_edit.setText("kept")
    window.save_button.click()
    assert target.read_text(encoding="utf-8").splitlines() == ["kept line"]


# ── WidgetLogHandler ──────────────────────────────────────────────────────
def test_widget_handler_writes_prefixed_records_until_stopped(qtbot):
    widget = LogWidget()
    qtbot.addWidget(widget)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    widget_handler = WidgetLogHandler(widget)
    try:
        logger.info("plain")
        logger.error("broken")
    finally:
        widget_handler.stop()
        logger.setLevel(previous_level)
    logger.error("after stop")
    assert widget.toPlainText().splitlines() == ["plain", "ERROR: broken"]


# ── RunTask ───────────────────────────────────────────────────────────────
def test_run_task_shows_the_records_of_the_task_through_the_shared_handler(qtbot):
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        dialog = RunTask(lambda: logger.warning("task warning"), title="Doing")
        qtbot.addWidget(dialog)
        logger.info("after the task")
    finally:
        logger.setLevel(previous_level)
    assert dialog.text.toPlainText().splitlines() == ["WARNING: task warning", "✅ Doing finished."]
    assert logger.level == previous_level
    assert any(text == "task warning" for _, text in GuiLogHandler.install().history)


def test_run_task_reports_an_exception_of_the_task(qtbot):
    def failing():
        raise ValueError("boom")

    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        dialog = RunTask(failing, title="Failing")
        qtbot.addWidget(dialog)
    finally:
        logger.setLevel(previous_level)
    assert dialog.text.toPlainText().splitlines() == ["CRITICAL: Unexpected error: boom",
                                                      "CRITICAL: Operation aborted."]
