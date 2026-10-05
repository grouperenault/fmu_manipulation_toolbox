"""Tests for the headless assembly bridge (``fmutool-mcp`` backend).

The unit tests in ``test_assistant_server.py`` pin the MCP contract against a
fake bridge; these ones check that the **real** GUI-less backend applies what
the tools ask for, using actual FMU files.

Audit reference: B2/I7 — the assistant used to exist only while the Container
Builder GUI was running, and re-implemented assembly by driving a Qt scene
instead of using the public ``Assembly`` API.
"""
import json
from typing import Any

import pytest

pytestmark = [pytest.mark.unit]

from fmu_manipulation_toolbox.assembly import AssemblyError  # noqa: E402
from fmu_manipulation_toolbox.assistant import AssemblyBridge  # noqa: E402
from fmu_manipulation_toolbox.assistant.headless import (  # noqa: E402
    DEFAULT_OPTIONS, HeadlessAssemblyBridge, describe_fmu,
)


@pytest.fixture
def ball(data_dir):
    """Directory holding the two bouncing-ball FMUs."""
    return data_dir / "containers" / "bouncing_ball"


@pytest.fixture
def bridge():
    return HeadlessAssemblyBridge()


@pytest.fixture
def loaded(bridge, ball):
    """A bridge with both bouncing-ball FMUs added."""
    bridge.add_fmu(str(ball / "bb_position.fmu"))
    bridge.add_fmu(str(ball / "bb_velocity.fmu"))
    return bridge


# --------------------------------------------------------------------------- #
#                                  contract                                    #
# --------------------------------------------------------------------------- #
def test_the_headless_bridge_satisfies_the_protocol(bridge):
    assert isinstance(bridge, AssemblyBridge)


def test_it_starts_empty(bridge):
    assert bridge.list_fmus() == []
    assert bridge.get_assembly_json() == {}


# --------------------------------------------------------------------------- #
#                            reading a real FMU                                #
# --------------------------------------------------------------------------- #
def test_describing_a_file_reports_its_interface(ball):
    description = describe_fmu(ball / "bb_velocity.fmu")

    assert description["fmu"] == "bb_velocity.fmu"
    assert description["fmi_version"] == 2
    assert description["kinds"] == ["CoSimulation"]
    assert {port["name"]: port["causality"] for port in description["ports"]} == {
        "reset": "input", "velocity": "output", "time": "independent"}
    # Every port carries the descriptor attributes, even when undeclared.
    assert all({"variability", "unit", "start", "description"} <= set(port)
               for port in description["ports"])


def test_describing_a_missing_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        describe_fmu(tmp_path / "ghost.fmu")


def test_inspecting_a_file_does_not_add_it(bridge, ball):
    bridge.inspect_fmu_file(str(ball / "bb_velocity.fmu"))
    assert bridge.list_fmus() == []


# --------------------------------------------------------------------------- #
#                               editing the assembly                            #
# --------------------------------------------------------------------------- #
def test_adding_an_fmu_summarises_it(bridge, ball):
    summary = bridge.add_fmu(str(ball / "bb_position.fmu"))

    assert summary["fmu"] == "bb_position.fmu"
    assert summary["fmi_version"] == 2
    assert summary["counts"]["output"] >= 1
    assert bridge.list_fmus() == ["bb_position.fmu"]


def test_adding_the_same_file_twice_is_harmless(bridge, ball):
    bridge.add_fmu(str(ball / "bb_position.fmu"))
    bridge.add_fmu(str(ball / "bb_position.fmu"))
    assert bridge.list_fmus() == ["bb_position.fmu"]


def test_two_files_sharing_a_name_are_refused(bridge, ball, tmp_path):
    """FMUs are designated by file name: a duplicate would make the name
    ambiguous, so it is refused rather than silently resolved."""
    import shutil

    twin = tmp_path / "bb_position.fmu"
    shutil.copy(ball / "bb_position.fmu", twin)
    bridge.add_fmu(str(ball / "bb_position.fmu"))

    with pytest.raises(ValueError, match="rename one of them"):
        bridge.add_fmu(str(twin))


def test_an_unknown_fmu_is_reported_with_what_is_loaded(loaded):
    with pytest.raises(ValueError, match="currently: bb_position.fmu, bb_velocity.fmu"):
        loaded.list_fmu_ports("ghost.fmu")


def test_linking_requires_an_output_then_an_input(loaded):
    link = loaded.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    assert link == "bb_velocity.fmu/velocity -> bb_position.fmu/velocity"

    # Reversed: the source is an input, not an output.
    with pytest.raises(ValueError, match="not an output"):
        loaded.add_link("bb_position.fmu", "velocity", "bb_velocity.fmu", "reset")

    with pytest.raises(ValueError, match="is not a port"):
        loaded.add_link("bb_velocity.fmu", "nope", "bb_position.fmu", "velocity")


def test_the_same_link_is_not_duplicated(loaded):
    loaded.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    loaded.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    assert len(loaded.get_assembly_json()["link"]) == 1


def test_a_link_can_be_removed(loaded):
    loaded.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")

    assert loaded.remove_link("bb_velocity.fmu", "velocity",
                              "bb_position.fmu", "velocity")

    assert "link" not in loaded.get_assembly_json()


def test_removing_an_unknown_link_is_reported(loaded):
    with pytest.raises(ValueError, match="no link"):
        loaded.remove_link("bb_velocity.fmu", "velocity",
                           "bb_position.fmu", "velocity")


def test_a_start_value_can_be_unset(loaded):
    loaded.set_start_value("bb_velocity.fmu", "reset", "true")

    loaded.unset_start_value("bb_velocity.fmu", "reset")

    ports = {port["name"]: port for port in
             loaded.list_fmu_ports("bb_velocity.fmu")["ports"]}
    # Back to whatever the FMU itself declares.
    assert ports["reset"]["start"] != "true"
    assert "start" not in loaded.get_assembly_json()


