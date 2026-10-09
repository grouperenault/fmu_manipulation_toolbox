"""Unit tests for the MCP server exposed by the ``assistant`` package.

These tests drive the server through an in-memory ``fastmcp.Client`` against a
**fake bridge**, so no Qt (and no GUI) is involved: they pin the MCP contract
(tool/resource inventory and signatures) independently of the backend that
applies the operations.

The expected inventory below is the one measured on the pre-refactoring server
(see ``docs/mcp_audit.md``); it is the regression net for the follow-up PRs.
"""
import asyncio
import importlib
import json
import logging
import sys
import threading
import time

import pytest

pytestmark = [pytest.mark.unit]

fastmcp = pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")

from pathlib import Path
from fastmcp.exceptions import ToolError  # noqa: E402

from fmu_manipulation_toolbox.assistant import (  # noqa: E402
    DEFAULT_PORT, DEFAULT_TIMEOUT, PORT_ENV_VAR, TIMEOUT_ENV_VAR, AssemblyBridge,
    PathPolicy, PathValidationError, build_server, resolve_port, resolve_timeout,
)
from fmu_manipulation_toolbox.assistant.bridge import SUPPORTED_FMI_VERSIONS  # noqa: E402
from fmu_manipulation_toolbox.assistant.server import describe_argument_errors  # noqa: E402

#: Tool name -> ordered parameter names.
#: Starts from the inventory measured before the refactoring; the ``overwrite``
#: flags were added when the write guard-rails landed (B3).
EXPECTED_TOOLS = {
    "list_fmus": [],
    "list_fmu_ports": ["fmu", "causality", "name_pattern", "offset", "limit"],
    "inspect_fmu_file": ["path", "causality", "name_pattern", "offset", "limit"],
    "add_fmu": ["path"],
    "remove_fmu": ["name"],
    "add_link": ["from_fmu", "from_port", "to_fmu", "to_port"],
    "add_links": ["links"],
    "remove_link": ["from_fmu", "from_port", "to_fmu", "to_port"],
    "expose_input": ["fmu", "port"],
    "expose_output": ["fmu", "port"],
    "set_start_value": ["fmu", "port", "value"],
    "unset_start_value": ["fmu", "port"],
    "set_container_options": ["options"],
    "get_assembly_json": [],
    "save_as_json": ["path", "overwrite"],
    "save_as_fmu": ["path", "fmi_version", "datalog", "overwrite"],
    # Single-FMU tools: they never touch the assembly (audit I8).
    "summarize_fmu": ["path"],
    "check_fmu": ["path"],
    "dump_ports_csv": ["fmu", "path", "overwrite"],
    "rename_ports_from_csv": ["fmu", "csv", "output", "overwrite"],
    "apply_operation": ["fmu", "output", "operation", "argument", "causality", "overwrite"],
}

EXPECTED_RESOURCES = {"guide://usage", "assembly://current",
                      "fmi://conventions", "container://options"}

EXPECTED_RESOURCE_TEMPLATES = {"fmu://{name}/ports"}

EXPECTED_PROMPTS = {"build_container", "diagnose_assembly", "inspect_fmu"}


def _port(name, causality, type_="Real", **extra):
    port = {"name": name, "type": type_, "causality": causality,
            "variability": None, "unit": None, "start": None, "description": None}
    port.update(extra)
    return port


