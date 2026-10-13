"""The link assistant opened from the Wire Details panel of the Container Builder, on real FMUs."""
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow
    from fmu_manipulation_toolbox.gui.fmucontainer.details.link_assistant import (
        _CriterionEditor, StagedLink, A_TO_B)
    from fmu_manipulation_toolbox.gui.fmucontainer.details.link_matching import (
        AffixRule, ALREADY_FED, LOSSY, SIZE_MISMATCH)
    from fmu_manipulation_toolbox.gui.fmucontainer.details.wire_detail import wire_sides
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"GUI dependencies not available: {exc}", allow_module_level=True)

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def fresh_session():
    _CriterionEditor._session_rules = None
    _CriterionEditor._session_ignore_case = True


@pytest.fixture
def window(qapp):
    window = MainWindow()
    try:
        yield window
    finally:
        # See test_fmucontainer_instances.py: no "save your changes?" question, no access to deleted items.
        assistant = window._tree.wire_detail._assistant
        if assistant is not None:
            assistant._staged = []
            assistant.close()
        window._dirty = False
        window._graph.scene.blockSignals(True)
        window.close()
        window.deleteLater()
        QApplication.processEvents()


@pytest.fixture
def ball(data_dir):
    return data_dir / "containers" / "bouncing_ball"


def _set_mappings(window, wire, mappings):
    """Set the mappings of *wire* and reload the Wire Details panel, as the MCP bridge does: otherwise selecting
    another wire writes the stale table of the panel back into it."""
    wire.mappings = mappings
    details = window._tree.wire_detail
    if details._wire is wire:
        details._load_from_wire()


def _open(window, wire):
    """Show *wire* in the Wire Details panel and open the assistant on it."""
    details = window._tree.wire_detail
    details.set_wire(wire)
    details._on_assistant()
    dialog = details._assistant
    dialog._on_run()
    return details, dialog


def test_auto_connect_is_replaced_by_the_assistant(window):
    texts = {button.text() for button in window._tree.wire_detail.findChildren(QPushButton)}
    assert "Link Assistant" in texts and "Auto-Connect" not in texts


def test_same_name_then_apply_updates_the_wire(window, ball):
    scene = window._graph.scene
    position, velocity = scene.add_node(ball / "bb_position.fmu"), scene.add_node(ball / "bb_velocity.fmu")
    wire = scene.add_wire(velocity, position)
    details, dialog = _open(window, wire)

    assert dialog._criterion.rule().kind == "Same name"
    suggestions = dialog._suggestions_model.suggestions
    assert [(s.output.name, s.input.name) for s in suggestions] == [("velocity", "velocity")]
    dialog._on_stage_checked()
    dialog._on_apply()

    assert wire.mappings == [("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")]
    assert details._tab_ab.mappings() == wire.mappings      # the table of the panel is reloaded
    assert window._dirty


def test_inputs_fed_elsewhere_are_errors(window, ball):
    scene = window._graph.scene
    position = scene.add_node(ball / "bb_position.fmu")
    velocity, velocity_1 = scene.add_node(ball / "bb_velocity.fmu"), scene.add_node(ball / "bb_velocity.fmu")
    first = scene.add_wire(velocity, position)
    _set_mappings(window, first, [(velocity.name, "velocity", position.name, "velocity")])
    second = scene.add_wire(velocity_1, position)

    assert "velocity" in wire_sides(second)[1].fed
    _, dialog = _open(window, second)
    assert [s.status.codes for s in dialog._suggestions_model.suggestions] == [(ALREADY_FED,)]


def test_exposed_input_is_fed(window, ball):
    scene = window._graph.scene
    position, velocity = scene.add_node(ball / "bb_position.fmu"), scene.add_node(ball / "bb_velocity.fmu")
    position.user_exposed_inputs["velocity"] = True
    wire = scene.add_wire(velocity, position)
    side_a, side_b = wire_sides(wire)
    assert side_b.fed == {"velocity"}


