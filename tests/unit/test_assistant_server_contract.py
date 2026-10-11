"""Contract of the MCP server exposed by the ``assistant`` package.

These tests drive the server through an in-memory ``fastmcp.Client`` against a
**fake bridge**, so no Qt (and no GUI) is involved. The expected inventories
below are the published MCP contract: a change of tool, parameter, resource or
prompt must be deliberate, and update them. The schemas, the typing of the
arguments and the reporting of errors are part of that contract.
"""
import importlib
import json
import logging
import sys

import pytest

pytestmark = [pytest.mark.unit]

fastmcp = pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")

from fastmcp.exceptions import ToolError  # noqa: E402
from fmu_manipulation_toolbox.assistant import AssemblyBridge, build_server  # noqa: E402
from fmu_manipulation_toolbox.assistant.server import compact_schema, describe_argument_errors  # noqa: E402

from _helpers.assistant_bridge import FakeBridge, call_tool, input_schema, inventory, resolve_ref, run  # noqa: E402


#: Tool name -> ordered parameter names.
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
    "get_assembly_json": ["node", "section", "offset", "limit"],
    "analyze_assembly": ["mode", "node"],
    "save_as_json": ["path", "overwrite"],
    "save_as_fmu": ["path", "fmi_version", "datalog", "overwrite"],
    # Single-FMU tools: they never touch the assembly.
    "summarize_fmu": ["path"],
    "check_fmu": ["path"],
    "dump_ports_csv": ["fmu", "path", "overwrite"],
    "rename_ports_from_csv": ["fmu", "csv", "output", "overwrite"],
    "apply_operation": ["fmu", "output", "operation", "argument", "causality", "overwrite"],
}

EXPECTED_RESOURCES = {"guide://usage", "assembly://current",
                      "fmi://conventions", "container://options"}

EXPECTED_RESOURCE_TEMPLATES = {"fmu://{name}/ports"}

EXPECTED_PROMPTS = {"build_container", "diagnose_assembly", "inspect_fmu", "analyze_assembly"}


# --------------------------------------------------------------------------- #
#                                   contract                                  #
# --------------------------------------------------------------------------- #
def test_fake_bridge_satisfies_the_protocol():
    assert isinstance(FakeBridge(), AssemblyBridge)


def test_the_server_advertises_a_stable_name():
    """The name clients see. Renaming it is a breaking change for anyone whose
    configuration already references it, hence this reminder."""
    assert build_server(FakeBridge()).name == "fmutool"


def test_tool_inventory_matches_reference():
    tools, _ = run(inventory(FakeBridge()))
    assert {tool.name for tool in tools} == set(EXPECTED_TOOLS)


def test_tool_signatures_match_reference():
    tools, _ = run(inventory(FakeBridge()))
    for tool in tools:
        schema = input_schema(tool)
        assert list((schema.get("properties") or {}).keys()) == EXPECTED_TOOLS[tool.name], tool.name


def test_every_tool_is_documented():
    tools, _ = run(inventory(FakeBridge()))
    assert all(tool.description for tool in tools)


def test_resource_inventory_matches_reference():
    _, resources = run(inventory(FakeBridge()))
    assert {str(resource.uri) for resource in resources} == EXPECTED_RESOURCES


def test_prompt_inventory_matches_reference():
    """The know-how is also published as prompts, since no client consults a
    resource spontaneously."""
    async def scenario():
        async with fastmcp.Client(build_server(FakeBridge())) as client:
            return await client.list_prompts()

    prompts = run(scenario())
    assert {prompt.name for prompt in prompts} == EXPECTED_PROMPTS
    assert all(prompt.description for prompt in prompts)


def test_fmu_ports_resource_template_is_exposed():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            templates = await client.list_resource_templates()
            return templates, await client.read_resource("fmu://a.fmu/ports")

    templates, content = run(scenario())
    assert {t.uri_template for t in templates} == EXPECTED_RESOURCE_TEMPLATES
    assert json.loads(content[0].text)["fmu"] == "a.fmu"


# --------------------------------------------------------------------------- #
#                                   schemas                                   #
# --------------------------------------------------------------------------- #
def test_optional_parameters_are_published_without_null():
    """`anyOf: [X, null]` and `default: null` would cost tokens at every request."""
    async def scenario():
        async with fastmcp.Client(build_server(FakeBridge())) as client:
            return await client.list_tools()

    schemas = json.dumps([tool.input_schema for tool in run(scenario())])
    assert '{"type": "null"}' not in schemas and '"default": null' not in schemas


def test_null_is_still_accepted_for_an_optional_parameter():
    """Only the published schema is compact: models that send `null` for an unset option keep working."""
    bridge = FakeBridge()

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            await client.call_tool("set_container_options", {"options": {"mt": None, "auto_link": False}})
            return await client.call_tool("list_fmu_ports", {"fmu": "a.fmu", "causality": None})

    bridge.add_fmu("a.fmu")
    assert run(scenario()).structured_content["total"] == 4


def test_compact_schema():
    schema = {"properties": {"a": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None,
                                   "description": "d"},
                             "b": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                             "c": {"type": "integer", "default": 2}}}
    assert compact_schema(schema) == {"properties": {"a": {"type": "string", "description": "d"},
                                              "b": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                                              "c": {"type": "integer", "default": 2}}}
    assert schema["properties"]["a"]["default"] is None      # the original is left untouched


