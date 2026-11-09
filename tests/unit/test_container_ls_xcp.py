"""Containers of FMUs of FMI-LS-XCP.

The stub FMUs of `tests/data/ls-xcp` (descriptor, manifest and A2L files, without binaries) are enough to build the
container: the runtime is checked by the native tests (`container/tests/test_xcp_container.c`).
"""
from pathlib import Path

import logging
import xml.etree.ElementTree as ET
import zipfile

import pytest

from _helpers.archive import read_entry, rewrite_fmu, zip_fmu
from fmu_manipulation_toolbox.checker import OperationLsXcpCheck
from fmu_manipulation_toolbox.container import FMUContainer, FMUContainerError
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [pytest.mark.unit, pytest.mark.lsxcp]

DATA_DIR = Path(__file__).parent.parent / "data" / "ls-xcp"


MANIFEST = "extra/org.fmi-standard.fmi-ls-xcp/fmi-ls-manifest.xml"
#: Empty binaries of the stub FMUs, so that the container is built for the three OS (the archives of
#: tests/data/ls-xcp have no binaries).
BINARIES = {2: ("win64/stub_xcp.dll", "linux64/stub_xcp.so", "darwin64/stub_xcp.dylib"),
            3: ("x86_64-windows/stub_xcp.dll", "x86_64-linux/stub_xcp.so", "aarch64-darwin/stub_xcp.dylib")}


@pytest.fixture
def xcp_dir(tmp_path, monkeypatch) -> Path:
    for version in (2, 3):
        archive = zip_fmu(DATA_DIR / f"stub_xcp_fmi{version}", tmp_path / "tmp.fmu")
        rewrite_fmu(archive, tmp_path / f"stub_xcp_fmi{version}.fmu",
                    replace={f"binaries/{binary}": b"" for binary in BINARIES[version]})
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _patch_manifest(xcp_dir: Path, version: int, old: str, new: str):
    filename = xcp_dir / f"stub_xcp_fmi{version}.fmu"
    text = read_entry(filename, MANIFEST).decode()
    assert old in text
    rewrite_fmu(filename, xcp_dir / "patched.fmu", replace={MANIFEST: text.replace(old, new).encode()})
    (xcp_dir / "patched.fmu").replace(filename)


def _variables(model_description: str) -> dict[str, ET.Element]:
    root = ET.fromstring(model_description)
    return {element.get("name"): element for element in root.find("ModelVariables")}


def _manifest(filename: str) -> ET.Element:
    return ET.fromstring(read_entry(filename, MANIFEST))


def _container_txt(container: FMUContainer, name: str = "container") -> list[str]:
    container.make_fmu(f"{name}.fmu", step_size=0.1, debug=True)
    return Path(f"{name}/resources/container.txt").read_text().splitlines()


def _start_values(lines: list[str], type_name: str) -> list[str]:
    header = next(i for i, line in enumerate(lines) if line.startswith("# Start values of") and
                  line.endswith(f"- {type_name}: <FMU_VR> <DIM> <RESET> <VALUE>"))
    nb = int(lines[header + 1].split()[0])
    return lines[header + 2:header + 2 + nb]


def test_structural_parameter_is_set_in_configuration_mode(xcp_dir):
    container = FMUContainer("xcp", xcp_dir, fmi_version=3)
    container.get_fmu("stub_xcp_fmi3.fmu")
    container.add_start_value("stub_xcp_fmi3.fmu", "XCP.TCP.Port", "6000")
    lines = _container_txt(container)
    assert "stub_xcp_fmi3.fmu 3 0 1" in lines           # <has_configuration_mode>
    assert _start_values(lines, "uinteger16") == ["2 1 2 6000"]


def test_parameter_has_no_configuration_mode(xcp_dir):
    container = FMUContainer("xcp", xcp_dir)
    container.get_fmu("stub_xcp_fmi2.fmu")
    container.add_start_value("stub_xcp_fmi2.fmu", "XCP.TCP.Port", "6002")
    lines = _container_txt(container)
    assert "stub_xcp_fmi2.fmu 2 0 0" in lines
    assert _start_values(lines, "integer32") == ["2 1 0 6002"]


