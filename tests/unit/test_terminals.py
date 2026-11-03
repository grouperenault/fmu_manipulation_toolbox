"""Unit tests for terminal parsing and connection rules (``terminals`` module).

The terminal layer turns ``terminalsAndIcons.xml`` descriptions into
``Terminal`` objects and computes variable-to-variable links according to the
FMI terminal ``matchingRule`` (plug / bus / sequence / LS-BUS transceiver).
These tests pin the produced links for each rule and the defensive behaviour on
mismatching terminals (an error is logged, no exception is raised and no partial
link is emitted), as well as the XML parser's tolerance to malformed input.
"""
import io
import logging

from pathlib import Path

import pytest

from fmu_manipulation_toolbox.terminals import Terminal, TerminalError, Terminals

pytestmark = [pytest.mark.unit]


def _terminal(name, matching, members, kind="k"):
    term = Terminal(name, kind, matching)
    for member_name, variable_name in members.items():
        term.add_member(member_name, variable_name)
    return term


# --------------------------------------------------------------------------- #
#                               connect rules                                   #
# --------------------------------------------------------------------------- #
def test_connect_plug_links_matching_members():
    a = _terminal("A", "plug", {"x": "A.x", "y": "A.y"})
    b = _terminal("B", "plug", {"x": "B.x", "y": "B.y"})
    assert set(a.connect(b)) == {("A.x", "B.x"), ("A.y", "B.y")}


def test_connect_plug_mismatch_logs_error_and_links_nothing(caplog):
    a = _terminal("A", "plug", {"x": "A.x", "y": "A.y"})
    b = _terminal("B", "plug", {"x": "B.x", "z": "B.z"})
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        links = a.connect(b)
    assert links == []
    assert "does not exactly fit" in caplog.text


def test_connect_bus_links_common_members_only():
    a = _terminal("A", "bus", {"x": "A.x", "y": "A.y"})
    b = _terminal("B", "bus", {"y": "B.y", "z": "B.z"})
    # Only the shared member "y" is wired; extras on either side are ignored.
    assert a.connect(b) == [("A.y", "B.y")]


def test_connect_sequence_links_by_order():
    a = _terminal("A", "sequence", {"first": "A.1", "second": "A.2"})
    b = _terminal("B", "sequence", {"alpha": "B.1", "beta": "B.2"})
    assert a.connect(b) == [("A.1", "B.1"), ("A.2", "B.2")]


def test_connect_sequence_length_mismatch_logs_error(caplog):
    a = _terminal("A", "sequence", {"first": "A.1", "second": "A.2"})
    b = _terminal("B", "sequence", {"only": "B.1"})
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        links = a.connect(b)
    assert links == []
    assert "does not exactly fit" in caplog.text


def test_connect_transceiver_maps_tx_to_rx_both_ways():
    members = {"Tx_Data": "{0}.Tx_Data", "Tx_Clock": "{0}.Tx_Clock",
               "Rx_Data": "{0}.Rx_Data", "Rx_Clock": "{0}.Rx_Clock"}
    a = _terminal("A", "org.fmi-ls-bus.transceiver",
                  {k: v.format("A") for k, v in members.items()})
    b = _terminal("B", "org.fmi-ls-bus.transceiver",
                  {k: v.format("B") for k, v in members.items()})
    assert a.connect(b) == [
        ("A.Tx_Data", "B.Rx_Data"),
        ("A.Tx_Clock", "B.Rx_Clock"),
        ("A.Rx_Data", "B.Tx_Data"),
        ("A.Rx_Clock", "B.Tx_Clock"),
    ]


def test_connect_unknown_rule_logs_error_and_links_nothing(caplog):
    a = _terminal("A", "no-such-rule", {"x": "A.x"})
    b = _terminal("B", "no-such-rule", {"x": "B.x"})
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        links = a.connect(b)
    assert links == []
    assert "not defined to connect" in caplog.text


def test_terminal_equality_depends_on_kind_and_rule():
    a = _terminal("A", "plug", {"x": "A.x"}, kind="network")
    same = _terminal("B", "plug", {"y": "B.y"}, kind="network")  # name/members differ
    other_rule = _terminal("C", "bus", {"x": "C.x"}, kind="network")
    assert a == same
    assert a != other_rule
    assert a != "not-a-terminal"


