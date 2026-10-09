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
