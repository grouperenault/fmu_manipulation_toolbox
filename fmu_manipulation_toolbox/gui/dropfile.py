"""
Reusable drop zone widget to load an .fmu file.
Used by fmutool.py and editor.py.
"""

import logging
import os

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QImage
from PySide6.QtWidgets import QLabel, QFileDialog

from fmu_manipulation_toolbox.operations import FMU

logger = logging.getLogger("fmu_manipulation_toolbox")


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

    def set_image(self, filename=None):
        """Display the FMU thumbnail (with rounded mask) or the placeholder."""
        resources = os.path.join(os.path.dirname(__file__), "..", "resources")

        if not filename:
            filename = os.path.join(resources, "drop_fmu.png")
        elif not os.path.isfile(filename):
            filename = os.path.join(resources, "fmu.png")

        base_image = QImage(filename).scaled(
            self.WIDTH, self.HEIGHT,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        mask_filename = os.path.join(resources, "mask.png")
        mask_image = QImage(mask_filename).scaled(
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
            self.set_fmu(file_path)
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
            self.set_fmu(fmu_filename)

    # -- FMU loading -----------------------------------------------------------

    def set_fmu(self, filename: str):
        """Load an FMU from *filename* and emit the signals."""
        try:
            self.last_directory = os.path.dirname(filename)
            self.fmu = FMU(filename)
            self.set_image(os.path.join(self.fmu.tmp_directory, "model.png"))
        except Exception as e:
            logger.error(f"Cannot load this FMU: {e}")
            self.set_image(None)
            self.fmu = None

        self.clicked.emit()
        self.fmu_loaded.emit(self.fmu)


