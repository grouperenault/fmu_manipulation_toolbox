"""Error-path / contract tests for the Command Line Interfaces.

These complement ``test_cli.py`` (which covers the happy paths) by pinning the
*observable contract* of each CLI when given invalid or incompatible input: the
process exit code and a stable fragment of the fatal error message. They are
pure-Python, deterministic and platform-independent (no compiled binary, no
simulation), so they run on every OS and Python version.

Each test drives the CLI through ``sys.argv`` (restored by the autouse
``clean_argv`` fixture) inside an isolated copy of its data area (``area_dir``).
The package logger writes fatal messages that pytest captures through
``caplog``; we only assert on contractual substrings, never on the exact
wording or on ANSI colour codes.
"""
import logging
import sys

import pytest

from fmu_manipulation_toolbox.cli.fmutool import fmutool
from fmu_manipulation_toolbox.cli.fmucontainer import fmucontainer
from fmu_manipulation_toolbox.cli.fmusplit import fmusplit
from fmu_manipulation_toolbox.cli.utils import ExitCode

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _capture_package_logger(caplog):
    """Force capture of the ``fmu_manipulation_toolbox`` logger at DEBUG level so
    the fatal messages emitted by the CLIs are visible to ``caplog`` regardless
    of the handler the CLI installs on that logger."""
    caplog.set_level(logging.DEBUG, logger="fmu_manipulation_toolbox")


# --------------------------------------------------------------------------- #
#                                  fmutool                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.area("operations")
def test_fmutool_same_input_output_exits(area_dir, caplog):
    sys.argv = ["fmutool", "-input", "bouncing_ball.fmu",
                "-output", "bouncing_ball.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == ExitCode.USAGE_ERROR
    assert "different files" in caplog.text


@pytest.mark.area("operations")
def test_fmutool_missing_input_exits(area_dir, caplog):
    sys.argv = ["fmutool", "-input", "does-not-exist.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == ExitCode.INPUT_UNREADABLE
    assert "does-not-exist.fmu" in caplog.text


@pytest.mark.area("operations")
def test_fmutool_operation_error_exits(area_dir, caplog):
    # The sample FMU only ships win64 binaries, so requesting a win64 remoting
    # interface (which requires a *win32* source interface) raises an
    # OperationError while the operation is applied → exit code 5 (OPERATION_FAILED).
    sys.argv = ["fmutool", "-input", "bouncing_ball.fmu", "-add-remoting-win64"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == ExitCode.OPERATION_FAILED
    assert "win32" in caplog.text


@pytest.mark.area("operations")
def test_fmutool_not_a_zip_exits(area_dir, caplog):
    with open("not_a_zip.fmu", "w") as file:
        file.write("this is not a zip archive")
    sys.argv = ["fmutool", "-input", "not_a_zip.fmu", "-summary"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == ExitCode.INVALID_INPUT
    assert "not a ZIP archive" in caplog.text


@pytest.mark.area("operations")
def test_fmutool_unreadable_descriptor_exits(area_dir, caplog):
    import zipfile
    with zipfile.ZipFile("broken.fmu", "w") as fmu:
        fmu.writestr("modelDescription.xml", "<fmiModelDescription fmiVersion='2.0'><x>a < b</x>"
                                             "</fmiModelDescription>")
    sys.argv = ["fmutool", "-input", "broken.fmu", "-summary"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == ExitCode.INVALID_INPUT
    assert "not well-formed" in caplog.text


@pytest.mark.area("operations")
def test_fmutool_refused_operation_exits(area_dir, caplog):
    # Keeping no port at all would leave an empty <ModelVariables>: refused (D10).
    sys.argv = ["fmutool", "-input", "bouncing_ball.fmu", "-keep-only-regexp", "nothing-matches",
                "-output", "out.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == ExitCode.OPERATION_FAILED
    assert "remove every variable" in caplog.text
    assert not (area_dir / "out.fmu").exists()


@pytest.mark.area("operations")
def test_fmutool_check_conforming_fmu_succeeds(area_dir, caplog):
    sys.argv = ["fmutool", "-input", "bouncing_ball.fmu", "-check"]
    fmutool()  # no SystemExit: exit status 0
    assert "No semantic error" in caplog.text


@pytest.mark.area("operations")
def test_fmutool_check_non_conforming_fmu_exits(area_dir, caplog):
    import zipfile
    with zipfile.ZipFile("bad.fmu", "w") as fmu:  # output not listed in <Outputs>
        fmu.writestr("modelDescription.xml",
                     '<fmiModelDescription fmiVersion="2.0" modelName="m" guid="{x}">'
                     '<CoSimulation modelIdentifier="m"/><ModelVariables>'
                     '<ScalarVariable name="y" valueReference="1" causality="output"><Real/></ScalarVariable>'
                     '</ModelVariables><ModelStructure/></fmiModelDescription>')
    sys.argv = ["fmutool", "-input", "bad.fmu", "-check", "-output", "bad-copy.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == ExitCode.CHECK_FAILED
    assert "is not listed in <Outputs>" in caplog.text
    assert (area_dir / "bad-copy.fmu").exists()  # the other options are still honoured


@pytest.mark.area("operations")
def test_fmutool_output_error_exits(area_dir, caplog):
    sys.argv = ["fmutool", "-input", "bouncing_ball.fmu", "-output", "no_such_directory/out.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == ExitCode.OUTPUT_ERROR


# --------------------------------------------------------------------------- #
#                               fmucontainer                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/bouncing_ball")
def test_fmucontainer_missing_description_exits(area_dir, caplog):
    sys.argv = ["fmucontainer", "-fmu-directory", ".",
                "-container", "does-not-exist.csv"]

    with pytest.raises(SystemExit) as exc:
        fmucontainer()

    assert exc.value.code == ExitCode.INPUT_UNREADABLE
    assert "Cannot read file" in caplog.text


@pytest.mark.area("containers/bouncing_ball")
def test_fmucontainer_invalid_fmu_directory_exits(area_dir, caplog):
    # An FMU directory that does not exist is rejected at Assembly construction
    # time with an AssemblyError → exit code 4 (INVALID_INPUT).
    sys.argv = ["fmucontainer", "-fmu-directory", "no_such_directory",
                "-container", "bouncing.csv"]

    with pytest.raises(SystemExit) as exc:
        fmucontainer()

    assert exc.value.code == ExitCode.INVALID_INPUT
    assert "no_such_directory" in caplog.text


# --------------------------------------------------------------------------- #
#                                 fmusplit                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.area("operations")
def test_fmusplit_not_a_container_exits(area_dir, caplog):
    # A plain FMU has no resources/container.txt → FMUSplitterError → exit 4 (INVALID_INPUT).
    sys.argv = ["fmusplit", "-fmu", "bouncing_ball.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmusplit()

    assert exc.value.code == ExitCode.INVALID_INPUT
    assert "not an FMU Container" in caplog.text


@pytest.mark.area("operations")
def test_fmusplit_missing_file_exits(area_dir, caplog):
    sys.argv = ["fmusplit", "-fmu", "does-not-exist.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmusplit()

    assert exc.value.code == ExitCode.INPUT_UNREADABLE
    assert "Cannot read file" in caplog.text

