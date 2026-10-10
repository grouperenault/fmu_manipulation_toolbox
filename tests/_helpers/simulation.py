"""Simulation helpers (require `fmpy` and `numpy`), extracted from the legacy
``test_suite.py``. Imports of fmpy/numpy are kept at call time friendly so that
pure-build assertions in a test do not pay the import cost unless a simulation
is actually requested.
"""
from pathlib import Path

import numpy as np
from fmpy.simulation import simulate_fmu

from _helpers.assertions import assert_identical_files


def assert_simulation(filename: Path | str, step_size: float | None = None):
    """Simulate `filename` and compare the results CSV against its REF-* file."""
    if isinstance(filename, str):
        filename = Path(filename)
    result_filename = filename.with_name("results-" + filename.with_suffix(".csv").name)
    ref_filename = result_filename.with_stem("REF-" + result_filename.stem)

    def fmu_log(*args):
        print(f"SIMU     | {args[-1].decode('utf-8')}")

    result = simulate_fmu(filename, step_size=step_size, stop_time=10,
                          output_interval=step_size, validate=True, logger=fmu_log,
                          debug_logging=False)

    np.savetxt(result_filename, result, delimiter=',', fmt="%.5e")
    assert_identical_files(result_filename, ref_filename)


def assert_simulation_log(filename: Path | str, step_size: float | None = None):
    """Simulate `filename` with debug logging and compare the log against REF.

    The first lines of an FMI debug log carry volatile build/instance metadata
    (GUID, timestamps, ...), so they are skipped. The remaining lines are
    compared one by one *including the line count*, so a truncated or overlong
    log is reported rather than silently accepted.
    """
    if isinstance(filename, str):
        filename = Path(filename)

    log_filename = filename.with_name("log-" + filename.with_suffix(".txt").name)
    with open(log_filename, "wt") as log_file:
        def fmu_log(*args):
            print(f"{args[-1].decode('utf-8')}", file=log_file)

        simulate_fmu(filename, step_size=step_size, stop_time=10, relative_tolerance=1e-9,
                     output_interval=step_size, validate=True, logger=fmu_log, debug_logging=True)

    ref_filename = log_filename.with_stem("REF-" + log_filename.stem)

    # Number of leading log lines carrying volatile metadata (not part of the
    # contract) that must be excluded from the comparison.
    header_lines = 11
    log_lines = Path(log_filename).read_text().splitlines()[header_lines:]
    ref_lines = Path(ref_filename).read_text().splitlines()[header_lines:]

    assert len(log_lines) == len(ref_lines), (
        f"files {log_filename} and {ref_filename} mismatch "
        f"(after the {header_lines}-line header): "
        f"{len(log_lines)} vs {len(ref_lines)} lines"
    )
    for offset, (actual, expected) in enumerate(zip(log_lines, ref_lines)):
        lineno = header_lines + offset + 1
        assert actual == expected, (
            f"files {log_filename} and {ref_filename} mismatch at line {lineno} "
            f"(excl. volatile header):\n"
            f"{actual}\n"
            f"vs.\n\n"
            f"{expected}"
        )

