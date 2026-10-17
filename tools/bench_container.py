"""
Benchmark of the container runtime (`docs/local/container_perf.md`): builds reference containers, simulates each one
several times with fmpy, and prints for each case the time of the simulation loop (`doStep` only), the number of FMI calls of the input and
output exchanges of one internal step (port by port, and grouped by type), and a digest of the results (they must not
change from one version of the runtime to the next).

    python tools/bench_container.py                    # every case
    python tools/bench_container.py --list             # their names
    python tools/bench_container.py A-parallel C-rk4   # some of them
    python tools/bench_container.py --runs 10 --stop-time 2

The FMUs come from `tests/data` (`compile/3.0/Feedthrough.fmu`, `containers/VanDerPol/VanDerPol.fmu`,
`containers/mt/1.fmu`), copied into a
temporary directory. Requires fmpy, and the container runtime built for the host (`cmake -B build -S container`).
Not shipped, not run by the tests.
"""

import argparse
import hashlib
import logging
import os
import re
import shutil
import statistics
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fmu_manipulation_toolbox.container import FMUContainer       # noqa: E402

DATA = ROOT / "tests" / "data"
STEP_SIZE = 0.001                       # internal time step of the containers
COMMUNICATION_STEP = 0.01               # step of the importer: 10 internal steps

#: Ports of `Feedthrough.fmu` (`<name>_input` -> `<name>_output`) linked from one instance to the next (no FMI-3
#: `Enumeration`: the container handles it as an `Int32`).
PORTS = ("Float32_continuous", "Float64_continuous", "Float64_discrete", "Int8", "UInt8", "Int16", "UInt16", "Int32",
         "UInt32", "Int64", "UInt64", "Boolean", "String")
#: Number of chained instances of Feedthrough in the cases A: 13 ports in and 13 out each.
INSTANCES = 20

#: name -> function building the container in the current directory, returning the outputs to digest and extra
#: start values of the simulation
CASES: dict[str, Callable[[], tuple[list[str], dict]]] = {}
#: name -> default stop time, for about 1 s of computation on a laptop
STOP_TIMES: dict[str, float] = {}


def case(name: str, stop_time: float):
    def register(function):
        CASES[name] = function
        STOP_TIMES[name] = stop_time
        return function
    return register


def me_only(source: str, target: str):
    """Copy of an FMU without its Co-Simulation interface: the container embeds it in Model-Exchange mode."""
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "modelDescription.xml":
                data = re.sub(rb"<CoSimulation\b.*?/>", b"", data, flags=re.DOTALL)
            zout.writestr(item, data)


def many_ports(mode: str) -> tuple[list[str], dict]:
    container = FMUContainer("bench", ".", fmi_version=3)
    container.get_fmu("VanDerPol.fmu")
    names = ["Feedthrough.fmu"] + [f"Feedthrough-{i}.fmu" for i in range(1, INSTANCES)]
    for name in names:
        container.get_fmu("Feedthrough.fmu", name=name)
    for port in PORTS:
        if port != "String":
            container.add_link("VanDerPol.fmu", "x0", names[0], f"{port}_input")
    for upstream, downstream in zip(names, names[1:]):
        for port in PORTS:
            container.add_link(upstream, f"{port}_output", downstream, f"{port}_input")
    container.add_output(names[-1], "Float64_continuous_output", "y")
    container.make_fmu("bench.fmu", step_size=STEP_SIZE, mt=mode == "mt", sequential=mode == "sequential")
    return ["y"], {}


for _mode, _stop_time in (("parallel", 40.0), ("sequential", 45.0), ("mt", 16.0)):
    case(f"A-{_mode}", _stop_time)(lambda mode=_mode: many_ports(mode))


@case("B-uncoupled", 1500.0)
def me_uncoupled():
    container = FMUContainer("bench", ".", fmi_version=3)
    for i in range(4):
        container.get_fmu("VanDerPolME.fmu", name=f"VanDerPolME-{i}.fmu" if i else None)
    container.add_output("VanDerPolME.fmu", "x0", "y")
    container.make_fmu("bench.fmu", step_size=STEP_SIZE)
    return ["y"], {}


def me_coupled(solver: int):
    container = FMUContainer("bench", ".", fmi_version=3)
    container.get_fmu("VanDerPolME.fmu")
    names = ["FeedthroughME.fmu"] + [f"FeedthroughME-{i}.fmu" for i in range(1, 4)]
    for name in names:
        container.get_fmu("FeedthroughME.fmu", name=name)
    container.add_link("VanDerPolME.fmu", "x0", names[0], "Float64_continuous_input")
    container.add_link("VanDerPolME.fmu", "x1", names[0], "Float32_continuous_input")
    for upstream, downstream in zip(names, names[1:]):
        for port in ("Float64_continuous", "Float32_continuous"):
            container.add_link(upstream, f"{port}_output", downstream, f"{port}_input")
    container.add_output(names[-1], "Float64_continuous_output", "y")
    container.make_fmu("bench.fmu", step_size=STEP_SIZE)
    return ["y"], {"container.solver": solver}


case("C-euler", 480.0)(lambda: me_coupled(0))
case("C-rk4", 350.0)(lambda: me_coupled(1))


@case("D-mixed", 1000.0)
def me_fed_by_cs():
    container = FMUContainer("bench", ".", fmi_version=3)
    container.get_fmu("VanDerPol.fmu")
    names = ["FeedthroughME.fmu"] + [f"FeedthroughME-{i}.fmu" for i in range(1, 4)]
    for name in names:
        container.get_fmu("FeedthroughME.fmu", name=name)
        container.add_link("VanDerPol.fmu", "x0", name, "Float64_continuous_input")
        container.add_link("VanDerPol.fmu", "x1", name, "Float32_continuous_input")
    container.add_output(names[-1], "Float64_continuous_output", "y")
    container.make_fmu("bench.fmu", step_size=STEP_SIZE)
    return ["y"], {}


