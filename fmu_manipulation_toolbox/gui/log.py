"""GUI log of the toolbox: each record belongs to the window that emitted it.

``GuiLogHandler`` is the single GUI sink of the ``fmu_manipulation_toolbox`` logger; ``window_log_context`` pins the
owner window of the records; ``LogWidget``, ``LogStatusBar``, ``LogWindow`` and ``RunTask`` are the views.
"""
import contextlib
import contextvars
import logging
import sys
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QEvent
from PySide6.QtGui import QColor, QPixmap, QTextCursor
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QStatusBar, QTextBrowser, QVBoxLayout, QWidget)

from fmu_manipulation_toolbox.gui.helper import LastDirectory, MenuSelector
from fmu_manipulation_toolbox.gui.style import log_color

logger = logging.getLogger("fmu_manipulation_toolbox")


def _level_color(levelno: int) -> str:
    """Colour of a log level (levels in between use the colour of the level below)."""
    for level, name in ((logging.CRITICAL, "CRITICAL"), (logging.ERROR, "ERROR"), (logging.WARNING, "WARNING"),
                        (logging.INFO, "INFO")):
        if levelno >= level:
            return log_color[name]
    return log_color["DEBUG"]


def save_log_text(parent, text: str):
    """Ask for a .txt file and write the given log text into it."""
    filename = LastDirectory.get_save_file_name(
        parent=parent,
        caption="Save Logs",
        filter="Text files (*.txt);;All files (*)",
        default_name="logs.txt",
    )
    if not filename:
        return

    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        QMessageBox.critical(parent, "Save Logs", f"Cannot save logs: {e}")


#: Owner window pinned by ``window_log_context``; ``_NOT_PINNED`` lets the handler use the window of the last user event.
_NOT_PINNED = object()
_pinned_owner: contextvars.ContextVar = contextvars.ContextVar("fmu_manipulation_toolbox_log_owner",
                                                               default=_NOT_PINNED)


def _current_owner() -> int | None:
    """The pinned owner, otherwise (main thread only) the window of the last user event; registered or not."""
    owner = _pinned_owner.get()
    if owner is _NOT_PINNED:
        owner = GuiLogHandler.current_owner if threading.current_thread() is threading.main_thread() else None
    return owner


class _OwnerFilter(logging.Filter):
    """Logger filter: stores the current owner of the record in ``record.gui_owner``, for every handler."""

    def filter(self, record):
        record.gui_owner = _current_owner()
        return True


_owner_filter = _OwnerFilter()


class _StdoutHandler(logging.StreamHandler):
    """Writes on the current ``sys.stdout``, even when it is replaced after the creation of the handler."""

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, _):
        pass


