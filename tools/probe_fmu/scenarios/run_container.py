"""Run the scenarios of the importer comparison study as FMU Containers (docs/local/importer_comparison.md).

For each scenario `<S>` (a `<S>.json` description of this directory), the script works in
`<output>/<S>/container/`: it copies the description and the probes compiled for the host, builds the container,
simulates it with fmpy from that directory and leaves there:

- `A.csv`, `B.csv`, `C.csv`: the traces of the probes;
- `results.csv`: the outputs of the container;
- `log.txt`: the messages of the container and of the probes;
- `wall.txt`: the wall time of the simulation (s).

Usage: python run_container.py -output DIRECTORY [SCENARIO ...]   (default: every scenario)
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PROBE_DIR = HERE.parent

#: Stop time of the simulations (s).
STOP_TIMES = {"S6s": 1.0, "S6m": 1.0}
DEFAULT_STOP_TIME = 0.2


def scenarios() -> list[str]:
    return sorted(path.stem for path in HERE.glob("S*.json"))


def compile_probes(directory: Path) -> Path:
    """Compile the probes for the host into `directory` (once)."""
    from fmu_manipulation_toolbox.compiler import OperationCompileSources
    from fmu_manipulation_toolbox.operations import FMU

    directory.mkdir(parents=True, exist_ok=True)
    for source in sorted(PROBE_DIR.glob("Probe*.fmu")):
        target = directory / f"{source.stem}-host.fmu"
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            with FMU(source) as fmu:
                fmu.apply_operation(OperationCompileSources())
                fmu.repack(target)
    return directory


def run(scenario: str, output: Path, probes: Path) -> Path:
    from fmpy import read_model_description
    from fmpy.simulation import simulate_fmu
    import numpy as np

    from fmu_manipulation_toolbox.assembly import Assembly

    directory = output / scenario / "container"
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    description = HERE / f"{scenario}.json"
    shutil.copy(description, directory)
    for probe in json.loads(description.read_text())["path"].values():
        shutil.copy(probes / probe, directory)

    cwd = Path.cwd()
    os.chdir(directory)       # the probes write their traces in the current directory
    try:
        assembly = Assembly(f"{scenario}.json")
        assembly.make_fmu()
        container = f"{scenario}.fmu"
        step_size = read_model_description(container).defaultExperiment.stepSize
        step_size = float(step_size)

        with open("log.txt", "w") as log_file:
            def logger(*args):
                print(args[-1].decode("utf-8", errors="replace"), file=log_file)

            start = time.perf_counter()
            result = simulate_fmu(container, start_time=0.0, stop_time=STOP_TIMES.get(scenario, DEFAULT_STOP_TIME),
                                  step_size=step_size, output_interval=step_size, logger=logger)
            wall = time.perf_counter() - start

        np.savetxt("results.csv", result, delimiter=",", fmt="%.17g", header=",".join(result.dtype.names),
                   comments="")
        Path("wall.txt").write_text(f"{wall:.6f}\n")
    finally:
        os.chdir(cwd)
    return directory


def main():
    parser = argparse.ArgumentParser(description="Run the comparison scenarios as FMU Containers.")
    parser.add_argument("-output", type=Path, required=True, metavar="DIRECTORY",
                        help="Directory of the results (one sub-directory per scenario).")
    parser.add_argument("scenarios", nargs="*", metavar="SCENARIO", help=f"Among {', '.join(scenarios())}.")
    args = parser.parse_args()

    selected = args.scenarios or scenarios()
    unknown = sorted(set(selected) - set(scenarios()))
    if unknown:
        sys.exit(f"Unknown scenario(s): {', '.join(unknown)}")

    output = args.output.resolve()
    probes = compile_probes(output / "probes")
    for scenario in selected:
        print(f"{scenario}: {run(scenario, output, probes)}")


if __name__ == "__main__":
    main()
