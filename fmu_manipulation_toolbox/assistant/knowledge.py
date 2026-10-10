"""Portable know-how shipped with the MCP server.

Everything an assistant needs in order to drive the toolbox correctly lives
here, and is exposed over MCP as **prompts** (procedures) and **resources**
(reference material). This is deliberate: a client connecting from Claude
Desktop, Cline or a home-grown agent carries no repository file with it, so
`SKILL.md` or `copilot-instructions.md` would never reach it. Prompts and
resources travel with the server.

The module only depends on the standard library, so importing the package
stays cheap and possible without the optional ``mcp`` extra.
"""

from typing import Any

# ---------------------------------------------------------------------------
# Usage guide — the single source of truth for the workflow
# ---------------------------------------------------------------------------

USAGE_GUIDE = """\
# FMU Container Builder — AI assistant guide

You help the user compose several FMUs into a single **FMU Container**.

The same tools are served by two backends. When the server was started from
the Container Builder GUI, every action is applied to the **live canvas** and
the user watches it happen; when it runs standalone (`fmutool-mcp`), the
assembly only exists in the server until you export or build it. Either way
the workflow is identical — but in the standalone case, nothing is visible to
the user before `save_as_json` or `save_as_fmu`, so describe what you do.

Recommended workflow:
1. `list_fmus` to see what is already on the canvas.
2. `inspect_fmu_file(path)` to look at a candidate file *without* adding it.
3. `add_fmu(path)` for each FMU file the user wants to combine. The answer
   already summarises the FMU (counts per causality, FMI version).
4. `list_fmu_ports(fmu)` to discover the ports of an FMU on the canvas.
5. `add_link(from_fmu, from_port, to_fmu, to_port)` to connect an OUTPUT of one
   FMU to an INPUT of another. Types should be compatible. Use `add_links`
   to create several at once.
6. `expose_input` / `expose_output` to surface ports on the container boundary
   (only needed when auto_input/auto_output are disabled or for clarity).
7. `set_start_value(fmu, port, value)` for initial values / parameters.
8. `set_container_options({...})` for step_size, mt, profiling, sequential,
   auto_link, auto_input, auto_output, auto_parameter, auto_local.
9. `get_assembly_json` to review the whole assembly before building.
10. `save_as_json(path)` to save the description, or
    `save_as_fmu(path, fmi_version=2|3, datalog=False)` to build the container.

To undo: `remove_link` drops a link, `unset_start_value` drops a start value
you set, `remove_fmu` drops an FMU and everything attached to it.

Tips:
- FMU names are the file base names (e.g. `controller.fmu`).
- Port listings are paginated. Filter with `causality=['output']` or
  `name_pattern='^engine_'` rather than paging through an industrial FMU, and
  check the `truncated` flag before concluding that a port does not exist.
- `auto_link` connects same-named/typed ports automatically at build time, so
  you often only need explicit `add_link` for ports whose names differ. Links
  it creates are derived at build time: `remove_link` cannot undo them, you
  have to disable the option.
- `add_links` applies its links in order and independently: a rejected one
  does not undo the previous ones, so always read `failed`.
- Always confirm the target output filename with the user before `save_as_fmu`.
- `save_as_fmu` is slow and reports its progress: wait for it rather than
  retrying, and never start a second build while one is running.

Known limit: **nested containers** cannot be built from here. The tools
describe a single, flat container. If the user needs a hierarchy, say so and
point them at the Container Builder GUI or a JSON description.

Reference material:
- `fmi://conventions` — what causality, variability and types mean here.
- `container://options` — every container option, with its default.
- `fmu://{name}/ports` — the ports of one FMU of the assembly.

Beyond assembling, single-FMU tools are also available. They read or rewrite
**one** `.fmu` file and never touch the assembly:
- `summarize_fmu(path)` — identity, capabilities, platforms, port counts.
- `check_fmu(path)` — FMI schema conformity and registered checkers.
- `dump_ports_csv(fmu, path)` / `rename_ports_from_csv(fmu, csv, output)` —
  bulk renaming. An **empty** new name **removes** the port.
- `apply_operation(fmu, output, operation, ...)` — prefix stripping, trimming
  and regexp filtering of port names.

These rewrite the FMU interface, so they produce a **new** file and leave the
source untouched. Warn the user that anything already connected to the old
names will break.
"""