class GuiLogHandler(logging.Handler):
    """The single GUI sink of the toolbox logger.

    Each record belongs to the window that emitted it (its *owner*), or to no window. The owner is the window pinned
    by ``window_log_context`` if any, otherwise, on the main thread, the window of the last user event (mouse press,
    key press, drop), otherwise none. Only the windows registered with ``register_window`` own records; a record
    without owner is meant for every window.

    It keeps a bounded history per registered window and broadcasts each record through the
    ``record_emitted(owner, levelno, text)`` Qt signal, ``owner`` being a key from ``window_key`` or ``None``. It never
    touches a widget: records logged from a worker thread (e.g. the MCP tools) reach the views through a queued
    connection, on the Qt main thread. Create it on the Qt main thread.

    Each registered window has its own level: records of a window below its level are dropped, and the logger level is
    the lowest level of the registered windows. A window in verbose mode (``set_window_verbose``) gets the DEBUG level
    and a copy of its records, and of the records without owner, on stdout.

    Once installed, a logger filter stores the owner of each record in its ``gui_owner`` attribute (``_OwnerFilter``).
    """

    HISTORY_SIZE = 5000
    DEFAULT_LEVEL = logging.INFO
    USER_EVENTS = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.KeyPress,
                   QEvent.Type.Drop)

    class _Emitter(QObject):
        record_emitted = Signal(object, int, str)

    class _VerboseFilter(logging.Filter):
        """Filter of the stdout copy: the records of the windows in verbose mode and the records without owner."""

        def __init__(self, handler: "GuiLogHandler"):
            super().__init__()
            self._handler = handler

        def filter(self, record):
            owner = self._handler._record_owner(record)
            return owner is None or owner in self._handler._verbose

    class _EventTracker(QObject):
        """Application event filter: the window of each user event becomes the current owner of the records."""

        def eventFilter(self, watched, event):
            if event.type() in GuiLogHandler.USER_EVENTS and isinstance(watched, QWidget):
                handler = GuiLogHandler._installed
                GuiLogHandler.current_owner = handler.owner_of(watched) if handler is not None else None
            return False

    _event_tracker: "_EventTracker | None" = None
    _installed: "GuiLogHandler | None" = None
    #: Owner of the records of the main thread when no window is pinned: the window of the last user event.
    current_owner: int | None = None

    def __init__(self, history_size: int = HISTORY_SIZE):
        super().__init__()
        self._history_size = history_size
        #: Every record, for the views bound to no window.
        self.history: deque[tuple[int, str]] = deque(maxlen=history_size)
        self._histories: dict[int, deque[tuple[int, str]]] = {}
        self._levels: dict[int, int] = {}
        self._emitter = GuiLogHandler._Emitter()
        self.record_emitted = self._emitter.record_emitted
        self._verbose: set[int] = set()
        self._stdout_handler = _StdoutHandler()
        self._stdout_handler.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))
        self._stdout_handler.addFilter(GuiLogHandler._VerboseFilter(self))

    # ── Windows ────────────────────────────────────────────────────────────
    @staticmethod
    def window_key(window: QWidget) -> int:
        return id(window)

    def register_window(self, window: QWidget, level: int = DEFAULT_LEVEL):
        """Make ``window`` an owner of records, until ``unregister_window`` or its destruction."""
        key = self.window_key(window)
        with self.lock:
            self._levels[key] = level
            self._histories[key] = deque(maxlen=self._history_size)
        window.destroyed.connect(lambda *_: self._unregister_key(key))
        self._update_logger_level()

    def unregister_window(self, window: QWidget):
        self._unregister_key(self.window_key(window))

    def _unregister_key(self, key: int):
        with self.lock:
            registered = self._levels.pop(key, None) is not None
            self._histories.pop(key, None)
            if GuiLogHandler.current_owner == key:
                GuiLogHandler.current_owner = None
            self._verbose.discard(key)
        if registered:
            self._update_logger_level()
            self._update_stdout_handler()

    def is_registered(self, window: QWidget) -> bool:
        return self.window_key(window) in self._levels

    def window_level(self, window: QWidget) -> int:
        return self._levels.get(self.window_key(window), logging.NOTSET)

    def set_window_level(self, window: QWidget, level: int):
        key = self.window_key(window)
        if key in self._levels:
            self._levels[key] = level
            self._update_logger_level()

    def set_window_verbose(self, window: QWidget, verbose: bool):
        """Verbose mode of ``window``: DEBUG level, and a copy of its records on stdout."""
        key = self.window_key(window)
        if key not in self._levels:
            return
        if verbose:
            self._verbose.add(key)
        else:
            self._verbose.discard(key)
        self._update_stdout_handler()
        self.set_window_level(window, logging.DEBUG if verbose else self.DEFAULT_LEVEL)

    def is_window_verbose(self, window: QWidget) -> bool:
        return self.window_key(window) in self._verbose

    def _update_stdout_handler(self):
        if self._verbose:
            logger.addHandler(self._stdout_handler)       # no-op when already there
        else:
            logger.removeHandler(self._stdout_handler)

    def _update_logger_level(self):
        levels = list(self._levels.values())
        logger.setLevel(min(levels) if levels else self.DEFAULT_LEVEL)

    def owner_of(self, widget: QWidget | None) -> int | None:
        """The key of the registered window ``widget`` belongs to, through the parents of its dialogs. Main thread."""
        while widget is not None:
            top = widget.window()
            if self.window_key(top) in self._levels:
                return self.window_key(top)
            widget = top.parentWidget()
        return None

    def _key(self, window: QWidget | int | None) -> int | None:
        return self.window_key(window) if isinstance(window, QWidget) else window

    def accepts(self, window: QWidget | int | None, owner: int | None, levelno: int) -> bool:
        """Whether a view of ``window`` (a widget or a key) shows a record of ``owner``.

        A view of no window shows every record.
        """
        key = self._key(window)
        if key is None:
            return True
        return owner in (key, None) and levelno >= self._levels.get(key, logging.NOTSET)

    # ── Records ────────────────────────────────────────────────────────────
    def _record_owner(self, record: logging.LogRecord) -> int | None:
        """The owner stored by the logger filter (the current one when the filter is not installed), if registered."""
        owner = getattr(record, "gui_owner", _NOT_PINNED)
        if owner is _NOT_PINNED:
            owner = _current_owner()
        return owner if owner in self._levels else None

    def emit(self, record: logging.LogRecord):
        try:
            text = self.format(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)
            return
        # Handler.handle() holds self.lock: histories and signal stay in the same order.
        owner = self._record_owner(record)
        if owner is not None and record.levelno < self._levels[owner]:
            return
        self.history.append((record.levelno, text))
        for key, history in self._histories.items():
            if owner in (key, None) and record.levelno >= self._levels[key]:
                history.append((record.levelno, text))
        self.record_emitted.emit(owner, record.levelno, text)

    def connect_with_history(self, slot: Callable[[int | None, int, str], None],
                             window: QWidget | int | None = None) -> list[tuple[int, str]]:
        """Connect ``slot`` to the records and return the history of ``window`` it has not seen.

        Done under the handler lock, so that no record is lost or duplicated
        between the copy of the history and the connection.
        """
        with self.lock:
            history = list(self._history(window))
            self.record_emitted.connect(slot)
        return history

    def _history(self, window: QWidget | int | None) -> deque[tuple[int, str]]:
        key = self._key(window)
        if key is None:
            return self.history
        return self._histories.get(key, deque())

    def clear(self, window: QWidget | int | None = None):
        """Forget the history of ``window``, or every history."""
        with self.lock:
            if window is None:
                self.history.clear()
                for history in self._histories.values():
                    history.clear()
            else:
                self._history(window).clear()

    @classmethod
    def install(cls) -> "GuiLogHandler":
        """Attach the application-wide handler to the toolbox logger, and the event filter to the application (once)."""
        if cls._installed is None:
            cls._installed = cls()
            logger.addFilter(_owner_filter)
            logger.addHandler(cls._installed)
            cls.track_user_events()
        return cls._installed

    @classmethod
    def track_user_events(cls):
        """Install the application event filter that follows the window of the user events (once)."""
        application = QApplication.instance()
        if application is not None and cls._event_tracker is None:
            cls._event_tracker = GuiLogHandler._EventTracker(application)       # owned by the application
            application.installEventFilter(cls._event_tracker)

    @classmethod
    def uninstall(cls):
        if cls._installed is not None:
            application = QApplication.instance()
            if application is not None and cls._event_tracker is not None:
                application.removeEventFilter(cls._event_tracker)
            logger.removeFilter(_owner_filter)
            logger.removeHandler(cls._installed._stdout_handler)
            logger.removeHandler(cls._installed)
            cls._installed.close()
            cls._installed = None
            cls._event_tracker = None
            GuiLogHandler.current_owner = None


