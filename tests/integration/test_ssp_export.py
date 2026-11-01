"""Writing assemblies as SSP files (plan `ssp_export`, step 1).

The SSP written must be valid against the SSP schema, describe the whole routing (the `auto_*` rules resolved),
and be read back by fmutool into the same container: same `container.txt`, same options, start values, dropped
ports, architecture wires and geometry.
"""
import logging
import shutil
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError, AssemblyNode
from fmu_manipulation_toolbox.ssp import validate_ssd

pytestmark = [pytest.mark.integration]


def _ssd(ssp: Path) -> str:
    with zipfile.ZipFile(ssp) as archive:
        return archive.read("SystemStructure.ssd").decode("utf-8")


def _assert_valid(ssp: Path):
    assert validate_ssd(_ssd(ssp).encode("utf-8"), ssp.name) == 0


def _container_txt(fmu: Path) -> list[str]:
    """`container.txt`, without the GUID line (a new one at each build)."""
    with zipfile.ZipFile(fmu) as archive:
        lines = archive.read("resources/container.txt").decode().splitlines()
    return [line for line in lines if not (len(line) == 36 and line.count("-") == 4)]


def _shape(node: AssemblyNode) -> dict:
    """What a node describes, its FMUs named by their file name (the extraction directory differs)."""
    def name(fmu: str) -> str:
        return Path(fmu).name

    return {
        "fmus": [name(fmu) for fmu in node.fmu_names_list],
        "files": sorted((name(fmu), Path(path).name) for fmu, path in node.fmu_paths.items()),
        "links": sorted(f"{name(l.from_port.fmu_name)}/{l.from_port.port_name} -> "
                        f"{name(l.to_port.fmu_name)}/{l.to_port.port_name}" for l in node.links),
        "inputs": sorted((source, name(port.fmu_name), port.port_name) for port, source in node.input_ports.items()),
        "outputs": sorted((name(port.fmu_name), port.port_name, target) for port, target in node.output_ports.items()),
        "start": sorted((name(port.fmu_name), port.port_name, value) for port, value in node.start_values.items()),
        "drop": sorted((name(port.fmu_name), port.port_name) for port in node.drop_ports),
        "wires": sorted((name(w.start_fmu), name(w.end_fmu), w.orientation, w.description)
                        for w in node.architecture_wires),
        "geometry": sorted((name(fmu), box) for fmu, box in node.fmu_geometry.items()),
        "options": (node.step_size, node.mt, node.profiling, node.sequential, node.ts_multiplier, node.reset_ports),
        "times": (node.start_time, node.stop_time),
        "children": {name(child): _shape(sub) for child, sub in node.children.items()},
    }


# --------------------------------------------------------------------------- #
#                       the routing resolved, the same container              #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/arch")
@pytest.mark.needs_container
def test_a_json_assembly_gives_the_same_container_through_ssp(area_dir):
    """`hierarchical.json` has no explicit link: everything comes from the `auto_*` rules, in a sub-container."""
    Assembly("hierarchical.json").write_ssp("hierarchical.ssp")
    _assert_valid(Path("hierarchical.ssp"))

    Assembly("hierarchical.json").make_fmu(filename="from_json.fmu")
    Assembly("hierarchical.ssp").make_fmu(filename="from_ssp.fmu")

    assert _container_txt(Path("from_ssp.fmu")) == _container_txt(Path("from_json.fmu"))


@pytest.mark.area("containers/arch")
def test_the_auto_rules_are_written_as_connections(area_dir):
    Assembly("hierarchical.json").write_ssp("hierarchical.ssp")
    ssd = _ssd(Path("hierarchical.ssp"))

    assert '<ssd:Connection startElement="level1" startConnector="integrate" endElement="gain" ' \
           'endConnector="integrate" />' in ssd
    assert '<ssd:Connection startElement="gain" startConnector="final" endConnector="final" />' in ssd
    assert 'autoLink="false" autoInput="false" autoOutput="false"' in ssd
    assert 'autoLink="true"' not in ssd


@pytest.mark.area("containers/arch")
@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.windows_only  # the FMUs of containers/arch have Windows binaries only (as test_container.py)
@pytest.mark.slow
def test_the_container_of_the_ssp_simulates_as_the_reference(area_dir):
    from _helpers.simulation import assert_simulation
    Assembly("hierarchical.json").write_ssp("hierarchical.ssp")
    Path("hierarchical.json").unlink()  # the container is built from the SSP file only

    Assembly("hierarchical.ssp").make_fmu()

    assert_simulation(Path("hierarchical.fmu"))


