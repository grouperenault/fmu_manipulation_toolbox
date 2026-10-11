"""Tools of the MCP server exposed by the ``assistant`` package.

These tests drive the server through an in-memory ``fastmcp.Client`` against a
**fake bridge**: the tools reach the bridge, list ports in bounded pages, page
and analyse the assembly, edit it, write files within guard-rails, and chain into
end-to-end scenarios.
"""
import json

import pytest

pytestmark = [pytest.mark.unit]

fastmcp = pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")

from fastmcp.exceptions import ToolError  # noqa: E402
from fmu_manipulation_toolbox.assistant import PathPolicy, PathValidationError, build_server  # noqa: E402
from fmu_manipulation_toolbox.assistant.bridge import SUPPORTED_FMI_VERSIONS  # noqa: E402
from fmu_manipulation_toolbox.assistant.models import (  # noqa: E402
    DEFAULT_PORT_LIMIT, MAX_DESCRIPTION_LENGTH, MAX_PORT_LIMIT,
)

from _helpers.assistant_bridge import FakeBridge, call_tool, fmu_file, input_schema, inventory, run  # noqa: E402


# --------------------------------------------------------------------------- #
#                            tools reach the bridge                           #
# --------------------------------------------------------------------------- #
def test_tools_are_forwarded_to_the_bridge(tmp_path):
    bridge = FakeBridge()
    first, second = fmu_file(tmp_path, "a.fmu"), fmu_file(tmp_path, "b.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            await client.call_tool("add_fmu", {"path": str(first)})
            await client.call_tool("add_fmu", {"path": str(second)})
            await client.call_tool("add_link", {"from_fmu": "a.fmu", "from_port": "y",
                                                "to_fmu": "b.fmu", "to_port": "u"})
            return await client.call_tool("list_fmus", {})

    result = run(scenario())
    assert result.data == ["a.fmu", "b.fmu"]
    assert ("add_link", "a.fmu", "y", "b.fmu", "u") in bridge.calls


# --------------------------------------------------------------------------- #
#                      structured, bounded port listings                      #
# --------------------------------------------------------------------------- #
def _ports_call(bridge, tool="list_fmu_ports", **arguments):
    """Call a port-listing tool and return its structured payload as a dict."""
    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool(tool, arguments)

    return run(scenario()).structured_content


def test_port_listing_reports_every_causality(tmp_path):
    """Every causality is reported in its own list: parameters and locals are
    visible, and parameters are not merged with the inputs."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    payload = _ports_call(bridge, fmu="a.fmu")

    assert {port["name"]: port["causality"] for port in payload["ports"]} == {
        "u": "input", "y": "output", "gain": "parameter", "state": "local"}
    assert payload["counts"] == {"input": 1, "output": 1, "parameter": 1, "local": 1}


def test_port_listing_can_be_filtered_by_causality(tmp_path):
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    payload = _ports_call(bridge, fmu="a.fmu", causality=["output", "parameter"])

    assert [port["name"] for port in payload["ports"]] == ["y", "gain"]
    # `counts` describes the FMU, not the filtered page.
    assert payload["counts"]["local"] == 1
    assert payload["total"] == 2
    assert payload["truncated"] is False


def test_port_listing_can_be_filtered_by_name_pattern():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    payload = _ports_call(bridge, fmu="a.fmu", name_pattern="^g")

    assert [port["name"] for port in payload["ports"]] == ["gain"]


def test_an_invalid_pattern_is_reported_rather_than_crashing():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    with pytest.raises(Exception, match="Invalid regular expression"):
        _ports_call(bridge, fmu="a.fmu", name_pattern="[unclosed")


def test_port_listing_is_paginated(tmp_path):
    """A large FMU is listed page by page, never dumped whole."""
    bridge = FakeBridge()
    bridge.fmus["big.fmu"] = FakeBridge._description("big.fmu", port_count=500)

    first = _ports_call(bridge, fmu="big.fmu", limit=10)
    assert first["returned"] == 10
    assert first["total"] == 503
    assert first["truncated"] is True

    second = _ports_call(bridge, fmu="big.fmu", limit=10, offset=10)
    assert [p["name"] for p in second["ports"]] != [p["name"] for p in first["ports"]]

    last = _ports_call(bridge, fmu="big.fmu", limit=10, offset=500)
    assert last["truncated"] is False


def test_the_default_limit_keeps_the_answer_small():
    bridge = FakeBridge()
    bridge.fmus["big.fmu"] = FakeBridge._description("big.fmu", port_count=500)

    payload = _ports_call(bridge, fmu="big.fmu")

    assert payload["returned"] == DEFAULT_PORT_LIMIT == 50
    assert payload["truncated"] is True


def test_ports_are_compact():
    """Undeclared attributes are left out, long descriptions cut."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")
    bridge.fmus["a.fmu"]["ports"][0]["description"] = "x" * 200
    bridge.fmus["a.fmu"]["ports"][1]["description"] = "short"

    ports = _ports_call(bridge, fmu="a.fmu")["ports"]

    assert ports[0]["description"] == "x" * (MAX_DESCRIPTION_LENGTH - 1) + "…"
    assert ports[1] == {"name": "y", "type": "Real", "causality": "output", "description": "short"}
    assert "unit" not in ports[0] and "variability" not in ports[0]


