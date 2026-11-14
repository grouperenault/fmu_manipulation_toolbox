"""Rules of FMI-LS-BUS (`OperationLsBusCheck`).

The FMUs of `tests/data/ls-bus` follow the standard: one rule is broken in each test by a change of their files.
"""
import logging
from pathlib import Path

import pytest

from _helpers.archive import read_entry, rewrite_fmu
from fmu_manipulation_toolbox.checker import OperationLsBusCheck, get_checkers
from fmu_manipulation_toolbox.ls import LayeredStandard
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [pytest.mark.unit, pytest.mark.lsbus]

DATA_DIR = Path(__file__).parent.parent / "data"
NODE = DATA_DIR / "ls-bus" / "node1.fmu"
BUS = DATA_DIR / "ls-bus" / "bus.fmu"
BOUNCING_BALL = DATA_DIR / "reference-fmus" / "3.0"
MODEL = "modelDescription.xml"
MANIFEST = "extra/org.fmi-standard.fmi-ls-bus/fmi-ls-manifest.xml"
TERMINALS = "terminalsAndIcons/terminalsAndIcons.xml"
TX_CLOCK = '<Clock name="CanChannel.Tx_Clock" valueReference="3" causality="output" intervalVariability="triggered" />'
RX_CLOCK = '<Clock name="CanChannel.Rx_Clock" valueReference="2" causality="input" intervalVariability="triggered" />'
MIME = "application/org.fmi-standard.fmi-ls-bus.can; version=&quot;1.0.0-beta.1&quot;"


def _errors(path) -> list[str]:
    check = OperationLsBusCheck()
    with FMU(path) as fmu:
        fmu.apply_operation(check)
    return check.errors


def _patched(tmp_path, entry: str, old: str, new: str, source=NODE) -> Path:
    text = read_entry(source, entry).decode()
    assert old in text
    return rewrite_fmu(source, tmp_path / "patched.fmu", replace={entry: text.replace(old, new).encode()})


def test_checker_is_registered():
    assert OperationLsBusCheck in get_checkers()


@pytest.mark.parametrize("path", [NODE, BUS, DATA_DIR / "ls-bus" / "node2.fmu"], ids=lambda path: path.name)
def test_fmus_following_the_standard_have_no_error(path, caplog):
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        assert _errors(path) == []
    assert "No error against FMI-LS-BUS" in caplog.text


def test_fmu_without_ls_bus_is_not_checked(caplog):
    path = next((DATA_DIR / "compile" / "3.0").glob("*.fmu"))
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        assert _errors(path) == []
    assert "FMI-LS-BUS not present." in caplog.text
    assert "error against FMI-LS-BUS" not in caplog.text


def test_version_of_the_manifest_is_read(tmp_path):
    with FMU(NODE) as fmu:
        assert LayeredStandard(fmu.tmp_directory).bus_version == "1.0.0-beta.1"


def test_terminals_without_manifest(tmp_path):
    path = rewrite_fmu(NODE, tmp_path / "patched.fmu", drop=(MANIFEST,))
    assert any("without the manifest" in error for error in _errors(path))


@pytest.mark.parametrize("old, new, expected", [
    ('fmi-ls:fmi-ls-name="org.fmi-standard.fmi-ls-bus"', 'fmi-ls:fmi-ls-name="other"', "fmi-ls-name"),
    ('fmi-ls:fmi-ls-version="1.0.0-beta.1"', "", "no fmi-ls-version"),
    ('isBusSimulationFMU="false"', 'isBusSimulationFMU="maybe"', "not a boolean"),
    ("fmi-ls:fmi-ls-name", "<broken", "Cannot parse"),
])
def test_manifest(tmp_path, old, new, expected):
    assert any(expected in error for error in _errors(_patched(tmp_path, MANIFEST, old, new)))


@pytest.mark.parametrize("old, new, expected", [
    ('matchingRule="org.fmi-ls-bus.transceiver"', 'matchingRule="plug"', "matchingRule must be"),
    ('memberName="Tx_Clock"', 'memberName="Other"', "no member Tx_Clock"),
    ('variableName="CanChannel.Rx_Data"', 'variableName="Missing"', "does not exist"),
    ('variableName="CanChannel.Rx_Data"', 'variableName="CanChannel.Tx_Data"', "is used by"),
])
def test_bus_terminal(tmp_path, old, new, expected):
    assert any(expected in error for error in _errors(_patched(tmp_path, TERMINALS, old, new)))


def test_variable_kind_of_a_member(tmp_path):
    text = read_entry(NODE, TERMINALS).decode()
    path = rewrite_fmu(NODE, tmp_path / "patched.fmu", replace={
        TERMINALS: text.replace('variableKind="signal"', 'variableKind="other"', 1).encode()})
    assert any("variableKind" in error for error in _errors(path))


@pytest.mark.parametrize("old, new, expected", [
    (TX_CLOCK, TX_CLOCK.replace('causality="output"', 'causality="input"'), "triggered Tx_Clock must be an output"),
    (TX_CLOCK, TX_CLOCK.replace("triggered", "countdown"), "time-based Tx_Clock must be an input"),
    (RX_CLOCK, RX_CLOCK.replace('causality="input"', 'causality="output"'), "causality of Rx_Clock"),
    (RX_CLOCK, RX_CLOCK.replace("triggered", "countdown"), "Rx_Clock must be triggered or periodic"),
    (MIME, "application/octet-stream", "no MIME type of FMI-LS-BUS"),
    (MIME, MIME.replace(".can;", ".other;"), "no MIME type of FMI-LS-BUS"),
])
def test_variables(tmp_path, old, new, expected):
    assert any(expected in error for error in _errors(_patched(tmp_path, MODEL, old, new)))


def test_periodic_rx_clock_is_allowed(tmp_path):
    path = _patched(tmp_path, MODEL, RX_CLOCK, RX_CLOCK.replace("triggered", "constant"))
    assert _errors(path) == []


def test_tx_data_and_rx_data_of_different_mime_types(tmp_path):
    text = read_entry(NODE, MODEL).decode()
    path = rewrite_fmu(NODE, tmp_path / "patched.fmu",
                       replace={MODEL: text.replace(MIME, MIME.replace("beta.1", "rc.1"), 1).encode()})
    assert any("different MIME types" in error for error in _errors(path))


def test_time_based_tx_clock_without_variable_step_gives_a_warning(tmp_path, caplog):
    text = read_entry(BUS, MODEL).decode()
    assert 'canHandleVariableCommunicationStepSize="true"' in text
    path = rewrite_fmu(BUS, tmp_path / "patched.fmu", replace={MODEL: text.replace(
        'canHandleVariableCommunicationStepSize="true"', 'canHandleVariableCommunicationStepSize="false"').encode()})
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        assert _errors(path) == []
    assert "should come with canHandleVariableCommunicationStepSize" in caplog.text


def test_configuration_terminal(tmp_path):
    configuration = ('<Terminal terminalKind="{}" name="Configuration" matchingRule="{}">'
                     '<TerminalMemberVariable variableKind="signal" variableName="x" memberName="BusNotifications"/>'
                     '</Terminal></Terminal>')
    wrong_rule = configuration.format("org.fmi-ls-bus.network-terminal.configuration", "plug")
    path = _patched(tmp_path, TERMINALS, "</Terminal>", wrong_rule)
    assert any("Configuration" in error and "matchingRule must be bus" in error for error in _errors(path))

    wrong_kind = configuration.format("other", "bus")
    path = _patched(tmp_path, TERMINALS, "</Terminal>", wrong_kind)
    assert any("kind of a Configuration Terminal" in error for error in _errors(path))
