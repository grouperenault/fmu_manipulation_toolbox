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

1. **Rules** (proposal 2, with one matching criterion at a time) — the main tool for hundreds of ports;
2. **Manual** (proposal 1) — for the leftovers ("unmatched" ports of the rules tab are directly shown there).

Proposal 3 is kept as an optional later step (a tree mode of the manual lists), only if your FMUs use
hierarchical names. The window is pure GUI: the result is written into `WireItem.mappings` exactly like the
table does today, so neither the `Assembly` model, the JSON format nor the builder change.

### Mockup of the combined window (proposals 1 + 2)

The window is split vertically: the **tabs** on top, the **staged links** at the bottom (`QSplitter`, both parts
can be resized). The header and the staged links stay visible whatever the tab.

#### Tab "Rules" (opened by default)

One matching criterion at a time (decision 2026-10-12): the user picks a criterion, adjusts it, stages the good
suggestions, then goes on with another criterion, which only sees the ports still free. The order of the criteria
is the order in which the user applies them.

```
┌─ Link assistant — engine.fmu (A) ↔ ecu.fmu (B) ─────────────────────────────────────────┐
│ engine.fmu                                →  ecu.fmu                      [ A → B ▾ ]   │
│ Σ 412   ● 35   ○ 377                         Σ 380   ● 40   ○ 340                       │
│ ┌───────┬────────┐                                                                      │
│ │ Rules │ Manual │                                                                      │
│ ├───────┴────────┴────────────────────────────────────────────────────────────────────┐ │
│ │ Match by [Prefix/suffix ▾] ☑ ignore case… ☐ param.  Allow only: ☑ types ☐ units     │ │
│ │ Output: [engine.out.    ] … [suffix  ]  →  Input: [ecu.in.engine_ ] … [suffix  ]    │ │
│ ├─────────────────────────────────────────────────────────────────────────────────────┤ │
│ │ Suggestions: 172  ✔ 139 ⚠ 17 ✖ 16                     Show [All ▾] [Filter   ]      │ │
│ │ ☑ │ Output (A)           │ Type │ Input (B)              │ Type  │ Unit │ Status    │ │
│ │ ☑ │ engine.out.speed     │ Real │ ecu.in.engine_speed    │ Real  │ rpm  │ ✔         │ │
│ │ ☑ │ engine.out.torque    │ Real │ ecu.in.engine_torque   │ Int32 │ N.m  │ ⚠ lossy   │ │
│ │ ☐ │ engine.out.temp      │ Real │ ecu.in.engine_temp     │ Real  │ degC │ ✖ fed     │ │
│ │   │ …                    │      │                        │       │      │           │ │
│ │ [Check all ✔] [Uncheck all]                             [ Stage checked links ⇩ ]   │ │
│ └─────────────────────────────────────────────────────────────────────────────────────┘ │
├══════════════════════════════════════ splitter ═════════════════════════════════════════┤
│ Staged links: 386                             Show [All ▾]   Filter [             ]     │
│ Output (A)          │ Input (B)             │ Origin    │ Status                        │
│ engine.out.speed    │ ecu.in.engine_speed   │ prefix    │ ✔                             │
│ engine.out.torque   │ ecu.in.engine_torque  │ prefix    │ ⚠ Real → Int32 (lossy)        │
│ wheel.speed         │ ecu.in.wheel_speed    │ manual    │ ✔ array of 4                  │
│ …                   │                       │           │                               │
│ [Remove selected] [Remove All]   The 35 existing links of the wire are kept.            │
│                                                       [ Cancel ]  [ Apply 386 links ]   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

The criteria of **Match by**, all affected by **ignore case and separators** (checked by default):

| Criterion | Parameters | Example (case and separators ignored) |
|-----------|------------|---------------------------------------|
| Same name | — | `Throttle_Pos` → `throttle.pos` |
| Replace prefix / suffix | prefix and suffix of the output, replaced by those of the input | `engine.out.` → `ecu.in.engine_` |
| Regular expression | regex on the output name (`fullmatch`), input name with `\1`, `\2`… | `^sensor\.(\w+)\.(\w+)$` → `sensor_\2_\1` |
| Similar names | score threshold (1.00 to 0.50 by 0.05), the links found are ⚠ to be reviewed | `chassis.pressure` → `chassis.press` |

The **Run ▶** button is only shown when the last search took more than 0.3 s (see *Response time* below);
otherwise the suggestions are updated 250 ms after the last change.

#### Tab "Manual"

```
┌─ Link assistant — engine.fmu (A) ↔ ecu.fmu (B) ─────────────────────────────────────────┐
│ engine.fmu                                →  ecu.fmu                      [ A → B ▾ ]   │
│ Σ 412   ● 35   ○ 377                         Σ 380   ● 40   ○ 340                       │
│ ┌───────┬────────┐                                                                      │
│ │ Rules │ Manual │                                                                      │
│ ├───────┴────────┴─────────────────────────┬──────────────────────────────────────────┐ │
│ │ Filter [temp          ] [All types ▾]    │ Filter [temp          ] [All types ▾]    │ │
│ │ ☑ only free ports                        │ ☑ only free ports    ☐ show parameters   │ │
│ │ Name                │ Type │ Unit │ Desc.│ Name                │ Type │ Unit │ ...  │ │
│ │ ▶engine.out.temp_oil│ Real │ degC │ Oil t│ ▶ecu.in.oil_temp    │ Real │ degC │ ...  │ │
│ │ ▶engine.out.temp_h2o│ Real │ degC │ Coola│ ▶ecu.in.water_temp  │ Real │ degC │ ...  │ │
│ │  engine.out.temp_exh│ Real │ degC │ Exhau│  ecu.in.exhaust_temp│ Real │ K    │ ...  │ │
│ │  …                                       │  …                                       │ │
│ ├──────────────────────────────────────────┴──────────────────────────────────────────┤ │
│ │                                 [ Link selection ↓ ]                                │ │
│ │                        engine.out.temp_oil → ecu.in.oil_temp                        │ │
│ │                       engine.out.temp_h2o → ecu.in.water_temp                       │ │
│ │                  2 output(s) ↔ 2 input(s): paired in display order                  │ │
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
| Direction | Changing it searches the suggestions of the new direction; the staged links of the other direction are kept, and the staged list then shows a direction column, so both directions can be prepared in one session |
| Counters `Σ ● ○` below each FMU name | Σ total, ● used, ○ free ports (tooltip on each symbol): outputs linked on this wire (existing or staged links); inputs fed by a link of any wire of the node, an exposed input, or a staged link |
| Manual tab | Opens with "only free ports" checked; each list is below the name of its FMU in the header |
| Match by | One criterion at a time; the parameters of each criterion are kept while the window is open; any change of the criterion, its parameters, the options or the direction searches again 250 ms after the last change (or enables **Run**, see *Response time*) |
| Suggestions | Checked by default when ✔ or ⚠, unchecked when ✖; a tooltip on the status gives the reason; double-click on a row stages it; not searched again after a staging (the suggestions whose ports were just staged are removed, the check boxes of the others are kept) |
| Stage checked links | Moves the checked suggestions to the staged links; their ports are no longer free in either tab |
| Manual lists | Sortable columns, multi-selection (Shift / Ctrl), preview of the pairing before **Link selection** |
| Remove selected / Remove All | Remove staged links; the current criterion is searched again, so that the suggestions of the freed ports come back (the check boxes already set by the user are kept when the status of the suggestion did not change) |
| Staged links | Status recomputed on each change (e.g. two staged links on one input are both ✖ `duplicate target`); **Apply** is disabled while a ✖ link remains |
| Apply | Adds the staged links to `WireItem.mappings`, refreshes the Wire Details tabs and the wire, marks the assembly modified, closes the window |
| Cancel / closing the window | Asks for confirmation when links are staged; the wire is never modified |

