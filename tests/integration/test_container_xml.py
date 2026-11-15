"""`modelDescription.xml` of FMU Containers.

These tests check that:

- names and descriptions coming from the embedded FMUs are escaped, so that the
  descriptor stays well-formed when one contains `&`, `<` or `"`;
- the file is encoded in UTF-8, as FMI 2.0 and 3.0 require, whatever the locale;
- the FMI-2 `<Unknown index>` entries of `<Outputs>` point to the outputs, also
  when `ts_multiplier`, `solver` or profiling variables are present;
- the initial unknowns leave out the outputs that copy `initial="exact"` from
  their embedded FMU (FMI-2 §2.2.8, FMI-3 §2.4.8), and the descriptor passes
  the semantic checker.
"""
import getpass
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xmlschema

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.checker import OperationSemanticCheck
from fmu_manipulation_toolbox.model_description import ModelDescription
from fmu_manipulation_toolbox.operations import FMU, OperationAbstract

pytestmark = [pytest.mark.integration, pytest.mark.area("containers/bouncing_ball")]

XSD_DIR = Path(__file__).parent.parent.parent / "fmu_manipulation_toolbox" / "resources"

SPECIAL_DESCRIPTION = 'Position & "height" < 10 m — hauteur µ'
SPECIAL_AUTHOR = "Zoë & <admin>"
SPECIAL_OUTPUT = "pos_é&<1>"


def _schema(fmi_version: int) -> xmlschema.XMLSchema:
    return xmlschema.XMLSchema(str(XSD_DIR / f"fmi-{fmi_version}.0" / f"fmi{fmi_version}ModelDescription.xsd"))


class _SetDescription(OperationAbstract):
    def __init__(self, port_name: str, description: str):
        self.port_name = port_name
        self.description = description

    def port_attrs(self, fmu_port) -> int:
        if fmu_port["name"] == self.port_name:
            fmu_port.attrs_list[0]["description"] = self.description
        return 0


class _SetExact(OperationAbstract):
    """Give an FMI-2 output `initial="exact"` and a start value."""
    def __init__(self, port_name: str, start: str):
        self.port_name = port_name
        self.start = start

    def port_attrs(self, fmu_port) -> int:
        if fmu_port["name"] == self.port_name:
            fmu_port.attrs_list[0]["initial"] = "exact"
            fmu_port.attrs_list[1]["start"] = self.start
        return 0


def semantic_errors(descriptor: Path) -> list[str]:
    check = OperationSemanticCheck()
    check.model_description = ModelDescription.load(descriptor)
    check.closure()
    return check.errors


@pytest.fixture
def special_assembly(area_dir, monkeypatch) -> Path:
    """Assembly whose embedded FMU, exposed output name and author contain characters to escape."""
    with FMU("bb_position.fmu") as fmu:
        fmu.apply_operation(_SetDescription("position1", SPECIAL_DESCRIPTION))
        fmu.repack("bb_special.fmu")
    monkeypatch.setattr(getpass, "getuser", lambda: SPECIAL_AUTHOR)
    csv = Path("special.csv")
    csv.write_text("rule;from_fmu;from_port;to_fmu;to_port\n"
                   "FMU;bb_special.fmu;;;\n"
                   "FMU;bb_velocity.fmu;;;\n"
                   f"OUTPUT;bb_special.fmu;position1;;{SPECIAL_OUTPUT}\n"
                   "LINK;bb_special.fmu;is_ground;bb_velocity.fmu;reset\n"
                   "LINK;bb_velocity.fmu;velocity;bb_special.fmu;velocity\n", encoding="utf-8")
    return csv


@pytest.mark.parametrize("fmi_version", [2, 3])
def test_container_descriptor_is_escaped_utf8(special_assembly, fmi_version):
    Assembly(str(special_assembly), debug=True).make_fmu(fmi_version=fmi_version)
    descriptor = Path("special/modelDescription.xml")

    raw = descriptor.read_bytes()
    assert raw.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n')     # UTF-8, whatever the locale
    raw.decode("utf-8")

    root = ET.fromstring(raw)                                               # well-formed: special characters escaped
    assert root.get("author") == SPECIAL_AUTHOR
    output = [v for v in root.find("ModelVariables") if v.get("name") == SPECIAL_OUTPUT]
    assert len(output) == 1 and output[0].get("description") == SPECIAL_DESCRIPTION
    assert [error.reason for error in _schema(fmi_version).iter_errors(str(descriptor))] == []
    assert semantic_errors(descriptor) == []