# --------------------------------------------------------------------------- #
#                     Forwarding of the XCP services                            #
# --------------------------------------------------------------------------- #
def test_fmi3_container_forwards_the_xcp_service(xcp_dir):
    container = FMUContainer("xcp", xcp_dir, fmi_version=3)
    container.get_fmu("stub_xcp_fmi3.fmu")
    wired = container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
    assert wired.nb_param == 3
    lines = _container_txt(container)

    variables = _variables(Path("container/modelDescription.xml").read_text())
    for name in ("stub_xcp_fmi3.XCP.TCP.Enable", "stub_xcp_fmi3.XCP.TCP.Port", "stub_xcp_fmi3.XCP.TCP.ListenAddress"):
        assert variables[name].get("causality") == "structuralParameter"
    assert "stub_xcp_fmi3.fmu 3 0 1" in lines
    assert _start_values(lines, "uinteger16") == ["2 1 2 5555"]       # default start values, in Configuration Mode
    assert _start_values(lines, "boolean1") == ["1 1 2 1"]

    manifest = _manifest("container.fmu")
    (interface,) = manifest.findall("Interface")
    assert interface.get("definition") == "stub_xcp_fmi3/ecu.a2l"
    assert interface.get("containsXCPService") == "true"
    assert {variable.get("role"): variable.get("name") for variable in interface} == {
        "XCPServiceTCPEnable": "stub_xcp_fmi3.XCP.TCP.Enable",
        "XCPServiceTCPPort": "stub_xcp_fmi3.XCP.TCP.Port",
        "XCPServiceTCPListenAddress": "stub_xcp_fmi3.XCP.TCP.ListenAddress"}
    with zipfile.ZipFile("container.fmu") as archive:
        a2l = {name for name in archive.namelist() if name.endswith(".a2l") and name.startswith("extra/")}
    assert a2l == {f"extra/org.fmi-standard.fmi-ls-xcp/{platform}/stub_xcp_fmi3/ecu.a2l"
                   for platform in ("x86_64-windows", "x86_64-linux", "aarch64-darwin")}


@pytest.mark.parametrize("fmi_version", [2, 3])
def test_container_follows_the_standard(xcp_dir, fmi_version, caplog):
    container = FMUContainer("xcp", xcp_dir, fmi_version=fmi_version)
    container.get_fmu("stub_xcp_fmi2.fmu")
    container.get_fmu("stub_xcp_fmi3.fmu")
    container.add_start_value("stub_xcp_fmi3.fmu", "XCP.TCP.Port", "6000")
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
        container.make_fmu("container.fmu", step_size=0.1)
    # The port of the FMU of the other FMI version is not exposed (its type would not be the one of the role)
    assert "XCP.TCP.Port (XCPServiceTCPPort) is not exposed" in caplog.text
    check = OperationLsXcpCheck()
    with FMU("container.fmu") as fmu:
        fmu.apply_operation(check)
    assert check.errors == []
    assert len(_manifest("container.fmu").findall("Interface")) == 2


def test_fmi2_container(xcp_dir, caplog):
    container = FMUContainer("xcp", xcp_dir, fmi_version=2)
    container.get_fmu("stub_xcp_fmi2.fmu")
    container.get_fmu("stub_xcp_fmi3.fmu")
    container.add_start_value("stub_xcp_fmi3.fmu", "XCP.TCP.Port", "6000")
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
    # FMI-3.0 UInt16 and Boolean: no such type in an FMI-2.0 container
    assert "container would expose it as uinteger16, FMI-LS-XCP needs Integer" in caplog.text
    assert "container would expose it as boolean1, FMI-LS-XCP needs Boolean" in caplog.text
    lines = _container_txt(container)

    variables = _variables(Path("container/modelDescription.xml").read_text())
    assert variables["stub_xcp_fmi2.XCP.TCP.Port"].get("causality") == "parameter"
    assert variables["stub_xcp_fmi3.XCP.TCP.ListenAddress"].get("causality") == "parameter"  # structural in the FMU
    assert "stub_xcp_fmi3.XCP.TCP.Port" not in variables
    assert "stub_xcp_fmi2.fmu 2 0 0" in lines and "stub_xcp_fmi3.fmu 3 0 1" in lines
    roles = {interface.get("definition"): {variable.get("role") for variable in interface}
             for interface in _manifest("container.fmu").findall("Interface")}
    assert roles["stub_xcp_fmi3/ecu.a2l"] == {"XCPServiceTCPListenAddress"}
    with zipfile.ZipFile("container.fmu") as archive:
        assert "extra/org.fmi-standard.fmi-ls-xcp/linux64/stub_xcp_fmi3/ecu.a2l" in archive.namelist()


def test_variable_exposed_by_a_rule_keeps_its_name(xcp_dir):
    container = FMUContainer("xcp", xcp_dir, fmi_version=3)
    container.get_fmu("stub_xcp_fmi3.fmu")
    container.add_input("xcp_port", "stub_xcp_fmi3.fmu", "XCP.TCP.Port")
    container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
    container.make_fmu("container.fmu", step_size=0.1)
    names = {variable.get("role"): variable.get("name") for variable in _manifest("container.fmu").iter("Variable")}
    assert names["XCPServiceTCPPort"] == "xcp_port"


def test_structural_parameter_giving_a_dimension_is_refused(xcp_dir):
    filename = xcp_dir / "stub_xcp_fmi3.fmu"
    text = read_entry(filename, "modelDescription.xml").decode()
    text = text.replace('<Int32 name="counter" valueReference="4" causality="output" variability="discrete" '
                        'initial="exact" start="0"/>',
                        '<Int32 name="counter" valueReference="4" causality="output" variability="discrete" '
                        'initial="exact" start="0"><Dimension valueReference="2"/></Int32>')
    rewrite_fmu(filename, xcp_dir / "dim.fmu", replace={"modelDescription.xml": text.encode()})
    container = FMUContainer("xcp", xcp_dir, fmi_version=3)
    with pytest.raises(Exception, match="gives the dimension|depends on structuralParameter"):
        container.get_fmu("dim.fmu")
        container.add_input("xcp_port", "dim.fmu", "XCP.TCP.Port")