#### Response time

Measured on the fictitious FMUs (one criterion on every port of the direction):

| Ports per FMU | Same name | Prefix / suffix | Regex | Similar names |
|---------------|-----------|-----------------|-------|---------------|
| 400 | < 1 ms | 1 ms | < 1 ms | 0.03 s |
| 1000 | 1 ms | 2 ms | < 1 ms | 0.08 s |
| 2000 | 3 ms | 5 ms | 1 ms | 0.2 s |
| 5000 | 7 ms | 12 ms | 4 ms | 0.7 s |

"Similar names" compared with `difflib` every output to every input: 5 s at 2000 ports (19 s with a threshold of
0.6). It now looks first for the inputs sharing the most 3-character fragments with the output (index, the
fragments found in more than 10 % of the inputs being ignored), and compares only the 20 best ones: 25 times
faster, same result at a threshold of 0.8 on 400 ports (264 of the 265 pairs of the exhaustive search).

To never freeze the window while typing: a search longer than 0.3 s stops the automatic update and shows the
**Run ▶** button; the automatic update comes back after a search shorter than 0.3 s.

## Decisions to take

| # | Question | Options | Decision |
|---|----------|---------|----------|
| 1 | Interface | P1 / P2 / P3 / P1+P2 (recommended) / P1+P2+P3 | P1 + P2 (Rules with one criterion at a time, Manual) (2026-10-12) |
| 2 | Where is the **Assistant…** button | Wire Details panel only / also context menu of a wire / also menu bar | Wire Details panel only (2026-10-12) |
| 3 | Window modality | Non-modal (graph visible, recommended) / modal | Non-modal (2026-10-12) |
| 4 | Directions handled at once | One direction at a time with a selector (recommended) / both directions in one run | One direction at a time with a selector; the staged links of both directions are kept (2026-10-12) |
| 5 | Rules of the first version | exact; ignore case and separators; prefix/suffix replace; regex rewrite; similarity score; same description; same unit | One criterion at a time among same name, prefix / suffix, regex, similar names; "ignore case and separators" is an option of every criterion (2026-10-12) |
| 6 | Similarity algorithm (if kept) | `difflib.SequenceMatcher` (stdlib, recommended) / token-based / other | `difflib.SequenceMatcher`, after a pre-filter on 3-character fragments (see *Response time*) (2026-10-12) |
| 7 | Type check | Block incompatible pairs and warn on lossy / warn only | Incompatible type ✖ (unchecking "Allow only: compatible types" makes it ⚠), lossy conversion ⚠ (2026-10-12) |
| 8 | Unit check | Required equality / warn only / ignored | Different unit ⚠ (checking "Allow only: same units" makes it ✖) (2026-10-12) |
| 9 | "Input already fed" detection scope | This wire only / every wire of the node + exposed inputs (recommended) | Every wire of the node + exposed inputs (2026-10-12) |
| 10 | One output to several inputs in the rules tab | Allowed (fan-out) / one suggestion per output | One suggestion per output in the Rules tab; fan-out in the Manual tab only (2026-10-12) |
| 11 | Parameters (`causality="parameter"`) as targets | Listed / hidden by default with a checkbox (recommended) / never | Hidden by default, with a check box (2026-10-12) |
| 12 | FMI-2 array aggregates | Treated as one port (as the table) / aggregates and elements both listed | Treated as one port, as the table (2026-10-12) |
| 13 | Persist rules | No / remembered per session / saved in a user settings file / exported with the JSON | Remembered for the session of the application (2026-10-12) |
| 14 | Existing **Auto-Connect** button | Kept as is / replaced by the assistant | Replaced by the assistant, which opens on "Same name" (2026-10-12) |
| 15 | MCP exposure of the matching engine (e.g. `suggest_links` tool) | No / later / in this plan | Later, not in this plan (2026-10-12) |
| 16 | Qt mockup of step 0: location and fate | Throw-away script, not committed / `tools/link_assistant_mockup.py` kept in the repository / start of the real window of step 2 | Start of the real window of step 2 (2026-10-11) |
| 17 | Update of the suggestions while typing | Yes / **Run** button | Yes, if there is no risk for the response time of the window (2026-10-12): automatic, and **Run** after a search longer than 0.3 s |

