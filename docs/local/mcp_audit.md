# Audit of the MCP server (FastMCP)

**Audit**: 3 October 2026 — **Closing verification**: 9 October 2026 (§8), N1 checked again on 10 October 2026 —
**Branch**: `features/mcp`, merged into `integration`
**Initial scope**: `fmu_manipulation_toolbox/gui/fmucontainer/mcp_server.py` (616 lines). This file no longer exists: the
server was reorganized into the `fmu_manipulation_toolbox/assistant` package (`server.py`, `models.py`, `paths.py`,
`auth.py`, `headless.py`, `fmutools.py`, `knowledge.py`), the Qt bridge is in `gui/fmucontainer/mcp_bridge.py` and the
standalone server in `cli/fmutool_mcp.py`. The `mcp_server.py:NNN` references of the findings are historical; the
"Current location" column gives where each point is handled today.
**Environment**: audit with `fastmcp` 4.0.3, Python 3.13.3, macOS; verification with `fastmcp` 4.1.0, Python 3.14.8, macOS.
**Method**: code review + actual execution of the server through an in-memory `fastmcp.Client` (inventory, scenarios,
error cases) + `pytest`.

File names in this document are relative to the root of the repository.

---

## 1. Summary

**Status on 10 October 2026.** The 14 steps of the action plan (§6) are done, step 12 partially, as planned. The server
exposes **21 annotated tools, 4 resources, 1 resource template and 3 prompts**. It starts without the GUI (`fmutool-mcp`,
stdio) or from the GUI (HTTP, optional token), and it is covered by **214 tests**. The 6 blocking and 12 important findings
are fixed; I7 and I8 partially, by documented choice. Still open: M4 (access to private attributes in the Qt bridge), a vague
message of the Qt bridge for M3, no dedicated test for I11, and a new finding (N3). N1 is resolved since the `element-tree`
branch was merged (§8).

**Initial summary (3 October 2026).** The server exposed **12 tools, 2 resources, 0 prompt** and drove the *Container
Builder* GUI live. The marshalling to the Qt thread (`MainThreadInvoker`) and the shutdown of uvicorn were careful and well
justified. **Two complete assembly scenarios were executed successfully** (JSON export in 9 calls, build of a valid
93,807-byte FMI-2 container in 7 calls), and three error messages out of four turned out to be really actionable for an
LLM. The weaknesses were elsewhere: the server **only existed while the GUI was running** (no entry point, no stdio
transport), it **was not covered by any test**, it **applied no control on the file system** — I accidentally overwrote a
tracked file of the repository during the audit — and it **accepted `fmi_version=7`, producing a corrupted FMU reported as
a success**. Finally, it only covered a fraction of the toolbox: nothing from `fmutool`, the `Checker` or `fmusplit`. The
tools lacked annotations (`readOnlyHint`/`destructiveHint`), constrained typing (`Literal`, `Field`) and bounds on their
outputs.

---

## 2. Findings by severity

The findings are those of 3 October; the "Status" column is that of the 9 October verification.

### 🔴 Blocking

| # | Finding (3 Oct.) | Status on 9 Oct. | Current location |
|---|---|---|---|
| **B1** | **No test.** No `tests/**/*mcp*` file; server coverage = 0. | ✅ **Fixed** (step 3): 214 tests (in-memory client, headless bridge, Qt bridge, stdio, token, `fmutool` tools) | `tests/unit/test_assistant_*.py`, `tests/integration/test_assistant_stdio_server.py`, `tests/gui/test_assistant_qt_bridge.py` |
| **B2** | **No standalone entry point**: start only from the *AI Assistant On* menu; no `console_scripts`, no stdio transport. | ✅ **Fixed** (step 10): `fmutool-mcp`, stdio by default, without GUI | `cli/fmutool_mcp.py`, `setup.py` |
| **B3** | **No control on the file system**: any path accepted, no extension check, no overwrite guard. **Seen in practice**: `save_as_json` overwrote `tests/data/containers/bouncing_ball/bouncing.csv` (restored with `git checkout`). | ✅ **Fixed** (step 2); checked again: extension enforced, refusal to overwrite without `overwrite=True`, refusal outside the allowed root | `assistant/paths.py` (`PathPolicy`) |
| **B4** | **Local HTTP without authentication**: any process of the machine can drive the GUI and write files. | ✅ **Fixed** (step 13): opt-in shared token (`--token generate` / `FMUCONTAINER_MCP_TOKEN`), documented threat model; stdio removes the problem for the clients that launch the server | `assistant/auth.py`, `cli/fmutool_mcp.py` |
| **B5** | **No `ToolError`**: any internal error leaks raw (`'NoneType' object has no attribute 'list_fmus'` + traceback). | ✅ **Fixed** (step 4); completed on 9 Oct. for argument validation errors (N2, §8) | `assistant/server.py` (`_guard`, `ArgumentErrors` middleware) |
| **B6** | **`fmi_version` not validated**: `save_as_fmu(fmi_version=7)` returns `OK` and produces a **0-byte** `modelDescription.xml`. | ✅ **Fixed** (step 1); checked again: schema `enum: [2, 3]`, 7 rejected before reaching the bridge | `assistant/server.py` (`save_as_fmu`), `assistant/bridge.py` (`SUPPORTED_FMI_VERSIONS`) |

