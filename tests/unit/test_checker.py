"""Unit test for the FMU compliance checker.

Migrated from the legacy ``test_suite.py``. Runs in an isolated copy of
``tests/data/operations``.
"""
import pytest

from fmu_manipulation_toolbox.operations import FMU
from fmu_manipulation_toolbox.checker import OperationGenericCheck

pytestmark = [pytest.mark.unit, pytest.mark.area("operations")]


def test_checker(area_dir):
    fmu = FMU("bouncing_ball.fmu")
    fmu.apply_operation(OperationGenericCheck())

