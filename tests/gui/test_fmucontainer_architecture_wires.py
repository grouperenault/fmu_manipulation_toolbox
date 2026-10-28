"""Architecture wires of an SSP file in the Container Builder GUI.

An architecture wire (connection annotated `fmu_manipulation_toolbox.architecture-wire`) becomes the wire of its pair
of nodes: drawn dashed with the arrowheads of its orientation while the wire has no link, its description shown in
the wire details. It is a hint only: it produces no link when the assembly is saved.
"""
import json
import shutil
import zipfile

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtGui import QImage, QPainter, QTextDocument
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"GUI dependencies not available: {exc}", allow_module_level=True)

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


def _wire(start: str, end: str, orientation: str, description: str = "") -> str:
    return (f'<ssd:Connection startElement="{start}" startConnector="aw.{end}" endElement="{end}" '
            f'endConnector="aw.{start}" description="{description}">'
            f'<ssd:Annotations><ssc:Annotation type="fmu_manipulation_toolbox.architecture-wire">'
            f'<aw:Wire xmlns:aw="urn:fmu_manipulation_toolbox:architecture-wire:1" formatVersion="1" '
            f'orientation="{orientation}"/></ssc:Annotation></ssd:Annotations></ssd:Connection>')


def _ssp(data_dir, tmp_path, wire: str, keep_links: bool) -> str:
    """`bouncing.ssp` with *wire* added, and its two links removed unless *keep_links*."""
    destination = tmp_path / "bouncing.ssp"
    with zipfile.ZipFile(data_dir / "containers" / "ssp" / "bouncing.ssp") as source, \
            zipfile.ZipFile(destination, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "SystemStructure.ssd":
                ssd = content.decode("utf-8")
                start, end = ssd.index("<ssd:Connections>"), ssd.index("</ssd:Connections>")
                links = ssd[start + len("<ssd:Connections>"):end] if keep_links else ""
                ssd = ssd[:start] + "<ssd:Connections>" + links + wire + ssd[end:]
                content = ssd.encode("utf-8")
            target.writestr(name, content)
    return str(destination)


def _only_wire(window):
    wires = window._graph.scene.wires()
    assert len(wires) == 1
    return wires[0]


@pytest.mark.parametrize("start, end, orientation, direction", [
    ("bb_velocity", "bb_position", "directed", "velocity_to_position"),
    ("bb_position", "bb_velocity", "directed", "position_to_velocity"),
    ("bb_velocity", "bb_position", "bidirectional", "both"),
    ("bb_velocity", "bb_position", "undirected", "none"),
])
def test_architecture_wire_without_link(window, data_dir, tmp_path, start, end, orientation, direction):
    window.import_assembly_file(_ssp(data_dir, tmp_path, _wire(start, end, orientation), keep_links=False))
    wire = _only_wire(window)

    assert wire.mappings == [] and wire.is_architecture_only()
    if direction in ("velocity_to_position", "position_to_velocity"):
        source = "bb_velocity.fmu" if direction == "velocity_to_position" else "bb_position.fmu"
        expected = "a_to_b" if wire.node_a.name == source else "b_to_a"
    else:
        expected = direction
    assert wire.architecture_direction == expected

    # The dashed wire and its arrowheads are drawn without error.
    image = QImage(400, 300, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    window._graph.scene.render(painter)
    painter.end()


def test_architecture_wire_on_a_linked_pair(window, data_dir, tmp_path):
    window.import_assembly_file(_ssp(data_dir, tmp_path, _wire("bb_velocity", "bb_position", "directed"),
                                     keep_links=True))
    wire = _only_wire(window)

    assert len(wire.mappings) == 2
    assert wire.architecture_direction is not None and not wire.is_architecture_only()


def _shown_document(label) -> QTextDocument:
    document = QTextDocument()
    document.setHtml(label.text())
    return document


def test_details_show_the_architecture_hint(window, data_dir, tmp_path):
    window.import_assembly_file(_ssp(data_dir, tmp_path,
                                     _wire("bb_velocity", "bb_position", "bidirectional", "Speed&#10;and *reset*"),
                                     keep_links=False))
    detail = window._tree.wire_detail
    detail.set_wire(_only_wire(window))

    assert not detail._architecture_label.isHidden()
    # Markdown: the single new line is a soft break.
    assert _shown_document(detail._architecture_label).toPlainText() == "Architecture wire: A ↔ B\nSpeed and reset"


def test_details_show_headings_at_the_panel_size(window, data_dir, tmp_path):
    window.import_assembly_file(_ssp(data_dir, tmp_path,
                                     _wire("bb_velocity", "bb_position", "directed", "# Coupling&#10;&#10;Speed"),
                                     keep_links=False))
    detail = window._tree.wire_detail
    detail.set_wire(_only_wire(window))

    fonts = _fragment_fonts(_shown_document(detail._architecture_label))
    assert fonts["Coupling"].pointSizeF() == pytest.approx(fonts["Speed"].pointSizeF())
    assert fonts["Coupling"].bold()


def _fragment_fonts(document) -> dict:
    """Font of each text fragment of *document*, by text."""
    fonts = {}
    block = document.begin()
    while block.isValid():
        fragments = block.begin()
        while not fragments.atEnd():
            fragment = fragments.fragment()
            fonts[fragment.text()] = fragment.charFormat().font()
            fragments += 1
        block = block.next()
    return fonts


def test_details_hide_the_architecture_hint_of_a_regular_wire(window, data_dir, tmp_path):
    shutil.copy(data_dir / "containers" / "ssp" / "bouncing.ssp", tmp_path / "bouncing.ssp")
    window.import_assembly_file(str(tmp_path / "bouncing.ssp"))
    detail = window._tree.wire_detail
    detail.set_wire(_only_wire(window))

    assert detail._architecture_label.isHidden()


def test_architecture_wire_adds_no_link_when_saved(window, data_dir, tmp_path):
    window.import_assembly_file(_ssp(data_dir, tmp_path, _wire("bb_velocity", "bb_position", "directed"),
                                     keep_links=False))
    window.save_as_json(tmp_path / "saved.json")

    saved = json.loads((tmp_path / "saved.json").read_text())
    assert "link" not in saved
