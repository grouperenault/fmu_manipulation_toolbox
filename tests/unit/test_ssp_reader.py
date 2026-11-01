"""The SSP reader on hand-built SSP archives.

Each test writes a small `SystemStructure.ssd` and the FMUs it refers to (descriptor only: reading an SSP does not
run them), then reads it with `Assembly`. What the container cannot honour is refused with an `AssemblyError` when
it would change the result, and only reported when it would not (plan `ssp_beta`, decision D1).
"""
import logging
import zipfile

import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError

pytestmark = [pytest.mark.unit]

NAMESPACES = ('xmlns:ssd="http://ssp-standard.org/SSP1/SystemStructureDescription" '
              'xmlns:ssc="http://ssp-standard.org/SSP1/SystemStructureCommon" '
              'xmlns:ssv="http://ssp-standard.org/SSP1/SystemStructureParameterValues" '
              'xmlns:ssm="http://ssp-standard.org/SSP1/SystemStructureParameterMapping"')

#: FMI 2.0 descriptor of the FMUs of the tests: one input `u`, one output `y` (Real, unit m), one parameter `k`.
DESCRIPTOR = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="{name}" guid="{{{name}}}">
  <CoSimulation modelIdentifier="{name}"/>
  <UnitDefinitions><Unit name="m"/></UnitDefinitions>
  <ModelVariables>
    <ScalarVariable name="u" valueReference="0" causality="input"><Real start="0" unit="m"/></ScalarVariable>
    <ScalarVariable name="y" valueReference="1" causality="output"><Real unit="m"/></ScalarVariable>
    <ScalarVariable name="k" valueReference="2" causality="parameter" variability="fixed"><Real start="1"/></ScalarVariable>
    <ScalarVariable name="n" valueReference="3" causality="parameter" variability="fixed"><Integer start="0"/></ScalarVariable>
    <ScalarVariable name="b" valueReference="4" causality="parameter" variability="fixed"><Boolean start="false"/></ScalarVariable>
  </ModelVariables>
  <ModelStructure><Outputs><Unknown index="2"/></Outputs></ModelStructure>
