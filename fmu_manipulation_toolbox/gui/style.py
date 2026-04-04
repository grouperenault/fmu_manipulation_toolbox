import os


# ─── OS-specific font sizes ───
_FONT_SIZE_MAIN = "10pt" if os.name == 'nt' else "12pt"
_FONT_TEXTBROWSER = "11pt \"Consolas\"" if os.name == 'nt' else "14pt \"Courier New\""

# ─── Common stylesheet (multi-platform) ───
_COMMON_STYLE = """
    QWidget {{
        font: {font_size} "Verdana";
        background: #4b4e51;
        color: #b5bab9;
    }}
    QWidget#launcher_window {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #282830, stop:1 #4b4e51);
    }}
    QPushButton, QComboBox {{
        min-height: 30px;
        padding: 1px 1px 0.2em 0.2em;
        border: 1px solid #282830;
        border-radius: 5px;
        color: #dddddd;
    }}
    QPushButton:pressed {{
        border: 2px solid #282830;
    }}
    QPushButton.info {{
        background-color: #4e6749;
    }}
    QPushButton.info:hover {{
        background-color: #5f7850;
    }}
    QPushButton.modify {{
        background-color: #98763f;
    }}
    QPushButton.modify:hover {{
        background-color: #a9874f;
    }}
    QPushButton.removal {{
        background-color: #692e2e;
    }}
    QPushButton.removal:hover {{
        background-color: #7a3f3f;
    }}
    QPushButton.save {{
        background-color: #564967;
    }}
    QPushButton.save:hover {{
        background-color: #675a78;
    }}
    QPushButton.quit {{
        background-color: #4571a4;
    }}
    QPushButton.quit:hover {{
        background-color: #5682b5;
    }}
    QPushButton::disabled {{
        background-color: gray;
    }}
    QToolTip {{
        color: black
    }}
    QLabel.dropped_fmu {{
        background-color: #b5bab9
    }}
    QLabel.title {{
        font: 14pt bold "Verdana";
    }}
    QLabel.dropped_fmu:hover {{
        background-color: #c6cbca
    }}
    QTextBrowser, QTreeView {{
        font: {font_textbrowser};
        background-color: #282830;
        color: #b5bab9;
    }}
    QTreeView::item:selected:active,
    QTreeView::item:selected:!active {{
        background: #4571a4;
        color: #ffffff;
    }}
    QMenu::item {{
        padding: 2px 250px 2px 20px;
        border: 1px solid transparent;
    }}
    QMenu::item::indicator, QCheckBox::item::indicator {{
        width: 32px;
        height: 32px;
    }}
    QMenu::indicator:checked, QCheckBox::indicator:checked {{
        image: url(images:checkbox-checked.png);
    }}
    QMenu::indicator:checked:hover, QCheckBox::indicator:checked:hover {{
        image: url(images:checkbox-checked-hover.png);
    }}
    QMenu::indicator:checked:disabled, QCheckBox::indicator:checked:disabled {{
        image: url(images:checkbox-checked-disabled.png);
    }}
    QMenu::indicator:unchecked, QCheckBox::indicator:unchecked {{
        image: url(images:checkbox-unchecked.png);
    }}
    QMenu::indicator:unchecked:hover, QCheckBox::indicator:unchecked:hover {{
        image: url(images:checkbox-unchecked-hover.png);
    }}
    QMenu::indicator:unchecked:disabled, QCheckBox::indicator:unchecked:disabled {{
        image: url(images:checkbox-unchecked-disabled.png);
    }}
    QCheckBox::item {{
        padding: 2px 250px 2px 20px;
        border: 1px solid transparent;
    }}
    QTabBar::tab {{
        min-height: 30px;
        padding: 1px 1px 0.2em 0.2em;
        color: #dddddd;
        margin: 2px;
        margin-bottom: 0px;
        border: 1px solid #282830;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
    }} 
    QTabBar::tab:selected, QTabBar::tab:hover {{
        background-color: #5f7850;
        margin-bottom:-1px;
    }}
    QTabBar {{
        border-bottom: 1px solid #282830;
    }}
    QTabBar::tab:top:last, QTabBar::tab:bottom:last {{
        margin-right: 0;
    }}
    QTabBar::tab:top:first, QTabBar::tab:bottom:first {{
        margin-left: 0;
    }}
    QLabel.caption {{
        color: #888888;
        font: bold;
    }}
    QLabel.info {{
        color: #999999;
    }}
    QTableView {{
        background-color: #282830;
        color: #b5bab9;
        gridline-color: #3a3a44;
        selection-background-color: #4571a4;
        selection-color: #ffffff;
        alternate-background-color: #35353d;
    }}
    QHeaderView::section {{
        background-color: #3a3a44;
        color: #dddddd;
        padding: 4px;
        border: 1px solid #282830;
    }}
    QLineEdit {{
        background-color: #282830;
        color: #b5bab9;
        border: 1px solid #3a3a44;
        border-radius: 3px;
        padding: 2px 4px;
    }}
    QLineEdit:focus {{
        border: 1px solid #4571a4;
    }}
    QToolButton.launcher {{
        min-width: 180px;
        max-width: 180px;
        min-height: 180px;
        max-height: 180px;
        border: 1px solid #282830;
        border-radius: 5px;
        font: bold 11pt "Verdana";
        color: #dddddd;
        background-color: #4b4e51;
    }}
    QToolButton.launcher:hover {{
        background-color: qlineargradient(x1:0, y1:0.2, x2:0.2, y2:1, stop:0 #5c5f62, stop:1 #a9874f);
        border: 2px solid #b5bab9;
    }}
    QToolButton.launcher:pressed {{
        border: 3px solid #b5bab9;
    }}
"""

# ─── Build final stylesheet with OS-specific values ───
gui_style = _COMMON_STYLE.format(
    font_size=_FONT_SIZE_MAIN,
    font_textbrowser=_FONT_TEXTBROWSER,
)

placeholder_color = "#505058"

log_color = {
    "DEBUG": "#6E6B6B",
    "INFO": "#b5bab9",
    "WARNING": "#F7C61B",
    "ERROR": "#F54927",
    "CRITICAL": "#FF00FF",
}
