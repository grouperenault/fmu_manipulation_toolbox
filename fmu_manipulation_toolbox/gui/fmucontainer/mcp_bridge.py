"""Qt bridge and HTTP runner for the Container Builder MCP server.

This module is the **Qt side** of the AI assistant: it implements the
:class:`~fmu_manipulation_toolbox.assistant.bridge.AssemblyBridge` protocol on
top of the live Container Builder window, and runs the MCP server (built by
:func:`~fmu_manipulation_toolbox.assistant.server.build_server`) over the
Streamable HTTP transport.

Every action is applied on the live scene/tree (so the user sees it happen),
marked *dirty* (undoable / re-savable) and logged to the visible log panel.

Design
------
Qt owns the main-thread event loop. The MCP server (uvicorn + anyio) runs in a
dedicated ``QThread``, and FastMCP additionally dispatches synchronous tools to
its own worker threads. Because all GUI objects must only be touched from the
Qt main thread, every bridge method marshals its work onto the main thread
through :class:`MainThreadInvoker` (a queued signal + blocking wait), and
returns the result to the calling worker thread.
"""

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal

from fmu_manipulation_toolbox.assistant import (
    BUILD_TIMEOUT_FACTOR, DEFAULT_HOST, PORT_ENV_VAR, TIMEOUT_ENV_VAR, build_server,
    resolve_port, resolve_timeout,
)
from fmu_manipulation_toolbox.assistant.auth import (
    TOKEN_ENV_VAR, build_auth_middleware, resolve_token,
)
from fmu_manipulation_toolbox.assistant.bridge import SUPPORTED_FMI_VERSIONS

from .details import ContainerParameters
from .graph import NodeItem
from .tree.model import _NodeTreeModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .__main__ import MainWindow


logger = logging.getLogger("fmu_manipulation_toolbox")
tree_logger = logging.getLogger("fmu_manipulation_toolbox.gui.tree")