@contextlib.contextmanager
def window_log_context(window: QWidget | int | None):
    """Make ``window`` the owner of the records logged in the block, in this thread (and the tasks it starts).

    ``window`` is a widget of the window (resolved on the main thread), a key from ``GuiLogHandler.window_key``
    (usable in any thread), or ``None`` for records without owner. It wins over the window of the user events.
    """
    if isinstance(window, QWidget):
        window = GuiLogHandler.install().owner_of(window)
    token = _pinned_owner.set(window)
    try:
        yield
    finally:
        _pinned_owner.reset(token)


class LogWidget(QTextBrowser):
    """Coloured log view. It is fed through ``append_record``, by a view of the ``GuiLogHandler`` records."""

    LOG_PREFIX = {
        logging.WARNING: "WARNING: ",
        logging.ERROR: "ERROR: ",
        logging.CRITICAL: "CRITICAL: ",
    }

    def __init__(self, parent=None, width=1200, height=500):
        super().__init__(parent)

        self.setMinimumWidth(width)
        self.setMinimumHeight(height)
        self.setSearchPaths([str(Path(__file__).parent.parent / "resources")])

    def loadResource(self, _, name):
        image_path = Path(__file__).parent.parent / "resources" / name.toString()
        return QPixmap(str(image_path))

    def append_record(self, levelno: int, text: str):
        # Append at the end, wherever the user clicked in the text.
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.setTextColor(QColor(_level_color(levelno)))
        self.insertPlainText(self.LOG_PREFIX.get(levelno, "") + text + "\n")
        self.ensureCursorVisible()


