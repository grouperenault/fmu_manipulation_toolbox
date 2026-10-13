"""
Make the screenshots of the graphical interfaces shown in the user documentation.

    python tools/screenshots.py            # every screenshot
    python tools/screenshots.py --list     # their names
    python tools/screenshots.py NAME ...   # some of them

The windows are rendered without being shown on screen (`WA_DontShowOnScreen`), with the native style of the
platform: the screenshots of the documentation are made on macOS, at the resolution of the screen (2x on a Retina
display). They show the content of the windows, without title bar. The FMUs come from `tests/data`, copied into a
temporary directory so that no path of the machine appears in the images. Requires PySide6, and the package
importable (installed, or run from the root of the repository).
"""

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QPoint, QRect, QItemSelectionModel    # noqa: E402
from PySide6.QtGui import QPainter, QPixmap, QContextMenuEvent, QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QWidget, QMenu, QLineEdit, QPushButton  # noqa: E402

from fmu_manipulation_toolbox.gui.helper import Application           # noqa: E402

DOCS = ROOT / "docs"
DATA = ROOT / "tests" / "data"
# Short and neutral paths in the images (FMU Tool shows the path of the FMU and of its temporary directory).
if os.name != "nt" and Path("/tmp").is_dir():
    tempfile.tempdir = "/tmp"
WORK = Path(tempfile.gettempdir()) / "fmutool"

#: The windows are kept until the end: some of them install a logging handler writing into one of their widgets,
#: which must not be deleted while the next windows log.
WINDOWS: list[QWidget] = []

#: name -> (image path relative to `docs/`, function making the image)
SHOTS: dict[str, tuple[str, Callable[[], QPixmap]]] = {}


def shot(name: str, path: str):
    def register(function):
        SHOTS[name] = (path, function)
        return function
    return register


# ── Helpers ─────────────────────────────────────────────────────────────

def settle():
    for _ in range(5):
        Application.processEvents()


def offscreen(widget_class, *args, size: tuple[int, int] | None = None, **kwargs) -> QWidget:
    """Create a window and render it off screen. Some windows call `show()` in their constructor: this call is
    skipped while they are built, then the window is shown with `WA_DontShowOnScreen`."""
    widget_class.show = lambda self: None
    try:
        widget = widget_class(*args, **kwargs)
    finally:
        del widget_class.show
    WINDOWS.append(widget)
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    if size:
        widget.resize(*size)
    widget.show()
    settle()
    return widget


def copy_data(*relative_paths: str) -> Path:
    """Copy files or directories of `tests/data` into the work directory; return the work directory."""
    for relative in relative_paths:
        source, target = DATA / relative, WORK / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return WORK


def with_popups(window: QWidget, popups: list[tuple[QWidget, QPoint]], crop: QRect | None = None) -> QPixmap:
    """The rendering of *window* with *popups* (menus) drawn at their position (in window coordinates), cropped
    to *crop* (in window coordinates) if given."""
    pixmap = window.grab()
    painter = QPainter(pixmap)
    for popup, position in popups:
        painter.drawPixmap(position, popup.grab())
    painter.end()
    return cropped(pixmap, crop)


def cropped(pixmap: QPixmap, crop: QRect | None) -> QPixmap:
    if crop is None:
        return pixmap
    ratio = pixmap.devicePixelRatio()
    crop = crop.intersected(QRect(QPoint(0, 0), pixmap.size() / ratio))
    return pixmap.copy(QRect(int(crop.x() * ratio), int(crop.y() * ratio),
                             int(crop.width() * ratio), int(crop.height() * ratio)))


def rendered_menu(menu: QMenu) -> QMenu:
    """Lay out a menu off screen, so that it can be rendered."""
    menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    menu.popup(QPoint(0, 0))
    settle()
    return menu


class CapturedMenu:
    """Within `with CapturedMenu(module) as captured:`, the menus that *module* builds and opens with `exec` are
    not opened: the last one is kept in `captured.menu` (and no action is chosen)."""

    def __init__(self, module):
        self._module = module

    def __enter__(self):
        captured = self
        captured.menu = None

        class Menu(QMenu):
            def exec(self, *args, **kwargs):
                captured.menu = self
                return None

        self._qmenu = self._module.QMenu
        self._module.QMenu = Menu
        return self

    def __exit__(self, *exc):
        self._module.QMenu = self._qmenu


