"""The ticks of the time-based clocks of FMI 3.0, scheduled by a container (`intervalVariability` constant, fixed,
tunable, changing and countdown).

`tests/data/clock-ticks` is an FMU compiled for the host. It refuses what FMI 3.0 forbids to an importer, so that a
wrong call stops the simulation. It counts the ticks of its clocks and sums their times: `a.fmu` owns the time-based
clocks, each of them drives the triggered clock of `b.fmu`.
"""
import csv
import json
import locale
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
#: Every time-based clock of the FMU, the faulty ones included
ALL_CLOCKS = CLOCKS + ("repeated", "forgetful", "silent", "unwritten", "invalid")


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


def _declaring(source: str, destination: str, clocks):
    """Copy of the FMU `source` whose modelDescription.xml declares, of its time-based clocks, only `clocks`.

    The container schedules every time-based input clock that is not linked: the clocks out of a test, some of them
    faulty on purpose, must not be declared."""
    kept = {f"clk_{clock}" for clock in clocks}
    with zipfile.ZipFile(source) as archive_in, zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive_out:
        for item in archive_in.infolist():
            data = archive_in.read(item)
            if item.filename == "modelDescription.xml":
                lines = data.decode("utf-8").splitlines(keepends=True)
                data = "".join(line for line in lines
                               if not ('<Clock name="clk_' in line and line.split('"')[1] not in kept)).encode("utf-8")
            archive_out.writestr(item, data)


