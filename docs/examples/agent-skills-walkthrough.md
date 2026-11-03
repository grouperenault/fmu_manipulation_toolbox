---
title: Using the Agent Skills, Step by Step
description: Walkthrough of an AI agent session with the skills of the toolbox - inspect an FMU, edit its interface, build an FMU container
---

# Using the agent skills, step by step

This walkthrough follows a session with an AI agent equipped with the
[agent skills](../user-guide/agent-skills.md) of the toolbox. The agent:

1. inspects an FMU,
2. edits its interface,
3. assembles two FMUs into an FMU container.

It uses **Claude Code** with the `fmutool` plugin; the
[last sections](#without-the-mcp-server) show the same session without MCP server, on claude.ai and with other
agents. The FMUs are those of the test suite of the toolbox (`tests/data`), and the results shown are the real
ones, shortened.

You write the requests in plain language: the agent picks the skill whose description matches, follows its
procedure and calls the tools. You never have to name a tool.

## Step 1 — Install the toolbox

In a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install "fmu-manipulation-toolbox[mcp]>=2.1a1"   # the version the skills need
fmutool-mcp --help                   # the MCP server the plugin starts
fmutool-agent list-tools             # the same tools, as a command line
```

`fmutool-mcp` must be on the `PATH` of Claude Code: start Claude Code from this activated environment.

## Step 2 — Install the plugin

In Claude Code:

```
/plugin marketplace add grouperenault/fmutool
/plugin install fmutool@fmutool
```

Restart Claude Code, then check:

- `/plugin` lists `fmutool` as installed: it brings the skills `fmu-inspect`, `fmu-edit` and `fmu-container`;
- `/mcp` shows the server `fmutool` as **connected**. If it failed, `fmutool-mcp` is not on the `PATH`: the
  skills then fall back on `fmutool-agent` (see [Without the MCP server](#without-the-mcp-server)).

## Step 3 — Prepare a working directory

Put the FMUs in a directory and start Claude Code there:

```
work/
├── bouncing_ball.fmu     # tests/data/compile/3.0/BouncingBall.fmu
├── bb_position.fmu       # tests/data/fmi3/bouncing_ball/bb_position.fmu
└── bb_velocity.fmu       # tests/data/fmi3/bouncing_ball/bb_velocity.fmu
```

```bash
cd work
export FMUCONTAINER_MCP_ROOT="$PWD"  # optional: confine the server to this directory
claude
```

With `FMUCONTAINER_MCP_ROOT`, the server refuses to read or write outside `work/`.

## Step 4 — Inspect an FMU

!!! example "Request"

    What is in `bouncing_ball.fmu`? Which parameters can I tune, and what is the unit of the position?

The agent loads **`fmu-inspect`** and follows its procedure:

1. `summarize_fmu` — identity and port counts:

    ```json
    {"fmu": "bouncing_ball.fmu", "fmi_version": 3, "counts": {"independent": 1, "output": 2, "local": 3, "parameter": 2}, ...}
    ```

2. `inspect_fmu_file`, **filtered** on the parameters rather than listing everything:

    ```json
    {"path": "bouncing_ball.fmu", "causality": ["parameter"]}
    ```

    ```json
    {"total": 2, "truncated": false, "ports": [
      {"name": "g", "type": "Float64", "causality": "parameter", "variability": "fixed", "start": "-9.81", "description": "Gravity acting on the ball"},
      {"name": "e", "type": "Float64", "causality": "parameter", "variability": "tunable", "start": "0.7", "description": "Coefficient of restitution"}]}
    ```

3. `describe_port` on `h`: the listing gives no unit, because it is declared by the type of the port, not by the
   port itself.

    ```json
    {"name": "h", "type": "Float64", "causality": "output",
     "declared_type": {"name": "Position", "attributes": {"quantity": "Position", "unit": "m"}, "inherited": {"quantity": "Position", "unit": "m"}},
     "aliases": [{"name": "h_ft", "description": "Position in feet", "displayUnit": "ft"}]}
    ```

!!! quote "Answer (excerpt)"

    `bouncing_ball.fmu` is an FMI 3.0 FMU (Reference FMUs), for co-simulation and model exchange. It has two
    parameters: `g` (gravity, −9.81, `fixed`: it cannot change during the simulation) and `e` (coefficient of
    restitution, 0.7, `tunable`). The position `h` is in metres, through its declared type `Position`; it also
    has an alias `h_ft`, in feet.

Follow-up requests work the same way: *"is it compliant?"* calls `check_fmu`, which answers `compliant: true` only
when the schema validates **and** no checker reports an error.

## Step 5 — Edit its interface

!!! example "Request"

    Make a copy of `bouncing_ball.fmu` where `h` is called `height` and `v` is called `velocity`.

The agent loads **`fmu-edit`**. Its rules: the source is never modified, the result is a new FMU, and the change
of interface is **confirmed with you** first:

> I will write `bouncing_ball-renamed.fmu`, renaming `h` → `height` and `v` → `velocity`. Anything connected to
> the old names will no longer be. Shall I proceed?

Once you agree, it calls `rename_ports`:

```json
{"fmu": "bouncing_ball.fmu", "output": "bouncing_ball-renamed.fmu", "mapping": {"h": "height", "v": "velocity"}}
```

and reports from the result: `renamed: 2, removed: 0`. Had a name been mistyped, the result would say so —
`"unknown": ["hh"]` — rather than silently renaming nothing. It finally checks the output with `check_fmu`.

!!! example "Request"

    Now remove the tunable parameters.

The agent previews the ports concerned with `inspect_fmu_file` and the **same filters** as the operation
(`causality: ["parameter"]`, `variability: ["tunable"]`: only `e`), confirms, then:

```json
{"fmu": "bouncing_ball.fmu", "output": "bb-no-tunable.fmu", "operation": "remove_regexp", "argument": ".*",
 "causality": ["parameter"], "variability": ["tunable"]}
```

!!! example "Request"

    And remove `h`.

The toolbox refuses, and the agent explains why instead of forcing it:

```json
{"error": "The operation would remove variables that are still referenced: 'h' is referenced by 'der(h)' (derivative)"}
```

> `h` cannot be removed: it is a state of the model, and its derivative `der(h)` refers to it. Nothing was
> written.

## Step 6 — Build an FMU container

!!! example "Request"

    Couple `bb_position.fmu` and `bb_velocity.fmu` in an FMI 3.0 container, `bouncing.fmu`. The ball must
    bounce when it touches the ground.

The agent loads **`fmu-container`**:

1. `add_fmu` for each FMU; the result gives the name to use afterwards (`bb_position.fmu`, `bb_velocity.fmu`).

2. `list_fmu_ports` on both, inputs and outputs only:

    | FMU | Inputs | Outputs |
    |---|---|---|
    | `bb_position.fmu` | `velocity` (Float64) | `is_ground` (Boolean), `position1` (Float64) |
    | `bb_velocity.fmu` | `reset` (Boolean) | `velocity` (Float64) |

3. Links: `velocity` → `velocity` has the same name and type on both sides, so `auto_link` (on by default)
   connects it. The bounce needs `is_ground` → `reset`, linked with `add_links`. The skill tells the agent to read
   `failed`: had it guessed a port name, the link would have been rejected, and said so:

    ```json
    {"created": ["bb_position.fmu/is_ground -> bb_velocity.fmu/reset"],
     "failed": [{"link": "bb_position.fmu/position -> bb_velocity.fmu/reset",
                 "reason": "'position' is not a port of 'bb_position.fmu'."}]}
    ```

4. Review: `analyze_assembly` in `summary` mode (FMUs, links, exposed ports), then in `lint` mode
   (`"findings": []`: nothing to report).

5. Build, once you confirmed the path: `save_as_fmu` with `{"path": "bouncing.fmu", "fmi_version": 3}`. FMI 3.0
   is the right choice here: an FMI 2.0 container could not expose the `Boolean` ports of FMI 3.0 FMUs.

!!! quote "Answer (excerpt)"

    `bouncing.fmu` is built (FMI 3.0). `velocity` is linked automatically; I linked `is_ground` → `reset` so
    that the velocity is reset when the ball touches the ground. The unconnected output `position1` is exposed
    by the container.

To keep the description of the assembly, ask for it: `save_as_json` writes the
[JSON description](../user-guide/fmucontainer/container.md#json-input-file), which `fmucontainer` builds again.

## Without the MCP server

When the server is not connected (no MCP client, `fmutool-mcp` not on the `PATH`), the skills tell the agent to
run `fmutool-agent`, which takes the same arguments as JSON and prints the same results. The session above
becomes a series of commands the agent runs in a terminal:

```bash
fmutool-agent summarize_fmu --args '{"path": "bouncing_ball.fmu"}'
fmutool-agent inspect_fmu_file --args '{"path": "bouncing_ball.fmu", "causality": ["parameter"]}'
fmutool-agent rename_ports --args '{"fmu": "bouncing_ball.fmu", "output": "bouncing_ball-renamed.fmu", "mapping": {"h": "height", "v": "velocity"}}'

fmutool-agent add_fmu --state assembly.json --args '{"path": "bb_position.fmu"}'
fmutool-agent add_fmu --state assembly.json --args '{"path": "bb_velocity.fmu"}'
fmutool-agent add_links --state assembly.json --args '{"links": [{"from_fmu": "bb_position.fmu", "from_port": "is_ground", "to_fmu": "bb_velocity.fmu", "to_port": "reset"}]}'
fmutool-agent analyze_assembly --state assembly.json --args '{"mode": "lint"}'
fmutool-agent save_as_fmu --state assembly.json --args '{"path": "bouncing.fmu", "fmi_version": 3}'
```

Each call is a separate process: the assembly lives in the file given by `--state`, created by the first call.
One file per assembly; delete it to start over.

## On claude.ai

1. From a clone of the repository, build the skills: `python tools/build_skill_zips.py` writes
   `dist/skills/fmu-inspect.zip`, `fmu-edit.zip` and `fmu-container.zip`.
2. Upload them in *Settings > Capabilities > Skills* (code execution must be enabled).
3. In a conversation, attach the FMUs and write the same requests as above.

The agent runs in a sandbox without MCP server: following the skills, it installs the toolbox
(`pip install "fmu-manipulation-toolbox>=2.1a1"`, which needs network access from the sandbox) and uses `fmutool-agent`.
It gives back the FMUs it wrote as files to download.

## With other agents

Any agent able to read files and run commands can use the skills: they are Markdown files
(`plugins/fmutool/skills/*/SKILL.md`, and the shared `plugins/fmutool/references/fmi-reference.md`). Point the
agent at them in its instructions, for example in an `AGENTS.md` file:

```markdown
For any request about FMUs (.fmu files), first read the matching skill and follow it:
- inspect an FMU: plugins/fmutool/skills/fmu-inspect/SKILL.md
- rename, remove or filter ports: plugins/fmutool/skills/fmu-edit/SKILL.md
- build an FMU container: plugins/fmutool/skills/fmu-container/SKILL.md
```

An agent with an MCP client can also be given the server directly (`fmutool-mcp`, see
[Connecting a client that launches the server](../user-guide/fmucontainer/ai-assistant.md#connecting-a-client-that-launches-the-server));
the skills then add the procedures on top of the tools.

## Tips

- **Name the files, describe the goal.** *"Couple these two FMUs so that the ball bounces"* is enough: the agent
  reads the ports itself. Do not dictate port names you are not sure of; the agent checks them anyway.
- **Expect confirmations.** Renaming, removing ports, removing an FMU from the assembly and writing the container
  are confirmed before they happen: it is part of the skills.
- **Ask for the evidence.** *"Show me the ports you are going to remove"*, *"what did the lint say?"*: the
  agent quotes the results of the tools.
- **Large FMUs.** On an FMU with thousands of ports, ask with filters in mind (*"the real inputs of the engine
  subsystem"*): the agent narrows its listings (`causality`, `type`, `variability`, `name_pattern`) instead of
  paging through everything.
- **What the skills cannot do.** Nested containers (use a JSON description and `fmucontainer`), unit conversions
  (units are only checked, never converted), remoting and compilation of the sources (`fmutool -h`).
