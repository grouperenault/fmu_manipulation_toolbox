# Plan: help the MCP clients analyse an FMU assembly

**Created**: 10 October 2026 — **Status**: ready (all decisions taken; D9 settled by the investigation of phase 0)

Describing the content and the behaviour of a loaded assembly is a frequent request to the AI Assistant. On a real
case (`bug.fmu`: 3 nested containers, 5 FMUs, 271 exposed ports, 295 links), the existing tools are not enough:
the model has to write its own scripts to understand the assembly, and it has no rule set to spot the usual traps.
This plan adds a bounded **analysis tool** (summary and lint), makes `get_assembly_json` usable on large assemblies,
and distributes the analysis know-how as **MCP prompts**, like the existing `build_container`, `diagnose_assembly`
and `inspect_fmu`.

---

## 1. Current state

### Case study (10 October 2026)

Assembly `bug.fmu` loaded in the Container Builder, analysed through the GUI MCP server:

```
bug.fmu                                   step 0.5 s, mt off
├── SCENARIO_..._WK2543StopT.fmu
└── CONTAINER_..._WK2542stopT.fmu         step 0.5 s, mt on
    ├── AMESIM_BIG_..._WK2542.fmu
    └── level2.fmu                        step 0.005 s, mt on
        ├── CARBODY_..._WK2530.fmu
        ├── SIMULINK_..._WK2530.fmu
        └── CONSTANT_STUB_..._WK2542.fmu
```

| Item | Size |
|---|---|
| `get_assembly_json` | **149 228 characters**: over the maximum size of a tool result of the client; saved to a file instead |
| Root level | 223 exposed inputs, 48 exposed outputs, 11 links |
| Level 1 | 7 inputs, 52 outputs, 269 links |
| Level 2 | 92 inputs, 178 outputs, 15 links |

To describe it, the model had to parse the saved file with two ad hoc Python scripts: walk the container tree, group
the ports by name prefix (`Sc_2_DV.*`, `DV_2_Assesment.*`, `SNR_*`...), count the links per pair of FMUs. The
interpretation then relied on patterns that no tool reports: `mt` on two nested levels, a step ratio of 100 between
levels, a fan-out (`Twheel_fr` feeding two inputs), a stub FMU feeding constants to disable inputs.

### Findings

| # | Finding | Location |
|---|---|---|
| A1 | `get_assembly_json` is not bounded: 149k characters on a real assembly; the budget test only measures a one-FMU assembly (257 characters) | `assistant/server.py`, `tests/unit/test_assistant_budget.py` |
| A2 | No tool gives a synthetic view of an assembly (tree, options per level, links grouped by FMU pair and prefix) | `assistant/server.py` |
| A3 | No tool reports the structural traps (nested `mt`, step ratios, fan-out, stubs, options) nor the port-level ones (causality, types, units, inputs neither linked nor exposed) | — |
| A4 | The tool definitions take 15 664 characters for a budget of 16 000: room for no new tool as is | `tests/_helpers/mcp_budget.py` |
| A5 | The prompt `diagnose_assembly` starts with `get_assembly_json` and lists checks the model must perform by hand; no prompt explains how to describe the content and behaviour of an assembly | `assistant/knowledge.py` |
| A6 | The headless bridge only builds flat assemblies (one node); the GUI bridge handles nested containers and `list_fmus` returns the FMUs of every level | `assistant/headless.py`, `gui/fmucontainer/mcp_bridge.py` |
| A7 | Links created by `auto_link` and ports exposed by `auto_input`/`auto_output` are derived at build time: they are absent from the JSON, so "an input neither linked nor exposed" cannot be read from the JSON alone | `assembly.py`, `container/builder.py` |

---

## 2. Goals

1. Describe any assembly, whatever its size, within the result budget (12 000 characters with default arguments).
2. Report the known traps of an assembly, structural and port-level, grouped and bounded like `check_fmu`.
3. Keep the tool definitions within their budget (D1).
4. Ship the procedure ("describe an assembly", "diagnose an assembly") as MCP prompts, so that any MCP client
   gets it.
5. Budgets and rules covered by tests, on the fixtures of `tests/data/containers/arch` and on a synthetic large
   nested assembly.

---

## 3. Decisions

### Taken on 10 October 2026

D1 to D4 chosen by the user; D5 to D10 taken as recommended.

