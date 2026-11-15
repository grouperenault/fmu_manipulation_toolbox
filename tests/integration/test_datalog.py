"""Integration tests for the container datalog feature and `datalog2pcap`.

`test_datalog` / `test_datalog3`
reuse the ``containers/bouncing_ball`` and ``containers/VanDerPol`` data sets;
`test_datalog_pcap` converts an LS-BUS datalog CSV to a PCAPNG file. Each test runs
in an isolated copy of its data area (see the ``area_dir`` fixture).
"""
import sys
from pathlib import Path

import pytest

from _helpers.assertions import assert_file_exist, assert_identical_files
from _helpers.simulation import assert_simulation
from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.cli.datalog2pcap import datalog2pcap

pytestmark = [pytest.mark.integration]

WIN = sys.platform == "win32"


@pytest.mark.area("containers/bouncing_ball")
def test_datalog(area_dir):
    assembly = Assembly("bouncing.csv", default_mt=True, debug=True)
    assembly.make_fmu(filename="bouncing-datalog.fmu", datalog=True)
    assert_identical_files("bouncing-datalog/resources/datalog.txt", "REF-datalog.txt")
    if WIN:
        assert_simulation("bouncing-datalog.fmu")
        assert_file_exist("bouncing-datalog.csv")


@pytest.mark.fmi3
@pytest.mark.area("containers/VanDerPol")
def test_datalog3(area_dir):
    assembly = Assembly("VanDerPol.json", default_mt=True, debug=True)
    assembly.make_fmu(filename="VanDerPol-datalog.fmu", datalog=True, fmi_version=3)
    assert_identical_files("VanDerPol-datalog/resources/datalog.txt", "REF-datalog.txt")
    assert_simulation("VanDerPol-datalog.fmu", 0.1)
    assert_file_exist("VanDerPol-Container-datalog.csv")


@pytest.mark.lsbus
@pytest.mark.area("ls-bus")
def test_datalog_pcap(area_dir):
    reference = Path("REF-nodes-only-datalog.pcapng").read_bytes()
    Assembly("nodes-only.json").make_fmu(fmi_version=3, datalog=True)
    sys.argv = ["datalog2pcap", "REF-nodes-only-datalog.csv", "-fmu", "nodes-only.fmu"]
    datalog2pcap()
    assert Path("REF-nodes-only-datalog.pcapng").read_bytes() == reference
