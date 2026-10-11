# Link assistant for the wires of the Container Builder

ROADMAP: "Efficient assistant to connect 2 FMUs".

## Context

When a wire is selected, `WireDetailWidget` (`gui/fmucontainer/details/wire_detail.py`) shows three tabs
(`A → B`, `B → A`, `Terminals`). A direction tab (`_WireDirectionTab`) is a 2-column table; each link is created
one at a time: **Add link**, then a popup (`_PortListSelectorDialog`) for the output, then another for the input.
The only bulk helpers are:

| Helper | Limit |
|--------|-------|
| **Auto-Connect** | Exact same name only, both directions at once, no preview, no type check |
| **Import / Export** CSV | Requires an external tool to build the list |

With FMUs of several hundreds of variables, the user typically faces names that match *after a transformation*
(prefix / suffix, separator `.` vs `_`, case, bus path such as `engine.out.speed` → `ecu.in.engine_speed`), and
needs to see which ports are still free.

What the GUI already knows about each port (`NodeItem`, `graph/node.py`), usable by the assistant:

| Data | Source |
|------|--------|
| Name, causality | `fmu_output_names`, `fmu_input_names`, `fmu_port_causality` |
| FMI type | `fmu_port_type` (`Real`, `Float64`, …); container type via `container.types.FMI_TO_CONTAINER` |
| Unit, variability, description | `fmu_port_details` |
| FMI-2 array aggregates | `fmu_array_aggregate_elements` |
| Existing links | `WireItem.mappings` of every wire of the node |

Constraints of the builder (`container/builder.py`, `container/types.py`) the assistant can check *before* the
build:

- an input is fed only once (`check_not_fed`): by one link, *or* exposed as container input, *or* … — a second
  feeder is an error at build time;
- an output can feed several inputs (fan-out);
- different types need an entry of `CONVERSION_FUNCTION`; `is_lossy()` tells the narrowing ones.

## Interface proposals

All proposals share the same frame: a **non-modal window** (`QDialog`) opened by a new **Assistant…** button in
the Wire Details panel, working on the wire currently selected, with a *direction* selector (A → B / B → A),
a **staging list** of proposed links and **Apply** / **Cancel** buttons. Nothing is written into the wire before
**Apply**, so the assistant is free to experiment.

### Proposal 1 — Two filtered lists, manual pairing

```
┌─ Link assistant — engine.fmu (A) → ecu.fmu (B) ─────────────── [A → B ▾] ─┐
│ Outputs of A                         │ Inputs of B                        │
│ [filter: speed        ] [Real ▾]     │ [filter: speed       ] [Real ▾]    │
│ [x] hide already linked              │ [x] hide already fed               │
│ ┌──────────────────────────────────┐ │ ┌────────────────────────────────┐ │
│ │ engine.out.speed      Real  rpm  │ │ │ ecu.in.engine_speed  Real rpm  │ │
│ │ engine.out.speed_ref  Real  rpm  │ │ │ ecu.in.speed_target  Real rpm  │ │
│ │ wheel.speed[1..4]     Real  m/s  │ │ │ ecu.in.wheel_speed   Real m/s  │ │
│ └──────────────────────────────────┘ │ └────────────────────────────────┘ │
│        [ Link selection ⇩ ]  (pairs the n selected outputs with the n     │
│                               selected inputs, in display order; 1 → n)   │
├───────────────────────────────────────────────────────────────────────────┤
│ Staged links (3)                                                          │
│  ✔ engine.out.speed      → ecu.in.engine_speed                            │
│  ⚠ engine.out.torque     → ecu.in.torque_i32     Real→Int32 (lossy)       │
│  ✖ engine.out.temp       → ecu.in.temp           input already fed        │
│                                         [Remove] [Clear]  [Cancel][Apply] │
└───────────────────────────────────────────────────────────────────────────┘
```

- Fast for a few tens of links, easy to understand.
- Still one action per small group: does not scale to hundreds when names differ.

### Proposal 2 — Matching rules and suggestion table

