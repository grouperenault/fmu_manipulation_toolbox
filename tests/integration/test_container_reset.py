"""Integration tests for the reset of embedded FMUs (`docs/local/fmu_reset.md`).

The FMUs of `containers/mt` are built for every platform: these tests simulate on every OS.
"""
import json
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly

from _helpers.simulation import simulate

pytestmark = [pytest.mark.integration]


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
    """Low-level (fmpy) driver of a co-simulation container with a Float64 parameter `mu` and output `x0`."""

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

    def run(self, mu: float, nb_steps: int = 20, step_size: float = 0.01) -> list[float]:
        """Initialize at time 0 with `mu`, then return `x0` after each step."""
        if self.fmi_version == 2:
            self.fmu.setupExperiment(startTime=0)
            self.fmu.setReal([self.vrs["mu"]], [mu])
            self.fmu.enterInitializationMode()
        else:
            self.fmu.setFloat64([self.vrs["mu"]], [mu])
            self.fmu.enterInitializationMode(startTime=0)
        self.fmu.exitInitializationMode()

        get = self.fmu.getReal if self.fmi_version == 2 else self.fmu.getFloat64
        values = []
        for i in range(nb_steps):
            self.fmu.doStep(i * step_size, step_size)
            values.append(get([self.vrs["x0"]])[0])
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
