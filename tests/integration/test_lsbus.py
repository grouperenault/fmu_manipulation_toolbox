"""Integration tests for the LS-BUS feature (bus/node FMU containers).

Runs in an isolated copy of
``tests/data/ls-bus``; the container is built with datalog enabled and the
simulation log / datalog CSV are compared against their REF-* counterparts (the time of the datalog within a
relative tolerance: its last bit depends on the platform).
"""
from pathlib import Path

import pytest

from _helpers.assertions import assert_equivalent_csv
from _helpers.simulation import assert_simulation_log
from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.cli.datalog2pcap import DatalogConverter

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
    assert_equivalent_csv("bus+nodes-datalog.csv", "REF-bus+nodes-datalog.csv")


def test_ls_bus_frames_of_the_bus_reach_the_nodes(area_dir):
    """A frame sent by a Bus Simulation on a time-based clock is delivered while this clock is active."""
    Assembly("bus+nodes.json").make_fmu(fmi_version=3, datalog=True)
    assert_simulation_log("bus+nodes.fmu", 0.1)
    log = Path("log-bus+nodes.txt").read_text()
    for node in ("node1.fmu", "node2.fmu"):
        assert f"{node}: Set RX buffer" in log
        assert f"{node}: Received CAN frame" in log


def test_ls_bus_nodes_only(area_dir):
    assembly = Assembly("nodes-only.json")
    assembly.make_fmu(fmi_version=3, datalog=True)
    assert_simulation_log("nodes-only.fmu", 0.1)
    assert_equivalent_csv("nodes-only-datalog.csv", "REF-nodes-only-datalog.csv")

    # Both nodes send at the same time on their triggered clocks: each of them receives the frames of the other one.
    log = Path("log-nodes-only.txt").read_text()
    for sender, receiver in (("node1.fmu", "node2.fmu"), ("node2.fmu", "node1.fmu")):
        sent = log.count(f"{sender}: Transmitting CAN frame")
        assert sent > 0
        assert log.count(f"{receiver}: Received CAN frame") == sent


def test_ls_bus_datalog_with_a_decimal_comma(area_dir, decimal_comma_locale):
    """The datalog follows the locale of the importer, with a semicolon between its columns: it holds the same values,
    and `datalog2pcap` makes the same capture out of it."""
    from fmpy import simulate_fmu

    reference = Path("REF-nodes-only-datalog.pcapng").read_bytes()
    Assembly("nodes-only.json").make_fmu(fmi_version=3, datalog=True)
    simulate_fmu("nodes-only.fmu", step_size=0.1, stop_time=10, relative_tolerance=1e-9, output_interval=0.1,
                 validate=True)

    assert Path("nodes-only-datalog.csv").read_text().startswith("time;")
    assert_equivalent_csv("nodes-only-datalog.csv", "REF-nodes-only-datalog.csv")

    DatalogConverter("nodes-only-datalog.csv", "nodes-only.fmu").convert()
    assert Path("nodes-only-datalog.pcapng").read_bytes() == reference


def test_ls_bus_capture_has_each_operation_once(area_dir):
    """Each operation exchanged is once in the capture, also the ones of a Bus Simulation on its scheduled Tx_Clock."""
    Assembly("bus+nodes.json").make_fmu(fmi_version=3, datalog=True)
    assert_simulation_log("bus+nodes.fmu", 0.1)
    log = Path("log-bus+nodes.txt").read_text()

    converter = DatalogConverter("bus+nodes-datalog.csv", "bus+nodes.fmu")
    converter.convert()

    # And the operations prepared in Initialization Mode, sent in the first Event Mode: the two Configuration operations
    # (baud rate, arbitration lost behavior) of each node, which the nodes do not log.
    assert converter.nb_operations == (log.count("Transmitting CAN frame")
                                       + log.count("Sending confirmation for CAN frame")
                                       + log.count("Sending CAN frame") + 2 * 2)