```
┌─ Link assistant — engine.fmu (A) → ecu.fmu (B) ─────────────── [A → B ▾] ─┐
│ Rules (applied in order, first match wins)                                │
│  [x] Exact name                                                           │
│  [x] Ignore case and separators ( . _ - [ ] )                             │
│  [x] Rewrite A name: regex [^engine\.out\.(.*)$ ] → [ecu.in.engine_\1 ]   │
│  [ ] Similar names (score ≥ [0.80])                                       │
│  [x] Same unit required        [x] Compatible type required               │
│                                                    [+ rule] [Run ▶]       │
├───────────────────────────────────────────────────────────────────────────┤
│ Suggestions: 412 found — 398 ✔  10 ⚠  4 ✖      filter: [            ]     │
│ ☑ │ Output (A)            │ Input (B)              │ Rule    │ Status     │
│ ☑ │ engine.out.speed      │ ecu.in.engine_speed    │ regex   │ ✔          │
│ ☑ │ engine.out.torque     │ ecu.in.engine_torque   │ regex   │ ⚠ lossy    │
│ ☐ │ engine.out.temp       │ ecu.in.engine_temp     │ regex   │ ✖ fed      │
│ ☐ │ engine.out.pres       │ ecu.in.press  (0.83)   │ similar │ ? check    │
│                     [Check all ✔] [Uncheck all]  unmatched: 37 out / 12 in│
│                                                           [Cancel][Apply] │
└───────────────────────────────────────────────────────────────────────────┘
```

- Scales to hundreds of ports: one rule may produce hundreds of links, reviewed then applied in one click.
- Generalises today's **Auto-Connect** (= rule "Exact name").
- Needs some knowledge of regular expressions for the rewrite rule (a simpler *prefix/suffix replace* rule can
  cover most cases without regex).

### Proposal 3 — Tree by name hierarchy, sub-tree to sub-tree

```
┌─ Link assistant — engine.fmu (A) → ecu.fmu (B) ─────────────── [A → B ▾] ─┐
│ Outputs of A                        │ Inputs of B                         │
│ ▾ engine                            │ ▾ ecu                               │
│   ▾ out          (24 / 3 linked)    │   ▾ in            (40 / 3 fed)      │
│       speed                         │       engine_speed                  │
│       torque                        │     ▸ engine      (12)  ◀── drop    │
│     ▸ thermal    (8)   ── drag ──▶  │     ▸ thermal     (8)               │
│   ▸ diag         (60)               │   ▸ diag          (55)              │
├─────────────────────────────────────┴─────────────────────────────────────┤
│ Drop "engine.out.thermal" on "ecu.in.thermal": 7 of 8 leaves match by     │
│ relative name → staged.                                                   │
│ Staged links …                                            [Cancel][Apply] │
└───────────────────────────────────────────────────────────────────────────┘
```

- Very efficient for structured names (Modelica-like, bus signals): one drag connects a whole sub-system.
- Useless for flat names; tree splitting depends on a separator to choose.

### Recommendation

A single window with **two tabs sharing one staging list and one status column**:

1. **Rules** (proposal 2) — the main tool for hundreds of ports;
2. **Manual** (proposal 1) — for the leftovers ("unmatched" ports of the rules tab are directly shown there).

Proposal 3 is kept as an optional later step (a tree mode of the manual lists), only if your FMUs use
hierarchical names. The window is pure GUI: the result is written into `WireItem.mappings` exactly like the
table does today, so neither the `Assembly` model, the JSON format nor the builder change.

### Mockup of the combined window (proposals 1 + 2)

The window is split vertically: the **tabs** on top, the **staged links** at the bottom (`QSplitter`, both parts
can be resized). The header and the staged links stay visible whatever the tab.

#### Tab "Rules" (opened by default)

