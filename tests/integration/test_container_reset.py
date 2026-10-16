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
