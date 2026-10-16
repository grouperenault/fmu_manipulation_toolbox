"""Integration tests for the reset of embedded FMUs (`docs/local/fmu_reset.md`).

The FMUs used here (`containers/mt`, `containers/VanDerPol`, `ls-bus`, the sources of `compile`) are built, or
compiled, for every platform: these tests simulate on every OS.
"""
import csv
import json
import re
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.container import FMUContainer

from _helpers.archive import read_entry, rewrite_fmu
from _helpers.simulation import simulate

pytestmark = [pytest.mark.integration]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _simulate_with_debug_log(filename: str, **kwargs) -> list[str]:
    """Simulate `filename` with the debug logging on; return the logged messages."""
    messages = []

    def fmu_log(*args):
        messages.append(args[-1].decode("utf-8"))

    simulate(filename, logger=fmu_log, debug_logging=True, **kwargs)
    return messages


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("containers/mt")
@pytest.mark.parametrize("fmi_version", [2, 3])
def test_container_caches_values_set_by_the_importer(area_dir, fmi_version):
    """The values set by the importer on the ports forwarded to an embedded FMU (a parameter, and an input fanned
    out to two FMUs) are cached by the container; the local ports are not."""
    Path("cache.json").write_text(json.dumps({
        "name": "cache.fmu", "auto_link": False, "auto_input": False, "auto_output": False, "step_size": 0.01,
        "fmu": ["1.fmu", "1-1.fmu"], "path": {"1-1.fmu": "1.fmu"},
        "input": [["gain", "1.fmu", "p0"], ["u", "1.fmu", "u0"], ["u", "1-1.fmu", "u0"]],
        "output": [["1.fmu", "y0", "first"], ["1-1.fmu", "y0", "second"]],
    }))
    Assembly("cache.json").make_fmu(fmi_version=fmi_version)

    messages = _simulate_with_debug_log("cache.fmu", stop_time=0.1, start_values={"gain": 2.5, "u": 1.25})

    cached = [message for message in messages if message.startswith("[DEBUG] Cache ")]
    assert any(message.endswith("= 2.5 (1 value(s))") for message in cached), cached
    assert any(message.endswith("= 1.25 (1 value(s))") for message in cached), cached