```
┌─ Link assistant — engine.fmu (A) ↔ ecu.fmu (B) ─────────────────────────────────────────┐
│ Direction [ A → B ▾ ]       A: 412 outputs, 35 linked       B: 380 inputs, 40 fed       │
│ ┌───────┬────────────────┐                                                              │
│ │ Rules │ Manual (37│12) │  ← ports still free on each side (A│B)                       │
│ ├───────┴────────────────┴────────────────────────────────────────────────────────────┐ │
│ │ Rules — applied in order, the first rule matching a port wins                       │ │
│ │ ☑ 1. Exact name                                                         [▲][▼][✕]   │ │
│ │ ☑ 2. Ignore case and separators ( . _ - [ ] )                           [▲][▼][✕]   │ │
│ │ ☑ 3. Replace prefix  A:[engine.out.    ] → B:[ecu.in.engine_ ]          [▲][▼][✕]   │ │
│ │ ☐ 4. Regex           A:[^(.*)_degC$    ] → B:[\1_temp        ]          [▲][▼][✕]   │ │
│ │ ☐ 5. Similar names   score ≥ [0.80]                                     [▲][▼][✕]   │ │
│ │ [+ Add rule ▾]     Checks: ☑ compatible type  ☐ same unit               [ Run ▶ ]   │ │
│ ├─────────────────────────────────────────────────────────────────────────────────────┤ │
│ │ Suggestions: 398   ✔ 384  ⚠ 10  ✖ 4         Show [All ▾]   Filter [             ]   │ │
│ │ ☑ │ Output (A)          │ Type │ Input (B)             │ Type  │ Rule │ Status      │ │
│ │ ☑ │ engine.out.speed    │ Real │ ecu.in.engine_speed   │ Real  │ 3    │ ✔           │ │
│ │ ☑ │ engine.out.torque   │ Real │ ecu.in.engine_torque  │ Int32 │ 3    │ ⚠ lossy     │ │
│ │ ☐ │ engine.out.temp     │ Real │ ecu.in.engine_temp    │ Real  │ 3    │ ✖ fed       │ │
│ │ ☑ │ Throttle_Pos        │ Real │ throttle.pos          │ Real  │ 2    │ ✔           │ │
│ │   │ …                   │      │                       │       │      │             │ │
│ │ [Check all ✔] [Uncheck all]                             [ Stage checked links ⇩ ]   │ │
│ └─────────────────────────────────────────────────────────────────────────────────────┘ │
├══════════════════════════════════════ splitter ═════════════════════════════════════════┤
│ Staged links: 386                             Show [All ▾]   Filter [             ]     │
│ Output (A)          │ Input (B)             │ Origin │ Status                           │
│ engine.out.speed    │ ecu.in.engine_speed   │ rule 3 │ ✔                                │
│ engine.out.torque   │ ecu.in.engine_torque  │ rule 3 │ ⚠ Real → Int32 (lossy)           │
│ wheel.speed         │ ecu.in.wheel_speed    │ manual │ ✔ aggregate (4 elements)         │
│ …                   │                       │        │                                  │
│ [Remove selected] [Clear]        The 35 existing links of the wire are kept.            │
│                                                       [ Cancel ]  [ Apply 386 links ]   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Tab "Manual"

```
┌─ Link assistant — engine.fmu (A) ↔ ecu.fmu (B) ─────────────────────────────────────────┐
│ Direction [ A → B ▾ ]       A: 412 outputs, 35 linked       B: 380 inputs, 40 fed       │
│ ┌───────┬────────────────┐                                                              │
│ │ Rules │ Manual (37│12) │                                                              │
│ ├───────┴────────────────┴──────────────────┬─────────────────────────────────────────┐ │
│ │ Outputs of A                              │ Inputs of B                             │ │
│ │ Filter [temp         ]  Type [All ▾]      │ Filter [temp         ]  Type [All ▾]    │ │
│ │ ☑ only free ports                         │ ☑ only free ports  ☐ show parameters    │ │
│ │ Name                │ Type │ Unit │ Desc. │ Name                │ Type │ Unit │ ... │ │
│ │▶engine.out.temp_oil │ Real │ degC │ Oil t │▶ecu.in.oil_temp     │ Real │ degC │ ... │ │
│ │▶engine.out.temp_h2o │ Real │ degC │ Coola │▶ecu.in.water_temp   │ Real │ degC │ ... │ │
│ │ engine.out.temp_exh │ Real │ degC │ Exhau │ ecu.in.exhaust_temp │ Real │ K    │ ... │ │
│ │ …                   │      │      │       │ …                   │      │      │     │ │
│ ├───────────────────────────────────────────┴─────────────────────────────────────────┤ │
│ │ Preview: engine.out.temp_oil → ecu.in.oil_temp                                      │ │
│ │          engine.out.temp_h2o → ecu.in.water_temp                                    │ │
│ │ 2 outputs ↔ 2 inputs: paired in display order               [ Link selection ⇩ ]    │ │
│ └─────────────────────────────────────────────────────────────────────────────────────┘ │
├══════════════════════════════════════ splitter ═════════════════════════════════════════┤
│ Staged links: 388   (same list as in the "Rules" tab)                                   │
│ …                                                                                       │
│                                                       [ Cancel ]  [ Apply 388 links ]   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

`▶` marks the selected rows. With 1 output and n inputs selected, the output feeds every selected input
(fan-out); any other unequal count disables **Link selection**.

#### Behaviour