### 🟠 Important

| # | Finding (3 Oct.) | Status on 9 Oct. | Current location |
|---|---|---|---|
| **I1** | **No annotation** `readOnlyHint`/`destructiveHint`/`idempotentHint` on the 12 tools. | ✅ **Fixed** (step 4); checked again on the 21 tools | `assistant/server.py` (`READ_ONLY`, `IDEMPOTENT_WRITE`, `DESTRUCTIVE_WRITE`) |
| **I2** | **Typing too weak**: `options: Dict[str, Any]`, `fmi_version: int`, no `Annotated`/`Field`/`Literal`. | ✅ **Fixed** (step 5) | `assistant/models.py` (`ContainerOptions`), `assistant/server.py` |
| **I3** | **Unstructured, unbounded outputs** (`list_fmu_ports`: no pagination, filter or model). | ✅ **Fixed** (step 6): Pydantic models, filter by causality and by pattern, pagination | `assistant/models.py` (`FmuPorts`, `Port`) |
| **I4** | **Wrong split between tools and resources**; no templated resource. | ✅ **Fixed** (step 7): `fmu://{name}/ports`, `assembly://current`… | `assistant/server.py` |
| **I5** | **No use of `Context`**, fixed 60 s timeout. | ✅ **Fixed** (step 8): `report_progress` in `save_as_fmu`, configurable timeout (`FMUCONTAINER_MCP_TIMEOUT`) | `assistant/server.py` (`save_as_fmu`, `resolve_timeout`) |
| **I6** | **No MCP prompt**; `USAGE_GUIDE` duplicated the user documentation. | ✅ **Fixed** (step 7): 3 prompts, single source (tested) | `assistant/server.py`, `assistant/knowledge.py` |
| **I7** | **Duplication instead of reuse** of the `Assembly` API. | ✅ **Partial, by choice** (step 10): the headless bridge relies on `Assembly`; the Qt bridge drives the scene, which is its very purpose (the user must *see* the agent working) | `assistant/headless.py`, `gui/fmucontainer/mcp_bridge.py` |
| **I8** | **Almost no coverage of the toolbox** (`fmutool`, `Checker`, `fmusplit`). | ✅ **Partial, by choice** (step 11): `summarize_fmu`, `check_fmu`, `dump_ports_csv`, `rename_ports_from_csv`, `apply_operation`; `fmusplit` and remoting stay out of scope | `assistant/fmutools.py` |
| **I9** | **Implicit `uvicorn` dependency.** | ✅ **Fixed** (step 9) | `setup.py` (`mcp` extra), `requirements.txt` |
| **I10** | **Unclear version contract** (`>= 2.14.0` without upper bound, documentation saying "FastMCP 2"). | ✅ **Fixed** (step 9): `fastmcp >= 4.0.3, < 5`, no mention of "FastMCP 2" left | `setup.py`, `requirements.txt` |
| **I11** | **Build failures swallowed**: `FMUContainerError` logged, path returned as a success. | ✅ **Fixed** (step 1): the error is propagated. ⚠️ No test checks that a failed build is reported as a failure | `gui/fmucontainer/assembly_io.py` (`save_as_fmu`) |
| **I12** | **Testability hampered by the Qt coupling.** | ✅ **Fixed** (steps 3 and 10): the headless bridge is tested without Qt; the Qt bridge has its own tests | `assistant/headless.py`, `tests/gui/test_assistant_qt_bridge.py` |

### 🟡 Minor

