"""`fmutool-agent`: the tools of the MCP server as a JSON command line.

The command line and the MCP server call the same `Toolbox`: these tests check
that they offer the same tools, with the same parameters, and that a scenario
gives the same results through both. The command line itself must run without
`fastmcp` and Pydantic, and keep the assembly in its state file between calls.
"""
import json
import shutil
import subprocess
import sys

import pytest

from fmu_manipulation_toolbox.assistant.headless import HeadlessAssemblyBridge
from fmu_manipulation_toolbox.assistant.tools import TOOLS
from fmu_manipulation_toolbox.cli.fmutool_agent import (
    ASSEMBLY_TOOLS,
    CHANGING_TOOLS,
    EXIT_TOOL_ERROR,
    EXIT_USAGE_ERROR,
    parameters,
    run,
)
from fmu_manipulation_toolbox.version import __version__ as version

pytestmark = [pytest.mark.unit]


@pytest.fixture
def fmus(data_dir, tmp_path):
    """Two FMI 3 FMUs to assemble, copied where the outputs are written."""
    for name in ("bb_position.fmu", "bb_velocity.fmu"):
        shutil.copy(data_dir / "fmi3" / "bouncing_ball" / name, tmp_path / name)
    return tmp_path


def agent(capsys, tool, arguments=None, state=None, *extra):
    """Run `fmutool-agent`; returns its exit code and the JSON it printed."""
    argv = [tool, *extra]
    if arguments is not None:
        argv += ["--args", json.dumps(arguments)]
    if state is not None:
        argv += ["--state", str(state)]
    code = run(argv)
    return code, json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------- #
#                            same tools as the server                         #
# --------------------------------------------------------------------------- #
def test_the_tool_lists_agree():
    assert set(ASSEMBLY_TOOLS) <= set(TOOLS)
    assert set(CHANGING_TOOLS) <= set(ASSEMBLY_TOOLS)


def test_the_tools_and_their_parameters_are_those_of_the_server():
    pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")
    from _helpers.assistant_bridge import FakeBridge, input_schema, inventory
    from _helpers.assistant_bridge import run as run_async

    tools, _ = run_async(inventory(FakeBridge()))
    published = {tool.name: input_schema(tool) for tool in tools}

    assert set(published) == set(TOOLS)
    for tool in TOOLS:
        schema = published[tool]
        assert [parameter.name for parameter in parameters(tool)] == list(schema.get("properties", {})), tool
        required = {parameter.name for parameter in parameters(tool) if parameter.default is parameter.empty}
        assert required == set(schema.get("required", [])), tool
        for parameter in parameters(tool):
            if parameter.default is not parameter.empty and parameter.default is not None:
                assert schema["properties"][parameter.name].get("default") == parameter.default, (tool, parameter)


def test_the_tools_are_listed_with_their_parameters(capsys):
    code, listing = agent(capsys, "list-tools")

    assert code == 0
    assert listing["version"] == version
    by_name = {tool["name"]: tool for tool in listing["tools"]}
    assert list(by_name) == list(TOOLS)
    assert by_name["add_fmu"]["needs_state"] is True
    assert by_name["describe_port"]["needs_state"] is False
    assert by_name["list_fmu_ports"]["parameters"][1] == {"name": "causality", "type": "list[string]",
                                                          "default": None}
    assert by_name["save_as_fmu"]["parameters"][1] == {"name": "fmi_version", "type": "2 | 3", "default": 2}


