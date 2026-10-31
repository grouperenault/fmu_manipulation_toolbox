# Plan: agent skills for the FMU Manipulation Toolbox

**Created**: 31 October 2026 — **Status**: decisions taken, not started

Give AI agents a reliable way to (1) introspect FMUs, (2) operate on them (checks, renaming, removal of ports by
type, name, variability...) and (3) build FMU containers. The capability already largely exists as the MCP server
(`fmu_manipulation_toolbox/assistant/`, `fmutool-mcp`); what is missing is the *know-how* (which tool, in which
order, how to read the results, FMI rules) and a path for agents that have no MCP server (claude.ai, Claude API /
Agent SDK sandboxes). This plan adds:

- a few API additions (filters by type and variability, direct renaming, extended introspection);
- `fmutool-agent`, a JSON command line strictly aligned on the MCP tools;
- a Claude Code plugin, shipped in this repository, with three skills that use the MCP tools when available and
  `fmutool-agent` otherwise.

---

## 1. Current state

### Coverage of the three needs (31 October 2026)

| Need | Covered by | Gap |
|---|---|---|
| Introspection | `inspect_fmu_file`, `list_fmu_ports` (name, type, causality, variability, unit, start, truncated description; filters `causality`, `name_pattern`; pagination), `summarize_fmu` | min/max, nominal, FMI 3 attributes (dimensions, clocks...), `ModelStructure` dependencies |
| Operations | `check_fmu`, `dump_ports_csv`, `rename_ports_from_csv`, `apply_operation` (`strip_toplevel`, `merge_toplevel`, `trim_until`, `remove_regexp`, `keep_only_regexp`, `remove_sources`) | Scope restricted by **causality only** (`apply_on`); no filter by type or variability; renaming requires a CSV file |
| Containers | `add_fmu`, `add_link(s)`, `expose_input/output`, `set_start_value`, `set_container_options`, `analyze_assembly`, `save_as_json`, `save_as_fmu` (headless bridge) | None for the MCP; nothing without an MCP server |
| Know-how | Server instructions and resources (`guide://usage`, `fmi://conventions`, `container://options`) | Not usable without the MCP server; no workflow guidance (e.g. "prepare an FMU before putting it in a container") |

### Findings

| # | Finding | Location |
|---|---|---|
| F1 | The tool definitions measure **16 848 characters for a budget of 17 000** (`python tests/_helpers/mcp_budget.py`): any new parameter or tool breaks `test_assistant_budget.py` | `tests/_helpers/mcp_budget.py`, `assistant/server.py` |
| F2 | `FMU.apply_operation(operation, apply_on)` and `Manipulation.manipulate` filter by causality only; the CLI exposes it as `-only-parameters/-inputs/-outputs/-locals` | `operations.py`, `cli/fmutool.py` |
| F3 | `OperationRenameFromCSV` is the only renaming operation; the MCP tool `rename_ports_from_csv` needs a CSV file on disk | `operations.py`, `assistant/fmutools.py` |
| F4 | `Port` (MCP model) holds 7 fields; the default port page costs ~7.9k characters on the 5000-variable FMU | `assistant/models.py` |
| F5 | `HeadlessAssemblyBridge` keeps the assembly in memory only: it can export JSON (`save_as_json`) but not reload it, although `Assembly.read_json` exists | `assistant/headless.py`, `assembly.py` |
| F6 | `uv` is not assumed to be installed on users' machines | — |

---

## 2. Goals

1. An agent can introspect, edit and containerize FMUs with or without an MCP server, with the **same** operations
   and the **same** JSON results either way.
2. Ports can be selected by causality, type, variability and name, in the Python API, the MCP tools and the CLI.
3. The MCP budgets of `mcp_optimize` stay enforced (definitions budget raised at most to ~18 000 characters).
4. Skills installable in Claude Code with `/plugin marketplace add grouperenault/fmutool`, and as `.zip` uploads for
   claude.ai.

---

## 3. Decisions

Decided on 31 October 2026.

