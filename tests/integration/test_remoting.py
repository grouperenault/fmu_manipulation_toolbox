"""Integration test for the Remoting feature (adding a win64 interface to a
win32 FMU).

Migrated from the legacy ``test_suite.py``. Requires win32 and the compiled
remoting binaries shipped under ``resources/``; it runs in an isolated copy of
``tests/data/remoting``.
"""
import pytest

from fmu_manipulation_toolbox.operations import FMU
from fmu_manipulation_toolbox.remoting import OperationAddRemotingWin64

from _helpers.simulation import assert_simulation

pytestmark = [
    pytest.mark.integration,
    pytest.mark.needs_remoting,
    pytest.mark.windows_only,
    pytest.mark.area("remoting"),
]


def test_add_remoting_win32(area_dir):
    fmu = FMU("bouncing_ball-win32.fmu")
    fmu.apply_operation(OperationAddRemotingWin64())
    fmu.repack("bouncing_ball-win64.fmu")
    assert_simulation("bouncing_ball-win32.fmu")
    assert_simulation("bouncing_ball-win64.fmu")


