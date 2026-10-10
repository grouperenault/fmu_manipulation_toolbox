"""Tests for the analysis of an assembly: bounded summary (docs/local/assembly_analysis.md, phase 1).

On a real assembly of 3 nested containers, `get_assembly_json` is over 100k characters: the model had to write its
own scripts to see the container tree and the data flows. The summary reduces the JSON to that view, within the
result budget of a tool.
"""
import json

import pytest

pytestmark = [pytest.mark.unit]

from fmu_manipulation_toolbox.assistant.analysis import (  # noqa: E402
    MAX_EXAMPLES, MAX_GROUPS, MAX_SUMMARY_SIZE, fmu_name, port_prefix, summarize_assembly,
)

from _helpers.mcp_budget import make_large_assembly  # noqa: E402


def _arch(data_dir, name):
    return json.loads((data_dir / "containers" / "arch" / name).read_text())


def _nodes(summary):
    yield summary
    for child in summary["containers"]:
        yield from _nodes(child)


# --------------------------------------------------------------------------- #
#                                  helpers                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name, prefix", [
    ("Sc_2_DV.Rho", "Sc_2_DV"),
    ("run_parameters.tolerance", "run_parameters"),
    ("a.b.c", "a"),
    ("SNR_T_amb", "SNR_"),
    ("veh_vel_ms", "veh_"),
    ("Tout", ""),
])
def test_port_prefix(name, prefix):
    """Decision D7: the segment before `.`, otherwise the part before the first `_`."""
    assert port_prefix(name) == prefix


@pytest.mark.parametrize("reference", ["model.fmu", "/models/model.fmu", r"C:\models\model.fmu"])
def test_fmu_name(reference):
    """The root level of the JSON designates the FMUs by path, on any platform."""
    assert fmu_name(reference) == "model.fmu"


# --------------------------------------------------------------------------- #
#                                 structure                                    #
# --------------------------------------------------------------------------- #
def test_an_empty_assembly_gives_an_empty_summary():
    assert summarize_assembly({}) == {}


def test_flat_assembly(data_dir):
    """Only the options given by the JSON are reported."""
    summary = summarize_assembly(_arch(data_dir, "flat.json"))

    assert summary["name"] is None
    assert summary["options"] == {"step_size": 0.5}
    assert summary["fmus"] == ["sine.fmu", "integrate.fmu", "gain.fmu"]
    assert summary["counts"] == {"inputs": 0, "outputs": 0, "links": 0, "start_values": 0, "dropped": 0}
    assert summary["links"] == {"total": 0, "truncated": False, "groups": []}
    assert summary["containers"] == []


def test_hierarchical_assembly(data_dir):
    summary = summarize_assembly(_arch(data_dir, "hierarchical.json"))

    assert summary["fmus"] == ["gain.fmu"]
    [child] = summary["containers"]
    assert child["name"] == "level1.fmu"
    assert child["options"] == {"step_size": 0.01}
    assert child["fmus"] == ["sine.fmu", "integrate.fmu"]


def test_nested_assembly(data_dir):
    """Sub-containers are designated by name in the links of their parent, like FMUs."""
    summary = summarize_assembly(_arch(data_dir, "nested.json"))

    assert [node["name"] for node in _nodes(summary)] == ["level0.fmu", "level1.fmu", "level2a.fmu", "level2b.fmu"]
    level1 = summary["containers"][0]
    assert level1["counts"]["links"] == 4
    assert level1["links"] == {"total": 0, "truncated": False, "groups": [], "ungrouped": {
        "count": 4, "examples": ["fmu1a_out0 -> fmu1b_in1", "level2a_out0 -> fmu1b_in2", "fmu1b_out1 -> fmu1c_in0"]}}
    assert summary["links"]["groups"] == [
        {"from": "fmu0a.fmu", "from_prefix": "fmu0a_", "to": "level1.fmu", "to_prefix": "level1_", "count": 2,
         "examples": ["fmu0a_out0 -> level1_in1", "fmu0a_out1 -> level1_in2"]},
        {"from": "level1.fmu", "from_prefix": "level1_", "to": "fmu0b.fmu", "to_prefix": "fmu0b_", "count": 2,
         "examples": ["level1_out1 -> fmu0b_in0", "level1_out2 -> fmu0b_in1"]},
    ]
    assert summary["inputs"]["ungrouped"] == {"count": 2, "examples": ["IN_A", "IN_B"]}


