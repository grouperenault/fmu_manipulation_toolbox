"""`modelDescription.xml` of FMU Containers (phase 4 of `docs/local/refactoring.md`).

The container descriptor is built as an ElementTree since phase 4. These tests
pin down what the former f-string generation got wrong:

- D7: names and descriptions coming from the embedded FMUs were written
  unescaped (invalid XML as soon as one contained `&`, `<` or `"`);
- D8: the file declared ISO-8859-1 but was written with the locale encoding;
  FMI 2.0 and 3.0 require UTF-8;
- D15: FMI-2 `<Unknown index>` entries were computed by hand and ignored the
  `ts_multiplier`, `solver` and profiling variables, so that `<Outputs>` listed
  local variables instead of the outputs as soon as one of them was present.
"""
import getpass
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xmlschema

from fmu_manipulation_toolbox.assembly import Assembly
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
    assert raw.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n')     # D8
    raw.decode("utf-8")

    root = ET.fromstring(raw)                                               # D7: well-formed
    assert root.get("author") == SPECIAL_AUTHOR
    output = [v for v in root.find("ModelVariables") if v.get("name") == SPECIAL_OUTPUT]
    assert len(output) == 1 and output[0].get("description") == SPECIAL_DESCRIPTION
    assert [error.reason for error in _schema(fmi_version).iter_errors(str(descriptor))] == []


@pytest.mark.parametrize("options", [
    {"default_profiling": True},
    {"default_ts_multiplier": True},
    {"default_profiling": True, "default_ts_multiplier": True},
    {},
], ids=["profiling", "ts_multiplier", "both", "none"])
def test_fmi2_outputs_index_the_output_variables(area_dir, options):
    """FMI-2 §2.2.8: <Outputs> lists exactly the variables with causality="output", by 1-based index."""
    Assembly("bouncing-profiling.csv", debug=True, **options).make_fmu(fmi_version=2)
    root = ET.parse("bouncing-profiling/modelDescription.xml").getroot()
    variables = root.find("ModelVariables").findall("ScalarVariable")
    expected = [index for index, variable in enumerate(variables, start=1) if variable.get("causality") == "output"]
    assert expected, "the assembly should expose outputs"

    for section in ("Outputs", "InitialUnknowns"):
        indexes = [int(unknown.get("index")) for unknown in root.find(f"ModelStructure/{section}")]
        assert indexes == expected, section


@pytest.mark.fmi3
def test_fmi3_outputs_reference_the_output_variables(area_dir):
    Assembly("bouncing-profiling.csv", debug=True, default_profiling=True,
             default_ts_multiplier=True).make_fmu(fmi_version=3)
    root = ET.parse("bouncing-profiling/modelDescription.xml").getroot()
    outputs = [v.get("valueReference") for v in root.find("ModelVariables") if v.get("causality") == "output"]
    assert [o.get("valueReference") for o in root.find("ModelStructure").findall("Output")] == outputs
