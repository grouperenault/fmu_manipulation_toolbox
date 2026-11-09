---
name: fmu-container
compatibility: Requires fmu-manipulation-toolbox 2.1a1 or later (pip install "fmu-manipulation-toolbox>=2.1a1").
description: Assemble several FMUs (.fmu files) into one FMU container with the FMU Manipulation Toolbox - add FMUs, connect outputs to inputs, expose ports on the container interface, set start values and parameters, choose the container options (step size, multithreading, auto-linking), review and lint the assembly, then build the container FMU (FMI 2.0 or 3.0) or save its description as JSON or SSP. Also loads an existing JSON, CSV or SSP assembly file to edit it. Use when asked to combine, couple, wire or co-simulate FMUs together, to build an FMU container, or to edit or convert an assembly or an SSP file.
---

# Build an FMU container

A container is an FMU that runs several embedded FMUs with a fixed internal
step, wired together. Build it step by step, checking each result: never guess
a port name, and confirm the output path with the user before building.

## Backend

Use the first one available:

1. **MCP tools** of the `fmutool` server (their names end with `add_fmu`,
   `add_links`, `save_as_fmu`...): call them with the arguments shown below. The
   server keeps the assembly in memory; `list_fmus` shows what is already there.
2. **`fmutool-agent`** on the command line: `fmutool-agent <tool> --args '<JSON>'`
   takes the same arguments and prints the same JSON. The assembly lives in the
   file given by `--state`, created by the first call: pass the same file to
   every call of one assembly, and a new file for a new assembly.
3. Neither: install the toolbox with
   `pip install "fmu-manipulation-toolbox>=2.1a1"`
   (`"fmu-manipulation-toolbox[mcp]>=2.1a1"` for the MCP server), then use
   `fmutool-agent`.

**Too old?** This skill needs fmu-manipulation-toolbox **2.1a1 or later**.
When the MCP server has no `save_assembly` tool, or `fmutool-agent` is missing
or does not list `save_assembly`, the installed toolbox is older: say so (with
the `version` printed by `fmutool-agent list-tools`, if any) and upgrade it with
`pip install --upgrade "fmu-manipulation-toolbox>=2.1a1"`.

## Procedure

1. **Add** each FMU. The returned `fmu` is the name to use afterwards; adding a
   file again adds another instance, named `<stem>-<n>.fmu`.

   ```bash
   fmutool-agent add_fmu --state assembly.json --args '{"path": "bb_position.fmu"}'
   fmutool-agent add_fmu --state assembly.json --args '{"path": "bb_velocity.fmu"}'
   ```

2. **Read the ports** of each FMU, inputs and outputs first. `describe_port`
   gives the unit of a port when the listing does not.

   ```bash
   fmutool-agent list_fmu_ports --state assembly.json --args '{"fmu": "bb_position.fmu", "causality": ["input", "output"]}'
   ```

3. **Link** outputs to inputs. `auto_link` (on by default) already connects
   ports with the same name and type: link the others. A link goes from an
   `output` to an `input`; numeric conversions may lose precision and units are
   never converted, so tell the user about such links. `add_links` applies the
   links one by one: read `failed` before saying the wiring is done.

   ```bash
   fmutool-agent add_links --state assembly.json --args '{"links": [{"from_fmu": "bb_velocity.fmu", "from_port": "velocity", "to_fmu": "bb_position.fmu", "to_port": "velocity"}]}'
   ```

4. **Interface and values**. Unconnected inputs and outputs are exposed
   automatically (`auto_input`, `auto_output`); `expose_input` and
   `expose_output` are for a container interface chosen by the user.
   `set_start_value` takes a typed value (`0.01`, `3`, `true`, `"text"`).
   Leave `step_size` unset unless the user gives one: the toolbox derives it from
   the embedded FMUs.

   ```bash
   fmutool-agent set_start_value --state assembly.json --args '{"fmu": "bb_velocity.fmu", "port": "reset", "value": false}'
   fmutool-agent set_container_options --state assembly.json --args '{"options": {"mt": true}}'
   ```

5. **Review**: `analyze_assembly` with `mode` `summary` (structure, grouped
   ports and links) and `lint` (known traps, checked by the container builder:
   quote its findings); `get_assembly_json` for the details.

   ```bash
   fmutool-agent analyze_assembly --state assembly.json --args '{"mode": "lint"}'
   ```

6. **Build** once the user confirmed the path: `save_as_fmu`, with
   `fmi_version` 2 or 3 for the interface of the container (an FMI 2 container
   cannot expose the FMI 3 ports that have no FMI 2 type: prefer 3 when it
   embeds FMI 3 FMUs, and report the ports the build log says it could not
   expose), `datalog` to record the exchanged values. `save_assembly` writes the
   description only, in the format of the extension of its path: `.json`, or
   `.ssp` with the FMUs embedded and the routing resolved (`ssp_version` `2.0`
   by default, or `1.0`).

   ```bash
   fmutool-agent save_assembly --state assembly.json --args '{"path": "container.json"}'
   fmutool-agent save_assembly --state assembly.json --args '{"path": "container.ssp"}'
   fmutool-agent save_as_fmu --state assembly.json --args '{"path": "container.fmu", "fmi_version": 3}'
   ```

## From an existing file

`import_assembly` loads a `.json`, `.csv` or `.ssp` file, to edit it with the
tools above and save it again, in the same format or another one. It replaces
the assembly: on a non-empty one it is refused until called with
`"replace": true`, so ask the user first. Report its `warnings`: what the file
holds and the container ignores (a component without source, for instance).

```bash
fmutool-agent import_assembly --state assembly.json --args '{"path": "container.ssp", "replace": true}'
```

An FMU of an SSP file is extracted next to it, in `<file>.dir`. To look at an
SSP file without importing it: `inspect_ssp` (see the skill `fmu-inspect`).

## Limits

- One flat container: nested containers are built from a JSON description with
  the `fmucontainer` command line or the Container Builder GUI. Without the GUI,
  `import_assembly` refuses a file with sub-containers.
- Removing an FMU (`remove_fmu`) also removes its links: say how many
  (`removed_links`).

Causality, variability, types and units in an assembly:
[FMI reference](../../references/fmi-reference.md).
