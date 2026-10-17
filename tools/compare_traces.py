"""Compare the traces of the probe FMUs written by two importers (docs/local/importer_comparison.md, Step 4).

The scenarios are run as FMU Containers (`tools/probe_fmu/scenarios/run_container.py`) and as Simulink models
(`tools/probe_fmu/scenarios/simulink/`); each run leaves the traces of its probes in
`<root>/<scenario>/<importer>/` (`A.csv`, `B.csv`, `C.csv`). This script compares, for each pair of scenario
variants, the traces of each instance and writes a Markdown report:

- the calls of each phase (before `fmi2SetupExperiment`, before `fmi2EnterInitializationMode`, in Initialization
  Mode) with their values;
- the variables whose snapshot (before / after the initialization) differs;
- the steps (number, step sizes, first times);
- the values of the inputs seen by the steps, where they differ;
- the wall time of the simulations (`wall.txt`).

Usage: python compare_traces.py ROOT [-output REPORT.md] [CONTAINER_SCENARIO ...]
"""
import argparse
import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

#: Container variant -> Simulink variants it is compared with.
PAIRS = {
    "S1": ["S1"], "S2": ["S2"], "S3": ["S3"],
    "S4a": ["S4s", "S4m"], "S4b": ["S4s", "S4m"], "S4c": ["S4s", "S4m"], "S4d": ["S4s", "S4m"],
    "S5j": ["S5"], "S5s": ["S5"], "S5r": ["S5"],
    "S6s": ["S6s"], "S6m": ["S6m"],
}
INSTANCES = ("A", "B", "C")
INPUTS = ("u_cont", "u_disc", "u_int", "u_bool")

#: Number of differing step inputs shown per input.
MAX_INPUT_ROWS = 6


@dataclass
class Call:
    seq: int
    function: str
    status: str
    time: str
    h: str
    note: str
    value: str = ""                                                 # value of a call without variable
    values: list[tuple[str, str]] = field(default_factory=list)     # (name, value)

    def text(self) -> str:
        values = ", ".join(f"{name}={value}" for name, value in self.values if name)
        details = " ".join(part for part in (values, self.value, self.note) if part)
        if self.function == "fmi2DoStep":
            details = f"h={self.h}"
        return f"{self.function}({details})" if details else self.function


class Trace:
    """Trace of one probe instance."""

    def __init__(self, filename: Path):
        self.filename = filename
        text = filename.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        self.lines = list(csv.DictReader(io.StringIO(text)))
        self.calls: list[Call] = []
        self.snapshots: dict[str, dict[str, str]] = {}
        self.step_inputs: list[tuple[str, dict[str, str]]] = []      # (time, {input: value})
        for line in self.lines:
            if line["function"] == "SNAPSHOT":
                self.snapshots.setdefault(line["note"], {})[line["name"]] = line["value"]
                continue
            if line["function"] == "fmi2DoStep" and line["note"] == "input":
                self.step_inputs[-1][1][line["name"]] = line["value"]
                continue
            seq = int(line["seq"])
            if not self.calls or self.calls[-1].seq != seq:
                self.calls.append(Call(seq, line["function"], line["status"], line["time"], line["h"],
                                       line["note"] if not line["name"] else "",
                                       line["value"] if not line["name"] else ""))
                if line["function"] == "fmi2DoStep":
                    self.step_inputs.append((line["time"], {}))
            if line["name"]:
                self.calls[-1].values.append((line["name"], line["value"]))
        self.wall = [float(line["wall"]) for line in self.lines]

    def phase(self, start: str | None, end: str) -> list[Call]:
        """Calls after the call `start` (from the first call if None) and before the call `end`."""
        calls, inside = [], start is None
        for call in self.calls:
            if call.function == end:
                break
            if inside and call.function != "fmi2Instantiate":
                calls.append(call)
            if call.function == start:
                inside = True
        return calls

    def steps(self) -> list[Call]:
        return [call for call in self.calls if call.function == "fmi2DoStep"]

    def instance_name(self) -> str:
        return self.calls[0].value if self.calls else ""


def find_trace(directory: Path, instance: str) -> Path | None:
    """Trace of `instance` in `directory` (`A.csv`, or `'A.csv'` written by a quoted trace_file)."""
    for name in (f"{instance}.csv", f"'{instance}.csv'"):
        if (directory / name).exists():
            return directory / name
    return None


def read_wall(directory: Path) -> str:
    path = directory / "wall.txt"
    return f"{float(path.read_text()):.3f} s" if path.exists() else "—"


def same(a: str | None, b: str | None) -> bool:
    """Equal values; numbers within a relative 1e-9 (the importers compute the times differently)."""
    if a == b:
        return True
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))


def time_key(time: str) -> float:
    return round(float(time), 9)


def cell(text: str) -> str:
    return text.replace("|", "\\|") if text else "—"


def calls_text(calls: list[Call]) -> str:
    return "<br>".join(cell(call.text()) for call in calls) or "—"


def step_summary(trace: Trace) -> str:
    steps = trace.steps()
    if not steps:
        return "no step"
    sizes = sorted({call.h for call in steps})
    times = ", ".join(call.time for call in steps[:4])
    return f"{len(steps)} steps, h = {', '.join(sizes)}; t = {times}{', …' if len(steps) > 4 else ''}"