# --------------------------------------------------------------------------- #
#                                Port conflicts                                 #
# --------------------------------------------------------------------------- #
def _two_instances(xcp_dir) -> FMUContainer:
    container = FMUContainer("xcp", xcp_dir, fmi_version=3)
    container.get_fmu("stub_xcp_fmi3.fmu", "ecu1.fmu")
    container.get_fmu("stub_xcp_fmi3.fmu", "ecu2.fmu")
    return container


def test_two_services_on_the_same_port_are_refused(xcp_dir):
    container = _two_instances(xcp_dir)
    container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
    with pytest.raises(FMUContainerError, match="'ecu1.fmu' and 'ecu2.fmu'.*same TCP port 5555"):
        container.make_fmu("container.fmu", step_size=0.1)


def test_two_services_on_different_ports(xcp_dir):
    container = _two_instances(xcp_dir)
    container.add_start_value("ecu2.fmu", "XCP.TCP.Port", "5556")
    container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
    container.make_fmu("container.fmu", step_size=0.1)
    assert [interface.get("definition") for interface in _manifest("container.fmu").findall("Interface")] == \
        ["ecu1/ecu.a2l", "ecu2/ecu.a2l"]


def test_disabled_service_is_not_in_conflict(xcp_dir):
    container = _two_instances(xcp_dir)
    container.add_start_value("ecu2.fmu", "XCP.TCP.Enable", "false")
    container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
    container.make_fmu("container.fmu", step_size=0.1)


def test_port_of_the_a2l_file(xcp_dir):
    """Without a variable for the port, the port is the one of the IF_DATA XCP of the A2L file (5555)."""
    _patch_manifest(xcp_dir, 3, '<Variable name="XCP.TCP.Port" role="XCPServiceTCPPort"/>', "")
    container = _two_instances(xcp_dir)
    container.add_start_value("ecu2.fmu", "XCP.TCP.ListenAddress", "127.0.0.2")    # same port anyway
    container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
    with pytest.raises(FMUContainerError, match="same TCP port 5555"):
        container.make_fmu("container.fmu", step_size=0.1)


def test_direct_memory_access_is_not_forwarded(xcp_dir, caplog):
    _patch_manifest(xcp_dir, 3, 'containsXCPService="true"', 'supportsDirectMemoryAccess="true"')
    container = FMUContainer("xcp", xcp_dir, fmi_version=3)
    container.get_fmu("stub_xcp_fmi3.fmu")
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        wired = container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
    assert wired.nb_param == 0
    assert "only supports direct memory access" in caplog.text
    container.make_fmu("container.fmu", step_size=0.1)
    assert read_entry("container.fmu", MANIFEST) is None


def test_read_only_role_is_not_exposed(xcp_dir, caplog):
    filename = xcp_dir / "stub_xcp_fmi3.fmu"
    text = read_entry(filename, "modelDescription.xml").decode()
    text = text.replace('causality="structuralParameter" variability="fixed" start="5555"',
                        'causality="output" variability="constant" start="5555"')
    rewrite_fmu(filename, xcp_dir / "constant.fmu", replace={"modelDescription.xml": text.encode()})
    container = FMUContainer("xcp", xcp_dir, fmi_version=3)
    container.get_fmu("constant.fmu")
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        wired = container.add_implicit_rule(auto_input=False, auto_output=False, auto_link=False)
    assert wired.nb_param == 2
    assert "only announces the configuration" in caplog.text


# --------------------------------------------------------------------------- #
#                            Assembly: JSON and SSP                             #
# --------------------------------------------------------------------------- #
def test_ssp_round_trip(xcp_dir):
    """The exposed variables are rules of the assembly: the SSP export keeps them, as structural parameters."""
    import json
    from fmu_manipulation_toolbox.assembly import Assembly

    Path("xcp.json").write_text(json.dumps({"name": "xcp.fmu", "fmu": ["stub_xcp_fmi3.fmu"], "auto_input": False}))
    assembly = Assembly("xcp.json")
    assembly.make_fmu(fmi_version=3)
    assembly.write_ssp("xcp.ssp")
    ssd = read_entry("xcp.ssp", "SystemStructure.ssd").decode()
    assert '<ssd:Connector name="stub_xcp_fmi3.XCP.TCP.Port" kind="structuralParameter">' in ssd

    Assembly("xcp.ssp").make_fmu(fmi_version=3, filename="back.fmu")
    names = {variable.get("role"): variable.get("name") for variable in _manifest("back.fmu").iter("Variable")}
    assert names == {"XCPServiceTCPEnable": "stub_xcp_fmi3.XCP.TCP.Enable",
                     "XCPServiceTCPPort": "stub_xcp_fmi3.XCP.TCP.Port",
                     "XCPServiceTCPListenAddress": "stub_xcp_fmi3.XCP.TCP.ListenAddress"}