| Element | Behaviour |
|---------|-----------|
| Direction | Changing it empties the suggestions; the staged links of the other direction are kept, and the staged list then shows a direction column, so both directions can be prepared in one session |
| Counters `A: … linked`, `B: … fed` | Count the existing links of every wire of the node, the exposed inputs, and the staged links |
| `Manual (37│12)` | Outputs of A / inputs of B still free; the tab opens with "only free ports" checked |
| Rules | Edited in place; **Run** recomputes the suggestions; `[▲][▼]` change the order; `[+ Add rule ▾]` lists the rule kinds |
| Suggestions | Checked by default when ✔ or ⚠, unchecked when ✖; a tooltip on the status gives the reason; double-click on a row stages it |
| Stage checked links | Moves the checked suggestions to the staged links; their ports are no longer free in either tab |
| Manual lists | Sortable columns, multi-selection (Shift / Ctrl), preview of the pairing before **Link selection** |
| Staged links | Status recomputed on each change (e.g. two staged links on one input are both ✖ `duplicate target`); **Apply** is disabled while a ✖ link remains |
| Apply | Adds the staged links to `WireItem.mappings`, refreshes the Wire Details tabs and the wire, marks the assembly modified, closes the window |
| Cancel / closing the window | Asks for confirmation when links are staged; the wire is never modified |

## Decisions to take

| # | Question | Options | Decision |
|---|----------|---------|----------|
| 1 | Interface | P1 / P2 / P3 / P1+P2 (recommended) / P1+P2+P3 | |
| 2 | Where is the **Assistant…** button | Wire Details panel only / also context menu of a wire / also menu bar | |
| 3 | Window modality | Non-modal (graph visible, recommended) / modal | |
| 4 | Directions handled at once | One direction at a time with a selector (recommended) / both directions in one run | |
| 5 | Rules of the first version | exact; ignore case and separators; prefix/suffix replace; regex rewrite; similarity score; same description; same unit | |
| 6 | Similarity algorithm (if kept) | `difflib.SequenceMatcher` (stdlib, recommended) / token-based / other | |
| 7 | Type check | Block incompatible pairs and warn on lossy / warn only | |
| 8 | Unit check | Required equality / warn only / ignored | |
| 9 | "Input already fed" detection scope | This wire only / every wire of the node + exposed inputs (recommended) | |
| 10 | One output to several inputs in the rules tab | Allowed (fan-out) / one suggestion per output | |
| 11 | Parameters (`causality="parameter"`) as targets | Listed / hidden by default with a checkbox (recommended) / never | |
| 12 | FMI-2 array aggregates | Treated as one port (as the table) / aggregates and elements both listed | |
| 13 | Persist rules | No / remembered per session / saved in a user settings file / exported with the JSON | |
| 14 | Existing **Auto-Connect** button | Kept as is / replaced by the assistant | |
| 15 | MCP exposure of the matching engine (e.g. `suggest_links` tool) | No / later / in this plan | |
| 16 | Qt mockup of step 0: location and fate | Throw-away script, not committed / `tools/link_assistant_mockup.py` kept in the repository / start of the real window of step 2 | |

## Steps

Step 0 is a mockup used to take the decisions above. The steps 1 to 5 assume the recommended options (P1 + P2,
non-modal, one direction at a time); they will be adjusted to the decisions before implementation.

### Step 0 — Qt mockup with two fictitious FMUs

Goal: test the interface (proposals 1 + 2, mockup above) with realistic volumes **before** writing the real code,
and fill the decisions table from what is seen. No change to the application.

Standalone script (location: decision 16), run with `python <script> [--ports N]`, using PySide6 and the
stylesheet of the application (`gui.style.gui_style`) so that it looks like the Container Builder:

- **Two fictitious FMUs generated in memory** (no `.fmu` file, no `NodeItem`), fixed random seed so that every run
  is identical. `--ports N` sets the number of ports per side (default 400; 100 / 1000 / 2000 to test the
  responsiveness). The generated names cover every case the assistant must handle:

  | Case | A (outputs) | B (inputs) |
  |------|-------------|------------|
  | Same name | `vehicle.speed` | `vehicle.speed` |
  | Case and separators | `Throttle_Pos` | `throttle.pos` |
  | Prefix to replace | `engine.out.torque` | `ecu.in.engine_torque` |
  | Regex rewrite | `oil_degC` | `oil_temp` |
  | Similar names | `engine.out.pres` | `ecu.in.engine_press` |
  | Lossy / incompatible type | `Real` | `Int32` / `String` |
  | Different units | `degC` | `K` |
  | FMI-2 array aggregate | `wheel.speed[1]` … `[4]` | `wheel_speed` (FMI-3 array) |
  | Input already fed by another wire | — | marked as fed |
  | Parameters | — | `causality="parameter"` |
  | Without counterpart | some outputs | some inputs |

  Each port has a type, a unit and a description, as `NodeItem.fmu_port_type` / `fmu_port_details`.