| # | Finding (3 Oct.) | Status on 9 Oct. | Current location |
|---|---|---|---|
| **M1** | `int(os.environ[...])` at module load: a malformed value → `ValueError` at import. | ✅ **Fixed**: read at start-up, clear message | `assistant/server.py` (`resolve_port`) |
| **M2** | `NodeItem` probe created then `del`: does not guarantee the release of a `QGraphicsItem`. | ➖ **Unchanged, no impact seen**: the probe is never added to a scene, Python releases it | `gui/fmucontainer/mcp_bridge.py` (`_inspect_fmu_file_impl`) |
| **M3** | FMUs identified by *basename*: ambiguous with two files of the same name. | ⚠️ **Partial**: the headless bridge refuses a second file with the same name with an explicit message; the Qt bridge refuses it too, but with a hesitant message ("could not be added (already present?)") | `assistant/headless.py`, `gui/fmucontainer/mcp_bridge.py` (`_add_fmu_impl`) |
| **M4** | Heavy access to private attributes of other classes. | ❌ **Open**: 6 accesses left (`fmu_detail._current_node`, `_load_from_node`, `wire_detail._wire`, `_load_from_wire`, import of `_NodeTreeModel`) | `gui/fmucontainer/mcp_bridge.py` |
| **M5** | One-line docstrings: no preconditions, no examples, no "when to use". | ✅ **Fixed** (step 5): detailed docstrings and field descriptions, visible in the schema | `assistant/server.py` |
| **M6** | `list_fmu_ports` mixes two intents (FMU of the canvas **or** file on disk). | ✅ **Fixed**: `list_fmu_ports` (assembly) and `inspect_fmu_file` (disk) are separate | `assistant/server.py` |
| **M7** | Incomplete client documentation (JetBrains + VS Code only). | ✅ **Fixed** (step 14): Claude Desktop, VS Code, JetBrains, known limits | `docs/user-guide/fmucontainer/ai-assistant.md` |
| **M8** | `list_fmu_ports` merges `input` and `parameter`, excludes `local`, outputs without `causality` nor `start`. | ✅ **Fixed** (step 6): every port with its causality, variability, type, unit, `start` | `assistant/models.py` (`Port`) |

### ✅ Compliant points (3 Oct., still true on 9 Oct.)

Consistent `verb_object` naming · one intent per tool (M6 fixed since) · `outputSchema` generated for every tool (12, then
21) · documented thread-safe marshalling · graceful then forced shutdown of uvicorn · port pre-check with `SO_REUSEADDR` ·
errors raised on the main thread · really actionable business validation messages (S8 below). These points are now in
`gui/fmucontainer/mcp_bridge.py` (`MainThreadInvoker`, start and stop of the HTTP server).

---

## 3. Coverage

| Feature | Exposed through MCP (3 Oct.) | Usefulness for an agent | Recommendation | Status on 9 Oct. |
|---|---|---|---|---|
| Assemble a container | **Yes** | High | Keep; harden types + annotations | ✅ |
| Introspect the ports of an FMU | **Partial** (M8) | High | Enrich, filter, paginate | ✅ `list_fmu_ports`, `inspect_fmu_file` |
| Read the assembly back | Yes | High | Also provide as a resource | ✅ `assembly://current` |
| `OperationSummary` | **No** | High | To expose | ✅ `summarize_fmu` |
| `Checker` / XSD validation | **No** | High | To expose | ✅ `check_fmu` |
| `OperationSaveNamesToCSV` | **No** | High | To expose | ✅ `dump_ports_csv` |
| `OperationRenameFromCSV` | **No** | Medium | To expose | ✅ `rename_ports_from_csv` |
| Regexp / TrimUntil / TopLevel | **No** | Medium | Parameterized `apply_operation` tool | ✅ `apply_operation` (N1 resolved, §8) |
| `fmusplit` | **No** | Medium | To expose | ➖ Out of scope (I8) |
| Read a JSON/CSV/SSP assembly | **No** | Medium | `read_assembly(path)` | ➖ Postponed, documented limit (§7) |
| Nested sub-containers | **No** | Medium | Structural gap | ➖ Postponed, documented limit (§7) |
| `remove_link` / `unset_start_value` | **No** | Medium | Add | ✅ (+ bulk `add_links`) |
| Terminals / LS-BUS | **No** (read-only) | Medium | Document the limit | ✅ terminals read by `list_fmu_ports` |
| Remoting / win32-64 frontend | **No** | Low | Leave to the CLI | ➖ Left to the CLI |
| `datalog2pcap` | **No** | Low | Leave to the CLI | ➖ Left to the CLI |