def test_the_page_size_is_bounded():
    bridge = FakeBridge()
    bridge.fmus["big.fmu"] = FakeBridge._description("big.fmu", port_count=500)

    assert _ports_call(bridge, fmu="big.fmu", limit=MAX_PORT_LIMIT)["returned"] == MAX_PORT_LIMIT
    with pytest.raises(ToolError, match="limit"):
        _ports_call(bridge, fmu="big.fmu", limit=MAX_PORT_LIMIT + 1)


def test_inspecting_a_file_does_not_add_it_to_the_assembly(tmp_path):
    """A file is inspected with `inspect_fmu_file`, without being added to the
    assembly; `list_fmu_ports` only takes the name of an FMU of the assembly."""
    bridge = FakeBridge()
    candidate = fmu_file(tmp_path, "candidate.fmu")

    payload = _ports_call(bridge, tool="inspect_fmu_file", path=str(candidate))

    assert payload["fmu"] == "candidate.fmu"
    assert bridge.list_fmus() == []
    assert not any(call[0] == "add_fmu" for call in bridge.calls)


def test_listing_the_ports_of_a_file_path_is_refused(tmp_path):
    """`list_fmu_ports` is about the canvas: a path must be redirected to
    `inspect_fmu_file` instead of being silently accepted."""
    bridge = FakeBridge()
    candidate = fmu_file(tmp_path, "candidate.fmu")

    with pytest.raises(Exception, match="not in the assembly"):
        _ports_call(bridge, fmu=str(candidate))


