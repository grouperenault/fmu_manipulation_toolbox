"""Tests for the single-FMU tools: summary, checker and descriptor operations.

Audit reference I8 / scenarios S4-S7 — the assistant used to cover only the
container assembly: nothing of `fmutool`, nothing of the `Checker`, so an
agent could not answer "what is in this FMU?", "is it compliant?" or "rename
these ports for me".
"""
import logging

import pytest

pytestmark = [pytest.mark.unit]

from fmu_manipulation_toolbox.assistant.fmutools import (  # noqa: E402
    CAUSALITIES, MAX_EXAMPLES, MAX_MESSAGE_GROUPS, OPERATIONS, _grouped, apply_operation, check_fmu,
    dump_ports_csv, rename_ports_from_csv, summarize_fmu,
)

from _helpers.mcp_budget import make_large_fmu  # noqa: E402


@pytest.fixture
def fmu(data_dir):
    return data_dir / "containers" / "bouncing_ball" / "bb_velocity.fmu"


# --------------------------------------------------------------------------- #
#                                   summary                                    #
# --------------------------------------------------------------------------- #
def test_summary_reports_structured_facts_and_the_full_report(fmu):
    summary = summarize_fmu(fmu)

    assert summary["fmu"] == "bb_velocity.fmu"
    assert summary["fmi_version"] == 2
    assert summary["counts"] == {"input": 1, "output": 1, "independent": 1}
    # The toolbox only logs its summary: the tool must capture it, otherwise
    # the interesting half scrolls past on the server's own output.
    assert "FMI properties" in summary["report"]
    assert "MD5Sum" in summary["report"]


def test_summary_does_not_modify_the_source(fmu):
    before = fmu.read_bytes()
    summarize_fmu(fmu)
    assert fmu.read_bytes() == before


def test_summary_restores_the_logger(fmu, caplog):
    """The capture lowers the logger level; it must put it back, or the whole
    application starts logging at DEBUG after one tool call."""
    logger = logging.getLogger("fmu_manipulation_toolbox")
    logger.setLevel(logging.ERROR)
    try:
        summarize_fmu(fmu)
        assert logger.level == logging.ERROR
    finally:
        logger.setLevel(logging.NOTSET)


# --------------------------------------------------------------------------- #
#                                   checker                                    #
# --------------------------------------------------------------------------- #
def test_a_valid_fmu_is_reported_compliant(fmu):
    result = check_fmu(fmu)

    assert result["compliant"] is True
    assert result["compliant_with"] == "2.0"
    assert result["errors"] == []
    assert result["checkers"]  # at least the built-in schema check ran


def test_a_broken_descriptor_is_reported_with_its_errors(fmu, tmp_path):
    """A corrupted `modelDescription.xml` must come back as actionable errors,
    not as a silent `compliant: false`."""
    import zipfile

    broken = tmp_path / "broken.fmu"
    with zipfile.ZipFile(fmu) as source, zipfile.ZipFile(broken, "w") as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "modelDescription.xml":
                payload = payload.replace(b'causality="input"', b'causality="nonsense"')
            target.writestr(item, payload)

    result = check_fmu(broken)

    assert result["compliant"] is False
    assert result["errors"]


def test_semantic_errors_make_the_fmu_non_compliant(tmp_path):
    """`compliant` is the whole verdict, not the schema one only (docs/local/mcp_optimize.md, C8)."""
    result = check_fmu(make_large_fmu(tmp_path / "broken.fmu", nb_variables=40, broken=True))

    assert result["compliant_with"] == "2.0"             # the schema validates...
    assert result["compliant"] is False                  # ...but the semantic rules do not
    assert result["error_count"] == 21                   # 20 variables without start value, and the summary line


def test_errors_of_the_same_rule_are_grouped(tmp_path):
    result = check_fmu(make_large_fmu(tmp_path / "broken.fmu", broken=True))

    assert result["error_count"] == 2501
    assert result["truncated"] is False
    start = result["errors"][0]
    assert start["message"] == "Variable '…': a start value is required (FMI-2 §2.2.7)."
    assert start["count"] == 2500
    assert start["examples"][0] == ("Variable 'Subsystem0.Block0.signal_0': a start value is required "
                                    "(FMI-2 §2.2.7).")
    assert len(start["examples"]) == MAX_EXAMPLES
    assert result["errors"][1] == {"message": "2500 semantic error(s) against the FMI-2 standard.", "count": 1}


def test_message_groups_are_bounded():
    messages = [f"Rule {i}: '{name}' is wrong" for i in range(MAX_MESSAGE_GROUPS + 10) for name in ("a", "b")]

    groups, truncated = _grouped(messages)

    assert truncated is True
    assert len(groups) == MAX_MESSAGE_GROUPS
    assert groups[0] == {"message": "Rule 0: '…' is wrong", "count": 2, "examples": ["Rule 0: 'a' is wrong",
                                                                                   "Rule 0: 'b' is wrong"]}


