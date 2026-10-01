"""Simulation helpers (require `fmpy` and `numpy`), extracted from the legacy
``test_suite.py``. Imports of fmpy/numpy are kept at call time friendly so that
pure-build assertions in a test do not pay the import cost unless a simulation
is actually requested.
"""
from pathlib import Path
from typing import Optional, Union

import numpy as np
from fmpy.simulation import simulate_fmu

from _helpers.assertions import assert_identical_files


def assert_simulation(filename: Union[Path, str], step_size: Optional[float] = None):
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


def assert_simulation_log(filename: Union[Path, str], step_size: Optional[float] = None):
    """Simulate `filename` with debug logging and compare the log against REF."""
    if isinstance(filename, str):
        filename = Path(filename)

    log_filename = filename.with_name("log-" + filename.with_suffix(".txt").name)
    with open(log_filename, "wt") as log_file:
        def fmu_log(*args):
            print(f"{args[-1].decode('utf-8')}", file=log_file)

        simulate_fmu(filename, step_size=step_size, stop_time=10, relative_tolerance=1e-9,
                     output_interval=step_size, validate=True, logger=fmu_log, debug_logging=True)

    ref_filename = log_filename.with_stem("REF-" + log_filename.stem)

    with open(log_filename, mode="rt", newline=None) as a, open(ref_filename, mode="rt", newline=None) as b:
        for i, (lineA, lineB) in enumerate(zip(a, b)):
            if i > 10:
                assert lineA == lineB, \
                    f"files {log_filename} and {ref_filename} missmatch (excl. GUID):\n" \
                    f"{lineA}\n" \
                    f"vs.\n\n" \
                    f"{lineB}"