---

## 4. Scenarios

Executed through an in-memory `fastmcp.Client`, real `MainThreadInvoker`, active Qt loop (`QT_QPA_PLATFORM=offscreen`), data
from `tests/data/containers/bouncing_ball`.

| # | Scenario | Result (3 Oct.) | Calls | Blocker (3 Oct.) | Replayed on 9 Oct. |
|---|---|---|---|---|---|
| **S1** | Assemble 2 FMUs + JSON export | **Completes.** Correct JSON | **9** | None | ✅ Completes (headless bridge); a second export without `overwrite=True` is refused |
| **S2** | Build the FMI-2 container `.fmu` | **Completes.** 93,807 bytes, `fmiVersion="2.0"` | **7** | None | ✅ Completes: 93,770 bytes |
| **S3** | Inspect the inputs/outputs of an FMU outside the canvas | **Partial**: parameters mixed with inputs, locals missing | 1 | Not enough information | ✅ `inspect_fmu_file`: every causality, unit, `start`, description |
| **S4** | Rename ports from a CSV | ❌ Blocked at once | 0 | `OperationRenameFromCSV` not exposed | ✅ `rename_ports_from_csv` (unit tests) |
| **S5** | Remove the local variables | ❌ Blocked at once | 0 | No `fmutool` tool | ✅ `apply_operation` (`remove_regexp` + `causality=["local"]`); not replayed, filtering by causality covered by unit tests |
| **S6** | Check the conformity of an FMU | ❌ Blocked at once | 0 | `Checker` not exposed | ✅ `check_fmu` executed: compliant with FMI-2.0 |
| **S7** | Compare two versions of an FMU | ❌ Impossible | 0 | No CSV dump, no summary, no diff | ✅ Possible: `summarize_fmu` + `dump_ports_csv` (the agent still does the comparison) |
| **S8** | Error handling | 3 cases out of 4 correct | 4 | 1 silent corruption | ✅ 4 cases out of 4 correct (details below) |

**S8 details (actual outputs)**

| Case | Result seen on 3 Oct. | Verdict | Result seen on 9 Oct. |
|---|---|---|---|
| `add_link` on a missing port | `ToolError: ... 'nope' is not an output of 'bb_velocity.fmu'.` | ✅ actionable | `'nope' is not a port of 'bb_velocity.fmu'.` ✅ |
| `list_fmu_ports('ghost.fmu')` | `ToolError: ... is neither loaded nor a valid file path.` | ✅ actionable | Refused with the file name ✅ |
| unknown option | `ToolError: Unknown container option(s): ['stepsize']. Allowed: [...]` | ✅ excellent | Before the fix: raw Pydantic text with a documentation link (N2). After: `unknown option 'stepsize' (allowed: auto_input, …, step_size, ts_multiplier)` ✅ |
| `save_as_fmu(fmi_version=7)` | `OK` + archive with an empty `modelDescription.xml` | ❌ **B6** | Refused before the bridge: `'fmi_version': Input should be 2 or 3 (got 7)` ✅ |

**Methodological note** — a first harness using a "direct" invoker produced an empty assembly. After checking, **FastMCP runs
synchronous tools in an `AnyIO worker thread`** (`TOOL THREAD: AnyIO worker thread main=False`): it was not a product bug but
a test artifact, and it **validates** the design of the `MainThreadInvoker`.

**Gaps / redundancies / sizing** (3 Oct. → 9 Oct.)
- *Gaps*: `remove_link` ✅, `unset_start_value` ✅, sub-containers ➖ postponed, loading an existing assembly ➖ postponed,
  undo ➖ not handled.
- *Redundancies*: `get_assembly_json` ≡ `assembly://current` (acceptable); `USAGE_GUIDE` duplicated the user documentation
  → ✅ single source, tested.
- *Too poor*: `add_fmu` only returned the name → ✅ returns a card (FMI version, generator, ports per causality);
  `remove_fmu` returned a constant `True` → ✅ returns the removed links.
- *Unbounded*: `list_fmu_ports` → ✅ paginated; `get_assembly_json` ➖ unchanged (its size depends on the assembly, not on an
  FMU).
- *Number of calls*: no bulk wiring → ✅ `add_links`.

---

## 5. Recommendation about skills