class LogStatusBar(QStatusBar):
    """Shows the last record (INFO and above) of a ``GuiLogHandler``; a click opens the ``LogWindow``.

    Bound to a registered *window*, it only shows the records of that window and the records without owner.
    Until the first record, it shows *initial_text* ("Ready"), which is not a record: it is neither in the
    history of the handler nor in the ``LogWindow``.
    """

    clicked = Signal()
    INITIAL_TEXT = "Ready"

    def __init__(self, handler: GuiLogHandler, parent=None, level=logging.INFO, initial_text: str = INITIAL_TEXT,
                 window: QWidget | None = None):
        super().__init__(parent)
        self._handler = handler
        self._level = level
        self._window = window
        self._log_window: LogWindow | None = None

        self._label = QLabel(initial_text)
        self._label.setStyleSheet(f"color: {_level_color(logging.INFO)};")
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._label.setContentsMargins(6, 0, 6, 2)
        self.addWidget(self._label, 1)
        self.setSizeGripEnabled(False)
        self.setToolTip("Click to show the log")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        handler.record_emitted.connect(self._on_record)
        self.clicked.connect(self.show_log_window)

    def text(self) -> str:
        return self._label.text()

    def _on_record(self, owner: int | None, levelno: int, text: str):
        if levelno < self._level or not self._handler.accepts(self._window, owner, levelno):
            return
        lines = text.strip().splitlines() or [""]
        self._label.setText(lines[0] + (" …" if len(lines) > 1 else ""))
        self._label.setStyleSheet(f"color: {_level_color(levelno)};")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def show_log_window(self) -> "LogWindow":
        if self._log_window is None:
            self._log_window = LogWindow(self._handler, parent=self.window(), window=self._window)
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()
        return self._log_window


