"""Tests for the GUI log components of ``gui/log.py``.

``GuiLogHandler`` is the single GUI sink of the toolbox logger, which knows the
window each record belongs to; ``LogStatusBar`` shows its last record and
``LogWindow`` its whole history, with a level filter and a search.
"""
import logging
import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtCore import QObject, Qt, QThread
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.helper import LastDirectory
    from fmu_manipulation_toolbox.gui.log import (GuiLogHandler, LogStatusBar, LogWidget, LogWindow, RunTask,
                                                  busy_cursor, window_log_context)
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

    def on_record(self, owner, levelno, text):
        self.received.append((text, QThread.currentThread()))


def test_record_from_a_worker_thread_is_delivered_on_the_main_thread(qtbot, handler):
    receiver = _Receiver()
    handler.record_emitted.connect(receiver.on_record)

    worker = threading.Thread(target=lambda: logger.warning("from worker"))
    worker.start()
    worker.join()

    qtbot.waitUntil(lambda: bool(receiver.received))
    assert receiver.received == [("from worker", QApplication.instance().thread())]


# ── Owner window of the records ───────────────────────────────────────────
def _histories(handler, *windows):
    return [[text for _, text in handler.connect_with_history(lambda *_: None, window)] for window in windows]


@pytest.fixture
def windows(qtbot, handler, monkeypatch):
    """Two windows registered with ``handler`` (the installed one) at INFO level, the application event filter on."""
    monkeypatch.setattr(GuiLogHandler, "_installed", handler)
    first, second = QWidget(), QWidget()
    for window in (first, second):
        qtbot.addWidget(window)
        handler.register_window(window)
    monkeypatch.setattr(GuiLogHandler, "current_owner", None)
    GuiLogHandler.track_user_events()
    return first, second


def test_record_belongs_to_the_pinned_window(windows, handler):
    first, second = windows
    with window_log_context(first):
        logger.info("first")
    with window_log_context(second):
        logger.info("second")
    assert _histories(handler, first, second) == [["first"], ["second"]]


def test_nested_pins_are_restored(windows, handler):
    first, second = windows
    with window_log_context(first):
        with window_log_context(second):
            logger.info("inner")
        logger.info("outer")
    assert _histories(handler, first, second) == [["outer"], ["inner"]]


def test_record_without_owner_belongs_to_every_window(windows, handler):
    first, second = windows
    GuiLogHandler.current_owner = None
    logger.info("shared")
    with window_log_context(None):
        logger.info("explicitly shared")
    assert _histories(handler, first, second) == [["shared", "explicitly shared"]] * 2


def test_user_event_makes_its_window_the_owner(qtbot, windows, handler):
    first, second = windows
    button = QPushButton("act", second)
    second.show()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    logger.info("after click")
    assert _histories(handler, first, second) == [[], ["after click"]]


def test_dialog_records_belong_to_its_parent_window(qtbot, windows, handler):
    first, _ = windows
    dialog = QDialog(first)
    qtbot.addWidget(dialog)
    assert handler.owner_of(QPushButton(dialog)) == handler.window_key(first)


def test_unregistered_window_owns_no_record(qtbot, windows, handler):
    first, second = windows
    launcher = QWidget()
    qtbot.addWidget(launcher)
    assert handler.owner_of(launcher) is None
    with window_log_context(GuiLogHandler.window_key(launcher)):
        logger.info("from the launcher")
    assert _histories(handler, first, second) == [["from the launcher"]] * 2


def test_worker_thread_uses_its_pinned_window_only(windows, handler):
    first, second = windows
    GuiLogHandler.current_owner = handler.window_key(first)       # not seen by a worker thread
    key = handler.window_key(second)

    def work():
        logger.info("unpinned")
        with window_log_context(key):
            logger.info("pinned")

    worker = threading.Thread(target=work)
    worker.start()
    worker.join()
    assert _histories(handler, first, second) == [["unpinned"], ["unpinned", "pinned"]]


def test_each_window_has_its_own_level(windows, handler):
    first, second = windows
    handler.set_window_level(first, logging.DEBUG)
    assert logger.level == logging.DEBUG
    with window_log_context(first):
        logger.debug("debug of first")
    with window_log_context(second):
        logger.debug("debug of second")            # below the level of its window: dropped
    with window_log_context(None):
        logger.debug("shared debug")
    assert _histories(handler, first, second) == [["debug of first", "shared debug"], []]
    assert handler.accepts(first, None, logging.DEBUG)
    assert not handler.accepts(second, None, logging.DEBUG)
    assert not handler.accepts(second, handler.window_key(first), logging.ERROR)
    assert handler.accepts(None, handler.window_key(first), logging.DEBUG)


