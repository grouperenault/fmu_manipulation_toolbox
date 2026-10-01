"""Integration tests for the Command Line Interfaces (`fmutool`, `fmucontainer`,
`fmusplit`).

Migrated from the legacy ``test_suite.py``. Each test runs in an isolated copy of
its data area (see the ``area_dir`` fixture) and drives the CLI by setting
``sys.argv`` (restored automatically by the ``clean_argv`` fixture).
"""
import sys
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.cli.fmutool import fmutool
from fmu_manipulation_toolbox.cli.fmucontainer import fmucontainer
from fmu_manipulation_toolbox.cli.fmusplit import fmusplit

from _helpers.assertions import assert_identical_files

pytestmark = [pytest.mark.integration]


@pytest.mark.area("operations")
def test_fmutool(area_dir):
    sys.argv = ["fmutool", "-input", "bouncing_ball.fmu", "-summary", "-check",
                "-dump-csv", "cli-bouncing_ball.csv"]
    fmutool()
    assert_identical_files("cli-bouncing_ball.csv", "REF-bouncing_ball.csv")


@pytest.mark.area("containers/bouncing_ball")
def test_fmucontainer_csv(area_dir):
    sys.argv = ["fmucontainer", "-container", "cli-bouncing.csv",
                "-fmu-directory", ".", "-mt", "-debug"]
    fmucontainer()
    assert_identical_files("REF-container.txt", "cli-bouncing/resources/container.txt")


@pytest.mark.area("containers/arch")
def test_fmucontainer_json(area_dir):
    sys.argv = ["fmucontainer", "-fmu-directory", ".", "-container", "cli-flat.json", "-dump"]
    fmucontainer()
    assert_identical_files("REF-cli-flat-dump.json", "cli-flat-dump.json")


@pytest.mark.area("containers/ssp")
def test_fmusplit_ssp(area_dir):
    # Build the SSP container first. The legacy test relied on `test_container_ssp`
    # running earlier and leaving `bouncing.fmu` behind (an execution-order
    # dependency); building it here makes the test self-contained.
    Assembly("bouncing.ssp").make_fmu()
    sys.argv = ["fmusplit", "-fmu", "bouncing.fmu"]
    fmusplit()
    assert Path("bouncing.dir/bb_position.fmu").exists()
    assert Path("bouncing.dir/bb_velocity.fmu").exists()
    assert_identical_files("REF-split-bouncing.json", "bouncing.dir/bouncing.json")

