"""Bridge protocol between the MCP server and an FMU assembly backend.

The assistant layer never talks to a GUI (nor to Qt) directly: it only knows
the :class:`AssemblyBridge` protocol defined here. Two implementations are
expected:

* the **Qt bridge** (:mod:`fmu_manipulation_toolbox.gui.fmucontainer.mcp_bridge`),
  which drives the live Container Builder window, and
* a **headless bridge**, built on top of the public
  [Assembly][fmu_manipulation_toolbox.assembly.Assembly] API.

This module only depends on the standard library so that
``import fmu_manipulation_toolbox.assistant`` stays cheap and works even when
the optional ``fastmcp`` package is not installed.
"""

from typing import Any, Dict, List, Literal, Protocol, runtime_checkable

#: FMI versions a container interface can be built for.
SUPPORTED_FMI_VERSIONS = (2, 3)



@runtime_checkable
class AssemblyBridge(Protocol):
    """Assembly operations an MCP client can drive.

    Embedded FMUs are designated by their **file name** (e.g. ``controller.fmu``),
    not by their full path.

    Implementations raise plain exceptions on invalid requests
    (``ValueError`` for an unknown FMU/port, ``FileNotFoundError`` for a missing
    file); the server layer turns them into MCP errors.
    """

    # -- introspection -----------------------------------------------------
    def list_fmus(self) -> List[str]:
        """Return the file names of the FMUs currently in the assembly."""

    def list_fmu_ports(self, fmu: str) -> Dict[str, Any]:
        """Describe an FMU of the assembly, designated by its name.

        Returns a mapping with ``fmu``, ``fmi_version``, ``generator``,
        ``kinds``, ``terminals`` and ``ports``: the **complete**, unfiltered
        port list, every causality included. Filtering and pagination are
        applied by the server, not here.
        """

    def inspect_fmu_file(self, path: str) -> Dict[str, Any]:
        """Describe an ``.fmu`` file without adding it to the assembly.

        Same shape as :meth:`list_fmu_ports`.
        """

    def get_assembly_json(self) -> Dict[str, Any]:
        """Return the current assembly as a JSON-serialisable description."""

    # -- mutations ---------------------------------------------------------
    def add_fmu(self, path: str) -> Dict[str, Any]:
        """Add the FMU found at ``path``.

        Returns a summary: ``fmu`` (the name to use afterwards), ``path``,
        ``fmi_version``, ``generator``, ``kinds``, ``counts``, ``terminals``.
        """

    def remove_fmu(self, name: str) -> Dict[str, Any]:
        """Remove ``name`` and the links attached to it.

        Returns ``fmu`` and ``removed_links``.
        """

    def add_link(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        """Connect an output port of one FMU to an input port of another."""

    def remove_link(self, from_fmu: str, from_port: str, to_fmu: str, to_port: str) -> str:
        """Disconnect a link previously created by :meth:`add_link`.

        Raises ``ValueError`` when the link does not exist: silently doing
        nothing would let a client believe it undid something it did not.
        """

    def expose_input(self, fmu: str, port: str) -> str:
        """Expose an input port of ``fmu`` as a container input."""

    def expose_output(self, fmu: str, port: str) -> str:
        """Expose an output port of ``fmu`` as a container output."""

    def set_start_value(self, fmu: str, port: str, value: str) -> str:
        """Set the start value (or parameter value) of a port."""

    def unset_start_value(self, fmu: str, port: str) -> str:
        """Drop a start value set by :meth:`set_start_value`.

        The port falls back to the value declared by the FMU itself. Raises
        ``ValueError`` when no start value was set.
        """

    def set_container_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """Update the root container options and return them all."""

    # -- build / export ----------------------------------------------------
    def save_as_json(self, path: str) -> str:
        """Export the assembly description to ``path`` and return it."""

    def save_as_fmu(self, path: str, fmi_version: Literal[2, 3] = 2, datalog: bool = False) -> str:
        """Build the container FMU into ``path`` and return it.

        ``fmi_version`` is the FMI version of the container interface and must
        be 2 or 3; implementations reject any other value instead of producing
        a broken archive.
        """