| # | Question | Decision |
|---|---|---|
| D1 | Environments | **Both**: skills use the MCP tools when the `fmutool` server is connected, `fmutool-agent` otherwise |
| D2 | Location | **Claude Code plugin in this repository** |
| D3 | API additions in scope | **Filters by type/variability, direct renaming, extended introspection** |
| D4 | Definitions budget (F1) | **Compact first, then raise slightly**: shorten existing descriptions, share one filter object between tools; raise `DEFINITIONS_BUDGET` to ~18 000 only if still needed |
| D5 | Extended introspection | **New tool `describe_port(fmu, port)`**: every attribute of one port, bounded cost; port pages unchanged |
| D6 | Type/variability filters | **API + MCP + CLI**: `FMU.apply_operation` gains type and variability filters (`apply_on` kept compatible), so does the MCP tool, and `fmutool` gains `-only-type` / `-only-variability` |
| D7 | Direct renaming | **Extend into a single `rename_ports`** tool accepting either a mapping or a CSV; replaces `rename_ports_from_csv` (breaking for the MCP tool name, documented in `CHANGELOG.md`) |
| D8 | Fallback without MCP | **JSON CLI aligned on the MCP**: `fmutool-agent <tool> --args '<json>'`, same functions and same JSON results; assembly state kept in a JSON file |
| D9 | MCP launch from the plugin | **`fmutool-mcp` on the `PATH`** (`pip install fmu-manipulation-toolbox[mcp]`); the skills detect its absence and tell how to install it |
| D10 | Skills split | **Three skills + shared reference**: `fmu-inspect`, `fmu-edit`, `fmu-container`, and a shared FMI reference |
| D11 | Plugin layout and distribution | **Marketplace in the repository**: `.claude-plugin/marketplace.json` at the root, plugin in `plugins/fmutool/`, a `tools/` script building the claude.ai `.zip` files |

### Decided during the work

| # | Question | Decision |
|---|---|---|
| Q1 | Shape of the port filters; type names | **Flat parameters** `causality`, `type`, `variability`, `name_pattern` side by side (shared `Annotated` types); Python API `FMU.apply_operation(operation, apply_on=None, *, types=None, variabilities=None)`. **Native names plus FMI 2 families**: the exact name of the FMU (`Real`, `Float64`, `Int32`...) selects that type; on an FMI 3 FMU an FMI 2 name selects its family (`Real` = `Float32`/`Float64`, `Integer` = `Int8`...`UInt64`) (31 October 2026) |
| Q3 | `fmutool-agent` state file | **Explicit `--state FILE`**, required by the assembly tools (refused otherwise), created by the first call; the single-FMU tools need none (31 October 2026) |
| Q3b | How `fmutool-agent` reuses the tools | **Direct calls, without `fastmcp`**; and since Pydantic only comes with the `mcp` extra: **plain Python, shared logic**: the work of each tool moves to `assistant/tools.py` (`Toolbox`), called by the MCP server and by the command line; the command line checks its arguments against the signatures of `Toolbox`; a contract test checks tools, parameters and results against the server (31 October 2026) |
| Q4 | Source of the skills | **The plugin is the single source**: `tools/build_skill_zips.py` builds the claude.ai `.zip` from it (into `dist/skills/`, not tracked), copying the shared reference into each (31 October 2026) |
| Q5 | Evaluation of the skills | **Deterministic tests** in the pytest suite: manifests, frontmatter, links, tools named, `fmutool-agent` examples run on `tests/data`; no model, no API key (31 October 2026) |
| Q2 | Content of `describe_port` | Every declared attribute and the FMI 3 dimensions, plus the **resolved declared type** (inherited attributes and their origin, enumeration items), the **aliases** (FMI 3 `<Alias>`; FMI 2 variables sharing the value reference and the type) and the **terminals** the port belongs to, with its member name. Not the `ModelStructure` role (31 October 2026) |

---

## 4. Plan

### Phase 0 — Safety net

