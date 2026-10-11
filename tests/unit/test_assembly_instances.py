"""Several instances of the same FMU in an `Assembly`: names distinct from FMU files.

An embedded FMU is designated by its name in every rule (links, inputs, outputs, start values, dropped ports). The
name is also the path of the FMU file, unless the `path` block of the JSON (`AssemblyNode.fmu_paths`) gives another
file: this is how the same FMU is embedded several times at one level.
"""
import json

import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError, AssemblyNode, instance_name

pytestmark = [pytest.mark.unit]


def _assembly_from(tmp_path, name: str, data: dict) -> Assembly:
    (tmp_path / name).write_text(json.dumps(data))
    return Assembly(name, fmu_directory=tmp_path)


INSTANCES = {
    "name": "two.fmu",
    "fmu": ["model.fmu", "model-1.fmu"],
    "path": {"model-1.fmu": "model.fmu"},
    "link": [["model.fmu", "y", "model-1.fmu", "u"]],
    "start": [["model-1.fmu", "k", "2"]],
}


# --------------------------------------------------------------------------- #
#                                instance names                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path, used, expected", [
    ("model.fmu", [], "model.fmu"),
    ("model.fmu", ["other.fmu"], "model.fmu"),
    ("model.fmu", ["model.fmu"], "model-1.fmu"),
    ("model.fmu", ["model.fmu", "model-1.fmu"], "model-2.fmu"),
    ("model.fmu", ["model.fmu", "model-2.fmu"], "model-1.fmu"),                       # smallest free number
    ("/models/model.fmu", ["/models/model.fmu"], "/models/model-1.fmu"),              # sibling of the file
    ("b/model.fmu", ["a/model.fmu"], "b/model-1.fmu"),                                # same base name, other file
    (r"C:\models\model.fmu", [r"C:\models\model.fmu"], r"C:\models\model-1.fmu"),     # separator kept
], ids=["free", "other-used", "taken", "next", "smallest-free", "absolute", "other-directory", "windows"])
def test_instance_name(path, used, expected):
    assert instance_name(path, used) == expected


def test_add_fmu_keeps_the_file_of_an_instance():
    node = AssemblyNode("c.fmu")
    node.add_fmu("model.fmu")
    node.add_fmu("model-1.fmu", "model.fmu")
    node.add_fmu("other.fmu", "other.fmu")              # a name that is its own path needs no entry

    assert node.fmu_names_list == ["model.fmu", "model-1.fmu", "other.fmu"]
    assert node.fmu_paths == {"model-1.fmu": "model.fmu"}
    assert node.fmu_path("model-1.fmu") == "model.fmu"
    assert node.fmu_path("model.fmu") == "model.fmu"


def test_add_fmu_twice_with_the_same_file_is_a_no_op():
    node = AssemblyNode("c.fmu")
    node.add_fmu("model-1.fmu", "model.fmu")
    node.add_fmu("model-1.fmu", "model.fmu")
    assert node.fmu_names_list == ["model-1.fmu"]


def test_one_name_cannot_designate_two_files():
    node = AssemblyNode("c.fmu")
    node.add_fmu("model-1.fmu", "model.fmu")
    with pytest.raises(AssemblyError, match="already declared with another file"):
        node.add_fmu("model-1.fmu", "other.fmu")


# --------------------------------------------------------------------------- #
#                                 JSON format                                  #
# --------------------------------------------------------------------------- #
def test_json_path_block_gives_the_file_of_an_instance(tmp_path):
    root = _assembly_from(tmp_path, "two.json", INSTANCES).root

    assert root.fmu_names_list == ["model.fmu", "model-1.fmu"]
    assert root.fmu_path("model-1.fmu") == "model.fmu"
    assert [str(link) for link in root.links] == ["model.fmu/y -> model-1.fmu/u"]


def test_json_path_block_may_come_before_the_fmu_block(tmp_path):
    data = {"path": INSTANCES["path"], **{key: value for key, value in INSTANCES.items() if key != "path"}}
    assert _assembly_from(tmp_path, "two.json", data).root.fmu_paths == {"model-1.fmu": "model.fmu"}


def test_json_round_trip_keeps_the_instances(tmp_path):
    original = _assembly_from(tmp_path, "two.json", INSTANCES)
    original.write_json("two-out.json")
    written = json.loads((tmp_path / "two-out.json").read_text())

    assert written["fmu"] == ["model-1.fmu", "model.fmu"]
    assert written["path"] == {"model-1.fmu": "model.fmu"}
    assert Assembly("two-out.json", fmu_directory=tmp_path).json_encode() == original.json_encode()


def test_json_without_instances_has_no_path_block(tmp_path):
    data = {key: value for key, value in INSTANCES.items() if key not in ("path", "start")}
    data["fmu"] = ["model.fmu", "other.fmu"]
    data["link"] = [["model.fmu", "y", "other.fmu", "u"]]
    assert "path" not in _assembly_from(tmp_path, "flat.json", data).json_encode()


@pytest.mark.parametrize("path_block, message", [
    (["model.fmu"], "should define a dictionary"),
    ({"model-1.fmu": 3}, "should define a dictionary"),
    ({"ghost.fmu": "model.fmu"}, "not in the 'fmu' list"),
], ids=["not-a-dict", "not-a-file", "unknown-name"])
def test_json_malformed_path_block_raises(tmp_path, path_block, message):
    with pytest.raises(AssemblyError, match=message):
        _assembly_from(tmp_path, "bad.json", {**INSTANCES, "path": path_block})


def test_json_files_of_the_path_block_are_made_relative(tmp_path):
    """Absolute names and files, as the GUI gives them, are written relative to the JSON file."""
    models = tmp_path / "models"
    node = AssemblyNode("two.fmu")
    node.add_fmu(str(models / "model.fmu"))
    node.add_fmu(instance_name(str(models / "model.fmu"), node.fmu_names_list), str(models / "model.fmu"))
    node.add_link(str(models / "model.fmu"), "y", str(models / "model-1.fmu"), "u")
    assembly = Assembly(fmu_directory=tmp_path)
    assembly.root = node

    assembly.write_json("two.json")
    written = json.loads((tmp_path / "two.json").read_text())
    assert written["fmu"] == ["models/model-1.fmu", "models/model.fmu"]
    assert written["path"] == {"models/model-1.fmu": "models/model.fmu"}
    assert written["link"] == [["models/model.fmu", "y", "models/model-1.fmu", "u"]]

    assembly.write_json("doc.json", basenames_only=True)
    written = json.loads((tmp_path / "doc.json").read_text())
    assert written["path"] == {"model-1.fmu": "model.fmu"}


# --------------------------------------------------------------------------- #
#                                  CSV format                                  #
# --------------------------------------------------------------------------- #
def test_csv_export_refuses_instances(tmp_path):
    assembly = _assembly_from(tmp_path, "two.json", INSTANCES)
    with pytest.raises(AssemblyError, match="use the JSON format"):
        assembly.write_csv("two.csv")
