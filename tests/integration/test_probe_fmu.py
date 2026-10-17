"""Integration tests of the probe FMU of `tools/probe_fmu`, and of the container runtime seen through it.

The generated FMUs (sources only) are compiled for the host platform, then simulated with fmpy; the trace written
by the probe is checked: the FMI calls of the container scenarios (reference traces), the propagation of the links
during the initialization, and the internal steps of a container driven with a communication step that is not a
multiple of its own. Each test runs in its own temporary directory.
"""
import csv
import logging
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


def _slave_callbacks():
    """Callbacks with a logger for an FMU2Slave: fmpy 0.3.32 otherwise calls the freed logger of the last simulation
    given one (see tests/_helpers/simulation.py)."""
    from fmpy.fmi1 import calloc, free
    from fmpy.fmi2 import (fmi2CallbackAllocateMemoryTYPE, fmi2CallbackFreeMemoryTYPE, fmi2CallbackFunctions,
                           fmi2CallbackLoggerTYPE)

    callbacks = fmi2CallbackFunctions()
    callbacks.logger = fmi2CallbackLoggerTYPE(lambda *args: None)
    callbacks.allocateMemory = fmi2CallbackAllocateMemoryTYPE(calloc)
    callbacks.freeMemory = fmi2CallbackFreeMemoryTYPE(free)
    return callbacks


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
    callbacks = _slave_callbacks()      # kept alive until freeInstance
    fmu.instantiate(callbacks=callbacks)
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


# --------------------------------------------------------------------------- #
#                         Scenarios (FMU Containers)                           #
# --------------------------------------------------------------------------- #
def _run_container():
    spec = importlib.util.spec_from_file_location("run_container", PROBE_DIR / "scenarios" / "run_container.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scenario_descriptions_are_valid():
    from fmu_manipulation_toolbox.assembly import Assembly

    run_container = _run_container()
    assert run_container.scenarios() == ["S1", "S2", "S3", "S4a", "S4b", "S4c", "S4d", "S5j", "S5r", "S5s", "S6m",
                                         "S6s"]
    for scenario in run_container.scenarios():
        assembly = Assembly(PROBE_DIR / "scenarios" / f"{scenario}.json")
        assert assembly.root.name == f"{scenario}.fmu"


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
def test_scenario_s1_in_a_container(probe_dir):
    run_container = _run_container()
    probes = run_container.compile_probes(probe_dir / "probes")
    directory = run_container.run("S1", probe_dir, probes)

    for name in ("A.csv", "results.csv", "log.txt", "wall.txt"):
        assert (directory / name).exists(), name
    trace = _trace(directory / "A.csv")
    steps = [line for line in trace if line["function"] == "fmi2DoStep" and not line["name"]]
    assert len(steps) == 20
    assert all(float(line["h"]) == pytest.approx(0.01) for line in steps)
    assert _snapshot(trace, "after_initialization")["trace_file"] == "A.csv"


# --------------------------------------------------------------------------- #
#                 Reference traces and comparison of the traces                #
# --------------------------------------------------------------------------- #
REF_DIR = Path(__file__).parents[1] / "data" / "probe"
REF_SCENARIOS = ["S1", "S2", "S3", "S4a", "S4b", "S4c", "S4d", "S5j", "S5s", "S5r"]


def _without_wall(filename: Path) -> list[list[str]]:
    with open(filename, newline="") as file:
        return [row[:1] + row[2:] for row in csv.reader(file)]


@pytest.fixture(scope="module")
def compiled_probes(tmp_path_factory) -> Path:
    return _run_container().compile_probes(tmp_path_factory.mktemp("probes"))


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
@pytest.mark.parametrize("scenario", REF_SCENARIOS)
def test_container_traces(probe_dir, compiled_probes, scenario):
    """The FMI calls of the container runtime match tests/data/probe/REF-<scenario>-<instance>.csv.

    After an intended change, regenerate the REF files from the traces of
    `run_container.py -output DIRECTORY` (without their `wall` column).
    """
    directory = _run_container().run(scenario, probe_dir, compiled_probes)
    references = sorted(REF_DIR.glob(f"REF-{scenario}-*.csv"))
    assert references
    for reference in references:
        trace = directory / f"{reference.stem.rsplit('-', 1)[1]}.csv"
        _assert_same_trace(_without_wall(trace), _without_wall_ref(reference), f"{scenario}: {trace.name}")


def _same_field(a: str, b: str) -> bool:
    """Equal fields; numbers within a relative 1e-9: the last digits of the times and steps depend on the compiler
    of the runtime (MSVC /fp:fast reassociates the computation of the internal steps)."""
    if a == b:
        return True
    try:
        x, y = float(a), float(b)
    except ValueError:
        return False
    return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))


