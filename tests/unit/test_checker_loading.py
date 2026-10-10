"""Loading of the checkers added by users (docs/local/fmuport.md, phase 2).

A checker that cannot be imported, for instance because it still imports `FMUPort` (removed in 2.0), is reported
and skipped: it must never stop `fmutool`.
"""
import logging
from types import SimpleNamespace

import pytest

from fmu_manipulation_toolbox import checker
from fmu_manipulation_toolbox.checker import OperationGenericCheck, OperationSemanticCheck, add_from_file, get_checkers

pytestmark = [pytest.mark.unit]

HINT = "FMUPort was removed in 2.0: use ModelVariable"


@pytest.fixture(autouse=True)
def builtin_checkers_only(monkeypatch):
    """`add_from_file` registers into a module-level list: give each test its own copy."""
    monkeypatch.setattr(checker, "_checkers_list", list(checker._checkers_list))


def _write_checker(tmp_path, port_type: str):
    path = tmp_path / "my_checkers.py"
    path.write_text(f"""
from fmu_manipulation_toolbox.operations import OperationAbstract, {port_type}


class CheckNames(OperationAbstract):
    def port_attrs(self, fmu_port: {port_type}) -> int:
        return 0
""")
    return str(path)


def test_checker_with_model_variable_is_added(tmp_path):
    add_from_file(_write_checker(tmp_path, "ModelVariable"))
    assert "CheckNames" in [checker_class.__name__ for checker_class in get_checkers()]


def test_checker_importing_fmuport_is_reported(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        add_from_file(_write_checker(tmp_path, "FMUPort"))
    assert "Cannot load" in caplog.text and HINT in caplog.text
    assert get_checkers()[:2] == [OperationGenericCheck, OperationSemanticCheck]


def test_addon_checker_that_cannot_be_imported_is_skipped(monkeypatch, caplog):
    def load():
        raise ImportError("cannot import name 'FMUPort' from 'fmu_manipulation_toolbox.operations'")

    broken = SimpleNamespace(name="broken", load=load)
    monkeypatch.setattr(checker, "entry_points", lambda group: [broken])
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        checkers = get_checkers()
    assert checkers == [OperationGenericCheck, OperationSemanticCheck]
    assert "Cannot load the addon checker 'broken'" in caplog.text and HINT in caplog.text
