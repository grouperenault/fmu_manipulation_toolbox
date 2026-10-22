"""AI assistant layer: MCP server exposing the FMU Manipulation Toolbox.

This package is GUI-agnostic: it never imports Qt. The MCP tools are defined
against the :class:`~fmu_manipulation_toolbox.assistant.bridge.AssemblyBridge`
protocol, which the Container Builder GUI implements to let an MCP client drive
the live window.

Importing this package does **not** require the optional ``mcp`` extra:
``fastmcp`` is only imported when
:func:`~fmu_manipulation_toolbox.assistant.server.build_server` is called.
"""

from .bridge import AssemblyBridge
from .paths import PathPolicy, PathValidationError
from .server import (
    BUILD_TIMEOUT_FACTOR, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_TIMEOUT,
    PORT_ENV_VAR, TIMEOUT_ENV_VAR, USAGE_GUIDE,
    McpUnavailableError, build_server, resolve_port, resolve_timeout,
)

__all__ = [
    "AssemblyBridge",
    "BUILD_TIMEOUT_FACTOR",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_TIMEOUT",
    "PORT_ENV_VAR",
    "TIMEOUT_ENV_VAR",
    "USAGE_GUIDE",
    "McpUnavailableError",
    "PathPolicy",
    "PathValidationError",
    "build_server",
    "resolve_port",
    "resolve_timeout",
]

