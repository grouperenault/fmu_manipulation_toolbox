"""Benchmark of `FMU.apply_operation` on large synthetic descriptors.

Baseline for the switch of `Manipulation` to ElementTree (see
`docs/local/done/refactoring.md`, phases 0 and 2): building a full tree must stay within a
reasonable factor of the current SAX implementation, in time and in memory.

Not part of the test suite (it is not collected by pytest). Run it from the
repository root and paste its Markdown output into `docs/local/done/refactoring.md`:

    python tests/benchmarks/bench_manipulation.py [--variables 1000 10000 100000] [--repeat 3]
"""
import argparse
import logging
import platform
import sys
import tempfile
import time
import tracemalloc
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fmu_manipulation_toolbox.operations import FMU, OperationAbstract, OperationRemoveRegexp  # noqa: E402


def fmi2_descriptor(nb_variables: int) -> str:
    """Half inputs, half outputs; each output depends on the input of same rank."""
    half = nb_variables // 2
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<fmiModelDescription fmiVersion="2.0" modelName="bench" guid="{bench}">',
             '  <CoSimulation modelIdentifier="bench"/>',
             '  <ModelVariables>']
    for i in range(half):
        lines.append(f'    <ScalarVariable name="bus{i % 10}.in{i}" valueReference="{i}" causality="input" '
                     f'variability="continuous" description="input &amp; &lt;{i}&gt;"><Real start="0"/>'
                     f'</ScalarVariable>')
    for i in range(half):
        lines.append(f'    <ScalarVariable name="bus{i % 10}.out{i}" valueReference="{half + i}" causality="output" '
                     f'variability="continuous"><Real/></ScalarVariable>')
    lines += ['  </ModelVariables>', '  <ModelStructure>', '    <Outputs>']
    lines += [f'      <Unknown index="{half + i + 1}" dependencies="{i + 1}"/>' for i in range(half)]
    lines += ['    </Outputs>', '  </ModelStructure>', '</fmiModelDescription>']
    return "\n".join(lines)


def fmi3_descriptor(nb_variables: int) -> str:
    half = nb_variables // 2
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<fmiModelDescription fmiVersion="3.0" modelName="bench" instantiationToken="{bench}">',
             '  <CoSimulation modelIdentifier="bench"/>',
             '  <ModelVariables>']
    lines += [f'    <Float64 name="bus{i % 10}.in{i}" valueReference="{i}" causality="input" start="0" '
              f'description="input &amp; &lt;{i}&gt;"/>' for i in range(half)]
    lines += [f'    <Float64 name="bus{i % 10}.out{i}" valueReference="{half + i}" causality="output"/>'
              for i in range(half)]
    lines += ['  </ModelVariables>', '  <ModelStructure>']
    lines += [f'    <Output valueReference="{half + i}" dependencies="{i}"/>' for i in range(half)]
    lines += ['  </ModelStructure>', '</fmiModelDescription>']
    return "\n".join(lines)


class ElementTreeRoundTrip:
    """Not an operation: parses and rewrites the descriptor with ElementTree, to
    estimate the cost of a full tree before phase 2 exists."""

    def apply(self, fmu: FMU):
        ET.parse(fmu.descriptor_filename).write(fmu.descriptor_filename, encoding="UTF-8", xml_declaration=True)


OPERATIONS = {
    "noop": lambda: OperationAbstract(),
    "remove 10%": lambda: OperationRemoveRegexp("bus0"),
    "*ET parse+write (estimate)*": lambda: ElementTreeRoundTrip(),
}


def run(fmu: FMU, operation) -> None:
    if isinstance(operation, ElementTreeRoundTrip):
        operation.apply(fmu)
    else:
        fmu.apply_operation(operation)


def measure(fmu_filename: Path, operation_factory, repeat: int):
    """Best wall-clock time over `repeat` runs, then peak traced memory of one run."""
    best = float("inf")
    for _ in range(repeat):
        fmu = FMU(str(fmu_filename))
        start = time.perf_counter()
        run(fmu, operation_factory())
        best = min(best, time.perf_counter() - start)
        del fmu

    fmu = FMU(str(fmu_filename))
    tracemalloc.start()
    run(fmu, operation_factory())
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del fmu
    return best, peak


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variables", type=int, nargs="+", default=[1_000, 10_000, 100_000])
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    # "remove 10%" logs one warning per removed dependency.
    logging.getLogger("fmu_manipulation_toolbox").setLevel(logging.ERROR)

    print(f"Python {platform.python_version()} — {platform.platform()} — best of {args.repeat} runs\n")
    print("| FMI | Variables | Descriptor | Operation | Time | Peak memory (tracemalloc) |")
    print("|---|---:|---:|---|---:|---:|")
    with tempfile.TemporaryDirectory() as tmp:
        for fmi_version, generator in (("2.0", fmi2_descriptor), ("3.0", fmi3_descriptor)):
            for nb_variables in args.variables:
                descriptor = generator(nb_variables)
                fmu_filename = Path(tmp) / f"bench-{fmi_version}-{nb_variables}.fmu"
                with zipfile.ZipFile(fmu_filename, "w", zipfile.ZIP_DEFLATED) as fmu:
                    fmu.writestr("modelDescription.xml", descriptor)
                size_mb = len(descriptor.encode("utf-8")) / 1e6
                for name, factory in OPERATIONS.items():
                    elapsed, peak = measure(fmu_filename, factory, args.repeat)
                    print(f"| {fmi_version} | {nb_variables:,} | {size_mb:.1f} MB | {name} | "
                          f"{elapsed:.2f} s | {peak / 1e6:.1f} MB |")


if __name__ == "__main__":
    main()