# ---------------------------------------------------------------------------
# Reference resources
# ---------------------------------------------------------------------------

FMI_CONVENTIONS = """\
# FMI conventions, as seen through this server

## Causality — what a port may be used for
| Causality | Meaning | Usable as |
|---|---|---|
| `input` | Value provided from outside at each step | **destination** of `add_link`, `expose_input`, `set_start_value` |
| `output` | Value produced by the FMU | **source** of `add_link`, `expose_output` |
| `parameter` | Constant over the simulation, set before it starts | `set_start_value` only |
| `calculatedParameter` | Derived by the FMU from other parameters | read-only |
| `local` | Internal variable, observable but not connectable | read-only |
| `independent` | The time variable | never connect it |

A link always goes **output → input**. Linking anything else is rejected.

## Variability — when a value may change
`constant` < `fixed` < `tunable` < `discrete` < `continuous`. Only `fixed` and
`tunable` variables accept a meaningful start value from the user; writing a
start value on a `constant` is at best ignored.

## Types
FMI 2.0 uses `Real`, `Integer`, `Boolean`, `String`, `Enumeration`.
FMI 3.0 splits reals and integers by width: `Float32`/`Float64`,
`Int8`...`UInt64`, plus `Boolean`, `String`, `Binary`, `Clock`.

The container converts between numeric types when a link requires it, but the
conversion may lose precision (`Float64` → `Int32`) or meaning
(`Float64` → `Boolean`). Mention it to the user rather than silently wiring it.

## Start values
Start values are written as text into `modelDescription.xml`: booleans are
`true`/`false` (lowercase), reals use a dot as decimal separator. The
`set_start_value` tool accepts a typed value and performs the conversion.

## Units
A unit is only declarative: the toolbox does **not** convert between units.
Two ports in `m/s` and `km/h` will be linked happily and give wrong results —
check the `unit` field of `list_fmu_ports` before wiring physical quantities.

## The container itself
A container is a plain FMU, so it can be embedded into another container. It
runs the embedded FMUs with a fixed internal step (`step_size`) and exposes
only the ports you chose to expose.
"""


