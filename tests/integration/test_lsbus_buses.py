"""LIN, FlexRay and Ethernet networks in a container: a Bus Simulation and two nodes exchange frames.

`tests/data/ls-bus-demos` holds the demos of `fmi-ls-bus-examples` as sources, with their headers: FMI-LS-BUS 1.3.0-rc.1
for LIN and Ethernet, and 1.1.0-alpha.1, whose API they use, for FlexRay. They are compiled for the host. The frames must
reach the Bus Simulation, then the other node, and the sender must receive its confirmation.

Only the first exchanges of FlexRay are checked: the startup of the demo does not go further in a container, and without
a reference importer nothing tells yet whether the demo or the container is the cause.
"""
import json
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.checker import OperationLsBusCheck
from fmu_manipulation_toolbox.compiler import OperationCompileSources
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [
    pytest.mark.integration,
    pytest.mark.lsbus,
    pytest.mark.fmi3,
    pytest.mark.slow,
    pytest.mark.needs_fmpy,
    pytest.mark.needs_container,
    pytest.mark.needs_compiler,
    pytest.mark.area("ls-bus-demos"),
]


def _compile(source: str, destination: str):
    with FMU(source) as fmu:
        fmu.apply_operation(OperationCompileSources())
        fmu.repack(destination)


def _simulate(config: dict, step_size: float, stop_time: float) -> str:
    from fmpy import simulate_fmu

    Path("network.json").write_text(json.dumps({"name": "network.fmu", "fmu": ["bus.fmu", "node1.fmu", "node2.fmu"],
                                                "step_size": step_size, **config}))
    Assembly("network.json").make_fmu(fmi_version=3)

    lines = []

    def logger(*args):
        message = args[-1]
        lines.append(message.decode() if isinstance(message, bytes) else str(message))

    simulate_fmu("network.fmu", step_size=step_size, stop_time=stop_time, output_interval=step_size, validate=False,
                 logger=logger, debug_logging=True, relative_tolerance=1e-9)
    return "\n".join(lines)


@pytest.mark.parametrize("fmu", ["lin-node", "lin-bus", "ethernet-node", "ethernet-bus", "flexray-node1", "flexray-bus"])
def test_demos_follow_ls_bus(area_dir, fmu):
    check = OperationLsBusCheck()
    with FMU(f"{fmu}.fmu") as fmu_file:
        fmu_file.apply_operation(check)
    assert check.errors == []


@pytest.mark.parametrize("bus, channel, frame", [("lin", "LinChannel", "LIN frame"),
                                                 ("ethernet", "EthernetChannel", "Ethernet frame")])
def test_frames_of_the_nodes_reach_the_other_node(area_dir, bus, channel, frame):
    _compile(f"{bus}-bus.fmu", "bus.fmu")
    _compile(f"{bus}-node.fmu", "node1.fmu")
    Path("node2.fmu").write_bytes(Path("node1.fmu").read_bytes())

    log = _simulate({"link": [["node1.fmu", channel, "bus.fmu", "Node1"], ["node2.fmu", channel, "bus.fmu", "Node2"]]},
                    step_size=0.1, stop_time=2.0)

    # A frame every 0.3 s from each node, the last ones are sent at t=1.8
    transmitted = log.count(f"Transmitting {frame}")
    assert transmitted == 12
    assert log.count(f"bus.fmu: Received {frame}") == transmitted
    assert log.count(f"Sending confirmation for {frame}") == transmitted
    for node in ("node1.fmu", "node2.fmu"):
        assert log.count(f"{node}: Received {frame}") == transmitted // 2


def test_flexray_start_of_communication(area_dir):
    """The start of communication and the first frames go through the Bus Simulation, in both directions."""
    _compile("flexray-bus.fmu", "bus.fmu")
    _compile("flexray-node1.fmu", "node1.fmu")
    _compile("flexray-node2.fmu", "node2.fmu")

    channel = "FlexRayChannel"
    log = _simulate({"link": [["node1.fmu", channel, "bus.fmu", f"{channel}.Node1"],
                              ["node2.fmu", channel, "bus.fmu", f"{channel}.Node2"]],
                     "start": [["node2.fmu", "IsSecondNode", "true"]]},  # The demo ignores its own start value.
                    step_size=0.001, stop_time=0.05)

    assert "bus.fmu: Received FlexRay cluster configuration" in log
    assert "node2.fmu: Received CAS symbol" in log
    assert "node2.fmu: Received StartCommunication" in log
    assert "bus.fmu: Received frame in cycle 0, slot 1" in log
    assert "node2.fmu: Received frame in cycle 0, slot 1" in log
    assert "node1.fmu: Received transmission confirmation" in log
