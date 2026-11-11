"""Rules of FMI-LS-XCP (`OperationLsXcpCheck`).

The stub FMUs of `tests/data/ls-xcp` (descriptor, manifest and A2L files, without binaries) follow the standard: one
rule is broken in each test by a change of their files.
"""
import logging
from pathlib import Path

import pytest

from _helpers.archive import read_entry, rewrite_fmu, zip_fmu
from fmu_manipulation_toolbox.checker import OperationLsXcpCheck, get_checkers
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [pytest.mark.unit, pytest.mark.lsxcp]

DATA_DIR = Path(__file__).parent.parent / "data"
MODEL = "modelDescription.xml"
XCP = "extra/org.fmi-standard.fmi-ls-xcp"
MANIFEST = f"{XCP}/fmi-ls-manifest.xml"
A2L_PLATFORMS = {2: ("win64", "linux64", "darwin64"), 3: ("x86_64-windows", "x86_64-linux", "aarch64-darwin")}


@pytest.fixture(params=[2, 3], ids=["fmi2", "fmi3"])
def stub(request, tmp_path) -> tuple[Path, int]:
    version = request.param
    return zip_fmu(DATA_DIR / "ls-xcp" / f"stub_xcp_fmi{version}", tmp_path / "stub.fmu"), version


@pytest.fixture
def stub3(tmp_path) -> Path:
    return zip_fmu(DATA_DIR / "ls-xcp" / "stub_xcp_fmi3", tmp_path / "stub.fmu")


def _errors(path) -> list[str]:
    check = OperationLsXcpCheck()
    with FMU(path) as fmu:
        fmu.apply_operation(check)
    return check.errors


def _patched(source: Path, entry: str, old: str, new: str) -> Path:
    text = read_entry(source, entry).decode()
    assert old in text
    destination = source.with_name(f"patched-{len(list(source.parent.glob('patched*.fmu')))}.fmu")
    return rewrite_fmu(source, destination, replace={entry: text.replace(old, new).encode()})


def _has(errors: list[str], expected: str) -> bool:
    return any(expected in error for error in errors)


def test_checker_is_registered():
    assert OperationLsXcpCheck in get_checkers()


def test_stub_follows_the_standard(stub, caplog):
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        assert _errors(stub[0]) == []
    assert "No error against FMI-LS-XCP" in caplog.text
    assert "has no binaries" in caplog.text     # A2L files of platforms, archive without binaries


def test_fmu_without_ls_xcp_is_not_checked(caplog):
    path = DATA_DIR / "ls-bus" / "node1.fmu"
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        assert _errors(path) == []
    assert "FMI-LS-XCP not present." in caplog.text
    assert "error against FMI-LS-XCP" not in caplog.text


@pytest.mark.parametrize("old, new, expected", [
    ('fmi-ls:fmi-ls-version="1.0.0"', "", "fmi-ls-version"),
    ('fmi-ls:fmi-ls-name="org.fmi-standard.fmi-ls-xcp"', 'fmi-ls:fmi-ls-name="other"', "fmi-ls-name"),
    ('role="XCPServiceTCPPort"', 'role="XCPServicePort"', "XCPServicePort"),
    ('<Interface', '<broken', "Cannot parse the manifest of FMI-LS-XCP"),
])
def test_manifest_against_xsd(stub, old, new, expected):
    assert _has(_errors(_patched(stub[0], MANIFEST, old, new)), expected)


def test_manifest_errors_name_the_attributes_without_namespace(stub):
    """A fixed value of the XSD: the attribute is named 'fmi-ls-description', without its namespace."""
    errors = _errors(_patched(stub[0], MANIFEST, 'fmi-ls:fmi-ls-description="Layered',
                              'fmi-ls:fmi-ls-description="Other'))
    assert _has(errors, "Manifest of FMI-LS-XCP: attribute 'fmi-ls-description' has a fixed value")
    assert not any("{" in error for error in errors)


def test_neither_service_nor_direct_memory_access(stub):
    path = _patched(stub[0], MANIFEST, 'containsXCPService="true"', "")
    errors = _errors(path)
    assert _has(errors, "neither containsXCPService nor supportsDirectMemoryAccess")


@pytest.mark.parametrize("definition, expected", [
    ("../ecu.a2l", "dot segments"),
    ("./ecu.a2l", "dot segments"),
    ("/ecu.a2l", "relative URI"),
    ("file:///ecu.a2l", "relative URI"),
    ("other.a2l", "no A2L file"),
])
def test_definition(stub, definition, expected):
    path = _patched(stub[0], MANIFEST, 'definition="ecu.a2l"', f'definition="{definition}"')
    assert _has(_errors(path), expected)