class FakeBridge:
    """In-memory :class:`AssemblyBridge` recording the calls it receives."""

    def __init__(self):
        self.calls = []
        self.fmus = {}
        self.links = []
        self.start_values = {}
        self.options = {"step_size": None, "mt": False, "auto_link": True}

    def _record(self, name, *args):
        self.calls.append((name,) + args)

    @staticmethod
    def _description(name, port_count=1):
        ports = [_port("u", "input", start="0"), _port("y", "output"),
                 _port("gain", "parameter", start="1"), _port("state", "local")]
        ports += [_port(f"extra_{i}", "input") for i in range(port_count - 1)]
        return {
            "fmu": name,
            "path": f"/models/{name}",
            "fmi_version": 2,
            "generator": "fake",
            "kinds": ["CoSimulation"],
            "terminals": [],
            "ports": ports,
        }

    # -- introspection -----------------------------------------------------
    def list_fmus(self):
        self._record("list_fmus")
        return sorted(self.fmus)

    def list_fmu_ports(self, fmu):
        self._record("list_fmu_ports", fmu)
        if fmu not in self.fmus:
            raise ValueError(f"FMU '{fmu}' is not in the assembly (currently: none).")
        return self.fmus[fmu]

    def inspect_fmu_file(self, path):
        self._record("inspect_fmu_file", path)
        return self._description(str(Path(path).name))

    def get_assembly_json(self):
        self._record("get_assembly_json")
        return {"name": "container.fmu", "fmu": sorted(self.fmus), "link": self.links}

    # -- mutations ---------------------------------------------------------
    def add_fmu(self, path):
        self._record("add_fmu", path)
        name = str(Path(path).name)
        self.fmus[name] = self._description(name)
        return {
            "fmu": name,
            "path": path,
            "fmi_version": 2,
            "generator": "fake",
            "kinds": ["CoSimulation"],
            "counts": {"input": 1, "output": 1, "parameter": 1, "local": 1},
            "terminals": [],
        }

    def remove_fmu(self, name):
        self._record("remove_fmu", name)
        if name not in self.fmus:
            raise ValueError(f"FMU '{name}' is not in the assembly.")
        del self.fmus[name]
        return {"fmu": name, "removed_links": 0}

    def add_link(self, from_fmu, from_port, to_fmu, to_port):
        self._record("add_link", from_fmu, from_port, to_fmu, to_port)
        for name in (from_fmu, to_fmu):
            if name not in self.fmus:
                raise ValueError(f"FMU '{name}' is not in the assembly.")
        outputs = [p["name"] for p in self.fmus[from_fmu]["ports"]
                   if p["causality"] == "output"]
        if from_port not in outputs:
            raise ValueError(f"'{from_port}' is not an output of '{from_fmu}'.")
        self.links.append([from_fmu, from_port, to_fmu, to_port])
        return f"{from_fmu}/{from_port} -> {to_fmu}/{to_port}"

    def remove_link(self, from_fmu, from_port, to_fmu, to_port):
        self._record("remove_link", from_fmu, from_port, to_fmu, to_port)
        link = [from_fmu, from_port, to_fmu, to_port]
        if link not in self.links:
            raise ValueError(f"There is no link {from_fmu}/{from_port} -> "
                             f"{to_fmu}/{to_port}.")
        self.links.remove(link)
        return f"{from_fmu}/{from_port} -> {to_fmu}/{to_port}"

    def expose_input(self, fmu, port):
        self._record("expose_input", fmu, port)
        return f"{fmu}/{port}"

    def expose_output(self, fmu, port):
        self._record("expose_output", fmu, port)
        return f"{fmu}/{port}"

    def set_start_value(self, fmu, port, value):
        self._record("set_start_value", fmu, port, value)
        self.start_values[(fmu, port)] = value
        return f"{fmu}/{port} = {value}"

    def unset_start_value(self, fmu, port):
        self._record("unset_start_value", fmu, port)
        if (fmu, port) not in self.start_values:
            raise ValueError(f"No start value was set on {fmu}/{port}.")
        del self.start_values[(fmu, port)]
        return f"{fmu}/{port}"

    def set_container_options(self, options):
        self._record("set_container_options", options)
        unknown = set(options) - set(self.options)
        if unknown:
            raise ValueError(f"Unknown container option(s): {sorted(unknown)}.")
        self.options.update(options)
        return dict(self.options)

    # -- build / export ----------------------------------------------------
    def save_as_json(self, path):
        self._record("save_as_json", path)
        return path

    def save_as_fmu(self, path, fmi_version=2, datalog=False):
        self._record("save_as_fmu", path, fmi_version, datalog)
        if fmi_version not in SUPPORTED_FMI_VERSIONS:
            raise ValueError(f"Unsupported FMI version {fmi_version!r}.")
        return path


def _run(coro):
    return asyncio.run(coro)


def _input_schema(tool):
    """Read a tool's input schema, whatever the FastMCP version.

    FastMCP 4 renamed ``Tool.inputSchema`` to ``Tool.input_schema`` and
    deprecated the old spelling.
    """
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = tool.inputSchema
    return schema or {}


def _fmu_file(directory, name):
    """Create a placeholder `.fmu` file so path validation accepts it."""
    path = directory / name
    path.write_bytes(b"not a real FMU")
    return path


async def _inventory(bridge):
    async with fastmcp.Client(build_server(bridge)) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        return tools, resources


# --------------------------------------------------------------------------- #
#                                  contract                                    #
# --------------------------------------------------------------------------- #
def test_fake_bridge_satisfies_the_protocol():
    assert isinstance(FakeBridge(), AssemblyBridge)


def test_the_server_advertises_a_stable_name():
    """The name clients see. Renaming it is a breaking change for anyone whose
    configuration already references it, hence this reminder."""
    assert build_server(FakeBridge()).name == "fmutool"


def test_tool_inventory_matches_reference():
    tools, _ = _run(_inventory(FakeBridge()))
    assert {tool.name for tool in tools} == set(EXPECTED_TOOLS)


def test_tool_signatures_match_reference():
    tools, _ = _run(_inventory(FakeBridge()))
    for tool in tools:
        schema = _input_schema(tool)
        assert list((schema.get("properties") or {}).keys()) == EXPECTED_TOOLS[tool.name], tool.name


