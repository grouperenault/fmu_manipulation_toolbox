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
