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


def _variant(ssp: Path, destination: Path, transform) -> Path:
    """Copy `ssp` to `destination`, with `transform` applied to SystemStructure.ssd."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ssp) as source, zipfile.ZipFile(destination, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "SystemStructure.ssd":
                content = transform(content.decode("utf-8")).encode("utf-8")
            target.writestr(name, content)
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
    _variant(area_dir / "bouncing.ssp", area_dir / "two.ssp", _second_ball)
    assembly = Assembly("two.ssp")
    root = assembly.root

    assert root.fmu_names_list == ["two.dir/bb_velocity.fmu", "two.dir/bb_position.fmu",
                                   "two.dir/bb_velocity-1.fmu", "two.dir/bb_position-1.fmu"]
    assert root.fmu_paths == {"two.dir/bb_velocity-1.fmu": "two.dir/bb_velocity.fmu",
                              "two.dir/bb_position-1.fmu": "two.dir/bb_position.fmu"}
    assert [str(link) for link in root.links[2:]] == [
        "two.dir/bb_velocity-1.fmu/velocity -> two.dir/bb_position-1.fmu/velocity",
        "two.dir/bb_position-1.fmu/is_ground -> two.dir/bb_velocity-1.fmu/reset"]

    assembly.make_fmu()
    with zipfile.ZipFile("two.fmu") as container:
        declarations = container.read("resources/container.txt").decode().splitlines()
    assert [line.split()[0] for line in declarations if ".fmu " in line and not line.startswith("#")] == \
           ["bb_velocity.fmu", "bb_position.fmu", "bb_velocity-1.fmu", "bb_position-1.fmu"]