1. Record the current budget report in this plan (F1).
2. Tests pinning the current behaviour of `apply_on` (causality only), `rename_ports_from_csv` and the port page,
   so that phases 1 and 2 can prove compatibility.

*Exit criterion*: suite green; baseline recorded.

*Commit*: `Tests pinning the scope of the operations (causality), the renaming from CSV and the port page, before the agent skills`

**Status on 31 October 2026: done.**

| Item | File |
|---|---|
| Scope of the operations on hand-built FMI 2 and FMI 3 FMUs (every type and variability): no scope, empty scope, by causality, missing causality is `local`; a read-only probe operation records the ports seen | `tests/unit/test_operations_scope.py` |
| Renaming from CSV and the port page: already pinned | `tests/unit/test_assistant_fmutools.py`, `tests/unit/test_assistant_budget.py` |

Baseline (`python tests/_helpers/mcp_budget.py`, characters): definitions **16 848** / 17 000; `list_fmu_ports` and
`inspect_fmu_file` default page 7 867; `summarize_fmu` 731; `check_fmu` 204 (2501 errors: 628); every result within
`RESULT_BUDGET` (12 000).

Checks performed: unit suite **1073 passed**.

### Phase 1 — Python API (D3, D5, D6, D7)

1. Port filter in `operations.py`: `FMU.apply_operation(operation, apply_on=None, *, types=None, variabilities=None)`
   (Q1); `Manipulation.manipulate` applies the conjunction of the filters. `apply_on` unchanged.
2. `OperationRenameFromMapping` (or `OperationRenameFromCSV` accepting a mapping), with the same checks as the CSV
   version (duplicates, unknown names reported).
3. Extended port description (Q2): a function returning every attribute of one variable (FMI 2 and FMI 3), its
   resolved declared type, its aliases and its terminals.
4. CLI `fmutool`: `-only-type <type>` and `-only-variability <variability>` (repeatable), combined with `-only-*`.
5. Unit tests for each, FMI 2 and FMI 3.

*Commit*: `Operations restricted by type and variability (API and fmutool CLI), renaming from a mapping, full description of one port`

**Status on 31 October 2026: done.**

| Item | File |
|---|---|
| `ModelVariable.causality`, `ModelVariable.variability` (defaults of the standard, now also used by the checker) and `ModelVariable.has_type` (exact type, or FMI 2 family on an FMI 3 FMU); `ModelDescription.FMI2_TYPE_FAMILIES`, `ModelDescription.VARIABILITIES` | `model_description.py`, `checker.py` |
| `FMU.apply_operation(operation, apply_on=None, *, types=None, variabilities=None)`, `Manipulation.in_scope`: the filters combine | `operations.py` |
| `OperationRename(translations)` with `found` (names of the mapping met in the FMU); `OperationRenameFromCSV` derives from it | `operations.py` |
| `describe_port(path, port)`: declared attributes, effective causality and variability, dimensions, resolved declared type (`inherited`, enumeration `items`), aliases, terminals; an unknown port suggests close names | `assistant/fmutools.py` |
| `fmutool -only-type <type>` and `-only-variability <variability>` (repeatable, choices checked by argparse) | `cli/fmutool.py`, `help.py` |
| Tests: filters by type, family, variability (FMI 3 defaults), combinations, ports out of scope untouched, renaming from a mapping; port cards on the reference FMUs and on hand-built FMI 2 aliases, enumeration and FMI 3 array; CLI filters through `-dump-csv` | `tests/unit/test_operations_scope.py`, `tests/unit/test_assistant_fmutools.py`, `tests/integration/test_cli.py` |

Checks performed: unit and integration suites **2015 passed, 2 skipped**. No linter installed in the virtual
environment (ruff, pyflakes): unused names checked by hand (`Checker.PARAMETERS`, now unused, removed).

### Phase 2 — MCP tools (D4, D5, D7)

1. Compact the existing descriptions of `assistant/server.py`; one shared filter type for `inspect_fmu_file`,
   `list_fmu_ports` and `apply_operation`.