# --------------------------------------------------------------------------- #
#                         same results as the server                          #
# --------------------------------------------------------------------------- #
def _scenario(directory):
    """Calls of an assembly session, then of the single-FMU tools."""
    position, velocity = str(directory / "bb_position.fmu"), str(directory / "bb_velocity.fmu")
    return [
        ("inspect_fmu_file", {"path": position, "causality": ["input"]}),
        ("add_fmu", {"path": position}),
        ("add_fmu", {"path": velocity}),
        ("list_fmus", {}),
        ("list_fmu_ports", {"fmu": "bb_velocity.fmu", "type": ["Real"], "variability": ["continuous"]}),
        ("add_links", {"links": [{"from_fmu": "bb_velocity.fmu", "from_port": "velocity",
                                  "to_fmu": "bb_position.fmu", "to_port": "velocity"},
                                 {"from_fmu": "bb_position.fmu", "from_port": "nothing",
                                  "to_fmu": "bb_velocity.fmu", "to_port": "reset"}]}),
        ("set_start_value", {"fmu": "bb_velocity.fmu", "port": "reset", "value": False}),
        ("set_container_options", {"options": {"mt": True}}),
        ("expose_output", {"fmu": "bb_position.fmu", "port": "position1"}),
        ("get_assembly_json", {}),
        ("analyze_assembly", {"mode": "summary"}),
        ("analyze_assembly", {"mode": "lint"}),
        ("unset_start_value", {"fmu": "bb_velocity.fmu", "port": "reset"}),
        ("remove_link", {"from_fmu": "bb_velocity.fmu", "from_port": "velocity",
                         "to_fmu": "bb_position.fmu", "to_port": "velocity"}),
        ("save_assembly", {"path": str(directory / "assembly.json"), "overwrite": True}),
        ("save_assembly", {"path": str(directory / "assembly.ssp"), "overwrite": True}),
        ("inspect_ssp", {"path": str(directory / "assembly.ssp")}),
        ("inspect_ssp", {"path": str(directory / "assembly.ssp"), "section": "output"}),
        ("import_assembly", {"path": str(directory / "assembly.json"), "replace": True}),
        ("list_fmus", {}),
        ("remove_fmu", {"name": "bb_velocity.fmu"}),
        ("summarize_fmu", {"path": position}),
        ("check_fmu", {"path": position}),
        ("describe_port", {"fmu": "bb_position.fmu", "port": "position1"}),
        ("dump_ports_csv", {"fmu": position, "path": str(directory / "ports.csv"), "overwrite": True}),
        ("rename_ports", {"fmu": position, "output": str(directory / "renamed.fmu"),
                          "mapping": {"position1": "x", "missing": "y"}, "overwrite": True}),
        ("apply_operation", {"fmu": position, "output": str(directory / "filtered.fmu"),
                             "operation": "remove_regexp", "argument": "^is_", "type": ["Boolean"],
                             "overwrite": True}),
    ]


def _through_the_server(directory):
    pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")
    import fastmcp

    from _helpers.assistant_bridge import run as run_async
    from fmu_manipulation_toolbox.assistant import PathPolicy, build_server

    async def scenario():
        results = []
        server = build_server(HeadlessAssemblyBridge(), policy=PathPolicy(directory))
        async with fastmcp.Client(server) as client:
            for tool, arguments in _scenario(directory):
                result = await client.call_tool(tool, arguments)
                results.append(result.structured_content)
        return results

    return run_async(scenario())


def test_a_session_gives_the_same_results_through_both(fmus, capsys):
    expected = _through_the_server(fmus)
    state = fmus / "state.json"

    for (tool, arguments), wanted in zip(_scenario(fmus), expected):
        # `describe_port` takes the state when it is given: the port of an FMU of the assembly, by its name.
        with_state = tool in ASSEMBLY_TOOLS or tool == "describe_port"
        code, result = agent(capsys, tool, arguments, state if with_state else None, "--root", str(fmus))
        assert code == 0, (tool, result)
        assert _without_temporary_directory(result) == _without_temporary_directory(wanted), tool


def _without_temporary_directory(result):
    """The report of `summarize_fmu` names the directory the FMU was extracted to: a new one at each call."""
    if "report" not in result:
        return result
    lines = [line for line in result["report"].splitlines() if not line.startswith("| temporary directory =")]
    return {**result, "report": lines}


