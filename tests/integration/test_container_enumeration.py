"""FMI-3 `Enumeration` ports in a container: FMI 3.0 accesses them as `Int64` (`fmi3GetInt64`/`fmi3SetInt64`)."""
import logging
import shutil
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.container import FMUContainer

from _helpers.archive import read_entry
from _helpers.simulation import simulate

pytestmark = [pytest.mark.integration, pytest.mark.area("containers/enumeration")]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def feedthrough(area_dir):
    shutil.copy(DATA_DIR / "compile" / "3.0" / "Feedthrough.fmu", "Feedthrough.fmu")
    return area_dir


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
def test_enumeration_through_a_link(feedthrough):
    """The value of an enumeration goes through a container input, a link between two instances, and an output."""
    container = FMUContainer("enumeration", ".", fmi_version=3)
    container.get_fmu("Feedthrough.fmu")
    container.get_fmu("Feedthrough.fmu", name="Feedthrough-1.fmu")
    container.add_input("option_in", "Feedthrough.fmu", "Enumeration_input")
    container.add_link("Feedthrough.fmu", "Enumeration_output", "Feedthrough-1.fmu", "Enumeration_input")
    container.add_output("Feedthrough-1.fmu", "Enumeration_output", "option_out")
    container.make_fmu("enumeration.fmu", step_size=0.001)

    description = read_entry("enumeration.fmu", "modelDescription.xml").decode("utf-8")
    assert '<Int64 name="option_in"' in description and '<Int64 name="option_out"' in description

    result = simulate("enumeration.fmu", stop_time=0.01, output_interval=0.001, start_values={"option_in": 2})
    assert (result["option_out"] == 2).all()


def test_enumeration_is_not_exposed_by_an_fmi2_container(feedthrough, caplog):
    """FMI 2.0 has no 64-bit integer: an FMI-3 enumeration cannot be a port of an FMI-2 container."""
    caplog.set_level(logging.DEBUG, logger="fmu_manipulation_toolbox")
    container = FMUContainer("enumeration2", ".", fmi_version=2)
    container.get_fmu("Feedthrough.fmu")
    container.add_output("Feedthrough.fmu", "Enumeration_output", "option_out")
    container.make_fmu("enumeration2.fmu", step_size=0.001)

    assert "Cannot expose (output) 'option_out' because type 'integer64' is not compatible with FMI-2.0" \
        in caplog.text
    assert 'name="option_out"' not in read_entry("enumeration2.fmu", "modelDescription.xml").decode("utf-8")
