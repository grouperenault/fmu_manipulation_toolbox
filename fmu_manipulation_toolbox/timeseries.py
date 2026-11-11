"""Time series of FMI-LS-REF: stimuli and references of the experiments, simulated outputs.

The CSV files follow the convention of the FMI cross-check (Reference-FMUs, fmpy): comma separator, a header whose
first column is `time` and whose other columns are the names of the FMI variables (quotes allowed), then one row per
instant. Two rows may have the same time: an event, the second row gives the values after it.
"""
import bisect
import csv
import math

from dataclasses import dataclass, field
from pathlib import Path

#: Interpolation of a column between two instants: linear (continuous real variables).
LINEAR = "linear"
#: Interpolation of a column between two instants: previous value (zero-order hold).
HOLD = "hold"


class TimeSeriesError(Exception):
    """A time series that cannot be read or used."""


@dataclass
class TimeSeries:
    """Values of variables over time.

    Attributes:
        times (list[float]): Instants, non-decreasing (equal instants: an event).
        columns (dict[str, list]): Values of each variable, one per instant: text as read in a CSV file, or numbers.
    """
    times: list[float] = field(default_factory=list)
    columns: dict[str, list] = field(default_factory=dict)

    def index(self, time: float) -> int:
        """Index of the last instant that is not after `time` (the value after an event at `time`); -1 before the
        first instant. `time` matches an instant within a relative epsilon of 1e-9, so that a communication point
        computed by the simulation finds the row of its instant."""
        return bisect.bisect_right(self.times, time + 1e-9 * max(1.0, abs(time))) - 1

    def until(self, time: float) -> "TimeSeries":
        """Copy of the series up to `time` included (within the epsilon of `index`)."""
        end = self.index(time) + 1
        return TimeSeries(times=self.times[:end], columns={name: values[:end] for name, values in self.columns.items()})

    def value(self, name: str, time: float, interpolation: str = LINEAR):
        """Value of the variable `name` at `time`: before the first instant, the first value; after the last one, the
        last value; in between, the value interpolated as `interpolation` (`LINEAR` or `HOLD`).

        Raises:
            TimeSeriesError: The series has no instant, or a value to interpolate linearly is not a number.
        """
        if not self.times:
            raise TimeSeriesError("the time series has no instant")
        values = self.columns[name]
        i = self.index(time)
        if i < 0:
            return values[0]
        if interpolation == HOLD or i == len(self.times) - 1:
            return values[i]
        t0, t1 = self.times[i], self.times[i + 1]
        v0, v1 = to_number(values[i]), to_number(values[i + 1])
        fraction = min(max((time - t0) / (t1 - t0), 0.0), 1.0)   # time may precede t0 by the epsilon of index()
        return v0 + (v1 - v0) * fraction


def to_number(value) -> float:
    """A value of a time series as a number: numbers as they are, text parsed (`true` / `false` accepted).

    Raises:
        TimeSeriesError: The value is not a number.
    """
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.lower() in ("true", "false"):
        return 1.0 if text.lower() == "true" else 0.0
    try:
        return float(text)
    except ValueError:
        raise TimeSeriesError(f"'{value}' is not a number") from None


def read_csv(filename: Path | str) -> TimeSeries:
    """Reads a CSV file of the FMI cross-check convention.

    Raises:
        TimeSeriesError: The file has no header, its first column is not `time`, a name is empty or repeated, a row
            has not the number of fields of the header, a time is not a number or the times decrease.
    """
    filename = Path(filename)
    with open(filename, newline="", encoding="utf-8") as file:
        rows = list(csv.reader(file))
    if not rows:
        raise TimeSeriesError(f"'{filename.name}': no header")
    header = [name.strip() for name in rows[0]]
    if header[0] != "time":
        raise TimeSeriesError(f"'{filename.name}': the first column is '{header[0]}', not 'time'")
    names = header[1:]
    for name in names:
        if not name:
            raise TimeSeriesError(f"'{filename.name}': a column has no name")
        if names.count(name) > 1:
            raise TimeSeriesError(f"'{filename.name}': the column '{name}' is repeated")

    series = TimeSeries(columns={name: [] for name in names})
    for line, row in enumerate(rows[1:], start=2):
        if not row:
            continue                                    # empty line, e.g. at the end of the file
        if len(row) != len(header):
            raise TimeSeriesError(f"'{filename.name}' line {line}: {len(row)} fields instead of {len(header)}")
        try:
            time = float(row[0])
        except ValueError:
            raise TimeSeriesError(f"'{filename.name}' line {line}: time '{row[0]}' is not a number") from None
        if not math.isfinite(time):
            raise TimeSeriesError(f"'{filename.name}' line {line}: time '{row[0]}' is not finite")
        if series.times and time < series.times[-1]:
            raise TimeSeriesError(f"'{filename.name}' line {line}: time {time} before the previous one")
        series.times.append(time)
        for name, value in zip(names, row[1:]):
            series.columns[name].append(value.strip())
    return series


@dataclass
class Comparison:
    """Result of the comparison of a simulated variable with its reference.

    Attributes:
        name (str): Name of the variable.
        max_error (float): Maximal absolute error over the instants of the reference (numbers only).
        max_error_time (float | None): Instant of the maximal error.
        failure_time (float | None): First instant where the criterion fails; `None` when the variable matches.
        expected: Value of the reference at `failure_time`.
        simulated: Simulated value at `failure_time`.
    """
    name: str
    max_error: float = 0.0
    max_error_time: float | None = None
    failure_time: float | None = None
    expected: object = None
    simulated: object = None

    @property
    def passed(self) -> bool:
        return self.failure_time is None


def compare(reference: TimeSeries, simulated: TimeSeries, name: str, rtol: float, atol: float,
            interpolation: str = LINEAR, exact: bool = False) -> Comparison:
    """Compares the variable `name` of `simulated` with `reference` at the instants of the reference.

    The simulated value is interpolated as `interpolation`. Numbers (booleans as 0 / 1) match when
    `abs(simulated - reference) <= atol + rtol * abs(reference)`; with `exact` (strings), when the texts are equal. At
    an event of the reference (rows with the same time), the value after it (its last row) is compared.

    Raises:
        TimeSeriesError: A number is not a number, or a series has no instant.
    """
    result = Comparison(name)
    times, values = reference.times, reference.columns[name]
    for i, (time, expected) in enumerate(zip(times, values)):
        if i + 1 < len(times) and times[i + 1] == time:
            continue                                    # before an event: the value after it is compared
        actual = simulated.value(name, time, interpolation)
        if exact:
            passed = str(actual) == str(expected)
        else:
            error = abs(to_number(actual) - to_number(expected))
            if error > result.max_error or result.max_error_time is None:
                result.max_error, result.max_error_time = error, time
            passed = error <= atol + rtol * abs(to_number(expected))    # NaN fails
        if result.failure_time is None and not passed:
            result.failure_time, result.expected, result.simulated = time, expected, actual
    return result