**The know-how must live in the server, not in the repository.** The constraint "usable by any MCP client" rules out
`SKILL.md` and `.github/copilot-instructions.md` as the main medium: they would not follow a user connected from Claude
Desktop, Cline or a home-made agent.

| Medium | Portable? | Verdict |
|---|---|---|
| Tool docstrings | ✅ | **Mandatory base** (too poor on 3 Oct., see M5; enriched since) |
| **MCP prompts** (`@mcp.prompt`) | ✅ | ✅ **Priority 1** — they travel with the server |
| MCP resources | ✅ | ✅ Good for the FMI *reference*, not for the procedure |
| Skills (`SKILL.md`) | ❌ Claude/Agent Skills | ⚠️ Complement only |
| `copilot-instructions.md` / prompt files | ❌ | ⚠️ Useful to *contribute* to fmutool, not for the end user |

**Chosen strategy, in 3 layers:**
1. Enrich docstrings + annotations (low cost, 100 % portable).
2. Expose 3 MCP prompts based on `USAGE_GUIDE`: `build_container`, `diagnose_assembly`, `inspect_fmu`.
3. Add 2 reference resources: `fmi://conventions`, `container://options`.

**Skills are only justified** for multi-tool workflows going beyond MCP (MCP + `fmutool` CLI + `fmpy` to validate by
simulation). They are then a **superset** of the prompts, never a substitute.

| P | Skill | Goal | Trigger | Tools |
|---|---|---|---|---|
| 1 | `build-fmu-container` | Assemble N FMUs into a valid container | "combine/assemble these FMUs" | `add_fmu`, `list_fmu_ports`, `add_link`, `expose_*`, `set_container_options`, `get_assembly_json`, `save_as_fmu` |
| 2 | `diagnose-container-assembly` | Explain a failing build | "the container does not work" | `get_assembly_json`, `list_fmu_ports`, `set_container_options` |
| 3 | `inspect-fmu` | Identity card of an FMU | "what does this FMU contain?" | `inspect_fmu_file`, `summarize_fmu`, `check_fmu` |

<details>
<summary>Draft <code>build-fmu-container/SKILL.md</code> (updated on 9 October 2026)</summary>

```markdown
---
name: build-fmu-container
description: >
  Assemble several FMUs into a single FMU Container using the FMU Manipulation
  Toolbox MCP server (fmucontainer). Use when the user wants to combine, merge,
  co-simulate or package multiple .fmu files together, or to export/build a
  container FMU. Works with the standalone `fmutool-mcp` server or with the
  Container Builder GUI (AI Assistant On).
---

# Build an FMU Container

## Preconditions
- The `fmutool` MCP server must be reachable. If tools are unavailable, tell the
  user to configure `fmutool-mcp` in the client, or to launch `fmucontainer-gui` and
  enable **Configuration -> AI Assistant On**.
- With the GUI server, actions are applied to the **live GUI** and are immediately
  visible to the user.

## Workflow
1. **Inventory** - `list_fmus`. Never assume the canvas is empty.
2. **Add** - `add_fmu(path)` per file. FMUs are identified afterwards by their
   **base name** (`controller.fmu`), not their full path. Refuse to continue if two
   different files share the same base name: ask the user to rename one.
3. **Introspect** - `list_fmu_ports(fmu)` for every FMU *before* wiring. Each port
   comes with its `causality`; filter by causality or name pattern, and page through
   large FMUs with `offset`/`limit`.
4. **Route** - `auto_link` is **on by default** and already connects ports sharing
   name and type. Only call `add_link` for ports whose names differ. Connect an
   OUTPUT to an INPUT; numeric conversions are applied but may be lossy, and
   real<->boolean is a red flag worth confirming.
5. **Boundary** - rely on `auto_input`/`auto_output` by default. Use
   `expose_input`/`expose_output` only when auto-exposure is disabled or when the
   user asks for a specific container interface.
6. **Initial values** - `set_start_value(fmu, port, value)`. Values are strings:
   `"true"`/`"false"` for booleans, `"0.01"` for reals.
7. **Options** - `set_container_options`. Accepted keys only: `step_size`, `mt`,
   `profiling`, `sequential`, `auto_link`, `auto_input`, `auto_output`,
   `auto_parameter`, `auto_local`, `ts_multiplier`. Leave `step_size` unset to let
   the toolbox derive it from the embedded FMUs; never invent a value.
8. **Review** - `get_assembly_json`, summarise FMUs/links/exposed ports/options.
   **Stop and ask for confirmation.**
9. **Build** - `save_as_fmu(path, fmi_version=2|3)`.
   - `fmi_version` is 2 or 3 (any other value is rejected).
   - `save_as_fmu` and `save_as_json` refuse to replace an existing file: ask the
     user before calling them again with `overwrite=True`. Never write inside a
     source or data directory.
10. **Verify** - restate the output path and the options actually used.

## Red flags
- An embedded input neither linked nor exposed stays at its start value: mention it.
- A port the user names but absent from `list_fmu_ports`: do not guess, ask.
- A failed build is reported as an error: never announce a container that was not built.
```
</details>

