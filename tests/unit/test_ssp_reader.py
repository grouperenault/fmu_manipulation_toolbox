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

#: FMI 2.0 descriptor of the FMUs of the tests: inputs `u` (unit m) and `v`, output `y` (unit m), parameters
#: `k`, `n`, `b`; constant `c`.
DESCRIPTOR = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="{name}" guid="{{{name}}}">
  <CoSimulation modelIdentifier="{name}"/>
  <UnitDefinitions><Unit name="m"/></UnitDefinitions>
  <ModelVariables>
    <ScalarVariable name="u" valueReference="0" causality="input"><Real start="0" unit="m"/></ScalarVariable>
    <ScalarVariable name="y" valueReference="1" causality="output"><Real unit="m"/></ScalarVariable>
    <ScalarVariable name="v" valueReference="5" causality="input"><Real start="0"/></ScalarVariable>
    <ScalarVariable name="k" valueReference="2" causality="parameter" variability="fixed"><Real start="1"/></ScalarVariable>
    <ScalarVariable name="n" valueReference="3" causality="parameter" variability="fixed"><Integer start="0"/></ScalarVariable>
    <ScalarVariable name="b" valueReference="4" causality="parameter" variability="fixed"><Boolean start="false"/></ScalarVariable>
    <ScalarVariable name="c" valueReference="6" causality="local" variability="constant"><Real start="3"/></ScalarVariable>
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
    bindings = ('<ssd:ParameterBindings><ssd:ParameterBinding><ssd:ParameterValues>'
                '<ssv:ParameterSet version="1.0" name="set"><ssv:Parameters/></ssv:ParameterSet></ssd:ParameterValues>'
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


# --------------------------------------------------------------------------- #
#                 step 2: connections checked against the FMUs                #
# --------------------------------------------------------------------------- #
def test_an_unknown_connector_is_reported_with_close_names(tmp_path):
    description = ssd(component("a") + component("b"), link(start_connector="yy"))

    with pytest.raises(AssemblyError, match=r"connection a\.yy -> b\.u: component 'a' \('resources/a\.fmu'\) has no "
                                            r"variable 'yy'\. Close names: 'y'"):
        read(tmp_path, description)


@pytest.mark.parametrize("start_connector, end_connector, message", [
    ("u", "u", "'u' of component 'a' is an input, not an output"),
    ("y", "y", "'y' of component 'b' is an output, not an input"),
    ("y", "k", "'k' of component 'b' is a parameter, not an input"),
])
def test_a_link_goes_from_an_output_to_an_input(tmp_path, start_connector, end_connector, message):
    description = ssd(component("a") + component("b"), link(start_connector=start_connector,
                                                             end_connector=end_connector))

    with pytest.raises(AssemblyError, match=message):
        read(tmp_path, description)


def test_a_parameter_can_be_exposed_as_an_input_of_the_container(tmp_path):
    system = '<ssd:Connectors><ssd:Connector name="gain" kind="parameter"><ssc:Real/></ssd:Connector></ssd:Connectors>'
    connection = '<ssd:Connection startConnector="gain" endElement="a" endConnector="k"/>'

    root = read(tmp_path, ssd(component("a"), connection, system=system), fmus=("a",)).root

    assert len(root.input_ports) == 1


def test_an_exposed_output_must_be_an_output(tmp_path):
    system = '<ssd:Connectors><ssd:Connector name="out" kind="output"><ssc:Real/></ssd:Connector></ssd:Connectors>'
    connection = '<ssd:Connection startElement="a" startConnector="u" endConnector="out"/>'

    with pytest.raises(AssemblyError, match="'u' of component 'a' is an input, not an output"):
        read(tmp_path, ssd(component("a"), connection, system=system), fmus=("a",))


def test_an_fmi3_alias_is_a_variable(tmp_path):
    descriptor = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="c" instantiationToken="{c}">
  <CoSimulation modelIdentifier="c"/>
  <ModelVariables>
    <Float64 name="y" valueReference="1" causality="output"><Alias name="y_alias"/></Float64>
  </ModelVariables>
  <ModelStructure><Output valueReference="1"/></ModelStructure>
</fmiModelDescription>
"""
    description = ssd(component("c") + component("b"), link("c", "y_alias", "b", "u"))

    root = read(tmp_path, description, fmus=("b",), files={"resources/c.fmu": _fmu_bytes(tmp_path, descriptor)}).root

    assert [str(item) for item in root.links] == ["model.dir/resources/c.fmu/y_alias -> model.dir/resources/b.fmu/u"]


def test_an_fmu_missing_from_the_archive_is_reported(tmp_path):
    description = ssd(component("a") + component("b"), link())

    with pytest.raises(AssemblyError, match="the FMU 'resources/b.fmu' of component 'b' is not in the SSP archive"):
        read(tmp_path, description, fmus=("a",))


def test_an_unused_connector_of_the_system_is_not_exposed(tmp_path, caplog):
    system = '<ssd:Connectors><ssd:Connector name="spare" kind="input"><ssc:Real/></ssd:Connector></ssd:Connectors>'

    with caplog.at_level(logging.DEBUG, logger="fmu_manipulation_toolbox"):
        root = read(tmp_path, ssd(component("a") + component("b"), link(), system=system)).root

    assert root.input_ports == {}
    assert "Connector 'spare' of system 'root.fmu' is not exposed" in caplog.text


def _fmu_bytes(tmp_path, descriptor: str) -> bytes:
    path = tmp_path / "extra.fmu"
    with zipfile.ZipFile(path, "w") as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
    return path.read_bytes()


# --------------------------------------------------------------------------- #
#                         step 3: parameter values                            #
# --------------------------------------------------------------------------- #
def values(*parameters, **attributes):
    """A parameter binding with inline values: `(name, type, value[, unit])` each."""
    attrs = " ".join(f'{key}="{value}"' for key, value in attributes.items())
    content = "".join(f'<ssv:Parameter name="{p[0]}"><ssv:{p[1]} value="{p[2]}"'
                      f'{f" unit={chr(34)}{p[3]}{chr(34)}" if len(p) > 3 else ""}/></ssv:Parameter>'
                      for p in parameters)
    return (f'<ssd:ParameterBinding {attrs}><ssd:ParameterValues><ssv:ParameterSet version="1.0" name="set">'
            f'<ssv:Parameters>{content}</ssv:Parameters></ssv:ParameterSet></ssd:ParameterValues></ssd:ParameterBinding>')


def bindings(*items):
    return "<ssd:ParameterBindings>" + "".join(items) + "</ssd:ParameterBindings>"


def parameter_set(*parameters):
    return ('<?xml version="1.0" encoding="UTF-8"?><ssv:ParameterSet version="1.0" name="set" '
            'xmlns:ssv="http://ssp-standard.org/SSP1/SystemStructureParameterValues"><ssv:Parameters>'
            + "".join(f'<ssv:Parameter name="{n}"><ssv:{t} value="{v}"/></ssv:Parameter>' for n, t, v in parameters)
            + '</ssv:Parameters></ssv:ParameterSet>')


def starts(root):
    return {(port.fmu_name.rsplit("/", 1)[-1], port.port_name): value for port, value in root.start_values.items()}


def test_inline_values_become_start_values_without_exposing_the_parameters(tmp_path):
    """D3, D4."""
    extra = bindings(values(("k", "Real", "2.5"), ("n", "Integer", "3"), ("b", "Boolean", "true"), ("u", "Real", "1")))
    root = read(tmp_path, ssd(component("a", extra=extra) + component("b"), link())).root

    assert starts(root) == {("a.fmu", "k"): "2.5", ("a.fmu", "n"): "3", ("a.fmu", "b"): "true", ("a.fmu", "u"): "1"}
    assert root.input_ports == {}


def test_an_empty_parameter_set_is_fine(tmp_path):
    """easySSP writes one on every element."""
    root = read(tmp_path, ssd(component("a", extra=bindings(values())) + component("b"), link(),
                              system=bindings(values()))).root

    assert root.start_values == {}


def test_values_from_an_ssv_file_of_the_archive(tmp_path):
    extra = bindings('<ssd:ParameterBinding source="resources/a.ssv"/>')
    files = {"resources/a.ssv": parameter_set(("k", "Real", "4"))}

    root = read(tmp_path, ssd(component("a", extra=extra) + component("b"), link()), files=files).root

    assert starts(root) == {("a.fmu", "k"): "4"}


def test_values_from_an_ssv_file_of_the_fmu(tmp_path):
    """D17: `sourceBase="component"` resolves the source inside the FMU of the component."""
    path = tmp_path / "c.fmu"
    with zipfile.ZipFile(path, "w") as fmu:
        fmu.writestr("modelDescription.xml", DESCRIPTOR.format(name="c"))
        fmu.writestr("resources/defaults.ssv", parameter_set(("k", "Real", "7")))
    extra = bindings('<ssd:ParameterBinding source="resources/defaults.ssv" sourceBase="component"/>')

    root = read(tmp_path, ssd(component("c", extra=extra) + component("b"), link("c")), fmus=("b",),
                files={"resources/c.fmu": path.read_bytes()}).root

    assert starts(root) == {("c.fmu", "k"): "7"}


@pytest.mark.parametrize("binding, message", [
    ('<ssd:ParameterBinding type="application/x-other"/>', "is of type 'application/x-other'"),
    ('<ssd:ParameterBinding source="http://example.com/values.ssv"/>', "must be a relative path inside the SSP"),
    ('<ssd:ParameterBinding source="../values.ssv"/>', "must be a relative path inside the SSP"),
    ('<ssd:ParameterBinding source="resources/missing.ssv"/>', "'resources/missing.ssv' of component 'a' is not in "
                                                               "the SSP archive"),
], ids=["type", "url", "outside", "missing"])
def test_unsupported_parameter_sources_are_refused(tmp_path, binding, message):
    """D17."""
    with pytest.raises(AssemblyError, match=message):
        read(tmp_path, ssd(component("a", extra=bindings(binding)) + component("b"), link()))


def test_a_system_binding_uses_hierarchical_names_and_its_prefix(tmp_path):
    system = bindings(values(("a.k", "Real", "1")), values(("n", "Integer", "5"), prefix="b."))

    root = read(tmp_path, ssd(component("a") + component("b"), link(), system=system)).root

    assert starts(root) == {("a.fmu", "k"): "1", ("b.fmu", "n"): "5"}


def test_a_value_for_a_connector_of_the_system_follows_its_connections(tmp_path):
    """D16: the parameters it is connected to get the value, and stay exposed as the connections say."""
    system = ('<ssd:Connectors><ssd:Connector name="gain" kind="parameter"><ssc:Real/></ssd:Connector>'
              '</ssd:Connectors>' + bindings(values(("gain", "Real", "9"))))
    connections = (link() + '<ssd:Connection startConnector="gain" endElement="a" endConnector="k"/>'
                   '<ssd:Connection startConnector="gain" endElement="b" endConnector="k"/>')

    root = read(tmp_path, ssd(component("a") + component("b"), connections, system=system)).root

    assert starts(root) == {("a.fmu", "k"): "9", ("b.fmu", "k"): "9"}


def test_a_nested_system_is_reached_by_its_hierarchical_name(tmp_path):
    inner = ('<ssd:System name="sub"><ssd:Elements>' + component("c") + '</ssd:Elements></ssd:System>')
    description = ssd(component("a") + component("b") + inner, link(),
                      system=bindings(values(("sub.c.k", "Real", "6"))))

    root = read(tmp_path, description, fmus=("a", "b", "c")).root

    assert starts(root.children["sub.fmu"]) == {("c.fmu", "k"): "6"}


def test_the_priorities_of_the_standard(tmp_path):
    """A later binding overrides an earlier one at the same level; the system overrides its elements."""
    extra = bindings(values(("k", "Real", "1"), ("n", "Integer", "1")), values(("k", "Real", "2")))
    system = bindings(values(("a.n", "Integer", "3")))

    root = read(tmp_path, ssd(component("a", extra=extra) + component("b"), link(), system=system)).root

    assert starts(root) == {("a.fmu", "k"): "2", ("a.fmu", "n"): "3"}


def test_a_name_matching_no_variable_is_a_warning(tmp_path, caplog):
    """D14: the standard ignores it; the warning catches typos."""
    extra = bindings(values(("kk", "Real", "1"), ("k", "Real", "2")))

    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        root = read(tmp_path, ssd(component("a", extra=extra) + component("b"), link())).root

    assert starts(root) == {("a.fmu", "k"): "2"}
    assert "parameter 'kk' of component 'a' matches no variable: it is ignored" in caplog.text


@pytest.mark.parametrize("name, message", [
    ("y", r"the variable \(output, initial 'calculated'\) is computed by the FMU"),
    ("c", "the variable is a constant"),
])
def test_a_variable_that_cannot_be_parameterized_is_refused(tmp_path, name, message):
    """D15."""
    extra = bindings(values((name, "Real", "1")))

    with pytest.raises(AssemblyError, match=message):
        read(tmp_path, ssd(component("a", extra=extra) + component("b"), link()))


def test_a_value_in_another_unit_is_refused(tmp_path):
    """D8, for a parameter value: `u` is in m."""
    extra = bindings(values(("u", "Real", "1", "km")))

    with pytest.raises(AssemblyError, match="the value is in 'km', the variable in 'm'"):
        read(tmp_path, ssd(component("a", extra=extra) + component("b"), link()))


def test_a_binary_value_is_refused(tmp_path):
    extra = bindings(values(("k", "Binary", "00ff")))

    with pytest.raises(AssemblyError, match="binary start values are not supported"):
        read(tmp_path, ssd(component("a", extra=extra) + component("b"), link()))


def test_an_enumeration_value_is_given_by_its_item(tmp_path):
    descriptor = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="e" guid="{e}">
  <CoSimulation modelIdentifier="e"/>
  <TypeDefinitions><SimpleType name="Gear"><Enumeration><Item name="park" value="1"/><Item name="drive" value="4"/>
  </Enumeration></SimpleType></TypeDefinitions>
  <ModelVariables>
    <ScalarVariable name="gear" valueReference="0" causality="parameter" variability="fixed"><Enumeration declaredType="Gear" start="1"/></ScalarVariable>
    <ScalarVariable name="y" valueReference="1" causality="output"><Real/></ScalarVariable>
  </ModelVariables>
  <ModelStructure><Outputs><Unknown index="2"/></Outputs></ModelStructure>
</fmiModelDescription>
"""
    files = {"resources/e.fmu": _fmu_bytes(tmp_path, descriptor)}

    root = read(tmp_path, ssd(component("e", extra=bindings(values(("gear", "Enumeration", "drive")))) +
                              component("b"), link("e")), fmus=("b",), files=files).root
    assert starts(root) == {("e.fmu", "gear"): "4"}

    with pytest.raises(AssemblyError, match="'reverse' is not an item of its enumeration \\(park, drive\\)"):
        read(tmp_path, ssd(component("e", extra=bindings(values(("gear", "Enumeration", "reverse")))) +
                           component("b"), link("e")), fmus=("b",), files=files)


def test_the_values_of_an_ignored_component_are_ignored(tmp_path):
    """D13: without source, the component and everything about it are left out."""
    sourceless = ('<ssd:Component name="z"><ssd:ParameterBindings><ssd:ParameterBinding source="missing.ssv"/>'
                  '</ssd:ParameterBindings></ssd:Component>')

    root = read(tmp_path, ssd(component("a") + component("b") + sourceless, link())).root

    assert root.start_values == {}


# --------------------------------------------------------------------------- #
#                 step 4: the default experiment of the container             #
# --------------------------------------------------------------------------- #
def test_the_default_experiment_gives_the_start_and_stop_times(tmp_path):
    """D9 (revised): SSP has no step size; its start and stop times become those of the container."""
    experiment = '<ssd:DefaultExperiment startTime="1" stopTime="12.5"/>'

    root = read(tmp_path, ssd(component("a") + component("b"), link(), after=experiment)).root

    assert (root.start_time, root.stop_time) == (1.0, 12.5)


def test_without_default_experiment_the_fmus_decide(tmp_path):
    root = read(tmp_path, ssd(component("a") + component("b"), link())).root

    assert (root.start_time, root.stop_time) == (None, None)


def test_an_invalid_time_is_a_warning(tmp_path, caplog):
    experiment = '<ssd:DefaultExperiment startTime="soon" stopTime="3"/>'

    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        root = read(tmp_path, ssd(component("a") + component("b"), link(), after=experiment)).root

    assert (root.start_time, root.stop_time) == (None, 3.0)
    assert "startTime 'soon' of the default experiment is not a number" in caplog.text


# --------------------------------------------------------------------------- #
#                         step 5: validation against the XSD                   #
# --------------------------------------------------------------------------- #
def test_an_invalid_ssd_is_read_with_warnings(tmp_path, caplog):
    """D10: the validation errors are warnings; the parser reads what it understands."""
    description = ssd(component("a", attributes='colour="blue"') + component("b"), link())

    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        root = read(tmp_path, description).root

    assert len(root.links) == 1
    assert "'SystemStructure.ssd' is not valid against the SSP schema" in caplog.text
    assert "colour" in caplog.text


def test_a_valid_ssd_gives_no_validation_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        read(tmp_path, ssd(component("a") + component("b"), link()))

    assert "SSP schema" not in caplog.text


def test_the_validation_warnings_are_bounded(caplog):
    from fmu_manipulation_toolbox.assembly import MAX_SSD_VALIDATION_WARNINGS, validate_ssd
    components = "".join(f'<ssd:Component name="c{i}" source="c.fmu" colour="blue"/>' for i in range(30))

    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        count = validate_ssd(ssd(components).encode(), "many.ssd")

    assert count >= 30  # one per unknown attribute, at least
    assert caplog.text.count("is not valid against the SSP schema") == MAX_SSD_VALIDATION_WARNINGS
    assert f"{count - MAX_SSD_VALIDATION_WARNINGS} more validation error(s)" in caplog.text