## Steps

Step 0 is a mockup used to take the decisions above, all taken on 2026-10-12. Steps 1 to 3 start from the code
written at step 0.

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
- whether the criterion editor is understandable without documentation (prefix vs regex);
- the size of the window on a laptop screen; the splitter between the tabs and the staged links;
- the answers to the decisions 1 to 15.

Result expected: the decisions table filled, the mockups and the behaviour table of this plan updated, the steps
below adjusted.

Commit message: `Add a first version of the link assistant window, with a mockup of two fictitious FMUs`

**Result:** written directly as the start of the real window (decision 16), not yet connected to the Wire Details
panel:

| File | Content |
|------|---------|
| `gui/fmucontainer/details/link_matching.py` | Matching engine without Qt (start of step 1): `PortInfo`, `Status`, `Checks`, `link_status` (input already fed, array size, conversion through `CONVERSION_FUNCTION` / `is_lossy`, unit), criteria `SameNameRule`, `AffixRule`, `RegexRule`, `SimilarityRule` (pre-filter on 3-character fragments), all with the option `ignore_case`, `suggest` with one criterion (an input proposed once, fed inputs proposed as ✖, a similar name below a score of 1 is ⚠), `staged_statuses` (two staged links on one input are ✖) |
| `gui/fmucontainer/details/link_assistant.py` | `LinkAssistantDialog(side_a, side_b, existing)`, non-modal, as the mockups above; it only knows `WireSide` (node name, `PortInfo` list, inputs fed outside of the wire) and the 4-tuples of `WireItem.mappings`; `applied(list)` gives the new 4-tuples |
| `gui/fmucontainer/details/link_assistant_demo.py` | `python -m fmu_manipulation_toolbox.gui.fmucontainer.details.link_assistant_demo [--ports N] [--seed S]`: the two fictitious FMUs (`engine.fmu` FMI 2, `ecu.fmu` FMI 3, every case of the table above, B → A commands included) and a main window standing for the Wire Details panel |
| `tests/unit/test_link_matching.py`, `tests/gui/test_link_assistant.py` | Criteria with and without `ignore_case`, statuses, update while typing, **Run** after a slow search, staging, manual pairing, both directions, Apply |

