"""Tests for the analysis of an assembly: bounded summary and paged views (docs/local/assembly_analysis.md).

On a real assembly of 3 nested containers, `get_assembly_json` is over 100k characters: the model had to write its
own scripts to see the container tree and the data flows. The summary reduces the JSON to that view, within the
result budget of a tool.
"""
import json
import zipfile

import pytest

pytestmark = [pytest.mark.unit]

from fmu_manipulation_toolbox.assistant.analysis import (  # noqa: E402
    MAX_EXAMPLES, MAX_GROUPS, MAX_RESULT_SIZE, RULES, SECTIONS, assembly_page, find_container, fmu_name,
    lint_assembly, port_prefix, summarize_assembly,
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

    assert len(json.dumps(summary)) <= MAX_RESULT_SIZE

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
    """Beyond `MAX_RESULT_SIZE`, the sub-containers keep their identity and counts only."""
    def container(name, depth):
        links = [["a.fmu", f"signal{i}_{name}_x", "b.fmu", f"signal{i}_{name}_y"] for i in range(200)]
        links += [["a.fmu", f"p{i}.{name}", "b.fmu", f"p{i}.{name}"] for i in range(MAX_GROUPS) for _ in range(2)]
        node = {"name": f"{name}.fmu", "mt": True, "fmu": ["a.fmu", "b.fmu"], "link": links}
        if depth:
            node["container"] = [container(f"{name}{i}", depth - 1) for i in range(3)]
        return node

    summary = summarize_assembly(container("root", 2))

    assert len(json.dumps(summary)) <= MAX_RESULT_SIZE
    assert "reduced" not in summary and "links" in summary
    reduced = list(_nodes(summary))[1:]
    assert len(reduced) == 12
    for node in reduced:
        assert node["reduced"] is True
        assert "links" not in node
        assert node["options"] == {"mt": True}
        assert node["counts"]["links"] == 200 + 2 * MAX_GROUPS


# --------------------------------------------------------------------------- #
#                     paged views of the JSON (phase 2)                        #
# --------------------------------------------------------------------------- #
def test_a_small_assembly_is_returned_whole_with_names(data_dir):
    """Decision D6: no change for a small assembly, except the FMU paths of the root, replaced by names."""
    assembly = _arch(data_dir, "nested.json")
    assembly["fmu"] = [f"/models/{fmu}" for fmu in assembly["fmu"]]
    assembly["link"][0][0] = r"C:\models\fmu0a.fmu"

    page = assembly_page(assembly)

    assert page == _arch(data_dir, "nested.json")


def test_an_empty_assembly_gives_an_empty_page():
    assert assembly_page({}) == {}


def test_a_container_is_designated_by_name(data_dir):
    page = assembly_page(_arch(data_dir, "nested.json"), node="level1.fmu")

    assert page["name"] == "level1.fmu"
    assert page["fmu"] == ["fmu1a.fmu", "fmu1b.fmu", "fmu1c.fmu"]
    assert page["counts"] == {"input": 3, "output": 3, "link": 4, "start": 0, "drop": 0}
    assert page["container"] == [
        {"name": "level2a.fmu", "counts": {"input": 1, "output": 1, "link": 0, "start": 0, "drop": 0}},
        {"name": "level2b.fmu", "counts": {"input": 1, "output": 1, "link": 0, "start": 0, "drop": 0}},
    ]
    assert len(page["link"]) == 4
    assert page["truncated"] is False


def test_an_unknown_container_lists_the_known_ones(data_dir):
    with pytest.raises(ValueError, match=r"No container is named 'nope.fmu' \(containers: level0.fmu, level1.fmu, "
                                         r"level2a.fmu, level2b.fmu\)"):
        find_container(_arch(data_dir, "nested.json"), "nope.fmu")


def test_an_ambiguous_container_is_refused_with_its_paths():
    """Decision D5: names only; two containers with one name cannot be designated."""
    assembly = {"name": "root.fmu", "container": [
        {"name": "a.fmu", "container": [{"name": "same.fmu"}]},
        {"name": "b.fmu", "container": [{"name": "same.fmu"}]},
    ]}
    with pytest.raises(ValueError, match="root.fmu/a.fmu/same.fmu, root.fmu/b.fmu/same.fmu"):
        find_container(assembly, "same.fmu")


def test_a_section_is_paged(data_dir):
    page = assembly_page(_arch(data_dir, "nested.json"), node="level1.fmu", section="link", offset=1, limit=2)

    assert page == {"node": "level1.fmu", "section": "link", "total": 4, "offset": 1, "returned": 2,
                    "truncated": True, "entries": [["level2a.fmu", "level2a_out0", "fmu1b.fmu", "fmu1b_in2"],
                                                   ["fmu1b.fmu", "fmu1b_out1", "fmu1c.fmu", "fmu1c_in0"]]}


def test_an_unknown_section_is_refused(data_dir):
    with pytest.raises(ValueError, match="Unknown section 'links'"):
        assembly_page(_arch(data_dir, "nested.json"), section="links")


def test_sections_use_fmu_names(tmp_path):
    """The root level of the JSON designates its FMUs by path: every section is given with names."""
    assembly = make_large_assembly(tmp_path)
    for section in SECTIONS:
        for entry in assembly_page(assembly, section=section, limit=1000)["entries"]:
            assert str(tmp_path) not in json.dumps(entry)


def test_a_large_assembly_is_given_one_container_at_a_time(tmp_path):
    """Decision D6, then the sections: every view within the budget, and every entry reachable."""
    assembly = make_large_assembly(tmp_path)

    root = assembly_page(assembly)
    assert len(json.dumps(root)) <= MAX_RESULT_SIZE
    assert root["name"] == "large_assembly.fmu"
    assert root["truncated"] is True
    assert "input" not in root
    assert root["counts"]["input"] == len(assembly["input"])
    assert root["container"] == [{"name": "vehicle.fmu", "counts": {
        "input": 7, "output": 52, "link": 265, "start": 0, "drop": 0}}]

    for name in ("vehicle.fmu", "level2.fmu"):
        node = find_container(assembly, name)
        page = assembly_page(assembly, node=name)
        assert len(json.dumps(page)) <= MAX_RESULT_SIZE
        for section in SECTIONS:
            entries, offset = [], 0
            while True:
                part = assembly_page(assembly, node=name, section=section, offset=offset)
                assert len(json.dumps(part)) <= MAX_RESULT_SIZE
                entries += part["entries"]
                offset += part["returned"]
                if not part["truncated"]:
                    break
            assert entries == node.get(section, [])


# --------------------------------------------------------------------------- #
#                          structural lint (phase 3)                           #
# --------------------------------------------------------------------------- #
#: Options of an explicit assembly: every `auto_*` rule off, so that nothing is derived at build time.
EXPLICIT = {"auto_link": False, "auto_input": False, "auto_output": False}


def _findings(assembly):
    """`(rule, severity) -> examples` of the lint of `assembly`."""
    return {(group["rule"], group["severity"]): group["examples"] for group in lint_assembly(assembly)["findings"]}


def test_no_finding_on_a_flat_assembly(data_dir):
    report = lint_assembly(_arch(data_dir, "flat.json"))

    assert report == {"error_count": 0, "warning_count": 0, "info_count": 0, "truncated": False, "findings": []}
    assert lint_assembly({}) == report


def test_input_fed_twice():
    """The builder refuses a second feeder: link and exposed input, two links, or two exposed inputs."""
    assembly = {"name": "c.fmu", "fmu": ["a.fmu", "b.fmu"],
                "input": [["u", "b.fmu", "u"], ["v1", "b.fmu", "v"], ["v2", "b.fmu", "v"]],
                "link": [["a.fmu", "y", "b.fmu", "u"], ["a.fmu", "y1", "b.fmu", "w"], ["a.fmu", "y2", "b.fmu", "w"]]}

    assert _findings(assembly)[("input-fed-twice", "error")] == [
        "c.fmu: b.fmu/u fed by container input 'u', link from a.fmu/y",
        "c.fmu: b.fmu/v fed by container input 'v1', container input 'v2'",
        "c.fmu: b.fmu/w fed by link from a.fmu/y1, link from a.fmu/y2",
    ]
    assert lint_assembly(assembly)["error_count"] == 3


def test_duplicate_output():
    assembly = {"name": "c.fmu", "fmu": ["/models/a.fmu", "b.fmu"],
                "output": [["/models/a.fmu", "y", "out"], ["b.fmu", "y", "out"], ["b.fmu", "z", "z"]]}

    assert _findings(assembly)[("duplicate-output", "error")] == ["c.fmu: output 'out' exposes a.fmu/y, b.fmu/y"]


def test_nested_mt_and_mt_sequential():
    assembly = {"name": "root.fmu", "mt": True, "container": [
        {"name": "mid.fmu", "container": [{"name": "leaf.fmu", "mt": True, "sequential": True}]}]}

    findings = _findings(assembly)
    assert findings[("nested-mt", "warning")] == ["leaf.fmu inside root.fmu"]
    assert findings[("mt-sequential", "warning")] == ["leaf.fmu"]


@pytest.mark.parametrize("parent, child, severity, example", [
    (0.5, 0.1, "info", "sub.fmu (0.1 s) in root.fmu (0.5 s): ratio 5"),
    (0.5, 0.005, "warning", "sub.fmu (0.005 s) in root.fmu (0.5 s): ratio 100"),
    (0.5, 0.2, "warning", "sub.fmu (0.2 s) in root.fmu (0.5 s): ratio 2.5, not an integer"),
    (0.1, 0.3, "warning", "sub.fmu (0.3 s) in root.fmu (0.1 s): ratio 0.333333, not an integer"),
])
def test_step_ratio(parent, child, severity, example):
    """Exact ratios (decimal steps compared as fractions, 0.5 / 0.1 is 5)."""
    assembly = {"name": "root.fmu", "step_size": parent, "container": [{"name": "sub.fmu", "step_size": child}]}

    assert _findings(assembly) == {("step-ratio", severity): [example]}


@pytest.mark.parametrize("child", [{"name": "sub.fmu", "step_size": 0.5}, {"name": "sub.fmu"}])
def test_no_step_ratio_for_equal_or_derived_steps(child):
    assert _findings({"name": "root.fmu", "step_size": 0.5, "container": [child]}) == {}


def test_fan_out():
    assembly = {"name": "c.fmu", "fmu": ["a.fmu", "b.fmu"],
                "input": [["u", "a.fmu", "u"], ["u", "b.fmu", "u"]],
                "link": [["a.fmu", "y", "b.fmu", "v"], ["a.fmu", "y", "b.fmu", "w"]]}

    assert _findings(assembly)[("fan-out", "info")] == [
        "c.fmu: a.fmu/y -> b.fmu/v, b.fmu/w",
        "c.fmu: container input 'u' -> a.fmu/u, b.fmu/u",
    ]


def test_source_fmu():
    """Only when no `auto_*` rule may feed the FMU: derived links and exposures are not in the JSON."""
    assembly = {"name": "c.fmu", **EXPLICIT, "fmu": ["a.fmu", "b.fmu"], "container": [{"name": "sub.fmu"}],
                "link": [["a.fmu", "y", "b.fmu", "u"], ["sub.fmu", "y", "b.fmu", "v"]],
                "output": [["b.fmu", "z", "z"]]}

    assert _findings(assembly)[("source-fmu", "info")] == ["c.fmu: a.fmu", "c.fmu: sub.fmu"]
    assert ("source-fmu", "info") not in _findings({**assembly, "auto_link": True})
    assert ("source-fmu", "info") not in _findings({key: value for key, value in assembly.items()
                                                    if key != "auto_input"})


def test_auto_off_nothing_exposed():
    """On the root container only: a sub-container exposes what its parent links."""
    assembly = {"name": "c.fmu", **EXPLICIT, "fmu": ["a.fmu"], "input": [["u", "a.fmu", "u"]],
                "container": [{"name": "sub.fmu", **EXPLICIT}]}

    assert _findings(assembly)[("auto-off-nothing-exposed", "warning")] == ["c.fmu: auto_output off, no output exposed"]


def test_findings_are_ordered_counted_and_bounded():
    """Errors first; each group with the meaning of its rule, its count and a few examples."""
    links = [["a.fmu", f"y{i}", "b.fmu", "u"] for i in range(10)] + [["a.fmu", "y0", "b.fmu", "v"]]
    report = lint_assembly({"name": "root.fmu", "mt": True, "fmu": ["a.fmu", "b.fmu"], "link": links,
                            "container": [{"name": "sub.fmu", "mt": True}]})

    assert [(group["rule"], group["severity"]) for group in report["findings"]] == [
        ("input-fed-twice", "error"), ("nested-mt", "warning"), ("fan-out", "info")]
    assert (report["error_count"], report["warning_count"], report["info_count"]) == (1, 1, 1)
    assert report["findings"][0]["message"] == RULES["input-fed-twice"]
    assert len(report["findings"][0]["examples"]) == 1


def test_examples_are_bounded():
    links = [["a.fmu", f"y{i}", "b.fmu", f"u{i}"] for i in range(10)] + [["a.fmu", f"z{i}", "b.fmu", f"u{i}"]
                                                                         for i in range(10)]
    [group] = lint_assembly({"name": "c.fmu", "fmu": ["a.fmu", "b.fmu"], "link": links})["findings"]

    assert group["count"] == 10
    assert len(group["examples"]) == MAX_EXAMPLES


def test_the_large_assembly_is_linted(tmp_path):
    """The patterns of the case study: nested `mt`, a step ratio of 100 and a fan-out; within the budget."""
    report = lint_assembly(make_large_assembly(tmp_path))

    assert len(json.dumps(report)) <= MAX_RESULT_SIZE
    assert set(_findings(make_large_assembly(tmp_path))) == {
        ("nested-mt", "warning"), ("step-ratio", "warning"), ("fan-out", "info")}
    assert report["error_count"] == 0


# --------------------------------------------------------------------------- #
#               port-level lint: replay into the builder (phase 4)             #
# --------------------------------------------------------------------------- #
def _write_fmu(path, variables):
    """FMI-2 FMU (descriptor only); `variables` are `(name, causality, type, unit, start)`."""
    xml = []
    for i, (name, causality, type_, unit, start) in enumerate(variables):
        attributes = (f' unit="{unit}"' if unit else "") + (f' start="{start}"' if start is not None else "")
        xml.append(f'<ScalarVariable name="{name}" valueReference="{i}" causality="{causality}">'
                   f'<{type_}{attributes}/></ScalarVariable>')
    outputs = "".join(f'<Unknown index="{i + 1}"/>' for i, variable in enumerate(variables) if variable[1] == "output")
    descriptor = (f'<?xml version="1.0" encoding="UTF-8"?>\n<fmiModelDescription fmiVersion="2.0" '
                  f'modelName="{path.stem}" guid="{{{path.stem}}}"><CoSimulation modelIdentifier="{path.stem}"/>'
                  f'<ModelVariables>{"".join(xml)}</ModelVariables><ModelStructure><Outputs>{outputs}</Outputs>'
                  f'</ModelStructure></fmiModelDescription>')
    with zipfile.ZipFile(path, "w") as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
    return path


def _describer(directory):
    """`describe` of the bridges, reading the FMUs of `directory`; an unknown FMU is refused as by the bridges."""
    from fmu_manipulation_toolbox.assistant.headless import describe_fmu

    def describe(name):
        path = directory / name
        if not path.is_file():
            raise ValueError(f"FMU '{name}' is not in the assembly.")
        return describe_fmu(path)

    return describe


@pytest.fixture
def two_fmus(tmp_path):
    _write_fmu(tmp_path / "a.fmu", [("y", "output", "Real", "m", None), ("r", "output", "Real", None, None),
                                    ("s", "output", "String", None, None), ("dup", "output", "Real", None, None)])
    _write_fmu(tmp_path / "b.fmu", [("u", "input", "Real", "km", "0"), ("i", "input", "Integer", None, "0"),
                                    ("w", "input", "Real", None, "0"), ("free", "input", "Real", None, None),
                                    ("dup", "output", "Real", None, None)])
    return tmp_path


def test_the_builder_checks_the_ports(two_fmus):
    """Each refusal of the builder is an error with its message; conversions, units and unfed inputs are warned."""
    assembly = {"name": "c.fmu", **EXPLICIT, "fmu": [str(two_fmus / "a.fmu"), "b.fmu"],
                "input": [["x", "a.fmu", "y"]],
                "output": [["b.fmu", "u", "o"], ["a.fmu", "dup", "dup"]],
                "link": [["a.fmu", "y", "b.fmu", "u"], ["a.fmu", "r", "b.fmu", "i"], ["a.fmu", "s", "b.fmu", "w"],
                         ["a.fmu", "nope", "b.fmu", "w"]],
                "start": [["b.fmu", "i", "not a number"]]}

    findings = _findings_with(assembly, two_fmus)

    assert set(findings) == {("invalid-input", "error"), ("invalid-output", "error"), ("invalid-link", "error"),
                             ("invalid-start", "error"), ("lossy-link", "warning"), ("link-unit", "warning"),
                             ("dangling-input", "warning"), ("input-fed-twice", "error")}
    assert len(findings[("invalid-link", "error")]) == 1  # The second feeder of 'w' is reported once, structurally.
    assert findings[("link-unit", "warning")] == ["c.fmu: a.fmu/y (m) -> b.fmu/u (km)"]
    assert findings[("dangling-input", "warning")] == ["c.fmu: b.fmu/free"]
    assert all(example.startswith("c.fmu: ") for examples in findings.values() for example in examples)


def _findings_with(assembly, directory, **arguments):
    report = lint_assembly(assembly, describe=_describer(directory), **arguments)
    return {(group["rule"], group["severity"]): group["examples"] for group in report["findings"]}


def test_the_auto_rules_are_dry_run(two_fmus):
    """`auto_input` exposes the free input at build time: it is not dangling."""
    assembly = {"name": "c.fmu", **EXPLICIT, "auto_input": True, "fmu": ["a.fmu", "b.fmu"]}

    assert ("dangling-input", "warning") not in _findings_with(assembly, two_fmus)


def test_an_auto_rule_refused_by_the_builder(two_fmus):
    """`auto_output` exposes both 'dup' outputs under the same name: the build fails."""
    assembly = {"name": "c.fmu", "fmu": ["a.fmu", "b.fmu"]}

    [example] = _findings_with(assembly, two_fmus)[("auto-rules-error", "error")]
    assert "dup" in example


def test_entries_with_a_sub_container_are_not_checked(two_fmus):
    """Decision D9': a sub-container only exists once built."""
    assembly = {"name": "c.fmu", "fmu": ["a.fmu"], "container": [{"name": "sub.fmu", **EXPLICIT, "fmu": ["b.fmu"]}],
                "link": [["a.fmu", "y", "sub.fmu", "u"], ["a.fmu", "r", "sub.fmu", "i"]]}

    findings = _findings_with(assembly, two_fmus)

    assert findings[("sub-container-unchecked", "info")] == ["c.fmu: 2 entries with sub.fmu"]
    assert findings[("auto-rules-partial", "info")] == ["c.fmu: sub.fmu"]


def test_an_fmu_the_bridge_does_not_know_is_not_checked(tmp_path):
    assembly = {"name": "c.fmu", "fmu": ["ghost.fmu"]}

    assert _findings_with(assembly, tmp_path)[("not-checked", "info")] == ["c.fmu: ghost.fmu, file not found"]


def test_input_clocks_may_be_fed_twice():
    """The builder lets several feeders reach an input clock (LS-BUS): no structural error for them."""
    def describe(name):
        return {"path": f"/nowhere/{name}", "ports": [{"name": "tick", "type": "Clock", "causality": "input"}]}

    assembly = {"name": "c.fmu", "fmu": ["a.fmu", "b.fmu"],
                "link": [["a.fmu", "t1", "b.fmu", "tick"], ["a.fmu", "t2", "b.fmu", "tick"]]}

    assert ("input-fed-twice", "error") in _findings(assembly)
    report = lint_assembly(assembly, describe=describe)
    assert "input-fed-twice" not in {group["rule"] for group in report["findings"]}


def test_the_lint_can_be_restricted_to_one_container(data_dir):
    report = lint_assembly(_arch(data_dir, "hierarchical.json"), node="level1.fmu")

    assert [(group["rule"], group["severity"], group["examples"]) for group in report["findings"]] == [
        ("step-ratio", "warning", ["level1.fmu (0.01 s) in (root) (0.5 s): ratio 50"])]
    with pytest.raises(ValueError, match="No container is named"):
        lint_assembly(_arch(data_dir, "hierarchical.json"), node="nope.fmu")


def test_the_large_assembly_passes_the_builder(tmp_path):
    """Every rule of the large assembly is accepted by the builder; the report stays within the budget."""
    assembly = make_large_assembly(tmp_path)
    report = lint_assembly(assembly, describe=_describer(tmp_path))

    assert len(json.dumps(report)) <= MAX_RESULT_SIZE
    assert report["error_count"] == 0
    assert {group["rule"] for group in report["findings"]} == {
        "nested-mt", "step-ratio", "fan-out", "sub-container-unchecked"}