def container_options_reference(options: list[dict[str, Any]]) -> str:
    """Render the container options as a Markdown reference table.

    The table is built from the schema of the option model itself, so it
    cannot drift away from what the tool actually accepts.

    Args:
        options: One mapping per option, with ``name``, ``type``,
            ``description`` keys.
    """
    lines = [
        "# Container options",
        "",
        "Passed to `set_container_options`. Only the options you provide are",
        "changed; the others keep their current value.",
        "",
        "| Option | Type | Meaning |",
        "|---|---|---|",
    ]
    for option in options:
        description = " ".join(str(option.get("description", "")).split())
        lines.append(f"| `{option['name']}` | {option.get('type', '')} | {description} |")
    lines += [
        "",
        "## Defaults worth knowing",
        "- `auto_link`, `auto_input` and `auto_output` are **enabled**: ports",
        "  sharing a name and a type are wired together, and whatever stays",
        "  unconnected is surfaced on the container boundary. Most assemblies",
        "  therefore need very few explicit calls.",
        "- `step_size` is derived from the embedded FMUs when left unset.",
        "  Never invent a value: a step that is too large silently degrades the",
        "  results.",
        "- `mt` and `sequential` describe opposite intents; setting both is a",
        "  sign that the user's request was misunderstood.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts — procedures the user can invoke explicitly
# ---------------------------------------------------------------------------

def build_container_prompt(fmus: str | None = None,
                           output: str | None = None) -> str:
    """Procedure for assembling FMUs into a container."""
    target = f"\nFMUs to combine: {fmus}." if fmus else ""
    destination = f"\nRequested output file: {output}." if output else ""
    return f"""\
Assemble several FMUs into a single FMU Container, using the `fmutool`
tools. If the server is backed by the Container Builder GUI, the canvas is
live and every action is immediately visible to the user; if it runs
standalone, the assembly only materialises when you export or build it.
{target}{destination}

Follow this procedure:

1. **Inventory** — call `list_fmus`. Never assume the canvas is empty.
2. **Add** — `add_fmu(path)` per file. Afterwards, FMUs are designated by their
   **base name** (`controller.fmu`), not by their path. If two different files
   share the same base name, stop and ask the user to rename one.
3. **Introspect** — `list_fmu_ports(fmu)` before wiring anything. Filter with
   `causality=['output']` or `name_pattern` on large FMUs, and never guess a
   port name.
4. **Route** — `auto_link` is on by default and already connects ports sharing
   a name and a type. Only call `add_link` for ports whose names differ.
   Connect an OUTPUT to an INPUT. Flag lossy conversions and mismatched units
   (see `fmi://conventions`) instead of wiring them silently.
5. **Boundary** — rely on `auto_input`/`auto_output` unless the user asked for
   a specific container interface; then use `expose_input`/`expose_output`.
6. **Initial values** — `set_start_value(fmu, port, value)` for parameters and
   initial conditions the user mentioned.
7. **Options** — `set_container_options`. See `container://options`. Leave
   `step_size` unset unless the user gave one.
8. **Review** — `get_assembly_json`, then summarise for the user: FMUs, links,
   exposed ports, options. **Stop here and ask for confirmation.**
9. **Build** — `save_as_fmu(path, fmi_version=2|3)` once confirmed. The call
   refuses to overwrite an existing file unless `overwrite=True`, so confirm
   the destination rather than forcing it.
10. **Report** — restate the output path and the options actually used.

Red flags to raise rather than resolve on your own:
- an embedded input that is neither linked nor exposed keeps its start value;
- a port the user names but that is absent from `list_fmu_ports`;
- a real-to-boolean link, or two linked ports with different units.
"""


def diagnose_assembly_prompt(symptom: str | None = None) -> str:
    """Procedure for investigating an assembly that does not behave."""
    reported = f"\nReported symptom: {symptom}." if symptom else ""
    return f"""\
Diagnose an FMU Container assembly that fails to build or behaves unexpectedly.
{reported}

Investigate in this order, reporting findings as you go:

1. `get_assembly_json` — the whole picture: FMUs, links, exposed ports,
   options. Note that FMUs appear here by *path*, whereas the tools use names.
2. `list_fmus` — confirm every FMU the user mentions is actually loaded.
3. For each FMU involved, `list_fmu_ports(fmu)` and check:
   - every link source is an `output` and every destination an `input`;
   - linked ports have compatible types (`fmi://conventions`);
   - linked ports share the same unit — the toolbox does **not** convert;
   - no input is left both unlinked and unexposed, unless its start value is
     intentional.
4. Review the options against `container://options`. The usual suspects are a
   hand-picked `step_size`, `auto_link` disabled while links are missing, and
   `mt` combined with `sequential`.
5. Only then propose a fix, one change at a time, and explain what it should
   change in the user's observations.

Do not rebuild the container without asking: `save_as_fmu` writes to disk.
If a tool reports an error, quote it verbatim — the messages are actionable.
"""


def inspect_fmu_prompt(fmu: str | None = None) -> str:
    """Procedure for producing the identity card of an FMU."""
    subject = f"\nFMU to inspect: {fmu}." if fmu else ""
    return f"""\
Produce a readable identity card for an FMU.
{subject}

1. If you were given a **path**, use `inspect_fmu_file(path)`: it does not
   touch the assembly. If you were given the **name** of an FMU already on the
   canvas, use `list_fmu_ports(fmu)`.
2. Start with the summary fields: `fmi_version`, `kinds` (CoSimulation and/or
   ModelExchange), `generator`, and `counts` — the number of ports per
   causality, over the whole FMU. `summarize_fmu(path)` adds the platforms,
   the embedded resources and the MD5 sum; `check_fmu(path)` tells whether
   the FMU conforms to the FMI standard (schema and semantic rules).
3. Then describe the interface, causality by causality, using filtered calls
   (`causality=['input']`, then `['output']`, then `['parameter']`) rather than
   dumping everything. Keep `local` variables for last, and only if relevant.
4. For every port worth mentioning, give its name, type, unit and description.
   Flag ports with no description or no unit: they are the ones most likely to
   be mis-wired.
5. Watch the `truncated` flag: if it is true, say so explicitly instead of
   presenting a partial list as complete.
6. Conclude with what the FMU is plausibly for, and what a caller must provide
   to use it — but make clear what is read from the model description and what
   is your interpretation.
"""