def test_adding_an_fmu_summarises_what_it_brings(tmp_path):
    """`add_fmu` describes the added FMU, so that no extra round-trip is needed
    to learn what it brings."""
    bridge = FakeBridge()
    source = fmu_file(tmp_path, "model.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("add_fmu", {"path": str(source)})

    payload = run(scenario()).structured_content
    assert payload["fmu"] == "model.fmu"
    assert payload["fmi_version"] == 2
    assert payload["counts"]["output"] == 1


def test_removing_an_fmu_reports_the_discarded_links(tmp_path):
    """`remove_fmu` reports the links removed with the FMU."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("remove_fmu", {"name": "a.fmu"})

    payload = run(scenario()).structured_content
    assert payload == {"fmu": "a.fmu", "removed_links": 0}


def test_save_as_fmu_defaults_are_forwarded(tmp_path):
    bridge = FakeBridge()
    destination = tmp_path / "out.fmu"

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("save_as_fmu", {"path": str(destination)})

    assert run(scenario()).data == str(destination.resolve())
    assert ("save_as_fmu", str(destination.resolve()), 2, False) in bridge.calls


@pytest.mark.parametrize("fmi_version", [2, 3])
def test_save_as_fmu_accepts_supported_fmi_versions(tmp_path, fmi_version):
    bridge = FakeBridge()
    destination = tmp_path / "out.fmu"

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("save_as_fmu", {"path": str(destination),
                                                          "fmi_version": fmi_version})

    assert run(scenario()).data == str(destination.resolve())


@pytest.mark.parametrize("fmi_version", [0, 1, 7, 42, "2"])
def test_save_as_fmu_rejects_unsupported_fmi_versions(tmp_path, fmi_version):
    """An unsupported version is refused, instead of building a corrupted FMU
    (empty ``modelDescription.xml``) while reporting success."""
    bridge = FakeBridge()

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("save_as_fmu", {"path": str(tmp_path / "out.fmu"),
                                                          "fmi_version": fmi_version})

    with pytest.raises(Exception):
        run(scenario())
    # The request must be rejected *before* reaching the backend.
    assert not any(call[0] == "save_as_fmu" for call in bridge.calls)


def test_save_as_fmu_declares_the_supported_versions_in_its_schema():
    tools, _ = run(inventory(FakeBridge()))
    schema = input_schema(next(tool for tool in tools if tool.name == "save_as_fmu"))
    assert schema["properties"]["fmi_version"]["enum"] == list(SUPPORTED_FMI_VERSIONS)


def test_bridge_errors_are_reported_to_the_client():
    async def scenario():
        async with fastmcp.Client(build_server(FakeBridge())) as client:
            return await client.call_tool("list_fmu_ports", {"fmu": "ghost.fmu"})

    with pytest.raises(Exception, match="ghost.fmu"):
        run(scenario())


# --------------------------------------------------------------------------- #
#                         assembly paging and analysis                        #
# --------------------------------------------------------------------------- #
class NestedBridge(FakeBridge):
    """Serves the nested assembly of `tests/data/containers/arch`, its root FMUs designated by path."""

    def __init__(self, assembly):
        super().__init__()
        self.assembly = assembly

    def get_assembly_json(self):
        return self.assembly


def test_assembly_is_paged_by_container_and_section(data_dir):
    """A large assembly is read one container, then one section, at a time; the FMUs are designated by name, as in
    the other tools."""
    assembly = json.loads((data_dir / "containers" / "arch" / "nested.json").read_text())
    assembly["fmu"] = [f"/models/{fmu}" for fmu in assembly["fmu"]]

    async def scenario():
        async with fastmcp.Client(build_server(NestedBridge(assembly))) as client:
            whole = (await client.call_tool("get_assembly_json", {})).data
            level = (await client.call_tool("get_assembly_json", {"node": "level1.fmu"})).data
            page = (await client.call_tool("get_assembly_json", {"node": "level1.fmu", "section": "input",
                                                                 "limit": 2})).data
            resource = json.loads((await client.read_resource("assembly://current"))[0].text)
            return whole, level, page, resource

    whole, level, page, resource = run(scenario())
    assert whole["fmu"] == ["fmu0a.fmu", "fmu0b.fmu"]
    assert resource == whole
    assert level["name"] == "level1.fmu" and level["counts"]["link"] == 4
    assert page["total"] == 3 and page["returned"] == 2 and page["truncated"] is True


def test_analyze_assembly_summarises_and_lints(data_dir):
    """`analyze_assembly`: one read-only tool, two modes (summary, lint), optionally on one container."""
    assembly = json.loads((data_dir / "containers" / "arch" / "hierarchical.json").read_text())

    async def scenario():
        async with fastmcp.Client(build_server(NestedBridge(assembly))) as client:
            summary = (await client.call_tool("analyze_assembly", {})).data
            sub = (await client.call_tool("analyze_assembly", {"node": "level1.fmu"})).data
            lint = (await client.call_tool("analyze_assembly", {"mode": "lint"})).data
            return summary, sub, lint

    summary, sub, lint = run(scenario())
    assert summary["fmus"] == ["gain.fmu"]
    assert summary["containers"][0]["name"] == "level1.fmu"
    assert sub["name"] == "level1.fmu" and sub["options"] == {"step_size": 0.01}
    rules = {group["rule"] for group in lint["findings"]}
    assert "step-ratio" in rules
    # The fake bridge knows none of these FMUs: their ports are reported as not checked.
    assert "not-checked" in rules


def test_analyze_assembly_lints_the_ports_with_the_builder(tmp_path):
    """Through the headless bridge (flat assembly): a wired assembly passes the builder."""
    from fmu_manipulation_toolbox.assistant.headless import HeadlessAssemblyBridge
    from _helpers.mcp_budget import make_fmu

    make_fmu(tmp_path / "a.fmu", outputs=["y"])
    make_fmu(tmp_path / "b.fmu", inputs=["y", "free"], outputs=["z"])

    async def scenario():
        server = build_server(HeadlessAssemblyBridge(), policy=PathPolicy(tmp_path))
        async with fastmcp.Client(server) as client:
            for name in ("a.fmu", "b.fmu"):
                await client.call_tool("add_fmu", {"path": str(tmp_path / name)})
            await client.call_tool("add_link", {"from_fmu": "a.fmu", "from_port": "y",
                                                "to_fmu": "b.fmu", "to_port": "y"})
            return (await client.call_tool("analyze_assembly", {"mode": "lint"})).data

    report = run(scenario())
    assert report["error_count"] == 0
    assert "not-checked" not in {group["rule"] for group in report["findings"]}


def test_an_unknown_container_is_reported(data_dir):
    assembly = json.loads((data_dir / "containers" / "arch" / "nested.json").read_text())

    async def scenario():
        async with fastmcp.Client(build_server(NestedBridge(assembly))) as client:
            await client.call_tool("get_assembly_json", {"node": "nope.fmu"})

    with pytest.raises(ToolError, match="No container is named 'nope.fmu'"):
        run(scenario())


# --------------------------------------------------------------------------- #
#                               assembly edition                              #
# --------------------------------------------------------------------------- #
def test_links_can_be_created_in_bulk(tmp_path):
    """Several links are created in one call, not one round-trip per link."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")
    bridge.add_fmu("b.fmu")

    payload = call_tool(bridge, "add_links", {"links": [
        {"from_fmu": "a.fmu", "from_port": "y", "to_fmu": "b.fmu", "to_port": "u"},
        {"from_fmu": "b.fmu", "from_port": "y", "to_fmu": "a.fmu", "to_port": "u"},
    ]}).structured_content

    assert len(payload["created"]) == 2
    assert payload["failed"] == []


