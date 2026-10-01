"""Unit tests for FMU operations (modelDescription.xml manipulations).

Migrated from the legacy ``test_suite.py``. Each test runs in an isolated copy
of ``tests/data/operations`` (see the ``area_dir`` fixture) so generated files
never pollute the source tree.
"""
import pytest

from fmu_manipulation_toolbox.operations import (
    FMU,
    OperationStripTopLevel,
    OperationRenameFromCSV,
    OperationRemoveRegexp,
    OperationKeepOnlyRegexp,
)

from _helpers.assertions import assert_names_match_ref

pytestmark = [pytest.mark.unit, pytest.mark.area("operations")]


def _apply_and_match_ref(target_fmu, operation):
    """Apply an operation on the reference FMU, repack it, and compare the
    dumped variable names against the committed REF-* file."""
    fmu = FMU("bouncing_ball.fmu")
    fmu.apply_operation(operation)
    fmu.repack(target_fmu)
    assert_names_match_ref(target_fmu)


def test_strip_top_level(area_dir):
    _apply_and_match_ref("bouncing_ball-no-tl.fmu", OperationStripTopLevel())


def test_save_names_to_csv(area_dir):
    assert_names_match_ref("bouncing_ball.fmu")


def test_rename_from_csv(area_dir):
    _apply_and_match_ref("bouncing_ball-renamed.fmu",
                         OperationRenameFromCSV("bouncing_ball-modified.csv"))


def test_remove_regexp(area_dir):
    _apply_and_match_ref("bouncing_ball-removed.fmu", OperationRemoveRegexp("e"))


def test_keep_only_regexp(area_dir):
    _apply_and_match_ref("bouncing_ball-keeponly.fmu", OperationKeepOnlyRegexp("e"))