# --------------------------------------------------------------------------- #
#                         SSP -> assembly -> SSP -> assembly                  #
# --------------------------------------------------------------------------- #
def _enriched(ssd: str) -> str:
    """`bouncing.ssp` with an architecture wire, a start value, a dropped port and a default experiment."""
    wire = ('<ssd:Connection startElement="bb_velocity" startConnector="aw.bb_position" endElement="bb_position" '
            'endConnector="aw.bb_velocity" description="Speed&#10;and reset"><ssd:Annotations>'
            '<ssc:Annotation type="fmu_manipulation_toolbox.architecture-wire">'
            '<aw:Wire xmlns:aw="urn:fmu_manipulation_toolbox:architecture-wire:1" formatVersion="1" '
            'orientation="directed"/></ssc:Annotation></ssd:Annotations></ssd:Connection>')
    value = ('<ssv:Parameter name="velocity"><ssv:Real value="2.5"/></ssv:Parameter>')
    ssd = ssd.replace("</ssd:Connections>", wire + "</ssd:Connections>")
    ssd = ssd.replace('<ssv:Parameters/>\n                            </ssv:ParameterSet>\n                        '
                      '</ssd:ParameterValues>\n                    </ssd:ParameterBinding>\n                '
                      '</ssd:ParameterBindings>\n            </ssd:Component>\n        </ssd:Elements>',
                      f'<ssv:Parameters>{value}</ssv:Parameters>\n                            </ssv:ParameterSet>\n'
                      f'                        </ssd:ParameterValues>\n                    </ssd:ParameterBinding>\n'
                      f'                </ssd:ParameterBindings>\n            </ssd:Component>\n        </ssd:Elements>')
    return ssd.replace("</ssd:System>", '</ssd:System><ssd:DefaultExperiment startTime="0" stopTime="4"/>', 1)


@pytest.mark.area("containers/ssp")
def test_an_ssp_file_is_read_back_without_loss(area_dir):
    # Named as the files written: `read_ssp` names the root system after its file.
    with zipfile.ZipFile("bouncing.ssp") as source, zipfile.ZipFile("model.ssp", "w") as target:
        for member in source.namelist():
            content = source.read(member)
            if member == "SystemStructure.ssd":
                content = _enriched(content.decode()).encode()
            target.writestr(member, content)
    first = Assembly("model.ssp")
    assert first.root.start_values  # the enrichment took effect
    first.root.add_drop_port(first.root.fmu_names_list[1], "position1")
    first.root.step_size, first.root.mt = 0.01, True

    # An SSP file is read from its directory (its FMUs are extracted next to it).
    Path("one").mkdir()
    first.write_ssp("one/model.ssp")
    second = Assembly("model.ssp", fmu_directory=Path("one"))
    Path("two").mkdir()
    second.write_ssp(Path("two/model.ssp").resolve())  # relative paths are relative to `fmu_directory`

    assert _shape(second.root) == _shape(first.root)
    # Written again from what was read back: the same file.
    assert _ssd(Path("two/model.ssp")) == _ssd(Path("one/model.ssp"))
    _assert_valid(Path("one/model.ssp"))


@pytest.mark.area("containers/ssp")
def test_the_options_of_the_file_prevail_over_the_command_line(area_dir, caplog):
    """E3: the annotation wins, with a message."""
    first = Assembly("bouncing.ssp")
    first.root.step_size = 0.02
    first.write_ssp("options.ssp")

    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        second = Assembly("options.ssp", default_step_size=0.5, default_mt=True)

    assert (second.root.step_size, second.root.mt) == (0.02, False)
    # The system keeps the name of the assembly it was written from.
    assert "options of 'bouncing.fmu' read from the SSP file (they prevail over the command line)" in caplog.text


@pytest.mark.area("containers/ssp")
def test_an_ssp_file_without_options_annotation_takes_the_command_line(area_dir):
    assert Assembly("bouncing.ssp", default_step_size=0.5).root.step_size == 0.5


# --------------------------------------------------------------------------- #
#                           files, versions, units                            #
# --------------------------------------------------------------------------- #
def _bouncing_node(data_dir, directory: Path) -> Assembly:
    """Two instances of one FMU, linked by hand, in an assembly built by the API."""
    shutil.copy(data_dir / "fmi3" / "bouncing_ball" / "bb_velocity.fmu", directory / "bb_velocity.fmu")
    shutil.copy(data_dir / "fmi3" / "bouncing_ball" / "bb_position.fmu", directory / "bb_position.fmu")
    assembly = Assembly(fmu_directory=directory)
    node = AssemblyNode("pair.fmu", auto_link=False, auto_input=False, auto_output=False)
    node.add_fmu("bb_velocity.fmu")
    node.add_fmu("bb_position.fmu")
    node.add_fmu("bb_position-1.fmu", "bb_position.fmu")
    node.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    node.add_link("bb_velocity.fmu", "velocity", "bb_position-1.fmu", "velocity")
    node.add_output("bb_position-1.fmu", "position1", "height")
    assembly.root = node
    return assembly