</fmiModelDescription>
"""


def component(name, connectors="", extra="", attributes=""):
    """An FMU component `name` (source `resources/<name>.fmu`) with the connectors `u`, `y` and the given ones."""
    return (f'<ssd:Component name="{name}" source="resources/{name}.fmu" {attributes}>'
            f'<ssd:Connectors>'
            f'<ssd:Connector name="u" kind="input"><ssc:Real unit="m"/></ssd:Connector>'
            f'<ssd:Connector name="y" kind="output"><ssc:Real unit="m"/></ssd:Connector>'
            f'{connectors}</ssd:Connectors>{extra}</ssd:Component>')


def link(start="a", start_connector="y", end="b", end_connector="u", content="", attributes=""):
    return (f'<ssd:Connection startElement="{start}" startConnector="{start_connector}" endElement="{end}" '
            f'endConnector="{end_connector}" {attributes}>{content}</ssd:Connection>')


def ssd(elements, connections="", system="", after=""):
    """A system structure description: one system `root`, with `elements` and `connections`."""
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<ssd:SystemStructureDescription version="1.0" name="root" {NAMESPACES}>'
            f'<ssd:System name="root">{system}<ssd:Elements>{elements}</ssd:Elements>'
            f'<ssd:Connections>{connections}</ssd:Connections></ssd:System>{after}'
            f'</ssd:SystemStructureDescription>')


def read(tmp_path, description, fmus=("a", "b"), files=None):
    """Write `model.ssp` with `description` and the FMUs `fmus`, and read it."""
    path = tmp_path / "model.ssp"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SystemStructure.ssd", description)
        for name in fmus:
            fmu = tmp_path / f"{name}.fmu"
            with zipfile.ZipFile(fmu, "w") as content:
                content.writestr("modelDescription.xml", DESCRIPTOR.format(name=name))
            archive.write(fmu, f"resources/{name}.fmu")
        for name, content in (files or {}).items():
            archive.writestr(name, content)
    return Assembly("model.ssp", fmu_directory=tmp_path)


def test_a_plain_ssp_is_read(tmp_path):
    root = read(tmp_path, ssd(component("a") + component("b"), link())).root

    assert [str(item) for item in root.links] == ["model.dir/resources/a.fmu/y -> model.dir/resources/b.fmu/u"]


# --------------------------------------------------------------------------- #
#                       step 1: unsupported constructions                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("component_type", ["application/x-ssp-definition", "application/x-ssp-package"])
def test_a_component_that_is_not_an_fmu_is_refused(tmp_path, component_type):
    """D6."""
    description = ssd(component("a") + component("b", attributes=f'type="{component_type}"'), link())

    with pytest.raises(AssemblyError, match=f"component 'b' is of type '{component_type}'"):
        read(tmp_path, description)


def test_the_fmu_type_may_be_explicit_or_omitted(tmp_path):
    description = ssd(component("a", attributes='type="application/x-fmu-sharedlibrary"') + component("b"), link())

    assert len(read(tmp_path, description).root.links) == 1


def test_a_component_without_source_is_only_a_warning(tmp_path, caplog):
    """D13: kept from modeler-bridge, whatever its type, and its connections are ignored."""
    sourceless = ('<ssd:Component name="c" type="application/x-ssp-definition"><ssd:Connectors>'
                  '<ssd:Connector name="u" kind="input"><ssc:Real unit="km"/></ssd:Connector>'
                  '</ssd:Connectors></ssd:Component>')
    connections = link() + link("a", "y", "c", "u", content='<ssc:LinearTransformation factor="2"/>')

    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        root = read(tmp_path, ssd(component("a") + component("b") + sourceless, connections)).root

    assert len(root.links) == 1
    assert "Component 'c' has no source FMU" in caplog.text


@pytest.mark.parametrize("transformation", [
    '<ssc:LinearTransformation factor="2" offset="0"/>',
    '<ssc:BooleanMappingTransformation><ssc:MapEntry source="true" target="false"/></ssc:BooleanMappingTransformation>',
    '<ssc:IntegerMappingTransformation><ssc:MapEntry source="1" target="2"/></ssc:IntegerMappingTransformation>',
    '<ssc:EnumerationMappingTransformation><ssc:MapEntry source="x" target="y"/>'
    '</ssc:EnumerationMappingTransformation>',
])
def test_a_connection_transformation_is_refused(tmp_path, transformation):
    """D2: the message names the connection."""
    description = ssd(component("a") + component("b"), link(content=transformation))

    with pytest.raises(AssemblyError, match=r"connection a\.y -> b\.u has a \w+Transformation"):
        read(tmp_path, description)


def test_a_parameter_mapping_is_refused(tmp_path):
    """D5."""
    bindings = ('<ssd:ParameterBindings><ssd:ParameterBinding source="resources/values.ssv">'
                '<ssd:ParameterMapping source="resources/mapping.ssm"/></ssd:ParameterBinding></ssd:ParameterBindings>')
    description = ssd(component("a", extra=bindings) + component("b"), link())

    with pytest.raises(AssemblyError, match="component 'a' has a parameter mapping"):
        read(tmp_path, description)


def test_a_connection_through_a_signal_dictionary_is_refused(tmp_path):
    """D7."""
    reference = ('<ssd:SignalDictionaryReference name="bus" dictionary="signals"><ssd:Connectors>'
                 '<ssd:Connector name="speed" kind="inout"><ssc:Real/></ssd:Connector>'
                 '</ssd:Connectors></ssd:SignalDictionaryReference>')
    description = ssd(component("a") + component("b") + reference, link() + link("a", "y", "bus", "speed"))

    with pytest.raises(AssemblyError, match="goes through the signal dictionary reference 'bus'"):
        read(tmp_path, description)


def test_an_unused_signal_dictionary_is_only_a_warning(tmp_path, caplog):
    """D7: it changes nothing."""
    dictionaries = ('<ssd:SignalDictionaries><ssd:SignalDictionary name="signals"><ssb:DictionaryEntry '
                    'xmlns:ssb="http://ssp-standard.org/SSP1/SystemStructureSignalDictionary" name="speed">'
                    '<ssc:Real/></ssb:DictionaryEntry></ssd:SignalDictionary></ssd:SignalDictionaries>')
    description = ssd(component("a") + component("b"), link(), system="").replace(
        "</ssd:Connections>", "</ssd:Connections>" + dictionaries)

    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        root = read(tmp_path, description).root

    assert len(root.links) == 1
    assert "signal dictionaries are not supported; 'signals' ignored" in caplog.text


def _units(*definitions):
    return "<ssd:Units>" + "".join(definitions) + "</ssd:Units>"


def test_connected_connectors_of_different_units_are_refused(tmp_path):
    """D8: SSP implies a conversion."""
    end = '<ssd:Connector name="v" kind="input"><ssc:Real unit="km"/></ssd:Connector>'
    description = ssd(component("a") + component("b", connectors=end), link(end_connector="v"))

    with pytest.raises(AssemblyError, match=r"connection a\.y -> b\.v joins connectors of different units "
                                            r"\('m' and 'km'\)"):
        read(tmp_path, description)


def test_units_with_the_same_definition_need_no_conversion(tmp_path):
    """D8: the definitions of `ssc:Units` (after the system in the file) decide, not the names."""
    end = '<ssd:Connector name="v" kind="input"><ssc:Real unit="metre"/></ssd:Connector>'
    units = _units('<ssc:Unit name="m"><ssc:BaseUnit m="1"/></ssc:Unit>',
                   '<ssc:Unit name="metre"><ssc:BaseUnit m="1" factor="1"/></ssc:Unit>')
    description = ssd(component("a") + component("b", connectors=end), link(end_connector="v"), after=units)

    assert len(read(tmp_path, description).root.links) == 1


def test_units_with_another_definition_are_refused(tmp_path):
    end = '<ssd:Connector name="v" kind="input"><ssc:Real unit="km"/></ssd:Connector>'
    units = _units('<ssc:Unit name="m"><ssc:BaseUnit m="1"/></ssc:Unit>',
                   '<ssc:Unit name="km"><ssc:BaseUnit m="1" factor="1000"/></ssc:Unit>')
    description = ssd(component("a") + component("b", connectors=end), link(end_connector="v"), after=units)

    with pytest.raises(AssemblyError, match="different units"):
        read(tmp_path, description)


@pytest.mark.parametrize("end, attributes", [
    ('<ssd:Connector name="v" kind="input"><ssc:Real/></ssd:Connector>', ""),  # one side without unit
    ('<ssd:Connector name="v" kind="input"><ssc:Real unit="km"/></ssd:Connector>', 'suppressUnitConversion="true"'),
], ids=["no-unit", "conversion-suppressed"])
def test_units_are_otherwise_ignored(tmp_path, end, attributes):
    description = ssd(component("a") + component("b", connectors=end), link(end_connector="v", attributes=attributes))

    assert len(read(tmp_path, description).root.links) == 1


def test_the_units_of_an_exposed_port_are_checked(tmp_path):
    """A connection from a system connector to a component is a conversion too."""
    system = '<ssd:Connectors><ssd:Connector name="x" kind="input"><ssc:Real unit="km"/></ssd:Connector></ssd:Connectors>'
    connection = '<ssd:Connection startConnector="x" endElement="a" endConnector="u"/>'

    with pytest.raises(AssemblyError, match=r"connection x -> a\.u joins connectors of different units"):
        read(tmp_path, ssd(component("a"), connection, system=system), fmus=("a",))


def test_an_architecture_wire_is_not_checked(tmp_path):
    """Its connectors (`aw.<peer>` in the files of MIC modeler) declare no type and are not variables."""
    connectors = '<ssd:Connector name="aw.b" kind="output"/>'
    wire = link(start_connector="aw.b", end_connector="aw.a", content=(
        '<ssd:Annotations><ssc:Annotation type="fmu_manipulation_toolbox.architecture-wire">'
        '<aw:Wire xmlns:aw="urn:fmu_manipulation_toolbox:architecture-wire:1" formatVersion="1" orientation="directed"/>'
        '</ssc:Annotation></ssd:Annotations>'))

    root = read(tmp_path, ssd(component("a", connectors=connectors) + component("b"), wire)).root

    assert len(root.architecture_wires) == 1
