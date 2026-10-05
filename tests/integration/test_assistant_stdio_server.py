"""Integration test: the standalone ``fmutool-mcp`` server over stdio.

Audit reference B2 — the assistant used to require a running GUI, which ruled
out every MCP client that *launches* its server (Claude Desktop, Cline, a
``mcp.json`` with a ``command``). These tests spawn the real console script as
a subprocess and talk to it the way such a client would.
"""
import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

pytestmark = [pytest.mark.integration]

fastmcp = pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")

from fastmcp.client.transports import StdioTransport  # noqa: E402

#: Repository root, so the subprocess can import the package from the checkout.
REPO_ROOT = Path(__file__).resolve().parents[2]

MODULE = "fmu_manipulation_toolbox.cli.fmutool_mcp"


def _run(coro):
    return asyncio.run(coro)


def _client(*extra_args, root: Optional[Path] = None):
    """An MCP client bound to a freshly spawned stdio server."""
    args = ["-m", MODULE, "--transport", "stdio", *extra_args]
    if root is not None:
        args += ["--root", str(root)]
    return fastmcp.Client(StdioTransport(command=sys.executable, args=args,
                                         env={"PYTHONPATH": str(REPO_ROOT)}))


@pytest.fixture
def ball(data_dir):
    return data_dir / "containers" / "bouncing_ball"


def test_the_server_starts_without_any_gui():
    """No display, no Qt, no running GUI: just a process speaking stdio."""
    async def scenario():
        async with _client() as client:
            return await client.list_tools(), await client.list_prompts()

    tools, prompts = _run(scenario())
    assert {tool.name for tool in tools} >= {"add_fmu", "add_link", "save_as_fmu"}
    assert {prompt.name for prompt in prompts} == {"build_container",
                                                   "diagnose_assembly", "inspect_fmu"}


def test_it_assembles_fmus_over_stdio(ball, tmp_path):
    destination = tmp_path / "assembly.json"

    async def scenario():
        async with _client() as client:
            await client.call_tool("add_fmu", {"path": str(ball / "bb_position.fmu")})
            await client.call_tool("add_fmu", {"path": str(ball / "bb_velocity.fmu")})
            await client.call_tool("add_link", {"from_fmu": "bb_velocity.fmu",
                                                "from_port": "velocity",
                                                "to_fmu": "bb_position.fmu",
                                                "to_port": "velocity"})
            return (await client.call_tool("save_as_json",
                                           {"path": str(destination)})).data

    assert _run(scenario()) == str(destination.resolve())
    assert destination.is_file()


def test_errors_stay_actionable_over_stdio(ball):
    async def scenario():
        async with _client() as client:
            return await client.call_tool("list_fmu_ports", {"fmu": "ghost.fmu"})

    with pytest.raises(Exception, match="not in the assembly"):
        _run(scenario())


def test_the_root_option_confines_the_assistant(ball, tmp_path):
    """``--root`` is the knob that makes the standalone server safe to hand to
    an agent: it cannot read or write outside the directory."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    async def scenario():
        async with _client(root=allowed) as client:
            return await client.call_tool("add_fmu",
                                          {"path": str(ball / "bb_position.fmu")})

    with pytest.raises(Exception, match="outside the allowed directory"):
        _run(scenario())


def test_logs_never_pollute_the_protocol_stream(ball):
    """stdout *is* the JSON-RPC channel: a single log line written there would
    break the session. Everything the toolbox logs must go to stderr."""
    async def scenario():
        async with _client() as client:
            # `add_fmu` logs "[AI] Added FMU ..." — the regression bait.
            await client.call_tool("add_fmu", {"path": str(ball / "bb_velocity.fmu")})
            return (await client.call_tool("list_fmus", {})).data

    assert _run(scenario()) == ["bb_velocity.fmu"]


def test_the_module_reports_a_bad_root_instead_of_crashing(tmp_path):
    """A misconfigured client must get a readable message, not a traceback."""
    completed = subprocess.run(
        [sys.executable, "-m", MODULE, "--root", str(tmp_path / "missing")],
        capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )

    assert completed.returncode == 1
    assert "not a directory" in completed.stderr
    assert completed.stdout == ""


def test_the_help_is_available(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", MODULE, "--help"],
        capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )

    assert completed.returncode == 0
    assert "stdio" in completed.stdout