# --------------------------------------------------------------------------- #
#                                  grouping                                    #
# --------------------------------------------------------------------------- #
def _node(links=(), inputs=()):
    return {"name": "c.fmu", "fmu": ["a.fmu", "b.fmu"], "link": list(links), "input": list(inputs)}


def test_ports_alone_in_their_group_are_merged():
    summary = summarize_assembly(_node(inputs=[["bus.x", "a.fmu", "x"], ["bus.y", "a.fmu", "y"],
                                               ["alpha", "a.fmu", "alpha"], ["beta", "b.fmu", "beta"]]))

    assert summary["inputs"] == {
        "total": 1, "truncated": False,
        "groups": [{"fmu": "a.fmu", "prefix": "bus", "count": 2, "examples": ["bus.x", "bus.y"]}],
        "ungrouped": {"count": 2, "examples": ["alpha", "beta"]},
    }


def test_groups_are_sorted_and_bounded():
    """The largest groups first, at most `MAX_GROUPS`, with at most `MAX_EXAMPLES` examples each."""
    links = [["a.fmu", f"out{g}_{i}", "b.fmu", f"in{g}_{i}"]
             for g in range(MAX_GROUPS + 5) for i in range(2 + g)]
    groups = summarize_assembly(_node(links=links))["links"]

    assert groups["total"] == MAX_GROUPS + 5
    assert groups["truncated"] is True
    assert len(groups["groups"]) == MAX_GROUPS
    counts = [group["count"] for group in groups["groups"]]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == MAX_GROUPS + 6
    assert all(len(group["examples"]) <= MAX_EXAMPLES for group in groups["groups"])


def test_a_renamed_link_shows_both_ends():
    links = [["a.fmu", "speed", "b.fmu", "speed"], ["a.fmu", "v_out", "b.fmu", "v_in"]]
    summary = summarize_assembly(_node(links=links))

    assert summary["links"]["ungrouped"]["examples"] == ["speed", "v_out -> v_in"]


# --------------------------------------------------------------------------- #
#                                   bounds                                     #
# --------------------------------------------------------------------------- #
def test_the_large_assembly(tmp_path):
    """Exit criterion of phase 1: within the budget, and every count equal to the JSON."""
    assembly = make_large_assembly(tmp_path)
    summary = summarize_assembly(assembly)

    assert len(json.dumps(summary)) <= MAX_SUMMARY_SIZE

    def check(node, json_node):
        assert "reduced" not in node
        for key, entry in (("inputs", "input"), ("outputs", "output"), ("links", "link")):
            assert node["counts"][key] == len(json_node.get(entry, []))
            groups = node[key]
            if not groups["truncated"]:
                listed = sum(group["count"] for group in groups["groups"])
                assert listed + groups.get("ungrouped", {}).get("count", 0) == node["counts"][key]
        for child, json_child in zip(node["containers"], json_node.get("container", []), strict=True):
            check(child, json_child)

    check(summary, assembly)


def test_large_trees_are_reduced_below_the_root():
    """Beyond `MAX_SUMMARY_SIZE`, the sub-containers keep their identity and counts only."""
    def container(name, depth):
        links = [["a.fmu", f"signal{i}_{name}_x", "b.fmu", f"signal{i}_{name}_y"] for i in range(200)]
        links += [["a.fmu", f"p{i}.{name}", "b.fmu", f"p{i}.{name}"] for i in range(MAX_GROUPS) for _ in range(2)]
        node = {"name": f"{name}.fmu", "mt": True, "fmu": ["a.fmu", "b.fmu"], "link": links}
        if depth:
            node["container"] = [container(f"{name}{i}", depth - 1) for i in range(3)]
        return node

    summary = summarize_assembly(container("root", 2))

    assert len(json.dumps(summary)) <= MAX_SUMMARY_SIZE
    assert "reduced" not in summary and "links" in summary
    reduced = list(_nodes(summary))[1:]
    assert len(reduced) == 12
    for node in reduced:
        assert node["reduced"] is True
        assert "links" not in node
        assert node["options"] == {"mt": True}
        assert node["counts"]["links"] == 200 + 2 * MAX_GROUPS
