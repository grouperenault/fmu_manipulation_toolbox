"""Unit tests of `model_description.py` (phase 1 of `docs/local/refactoring.md`).

Three sets of descriptors are used:

- every FMU of `tests/data` (what the toolbox meets in practice);
- the Reference FMUs descriptors of `tests/data/reference-fmus` (written by the
  authors of the FMI standard, they cover features absent from the FMUs above:
  FMI-2 type definitions, FMI-3 aliases, binaries, clocks, ScheduledExecution);
- small hand-written descriptors, for features absent from both (comments,
  namespaces, variable annotations, escaping, ...).
"""
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
import xmlschema

from fmu_manipulation_toolbox.model_description import ModelDescription, ModelDescriptionError, ModelVariable
from fmu_manipulation_toolbox.operations import FMU, FMUPort, OperationAbstract

from _helpers.assertions import assert_equivalent_xml

pytestmark = [pytest.mark.unit]

DATA_DIR = Path(__file__).parent.parent / "data"
XSD_DIR = Path(__file__).parent.parent.parent / "fmu_manipulation_toolbox" / "resources"


def _toolbox_descriptors() -> dict[str, bytes]:
    descriptors = {}
    for fmu_path in sorted(DATA_DIR.rglob("*.fmu")):
        with zipfile.ZipFile(fmu_path) as fmu:
            descriptors[fmu_path.relative_to(DATA_DIR).as_posix()] = fmu.read("modelDescription.xml")
    return descriptors


def _reference_descriptors() -> dict[str, bytes]:
    return {path.relative_to(DATA_DIR).as_posix(): path.read_bytes()
            for path in sorted((DATA_DIR / "reference-fmus").rglob("modelDescription.xml"))}


DESCRIPTORS: dict[str, bytes] = {**_toolbox_descriptors(), **_reference_descriptors()}

FMI2 = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="m" guid="{{8c4e810f-3df3-4a00-8276-176fa3c9f000}}">
  <CoSimulation modelIdentifier="m"/>
  {header}
  <ModelVariables>
    <ScalarVariable name="u" valueReference="1" causality="input" variability="continuous" description="input">
      <Real start="0"/>{variable}
    </ScalarVariable>
    <ScalarVariable name="y" valueReference="2" causality="output" variability="continuous">
      <Real/>
    </ScalarVariable>
  </ModelVariables>
  <ModelStructure>
    <Outputs><Unknown index="2" dependencies="1"/></Outputs>
  </ModelStructure>
</fmiModelDescription>
"""

FMI3 = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{{8c4e810f-3df3-4a00-8276-176fa3c9f000}}">
  <CoSimulation modelIdentifier="m"/>
  <ModelVariables>
    <Float64 name="u" valueReference="1" causality="input" start="0">{variable}</Float64>
    <Float64 name="y" valueReference="2" causality="output"/>{extra_variable}
  </ModelVariables>
  <ModelStructure>
    <Output valueReference="2" dependencies="1"/>
  </ModelStructure>
</fmiModelDescription>
"""


def fmi2(header="", variable="") -> bytes:
    return FMI2.format(header=header, variable=variable).encode("utf-8")


def fmi3(variable="", extra_variable="") -> bytes:
    return FMI3.format(variable=variable, extra_variable=extra_variable).encode("utf-8")


#: Hand-written descriptors exercising what the expat implementation loses (D1 to D5).
EDGE_CASES: dict[str, bytes] = {
    "escaped-text": fmi2(header='<VendorAnnotations><Tool name="T"><Info>x &lt; y &amp; z</Info></Tool>'
                                '</VendorAnnotations>'),
    "escaped-attribute": fmi2().replace(b'description="input"', b'description="a &amp;lt; b &quot;c&quot;"'),
    "fmi2-variable-annotations": fmi2(variable='<Annotations><Tool name="T"><Meta k="v"/></Tool></Annotations>'),
    "fmi3-alias": fmi3(variable='<Alias name="u_alias" description="alias"/>'),
    "fmi3-string-array": fmi3(extra_variable='<String name="s" valueReference="3" causality="parameter" '
                                             'variability="fixed"><Dimension start="2"/>'
                                             '<Start value="a&quot;b"/><Start value="&lt;c&gt;"/></String>'),
    "comments": fmi2(header="<!-- inside the root -->").replace(
        b"<fmiModelDescription", b"<!-- before the root -->\n<fmiModelDescription") + b"<!-- after the root -->\n",
    "namespaces": fmi3(variable='<Annotations><Annotation type="com.example"><v:Data xmlns:v="urn:vendor" v:k="1">'
                                'text</v:Data></Annotation></Annotations>'),
    "non-ascii": fmi2().replace(b'description="input"', 'description="débit µ ≤ 1"'.encode("utf-8")),
}