class _Container:
    """Low-level (fmpy) driver of a co-simulation container of `VanDerPol.fmu`, with an output `x0`."""

    def __init__(self, filename: str):
        from fmpy import extract, read_model_description
        from fmpy.simulation import instantiate_fmu

        model_description = read_model_description(filename)
        self.fmi_version = int(model_description.fmiVersion[0])
        self.vrs = {variable.name: variable.valueReference for variable in model_description.modelVariables}
        # Always with a logger, kept alive with the instance: see `_helpers.simulation.simulate`.
        self.messages = []
        self._logger = lambda *args: self.messages.append(args[-1].decode("utf-8"))
        self.fmu = instantiate_fmu(extract(filename), model_description, fmi_type="CoSimulation",
                                   logger=self._logger)

    def initialize(self, **reals: float):
        """Initialize at time 0, with the given values of Float64 inputs or parameters."""
        set_reals = self.fmu.setReal if self.fmi_version == 2 else self.fmu.setFloat64
        if self.fmi_version == 2:
            self.fmu.setupExperiment(startTime=0)
        if reals:
            set_reals([self.vrs[name] for name in reals], list(reals.values()))
        if self.fmi_version == 2:
            self.fmu.enterInitializationMode()
        else:
            self.fmu.enterInitializationMode(startTime=0)
        self.fmu.exitInitializationMode()

    def x0(self) -> float:
        get = self.fmu.getReal if self.fmi_version == 2 else self.fmu.getFloat64
        return get([self.vrs["x0"]])[0]

    def run(self, mu: float, nb_steps: int = 20, step_size: float = 0.01) -> list[float]:
        """Initialize at time 0 with the parameter `mu`, then return `x0` after each step."""
        self.initialize(mu=mu)
        values = []
        for i in range(nb_steps):
            self.fmu.doStep(i * step_size, step_size)
            values.append(self.x0())
        return values

    def free(self):
        self.fmu.terminate()
        self.fmu.freeInstance()


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("containers/VanDerPol")
@pytest.mark.parametrize("fmi_version", [2, 3])
def test_container_reset(area_dir, fmi_version):
    """fmi2Reset / fmi3Reset of a container: the simulation starts again from the initial state, with the parameter
    set after the reset."""
    Path("reset.json").write_text(json.dumps({
        "name": "reset.fmu", "auto_link": False, "auto_input": False, "auto_output": False, "step_size": 0.01,
        "fmu": ["VanDerPol.fmu"],
        "input": [["mu", "VanDerPol.fmu", "mu"]],
        "output": [["VanDerPol.fmu", "x0", "x0"]],
    }))
    Assembly("reset.json").make_fmu(fmi_version=fmi_version)

    container = _Container("reset.fmu")
    first = container.run(mu=2.5)
    container.fmu.reset()
    again = container.run(mu=2.5)
    container.fmu.reset()
    other = container.run(mu=0.5)
    container.free()

    fresh = _Container("reset.fmu")
    expected_other = fresh.run(mu=0.5)
    fresh.free()

    assert first[0] != first[-1]        # the state evolves
    assert again == first
    assert other == expected_other
    assert other != first


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("containers/VanDerPol")
@pytest.mark.parametrize("fmi_version", [2, 3])
def test_reset_of_an_embedded_fmu_by_the_importer(area_dir, fmi_version):
    """The importer sets the exposed `container.vanderpol.reset`: the FMU starts again from its initial state at the
    next step, and the input is back to false after it."""
    container = FMUContainer("reset", ".", fmi_version=fmi_version, reset_ports=True)
    container.get_fmu("VanDerPol.fmu")
    container.add_output("VanDerPol.fmu", "x0", "x0")
    container.add_input("", "VanDerPol.fmu", "container.reset")
    container.make_fmu("reset.fmu", step_size=0.01)

    driver = _Container("reset.fmu")
    driver.initialize()
    reset_vr = driver.vrs["container.vanderpol.reset"]
    values, triggers = [], []
    for i in range(8):
        if i == 4:
            driver.fmu.setBoolean([reset_vr], [True])
        driver.fmu.doStep(i * 0.01, 0.01)
        values.append(driver.x0())
        triggers.append(bool(driver.fmu.getBoolean([reset_vr])[0]))
    driver.free()

    assert values[4:] == values[:4]
    assert values[3] != values[0]
    assert not any(triggers)


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("containers/VanDerPol")
@pytest.mark.parametrize("fmi_version", [2, 3])
def test_reset_of_an_embedded_fmu_by_a_link(area_dir, fmi_version):
    """`x0` of a second instance (never 0, so true once converted) drives the reset of the first one: the trigger
    is cleared at the end of each step where it reset the FMU, and the source sets it again at the end of the next
    one, so the FMU is reset every other step."""
    container = FMUContainer("reset", ".", fmi_version=fmi_version, reset_ports=True)
    container.get_fmu("VanDerPol.fmu")
    container.get_fmu("VanDerPol.fmu", name="VanDerPol-1.fmu")
    container.add_output("VanDerPol.fmu", "x0", "x0")
    container.add_link("VanDerPol-1.fmu", "x0", "VanDerPol.fmu", "container.reset")
    container.make_fmu("reset.fmu", step_size=0.01)

    driver = _Container("reset.fmu")
    driver.initialize()
    values = []
    for i in range(8):
        driver.fmu.doStep(i * 0.01, 0.01)
        values.append(driver.x0())
    driver.free()

    assert values[0] != values[1]
    assert values == values[:2] * 4


