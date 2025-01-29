# if os.name == 'nt':
#    font = QFont('Consolas')
#    font.setPointSize(11)
# else:
#    font = QFont('Courier New')
#    font.setPointSize(12)
# self.setFont(font)


gui_style_dark = """
QWidget {
    font: 10pt "Verdana";
    background: #4b4e51;
    color: #b5bab9;
}
QPushButton, QComboBox {
    min-height: 30px;
    padding: 1px 1px 0.2em 0.2em;
    border: 1px solid #282830;
    border-radius: 5px;
    color: #dddddd;
}
QPushButton:pressed {
    border: 2px solid #282830;
}
QPushButton.info {
    background-color: #4e6749;
}
QPushButton.info:hover {
    background-color: #5f7850;
}
QPushButton.modify {
    background-color: #98763f;
}
QPushButton.modify:hover {
    background-color: #a9874f;
}
QPushButton.removal {
    background-color: #692e2e;
}
QPushButton.removal:hover {
    background-color: #7a3f3f;
}
QPushButton.save {
    background-color: #564967;
}
QPushButton.save:hover {
    background-color: #675a78;
}
QPushButton.quit {
    background-color: #4571a4;
}
QPushButton.quit:hover {
    background-color: #5682b5;
}
QPushButton::disabled {
    background-color: gray;
}
QToolTip {
    color: black
}
QLabel.dropped_fmu {
    background-color: #b5bab9
}
QLabel.title {
    font: 14pt bold "Verdana";
}
QLabel.dropped_fmu:hover {
    background-color: #c6cbca
}
QTextBrowser, QTreeView {
    font: 11pt "Consolas";
    background-color: #282830;
    color: #b5bab9;
}
QMenu::item {
    padding: 2px 250px 2px 20px;
    border: 1px solid transparent;
}
QMenu::item::indicator, QCheckBox::item::indicator {
    width: 32px;
    height: 32px;
}
QMenu::indicator:checked, QCheckBox::indicator:checked {
    image: url(images:checkbox-checked.png);
}
QMenu::indicator:checked:hover, QCheckBox::indicator:checked:hover {
    image: url(images:checkbox-checked-hover.png);
}
QMenu::indicator:checked:disabled, QCheckBox::indicator:checked:disabled {
    image: url(images:checkbox-checked-disabled.png);
}
QMenu::indicator:unchecked, QCheckBox::indicator:unchecked {
    image: url(images:checkbox-unchecked.png);
}
QMenu::indicator:unchecked:hover, QCheckBox::indicator:unchecked:hover {
    image: url(images:checkbox-unchecked-hover.png);
}
QMenu::indicator:unchecked:disabled, QCheckBox::indicator:unchecked:disabled {
    image: url(images:checkbox-unchecked-disabled.png);
}
QCheckBox::item {
    padding: 2px 250px 2px 20px;
    border: 1px solid transparent;
}
QTabBar::tab {
    min-height: 30px;
    padding: 1px 1px 0.2em 0.2em;
    color: #dddddd;
    margin: 2px;
    margin-bottom: 0px;
    border: 1px solid #282830;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
} 
QTabBar::tab:selected, QTabBar::tab:hover {
    background-color: #5f7850;
    margin-bottom:-1px;
}
QTabBar {
    border-bottom: 1px solid #282830;
}
QTabBar::tab:top:last, QTabBar::tab:bottom:last {
    margin-right: 0;
}
QTabBar::tab:top:first, QTabBar::tab:bottom:first {
    margin-left: 0;
}
"""
