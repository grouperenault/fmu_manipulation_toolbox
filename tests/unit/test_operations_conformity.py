"""Conformity of the operations with the FMI 2.0.5 and 3.0.2 specifications.

Defects found while checking `model_description.py` against the standard
(`docs/refactoring.md`, phase 1) and fixed in phase 2. Unlike D1 to D9, they are
not caused by the XML serialisation: the operations themselves broke rules of
the standard that the XSD does not check.

D11 is fixed by renumbering. For D10, D12 and D13 the chosen policy is to
refuse the operation (`OperationError`) and to leave the descriptor unchanged.
"""
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.operations import (FMU, OperationError, OperationKeepOnlyRegexp,
                                                 OperationMergeTopLevel, OperationRemoveRegexp,
                                                 OperationStripTopLevel)

pytestmark = [pytest.mark.unit]


def make_fmu(tmp_path: Path, descriptor: str) -> FMU:
    fmu_filename = tmp_path / "test.fmu"
    with zipfile.ZipFile(fmu_filename, "w") as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
    return FMU(str(fmu_filename))


def variables(fmu: FMU):
    return list(ET.parse(fmu.descriptor_filename).getroot().find("ModelVariables"))


def assert_refused(fmu: FMU, operation, match: str):
    """The operation raises `OperationError` and leaves the descriptor file untouched."""
    before = Path(fmu.descriptor_filename).read_bytes()
    with pytest.raises(OperationError, match=match):
        fmu.apply_operation(operation)
    assert Path(fmu.descriptor_filename).read_bytes() == before


FMI2_ME = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="m" guid="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <ModelExchange modelIdentifier="m"/>
  <ModelVariables>
    <ScalarVariable name="p" valueReference="0" causality="parameter" variability="fixed"><Real start="1"/></ScalarVariable>
    <ScalarVariable name="x" valueReference="1" causality="local" variability="continuous" initial="exact"><Real start="0"/></ScalarVariable>
    <ScalarVariable name="der(x)" valueReference="2" causality="local" variability="continuous"><Real derivative="2"/></ScalarVariable>
  </ModelVariables>
  <ModelStructure>
    <Derivatives><Unknown index="3" dependencies="2"/></Derivatives>
  </ModelStructure>
</fmiModelDescription>
"""

FMI3_ME = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <ModelExchange modelIdentifier="m"/>
  <ModelVariables>
    <Float64 name="x" valueReference="1" causality="local" variability="continuous" initial="exact" start="0"/>
    <Float64 name="der(x)" valueReference="2" causality="local" variability="continuous" derivative="1"/>
  </ModelVariables>
  <ModelStructure>
    <ContinuousStateDerivative valueReference="2"/>
  </ModelStructure>
</fmiModelDescription>
"""

FMI3_REFERENCES = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <CoSimulation modelIdentifier="m"/>
  <ModelVariables>
    <UInt64 name="n" valueReference="1" causality="structuralParameter" variability="fixed" start="2"/>
    <Clock name="clk" valueReference="2" causality="input" intervalVariability="triggered"/>
    <Float64 name="z" valueReference="3" causality="local" variability="discrete" clocks="2" initial="exact" start="0"/>
    <Float64 name="y" valueReference="4" causality="output" variability="discrete" clocks="2" previous="3">
      <Dimension valueReference="1"/>
    </Float64>
  </ModelVariables>
  <ModelStructure>
    <Output valueReference="4"/>
  </ModelStructure>