Measured: see *Response time*.

Changed after a first review (2026-10-12): the ordered list of rules is replaced by one criterion at a time,
"ignore case and separators" becoming an option of every criterion, and the suggestions are updated while typing.

Seen while building the mockup, to be confirmed by the user:

- the "similar names" rule gives false positives on generated names (`diag.intake_temperature` →
  `ecu.aux.intake2_temperature`): its links are ⚠ so that they are reviewed;
- `invalidateFilter` is deprecated since Qt 6.10: the window uses `beginFilterChange` / `endFilterChange` when
  available (PySide6 ≥ 6.9), the project still accepting PySide6 6.8.

Mockup validated by the user (2026-10-12); a few aesthetic adjustments remain, to be listed before step 3.

### Step 1 — Matching engine (no GUI)

New module `gui/fmucontainer/details/link_matching.py` (pure Python, no Qt, so it can be unit-tested and reused by
MCP later):

- `PortInfo` (name, causality, FMI version, FMI type, unit, description, is_aggregate);
- criteria (`Rule` classes): `SameNameRule`, `AffixRule` (prefix/suffix replace), `RegexRule` (rewrite of the
  source name), `SimilarityRule` (score threshold), each with the option "ignore case and separators";
- `suggest(outputs, inputs, rule, ignore_case, already_fed) -> list[Suggestion]` where `Suggestion` holds the pair,
  a score and a `status` (`ok`, `lossy`, `incompatible_type`, `unit_mismatch`, `already_fed`, `duplicate_target`);
- type compatibility through `FMI_TO_CONTAINER`, `CONVERSION_FUNCTION` and `is_lossy`.

Tests (`tests/unit/`): each criterion with and without "ignore case and separators", one target proposed twice,
statuses, a 2000 × 2000 port case in a reasonable time.

Commit message: `Complete the matching engine of the link assistant`

**Result:** the engine was written at step 0; this step completes it:

- `Status.codes`: stable codes of the reasons of a status (`already_fed`, `size_mismatch`, `incompatible_type`,
  `lossy`, `unit_mismatch`, `similar_name`, `duplicate_target`), next to the message shown to the user; several
  warnings give several codes (e.g. `lossy` + `unit_mismatch`);
- `PortInfo.container_type` handles an `Enumeration` as an integer (`Integer` / `Int32`), as the builder does
  (`EmbeddedFMU.port_attrs`); so Enumeration → Float64 is ⚠ `lossy`, like `integer32/real64` in
  `CONVERSION_FUNCTION`;
- `PortInfo.size` (number of elements of an array or of an FMI-2 aggregate) instead of an `is_aggregate` flag: two
  arrays of different sizes give ✖ `size_mismatch`;
