"""Unit tests for the scope of the operations: which ports an operation sees.

An operation is applied to every port, or only to the ports of some
causalities (`apply_on`, the `-only-*` options of `fmutool`). The FMUs are
hand-built, FMI 2.0 and FMI 3.0, with ports of every type and variability
that the filters have to tell apart.
"""
import zipfile

import pytest

from fmu_manipulation_toolbox.operations import FMU, OperationAbstract, OperationRename

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
"""  # noqa: E501

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


# --------------------------------------------------------------------------- #
#                              by type and variability                         #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("types, expected", [
    (["Real"], {"x", "k", "y", "l"}),
    (["Integer"], {"n", "m"}),
    (["Boolean"], {"b"}),
    (["Real", "Boolean"], {"x", "k", "y", "l", "b"}),
])
def test_an_fmi2_type_selects_its_family_in_both_versions(fmu_path, types, expected):
    assert _scope(fmu_path, types=types) == expected


def test_an_fmi3_type_is_exact(tmp_path):
    fmi2, fmi3 = (_write(tmp_path, name, descriptor) for name, descriptor in (("a", FMI2), ("b", FMI3)))
    assert _scope(fmi3, types=["Float64"]) == {"x", "k", "y", "l"}
    assert _scope(fmi3, types=["Int32"]) == {"n", "m"}
    assert _scope(fmi3, types=["Float32"]) == set()
    # An FMI-2 FMU has no Float64: the FMI-3 names do not stand for FMI-2 types.
    assert _scope(fmi2, types=["Float64"]) == set()


@pytest.mark.parametrize("variabilities, expected", [
    (["discrete"], {"n", "m"}),
    (["fixed"], {"b"}),
    (["tunable"], {"k"}),
    (["continuous"], {"x", "y", "l"}),
    (["fixed", "tunable"], {"b", "k"}),
])
def test_the_scope_selects_ports_by_variability(fmu_path, variabilities, expected):
    """`l` declares no variability: the default of both standards for a real is `continuous`."""
    assert _scope(fmu_path, variabilities=variabilities) == expected


@pytest.mark.parametrize("apply_on, filters, expected", [
    (["input"], {"types": ["Real"]}, {"x"}),
    (["parameter"], {"variabilities": ["fixed"]}, {"b"}),
    (None, {"types": ["Real"], "variabilities": ["continuous"]}, {"x", "y", "l"}),
    (["output"], {"types": ["Boolean"]}, set()),
])
def test_the_filters_combine(fmu_path, apply_on, filters, expected):
    assert _scope(fmu_path, apply_on, **filters) == expected


FMI3_DEFAULTS = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <CoSimulation modelIdentifier="m"/>
  <ModelVariables>
    <Float64 name="p" valueReference="1" causality="parameter" start="1"/>
    <Int32 name="i" valueReference="2" causality="input" start="0"/>
    <Float32 name="f" valueReference="3" causality="input" start="0"/>
  </ModelVariables>
  <ModelStructure/>
</fmiModelDescription>
"""


@pytest.mark.parametrize("variability, expected", [
    ("fixed", {"p"}), ("discrete", {"i"}), ("continuous", {"f"}),
])
def test_fmi3_default_variabilities(tmp_path, variability, expected):
    """FMI-3 §2.4.7.4: parameters are `fixed`, floats `continuous`, the other types `discrete`."""
    path = _write(tmp_path, "defaults", FMI3_DEFAULTS)
    assert _scope(path, variabilities=[variability]) == expected


def test_ports_out_of_scope_are_left_untouched(fmu_path):
    """A renaming restricted to the real inputs keeps the integer input."""
    with FMU(fmu_path) as fmu:
        fmu.apply_operation(OperationRename({"x": "x2", "n": "n2"}), ["input"], types=["Real"])
        names = {variable.get("name") for variable in fmu.model_description.variables()}
    assert {"x2", "n"} <= names
    assert not {"x", "n2"} & names


def _write(tmp_path, name, descriptor):
    path = tmp_path / f"{name}.fmu"
    with zipfile.ZipFile(path, "w") as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
    return str(path)


# --------------------------------------------------------------------------- #
#                               renaming from a mapping                        #
# --------------------------------------------------------------------------- #
def test_a_mapping_renames_and_an_empty_name_removes(fmu_path):
    operation = OperationRename({"x": "speed", "k": "", "unknown": "whatever"})
    with FMU(fmu_path) as fmu:
        fmu.apply_operation(operation)
        names = {variable.get("name") for variable in fmu.model_description.variables()}
    assert names == ALL_NAMES - {"x", "k"} | {"speed"}
    # The caller can report the names of the mapping that the FMU does not have.
    assert operation.found == {"x", "k"}


def test_a_mapping_is_copied(fmu_path):
    mapping = {"x": "speed"}
    operation = OperationRename(mapping)
    mapping["x"] = "changed"
    assert operation.translations == {"x": "speed"}
