import contextvars
import logging
import os
import threading

import contextlib
from collections import deque
from collections.abc import Callable
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QStatusBar, QDialog, QTextBrowser, QVBoxLayout,
                               QHBoxLayout, QPushButton, QMessageBox, QTableView, QHeaderView, QLineEdit, QMenu,
                               QWidget)
from PySide6.QtGui import QDesktopServices, QIcon, QAction
from PySide6.QtCore import Qt, Signal, QObject, QEvent, QPoint, QDir, QUrl, QRect, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QImage, QGuiApplication, QTextCursor

from pathlib import Path

from fmu_manipulation_toolbox.gui.style import gui_style, log_color
from fmu_manipulation_toolbox.operations import FMU

logger = logging.getLogger("fmu_manipulation_toolbox")


def get_fmu_icon_path(fmu: FMU, fmi_version: int | None) -> Path | None:
    """Return the path to the FMU model icon inside its extraction directory.

    The icon location depends on the FMI version:
      - FMI 3.0: `terminalsAndIcons/icon.png`
      - FMI 2.0 (or unknown): `model.png` at the FMU root

    Args:
        fmu: The loaded FMU (uses its `tmp_directory`).
        fmi_version: The detected FMI version (`2` or `3`), or `None` if unknown.

    Returns:
        The icon `Path` if the file exists, otherwise `None`.
    """
    if fmu is None:
        return None

    base = Path(fmu.tmp_directory)
    if fmi_version == 3:
        icon_path = base / "terminalsAndIcons" / "icon.png"
    else:
        icon_path = base / "model.png"

    return icon_path if icon_path.is_file() else None


class LastDirectory:
    """Remembers the last directory used in any file dialog across the whole application.

    The first file dialog opened during the application lifetime defaults to the
    current working directory. Every subsequent file dialog defaults to the
    directory used in the previous file dialog (whatever window it was opened from).

    Also provides wrappers around QFileDialog static methods that automatically use
    and update this remembered directory.
    """

    _directory: str = os.getcwd()

    @classmethod
    def get(cls) -> str:
        return cls._directory

    @classmethod
    def update(cls, path: str | Path | None) -> None:
        """Update the remembered directory from a file (or directory) path."""
        if not path:
            return
        p = Path(path)
        if not p.is_dir():
            p = p.parent
        if str(p):
            cls._directory = str(p)

    @classmethod
    def get_open_file_name(cls, parent=None, caption: str = "", filter: str = "") -> str:
        """Wrapper around QFileDialog.getOpenFileName using/updating the last directory."""
        filename, _ = QFileDialog.getOpenFileName(parent, caption, cls.get(), filter)
        if filename:
            cls.update(filename)
        return filename

    @classmethod
    def get_open_file_names(cls, parent=None, caption: str = "", filter: str = "") -> list[str]:
        """Wrapper around QFileDialog.getOpenFileNames using/updating the last directory."""
        filenames, _ = QFileDialog.getOpenFileNames(parent, caption, cls.get(), filter)
        if filenames:
            cls.update(filenames[0])
        return filenames

    @classmethod
    def get_save_file_name(cls, parent=None, caption: str = "", filter: str = "", default_name: str = "") -> str:
        """Wrapper around QFileDialog.getSaveFileName using/updating the last directory.

        ``default_name`` is the proposed file name (without directory), appended to the
        last used directory.
        """
        directory = cls.get()
        if default_name:
            directory = str(Path(directory) / default_name)
        filename, _ = QFileDialog.getSaveFileName(parent, caption, directory, filter)
        if filename:
            cls.update(filename)
        return filename
def device_pixel_ratio() -> float:
    """Return the device pixel ratio of the current screen (default 1.0)."""
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen is not None else 1.0


