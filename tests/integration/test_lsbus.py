"""Integration tests for the LS-BUS feature (bus/node FMU containers).

Migrated from the legacy ``test_suite.py``. Runs in an isolated copy of
``tests/data/ls-bus``; the container is built with datalog enabled and the
simulation log / datalog CSV are compared against their REF-* counterparts.
"""
import pytest

from fmu_manipulation_toolbox.assembly import Assembly

from _helpers.assertions import assert_identical_files
from _helpers.simulation import assert_simulation_log

pytestmark = [
    pytest.mark.integration,
    pytest.mark.lsbus,
    pytest.mark.fmi3,
    pytest.mark.area("ls-bus"),
]


def test_ls_bus_nodes_and_bus(area_dir):
    assembly = Assembly("bus+nodes.json")
    assembly.make_fmu(fmi_version=3, datalog=True)
    assert_simulation_log("bus+nodes.fmu", 0.1)
    assert_identical_files("bus+nodes-datalog.csv", "REF-bus+nodes-datalog.csv")


def test_ls_bus_nodes_only(area_dir):
    assembly = Assembly("nodes-only.json")
    assembly.make_fmu(fmi_version=3, datalog=True)
    assert_simulation_log("nodes-only.fmu", 0.1)
    assert_identical_files("nodes-only-datalog.csv", "REF-nodes-only-datalog.csv")