class LogWindow(QDialog):
    """Non-modal window with the whole log of a ``GuiLogHandler``, a level filter and a search.

    Bound to a registered *window*, it only shows the records of that window and the records without owner.
    """

    LEVELS = (("Debug", logging.DEBUG), ("Info", logging.INFO), ("Warning", logging.WARNING),
              ("Error", logging.ERROR))

    def __init__(self, handler: GuiLogHandler, parent=None, window: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Log")
        self.setModal(False)
        self._handler = handler
        self._window = window
        self._records: deque[tuple[int, str]] = deque(maxlen=handler.history.maxlen)

        self.level_combo = MenuSelector()
        for name, level in self.LEVELS:
            self.level_combo.addItem(name, level)
        self.level_combo.setToolTip("Minimum level of the displayed records")
        self.level_combo.currentIndexChanged.connect(self._refresh)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._refresh)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(self.level_combo)
        filter_layout.addWidget(self.search_edit, 1)

        self.view = LogWidget(height=400)               # as wide as the log of `RunTask`

        self.save_button = QPushButton("Save Logs...")
        self.save_button.setProperty("class", "info")
        self.save_button.setMinimumWidth(150)
        self.save_button.clicked.connect(lambda: save_log_text(self, self.view.toPlainText()))

        self.clear_button = QPushButton("Clear")
        self.clear_button.setProperty("class", "quit")
        self.clear_button.setMinimumWidth(150)
        self.clear_button.clicked.connect(self.clear)

        self.close_button = QPushButton("Close")
        self.close_button.setProperty("class", "quit")
        self.close_button.setMinimumWidth(150)
        self.close_button.clicked.connect(self.close)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.clear_button)
        button_layout.addWidget(self.close_button)

        # The level selector as wide as the buttons, the search field as high as the selector.
        buttons = (self.save_button, self.clear_button, self.close_button)
        width = max([button.sizeHint().width() for button in buttons] + [150])
        for button in buttons:
            button.setMinimumWidth(width)
        self.level_combo.setFixedWidth(width)
        self.search_edit.setFixedHeight(self.level_combo.sizeHint().height())

        layout = QVBoxLayout(self)
        layout.addLayout(filter_layout)
        layout.addWidget(self.view, 1)
        layout.addLayout(button_layout)

        self._records.extend(handler.connect_with_history(self._on_record, window))
        self._refresh()

    def _accepts(self, levelno: int, text: str) -> bool:
        search = self.search_edit.text().lower()
        return levelno >= self.level_combo.currentData() and search in text.lower()

    def _on_record(self, owner: int | None, levelno: int, text: str):
        if not self._handler.accepts(self._window, owner, levelno):
            return
        self._records.append((levelno, text))
        if self._accepts(levelno, text):
            self.view.append_record(levelno, text)

    def _refresh(self):
        self.view.clear()
        for levelno, text in self._records:
            if self._accepts(levelno, text):
                self.view.append_record(levelno, text)

    def clear(self):
        """Forget the log of its window, also for the next opening of the window; the other windows keep theirs."""
        self._handler.clear(self._window)
        self._records.clear()
        self.view.clear()


@contextlib.contextmanager
def busy_cursor(window: QWidget | None = None):
    """Show the wait cursor while a task blocks the main thread; the cursor is restored even on error.

    With a *window*, the records of the task belong to it, even when the user acts in another window meanwhile.
    """
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        with window_log_context(window) if window is not None else contextlib.nullcontext():
            yield
    finally:
        QApplication.restoreOverrideCursor()


class RunTask(QDialog):
    """Runs a task on the main thread and shows the records it logs, through the shared ``GuiLogHandler``.

    The records of the task belong to the registered window of *parent*, even when the user acts in another window
    while the task runs.
    """

    def __init__(self, task: Callable, *args, parent=None, title="Run command...", **kwargs):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.text = LogWidget(height=300)

        self.save_button = QPushButton("Save Logs...")
        self.save_button.setProperty("class", "info")
        self.save_button.setMinimumWidth(150)
        self.save_button.clicked.connect(self.save_logs)

        self.close_button = QPushButton("Close")
        self.close_button.setProperty("class", "quit")
        self.close_button.setMinimumWidth(150)
        self.close_button.clicked.connect(self.close)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.close_button)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(self.text)
        layout.addLayout(button_layout)

        self.show()

        log_handler = GuiLogHandler.install()
        self._log_handler = log_handler
        self._owner = log_handler.owner_of(parent)
        log_handler.record_emitted.connect(self._on_record)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        with window_log_context(self._owner) if parent is not None else contextlib.nullcontext():
            logger.debug(f"Starting {title}...")
            try:
                task(*args, **kwargs)
                logger.info(f"✅ {title} finished.")
            except Exception as e:
                logger.critical(f"Unexpected error: {e}")
                logger.critical(f"Operation aborted.")
        QApplication.restoreOverrideCursor()
        log_handler.record_emitted.disconnect(self._on_record)

    def _on_record(self, owner: int | None, levelno: int, text: str):
        if not self._log_handler.accepts(self._owner, owner, levelno):
            return
        self.text.append_record(levelno, text)
        # The task blocks the main thread: repaint each record immediately.
        QApplication.processEvents()

    def save_logs(self):
        """Open a file dialog to save the current log content as a .txt file."""
        save_log_text(self, self.text.toPlainText())