ALL_DESCRIPTORS: dict[str, bytes] = {**DESCRIPTORS, **{f"edge/{k}": v for k, v in EDGE_CASES.items()}}


# --------------------------------------------------------------------------- #
#                                 Loading                                      #
# --------------------------------------------------------------------------- #
def test_load_from_file(tmp_path):
    path = tmp_path / "modelDescription.xml"
    path.write_bytes(fmi2())
    md = ModelDescription.load(path)
    assert md.fmi_version == 2
    assert md.root.get("modelName") == "m"


@pytest.mark.parametrize("fmi_version, expected", [("2.0", 2), ("3.0", 3), ("3.0.2", 3), ("3.1-dev", 3)])
def test_fmi_version(fmi_version, expected):
    assert ModelDescription.load(fmi2().replace(b'fmiVersion="2.0"', f'fmiVersion="{fmi_version}"'.encode())
                                 ).fmi_version == expected


@pytest.mark.parametrize("descriptor, message", [
    (fmi2().replace(b'fmiVersion="2.0"', b'fmiVersion="1.0"'), "Unsupported fmiVersion"),
    (fmi2().replace(b'fmiVersion="2.0"', b'fmiVersion="7"'), "Unsupported fmiVersion"),
    (fmi2().replace(b'fmiVersion="2.0"', b''), "Invalid fmiVersion"),
    (b'<?xml version="1.0"?><model/>', "expected <fmiModelDescription>"),
    (b'<fmiModelDescription fmiVersion="2.0"><Info>x < y</Info></fmiModelDescription>', "not well-formed"),
], ids=["fmi1", "fmi7", "no-version", "wrong-root", "not-well-formed"])
def test_load_errors(descriptor, message):
    with pytest.raises(ModelDescriptionError, match=message):
        ModelDescription.load(descriptor)


def test_missing_model_variables():
    md = ModelDescription.load(b'<fmiModelDescription fmiVersion="3.0"/>')
    with pytest.raises(ModelDescriptionError, match="ModelVariables"):
        md.variables()


# --------------------------------------------------------------------------- #
#                           Round trip (load + save)                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ALL_DESCRIPTORS)
def test_roundtrip_is_equivalent(name):
    original = ALL_DESCRIPTORS[name]
    assert_equivalent_xml(original, ModelDescription.load(original).to_bytes(), with_comments=True)


@pytest.mark.parametrize("name", ALL_DESCRIPTORS)
def test_saved_file_starts_with_utf8_declaration(name):
    """FMI-2 §2.2 / FMI-3 §2.4: the first line declares the encoding, which is always UTF-8."""
    saved = ModelDescription.load(ALL_DESCRIPTORS[name]).to_bytes()
    assert saved.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    saved.decode("utf-8")


def test_non_utf8_input_is_saved_in_utf8():
    latin1 = fmi2().replace(b'encoding="UTF-8"', b'encoding="ISO-8859-1"').replace(
        b'description="input"', 'description="débit"'.encode("latin-1"))
    saved = ModelDescription.load(latin1).to_bytes()
    assert 'description="débit"'.encode("utf-8") in saved
    assert ET.fromstring(saved).find("ModelVariables")[0].get("description") == "débit"


def test_comments_outside_root_are_kept():
    saved = ModelDescription.load(EDGE_CASES["comments"]).to_bytes()
    assert saved.index(b"<!-- before the root -->") < saved.index(b"<fmiModelDescription")
    assert saved.index(b"<!-- after the root -->") > saved.index(b"</fmiModelDescription>")


