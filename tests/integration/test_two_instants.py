"""The exchange of LS-BUS operations between FMUs of a container, in two super-dense time instants.

An FMU may evaluate its discrete states when its `Tx_Data` is read, and then refuse any input until
`fmi3UpdateDiscreteStates`: the FMUs of SystemDesk do so. `tests/data/ls-bus-strict` is an FMU compiled for the host which
behaves in this way: a call in the wrong order stops the simulation.
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
    pytest.mark.lsbus,
    pytest.mark.slow,
    pytest.mark.needs_fmpy,
    pytest.mark.needs_container,
    pytest.mark.needs_compiler,
    pytest.mark.area("ls-bus-strict"),
]

STOP_TIME = 1.0
STEP_SIZE = 0.1


def _build_fmu():
    with zipfile.ZipFile("no-binaries.fmu", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write("modelDescription.xml")
        for directory in ("sources", "terminalsAndIcons"):
            for source in Path(directory).iterdir():
                archive.write(source)
    with FMU("no-binaries.fmu") as fmu:
        fmu.apply_operation(OperationCompileSources())
        fmu.repack("a.fmu")
    Path("b.fmu").write_bytes(Path("a.fmu").read_bytes())


def _simulate(terminal: str, datalog: bool = False):
    from fmpy import simulate_fmu

    outputs = [["a.fmu", f"sent_{terminal}", "a_sent"], ["a.fmu", f"received_{terminal}", "a_received"],
               ["b.fmu", f"sent_{terminal}", "b_sent"], ["b.fmu", f"received_{terminal}", "b_received"]]
    Path("pair.json").write_text(json.dumps({
        "name": "pair.fmu", "fmu": ["a.fmu", "b.fmu"], "step_size": STEP_SIZE,
        "link": [["a.fmu", terminal, "b.fmu", terminal]], "output": outputs}))
    Assembly("pair.json").make_fmu(fmi_version=3, datalog=datalog)
    return simulate_fmu("pair.fmu", start_time=0, stop_time=STOP_TIME, step_size=STEP_SIZE, output_interval=STEP_SIZE,
                        validate=False)


@pytest.mark.parametrize("terminal, frames", [("constant", 11), ("countdown", 11), ("triggered", 11)])
def test_each_frame_sent_at_the_same_time_by_both_fmus_is_received(area_dir, terminal, frames):
    _build_fmu()
    result = _simulate(terminal)
    assert result["a_sent"][-1] == frames
    assert result["b_sent"][-1] == frames
    assert result["a_received"][-1] == frames
    assert result["b_received"][-1] == frames
