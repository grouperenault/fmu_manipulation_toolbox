"""The output clocks of FMI-3 activated in Event Mode, delivered by a container to the FMUs they are linked to.

`tests/data/clock-relay` is an FMU compiled for the host (see its `sources/model.c`): `source.fmu` ticks its output
clock once, when the Event Mode starts; `relay.fmu` ticks its output clock in `fmi3UpdateDiscreteStates()` when its
input clock has ticked; `sink.fmu` counts the ticks of its input clock. The chain is source -> relay -> sink, with
the sink before the relay in the order of the container.
"""
import json
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.compiler import OperationCompileSources
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fmi3,
    pytest.mark.slow,
    pytest.mark.needs_fmpy,
    pytest.mark.needs_container,
    pytest.mark.needs_compiler,
    pytest.mark.area("clock-relay"),
]


def _with_token(source: str, destination: str, token: str):
    with zipfile.ZipFile(source) as archive_in, zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive_out:
        for item in archive_in.infolist():
            data = archive_in.read(item)
            if item.filename == "modelDescription.xml":
                data = data.replace(b'instantiationToken="{clock-relay}"', f'instantiationToken="{token}"'.encode())
            archive_out.writestr(item, data)


def _simulate(order, relay_token="{clock-relay}"):
    from fmpy import simulate_fmu

    with zipfile.ZipFile("no-binaries.fmu", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write("modelDescription.xml")
        for source in Path("sources").iterdir():
            archive.write(source)
    with FMU("no-binaries.fmu") as fmu:
        fmu.apply_operation(OperationCompileSources())
        fmu.repack("compiled.fmu")
    _with_token("compiled.fmu", "source.fmu", "{clock-relay-source}")
    _with_token("compiled.fmu", "relay.fmu", relay_token)
    _with_token("compiled.fmu", "sink.fmu", "{clock-relay}")

    Path("relay.json").write_text(json.dumps({
        "name": "relay-container.fmu", "fmu": order, "step_size": 0.1, "auto_link": False,
        "link": [["source.fmu", "tx", "relay.fmu", "rx"], ["relay.fmu", "tx", "sink.fmu", "rx"]],
        "output": [["relay.fmu", "rx_count", "relay_rx"], ["relay.fmu", "tx_count", "relay_tx"],
                   ["sink.fmu", "rx_count", "sink_rx"]]}))
    Assembly("relay.json").make_fmu(fmi_version=3)
    result = simulate_fmu("relay-container.fmu", start_time=0, stop_time=1.0, step_size=0.1, output_interval=0.1,
                          validate=False)
    return {name: result[name][-1] for name in ("relay_rx", "relay_tx", "sink_rx")}


@pytest.mark.parametrize("order", [["source.fmu", "relay.fmu", "sink.fmu"], ["sink.fmu", "relay.fmu", "source.fmu"]],
                         ids=["sink-after-relay", "sink-before-relay"])
@pytest.mark.parametrize("relay_token", ["{clock-relay}", "{clock-relay-needs-update}"],
                         ids=["no-update-asked", "update-asked"])
def test_a_clock_ticked_in_the_event_iteration_reaches_its_receiver(area_dir, order, relay_token):
    counts = _simulate(order, relay_token)
    assert counts == {"relay_rx": 1.0, "relay_tx": 1.0, "sink_rx": 1.0}