def _build_fmu(clocks=ALL_CLOCKS, interval_function=True):
    """`a.fmu` owns the time-based clocks `clocks`; `b.fmu` has none, only the triggered clocks they drive.

    Without `interval_function`, the FMUs do not export fmi3GetIntervalDecimal."""
    if not interval_function:
        model = Path("sources/model.c")
        model.write_text(model.read_text().replace("fmi3Status fmi3GetIntervalDecimal(",
                                                   "fmi3Status unexported_GetIntervalDecimal("))
    with zipfile.ZipFile("no-binaries.fmu", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write("modelDescription.xml")
        for source in Path("sources").iterdir():
            archive.write(source)
    with FMU("no-binaries.fmu") as fmu:
        fmu.apply_operation(OperationCompileSources())
        fmu.repack("compiled.fmu")
    _declaring("compiled.fmu", "a.fmu", clocks)
    _declaring("compiled.fmu", "b.fmu", ())


def _simulate(clocks=CLOCKS, logger=None, datalog=False):
    from fmpy import simulate_fmu

    outputs = []
    for clock in clocks:
        outputs += [["a.fmu", f"{name}_{clock}", f"a_{name}_{clock}"] for name in ("count", "sum")]
        outputs += [["b.fmu", f"rx_{name}_{clock}", f"b_{name}_{clock}"] for name in ("count", "sum")]
    Path("ticks.json").write_text(json.dumps({
        "name": "ticks.fmu", "fmu": ["a.fmu", "b.fmu"], "step_size": STEP_SIZE,
        "link": [["a.fmu", f"clk_{clock}", "b.fmu", f"rx_{clock}"] for clock in clocks],
        "output": outputs}))
    Assembly("ticks.json").make_fmu(fmi_version=3, datalog=datalog)
    return simulate_fmu("ticks.fmu", start_time=0, stop_time=STOP_TIME, step_size=STEP_SIZE, output_interval=STEP_SIZE,
                        validate=False, logger=logger)


@pytest.mark.parametrize("clock", CLOCKS)
def test_ticks_of_one_clock(area_dir, clock):
    _build_fmu([clock])
    result = _simulate([clock])
    expected = _expected_ticks()[clock]

    # The FMU that owns the clock, and the FMU whose triggered clock it drives.
    for fmu in ("a", "b"):
        assert result[f"{fmu}_count_{clock}"][-1] == len(expected)
        assert result[f"{fmu}_sum_{clock}"][-1] == pytest.approx(sum(expected), abs=1e-6)


def test_tick_announced_again_at_the_same_time_waits_for_a_step(area_dir):
    """A clock ticks at most once per time instant: the FMU may need a step to go on, so that ticking it again in the
    same Event Mode would never end (the FlexRay nodes of `fmi-ls-bus-examples` do so)."""
    _build_fmu(["repeated"])
    result = _simulate(["repeated"])
    for fmu in ("a", "b"):
        assert result[f"{fmu}_count_repeated"][-1] == 2
        assert result[f"{fmu}_sum_repeated"][-1] == pytest.approx(2 * 0.25, abs=1e-6)


def test_announced_tick_is_kept_if_the_fmu_answers_not_yet_known(area_dir):
    """FMI 3.0 does not allow this answer about a tick already announced, but it must not lose this tick."""
    _build_fmu(["forgetful"])
    result = _simulate(["forgetful"])
    for fmu in ("a", "b"):
        assert result[f"{fmu}_count_forgetful"][-1] == 1
        assert result[f"{fmu}_sum_forgetful"][-1] == pytest.approx(0.25, abs=1e-6)


@pytest.mark.parametrize("clock", ["silent", "invalid"])
def test_no_tick_without_a_valid_qualifier(area_dir, clock):
    """An FMU that writes no qualifier, or an invalid one, announces nothing: the clock does not tick."""
    messages = []

    def logger(*args):
        messages.append(args[-1].decode() if isinstance(args[-1], bytes) else str(args[-1]))

    _build_fmu([clock])
    result = _simulate([clock], logger=logger)
    for fmu in ("a", "b"):
        assert result[f"{fmu}_count_{clock}"][-1] == 0
    assert not any("has no previous interval" in message for message in messages)


def test_new_interval_without_its_value_is_refused(area_dir):
    """A negative interval, here the one left by an FMU that does not write it, stops the simulation."""
    from fmpy.fmi1 import FMICallException

    _build_fmu(["unwritten"])
    with pytest.raises(FMICallException):
        _simulate(["unwritten"])


def test_fmi3_get_interval_decimal_is_only_required_by_the_clocks_that_need_it(area_dir):
    """FMI 3.0.1 (2.5): an importer should not rely on the functions it does not need. A clock whose interval is
    declared by the modelDescription.xml does not need fmi3GetIntervalDecimal: its FMU may not export it."""
    _build_fmu(["constant"], interval_function=False)
    result = _simulate(["constant"])
    expected = _expected_ticks()["constant"]
    for fmu in ("a", "b"):
        assert result[f"{fmu}_count_constant"][-1] == len(expected)


def test_fmi3_get_interval_decimal_missing_for_a_clock_that_needs_it(area_dir):
    """A tunable clock without declared interval needs fmi3GetIntervalDecimal: the container is refused when it is
    loaded, with the reason."""
    messages = []

    def logger(*args):
        messages.append(args[-1].decode() if isinstance(args[-1], bytes) else str(args[-1]))

    _build_fmu(["tunable"], interval_function=False)
    with pytest.raises(Exception):
        _simulate(["tunable"], logger=logger)
    assert any("does not export fmi3GetIntervalDecimal, needed by its tunable clock" in message
               for message in messages), messages


def test_declared_interval_and_shift_with_a_decimal_comma(area_dir, decimal_comma_locale):
    """The interval and the shift declared by the modelDescription.xml are read from `container.txt` with a dot,
    whatever the numeric locale of the importer."""
    _build_fmu(["constant"])
    result = _simulate(["constant"])
    assert locale.localeconv()["decimal_point"] == ","  # The locale of the importer is unchanged.

    expected = _expected_ticks()["constant"]
    assert result["a_count_constant"][-1] == len(expected)
    assert result["a_sum_constant"][-1] == pytest.approx(sum(expected), abs=1e-6)


@pytest.mark.parametrize("clock", ["constant", "fixed", "tunable", "changing", "countdown"])
def test_datalog_shows_each_tick_once(area_dir, clock):
    """A scheduled clock is active on one row of the datalog per tick, at the time of this tick."""
    _build_fmu([clock])
    _simulate([clock], datalog=True)
    with open("ticks-datalog.csv", newline="") as file:
        ticks = [float(row["time"]) for row in csv.DictReader(file) if row[f"a.clk_{clock}"] == "1"]
    assert ticks == pytest.approx(_expected_ticks()[clock], abs=1e-6)


def test_ticks_of_all_the_clocks_together(area_dir):
    _build_fmu(CLOCKS)
    result = _simulate()
    for clock, expected in _expected_ticks().items():
        for fmu in ("a", "b"):
            assert result[f"{fmu}_count_{clock}"][-1] == len(expected), clock
            assert result[f"{fmu}_sum_{clock}"][-1] == pytest.approx(sum(expected), abs=1e-6), clock
