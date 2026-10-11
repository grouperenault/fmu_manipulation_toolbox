"""Resources, prompts and runtime behaviour of the MCP server.

These tests drive the server through an in-memory ``fastmcp.Client`` against a
**fake bridge**: resources and prompts served, port and timeout resolution, and
progress reporting of the long tools.
"""
import asyncio
import importlib
import json
import threading
import time

import pytest

pytestmark = [pytest.mark.unit]

fastmcp = pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")

from fmu_manipulation_toolbox.assistant import (  # noqa: E402
    DEFAULT_PORT, DEFAULT_TIMEOUT, PORT_ENV_VAR, TIMEOUT_ENV_VAR, build_server, resolve_port, resolve_timeout,
)

from _helpers.assistant_bridge import FakeBridge, input_schema, inventory, read_resource, resolve_ref, run  # noqa: E402


# --------------------------------------------------------------------------- #
#                                  resources                                  #
# --------------------------------------------------------------------------- #
def test_usage_guide_resource_is_served():
    async def scenario():
        async with fastmcp.Client(build_server(FakeBridge())) as client:
            return await client.read_resource("guide://usage")

    assert "FMU Container Builder" in run(scenario())[0].text


def test_current_assembly_resource_serves_json():
    bridge = FakeBridge()
    bridge.add_fmu("a.fmu")

    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.read_resource("assembly://current")

    assert json.loads(run(scenario())[0].text)["fmu"] == ["a.fmu"]


# --------------------------------------------------------------------------- #
#              portable know-how: prompts and reference resources             #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prompt, arguments, expected", [
    ("build_container", {"fmus": "a.fmu, b.fmu"}, "a.fmu, b.fmu"),
    ("build_container", {}, "list_fmus"),
    ("diagnose_assembly", {"symptom": "step too large"}, "step too large"),
    ("inspect_fmu", {"fmu": "controller.fmu"}, "controller.fmu"),
    ("inspect_fmu", {}, "inspect_fmu_file"),
    ("diagnose_assembly", {}, "analyze_assembly(mode='lint')"),
    ("analyze_assembly", {"focus": "thermal loop"}, "thermal loop"),
    ("analyze_assembly", {}, "list_fmus"),
])
def test_prompts_render_with_and_without_arguments(prompt, arguments, expected):
    async def scenario():
        async with fastmcp.Client(build_server(FakeBridge())) as client:
            return await client.get_prompt(prompt, arguments)

    rendered = run(scenario()).messages[0].content.text
    assert expected in rendered


#: Prefixes of the tool names: a back-quoted word starting with one of them, in the know-how, designates a tool.
TOOL_VERBS = ("list_", "add_", "remove_", "expose_", "set_", "unset_", "get_", "save_", "inspect_", "summarize_",
              "check_", "dump_", "rename_", "apply_", "analyze_")


def test_the_know_how_only_names_existing_tools():
    """A prompt or the guide naming a tool that does not exist (renamed, removed) would send the model after it."""
    import re
    from fmu_manipulation_toolbox.assistant import knowledge

    tools, _ = run(inventory(FakeBridge()))
    names = {tool.name for tool in tools}
    texts = [knowledge.USAGE_GUIDE, knowledge.build_container_prompt(), knowledge.diagnose_assembly_prompt(),
             knowledge.analyze_assembly_prompt(), knowledge.inspect_fmu_prompt()]
    for text in texts:
        called = set(re.findall(r"`([a-z][a-z0-9_]*)\(", text))
        mentioned = {word for word in re.findall(r"`([a-z][a-z0-9_]*)[(`]", text) if word.startswith(TOOL_VERBS)}
        assert called | mentioned <= names, (called | mentioned) - names


def test_reference_resources_are_served():
    """The FMI reference material is served as resources."""
    bridge = FakeBridge()
    assert "Causality" in read_resource(bridge, "fmi://conventions")
    assert "step_size" in read_resource(bridge, "container://options")


def test_the_options_reference_is_derived_from_the_schema():
    """The documented options cannot drift away from the accepted ones."""
    tools, _ = run(inventory(FakeBridge()))
    schema = input_schema(next(t for t in tools if t.name == "set_container_options"))
    accepted = set(resolve_ref(schema, schema["properties"]["options"])["properties"])

    reference = read_resource(FakeBridge(), "container://options")

    assert all(f"`{option}`" in reference for option in accepted)




def test_the_usage_guide_has_a_single_source():
    """The guide must not be duplicated between the server and the knowledge
    module, otherwise the two drift apart."""
    from fmu_manipulation_toolbox.assistant import knowledge, server

    assert server.USAGE_GUIDE is knowledge.USAGE_GUIDE


# --------------------------------------------------------------------------- #
#                               port resolution                               #
# --------------------------------------------------------------------------- #
def test_port_defaults_when_the_variable_is_unset(monkeypatch):
    monkeypatch.delenv(PORT_ENV_VAR, raising=False)
    assert resolve_port() == DEFAULT_PORT


def test_port_honours_the_environment(monkeypatch):
    monkeypatch.setenv(PORT_ENV_VAR, "9001")
    assert resolve_port() == 9001


@pytest.mark.parametrize("value", ["", "abc", "80.5", "0", "-1", "65536"])
def test_invalid_port_is_reported_at_startup_not_at_import(monkeypatch, value):
    """The port is parsed at startup, not at import time: a malformed value
    must not break an unrelated ``import`` of the package."""
    monkeypatch.setenv(PORT_ENV_VAR, value)

    importlib.reload(importlib.import_module("fmu_manipulation_toolbox.assistant"))

    with pytest.raises(ValueError, match=PORT_ENV_VAR):
        resolve_port()


# --------------------------------------------------------------------------- #
#                             configurable timeout                            #
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
#                              progress reporting                             #
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
    """The build reports its progress, so that the client can tell a slow build
    from a hung one."""
    bridge = FakeBridge()
    updates = []

    async def scenario():
        async def on_progress(progress, total, message):
            updates.append((progress, total, message))

        async with fastmcp.Client(build_server(bridge),
                                  progress_handler=on_progress) as client:
            return await client.call_tool("save_as_fmu", {"path": str(tmp_path / "out.fmu")})

    run(scenario())

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

    loop_thread = run(scenario())
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

    assert run(scenario()).data == []