def around(*rects: QRect, margin: int = 24) -> QRect:
    """Smallest rectangle containing *rects*, with a margin."""
    union = rects[0]
    for rect in rects[1:]:
        union = union.united(rect)
    return union.adjusted(-margin, -margin, margin, margin)


def rect_in(widget: QWidget, window: QWidget) -> QRect:
    return QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())


# ── Launcher, FMU Tool, FMU Editor ──────────────────────────────────────

@shot("launcher", "gui-launcher.png")
def launcher():
    from fmu_manipulation_toolbox.gui.__main__ import LauncherWindow
    return offscreen(LauncherWindow).grab()


def fmutool_window():
    from fmu_manipulation_toolbox.gui.fmutool.__main__ import MainWindow
    work = copy_data("containers/VanDerPol/VanDerPol.fmu")
    window = offscreen(MainWindow, size=(1030, 860))
    window.load(str(work / "containers/VanDerPol/VanDerPol.fmu"))
    settle()
    return window


@shot("fmutool", "user-guide/fmutool/fmutool-gui.png")
def fmutool():
    window = fmutool_window()
    window.log_widget.verticalScrollBar().setValue(0)
    settle()
    return window.grab()


@shot("fmutool-filter", "user-guide/fmutool/fmutool-filter.png")
def fmutool_filter():
    window = fmutool_window()
    button, label = window.filter_list, window.apply_filter_label
    for action in button.menu.actions():                      # only the inputs and the parameters
        if action.text() not in ("input", "parameter"):
            action.trigger()
    settle()
    menu = rendered_menu(button.menu)
    position = button.mapTo(window, QPoint(0, button.height()))
    crop = around(rect_in(label, window), rect_in(button, window), QRect(position, menu.size()))
    return with_popups(window, [(menu, position)], crop)


@shot("fmutool-check", "user-guide/fmutool/fmutool-check.png")
def fmutool_check():
    window = fmutool_window()
    check = next(button for button in window.findChildren(QPushButton) if button.text() == "Check")
    check.click()
    settle()
    window.log_widget.verticalScrollBar().setValue(window.log_widget.verticalScrollBar().maximum())
    settle()
    return window.grab()


@shot("fmutool-compile", "user-guide/fmutool/fmutool-compile.png")
def fmutool_compile():
    """`Compile sources` on the FMI 3.0 Reference FMU `BouncingBall` copied without its binaries."""
    import zipfile
    from fmu_manipulation_toolbox.gui.fmutool.__main__ import MainWindow
    source = DATA / "compile" / "3.0" / "BouncingBall.fmu"
    target = WORK / "BouncingBall.fmu"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if not item.filename.startswith("binaries/"):
                zout.writestr(item, zin.read(item.filename))
    window = offscreen(MainWindow, size=(1030, 860))
    window.load(str(target))
    settle()
    compile_button = next(button for button in window.findChildren(QPushButton)
                          if button.text() == "Compile sources")
    compile_button.click()
    settle()
    window.log_widget.verticalScrollBar().setValue(window.log_widget.verticalScrollBar().maximum())
    settle()
    return window.grab()


@shot("fmutool-compile-options", "user-guide/fmutool/fmutool-compile-options.png")
def fmutool_compile_options():
    """The dialog of `Compile sources` after a failure: `model.c` of `BouncingBall` needs `FOO`."""
    import zipfile
    from fmu_manipulation_toolbox.gui.fmutool import __main__ as fmutool_gui
    source = DATA / "compile" / "3.0" / "BouncingBall.fmu"
    target = WORK / "BouncingBall.fmu"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "sources/model.c":
                content = b'#ifndef FOO\n#error "FOO is not defined"\n#endif\n' + content
            if not item.filename.startswith("binaries/"):
                zout.writestr(item, content)

    images = []

    class Dialog(fmutool_gui.CompileOptionsDialog):
        """Grabbed instead of being executed; then cancelled."""
        def exec(self):
            self.edits["compiler_options"].setText("-DFOO")
            self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            self.show()
            settle()
            images.append(self.grab())
            return fmutool_gui.QDialog.DialogCode.Rejected

    window = offscreen(fmutool_gui.MainWindow, size=(1030, 860))
    window.load(str(target))
    settle()
    original, fmutool_gui.CompileOptionsDialog = fmutool_gui.CompileOptionsDialog, Dialog
    try:
        window.compile_sources()
    finally:
        fmutool_gui.CompileOptionsDialog = original
    return images[0]


