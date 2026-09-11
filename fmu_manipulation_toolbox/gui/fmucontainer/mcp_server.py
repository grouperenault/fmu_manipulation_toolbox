"""
FMU Container Builder – MCP (Model Context Protocol) server.

Exposes the running Container Builder GUI to an AI agent (e.g. GitHub Copilot
in *Agent* mode) over an HTTP/SSE transport bound to localhost. The agent can
introspect FMUs, add them to the assembly, wire ports together, expose
container inputs/outputs, set start values and finally build the container FMU.

Every action is applied on the live scene/tree (so the user sees it happen),
marked *dirty* (undoable / re-savable) and logged to the visible log panel.

Design
------
Qt owns the main-thread event loop. The MCP server (uvicorn + anyio) runs in a
dedicated ``QThread``. Because all GUI objects must only be touched from the
Qt main thread, every tool marshals its work onto the main thread through
:class:`MainThreadInvoker` (a queued signal + blocking wait), and returns the
result to the MCP worker thread.

The FastMCP 2 SDK (``fastmcp`` package) requires Python >= 3.10; the import is
therefore performed lazily so the rest of the GUI keeps working on Python 3.9.
The server uses the recommended Streamable HTTP transport (endpoint ``/mcp``).
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal

from .details import ContainerParameters
from .graph import NodeItem
from .tree.model import _NodeTreeModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .__main__ import MainWindow


logger = logging.getLogger("fmu_manipulation_toolbox")
tree_logger = logging.getLogger("fmu_manipulation_toolbox.gui.tree")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("FMUCONTAINER_MCP_PORT", "8765"))


class McpUnavailableError(RuntimeError):
    """Raised when the optional ``mcp`` dependency cannot be imported."""


# ---------------------------------------------------------------------------
# Main-thread marshaling
# ---------------------------------------------------------------------------


class MainThreadInvoker(QObject):
    """Runs arbitrary callables on the Qt main thread and returns their result.

    Must be instantiated on the Qt main thread. Worker threads call
    :meth:`call`, which posts the callable through a queued signal and blocks
    until the main thread has executed it.
    """

    _invoke = Signal(object)

    def __init__(self):
        super().__init__()
        # QueuedConnection guarantees `_run` executes in this object's thread
        # (the main thread), regardless of the emitting thread.
        self._invoke.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def _run(task: Callable[[], None]):
        task()

    def call(self, fn: Callable[[], Any], timeout: float = 60.0) -> Any:
        """Execute ``fn`` on the Qt main thread and return its result.

        Re-raises on the calling thread any exception raised by ``fn``.
        """
        outcome: Dict[str, Any] = {}
        done = threading.Event()

        def task():
            try:
                outcome["value"] = fn()
            except Exception as exc:  # noqa: BLE001 - forwarded to caller
                outcome["error"] = exc
            finally:
                done.set()

        self._invoke.emit(task)
        if not done.wait(timeout):
            raise TimeoutError("Timed out waiting for the GUI main thread.")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")


# ---------------------------------------------------------------------------
# GUI bridge – all methods run on the Qt main thread (via the invoker)
# ---------------------------------------------------------------------------


class GuiBridge:
    """Thin adapter mapping MCP tool calls onto Container Builder GUI actions.

    All public methods assume they run on the Qt main thread (the MCP tools
    wrap them with :meth:`MainThreadInvoker.call`).
    """

    def __init__(self, window: "MainWindow"):
        self._window = window

    # -- lookup helpers ----------------------------------------------------

    @property
    def _scene(self):
        return self._window._graph.scene

    def _node_by_name(self, name: str) -> Optional[NodeItem]:
        target = Path(name).name
        for node in self._scene.fmu_nodes():
            if node.fmu_path.name == target:
                return node
        return None

    def _existing_wire(self, node_a: NodeItem, node_b: NodeItem):
        for wire in node_a.wires:
            other = wire.node_b if wire.node_a is node_a else wire.node_a
            if other is node_b:
                return wire
        return None

    def _mark_dirty(self):
        self._window._mark_dirty()

    def _resync_fmu_detail_panel(self, node: NodeItem):
        """Refresh the FMU detail panel's tables if it currently displays *node*.

        Mirrors the wire-detail fix in :meth:`add_link`: `add_fmu()` selects
        the new node, which synchronously shows it in the FMU detail panel
        (loading its *pre-mutation* `user_start_values` /
        `user_exposed_inputs` / `user_exposed_outputs`). A later, direct
        mutation of those dicts (via `expose_input`/`expose_output`/
        `set_start_value`) would otherwise be silently discarded the next
        time `create_assembly()` calls `fmu_detail.sync_to_node()` (used by
        `get_assembly_json`/`save_as_json`/`save_as_fmu`), since that method
        overwrites the node's dicts with the (stale) table content.
        """
        fmu_detail = self._window._tree.fmu_detail
        if fmu_detail._current_node is node:
            fmu_detail._load_from_node(node)

    # -- introspection -----------------------------------------------------

    def list_fmus(self) -> List[str]:
        return [node.fmu_path.name for node in self._scene.fmu_nodes()]

    @staticmethod
    def _node_ports(node: NodeItem) -> Dict[str, Any]:
        return {
            "fmu": node.fmu_path.name,
            "fmi_version": node.fmu_fmi_version,
            "generator": node.fmu_generator,
            "inputs": [
                {"name": name, "type": node.fmu_port_type.get(name, ""),
                 "causality": node.fmu_port_causality.get(name, ""),
                 "start": node.fmu_start_values.get(name)}
                for name in node.fmu_input_names
            ],
            "outputs": [
                {"name": name, "type": node.fmu_port_type.get(name, "")}
                for name in node.fmu_output_names
            ],
            "terminals": list(node.fmu_terminal_names),
        }

    def list_fmu_ports(self, fmu: str) -> Dict[str, Any]:
        node = self._node_by_name(fmu)
        if node is not None:
            return self._node_ports(node)

        # Not in the scene yet: introspect the file off-scene, then discard.
        path = Path(fmu)
        if not path.is_file():
            raise FileNotFoundError(f"FMU '{fmu}' is neither loaded nor a valid file path.")
        probe = NodeItem(path)
        try:
            return self._node_ports(probe)
        finally:
            del probe

    def get_assembly_json(self) -> Dict[str, Any]:
        assembly = self._window.create_assembly()
        if assembly is None or assembly.root is None:
            return {}
        return assembly.json_encode()

    # -- mutations ---------------------------------------------------------

    def add_fmu(self, path: str) -> str:
        fmu_path = Path(path)
        if not fmu_path.is_file():
            raise FileNotFoundError(f"FMU file not found: '{path}'")
        node = self._scene.add_node(fmu_path)
        if node is None:
            raise ValueError(f"'{fmu_path.name}' could not be added (already present?).")
        self._mark_dirty()
        tree_logger.info(f"[AI] Added FMU '{fmu_path.name}'")
        return node.fmu_path.name

    def remove_fmu(self, name: str) -> bool:
        node = self._node_by_name(name)
        if node is None:
            raise ValueError(f"FMU '{name}' is not in the assembly.")
        self._scene.node_removed.emit(node)
        node.remove_wires()
        self._scene.removeItem(node)
        self._mark_dirty()
        tree_logger.info(f"[AI] Removed FMU '{name}'")
        return True

    def add_link(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        node_from = self._node_by_name(from_fmu)
        node_to = self._node_by_name(to_fmu)
        if node_from is None:
            raise ValueError(f"Source FMU '{from_fmu}' is not in the assembly.")
        if node_to is None:
            raise ValueError(f"Destination FMU '{to_fmu}' is not in the assembly.")
        if from_port not in node_from.fmu_output_names:
            raise ValueError(f"'{from_port}' is not an output of '{node_from.fmu_path.name}'.")
        if to_port not in node_to.fmu_input_names:
            raise ValueError(f"'{to_port}' is not an input of '{node_to.fmu_path.name}'.")

        wire = self._scene.add_wire(node_from, node_to)
        if wire is None:  # a wire already connects the two nodes
            wire = self._existing_wire(node_from, node_to)
        if wire is None:
            raise ValueError(f"Cannot create a wire between '{from_fmu}' and '{to_fmu}'.")

        mapping = (node_from.fmu_path.name, from_port, node_to.fmu_path.name, to_port)
        if mapping not in wire.mappings:
            wire.mappings.append(mapping)
            self._scene.wire_added.emit(wire)
        wire.update()
        # `scene.add_wire()` selects the new wire, which synchronously triggers
        # the tree panel's `show_wire()` -> `wire_detail.set_wire()` ->
        # `_load_from_wire()`, loading the *previous* (pre-mutation) mappings
        # into the detail panel's tab widgets. Any later `sync_to_wire()` call
        # (e.g. from `create_assembly()`, used by get/save assembly tools)
        # would then blindly overwrite `wire.mappings` with that stale/empty
        # widget content, silently discarding the link we just added. Reload
        # the panel now so it reflects the up-to-date mappings.
        wire_detail = self._window._tree.wire_detail
        if wire_detail._wire is wire:
            wire_detail._load_from_wire()
        self._mark_dirty()
        link = f"{node_from.fmu_path.name}/{from_port} -> {node_to.fmu_path.name}/{to_port}"
        tree_logger.info(f"[AI] Linked {link}")
        return link

    def expose_input(self, fmu: str, port: str) -> str:
        node = self._node_by_name(fmu)
        if node is None:
            raise ValueError(f"FMU '{fmu}' is not in the assembly.")
        if port not in node.fmu_input_names:
            raise ValueError(f"'{port}' is not an input of '{node.fmu_path.name}'.")
        node.user_exposed_inputs[port] = True
        self._resync_fmu_detail_panel(node)
        self._mark_dirty()
        tree_logger.info(f"[AI] Exposed input {node.fmu_path.name}/{port}")
        return f"{node.fmu_path.name}/{port}"

    def expose_output(self, fmu: str, port: str) -> str:
        node = self._node_by_name(fmu)
        if node is None:
            raise ValueError(f"FMU '{fmu}' is not in the assembly.")
        if port not in node.fmu_output_names:
            raise ValueError(f"'{port}' is not an output of '{node.fmu_path.name}'.")
        node.user_exposed_outputs[port] = True
        self._resync_fmu_detail_panel(node)
        self._mark_dirty()
        tree_logger.info(f"[AI] Exposed output {node.fmu_path.name}/{port}")
        return f"{node.fmu_path.name}/{port}"

    def set_start_value(self, fmu: str, port: str, value: str) -> str:
        node = self._node_by_name(fmu)
        if node is None:
            raise ValueError(f"FMU '{fmu}' is not in the assembly.")
        if port not in node.fmu_port_causality:
            raise ValueError(f"'{port}' is not a port of '{node.fmu_path.name}'.")
        node.user_start_values[port] = str(value)
        self._resync_fmu_detail_panel(node)
        self._mark_dirty()
        tree_logger.info(f"[AI] Start value {node.fmu_path.name}/{port} = {value}")
        return f"{node.fmu_path.name}/{port} = {value}"

    def set_container_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        root = self._window._tree.root
        params: Optional[ContainerParameters] = root.data(_NodeTreeModel.ROLE_CONTAINER_PARAMETERS)
        if params is None:
            params = ContainerParameters(root.text() or "container.fmu")
            root.setData(params, _NodeTreeModel.ROLE_CONTAINER_PARAMETERS)

        allowed = set(params.parameters.keys())
        unknown = set(options) - allowed
        if unknown:
            raise ValueError(f"Unknown container option(s): {sorted(unknown)}. Allowed: {sorted(allowed)}")
        params.parameters.update(options)
        self._mark_dirty()
        tree_logger.info(f"[AI] Container options updated: {options}")
        return dict(params.parameters)

    # -- build / export ----------------------------------------------------

    def save_as_json(self, path: str) -> str:
        self._window.save_as_json(path)
        tree_logger.info(f"[AI] Exported assembly JSON to '{path}'")
        return path

    def save_as_fmu(self, path: str, fmi_version: int = 2, datalog: bool = False) -> str:
        self._window.save_as_fmu(path, fmi_version=fmi_version, datalog=datalog)
        tree_logger.info(f"[AI] Built container FMU '{path}' (FMI-{fmi_version})")
        return path


# ---------------------------------------------------------------------------
# MCP application factory
# ---------------------------------------------------------------------------

USAGE_GUIDE = """\
# FMU Container Builder — AI assistant guide

