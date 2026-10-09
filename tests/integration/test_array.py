"""Integration tests for array-port support (operation summary + containers).

Migrated from the legacy ``test_suite.py``. Runs in an isolated copy of
``tests/data/array``; FMI-2/FMI-3 array containers are built, validated with
`fmpy`, and (on Windows) simulated against their REF-* references.
"""
import sys

import pytest

from fmpy.validation import validate_fmu

from fmu_manipulation_toolbox.operations import FMU, OperationSummary
from fmu_manipulation_toolbox.assembly import Assembly

from _helpers.assertions import VOLATILE_XML_ATTRIBUTES, assert_equivalent_xml, assert_identical_files
from _helpers.simulation import assert_simulation

pytestmark = [pytest.mark.integration, pytest.mark.area("array")]

WIN = sys.platform == "win32"


def test_array_operation(area_dir):
    fmu = FMU("StateSpace.fmu")
    fmu.apply_operation(OperationSummary())
    fmu.save_descriptor("modelDescription.xml")
    fmu.repack("StateSpace-copy.fmu")
    validate_fmu("StateSpace-copy.fmu")
    assert_equivalent_xml("REF-modelDescription.xml", "modelDescription.xml")


@pytest.mark.fmi3
def test_array3_container(area_dir):
    assembly = Assembly("array-3.json", debug=True)
    assembly.make_fmu(fmi_version=3)
    validate_fmu("array-3.fmu")
    assert_equivalent_xml("REF-container-modelDescription-3.xml", "array-3/modelDescription.xml",
                          ignore_attributes=VOLATILE_XML_ATTRIBUTES)
    if WIN:
        assert_simulation("array-3.fmu", 0.1)


@pytest.mark.fmi2
def test_array2_container(area_dir):
    assembly = Assembly("array-2.json", debug=True)
    assembly.make_fmu(fmi_version=2)
    validate_fmu("array-2.fmu")
    assert_equivalent_xml("REF-container-modelDescription-2.xml", "array-2/modelDescription.xml",
                          ignore_attributes=VOLATILE_XML_ATTRIBUTES)
    if WIN:
        assert_simulation("array-2.fmu", 0.1)


@pytest.mark.fmi3
def test_array23_container(area_dir):
    assembly = Assembly("array-23.json", debug=True)
    assembly.make_fmu(fmi_version=3)
    assert_identical_files("REF-container-23.txt", "array-23/resources/container.txt")
    if WIN:
        assert_simulation("array-23.fmu", 0.1)


@pytest.mark.fmi3
def test_array32_container(area_dir):
    assembly = Assembly("array-32.json", debug=True)
    assembly.make_fmu(fmi_version=3)
    assert_identical_files("REF-container-32.txt", "array-32/resources/container.txt")
    if WIN:
        assert_simulation("array-32.fmu", 0.1)