- **The window of the mockup** (header, tabs Rules and Manual, staged links, behaviour table above), with a
  simplified matching written in the script (rules exact, case and separators, prefix, regex, `difflib`
  similarity; status from the generated data). **Apply** prints the staged links on the console instead of
  writing a wire.
- An **Assistant…** button in a small main window that mimics the Wire Details panel, to also judge the opening of
  the window (modal or not, size, position).

What to check with the mockup, together with the user:

- readability and speed of the tables with 400 / 1000 / 2000 ports (filtering, sorting, **Run**);
- the time needed to link ~300 ports, and the number of clicks, compared with the current table;
- whether the rule editor is understandable without documentation (prefix vs regex);
- the size of the window on a laptop screen; the splitter between the tabs and the staged links;
- the answers to the decisions 1 to 15.

Result expected: the decisions table filled, the mockups and the behaviour table of this plan updated, the steps
below adjusted.

Commit message (if the mockup is kept in the repository, decision 16): `Add a Qt mockup of the link assistant`

### Step 1 — Matching engine (no GUI)

New module `gui/fmucontainer/details/link_matching.py` (pure Python, no Qt, so it can be unit-tested and reused by
MCP later):

- `PortInfo` (name, causality, FMI version, FMI type, unit, description, is_aggregate);
- `Rule` classes: `ExactRule`, `NormalizedRule` (case + separators), `AffixRule` (prefix/suffix replace),
  `RegexRule` (rewrite of the source name), `SimilarityRule` (score threshold);
- `suggest(outputs, inputs, rules, already_fed) -> list[Suggestion]` where `Suggestion` holds the pair, the rule,
  a score and a `status` (`ok`, `lossy`, `incompatible_type`, `unit_mismatch`, `already_fed`, `duplicate_target`);
- type compatibility through `FMI_TO_CONTAINER`, `CONVERSION_FUNCTION` and `is_lossy`.

Tests (`tests/unit/`): each rule, rule order (first match wins), one target proposed twice, statuses, a
500 × 500 port case in a reasonable time.

Commit message: `Add the matching engine of the link assistant`

### Step 2 — Assistant window: staging list and manual tab

New `gui/fmucontainer/details/link_assistant.py`:

- `LinkAssistantDialog(wire, direction)`: header with the direction selector, staging list (model + status
  column computed by the engine), **Apply** / **Cancel**;
- **Manual** tab: two `QTableView` (name, type, unit, description) behind `QSortFilterProxyModel`, text filter,
  type filter, "hide linked / fed"; **Link selection** pairs n outputs with n inputs in display order, or one
  output with n inputs;
- **Apply** merges the staged links into `WireItem.mappings` (no duplicate), then reloads the Wire Details tabs and
  emits `changed` (dirty flag, wire redraw);
- **Assistant…** button added to `WireDetailWidget`.

Tests (`tests/gui/`, with `qtbot` as `tests/gui/test_gui.py`): open on a wire, stage, apply, cancel leaves the wire
untouched, the direction selector, ports already fed by another wire are flagged.

Commit message: `Add the link assistant window with its manual pairing tab`

### Step 3 — Rules tab

- Rule list editor (enable, parameters, order, add / remove), **Run**;
- suggestion table with check boxes, filter, counters (✔ / ⚠ / ✖, unmatched outputs / inputs), **Check all ✔**;
- checked suggestions go to the staging list; "unmatched" counters link to the manual tab pre-filtered.

Tests: the regex rule on a generated pair of FMUs (or on `tests/data` FMUs), checking / unchecking, interplay with
the manual tab.

Commit message: `Add the rule-based suggestions to the link assistant`

### Step 4 — (optional, decision 1) Tree mode

Tree view of the manual lists split on a separator; drag of a sub-tree onto a sub-tree stages the links of the
leaves having the same relative name.

Commit message: `Add the hierarchical mode to the link assistant`

### Step 5 — User documentation

- `docs/user-guide/fmucontainer/gui-usage.md`, section *Wire Details*: the **Assistant…** button, the two tabs,
  the rules, the statuses, screenshots;
- `CHANGELOG.md`;
- ROADMAP: check "Efficient assistant to connect 2 FMUs"; move this plan to `docs/local/done`.

Commit message: `Document the link assistant of the Container Builder`
