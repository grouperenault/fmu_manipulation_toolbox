"""`datalog2pcap`: the operations of the four types of bus, one packet each, for the Wireshark plugin of FMI-LS-BUS.

The container gives the type of bus of the columns of the CSV. Reading the captures back here checks their structure;
the dissection by the plugin itself is checked when Wireshark is installed.
"""
import json
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.cli.datalog2pcap import DatalogConverter, DatalogError, datalog2pcap

pytestmark = [
    pytest.mark.integration,
    pytest.mark.lsbus,
    pytest.mark.fmi3,
    pytest.mark.needs_container,
    pytest.mark.area("ls-bus"),
]

CAN_MIME = "fmi-ls-bus.can;"
#: Two operations of each type of bus in a single binary: their opcodes and lengths are what matters here.
OPERATION_1 = struct.pack("<II", 0x10, 12) + b"\x01\x02\x03\x04"
OPERATION_2 = struct.pack("<II", 0x20, 9) + b"\x05"
PLUGIN = Path(__file__).parent.parent / "data" / "ls-bus-spec" / "fmi_ls_bus.lua"
TSHARK = shutil.which("tshark") or (
    "/Applications/Wireshark.app/Contents/MacOS/tshark"
    if Path("/Applications/Wireshark.app/Contents/MacOS/tshark").exists() else None)


def _set_bus(filename: str, bus: str):
    source = Path(filename)
    patched = source.with_suffix(".tmp")
    with zipfile.ZipFile(source) as zip_in, zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as zip_out:
        for item in zip_in.infolist():
            data = zip_in.read(item.filename)
            if item.filename == "modelDescription.xml":
                data = data.decode().replace(CAN_MIME, f"fmi-ls-bus.{bus};").encode()
            zip_out.writestr(item, data)
    patched.replace(source)


def _build_container(bus="can") -> str:
    for filename in ("node1.fmu", "node2.fmu"):
        _set_bus(filename, bus)
    Assembly("nodes-only.json").make_fmu(fmi_version=3, datalog=True)
    return "nodes-only.fmu"


def _write_csv(data: bytes, clock="1") -> str:
    Path("datalog.csv").write_text("time,node1.CanChannel.Tx_Data,node1.CanChannel.Tx_Clock\n"
                                   f"1.5,{data.hex().upper()},{clock}\n"
                                   f"2.25,{OPERATION_1.hex().upper()},0\n")
    return "datalog.csv"


def _read_packets(filename) -> list[tuple[int, str, bytes]]:
    """(microseconds, PROTO_NAME, operation) of each Enhanced Packet Block."""
    data = Path(filename).read_bytes()
    packets = []
    offset = 0
    link_type = None
    while offset < len(data):
        block_type, length = struct.unpack_from("<II", data, offset)
        assert length % 4 == 0
        assert struct.unpack_from("<I", data, offset + length - 4)[0] == length
        if block_type == 0x0A0D0D0A:
            assert struct.unpack_from("<I", data, offset + 8)[0] == 0x1A2B3C4D
        elif block_type == 1:
            link_type = struct.unpack_from("<H", data, offset + 8)[0]
        elif block_type == 6:
            high, low, captured, original = struct.unpack_from("<IIII", data, offset + 12)
            assert captured == original
            packet = data[offset + 28:offset + 28 + captured]
            tag, tag_length = struct.unpack_from(">HH", packet, 0)
            assert tag == 12
            name = packet[4:4 + tag_length].rstrip(b"\0").decode()
            assert struct.unpack_from(">HH", packet, 4 + tag_length) == (0, 0)
            packets.append(((high << 32) | low, name, packet[8 + tag_length:]))
        else:
            pytest.fail(f"unexpected block {block_type:#x}")
        offset += length
    assert link_type == 252
    return packets


@pytest.mark.parametrize("bus, protocol", [("can", "fmi_ls_bus_can"), ("lin", "fmi_ls_bus_lin"),
                                           ("flexray", "fmi_ls_bus_flexray"), ("ethernet", "fmi_ls_bus_eth")])
def test_operations_of_each_bus(area_dir, bus, protocol):
    fmu = _build_container(bus)
    sys.argv = ["datalog2pcap", _write_csv(OPERATION_1 + OPERATION_2), "-fmu", fmu]
    datalog2pcap()
    # Two operations of the first row, nothing for the second one: its clock is not active.
    assert _read_packets("datalog.pcapng") == [(1500000, protocol, OPERATION_1), (1500000, protocol, OPERATION_2)]


def test_truncated_operation_is_reported(area_dir, caplog):
    fmu = _build_container()
    DatalogConverter(_write_csv(OPERATION_1 + struct.pack("<II", 0x20, 99)), fmu).convert()
    assert _read_packets("datalog.pcapng") == [(1500000, "fmi_ls_bus_can", OPERATION_1)]
    assert "invalid length 99" in caplog.text


def test_csv_without_ls_bus_column_is_refused(area_dir):
    fmu = _build_container()
    Path("other.csv").write_text("time,x\n0,1\n")
    with pytest.raises(DatalogError, match="No column"):
        DatalogConverter("other.csv", fmu).convert()


def test_missing_container_is_refused(area_dir):
    with pytest.raises(DatalogError, match="Cannot read the container"):
        DatalogConverter(_write_csv(OPERATION_1), "missing.fmu").convert()


def test_can_option_is_removed(area_dir):
    sys.argv = ["datalog2pcap", "-can", "datalog.csv"]
    with pytest.raises(SystemExit):
        datalog2pcap()


@pytest.mark.skipif(TSHARK is None, reason="Wireshark is not installed")
@pytest.mark.parametrize("bus, protocol", [("can", "fmi_ls_bus_can"), ("lin", "fmi_ls_bus_lin"),
                                           ("flexray", "fmi_ls_bus_flexray"), ("ethernet", "fmi_ls_bus_eth")])
def test_capture_is_dissected_by_the_plugin(area_dir, bus, protocol):
    fmu = _build_container(bus)
    DatalogConverter(_write_csv(OPERATION_1), fmu).convert()
    output = subprocess.run([TSHARK, "-X", f"lua_script:{PLUGIN}", "-r", "datalog.pcapng", "-T", "fields",
                             "-e", "frame.protocols", "-e", "_ws.col.Protocol", "-e", "_ws.col.Info"],
                            capture_output=True, text=True, check=True).stdout
    assert protocol in output
    assert "FMI-LS-BUS" in output