def test_namespace_prefixes_are_kept():
    saved = ModelDescription.load(EDGE_CASES["namespaces"]).to_bytes()
    assert b"<v:Data" in saved and b'xmlns:v="urn:vendor"' in saved
    assert b"ns0:" not in saved


@pytest.mark.parametrize("name", DESCRIPTORS)
def test_roundtrip_keeps_xsd_validity(name, tmp_path):
    original = DESCRIPTORS[name]
    md = ModelDescription.load(original)
    schema = _schema(md.fmi_version)
    if not schema.is_valid(ET.fromstring(original)):
        pytest.skip("the original descriptor is not XSD-valid")
    path = tmp_path / "modelDescription.xml"
    md.save(path)
    assert [error.reason for error in schema.iter_errors(str(path))] == []


_SCHEMAS: dict[int, xmlschema.XMLSchema] = {}


def _schema(fmi_version: int) -> xmlschema.XMLSchema:
    if fmi_version not in _SCHEMAS:
        _SCHEMAS[fmi_version] = xmlschema.XMLSchema(
            str(XSD_DIR / f"fmi-{fmi_version}.0" / f"fmi{fmi_version}ModelDescription.xsd"))
    return _SCHEMAS[fmi_version]


def test_save_to_file_object(tmp_path):
    md = ModelDescription.load(fmi3())
    with open(tmp_path / "md.xml", "wb") as file:
        md.save(file)
    assert (tmp_path / "md.xml").read_bytes() == md.to_bytes()


# --------------------------------------------------------------------------- #
#                                 Structure                                    #
# --------------------------------------------------------------------------- #
def _reference(name: str) -> ModelDescription:
    return ModelDescription.load(DESCRIPTORS[f"reference-fmus/{name}/modelDescription.xml"])


def test_fmi2_type_definitions_are_not_variables():
    """FMI-2 `<SimpleType>` children share their tag with variable types (`<Real>`, `<Enumeration>`...)."""
    md = _reference("2.0/Feedthrough")
    assert md.root.find("TypeDefinitions") is not None
    variables = md.variables()
    assert [v.tag for v in variables] == ["ScalarVariable"] * len(md.root.find("ModelVariables").findall("ScalarVariable"))
    assert all(port.fmi_type in ModelDescription.FMI2_VARIABLE_TYPES for port in md.iter_ports())


def test_fmi3_variables_exclude_comments():
    md = ModelDescription.load(fmi3(variable="<!-- c -->").replace(b"<ModelVariables>", b"<ModelVariables><!-- c -->"))
    assert [v.get("name") for v in md.variables()] == ["u", "y"]


@pytest.mark.parametrize("name, expected", [
    ("2.0/BouncingBall", {"ModelExchange", "CoSimulation"}),
    ("3.0/BouncingBall", {"ModelExchange", "CoSimulation"}),
    ("3.0/Clocks", {"ScheduledExecution"}),
])
def test_interfaces(name, expected):
    assert set(_reference(name).interfaces) == expected


def test_fmi2_model_structure_entries():
    md = _reference("2.0/BouncingBall")
    entries = md.model_structure_entries()
    sections = [section for section, _ in entries]
    assert set(sections) <= set(ModelDescription.FMI2_STRUCTURE_SECTIONS)
    assert all(element.tag == "Unknown" for _, element in entries)
    # `index` is 1-based in the order of the variables.
    names = [v.get("name") for v in md.variables()]
    derivatives = [names[int(element.get("index")) - 1] for section, element in entries if section == "Derivatives"]
    assert derivatives == ["der(h)", "der(v)"]


def test_fmi3_model_structure_entries():
    md = _reference("3.0/BouncingBall")
    entries = md.model_structure_entries()
    assert {section for section, _ in entries} <= set(ModelDescription.FMI3_STRUCTURE_ELEMENTS)
    assert all(section == element.tag for section, element in entries)
    assert "EventIndicator" in {section for section, _ in entries}


def test_model_structure_entries_without_model_structure():
    md = ModelDescription.load(fmi3().replace(b"<ModelStructure>\n    <Output valueReference=\"2\" dependencies=\"1\"/>"
                                              b"\n  </ModelStructure>", b""))
    assert md.model_structure is None
    assert md.model_structure_entries() == []


