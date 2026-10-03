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

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _capture_package_logger(caplog):
    """Capture the ``fmu_manipulation_toolbox`` logger at DEBUG level so the
    fatal messages emitted by the CLIs are visible to ``caplog`` regardless of
    the handler the CLI installs on it."""
    caplog.set_level(logging.DEBUG, logger="fmu_manipulation_toolbox")
    return caplog


# --------------------------------------------------------------------------- #
#                                  fmutool                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.area("operations")
def test_fmutool_same_input_output_exits(area_dir, caplog):
    sys.argv = ["fmutool", "-input", "bouncing_ball.fmu",
                "-output", "bouncing_ball.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == -3
    assert "different files" in caplog.text


@pytest.mark.area("operations")
def test_fmutool_missing_input_exits(area_dir, caplog):
    sys.argv = ["fmutool", "-input", "does-not-exist.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == -4
    assert "does-not-exist.fmu" in caplog.text


@pytest.mark.area("operations")
def test_fmutool_operation_error_exits(area_dir, caplog):
    # The sample FMU only ships win64 binaries, so requesting a win64 remoting
    # interface (which requires a *win32* source interface) raises an
    # OperationError while the operation is applied → exit code -6.
    sys.argv = ["fmutool", "-input", "bouncing_ball.fmu", "-add-remoting-win64"]

    with pytest.raises(SystemExit) as exc:
        fmutool()

    assert exc.value.code == -6
    assert "win32" in caplog.text


# --------------------------------------------------------------------------- #
#                               fmucontainer                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/bouncing_ball")
def test_fmucontainer_missing_description_exits(area_dir, caplog):
    sys.argv = ["fmucontainer", "-fmu-directory", ".",
                "-container", "does-not-exist.csv"]

    with pytest.raises(SystemExit) as exc:
        fmucontainer()

    assert exc.value.code == -1
    assert "Cannot read file" in caplog.text


@pytest.mark.area("containers/bouncing_ball")
def test_fmucontainer_invalid_fmu_directory_exits(area_dir, caplog):
    # An FMU directory that does not exist is rejected at Assembly construction
    # time with an AssemblyError → exit code -2.
    sys.argv = ["fmucontainer", "-fmu-directory", "no_such_directory",
                "-container", "bouncing.csv"]

    with pytest.raises(SystemExit) as exc:
        fmucontainer()

    assert exc.value.code == -2
    assert "no_such_directory" in caplog.text


# --------------------------------------------------------------------------- #
#                                 fmusplit                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.area("operations")
def test_fmusplit_not_a_container_exits(area_dir, caplog):
    # A plain FMU has no resources/container.txt → FMUSplitterError → exit -1.
    sys.argv = ["fmusplit", "-fmu", "bouncing_ball.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmusplit()

    assert exc.value.code == -1
    assert "not an FMU Container" in caplog.text


@pytest.mark.area("operations")
def test_fmusplit_missing_file_exits(area_dir, caplog):
    sys.argv = ["fmusplit", "-fmu", "does-not-exist.fmu"]

    with pytest.raises(SystemExit) as exc:
        fmusplit()

    assert exc.value.code == -2
    assert "Cannot read file" in caplog.text