def test_a2l_of_source_code_fmu(stub):
    source, version = stub
    a2l = read_entry(source, f"{XCP}/{A2L_PLATFORMS[version][0]}/ecu.a2l")
    path = rewrite_fmu(source, source.with_name("source.fmu"), drop=tuple(f"{XCP}/{p}/" for p in A2L_PLATFORMS[version]),
                       replace={f"{XCP}/ecu.a2l": a2l})
    assert _errors(path) == []


def test_a2l_include_is_forbidden(stub):
    source, version = stub
    entry = f"{XCP}/{A2L_PLATFORMS[version][1]}/ecu.a2l"
    path = _patched(source, entry, "/begin MODULE", '/include "other.a2l"\n  /begin MODULE')
    assert _has(_errors(path), "uses /include")


def test_types_not_provided_is_a_warning(stub, caplog):
    path = _patched(stub[0], MANIFEST, 'definition="ecu.a2l"', 'definition="ecu.a2l" types="ModelExchange"')
    assert _errors(path) == []
    assert "applies to ModelExchange, which the FMU does not provide" in caplog.text


def test_role_given_twice(stub):
    path = _patched(stub[0], MANIFEST, 'name="XCP.TCP.ListenAddress" role="XCPServiceTCPListenAddress"',
                    'name="XCP.TCP.ListenAddress" role="XCPServiceTCPPort"')
    assert _has(_errors(path), "role XCPServiceTCPPort is given several times")


def test_variable_used_twice(stub):
    path = _patched(stub[0], MANIFEST, 'name="XCP.TCP.ListenAddress"', 'name="XCP.TCP.Port"')
    assert _has(_errors(path), "'XCP.TCP.Port' is already used")


def test_unknown_variable(stub):
    path = _patched(stub[0], MANIFEST, 'name="XCP.TCP.Port"', 'name="XCP.Port"')
    assert _has(_errors(path), "'XCP.Port' of role XCPServiceTCPPort does not exist")


def test_role_without_service_is_a_warning(stub, caplog):
    path = _patched(stub[0], MANIFEST, 'containsXCPService="true"', 'supportsDirectMemoryAccess="true"')
    assert _errors(path) == []
    assert "without containsXCPService" in caplog.text


@pytest.mark.parametrize("old, new, expected", [
    ('<UInt16 name="XCP.TCP.Port" valueReference="2"', '<Int32 name="XCP.TCP.Port" valueReference="2"',
     "must be a UInt16, not a Int32"),
    ('<Boolean name="XCP.TCP.Enable" valueReference="1" causality="structuralParameter"',
     '<Boolean name="XCP.TCP.Enable" valueReference="1" causality="parameter"', None),
    ('causality="structuralParameter" variability="fixed" start="5555"',
     'causality="structuralParameter" variability="tunable" start="5555"', "tunable structuralParameter"),
    ('<Int32 name="counter" valueReference="4" causality="output" variability="discrete" initial="exact" start="0"/>',
     '<Int32 name="counter" valueReference="4" causality="output" variability="discrete" initial="exact" start="0"/>'
     '<UInt16 name="XCP.TCP.Port2" valueReference="5" causality="input" variability="discrete" start="1"/>',
     "discrete input"),
    ('causality="structuralParameter" variability="fixed" start="5555"/>',
     'causality="structuralParameter" variability="fixed" start="5555 5556"><Dimension start="2"/></UInt16>',
     "must be a scalar"),
])
def test_variables_fmi3(stub3, old, new, expected):
    path = _patched(stub3, MODEL, old, new)
    if "XCP.TCP.Port2" in new:
        path = _patched(path, MANIFEST, 'name="XCP.TCP.Port"', 'name="XCP.TCP.Port2"')
    errors = _errors(path)
    if expected is None:
        assert errors == []
    else:
        assert _has(errors, expected)


@pytest.mark.parametrize("old, new, expected", [
    ("<Integer start=\"5555\"/>", "<Real start=\"5555\"/>", "must be a Integer, not a Real"),
    ('name="XCP.TCP.Enable" valueReference="1" causality="parameter" variability="fixed"',
     'name="XCP.TCP.Enable" valueReference="1" causality="output" variability="constant"', None),
    ('name="XCP.TCP.Port" valueReference="2" causality="parameter" variability="fixed"',
     'name="XCP.TCP.Port" valueReference="2" causality="calculatedParameter" variability="tunable"', None),
    ('name="XCP.TCP.Port" valueReference="2" causality="parameter" variability="fixed"',
     'name="XCP.TCP.Port" valueReference="2" causality="parameter" variability="tunable"', "tunable parameter"),
])
def test_variables_fmi2(tmp_path, old, new, expected):
    source = zip_fmu(DATA_DIR / "ls-xcp" / "stub_xcp_fmi2", tmp_path / "stub.fmu")
    errors = _errors(_patched(source, MODEL, old, new))
    if expected is None:
        assert errors == []
    else:
        assert _has(errors, expected)