- tests: status codes, Enumeration, and 2000 × 2000 ports with synthetic names for each criterion (expected pairs
  found, nothing wrong, < 5 s; "Similar names" takes 0.3 s).

### Step 2 — Assistant window: staging list and manual tab

`gui/fmucontainer/details/link_assistant.py` (written at step 0), connected to the graph:

- `LinkAssistantDialog(side_a, side_b, existing)`: header with the direction selector, staging list (model + status
  column computed by the engine), **Apply** / **Cancel**;
- **Manual** tab: two `QTableView` (name, type, unit, description) behind `QSortFilterProxyModel`, text filter,
  type filter, "hide linked / fed"; **Link selection** pairs n outputs with n inputs in display order, or one
  output with n inputs;
- **Apply** merges the staged links into `WireItem.mappings` (no duplicate), then reloads the Wire Details tabs and
  emits `changed` (dirty flag, wire redraw);
- **Assistant…** button in `WireDetailWidget`, **replacing Auto-Connect** (decision 14): it opens the assistant
  on the selected wire, on "Same name" (`_WireDirectionTab.auto_connect` and `_on_auto_connect` are removed);
- the parameters of the criteria and the option "ignore case and separators" are kept for the session of the
  application (decision 13), e.g. in class attributes of the dialog, not in a file;
- `WireSide` built from the `NodeItem` (`PortInfo` from `fmu_port_causality`, `fmu_port_type`,
  `fmu_port_details`, `fmu_array_aggregate_elements`), and `fed` from the other wires of the node and its exposed
  inputs (`user_exposed_inputs`);
- the aesthetic adjustments asked by the user after the mockup.

Tests (`tests/gui/`, with `qtbot` as `tests/gui/test_gui.py`): open on a wire, stage, apply, cancel leaves the wire
untouched, the direction selector, ports already fed by another wire are flagged.

Commit message: `Open the link assistant from the Wire Details panel, instead of Auto-Connect`

**Result:**

- `WireDetailWidget`: **Assistant…** replaces **Auto-Connect** (`_WireDirectionTab.auto_connect` and
  `_on_auto_connect` removed); one assistant at a time: the button raises the open assistant of the same wire, and
  closes the one of another wire (asking first when links are staged there);
- **Apply** adds the links to the wire it was opened on, even if another wire is now displayed; a link whose input
  was fed meanwhile on the wire is skipped (with a message); if the wire was deleted, nothing is added (message);
  then the panel is reloaded and `changed` marks the assembly modified;
- `wire_sides(wire)` (in `wire_detail.py`) builds the `WireSide` of both nodes: ports from `fmu_port_causality`,
  `fmu_port_type`, `fmu_port_details`, the new `fmu_port_size`; inputs fed by a link of any wire of the node or
  exposed (`user_exposed_inputs`); FMI-2 aggregates;
- `NodeItem.fmu_port_size`: number of elements of each port (product of the `<Dimension start>` of an FMI-3
  array, number of elements of an FMI-2 aggregate, 0 when a dimension is a structural parameter: no size check);
  cleared on *Replace FMU*; the configuration node has none (size 1);
- an FMI-2 aggregate and its elements are one input for the assistant (`link_matching.with_overlaps`): staging one
  takes the others, and two staged links on them are ✖ `duplicate_target`;
- the criteria and "ignore case and separators" are kept for the session (class attributes of `_CriterionEditor`);
  the assistant always opens on "Same name";
- tests `tests/gui/test_link_assistant_wire.py` on the FMUs of `tests/data` (bouncing ball, FMI-3 arrays and FMI-2
  aggregates of `tests/data/array`).

Not done in this step:

- the aesthetic adjustments: still to be listed by the user;
- the inputs fed through a **terminal** link (Terminals tab) are not counted as fed: the node only keeps the names of
  its terminals, not their member ports.

Seen while testing, not related to this plan: when `tests/gui` runs **before** `tests/unit` (not the order of
`pytest.ini`), 88 unit tests fail on `RuntimeError: Internal C++ object (LogWidget) already deleted`: a GUI test
leaves a `LogWidget` handler on a logger.

### Step 3 — Rules tab

- criterion editor (**Match by**, parameters of the criterion, "ignore case and separators"), update while typing,
  **Run** after a slow search;