| # | Question | Decision |
|---|---|---|
| D1 | Definitions budget (A4) | **One parametrised tool**, `analyze_assembly(mode="summary" \| "lint", ...)`, instead of two tools; the budget is raised slightly or kept by shortening other descriptions (measured in phase 4) |
| D2 | `get_assembly_json` unbounded (A1) | **Paged by node**: a `node` argument returns one container at a time |
| D3 | Lint scope (A3) | **Structural and port-level** rules; the port rules read the FMU descriptors through the bridge |
| D4 | Distribution of the skills (A5) | **MCP prompts**: a new prompt `analyze_assembly`, and `diagnose_assembly` updated to rely on the summary and the lint |
| D5 | Designation of a node (D2) | **Container name** (`level2.fmu`); when two sub-containers share a name, an error lists the candidates |
| D6 | `get_assembly_json` without `node` (D2) | **Whole assembly** when it fits the result budget; otherwise the **root level only**, the sub-containers reduced to their name and counts, with `truncated: true` |
| D7 | Grouping of port names (summary) | **First segment before `.`**; for names without `.`, the part **before the first `_`** (`Sc_2_DV.Rho` → `Sc_2_DV`, `SNR_T_amb` → `SNR_`) |
| D8 | Rule set and severities (lint) | The rules of the phase 3 and 4 tables; step ratio threshold of **10** (warning above it, or when the ratio is not an integer) |
| D9 | Derived links and exposures (A7) | **Reuse the rule engine** of `container/builder.py` on a copy of the node (dry run, no build) if the investigation of phase 0 shows it is possible; otherwise **ignore the `auto_*` rules** and only report when they are all off, documented as a known limit |
| D10 | Lint on the headless bridge (A6) | **Same tool**: only the root level exists there; nesting the headless bridge is out of scope |

---

## 4. Plan

### Phase 0 — Fixtures, measurements and investigation

1. Synthetic large nested assembly in `tests/_helpers/mcp_budget.py` (`make_large_assembly()`): 3 levels, about 300
   exposed ports and 300 links, port names with `.` and `_` prefixes, built from the synthetic FMUs of
   `make_large_fmu()`, to reproduce the order of magnitude of `bug.fmu` without its files.
2. Budget test: `get_assembly_json` on that assembly, marked `xfail(strict=True)` (A1).
3. Investigation for D9: can the auto-link / auto-expose rules of `container/builder.py` run on a node without building the
   container? Result recorded in this plan.

*Exit criterion*: baseline of `get_assembly_json` on the large assembly recorded here; D9 settled (engine reused, or limit documented); suite green.

*Commit message*: `Add a large nested assembly to the MCP budget fixtures (assembly_analysis phase 0)`

### Phase 1 — Assembly summary (A2, D7)

New module `assistant/analysis.py`, pure functions on the assembly JSON (both bridges produce it):

1. `summarize_assembly(assembly_json)`: for every node, recursively: name, options (`step_size`, `mt`,
   `sequential`, `profiling`, `auto_*`, `ts_multiplier`), FMUs (base names), sub-containers; counts of exposed
   inputs, outputs, links, start values, dropped ports.
2. Groups: exposed ports per (FMU, prefix), links per (source FMU, prefix, destination FMU, prefix), each with a
   `count` and at most 3 `examples`; at most 30 groups per list, with `truncated`.
3. FMUs designated by base name in the result (the JSON uses paths at the root level, names below).
4. Tests on `tests/data/containers/arch/{flat,hierarchical,nested}.json` and on the large assembly: structure,
   counts, grouping, bounds.

*Exit criterion*: the summary of the large assembly within the result budget; the counts equal to those of the JSON.

*Commit message*: `Summarise an assembly by container, FMU pair and port prefix (assembly_analysis phase 1)`

### Phase 2 — `get_assembly_json` paged by node (A1, D2, D5, D6)

1. `node` argument (D5) on the tool; behaviour without `node` as decided in D6; a `truncated` flag and the list of
   the sub-containers left out, so the model knows what to ask next.
2. Tool description: point to `analyze_assembly` for an overview, to `save_as_json` for the complete file.
3. The resource `assembly://current` follows the same rule (same function).
4. Tests: unknown node, ambiguous node, nested fixtures; the `xfail` of phase 0 removed.

*Exit criterion*: `get_assembly_json` on the large assembly within the budget, with and without `node`.

*Commit message*: `Page get_assembly_json by container node (assembly_analysis phase 2)`

### Phase 3 — Structural lint (A3, D8)

