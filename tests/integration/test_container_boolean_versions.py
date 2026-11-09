"""Outputs of embedded FMUs that are booleans of the other FMI version (FMI-2.0 `Boolean`, an `int`, in an FMI-3.0
container; FMI-3.0 `Boolean`, a `bool`, in an FMI-2.0 container): exposed through a converted local variable.

`Feedthrough.fmu` of `tests/data/compile`, compiled for the host platform, feeds `Boolean_input` through to
`Boolean_output`: its start value `true` (start values have the type of the embedded port) must come out of the
container. Each test runs in its own directory.
"""
import re

import pytest

from _helpers.archive import read_entry
from _helpers.ls_ref import compiled_fmu
from fmu_manipulation_toolbox.container import FMUContainer

pytestmark = [pytest.mark.integration, pytest.mark.needs_compiler]

CASES = [pytest.param("2.0", 3, "B_B1", marks=pytest.mark.fmi2, id="fmi2-in-fmi3"),
         pytest.param("3.0", 2, "B1_B", marks=pytest.mark.fmi3, id="fmi3-in-fmi2")]


def _container(tmp_path, version: str, fmi_version: int, linked: bool = False) -> FMUContainer:
    compiled_fmu(version, "Feedthrough", tmp_path / "Feedthrough.fmu")
    container = FMUContainer("booleans", tmp_path, fmi_version=fmi_version)
    container.get_fmu("Feedthrough.fmu")
    container.add_start_value("Feedthrough.fmu", "Boolean_input", "true")
    container.add_output("Feedthrough.fmu", "Boolean_output", "flag")
    if linked:      # the port also feeds another instance: the local variable of its link is shared
        container.get_fmu("Feedthrough.fmu", name="Feedthrough-2.fmu")
        container.add_link("Feedthrough.fmu", "Boolean_output", "Feedthrough-2.fmu", "Boolean_input")
        container.add_output("Feedthrough-2.fmu", "Boolean_output", "flag2")
    return container


@pytest.mark.parametrize("version, fmi_version, conversion", CASES)
def test_boolean_output_is_exposed(tmp_path, version, fmi_version, conversion, caplog):
    container = _container(tmp_path, version, fmi_version)
    container.make_fmu(tmp_path / "booleans.fmu", step_size=0.1)
    assert "Cannot expose" not in caplog.text

    description = read_entry(tmp_path / "booleans.fmu", "modelDescription.xml").decode()
    if fmi_version == 3:
        assert re.search(r'<Boolean name="flag" valueReference="(\d+)" causality="output"', description)
    else:
        assert re.search(r'<ScalarVariable name="flag" valueReference="\d+" causality="output"[^>]*>\s*<Boolean',
                         description)
    txt = read_entry(tmp_path / "booleans.fmu", "resources/container.txt").decode()
    assert re.search(rf"^\d+ \d+ {conversion}$", txt, re.MULTILINE)


@pytest.mark.needs_fmpy
@pytest.mark.parametrize("linked", [False, True], ids=["alone", "linked"])
@pytest.mark.parametrize("version, fmi_version, conversion", CASES)
def test_boolean_output_value(tmp_path, version, fmi_version, conversion, linked):
    from _helpers.simulation import simulate

    container = _container(tmp_path, version, fmi_version, linked)
    container.make_fmu(tmp_path / "booleans.fmu", step_size=0.1)
    outputs = ["flag", "flag2"] if linked else ["flag"]
    result = simulate(tmp_path / "booleans.fmu", stop_time=0.3, output_interval=0.1, output=outputs)
    assert all(bool(value) for value in result["flag"])
    if linked:
        assert all(bool(value) for value in result["flag2"][1:])     # through the link: from the first step