2. `apply_operation`: type and variability filters.
3. `rename_ports` (mapping or CSV) replaces `rename_ports_from_csv`.
4. `describe_port(fmu, port)` (assembly FMU or file path, as the port tools).
5. Budget tests: definitions within budget (raise to ~18 000 only if compaction is not enough; the measure is
   recorded here); `describe_port` result within `RESULT_BUDGET`.
6. GUI bridge checked (`mcp_bridge.py`) as well as the headless one.

*Commit*: `MCP: filters by type and variability, rename_ports (mapping or CSV) instead of rename_ports_from_csv, describe_port; tool descriptions compacted within the budget`

**Status on 31 October 2026: done.**

| Item | File |
|---|---|
| `default_variability` and `matches_type`, module functions shared by `ModelVariable` and the port pages | `model_description.py` |
| `fmutools.select_ports` (filters of the port pages, same rules as the operations; any causality can be listed), `check_port_filters` (unknown type or variability refused with the accepted values), `TYPES`, `VARIABILITIES`; `apply_operation` with `types` and `variabilities` | `assistant/fmutools.py` |
| `fmutools.rename_ports(fmu, output, mapping=None, csv_path=None)` replaces `rename_ports_from_csv`: counts the ports actually renamed or removed, reports the names of the mapping absent from the FMU (`unknown`, first 20, `unknown_total`) | `assistant/fmutools.py` |
| `describe_port`: aliases bounded to 20 (`aliases_total`) | `assistant/fmutools.py` |
| MCP: `type` and `variability` on `list_fmu_ports`, `inspect_fmu_file`, `apply_operation`; `rename_ports` (`mapping` or `csv`) replaces `rename_ports_from_csv`; `describe_port(fmu, port)`, `fmu` an FMU of the assembly or a file | `assistant/server.py` |
| Usage guide: `describe_port`, `rename_ports`, the filters | `assistant/knowledge.py` |
| Compaction (D4): shared `CausalityFilter`, `TypeFilter`, `VariabilityFilter`, `PatternFilter`, `OutputFmu`, `Overwrite`; shorter `FmuName`, `apply_operation` operations, `set_start_value` value, `save_as_fmu`, container options `auto_link`, `auto_input`, `auto_output`, `reset_ports` | `assistant/server.py`, `assistant/models.py` |
| Budget: `DEFINITIONS_BUDGET` raised to **18 000**; `describe_port` and `rename_ports` (1000 unknown names) measured | `tests/_helpers/mcp_budget.py` |
| Tests: filters and refusal of unknown values, `select_ports`, renaming from a mapping (unknown names, mapping xor CSV), bounded aliases; server: filtered pages, `describe_port` from a file and from the assembly, `rename_ports`; contract inventory | `tests/unit/test_assistant_fmutools.py`, `tests/unit/test_assistant_server_tools.py`, `tests/unit/test_assistant_server_contract.py` |

Budget measured (characters): definitions **18 347** before compaction, **17 444** after (budget 18 000); the
remaining cuts would have removed instructions that prevent mistakes. `describe_port` 302; `rename_ports` with 1000
unknown names 418.

Checks performed: unit and integration suites **2030 passed, 2 skipped**; GUI tests of the MCP bridge **33 passed**.
Pre-existing, unrelated: when the GUI tests are collected in the same session, `test_container_reset.py` (2) and
`test_lsbus.py` (2) fail; they pass alone and without the GUI tests, and fail the same way without the changes of
this phase.

### Phase 3 — `fmutool-agent` (D8)

1. `HeadlessAssemblyBridge.load_json(path)` (F5), round-trip tested against `save_as_json`.
2. `cli/fmutool_agent.py`, console script `fmutool-agent`: `fmutool-agent list-tools`, `fmutool-agent <tool>
   --args '<json>' [--state assembly.json]` (per Q3). The tool table is taken from the MCP server definitions, so
   that a tool added to the server is available here with no extra code; arguments validated with the same schemas;
   results printed as the same JSON; errors as `{"error": ...}` with a non-zero exit code.