def crop_transparent_border(image: QImage) -> QImage:
    """Return *image* cropped to the bounding box of its non-transparent pixels.

    Fully-opaque images (or images without an alpha channel) are returned
    unchanged. A fully-transparent image is also returned unchanged.
    """
    if image.isNull() or not image.hasAlphaChannel():
        return image

    img = image.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    data = bytes(img.constBits())

    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        # Alpha bytes of the row (ARGB32 little-endian -> B,G,R,A per pixel).
        alphas = data[y * bpl: y * bpl + w * 4][3::4]
        if alphas.count(0) == len(alphas):
            continue  # fully transparent row
        left = 0
        while alphas[left] == 0:
            left += 1
        right = len(alphas) - 1
        while alphas[right] == 0:
            right -= 1
        min_x = min(min_x, left)
        max_x = max(max_x, right)
        min_y = min(min_y, y)
        max_y = max(max_y, y)

    if max_x < 0:  # fully transparent image
        return image
    if min_x == 0 and min_y == 0 and max_x == w - 1 and max_y == h - 1:
        return image  # nothing to crop

    return img.copy(QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))


def load_scaled_pixmap(source: Path | str | QImage, max_width: int, max_height: int,
                       keep_aspect_ratio: bool = True,
                       mask_path: Path | None = None,
                       trim_transparent: bool = False) -> QPixmap | None:
    """Load *source* and scale it to fit within *max_width* x *max_height*.

    The pixmap is rendered at the screen device-pixel-ratio and tagged with it,
    so it stays sharp on HiDPI/Retina displays while still occupying the
    requested *logical* size.

    Args:
        source: image file path or an already-loaded QImage.
        max_width, max_height: bounding box in logical pixels.
        keep_aspect_ratio: preserve the aspect ratio when scaling.
        mask_path: optional rounded-corners mask composited over the image.
        trim_transparent: crop any fully-transparent border before scaling.

    Returns:
        A QPixmap, or None if the source image could not be loaded.
    """
    image = source if isinstance(source, QImage) else QImage(str(source))
    if image.isNull():
        return None

    if trim_transparent:
        image = crop_transparent_border(image)

    dpr = device_pixel_ratio()
    target_w = max(1, int(round(max_width * dpr)))
    target_h = max(1, int(round(max_height * dpr)))
    mode = (Qt.AspectRatioMode.KeepAspectRatio if keep_aspect_ratio
            else Qt.AspectRatioMode.IgnoreAspectRatio)
    image = image.scaled(target_w, target_h, mode, Qt.TransformationMode.SmoothTransformation)

    if mask_path is not None:
        mask_image = QImage(str(mask_path)).scaled(
            image.width(), image.height(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        composed = QImage(image.width(), image.height(), QImage.Format.Format_ARGB32)
        composed.fill(QColor(0, 0, 0, 0))
        painter = QPainter()
        painter.begin(composed)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(QPoint(0, 0), image)
        painter.drawImage(QPoint(0, 0), mask_image)
        painter.end()
        image = composed

    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def unlock_column_resize(table: QTableView):
    """Switch from *Stretch* to *Interactive*, preserving the current widths.

    Call from ``showEvent`` so the columns start stretched (50 / 50) and
    then become user-resizable.  Runs only once (no-op after the switch).
    """
    header = table.horizontalHeader()
    if header.sectionResizeMode(0) != QHeaderView.ResizeMode.Stretch:
        return
    widths = [header.sectionSize(i) for i in range(header.count())]
    if not any(widths):
        return
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for i, w in enumerate(widths):
        header.resizeSection(i, w)


class Application(QApplication):
    def __init__(self, *args, **kwargs):
        self.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
        super().__init__(*args, **kwargs)
        if os.name == 'nt':
            import ctypes
            self.setWindowIcon(QIcon(str(Path(__file__).parent.parent / 'resources' / 'icon-round.png')))
            # https://stackoverflow.com/questions/1551605/how-to-set-applications-taskbar-icon-in-windows-7/1552105#1552105
            application_id = 'FMU_Manipulation_Toolbox'  # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(application_id)
        else:
            self.setWindowIcon(QIcon(str(Path(__file__).parent.parent / 'resources' / 'icon.png')))

        QDir.addSearchPath('images', str(Path(__file__).parent.parent / "resources"))
        self.setStyleSheet(gui_style)
        self.window = None


class HelpWidget(QLabel):
    HELP_URL = "https://grouperenault.github.io/fmu_manipulation_toolbox/"

    def __init__(self):
        super().__init__()
        self.setProperty("class", "help")
        self.setStyleSheet("background: transparent;")

        filename = Path(__file__).parent.parent / "resources" / "help.png"
        image = QPixmap(str(filename))
        self.setPixmap(image)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)

    def mousePressEvent(self, event):
        QDesktopServices.openUrl(QUrl(self.HELP_URL))


class DropZoneWidget(QLabel):
    """Drag-and-drop / click zone to select and load an .fmu file.

    Signals:
        clicked: emitted after each load attempt (success or failure).
        fmu_loaded(object): emitted with the loaded FMU object, or None on failure.
    """

    WIDTH = 150
    HEIGHT = 150

    clicked = Signal()
    fmu_loaded = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fmu = None
        self.setAcceptDrops(True)
        self.setProperty("class", "dropped_fmu")
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.set_image(None)

    # -- Display ----------------------------------------------------------------

    def set_image(self, filename:Path | None=None):
        """Display the FMU thumbnail (with rounded mask) or the placeholder."""
        resources = Path(__file__).parent.parent / "resources"

        if not filename:
            filename = resources / "drop_fmu.png"
        elif not filename.is_file():
            filename = resources / "fmu.png"

        pixmap = load_scaled_pixmap(
            filename, self.WIDTH, self.HEIGHT,
            keep_aspect_ratio=False,
            mask_path=resources / "mask.png",
            trim_transparent=True,
        )
        if pixmap is not None:
            self.setPixmap(pixmap)

    # -- Drag & drop events ----------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            try:
                file_path = event.mimeData().urls()[0].toLocalFile()
            except IndexError:
                logger.error("Please select a regular file.")
                return
            self.set_fmu(Path(file_path))
            event.accept()
        else:
            event.ignore()

    def mousePressEvent(self, event):
        fmu_filename = LastDirectory.get_open_file_name(
            parent=self,
            caption="Select FMU",
            filter="FMU files (*.fmu)",
        )
        if fmu_filename:
            self.set_fmu(Path(fmu_filename))

    # -- FMU loading -----------------------------------------------------------

    def set_fmu(self, filename: Path):
        """Load an FMU from *filename* and emit the signals."""
        try:
            LastDirectory.update(filename)
            self.fmu = FMU(filename)
            # At load time the FMU is not parsed yet, so fmi_version is unknown:
            # the FMI-2 icon (model.png) is shown here, and each tool refreshes
            # the icon once the FMI version has been detected.
            self.set_image(get_fmu_icon_path(self.fmu, self.fmu.fmi_version))
        except Exception as e:
            logger.error(f"Cannot load this FMU: {e}")
            self.set_image(None)
            self.fmu = None

        self.clicked.emit()
        self.fmu_loaded.emit(self.fmu)


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


class MenuSelector(QPushButton):
    """One choice among a few items: a push button (class `quit`) opening a menu, as the other selectors of the
    application ("Configuration" of the Container Builder, `FilterWidget` of FMU Tool). The items are not checkable
    (one choice only): the current one is in bold. Offers the part of the `QComboBox` interface used by the GUI."""
    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "quit")
        self._menu = QMenu(self)
        self._actions: list[QAction] = []
        self._items: list[tuple[str, object]] = []
        self._index = -1
        self.setMenu(self._menu)

    def addItem(self, text: str, data=None):
        action = QAction(text, self)
        index = len(self._items)
        action.triggered.connect(lambda _=False, i=index: self.setCurrentIndex(i))
        self._actions.append(action)
        self._menu.addAction(action)
        self._items.append((text, data))
        if self._index < 0:
            self.setCurrentIndex(0)

    def clear(self):
        self._menu.clear()
        self._actions = []
        self._items = []
        self._index = -1
        self.setText("")

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:
        return self._index

    def currentData(self):
        return self._items[self._index][1] if 0 <= self._index < len(self._items) else None

    def currentText(self) -> str:
        return self._items[self._index][0] if 0 <= self._index < len(self._items) else ""

    def findData(self, data) -> int:
        return next((index for index, (_, value) in enumerate(self._items) if value == data), -1)

    def sizeHint(self):
        """Wide enough for the longest item, and for the arrow of the menu."""
        hint = super().sizeHint()
        texts = [text for text, _ in self._items] or [self.text()]
        width = max(self.fontMetrics().horizontalAdvance(text) for text in texts) + 60
        return hint.expandedTo(QSize(width, hint.height()))

    def setCurrentIndex(self, index: int):
        if index == self._index or not 0 <= index < len(self._items):
            return
        self._index = index
        self.setText(self._items[index][0])
        for position, action in enumerate(self._actions):
            font = action.font()
            font.setBold(position == index)
            action.setFont(font)
        self.currentIndexChanged.emit(index)