`lint_assembly(assembly_json)` in `assistant/analysis.py`, from the JSON only. Proposed rules (D8):

| Rule | Severity | Detail |
|---|---|---|
| `nested-mt` | warning | `mt` enabled on a container and on one of its sub-containers |
| `mt-sequential` | warning | `mt` and `sequential` both enabled |
| `step-ratio` | info / warning | ratio between the step of a container and of a sub-container; warning above the threshold (10), or when not an integer |
| `fan-out` | info | one output feeding several inputs |
| `constant-stub` | info | an FMU whose outputs only feed other FMUs and that has no exposed input (stub of constants) |
| `duplicate-exposure` | error | two ports exposed under the same container name |
| `link-to-exposed-input` | warning | an input both linked and exposed |
| `auto-off-nothing-exposed` | warning | `auto_input`/`auto_output` off and no exposed port of that kind on the root container |

Result shaped like `check_fmu`: findings grouped per rule (`rule`, `severity`, `message`, `count`, `examples`),
`error_count`, `warning_count`, `truncated`; at most 50 groups.

Tests: one fixture per rule (small JSON written in the test), no finding on `flat.json`, bounds on the large assembly.

*Commit message*: `Lint the structure of an assembly (assembly_analysis phase 3)`

### Phase 4 — Port-level lint and the `analyze_assembly` tool (A3, A4, D1, D9, D10)

1. Port-level rules, fed with the descriptions given by `bridge.list_fmu_ports(name)` (read once per FMU):

   | Rule | Severity | Detail |
   |---|---|---|
   | `unknown-port` | error | a linked, exposed or started port absent from the FMU |
   | `link-causality` | error | link source not an `output`, or destination not an `input` |
   | `link-type` | warning / error | type conversion (warning), or conversion refused by the container (error) |
   | `link-unit` | warning | linked ports with different units: the toolbox does not convert |
   | `dangling-input` | warning | an input neither linked nor exposed, without start value (D9 decides how the `auto_*` rules are taken into account) |
   | `parameter-not-set` | info | a parameter neither exposed nor given a start value (only when `auto_parameter` is off) |

2. Tool `analyze_assembly(mode: "summary" | "lint" = "summary", node: str | None = None)` in `assistant/server.py`
   (`READ_ONLY`), `node` restricting the analysis to one container (same designation as D5).
3. Definitions budget: measured with the new tool; shorten other descriptions or raise `DEFINITIONS_BUDGET`
   (to be proposed with the measurement, D1).
4. Tests: through the in-memory FastMCP client with the headless bridge (flat, D10) and with the JSON fixtures for the
   nested cases; budget tests for both modes on the large assembly.

*Exit criterion*: both modes within the result budget on the large assembly; definitions within their budget.

*Commit message*: `Add the analyze_assembly tool, with port-level lint rules (assembly_analysis phase 4)`

### Phase 5 — Prompts (A5, D4)

1. New prompt `analyze_assembly(focus: str = "")` in `assistant/knowledge.py`: `list_fmus`, then
   `analyze_assembly(mode="summary")`, `get_assembly_json(node=...)` only for the level to detail,
   `summarize_fmu`/`list_fmu_ports` with filters for the key FMUs; how to read the naming conventions (prefixes as
   signal buses, direction in the names such as `A_2_B`); the expected answer: tree, data flows per level, options,
   behaviour, then the lint findings; separate what is read from the assembly from what is interpreted.
2. `diagnose_assembly` rewritten around `analyze_assembly(mode="lint")`: the manual checks it lists today become the
   reading of the rules, plus what the lint cannot see (simulation results, symptom of the user).
3. `guide://usage` updated (new tool, `node` argument).
4. Tests: the prompts are listed, render with and without arguments, and only name existing tools (test checking the
   back-quoted tool names against the server).

*Commit message*: `Add the analyze_assembly prompt and base diagnose_assembly on the lint (assembly_analysis phase 5)`

### Phase 6 — User documentation

1. `docs/user-guide/fmucontainer/ai-assistant.md`: `analyze_assembly` in the tool table, a section "Analysing an
   assembly" (modes, rules and severities, `node`), `get_assembly_json` paging, the new prompt in the prompt table,
   known limits (D9, D10).
2. `CHANGELOG.md`: new tool, new prompt, `get_assembly_json` behaviour on large assemblies.
3. This plan moved to `docs/local/done/`.

*Commit message*: `Document the assembly analysis of the AI Assistant (assembly_analysis phase 6)`