# --------------------------------------------------------------------------- #
#                                  the state                                  #
# --------------------------------------------------------------------------- #
def test_the_state_rebuilds_the_same_bridge(fmus):
    bridge = HeadlessAssemblyBridge("vehicle.fmu")
    bridge.add_fmu(str(fmus / "bb_position.fmu"))
    bridge.add_fmu(str(fmus / "bb_position.fmu"))  # a second instance
    bridge.add_fmu(str(fmus / "bb_velocity.fmu"))
    bridge.add_link("bb_velocity.fmu", "velocity", "bb_position-1.fmu", "velocity")
    bridge.expose_input("bb_velocity.fmu", "reset")
    bridge.set_start_value("bb_position.fmu", "velocity", "1.5")
    bridge.set_container_options({"step_size": 0.01})

    rebuilt = HeadlessAssemblyBridge.from_state(json.loads(json.dumps(bridge.state())))

    assert rebuilt.state() == bridge.state()
    assert rebuilt.get_assembly_json() == bridge.get_assembly_json()


def test_a_file_that_is_not_a_state_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Not an assembly state"):
        HeadlessAssemblyBridge.from_state({"name": "x"})


def test_the_assembly_is_kept_between_calls(fmus, capsys):
    state = fmus / "state.json"

    agent(capsys, "add_fmu", {"path": str(fmus / "bb_position.fmu")}, state)
    agent(capsys, "set_container_options", {"options": {"mt": True}}, state)
    code, listed = agent(capsys, "list_fmus", {}, state)

    assert code == 0
    assert listed == {"result": ["bb_position.fmu"]}
    assert json.loads(state.read_text())["options"]["mt"] is True


def _description(fmus, **content):
    path = fmus / "description.json"
    path.write_text(json.dumps({"name": "pair.fmu", "fmu": ["bb_position.fmu", "bb_velocity.fmu"], **content}))
    return str(path)


def test_an_imported_assembly_is_found_by_the_next_call(fmus, capsys):
    state = fmus / "state.json"

    code, imported = agent(capsys, "import_assembly", {"path": _description(fmus, output=[
        ["bb_position.fmu", "position1", "height"]])}, state)
    assert code == 0, imported
    assert imported["file"] == "description.json"

    assert agent(capsys, "list_fmus", {}, state) == (0, {"result": ["bb_position.fmu", "bb_velocity.fmu"]})
    code, written = agent(capsys, "save_assembly", {"path": str(fmus / "written.ssp")}, state)
    assert code == 0, written
    code, inspected = agent(capsys, "inspect_ssp", {"path": str(fmus / "written.ssp"), "section": "output"})
    assert code == 0, inspected
    assert inspected["readable"] is True
    assert ["bb_position.fmu", "position1", "height"] in inspected["entries"]


def test_an_import_refused_leaves_the_state_as_it_was(fmus, capsys):
    state = fmus / "state.json"
    agent(capsys, "add_fmu", {"path": str(fmus / "bb_position.fmu")}, state)
    before = state.read_text()

    code, result = agent(capsys, "import_assembly", {"path": _description(fmus)}, state)
    assert code == EXIT_TOOL_ERROR
    assert "replace=True" in result["error"]
    assert state.read_text() == before

    nested = _description(fmus, container=[{"name": "sub.fmu", "fmu": ["bb_velocity.fmu"]}])
    code, result = agent(capsys, "import_assembly", {"path": nested, "replace": True}, state)
    assert code == EXIT_TOOL_ERROR
    assert "sub-containers" in result["error"]
    assert state.read_text() == before


def test_inspecting_an_ssp_file_needs_no_state(fmus, capsys):
    (fmus / "broken.ssp").write_text("not an archive")

    code, result = agent(capsys, "inspect_ssp", {"path": str(fmus / "broken.ssp")})

    assert code == 0
    assert result["readable"] is False


