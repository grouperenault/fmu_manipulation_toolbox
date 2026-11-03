"""The ticks of the time-based clocks of FMI 3.0, scheduled by a container (`intervalVariability` constant, fixed,
tunable, changing and countdown).

`tests/data/clock-ticks` is an FMU compiled for the host. It refuses what FMI 3.0 forbids to an importer, so that a
wrong call stops the simulation. It counts the ticks of its clocks and sums their times: `a.fmu` owns the time-based
clocks, each of them drives the triggered clock of `b.fmu`.
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
    pytest.mark.area("clock-ticks"),
]

STOP_TIME = 3.0
STEP_SIZE = 0.1
CLOCKS = ("constant", "fixed", "tunable", "changing", "countdown")


def _periodic(first, interval, stop=STOP_TIME):
    return [first + i * interval for i in range(int((stop + 1e-6 - first) / interval) + 1)]


def _expected_ticks() -> dict[str, list[float]]:
    changing = [0.1]
    interval = 0.2
    while changing[-1] + interval <= STOP_TIME + 1e-6:
        changing.append(changing[-1] + interval)
        interval += 0.1
    return {
        "constant": _periodic(0.1, 0.3),                    # interval and shift of the modelDescription.xml
        "fixed": _periodic(0.05, 0.25),                     # interval and shift of the FMU
        "tunable": _periodic(0.0, 0.2, 1.0) + _periodic(1.4, 0.4),  # a new interval from t=1, relative to t=1
        "changing": changing,                               # each interval is relative to the previous tick
        "countdown": [0.65] + _periodic(1.0, 0.35),         # not known until t=0.5, then relative to each tick
    }


def _build_fmu():
    with zipfile.ZipFile("no-binaries.fmu", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write("modelDescription.xml")
        for source in Path("sources").iterdir():
            archive.write(source)
    with FMU("no-binaries.fmu") as fmu:
        fmu.apply_operation(OperationCompileSources())
        fmu.repack("a.fmu")
    Path("b.fmu").write_bytes(Path("a.fmu").read_bytes())


def _simulate(clocks=CLOCKS):
    from fmpy import simulate_fmu

    outputs = []
    for clock in clocks:
        outputs += [["a.fmu", f"{name}_{clock}", f"a_{name}_{clock}"] for name in ("count", "sum")]
        outputs += [["b.fmu", f"rx_{name}_{clock}", f"b_{name}_{clock}"] for name in ("count", "sum")]
    Path("ticks.json").write_text(json.dumps({
        "name": "ticks.fmu", "fmu": ["a.fmu", "b.fmu"], "step_size": STEP_SIZE,
        "link": [["a.fmu", f"clk_{clock}", "b.fmu", f"rx_{clock}"] for clock in clocks],
        "output": outputs}))
    Assembly("ticks.json").make_fmu(fmi_version=3)
    return simulate_fmu("ticks.fmu", start_time=0, stop_time=STOP_TIME, step_size=STEP_SIZE, output_interval=STEP_SIZE,
                        validate=False)


@pytest.mark.parametrize("clock", CLOCKS)
def test_ticks_of_one_clock(area_dir, clock):
    _build_fmu()
    result = _simulate([clock])
    expected = _expected_ticks()[clock]

    # The FMU that owns the clock, and the FMU whose triggered clock it drives.
    for fmu in ("a", "b"):
        assert result[f"{fmu}_count_{clock}"][-1] == len(expected)
        assert result[f"{fmu}_sum_{clock}"][-1] == pytest.approx(sum(expected), abs=1e-6)


def test_ticks_of_all_the_clocks_together(area_dir):
    _build_fmu()
    result = _simulate()
    for clock, expected in _expected_ticks().items():
        for fmu in ("a", "b"):
            assert result[f"{fmu}_count_{clock}"][-1] == len(expected), clock
            assert result[f"{fmu}_sum_{clock}"][-1] == pytest.approx(sum(expected), abs=1e-6), clock
