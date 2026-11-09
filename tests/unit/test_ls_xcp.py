"""Reading of FMI-LS-XCP: manifest (`LayeredStandard`) and XCP settings of the A2L files (`read_xcp_settings`)."""
import shutil
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.ls import LayeredStandard, XcpSettings, read_xcp_settings

pytestmark = [pytest.mark.unit, pytest.mark.lsxcp]

DATA_DIR = Path(__file__).parent.parent / "data" / "ls-xcp"
XCP_DIR = Path("extra") / "org.fmi-standard.fmi-ls-xcp"

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<fmiLayeredStandardManifest
    xmlns:fmi-ls="http://fmi-standard.org/fmi-ls-manifest"
    fmi-ls:fmi-ls-name="org.fmi-standard.fmi-ls-xcp"
    fmi-ls:fmi-ls-version="1.0.0"
    fmi-ls:fmi-ls-description="XCP">
    <Interface definition="ecu.a2l" description="vECU" containsXCPService="true">
        <Variable name="XCP.TCP.Enable" role="XCPServiceTCPEnable"/>
        <Variable name="XCP.TCP.Port" role="XCPServiceTCPPort"/>
    </Interface>
    <Interface definition="mem.a2l" types="ModelExchange CoSimulation" supportsDirectMemoryAccess="true"/>
</fmiLayeredStandardManifest>
"""


def _fmu_directory(tmp_path: Path, manifest: str = MANIFEST) -> Path:
    xcp = tmp_path / XCP_DIR
    xcp.mkdir(parents=True)
    (xcp / "fmi-ls-manifest.xml").write_text(manifest)
    return tmp_path


def test_fmu_without_ls_xcp(tmp_path):
    ls = LayeredStandard(tmp_path)
    assert ls.standards == []
    assert ls.xcp_interfaces == []


def test_manifest_is_read(tmp_path):
    ls = LayeredStandard(_fmu_directory(tmp_path))
    assert ls.standards == ["LS-XCP"]
    assert ls.xcp_version == "1.0.0"
    ecu, mem = ls.xcp_interfaces
    assert ecu.definition == "ecu.a2l"
    assert ecu.description == "vECU"
    assert ecu.contains_xcp_service and not ecu.supports_direct_memory_access
    assert ecu.variables == {"XCPServiceTCPEnable": "XCP.TCP.Enable", "XCPServiceTCPPort": "XCP.TCP.Port"}
    assert ecu.types is None and ecu.applies_to("CoSimulation")
    assert mem.supports_direct_memory_access and not mem.contains_xcp_service
    assert mem.types == ["ModelExchange", "CoSimulation"]
    assert mem.applies_to("ModelExchange") and not mem.applies_to("ScheduledExecution")


def test_broken_manifest_is_reported(tmp_path, caplog):
    ls = LayeredStandard(_fmu_directory(tmp_path, "<broken"))
    assert ls.standards == ["LS-XCP"]
    assert ls.xcp_interfaces == []
    assert "Cannot parse the manifest of LS-XCP" in caplog.text


def test_a2l_files_per_platform(tmp_path):
    ls = LayeredStandard(_fmu_directory(tmp_path))
    xcp = ls.xcp_directory
    for platform in ("x86_64-windows", "x86_64-linux"):
        (xcp / platform).mkdir()
        shutil.copy(DATA_DIR / "ecu.a2l", xcp / platform / "ecu.a2l")
    shutil.copy(DATA_DIR / "ecu.a2l", xcp / "ecu.a2l")
    files = ls.xcp_interfaces[0].a2l_files(xcp)
    assert files == {None: xcp / "ecu.a2l",
                     "x86_64-linux": xcp / "x86_64-linux" / "ecu.a2l",
                     "x86_64-windows": xcp / "x86_64-windows" / "ecu.a2l"}
    assert ls.xcp_interfaces[1].a2l_files(xcp) == {}


def test_xcp_settings_of_a2l():
    assert read_xcp_settings(DATA_DIR / "ecu.a2l") == {"TCP": XcpSettings(5555, "127.0.0.1"),
                                                       "UDP": XcpSettings(5556, "localhost")}


@pytest.mark.parametrize("text, expected", [
    ("", {}),
    ('/begin IF_DATA CANAPE /begin XCP_ON_TCP_IP 0x0104 1234 /end XCP_ON_TCP_IP /end IF_DATA', {}),
    ('/begin IF_DATA XCPplus /begin XCP_ON_UDP_IP 0x0104 1234 /end XCP_ON_UDP_IP /end IF_DATA',
     {"UDP": XcpSettings(1234, None)}),
    ('/begin IF_DATA XCP /begin XCP_ON_TCP_IP 0x0104 1234 IPV6 "::1" /end XCP_ON_TCP_IP /end IF_DATA',
     {"TCP": XcpSettings(1234, "::1")}),
    ('/begin IF_DATA XCP /* /begin XCP_ON_TCP_IP 0x0104 1 */ /end IF_DATA', {}),
    ('/begin IF_DATA XCP /begin XCP_ON_TCP_IP 0x0104 1 /end XCP_ON_TCP_IP '
     '/begin XCP_ON_TCP_IP 0x0104 2 /end XCP_ON_TCP_IP /end IF_DATA', {"TCP": XcpSettings(1, None)}),
    ('/begin IF_DATA XCP /begin XCP_ON_TCP_IP 0x0104 port /end XCP_ON_TCP_IP /end IF_DATA',
     {"TCP": XcpSettings(None, None)}),
], ids=["empty", "other-if-data", "xcpplus", "ipv6", "comment", "first-block", "bad-port"])
def test_xcp_settings_variants(tmp_path, text, expected):
    a2l = tmp_path / "x.a2l"
    a2l.write_text(text)
    assert read_xcp_settings(a2l) == expected