def fmueditor_window():
    from fmu_manipulation_toolbox.gui.fmueditor.__main__ import MainWindow
    work = copy_data("containers/VanDerPol/VanDerPol.fmu")
    window = offscreen(MainWindow, size=(1100, 720))
    window.load(str(work / "containers/VanDerPol/VanDerPol.fmu"))
    settle()
    return window


@shot("fmueditor", "user-guide/fmutool/fmueditor.png")
def fmueditor():
    return fmueditor_window().grab()


@shot("fmueditor-edit", "user-guide/fmutool/fmueditor-edit.png")
def fmueditor_edit():
    window = fmueditor_window()
    model = window._model
    for row, variable in enumerate(model.variables):
        if variable.name == "mu":
            column = next(c for c in range(model.columnCount())
                          if model.headerData(c, Qt.Orientation.Horizontal) == "Description")
            model.setData(model.index(row, column), "damping of the oscillator", Qt.ItemDataRole.EditRole)
    search = next(edit for edit in window.findChildren(QLineEdit) if edit.placeholderText() == "Filter variables…")
    search.setText("m")
    settle()
    return window.grab()


# ── Container Builder ───────────────────────────────────────────────────

def container_window(size=(1600, 900)):
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow
    window = offscreen(MainWindow, size=size)
    return window


def discard(window):
    """No "save your changes?" question when the script ends."""
    window._dirty = False


def node_named(window, name):
    return next(node for node in window._graph.scene.nodes() if node.name == name)


def wire_between(window, name_a, name_b):
    return next(wire for wire in window._graph.scene.wires()
                if {wire.node_a.name, wire.node_b.name} == {name_a, name_b})


def select(window, item):
    window._graph.scene.clearSelection()
    item.setSelected(True)
    settle()


@shot("container", "user-guide/fmucontainer/fmucontainer-gui.png")
def container():
    work = copy_data("containers/arch")
    window = container_window()
    window.import_assembly_file(str(work / "containers/arch/hierarchical.json"))
    settle()
    # The assembly relies on `auto_link`: its links are drawn here.
    scene = window._graph.scene
    sine, integrate, gain = (node_named(window, name) for name in ("sine.fmu", "integrate.fmu", "gain.fmu"))
    for column, node in enumerate((sine, integrate, gain)):
        node.setPos(column * 215, 0)
    for source, port, target in ((sine, "sine", integrate), (integrate, "integrate", gain)):
        wire = scene.add_wire(source, target)
        wire.mappings = [(source.name, port, target.name, port)]
    settle()
    window._tree.wire_detail._load_from_wire()
    select(window, wire)
    window._graph.view.fit_all()
    settle()
    discard(window)
    return window.grab()


@shot("container-vr", "user-guide/fmucontainer/container-vr-gui.png")
def container_vr():
    work = copy_data("containers/VanDerPol")
    window = container_window()
    window.import_assembly_file(str(work / "containers/VanDerPol/VanDerPol-vr.json"))
    settle()
    select(window, wire_between(window, "sched2.fmu", "configuration"))
    details = window._tree.wire_detail
    details._tabs.setCurrentWidget(details._tab_ba if details._wire.node_a.name == "configuration"
                                   else details._tab_ab)               # the tab holding the link
    window._graph.view.fit_all()
    settle()
    discard(window)
    return window.grab()


def bouncing_balls(window, instances=False):
    work = copy_data("containers/bouncing_ball/bb_position.fmu", "containers/bouncing_ball/bb_velocity.fmu")
    folder = work / "containers/bouncing_ball"
    scene = window._graph.scene
    pairs = [(scene.add_node(folder / "bb_velocity.fmu"), scene.add_node(folder / "bb_position.fmu"))]
    if instances:
        pairs.append((scene.add_node(folder / "bb_velocity.fmu"), scene.add_node(folder / "bb_position.fmu")))
    for row, (velocity, position) in enumerate(pairs):
        velocity.setPos(0, row * 260)
        position.setPos(380, row * 260)
        wire = scene.add_wire(velocity, position)
        wire.mappings = [(velocity.name, "velocity", position.name, "velocity")]
    settle()
    window._tree.wire_detail._load_from_wire()
    return pairs


