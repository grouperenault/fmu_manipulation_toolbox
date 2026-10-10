# AI Assistant (MCP server)

The toolbox exposes its FMU Container assembly capabilities to an AI agent
(such as GitHub Copilot in *Agent* mode) through a
[Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server.

It comes in **two flavours**, serving exactly the same tools:

| Flavour | How it starts | What the agent drives |
|---------|---------------|-----------------------|
| **GUI** | **AI Assistant On** in the Container Builder | The **live** canvas |
| **Standalone** | `fmutool-mcp`, launched by the MCP client | An in-memory assembly |

With the GUI flavour, FMUs the agent adds, links it creates and options it
sets appear immediately in the window. Every action is marked as an unsaved
change (so it can be reviewed, undone or saved) and is written to the log
panel.

The standalone flavour needs neither a display nor a running GUI, and speaks
the **stdio** transport that most MCP clients expect from a server they launch
themselves. Nothing is visible until the agent exports or builds the assembly.

## Requirements

- The optional `fastmcp` package. It is **not**
  installed by default: pull it in through the `mcp` extra of the toolbox:

  ```bash
  pip install "fmu-manipulation-toolbox[mcp]"
  ```

  To combine it with the GUI (required to run the Container Builder), use:

  ```bash
  pip install "fmu-manipulation-toolbox[gui,mcp]"
  ```

## Starting the standalone server

The server is normally **launched by the MCP client**, not by hand. Declare it
as a command (see [Connecting a client that launches the
server](#connecting-a-client-that-launches-the-server) below); the useful
options are:

```
fmutool-mcp [--transport stdio|http] [--root DIR] [--host H] [--port P] [--name container.fmu] [--token TOKEN]
```

- `--transport stdio` (the default) is what a client that spawns the server
  expects. `--transport http` lets clients attach to an already-running
  server instead.
- `--root DIR` confines the assistant to a directory tree. **Use it**: it is
  what keeps an agent from reading or writing anywhere on your disk. The
  `FMUCONTAINER_MCP_ROOT` environment variable does the same.
- `--token generate` requires a bearer token from HTTP clients and prints it.
  See [Security](#security); it is pointless with the stdio transport.

All logs go to **stderr**, since with the stdio transport stdout carries the
protocol itself.

## Starting the server from the GUI

1. Launch the Container Builder (`fmucontainer-gui`).
2. Open the **Configuration** menu (top-left button).
3. Select **AI Assistant On**.

The server listens locally using the **Streamable HTTP** transport on:

```
http://127.0.0.1:8765/mcp
```

The port can be overridden with the `FMUCONTAINER_MCP_PORT` environment
variable. The server is bound to `127.0.0.1` only.

### Tuning the timeout

Each tool waits for the GUI to apply its operation before answering (this
concerns the GUI flavour only — the standalone server has no window to wait
for). That budget defaults to **60 s** and can be changed with
`FMUCONTAINER_MCP_TIMEOUT` (a number of seconds):

```bash
FMUCONTAINER_MCP_TIMEOUT=180 fmucontainer-gui
```

Building a container may be slower than editing one, so `save_as_json` and
`save_as_fmu` get ten times that budget automatically — there is no second
variable to set.

A timeout means the window did not *answer*, usually because a dialog is
waiting for you; it does not mean the operation failed. Check the window
before retrying.

Select **AI Assistant Off** (or close the window) to stop the server.

## Connecting a client that launches the server

This is the standalone flavour: the client spawns `fmutool-mcp` itself,
so there is nothing to start beforehand.

**Claude Desktop** — add to `claude_desktop_config.json`
(`~/Library/Application Support/Claude/` on macOS,
`%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "fmutool": {
      "command": "fmutool-mcp",
      "args": ["--root", "/path/to/my/fmus"]
    }
  }
}
```

**VS Code** — in `.vscode/mcp.json`:

```json
{
  "servers": {
    "fmutool": {
      "type": "stdio",
      "command": "fmutool-mcp",
      "args": ["--root", "${workspaceFolder}"]
    }
  }
}
```

The `fmutool` key is the name the client will show you; it is yours to choose,
and does not have to match the name the server advertises.

If `fmutool-mcp` is not on the `PATH` of the client (a common case when
the toolbox lives in a virtual environment), give the absolute path of the
script, or use `"command": "/path/to/venv/bin/python"` with
`"args": ["-m", "fmu_manipulation_toolbox.cli.fmutool_mcp", ...]`.

## Connecting GitHub Copilot to the GUI server

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
    "fmutool": {
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
    "fmutool": {
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
| `list_fmu_ports` | List the ports of an FMU on the canvas, with filters and paging |
| `inspect_fmu_file` | Describe an `.fmu` file without adding it to the assembly |
| `add_fmu` | Add an FMU file to the assembly |
| `remove_fmu` | Remove an FMU and its wires |
| `add_link` / `add_links` | Connect an output port to an input port, one at a time or in bulk |
| `remove_link` | Disconnect an explicit link |
| `expose_input` / `expose_output` | Surface a port on the container boundary |
| `set_start_value` / `unset_start_value` | Set, or drop, a start value / parameter |
| `set_container_options` | Set `step_size`, `mt`, `profiling`, `auto_*`, … |
| `get_assembly_json` | Review the whole assembly |
| `save_as_json` | Export the assembly description |
| `save_as_fmu` | Build the container FMU (FMI 2 or 3), reporting progress |

### Single-FMU tools

These come from `fmutool` and the `Checker`. They read or rewrite **one**
`.fmu` file and never touch the assembly:

| Tool | Description |
|------|-------------|
| `summarize_fmu` | Identity, capabilities, platforms, embedded resources, port counts |
| `check_fmu` | Conformity to the FMI standard: schema and semantic rules, plus any registered checker |
| `dump_ports_csv` | Export every port to a CSV file, for bulk renaming |
| `rename_ports_from_csv` | Rename — or drop — ports from that CSV |
| `apply_operation` | Strip/merge a `Bus.` prefix, trim, or filter ports by regexp |

The three that rewrite an FMU always produce a **new** file and leave the
source untouched. They change the FMU interface, so anything already
connected to the old port names will break.

`check_fmu` answers `compliant: true` only when the descriptor validates against the FMI schema **and** no
checker reports an error (`compliant_with` gives the FMI version of the schema). To keep the answer small, the
messages of the same rule are grouped, with their `count` and a few `examples` — 2500 variables without start
value make one entry — and at most 50 groups are returned per list; `error_count` and `warning_count` give the
totals and `truncated` tells whether groups were left out. The full report is printed by
`fmutool -input model.fmu -check`.

!!! warning "An empty `newName` removes the port"

    In the CSV consumed by `rename_ports_from_csv`, a row whose second column
    is empty **deletes** that port. The tool reports `renamed` and `removed`
    separately so the assistant can tell you what actually happened.

### Reading port listings

`list_fmu_ports` and `inspect_fmu_file` report **every** variable of the FMU —
inputs, outputs, parameters and locals alike — each with its `causality`,
`variability`, `type`, `unit`, `start` value and `description`. Attributes the
FMU does not declare are left out, and descriptions are cut after 80
characters.

Industrial FMUs have thousands of variables, so the answer is bounded: 50
ports are returned per call by default, at most 200 with `limit`. Rather than
paging blindly, narrow the request:

- `causality=["output"]` before looking for something to wire,
- `name_pattern="^engine_"` to search by name (a regular expression),
- `offset` to fetch the next page when `truncated` is `true`.

The `counts` field always describes the whole FMU, whatever the filter, and
`total` counts the ports matching the filter. Comparing `returned` with
`total` tells the assistant whether it has seen everything.

Two resources are also exposed: `guide://usage` (how to drive the tool) and
`assembly://current` (the current assembly as JSON).

## Local models

The tools also work with models run locally, e.g. Qwen, Llama or Mistral served by
[Ollama](https://ollama.com/) or [LM Studio](https://lmstudio.ai/), provided their **context window** is large
enough. The definitions of the tools alone take about 4,000 tokens, sent with every request, and every tool
result stays in the conversation: a page of ports is about 2,000 tokens.

- Use a context of **16k tokens at least, 32k recommended**. Local runtimes often start with a much smaller
  one: in Ollama, raise `num_ctx` (e.g. `PARAMETER num_ctx 32768` in a `Modelfile`, or the `options` of the
  API request); in LM Studio, raise the *Context Length* of the model.
- When the context is too small, the runtime silently drops the beginning of the conversation: the assistant
  **forgets its tools** or its instructions, calls tools that do not exist, or answers without using them.
  Increase the context, or start a new conversation.
- Keep the requests narrow: filter the port listings (`causality`, `name_pattern`) rather than paging through a
  whole FMU.

## Prompts and reference resources

The know-how travels with the server rather than with this repository, so it
reaches any MCP client — not only the ones able to read a `SKILL.md`.

Three **prompts** describe a complete procedure. They appear in the client as
slash-commands or ready-made conversations, and all their arguments are
optional:

| Prompt | Use it when the user… |
|--------|------------------------|
| `build_container` | …wants to combine, merge or package several FMUs |
| `diagnose_assembly` | …reports a container that fails to build or misbehaves |
| `inspect_fmu` | …asks what an FMU contains |

Four fixed **resources** and one templated resource carry the reference
material:

| Resource | Content |
|----------|---------|
| `guide://usage` | The recommended workflow, end to end |
| `fmi://conventions` | Causality, variability, types, units — and their traps |
| `container://options` | Every container option, derived from the tool schema |
| `assembly://current` | The current assembly, as JSON |
| `fmu://{name}/ports` | The ports of one FMU of the assembly, as JSON |

`container://options` is generated from the very model that validates
`set_container_options`, so the documented options can never drift away from
the accepted ones.

## Security

### What the assistant can do

The tools act **on your behalf**: they read `.fmu` files, and they write
`.json`, `.csv` and `.fmu` files wherever you allow them to. Two guard-rails
are always on:

- the destination extension must match the tool (`.fmu` for a container,
  `.json` for a description, `.csv` for a port dump);
- an existing file is never replaced unless the caller passes
  `overwrite=True` — which an assistant should confirm with you first.

Set `FMUCONTAINER_MCP_ROOT` (or `--root DIR`) to confine every read and write
to one directory tree. **This is the single most useful setting** when an
agent drives the server.

### Transport

| Transport | Exposure |
|-----------|----------|
| **stdio** | None. The client *is* the parent process; nothing else can connect. |
| **HTTP** | Bound to `127.0.0.1`: remote machines cannot reach it, **but every local process can**. |

The HTTP port is therefore an unauthenticated file-system capability for any
script, any other user of a shared workstation, and any web page able to issue
a request to localhost. Require a token:

```bash
# Standalone server: print a freshly generated token
fmutool-mcp --transport http --token generate

# GUI assistant: same thing, through the environment
FMUCONTAINER_MCP_TOKEN=generate fmucontainer-gui
```

The token is written to the log; configure your client to send it:

```json
{
  "servers": {
    "fmutool": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": { "Authorization": "Bearer <the-token>" }
    }
  }
}
```

A token of your own works too (`--token my-long-shared-secret`), as long as it
is at least 16 characters: a short one only provides the illusion of
protection, so it is rejected.

Without a token the server still starts — enabling the assistant must not
require ceremony — but it says clearly in the log that the port is open.

## Known limits

- **No nested containers.** The tools describe a single, flat container. Use
  the Container Builder GUI or a hand-written JSON description for a
  hierarchy.
- **No `read_assembly`.** An existing `.json` description cannot be loaded
  into the assistant; open it in the GUI instead.
- **`auto_link` links cannot be removed** one by one: they are derived when
  the container is built. Disable the option and wire explicitly.
- **Units are not converted.** Linking `m/s` to `km/h` is accepted and gives
  wrong results; the assistant is told to check, but cannot enforce it.