---

## 6. Prioritized action plan

Each step is independent and sized for one PR.

| # | PR | Content | Fixes | Effort | Status |
|---|---|---|---|---|---|
| **1** | `fix(mcp): validate fmi_version` | `fmi_version: Literal[2, 3]`; propagate the failure of `make_fmu` instead of returning a success. | B6, I11 | XS | ✅ done |
| **2** | `fix(mcp): secure writes` | Check the extension (`.json`/`.fmu`), refuse to overwrite without `overwrite=True`, normalize/resolve paths, configurable allowed root. | B3 | S | ✅ done |
| **3** | `test(mcp): first in-memory client tests` | `QApplication` fixture + Qt loop + client thread; cover inventory, S1, S2 and the 4 error cases. `gui` marker. | B1, I12 | M | ✅ done |
| **4** | `feat(mcp): ToolError + annotations` | `ToolError` with actionable messages; `readOnlyHint` on `list_*`/`get_*`, `destructiveHint` on `remove_fmu`/`save_as_*`, `idempotentHint` on `expose_*`/`set_*`. | B5, I1 | S | ✅ done |
| **5** | `feat(mcp): strict input typing` | `Annotated`/`Field` with descriptions; `ContainerOptions` as a Pydantic model instead of `Dict[str, Any]`. | I2 | S | ✅ done |
| **6** | `feat(mcp): structured, bounded outputs` | Pydantic models for the ports; `causality`/regex filter + pagination on `list_fmu_ports`; also expose `parameter` and `local` distinctly. | I3, M8 | M | ✅ done |
| **7** | `feat(mcp): prompts and reference resources` | 3 prompts (`build_container`, `diagnose_assembly`, `inspect_fmu`); resources `fmi://conventions`, `container://options`, `fmu://{name}/ports`; `USAGE_GUIDE` becomes the single source. | I4, I6 | M | ✅ done |
| **8** | `feat(mcp): progress and logging` | `Context` injection; `ctx.info()` + `report_progress()` in `save_as_fmu`; configurable timeout. | I5 | S | ✅ done (`report_progress` with a message: the *logging capability* of the SDK is deprecated since SEP-2577) |
| **9** | `chore(mcp): packaging` | Declare `uvicorn` in the `mcp` extra; bound `fastmcp >= 2.14, < 5`; align code and documentation with the version actually supported. | I9, I10 | XS | ✅ done |
| **10** | `feat(mcp): standalone stdio server` | Extract a "headless" bridge on top of the `Assembly` API; `fmutool-mcp` console script; stdio transport; GUI mode kept. | B2, I7 | L | ✅ done |
| **11** | `feat(mcp): expose fmutool and the checker` | `summarize_fmu`, `check_fmu`, `dump_ports_csv`, `rename_ports_from_csv`, `apply_operation`. | I8, S4-S7 | M | ✅ done |
| **12** | `feat(mcp): complete assembly editing` | `remove_link`, `unset_start_value`, `read_assembly(path)`, sub-containers, bulk `add_links`. | §4 gaps | M | ✅ partial: `remove_link`, `unset_start_value` and `add_links` delivered; `read_assembly` and sub-containers are not covered and are now documented as known limits |
| **13** | `chore(mcp): secure the transport` | Shared token or Unix socket; document the threat model. | B4 | M | ✅ done: opt-in shared token on HTTP + documented threat model. The Unix socket was not kept: step 10 made stdio available, which removes the problem at its root for the clients that launch the server |
| **14** | `docs(mcp): update the guide` | Claude Desktop example (after step 10), known limits, annotation table. | M7 | XS | ✅ done |

**Recommended order**: 1 → 2 → 3 (securing and test net), then 4 → 5 → 6 → 7 (agent interface quality), then 9 → 8, then 10
(structural rework) and finally 11 → 12 → 13 → 14.

