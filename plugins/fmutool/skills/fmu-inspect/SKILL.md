---
name: fmu-inspect
compatibility: Requires fmu-manipulation-toolbox 2.1a1 or later (pip install "fmu-manipulation-toolbox>=2.1a1").
description: Inspect FMUs (Functional Mock-up Units, .fmu files) with the FMU Manipulation Toolbox - FMI version, generator, capabilities, ports (inputs, outputs, parameters, locals) with their type, causality, variability, unit, start value and description, one port in full (min, max, nominal, declared type, aliases, terminals), and FMI compliance checks. Also describes SSP files (.ssp): systems, FMUs, connections, values, and why a file is refused. Use when asked what an FMU or an SSP file contains, which ports or parameters it has, how a port is declared, or whether an FMU or an SSP file is valid.
---

# Inspect an FMU

Answer from what the tools return, never from what an FMU "usually" contains:
port names are case-sensitive and generator-specific.

## Backend

Use the first one available:

1. **MCP tools** of the `fmutool` server (their names end with
   `inspect_fmu_file`, `describe_port`, `check_fmu`...): call them with the
   arguments shown below.
2. **`fmutool-agent`** on the command line: `fmutool-agent <tool> --args '<JSON>'`
   takes the same arguments and prints the same JSON. `fmutool-agent list-tools`
   lists the tools and their parameters.
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

1. **Identity**: `summarize_fmu` gives the FMI version, the generator, the
   interfaces (co-simulation, model exchange), the platforms of the binaries and
   the number of ports per causality.

   ```bash
   fmutool-agent summarize_fmu --args '{"path": "model.fmu"}'
   ```

2. **Ports**: `inspect_fmu_file`, filtered on what the question is about. Filter
   rather than page: an industrial FMU has thousands of ports.

   ```bash
   fmutool-agent inspect_fmu_file --args '{"path": "model.fmu", "causality": ["parameter"]}'
   fmutool-agent inspect_fmu_file --args '{"path": "model.fmu", "type": ["Real"], "variability": ["continuous"], "name_pattern": "^v"}'
   ```

   `counts` covers the whole FMU, `total` the ports matching the filters. If
   `truncated` is true, say the list is partial and narrow the filters (or use
   `offset`).

3. **One port in full**: `describe_port` for its bounds, nominal value,
   declared type and unit, aliases and terminals.

   ```bash
   fmutool-agent describe_port --args '{"fmu": "model.fmu", "port": "h"}'
   ```

   An unknown name is reported with the closest existing names: use them, do
   not guess.

4. **Compliance**: `check_fmu`. `compliant` is true only when the schema
   validates **and** no checker reported an error. Messages of one rule are
   grouped (`count`, `examples`): quote them. If `truncated`, say the report is
   partial (full report: `fmutool -input model.fmu -check`).

   ```bash
   fmutool-agent check_fmu --args '{"path": "model.fmu"}'
   ```

5. **An SSP file**: `inspect_ssp` describes it without importing it, and writes
   nothing next to it. If `readable` is false, `reason` says why the container
   refuses it: quote it. Otherwise it gives a summary per system (FMUs, `counts`,
   exposed ports and links grouped) and the `warnings` of the reader;
   `section` (`input`, `output`, `link`, `start`, `drop`) and `node` page
   through the details.

   ```bash
   fmutool-agent inspect_ssp --args '{"path": "model.ssp"}'
   fmutool-agent inspect_ssp --args '{"path": "model.ssp", "section": "link", "limit": 20}'
   ```

## Reporting

- Give names exactly as returned, with their causality, type and unit.
- An attribute absent from a listing is not declared on the variable; the unit
  may come from the declared type (`describe_port` resolves it).
- What causality, variability and the types mean, the filters and their
  defaults: [FMI reference](../../references/fmi-reference.md).
