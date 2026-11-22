"""Errors of the remoting operations that need no remoting binaries: they run on every platform."""
import logging
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox import remoting
from fmu_manipulation_toolbox.operations import FMU, OperationError
from fmu_manipulation_toolbox.remoting import OperationAddFrontendWin64

pytestmark = [pytest.mark.unit, pytest.mark.area("operations")]


def test_missing_remoting_binaries_fail(area_dir, tmp_path, monkeypatch, caplog):
    """Without its client or server binaries the operation fails, and the FMU is left unchanged (D6 of
    `log_consistency.md`): it is no longer saved without its remoting."""
    (tmp_path / "resources").mkdir()                    # no win32 / win64 binaries
    monkeypatch.setattr(remoting, "__file__", str(tmp_path / "remoting.py"))
    with FMU("bouncing_ball.fmu") as fmu, caplog.at_level(logging.DEBUG, logger="fmu_manipulation_toolbox"):
        before = sorted(path.name for path in (Path(fmu.tmp_directory) / "binaries" / "win64").iterdir())
        with pytest.raises(OperationError, match="^Cannot add the remoting client: '.*client_sm.dll' is missing.$"):
            fmu.apply_operation(OperationAddFrontendWin64())
        assert sorted(path.name for path in (Path(fmu.tmp_directory) / "binaries" / "win64").iterdir()) == before
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_remoting_needs_fmi2(area_dir, tmp_path):
    with zipfile.ZipFile("bouncing_ball.fmu") as source, zipfile.ZipFile(tmp_path / "fmi3.fmu", "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "modelDescription.xml":
                data = data.replace(b'fmiVersion="2.0"', b'fmiVersion="3.0"')
            target.writestr(item, data)
    with FMU(str(tmp_path / "fmi3.fmu")) as fmu:
        with pytest.raises(OperationError, match="^Adding remoting is only available for FMI-2.$"):
            fmu.apply_operation(OperationAddFrontendWin64())