def test_logger_level_is_the_lowest_window_level(qtbot, windows, handler):
    first, second = windows
    handler.set_window_level(second, logging.DEBUG)
    assert logger.level == logging.DEBUG
    handler.unregister_window(second)
    assert logger.level == logging.INFO
    assert not handler.is_registered(second)

    doomed = QWidget()
    handler.register_window(doomed, logging.DEBUG)
    assert logger.level == logging.DEBUG
    doomed.deleteLater()
    qtbot.waitUntil(lambda: logger.level == logging.INFO)
    assert handler._levels.keys() == {handler.window_key(first)}


def test_clear_forgets_the_history_of_one_window(windows, handler):
    first, second = windows
    with window_log_context(None):
        logger.info("shared")
    handler.clear(first)
    assert _histories(handler, first, second) == [[], ["shared"]]


def test_verbose_window_copies_its_records_and_the_shared_ones_on_stdout(windows, handler, capsys):
    first, second = windows
    handler.set_window_verbose(first, True)
    assert handler.is_window_verbose(first) and handler.window_level(first) == logging.DEBUG
    assert handler.window_level(second) == logging.INFO
    try:
        with window_log_context(first):
            logger.debug("debug of first")
        with window_log_context(second):
            logger.info("info of second")
        with window_log_context(None):
            logger.info("shared")
        assert capsys.readouterr().out.splitlines() == ["DEBUG    | debug of first", "INFO     | shared"]

        handler.set_window_verbose(second, True)
        with window_log_context(None):
            logger.info("printed once")
        assert capsys.readouterr().out.splitlines() == ["INFO     | printed once"]
    finally:
        handler.set_window_verbose(first, False)
        handler.set_window_verbose(second, False)
    assert logger.level == logging.INFO
    with window_log_context(None):
        logger.info("quiet")
    assert capsys.readouterr().out == ""


def test_unregistered_window_leaves_the_verbose_mode(windows, handler, capsys):
    first, _ = windows
    handler.set_window_verbose(first, True)
    handler.unregister_window(first)
    assert logger.level == logging.INFO
    logger.info("quiet")
    assert capsys.readouterr().out == ""


# ── Views bound to a window ───────────────────────────────────────────────
def test_status_bar_of_a_window_ignores_the_records_of_the_others(qtbot, windows, handler):
    first, second = windows
    bar = LogStatusBar(handler, window=first)
    qtbot.addWidget(bar)
    with window_log_context(first):
        logger.info("mine")
    with window_log_context(second):
        logger.warning("not mine")
    assert bar.text() == "mine"
    with window_log_context(None):
        logger.info("shared")
    assert bar.text() == "shared"


def test_log_window_of_a_window_shows_its_history_and_live_records(qtbot, windows, handler):
    first, second = windows
    with window_log_context(first):
        logger.info("old mine")
    with window_log_context(second):
        logger.info("old not mine")
    window = LogWindow(handler, window=first)
    qtbot.addWidget(window)
    with window_log_context(second):
        logger.info("new not mine")
    with window_log_context(first):
        logger.info("new mine")
    assert _view_lines(window) == ["old mine", "new mine"]


def test_log_window_clear_keeps_the_log_of_the_other_windows(qtbot, windows, handler):
    first, second = windows
    with window_log_context(None):
        logger.info("shared")
    log_window = LogWindow(handler, window=first)
    qtbot.addWidget(log_window)
    log_window.clear()
    assert _histories(handler, first, second) == [[], ["shared"]]


def test_run_task_pins_its_parent_window(qtbot, windows, handler):
    first, second = windows

    def task():
        GuiLogHandler.current_owner = handler.window_key(second)   # the user clicks in another window
        logger.info("task record")

    dialog = RunTask(task, parent=first, title="Pinned")      # deleted with its parent
    with window_log_context(second):
        logger.info("other window")
    assert dialog.text.toPlainText().splitlines() == ["task record", "✅ Pinned finished."]
    assert _histories(handler, first, second) == [["task record", "✅ Pinned finished."], ["other window"]]


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


def test_busy_cursor_pins_its_window(windows, handler):
    first, second = windows
    with busy_cursor(window=first):
        GuiLogHandler.current_owner = handler.window_key(second)   # the user clicks in another window
        logger.info("task record")
    assert _histories(handler, first, second) == [["task record"], []]


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
