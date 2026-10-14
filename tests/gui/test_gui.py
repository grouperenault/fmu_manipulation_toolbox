"""Tests for the 3 GUI interfaces (FMU Tool, FMU Editor, FMU Container Builder).

These tests verify that the windows
can be instantiated and that basic programmatic interactions work. They require
`PySide6` and `pytest-qt`; the whole module is skipped if the GUI stack (or a
usable Qt platform) is unavailable. Qt is forced to the offscreen platform in
``conftest.py``.
"""
import pytest

# Skip the whole module if the GUI dependencies are not importable.
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmutool.__main__ import MainWindow as FMUToolWindow
    from fmu_manipulation_toolbox.gui.fmueditor.__main__ import MainWindow as FMUEditorWindow
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow as FMUContainerWindow
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"GUI dependencies not available: {exc}", allow_module_level=True)

pytestmark = pytest.mark.gui


@pytest.fixture
def bouncing_ball(data_dir):
    """Absolute path to the sample FMU used by the load tests."""
    return str(data_dir / "operations" / "bouncing_ball.fmu")


# ── FMU Tool GUI ──────────────────────────────────────────────────────────
def test_fmutool_window_opens(qtbot):
    window = FMUToolWindow()
    qtbot.addWidget(window)
    assert window.isVisible()
    assert window.windowTitle() == "FMU Manipulation Toolbox"


def test_fmutool_load_fmu(qtbot, bouncing_ball):
    window = FMUToolWindow()
    qtbot.addWidget(window)
    window.load(bouncing_ball)
    assert "bouncing_ball.fmu" in window.fmu_title.text()


def test_fmutool_operations_buttons_exist(qtbot):
    window = FMUToolWindow()
    qtbot.addWidget(window)
    assert len(window.operations_button_list) == 16


def test_fmutool_busy_cursor_during_operation(qtbot, bouncing_ball):
    """The wait cursor is shown while an operation runs, and restored afterwards, also when it fails."""
    from PySide6.QtCore import Qt
    from fmu_manipulation_toolbox.operations import OperationAbstract, OperationError

    class Probe(OperationAbstract):
        read_only = True
        cursors = []

        def __init__(self, fail=False):
            self.fail = fail

        def closure(self):
            cursor = QApplication.overrideCursor()
            Probe.cursors.append(cursor.shape() if cursor else None)
            if self.fail:
                raise OperationError("probe failure")

    window = FMUToolWindow()
    qtbot.addWidget(window)
    window.load(bouncing_ball)
    window.apply_operation(Probe())
    window.apply_operation(Probe(fail=True))
    assert Probe.cursors == [Qt.CursorShape.WaitCursor, Qt.CursorShape.WaitCursor]
    assert QApplication.overrideCursor() is None
    assert "probe failure" in window.log_widget.toPlainText()


class _FakeCompileOptionsDialog:
    """Replaces `CompileOptionsDialog`: answers with the next of `answers` (`None` = Cancel), records the calls."""
    answers: list = []
    calls: list = []

    def __init__(self, values, toolchain, parent=None):
        _FakeCompileOptionsDialog.calls.append(dict(values))
        self.answer = _FakeCompileOptionsDialog.answers.pop(0)

    def exec(self):
        from PySide6.QtWidgets import QDialog
        return QDialog.DialogCode.Rejected if self.answer is None else QDialog.DialogCode.Accepted

    def values(self):
        return self.answer


@pytest.fixture
def fake_compile_dialog(monkeypatch):
    import fmu_manipulation_toolbox.gui.fmutool.__main__ as fmutool_gui
    monkeypatch.setattr(fmutool_gui, "CompileOptionsDialog", _FakeCompileOptionsDialog)
    _FakeCompileOptionsDialog.answers, _FakeCompileOptionsDialog.calls = [], []
    return _FakeCompileOptionsDialog


@pytest.fixture
def needs_foo_fmu(data_dir, tmp_path):
    """FMI 3.0 Reference FMU without binaries, whose `model.c` only compiles with `FOO` defined."""
    from _helpers.archive import read_entry, rewrite_fmu
    source = data_dir / "compile" / "3.0" / "BouncingBall.fmu"
    model = read_entry(source, "sources/model.c")
    return str(rewrite_fmu(source, tmp_path / "needs-foo.fmu", drop=("binaries/",),
                           replace={"sources/model.c": b'#ifndef FOO\n#error "FOO is not defined"\n#endif\n' + model}))


