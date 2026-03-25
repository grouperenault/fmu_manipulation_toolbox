import os

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QDir
from PySide6.QtGui import QIcon

from fmu_manipulation_toolbox.gui.style import gui_style


class Application(QApplication):
    def __init__(self, *args, **kwargs):
        self.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
        super().__init__(*args, **kwargs)


        QDir.addSearchPath('images', os.path.join(os.path.dirname(__file__), "../resources"))
        self.setStyleSheet(gui_style)

        if os.name == 'nt':
            import ctypes
            self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), '../resources', 'icon-round.png')))

            # https://stackoverflow.com/questions/1551605/how-to-set-applications-taskbar-icon-in-windows-7/1552105#1552105

            application_id = 'FMU_Manipulation_Toolbox'  # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(application_id)
        else:
            self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), '../resources', 'icon.png')))

        self.window = None