def test_parent_of():
    md = ModelDescription.load(fmi2())
    first, second = md.variables()
    assert md.parent_of(md.root) is None
    assert md.parent_of(first) is md.model_variables
    md.model_variables.remove(first)
    new = ET.SubElement(md.model_variables, "ScalarVariable")
    assert md.parent_of(new) is md.model_variables
    with pytest.raises(KeyError):
        md.parent_of(first)


# --------------------------------------------------------------------------- #
#                 ModelVariable: compatibility with FMUPort                    #
# --------------------------------------------------------------------------- #
class _CollectPorts(OperationAbstract):
    def __init__(self):
        self.ports = []

    def port_attrs(self, fmu_port: FMUPort) -> int:
        self.ports.append(_port_view(fmu_port))
        return 0


def _port_view(port) -> dict:
    """What an operation can read from an `FMUPort` or a `ModelVariable`."""
    keys = {key for attrs in port.attrs_list for key in attrs}
    return {
        "fmi_type": port.fmi_type,
        "attrs_list": [dict(attrs) for attrs in port.attrs_list],
        "values": {key: port[key] for key in keys},
        "contains": {key: key in port for key in keys | {"start", "missing"}},
        "start": port.get("start", None),
        "dimensions": port.dimensions,
    }


def _expat_ports(descriptor: bytes, tmp_path: Path) -> list[dict]:
    fmu_path = tmp_path / "test.fmu"
    with zipfile.ZipFile(fmu_path, "w") as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
    collector = _CollectPorts()
    FMU(str(fmu_path)).apply_operation(collector)
    return collector.ports


@pytest.mark.parametrize("name", DESCRIPTORS)
def test_model_variable_reads_like_fmu_port(name, tmp_path):
    """`ModelVariable` gives operations exactly what `FMUPort` gives them today."""
    descriptor = DESCRIPTORS[name]
    expected = _expat_ports(descriptor, tmp_path)
    assert expected, "no variable collected: the comparison would be vacuous"
    actual = [_port_view(port) for port in ModelDescription.load(descriptor).iter_ports()]
    assert actual == expected


def test_model_variable_writes_go_to_the_tree():
    md = ModelDescription.load(fmi2())
    u, y = md.iter_ports()
    u["name"] = "renamed"                      # existing attribute, ScalarVariable level
    u["start"] = "1.5"                         # existing attribute, <Real> level
    u.attrs_list[0]["description"] = "new"     # fmueditor creates attributes this way
    y.fmi_type = "Integer"                     # EmbeddedFMU turns enumerations into integers this way
    with pytest.raises(KeyError):
        u["unit"] = "m"                        # FMUPort does not create attributes through []
    saved = ET.fromstring(md.to_bytes())
    first, second = saved.find("ModelVariables").findall("ScalarVariable")
    assert first.get("name") == "renamed" and first.get("description") == "new"
    assert first.find("Real").get("start") == "1.5"
    assert second.find("Integer") is not None and second.find("Real") is None


def test_model_variable_fmi3_start_elements():
    md = ModelDescription.load(EDGE_CASES["fmi3-string-array"])
    string = [port for port in md.iter_ports() if port.fmi_type == "String"][0]
    assert string["start"] == 'a"b'            # first <Start>, as FMUPort
    assert string.dimensions == [("start", 2)]
    string["start"] = "changed"
    for attrs in string.attrs_list:
        attrs.pop("description", None)         # fmueditor removes descriptions this way
    starts = ET.fromstring(md.to_bytes()).find("ModelVariables").find("String").findall("Start")
    assert [start.get("value") for start in starts] == ["changed", "<c>"]


def test_model_variable_dimension_of_one_is_scalar():
    """Same convention as `FMUPort.dimensions`."""
    md = ModelDescription.load(fmi3(extra_variable='<Float64 name="a" valueReference="3"><Dimension start="1"/>'
                                                   '</Float64>'))
    assert [port.dimensions for port in md.iter_ports()] == [[], [], []]


def test_model_variable_repr():
    port = next(ModelDescription.load(fmi3()).iter_ports())
    assert isinstance(port, ModelVariable)
    assert repr(port) == "<ModelVariable Float64 'u'>"
