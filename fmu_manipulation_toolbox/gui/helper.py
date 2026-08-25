import logging
import os

from typing import *
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QStatusBar, QDialog, QTextBrowser, QVBoxLayout,
                               QHBoxLayout, QPushButton, QMessageBox, QMainWindow, QTableView, QHeaderView)
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtCore import Qt, Signal, QPoint, QDir, QUrl, QRect
from PySide6.QtGui import QPixmap, QPainter, QColor, QImage, QGuiApplication

from pathlib import Path

from fmu_manipulation_toolbox.gui.style import gui_style, log_color
from fmu_manipulation_toolbox.operations import FMU

logger = logging.getLogger("fmu_manipulation_toolbox")


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
    def update(cls, path: Optional[Union[str, "Path"]]) -> None:
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
    def get_open_file_names(cls, parent=None, caption: str = "", filter: str = "") -> List[str]:
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


def load_scaled_pixmap(source: Union[Path, str, QImage], max_width: int, max_height: int,
                       keep_aspect_ratio: bool = True,
                       mask_path: Optional[Path] = None,
                       trim_transparent: bool = False) -> Optional[QPixmap]:
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

    def set_image(self, filename:Optional[Path]=None):
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
            self.set_image(Path(self.fmu.tmp_directory) / "model.png")
        except Exception as e:
            logger.error(f"Cannot load this FMU: {e}")
            self.set_image(None)
            self.fmu = None

        self.clicked.emit()
        self.fmu_loaded.emit(self.fmu)


class StatusBar(QStatusBar):
    class StatusBarLogHandler(logging.Handler):
        """Affiche les logs dans une QStatusBar avec une couleur par niveau."""

        LOG_COLORS = {
            logging.DEBUG: log_color["DEBUG"],
            logging.INFO: log_color["INFO"],
            logging.WARNING: log_color["WARNING"],
            logging.ERROR: log_color["ERROR"],
            logging.CRITICAL: log_color["CRITICAL"],
        }

        def __init__(self, status_bar: QStatusBar, level=logging.INFO):
            super().__init__(level)
            self._status_bar = status_bar
            logger.addHandler(self)
            logger.setLevel(level)

        def emit(self, record: logging.LogRecord):
            color = self.LOG_COLORS.get(record.levelno, log_color["INFO"])
            self._status_bar.setStyleSheet(f"QStatusBar {{ color: {color}; }}")
            self._status_bar.showMessage(self.format(record), 10000)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._log_handler = StatusBar.StatusBarLogHandler(self)

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.removeHandler(self._log_handler)
        self._log_handler.close()


class LogWidget(QTextBrowser):
    class LogHandler(logging.Handler):
        LOG_COLOR = {
            logging.DEBUG: QColor(log_color["DEBUG"]),
            logging.INFO: QColor(log_color["INFO"]),
            logging.WARNING: QColor(log_color["WARNING"]),
            logging.ERROR: QColor(log_color["ERROR"]),
            logging.CRITICAL: QColor(log_color["CRITICAL"]),
        }
        LOG_PREFIX = {
            logging.DEBUG: "",
            logging.INFO: "",
            logging.WARNING: "WARNING: ",
            logging.ERROR: "ERROR: ",
            logging.CRITICAL: "CRITICAL: ",
        }

        def __init__(self, text_browser, level):
            super().__init__(level)
            self.text_browser: QTextBrowser = text_browser
            logger.addHandler(self)
            logger.setLevel(level)

        def emit(self, record) -> None:
            self.text_browser.setTextColor(self.LOG_COLOR[record.levelno])
            self.text_browser.insertPlainText(self.LOG_PREFIX[record.levelno])
            self.text_browser.insertPlainText(self.format(record) + "\n")
            self.text_browser.ensureCursorVisible()
            # Keep the RunTask dialog responsive and repaint log lines immediately.
            QApplication.processEvents()

    def __init__(self, parent=None, level=logging.INFO, width=1200, height=500):
        super().__init__(parent)

        self.setMinimumWidth(width)
        self.setMinimumHeight(height)
        self.setSearchPaths([str(Path(__file__).parent.parent / "resources")])
        self.log_handler = LogWidget.LogHandler(self, level)

    def loadResource(self, _, name):
        image_path = Path(__file__).parent.parent / "resources" / name.toString()
        return QPixmap(str(image_path))

    def stop_logging(self):
        logger.removeHandler(self.log_handler)


class RunTask(QDialog):
    def __init__(self, task: Callable, *args, parent=None, title="Run command...",  level=logging.INFO, **kwargs):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.text = LogWidget(height=300, level=level)

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

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        logger.debug(f"Starting {title}...")
        try:
            task(*args, **kwargs)
            logger.info(f"✅ {title} finished.")
        except Exception as e:
            logger.critical(f"Unexpected error: {e}")
            logger.critical(f"Operation aborted.")
        QApplication.restoreOverrideCursor()
        self.text.stop_logging()

    def save_logs(self):
        """Open a file dialog to save the current log content as a .txt file."""
        filename = LastDirectory.get_save_file_name(
            parent=self,
            caption="Save Logs",
            filter="Text files (*.txt);;All files (*)",
            default_name="logs.txt",
        )
        if not filename:
            return

        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self.text.toPlainText())
        except OSError as e:
            QMessageBox.critical(self, "Save Logs", f"Cannot save logs: {e}")


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