@shot("fmu-details", "user-guide/fmucontainer/fmucontainer-fmu-details.png")
def fmu_details():
    work = copy_data("containers/VanDerPol/VanDerPol.fmu")
    window = container_window()
    node = window._graph.scene.add_node(work / "containers/VanDerPol/VanDerPol.fmu")
    select(window, node)
    # Set once the node is displayed: selecting it writes the table of the panel into the node.
    node.user_start_values["mu"] = "1.5"
    window._tree.fmu_detail._load_from_node(node)
    settle()
    discard(window)
    return cropped(window.grab(), rect_in(window._tree._detail_panel, window).adjusted(-8, -8, 8, 8))


@shot("invalid-wire", "user-guide/fmucontainer/fmucontainer-invalid-wire.png")
def invalid_wire():
    window = container_window()
    (velocity, position), = bouncing_balls(window)
    wire = position.wires[0]                                   # displayed by the panel
    # As after "Replace FMU" with an FMU whose input is named differently.
    wire.mappings = [(velocity.name, "velocity", position.name, "speed")]
    window._tree.wire_detail._load_from_wire()
    # The wire is drawn in red when it is not selected; the panel keeps showing it.
    scene = window._graph.scene
    scene.blockSignals(True)
    wire.setSelected(False)
    scene.blockSignals(False)
    window._graph.view.fit_all()
    settle()
    discard(window)
    return window.grab()


@shot("instances", "user-guide/fmucontainer/fmucontainer-instances.png")
def instances():
    window = container_window()
    pairs = bouncing_balls(window, instances=True)
    position_1 = pairs[1][1]
    select(window, position_1)
    window._graph.view.fit_all()
    settle()
    discard(window)
    return window.grab()


@shot("container-details", "user-guide/fmucontainer/fmucontainer-container-details.png")
def container_details():
    window = container_window()
    bouncing_balls(window)
    tree = window._tree.tree_view
    window._graph.scene.clearSelection()
    tree.selectionModel().setCurrentIndex(window._tree.root.index(),
                                          QItemSelectionModel.SelectionFlag.ClearAndSelect)
    settle()
    discard(window)
    return cropped(window.grab(), rect_in(window._tree, window).adjusted(-8, -8, 8, 8))


@shot("configuration-menu", "user-guide/fmucontainer/fmucontainer-configuration.png")
def configuration_menu():
    window = container_window()
    button = window._config_button
    menu = rendered_menu(button.menu())
    position = button.mapTo(window, QPoint(0, -menu.height()))
    discard(window)
    return with_popups(window, [(menu, position)], around(rect_in(button, window), QRect(position, menu.size())))


@shot("canvas-menu", "user-guide/fmucontainer/fmucontainer-canvas-menu.png")
def canvas_menu():
    window = container_window()
    (velocity, position), = bouncing_balls(window)
    view = window._graph.view
    view.fit_all()
    settle()
    point = view.mapFromScene(position.sceneBoundingRect().center())
    from fmu_manipulation_toolbox.gui.fmucontainer.graph import view as view_module
    with CapturedMenu(view_module) as captured:
        view.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, view.mapToGlobal(point)))
    menu = rendered_menu(captured.menu)
    at = view.viewport().mapTo(window, point)
    discard(window)
    return with_popups(window, [(menu, at)], around(rect_in(view, window), QRect(at, menu.size())))