#: Owner window pinned by ``window_log_context``; ``_NOT_PINNED`` lets the handler use the window of the last user event.
_NOT_PINNED = object()
_pinned_owner: contextvars.ContextVar = contextvars.ContextVar("fmu_manipulation_toolbox_log_owner",
                                                               default=_NOT_PINNED)


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
    the lowest level of the registered windows.
    """

    HISTORY_SIZE = 5000
    DEFAULT_LEVEL = logging.INFO
    USER_EVENTS = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.KeyPress,
                   QEvent.Type.Drop)

    class _Emitter(QObject):
        record_emitted = Signal(object, int, str)

    class _EventTracker(QObject):
        """Application event filter: the window of each user event becomes the current owner of the records."""

        def __init__(self, handler: "GuiLogHandler"):
            super().__init__()
            self._handler = handler

        def eventFilter(self, watched, event):
            if event.type() in GuiLogHandler.USER_EVENTS and isinstance(watched, QWidget):
                self._handler.current_owner = self._handler.owner_of(watched)
            return False

    _installed: "GuiLogHandler | None" = None

    def __init__(self, history_size: int = HISTORY_SIZE):
        super().__init__()
        self._history_size = history_size
        #: Every record, for the views bound to no window.
        self.history: deque[tuple[int, str]] = deque(maxlen=history_size)
        self._histories: dict[int, deque[tuple[int, str]]] = {}
        self._levels: dict[int, int] = {}
        #: Owner of the records of the main thread when no window is pinned: the window of the last user event.
        self.current_owner: int | None = None
        self._emitter = GuiLogHandler._Emitter()
        self.record_emitted = self._emitter.record_emitted
        self._event_tracker = GuiLogHandler._EventTracker(self)

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
            if self.current_owner == key:
                self.current_owner = None
        if registered:
            self._update_logger_level()

    def is_registered(self, window: QWidget) -> bool:
        return self.window_key(window) in self._levels

    def window_level(self, window: QWidget) -> int:
        return self._levels.get(self.window_key(window), logging.NOTSET)

    def set_window_level(self, window: QWidget, level: int):
        key = self.window_key(window)
        if key in self._levels:
            self._levels[key] = level
            self._update_logger_level()

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
    def _owner(self) -> int | None:
        owner = _pinned_owner.get()
        if owner is _NOT_PINNED:
            owner = self.current_owner if threading.current_thread() is threading.main_thread() else None
        return owner if owner in self._levels else None

    def emit(self, record: logging.LogRecord):
        try:
            text = self.format(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)
            return
        # Handler.handle() holds self.lock: histories and signal stay in the same order.
        owner = self._owner()
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
        """Attach the application-wide handler to the toolbox logger, and its event filter to the application (once)."""
        if cls._installed is None:
            cls._installed = cls()
            logger.addHandler(cls._installed)
            application = QApplication.instance()
            if application is not None:
                application.installEventFilter(cls._installed._event_tracker)
        return cls._installed

    @classmethod
    def uninstall(cls):
        if cls._installed is not None:
            application = QApplication.instance()
            if application is not None:
                application.removeEventFilter(cls._installed._event_tracker)
            logger.removeHandler(cls._installed)
            cls._installed.close()
            cls._installed = None


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
    """Coloured log view. It is fed through ``append_record``; see ``WidgetLogHandler``."""

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


class WidgetLogHandler(logging.Handler):
    """Writes the toolbox logs directly into a ``LogWidget`` (main thread only).

    Used where the log is displayed while a synchronous task runs on the main
    thread (FMU Tool): each record is repainted immediately.
    """

    def __init__(self, widget: LogWidget, level=logging.NOTSET):
        super().__init__(level)
        self.widget = widget
        logger.addHandler(self)

    def emit(self, record: logging.LogRecord):
        self.widget.append_record(record.levelno, self.format(record))
        QApplication.processEvents()

    def stop(self):
        logger.removeHandler(self)
        self.close()


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
def busy_cursor():
    """Show the wait cursor while a task blocks the main thread; the cursor is restored even on error."""
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
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


class UnsavedChangesWindowMixin:
    """Mixin to add unsaved changes detection to main windows.

    This mixin intercepts the closeEvent of QMainWindow subclasses and displays
    a confirmation dialog when unsaved changes are detected. The user can choose
    to save/discard changes or cancel the close operation.

    IMPORTANT: The mixin MUST be listed FIRST in the inheritance order to properly
    intercept closeEvent via Python's MRO (Method Resolution Order).

    Attributes (to be set in __init__):
        _check_unsaved_changes: Callable[[], bool]
            A callable (function, method, or lambda) that returns True if there
            are unsaved changes. This is mandatory.
        _unsaved_changes_message: str (optional)
            Custom message to display in the confirmation dialog.
            If not set, uses the default message.

    Example 1 - With method:
        class MyMainWindow(UnsavedChangesWindowMixin, QMainWindow):
            def __init__(self):
                super().__init__()
                self._dirty = False
                self._check_unsaved_changes = self._has_unsaved_changes
                self._unsaved_changes_message = "My custom message"

            def _has_unsaved_changes(self) -> bool:
                return self._dirty

    Example 2 - With lambda:
        class MyMainWindow(UnsavedChangesWindowMixin, QMainWindow):
            def __init__(self):
                super().__init__()
                self._dirty = False
                # Simple check using lambda
                self._check_unsaved_changes = lambda: self._dirty

    Behavior:
        - When user clicks X button to close:
            1. Mixin's closeEvent() is called first (due to MRO).
            2. Checks if _check_unsaved_changes() returns True.
            3. If True: displays dialog with Yes/No/Cancel options.
               - Yes: closes the window normally.
               - No: cancels the close operation.
            4. If False: closes the window immediately.
        - The dialog uses class styling with "removal" (Yes) and "info" (No) classes.
    """

    def closeEvent(self, event):
        """Check for unsaved changes and display a confirmation dialog if necessary."""
        # Check if there is a verification callable and call it
        check_unsaved = getattr(self, '_check_unsaved_changes', None)
        if check_unsaved and callable(check_unsaved):
            if check_unsaved():
                # Display the confirmation dialog
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("Unsaved changes")

                # Use a custom message if available, otherwise use the default message
                custom_message = getattr(self, '_unsaved_changes_message', None)
                if custom_message:
                    msg.setText(custom_message)
                else:
                    msg.setText("You have unsaved changes. Are you sure you want to quit?")

                msg.setStandardButtons(
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                msg.setDefaultButton(QMessageBox.StandardButton.No)

                # Style the buttons
                btn_yes = msg.button(QMessageBox.StandardButton.Yes)
                btn_no = msg.button(QMessageBox.StandardButton.No)

                btn_yes.setProperty("class", "removal")
                btn_no.setProperty("class", "info")

                btn_width = max(btn_yes.sizeHint().width(), btn_no.sizeHint().width(), 150)
                btn_yes.setMinimumWidth(btn_width)
                btn_no.setMinimumWidth(btn_width)

                # If the user clicks "No", cancel the close event
                if msg.exec() == QMessageBox.StandardButton.No:
                    event.ignore()
                    return

        # Accept the close event (default or if the user clicked "Yes")
        super().closeEvent(event)

