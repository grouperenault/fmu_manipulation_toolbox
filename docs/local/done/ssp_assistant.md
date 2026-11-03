# Plan: SSP in the MCP server, fmutool-agent and the agent skills

**Created**: 1 November 2026 — **Status**: done — **Depends on**: [ssp_export.md](done/ssp_export.md)

The SSP reader is stable and assemblies can be written as SSP, but an AI agent cannot use either: the MCP server
has no SSP tool, cannot load an existing assembly ("No `read_assembly`", a documented limit), and the skills do not
mention SSP. The goal of this plan is that an agent can inspect an SSP file, load it (or a JSON/CSV description) into
the assembly, edit it and save it as SSP, through the MCP server and `fmutool-agent` alike.

---

## 1. Current state

- `assistant/tools.py` (`Toolbox`): every tool, shared by `assistant/server.py` (MCP) and `cli/fmutool_agent.py`.
  `save_as_json(path, overwrite)` and `save_as_fmu(path, fmi_version, datalog, overwrite)` write the assembly.
- Bridges: `assistant/headless.py` (`HeadlessAssemblyBridge`, state of `fmutool-agent` in `state()`/`from_state()`)
  and `gui/fmucontainer/mcp_bridge.py` (the live canvas). Neither can load an assembly file.
- Budget of the tool definitions: **17 444 / 18 000** characters before this plan, 17 995 after it (`tests/_helpers/mcp_budget.py`).
- Skills: `plugins/fmutool/skills/fmu-container` (assembly), `fmu-inspect` (FMU files only).
- Documentation: `docs/user-guide/fmucontainer/ai-assistant.md` (Known limits: no nested container created, no
  `read_assembly`), `docs/user-guide/agent-skills.md`.

---

## 2. Decisions

| # | Question | Decision |
|---|---|---|
| A1 | SSP tools | **`save_as_ssp`**, **`import_assembly`** (JSON, CSV or SSP into the assembly) and **`inspect_ssp`** (an SSP file described without importing it) (1 November 2026). |
| A2 | Definitions budget | **Merge tools** rather than raise the budget (1 November 2026): breaking for the MCP API, documented in the CHANGELOG. Which tools, see A3. |
| A3 | The merge | **`save_assembly(path, overwrite, ssp_version)`** replaces `save_as_json`, the format given by the extension (`.json`, `.ssp`); **`add_link` removed**, `add_links` covers it; `save_as_fmu` kept (3 November 2026). |
| A4 | `import_assembly` on a non-empty assembly | **A `replace` argument**: refused by default, replaced with `replace=True` (3 November 2026). |
| A5 | Content of `inspect_ssp` | **A summary per system, the details paged** like `get_assembly_json`; a refused file is an answer, `readable: false` with the `reason`, not an error (3 November 2026). |
| A6 | Nested assemblies in the headless bridge | **Refused with a clear error** pointing to `inspect_ssp` and the GUI; flat files are imported without loss (3 November 2026). |

| A7 | Skills | **Extend `fmu-container`** (import, save as SSP) **and `fmu-inspect`** (`inspect_ssp`), no new skill; they need the toolbox **2.1a1**, the first release with `save_assembly` (3 November 2026). |

---

## 3. Changes

- `Toolbox`: `import_assembly`, `inspect_ssp`, and the save tool(s) of A3; the bridges get `import_assembly(path)`
  and `save_as_ssp(path, ssp_version)` (headless: through `Assembly` and the state; GUI: through the window, on its
  main thread).
- `assistant/server.py`: typed signatures, descriptions; the budget test stays at 18 000 (A2).
- `fmutool-agent`: nothing to write by hand (it calls `Toolbox`); `import_assembly` writes the state file.
- Skills and their tests (`tests/unit/test_agent_skills.py`: every example runs).
- Usage guide of the server (`assistant/knowledge.py`), contract and budget tests.

---

## 4. Steps

1. **Tools** (A1, A3–A6): `Toolbox`, both bridges, MCP signatures, merge, budget and contract tests.
   Commit message: `SSP in the assistant: import an assembly, inspect and save SSP files`
2. **fmutool-agent**: state written by `import_assembly`; contract test of the new tools against the server.
   Commit message: `fmutool-agent: import an assembly and save it as SSP`
3. **Skills** (A7): procedures, examples run by the tests, version needed (`compatibility`).
   Commit message: `Skills: SSP files`
4. **User documentation** (`ai-assistant.md`: tools, the "No read_assembly" limit removed; `agent-skills.md`;
   walkthrough) and CHANGELOG (breaking: the merged tools).
   Commit message: `Document SSP in the assistant and the skills`