You help the user compose several FMUs into a single **FMU Container** using
the live Container Builder GUI. Actions are applied immediately and visible to
the user.

Recommended workflow:
1. `list_fmus` to see what is already on the canvas.
2. `add_fmu(path)` for each FMU file the user wants to combine.
3. `list_fmu_ports(fmu)` to discover input/output ports and their types.
4. `add_link(from_fmu, from_port, to_fmu, to_port)` to connect an OUTPUT of one
   FMU to an INPUT of another. Types should be compatible.
5. `expose_input` / `expose_output` to surface ports on the container boundary
   (only needed when auto_input/auto_output are disabled or for clarity).
6. `set_start_value(fmu, port, value)` for initial values / parameters.
7. `set_container_options({...})` for step_size, mt, profiling, sequential,
   auto_link, auto_input, auto_output, auto_parameter, auto_local.
8. `get_assembly_json` to review the whole assembly before building.
9. `save_as_json(path)` to save the description, or
   `save_as_fmu(path, fmi_version=2|3, datalog=False)` to build the container.

Tips:
- FMU names are the file base names (e.g. `controller.fmu`).
- `auto_link` connects same-named/typed ports automatically at build time, so
  you often only need explicit `add_link` for ports whose names differ.
- Always confirm the target output filename with the user before `save_as_fmu`.
"""


def _build_fastmcp(bridge: GuiBridge, invoker: MainThreadInvoker):
    """Create and configure the FastMCP 2 server exposing the GUI tools."""
    try:
        from fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise McpUnavailableError(
            "The 'fastmcp' package is required for the AI assistant "
            "(pip install 'fastmcp>=2.14.0', Python >= 3.10)."
        ) from exc

    mcp = FastMCP("fmucontainer")

    def run_on_gui(fn: Callable[[], Any]) -> Any:
        return invoker.call(fn)

    @mcp.tool()
    def list_fmus() -> List[str]:
        """List the FMUs currently present in the assembly (by file name)."""
        return run_on_gui(bridge.list_fmus)

    @mcp.tool()
    def list_fmu_ports(fmu: str) -> Dict[str, Any]:
        """Describe the input/output ports of an FMU.

        `fmu` is either the name of an FMU already on the canvas or a path to
        an `.fmu` file to introspect.
        """
        return run_on_gui(lambda: bridge.list_fmu_ports(fmu))

    @mcp.tool()
    def add_fmu(path: str) -> str:
        """Add an FMU file to the assembly. Returns the FMU name."""
        return run_on_gui(lambda: bridge.add_fmu(path))

    @mcp.tool()
    def remove_fmu(name: str) -> bool:
        """Remove an FMU (and its wires) from the assembly."""
        return run_on_gui(lambda: bridge.remove_fmu(name))

    @mcp.tool()
    def add_link(from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        """Connect an OUTPUT port of one FMU to an INPUT port of another."""
        return run_on_gui(lambda: bridge.add_link(from_fmu, from_port, to_fmu, to_port))

    @mcp.tool()
    def expose_input(fmu: str, port: str) -> str:
        """Expose an FMU input port as a container input."""
        return run_on_gui(lambda: bridge.expose_input(fmu, port))

    @mcp.tool()
    def expose_output(fmu: str, port: str) -> str:
        """Expose an FMU output port as a container output."""
        return run_on_gui(lambda: bridge.expose_output(fmu, port))

    @mcp.tool()
    def set_start_value(fmu: str, port: str, value: str) -> str:
        """Set the start value (or parameter) of an FMU port."""
        return run_on_gui(lambda: bridge.set_start_value(fmu, port, value))

    @mcp.tool()
    def set_container_options(options: Dict[str, Any]) -> Dict[str, Any]:
        """Update root container options.

        Keys: step_size, mt, profiling, sequential, auto_link, auto_input,
        auto_output, auto_parameter, auto_local, ts_multiplier.
        """
        return run_on_gui(lambda: bridge.set_container_options(options))

    @mcp.tool()
    def get_assembly_json() -> Dict[str, Any]:
        """Return the current assembly as a JSON-serialisable description."""
        return run_on_gui(bridge.get_assembly_json)

    @mcp.tool()
    def save_as_json(path: str) -> str:
        """Export the current assembly description as a JSON file."""
        return run_on_gui(lambda: bridge.save_as_json(path))

    @mcp.tool()
    def save_as_fmu(path: str, fmi_version: int = 2, datalog: bool = False) -> str:
        """Build the container and save it as an `.fmu` file (FMI 2 or 3)."""
        return run_on_gui(lambda: bridge.save_as_fmu(path, fmi_version, datalog))

    @mcp.resource("guide://usage")
    def usage_guide() -> str:
        """How to drive the Container Builder to assemble FMUs."""
        return USAGE_GUIDE

    @mcp.resource("assembly://current")
    def current_assembly() -> str:
        """The current assembly description (JSON)."""
        import json
        return json.dumps(run_on_gui(bridge.get_assembly_json), indent=2)

    return mcp


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


class _UvicornThread(QThread):
    """Runs the uvicorn/Streamable-HTTP server for the MCP app in a thread."""

    failed = Signal(str)

    def __init__(self, app, host: str, port: int, parent=None):
        super().__init__(parent)
        self._app = app
        self._host = host
        self._port = port
        self._server = None

    def run(self):  # noqa: D401 - QThread entry point
        try:
            import uvicorn

            config = uvicorn.Config(self._app, host=self._host, port=self._port,
                                    log_level="warning", lifespan="on")
            self._server = uvicorn.Server(config)
            # uvicorn.Server.run() creates and manages its own asyncio loop.
            self._server.run()
        except Exception as exc:  # noqa: BLE001 - report back to the GUI
            self.failed.emit(str(exc))

    def stop(self):
        if self._server is not None:
            # Thread-safe flag polled by uvicorn's serve loop for graceful exit.
            self._server.should_exit = True

    def force_stop(self):
        """Ask uvicorn to drop remaining open connections instead of waiting.

        uvicorn's graceful ``shutdown()`` waits *indefinitely* for all open
        connections to close once ``should_exit`` is set. The Streamable HTTP
        transport used by MCP typically keeps a long-lived connection open
        (SSE-style stream), so a client that is still attached can make the
        graceful path hang forever. Setting ``force_exit`` makes uvicorn stop
        waiting for connections and close immediately.
        """
        if self._server is not None:
            self._server.force_exit = True


class McpServerController(QObject):
    """Starts/stops the MCP HTTP server bound to the Container Builder GUI.

    A ``QObject`` living on the Qt main thread: the worker thread's ``failed``
    signal is therefore delivered on the main thread (queued connection), so
    all error handling / logging / UI stays on the main thread (required on
    macOS).
    """

    #: Emitted on the main thread when the server cannot start / has failed.
    error = Signal(str)

    def __init__(self, window: "MainWindow", host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        super().__init__()
        self._window = window
        self._host = host
        self._port = port
        self._bridge = GuiBridge(window)
        # The invoker must live on the Qt main thread.
        self._invoker = MainThreadInvoker()
        self._thread: Optional[_UvicornThread] = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}/mcp"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _check_port_available(self):
        """Raise OSError (on the main thread) if the port is already taken.

        This avoids relying on the uvicorn worker thread to report a bind
        failure, which would otherwise log/handle the error off the main
        thread.
        """
        import socket

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Match uvicorn's own listening socket (see uvicorn.Config.bind_socket),
        # which always sets SO_REUSEADDR. Without it, this probe can report a
        # false "port already in use" right after a previous server instance
        # was stopped: the just-closed listening socket may still linger
        # briefly (TIME_WAIT) even though a real bind with SO_REUSEADDR would
        # succeed immediately.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((self._host, self._port))
        except OSError as exc:
            raise OSError(
                f"Cannot start the AI Assistant: address {self._host}:{self._port} "
                f"is already in use ({exc.strerror}). Close the other instance or set "
                f"a different port via the FMUCONTAINER_MCP_PORT environment variable."
            ) from exc
        finally:
            probe.close()

    def start(self):
        """Build the MCP app and start the Streamable HTTP server thread.

        Raises:
            McpUnavailableError: if the optional ``fastmcp`` package is missing.
            OSError: if the port is already in use.
        """
        if self.running:
            return
        self._check_port_available()
        mcp = _build_fastmcp(self._bridge, self._invoker)
        # FastMCP 2 Streamable HTTP ASGI app (endpoint path: /mcp).
        app = mcp.http_app(path="/mcp")
        self._thread = _UvicornThread(app, self._host, self._port)
        # Queued delivery on the main thread (self lives on the main thread).
        self._thread.failed.connect(self._on_thread_failed)
        self._thread.start()
        logger.info(f"MCP server (AI assistant) listening on {self.url}")

    def stop(self):
        if self._thread is None:
            return
        logger.info("Stopping MCP server (AI assistant)...")
        self._thread.stop()
        if not self._thread.wait(2000):
            # Graceful shutdown is stuck, most likely because uvicorn is
            # waiting for a still-open Streamable HTTP connection to close.
            # Force it to drop remaining connections instead of hanging.
            logger.warning(
                "MCP server did not stop gracefully (client still connected?); "
                "forcing shutdown..."
            )
            self._thread.force_stop()
            if not self._thread.wait(3000):
                # Last resort: hard-kill the thread. Note this may leave the
                # TCP port lingering for a short while (TIME_WAIT).
                logger.error("MCP server thread is unresponsive; terminating it.")
                self._thread.terminate()
                self._thread.wait(2000)
        self._thread = None

    def _on_thread_failed(self, message: str):
        """Handle a server-thread failure on the main thread."""
        logger.error(f"MCP server error: {message}")
        self.stop()
        self.error.emit(message)