# --------------------------------------------------------------------------- #
#                               argument errors                               #
# --------------------------------------------------------------------------- #
def _call_error(tool, arguments, tmp_path=None) -> str:
    """Message of the ToolError raised for an invalid call (the bridge must not be reached)."""
    bridge = FakeBridge()

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.call_tool(tool, arguments)

    with pytest.raises(ToolError) as error:
        run(scenario())
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
    """Invalid arguments are reported in a short message the client can act upon (e.g. "Unknown container
    option(s) ... Allowed: [...]"), not as the raw Pydantic text."""
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
#                       error reporting and annotations                       #
# --------------------------------------------------------------------------- #
class BrokenBridge(FakeBridge):
    """Bridge whose internals blow up the way a real bug would."""

    def list_fmus(self):
        raise AttributeError("'NoneType' object has no attribute 'fmu_nodes'")


def test_domain_errors_keep_their_message():
    with pytest.raises(ToolError, match="is not in the assembly"):
        call_tool(FakeBridge(), "remove_fmu", {"name": "ghost.fmu"})


def test_internal_errors_are_not_leaked_verbatim(caplog):
    """An internal error (e.g. an ``AttributeError``) does not reach the client
    as "'NoneType' object has no attribute ...", which no model can act upon."""
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        with pytest.raises(ToolError) as excinfo:
            call_tool(BrokenBridge(), "list_fmus", {})

    message = str(excinfo.value)
    assert "NoneType" not in message
    assert "bug in the FMU Manipulation Toolbox" in message
    assert "AttributeError" in message
    # The details are kept server-side, with the traceback, for the maintainer.
    assert "Unexpected error in MCP tool 'list_fmus'" in caplog.text
    assert "fmu_nodes" in caplog.text


@pytest.mark.parametrize("tool", sorted(EXPECTED_TOOLS))
def test_every_tool_declares_its_behaviour(tool):
    tools, _ = run(inventory(FakeBridge()))
    annotations = next(t for t in tools if t.name == tool).annotations
    assert annotations is not None, tool
    assert annotations.read_only_hint is not None, tool


@pytest.mark.parametrize("tool", ["list_fmus", "list_fmu_ports", "get_assembly_json"])
def test_read_only_tools_are_flagged(tool):
    tools, _ = run(inventory(FakeBridge()))
    annotations = next(t for t in tools if t.name == tool).annotations
    assert annotations.read_only_hint is True
    assert annotations.idempotent_hint is True


@pytest.mark.parametrize("tool", ["remove_fmu", "save_as_json", "save_as_fmu"])
def test_destructive_tools_are_flagged(tool):
    tools, _ = run(inventory(FakeBridge()))
    annotations = next(t for t in tools if t.name == tool).annotations
    assert annotations.destructive_hint is True
    assert annotations.read_only_hint is False


@pytest.mark.parametrize("tool", ["expose_input", "expose_output", "set_start_value",
                                  "set_container_options", "add_link"])
def test_idempotent_writes_are_flagged(tool):
    tools, _ = run(inventory(FakeBridge()))
    annotations = next(t for t in tools if t.name == tool).annotations
    assert annotations.idempotent_hint is True
    assert annotations.read_only_hint is False
    assert annotations.destructive_hint is not True


def test_adding_an_fmu_is_not_idempotent():
    """A second `add_fmu` on a file adds another instance: a client must not retry it blindly."""
    tools, _ = run(inventory(FakeBridge()))
    annotations = next(t for t in tools if t.name == "add_fmu").annotations
    assert annotations.idempotent_hint is False
    assert annotations.read_only_hint is False
    assert annotations.destructive_hint is False


# --------------------------------------------------------------------------- #
#                             strict input typing                             #
# --------------------------------------------------------------------------- #
def test_container_options_advertise_their_keys():
    """The options are typed, not an opaque ``Dict[str, Any]``: the model knows
    which keys exist."""
    tools, _ = run(inventory(FakeBridge()))
    schema = input_schema(next(t for t in tools if t.name == "set_container_options"))
    options = resolve_ref(schema, schema["properties"]["options"])

    assert set(options["properties"]) == {
        "step_size", "mt", "profiling", "sequential", "auto_link", "auto_input",
        "auto_output", "auto_parameter", "auto_local", "ts_multiplier",
    }
    assert options["additionalProperties"] is False
    assert all(field.get("description") for field in options["properties"].values())


def test_container_options_only_forward_what_was_provided():
    bridge = FakeBridge()
    bridge.options = {"step_size": None, "mt": False, "auto_link": True}

    call_tool(bridge, "set_container_options", {"options": {"step_size": 0.01}})

    assert ("set_container_options", {"step_size": 0.01}) in bridge.calls
    assert bridge.options["mt"] is False  # untouched


@pytest.mark.parametrize("step_size", [0, -1])
def test_container_options_reject_a_non_positive_step_size(step_size):
    with pytest.raises(ToolError, match="step_size"):
        call_tool(FakeBridge(), "set_container_options", {"options": {"step_size": step_size}})


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
    call_tool(bridge, "set_start_value", {"fmu": "a.fmu", "port": "u", "value": value})
    assert ("set_start_value", "a.fmu", "u", expected) in bridge.calls


def test_every_tool_parameter_is_documented():
    """Every parameter carries a description."""
    tools, _ = run(inventory(FakeBridge()))
    undocumented = []
    for tool in tools:
        for name, field in (input_schema(tool).get("properties") or {}).items():
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
