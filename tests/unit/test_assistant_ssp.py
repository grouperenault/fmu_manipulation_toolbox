"""The assembly files in the assistant: `import_assembly`, `inspect_ssp` and `save_assembly`, without the GUI."""
import json
import shutil
import zipfile

import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError, AssemblyNode
from fmu_manipulation_toolbox.assistant.headless import HeadlessAssemblyBridge
from fmu_manipulation_toolbox.assistant.paths import PathPolicy, PathValidationError
from fmu_manipulation_toolbox.assistant.tools import Toolbox

from _helpers.assistant_bridge import FakeBridge, call_tool

pytestmark = [pytest.mark.unit]


@pytest.fixture
def fmus(data_dir, tmp_path):
    for name in ("bb_position.fmu", "bb_velocity.fmu"):
        shutil.copy(data_dir / "fmi3" / "bouncing_ball" / name, tmp_path / name)
    return tmp_path


@pytest.fixture
def description(fmus):
    """A flat assembly with what the tools cannot create: a name on the container, a dropped port."""
    path = fmus / "pair.json"
    path.write_text(json.dumps({
        "name": "pair.fmu", "step_size": 0.5, "sequential": True, "auto_link": False, "auto_input": False,
        "auto_output": False,
        "fmu": ["bb_velocity.fmu", "bb_position.fmu"],
        "link": [["bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"]],
        "output": [["bb_position.fmu", "position1", "height"]],
        "start": [["bb_velocity.fmu", "reset", "true"]],
        "drop": [["bb_position.fmu", "is_ground"]],
    }))
    return path


def toolbox(root=None) -> Toolbox:
    return Toolbox(HeadlessAssemblyBridge(), PathPolicy(root))


def _ssd(ssp):
    with zipfile.ZipFile(ssp) as archive:
        return archive.read("SystemStructure.ssd").decode("utf-8")


# --------------------------------------------------------------------------- #
#                               import_assembly                               #
# --------------------------------------------------------------------------- #
def test_a_flat_file_is_imported_without_loss(description):
    tools = toolbox()

    imported = tools.import_assembly(str(description))

    assert imported["file"] == "pair.json"
    assert imported["warnings_total"] == 0
    assert imported["name"] == "pair.fmu"
    written = description.with_name("again.json")
    tools.save_assembly(str(written))
    again = json.loads(written.read_text())
    assert [entry[-1] for entry in again["output"]] == ["height"]
    assert [entry[-1] for entry in again["drop"]] == ["is_ground"]
    assert [entry[-1] for entry in again["start"]] == ["true"]
    assert again["step_size"] == 0.5 and again["sequential"] is True and again["auto_link"] is False


def test_an_imported_assembly_can_be_edited_and_built(description):
    tools = toolbox()
    tools.import_assembly(str(description))

    assert tools.remove_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    tools.add_links([{"from_fmu": "bb_velocity.fmu", "from_port": "velocity",
                      "to_fmu": "bb_position.fmu", "to_port": "velocity"}])
    tools.expose_output("bb_velocity.fmu", "velocity")
    tools.save_as_fmu(str(description.with_name("built.fmu")), fmi_version=3)

    assert zipfile.is_zipfile(description.with_name("built.fmu"))


def test_removing_an_imported_fmu_removes_what_refers_to_it(description):
    tools = toolbox()
    tools.import_assembly(str(description))

    tools.remove_fmu("bb_position.fmu")

    assert "drop" not in tools.bridge.get_assembly_json()


def test_a_non_empty_assembly_is_only_replaced_on_request(description, fmus):
    tools = toolbox()
    tools.add_fmu(str(fmus / "bb_position.fmu"))

    with pytest.raises(ValueError, match="replace=True"):
        tools.import_assembly(str(description))
    assert tools.list_fmus() == ["bb_position.fmu"]

    tools.import_assembly(str(description), replace=True)
    assert tools.list_fmus() == ["bb_position.fmu", "bb_velocity.fmu"]


def test_a_refused_file_leaves_the_assembly_as_it_was(fmus):
    refused = fmus / "refused.json"
    refused.write_text(json.dumps({"name": "x.fmu", "fmu": ["ghost.fmu"]}))
    tools = toolbox()
    tools.add_fmu(str(fmus / "bb_position.fmu"))

    with pytest.raises(FileNotFoundError):
        tools.import_assembly(str(refused), replace=True)

    assert tools.list_fmus() == ["bb_position.fmu"]


def test_sub_containers_are_refused_without_the_gui(fmus):
    nested = fmus / "nested.json"
    nested.write_text(json.dumps({"name": "root.fmu", "fmu": ["bb_position.fmu"],
                                  "container": [{"name": "sub.fmu", "fmu": ["bb_velocity.fmu"]}]}))
    tools = toolbox()

    with pytest.raises(AssemblyError, match="sub-containers.*Container Builder"):
        tools.import_assembly(str(nested))

    assert tools.list_fmus() == []


def test_a_description_cannot_bring_in_an_fmu_outside_the_allowed_root(fmus, tmp_path_factory):
    root = tmp_path_factory.mktemp("root")
    shutil.copy(fmus / "bb_position.fmu", tmp_path_factory.getbasetemp() / "outside.fmu")
    description = root / "pair.json"
    description.write_text(json.dumps({"name": "x.fmu", "fmu": ["../outside.fmu"]}))
    tools = toolbox(root)

    with pytest.raises(PathValidationError):
        tools.import_assembly(str(description))

    assert tools.list_fmus() == []


