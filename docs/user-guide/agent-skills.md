---
title: Agent Skills
description: Skills and a JSON command line that let AI agents inspect FMUs, edit their interface and build FMU containers
---

# Agent skills

The toolbox gives AI agents three **skills** — instructions an agent loads when
a request calls for them — together with the tools they rely on:

| Skill | What the agent can do |
|-------|-----------------------|
| `fmu-inspect` | Tell what an FMU contains: FMI version, generator, capabilities, ports with their type, causality, variability, unit, start value and description; one port in full (bounds, nominal value, declared type, aliases, terminals); FMI compliance |
| `fmu-edit` | Rename ports (from a mapping or a CSV file), remove them, keep only some, strip or merge `Bus.` prefixes — restricted to a causality, a type or a variability — and check the result |
| `fmu-container` | Assemble FMUs into an FMU container: add them, link outputs to inputs, expose ports, set start values and options, review and lint the assembly, build the container |

The skills drive the same tools as the [AI assistant](fmucontainer/ai-assistant.md), through the first backend
available:

1. the **MCP server** `fmutool-mcp`, when the agent has an MCP client;
2. otherwise the **`fmutool-agent`** command line, which offers the same tools, with the same arguments and the
   same JSON results, to an agent that can only run commands.

## Requirements

The skills need **fmu-manipulation-toolbox 2.1a1 or later**:

```bash
pip install "fmu-manipulation-toolbox[mcp]>=2.1a1"   # MCP server and fmutool-agent
pip install "fmu-manipulation-toolbox>=2.1a1"        # fmutool-agent only
```

The constraint names a pre-release, so `pip` accepts the development releases; any later release satisfies it.
Each skill declares the version in the `compatibility` field of its frontmatter, and checks the installed toolbox
by its tools rather than by its number: without the `describe_port` tool, or without `fmutool-agent`, it asks for
an upgrade. `fmutool-agent list-tools` prints the installed `version`.

`fmutool-agent` needs neither `fastmcp` nor Pydantic: the base installation is enough. Building a container
needs the container runtime of the platform, shipped in the wheels.

## Claude Code

The repository is a plugin marketplace. In Claude Code:

```
/plugin marketplace add grouperenault/fmutool
/plugin install fmutool@fmutool
```

(With Claude Code 2.1.275 or later, `/plugin install fmutool --marketplace grouperenault/fmutool` does both.)

The plugin brings the three skills and declares the MCP server: `fmutool-mcp` must be on the `PATH` of Claude
Code, e.g. installed in the active virtual environment. When it is not, the skills fall back on `fmutool-agent`,
or explain how to install the toolbox.

## claude.ai and the Claude API

A skill uploaded to claude.ai (*Settings > Capabilities > Skills*) or to the Claude API runs in a sandbox
without MCP server: it uses `fmutool-agent`, after installing the toolbox with `pip` (the sandbox needs network
access for that; the skills ask for `>=2.1a1`). Build one `.zip` per skill from a clone of the repository:

```bash
python tools/build_skill_zips.py          # writes dist/skills/fmu-inspect.zip, fmu-edit.zip, fmu-container.zip
```

Each `.zip` holds one skill and a copy of the FMI reference it links to.

## `fmutool-agent`

```
fmutool-agent TOOL [--args JSON] [--state FILE] [--root DIR] [--name NAME] [--debug]
fmutool-agent list-tools
```

- `TOOL` is one of the tools of the [AI assistant](fmucontainer/ai-assistant.md#available-tools);
  `list-tools` prints them all, with their parameters, types and defaults, and the `version` of the toolbox.
- `--args` gives the arguments as a JSON object (`-` reads it from stdin), exactly as an MCP client would.
- `--state FILE` keeps the assembly between calls, each call being a separate process. The assembly tools
  (`add_fmu`, `add_links`, `save_as_fmu`...) require it; the first call creates the file. Use one file per
  assembly. `describe_port` also takes it, to designate an FMU of the assembly by its name.
- `--root DIR` confines the files read and written to a directory tree, as for `fmutool-mcp`
  (`FMUCONTAINER_MCP_ROOT` does the same).

The result is printed on **stdout** as JSON: an object as is, any other value as `{"result": ...}`. The logs go to
stderr. A failure prints `{"error": "..."}` and exits with code 2 for wrong arguments, 1 for a tool error; the state
is only written after a change that succeeded.

```bash
fmutool-agent inspect_fmu_file --args '{"path": "model.fmu", "causality": ["parameter"], "variability": ["tunable"]}'
fmutool-agent describe_port --args '{"fmu": "model.fmu", "port": "h"}'
fmutool-agent rename_ports --args '{"fmu": "model.fmu", "output": "model-renamed.fmu", "mapping": {"h": "height"}}'

fmutool-agent add_fmu --state assembly.json --args '{"path": "bb_position.fmu"}'
fmutool-agent add_fmu --state assembly.json --args '{"path": "bb_velocity.fmu"}'
fmutool-agent analyze_assembly --state assembly.json --args '{"mode": "lint"}'
fmutool-agent save_as_fmu --state assembly.json --args '{"path": "container.fmu", "fmi_version": 3}'
```

## Limits

The limits of the [AI assistant](fmucontainer/ai-assistant.md#known-limits) apply: one flat container, no
conversion of units, `auto_link` links not removable one by one. In addition, the port listings show the unit
declared on a variable only; a unit inherited from a declared type is given by `describe_port`.
