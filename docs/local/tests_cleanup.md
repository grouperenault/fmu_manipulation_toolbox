# Clean-up of the test suite

## Context

The layout of `tests/` (`unit/`, `integration/`, `gui/`, markers, `_helpers/`) is sound. The complexity comes from
the traces left by the plans now archived in `docs/local/done/` (`refactoring.md`, `container.md`, `fmuport.md`,
`mcp_audit.md`, `mcp_optimize.md`, `assembly_analysis.md`):

- docstrings and section titles that describe *when* a test was written ("phase 2 of `refactoring.md`", "audit
  finding B3") instead of *what* it checks;
- "Migrated from the legacy `test_suite.py`" in 9 modules, although that file is gone;
- scaffolding that was only useful during a plan (the `xfail`/`OVER_BUDGET` machinery of the MCP budget tests);
- the reference tests built as a safety net for the refactorings (`integration/test_operations_characterization.py`
  with its 48 reference sets in `tests/data/refactoring/`, `integration/test_container_golden.py`);
- `unit/test_assistant_server.py`, 1 322 lines and 83 tests, 17 % of the test code.

## Decisions (2026-10-11)

| # | Question | Decision |
|---|----------|----------|
| 1 | Scope | Comments (A), temporary code (B), rename/split (C), reference tests (D) |
| 2 | Reference tests (characterization + golden) | Decide after an analysis of their overlap (step 1); ask the user before any removal |
| 3 | Defect / finding identifiers (D1…D14, I3, B3, C8, …) in comments | Remove them: the comment describes the behaviour itself, no reference to `docs/local/done/` |
| 4 | Split of `test_assistant_server.py` | 2 to 3 files |
| 5 | `PUBLIC_NAMES` of `test_container_internals.py` | Keep, presented as the public API of the `container` package |
| 6 | New name of `tests/data/refactoring/` | Chosen after the analysis of step 1 (the directory may disappear) |
| 7 | Expected tool/resource inventories of the MCP server | Keep, presented as the published MCP contract (any change must be deliberate) |
| 8 | Local hygiene (`tests/tmp`, `htmlcov`, `.coverage`, `.DS_Store`) | Out of scope |
| 9 | Characterization tests (after step 1) | Remove the snapshots; keep the two invariants; add targeted unit tests for the lines only they reached; delete `tests/data/refactoring/` |
| 10 | Container golden tests (after step 1) | Remove them and their `REF-golden-*` files; keep the determinism test |
| 11 | FMUs of the kept invariants | All the FMUs of `tests/data/`, discovered automatically (no reference file, so no maintenance cost) |
| 12 | Location of the kept tests | Invariants in `integration/test_operations_invariants.py`; determinism test in `integration/test_container.py` |
| 13 | `tests/benchmarks/bench_manipulation.py` (step 2) | Keep it as a performance measurement tool, reworded; documented in step 6 |

Rule for every step: no test is weakened silently. A step changes comments, names or file layout only, unless it
says otherwise; the number of collected tests and the coverage stay the same (except in step 5, by decision).

## Step 0 — Baseline

- Install the package in the venv (`pip install -e ".[all]"`; `fmu_manipulation_toolbox` is currently missing from
  `.venv`, so the suite does not even collect).
- From `tests/`: `pytest --cov=fmu_manipulation_toolbox -q`, and record in this plan the number of tests
  (passed / skipped / xfailed) and the total coverage. These figures are the reference of every later step.

No commit.

**Result (2026-10-11, macOS, Python 3.14, `.venv`):** 2 091 passed, 2 skipped (`windows_only`), 0 xfailed, 24.9 s.
Coverage (branch, `gui/` omitted): 89 % — 4 470 / 4 927 lines, 1 409 / 1 680 branches.

## Step 1 — Analysis of the reference tests

Goal: give the user the facts needed to decide the fate of `test_operations_characterization.py` and
`test_container_golden.py`. No code change.

- Inventory: list the cases of each module (FMU × operation, container scenario), the size of their data, and
  the time they take (`--durations`).
- Overlap, measured with coverage: run the suite without the two modules
  (`--deselect` / `--ignore`) and compare with step 0 (lines and branches only reached by them).
- Overlap, by content: map each case to the targeted tests that check the same behaviour
  (`unit/test_xml_roundtrip.py`, `unit/test_operations_conformity.py`, `unit/test_operations.py`,
  `integration/test_container_xml.py`, `integration/test_container.py`, …).
- Maintenance cost: how many reference files changed in the git history after the end of the refactorings, and why.
- Write the result in a "Step 1 — results" section of this plan, with the options (keep and rename / reduce to a
  listed sample / remove), then **prompt the user** for the decision, and for the new name of the data directory
  and of the modules when they are kept.

### Step 1 — results

#### `integration/test_operations_characterization.py`

- **Size:** 1 104 tests out of 2 091 (53 % of the suite), about 9 s out of 25 s (37 %). Data: 48 directories,
  2.3 MB in `tests/data/refactoring/`. The FMUs are discovered automatically: every `*.fmu` under `tests/data/`
  (48 today).
- **Cases, per FMU:**

  | Test | Cases | Kind |
  |------|-------|------|
  | `test_modifying_operation` | 9 operations × 48 = 432 | snapshot (`<case>.xml` / `<case>.error`) |
  | `test_read_only_operation` | 3 × 48 = 144 | invariant, but uses `noop.xml` as reference |
  | `test_names_csv` | 48 | snapshot (`names.csv`) |
  | `test_summary` | 48 | snapshot (`summary.txt`) |
  | `test_operation_keeps_descriptor_valid` | 9 × 48 = 432 | invariant (XSD validity), no reference file |

- **Coverage only reached by this module:** 25 lines and 14 branches (coverage 89 % → 88 %):
  - `model_description.py:138-146`: namespace-prefixed attributes (`_prefixed`, `_qualified`);
  - `operations.py:423-424, 456-458, 482-483`: model-structure entries depending on a removed port;
  - `operations.py:866-876, 893-896`: the "Embedded resources", "Additional (meta-)data" and "Terminals" sections
    of the summary;
  - `operations.py:917-918`: `OperationRemoveSources` on an FMU without sources.

  All of them could be reached by a handful of targeted unit tests.
- **Overlap by content:** the defects found during the refactoring are already pinned by targeted tests
  (`unit/test_xml_roundtrip.py`, `unit/test_operations_conformity.py`, `unit/test_operations.py`,
  `unit/test_model_description.py`). The snapshots add a broad "nothing else changed" check over 48 real FMUs.
- **Maintenance cost:** the references were written on 2026-10-09 (phase 0) and updated once by phase 2; not
  changed since. Hidden cost: since the FMUs are discovered automatically, adding an FMU anywhere in `tests/data/`
  makes the module fail until `--update-refs` is run, and a deliberate change in any operation (or in the summary
  wording) requires reviewing up to 48 regenerated references.

#### `integration/test_container_golden.py`

- **Size:** 12 tests (11 scenarios + determinism of the build), about 1.7 s. Data: 27 `REF-golden-*` files,
  240 kB, stored next to the input data of each area.
- **Coverage only reached by this module:** none.
- **Overlap by content:** it is the only check of the *content* of `container.txt` and `datalog.txt` without a
  simulation (Model Exchange, mixed CS/ME, LS-BUS, arrays, multi-threading, profiling, `ts_multiplier`); the other
  container tests check them through `fmpy` simulations (`slow`, `needs_fmpy`, `needs_container`), and
  `integration/test_container_xml.py` checks the descriptor. `test_container_build_is_deterministic` is an
  invariant, without reference file.
- **Maintenance cost:** references written on 2026-10-10 (container phase 0), not changed since. A deliberate
  change in the `container.txt` format requires regenerating them (this format is also documented in
  `docs/developer/container-txt-format.md`).

#### Options to decide

For the characterization module:

1. **Keep and rename** as permanent snapshots (new names for the module and the data directory).
2. **Reduce:** keep the two invariants (XSD validity, read-only operations — the latter rewritten to compare with a
   no-op applied in the test, so without reference file), keep the snapshots on a listed sample of FMUs (e.g. one
   per kind: FMI 2, FMI 3, Model Exchange, arrays, LS-BUS), and add targeted unit tests for the 25 lines above.
3. **Remove the snapshots:** keep only the two invariants, add the targeted unit tests, delete
   `tests/data/refactoring/`.

For the golden module: **keep** (renamed and reworded) or **remove**.

**Decided (2026-10-11):** option 3 for the characterization module, removal for the golden module (decisions 9
to 12). Note: `integration/test_container.py`, `test_array.py`, `test_datalog.py` and `test_cli.py` already compare
`container.txt` / `datalog.txt` with `REF-*` files for their own scenarios.

Commit message (adds the plan, with the baseline of step 0 and the analysis of step 1):

```
Plan the clean-up of the test suite (tests_cleanup steps 0 and 1)

Baseline of the suite, and analysis of the reference tests left by the finished
refactorings: the operation snapshots only add 25 covered lines, the container
golden files none. Decision: replace them by invariants and targeted unit tests.
```

## Step 2 — Remove the temporary scaffolding

- `unit/test_assistant_budget.py`: `OVER_BUDGET` is empty; remove it, the `xfail` parametrisation built from it
  and the sentence of the docstring about markers "removed by the phases".
- `unit/test_container_internals.py`: keep `PUBLIC_NAMES` and `test_public_names`, reworded as the public API of
  `fmu_manipulation_toolbox.container` (no mention of the refactoring or of "phase 2").
- Look for other leftovers of the same kind (`pytest.skip` / `xfail` whose reason refers to a plan, helpers
  without users) and list them here before removing them; if one is not clearly dead, **ask the user**.

Check: same number of tests passed as step 0 (the formerly parametrised budget tests are still collected).

**Result:** the only other leftover found is `tests/benchmarks/bench_manipulation.py` (decision 13): its docstring
is reworded, and its `ElementTreeRoundTrip` row, an estimate of the ElementTree cost made before the operations
used it, is removed (the `noop` row now measures exactly that). Suite: 2 091 passed, 2 skipped.

Commit message:

```
Remove the test scaffolding left by finished plans (tests_cleanup step 2)

The MCP budget tests no longer need their xfail machinery, the import check of
the container package is now presented as its public API, and the benchmark of
apply_operation drops its pre-ElementTree estimate.
```

## Step 3 — Comments describe the behaviour

For every module of `tests/` (and `conftest.py`, `_helpers/`):

- rewrite the module docstrings, test docstrings and section titles that refer to a plan, a phase, an audit finding
  or a defect identifier, so that they state the behaviour checked and, where useful, why it matters;
- remove the references to `docs/local/done/` and the identifiers (D1…D14, I1…I6, M1…M8, B3, B5, S1…S8, C8, …);
- remove "Migrated from the legacy `test_suite.py`" and the remarks that only make sense with that file
  (e.g. `integration/test_cli.py:48`, `integration/test_me.py:3`);
- `unit/test_assistant_server.py`: present `EXPECTED_TOOLS` and the other expected inventories as the published
  MCP contract (a change of name, parameter or resource must be deliberate and update the reference).

The wording of the reference tests (characterization / golden) is left to step 5, which knows their fate.

Check: `grep -rnE "docs/local|phase [0-9]|legacy|audit|\bD[0-9]+\b" tests/` returns only the hits of step 5;
same test count as step 2.

**Result:** 35 files reworded. The remaining hits are `conftest.py` (`--update-refs`, removed in step 5b), the two
modules removed in step 5b, and `unit/test_split_parsing.py:28`, where "legacy" names a `container.txt` format, not
the old test suite. Suite: 2 091 passed, 2 skipped.

Commit message:

```
Describe the behaviour under test instead of the plan history (tests_cleanup step 3)

Test docstrings and section titles no longer refer to archived plans, phases or
finding identifiers, nor to the removed legacy test_suite.py.
```

## Step 4 — Split `test_assistant_server.py`

- Move `FakeBridge` and `NestedBridge` (only used by this module) to `tests/_helpers/assistant_bridge.py`, with the
  shared fixtures/helpers of the module.
- Split the module into three files, by the current sections:
  - `unit/test_assistant_server_contract.py`: contract (name, tool/resource/prompt inventories and signatures),
    schemas, strict input typing, argument errors, error reporting and annotations;
  - `unit/test_assistant_server_tools.py`: tools reaching the bridge, port listings, assembly paging and analysis,
    assembly edition, write guard-rails, end-to-end scenarios;
  - `unit/test_assistant_server_runtime.py` (or merged into one of the two others if it stays small): resources,
    prompts and reference resources, port resolution, timeout, progress reporting.
- The final split (2 or 3 files, names) is checked against the actual size of each part before moving code; if
  it differs from the above, **ask the user**.

Check: same test count, same coverage of `fmu_manipulation_toolbox/assistant/` as step 3.

Commit message:

```
Split the MCP server tests by theme (tests_cleanup step 4)

The fake bridge moves to tests/_helpers so that the contract, tool and runtime
tests can share it.
```

## Step 5 — Apply the decision on the reference tests

Decisions 9 to 12. Done in two commits, so that the coverage is never lowered.

### Step 5a — targeted unit tests first

Add unit tests reaching the 25 lines and 14 branches listed in step 1, on small descriptors built in the test
(as `unit/test_xml_roundtrip.py` does), in the matching modules:

- `unit/test_model_description.py`: an attribute in a foreign namespace (prefixed) is read and written back with
  its prefix (`_prefixed`, `_qualified`);
- `unit/test_operations.py` (or `unit/test_operations_dependencies.py`, whichever fits): removing a port drops the
  model-structure entries of that port and its occurrences in the `dependencies` / `dependenciesKind` of the others
  (including the case where no dependency is left);
- `unit/test_operations.py`: the summary lists the embedded resources, the additional (meta-)data and the
  terminals; `OperationRemoveSources` on an FMU without sources only logs it.

Check: with `integration/test_operations_characterization.py` ignored, the coverage is back to the step 0 figure
(89 %, 4 470 lines, 1 409 branches); without ignoring it, unchanged.

Commit message:

```
Cover with unit tests what only the operation snapshots reached (tests_cleanup step 5a)

Namespace-prefixed attributes, model-structure entries of a removed port, the
optional sections of the summary and the removal of absent sources.
```

### Step 5b — remove the snapshots

- Create `integration/test_operations_invariants.py` with `test_operation_keeps_descriptor_valid` and
  `test_read_only_operation`, over every FMU of `tests/data/` (automatic discovery, now without the `refactoring`
  exclusion). The read-only test compares with the descriptor produced by a no-op operation applied in the test,
  instead of the `noop.xml` reference.
- Delete `integration/test_operations_characterization.py` and `tests/data/refactoring/`.
- Move `test_container_build_is_deterministic` to `integration/test_container.py`; delete
  `integration/test_container_golden.py` and the 27 `tests/data/**/REF-golden-*` files.
- `conftest.py`: remove the `--update-refs` option and the `update_refs` fixture (no other user).
- `_helpers/assertions.py`: remove `assert_identical_text` (no other user); keep `canonical_xml`, used by
  `assert_equivalent_xml`.
- `unit/test_checker_semantic.py:52`: remove the `"refactoring" not in path.parts` special case.
- Check `MANIFEST.in`, `tools/dist_inventory.py` and the CI for references to the removed files.

Check: expected test count 2 091 − 1 104 − 12 + 576 + 1 + (tests of step 5a); coverage equal to step 5a.

Commit message:

```
Replace the refactoring snapshots by invariants (tests_cleanup step 5b)

The operation snapshots (tests/data/refactoring/) and the container golden files
were the safety net of finished refactorings. The XSD validity and read-only
invariants are kept over every test FMU, without reference files; the
determinism of the container build moves to test_container.py. The
--update-refs option has no user any more.
```

## Step 6 — Documentation

- `CONTRIBUTING.md` and `docs/help/contributing.md` ("Running tests"):
  - update the table of directories (`tests/unit/` now covers much more than "operations, checker": model
    description, container internals, MCP server, …);
  - list the shared helpers of `tests/_helpers/` (`assertions.py`, `simulation.py`, `mcp_budget.py`,
    `assistant_bridge.py`);
  - mention the benchmark `tests/benchmarks/bench_manipulation.py` (not collected by pytest) and how to run it;
  - state the convention adopted here: test docstrings describe the behaviour, never a plan or a phase.
- Move this plan to `docs/local/done/`.

Commit message:

```
Document the test suite conventions (tests_cleanup step 6)
```