@pytest.mark.parametrize("name", ["model.fmu", "model.txt"])
def test_only_assembly_files_are_imported(tmp_path, name):
    (tmp_path / name).write_text("x")
    with pytest.raises(PathValidationError, match="must end with"):
        toolbox().import_assembly(str(tmp_path / name))


def test_the_state_keeps_an_imported_assembly(description):
    tools = toolbox()
    tools.import_assembly(str(description))
    state = json.loads(json.dumps(tools.bridge.state()))

    again = HeadlessAssemblyBridge.from_state(state)

    assert again.get_assembly_json() == tools.bridge.get_assembly_json()


def test_a_state_written_before_the_imports_is_still_read(fmus):
    bridge = HeadlessAssemblyBridge()
    bridge.add_fmu(str(fmus / "bb_position.fmu"))
    bridge.expose_output("bb_position.fmu", "position1")
    state = {key: value for key, value in bridge.state().items()
             if key not in ("file_order", "drops", "wires", "geometry", "experiment")}
    state["exposed_outputs"] = [["bb_position.fmu", "position1"]]

    assert HeadlessAssemblyBridge.from_state(state).get_assembly_json() == bridge.get_assembly_json()


# --------------------------------------------------------------------------- #
#                                save_assembly                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name, call", [("out.json", ("save_as_json",)), ("out.ssp", ("save_as_ssp", "2.0"))])
def test_the_format_comes_from_the_extension(tmp_path, name, call):
    bridge = FakeBridge()
    destination = str((tmp_path / name).resolve())

    call_tool(bridge, "save_assembly", {"path": destination})

    assert (call[0], destination, *call[1:]) in bridge.calls


def test_an_edited_ssp_round_trip_keeps_what_the_tools_do_not_handle(data_dir, fmus):
    """Geometry, architecture wires and start time are kept, through the SSP file and the state of the agent."""
    assembly = Assembly(fmu_directory=fmus)
    node = AssemblyNode("pair.fmu", auto_link=False, auto_input=False, auto_output=False)
    node.add_fmu("bb_velocity.fmu")
    node.add_fmu("bb_position.fmu")
    node.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    node.add_architecture_wire("bb_velocity.fmu", "bb_position.fmu", "directed", "the speed")
    node.fmu_geometry["bb_velocity.fmu"] = (0.0, 0.0, 10.0, 10.0)
    node.start_time = 2.0
    assembly.root = node
    assembly.write_ssp((fmus / "first.ssp").resolve())

    tools = toolbox()
    imported = tools.import_assembly(str(fmus / "first.ssp"))
    assert imported["warnings_total"] == 0
    tools.bridge = HeadlessAssemblyBridge.from_state(json.loads(json.dumps(tools.bridge.state())))
    tools.save_assembly(str(fmus / "second.ssp"))

    ssd = _ssd(fmus / "second.ssp")
    assert "architecture-wire" in ssd and "the speed" in ssd
    assert "ElementGeometry" in ssd
    assert 'startTime="2.0"' in ssd
    assert ssd.index('name="bb_velocity"') < ssd.index('name="bb_position"')


def test_an_ssp_version_can_be_chosen(fmus):
    tools = toolbox()
    tools.add_fmu(str(fmus / "bb_position.fmu"))

    tools.save_assembly(str(fmus / "old.ssp"), ssp_version="1.0")

    assert 'version="1.0"' in _ssd(fmus / "old.ssp")


# --------------------------------------------------------------------------- #
#                                 inspect_ssp                                 #
# --------------------------------------------------------------------------- #
@pytest.fixture
def ssp(description):
    path = description.with_name("pair.ssp")
    toolbox_with_pair = toolbox()
    toolbox_with_pair.import_assembly(str(description))
    toolbox_with_pair.save_assembly(str(path))
    return path


def test_an_ssp_file_is_summarized_without_writing_next_to_it(ssp):
    before = sorted(path.name for path in ssp.parent.iterdir())

    result = toolbox().inspect_ssp(str(ssp))

    assert result["file"] == "pair.ssp" and result["readable"] is True
    assert result["counts"]["links"] == 1
    assert result["architecture_wires"] == 0
    assert sorted(path.name for path in ssp.parent.iterdir()) == before


def test_inspecting_does_not_touch_the_assembly(ssp, fmus):
    tools = toolbox()
    tools.add_fmu(str(fmus / "bb_position.fmu"))

    tools.inspect_ssp(str(ssp))

    assert tools.list_fmus() == ["bb_position.fmu"]


def test_the_sections_of_an_ssp_file_are_paged(ssp):
    page = toolbox().inspect_ssp(str(ssp), section="link", limit=1)

    assert page["section"] == "link" and page["total"] == 1 and page["returned"] == 1 and page["truncated"] is False


def test_a_refused_ssp_file_is_an_answer_not_an_error(tmp_path):
    refused = tmp_path / "broken.ssp"
    refused.write_text("not an archive")

    result = toolbox().inspect_ssp(str(refused))

    assert result["readable"] is False and result["reason"]


def test_what_the_reader_ignores_is_reported(tmp_path):
    path = tmp_path / "planned.ssp"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SystemStructure.ssd", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ssd:SystemStructureDescription xmlns:ssd="http://ssp-standard.org/SSP1/SystemStructureDescription" '
            'version="2.0" name="planned"><ssd:System name="planned"><ssd:Elements>'
            '<ssd:Component name="later"/></ssd:Elements></ssd:System></ssd:SystemStructureDescription>'))

    result = toolbox().inspect_ssp(str(path))

    assert result["readable"] is True
    assert result["warnings_total"] == 1 and "later" in result["warnings"][0]
