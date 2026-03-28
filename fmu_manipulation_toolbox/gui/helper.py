import logging
import os

from typing import *
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QStatusBar
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


        QDir.addSearchPath('images', str(Path(__file__).parent.parent / "resources"))
        self.setStyleSheet(gui_style)

        if os.name == 'nt':
            import ctypes
            self.setWindowIcon(QIcon(str(Path(__file__).parent.parent / 'resources' / 'icon-round.png')))

            # https://stackoverflow.com/questions/1551605/how-to-set-applications-taskbar-icon-in-windows-7/1552105#1552105

            application_id = 'FMU_Manipulation_Toolbox'  # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(application_id)
        else:
            self.setWindowIcon(QIcon(str(Path(__file__).parent.parent / 'resources' / 'icon.png')))

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
