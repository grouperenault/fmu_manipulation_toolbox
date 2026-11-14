"""Tests for the single-FMU tools: summary, checker and descriptor operations.

Besides the container assembly, the assistant exposes what `fmutool` and the
`Checker` do on a single FMU, so that an agent can answer "what is in this
FMU?", "is it compliant?" or "rename these ports for me".
"""
import logging

import pytest

pytestmark = [pytest.mark.unit]

from _helpers.mcp_budget import make_large_fmu  # noqa: E402
from fmu_manipulation_toolbox.assistant.fmutools import (  # noqa: E402
    CAUSALITIES,
    MAX_EXAMPLES,
    MAX_MESSAGE_GROUPS,
    OPERATIONS,
    _grouped,
    apply_operation,
    check_fmu,
    describe_port,
    dump_ports_csv,
    rename_ports,
    select_ports,
    summarize_fmu,
)


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
    """`compliant` is the whole verdict, not the schema one only."""
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

    report = rename_ports(fmu, output, csv_path=csv_path)

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

    report = rename_ports(fmu, output, csv_path=csv_path)

    assert report["removed"] == 1
    assert "reset" not in _port_names(output)


def test_renaming_leaves_the_source_untouched(fmu, tmp_path):
    csv_path = tmp_path / "ports.csv"
    dump_ports_csv(fmu, csv_path)
    before = fmu.read_bytes()

    rename_ports(fmu, tmp_path / "copy.fmu", csv_path=csv_path)

    assert fmu.read_bytes() == before


def test_renaming_from_a_mapping(fmu, tmp_path):
    output = tmp_path / "renamed.fmu"

    report = rename_ports(fmu, output, {"velocity": "speed", "reset": ""})

    assert (report["renamed"], report["removed"]) == (1, 1)
    assert "unknown" not in report
    assert {"speed"} <= _port_names(output)
    assert not {"velocity", "reset"} & _port_names(output)


def test_the_names_absent_from_the_fmu_are_reported(fmu, tmp_path):
    """A typo in a mapping silently renames nothing: the report must say which names were not found."""
    report = rename_ports(fmu, tmp_path / "out.fmu", {"velocity": "speed", "velocty": "x"})

    assert report["renamed"] == 1
    assert report["unknown"] == ["velocty"]
    assert report["unknown_total"] == 1


@pytest.mark.parametrize("mapping, csv", [(None, None), ({"a": "b"}, "ports.csv")])
def test_renaming_needs_a_mapping_or_a_csv(fmu, tmp_path, mapping, csv):
    with pytest.raises(ValueError, match="either `mapping` or `csv`"):
        rename_ports(fmu, tmp_path / "out.fmu", mapping, tmp_path / csv if csv else None)


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


def test_an_operation_can_be_restricted_to_a_type_and_a_variability(data_dir, tmp_path):
    """On FMI 3, `Real` selects the Float64 parameters; `tunable` keeps the fixed one."""
    fmu = data_dir / "compile" / "3.0" / "BouncingBall.fmu"
    output = tmp_path / "filtered.fmu"

    apply_operation(fmu, output, "remove_regexp", ".*", causality=["parameter"], types=["Real"],
                    variabilities=["tunable"])

    assert "e" not in _port_names(output)
    assert {"g", "h", "v"} <= _port_names(output)


@pytest.mark.parametrize("filters, message", [
    ({"types": ["Double"]}, "Unknown type"),
    ({"variabilities": ["constantly"]}, "Unknown variability"),
])
def test_an_unknown_filter_value_is_reported(fmu, tmp_path, filters, message):
    with pytest.raises(ValueError, match=message):
        apply_operation(fmu, tmp_path / "out.fmu", "strip_toplevel", **filters)


def test_the_port_pages_select_like_the_operations():
    ports = [{"name": "p", "type": "Float64", "causality": "parameter"},
             {"name": "u", "type": "Int32", "causality": "input"},
             {"name": "t", "type": "Float64", "causality": "independent"}]

    assert [port["name"] for port in select_ports(ports, 3, types=["Real"])] == ["p", "t"]
    # Undeclared variabilities: the defaults of FMI 3 (parameter: fixed, integer: discrete).
    assert [port["name"] for port in select_ports(ports, 3, variabilities=["fixed"])] == ["p"]
    assert [port["name"] for port in select_ports(ports, 3, variabilities=["discrete"])] == ["u"]
    # Any causality can be listed, not only those an operation can be restricted to.
    assert [port["name"] for port in select_ports(ports, 3, causality=["independent"])] == ["t"]


def test_an_unknown_causality_is_reported(fmu, tmp_path):
    with pytest.raises(ValueError, match="Unknown causality"):
        apply_operation(fmu, tmp_path / "out.fmu", "strip_toplevel",
                        causality=["inputs"])


def test_the_exposed_operations_are_all_implemented():
    """The tool's `Literal` and this table must not drift apart."""
    assert set(OPERATIONS) == {"strip_toplevel", "merge_toplevel", "trim_until",
                               "remove_regexp", "keep_only_regexp", "remove_sources"}
    assert set(CAUSALITIES) == {"input", "output", "parameter", "local"}