# --------------------------------------------------------------------------- #
#                               XML parsing                                     #
# --------------------------------------------------------------------------- #
_VALID_XML = """<?xml version="1.0" encoding="UTF-8"?>
<fmiTerminalsAndIcons fmiVersion="3.0">
  <Terminals>
    <Terminal terminalKind="org.fmi-ls-bus.network-terminal"
              matchingRule="org.fmi-ls-bus.transceiver" name="CanChannel">
      <TerminalMemberVariable variableName="CanChannel.Rx_Data" memberName="Rx_Data"/>
      <TerminalMemberVariable variableName="CanChannel.Tx_Data" memberName="Tx_Data"/>
    </Terminal>
  </Terminals>
</fmiTerminalsAndIcons>
"""


def test_terminals_parse_from_xml_source():
    terminals = Terminals.from_xml_source(io.StringIO(_VALID_XML), label="<test>")
    assert len(terminals) == 1
    assert "CanChannel" in terminals
    term = terminals["CanChannel"]
    assert term.matching == "org.fmi-ls-bus.transceiver"
    assert term.members == {"Rx_Data": "CanChannel.Rx_Data",
                            "Tx_Data": "CanChannel.Tx_Data"}


def test_terminals_parse_after_graphical_representation():
    xml = _VALID_XML.replace("<Terminals>", "<GraphicalRepresentation><Icon/></GraphicalRepresentation><Terminals>")
    terminals = Terminals.from_xml_source(io.StringIO(xml), label="<test>")
    assert list(terminals.terminals) == ["CanChannel"]


def test_terminals_parse_without_terminals_is_not_an_error(caplog):
    xml = '<fmiTerminalsAndIcons fmiVersion="3.0"><GraphicalRepresentation/></fmiTerminalsAndIcons>'
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        terminals = Terminals.from_xml_source(io.StringIO(xml), label="<test>")
    assert len(terminals) == 0
    assert caplog.text == ""


def test_terminals_parse_malformed_xml_logs_error_without_raising(caplog):
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        terminals = Terminals.from_xml_source(io.StringIO("<not-closed>"), label="<bad>")
    assert len(terminals) == 0
    assert "Cannot parse" in caplog.text


# --------------------------------------------------------------------------- #
#                             nested terminals                                  #
# --------------------------------------------------------------------------- #
_MEMBERS = ("Tx_Data", "Tx_Clock", "Rx_Data", "Rx_Clock")
_SPEC_EXAMPLES = Path(__file__).parent.parent / "data" / "ls-bus-spec"


def _bus_xml(name, prefix=None, content=""):
    members = "".join(f'<TerminalMemberVariable variableKind="signal" variableName="{prefix or name}.{member}" '
                      f'memberName="{member}"/>' for member in _MEMBERS)
    return (f'<Terminal terminalKind="org.fmi-ls-bus.network-terminal" name="{name}" '
            f'matchingRule="org.fmi-ls-bus.transceiver">{members}{content}</Terminal>')


def _group_xml(name, content):
    return f'<Terminal name="{name}" matchingRule="none">{content}</Terminal>'


_CONFIGURATION_XML = ('<Terminal terminalKind="org.fmi-ls-bus.network-terminal.configuration" name="Configuration" '
                      'matchingRule="bus"><TerminalMemberVariable variableKind="signal" '
                      'variableName="BusNotifications" memberName="BusNotifications"/></Terminal>')


def _terminals(*content):
    xml = f'<fmiTerminalsAndIcons fmiVersion="3.0"><Terminals>{"".join(content)}</Terminals></fmiTerminalsAndIcons>'
    return Terminals.from_xml_source(io.StringIO(xml))


def _with_subs(name, matching, *subs):
    terminal = _terminal(name, matching, {})
    for sub in subs:
        sub.path = f"{name}.{sub.name}"
        terminal.sub_terminals[sub.name] = sub
    return terminal


def test_nested_terminals_are_designated_by_their_full_path():
    terminals = _terminals(_group_xml("Seg1", _bus_xml("P1", "S1P1") + _bus_xml("P2", "S1P2")),
                           _group_xml("Seg2", _bus_xml("P1", "S2P1")))
    assert list(terminals.terminals) == ["Seg1", "Seg1.P1", "Seg1.P2", "Seg2", "Seg2.P1"]
    assert terminals["Seg1.P1"].members["Tx_Data"] == "S1P1.Tx_Data"
    assert terminals["Seg2.P1"].members["Tx_Data"] == "S2P1.Tx_Data"
    assert "P1" not in terminals
    assert terminals.paths_of("P1") == ["Seg1.P1", "Seg2.P1"]
    assert terminals.paths_of("Seg1") == []


def test_grouping_terminal_links_its_sub_terminals_without_error(caplog):
    terminals = _terminals(_group_xml("Seg1", _bus_xml("P1", "A")))
    others = _terminals(_group_xml("Seg1", _bus_xml("P1", "B")))
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        links = terminals["Seg1"].connect(others["Seg1"])
    assert ("A.Tx_Data", "B.Rx_Data") in links and len(links) == 4
    assert caplog.text == ""


