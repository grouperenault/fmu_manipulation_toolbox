"""Reading of SSP archives: the SSD parser recognizes elements by namespace.

The former expat-based `SSDParser` matched the literal prefix `ssd:`. A valid
SSD that declared the same namespace with another prefix, or as the default
namespace, produced no system at all and `read_ssp` failed with an
`AttributeError`. These tests build such variants of `bouncing.ssp` (written by
easySSP) and expect exactly the same assembly.
"""
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError

from _helpers.assertions import assert_identical_files

pytestmark = [pytest.mark.integration, pytest.mark.area("containers/ssp")]


def _variant(ssp: Path, destination: Path, transform, renames: dict[str, str] | None = None) -> Path:
    """Copy `ssp` to `destination`, with `transform` applied to SystemStructure.ssd and the entries of `renames`
    stored under their new name."""
    renames = renames or {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ssp) as source, zipfile.ZipFile(destination, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "SystemStructure.ssd":
                content = transform(content.decode("utf-8")).encode("utf-8")
            target.writestr(renames.get(name, name), content)
    return destination


@pytest.mark.parametrize("transform", [
    lambda ssd: ssd.replace("ssd:", "s:").replace('xmlns:ssd="', 'xmlns:s="'),
    lambda ssd: ssd.replace("<ssd:", "<").replace("</ssd:", "</").replace('xmlns:ssd="', 'xmlns="'),
], ids=["other-prefix", "default-namespace"])
def test_ssd_prefix_does_not_matter(area_dir, monkeypatch, transform):
    # Same file name (it names the container), in a sub-directory.
    _variant(area_dir / "bouncing.ssp", area_dir / "variant" / "bouncing.ssp", transform)
    monkeypatch.chdir(area_dir / "variant")
    Assembly("bouncing.ssp").make_fmu(dump_json=True)
    assert_identical_files(area_dir / "REF-bouncing-dump.json", "bouncing-dump.json")


@pytest.mark.parametrize("transform, message", [
    (lambda ssd: ssd.replace("http://ssp-standard.org/SSP1/SystemStructureDescription", "urn:other"),
     "is not an SSP 1.0 system structure description"),
    (lambda ssd: ssd.replace('startElement="bb_position"', 'startElement="nowhere"', 1),
     "reference to an unknown element"),
    (lambda ssd: ssd.replace("<ssd:Elements>", "<ssd:Elements><<", 1), "is not well-formed"),
], ids=["wrong-namespace", "unknown-element", "not-well-formed"])
def test_invalid_ssd_raises_assembly_error(area_dir, transform, message):
    _variant(area_dir / "bouncing.ssp", area_dir / "invalid.ssp", transform)
    with pytest.raises(AssemblyError, match=message):
        Assembly("invalid.ssp")


def _second_ball(ssd: str) -> str:
    """Duplicate both components (same sources, other names) and their connections."""
    start, end = ssd.index("<ssd:Component "), ssd.index("</ssd:Elements>")
    components = ssd[start:end].replace('name="bb_velocity"', 'name="bb_velocity2"') \
                               .replace('name="bb_position"', 'name="bb_position2"')
    ssd = ssd[:end] + components + ssd[end:]
    start, end = ssd.index("<ssd:Connection "), ssd.index("</ssd:Connections>")
    connections = ssd[start:end].replace('Element="bb_velocity"', 'Element="bb_velocity2"') \
                                .replace('Element="bb_position"', 'Element="bb_position2"')
    return ssd[:end] + connections + ssd[end:]


def test_components_sharing_a_source_are_instances(area_dir):
    # Each component is embedded under its own name, next to its source file.
    _variant(area_dir / "bouncing.ssp", area_dir / "two.ssp", _second_ball)
    assembly = Assembly("two.ssp")
    root = assembly.root

    assert root.fmu_names_list == ["two.dir/resources/bb_velocity.fmu", "two.dir/resources/bb_position.fmu",
                                   "two.dir/resources/bb_velocity2.fmu", "two.dir/resources/bb_position2.fmu"]
    assert root.fmu_paths == {"two.dir/resources/bb_velocity2.fmu": "two.dir/resources/bb_velocity.fmu",
                              "two.dir/resources/bb_position2.fmu": "two.dir/resources/bb_position.fmu"}
    assert [str(link) for link in root.links[2:]] == [
        "two.dir/resources/bb_velocity2.fmu/velocity -> two.dir/resources/bb_position2.fmu/velocity",
        "two.dir/resources/bb_position2.fmu/is_ground -> two.dir/resources/bb_velocity2.fmu/reset"]

    assembly.make_fmu()
    with zipfile.ZipFile("two.fmu") as container:
        declarations = container.read("resources/container.txt").decode().splitlines()
    assert [line.split()[0] for line in declarations if ".fmu " in line and not line.startswith("#")] == \
           ["bb_velocity.fmu", "bb_position.fmu", "bb_velocity2.fmu", "bb_position2.fmu"]


# --------------------------------------------------------------------------- #
#        architecture wires, component paths, components without source       #
# --------------------------------------------------------------------------- #
def _architecture_wire(orientation: str, annotation_type="fmu_manipulation_toolbox.architecture-wire"):
    """Transform adding a wire between both balls, annotated with `annotation_type`."""
    wire = (f'<ssd:Connection startElement="bb_velocity" startConnector="aw.bb_position" '
            f'endElement="bb_position" endConnector="aw.bb_velocity" description="Speed&#10;and reset">'
            f'<ssd:Annotations><ssc:Annotation type="{annotation_type}">'
            f'<aw:Wire xmlns:aw="urn:fmu_manipulation_toolbox:architecture-wire:1" formatVersion="1" '
            f'orientation="{orientation}"/></ssc:Annotation></ssd:Annotations></ssd:Connection>')
    return lambda ssd: ssd.replace("</ssd:Connections>", wire + "</ssd:Connections>")


def _bouncing_variant(area_dir: Path, monkeypatch, transform, renames: dict[str, str] | None = None):
    """Variant of `bouncing.ssp` with the same file name (it names the container), in a sub-directory made the
    working directory."""
    _variant(area_dir / "bouncing.ssp", area_dir / "variant" / "bouncing.ssp", transform, renames)
    monkeypatch.chdir(area_dir / "variant")


@pytest.mark.parametrize("orientation", ["directed", "bidirectional", "undirected"])
def test_architecture_wire_is_not_a_link(area_dir, monkeypatch, orientation):
    _bouncing_variant(area_dir, monkeypatch, _architecture_wire(orientation))
    assembly = Assembly("bouncing.ssp")
    root = assembly.root

    assert len(root.links) == 2
    assert [(wire.start_fmu, wire.end_fmu, wire.orientation, wire.description)
            for wire in root.architecture_wires] == [
        ("bouncing.dir/resources/bb_velocity.fmu", "bouncing.dir/resources/bb_position.fmu", orientation,
         "Speed\nand reset")]

    # The wire takes no part in the container and is not written in the JSON description.
    assembly.make_fmu(dump_json=True)
    assert_identical_files(area_dir / "REF-bouncing-dump.json", "bouncing-dump.json")


def test_architecture_wire_with_unknown_orientation_is_undirected(area_dir, monkeypatch, caplog):
    _bouncing_variant(area_dir, monkeypatch, _architecture_wire("sideways"))
    root = Assembly("bouncing.ssp").root

    assert [wire.orientation for wire in root.architecture_wires] == ["undirected"]
    assert "unknown orientation 'sideways'" in caplog.text


def test_other_annotation_keeps_a_link(area_dir, monkeypatch):
    # Only the annotation type makes an architecture wire: the same content under another type is a link.
    _bouncing_variant(area_dir, monkeypatch, _architecture_wire("directed", annotation_type="com.example.other"))
    root = Assembly("bouncing.ssp").root

    assert root.architecture_wires == []
    assert str(root.links[-1]) == ("bouncing.dir/resources/bb_velocity.fmu/aw.bb_position -> "
                                   "bouncing.dir/resources/bb_position.fmu/aw.bb_velocity")


def test_sources_with_the_same_file_name(area_dir, monkeypatch):
    # Two FMUs named model.fmu in different directories: both are extracted, none overwrites the other.
    def transform(ssd: str) -> str:
        return ssd.replace('source="resources/bb_velocity.fmu"', 'source="resources/velocity/model.fmu"') \
                  .replace('source="resources/bb_position.fmu"', 'source="resources/position/model.fmu"')

    _bouncing_variant(area_dir, monkeypatch, transform,
                      renames={"resources/bb_velocity.fmu": "resources/velocity/model.fmu",
                               "resources/bb_position.fmu": "resources/position/model.fmu"})
    assembly = Assembly("bouncing.ssp")
    root = assembly.root

    assert root.fmu_names_list == ["bouncing.dir/resources/velocity/bb_velocity.fmu",
                                   "bouncing.dir/resources/position/bb_position.fmu"]
    assert root.fmu_paths == {"bouncing.dir/resources/velocity/bb_velocity.fmu":
                              "bouncing.dir/resources/velocity/model.fmu",
                              "bouncing.dir/resources/position/bb_position.fmu":
                              "bouncing.dir/resources/position/model.fmu"}
    assert Path("bouncing.dir/resources/velocity/model.fmu").read_bytes() != \
           Path("bouncing.dir/resources/position/model.fmu").read_bytes()

    assembly.make_fmu()
    with zipfile.ZipFile("bouncing.fmu") as container:
        declarations = container.read("resources/container.txt").decode().splitlines()
    assert [line.split()[0] for line in declarations if ".fmu " in line and not line.startswith("#")] == \
           ["bb_velocity.fmu", "bb_position.fmu"]


def test_component_without_source_is_ignored(area_dir, monkeypatch, caplog):
    def transform(ssd: str) -> str:
        return _architecture_wire("directed")(ssd.replace('source="resources/bb_position.fmu" ', ""))

    _bouncing_variant(area_dir, monkeypatch, transform)
    root = Assembly("bouncing.ssp").root

    assert root.fmu_names_list == ["bouncing.dir/resources/bb_velocity.fmu"]
    assert root.links == []
    assert root.architecture_wires == []
    assert "Component 'bb_position' has no source FMU" in caplog.text


@pytest.mark.parametrize("source", ["../bb_velocity.fmu", "/tmp/bb_velocity.fmu"])
def test_source_outside_the_archive_raises_assembly_error(area_dir, source):
    _variant(area_dir / "bouncing.ssp", area_dir / "invalid.ssp",
             lambda ssd: ssd.replace('source="resources/bb_velocity.fmu"', f'source="{source}"'))
    with pytest.raises(AssemblyError, match="must be a relative path inside the SSP archive"):
        Assembly("invalid.ssp")