# --------------------------------------------------------------------------- #
#                               one port in full                               #
# --------------------------------------------------------------------------- #
def test_a_port_card_has_every_declared_attribute(data_dir):
    card = describe_port(data_dir / "compile" / "2.0" / "BouncingBall.fmu", "h")

    assert card["type"] == "Real"
    assert card["causality"] == "output"
    assert card["attributes"]["description"] == "Position of the ball"
    assert card["attributes"]["start"] == "1"  # FMI-2: attribute of <Real>, merged with <ScalarVariable>


def test_a_port_card_resolves_its_declared_type(data_dir):
    card = describe_port(data_dir / "compile" / "3.0" / "BouncingBall.fmu", "h")

    assert card["declared_type"] == {"name": "Position", "attributes": {"quantity": "Position", "unit": "m"},
                                     "inherited": {"quantity": "Position", "unit": "m"}}


def test_a_port_card_lists_the_fmi3_aliases(data_dir):
    card = describe_port(data_dir / "compile" / "3.0" / "BouncingBall.fmu", "h")

    assert card["aliases"] == [{"name": "h_ft", "description": "Position in feet", "displayUnit": "ft"}]


def test_a_port_card_lists_its_terminals(data_dir):
    card = describe_port(data_dir / "ls-bus" / "node1.fmu", "CanChannel.Rx_Data")

    assert card["type"] == "Binary"
    assert card["terminals"] == [{"terminal": "CanChannel", "kind": "org.fmi-ls-bus.network-terminal",
                                  "member": "Rx_Data"}]


def test_optional_sections_are_omitted(data_dir):
    card = describe_port(data_dir / "compile" / "2.0" / "BouncingBall.fmu", "time")

    assert not {"declared_type", "aliases", "terminals", "dimensions"} & set(card)


FMI2_ALIASES = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="m" guid="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <CoSimulation modelIdentifier="m"/>
  <TypeDefinitions>
    <SimpleType name="Gear"><Enumeration><Item name="park" value="1"/><Item name="drive" value="2"/></Enumeration></SimpleType>
  </TypeDefinitions>
  <ModelVariables>
    <ScalarVariable name="gear" valueReference="1" causality="input"><Enumeration declaredType="Gear" start="1"/></ScalarVariable>
    <ScalarVariable name="gear_copy" valueReference="1" causality="output" variability="discrete"><Enumeration declaredType="Gear"/></ScalarVariable>
    <ScalarVariable name="other" valueReference="1" causality="output" variability="discrete"><Integer/></ScalarVariable>
  </ModelVariables>
  <ModelStructure><Outputs><Unknown index="2"/><Unknown index="3"/></Outputs></ModelStructure>
</fmiModelDescription>
"""

FMI3_ARRAY = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <CoSimulation modelIdentifier="m"/>
  <ModelVariables>
    <Float64 name="u" valueReference="1" causality="input" start="0 0 0"><Dimension start="3"/></Float64>
  </ModelVariables>
  <ModelStructure/>
</fmiModelDescription>
"""


def _hand_built(tmp_path, descriptor):
    import zipfile
    path = tmp_path / "model.fmu"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("modelDescription.xml", descriptor)
    return path


def test_fmi2_aliases_share_the_value_reference_and_the_type(tmp_path):
    card = describe_port(_hand_built(tmp_path, FMI2_ALIASES), "gear")

    assert card["aliases"] == [{"name": "gear_copy", "causality": "output"}]  # not `other`, an Integer


def test_an_enumeration_card_lists_its_items(tmp_path):
    card = describe_port(_hand_built(tmp_path, FMI2_ALIASES), "gear")

    assert card["declared_type"]["items"] == [{"name": "park", "value": "1"}, {"name": "drive", "value": "2"}]


def test_an_array_card_has_its_dimensions(tmp_path):
    card = describe_port(_hand_built(tmp_path, FMI3_ARRAY), "u")

    assert card["dimensions"] == [{"start": 3}]


def test_an_unknown_port_suggests_close_names(data_dir):
    with pytest.raises(ValueError, match=r"no port 'hh'.*\['h'"):
        describe_port(data_dir / "compile" / "2.0" / "BouncingBall.fmu", "hh")


def test_the_aliases_of_a_port_are_bounded(tmp_path):
    from fmu_manipulation_toolbox.assistant.fmutools import MAX_ALIASES
    variables = "".join(f'<ScalarVariable name="v{i}" valueReference="1" causality="local"><Real/></ScalarVariable>'
                        for i in range(MAX_ALIASES + 5))
    descriptor = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<fmiModelDescription fmiVersion="2.0" modelName="m" guid="{g}"><CoSimulation modelIdentifier="m"/>'
                  f'<ModelVariables>{variables}</ModelVariables><ModelStructure/></fmiModelDescription>')

    card = describe_port(_hand_built(tmp_path, descriptor), "v0")

    assert len(card["aliases"]) == MAX_ALIASES
    assert card["aliases_total"] == MAX_ALIASES + 4