def test_links_of_the_rule_and_of_the_sub_terminals_are_both_kept():
    a = _with_subs("T", "bus", _terminal("S", "bus", {"s": "A.s"}))
    b = _with_subs("T", "bus", _terminal("S", "bus", {"s": "B.s"}))
    a.add_member("x", "A.x")
    b.add_member("x", "B.x")
    assert a.connect(b) == [("A.x", "B.x"), ("A.s", "B.s")]


@pytest.mark.parametrize("rule", ["plug", "sequence", "none", "org.fmi-ls-bus.transceiver"])
@pytest.mark.parametrize("reverse", [False, True])
def test_missing_sub_terminal_is_an_error(rule, reverse):
    members = {member: f"A.{member}" for member in _MEMBERS} if rule == "org.fmi-ls-bus.transceiver" else {}
    a = _with_subs("A", rule, _terminal("S", "bus", {}), _terminal("Only", "bus", {}))
    b = _with_subs("B", rule, _terminal("S", "bus", {}))
    a.members.update(members)
    b.members.update(members)
    with pytest.raises(TerminalError, match="A.Only"):
        (b.connect(a) if reverse else a.connect(b))


@pytest.mark.parametrize("reverse", [False, True])
def test_missing_sub_terminal_of_the_bus_rule_is_ignored(reverse):
    a = _with_subs("A", "bus", _terminal("S", "bus", {"s": "A.s"}), _terminal("Only", "bus", {"o": "A.o"}))
    b = _with_subs("B", "bus", _terminal("S", "bus", {"s": "B.s"}))
    assert (b.connect(a) if reverse else a.connect(b)) == ([("B.s", "A.s")] if reverse else [("A.s", "B.s")])


@pytest.mark.parametrize("reverse", [False, True])
def test_configuration_may_be_missing_on_one_side(reverse):
    with_configuration = _terminals(_bus_xml("A", content=_CONFIGURATION_XML))["A"]
    without = _terminals(_bus_xml("B"))["B"]
    links = without.connect(with_configuration) if reverse else with_configuration.connect(without)
    assert len(links) == 4


def test_configuration_is_neither_linked_nor_connectable():
    terminals = _terminals(_bus_xml("A", content=_CONFIGURATION_XML))
    others = _terminals(_bus_xml("B", content=_CONFIGURATION_XML))
    assert list(terminals.terminals) == ["A"]
    assert "A.Configuration" not in terminals
    assert [terminal.path for terminal in terminals.walk()] == ["A", "A.Configuration"]
    assert len(terminals["A"].connect(others["B"])) == 4


def test_incompatible_sub_terminals_are_an_error():
    a = _with_subs("A", "none", _terminal("S", "bus", {}, kind="k1"))
    b = _with_subs("B", "none", _terminal("S", "bus", {}, kind="k2"))
    with pytest.raises(TerminalError, match="Incompatible"):
        a.connect(b)


def test_transceiver_without_its_members_is_an_error():
    a = _terminal("A", "org.fmi-ls-bus.transceiver", {"Tx_Data": "A.Tx_Data"})
    b = _terminal("B", "org.fmi-ls-bus.transceiver", {member: member for member in _MEMBERS})
    with pytest.raises(TerminalError, match="Tx_Clock, Rx_Data, Rx_Clock"):
        a.connect(b)


@pytest.mark.parametrize("example, name, nb_links", [
    ("X_network4FMI_terminalsAndIcons_lowCut.xml", "Powertrain", 4),
    ("X_network4FMI_terminalsAndIcons_highCut_dbc.xml", "Powertrain", 12),
    ("X_network4FMI_terminalsAndIcons_highCut_autosar.xml", "Powertrain", 3),
])
def test_examples_of_the_specification(example, name, nb_links):
    terminals = Terminals.from_xml_source(str(_SPEC_EXAMPLES / example))
    assert len(terminals[name].connect(terminals[name])) == nb_links


def test_frame_and_pdu_of_the_same_name_do_not_collide():
    terminals = Terminals.from_xml_source(str(_SPEC_EXAMPLES / "X_network4FMI_terminalsAndIcons_highCut_dbc.xml"))
    assert terminals["Powertrain.tcuSensors"].kind == "org.fmi-ls-bus.frame-terminal"
    assert terminals["Powertrain.tcuSensors.tcuSensors"].kind == "org.fmi-ls-bus.pdu-terminal"