- suggestion table with check boxes, filter, counters (✔ / ⚠ / ✖, unmatched outputs / inputs), **Check all ✔**;
- checked suggestions go to the staging list; "unmatched" counters link to the manual tab pre-filtered.

Tests: the regex criterion on a generated pair of FMUs (or on `tests/data` FMUs), checking / unchecking, interplay with
the manual tab.

Commit message: `Link the unmatched ports of the Rules tab to the Manual tab of the link assistant`

**Result:** the Rules tab was written at step 0 (criterion editor, update while typing, **Run** after a slow
search, suggestion table, counters, **Check all ✔** on the rows shown, staging). This step adds:

- (removed afterwards at the request of the user, see *Look and feel adjustments*, point 15) the counter
  "unmatched: N outputs / M inputs" is a link: it opens the Manual tab with the new check box "only
  ports without a suggestion in the Rules tab", which hides the ports having a suggestion (the elements of a
  suggested FMI-2 aggregate included); the lists then show exactly the N outputs and M inputs of the counter;
- the "Origin" column of the staged links is wider ("prefix / suffix" was cut);
- tests (`tests/gui/test_link_assistant.py`): the regex criterion (valid, then invalid: no suggestion, no
  exception), checking / unchecking (**Check all** on a filtered table), the unmatched counter and the Manual tab,
  a manual link removing the suggestions of its ports.

### Look and feel adjustments (asked by the user after step 3, 2026-10-12)

| # | Request | Done |
|---|---------|------|
| 1 | The button is labelled "Link Assistant" instead of "Assistant…" | `WireDetailWidget` |
| 2 | Same size for the buttons, aligned as much as possible | One width for every button of the assistant (the widest text, "Apply 99999 links" included) and one for every button of the Wire Details panel (tabs included); the staged links panel takes the inset of the frame of the tabs, so that tables and buttons line up exactly (left and right edges); `⇩` replaced by `↓`, drawn as an odd glyph by macOS |
| 3 | Artefact on the check box "only ports without a suggestion in the Rules tab" | Not reproduced (offscreen nor native macOS rendering); the check box was the only one stretched over the whole width of the tab: now in a row with a stretch, as the other check boxes. To be checked by the user |
| 4 | Suggestions: no space between the numbers and the symbols | The spacing depended on the width of the spaces of the font: each counter is now a label of its own (`_Summary`), in the color of its status, for the suggestions and for the staged links |

| 5 | "Remove selected" and "Clear" (renamed "Remove All") do not search the current criterion again | Both search it again (or, after a slow search, ask for **Run**); on every new search, a suggestion already there keeps its check box unless its status changed |

