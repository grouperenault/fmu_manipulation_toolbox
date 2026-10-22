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

import pytest

from fmu_manipulation_toolbox.terminals import Terminal, Terminals

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


def test_terminals_parse_malformed_xml_logs_error_without_raising(caplog):
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        terminals = Terminals.from_xml_source(io.StringIO("<not-closed>"), label="<bad>")
    assert len(terminals) == 0
    assert "Cannot parse" in caplog.text

