"""Integration tests of the probe FMU of `tools/probe_fmu` (see `docs/local/importer_comparison.md`).

The generated FMUs (sources only) are compiled for the host platform, then simulated with fmpy; the trace written
by the probe is checked. Each test runs in its own temporary directory.
"""
import csv
import importlib.util
import time
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.compiler import OperationCompileSources
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [pytest.mark.integration, pytest.mark.fmi2]

PROBE_DIR = Path(__file__).parents[2] / "tools" / "probe_fmu"
PROBES = {"Probe10ms": 0.01, "Probe20ms": 0.02, "Probe50ms": 0.05}


def _make_probe():
    spec = importlib.util.spec_from_file_location("make_probe", PROBE_DIR / "make_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def probe_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _compile(name: str) -> str:
    filename = f"{name}-host.fmu"
    with FMU(PROBE_DIR / f"{name}.fmu") as fmu:
        fmu.apply_operation(OperationCompileSources())
        fmu.repack(filename)
    return filename


def _simulate(filename: str, **kwargs):
    from _helpers.simulation import simulate
    return simulate(filename, **kwargs)


def _trace(filename: str) -> list[dict]:
    with open(filename, newline="") as file:
        return list(csv.DictReader(file))


def _snapshot(trace: list[dict], label: str) -> dict[str, str]:
    return {line["name"]: line["value"] for line in trace if line["function"] == "SNAPSHOT" and line["note"] == label}


# --------------------------------------------------------------------------- #
#                               Generation                                     #
# --------------------------------------------------------------------------- #
def test_generated_fmus_are_up_to_date(probe_dir):
    """The committed FMUs are those `make_probe.py` generates from the current sources."""
    make_probe = _make_probe()
    for name, step_size in PROBES.items():
        generated = make_probe.make_fmu(name, step_size, probe_dir)
        with zipfile.ZipFile(generated) as expected, zipfile.ZipFile(PROBE_DIR / f"{name}.fmu") as committed:
            assert sorted(committed.namelist()) == sorted(expected.namelist()), name
            for entry in expected.namelist():
                assert committed.read(entry) == expected.read(entry), f"{name}: {entry} (run make_probe.py)"


def test_generated_fmus_have_sources_only():
    for name in PROBES:
        with zipfile.ZipFile(PROBE_DIR / f"{name}.fmu") as archive:
            assert sorted(archive.namelist()) == ["modelDescription.xml", "sources/probe.c",
                                                  "sources/probe_config.h"]


def test_step_sizes_and_guids():
    from fmu_manipulation_toolbox.model_description import ModelDescription

    make_probe = _make_probe()
    for name, step_size in PROBES.items():
        with zipfile.ZipFile(PROBE_DIR / f"{name}.fmu") as archive:
            xml = archive.read("modelDescription.xml")
            config = archive.read("sources/probe_config.h").decode()
        description = ModelDescription.load(xml)
        assert f'stepSize="{step_size}"' in xml.decode()
        assert f'#define PROBE_STEP_SIZE {step_size!r}' in config
        assert f'#define PROBE_GUID "{make_probe.guid(name)}"' in config
        assert description is not None


# --------------------------------------------------------------------------- #
#                               Simulation                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
def test_trace_of_a_simulation(probe_dir):
    filename = _compile("Probe10ms")
    result = _simulate(filename, stop_time=0.05, output_interval=0.01, validate=True,
                       start_values={"p_real": 3.0, "u_cont": 2.0, "u_disc": 4.0, "u_int": 1, "u_bool": True})

    assert result["y_init"][-1] == 5.0                        # p_real + u_cont, frozen
    assert result["y_cont"][-1] == 2.0
    assert result["y_disc"][-1] == 4.0
    assert result["y_int"][-1] == 5 + 1000
    assert bool(result["y_bool"][-1])

    trace = _trace("Probe10ms.csv")
    functions = [line["function"] for line in trace]
    for function in ("fmi2Instantiate", "fmi2SetupExperiment", "fmi2EnterInitializationMode",
                     "fmi2ExitInitializationMode", "fmi2DoStep", "fmi2Terminate", "fmi2FreeInstance"):
        assert function in functions, function
    assert functions.index("fmi2SetupExperiment") < functions.index("fmi2EnterInitializationMode") \
        < functions.index("fmi2ExitInitializationMode") < functions.index("fmi2DoStep")

    assert _snapshot(trace, "before_setup_experiment")["p_real"] == "1"
    before = _snapshot(trace, "before_initialization")
    assert before["p_real"] == "3" and before["u_cont"] == "2" and before["y_init"] == "5"
    assert _snapshot(trace, "after_initialization")["y_init"] == "5"

    steps = [line for line in trace if line["function"] == "fmi2DoStep" and not line["name"]]
    assert len(steps) == 5
    assert all(float(line["h"]) == pytest.approx(0.01) and line["note"] == "" for line in steps)
    inputs = [line for line in trace if line["function"] == "fmi2DoStep" and line["note"] == "input"]
    assert len(inputs) == 5 * 4

    sets = [line for line in trace if line["function"] == "fmi2SetReal"]
    assert {line["name"] for line in sets} >= {"p_real", "u_cont", "u_disc"}


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
def test_y_init_is_frozen_after_initialization(probe_dir):
    """`u_cont` changed after the initialization does not change `y_init`."""
    from fmpy import read_model_description, extract
    from fmpy.fmi2 import FMU2Slave

    filename = _compile("Probe10ms")
    description = read_model_description(filename)
    vrs = {variable.name: variable.valueReference for variable in description.modelVariables}
    fmu = FMU2Slave(guid=description.guid, unzipDirectory=extract(filename),
                    modelIdentifier=description.coSimulation.modelIdentifier, instanceName="probe")
    fmu.instantiate()
    fmu.setupExperiment(startTime=0)
    fmu.enterInitializationMode()
    fmu.setReal([vrs["u_cont"]], [10.0])
    assert fmu.getReal([vrs["y_init"]]) == [11.0]
    fmu.exitInitializationMode()
    fmu.setReal([vrs["u_cont"]], [20.0])
    fmu.doStep(0.0, 0.01)
    assert fmu.getReal([vrs["y_init"], vrs["y_cont"]]) == [11.0, 20.0]
    fmu.terminate()
    fmu.freeInstance()

    assert _trace("probe.csv")[0]["function"] == "fmi2Instantiate"


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
def test_wrong_step_size(probe_dir):
    filename = _compile("Probe20ms")
    _simulate(filename, stop_time=0.04, step_size=0.01, output_interval=0.01,
              start_values={"trace_file": "loose.csv"})
    steps = [line for line in _trace("loose.csv") if line["function"] == "fmi2DoStep" and not line["name"]]
    assert len(steps) == 4
    assert all(line["status"] == "OK" and "h != step_size" in line["note"] for line in steps)

    from fmpy.fmi1 import FMICallException
    with pytest.raises(FMICallException):
        _simulate(filename, stop_time=0.04, step_size=0.01, output_interval=0.01,
                  start_values={"trace_file": "strict.csv", "strict_step": True})
    steps = [line for line in _trace("strict.csv") if line["function"] == "fmi2DoStep" and not line["name"]]
    assert steps[0]["status"] == "Error"


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.parametrize("sleep", [False, True])
def test_compute_time(probe_dir, sleep):
    filename = _compile("Probe20ms")
    start = time.perf_counter()
    _simulate(filename, stop_time=0.1, output_interval=0.02,
              start_values={"compute_time": 0.02, "compute_sleep": sleep})
    assert time.perf_counter() - start >= 5 * 0.02