def test_a_rejected_link_does_not_hide_the_others(tmp_path):
    """Partial success must be reported as such, not as a blanket failure."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")
    bridge.add_fmu("b.fmu")

    payload = call_tool(bridge, "add_links", {"links": [
        {"from_fmu": "a.fmu", "from_port": "y", "to_fmu": "b.fmu", "to_port": "u"},
        {"from_fmu": "a.fmu", "from_port": "nope", "to_fmu": "b.fmu", "to_port": "u"},
    ]}).structured_content

    assert len(payload["created"]) == 1
    assert len(payload["failed"]) == 1
    assert "is not an output" in payload["failed"][0]["reason"]
    assert "a.fmu/nope" in payload["failed"][0]["link"]


def test_an_empty_bulk_request_is_rejected():
    with pytest.raises(ToolError):
        call_tool(FakeBridge(), "add_links", {"links": []})


def test_a_link_can_be_removed():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")
    bridge.add_link("a.fmu", "y", "a.fmu", "u")

    call_tool(bridge, "remove_link", {"from_fmu": "a.fmu", "from_port": "y",
                                  "to_fmu": "a.fmu", "to_port": "u"})

    assert bridge.links == []


def test_removing_a_link_that_does_not_exist_is_reported():
    """Silently doing nothing would let the client believe it undid something."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    with pytest.raises(ToolError, match="no link"):
        call_tool(bridge, "remove_link", {"from_fmu": "a.fmu", "from_port": "y",
                                      "to_fmu": "a.fmu", "to_port": "u"})


