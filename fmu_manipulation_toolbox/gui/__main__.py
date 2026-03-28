"""
FMU Manipulation Toolbox – Launcher GUI

Home window with 3 square buttons to launch:
  1. FMU Tool      – Operations on FMU
  2. FMU Editor    – FMU variables editor
  3. FMU Builder   – FMU Container build
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QDir, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel,
    QPushButton, QToolButton, QVBoxLayout, QHBoxLayout,
)

from fmu_manipulation_toolbox.gui.style import gui_style
from fmu_manipulation_toolbox.gui.helper import HelpWidget
from fmu_manipulation_toolbox.version import __version__ as version


RESOURCES = Path(__file__).parent / ".." / "resources"


class LauncherButton(QToolButton):
    """Square button with icon centered above the text."""

    def __init__(self, object_name: str, label: str, icon_path: Path, parent=None):
        super().__init__(parent)
        self.setText(label)
        self.setObjectName(object_name)
        self.setProperty("class", "launcher")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(180, 180)
        self.setIconSize(QSize(100, 100))
        self.setIcon(QIcon(QPixmap(str(icon_path))))



class LauncherWindow(QWidget):
    """Main launcher window."""

    def __init__(self):
        super().__init__()
        self.setObjectName("launcher_window")
        self.setWindowTitle(f"FMU Manipulation Toolbox  v{version}")

        # References to opened windows (prevents garbage collection)
        self._child_windows = []

        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(20, 20, 20, 20)
        self.setLayout(root_layout)

        # --- Logo / Title + Help ---
        top_bar = QHBoxLayout()
        
        logo = QLabel()
        logo_pixmap = QPixmap(str(RESOURCES / "fmu_manipulation_toolbox.png"))
        if not logo_pixmap.isNull():
            logo_pixmap = logo_pixmap.scaledToWidth(
                400, Qt.TransformationMode.SmoothTransformation
            )
        logo.setPixmap(logo_pixmap)
        logo.setStyleSheet("background: transparent;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        help_widget = HelpWidget()

        top_bar.addStretch()
        top_bar.addWidget(logo)
        top_bar.addStretch()
        top_bar.addWidget(help_widget, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        root_layout.addLayout(top_bar)

        subtitle = QLabel(f"v{version}")
        subtitle.setProperty("class", "info")
        subtitle.setStyleSheet("background: transparent;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root_layout.addWidget(subtitle)

        root_layout.addSpacing(20)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(20)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        btn_fmutool = LauncherButton(
            "fmutool",
            "Operation\non FMU",
            RESOURCES / "fmutool.png",
        )
        btn_fmutool.clicked.connect(self._launch_fmutool)

        btn_editor = LauncherButton(
            "editor",
            "FMU Variables\nEditor",
            RESOURCES / "fmueditor.png",
        )
        btn_editor.clicked.connect(self._launch_editor)

        btn_builder = LauncherButton(
            "builder",
            "FMU Container\nBuild",
            RESOURCES / "fmucontainer.png",
        )
        btn_builder.clicked.connect(self._launch_builder)

        btn_layout.addWidget(btn_fmutool)
        btn_layout.addWidget(btn_editor)
        btn_layout.addWidget(btn_builder)

        # --- Exit Button (same width as the 3 buttons above) ---
        btn_exit = QPushButton("Exit")
        btn_exit.setProperty("class", "quit")
        btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_exit.clicked.connect(QApplication.quit)

        buttons_container = QVBoxLayout()
        buttons_container.setSpacing(15)
        buttons_container.setContentsMargins(0, 0, 0, 0)
        buttons_container.addLayout(btn_layout)
        buttons_container.addWidget(btn_exit)

        center_layout = QHBoxLayout()
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addLayout(buttons_container)
        root_layout.addLayout(center_layout)

        root_layout.addStretch()

        self.show()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _keep_ref(self, window):
        """Keep a reference to the window to prevent garbage collection."""
        self._child_windows.append(window)
        window.destroyed.connect(lambda: self._child_windows.remove(window))

    # ── Actions ──────────────────────────────────────────────────────────

    def _launch_fmutool(self):
        from fmu_manipulation_toolbox.gui.fmutool import MainWindow
        window = MainWindow()
        window.show()
        self._keep_ref(window)

    def _launch_editor(self):
        from fmu_manipulation_toolbox.gui.fmueditor import MainWindow
        window = MainWindow()
        window.show()
        self._keep_ref(window)

    def _launch_builder(self):
        from fmu_manipulation_toolbox.gui.fmucontainer import MainWindow
        window = MainWindow()
        window.show()
        self._keep_ref(window)


class Application(QApplication):
    def __init__(self, *args, **kwargs):
        self.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor
        )
        super().__init__(*args, **kwargs)

        QDir.addSearchPath("images", str(RESOURCES))
        self.setStyleSheet(gui_style)

        if sys.platform == "win32":
            import ctypes
            self.setWindowIcon(QIcon(str(RESOURCES / "icon-round.png")))
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "FMU_Manipulation_Toolbox_Launcher"
            )
        else:
            self.setWindowIcon(QIcon(str(RESOURCES / "icon.png")))

        self.window = LauncherWindow()


def main():
    app = Application(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