@case("E-same-type", 400.0)
def same_type_ports():
    """Chained instances of `containers/mt/1.fmu`: 5 `Float64` inputs and 5 outputs each, where grouping by type
    divides the number of calls by 5."""
    container = FMUContainer("bench", ".", fmi_version=3)
    names = ["1.fmu"] + [f"1-{i}.fmu" for i in range(1, INSTANCES)]
    for name in names:
        container.get_fmu("1.fmu", name=name)
    for upstream, downstream in zip(names, names[1:]):
        for k in range(5):
            container.add_link(upstream, f"y{k}", downstream, f"u{k}")
    container.add_output(names[-1], "y0", "y")
    container.make_fmu("bench.fmu", step_size=STEP_SIZE)
    return ["y"], {}


def exchange_calls(txt: Path) -> tuple[int, int]:
    """FMI calls of the input and output exchanges of every FMU for one internal step: port by port, and grouped
    by type (strings and binaries stay port by port), from the per-FMU sections of `container.txt`."""
    lines = txt.read_text().splitlines()
    per_port = grouped = 0
    for i, line in enumerate(lines):
        match = re.match(r"# (Inputs|Outputs) of .+ - (\w+): ", line)
        if match:
            count = int(lines[i + 1])
            per_port += count
            grouped += count if match.group(2) in ("string", "binary", "clock") else min(count, 1)
    return per_port, grouped


def run(name: str, runs: int, stop_time: float) -> dict:
    """Time the loop of `doStep` only (the extraction and the instantiation of the container are not timed); the
    outputs are read at each communication point, for the digest."""
    from fmpy import extract, read_model_description
    from fmpy.simulation import instantiate_fmu

    outputs, start_values = CASES[name]()
    with zipfile.ZipFile("bench.fmu") as fmu:
        Path("container.txt").write_bytes(fmu.read("resources/container.txt"))
    per_port, grouped = exchange_calls(Path("container.txt"))

    description = read_model_description("bench.fmu")
    vrs = {variable.name: variable.valueReference for variable in description.modelVariables}
    unzipdir = extract("bench.fmu")
    nb_steps = round(stop_time / COMMUNICATION_STEP)
    times, digest = [], None
    for _ in range(runs):
        logger = lambda *args: None     # noqa: E731, kept alive with the instance (fmpy keeps a pointer to it)
        fmu = instantiate_fmu(unzipdir, description, fmi_type="CoSimulation", logger=logger)
        for variable, value in start_values.items():
            fmu.setInt32([vrs[variable]], [value])
        fmu.enterInitializationMode(startTime=0)
        fmu.exitInitializationMode()
        output_vrs = [vrs[o] for o in outputs]
        values = []
        start = time.perf_counter()
        for i in range(nb_steps):
            fmu.doStep(i * COMMUNICATION_STEP, COMMUNICATION_STEP)
            values.extend(fmu.getFloat64(output_vrs))
        times.append(time.perf_counter() - start)
        fmu.terminate()
        fmu.freeInstance()
        digest = hashlib.sha256(repr(values).encode()).hexdigest()[:16]
    shutil.rmtree(unzipdir, ignore_errors=True)
    return {"case": name, "min": min(times), "mean": statistics.mean(times), "per_port": per_port,
            "grouped": grouped, "digest": digest}


def main():
    parser = argparse.ArgumentParser(description="Benchmark of the container runtime.")
    parser.add_argument("cases", nargs="*", help="cases to run (default: all)")
    parser.add_argument("--list", action="store_true", help="list the cases and exit")
    parser.add_argument("--runs", type=int, default=5, help="simulations per case (default: 5)")
    parser.add_argument("--stop-time", type=float, help="stop time of every case (default: one per case, for "
                                                         "about 1 s of computation)")
    args = parser.parse_args()
    if args.list:
        print("\n".join(CASES))
        return
    # The cases leave ports unconnected, and the runtime is built for the host only (the binaries of the other
    # platforms are missing): the log of the build is off, a real build error raises anyway.
    logging.getLogger("fmu_manipulation_toolbox").disabled = True
    names = args.cases or list(CASES)
    unknown = [name for name in names if name not in CASES]
    if unknown:
        parser.error(f"unknown case(s): {', '.join(unknown)}")

    print(f"{'case':<14} {'min (s)':>9} {'mean (s)':>9} {'calls/step':>11} {'grouped':>8}  digest")
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        shutil.copy(DATA / "compile" / "3.0" / "Feedthrough.fmu", work)
        shutil.copy(DATA / "containers" / "VanDerPol" / "VanDerPol.fmu", work)
        shutil.copy(DATA / "containers" / "mt" / "1.fmu", work)
        os.chdir(work)
        me_only("VanDerPol.fmu", "VanDerPolME.fmu")
        me_only("Feedthrough.fmu", "FeedthroughME.fmu")
        for name in names:
            row = run(name, args.runs, args.stop_time or STOP_TIMES[name])
            print(f"{row['case']:<14} {row['min']:>9.3f} {row['mean']:>9.3f} {row['per_port']:>11} "
                  f"{row['grouped']:>8}  {row['digest']}", flush=True)
            for path in work.iterdir():
                if path.name.startswith("bench"):
                    shutil.rmtree(path) if path.is_dir() else path.unlink()


if __name__ == "__main__":
    main()