def test_a_start_value_can_be_unset():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")
    bridge.set_start_value("a.fmu", "u", "1.5")

    call_tool(bridge, "unset_start_value", {"fmu": "a.fmu", "port": "u"})

    assert bridge.start_values == {}


def test_unsetting_a_start_value_that_was_never_set_is_reported():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    with pytest.raises(ToolError, match="No start value"):
        call_tool(bridge, "unset_start_value", {"fmu": "a.fmu", "port": "u"})


# --------------------------------------------------------------------------- #
#                              write guard-rails                              #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tool, name", [("save_as_json", "out.csv"),
                                        ("save_as_json", "out.fmu"),
                                        ("save_as_fmu", "out.json"),
                                        ("save_as_fmu", "out.txt")])
def test_saving_rejects_a_foreign_extension(tmp_path, tool, name):
    """A file is only written with the extension of its format: `save_as_json`
    must not overwrite a versioned `.csv` file, for instance."""
    bridge = FakeBridge()
    with pytest.raises(Exception, match="must end with"):
        call_tool(bridge, tool, {"path": str(tmp_path / name)})
    assert not bridge.calls


@pytest.mark.parametrize("tool, name", [("save_as_json", "out.json"),
                                        ("save_as_fmu", "out.fmu")])
def test_saving_refuses_to_overwrite_by_default(tmp_path, tool, name):
    existing = tmp_path / name
    existing.write_text("precious")
    bridge = FakeBridge()

    with pytest.raises(Exception, match="already exists"):
        call_tool(bridge, tool, {"path": str(existing)})

    assert not bridge.calls
    assert existing.read_text() == "precious"


@pytest.mark.parametrize("tool, name", [("save_as_json", "out.json"),
                                        ("save_as_fmu", "out.fmu")])
def test_saving_overwrites_when_explicitly_allowed(tmp_path, tool, name):
    existing = tmp_path / name
    existing.write_text("precious")
    bridge = FakeBridge()

    result = call_tool(bridge, tool, {"path": str(existing), "overwrite": True})

    assert result.data == str(existing.resolve())
    assert bridge.calls


def test_saving_rejects_a_missing_directory(tmp_path):
    with pytest.raises(Exception, match="Directory does not exist"):
        call_tool(FakeBridge(), "save_as_json", {"path": str(tmp_path / "nope" / "out.json")})


def test_add_fmu_rejects_a_missing_file(tmp_path):
    bridge = FakeBridge()
    with pytest.raises(Exception, match="File not found"):
        call_tool(bridge, "add_fmu", {"path": str(tmp_path / "ghost.fmu")})
    assert not bridge.calls


def test_add_fmu_rejects_a_foreign_extension(tmp_path):
    bridge = FakeBridge()
    source = tmp_path / "model.zip"
    source.write_bytes(b"")
    with pytest.raises(Exception, match="must end with"):
        call_tool(bridge, "add_fmu", {"path": str(source)})
    assert not bridge.calls