def _host_binary(window):
    from pathlib import Path
    from fmu_manipulation_toolbox.compiler import SourceCompiler
    return (Path(window.dropped_fmu.fmu.tmp_directory) / "binaries" / SourceCompiler.host_platform(3) /
            f"BouncingBall{SourceCompiler.library_suffix()}")


@pytest.mark.needs_compiler
def test_fmutool_compile_retry_with_options(qtbot, fake_compile_dialog, needs_foo_fmu):
    """After a compilation failure, the dialog asks for options; Retry with the right one succeeds; the options
    are kept and pre-filled for the session."""
    window = FMUToolWindow()
    qtbot.addWidget(window)
    window.load(needs_foo_fmu)
    fake_compile_dialog.answers = [{"compiler_options": "-DFOO", "linker_options": "", "libraries": ""}]
    window.compile_sources()
    assert fake_compile_dialog.calls == [{}]
    assert _host_binary(window).is_file()
    assert window.compile_options["compiler_options"] == "-DFOO"

    # Next click on another FMU: the remembered options are used, no dialog.
    window.load(needs_foo_fmu)
    window.compile_sources()
    assert len(fake_compile_dialog.calls) == 1
    assert _host_binary(window).is_file()


@pytest.mark.needs_compiler
def test_fmutool_compile_cancel(qtbot, fake_compile_dialog, needs_foo_fmu):
    window = FMUToolWindow()
    qtbot.addWidget(window)
    window.load(needs_foo_fmu)
    window.compile_options = {"compiler_options": "-DBAR", "linker_options": "", "libraries": ""}
    fake_compile_dialog.answers = [{"compiler_options": "-DBAZ", "linker_options": "", "libraries": ""}, None]
    window.compile_sources()
    # Two failures (with -DBAR, then -DBAZ), the dialog pre-filled with the last values, then Cancel.
    assert [call["compiler_options"] for call in fake_compile_dialog.calls] == ["-DBAR", "-DBAZ"]
    assert not _host_binary(window).exists()


def test_fmutool_compile_no_dialog_without_sources(qtbot, fake_compile_dialog, data_dir, tmp_path):
    """Not a compilation failure: no dialog."""
    from _helpers.archive import rewrite_fmu
    fmu = rewrite_fmu(data_dir / "compile" / "3.0" / "BouncingBall.fmu", tmp_path / "no-sources.fmu",
                      drop=("binaries/", "sources/"))
    window = FMUToolWindow()
    qtbot.addWidget(window)
    window.load(str(fmu))
    window.compile_sources()
    assert fake_compile_dialog.calls == []
    assert "does not embed sources" in window.log_widget.toPlainText()


def test_fmutool_compile_options_dialog(qtbot):
    from fmu_manipulation_toolbox.compiler import Toolchain
    from fmu_manipulation_toolbox.gui.fmutool.__main__ import CompileOptionsDialog
    dialog = CompileOptionsDialog({"compiler_options": "-DFOO"}, Toolchain("clang", ["cc"], ["c++"]))
    qtbot.addWidget(dialog)
    dialog.edits["libraries"].setText(" foo,bar ")
    assert dialog.values() == {"compiler_options": "-DFOO", "linker_options": "", "libraries": "foo,bar"}
    assert dialog.edits["linker_options"].placeholderText() == "e.g. -L/opt/lib"


@pytest.mark.parametrize("toolchain, linker_example", [
    (("msvc", ["cl"], ["cl"]), "e.g. /LIBPATH:C:\\lib"),
    (("gcc", ["gcc"], ["g++"]), "e.g. -L/opt/lib"),
    (None, "e.g. -L/opt/lib"),
])
def test_fmutool_compile_options_placeholders(qtbot, toolchain, linker_example):
    """The examples of the fields follow the compiler in use."""
    from fmu_manipulation_toolbox.compiler import Toolchain
    from fmu_manipulation_toolbox.gui.fmutool.__main__ import CompileOptionsDialog
    dialog = CompileOptionsDialog({}, Toolchain(*toolchain) if toolchain else None)
    qtbot.addWidget(dialog)
    assert dialog.edits["linker_options"].placeholderText() == linker_example
    msvc = toolchain is not None and toolchain[0] == "msvc"
    assert dialog.edits["compiler_options"].placeholderText().startswith("e.g. /D" if msvc else "e.g. -D")