@shot("tree-menu", "user-guide/fmucontainer/fmucontainer-tree-menu.png")
def tree_menu():
    window = container_window()
    bouncing_balls(window)
    tree = window._tree.tree_view
    index = window._tree.root.child(0).index()
    rect = tree.visualRect(index)
    tree.ensurePolished()                                       # the font of the tree comes from the stylesheet
    text_width = QFontMetrics(tree.font()).horizontalAdvance(index.data())
    point = QPoint(rect.left() + text_width + 48, rect.center().y())    # after the icon and the name
    from fmu_manipulation_toolbox.gui.fmucontainer.tree import widget as widget_module
    with CapturedMenu(widget_module) as captured:
        window._tree._tree_widget._on_context_menu(point)
    menu = rendered_menu(captured.menu)
    at = tree.viewport().mapTo(window, point)
    discard(window)
    crop = around(rect_in(tree, window), QRect(at, menu.size()))
    return with_popups(window, [(menu, at)], crop)


@shot("waypoints", "user-guide/fmucontainer/fmucontainer-waypoints.png")
def waypoints():
    window = container_window()
    (velocity, position), = bouncing_balls(window)
    position.setPos(380, 220)
    wire = position.wires[0]
    wire.update_path()
    start, end = velocity.sceneBoundingRect().center(), position.sceneBoundingRect().center()
    wire.add_waypoint(type(start)(end.x() - 60, start.y()))
    select(window, wire)
    view = window._graph.view
    view.fit_all()
    settle()
    discard(window)
    return cropped(window.grab(), rect_in(view, window))


# ── Link Assistant ──────────────────────────────────────────────────────

def link_assistant():
    from fmu_manipulation_toolbox.gui.fmucontainer.details.link_assistant import LinkAssistantDialog
    from fmu_manipulation_toolbox.gui.fmucontainer.details.link_assistant_demo import generate
    from fmu_manipulation_toolbox.gui.fmucontainer.details.link_matching import AffixRule
    side_a, side_b, existing = generate(400)
    dialog = offscreen(LinkAssistantDialog, side_a, side_b, existing, size=(1300, 900))
    dialog._on_run()
    dialog._on_stage_checked()                                  # "Same name" first
    dialog._criterion.set_kind(AffixRule)
    dialog._criterion.affix_fields["from_prefix"].setText("engine.out.")
    dialog._criterion.affix_fields["to_prefix"].setText("ecu.in.engine_")
    dialog._on_run()
    settle()
    return dialog


@shot("link-assistant-rules", "user-guide/fmucontainer/link-assistant-rules.png")
def link_assistant_rules():
    dialog = link_assistant()
    pixmap = dialog.grab()
    dialog._staged = []
    return pixmap


@shot("link-assistant-manual", "user-guide/fmucontainer/link-assistant-manual.png")
def link_assistant_manual():
    dialog = link_assistant()
    dialog._on_stage_checked()
    dialog._tabs.setCurrentIndex(1)
    fields = sorted((edit for edit in dialog.findChildren(QLineEdit)
                     if edit.placeholderText() == "Filter name / description"),
                    key=lambda edit: edit.mapTo(dialog, QPoint(0, 0)).x())
    fields[0].setText("diag.intake")
    fields[1].setText("aux.intake")
    for table in (dialog._outputs_table, dialog._inputs_table):
        for row in range(2):
            table.selectionModel().select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select
                                          | QItemSelectionModel.SelectionFlag.Rows)
    settle()
    pixmap = dialog.grab()
    dialog._staged = []
    return pixmap


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Make the screenshots of the user documentation.")
    parser.add_argument("names", nargs="*", help="screenshots to make (default: all)")
    parser.add_argument("--list", action="store_true", help="list the screenshots and exit")
    args = parser.parse_args()
    if args.list:
        for name, (path, _) in SHOTS.items():
            print(f"{name:24} docs/{path}")
        return
    unknown = set(args.names) - set(SHOTS)
    if unknown:
        parser.error(f"unknown screenshot(s): {', '.join(sorted(unknown))}")

    application = Application(sys.argv[:1])
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    try:
        for name in args.names or SHOTS:
            path, function = SHOTS[name]
            pixmap = function()
            pixmap.save(str(DOCS / path))
            print(f"docs/{path}  {pixmap.width()}x{pixmap.height()}")
            settle()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    application.processEvents()
    # No selection signal from a scene being destroyed at exit (as in the GUI tests).
    for window in WINDOWS:
        graph = getattr(window, "_graph", None)
        if graph is not None:
            graph.scene.blockSignals(True)


if __name__ == "__main__":
    main()