def _assert_same_trace(rows: list[list[str]], references: list[list[str]], label: str):
    assert len(rows) == len(references), f"{label}: {len(rows)} lines instead of {len(references)}"
    for number, (row, reference) in enumerate(zip(rows, references), start=1):
        assert len(row) == len(reference) and all(_same_field(a, b) for a, b in zip(row, reference)), \
            f"{label}, line {number}: {row} instead of {reference}"


def _without_wall_ref(filename: Path) -> list[list[str]]:
    with open(filename, newline="") as file:
        return list(csv.reader(file))


def _compare_traces():
    spec = importlib.util.spec_from_file_location("compare_traces", PROBE_DIR.parent / "compare_traces.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compare_identical_traces(tmp_path):
    """Two identical runs give no difference (the REF traces of S5j stand for both importers)."""
    compare_traces = _compare_traces()
    for importer, scenario in (("container", "S5j"), ("simulink", "S5")):
        directory = tmp_path / scenario / importer
        directory.mkdir(parents=True)
        for reference in REF_DIR.glob("REF-S5j-*.csv"):
            rows = _without_wall_ref(reference)
            with open(directory / f"{reference.stem.rsplit('-', 1)[1]}.csv", "w", newline="") as file:
                csv.writer(file).writerows([rows[0][:1] + ["wall"] + rows[0][1:]] +
                                           [row[:1] + ["0"] + row[1:] for row in rows[1:]])
    report = compare_traces.report(tmp_path, ["S5j"])
    assert "### S5j (container) vs S5 (Simulink)" in report
    assert report.count("#### Instance") == 3
    assert "differences" not in report


def test_compare_differences(tmp_path):
    """S3 against S5j: differences of snapshots and inputs are reported, missing results too."""
    compare_traces = _compare_traces()
    for importer, scenario, source in (("container", "S3", "S3"), ("simulink", "S3", "S5j")):
        directory = tmp_path / scenario / importer
        directory.mkdir(parents=True)
        for reference in REF_DIR.glob(f"REF-{source}-*.csv"):
            rows = _without_wall_ref(reference)
            with open(directory / f"'{reference.stem.rsplit('-', 1)[1]}.csv'", "w", newline="") as file:
                csv.writer(file, lineterminator="\r\n").writerows(
                    [rows[0][:1] + ["wall"] + rows[0][1:]] + [row[:1] + ["0"] + row[1:] for row in rows[1:]])
    report = compare_traces.report(tmp_path, ["S3", "S1"])
    assert "Snapshot `after_initialization`: differences:" in report
    assert "| `y_init` | 5 | 1 |" in report
    assert "### S1 (container) vs S1 (Simulink)\n\nResults missing." in report


# --------------------------------------------------------------------------- #
#           Propagation of the links during the initialization                 #
# --------------------------------------------------------------------------- #
def _build_and_simulate(directory: Path, probes: Path, description: dict, fmi_version: int = 2,
                        stop_time: float = 0.02) -> list[str]:
    """Build `description` as a container in `directory` (current directory) and simulate it; the messages."""
    import json
    import shutil
    from fmu_manipulation_toolbox.assembly import Assembly

    for probe in probes.glob("*-host.fmu"):
        shutil.copy(probe, directory)
    json_file = directory / f"{Path(description['name']).stem}.json"
    json_file.write_text(json.dumps(description))
    Assembly(json_file).make_fmu(fmi_version=fmi_version)
    messages = []
    _simulate(directory / description["name"], stop_time=stop_time, output_interval=0.01, step_size=0.01,
              logger=lambda *args: messages.append(args[-1].decode()), debug_logging=True)
    return messages


def _y_init(trace: Path) -> str:
    return _snapshot(_trace(trace), "after_initialization")["y_init"]


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
def test_propagation_chain(probe_dir, compiled_probes):
    """S3: A.y_init -> B.u_cont, B.y_cont -> C.u_cont: B and C are initialized with the values of A and B."""
    directory = _run_container().run("S3", probe_dir, compiled_probes)
    assert [_y_init(directory / f"{i}.csv") for i in "ABC"] == ["5", "6", "7"]


S3_LINKS = [["A.fmu", "y_init", "B.fmu", "u_cont"], ["B.fmu", "y_cont", "C.fmu", "u_cont"]]
S3_STARTS = [["A.fmu", "trace_file", "A.csv"], ["B.fmu", "trace_file", "B.csv"], ["C.fmu", "trace_file", "C.csv"],
             ["A.fmu", "p_real", 3.0], ["A.fmu", "u_cont", 2.0], ["C.fmu", "p_real", 2.0]]
PATHS = {"A.fmu": "Probe10ms-host.fmu", "B.fmu": "Probe10ms-host.fmu", "C.fmu": "Probe10ms-host.fmu"}


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
@pytest.mark.fmi3
def test_propagation_fmi3_container(probe_dir, compiled_probes):
    _build_and_simulate(probe_dir, compiled_probes,
                        {"name": "chain3.fmu", "auto_link": False, "auto_input": False, "fmu": list(PATHS),
                         "path": PATHS, "link": S3_LINKS, "start": S3_STARTS}, fmi_version=3)
    assert [_y_init(probe_dir / f"{i}.csv") for i in "ABC"] == ["5", "6", "7"]


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
def test_propagation_nested_container(probe_dir, compiled_probes):
    """A in the container, B and C in a sub-container fed by A: each level propagates its links."""
    sub = {"name": "sub.fmu", "auto_link": False, "auto_input": False, "fmu": ["B.fmu", "C.fmu"],
           "path": {"B.fmu": "Probe10ms-host.fmu", "C.fmu": "Probe10ms-host.fmu"},
           "input": [["u", "B.fmu", "u_cont"]], "link": [S3_LINKS[1]],
           "start": [start for start in S3_STARTS if start[0] != "A.fmu"]}
    _build_and_simulate(probe_dir, compiled_probes,
                        {"name": "nested.fmu", "auto_link": False, "auto_input": False, "fmu": ["A.fmu"],
                         "path": {"A.fmu": "Probe10ms-host.fmu"}, "container": [sub],
                         "link": [["A.fmu", "y_init", "sub.fmu", "u"]],
                         "start": [start for start in S3_STARTS if start[0] == "A.fmu"]})
    assert [_y_init(probe_dir / f"{i}.csv") for i in "ABC"] == ["5", "6", "7"]


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
def test_propagation_loop(probe_dir, compiled_probes, caplog):
    """A.y_cont -> B.u_cont, B.y_cont -> A.u_cont: the loop is cut before A (first FMU of the configuration), with a
    warning; A is initialized with the value of the link before the propagation, B with the output of A."""
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        _build_and_simulate(probe_dir, compiled_probes,
                            {"name": "loop.fmu", "auto_link": False, "auto_input": False,
                             "fmu": ["A.fmu", "B.fmu"], "path": {"A.fmu": PATHS["A.fmu"], "B.fmu": PATHS["B.fmu"]},
                             "link": [["A.fmu", "y_cont", "B.fmu", "u_cont"], ["B.fmu", "y_cont", "A.fmu", "u_cont"]],
                             "start": [["A.fmu", "trace_file", "A.csv"], ["B.fmu", "trace_file", "B.csv"],
                                       ["A.fmu", "p_tunable", 0.5]]})
    assert "Loop of links through the embedded FMU 'A.fmu'" in caplog.text
    a = _snapshot(_trace(probe_dir / "A.csv"), "after_initialization")
    b = _snapshot(_trace(probe_dir / "B.csv"), "after_initialization")
    assert float(a["u_cont"]) == 0.0                         # value of the link before the propagation
    assert float(b["u_cont"]) == float(a["y_cont"]) == 0.5   # output of A after its initialization


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
def test_propagation_before_a_get_in_initialization_mode(probe_dir, compiled_probes):
    """An output of the container read by the importer in Initialization Mode is not propagated yet: the links are
    propagated when the container leaves its Initialization Mode."""
    import shutil
    from fmpy import extract, read_model_description
    from fmpy.fmi2 import FMU2Slave
    from fmu_manipulation_toolbox.assembly import Assembly
    import json

    for probe in compiled_probes.glob("*-host.fmu"):
        shutil.copy(probe, probe_dir)
    (probe_dir / "get.json").write_text(json.dumps(
        {"name": "get.fmu", "auto_link": False, "auto_input": False, "fmu": list(PATHS), "path": PATHS,
         "link": S3_LINKS, "input": [["a_u", "A.fmu", "u_cont"]], "output": [["C.fmu", "y_init", "c_init"]],
         "start": [start for start in S3_STARTS if start[1] != "u_cont"]}))
    Assembly(probe_dir / "get.json").make_fmu()
    description = read_model_description("get.fmu")
    vrs = {variable.name: variable.valueReference for variable in description.modelVariables}
    fmu = FMU2Slave(guid=description.guid, unzipDirectory=extract("get.fmu"),
                    modelIdentifier=description.coSimulation.modelIdentifier, instanceName="get")
    callbacks = _slave_callbacks()      # kept alive until freeInstance
    fmu.instantiate(callbacks=callbacks)
    fmu.setupExperiment(startTime=0)
    fmu.enterInitializationMode()
    fmu.setReal([vrs["a_u"]], [4.0])
    assert fmu.getReal([vrs["c_init"]]) == [2.0]          # not propagated yet: C.p_real + C.u_cont start value
    fmu.exitInitializationMode()
    assert fmu.getReal([vrs["c_init"]]) == [9.0]          # 2 + (1 + (3 + 4))
    fmu.terminate()
    fmu.freeInstance()


# --------------------------------------------------------------------------- #
#     Communication steps that are not a multiple of the container step        #
# --------------------------------------------------------------------------- #
@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
def test_one_sub_container_per_rate(probe_dir, compiled_probes):
    """S4c: each probe gets its own step size, and an input seen by a step is the value at its beginning."""
    directory = _run_container().run("S4c", probe_dir, compiled_probes)
    for name, step, nb in (("A", 0.01, 20), ("B", 0.02, 10), ("C", 0.05, 4)):
        steps = [line for line in _trace(directory / f"{name}.csv") if line["function"] == "fmi2DoStep" and not line["name"]]
        assert len(steps) == nb and all(float(line["h"]) == pytest.approx(step) for line in steps), name
    seen = {float(line["time"]): float(line["value"]) for line in _trace(directory / "B.csv")
            if line["function"] == "fmi2DoStep" and line["name"] == "u_cont"}
    assert all(value == pytest.approx(time) for time, value in seen.items())     # A.y_time at the start of the step


def _drive(probe_dir, compiled_probes, communication_step: float,
           stop_time: float) -> tuple[list[dict], list[tuple[float, float]]]:
    """A container of Probe20ms (internal step 0.02 s) driven with `communication_step`; its input `u` set to the
    current time before each call. The inputs seen by the steps of the probe, and the outputs after each call."""
    import json
    import shutil
    from fmpy import extract, read_model_description
    from fmpy.fmi2 import FMU2Slave
    from fmu_manipulation_toolbox.assembly import Assembly

    shutil.copy(compiled_probes / "Probe20ms-host.fmu", probe_dir)
    (probe_dir / "drive.json").write_text(json.dumps(
        {"name": "drive.fmu", "step_size": 0.02, "auto_link": False, "auto_input": False, "auto_output": False,
         "fmu": ["A.fmu"], "path": {"A.fmu": "Probe20ms-host.fmu"},
         "input": [["u", "A.fmu", "u_cont"]], "output": [["A.fmu", "y_time", "t"]],
         "start": [["A.fmu", "trace_file", "A.csv"]]}))
    Assembly(probe_dir / "drive.json").make_fmu()
    description = read_model_description("drive.fmu")
    vrs = {variable.name: variable.valueReference for variable in description.modelVariables}
    fmu = FMU2Slave(guid=description.guid, unzipDirectory=extract("drive.fmu"),
                    modelIdentifier=description.coSimulation.modelIdentifier, instanceName="drive")
    callbacks = _slave_callbacks()      # kept alive until freeInstance
    fmu.instantiate(callbacks=callbacks)
    fmu.setupExperiment(startTime=0)
    fmu.enterInitializationMode()
    fmu.exitInitializationMode()
    outputs = []
    time = 0.0
    for k in range(round(stop_time / communication_step)):
        time = k * communication_step
        fmu.setReal([vrs["u"]], [time])
        fmu.doStep(currentCommunicationPoint=time, communicationStepSize=communication_step)
        outputs.append((round(time + communication_step, 9), fmu.getReal([vrs["t"]])[0]))
    fmu.terminate()
    fmu.freeInstance()
    trace = _trace(probe_dir / "A.csv")
    return [{"time": float(line["time"]), "h": float(line["h"])} | {"u": float(line["value"])}
            for line in trace if line["function"] == "fmi2DoStep" and line["name"] == "u_cont"], outputs


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
def test_communication_step_smaller_than_the_container_step(probe_dir, compiled_probes):
    """h = 0.01 s, internal step 0.02 s: one internal step every two calls, with the input of its beginning; the
    output is held between the internal steps."""
    steps, outputs = _drive(probe_dir, compiled_probes, 0.01, 0.08)
    assert [(round(s["time"], 9), s["h"], s["u"]) for s in steps] == \
        [(0.0, 0.02, 0.0), (0.02, 0.02, 0.02), (0.04, 0.02, 0.04), (0.06, 0.02, 0.06)]
    assert [round(value, 9) for _, value in outputs] == [0.0, 0.02, 0.02, 0.04, 0.04, 0.06, 0.06, 0.08]


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.needs_container
def test_communication_step_not_a_multiple_of_the_container_step(probe_dir, compiled_probes):
    """h = 0.03 s, internal step 0.02 s: each internal step uses the last value set before its beginning."""
    steps, outputs = _drive(probe_dir, compiled_probes, 0.03, 0.12)
    assert [(round(s["time"], 9), s["u"]) for s in steps] == \
        [(0.0, 0.0), (0.02, 0.0), (0.04, 0.03), (0.06, 0.06), (0.08, 0.06), (0.1, 0.09)]
    assert [round(value, 9) for _, value in outputs] == [0.02, 0.06, 0.08, 0.12]
