"""Integration tests for nested terminals in LS-BUS containers: a Bus Terminal inside a grouping terminal is
designated by its full path, in the assembly and in the assembly read back by `fmusplit`.
"""
import json
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.container import FMUContainerError
from fmu_manipulation_toolbox.split import FMUSplitter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.lsbus,
    pytest.mark.fmi3,
    pytest.mark.needs_container,
    pytest.mark.area("ls-bus"),
]

TERMINALS = "terminalsAndIcons/terminalsAndIcons.xml"


def _group_terminals(filename: str, group: str):
    """Move all the terminals of an FMU into a grouping terminal, in place."""
    source = Path(filename)
    patched = source.with_suffix(".tmp")
    with zipfile.ZipFile(source) as zip_in, zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as zip_out:
        for item in zip_in.infolist():
            data = zip_in.read(item.filename)
            if item.filename == TERMINALS:
                data = (data.decode()
                        .replace("<Terminals>", f'<Terminals><Terminal name="{group}" matchingRule="none">')
                        .replace("</Terminals>", "</Terminal></Terminals>")
                        .encode())
            zip_out.writestr(item, data)
    patched.replace(source)


def _assembly(links) -> Assembly:
    Path("nested.json").write_text(json.dumps({"name": "nested.fmu", "fmu": ["bus.fmu", "node1.fmu", "node2.fmu"],
                                               "link": links, "step_size": 0.1}))
    return Assembly("nested.json")


def test_nested_bus_terminals_by_full_path(area_dir):
    _group_terminals("bus.fmu", "Seg1")
    _assembly([["node1.fmu", "CanChannel", "bus.fmu", "Seg1.Node1"],
               ["node2.fmu", "CanChannel", "bus.fmu", "Seg1.Node2"]]).make_fmu(fmi_version=3)

    FMUSplitter("nested.fmu").split_fmu()
    config = json.loads(Path("nested.dir/nested.json").read_text())
    assert sorted(config["link"]) == [["bus.fmu", "Seg1.Node1", "node1.fmu", "CanChannel"],
                                      ["bus.fmu", "Seg1.Node2", "node2.fmu", "CanChannel"]]


def test_nested_bus_terminal_by_bare_name_is_refused(area_dir):
    _group_terminals("bus.fmu", "Seg1")
    with pytest.raises(FMUContainerError, match="full path: Seg1.Node1"):
        _assembly([["node1.fmu", "CanChannel", "bus.fmu", "Node1"]]).make_fmu(fmi_version=3)


def test_grouping_terminal_with_a_missing_sub_terminal_is_refused(area_dir):
    _group_terminals("bus.fmu", "Seg1")
    _group_terminals("node1.fmu", "Seg1")
    with pytest.raises(FMUContainerError, match="has no peer"):
        _assembly([["node1.fmu", "Seg1", "bus.fmu", "Seg1"]]).make_fmu(fmi_version=3)


# --------------------------------------------------------------------------- #
#                       parameters of Configuration terminals                   #
# --------------------------------------------------------------------------- #
def _add_bus_notifications(filename: str, terminal: str, attributes: str):
    """Add a Boolean variable `BusNotifications` to the Configuration terminal of a Bus Terminal, in place."""
    configuration = ('<Terminal terminalKind="org.fmi-ls-bus.network-terminal.configuration" name="Configuration" '
                     'matchingRule="bus"><TerminalMemberVariable variableKind="signal" '
                     'variableName="BusNotifications" memberName="BusNotifications"/></Terminal>')
    source = Path(filename)
    patched = source.with_suffix(".tmp")
    with zipfile.ZipFile(source) as zip_in, zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as zip_out:
        for item in zip_in.infolist():
            data = zip_in.read(item.filename)
            if item.filename == TERMINALS:
                text = data.decode()
                end = text.index("</Terminal>", text.index(f'name="{terminal}"'))
                data = (text[:end] + configuration + text[end:]).encode()
            elif item.filename == "modelDescription.xml":
                variable = f'<Boolean name="BusNotifications" valueReference="9000" {attributes}/>'
                data = data.decode().replace("</ModelVariables>", f"{variable}</ModelVariables>").encode()
            zip_out.writestr(item, data)
    patched.replace(source)


NODE_PARAMETER = 'causality="parameter" variability="fixed" start="false"'


def _start_value_of_node(assembly_data=None) -> str | None:
    config = {"name": "parameters.fmu", "fmu": ["bus.fmu", "node1.fmu"],
              "link": [["node1.fmu", "CanChannel", "bus.fmu", "Node1"]], "step_size": 0.1, **(assembly_data or {})}
    Path("parameters.json").write_text(json.dumps(config))
    Assembly("parameters.json").make_fmu(fmi_version=3)
    with zipfile.ZipFile("parameters.fmu") as archive:
        name = next(name for name in archive.namelist() if name.endswith("container.txt"))
        lines = archive.read(name).decode().splitlines()
    start = lines.index(next(line for line in lines if line.startswith("# Start values of node1.fmu - boolean1:")))
    return None if lines[start + 1] == "0 0" else lines[start + 2].split()[-1]