3. Does **not** require the `mcp` extra if possible (validation through the pydantic models); otherwise documented.
4. Contract test: for every tool, the MCP result and the `fmutool-agent` result are identical on the test FMUs.

*Commit*: `fmutool-agent: the MCP tools as a JSON command line, the assembly kept in a JSON file between calls`

**Status on 31 October 2026: done.**

| Item | File |
|---|---|
| `Toolbox(bridge, policy)`: one method per tool (same names, parameters and results as the MCP tools), plain JSON values; `ports_page`, `compact_port`, `format_start_value`, `is_actionable`, `DEFAULT_PORT_LIMIT`, `MAX_PORT_LIMIT`, `MAX_DESCRIPTION_LENGTH` moved here (re-exported by `models.py`); container options checked without Pydantic (`CONTAINER_OPTION_TYPES`); `TOOLS` | `assistant/tools.py` (new) |
| MCP tools delegate to `Toolbox`; they keep their typed signatures, descriptions and result models; `_as_ports_page`, `Port.from_description` removed | `assistant/server.py`, `assistant/models.py` |
| `HeadlessAssemblyBridge.state()` / `from_state()` (`"format": "fmutool-agent-state/1"`): FMU names and paths, links, exposed ports, start values, options. **Deviation from the plan**: not a `load_json` of the assembly description, which renames the instances and resolves the paths, but an exact state of what the client asked for | `assistant/headless.py` |
| `fmutool-agent TOOL [--args JSON\|-] [--state FILE] [--root DIR] [--name NAME] [--debug]`, `fmutool-agent list-tools`; result on stdout (an object as is, otherwise `{"result": ...}`, as the MCP structured content), logs on stderr; `{"error": ...}` with exit code 2 (usage) or 1 (tool); state written after a successful change only, through a temporary file | `cli/fmutool_agent.py` (new), `pyproject.toml` |
| Tests: tools and parameters (order, required, defaults) identical to the server; a whole session (23 calls, assembly and single-FMU tools) gives the same results through the server and the command line; state round trip (instances included), kept between calls, untouched by a failed change or a reading tool; errors; stdin; runs in an interpreter where `fastmcp` and `pydantic` cannot be imported | `tests/unit/test_fmutool_agent.py` (new) |

Checks performed: unit suite **1153 passed**, integration suite **897 passed, 2 skipped**, GUI tests of the MCP
bridge **33 passed**; definitions unchanged (17 444 / 18 000). The console script needs a reinstall of the package
(`pip install -e .`) to be on the `PATH`; the tests call the module.

### Phase 4 — Plugin and skills (D2, D9, D10, D11)

```
.claude-plugin/marketplace.json
plugins/fmutool/
  .claude-plugin/plugin.json
  .mcp.json                      # fmutool-mcp over stdio
  skills/
    fmu-inspect/SKILL.md
    fmu-edit/SKILL.md
    fmu-container/SKILL.md
    _shared/fmi-reference.md     # types, causality × variability, FMI 2 / FMI 3 (per Q4)
tools/build_skill_zips.py        # claude.ai uploads
```

1. Each `SKILL.md`: a triggering description, then the workflow. First step is always to detect the backend (MCP
   tools of the `fmutool` server, else `fmutool-agent` on the `PATH`, else installation instructions).
2. `fmu-inspect`: summary first, filtered pages rather than paging, `describe_port` for one port; how to read
   `check_fmu`.
3. `fmu-edit`: never overwrite the source (output path), check before and after, preview with `dump_ports_csv`,
   filters, renaming, removal.
4. `fmu-container`: add FMUs, inspect, link (never guess a port name), expose, start values, `analyze_assembly`
   before `save_as_fmu`.
5. Evaluation: a few scripted scenarios per skill on `tests/data` FMUs, run with and without the MCP server.
6. `tools/build_skill_zips.py` and a test checking that the plugin manifests are valid and the zips build.