| 6 | Same size and style for the popup menus as the rest of the interface | The combo boxes use a `QListView`, styled by `gui/style.py` (`QComboBox QAbstractItemView`, as the menus of the application: dark list, selection `#4571a4`); one width for all of them |
| 7 | Header: FMU names larger, with an arrow: `model1.fmu → model2.fmu` | Names with the class `title` of `gui/style.py`, in the order of the direction (source → target); the direction selector on the right. The rule `QLabel.title` was ignored by Qt (`font: 14pt bold` instead of `font: bold 14pt`): fixed, which also makes bold the titles of FMU Tool and FMU Editor (user's choice) |
| 8 | The counters (outputs, linked, inputs, fed) below | Each one below the name of its FMU |
| 9 | Rules tab: same height and style for the text fields and the score selector | One height for the buttons, combo boxes and text fields; the score is a combo box (1.00 to 0.50 by 0.05) instead of a spin box drawn by the platform |
| 10 | "Match by" prefix or regex: the labels A and B are misleading in the direction B → A | Labels "Output:" and "Input:" (and placeholders "prefix", "suffix", "regex on the output name", "input name"): they hold whatever the direction |

| 11 | Use the existing `gui/style.py` for homogeneity | No style nor color defined in the assistant: `gui/style.py` gets `QLineEdit[invalid="true"]` (invalid regex), `QLabel.status_ok / status_warning / status_error` and `status_color` (warning and error are the colors of `log_color`) |

| 12 | Less space between the FMU names and the counters | No vertical spacing in the header |
| 13 | The label "Direction" is superfluous | Removed: the selector `A → B` / `B → A` stays alone on the right |
| 14 | Same style as the rest of the application for the popups and the score selector | Every selector (direction, criterion, score, types, "Show") is a push button of class `quit` opening a menu of exclusive checkable actions (`_MenuSelector`), as "Configuration" of the Container Builder and `FilterWidget` of FMU Tool; one width for all of them, from their longest item; the combo box rules added before to `gui/style.py` are removed |
| 15 | The link "unmatched …" is not relevant | Removed; the check box "only ports without a suggestion in the Rules tab" of the Manual tab is kept (it works on its own) |
| 16 | The check boxes "compatible type", "same unit", "parameters as targets" after "ignore case and separators" | One row: Match by, ignore case and separators, Errors (✖): compatible type, same unit, parameters as targets, and **Run** on the right; the separators ( . _ - [ ] ) moved to the tooltip of "ignore case and separators" |

| 17 | The check marks in the popup menus are misleading: one choice only | The items of the menus are not checkable any more; the current one is in bold. The blue style of the buttons is kept |
| 18 | What does "Errors (✖)" mean? Replace it with "Allow only:"? | Yes: "Allow only: ☑ compatible types ☐ same units" (checked: the difference is ✖ and blocks **Apply**; unchecked: it is ⚠ — in the tooltips). "parameters as targets" is not a restriction: it moves before "Allow only:" |
| 19 | Same space between the check boxes, the label next to its box | `_OPTION_SPACING` (24 px) between every option of a row, Rules and Manual tabs |

| 20 | Rules tab: the criterion selector aligned with the score selector | "Match by" and the first label of the parameters of each criterion ("Output:", "score ≥") have one width, and both rows one spacing: the selector of the criterion, the score selector and the text fields start at the same position |
| 21 | Manual tab: no counter in the name of the tab | "Manual" |
| 22 | The FMU names of the header aligned with the lists of ports | The header and the Manual tab are made of the same two halves (`_halves`): each name is above the list of its ports, the arrow at the end of the left half, the direction selector at the right of the right half (it did not have to move above). The splitter between the two lists is replaced by these fixed halves, so that the alignment holds |
| 23 | The check box "only ports without a suggestion" is superfluous | Removed (with the filter on the suggested ports) |
| 24 | The labels "Outputs of …" / "Inputs of …" are superfluous, the names of the header being aligned | Removed |

| 25 | Manual tab: center "Link selection" | The button links the left list to the right one: centered below them (exactly between the two lists), the preview of the pairing centered below it |

| 26 | Rules tab: the duration of the search "(0.00 s)" is useless for the user | No longer shown; the duration is still measured, only to stop the update while typing and show **Run** after a search longer than 0.3 s (user's choice: keep this safeguard) |

| 27 | Symbols for the counters of the header (total, linked, fed, free) | `Σ 400   ● 159   ○ 241` (Σ total, ● linked outputs / fed inputs, ○ free), one label per counter with a tooltip (`_PortCounters`); symbols of Verdana, no emoji (drawn differently on each platform) |

| 28 | Same width for the tabs "Rules" and "Manual" | New class `QTabWidget.equal_tabs` in `gui/style.py` (`min-width: 120px` of the tabs), given to the tabs of the assistant and, at the request of the user, to those of the Wire Details panel (A → B, B → A, Terminals) |

Commit message: `Polish the look of the link assistant`

### Step 4 — (optional, decision 1) Tree mode

Not retained (user, 2026-10-12).


Tree view of the manual lists split on a separator; drag of a sub-tree onto a sub-tree stages the links of the
leaves having the same relative name.

Commit message: `Add the hierarchical mode to the link assistant`

### Step 5 — User documentation

- `docs/user-guide/fmucontainer/gui-usage.md`, section *Wire Details*: the **Assistant…** button (instead of
  **Auto-Connect**, also in the tip "Auto-Connect"), the two tabs, the criteria, the statuses, screenshots;
- `docs/help/troubleshooting.md`: the step using **Auto-Connect** after a *Replace FMU* now uses the assistant;
- `CHANGELOG.md`;
- ROADMAP: check "Efficient assistant to connect 2 FMUs"; move this plan to `docs/local/done`.

Commit message: `Document the link assistant of the Container Builder`