def test_fmutool_logs_into_its_log_widget(qtbot):
    import logging
    window = FMUToolWindow()
    qtbot.addWidget(window)
    logging.getLogger("fmu_manipulation_toolbox").warning("tool warning")
    assert "WARNING: tool warning" in window.log_widget.toPlainText()


# ── FMU Editor GUI ────────────────────────────────────────────────────────
def test_fmueditor_window_opens(qtbot):
    window = FMUEditorWindow()
    qtbot.addWidget(window)
    assert window.isVisible()
    assert window.windowTitle() == "FMU Variable Editor"


def test_fmueditor_load_fmu(qtbot, bouncing_ball):
    window = FMUEditorWindow()
    qtbot.addWidget(window)
    window.load(bouncing_ball)
    assert window._model.rowCount() > 0


def test_fmueditor_no_unsaved_changes_initially(qtbot, bouncing_ball):
    window = FMUEditorWindow()
    qtbot.addWidget(window)
    window.load(bouncing_ball)
    assert not window._has_unsaved_changes()


def test_fmueditor_status_bar_shows_the_log_and_opens_the_log_window(qtbot):
    import logging
    from PySide6.QtCore import Qt
    window = FMUEditorWindow()
    qtbot.addWidget(window)
    logging.getLogger("fmu_manipulation_toolbox").info("FMU saved as 'out.fmu'.")
    assert window._status_bar.text() == "FMU saved as 'out.fmu'."

    qtbot.mouseClick(window._status_bar, Qt.MouseButton.LeftButton)
    log_window = window._status_bar._log_window
    assert log_window.isVisible()
    assert "FMU saved as 'out.fmu'." in log_window.view.toPlainText()


# ── FMU Container Builder GUI ─────────────────────────────────────────────
def test_fmucontainer_window_opens(qtbot):
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert window.isVisible()
    assert window.windowTitle() == "FMU Container Builder"


def test_fmucontainer_initially_clean(qtbot):
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert not window._dirty


def test_fmucontainer_buttons_exist(qtbot):
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert window._load_button is not None
    assert window._import_button is not None
    assert window._export_button is not None
    assert window._save_button is not None
    assert window._exit_button is not None



def test_fmucontainer_verbose_mode_drives_the_shared_logger(qtbot, capsys):
    import logging
    logger = logging.getLogger("fmu_manipulation_toolbox")
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert logger.level == logging.INFO

    window._debug_checkbox.setChecked(True)
    assert logger.level == logging.DEBUG
    logger.debug("verbose line")
    assert "DEBUG    | verbose line" in capsys.readouterr().out

    window._debug_checkbox.setChecked(False)
    assert logger.level == logging.INFO
    logger.info("quiet line")
    assert "quiet line" not in capsys.readouterr().out


def test_fmucontainer_status_bar_shows_the_log_and_opens_the_log_window(qtbot):
    import logging
    from PySide6.QtCore import Qt
    logger = logging.getLogger("fmu_manipulation_toolbox")
    window = FMUContainerWindow()
    qtbot.addWidget(window)
    assert window.statusBar() is window._status_bar

    logger.info("AI Assistant enabled")
    assert window._status_bar.text() == "AI Assistant enabled"

    qtbot.mouseClick(window._status_bar, Qt.MouseButton.LeftButton)
    log_window = window._status_bar._log_window
    assert log_window.isVisible()
    assert "AI Assistant enabled" in log_window.view.toPlainText()


def test_fmutool_compile_options_dialog_names_the_compiler(qtbot):
    """MSVC is found with its full path: the dialog names the executable only."""
    from PySide6.QtWidgets import QLabel
    from fmu_manipulation_toolbox.compiler import Toolchain
    from fmu_manipulation_toolbox.gui.fmutool.__main__ import CompileOptionsDialog
    cl = r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.40\bin\Hostx64\x64\cl.exe"
    dialog = CompileOptionsDialog({}, Toolchain("msvc", [cl], [cl]))
    qtbot.addWidget(dialog)
    message = dialog.findChildren(QLabel)[0].text()
    assert "msvc (cl.exe)" in message and "Program Files" not in message