def test_paths_outside_the_allowed_root_are_rejected(tmp_path):
    """With a root configured, the assistant cannot roam the filesystem."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    policy = PathPolicy(root=allowed)
    bridge = FakeBridge()

    with pytest.raises(Exception, match="outside the allowed directory"):
        call_tool(bridge, "save_as_json", {"path": str(outside / "out.json")}, policy=policy)
    assert not bridge.calls

    result = call_tool(bridge, "save_as_json", {"path": str(allowed / "out.json")}, policy=policy)
    assert result.data == str((allowed / "out.json").resolve())


def test_traversal_out_of_the_allowed_root_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    policy = PathPolicy(root=allowed)

    with pytest.raises(Exception, match="outside the allowed directory"):
        call_tool(FakeBridge(), "save_as_json",
              {"path": str(allowed / ".." / "escaped.json")}, policy=policy)


def test_policy_rejects_a_root_that_is_not_a_directory(tmp_path):
    with pytest.raises(PathValidationError, match="not a directory"):
        PathPolicy(root=tmp_path / "missing")


# --------------------------------------------------------------------------- #
#                             end-to-end scenarios                            #
# --------------------------------------------------------------------------- #
def test_scenario_assemble_two_fmus_and_export_json(tmp_path):
    """Add two FMUs, wire them, review and export."""
    bridge = FakeBridge()
    first, second = fmu_file(tmp_path, "position.fmu"), fmu_file(tmp_path, "velocity.fmu")
    destination = tmp_path / "assembly.json"

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            assert (await client.call_tool("list_fmus", {})).data == []
            await client.call_tool("add_fmu", {"path": str(first)})
            await client.call_tool("add_fmu", {"path": str(second)})

            ports = (await client.call_tool("list_fmu_ports", {"fmu": "position.fmu"})).data
            assert [port.name for port in ports.ports if port.causality == "output"] == ["y"]

            await client.call_tool("add_link", {"from_fmu": "velocity.fmu", "from_port": "y",
                                                "to_fmu": "position.fmu", "to_port": "u"})
            await client.call_tool("set_container_options", {"options": {"step_size": 0.01}})

            assembly = (await client.call_tool("get_assembly_json", {})).data
            assert assembly["fmu"] == ["position.fmu", "velocity.fmu"]
            assert assembly["link"] == [["velocity.fmu", "y", "position.fmu", "u"]]

            return (await client.call_tool("save_as_json", {"path": str(destination)})).data

    assert run(scenario()) == str(destination.resolve())
    assert bridge.options["step_size"] == 0.01


def test_scenario_build_a_container(tmp_path):
    """Assemble, then build the container FMU."""
    bridge = FakeBridge()
    source = fmu_file(tmp_path, "model.fmu")
    destination = tmp_path / "container.fmu"

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            await client.call_tool("add_fmu", {"path": str(source)})
            await client.call_tool("expose_input", {"fmu": "model.fmu", "port": "u"})
            await client.call_tool("expose_output", {"fmu": "model.fmu", "port": "y"})
            await client.call_tool("set_start_value", {"fmu": "model.fmu", "port": "u",
                                                       "value": "1.5"})
            return (await client.call_tool("save_as_fmu", {"path": str(destination),
                                                           "fmi_version": 3})).data

    assert run(scenario()) == str(destination.resolve())
    assert ("save_as_fmu", str(destination.resolve()), 3, False) in bridge.calls
    assert ("set_start_value", "model.fmu", "u", "1.5") in bridge.calls


@pytest.mark.parametrize("tool, arguments, expected", [
    ("add_link", {"from_fmu": "a.fmu", "from_port": "nope",
                  "to_fmu": "a.fmu", "to_port": "u"}, "is not an output"),
    ("list_fmu_ports", {"fmu": "ghost.fmu"}, "ghost.fmu"),
    # A misspelled option is caught by the schema; the message names it and lists the allowed ones.
    ("set_container_options", {"options": {"stepsize": 1}}, r"unknown option 'stepsize' \(allowed: .*step_size"),
    ("remove_fmu", {"name": "ghost.fmu"}, "is not in the assembly"),
])
def test_scenario_errors_are_actionable(tmp_path, tool, arguments, expected):
    """The client must get a message it can act upon."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool(tool, arguments)

    with pytest.raises(Exception, match=expected):
        run(scenario())
