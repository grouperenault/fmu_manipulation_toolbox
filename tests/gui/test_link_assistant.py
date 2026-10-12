"""GUI tests of the link assistant window, fed with the fictitious FMUs of its mockup."""

import re

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

try:
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from fmu_manipulation_toolbox.gui.fmucontainer.details.link_assistant import (
        LinkAssistantDialog, _CriterionEditor, _PortsModel, StagedLink, A_TO_B)
    from fmu_manipulation_toolbox.gui.fmucontainer.details.link_assistant_demo import generate
    from fmu_manipulation_toolbox.gui.fmucontainer.details.link_matching import (
        AffixRule, RegexRule, SimilarityRule, ERROR, WARNING)
except Exception as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"GUI dependencies not available: {exc}", allow_module_level=True)

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def fresh_session():
    """The criteria are kept for the session of the application: each test starts with new ones."""
    _CriterionEditor._session_rules = None
    _CriterionEditor._session_ignore_case = True


@pytest.fixture
def dialog(qtbot):
    side_a, side_b, existing = generate(200)
    dialog = LinkAssistantDialog(side_a, side_b, existing)
    dialog.show()
    yield dialog
    # Closed here rather than by `qtbot.addWidget` (which closes before this teardown), once the staged links are
    # dropped, so that the "discard the staged links?" question is not asked.
    dialog._staged = []
    dialog.close()
    dialog.deleteLater()


def _use_prefix(dialog, from_prefix, to_prefix):
    dialog._criterion.set_kind(AffixRule)
    dialog._criterion.affix_fields["from_prefix"].setText(from_prefix)
    dialog._criterion.affix_fields["to_prefix"].setText(to_prefix)


def test_suggestions_follow_the_criterion(dialog, qtbot):
    # The window opens with "Same name" and searches by itself; typing updates the suggestions.
    qtbot.waitUntil(lambda: dialog._suggestions_model.suggestions != [])
    same_name = len(dialog._suggestions_model.suggestions)
    _use_prefix(dialog, "engine.out.", "ecu.in.engine_")
    qtbot.waitUntil(lambda: len(dialog._suggestions_model.suggestions) != same_name)
    assert all(s.output.name.startswith("engine.out.") for s in dialog._suggestions_model.suggestions)
    assert not dialog._run_button.isVisible()


def test_slow_search_shows_run_button(dialog, monkeypatch):
    monkeypatch.setattr(dialog, "AUTO_RUN_LIMIT", -1.0)
    dialog._on_run()
    assert dialog._run_button.isVisible()
    dialog._criterion.set_kind(SimilarityRule)
    assert "press Run" in dialog._suggestions_summary.text()


def test_rules_stage_and_apply(dialog, qtbot):
    _use_prefix(dialog, "engine.out.", "ecu.in.engine_")
    dialog._on_run()
    suggestions = dialog._suggestions_model.suggestions
    assert any(s.status.level == ERROR for s in suggestions)
    checked = [s for s in suggestions if s.checked]
    assert checked and all(s.status.level != ERROR for s in checked)

    unchecked = suggestions[-1]
    unchecked.checked = False
    dialog._on_stage_checked()
    assert len(dialog._staged) == len(checked) - (unchecked in checked)
    assert {link.origin for link in dialog._staged} == {"prefix / suffix"}
    # The suggestions not staged are kept, with their check box.
    assert unchecked in dialog._suggestions_model.suggestions and not unchecked.checked
    assert dialog._apply.isEnabled()

    with qtbot.waitSignal(dialog.applied) as blocker:
        dialog._on_apply()
    mappings = blocker.args[0]
    assert len(mappings) == len(checked) - (unchecked in checked)
    assert all(m[0] == "engine.fmu" and m[2] == "ecu.fmu" for m in mappings)


def test_manual_pairing_and_duplicate_target(dialog):
    dialog._tabs.setCurrentIndex(1)
    for table, count in ((dialog._outputs_table, 2), (dialog._inputs_table, 1)):
        for row in range(count):
            table.selectionModel().select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select
                                          | QItemSelectionModel.SelectionFlag.Rows)
    assert not dialog._link_selection.isEnabled()          # 2 outputs for 1 input

    dialog._outputs_table.clearSelection()
    dialog._outputs_table.selectRow(0)
    assert dialog._link_selection.isEnabled()
    dialog._on_link_selection()
    assert [link.origin for link in dialog._staged] == ["manual"]

    # The same input staged twice: both links are errors and Apply is disabled.
    dialog._staged.append(dialog._staged[0])
    dialog._refresh()
    assert not dialog._apply.isEnabled()


def test_direction_b_to_a(dialog):
    dialog._direction_combo.setCurrentIndex(1)
    _use_prefix(dialog, "ecu.out.", "engine.in.")
    dialog._on_run()
    dialog._on_stage_checked()
    mappings = dialog.staged_mappings()
    assert mappings and all(m[0] == "ecu.fmu" and m[2] == "engine.fmu" for m in mappings)


def test_regex_criterion(dialog):
    dialog._criterion.set_kind(RegexRule)
    pattern, replacement = dialog._criterion.regex_fields
    pattern.setText(r"^sensor\.(\w+)\.(\w+)$")
    replacement.setText(r"sensor_\2_\1")
    dialog._on_run()
    suggestions = dialog._suggestions_model.suggestions
    assert suggestions and all(s.output.name.startswith("sensor.") for s in suggestions)
    for s in suggestions:
        subsystem, quantity = s.output.name.split(".")[1:]
        assert s.input.name == f"sensor_{quantity}_{subsystem}"

    pattern.setText("(")                                          # invalid: nothing, no exception
    dialog._on_run()
    assert dialog._suggestions_model.suggestions == []


def test_check_uncheck_then_stage(dialog):
    _use_prefix(dialog, "engine.out.", "ecu.in.engine_")
    dialog._on_run()
    dialog._check_suggestions(False)
    dialog._on_stage_checked()
    assert dialog._staged == []

    dialog._suggestions_filter.level = WARNING                    # "Check all" acts on the rows shown only
    dialog._suggestions_filter.refresh()
    dialog._check_suggestions(True)
    dialog._on_stage_checked()
    assert dialog._staged and all(s.level == WARNING for s in dialog._statuses)


def test_unmatched_ports_in_the_manual_tab(dialog):
    _use_prefix(dialog, "engine.out.", "ecu.in.engine_")
    dialog._on_run()
    text = dialog._unmatched_link.text()
    outputs, inputs = (int(n) for n in re.search(r"unmatched: (\d+) outputs / (\d+) inputs", text).groups())

    dialog._on_unmatched_clicked()
    assert dialog._tabs.currentIndex() == 1 and dialog._only_unsuggested.isChecked()
    assert dialog._outputs_filter.rowCount() == outputs
    assert dialog._inputs_filter.rowCount() == inputs
    suggested = {s.output.name for s in dialog._suggestions_model.suggestions}
    shown = {dialog._outputs_filter.index(row, 0).data(_PortsModel.ROLE_PORT).name
             for row in range(dialog._outputs_filter.rowCount())}
    assert not shown & suggested


def test_manual_link_removes_the_suggestions_of_its_ports(dialog):
    _use_prefix(dialog, "engine.out.", "ecu.in.engine_")
    dialog._on_run()
    suggestion = next(s for s in dialog._suggestions_model.suggestions if s.status.level != ERROR)
    other = next(port for port in dialog._inputs() if port.name.startswith("ecu.aux."))
    dialog._staged.append(StagedLink(A_TO_B, suggestion.output, other, "manual"))
    dialog._refresh()
    assert suggestion not in dialog._suggestions_model.suggestions
