"""Integration test: the MCP server driving the real Container Builder GUI.

The unit tests in ``tests/unit/test_assistant_server.py`` pin the MCP contract
against a fake bridge. This module checks the other half: that the Qt bridge
really applies what the tools ask for, on actual FMUs, up to a built container.

Threading note
--------------
Three threads are involved, which is exactly why the bridge marshals its work:
the Qt event loop owns the main thread, the MCP client runs in a worker thread,
and FastMCP dispatches synchronous tools to its own AnyIO worker threads. The
main thread therefore pumps Qt events (rather than calling ``app.exec()``)
until the client thread is done, so the bridge's queued signals get processed.
"""
import asyncio
import threading
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.integration]

fastmcp = pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")
pytest.importorskip("PySide6", reason="the GUI extra is not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from fmu_manipulation_toolbox.assistant import build_server  # noqa: E402

#: Give the container build room to finish on a slow runner.
CLIENT_TIMEOUT = 120.0


def _drive(scenario, timeout=CLIENT_TIMEOUT):
    """Run ``scenario()`` in a worker thread while pumping the Qt event loop.

    Returns the scenario's result, or re-raises whatever it raised.
    """
    outcome = {}

    def worker():
        try:
            outcome["value"] = asyncio.run(scenario())
        except BaseException as exc:  # noqa: BLE001 - forwarded to the test
            outcome["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    deadline = time.monotonic() + timeout
    while thread.is_alive():
        QApplication.processEvents()
        time.sleep(0.01)
        if time.monotonic() > deadline:
            raise TimeoutError("The MCP client did not finish in time.")

    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


@pytest.fixture
def mcp_server(qapp, data_dir):
    """An MCP server bound to a live Container Builder window."""
    from fmu_manipulation_toolbox.gui.fmucontainer.__main__ import MainWindow
    from fmu_manipulation_toolbox.gui.fmucontainer.mcp_bridge import (
        MainThreadInvoker, QtAssemblyBridge,
    )

    window = MainWindow()
    bridge = QtAssemblyBridge(window, MainThreadInvoker())
    try:
        yield build_server(bridge), window
    finally:
        # The tools mark the window dirty; `UnsavedChangesWindowMixin.closeEvent`
        # would then pop a modal "save your changes?" dialog, which never
        # returns under the offscreen platform and hangs the test session.
        window._dirty = False
        window.close()
        # Delete the widgets now, while logging still works: letting the
        # garbage collector do it at interpreter shutdown makes Qt emit
        # selection signals on an already-deleted scene.
        window.deleteLater()
        QApplication.processEvents()


@pytest.mark.needs_container
def test_build_a_container_through_mcp(mcp_server, data_dir, tmp_path):
    """Audit scenario S2, end to end: add two FMUs, link them, build the FMU."""
    import zipfile

    server, window = mcp_server
    source = data_dir / "containers" / "bouncing_ball"
    destination = tmp_path / "container.fmu"

    async def scenario():
        async with fastmcp.Client(server) as client:
            summary = (await client.call_tool(
                "add_fmu", {"path": str(source / "bb_position.fmu")})).data
            assert summary.fmu == "bb_position.fmu"
            assert summary.counts["output"] >= 1
            await client.call_tool("add_fmu", {"path": str(source / "bb_velocity.fmu")})

            listed = (await client.call_tool("list_fmus", {})).data
            assert sorted(listed) == ["bb_position.fmu", "bb_velocity.fmu"]

            ports = (await client.call_tool("list_fmu_ports",
                                            {"fmu": "bb_velocity.fmu",
                                             "causality": ["output"]})).data
            assert ports.fmi_version == 2
            assert ports.kinds == ["CoSimulation"]
            assert [port.name for port in ports.ports] == ["velocity"]

            await client.call_tool("add_link", {"from_fmu": "bb_velocity.fmu",
                                                "from_port": "velocity",
                                                "to_fmu": "bb_position.fmu",
                                                "to_port": "velocity"})
            await client.call_tool("set_container_options", {"options": {"step_size": 0.01}})

            assembly = (await client.call_tool("get_assembly_json", {})).data
            assert assembly["step_size"] == 0.01
            # NOTE: the assembly description references FMUs by *path*, while
            # the tools designate them by *name*. Compare on base names.
            assert sorted(Path(fmu).name for fmu in assembly["fmu"]) == [
                "bb_position.fmu", "bb_velocity.fmu"]
            (link,) = assembly["link"]
            assert [Path(link[0]).name, link[1], Path(link[2]).name, link[3]] == [
                "bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"]

            return (await client.call_tool("save_as_fmu", {"path": str(destination)})).data

    assert _drive(scenario) == str(destination.resolve())

    # The produced archive must be a real FMI-2 container, not an empty shell:
    # `fmi_version=7` used to yield a 0-byte modelDescription.xml (audit B6).
    with zipfile.ZipFile(destination) as archive:
        descriptor = archive.read("modelDescription.xml").decode("utf-8", "replace")
    assert 'fmiVersion="2.0"' in descriptor


def test_inspecting_a_file_reads_the_real_descriptor(mcp_server, data_dir):
    """`inspect_fmu_file` reports the real ports without touching the canvas."""
    server, _ = mcp_server
    candidate = data_dir / "containers" / "bouncing_ball" / "bb_velocity.fmu"

    async def scenario():
        async with fastmcp.Client(server) as client:
            ports = (await client.call_tool("inspect_fmu_file",
                                            {"path": str(candidate)})).data
            listed = (await client.call_tool("list_fmus", {})).data
            return ports, listed

    ports, listed = _drive(scenario)
    assert listed == []
    assert ports.fmu == "bb_velocity.fmu"
    # Parameters and locals are reported too, each with its causality.
    assert set(ports.counts) >= {"output"}
    assert ports.total == sum(ports.counts.values())


def test_unknown_port_is_rejected_by_the_live_bridge(mcp_server, data_dir):
    """The Qt bridge validates against the real FMU, not a cached description."""
    server, _ = mcp_server
    source = data_dir / "containers" / "bouncing_ball"

    async def scenario():
        async with fastmcp.Client(server) as client:
            await client.call_tool("add_fmu", {"path": str(source / "bb_position.fmu")})
            await client.call_tool("add_link", {"from_fmu": "bb_position.fmu",
                                                "from_port": "does_not_exist",
                                                "to_fmu": "bb_position.fmu",
                                                "to_port": "velocity"})

    with pytest.raises(Exception, match="is not an output"):
        _drive(scenario)


def test_assembly_stays_empty_without_any_fmu(mcp_server):
    server, _ = mcp_server

    async def scenario():
        async with fastmcp.Client(server) as client:
            return (await client.call_tool("list_fmus", {})).data

    assert _drive(scenario) == []


def test_unlinking_cleans_the_scene(mcp_server, data_dir):
    """`remove_link` must leave no orphan wire behind, otherwise the canvas
    keeps showing a connection the assembly no longer has."""
    server, window = mcp_server
    source = data_dir / "containers" / "bouncing_ball"

    async def scenario():
        async with fastmcp.Client(server) as client:
            await client.call_tool("add_fmu", {"path": str(source / "bb_position.fmu")})
            await client.call_tool("add_fmu", {"path": str(source / "bb_velocity.fmu")})
            await client.call_tool("add_link", {"from_fmu": "bb_velocity.fmu",
                                                "from_port": "velocity",
                                                "to_fmu": "bb_position.fmu",
                                                "to_port": "velocity"})
            wired = len(window._graph.scene.wires())
            await client.call_tool("remove_link", {"from_fmu": "bb_velocity.fmu",
                                                   "from_port": "velocity",
                                                   "to_fmu": "bb_position.fmu",
                                                   "to_port": "velocity"})
            assembly = (await client.call_tool("get_assembly_json", {})).data
            return wired, len(window._graph.scene.wires()), assembly

    wired, remaining, assembly = _drive(scenario)
    assert wired == 1
    assert remaining == 0
    assert "link" not in assembly


def test_unsetting_a_start_value_restores_the_declared_one(mcp_server, data_dir):
    server, _ = mcp_server
    source = data_dir / "containers" / "bouncing_ball"

    async def scenario():
        async with fastmcp.Client(server) as client:
            await client.call_tool("add_fmu", {"path": str(source / "bb_velocity.fmu")})
            await client.call_tool("set_start_value", {"fmu": "bb_velocity.fmu",
                                                       "port": "reset", "value": True})
            after_set = (await client.call_tool(
                "list_fmu_ports", {"fmu": "bb_velocity.fmu",
                                   "name_pattern": "^reset$"})).data
            await client.call_tool("unset_start_value", {"fmu": "bb_velocity.fmu",
                                                         "port": "reset"})
            after_unset = (await client.call_tool(
                "list_fmu_ports", {"fmu": "bb_velocity.fmu",
                                   "name_pattern": "^reset$"})).data
            return after_set.ports[0].start, after_unset.ports[0].start

    after_set, after_unset = _drive(scenario)
    assert after_set == "true"
    assert after_unset != "true"


# --------------------------------------------------------------------------- #
#               main-thread marshalling and timeout (audit I5)                  #
# --------------------------------------------------------------------------- #
def _invoker(**kwargs):
    from fmu_manipulation_toolbox.gui.fmucontainer.mcp_bridge import MainThreadInvoker

    return MainThreadInvoker(**kwargs)


def test_the_timeout_is_configurable(qapp, monkeypatch):
    """Regression test for I5: the budget used to be hard-coded at 60 s, which
    is both too short for a big assembly and too long for an interactive
    session."""
    from fmu_manipulation_toolbox.assistant import DEFAULT_TIMEOUT, TIMEOUT_ENV_VAR

    monkeypatch.delenv(TIMEOUT_ENV_VAR, raising=False)
    assert _invoker().timeout == DEFAULT_TIMEOUT

    monkeypatch.setenv(TIMEOUT_ENV_VAR, "3.5")
    assert _invoker().timeout == 3.5

    # An explicit value still wins over the environment.
    assert _invoker(timeout=1.0).timeout == 1.0


def test_a_stalled_main_thread_is_reported_actionably(qapp):
    """Nobody pumps the Qt event loop here, so the queued call never runs:
    the caller must be told what to do rather than just "timed out"."""
    invoker = _invoker(timeout=0.05)
    outcome = {}

    def worker():
        try:
            invoker.call(lambda: "never reached")
        except BaseException as exc:  # noqa: BLE001 - inspected below
            outcome["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=5)

    assert isinstance(outcome.get("error"), TimeoutError)
    message = str(outcome["error"])
    assert "Container Builder" in message
    assert "FMUCONTAINER_MCP_TIMEOUT" in message


def test_building_gets_a_longer_budget_than_editing(qapp):
    """A build rewrites every embedded FMU: it cannot share the deadline of an
    instantaneous canvas edit."""
    from fmu_manipulation_toolbox.assistant import BUILD_TIMEOUT_FACTOR
    from fmu_manipulation_toolbox.gui.fmucontainer.mcp_bridge import QtAssemblyBridge

    bridge = QtAssemblyBridge(window=None, invoker=_invoker(timeout=2.0))

    assert bridge._build_timeout == 2.0 * BUILD_TIMEOUT_FACTOR


