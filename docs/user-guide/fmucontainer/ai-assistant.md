# AI Assistant (MCP server)

The **Container Builder** GUI can expose its assembly capabilities to an AI
agent (such as GitHub Copilot in *Agent* mode) through a
[Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server.

The agent drives the **live** canvas: FMUs it adds, links it creates and
options it sets appear immediately in the GUI. Every action is marked as an
unsaved change (so it can be reviewed, undone or saved) and is written to the
log panel.

## Requirements

- Python **3.10+** and the optional `fastmcp` package (FastMCP 2):

  ```bash
  pip install "fastmcp>=2.14.0"
  ```

  It is installed automatically with the toolbox on supported Python versions.

## Starting the server

1. Launch the Container Builder (`fmucontainer-gui`).
2. Open the **Configuration** menu (top-left button).
3. Select **AI Assistant On**.

The server listens locally using the **Streamable HTTP** transport on:

```
http://127.0.0.1:8765/mcp
```

The port can be overridden with the `FMUCONTAINER_MCP_PORT` environment
variable. The server is bound to `127.0.0.1` only.

Select **AI Assistant Off** (or close the window) to stop the server.

## Connecting GitHub Copilot

Copilot must be in **Agent** mode (MCP servers are not used in *Ask* mode), and
the server must be started **before** Copilot connects.

### JetBrains IDEs

Open the Copilot chat, switch to **Agent** mode, open the tools/settings menu
and **Edit MCP configuration**
(`Settings → Languages & Frameworks → GitHub Copilot → Model Context Protocol`),
then add:

```json
{
  "servers": {
    "fmucontainer": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

### VS Code

Create `.vscode/mcp.json` at the root of your workspace:

```json
{
  "servers": {
    "fmucontainer": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

## Available tools

| Tool | Description |
|------|-------------|
| `list_fmus` | List FMUs currently in the assembly |
| `list_fmu_ports` | Describe input/output ports of an FMU (loaded or by path) |
| `add_fmu` | Add an FMU file to the assembly |
| `remove_fmu` | Remove an FMU and its wires |
| `add_link` | Connect an output port to an input port |
| `expose_input` / `expose_output` | Surface a port on the container boundary |
| `set_start_value` | Set a start value / parameter |
| `set_container_options` | Set `step_size`, `mt`, `profiling`, `auto_*`, … |
| `get_assembly_json` | Review the whole assembly |
| `save_as_json` | Export the assembly description |
| `save_as_fmu` | Build the container FMU (FMI 2 or 3) |

Two resources are also exposed: `guide://usage` (how to drive the tool) and
`assembly://current` (the current assembly as JSON).

