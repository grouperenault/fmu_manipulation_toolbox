# Plan: help the MCP clients analyse an FMU assembly

**Created**: 10 October 2026 — **Updated**: 10 October 2026 (phases 0 to 2 done; D9', D11 to D13 taken) — **Status**: in progress

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
| D9' | Levels holding a sub-container (phase 0 investigation) | **Partial dry run, reported**: the engine is used as is; at a level holding a sub-container, the ports of the sub-container are not evaluated by the `auto_*` rules, and the lint emits an `info` finding saying so (no stand-in of the sub-container interface) |
| D11 | Bounds of the summary (phase 1: 19 169 characters on the real `bug.fmu` with 30 groups per list) | **Both bounds**: per container, at most **15** groups per list, the elements alone in their group merged into `ungrouped` (count and examples); for the whole tree, beyond the result budget, the root only is detailed and the sub-containers are reduced to their name, options, FMUs and counts (`reduced`), the detail being reached with `node` (phase 4) |
| D12 | A single container over the budget (phase 2: 24k to 57k characters per level of `bug.fmu`) | **Sections and paging**: without `section`, the container with its options, FMUs, `counts` per section and sub-containers (name and counts), its sections included only when they fit, otherwise `truncated`; with `section` (`input`, `output`, `link`, `start`, `drop`), `offset` and `limit` (default 50, maximum 200, as the port listings), one page of entries with `total` and `truncated` |
| D13 | FMU paths in `get_assembly_json` (30 to 45 % of the volume) | **Names everywhere** in the result of the tool and of `assembly://current`, as the other tools; `save_as_json` still writes the complete file |

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

**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| `make_fmu()` (FMI-2 descriptor with given Real inputs and outputs); `make_large_assembly()`: nested assembly of the shape of the case study (`large_assembly.fmu` → `vehicle.fmu` → `level2.fmu`; FMUs `scenario`, `plant`, `control`, `carbody`, `stub`), 318 exposed inputs, 277 exposed outputs, 291 links, every `auto_*` off, root FMUs by absolute path; it holds nested `mt`, a step ratio of 100, a fan-out and a stub of constants. `measure_assembly()` serves it through a headless bridge whose `get_assembly_json` is replaced (the headless bridge is flat, D10) | `tests/_helpers/mcp_budget.py` |
| `test_the_large_assembly_is_consistent`: the JSON reads back as an `Assembly` unchanged, and every port it designates exists (in the FMU descriptor, or among the exposed ports of a sub-container). Budget tests of `get_assembly_json` and `assembly://current` on it, `xfail(strict=True)`, each checked to fail on its budget (`--runxfail`) | `tests/unit/test_assistant_budget.py` |

Baseline (characters; the absolute paths make it depend on the temporary directory, measured with the helper):

| Item | Characters | Budget |
|---|---|---|
| `get_assembly_json` on the large assembly | 56 512 | over (12 000) |
| Resource `assembly://current` on the large assembly (indented JSON) | 105 528 | over |
| Tool definitions (unchanged) | 15 664 | 16 000 |

**D9 investigation.** The rule engine can run without building: per node, an `FMUContainer` fed with the FMUs, the
explicit inputs, outputs and links, then `add_implicit_rule()`, returns the derived rules (`AutoWired`) without
writing any file and without touching the `AssemblyNode` (the write-back is done by `AssemblyNode.make_fmu`, not by
the engine). Measured: a few milliseconds on `tests/data/containers/arch`; 0.7 s for the two largest FMUs of the case
study (194 MB and 57 MB: `EmbeddedFMU` extracts the whole archive). **Limit**: a node that holds a sub-container
cannot load it, since the sub-container only exists once built: on `hierarchical.json`, the engine sees neither the
ports of `level1.fmu` nor the auto-links between it and `gain.fmu`. Taking those levels into account requires a
stand-in of the sub-container interface (its exposed ports, typed after the embedded ports), built bottom-up from the
dry run of the child. Decision **D9'** (§3): partial dry run, reported by an `info` finding.

Checks performed: full suite **2024 passed, 2 skipped, 2 xfailed**; ruff not available in the environment (not run).

*Commit message*: `Add a large nested assembly to the MCP budget fixtures (assembly_analysis phase 0)`

### Phase 1 — Assembly summary (A2, D7)

New module `assistant/analysis.py`, pure functions on the assembly JSON (both bridges produce it):

1. `summarize_assembly(assembly_json)`: for every node, recursively: name, options (`step_size`, `mt`,
   `sequential`, `profiling`, `auto_*`, `ts_multiplier`), FMUs (base names), sub-containers; counts of exposed
   inputs, outputs, links, start values, dropped ports.
2. Groups: exposed ports per (FMU, prefix), links per (source FMU, prefix, destination FMU, prefix), each with a
   `count` and at most 3 `examples`; at most 15 groups per list, with `truncated`, the elements alone in their
   group merged into `ungrouped`; sub-containers reduced beyond the result budget (D11).
3. FMUs designated by base name in the result (the JSON uses paths at the root level, names below).
4. Tests on `tests/data/containers/arch/{flat,hierarchical,nested}.json` and on the large assembly: structure,
   counts, grouping, bounds.

*Exit criterion*: the summary of the large assembly within the result budget; the counts equal to those of the JSON.

**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| New module, standard library only: `fmu_name()` (base name, both separators), `port_prefix()` (D7), `summarize_assembly()`: per container `name`, `options` (those of the JSON), `fmus`, `counts` (inputs, outputs, links, start values, dropped ports), `inputs`/`outputs`/`links` grouped (`total`, `truncated`, `groups` with `count` and `examples`, `ungrouped`), `containers`; `MAX_GROUPS` = 15, `MAX_EXAMPLES` = 3, `MAX_SUMMARY_SIZE` = 12 000 (D11) | `assistant/analysis.py` |
| Tests: prefixes and names; `flat`, `hierarchical`, `nested` fixtures; grouping (merge of the elements alone, order, bounds, renamed links); the large assembly within the budget with every count equal to the JSON; a tree of 13 containers reduced below the root | `tests/unit/test_assistant_analysis.py` |

Measured (characters of `json.dumps`): large assembly of the fixtures **4 946**; real `bug.fmu` **11 924**, not
reduced (149 228 for its `get_assembly_json`). The first version, with 30 groups per list and no merge, gave 19 169
on `bug.fmu` but 6 264 on the fixture: real names (`Tout`, `ratio1`, `HV_aux_current`...) form many small groups,
which the regular names of the fixture do not show; the bounds are therefore tested on a synthetic tree of irregular
names.

Checks performed: full suite **2042 passed, 2 skipped, 2 xfailed**; ruff not available in the environment (not run).

*Commit message*: `Summarise an assembly by container, FMU pair and port prefix (assembly_analysis phase 1)`

### Phase 2 — `get_assembly_json` paged by node (A1, D2, D5, D6)

1. `node` argument (D5) on the tool; behaviour without `node` as decided in D6; a `truncated` flag and the list of
   the sub-containers left out, so the model knows what to ask next.
2. Tool description: point to `analyze_assembly` for an overview, to `save_as_json` for the complete file.
3. The resource `assembly://current` follows the same rule (same function).
4. Tests: unknown node, ambiguous node, nested fixtures; the `xfail` of phase 0 removed.

*Exit criterion*: `get_assembly_json` on the large assembly within the budget, with and without `node`.

Items 2 and 4 adjusted: the pointer to `analyze_assembly` in the description waits for the tool (phase 4); D12 and
D13 taken at the start of the phase, after measuring that one level of `bug.fmu` is still over the budget.

**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| `find_container()` (D5: by name; unknown name → the known containers listed; ambiguous name → the paths of the candidates), `assembly_page()` (D6, D12, D13), `SECTIONS`; `MAX_SUMMARY_SIZE` renamed `MAX_RESULT_SIZE`, shared by the summary and the pages | `assistant/analysis.py` |
| `get_assembly_json(node, section, offset, limit)` served by `assembly_page`; `assembly://current` too (compact JSON instead of `indent=2`); `Offset`/`Limit` descriptions made generic (ports and entries); `analysis` imported at module level (standard library only) | `assistant/server.py` |
| `diagnose_assembly`: the note "FMUs appear here by *path*" replaced by how to read a large assembly | `assistant/knowledge.py` |
| Tests: whole small assembly with names; container by name; unknown and ambiguous containers; section paging; names in every section; large assembly: every view within the budget and every entry of every section reached by paging. Through the client: paging by container and section, resource equal to the tool, unknown container reported. Signature of the tool in `EXPECTED_TOOLS` | `tests/unit/test_assistant_analysis.py`, `tests/unit/test_assistant_server.py` |
| Budget: the two `xfail` removed; the views by container and a section page of the large assembly measured | `tests/_helpers/mcp_budget.py`, `tests/unit/test_assistant_budget.py` |

Measured (characters): large assembly of the fixtures, `get_assembly_json` **56 512 → 396** (root, truncated),
`vehicle.fmu` 384, `level2.fmu` 9 933 (sections included), a page of links 2 385; `assembly://current`
**105 528 → 444**. Real `bug.fmu`: root 519, every level under 520 (truncated), largest page of a section 7 181
(149 228 before). Tool definitions **15 664 → 15 987** (budget 16 000): the new descriptions were shortened, and the
shared `Offset`/`Limit` ones too, to stay within it; phase 4 has no margin left (D1).

Visible change for phase 6 (`CHANGELOG.md`, `ai-assistant.md`): `get_assembly_json` and `assembly://current`
designate the FMUs by name, and a large assembly comes one container at a time.

Checks performed: full suite **2058 passed, 2 skipped**; ruff not available in the environment (not run).

*Commit message*: `Page get_assembly_json by container and section (assembly_analysis phase 2)`

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

### Phase 4 — Port-level lint and the `analyze_assembly` tool (A3, A4, D1, D9, D9', D10)

1. Port-level rules, fed with the descriptions given by `bridge.list_fmu_ports(name)` (read once per FMU):

   | Rule | Severity | Detail |
   |---|---|---|
   | `unknown-port` | error | a linked, exposed or started port absent from the FMU |
   | `link-causality` | error | link source not an `output`, or destination not an `input` |
   | `link-type` | warning / error | type conversion (warning), or conversion refused by the container (error) |
   | `link-unit` | warning | linked ports with different units: the toolbox does not convert |
   | `dangling-input` | warning | an input neither linked nor exposed, without start value; the `auto_*` rules are evaluated by a dry run of the engine (D9) |
   | `auto-rules-partial` | info | a level holding a sub-container and an `auto_*` rule on: the ports of the sub-container are not evaluated by the dry run (D9') |
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
   known limits (D9', D10).
2. `CHANGELOG.md`: new tool, new prompt, `get_assembly_json` behaviour on large assemblies.
3. This plan moved to `docs/local/done/`.

*Commit message*: `Document the assembly analysis of the AI Assistant (assembly_analysis phase 6)`