def test_unsetting_a_start_value_mentions_the_declared_one(loaded):
    """The message must tell what the port falls back to, since the user asked
    to remove a value and may expect "none"."""
    with pytest.raises(ValueError, match="No start value was set"):
        loaded.unset_start_value("bb_velocity.fmu", "reset")


def test_exposing_checks_the_causality(loaded):
    assert loaded.expose_output("bb_velocity.fmu", "velocity")
    with pytest.raises(ValueError, match="not an output"):
        loaded.expose_output("bb_velocity.fmu", "reset")
    assert loaded.expose_input("bb_velocity.fmu", "reset")


def test_start_values_are_reported_back(loaded):
    loaded.set_start_value("bb_velocity.fmu", "reset", "true")

    ports = {port["name"]: port for port in
             loaded.list_fmu_ports("bb_velocity.fmu")["ports"]}
    assert ports["reset"]["start"] == "true"


def test_setting_a_start_value_on_an_unknown_port_is_rejected(loaded):
    with pytest.raises(ValueError, match="is not a port"):
        loaded.set_start_value("bb_velocity.fmu", "ghost", "1")


def test_removing_an_fmu_discards_its_links(loaded):
    loaded.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    loaded.expose_output("bb_velocity.fmu", "velocity")

    assert loaded.remove_fmu("bb_velocity.fmu") == {"fmu": "bb_velocity.fmu",
                                                    "removed_links": 1}
    assert loaded.list_fmus() == ["bb_position.fmu"]
    assert "link" not in loaded.get_assembly_json()


def test_removing_an_unknown_fmu_is_reported(bridge):
    with pytest.raises(ValueError, match="not in the assembly"):
        bridge.remove_fmu("ghost.fmu")


# --------------------------------------------------------------------------- #
#                                   options                                    #
# --------------------------------------------------------------------------- #
def test_options_default_to_the_assembly_node_defaults(bridge):
    assert bridge.set_container_options({}) == DEFAULT_OPTIONS
    assert DEFAULT_OPTIONS["auto_link"] is True
    assert DEFAULT_OPTIONS["step_size"] is None


def test_only_the_provided_options_change(bridge):
    options = bridge.set_container_options({"step_size": 0.01})
    assert options["step_size"] == 0.01
    assert options["auto_link"] is True


def test_an_unknown_option_is_rejected(bridge):
    with pytest.raises(ValueError, match="Unknown container option"):
        bridge.set_container_options({"stepsize": 0.01})


def test_options_reach_the_assembly(loaded):
    loaded.set_container_options({"step_size": 0.02, "mt": True})
    assembly = loaded.get_assembly_json()
    assert assembly["step_size"] == 0.02
    assert assembly["mt"] is True


# --------------------------------------------------------------------------- #
#                               export / build                                 #
# --------------------------------------------------------------------------- #
def test_the_assembly_describes_what_was_asked(loaded):
    from pathlib import Path

    loaded.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    loaded.expose_input("bb_velocity.fmu", "reset")
    loaded.set_start_value("bb_velocity.fmu", "reset", "true")

    assembly = loaded.get_assembly_json()

    assert sorted(Path(fmu).name for fmu in assembly["fmu"]) == [
        "bb_position.fmu", "bb_velocity.fmu"]
    (link,) = assembly["link"]
    assert [Path(link[0]).name, link[1], Path(link[2]).name, link[3]] == [
        "bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"]
    assert assembly["start"] == [[str(link[0]), "reset", "true"]]


def test_exporting_json_writes_a_readable_description(loaded, tmp_path):
    destination = tmp_path / "assembly.json"
    loaded.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")

    assert loaded.save_as_json(str(destination)) == str(destination)

    written = json.loads(destination.read_text())
    assert len(written["fmu"]) == 2
    assert len(written["link"]) == 1


def test_exporting_an_empty_assembly_is_refused(bridge, tmp_path):
    with pytest.raises(AssemblyError, match="empty"):
        bridge.save_as_json(str(tmp_path / "assembly.json"))


@pytest.mark.parametrize("fmi_version", [0, 1, 7, "2"])
def test_building_rejects_an_unsupported_fmi_version(loaded, tmp_path, fmi_version: Any):
    """`"2"` is deliberately a string: a client may well send one, and the
    bridge must reject it rather than build a corrupted archive (audit B6)."""
    with pytest.raises(ValueError, match="Unsupported FMI version"):
        loaded.save_as_fmu(str(tmp_path / "out.fmu"), fmi_version=fmi_version)


@pytest.mark.integration
@pytest.mark.needs_container
def test_building_produces_a_real_container(loaded, tmp_path):
    """The whole point of the headless bridge: a container built with no GUI."""
    import zipfile

    destination = tmp_path / "container.fmu"
    loaded.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    loaded.set_container_options({"step_size": 0.01})

    assert loaded.save_as_fmu(str(destination)) == str(destination)

    with zipfile.ZipFile(destination) as archive:
        descriptor = archive.read("modelDescription.xml").decode("utf-8", "replace")
    assert 'fmiVersion="2.0"' in descriptor


@pytest.mark.integration
@pytest.mark.needs_container
def test_building_twice_stays_consistent(loaded, tmp_path):
    """The assembly is rebuilt for each build: ``make_fmu`` writes its
    auto-link/auto-expose rules back into the node it is given, so a reused
    node would accumulate derived content."""
    loaded.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")

    loaded.save_as_fmu(str(tmp_path / "first.fmu"))
    before = loaded.get_assembly_json()
    loaded.save_as_fmu(str(tmp_path / "second.fmu"))

    assert loaded.get_assembly_json() == before