The minor findings M1 to M8 had no dedicated step; their status is given in §2 (M2 unchanged without impact, M3 partial,
M4 open). The new findings of the closing verification are in §8.

## 7. Still to do

The two gaps identified in §4 that were not handled, and why:

| Gap | Why postponed |
|---|---|
| **Sub-containers** (hierarchical assemblies) | The `AssemblyBridge` protocol describes a flat container. Supporting them requires a tree model on the bridge side *and* on the GUI side (the Qt scene has no notion of a sub-container an agent could drive). To be handled as a product evolution, not as an interface fix. |
| **`read_assembly(path)`** | Loading an existing `.json` would overwrite the current assembly — destructive and without undo on the MCP side. Needs at least an explicit semantics (replace / merge) and a confirmation. |

Both are announced in the "Known limits" section of the user guide and in the `guide://usage` resource served to agents, so
that an assistant does not promise what it cannot do.

Points still open after the verification:

| Point | Nature | Proposal |
|---|---|---|
| **M4** — access to private attributes in the Qt bridge | Fragility: a renaming in `details/` or `tree/` would break the bridge without any error at import | Expose small public methods (`show_node`, `refresh_wire`…) in the detail panels and use them from the bridge |
| **M3** — message of the Qt bridge for a file with the same name | "could not be added (already present?)": the bridge does not know why `add_node` refused | Check the name clash in the bridge before calling the scene, with the same message as the headless bridge |
| **I11** — no test of a failed build | The error propagation exists, but a regression would go unnoticed | Test of the Qt bridge and of the headless bridge where `make_fmu` raises `FMUContainerError`: the client must get an error, not a path |
| **N3** — `summarize_fmu` returns the path of a deleted temporary directory | Useless noise for the agent | Remove the `temporary directory` line from the report returned by the tool |

---

## 8. Closing verification (9 October 2026)

**Method.** The real server (`build_server` + headless bridge, root confined to a temporary directory) is driven by an
in-memory `fastmcp.Client`, as during the audit: inventory, scenarios S1, S2, S3, S6, S8, editing tools and `fmutool`
tools, resources and prompts. The findings were then checked in the code one by one (§2), and the 214 tests of the server
were run.

**Inventory found.** 21 tools, all annotated and with an output schema: 6 read-only (`list_fmus`, `list_fmu_ports`,
`inspect_fmu_file`, `get_assembly_json`, `summarize_fmu`, `check_fmu`), 7 idempotent writes, 8 destructive writes.
4 resources (`guide://usage`, `fmi://conventions`, `container://options`, `assembly://current`), 1 resource template
(`fmu://{name}/ports`), 3 prompts (`build_container`, `diagnose_assembly`, `inspect_fmu`).

**New findings.**

| # | Finding | Status |
|---|---|---|
| **N1** | `apply_operation(operation="keep_only_regexp", argument="nothing")` returned `OK` and wrote an FMU whose `<ModelVariables>` is empty, which the FMI XSD forbids: an invalid FMU reported as a success, like B6. Cause: `fmutool` itself (defect D10 of `refactoring.md`), not the MCP server. | ✅ **Resolved** by the merge of the `element-tree` branch. Checked on 10 October 2026 on `integration`: the operation raises `OperationError` ("The operation would remove every variable"), no output file is written, and the error reaches the client as an actionable `ToolError` (exceptions of the toolbox package are actionable). |
| **N2** | Since the strict typing (step 5), Pydantic rejects invalid arguments *before* the tool, and FastMCP returned the raw text ("1 validation error for call[…]", error code, link to the Pydantic documentation). The "Unknown container option(s): … Allowed: […]" message, rated excellent in S8, was no longer produced. | ✅ **Fixed on 9 October**: a FastMCP middleware (`ArgumentErrors`) rewrites every argument validation error, for the 21 tools: unknown option or argument with the list of the allowed values (read from the tool schema), missing argument, value outside its constraint. 7 tests added (`tests/unit/test_assistant_server.py`). |
| **N3** | The `summarize_fmu` report contains `temporary directory = …`, the path of a directory already deleted when the agent reads it. | Open, minor (§7). |

**Conclusion.** The action plan is done and N1 is resolved: the audit can be closed. The open points (M4, M3 on the Qt side,
test of I11, N3) are robustness improvements, without risk for the user.