def _count_by_causality(ports: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for port in ports:
        causality = port["causality"] or "unknown"
        counts[causality] = counts.get(causality, 0) + 1
    return counts


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

    def __init__(self, timeout: Optional[float] = None):
        super().__init__()
        # QueuedConnection guarantees `_run` executes in this object's thread
        # (the main thread), regardless of the emitting thread.
        self._invoke.connect(self._run, Qt.ConnectionType.QueuedConnection)
        self.timeout = resolve_timeout() if timeout is None else timeout

    @staticmethod
    def _run(task: Callable[[], None]):
        task()

    def call(self, fn: Callable[[], Any], timeout: Optional[float] = None) -> Any:
        """Execute ``fn`` on the Qt main thread and return its result.

        Args:
            fn: Callable to run on the main thread.
            timeout: Seconds to wait. Defaults to :attr:`timeout`, itself
                configurable through ``FMUCONTAINER_MCP_TIMEOUT``.

        Re-raises on the calling thread any exception raised by ``fn``.

        Raises:
            TimeoutError: If the main thread did not run ``fn`` in time. This
                is not a failure of the operation: the GUI is simply busy (a
                modal dialog, a long build), and the operation may well still
                be applied afterwards.
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

        budget = self.timeout if timeout is None else timeout
        self._invoke.emit(task)
        if not done.wait(budget):
            raise TimeoutError(
                f"The Container Builder window did not answer within {budget:g} s. "
                f"It is probably busy (a dialog may be waiting for the user). The "
                f"operation may still complete on its own: check the window before "
                f"retrying, and raise {TIMEOUT_ENV_VAR} if this keeps happening."
            )
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")


# ---------------------------------------------------------------------------
# GUI bridge – all operations are marshalled onto the Qt main thread
# ---------------------------------------------------------------------------


class QtAssemblyBridge:
    """:class:`AssemblyBridge` implementation driving the Container Builder GUI.

    Public methods may be called from any thread: each one marshals its work
    onto the Qt main thread through the :class:`MainThreadInvoker`. The
    ``_impl``-suffixed counterparts hold the actual GUI logic and always run on
    the main thread.
    """

    def __init__(self, window: "MainWindow", invoker: MainThreadInvoker):
        self._window = window
        self._invoker = invoker

    @property
    def _build_timeout(self) -> float:
        """Budget for the operations that rewrite every embedded FMU.

        Editing the canvas is instantaneous; building a container is not, and
        the two cannot share a deadline without making one of them wrong.
        """
        return self._invoker.timeout * BUILD_TIMEOUT_FACTOR

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

        Mirrors the wire-detail fix in :meth:`_add_link_impl`: `add_fmu()`
        selects the new node, which synchronously shows it in the FMU detail
        panel (loading its *pre-mutation* `user_start_values` /
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
        return self._invoker.call(self._list_fmus_impl)

    def _list_fmus_impl(self) -> List[str]:
        return [node.fmu_path.name for node in self._scene.fmu_nodes()]

    @staticmethod
    def _node_ports(node: NodeItem) -> Dict[str, Any]:
        """Describe every port of *node*, all causalities included.

        Filtering and pagination are the server's job: this returns the whole
        picture so the assistant layer stays the single place that decides
        what the client actually sees.
        """
        kinds = []
        if node.fmu_is_cosimulation:
            kinds.append("CoSimulation")
        if node.fmu_is_model_exchange:
            kinds.append("ModelExchange")

        ports = []
        for name, causality in node.fmu_port_causality.items():
            details = node.fmu_port_details.get(name, {})
            ports.append({
                "name": name,
                "type": node.fmu_port_type.get(name, ""),
                "causality": causality,
                "variability": details.get("variability"),
                "unit": details.get("unit"),
                "start": node.user_start_values.get(name, node.fmu_start_values.get(name)),
                "description": details.get("description"),
            })

        return {
            "fmu": node.fmu_path.name,
            "path": str(node.fmu_path),
            "fmi_version": node.fmu_fmi_version,
            "generator": node.fmu_generator,
            "kinds": kinds,
            "terminals": list(node.fmu_terminal_names),
            "ports": ports,
        }

    def list_fmu_ports(self, fmu: str) -> Dict[str, Any]:
        return self._invoker.call(lambda: self._list_fmu_ports_impl(fmu))

    def _list_fmu_ports_impl(self, fmu: str) -> Dict[str, Any]:
        node = self._node_by_name(fmu)
        if node is None:
            known = ", ".join(self._list_fmus_impl()) or "none"
            raise ValueError(
                f"FMU '{fmu}' is not in the assembly (currently: {known}). "
                f"Use `inspect_fmu_file` to look at a file that has not been added."
            )
        return self._node_ports(node)

    def inspect_fmu_file(self, path: str) -> Dict[str, Any]:
        return self._invoker.call(lambda: self._inspect_fmu_file_impl(path))

    def _inspect_fmu_file_impl(self, path: str) -> Dict[str, Any]:
        # Read the descriptor off-scene through a throw-away node, so the
        # inspected file is never added to the assembly.
        probe = NodeItem(Path(path))
        try:
            return self._node_ports(probe)
        finally:
            del probe

    def get_assembly_json(self) -> Dict[str, Any]:
        return self._invoker.call(self._get_assembly_json_impl)

    def _get_assembly_json_impl(self) -> Dict[str, Any]:
        assembly = self._window.create_assembly()
        if assembly is None or assembly.root is None:
            return {}
        return assembly.json_encode()

    # -- mutations ---------------------------------------------------------

    def add_fmu(self, path: str) -> Dict[str, Any]:
        return self._invoker.call(lambda: self._add_fmu_impl(path))

    def _add_fmu_impl(self, path: str) -> Dict[str, Any]:
        fmu_path = Path(path)
        if not fmu_path.is_file():
            raise FileNotFoundError(f"FMU file not found: '{path}'")
        node = self._scene.add_node(fmu_path)
        if node is None:
            raise ValueError(f"'{fmu_path.name}' could not be added (already present?).")
        self._mark_dirty()
        tree_logger.info(f"[AI] Added FMU '{fmu_path.name}'")

        description = self._node_ports(node)
        return {
            "fmu": description["fmu"],
            "path": description["path"],
            "fmi_version": description["fmi_version"],
            "generator": description["generator"],
            "kinds": description["kinds"],
            "counts": _count_by_causality(description["ports"]),
            "terminals": description["terminals"],
        }

    def remove_fmu(self, name: str) -> Dict[str, Any]:
        return self._invoker.call(lambda: self._remove_fmu_impl(name))

    def _remove_fmu_impl(self, name: str) -> Dict[str, Any]:
        node = self._node_by_name(name)
        if node is None:
            raise ValueError(f"FMU '{name}' is not in the assembly.")
        removed_links = sum(len(wire.mappings) for wire in node.wires)
        self._scene.node_removed.emit(node)
        node.remove_wires()
        self._scene.removeItem(node)
        self._mark_dirty()
        tree_logger.info(f"[AI] Removed FMU '{name}' ({removed_links} link(s))")
        return {"fmu": node.fmu_path.name, "removed_links": removed_links}

    def add_link(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        return self._invoker.call(lambda: self._add_link_impl(from_fmu, from_port, to_fmu, to_port))

    def _add_link_impl(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
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

    def remove_link(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        return self._invoker.call(
            lambda: self._remove_link_impl(from_fmu, from_port, to_fmu, to_port))

    def _remove_link_impl(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        node_from = self._node_by_name(from_fmu)
        node_to = self._node_by_name(to_fmu)
        if node_from is None:
            raise ValueError(f"Source FMU '{from_fmu}' is not in the assembly.")
        if node_to is None:
            raise ValueError(f"Destination FMU '{to_fmu}' is not in the assembly.")

        wire = self._existing_wire(node_from, node_to)
        mapping = (node_from.fmu_path.name, from_port, node_to.fmu_path.name, to_port)
        if wire is None or mapping not in wire.mappings:
            raise ValueError(
                f"There is no link {from_fmu}/{from_port} -> {to_fmu}/{to_port}. "
                f"Use `get_assembly_json` to see the existing ones."
            )

        wire.mappings.remove(mapping)
        # Same staleness trap as in `_add_link_impl`: the detail panel holds a
        # copy of the mappings and would write it back over ours.
        wire_detail = self._window._tree.wire_detail
        if wire_detail._wire is wire:
            wire_detail._load_from_wire()

        # A wire carrying nothing is visual noise: drop it, unless it still
        # holds terminal mappings, which are links of their own.
        if not wire.mappings and not wire.terminal_mappings:
            self._scene.wire_removed.emit(wire)
            wire.remove()
        else:
            wire.update()

        self._mark_dirty()
        link = f"{node_from.fmu_path.name}/{from_port} -> {node_to.fmu_path.name}/{to_port}"
        tree_logger.info(f"[AI] Unlinked {link}")
        return link

    def expose_input(self, fmu: str, port: str) -> str:
        return self._invoker.call(lambda: self._expose_input_impl(fmu, port))

    def _expose_input_impl(self, fmu: str, port: str) -> str:
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
        return self._invoker.call(lambda: self._expose_output_impl(fmu, port))

    def _expose_output_impl(self, fmu: str, port: str) -> str:
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
        return self._invoker.call(lambda: self._set_start_value_impl(fmu, port, value))

    def _set_start_value_impl(self, fmu: str, port: str, value: str) -> str:
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

    def unset_start_value(self, fmu: str, port: str) -> str:
        return self._invoker.call(lambda: self._unset_start_value_impl(fmu, port))

    def _unset_start_value_impl(self, fmu: str, port: str) -> str:
        node = self._node_by_name(fmu)
        if node is None:
            raise ValueError(f"FMU '{fmu}' is not in the assembly.")
        if port not in node.user_start_values:
            declared = node.fmu_start_values.get(port)
            raise ValueError(
                f"No start value was set on {node.fmu_path.name}/{port}"
                + (f" (the FMU declares '{declared}')." if declared is not None
                   else " and the FMU declares none.")
            )
        del node.user_start_values[port]
        self._resync_fmu_detail_panel(node)
        self._mark_dirty()
        tree_logger.info(f"[AI] Start value cleared on {node.fmu_path.name}/{port}")
        return f"{node.fmu_path.name}/{port}"

    def set_container_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        return self._invoker.call(lambda: self._set_container_options_impl(options))

    def _set_container_options_impl(self, options: Dict[str, Any]) -> Dict[str, Any]:
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
        return self._invoker.call(lambda: self._save_as_json_impl(path),
                                  timeout=self._build_timeout)

    def _save_as_json_impl(self, path: str) -> str:
        self._window.save_as_json(path)
        tree_logger.info(f"[AI] Exported assembly JSON to '{path}'")
        return path

    def save_as_fmu(self, path: str, fmi_version: int = 2, datalog: bool = False) -> str:
        return self._invoker.call(lambda: self._save_as_fmu_impl(path, fmi_version, datalog),
                                  timeout=self._build_timeout)

    def _save_as_fmu_impl(self, path: str, fmi_version: int, datalog: bool) -> str:
        if fmi_version not in SUPPORTED_FMI_VERSIONS:
            raise ValueError(
                f"Unsupported FMI version {fmi_version!r}: expected one of "
                f"{list(SUPPORTED_FMI_VERSIONS)}."
            )
        self._window.save_as_fmu(path, fmi_version=fmi_version, datalog=datalog)
        tree_logger.info(f"[AI] Built container FMU '{path}' (FMI-{fmi_version})")
        return path


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

    def __init__(self, window: "MainWindow", host: str = DEFAULT_HOST, port: Optional[int] = None):
        super().__init__()
        self._window = window
        self._host = host
        # Resolved on first use (i.e. when the server starts), so a malformed
        # FMUCONTAINER_MCP_PORT cannot break an unrelated import.
        self._port = port
        # The invoker must live on the Qt main thread.
        self._invoker = MainThreadInvoker()
        self._bridge = QtAssemblyBridge(window, self._invoker)
        self._thread: Optional[_UvicornThread] = None
        #: Bearer token required from clients, resolved when the server starts.
        self._token: Optional[str] = None

    @property
    def token(self) -> Optional[str]:
        """Token clients must present, or ``None`` when the port is open."""
        return self._token

    @property
    def port(self) -> int:
        """TCP port the server listens on.

        Raises:
            ValueError: If ``FMUCONTAINER_MCP_PORT`` holds an invalid value.
        """
        if self._port is None:
            self._port = resolve_port()
        return self._port

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}/mcp"

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
            probe.bind((self._host, self.port))
        except OSError as exc:
            raise OSError(
                f"Cannot start the AI Assistant: address {self._host}:{self.port} "
                f"is already in use ({exc.strerror}). Close the other instance or set "
                f"a different port via the {PORT_ENV_VAR} environment variable."
            ) from exc
        finally:
            probe.close()

    def start(self):
        """Build the MCP app and start the Streamable HTTP server thread.

        Raises:
            McpUnavailableError: if the optional ``fastmcp`` package is missing.
            ValueError: if ``FMUCONTAINER_MCP_PORT`` holds an invalid value.
            OSError: if the port is already in use.
        """
        if self.running:
            return
        self._check_port_available()
        mcp = build_server(self._bridge)
        # FastMCP Streamable HTTP ASGI app (endpoint path: /mcp).
        app = mcp.http_app(path="/mcp")

        # Opt-in authentication: without a token, any local process can drive
        # the GUI and write files through it (see `assistant.auth`).
        self._token = resolve_token()
        if self._token:
            app = build_auth_middleware(self._token)(app)
            logger.info("MCP server: bearer token required. Configure your "
                        "client with: Authorization: Bearer <token>")
            logger.info(f"MCP server token: {self._token}")
        else:
            logger.warning(
                f"MCP server: no authentication. Any local process can drive "
                f"this window and read/write files through it. Set "
                f"{TOKEN_ENV_VAR}=generate to require a token."
            )

        self._thread = _UvicornThread(app, self._host, self.port)
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

