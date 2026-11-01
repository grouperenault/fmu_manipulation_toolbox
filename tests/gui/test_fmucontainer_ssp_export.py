"""Export as SSP in the Container Builder GUI (plan `ssp_export`, step 3).

The positions of the nodes become the geometry of the components, the architecture wires are kept, and the file
is read back with the same routing.
"""
import shutil
import zipfile

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"GUI dependencies not available: {exc}", allow_module_level=True)

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.ssp import validate_ssd

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qapp):
    window = MainWindow()
    try:
        yield window
    finally:
        window._dirty = False
        window._graph.scene.blockSignals(True)
        window.close()
        window.deleteLater()
        QApplication.processEvents()


WIRE = ('<ssd:Connection startElement="bb_position" startConnector="aw.bb_velocity" endElement="bb_velocity" '
        'endConnector="aw.bb_position" description="Bounce"><ssd:Annotations>'
        '<ssc:Annotation type="fmu_manipulation_toolbox.architecture-wire">'
        '<aw:Wire xmlns:aw="urn:fmu_manipulation_toolbox:architecture-wire:1" formatVersion="1" '
        'orientation="directed"/></ssc:Annotation></ssd:Annotations></ssd:Connection>')


def _ssp_with_wire(data_dir, directory):
    """`bouncing.ssp` with a directed architecture wire from bb_position to bb_velocity, its links kept."""
    destination = directory / "bouncing.ssp"
    with zipfile.ZipFile(data_dir / "containers" / "ssp" / "bouncing.ssp") as source, \
            zipfile.ZipFile(destination, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "SystemStructure.ssd":
                content = content.decode("utf-8").replace("</ssd:Connections>", WIRE + "</ssd:Connections>").encode()
            target.writestr(name, content)
    return destination


def _nodes(window) -> dict:
    return {node.name: node for node in window._graph.scene.fmu_nodes()}


def _read(path):
    """The root of the SSP file *path*, read from its own directory."""
    return Assembly(path.name, fmu_directory=path.parent).root


def _short(link: str) -> str:
    """A link with the FMUs named by their file name (the extraction directory differs)."""
    start, end = link.split(" -> ")
    return " -> ".join("/".join(side.split("/")[-2:]) for side in (start, end))


def test_the_export_button_is_next_to_the_json_one(window):
    assert window._export_ssp_button.text() == "Export as SSP"


def test_an_imported_ssp_is_exported_with_its_wire_and_geometry(window, data_dir, tmp_path):
    window.import_assembly_file(str(_ssp_with_wire(data_dir, tmp_path)))
    (tmp_path / "out").mkdir()
    exported = tmp_path / "out" / "bouncing.ssp"

    window.save_as_ssp(str(exported))

    with zipfile.ZipFile(exported) as archive:
        assert validate_ssd(archive.read("SystemStructure.ssd"), exported.name) == 0
    root = _read(exported)
    assert sorted(_short(str(link)) for link in root.links) == [
        "bb_position.fmu/is_ground -> bb_velocity.fmu/reset", "bb_velocity.fmu/velocity -> bb_position.fmu/velocity"]
    assert [(w.start_fmu.rsplit("/", 1)[-1], w.end_fmu.rsplit("/", 1)[-1], w.orientation, w.description)
            for w in root.architecture_wires] == [("bb_position.fmu", "bb_velocity.fmu", "directed", "Bounce")]
    geometry = {fmu.rsplit("/", 1)[-1]: box for fmu, box in root.fmu_geometry.items()}
    assert set(geometry) == {"bb_velocity.fmu", "bb_position.fmu"}
    # bb_velocity is on the left of bb_position, as on the canvas.
    assert geometry["bb_velocity.fmu"][2] <= geometry["bb_position.fmu"][0]


def test_a_moved_node_is_exported_where_it_is(window, data_dir, tmp_path):
    window.import_assembly_file(str(_ssp_with_wire(data_dir, tmp_path)))
    nodes = _nodes(window)
    velocity, position = nodes["bb_velocity.fmu"], nodes["bb_position.fmu"]
    # Put bb_velocity well below bb_position (scene y downwards).
    velocity.setPos(position.pos().x(), position.pos().y() + 10 * velocity.rect().height())
    (tmp_path / "out").mkdir()
    exported = tmp_path / "out" / "bouncing.ssp"

    window.save_as_ssp(str(exported))

    geometry = {fmu.rsplit("/", 1)[-1]: box for fmu, box in _read(exported).fmu_geometry.items()}
    # SSP coordinates: y upwards, so bb_velocity is now under bb_position.
    assert geometry["bb_velocity.fmu"][3] < geometry["bb_position.fmu"][1]
    width = velocity.rect().width()
    assert geometry["bb_velocity.fmu"][2] - geometry["bb_velocity.fmu"][0] == pytest.approx(width)


def test_the_exported_file_opens_in_the_builder(window, data_dir, tmp_path):
    shutil.copy(data_dir / "containers" / "ssp" / "bouncing.ssp", tmp_path / "bouncing.ssp")
    window.import_assembly_file(str(tmp_path / "bouncing.ssp"))
    (tmp_path / "out").mkdir()
    exported = tmp_path / "out" / "bouncing.ssp"
    window.save_as_ssp(str(exported))

    window.import_assembly_file(str(exported))

    assert set(_nodes(window)) == {"bb_velocity.fmu", "bb_position.fmu"}
    assert sum(len(wire.mappings) for wire in window._graph.scene.wires()) == 2