def test_every_tool_is_documented():
    tools, _ = _run(_inventory(FakeBridge()))
    assert all(tool.description for tool in tools)


def test_resource_inventory_matches_reference():
    _, resources = _run(_inventory(FakeBridge()))
    assert {str(resource.uri) for resource in resources} == EXPECTED_RESOURCES


# --------------------------------------------------------------------------- #
#                              tools reach the bridge                           #
# --------------------------------------------------------------------------- #
def test_tools_are_forwarded_to_the_bridge(tmp_path):
    bridge = FakeBridge()
    first, second = _fmu_file(tmp_path, "a.fmu"), _fmu_file(tmp_path, "b.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            await client.call_tool("add_fmu", {"path": str(first)})
            await client.call_tool("add_fmu", {"path": str(second)})
            await client.call_tool("add_link", {"from_fmu": "a.fmu", "from_port": "y",
                                                "to_fmu": "b.fmu", "to_port": "u"})
            return await client.call_tool("list_fmus", {})

    result = _run(scenario())
    assert result.data == ["a.fmu", "b.fmu"]
    assert ("add_link", "a.fmu", "y", "b.fmu", "u") in bridge.calls


# --------------------------------------------------------------------------- #
#             structured, bounded port listings (audit I3, M6 and M8)           #
# --------------------------------------------------------------------------- #
def _ports_call(bridge, tool="list_fmu_ports", **arguments):
    """Call a port-listing tool and return its structured payload as a dict."""
    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool(tool, arguments)

    return _run(scenario()).structured_content


def test_port_listing_reports_every_causality(tmp_path):
    """Regression test for M8: parameters and locals used to be invisible,
    inputs and parameters being merged into a single `inputs` list."""
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
    """Regression test for I3: a 2000-port FMU used to be dumped whole."""
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

    assert payload["returned"] <= 100
    assert payload["truncated"] is True


def test_inspecting_a_file_does_not_add_it_to_the_assembly(tmp_path):
    """Regression test for M6: `list_fmu_ports` used to accept both a canvas
    name and a file path, hiding which of the two the caller meant."""
    bridge = FakeBridge()
    candidate = _fmu_file(tmp_path, "candidate.fmu")

    payload = _ports_call(bridge, tool="inspect_fmu_file", path=str(candidate))

    assert payload["fmu"] == "candidate.fmu"
    assert bridge.list_fmus() == []
    assert not any(call[0] == "add_fmu" for call in bridge.calls)


def test_listing_the_ports_of_a_file_path_is_refused(tmp_path):
    """`list_fmu_ports` is about the canvas: a path must be redirected to
    `inspect_fmu_file` instead of being silently accepted."""
    bridge = FakeBridge()
    candidate = _fmu_file(tmp_path, "candidate.fmu")

    with pytest.raises(Exception, match="not in the assembly"):
        _ports_call(bridge, fmu=str(candidate))


def test_adding_an_fmu_summarises_what_it_brings(tmp_path):
    """Regression test for M6: `add_fmu` only returned a name, forcing an
    extra round-trip to learn anything about the FMU."""
    bridge = FakeBridge()
    source = _fmu_file(tmp_path, "model.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("add_fmu", {"path": str(source)})

    payload = _run(scenario()).structured_content
    assert payload["fmu"] == "model.fmu"
    assert payload["fmi_version"] == 2
    assert payload["counts"]["output"] == 1


def test_removing_an_fmu_reports_the_discarded_links(tmp_path):
    """Regression test for M6: `remove_fmu` returned a constant `True`, which
    told the caller nothing about the collateral damage."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("remove_fmu", {"name": "a.fmu"})

    payload = _run(scenario()).structured_content
    assert payload == {"fmu": "a.fmu", "removed_links": 0}


def test_save_as_fmu_defaults_are_forwarded(tmp_path):
    bridge = FakeBridge()
    destination = tmp_path / "out.fmu"

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("save_as_fmu", {"path": str(destination)})

    assert _run(scenario()).data == str(destination.resolve())
    assert ("save_as_fmu", str(destination.resolve()), 2, False) in bridge.calls


@pytest.mark.parametrize("fmi_version", [2, 3])
def test_save_as_fmu_accepts_supported_fmi_versions(tmp_path, fmi_version):
    bridge = FakeBridge()
    destination = tmp_path / "out.fmu"

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("save_as_fmu", {"path": str(destination),
                                                          "fmi_version": fmi_version})

    assert _run(scenario()).data == str(destination.resolve())


@pytest.mark.parametrize("fmi_version", [0, 1, 7, 42, "2"])
def test_save_as_fmu_rejects_unsupported_fmi_versions(tmp_path, fmi_version):
    """Regression test for B6: `fmi_version=7` used to build a corrupted FMU
    (empty ``modelDescription.xml``) while reporting success."""
    bridge = FakeBridge()

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool("save_as_fmu", {"path": str(tmp_path / "out.fmu"),
                                                          "fmi_version": fmi_version})

    with pytest.raises(Exception):
        _run(scenario())
    # The request must be rejected *before* reaching the backend.
    assert not any(call[0] == "save_as_fmu" for call in bridge.calls)


def test_save_as_fmu_declares_the_supported_versions_in_its_schema():
    tools, _ = _run(_inventory(FakeBridge()))
    schema = _input_schema(next(tool for tool in tools if tool.name == "save_as_fmu"))
    assert schema["properties"]["fmi_version"]["enum"] == list(SUPPORTED_FMI_VERSIONS)


def test_bridge_errors_are_reported_to_the_client():
    async def scenario():
        async with fastmcp.Client(build_server(FakeBridge())) as client:
            return await client.call_tool("list_fmu_ports", {"fmu": "ghost.fmu"})

    with pytest.raises(Exception, match="ghost.fmu"):
        _run(scenario())


# --------------------------------------------------------------------------- #
#                              argument errors                                 #
# --------------------------------------------------------------------------- #
def _call_error(tool, arguments, tmp_path=None) -> str:
    """Message of the ToolError raised for an invalid call (the bridge must not be reached)."""
    bridge = FakeBridge()

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool(tool, arguments)

    with pytest.raises(ToolError) as error:
        _run(scenario())
    assert not any(call[0] == tool for call in bridge.calls)
    return str(error.value)


@pytest.mark.parametrize("tool, arguments, expected", [
    ("set_container_options", {"options": {"stepsize": 1}},
     "unknown option 'stepsize' (allowed: auto_input, auto_link, auto_local, auto_output, auto_parameter, "
     "mt, profiling, sequential, step_size, ts_multiplier)"),
    ("set_container_options", {"options": {"step_size": -1}},
     "'options.step_size': Input should be greater than 0 (got -1)"),
    ("save_as_fmu", {"path": "out.fmu", "fmi_version": 7}, "'fmi_version': Input should be 2 or 3 (got 7)"),
    ("add_link", {"from_fmu": "a.fmu", "from_port": "y", "to_fmu": "b.fmu"}, "missing required argument 'to_port'"),
    ("list_fmus", {"verbose": True}, "unknown argument 'verbose'"),
], ids=["unknown-option", "constraint", "literal", "missing", "unknown-argument"])
def test_invalid_arguments_are_reported_without_pydantic_noise(tool, arguments, expected):
    """The audit's S8 message ("Unknown container option(s) ... Allowed: [...]") was lost when the
    options became a Pydantic model: FastMCP reported the raw Pydantic text instead."""
    message = _call_error(tool, arguments)
    assert expected in message
    assert message.startswith(f"Invalid arguments for '{tool}': ")
    assert "pydantic" not in message and "validation error for" not in message


def test_describe_argument_errors_follows_schema_references():
    schema = {"properties": {"options": {"anyOf": [{"$ref": "#/$defs/Options"}, {"type": "null"}]}},
              "$defs": {"Options": {"properties": {"b": {}, "a": {}}}}}
    errors = [{"loc": ("options", "c"), "type": "extra_forbidden", "msg": "", "input": 1}]
    assert describe_argument_errors("t", errors, schema) == (
        "Invalid arguments for 't': unknown option 'c' (allowed: a, b). Fix the arguments and call the tool again.")


def test_describe_argument_errors_truncates_long_values():
    errors = [{"loc": ("path",), "type": "string_type", "msg": "Input should be a valid string", "input": ["x"] * 50}]
    message = describe_argument_errors("t", errors, {})
    assert "..." in message and len(message) < 200


# --------------------------------------------------------------------------- #
#                                  resources                                   #
# --------------------------------------------------------------------------- #
def test_usage_guide_resource_is_served():
    async def scenario():
        async with fastmcp.Client(build_server(FakeBridge())) as client:
            return await client.read_resource("guide://usage")

    assert "FMU Container Builder" in _run(scenario())[0].text


def test_current_assembly_resource_serves_json():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.read_resource("assembly://current")

    assert json.loads(_run(scenario())[0].text)["fmu"] == ["a.fmu"]


# --------------------------------------------------------------------------- #
#          portable know-how: prompts and reference resources (I4, I6)          #
# --------------------------------------------------------------------------- #
def _read(bridge, uri):
    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.read_resource(uri)

    return _run(scenario())[0].text


def test_prompt_inventory_matches_reference():
    """Regression test for I6: the know-how only lived in a resource no client
    consults spontaneously."""
    async def scenario():
        async with fastmcp.Client(build_server(FakeBridge())) as client:
            return await client.list_prompts()

    prompts = _run(scenario())
    assert {prompt.name for prompt in prompts} == EXPECTED_PROMPTS
    assert all(prompt.description for prompt in prompts)


@pytest.mark.parametrize("prompt, arguments, expected", [
    ("build_container", {"fmus": "a.fmu, b.fmu"}, "a.fmu, b.fmu"),
    ("build_container", {}, "list_fmus"),
    ("diagnose_assembly", {"symptom": "step too large"}, "step too large"),
    ("inspect_fmu", {"fmu": "controller.fmu"}, "controller.fmu"),
    ("inspect_fmu", {}, "inspect_fmu_file"),
])
def test_prompts_render_with_and_without_arguments(prompt, arguments, expected):
    async def scenario():
        async with fastmcp.Client(build_server(FakeBridge())) as client:
            return await client.get_prompt(prompt, arguments)

    rendered = _run(scenario()).messages[0].content.text
    assert expected in rendered


def test_reference_resources_are_served():
    """Regression test for I4: reference material was missing entirely."""
    bridge = FakeBridge()
    assert "Causality" in _read(bridge, "fmi://conventions")
    assert "step_size" in _read(bridge, "container://options")


def test_the_options_reference_is_derived_from_the_schema():
    """The documented options cannot drift away from the accepted ones."""
    tools, _ = _run(_inventory(FakeBridge()))
    schema = _input_schema(next(t for t in tools if t.name == "set_container_options"))
    accepted = set(_resolve(schema, schema["properties"]["options"])["properties"])

    reference = _read(FakeBridge(), "container://options")

    assert all(f"`{option}`" in reference for option in accepted)


def test_fmu_ports_resource_template_is_exposed():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            templates = await client.list_resource_templates()
            return templates, await client.read_resource("fmu://a.fmu/ports")

    templates, content = _run(scenario())
    assert {t.uri_template for t in templates} == EXPECTED_RESOURCE_TEMPLATES
    assert json.loads(content[0].text)["fmu"] == "a.fmu"


def test_the_usage_guide_has_a_single_source():
    """The guide must not be duplicated between the server and the knowledge
    module, otherwise the two drift apart."""
    from fmu_manipulation_toolbox.assistant import knowledge, server

    assert server.USAGE_GUIDE is knowledge.USAGE_GUIDE


# --------------------------------------------------------------------------- #
#                       write guard-rails (audit finding B3)                    #
# --------------------------------------------------------------------------- #
def _call(bridge, tool, arguments, policy=None):
    async def scenario():
        async with fastmcp.Client(build_server(bridge, policy=policy)) as client:
            return await client.call_tool(tool, arguments)

    return _run(scenario())


@pytest.mark.parametrize("tool, name", [("save_as_json", "out.csv"),
                                        ("save_as_json", "out.fmu"),
                                        ("save_as_fmu", "out.json"),
                                        ("save_as_fmu", "out.txt")])
def test_saving_rejects_a_foreign_extension(tmp_path, tool, name):
    """Regression test for B3: `save_as_json` used to happily write JSON into
    a versioned `.csv` file."""
    bridge = FakeBridge()
    with pytest.raises(Exception, match="must end with"):
        _call(bridge, tool, {"path": str(tmp_path / name)})
    assert not bridge.calls


@pytest.mark.parametrize("tool, name", [("save_as_json", "out.json"),
                                        ("save_as_fmu", "out.fmu")])
def test_saving_refuses_to_overwrite_by_default(tmp_path, tool, name):
    existing = tmp_path / name
    existing.write_text("precious")
    bridge = FakeBridge()

    with pytest.raises(Exception, match="already exists"):
        _call(bridge, tool, {"path": str(existing)})

    assert not bridge.calls
    assert existing.read_text() == "precious"


@pytest.mark.parametrize("tool, name", [("save_as_json", "out.json"),
                                        ("save_as_fmu", "out.fmu")])
def test_saving_overwrites_when_explicitly_allowed(tmp_path, tool, name):
    existing = tmp_path / name
    existing.write_text("precious")
    bridge = FakeBridge()

    result = _call(bridge, tool, {"path": str(existing), "overwrite": True})

    assert result.data == str(existing.resolve())
    assert bridge.calls


def test_saving_rejects_a_missing_directory(tmp_path):
    with pytest.raises(Exception, match="Directory does not exist"):
        _call(FakeBridge(), "save_as_json", {"path": str(tmp_path / "nope" / "out.json")})


def test_add_fmu_rejects_a_missing_file(tmp_path):
    bridge = FakeBridge()
    with pytest.raises(Exception, match="File not found"):
        _call(bridge, "add_fmu", {"path": str(tmp_path / "ghost.fmu")})
    assert not bridge.calls


def test_add_fmu_rejects_a_foreign_extension(tmp_path):
    bridge = FakeBridge()
    source = tmp_path / "model.zip"
    source.write_bytes(b"")
    with pytest.raises(Exception, match="must end with"):
        _call(bridge, "add_fmu", {"path": str(source)})
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
        _call(bridge, "save_as_json", {"path": str(outside / "out.json")}, policy=policy)
    assert not bridge.calls

    result = _call(bridge, "save_as_json", {"path": str(allowed / "out.json")}, policy=policy)
    assert result.data == str((allowed / "out.json").resolve())


def test_traversal_out_of_the_allowed_root_is_rejected(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    policy = PathPolicy(root=allowed)

    with pytest.raises(Exception, match="outside the allowed directory"):
        _call(FakeBridge(), "save_as_json",
              {"path": str(allowed / ".." / "escaped.json")}, policy=policy)


def test_policy_rejects_a_root_that_is_not_a_directory(tmp_path):
    with pytest.raises(PathValidationError, match="not a directory"):
        PathPolicy(root=tmp_path / "missing")


# --------------------------------------------------------------------------- #
#               completing assembly edition (audit §4 "manques")               #
# --------------------------------------------------------------------------- #
def test_links_can_be_created_in_bulk(tmp_path):
    """Wiring used to cost one round-trip per link."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")
    bridge.add_fmu("b.fmu")

    payload = _call(bridge, "add_links", {"links": [
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

    payload = _call(bridge, "add_links", {"links": [
        {"from_fmu": "a.fmu", "from_port": "y", "to_fmu": "b.fmu", "to_port": "u"},
        {"from_fmu": "a.fmu", "from_port": "nope", "to_fmu": "b.fmu", "to_port": "u"},
    ]}).structured_content

    assert len(payload["created"]) == 1
    assert len(payload["failed"]) == 1
    assert "is not an output" in payload["failed"][0]["reason"]
    assert "a.fmu/nope" in payload["failed"][0]["link"]


def test_an_empty_bulk_request_is_rejected():
    with pytest.raises(ToolError):
        _call(FakeBridge(), "add_links", {"links": []})


def test_a_link_can_be_removed():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")
    bridge.add_link("a.fmu", "y", "a.fmu", "u")

    _call(bridge, "remove_link", {"from_fmu": "a.fmu", "from_port": "y",
                                  "to_fmu": "a.fmu", "to_port": "u"})

    assert bridge.links == []


def test_removing_a_link_that_does_not_exist_is_reported():
    """Silently doing nothing would let the client believe it undid something."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    with pytest.raises(ToolError, match="no link"):
        _call(bridge, "remove_link", {"from_fmu": "a.fmu", "from_port": "y",
                                      "to_fmu": "a.fmu", "to_port": "u"})


def test_a_start_value_can_be_unset():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")
    bridge.set_start_value("a.fmu", "u", "1.5")

    _call(bridge, "unset_start_value", {"fmu": "a.fmu", "port": "u"})

    assert bridge.start_values == {}


def test_unsetting_a_start_value_that_was_never_set_is_reported():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    with pytest.raises(ToolError, match="No start value"):
        _call(bridge, "unset_start_value", {"fmu": "a.fmu", "port": "u"})


# --------------------------------------------------------------------------- #
#                       port resolution (audit finding M1)                      #
# --------------------------------------------------------------------------- #
def test_port_defaults_when_the_variable_is_unset(monkeypatch):
    monkeypatch.delenv(PORT_ENV_VAR, raising=False)
    assert resolve_port() == DEFAULT_PORT


def test_port_honours_the_environment(monkeypatch):
    monkeypatch.setenv(PORT_ENV_VAR, "9001")
    assert resolve_port() == 9001


@pytest.mark.parametrize("value", ["", "abc", "80.5", "0", "-1", "65536"])
def test_invalid_port_is_reported_at_startup_not_at_import(monkeypatch, value):
    """Regression test for M1: the port used to be parsed at import time, so a
    malformed value broke an unrelated ``import`` of the package."""
    monkeypatch.setenv(PORT_ENV_VAR, value)

    importlib.reload(importlib.import_module("fmu_manipulation_toolbox.assistant"))

    with pytest.raises(ValueError, match=PORT_ENV_VAR):
        resolve_port()


# --------------------------------------------------------------------------- #
#                     configurable timeout (audit finding I5)                   #
# --------------------------------------------------------------------------- #
def test_timeout_defaults_when_the_variable_is_unset(monkeypatch):
    monkeypatch.delenv(TIMEOUT_ENV_VAR, raising=False)
    assert resolve_timeout() == DEFAULT_TIMEOUT


def test_timeout_honours_the_environment(monkeypatch):
    monkeypatch.setenv(TIMEOUT_ENV_VAR, "12.5")
    assert resolve_timeout() == 12.5


@pytest.mark.parametrize("value", ["", "abc", "0", "-1"])
def test_an_invalid_timeout_is_reported(monkeypatch, value):
    monkeypatch.setenv(TIMEOUT_ENV_VAR, value)
    with pytest.raises(ValueError, match=TIMEOUT_ENV_VAR):
        resolve_timeout()


# --------------------------------------------------------------------------- #
#                      progress reporting (audit finding I5)                    #
# --------------------------------------------------------------------------- #
class SlowBridge(FakeBridge):
    """Bridge whose build blocks, the way a real one does."""

    def __init__(self, delay=0.2):
        super().__init__()
        self._delay = delay
        self.build_thread = None

    def save_as_fmu(self, path, fmi_version=2, datalog=False):
        self.build_thread = threading.current_thread()
        time.sleep(self._delay)
        return super().save_as_fmu(path, fmi_version, datalog)


def test_building_reports_progress(tmp_path):
    """Regression test for I5: the longest tool used to run silently, leaving
    the client unable to tell a slow build from a hung one."""
    bridge = FakeBridge()
    updates = []

    async def scenario():
        async def on_progress(progress, total, message):
            updates.append((progress, total, message))

        async with fastmcp.Client(build_server(bridge),
                                  progress_handler=on_progress) as client:
            return await client.call_tool("save_as_fmu", {"path": str(tmp_path / "out.fmu")})

    _run(scenario())

    assert [(progress, total) for progress, total, _ in updates] == [(0, 2), (2, 2)]
    assert "Building" in updates[0][2]
    assert "out.fmu" in updates[-1][2]


def test_building_does_not_block_the_event_loop(tmp_path):
    """The blocking backend call must be offloaded: an ``async`` tool runs on
    the event loop, so calling it directly would freeze every other exchange —
    including the progress notifications the tool is sending."""
    bridge = SlowBridge()

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            loop_thread = threading.current_thread()
            await client.call_tool("save_as_fmu", {"path": str(tmp_path / "out.fmu")})
            return loop_thread

    loop_thread = _run(scenario())
    assert bridge.build_thread is not None
    assert bridge.build_thread is not loop_thread


def test_a_slow_build_does_not_starve_other_requests(tmp_path):
    """While a build runs, the server must still answer read-only tools."""
    bridge = SlowBridge(delay=0.5)

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            build = asyncio.create_task(
                client.call_tool("save_as_fmu", {"path": str(tmp_path / "out.fmu")}))
            await asyncio.sleep(0.05)
            listed = await asyncio.wait_for(client.call_tool("list_fmus", {}), timeout=0.3)
            await build
            return listed

    assert _run(scenario()).data == []


# --------------------------------------------------------------------------- #
#                    end-to-end scenarios (audit S1, S2 and S8)                 #
# --------------------------------------------------------------------------- #
def test_scenario_assemble_two_fmus_and_export_json(tmp_path):
    """Audit scenario S1: add two FMUs, wire them, review and export."""
    bridge = FakeBridge()
    first, second = _fmu_file(tmp_path, "position.fmu"), _fmu_file(tmp_path, "velocity.fmu")
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

    assert _run(scenario()) == str(destination.resolve())
    assert bridge.options["step_size"] == 0.01


def test_scenario_build_a_container(tmp_path):
    """Audit scenario S2: assemble, then build the container FMU."""
    bridge = FakeBridge()
    source = _fmu_file(tmp_path, "model.fmu")
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

    assert _run(scenario()) == str(destination.resolve())
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
    """Audit scenario S8: the client must get a message it can act upon."""
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool(tool, arguments)

    with pytest.raises(Exception, match=expected):
        _run(scenario())


# --------------------------------------------------------------------------- #
#                   error reporting and annotations (B5, I1)                    #
# --------------------------------------------------------------------------- #
class BrokenBridge(FakeBridge):
    """Bridge whose internals blow up the way a real bug would."""

    def list_fmus(self):
        raise AttributeError("'NoneType' object has no attribute 'fmu_nodes'")


def test_domain_errors_keep_their_message():
    with pytest.raises(ToolError, match="is not in the assembly"):
        _call(FakeBridge(), "remove_fmu", {"name": "ghost.fmu"})


def test_internal_errors_are_not_leaked_verbatim(caplog):
    """Regression test for B5: an internal ``AttributeError`` used to reach the
    client as "'NoneType' object has no attribute ...", which no model can act
    upon."""
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        with pytest.raises(ToolError) as excinfo:
            _call(BrokenBridge(), "list_fmus", {})

    message = str(excinfo.value)
    assert "NoneType" not in message
    assert "bug in the FMU Manipulation Toolbox" in message
    assert "AttributeError" in message
    # The details are kept server-side, with the traceback, for the maintainer.
    assert "Unexpected error in MCP tool 'list_fmus'" in caplog.text
    assert "fmu_nodes" in caplog.text


@pytest.mark.parametrize("tool", sorted(EXPECTED_TOOLS))
def test_every_tool_declares_its_behaviour(tool):
    tools, _ = _run(_inventory(FakeBridge()))
    annotations = next(t for t in tools if t.name == tool).annotations
    assert annotations is not None, tool
    assert annotations.read_only_hint is not None, tool


@pytest.mark.parametrize("tool", ["list_fmus", "list_fmu_ports", "get_assembly_json"])
def test_read_only_tools_are_flagged(tool):
    tools, _ = _run(_inventory(FakeBridge()))
    annotations = next(t for t in tools if t.name == tool).annotations
    assert annotations.read_only_hint is True
    assert annotations.idempotent_hint is True


@pytest.mark.parametrize("tool", ["remove_fmu", "save_as_json", "save_as_fmu"])
def test_destructive_tools_are_flagged(tool):
    tools, _ = _run(_inventory(FakeBridge()))
    annotations = next(t for t in tools if t.name == tool).annotations
    assert annotations.destructive_hint is True
    assert annotations.read_only_hint is False


@pytest.mark.parametrize("tool", ["expose_input", "expose_output", "set_start_value",
                                  "set_container_options", "add_fmu", "add_link"])
def test_idempotent_writes_are_flagged(tool):
    tools, _ = _run(_inventory(FakeBridge()))
    annotations = next(t for t in tools if t.name == tool).annotations
    assert annotations.idempotent_hint is True
    assert annotations.read_only_hint is False
    assert annotations.destructive_hint is not True


# --------------------------------------------------------------------------- #
#                    strict input typing (audit I2 and M5)                      #
# --------------------------------------------------------------------------- #
def _resolve(schema, node):
    """Follow a ``$ref`` if the model was not inlined by FastMCP."""
    ref = node.get("$ref")
    if ref is None:
        return node
    return schema["$defs"][ref.rsplit("/", 1)[-1]]


def test_container_options_advertise_their_keys():
    """Regression test for I2: the options used to be an opaque
    ``Dict[str, Any]``, so the model could not know which keys exist."""
    tools, _ = _run(_inventory(FakeBridge()))
    schema = _input_schema(next(t for t in tools if t.name == "set_container_options"))
    options = _resolve(schema, schema["properties"]["options"])

    assert set(options["properties"]) == {
        "step_size", "mt", "profiling", "sequential", "auto_link", "auto_input",
        "auto_output", "auto_parameter", "auto_local", "ts_multiplier",
    }
    assert options["additionalProperties"] is False
    assert all(field.get("description") for field in options["properties"].values())


def test_container_options_only_forward_what_was_provided():
    bridge = FakeBridge()
    bridge.options = {"step_size": None, "mt": False, "auto_link": True}

    _call(bridge, "set_container_options", {"options": {"step_size": 0.01}})

    assert ("set_container_options", {"step_size": 0.01}) in bridge.calls
    assert bridge.options["mt"] is False  # untouched


@pytest.mark.parametrize("step_size", [0, -1])
def test_container_options_reject_a_non_positive_step_size(step_size):
    with pytest.raises(ToolError, match="step_size"):
        _call(FakeBridge(), "set_container_options", {"options": {"step_size": step_size}})


@pytest.mark.parametrize("value, expected", [
    (True, "true"),
    (False, "false"),
    (0.01, "0.01"),
    (3, "3"),
    ("some text", "some text"),
])
def test_start_values_are_rendered_the_fmi_way(value, expected):
    """`str(True)` is "True", which FMI does not accept."""
    bridge = FakeBridge()
    _call(bridge, "set_start_value", {"fmu": "a.fmu", "port": "u", "value": value})
    assert ("set_start_value", "a.fmu", "u", expected) in bridge.calls


def test_every_tool_parameter_is_documented():
    """Regression test for M5: parameters used to carry no description."""
    tools, _ = _run(_inventory(FakeBridge()))
    undocumented = []
    for tool in tools:
        for name, field in (_input_schema(tool).get("properties") or {}).items():
            # `$ref` fields point at a model whose own fields are documented.
            if not field.get("description") and "$ref" not in str(field):
                undocumented.append(f"{tool.name}.{name}")
    assert not undocumented


def test_importing_the_package_does_not_require_fastmcp(monkeypatch):
    """The `mcp` extra stays optional: only `build_server` needs it."""
    monkeypatch.setitem(sys.modules, "fastmcp", None)
    monkeypatch.setitem(sys.modules, "pydantic", None)

    module = importlib.reload(importlib.import_module("fmu_manipulation_toolbox.assistant"))

    assert module.DEFAULT_HOST == "127.0.0.1"
