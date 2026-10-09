"""Conformity of the operations with the FMI 2.0.5 and 3.0.2 specifications.

Defects found while checking `model_description.py` against the standard
(`docs/refactoring.md`, phase 1). Unlike D1 to D9, they are not caused by the
XML serialisation: the operations themselves break rules of the standard that
the XSD does not check. Each test is `xfail(strict=True)` until fixed.
"""
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.operations import (FMU, OperationError, OperationRemoveRegexp,
                                                 OperationStripTopLevel)

pytestmark = [pytest.mark.unit]


def make_fmu(tmp_path: Path, descriptor: str) -> FMU:
    fmu_filename = tmp_path / "test.fmu"
    with zipfile.ZipFile(fmu_filename, "w") as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
    return FMU(str(fmu_filename))


def variables(fmu: FMU):
    return list(ET.parse(fmu.descriptor_filename).getroot().find("ModelVariables"))


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


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="D11: the FMI-2 `derivative` index is not renumbered when ports are removed "
                          "(docs/refactoring.md, fixed in phase 2)")
def test_d11_fmi2_derivative_index_is_renumbered(tmp_path):
    """FMI-2 §2.2.7: `derivative` is the `ScalarVariable` index (1-based position) of the state."""
    fmu = make_fmu(tmp_path, FMI2_ME)
    fmu.apply_operation(OperationRemoveRegexp("p"))
    svs = variables(fmu)
    names = [sv.get("name") for sv in svs]
    derivative = int(svs[names.index("der(x)")].find("Real").get("derivative"))
    assert names[derivative - 1] == "x"


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="D12: removing a variable referenced by another one leaves a dangling reference "
                          "(docs/refactoring.md, fixed in phase 2)")
def test_d12_no_dangling_reference_after_removal(tmp_path):
    """FMI-3: `derivative`, `previous`, `clocks` and `<Dimension valueReference>` refer to existing variables."""
    fmu = make_fmu(tmp_path, FMI3_ME)
    try:
        fmu.apply_operation(OperationRemoveRegexp("x"))  # the state; its derivative `der(x)` is kept
    except OperationError:
        return  # refusing the operation is an acceptable fix
    remaining = variables(fmu)
    value_references = {v.get("valueReference") for v in remaining}
    references = {v.get("derivative") for v in remaining} - {None}
    assert references <= value_references


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="D13: renaming operations can give the same name to several variables "
                          "(docs/refactoring.md, fixed in phase 2)")
def test_d13_renaming_keeps_names_unique(tmp_path):
    """FMI-2 §2.2.7 and FMI-3 §2.4 (uniqueNameAttribute): variable (and FMI-3 alias) names are unique."""
    fmu = make_fmu(tmp_path, FMI3_ME.replace('name="x"', 'name="a.y"').replace('name="der(x)"', 'name="b.y"'))
    try:
        fmu.apply_operation(OperationStripTopLevel())
    except OperationError:
        return  # refusing the operation is an acceptable fix
    names = [v.get("name") for v in variables(fmu)]
    assert len(names) == len(set(names)), f"duplicate names: {names}"