def test_instances_of_one_fmu_share_one_file(data_dir, tmp_path):
    """E6."""
    _bouncing_node(data_dir, tmp_path).write_ssp(tmp_path / "pair.ssp")

    with zipfile.ZipFile(tmp_path / "pair.ssp") as archive:
        members = sorted(archive.namelist())
    ssd = _ssd(tmp_path / "pair.ssp")
    assert members == ["SystemStructure.ssd", "resources/bb_position.fmu", "resources/bb_velocity.fmu"]
    assert '<ssd:Component name="bb_position-1" type="application/x-fmu-sharedlibrary" ' \
           'source="resources/bb_position.fmu">' in ssd
    _assert_valid(tmp_path / "pair.ssp")


def test_the_fmi3_types_in_ssp_2_and_ssp_1(data_dir, tmp_path):
    """E4: SSP 2.0 by default, the FMI 3.0 types exact; SSP 1.0 writes them as FMI 2.0 types."""
    assembly = _bouncing_node(data_dir, tmp_path)
    assembly.write_ssp(tmp_path / "v2.ssp")
    assembly.write_ssp(tmp_path / "v1.ssp", ssp_version="1.0")

    v2, v1 = _ssd(tmp_path / "v2.ssp"), _ssd(tmp_path / "v1.ssp")
    assert 'version="2.0"' in v2 and "<ssc:Float64 />" in v2
    assert 'version="1.0"' in v1 and "<ssc:Float64" not in v1 and "<ssc:Real />" in v1
    _assert_valid(tmp_path / "v2.ssp")
    _assert_valid(tmp_path / "v1.ssp")
    assert len(Assembly(tmp_path / "v1.ssp", fmu_directory=tmp_path).root.links) == 2


def test_connected_ports_of_different_units_suppress_the_conversion(tmp_path):
    """E10: the container does not convert; the file says so, and is read back."""
    def fmu(name, causality, unit):
        descriptor = f"""<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="{name}" guid="{{{name}}}">
  <CoSimulation modelIdentifier="{name}"/>
  <UnitDefinitions><Unit name="{unit}"/></UnitDefinitions>
  <ModelVariables>
    <ScalarVariable name="x" valueReference="0" causality="{causality}"><Real unit="{unit}"{' start="0"' if causality == 'input' else ''}/></ScalarVariable>
  </ModelVariables>
  <ModelStructure>{'<Outputs><Unknown index="1"/></Outputs>' if causality == 'output' else ''}</ModelStructure>
</fmiModelDescription>
"""
        with zipfile.ZipFile(tmp_path / f"{name}.fmu", "w") as archive:
            archive.writestr("modelDescription.xml", descriptor)

    fmu("source", "output", "m")
    fmu("sink", "input", "km")
    assembly = Assembly(fmu_directory=tmp_path)
    assembly.root = AssemblyNode("units.fmu", auto_input=False, auto_output=False, auto_link=False)
    assembly.root.add_fmu("source.fmu")
    assembly.root.add_fmu("sink.fmu")
    assembly.root.add_link("source.fmu", "x", "sink.fmu", "x")

    assembly.write_ssp(tmp_path / "units.ssp")

    ssd = _ssd(tmp_path / "units.ssp")
    assert 'suppressUnitConversion="true"' in ssd and '<ssc:Real unit="km" />' in ssd
    assert len(Assembly(tmp_path / "units.ssp", fmu_directory=tmp_path).root.links) == 1


@pytest.mark.parametrize("version", ["3.0", "1.1"])
def test_an_unknown_ssp_version_is_refused(data_dir, tmp_path, version):
    with pytest.raises(AssemblyError, match=f"SSP version '{version}' is not supported"):
        _bouncing_node(data_dir, tmp_path).write_ssp(tmp_path / "x.ssp", ssp_version=version)


def test_an_empty_assembly_cannot_be_written(tmp_path):
    with pytest.raises(AssemblyError, match="The assembly is empty"):
        Assembly(fmu_directory=tmp_path).write_ssp(tmp_path / "x.ssp")
