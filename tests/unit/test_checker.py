"""Unit test for the FMU compliance checker.

Runs in an isolated copy of
``tests/data/operations``.
"""
import logging

import pytest

from fmu_manipulation_toolbox.checker import OperationGenericCheck
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [pytest.mark.unit, pytest.mark.area("operations")]


def test_compliance_names_the_standard(area_dir, caplog):
    fmu = FMU("bouncing_ball.fmu")
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        fmu.apply_operation(OperationGenericCheck())
    assert "This FMU seems to be compliant with FMI-2." in caplog.messages


def test_checker(area_dir):
    fmu = FMU("bouncing_ball.fmu")
    fmu.apply_operation(OperationGenericCheck())