</fmiModelDescription>
"""


# --------------------------------------------------------------------------- #
#                  D11: FMI-2 `derivative` index renumbering                   #
# --------------------------------------------------------------------------- #
def test_d11_fmi2_derivative_index_is_renumbered(tmp_path):
    """FMI-2 §2.2.7: `derivative` is the `ScalarVariable` index (1-based position) of the state."""
    fmu = make_fmu(tmp_path, FMI2_ME)
    fmu.apply_operation(OperationRemoveRegexp("p"))
    svs = variables(fmu)
    names = [sv.get("name") for sv in svs]
    derivative = int(svs[names.index("der(x)")].find("Real").get("derivative"))
    assert names[derivative - 1] == "x"


# --------------------------------------------------------------------------- #
#               D12: removal of a variable that is still referenced            #
# --------------------------------------------------------------------------- #
def test_d12_fmi2_removing_a_state_is_refused(tmp_path):
    assert_refused(make_fmu(tmp_path, FMI2_ME), OperationRemoveRegexp("x"),
                   match=r"'x' is referenced by 'der\(x\)' \(derivative\)")


def test_d12_fmi3_removing_a_state_is_refused(tmp_path):
    assert_refused(make_fmu(tmp_path, FMI3_ME), OperationRemoveRegexp("x"),
                   match=r"'x' is referenced by 'der\(x\)' \(derivative\)")


@pytest.mark.parametrize("removed, kind", [("n", "Dimension"), ("clk", "clocks"), ("z", "previous")])
def test_d12_fmi3_references_are_checked(tmp_path, removed, kind):
    """FMI-3 §2.4.7: `<Dimension valueReference>`, `clocks` and `previous` refer to other variables."""
    assert_refused(make_fmu(tmp_path, FMI3_REFERENCES), OperationRemoveRegexp(f"{removed}$"),
                   match=f"'{removed}' is referenced by 'y' \\({kind}\\)")


def test_d12_removing_the_referencing_variable_too_is_accepted(tmp_path):
    fmu = make_fmu(tmp_path, FMI2_ME)
    fmu.apply_operation(OperationRemoveRegexp("(x|der)"))
    assert [sv.get("name") for sv in variables(fmu)] == ["p"]
    assert ET.parse(fmu.descriptor_filename).getroot().find("ModelStructure/Derivatives") is None


def test_d12_existing_dangling_references_are_not_reported(tmp_path):
    """Only references broken by the operation itself are refused."""
    dangling = FMI3_ME.replace('derivative="1"', 'derivative="99"')
    fmu = make_fmu(tmp_path, dangling.replace("</ModelVariables>",
                                              '<Float64 name="w" valueReference="5"/></ModelVariables>'))
    fmu.apply_operation(OperationRemoveRegexp("w"))
    assert [v.get("name") for v in variables(fmu)] == ["x", "der(x)"]


# --------------------------------------------------------------------------- #
#                         D13: names must stay unique                          #
# --------------------------------------------------------------------------- #
def test_d13_duplicate_names_are_refused(tmp_path):
    """FMI-2 §2.2.7 and FMI-3 §2.4 (uniqueNameAttribute): variable (and FMI-3 alias) names are unique."""
    fmu = make_fmu(tmp_path, FMI3_ME.replace('name="x"', 'name="a.y"').replace('name="der(x)"', 'name="b.y"'))
    assert_refused(fmu, OperationStripTopLevel(), match="same name to several variables: 'y'")


def test_d13_collision_with_an_alias_is_refused(tmp_path):
    """A variable renamed `a.b` -> `a_b` collides with the existing alias `a_b`."""
    descriptor = FMI3_ME.replace('name="der(x)"', 'name="a.b"').replace(
        'start="0"/>', 'start="0"><Alias name="a_b"/></Float64>', 1)
    assert_refused(make_fmu(tmp_path, descriptor), OperationMergeTopLevel(), match="'a_b'")


def test_d13_existing_duplicates_are_not_reported(tmp_path):
    """An FMU that already has duplicate names can still be processed."""
    fmu = make_fmu(tmp_path, FMI3_ME.replace('name="der(x)"', 'name="x"'))
    fmu.apply_operation(OperationMergeTopLevel())
    assert [v.get("name") for v in variables(fmu)] == ["x", "x"]


# --------------------------------------------------------------------------- #
#                    D10: <ModelVariables> cannot become empty                 #
# --------------------------------------------------------------------------- #
def test_d10_removing_every_variable_is_refused(tmp_path):
    assert_refused(make_fmu(tmp_path, FMI2_ME), OperationKeepOnlyRegexp("nothing"),
                   match="remove every variable")