def test_value_of_the_bus_known_at_build_time_is_propagated(area_dir):
    _add_bus_notifications("node1.fmu", "CanChannel", NODE_PARAMETER)
    _add_bus_notifications("bus.fmu", "Node1", 'causality="output" variability="constant" start="true"')
    assert _start_value_of_node() == "1"


def test_value_of_the_bus_known_at_runtime_only_gives_a_warning(area_dir, caplog):
    _add_bus_notifications("node1.fmu", "CanChannel", NODE_PARAMETER)
    _add_bus_notifications("bus.fmu", "Node1", 'causality="calculatedParameter" variability="fixed"')
    assert _start_value_of_node() is None
    assert "known at runtime only" in caplog.text


def test_start_value_of_the_user_is_kept(area_dir):
    _add_bus_notifications("node1.fmu", "CanChannel", NODE_PARAMETER)
    _add_bus_notifications("bus.fmu", "Node1", 'causality="output" variability="constant" start="true"')
    assert _start_value_of_node({"start": [["node1.fmu", "BusNotifications", "false"]]}) == "0"


def test_node_without_the_parameter_is_not_an_error(area_dir, caplog):
    _add_bus_notifications("bus.fmu", "Node1", 'causality="output" variability="constant" start="true"')
    assert _start_value_of_node() is None
    assert "BusNotifications" not in caplog.text


# --------------------------------------------------------------------------- #
#                         clocks of a Bus Simulation                            #
# --------------------------------------------------------------------------- #
def _patch_model_description(filename: str, old: str, new: str):
    source = Path(filename)
    patched = source.with_suffix(".tmp")
    with zipfile.ZipFile(source) as zip_in, zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as zip_out:
        for item in zip_in.infolist():
            data = zip_in.read(item.filename)
            if item.filename == "modelDescription.xml":
                text = data.decode()
                assert old in text
                data = text.replace(old, new).encode()
            zip_out.writestr(item, data)
    patched.replace(source)


def _clock_inputs(fmu_name: str) -> list[str]:
    """`<LOCAL_OFFSET> <DIM> <FMU_VR>` of the clocks set by the container to an FMU."""
    with zipfile.ZipFile("clocks.fmu") as archive:
        name = next(name for name in archive.namelist() if name.endswith("container.txt"))
        lines = archive.read(name).decode().splitlines()
    start = lines.index(next(line for line in lines if line.startswith(f"# Inputs of {fmu_name} - clock:")))
    return lines[start + 2:start + 2 + int(lines[start + 1])]


def _build_clocks():
    Path("clocks.json").write_text(json.dumps({"name": "clocks.fmu", "fmu": ["bus.fmu", "node1.fmu"],
                                               "link": [["node1.fmu", "CanChannel", "bus.fmu", "Node1"]],
                                               "step_size": 0.1}))
    Assembly("clocks.json").make_fmu(fmi_version=3)


TX_CLOCK = '<Clock name="CanChannel.Tx_Clock" valueReference="3" causality="{}" intervalVariability="{}" />'


def test_rx_clock_of_a_bus_is_fed_by_a_countdown_tx_clock_of_a_node(area_dir):
    _patch_model_description("node1.fmu", TX_CLOCK.format("output", "triggered"), TX_CLOCK.format("input", "countdown"))
    _build_clocks()
    assert [line.split()[-1] for line in _clock_inputs("bus.fmu")] == ["2"]  # Rx_Clock of Node1
    assert _clock_inputs("node1.fmu") != []
    assert not any(line.split()[-1] == "3" for line in _clock_inputs("node1.fmu"))  # Tx_Clock: by the schedule


def test_countdown_tx_clock_of_a_bus_is_activated_by_the_schedule_only(area_dir):
    _build_clocks()
    assert [line.split()[-1] for line in _clock_inputs("bus.fmu")] == ["2"]  # Not its Tx_Clock (3)


# --------------------------------------------------------------------------- #
#                                MIME types                                     #
# --------------------------------------------------------------------------- #
CAN_MIME = "application/org.fmi-standard.fmi-ls-bus.can; version=&quot;1.0.0-beta.1&quot;"


def test_link_between_different_types_of_bus_is_refused(area_dir):
    _patch_model_description("node1.fmu", CAN_MIME, CAN_MIME.replace(".can;", ".lin;"))
    with pytest.raises(FMUContainerError, match="different LS-BUS types .*can.*lin|different LS-BUS types .*lin.*can"):
        _build_clocks()


def test_link_between_different_versions_of_a_bus_gives_a_warning(area_dir, caplog):
    _patch_model_description("node1.fmu", CAN_MIME, CAN_MIME.replace("1.0.0-beta.1", "1.0.0"))
    _build_clocks()
    assert "different versions of LS-BUS can" in caplog.text


def test_same_mime_type_gives_no_warning(area_dir, caplog):
    _build_clocks()
    assert "LS-BUS can" not in caplog.text


def test_binary_outside_of_ls_bus_is_not_checked(area_dir, caplog):
    _patch_model_description("node1.fmu", CAN_MIME, "application/octet-stream")
    _build_clocks()
    assert "LS-BUS" not in caplog.text.replace("LS-BUS: importer", "")