def test_the_ssp_version_is_checked(fmus, capsys):
    state = fmus / "state.json"
    agent(capsys, "add_fmu", {"path": str(fmus / "bb_position.fmu")}, state)

    code, result = agent(capsys, "save_assembly", {"path": str(fmus / "x.ssp"), "ssp_version": "3.0"}, state)

    assert code == EXIT_USAGE_ERROR
    assert "ssp_version" in result["error"]


def test_a_failed_change_leaves_the_state_as_it_was(fmus, capsys):
    state = fmus / "state.json"
    agent(capsys, "add_fmu", {"path": str(fmus / "bb_position.fmu")}, state)
    before = state.read_text()

    code, result = agent(capsys, "remove_fmu", {"name": "nope.fmu"}, state)

    assert code == EXIT_TOOL_ERROR
    assert "not in the assembly" in result["error"]
    assert state.read_text() == before


def test_reading_tools_do_not_write_the_state(fmus, capsys):
    state = fmus / "state.json"

    agent(capsys, "list_fmus", {}, state)

    assert not state.exists()


# --------------------------------------------------------------------------- #
#                                   errors                                    #
# --------------------------------------------------------------------------- #
def test_an_assembly_tool_needs_a_state(fmus, capsys):
    code, result = agent(capsys, "add_fmu", {"path": str(fmus / "bb_position.fmu")})

    assert code == EXIT_USAGE_ERROR
    assert "--state" in result["error"]


@pytest.mark.parametrize("tool, arguments, message", [
    ("nothing", {}, "Unknown tool 'nothing'"),
    ("describe_port", {"fmu": "a.fmu"}, "missing required argument 'port'"),
    ("describe_port", {"fmu": "a.fmu", "port": "p", "prot": 1}, "unknown argument 'prot'"),
    ("inspect_fmu_file", {"path": "a.fmu", "causality": "input"}, "'causality' expects list[string]"),
    ("save_as_fmu", {"path": "a.fmu", "fmi_version": 4}, "'fmi_version' expects 2 | 3"),
    ("check_fmu", ["a.fmu"], "must be a JSON object"),
])
def test_wrong_arguments_are_reported(capsys, tmp_path, tool, arguments, message):
    code, result = agent(capsys, tool, arguments, tmp_path / "state.json")

    assert code == EXIT_USAGE_ERROR
    assert message in result["error"]


def test_invalid_json_is_reported(capsys):
    code = run(["check_fmu", "--args", "{path:"])

    assert code == EXIT_USAGE_ERROR
    assert "not valid JSON" in json.loads(capsys.readouterr().out)["error"]


def test_a_tool_error_is_reported_on_stdout(capsys, tmp_path):
    code, result = agent(capsys, "check_fmu", {"path": str(tmp_path / "missing.fmu")})

    assert code == EXIT_TOOL_ERROR
    assert "missing.fmu" in result["error"]


def test_the_arguments_can_come_from_stdin(fmus, capsys, monkeypatch):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"path": str(fmus / "bb_position.fmu")})))

    code = run(["summarize_fmu", "--args", "-"])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["fmu"] == "bb_position.fmu"


# --------------------------------------------------------------------------- #
#                          base installation only                             #
# --------------------------------------------------------------------------- #
def test_the_command_line_needs_neither_fastmcp_nor_pydantic(fmus):
    """Run in a fresh interpreter where importing either of them fails."""
    script = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('fastmcp', 'pydantic', 'pydantic_core', 'mcp'):\n"
        "            raise ImportError(f'blocked: {name}')\n"
        "sys.meta_path.insert(0, Block())\n"
        "from fmu_manipulation_toolbox.cli.fmutool_agent import run\n"
        f"sys.exit(run(['describe_port', '--args', '{{\"fmu\": \"{(fmus / 'bb_position.fmu').as_posix()}\", "
        "\"port\": \"position1\"}']))\n"
    )
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["name"] == "position1"