def _reset_once(driver: _Container, trigger: str, outputs: tuple[str, ...] = ("x0",), at: int = 4,
                nb_steps: int = 8, step_size: float = 0.01) -> dict[str, list[float]]:
    """Initialize, then step: the importer sets `trigger` before the step `at`. Return the outputs after each
    step."""
    get = driver.fmu.getReal if driver.fmi_version == 2 else driver.fmu.getFloat64
    driver.initialize()
    values = {name: [] for name in outputs}
    for i in range(nb_steps):
        if i == at:
            driver.fmu.setBoolean([driver.vrs[trigger]], [True])
        driver.fmu.doStep(i * step_size, step_size)
        for name in outputs:
            values[name].append(get([driver.vrs[name]])[0])
    return values


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("containers/VanDerPol")
@pytest.mark.parametrize("fmi_version", [2, 3])
@pytest.mark.parametrize("mode", ["parallel", "sequential", "mt"])
def test_reset_in_every_execution_mode(area_dir, fmi_version, mode):
    """Same behaviour in every execution mode: only the FMU of the trigger starts again."""
    container = FMUContainer("reset", ".", fmi_version=fmi_version, reset_ports=True)
    container.get_fmu("VanDerPol.fmu")
    container.get_fmu("VanDerPol.fmu", name="VanDerPol-1.fmu")
    container.add_output("VanDerPol.fmu", "x0", "x0")
    container.add_output("VanDerPol-1.fmu", "x0", "other")
    container.add_input("", "VanDerPol.fmu", "container.reset")
    container.make_fmu("reset.fmu", step_size=0.01, mt=mode == "mt", sequential=mode == "sequential")

    driver = _Container("reset.fmu")
    values = _reset_once(driver, "container.vanderpol.reset", outputs=("x0", "other"))
    driver.free()

    assert values["x0"][4:] == values["x0"][:4]
    assert values["other"][4:] != values["other"][:4]


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("containers/VanDerPol")
@pytest.mark.parametrize("fmi_version", [2, 3])
def test_reset_of_a_model_exchange_fmu(area_dir, fmi_version):
    """A Model-Exchange FMU (VanDerPol without its Co-Simulation interface) starts again from its initial state:
    the solver reads its states again."""
    description = read_entry("VanDerPol.fmu", "modelDescription.xml").decode("utf-8")
    description = re.sub(r"<CoSimulation\b.*?/>", "", description, flags=re.DOTALL)
    rewrite_fmu("VanDerPol.fmu", "VanDerPolME.fmu", replace={"modelDescription.xml": description.encode("utf-8")})

    container = FMUContainer("reset", ".", fmi_version=fmi_version, reset_ports=True)
    assert container.get_fmu("VanDerPolME.fmu").is_me
    container.add_output("VanDerPolME.fmu", "x0", "x0")
    container.add_input("", "VanDerPolME.fmu", "container.reset")
    container.make_fmu("reset.fmu", step_size=0.01)

    driver = _Container("reset.fmu")
    values = _reset_once(driver, "container.vanderpolme.reset")
    driver.free()

    assert values["x0"][3] != values["x0"][0]
    assert values["x0"][4:] == values["x0"][:4]


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("containers/VanDerPol")
@pytest.mark.parametrize("fmi_version", [2, 3])
def test_reset_of_a_sub_container(area_dir, fmi_version):
    """The reset port of a sub-container calls its fmi2Reset / fmi3Reset."""
    Path("outer.json").write_text(json.dumps({
        "name": "outer.fmu", "auto_link": False, "auto_input": True, "auto_output": True, "reset_ports": True,
        "step_size": 0.01,
        "container": [{"name": "inner.fmu", "auto_link": False, "auto_input": False, "auto_output": True,
                       "fmu": ["VanDerPol.fmu"]}],
    }))
    Assembly("outer.json").make_fmu(fmi_version=fmi_version)

    driver = _Container("outer.fmu")
    values = _reset_once(driver, "container.inner.reset")
    driver.free()

    assert values["x0"][3] != values["x0"][0]
    assert values["x0"][4:] == values["x0"][:4]


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("ls-bus")
def test_reset_refused_for_an_fmu_with_scheduled_clocks(area_dir):
    """The bus of an LS-BUS container has clocks scheduled by the container: its reset is refused (D21)."""
    assembly = json.loads(Path("bus+nodes.json").read_text())
    assembly.update({"name": "resettable.fmu", "reset_ports": True,
                     "input": [["container.bus.reset", "bus.fmu", "container.reset"]]})
    Path("resettable.json").write_text(json.dumps(assembly))
    Assembly("resettable.json").make_fmu(fmi_version=3)

    from fmpy.fmi1 import FMICallException

    driver = _Container("resettable.fmu")
    driver.initialize()
    driver.fmu.doStep(0.0, 0.1)
    driver.fmu.setBoolean([driver.vrs["container.bus.reset"]], [True])
    with pytest.raises(FMICallException):
        driver.fmu.doStep(0.1, 0.1)
    driver.fmu.freeInstance()

    assert any("reset of an FMU with scheduled clocks is not supported" in message for message in driver.messages)