# --------------------------------------------------------------------------- #
#                              CSV round-trip                                  #
# --------------------------------------------------------------------------- #
def test_ports_are_dumped_to_csv(fmu, tmp_path):
    destination = tmp_path / "ports.csv"

    report = dump_ports_csv(fmu, destination)

    assert report["ports"] == 3
    rows = destination.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("name;newName;valueReference")
    assert any(row.startswith("velocity;velocity;") for row in rows[1:])


def test_renaming_from_csv_produces_a_new_fmu(fmu, tmp_path):
    csv_path = tmp_path / "ports.csv"
    output = tmp_path / "renamed.fmu"
    dump_ports_csv(fmu, csv_path)
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace("velocity;velocity;",
                                                     "velocity;speed;"),
        encoding="utf-8")

    report = rename_ports_from_csv(fmu, csv_path, output)

    assert report["renamed"] == 1
    assert report["removed"] == 0
    assert output.is_file()
    assert "speed" in _port_names(output)
    assert "velocity" not in _port_names(output)


def test_an_empty_new_name_removes_the_port(fmu, tmp_path):
    """The CSV convention is easy to trigger by accident, so the report must
    say how many ports were dropped."""
    csv_path = tmp_path / "ports.csv"
    output = tmp_path / "trimmed.fmu"
    dump_ports_csv(fmu, csv_path)
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace("reset;reset;", "reset;;"),
        encoding="utf-8")

    report = rename_ports_from_csv(fmu, csv_path, output)

    assert report["removed"] == 1
    assert "reset" not in _port_names(output)


def test_renaming_leaves_the_source_untouched(fmu, tmp_path):
    csv_path = tmp_path / "ports.csv"
    dump_ports_csv(fmu, csv_path)
    before = fmu.read_bytes()

    rename_ports_from_csv(fmu, csv_path, tmp_path / "copy.fmu")

    assert fmu.read_bytes() == before


def _port_names(fmu_path):
    from fmu_manipulation_toolbox.assistant.headless import describe_fmu
    return {port["name"] for port in describe_fmu(fmu_path)["ports"]}


# --------------------------------------------------------------------------- #
#                            descriptor operations                             #
# --------------------------------------------------------------------------- #
def test_an_operation_rewrites_the_names(fmu, tmp_path):
    output = tmp_path / "filtered.fmu"

    report = apply_operation(fmu, output, "remove_regexp", "reset")

    assert "reset" in report["operation"]
    assert "reset" not in _port_names(output)
    assert "velocity" in _port_names(output)


def test_an_operation_can_be_restricted_to_a_causality(fmu, tmp_path):
    """`.*` would remove everything; restricted to inputs, outputs survive."""
    output = tmp_path / "inputs-dropped.fmu"

    apply_operation(fmu, output, "remove_regexp", ".*", causality=["input"])

    names = _port_names(output)
    assert "reset" not in names
    assert "velocity" in names


def test_an_unknown_operation_is_reported_with_the_available_ones(fmu, tmp_path):
    with pytest.raises(ValueError, match="Unknown operation"):
        apply_operation(fmu, tmp_path / "out.fmu", "do_magic")


def test_a_missing_argument_is_reported(fmu, tmp_path):
    with pytest.raises(ValueError, match="requires an `argument`"):
        apply_operation(fmu, tmp_path / "out.fmu", "remove_regexp")


def test_an_unexpected_argument_is_reported(fmu, tmp_path):
    with pytest.raises(ValueError, match="does not take an `argument`"):
        apply_operation(fmu, tmp_path / "out.fmu", "strip_toplevel", "oops")


def test_an_invalid_regular_expression_is_reported(fmu, tmp_path):
    with pytest.raises(ValueError, match="Cannot apply"):
        apply_operation(fmu, tmp_path / "out.fmu", "remove_regexp", "[unclosed")


def test_an_unknown_causality_is_reported(fmu, tmp_path):
    with pytest.raises(ValueError, match="Unknown causality"):
        apply_operation(fmu, tmp_path / "out.fmu", "strip_toplevel",
                        causality=["inputs"])


def test_the_exposed_operations_are_all_implemented():
    """The tool's `Literal` and this table must not drift apart."""
    assert set(OPERATIONS) == {"strip_toplevel", "merge_toplevel", "trim_until",
                               "remove_regexp", "keep_only_regexp", "remove_sources"}
    assert set(CAUSALITIES) == {"input", "output", "parameter", "local"}


