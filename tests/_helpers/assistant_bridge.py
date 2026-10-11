"""Fake bridge and helpers shared by the unit tests of the MCP server.

`FakeBridge` is an in-memory `AssemblyBridge` recording the calls it receives, so that the server can be driven
through an in-memory `fastmcp.Client` without Qt or real FMUs. Import it after
`pytest.importorskip("fastmcp")`: the `mcp` extra is optional.
"""
import asyncio
from pathlib import Path

import fastmcp

from fmu_manipulation_toolbox.assistant import build_server
from fmu_manipulation_toolbox.assistant.bridge import SUPPORTED_FMI_VERSIONS


def make_port(name, causality, type_="Real", **extra):
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
        ports = [make_port("u", "input", start="0"), make_port("y", "output"),
                 make_port("gain", "parameter", start="1"), make_port("state", "local")]
        ports += [make_port(f"extra_{i}", "input") for i in range(port_count - 1)]
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


def run(coro):
    return asyncio.run(coro)


def input_schema(tool):
    """Read a tool's input schema, whatever the FastMCP version.

    FastMCP 4 renamed ``Tool.inputSchema`` to ``Tool.input_schema`` and
    deprecated the old spelling.
    """
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = tool.inputSchema
    return schema or {}


def fmu_file(directory, name):
    """Create a placeholder `.fmu` file so path validation accepts it."""
    path = directory / name
    path.write_bytes(b"not a real FMU")
    return path


async def inventory(bridge):
    async with fastmcp.Client(build_server(bridge)) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        return tools, resources


def call_tool(bridge, tool, arguments, policy=None):
    async def scenario():
        async with fastmcp.Client(build_server(bridge, policy=policy)) as client:
            return await client.call_tool(tool, arguments)

    return run(scenario())


def read_resource(bridge, uri):
    async def scenario():
        async with fastmcp.Client(build_server(bridge)) as client:
            return await client.read_resource(uri)

    return run(scenario())[0].text


def resolve_ref(schema, node):
    """Follow a ``$ref`` if the model was not inlined by FastMCP."""
    ref = node.get("$ref")
    if ref is None:
        return node
    return schema["$defs"][ref.rsplit("/", 1)[-1]]