@pytest.mark.parametrize("options", [
    {"default_profiling": True},
    {"default_ts_multiplier": True},
    {"default_profiling": True, "default_ts_multiplier": True},
    {},
], ids=["profiling", "ts_multiplier", "both", "none"])
def test_fmi2_outputs_index_the_output_variables(area_dir, options):
    """FMI-2 §2.2.8: <Outputs> lists exactly the variables with causality="output", by 1-based index; the outputs
    of the bouncing ball are all initial="calculated": <InitialUnknowns> lists them too."""
    Assembly("bouncing-profiling.csv", debug=True, **options).make_fmu(fmi_version=2)
    descriptor = Path("bouncing-profiling/modelDescription.xml")
    root = ET.parse(descriptor).getroot()
    variables = root.find("ModelVariables").findall("ScalarVariable")
    expected = [index for index, variable in enumerate(variables, start=1) if variable.get("causality") == "output"]
    assert expected, "the assembly should expose outputs"

    for section in ("Outputs", "InitialUnknowns"):
        indexes = [int(unknown.get("index")) for unknown in root.find(f"ModelStructure/{section}")]
        assert indexes == expected, section
    assert semantic_errors(descriptor) == []


@pytest.mark.fmi3
def test_fmi3_outputs_reference_the_output_variables(area_dir):
    Assembly("bouncing-profiling.csv", debug=True, default_profiling=True,
             default_ts_multiplier=True).make_fmu(fmi_version=3)
    descriptor = Path("bouncing-profiling/modelDescription.xml")
    root = ET.parse(descriptor).getroot()
    outputs = [v.get("valueReference") for v in root.find("ModelVariables") if v.get("causality") == "output"]
    assert [o.get("valueReference") for o in root.find("ModelStructure").findall("Output")] == outputs
    assert [o.get("valueReference") for o in root.find("ModelStructure").findall("InitialUnknown")] == outputs
    assert semantic_errors(descriptor) == []


@pytest.fixture
def exact_assembly(area_dir) -> Path:
    """Assembly exposing `position1` with initial="exact" (and a start value) and `velocity`, initial="calculated"."""
    with FMU("bb_position.fmu") as fmu:
        fmu.apply_operation(_SetExact("position1", "1.0"))
        fmu.repack("bb_exact.fmu")
    csv = Path("exact.csv")
    csv.write_text("rule;from_fmu;from_port;to_fmu;to_port\n"
                   "FMU;bb_exact.fmu;;;\n"
                   "FMU;bb_velocity.fmu;;;\n"
                   "OUTPUT;bb_exact.fmu;position1;;position\n"
                   "OUTPUT;bb_velocity.fmu;velocity;;\n"
                   "LINK;bb_exact.fmu;is_ground;bb_velocity.fmu;reset\n"
                   "LINK;bb_velocity.fmu;velocity;bb_exact.fmu;velocity\n", encoding="utf-8")
    return csv


@pytest.mark.parametrize("fmi_version", [2, 3])
def test_initial_unknowns_leave_out_the_exact_outputs(exact_assembly, fmi_version):
    """FMI-2 §2.2.8, FMI-3 §2.4.8: an output that copies initial="exact" and its start value from the embedded FMU
    is listed as an output, not as an initial unknown."""
    Assembly(str(exact_assembly), debug=True).make_fmu(fmi_version=fmi_version)
    descriptor = Path("exact/modelDescription.xml")
    root = ET.parse(descriptor).getroot()
    variables = list(root.find("ModelVariables"))
    position = [v for v in variables if v.get("name") == "position"][0]
    assert (position.get("initial"), position.find("Real").get("start") if fmi_version == 2
            else position.get("start")) == ("exact", "1.0")

    if fmi_version == 2:
        outputs = [variables[int(u.get("index")) - 1].get("name") for u in root.find("ModelStructure/Outputs")]
        initial = [variables[int(u.get("index")) - 1].get("name")
                   for u in root.find("ModelStructure/InitialUnknowns")]
    else:
        by_vr = {v.get("valueReference"): v.get("name") for v in variables}
        outputs = [by_vr[o.get("valueReference")] for o in root.find("ModelStructure").findall("Output")]
        initial = [by_vr[o.get("valueReference")] for o in root.find("ModelStructure").findall("InitialUnknown")]
    assert sorted(outputs) == ["position", "velocity"]
    assert initial == ["velocity"]
    assert [error.reason for error in _schema(fmi_version).iter_errors(str(descriptor))] == []
    assert semantic_errors(descriptor) == []
