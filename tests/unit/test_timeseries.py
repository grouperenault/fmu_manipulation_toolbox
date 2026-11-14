"""Time series of FMI-LS-REF: CSV reading, interpolation and comparison (`fmu_manipulation_toolbox.timeseries`)."""
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.timeseries import HOLD, LINEAR, TimeSeries, TimeSeriesError, compare, read_csv, to_number

pytestmark = [pytest.mark.unit, pytest.mark.lsref]

DATA_DIR = Path(__file__).parent.parent / "data"


def _csv(tmp_path: Path, content: str) -> Path:
    filename = tmp_path / "series.csv"
    filename.write_text(content)
    return filename


def test_read_csv(tmp_path):
    series = read_csv(_csv(tmp_path, 'time,"x",y\n0,1,true\n0.5,2,false\n0.5,3,true\n\n'))
    assert series.times == [0.0, 0.5, 0.5]
    assert series.columns == {"x": ["1", "2", "3"], "y": ["true", "false", "true"]}


def test_read_reference_of_bouncing_ball():
    series = read_csv(DATA_DIR / "compile" / "REF-BouncingBall.csv")
    assert list(series.columns) == ["h", "v"]
    assert series.times[0] == 0.0 and series.times[-1] == pytest.approx(3.0)


@pytest.mark.parametrize("content, message", [
    ("", "no header"),
    ("t,x\n0,1\n", "the first column is 't', not 'time'"),
    ("time,x,\n0,1,2\n", "a column has no name"),
    ("time,x,x\n0,1,2\n", "the column 'x' is repeated"),
    ("time,x\n0,1,2\n", "line 2: 3 fields instead of 2"),
    ("time,x\nzero,1\n", "line 2: time 'zero' is not a number"),
    ("time,x\nnan,1\n", "line 2: time 'nan' is not finite"),
    ("time,x\n1,1\n0,1\n", "line 3: time 0.0 before the previous one"),
])
def test_bad_csv(tmp_path, content, message):
    with pytest.raises(TimeSeriesError, match=message):
        read_csv(_csv(tmp_path, content))


def test_to_number():
    assert to_number("1.5") == 1.5 and to_number(2) == 2.0
    assert to_number(" true ") == 1.0 and to_number("False") == 0.0
    with pytest.raises(TimeSeriesError, match="'abc' is not a number"):
        to_number("abc")


SERIES = TimeSeries(times=[0.0, 1.0, 1.0, 2.0], columns={"x": ["0", "10", "20", "40"], "s": ["a", "b", "c", "d"]})


@pytest.mark.parametrize("time, linear, hold", [
    (-1.0, "0", "a"),           # before the first instant: first value
    (0.0, 0.0, "a"),
    (0.25, 2.5, "a"),
    (1.0, 20.0, "c"),           # event: the value after it
    (1.0 - 1e-12, 20.0, "c"),   # a communication point computed with a rounding error finds its instant
    (1.5, 30.0, "c"),
    (2.0, "40", "d"),
    (3.0, "40", "d"),           # after the last instant: last value
])
def test_interpolation(time, linear, hold):
    assert SERIES.value("x", time, LINEAR) == linear
    assert SERIES.value("s", time, HOLD) == hold


@pytest.mark.parametrize("time, times", [
    (1.0, [0.0, 1.0, 1.0]),             # the instants of an event at the end are kept
    (1.0 - 1e-12, [0.0, 1.0, 1.0]),     # within the epsilon of index()
    (1.5, [0.0, 1.0, 1.0]),
    (-1.0, []),
])
def test_until(time, times):
    series = SERIES.until(time)
    assert series.times == times
    assert all(len(values) == len(times) for values in series.columns.values())
    assert len(SERIES.times) == 4           # the series itself is not modified


def test_empty_series():
    with pytest.raises(TimeSeriesError, match="no instant"):
        TimeSeries(columns={"x": []}).value("x", 0.0)


def test_compare_passes():
    reference = TimeSeries(times=[0.0, 1.0, 2.0], columns={"x": ["0", "1", "2"]})
    simulated = TimeSeries(times=[0.0, 0.5, 1.0, 1.5, 2.0], columns={"x": [0.0, 0.5, 1.0005, 1.5, 2.0]})
    result = compare(reference, simulated, "x", rtol=1e-3, atol=1e-6)
    assert result.passed
    assert result.max_error == pytest.approx(5e-4) and result.max_error_time == 1.0


def test_compare_fails():
    reference = TimeSeries(times=[0.0, 1.0, 2.0], columns={"x": ["0", "1", "2"]})
    simulated = TimeSeries(times=[0.0, 1.0, 2.0], columns={"x": [1e-5, 1.0, 2.5]})
    result = compare(reference, simulated, "x", rtol=1e-3, atol=1e-6)
    assert not result.passed
    assert result.failure_time == 0.0                    # atol only at 0
    assert result.max_error == pytest.approx(0.5) and result.max_error_time == 2.0


def test_compare_nan_fails():
    reference = TimeSeries(times=[0.0], columns={"x": ["1"]})
    simulated = TimeSeries(times=[0.0], columns={"x": [float("nan")]})
    assert not compare(reference, simulated, "x", rtol=1e-3, atol=1e-6).passed


def test_compare_strings_exactly():
    reference = TimeSeries(times=[0.0, 1.0], columns={"s": ["a", "b"]})
    assert compare(reference, TimeSeries(times=[0.0, 1.0], columns={"s": ["a", "b"]}), "s", 1e-3, 1e-6,
                   HOLD, exact=True).passed
    result = compare(reference, TimeSeries(times=[0.0, 1.0], columns={"s": ["a", "c"]}), "s", 1e-3, 1e-6,
                     HOLD, exact=True)
    assert (result.failure_time, result.expected, result.simulated) == (1.0, "b", "c")


def test_compare_held_values():
    """A discrete output has no intermediate value: held between the communication points."""
    reference = TimeSeries(times=[0.5], columns={"i": ["0"]})
    simulated = TimeSeries(times=[0.0, 1.0], columns={"i": [0, 10]})
    assert compare(reference, simulated, "i", 1e-3, 1e-6, HOLD).passed
    assert not compare(reference, simulated, "i", 1e-3, 1e-6, LINEAR).passed


def test_compare_value_after_an_event():
    reference = TimeSeries(times=[0.0, 1.0, 1.0, 2.0], columns={"x": ["0", "5", "-5", "-5"]})
    simulated = TimeSeries(times=[0.0, 1.0, 2.0], columns={"x": [0.0, -5.0, -5.0]})
    assert compare(reference, simulated, "x", 1e-3, 1e-6, HOLD).passed
    result = compare(reference, TimeSeries(times=[0.0, 1.0, 2.0], columns={"x": [0.0, 5.0, -5.0]}), "x", 1e-3, 1e-6,
                     HOLD)
    assert (result.failure_time, result.expected, result.simulated) == (1.0, "-5", 5.0)
