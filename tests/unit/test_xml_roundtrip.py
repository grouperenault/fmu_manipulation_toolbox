"""Regression tests of the `modelDescription.xml` rewriting defects.

`FMU.apply_operation` rewrites the descriptor even for an operation that changes
nothing; that rewrite must keep the meaning of the document. Each test below
targets one defect listed in `docs/refactoring.md` (D1 to D9) and is marked
`xfail(strict=True)` until the phase that fixes it: once fixed, the test passes,
`strict` turns it into a failure, and the marker must be removed.
"""
import xml.etree.ElementTree as ET
import xml.parsers.expat
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.operations import FMU, FMUError, OperationAbstract, OperationRemoveSources

from _helpers.assertions import assert_equivalent_xml

pytestmark = [pytest.mark.unit]

FMI2 = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="m" guid="{{8c4e810f-3df3-4a00-8276-176fa3c9f000}}"{root_attrs}>
  <CoSimulation modelIdentifier="m">{cosimulation}</CoSimulation>
  {header}
  <ModelVariables>
    <ScalarVariable name="u" valueReference="1" causality="input" variability="continuous">
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


def fmi2(root_attrs="", cosimulation="", header="", variable="") -> str:
    return FMI2.format(root_attrs=root_attrs, cosimulation=cosimulation, header=header, variable=variable)


def fmi3(variable="", extra_variable="") -> str:
    return FMI3.format(variable=variable, extra_variable=extra_variable)


def make_fmu(tmp_path: Path, descriptor: str, extra_files=()) -> Path:
    fmu_filename = tmp_path / "test.fmu"
    with zipfile.ZipFile(fmu_filename, "w") as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
        for name in extra_files:
            fmu.writestr(name, "")
    return fmu_filename


def assert_noop_roundtrip(tmp_path: Path, descriptor: str, with_comments=False) -> None:
    fmu = FMU(str(make_fmu(tmp_path, descriptor)))
    fmu.apply_operation(OperationAbstract())
    assert_equivalent_xml(descriptor.encode("utf-8"), fmu.descriptor_filename, with_comments=with_comments)


def xfail(defect: str, phase: int, raises=AssertionError):
    """Expected failure of a known defect, restricted to the exception that the defect raises."""
    return pytest.mark.xfail(strict=True, raises=raises,
                             reason=f"{defect} (docs/refactoring.md, fixed in phase {phase})")


# --------------------------------------------------------------------------- #
#                 Controls: the templates themselves round-trip                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("descriptor", [fmi2(), fmi3()], ids=["fmi2", "fmi3"])
def test_plain_descriptor_roundtrip(tmp_path, descriptor):
    assert_noop_roundtrip(tmp_path, descriptor)


# --------------------------------------------------------------------------- #
#                                   Defects                                    #
# --------------------------------------------------------------------------- #
@xfail("D1: text between tags is written unescaped", phase=2, raises=ET.ParseError)
def test_d1_text_is_escaped(tmp_path):
    header = '<VendorAnnotations><Tool name="T"><Info>x &lt; y &amp; z</Info></Tool></VendorAnnotations>'
    assert_noop_roundtrip(tmp_path, fmi2(header=header))


@xfail("D2: FMI-3 <Start value> of String variables is written unescaped", phase=2, raises=ET.ParseError)
def test_d2_string_start_is_escaped(tmp_path):
    extra = ('\n    <String name="s" valueReference="3" causality="parameter" variability="fixed">'
             '<Start value="a&quot;b&lt;c"/></String>')
    assert_noop_roundtrip(tmp_path, fmi3(extra_variable=extra))


@xfail("D3: attribute values are unescaped twice", phase=2)
def test_d3_attributes_are_not_unescaped_twice(tmp_path):
    assert_noop_roundtrip(tmp_path, fmi2(root_attrs=' description="a &amp;lt; b"'))


@xfail("D4: <Annotations> of an FMI-2 <ScalarVariable> are dropped", phase=2)
def test_d4_fmi2_variable_annotations_are_kept(tmp_path):
    variable = '\n      <Annotations><Tool name="T"><Meta k="v"/></Tool></Annotations>'
    assert_noop_roundtrip(tmp_path, fmi2(variable=variable))


@xfail("D4: <Alias> of an FMI-3 variable are dropped", phase=2)
def test_d4_fmi3_alias_is_kept(tmp_path):
    assert_noop_roundtrip(tmp_path, fmi3(variable='<Alias name="u_alias" description="alias"/>'))


@xfail("D4: all <Start> values of an FMI-3 String array but the first are dropped", phase=2)
def test_d4_fmi3_string_array_start_values_are_kept(tmp_path):
    extra = ('\n    <String name="s" valueReference="3" causality="parameter" variability="fixed">'
             '<Dimension start="2"/><Start value="a"/><Start value="b"/></String>')
    assert_noop_roundtrip(tmp_path, fmi3(extra_variable=extra))


@xfail("D5: comments are dropped", phase=2)
def test_d5_comments_are_kept(tmp_path):
    assert_noop_roundtrip(tmp_path, fmi2(header="<!-- generated by hand -->"), with_comments=True)


@xfail("D5: the XML declaration is dropped", phase=2)
def test_d5_xml_declaration_is_kept(tmp_path):
    fmu = FMU(str(make_fmu(tmp_path, fmi2())))
    fmu.apply_operation(OperationAbstract())
    assert Path(fmu.descriptor_filename).read_bytes().startswith(b"<?xml")


@xfail("D6: a second operation fails to parse the descriptor rewritten by the first one", phase=2,
        raises=xml.parsers.expat.ExpatError)
def test_d6_operations_can_be_chained(tmp_path):
    header = '<VendorAnnotations><Tool name="T"><Info>x &lt; y</Info></Tool></VendorAnnotations>'
    fmu = FMU(str(make_fmu(tmp_path, fmi2(header=header))))
    fmu.apply_operation(OperationAbstract())
    fmu.apply_operation(OperationAbstract())


@xfail("D9: -remove-sources keeps <SourceFiles> in the descriptor", phase=2)
def test_d9_remove_sources_updates_descriptor(tmp_path):
    cosimulation = '<SourceFiles><File name="m.c"/></SourceFiles>'
    fmu = FMU(str(make_fmu(tmp_path, fmi2(cosimulation=cosimulation), extra_files=["sources/m.c"])))
    fmu.apply_operation(OperationRemoveSources())
    assert not (Path(fmu.tmp_directory) / "sources").exists()
    assert b"SourceFiles" not in Path(fmu.descriptor_filename).read_bytes()


@xfail("FMU life cycle: a file that is not a zip archive raises BadZipFile instead of FMUError", phase=3,
        raises=zipfile.BadZipFile)
def test_not_a_zip_raises_fmu_error(tmp_path):
    not_a_zip = tmp_path / "not_a_zip.fmu"
    not_a_zip.write_text("this is not a zip archive")
    with pytest.raises(FMUError):
        FMU(str(not_a_zip))
