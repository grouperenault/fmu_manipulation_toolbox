"""Unit tests for the scope of the operations: which ports an operation sees.

An operation is applied to every port, or only to the ports of some
causalities (`apply_on`, the `-only-*` options of `fmutool`). The FMUs are
hand-built, FMI 2.0 and FMI 3.0, with ports of every type and variability
that the filters have to tell apart.
"""
import zipfile

import pytest

from fmu_manipulation_toolbox.operations import FMU, OperationAbstract

pytestmark = [pytest.mark.unit]

FMI2 = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="m" guid="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <CoSimulation modelIdentifier="m"/>
  <ModelVariables>
    <ScalarVariable name="x" valueReference="1" causality="input" variability="continuous"><Real start="0"/></ScalarVariable>
    <ScalarVariable name="n" valueReference="2" causality="input" variability="discrete"><Integer start="1"/></ScalarVariable>
    <ScalarVariable name="b" valueReference="3" causality="parameter" variability="fixed"><Boolean start="false"/></ScalarVariable>
    <ScalarVariable name="k" valueReference="4" causality="parameter" variability="tunable"><Real start="2"/></ScalarVariable>
    <ScalarVariable name="y" valueReference="5" causality="output" variability="continuous"><Real/></ScalarVariable>
    <ScalarVariable name="m" valueReference="6" causality="output" variability="discrete"><Integer/></ScalarVariable>
    <ScalarVariable name="l" valueReference="7"><Real/></ScalarVariable>
  </ModelVariables>
  <ModelStructure>
    <Outputs>
      <Unknown index="5"/>
      <Unknown index="6"/>
    </Outputs>
  </ModelStructure>
</fmiModelDescription>
"""

FMI3 = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <CoSimulation modelIdentifier="m"/>
  <ModelVariables>
    <Float64 name="x" valueReference="1" causality="input" variability="continuous" start="0"/>
    <Int32 name="n" valueReference="2" causality="input" variability="discrete" start="1"/>
    <Boolean name="b" valueReference="3" causality="parameter" variability="fixed" start="false"/>
    <Float64 name="k" valueReference="4" causality="parameter" variability="tunable" start="2"/>
    <Float64 name="y" valueReference="5" causality="output" variability="continuous"/>
    <Int32 name="m" valueReference="6" causality="output" variability="discrete"/>
    <Float64 name="l" valueReference="7"/>
  </ModelVariables>
  <ModelStructure>
    <Output valueReference="5"/>
    <Output valueReference="6"/>
  </ModelStructure>
</fmiModelDescription>
"""

ALL_NAMES = {"x", "n", "b", "k", "y", "m", "l"}


@pytest.fixture(params=[FMI2, FMI3], ids=["fmi2", "fmi3"])
def fmu_path(request, tmp_path):
    path = tmp_path / "model.fmu"
    with zipfile.ZipFile(path, "w") as fmu:
        fmu.writestr("modelDescription.xml", request.param)
    return str(path)


class OperationProbe(OperationAbstract):
    """Read-only operation recording the ports it is called for."""
    read_only = True

    def __init__(self):
        self.seen = set()

    def port_attrs(self, fmu_port):
        self.seen.add(fmu_port["name"])
        return 0


def _scope(fmu_path, apply_on=None, **filters):
    """Names of the ports an operation is applied to."""
    probe = OperationProbe()
    with FMU(fmu_path) as fmu:
        fmu.apply_operation(probe, apply_on, **filters)
    return probe.seen


def test_without_scope_every_port_is_processed(fmu_path):
    assert _scope(fmu_path) == ALL_NAMES


def test_an_empty_scope_means_every_port(fmu_path):
    assert _scope(fmu_path, []) == ALL_NAMES


@pytest.mark.parametrize("causalities, expected", [
    (["input"], {"x", "n"}),
    (["parameter"], {"b", "k"}),
    (["output"], {"y", "m"}),
    (["input", "parameter"], {"x", "n", "b", "k"}),
])
def test_the_scope_selects_ports_by_causality(fmu_path, causalities, expected):
    assert _scope(fmu_path, causalities) == expected


def test_a_port_without_causality_is_local(fmu_path):
    """FMI defaults the causality to `local`: the filter must too."""
    assert _scope(fmu_path, ["local"]) == {"l"}