def snapshot_rows(left: Trace, right: Trace, label: str) -> list[str]:
    a, b = left.snapshots.get(label, {}), right.snapshots.get(label, {})
    return [f"| `{name}` | {cell(a.get(name, ''))} | {cell(b.get(name, ''))} |"
            for name in sorted(set(a) | set(b)) if not same(a.get(name), b.get(name)) and name != "trace_file"]


def input_rows(left: Trace, right: Trace) -> list[str]:
    """Inputs seen by the steps at the same time, where they differ."""
    rows = []
    a = {time_key(time): (time, values) for time, values in left.step_inputs}
    b = {time_key(time): values for time, values in right.step_inputs}
    common = [key for key in a if key in b]
    for name in INPUTS:
        differing = [(a[key][0], a[key][1].get(name, ""), b[key].get(name, "")) for key in common
                     if not same(a[key][1].get(name), b[key].get(name))]
        for time, value_a, value_b in differing[:MAX_INPUT_ROWS]:
            rows.append(f"| `{name}` | {time} | {cell(value_a)} | {cell(value_b)} |")
        if len(differing) > MAX_INPUT_ROWS:
            rows.append(f"| `{name}` | … | {len(differing) - MAX_INPUT_ROWS} more | |")
    return rows


def compare_instance(instance: str, left: Trace, right: Trace, names: tuple[str, str]) -> list[str]:
    header = f"| | {names[0]} | {names[1]} |"
    lines = [f"#### Instance {instance}", "", header, "|---|---|---|",
             f"| Instance name | {cell(left.instance_name())} | {cell(right.instance_name())} |"]
    for title, start, end in (("Before `fmi2SetupExperiment`", None, "fmi2SetupExperiment"),
                              ("`fmi2SetupExperiment`", "fmi2Instantiate", "fmi2EnterInitializationMode"),
                              ("Initialization Mode", "fmi2EnterInitializationMode", "fmi2ExitInitializationMode")):
        if title == "`fmi2SetupExperiment`":
            setup = [[call for call in trace.calls if call.function == "fmi2SetupExperiment"] for trace in (left, right)]
            between = [trace.phase("fmi2SetupExperiment", "fmi2EnterInitializationMode") for trace in (left, right)]
            lines.append(f"| `fmi2SetupExperiment` | {calls_text(setup[0])} | {calls_text(setup[1])} |")
            lines.append(f"| Between `fmi2SetupExperiment` and `fmi2EnterInitializationMode` | "
                         f"{calls_text(between[0])} | {calls_text(between[1])} |")
            continue
        lines.append(f"| {title} | {calls_text(left.phase(start, end))} | {calls_text(right.phase(start, end))} |")
    lines.append(f"| Steps | {cell(step_summary(left))} | {cell(step_summary(right))} |")
    lines.append("")

    for label in ("before_initialization", "after_initialization"):
        rows = snapshot_rows(left, right, label)
        lines += [f"Snapshot `{label}`: " + ("same values." if not rows else "differences:"), ""]
        if rows:
            lines += [f"| Variable | {names[0]} | {names[1]} |", "|---|---|---|", *rows, ""]

    rows = input_rows(left, right)
    lines += ["Inputs seen by the steps (same time): " + ("same values." if not rows else "differences:"), ""]
    if rows:
        lines += [f"| Input | Time | {names[0]} | {names[1]} |", "|---|---|---|---|", *rows, ""]
    return lines


def compare(root: Path, container: str, simulink: str) -> list[str]:
    left_dir, right_dir = root / container / "container", root / simulink / "simulink"
    names = (f"container `{container}`", f"Simulink `{simulink}`")
    lines = [f"### {container} (container) vs {simulink} (Simulink)", "",
             f"Wall time: {read_wall(left_dir)} (container), {read_wall(right_dir)} (Simulink).", ""]
    for instance in INSTANCES:
        left, right = find_trace(left_dir, instance), find_trace(right_dir, instance)
        if left is None and right is None:
            continue
        if left is None or right is None:
            lines += [f"#### Instance {instance}", "", f"Trace missing: {left_dir if left is None else right_dir}.", ""]
            continue
        lines += compare_instance(instance, Trace(left), Trace(right), names)
    return lines


def report(root: Path, scenarios: list[str]) -> str:
    lines = ["# Probe traces: FMU Container vs Simulink", "",
             f"Generated by `tools/compare_traces.py` from `{root}`.", ""]
    for container in scenarios:
        for simulink in PAIRS[container]:
            if (root / container / "container").is_dir() and (root / simulink / "simulink").is_dir():
                lines += compare(root, container, simulink)
            else:
                lines += [f"### {container} (container) vs {simulink} (Simulink)", "", "Results missing.", ""]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Compare the probe traces of the FMU Container and Simulink.")
    parser.add_argument("root", type=Path, help="Directory of the results (<root>/<scenario>/<importer>/).")
    parser.add_argument("-output", type=Path, help="Markdown report (default: standard output).")
    parser.add_argument("scenarios", nargs="*", help=f"Container scenarios among {', '.join(PAIRS)}.")
    args = parser.parse_args()

    scenarios = args.scenarios or list(PAIRS)
    unknown = [scenario for scenario in scenarios if scenario not in PAIRS]
    if unknown:
        parser.error(f"unknown scenario(s): {', '.join(unknown)}")
    text = report(args.root, scenarios)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