*Commit*: `Claude Code plugin with the fmu-inspect, fmu-edit and fmu-container skills, through the MCP server or fmutool-agent`

**Status on 31 October 2026: done.**

| Item | File |
|---|---|
| Marketplace `fmutool` with the plugin `fmutool` (version **2.1.0**, the version of the toolbox the skills need); `.mcp.json` starts `fmutool-mcp --transport stdio` | `.claude-plugin/marketplace.json`, `plugins/fmutool/.claude-plugin/plugin.json`, `plugins/fmutool/.mcp.json` |
| Skills `fmu-inspect`, `fmu-edit`, `fmu-container`: backend (MCP tools, else `fmutool-agent`, else installation), procedure with `fmutool-agent` examples, how to report the results, what the toolbox refuses, limits | `plugins/fmutool/skills/*/SKILL.md` |
| Shared reference: `FMI_CONVENTIONS` of the server verbatim, plus the port filters, the default variabilities, how to read a listing and `describe_port`, what the toolbox refuses | `plugins/fmutool/references/fmi-reference.md` |
| claude.ai `.zip` (one skill each, shared reference copied, links rewritten) | `tools/build_skill_zips.py` |
| Tests (Q5): manifests, `.mcp.json` command and `fmutool-agent` are console scripts, frontmatter (name, description length, no `<>`), links resolve, tools and operations named exist, example arguments valid, the reference contains `FMI_CONVENTIONS`, **every example runs** (container skill: `needs_container`), zips self-contained | `tests/unit/test_agent_skills.py` |
| Packaging: `fmutool-agent` added to the entry points reference (missed in phase 3); the plugin left out of the sdist, as the documentation | `tests/data/packaging/entry-points.txt`, `MANIFEST.in` |

Checks performed: unit suite **1173 passed**; `claude plugin validate .` and `claude plugin validate plugins/fmutool`:
passed (no warning once the version was set). Not run locally: `tools/dist_inventory.py` (the `build` package is
not installed), checked by the CI.

Finding: the port pages report the `unit` declared on the variable only, not the one inherited from its declared
type (`h` of `BouncingBall` 3.0 has none in the page, `m` with `describe_port`). The skills say so; resolving it in
`describe_fmu` and the GUI bridge is left for later.

### Phase 5 — User documentation

1. New page `docs/user-guide/agent-skills.md` (installation in Claude Code, upload to claude.ai, use with the Agent
   SDK, backends) and its entry in `mkdocs.yml`.
2. `docs/user-guide/fmucontainer/ai-assistant.md`: `rename_ports`, `describe_port`, filters; `fmutool-agent`.
3. `docs/user-guide/fmutool/` (CLI and Python API): `-only-type`, `-only-variability`, renaming from a mapping.
4. `CHANGELOG.md` (breaking: `rename_ports_from_csv` renamed) and `docs/whats-new.md`; `ROADMAP.md`.
5. Move this plan to `docs/local/done`.

*Commit*: `Documentation of the agent skills, fmutool-agent, the filters by type and variability and rename_ports`

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| The definitions budget is exceeded again by the next tool | D4 compaction plus the budget test; the shared filter type avoids repeating descriptions |
| `fmutool-agent` and the MCP server diverge | Tool table taken from the server; contract test of phase 3 |
| Clients using `rename_ports_from_csv` | Breaking change documented in `CHANGELOG.md`; the Python API keeps `OperationRenameFromCSV` |
| Skills drift from the tools (renamed tool, new argument) | Skill evaluation scenarios run in CI; skills reference tool names checked by a test |
| `fmutool-mcp` not on the `PATH` (venv, conda) | Skills detect it and explain; `fmutool-agent` as fallback |
| claude.ai sandbox cannot install the package or lacks the container binaries for its platform | Checked in phase 4; documented as a limitation if so |

## 6. Delivery

One PR per phase. Phases 1–2 are useful on their own (MCP users); phases 3–4 bring the skills.
