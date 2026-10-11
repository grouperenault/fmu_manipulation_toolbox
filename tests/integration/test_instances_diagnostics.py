"""TEMPORARY diagnostics: why the simulation of two instances of the Simulink bouncing-ball FMUs crashed on Windows.

`test_container.py::test_container_with_instances_of_one_fmu` crashed (access violation in `fmi2Instantiate` of the
container) when the simulation ran in the pytest process, after the other tests, without debug log; it passes when
the simulation runs in a subprocess with the debug log of the container. Each variant below changes one factor, in a
subprocess, so that a crash fails that variant only:

- `test_alone_in_a_pytest_process`: the former in-process simulation, without debug log, in a pytest process that
  runs nothing else (do the other tests matter?);
- `test_subprocess_without_debug_log`: the current subprocess simulation, without debug log (does the debug log
  matter?).

To be removed once the cause is known.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly

pytestmark = [pytest.mark.integration, pytest.mark.windows_only]

#: Same assembly as `test_container.py::TWO_BALLS`: two independent bouncing balls.
TWO_BALLS = {
    "name": "two_balls.fmu", "profiling": True, "auto_link": False, "auto_input": False, "auto_output": False,
    "fmu": ["bb_position.fmu", "bb_velocity.fmu", "bb_position-1.fmu", "bb_velocity-1.fmu"],
    "path": {"bb_position-1.fmu": "bb_position.fmu", "bb_velocity-1.fmu": "bb_velocity.fmu"},
    "link": [["bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset"],
             ["bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"],
             ["bb_position-1.fmu", "is_ground", "bb_velocity-1.fmu", "reset"],
             ["bb_velocity-1.fmu", "velocity", "bb_position-1.fmu", "velocity"]],
    "output": [["bb_position.fmu", "position1", "position"],
               ["bb_position-1.fmu", "position1", "position_2"]],
}

#: Directory of the `two_balls.fmu` built by `test_alone_in_a_pytest_process`, for the pytest process it launches.
IN_PROCESS = "FMUTOOL_DIAGNOSTICS_IN_PROCESS"


def _build_two_balls():
    Path("two_balls.json").write_text(json.dumps(TWO_BALLS))
    Assembly("two_balls.json").make_fmu()


def _report(completed: subprocess.CompletedProcess) -> str:
    log = (completed.stdout + completed.stderr).splitlines()
    return f"exit code {completed.returncode}, last lines:\n" + "\n".join(log[-40:])


@pytest.mark.skipif(not os.environ.get(IN_PROCESS), reason="only run by test_alone_in_a_pytest_process")
def test_in_process_simulation(monkeypatch):
    """The former simulation: in the pytest process, without debug log."""
    from fmpy import simulate_fmu

    monkeypatch.chdir(os.environ[IN_PROCESS])
    result = simulate_fmu("two_balls.fmu", stop_time=10, output=["position", "position_2"])
    assert list(result["position"]) == list(result["position_2"])


@pytest.mark.needs_fmpy
@pytest.mark.area("containers/bouncing_ball")
def test_alone_in_a_pytest_process(area_dir):
    """Variant 1: the former in-process simulation, alone in its pytest process. `--noconftest`: the session start
    of `conftest.py` would wipe `tests/tmp`, the working directories of this session."""
    _build_two_balls()
    tests_dir = Path(__file__).resolve().parent.parent
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest",
         "integration/test_instances_diagnostics.py::test_in_process_simulation"],
        cwd=tests_dir, env={**os.environ, IN_PROCESS: str(area_dir)}, capture_output=True, text=True)
    assert completed.returncode == 0, _report(completed)
    assert "1 passed" in completed.stdout, _report(completed)


SIMULATE_WITHOUT_DEBUG_LOG = """
from fmpy import simulate_fmu

result = simulate_fmu("two_balls.fmu", stop_time=10, output=["position", "position_2"])
print("SAME POSITIONS" if list(result["position"]) == list(result["position_2"]) else "DIFFERENT POSITIONS",
      flush=True)
"""


@pytest.mark.needs_fmpy
@pytest.mark.area("containers/bouncing_ball")
def test_subprocess_without_debug_log(area_dir):
    """Variant 2: the current subprocess simulation, without debug log."""
    _build_two_balls()
    completed = subprocess.run([sys.executable, "-c", SIMULATE_WITHOUT_DEBUG_LOG], capture_output=True, text=True)
    assert completed.returncode == 0, _report(completed)
    assert "SAME POSITIONS" in completed.stdout, _report(completed)
