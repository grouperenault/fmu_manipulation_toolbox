---
name: fmu-edit
description: Modify the interface of FMUs (.fmu files) with the FMU Manipulation Toolbox - rename ports from a mapping or a CSV file, remove ports, keep only some ports, strip or merge hierarchical prefixes (Bus.signal), restricted to a causality, a type or a variability (e.g. remove every fixed parameter, rename only the real inputs), drop the embedded sources, and check the result. Use when asked to rename, delete, filter or clean up the ports or variables of an FMU.
---

# Edit the interface of an FMU

Every operation writes a **new** FMU (`output`): the source is never modified.
It changes the FMU interface, so whatever is connected to the old names breaks:
confirm the change with the user before applying it.

## Backend

Use the first one available:

1. **MCP tools** of the `fmutool` server (their names end with
   `rename_ports`, `apply_operation`, `inspect_fmu_file`...): call them with the
   arguments shown below.
2. **`fmutool-agent`** on the command line: `fmutool-agent <tool> --args '<JSON>'`
   takes the same arguments and prints the same JSON. `fmutool-agent list-tools`
   lists the tools and their parameters.
3. Neither: install the toolbox with `pip install fmu-manipulation-toolbox`
   (add `[mcp]` for the MCP server), then use `fmutool-agent`.

## Procedure

1. **Check the source** with `check_fmu`, so that problems already there are
   not blamed on the edit.

2. **Preview** the ports the operation will touch: `inspect_fmu_file` takes the
   same filters (`causality`, `type`, `variability`) as `apply_operation`, plus
   `name_pattern` for the name. Show them to the user.

   ```bash
   fmutool-agent check_fmu --args '{"path": "model.fmu"}'
   fmutool-agent inspect_fmu_file --args '{"path": "model.fmu", "causality": ["parameter"], "variability": ["tunable"]}'
   ```

3. **Apply** one of:

   - **Rename** with a mapping; an **empty** new name **removes** the port.

     ```bash
     fmutool-agent rename_ports --args '{"fmu": "model.fmu", "output": "model-renamed.fmu", "mapping": {"h": "height", "v": "velocity"}}'
     ```

     For hundreds of ports, `dump_ports_csv` writes every port to a CSV file;
     edit its `newName` column and pass it as `csv` instead of `mapping`.

   - **Rewrite or filter by name** with `apply_operation`, restricted by the
     filters when needed:

     | `operation` | `argument` | Effect |
     |---|---|---|
     | `remove_regexp` | regular expression | Remove the ports whose name matches (from the start) |
     | `keep_only_regexp` | regular expression | Remove every other port |
     | `strip_toplevel` | — | `Bus.signal` becomes `signal` |
     | `merge_toplevel` | — | `Bus.signal` becomes `Bus_signal` |
     | `trim_until` | separator | Cut each name up to the separator |
     | `remove_sources` | — | Drop the embedded sources |

     ```bash
     fmutool-agent apply_operation --args '{"fmu": "model.fmu", "output": "model-no-tunable.fmu", "operation": "remove_regexp", "argument": ".*", "causality": ["parameter"], "variability": ["tunable"]}'
     ```

4. **Report** what the tool says: `renamed` and `removed` count the ports
   actually changed; `unknown` lists the names of the mapping that the FMU does
   not have (a typo renames nothing). Then `check_fmu` the output.

   ```bash
   fmutool-agent check_fmu --args '{"path": "model-no-tunable.fmu"}'
   ```

## When the toolbox refuses

An operation that would break the standard is refused and nothing is written:
removing every variable, removing a variable still referenced (`der(h)` is the
derivative of `h`), or creating two ports with the same name. Quote the error,
narrow the operation (stricter regular expression, filters) and try again.

Operations the tools do not offer (remoting, compilation of the sources) are
available with the `fmutool` command line: `fmutool -h`.

The filters, their values and the default variabilities:
[FMI reference](../../references/fmi-reference.md).