def _bouncing_ball_without_reset(fmi_version: int, filename: str):
    """`BouncingBall` of `tests/data/compile`, compiled for the host with a `fmiXReset` that always fails."""
    from fmu_manipulation_toolbox.compiler import OperationCompileSources
    from fmu_manipulation_toolbox.operations import FMU

    reference = DATA_DIR / "compile" / f"{fmi_version}.0" / "BouncingBall.fmu"
    source_name = f"sources/fmi{fmi_version}Functions.c"
    source = read_entry(reference, source_name).decode("utf-8")
    source, count = re.subn(rf"(fmi{fmi_version}Status fmi{fmi_version}Reset\(\w+ \w+\) {{).*?\n}}",
                            rf"\1\n    return fmi{fmi_version}Error;\n}}", source, flags=re.DOTALL)
    assert count == 1
    rewrite_fmu(reference, "no-binaries.fmu", drop=("binaries/",), replace={source_name: source.encode("utf-8")})
    with FMU("no-binaries.fmu") as fmu:
        fmu.apply_operation(OperationCompileSources())
        fmu.repack(filename)


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.needs_compiler
@pytest.mark.area("containers/VanDerPol")
@pytest.mark.parametrize("fmi_version", [2, 3])
def test_failing_reset(area_dir, fmi_version):
    """An FMU that refuses fmiXReset: the step that resets it fails, as fmi2Reset / fmi3Reset of the container."""
    _bouncing_ball_without_reset(fmi_version, "BouncingBall.fmu")
    container = FMUContainer("noreset", ".", fmi_version=fmi_version, reset_ports=True)
    container.get_fmu("BouncingBall.fmu")
    container.add_output("BouncingBall.fmu", "h", "h")
    container.add_input("", "BouncingBall.fmu", "container.reset")
    container.make_fmu("noreset.fmu", step_size=0.01)

    from fmpy.fmi1 import FMICallException

    driver = _Container("noreset.fmu")
    driver.initialize()
    driver.fmu.doStep(0.0, 0.01)
    driver.fmu.setBoolean([driver.vrs["container.bouncingball.reset"]], [True])
    with pytest.raises(FMICallException):
        driver.fmu.doStep(0.01, 0.01)
    driver.fmu.freeInstance()
    assert any("'BouncingBall.fmu' cannot be reset" in message for message in driver.messages)

    driver = _Container("noreset.fmu")
    driver.initialize()
    with pytest.raises(FMICallException):
        driver.fmu.reset()
    driver.fmu.freeInstance()
    assert any("'BouncingBall.fmu' failed to reset" in message for message in driver.messages)


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("containers/VanDerPol")
@pytest.mark.parametrize("source", ["importer", "link"])
def test_reset_in_the_datalog(area_dir, source):
    """A row is written just before the reset, at the same time as the row of the previous step (D13). Set by the
    importer, the trigger is `true` in this row only; fed by a link, the datalog shows the link variable (the
    source value, before its conversion to the Boolean of the trigger)."""
    container = FMUContainer("logged", ".", fmi_version=3, reset_ports=True)
    container.get_fmu("VanDerPol.fmu")
    container.add_output("VanDerPol.fmu", "x0", "x0")
    if source == "importer":
        container.add_input("", "VanDerPol.fmu", "container.reset")
        trigger = "container.vanderpol.reset"
    else:
        container.get_fmu("VanDerPol.fmu", name="VanDerPol-1.fmu")
        container.add_link("VanDerPol-1.fmu", "x0", "VanDerPol.fmu", "container.reset")
        trigger = "vanderpol-1.x0"
    container.make_fmu("logged.fmu", step_size=0.01, datalog=True)

    driver = _Container("logged.fmu")
    if source == "importer":
        _reset_once(driver, trigger)
    else:
        driver.initialize()
        for i in range(4):
            driver.fmu.doStep(i * 0.01, 0.01)
    driver.free()

    with open("logged-datalog.csv", newline="") as file:
        rows = list(csv.DictReader(file))
    times = [float(row["time"]) for row in rows]
    repeated = [i for i in range(1, len(rows)) if times[i] == times[i - 1]]   # rows written before a reset

    if source == "importer":
        assert [times[i] for i in repeated] == [pytest.approx(0.04)]
        assert [row[trigger] for row in rows].count("1") == 1
        assert rows[repeated[0]][trigger] == "1" and rows[repeated[0] + 1][trigger] == "0"
        assert rows[repeated[0] + 1]["x0"] == rows[1]["x0"]     # started again
    else:
        assert [times[i] for i in repeated] == [pytest.approx(0.0), pytest.approx(0.02)]   # every other step
        assert all(float(rows[i][trigger]) != 0 for i in repeated)
