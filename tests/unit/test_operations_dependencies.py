"""Unit tests protecting the dependency-tree integrity after a port removal.

Removing a variable from ``modelDescription.xml`` is the riskiest manipulation:
the ``<ModelStructure>`` references variables by position (FMI-2 ``index``) or by
``valueReference`` (FMI-3), and every ``dependencies`` list must stay consistent
afterwards. A regression here would silently produce an *invalid* FMU. These
tests remove one middle variable and assert that:

* the removed variable disappears from ``<ModelVariables>``;
* surviving unknowns are renumbered / rewired correctly;
* dependencies on the removed variable are dropped (with the matching
  ``dependenciesKind`` entry), while other dependencies are preserved;
* unrelated variables and the root metadata are left untouched.

Tiny self-contained descriptors are built on the fly (documented inline); they
are the smallest representative inputs for this logic and do not rely on any
external FMU.
"""
import xml.etree.ElementTree as ET
import zipfile

import pytest

from fmu_manipulation_toolbox.operations import FMU, OperationRemoveRegexp

pytestmark = [pytest.mark.unit]


def _make_fmu(tmp_path, descriptor: str):
    """Pack a bare FMU (zip) containing only the given modelDescription.xml."""
    fmu_path = tmp_path / "model.fmu"
    with zipfile.ZipFile(fmu_path, "w") as zf:
        zf.writestr("modelDescription.xml", descriptor)
    return str(fmu_path)


def _remove_and_parse(tmp_path, descriptor: str, regexp: str) -> ET.Element:
    """Remove ports matching *regexp* and return the rewritten XML root."""
    fmu = FMU(_make_fmu(tmp_path, descriptor))
    fmu.apply_operation(OperationRemoveRegexp(regexp))
    out = tmp_path / "out.xml"
    fmu.save_descriptor(str(out))
    return ET.parse(out).getroot()


# --------------------------------------------------------------------------- #
#                                   FMI 2.0                                     #
# --------------------------------------------------------------------------- #
FMI2_DESCRIPTOR = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="dep" guid="{abc}">
<CoSimulation modelIdentifier="dep"/>
<ModelVariables>
  <ScalarVariable name="in1" valueReference="0" causality="input" variability="continuous">
    <Real start="0"/>
  </ScalarVariable>
  <ScalarVariable name="mid" valueReference="1" causality="local" variability="continuous">
    <Real/>
  </ScalarVariable>
  <ScalarVariable name="out1" valueReference="2" causality="output" variability="continuous">
    <Real/>
  </ScalarVariable>
</ModelVariables>
<ModelStructure>
  <Outputs>
    <Unknown index="3" dependencies="1 2" dependenciesKind="dependent dependent"/>
  </Outputs>
  <InitialUnknowns>
    <Unknown index="3" dependencies="1 2"/>
  </InitialUnknowns>
</ModelStructure>
</fmiModelDescription>
"""


def test_fmi2_removing_middle_port_renumbers_and_rewires_dependencies(tmp_path):
    root = _remove_and_parse(tmp_path, FMI2_DESCRIPTOR, "mid")

    names = [sv.get("name") for sv in root.iter("ScalarVariable")]
    assert names == ["in1", "out1"]  # 'mid' removed, order preserved

    # 'out1' was ScalarVariable #3 and now becomes #2 after the removal of #2.
    output = root.find("ModelStructure/Outputs/Unknown")
    assert output.get("index") == "2"
    # Dependency on the removed variable (old index 2) is dropped; the dependency
    # on 'in1' (old index 1) survives, and the matching Kind entry follows it.
    assert output.get("dependencies") == "1"
    assert output.get("dependenciesKind") == "dependent"

    initial = root.find("ModelStructure/InitialUnknowns/Unknown")
    assert initial.get("index") == "2"
    assert initial.get("dependencies") == "1"

    # Root metadata is untouched.
    assert root.get("modelName") == "dep"


# --------------------------------------------------------------------------- #
#                                   FMI 3.0                                     #
# --------------------------------------------------------------------------- #
FMI3_DESCRIPTOR = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="dep" instantiationToken="{abc}">
<CoSimulation modelIdentifier="dep"/>
<ModelVariables>
  <Float64 name="in1" valueReference="0" causality="input" variability="continuous" start="0"/>
  <Float64 name="mid" valueReference="1" causality="local" variability="continuous"/>
  <Float64 name="out1" valueReference="2" causality="output" variability="continuous"/>
</ModelVariables>
<ModelStructure>
  <Output valueReference="2" dependencies="0 1" dependenciesKind="dependent dependent"/>
</ModelStructure>
</fmiModelDescription>
"""


def test_fmi3_removing_middle_port_drops_its_dependency_only(tmp_path):
    root = _remove_and_parse(tmp_path, FMI3_DESCRIPTOR, "mid")

    names = [v.get("name") for v in root.iter("Float64")]
    assert names == ["in1", "out1"]  # 'mid' removed, order preserved

    # FMI-3 references by valueReference (stable): 'out1' keeps vr=2.
    output = root.find("ModelStructure/Output")
    assert output.get("valueReference") == "2"
    # Dependency on the removed variable (vr=1) is dropped; dependency on 'in1'
    # (vr=0) survives together with its dependenciesKind entry.
    assert output.get("dependencies") == "0"
    assert output.get("dependenciesKind") == "dependent"

    assert root.get("modelName") == "dep"

