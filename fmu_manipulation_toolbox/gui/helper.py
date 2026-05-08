import logging
import os

from typing import *
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QStatusBar, QDialog, QTextBrowser, QVBoxLayout,
                               QPushButton, QMessageBox, QMainWindow)
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtCore import Qt, Signal, QPoint, QDir, QUrl
from PySide6.QtGui import QPixmap, QPainter, QColor, QImage

from pathlib import Path

from fmu_manipulation_toolbox.gui.style import gui_style, log_color
from fmu_manipulation_toolbox.operations import FMU

logger = logging.getLogger("fmu_manipulation_toolbox")


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
        self.last_directory = None
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

        base_image = QImage(str(filename)).scaled(
            self.WIDTH, self.HEIGHT,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        mask_filename = resources / "mask.png"
        mask_image = QImage(str(mask_filename)).scaled(
            self.WIDTH, self.HEIGHT,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        rounded_image = QImage(self.WIDTH, self.HEIGHT, QImage.Format.Format_ARGB32)
        rounded_image.fill(QColor(0, 0, 0, 0))

        painter = QPainter()
        painter.begin(rounded_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(QPoint(0, 0), base_image)
        painter.drawImage(QPoint(0, 0), mask_image)
        painter.end()

        self.setPixmap(QPixmap.fromImage(rounded_image))

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
        if self.last_directory:
            default_directory = self.last_directory
        else:
            default_directory = os.path.expanduser("~")

        fmu_filename, _ = QFileDialog.getOpenFileName(
            parent=self,
            caption="Select FMU",
            dir=default_directory,
            filter="FMU files (*.fmu)",
        )
        if fmu_filename:
            self.set_fmu(Path(fmu_filename))

    # -- FMU loading -----------------------------------------------------------

    def set_fmu(self, filename: Path):
        """Load an FMU from *filename* and emit the signals."""
        try:
            self.last_directory = str(Path(filename).parent)
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
        self.button = QPushButton("Close")
        self.button.setProperty("class", "quit")
        self.button.clicked.connect(self.close)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(self.text)
        layout.addWidget(self.button)

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