def test_array_sizes(window, data_dir):
    scene = window._graph.scene
    arrays = scene.add_node(data_dir / "array" / "scalar2array-3.fmu")       # FMI 3 arrays
    aggregates = scene.add_node(data_dir / "array" / "array2scalar-2.fmu")   # FMI 2 aggregates
    wire = scene.add_wire(arrays, aggregates)
    side_a, side_b = wire_sides(wire)
    sizes_a = {port.name: port.size for port in side_a.ports if port.causality == "output"}
    sizes_b = {port.name: port.size for port in side_b.ports if port.name in ("In1", "In2", "In4")}
    assert (sizes_a["Out1"], sizes_a["Out2"], sizes_a["Out4"]) == (2, 3, 6)
    assert sizes_b == {"In1": 2, "In2": 3, "In4": 6}

    _, dialog = _open(window, wire)
    dialog._criterion.set_kind(AffixRule)
    dialog._criterion.affix_fields["from_prefix"].setText("Out")
    dialog._criterion.affix_fields["to_prefix"].setText("In")
    dialog._on_run()
    found = {(s.output.name, s.input.name): s.status.codes for s in dialog._suggestions_model.suggestions}
    assert found[("Out1", "In1")] == () and found[("Out2", "In2")] == ()
    assert found[("Out4", "In4")] == (LOSSY,)                    # Int32 → Real, as integer32/real64 in the table
    assert all(SIZE_MISMATCH not in codes for codes in found.values())


def test_criteria_are_kept_for_the_session(window, ball):
    scene = window._graph.scene
    position, velocity = scene.add_node(ball / "bb_position.fmu"), scene.add_node(ball / "bb_velocity.fmu")
    wire = scene.add_wire(velocity, position)
    details, dialog = _open(window, wire)
    dialog._criterion.set_kind(AffixRule)
    dialog._criterion.affix_fields["from_prefix"].setText("engine.out.")
    dialog._criterion._ignore_case.setChecked(False)
    dialog.close()

    details._on_assistant()
    reopened = details._assistant
    assert reopened is not dialog
    assert reopened._criterion.rule().kind == "Same name"                  # always opens on "Same name"
    assert reopened._criterion.affix_fields["from_prefix"].text() == "engine.out."
    assert not reopened._criterion.ignore_case


def test_links_fed_meanwhile_are_skipped(window, ball, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    scene = window._graph.scene
    position, velocity = scene.add_node(ball / "bb_position.fmu"), scene.add_node(ball / "bb_velocity.fmu")
    wire = scene.add_wire(velocity, position)
    details, dialog = _open(window, wire)
    dialog._on_stage_checked()

    # The user links the input in the table of the panel while the assistant is open.
    _set_mappings(window, wire, [("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")])
    dialog._on_apply()

    assert wire.mappings == [("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")]
    assert warnings and "1 link(s) not added" in warnings[0]


def test_staging_an_aggregate_takes_its_elements(window, data_dir):
    scene = window._graph.scene
    arrays = scene.add_node(data_dir / "array" / "scalar2array-3.fmu")
    aggregates = scene.add_node(data_dir / "array" / "array2scalar-2.fmu")
    wire = scene.add_wire(arrays, aggregates)
    _, dialog = _open(window, wire)
    assert {"In1", "In1[1]", "In1[2]"} <= _free_inputs(dialog)

    out1 = next(port for port in dialog._outputs() if port.name == "Out1")
    in1 = next(port for port in dialog._inputs() if port.name == "In1")
    element = next(port for port in dialog._inputs() if port.name == "In1[1]")
    dialog._staged.append(StagedLink(A_TO_B, out1, in1, "manual"))
    dialog._refresh()
    assert not {"In1", "In1[1]", "In1[2]"} & _free_inputs(dialog)

    dialog._staged.append(StagedLink(A_TO_B, out1, element, "manual"))      # same input, through an element
    dialog._refresh()
    assert not dialog._apply.isEnabled()


def _free_inputs(dialog):
    return {port.name for port in dialog._inputs() if port.name not in dialog._busy_inputs()}
