# Plan: refactoring of `container.py`

**Created**: 10 October 2026 — **Updated**: 10 October 2026 (decisions taken; phases 0 to 3 done) — **Status**: in progress — **Roadmap**: 2.0 ("refactor container.py")

`fmu_manipulation_toolbox/container.py` builds FMU Containers: it loads the embedded FMUs, records the wiring rules,
allocates the value references, then writes `modelDescription.xml`, `resources/container.txt` (read by the C runtime,
`container/`) and `resources/datalog.txt`, and zips the result. Its XML generation was moved to ElementTree by the
`refactoring.md` plan (phase 4); the rest has not changed in years.

---

## 1. Current state

2369 lines, 20 classes, used by:

| Consumer | What it uses |
|---|---|
| `assembly.py` | `FMUContainer`: `get_fmu`, `add_input`, `add_output`, `add_link`, `drop_port`, `add_start_value`, `add_implicit_rule` (and its `AutoWired` result), `make_fmu` |
| `split.py` (reads `container.txt` back) | `EmbeddedFMUPort.ALL_TYPES`, `FMI_TO_CONTAINER`, `CONTAINER_TO_FMI`, `ALL_TYPES[:-2]`; `Link.CONVERSION_FUNCTION` |
| `gui/fmucontainer` | `FMUContainerError`, `ArrayAggregate` |
| User scripts | `FMUContainer`, documented in `docs/user-guide/fmucontainer/container.md` ("Building a Container Programmatically"); the whole module is rendered in the API reference (`docs/API/container.md`: `::: fmu_manipulation_toolbox.container`) |
| Tests | `FMUContainer`, `EmbeddedFMU` |

### Structure

| Lines | Content |
|---|---|
| 41–170 | `ArrayAggregate`: detection of the FMI-2 `name[i,j]` families |
| 172–570 | `EmbeddedFMUPort` (type tables, `xml()`), `EmbeddedFMU` (an `OperationAbstract` reading the descriptor) |
| 572–1086 | Rules: `ContainerPort`, `ContainerInput`, `Link` (with the 170-line `CONVERSION_FUNCTION` table), `AutoWired` |
| 939–1044 | `ValueReferenceTable`: value references with the type in the upper byte, local storage offsets |
| 1088–1395 | `container.txt` writers: `FMUIOList`, `InvolvedFMU.write_txt`, `ClockList`; records `IOReference`, `Clock`, `LocalVariable`, `Platform`, `Port` |
| 1397–2369 | `FMUContainer`: rules API, auto-wiring, step size, `make_fmu_xml` (180 lines), `make_fmu_txt` (120 lines), datalog, platforms, skeleton, zip |

### Findings

Design:

| # | Finding | Location |
|---|---|---|
| C1 | **Value references are allocated while the XML is written**: `make_fmu_xml` calls `vr_table.add_vr` and stores the results on the rule objects (`link.vr`, `input_port.vr`, `output_port.vr`); `make_fmu_txt` and `make_datalog` then depend on these side effects, so the three writers must run in this order | `make_fmu_xml`, `make_fmu_txt`, `make_datalog` |
| C2 | **`make_fmu` is not idempotent**: a second call allocates new value references on the same table (counters keep growing, local storage doubled) and produces a wrong container. No current caller does it (each build creates a new `FMUContainer`), but nothing prevents it. `start_time`/`stop_time` are also overwritten by the first build | `FMUContainer.make_fmu` |
| C3 | **Hard-coded value references** in `container.txt`: `100663296 1 1 -1 0` (TS multiplier) and `100663297` (solver) are `6 << 24 \| 0` and `\| 1`, i.e. the first two `integer32` references, valid only because `make_fmu_xml` allocates them first. Likewise the time slot `0` and the profiling slots `1..n` of `real64` | `make_fmu_txt` |
| C4 | `EmbeddedFMUPort.xml()` **modifies the port** (`self.variability` set when absent) while generating XML | `EmbeddedFMUPort.xml` |
| C5 | The `container.txt` format is known on both sides without shared code: written here, read back by `split.py`, which imports the type tables from `EmbeddedFMUPort` and `Link`. `ALL_TYPES[:-2]` ("no start value for binary and clock") appears in both | `container.py`, `split.py` |
| C6 | `FMI_TO_CONTAINER` and `CONTAINER_TO_FMI` are two hand-written inverse tables | `EmbeddedFMUPort` |
| C7 | Duplicated code: `FMUIOList.add_input`/`add_output` (identical except the target dict), the input and output sections of `FMUIOList.write_txt`, the two branches of `ValueReferenceTable.add_vr` | `FMUIOList`, `ValueReferenceTable` |
| C8 | Auto-wiring is quadratic: `find_inputs` rebuilds the list of every port (`get_all_cports`, a `ContainerPort` per port) for each output | `find_inputs`, `add_implicit_rule` |
| C9 | **Inconsistent error policy**: a missing FMU port in `add_input`, `add_output`, `drop_port`, `add_start_value`, `add_link` is logged (`logger.error`) and the rule is **ignored**, the container is built anyway; a wrong causality or type raises `FMUContainerError` | rules API |
| C10 | `EmbeddedFMUPort` takes `FMUPort \| dict` and tests `isinstance(attrs, FMUPort)`; this blocks the planned removal of `FMUPort` (`refactoring.md`, "Removal of `FMUPort`", step 1) | `EmbeddedFMUPort.__init__` |
| C11 | Each `EmbeddedFMU` keeps its `FMU` (and its temporary directory) open until garbage collection, although only `fmu.fmu_filename` is used after the analysis | `EmbeddedFMU` |
| C12 | No unit test for the internal classes; the output is only checked by end-to-end tests | `tests/` |

Latent bugs (found by reading, to be confirmed by tests in phase 0):

| # | Bug | Location |
|---|---|---|
| B1 | `default_step_size`: if **one** FMU has no `stepSize` (and none has a fixed step), `None > float` raises `TypeError` and the step falls back to 0.1 s, ignoring the step sizes of the other FMUs | `default_step_size` |
| B2 | `default_step_size`: frequencies are truncated, `int(1.0 / step)`: a fixed step of 0.3 s gives a frequency of 3, a container step of 0.333 s and a warning; a step above 1 s gives a frequency of 0 | `default_step_size` |
| B3 | `sanity_check`: `ts_ratio != int(ts_ratio)` on floats warns for valid ratios (`0.3 / 0.1 = 2.9999999999999996`) | `sanity_check` |
| B4 | The build directory is `fmu_directory / <output name without suffix>`, created with `exist_ok=True` and **removed with `rmtree`** at the end: a user directory with that name is mixed with the build and deleted | `make_fmu`, `make_fmu_cleanup` |
| B6 | *(found in phase 0)* An FMU input can be fed twice: exposed as a container input **and** target of a link (or target of two links). `mark_ruled` accepts any rule combined with `LINK`, so both writers update the same input at every step | `FMUContainer.mark_ruled` |
| B5 | `Clock(container_vr, fmu_vr)` is called as `Clock(cport.port.vr, vr)`: the names are swapped (the output is right, because the writer prints them in the swapped order too); the `ClockList` docstring describes tuples | `ClockList` |

Minor: dead `try/except KeyError` around a `defaultdict` (`make_fmu_txt`, conversion table); `flag == True`;
`add_link_regular` indented by 12 spaces; small record classes (`IOReference`, `Clock`, `LocalVariable`, `Platform`,
`Port`) that could be dataclasses.

### Test coverage of the output

Golden files (`assert_identical_files` for `container.txt`, `assert_equivalent_xml` for `modelDescription.xml`):
bouncing ball (default, sequential, profiling, FMI-3), `start`, FMI-3 passthrough, arrays 2→3 and 3→2, datalog.
**Not covered** by a golden file: Model Exchange and mixed CS/ME containers, LS-BUS (`bus+nodes`, `nodes-only`), FMI-2
and FMI-3 array containers (`array-2`, `array-3`: XML only), multi-threaded flag, `ts_multiplier`, type conversions
(only through simulations, which need the compiled runtime and are skipped otherwise). *Correction after phase 0*:
type conversions were already covered by the `array-23`, `array-32` and FMI-3 passthrough golden files.

The conversion names are consistent today: the 132 values of `CONVERSION_FUNCTION` are exactly the 132 `CASE(...)` of
`container/convert.c`.

---

## 2. Goals

1. **Same output**: every refactoring phase produces byte-identical `container.txt` and `datalog.txt`, and an
   equivalent `modelDescription.xml` (C14N), for every scenario. The `container.txt` format version (6) does not
   change.
2. An explicit build pipeline: rules → layout (value references) → writers → package. Writers are functions of the
   layout, without side effects; `make_fmu` can be called twice.
3. One definition of the container types and conversions, shared with `split.py`.
4. Smaller modules with unit tests.
5. The latent bugs B1 to B3, B5 and B6 fixed, each with a test (B4 kept, D3).
6. Public API unchanged: `from fmu_manipulation_toolbox.container import X` keeps working for every class of today.

---

## 3. Decisions

Decided on 10 October 2026: **D1 (a)**, **D2 (a)**, **D3 (b)**, **D4 (a)**, **D5 (a)**. With D3 (b), the build directory
stays `fmu_directory/<name>` and B4 is not fixed by this plan (documented instead, phase 6).

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | Module layout | (a) package `fmu_manipulation_toolbox/container/` with sub-modules, `__init__.py` re-exporting every current name; (b) one module, reordered and cleaned | **(a)**: 2369 lines with four distinct concerns (types, embedded FMUs, rules, writers); the re-exports keep every import working |
| D2 | Missing port in a rule (C9) | (a) raise `FMUContainerError`, like the other rule errors; (b) keep logging and ignoring | **(a)**, as a breaking change of 2.0: today a typo in a port name silently produces a container without that connection. To check first: the GUI and the MCP assistant validate ports before building, so they are not affected |
| D3 | Build directory (B4) | (a) temporary directory (`tempfile`), kept as `fmu_directory/<name>` only with `debug`, and refused if that directory already exists; (b) unchanged | **(a)** |
| D4 | `FMUPort` in `EmbeddedFMUPort` (C10) | (a) build `EmbeddedFMUPort` from `ModelVariable` here (step 1 of the `FMUPort` removal); (b) leave it to the `FMUPort` plan | **(a)**: the class is rewritten anyway in phase 4 |
| D5 | Step size deduction (B1, B2) | (a) exact arithmetic with `fractions.Fraction` (`limit_denominator`), FMUs without `stepSize` ignored; (b) keep the current computation | **(a)**: a visible change (other deduced step sizes in some assemblies), `FIXED` entry in `CHANGELOG.md` |

---

## 4. Plan

### Phase 0 — Safety net

1. Golden files for the uncovered scenarios (§1): Model Exchange, mixed CS/ME, LS-BUS (two assemblies), `array-2`
   and `array-3` (`container.txt`), multi-threaded, `ts_multiplier`, a container with type conversions. Generated
   with the current code, then reviewed by hand.
2. Test of determinism: two builds of the same assembly give the same `container.txt`.
3. Consistency test: `CONVERSION_FUNCTION` values == `CASE(...)` names of `container/convert.c`.
4. Characterization unit tests: value reference layout (masks, local offsets), `ArrayAggregate.detect_all`,
   `default_step_size`, error cases of the rules API.
5. Tests reproducing B1 to B3 and C2 (`make_fmu` twice), marked `xfail(strict=True)` until their fix (B4 is kept,
   D3).

*Exit criterion*: every scenario of §1 covered by a golden file; suite green.

**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| 11 golden scenarios: Model Exchange (plain, multi-threaded), mixed CS/ME, LS-BUS (`bus+nodes`, `nodes-only`, with datalog), arrays `array-2` and `array-3`, multi-threaded FMI-2 and FMI-3 (`containers/mt`), profiling with datalog (`VanDerPol`), `ts_multiplier` (nested container and its parent); `container.txt`, `datalog.txt` compared line by line, whitespace included; `modelDescription.xml` in canonical form without the volatile attributes; determinism test (two builds of `bouncing.csv`) | `tests/integration/test_container_golden.py` |
| 27 references `REF-golden-<scenario>[-<container>]-{container.txt,modelDescription.xml,datalog.txt}`, next to the input data; regenerated with `--update-refs` (option help updated) | `tests/data/{me,ls-bus,array,containers/mt,containers/VanDerPol}/`, `tests/conftest.py` |
| `assert_identical_text`: exact line comparison (only the end of line convention may differ), with an optional pattern of lines to ignore | `tests/_helpers/assertions.py` |
| Characterization unit tests: the 18 public names, conversions == `CASE(...)` of `container/convert.c`, lossy prefix, value reference masks (`100663296` = `6 << 24`) and local storage offsets, `ArrayAggregate` (names, row-major order, rejected families, name collision), `default_step_size` (5 cases), rules API errors (7 causality/format cases, duplicate output, input exposed twice), missing port ignored with an error log (current behaviour, to be inverted in phase 4 by D2), lossy link warning | `tests/unit/test_container_internals.py` |
| `xfail(strict=True)`: B1, B2 (0.3 s and 2 s), B3, B6, C2 (`make_fmu` twice); each checked to fail on its assertion (`--runxfail`), not on an unrelated error | `tests/unit/test_container_internals.py` |

Findings during the phase:

- **New bug B6** (see §1): `add_input` then `add_link` to the same FMU input is accepted.
- **Generated GUID**: a nested container writes its random GUID (`uuid4`, without braces) in the `container.txt`
  of its parent; the golden comparison ignores the lines matching it. The GUIDs of the embedded FMUs (with braces)
  stay compared.
- `VanDerPol.json` asks for `mt` with a single FMU: the builder falls back to mono-thread (flag `0`), as expected.

Checks performed: the golden tests pass three times in a row against freshly generated references; clean Python 3.14
environment: full suite **1982 passed, 2 skipped, 6 xfailed**; ruff `F` on the new test files: clean.

### Phase 1 — Container types (`types.py`)

1. New module with `ALL_TYPES`, the FMI ↔ container mapping (one table per version, the inverse computed),
   `CONVERSION_FUNCTION`, `is_lossy(conversion)`, and a named constant for the types without start value (replaces
   `ALL_TYPES[:-2]`).
2. `EmbeddedFMUPort` and `Link` keep their class attributes as aliases of the module ones (compatibility); `split.py`
   uses the new module directly (C5, C6).

*Exit criterion*: no type table defined twice; golden files unchanged.

**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| New module: `ALL_TYPES`, `NO_START_VALUE_TYPES`, `START_VALUE_TYPES` (replaces `ALL_TYPES[:-2]`), `FMI_TO_CONTAINER`, `CONTAINER_TO_FMI` computed as its inverse (same order as the former hand-written table), `CONVERSION_FUNCTION`, `is_lossy()` | `fmu_manipulation_toolbox/container_types.py` |
| `EmbeddedFMUPort.ALL_TYPES`, `FMI_TO_CONTAINER`, `CONTAINER_TO_FMI` and `Link.CONVERSION_FUNCTION` kept as aliases (same objects); the module code uses the tables directly; `Link.add_target` uses `is_lossy()` | `fmu_manipulation_toolbox/container.py` (2369 → 2150 lines) |
| `split.py` imports `container_types` instead of `EmbeddedFMUPort` and `Link`; `FORMAT_2_TYPES` names the types of format 2 (binary and clock came with format 3), `START_VALUE_TYPES` the types with start values | `fmu_manipulation_toolbox/split.py` |
| Tests: aliases are the shared objects, `CONTAINER_TO_FMI` is the inverse in the former order, `START_VALUE_TYPES` | `tests/unit/test_container_internals.py` |

**Deviation**: the module is `fmu_manipulation_toolbox/container_types.py`, because a `container/` package cannot
coexist with `container.py`; phase 2 moves it to `container/types.py` (and updates the import of `split.py`).

Checks performed: golden files unchanged; full suite **1985 passed, 2 skipped, 6 xfailed** (clean Python 3.14
environment); `tools/dist_inventory.py --check --untracked`: rules satisfied; ruff `F`: only the 17 `F541` (f-strings
without placeholder) already present in `container.py` and `split.py`, left for phase 4.

### Phase 2 — Package (pure move)

Move the code without changing it (D1):

| Module | Content |
|---|---|
| `container/types.py` | phase 1 |
| `container/arrays.py` | `ArrayAggregate` |
| `container/embedded.py` | `EmbeddedFMUPort`, `EmbeddedFMU` |
| `container/rules.py` | `FMUContainerError`, `ContainerPort`, `ContainerInput`, `Link`, `AutoWired` |
| `container/layout.py` | `ValueReferenceTable` |
| `container/txt.py` | `container.txt` and `datalog.txt` writers: `FMUIOList`, `ClockList`, records |
| `container/builder.py` | `FMUContainer` |
| `container/__init__.py` | re-exports of every name importable today |

One commit with moves only, so that `git diff --color-moved` shows nothing else. `pyproject.toml` needs no change
(`packages.find` includes `fmu_manipulation_toolbox*`); `tools/dist_inventory.py` derives the wheel modules from git.

*Exit criterion*: every former `from fmu_manipulation_toolbox.container import X` works (test listing them); suite and
packaging check green.

**Status on 10 October 2026: done.**

| Module | Content | Lines |
|---|---|---|
| `container/__init__.py` | re-exports of the 18 former names, `__all__` | 19 |
| `container/types.py` | `container_types.py` of phase 1 (`git mv`) | 236 |
| `container/arrays.py` | `ArrayAggregate` | 153 |
| `container/errors.py` | `FMUContainerError` | 14 |
| `container/embedded.py` | `EmbeddedFMUPort`, `EmbeddedFMU` | 366 |
| `container/rules.py` | `ContainerPort`, `ContainerInput`, `Link`, `AutoWired` | 234 |
| `container/layout.py` | `ValueReferenceTable` | 116 |
| `container/txt.py` | `IOReference`, `FMUIOList`, `InvolvedFMU`, `Clock`, `ClockList`, `LocalVariable`, `Port` | 315 |
| `container/builder.py` | `Platform`, `FMUContainer` | 1011 |

Deviations from the table above: **`FMUContainerError` has its own module** (`errors.py`) instead of `rules.py`:
`EmbeddedFMU` raises it and `rules.py` imports `embedded.py`, so the plan's layout made an import cycle. `Platform`
stays with `FMUContainer` (only used by `get_platforms`).

**One change besides the moves**: `make_fmu_skeleton` located the toolbox resources with
`Path(__file__).parent / "resources"`, one level up now (`parent.parent`). The suite caught it (54 failures, missing
`fmucontainer.png`). Other edits: the import of `split.py` (`.container.types`), the test of the types, and comments
naming `container.py` or `container_types` (GUI, docstrings).

Checks performed:

- every class of the former module compared with its new source (`ast.get_source_segment`): identical, except two
  docstring/comment lines naming `container_types` and the `resources` path;
- each sub-module imports on its own (no cycle);
- full suite **1985 passed, 2 skipped, 6 xfailed** (golden files unchanged), clean Python 3.14 environment;
- `tools/dist_inventory.py --check --untracked`: rules satisfied (the new modules are packaged);
- `mkdocs build` of the former and of the new tree: the API reference of the container has the same 44 anchors.

`git` does not see `builder.py` as a rename of `container.py` (less than 50 % similar): use
`git diff --cached -M --color-moved` to review the moves.

### Phase 3 — Explicit build pipeline (C1 to C4)

1. A `ContainerLayout` computed from the rules by a fresh `ValueReferenceTable`: value references of time,
   `ts_multiplier`, solver, profiling slots, links and converted copies, container inputs and outputs, local storage.
2. `make_fmu_xml`, `make_fmu_txt`, `make_datalog` read the layout instead of the attributes written on the rules;
   the reserved slots of `container.txt` come from the layout (C3).
3. `make_fmu` computes a new layout at each call and does not overwrite `start_time`/`stop_time` (C2).
4. `EmbeddedFMUPort.xml()` without side effect (C4).

*Exit criterion*: golden files unchanged; the "`make_fmu` twice" test passes (`xfail` removed).

**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| `ContainerLayout` (dataclass): `allocate(links, inputs, outputs, nb_profiling)` allocates, on a fresh `ValueReferenceTable` and in the former order, time, `ts_multiplier`, solver, profiling slots, local variables of the links and their converted copies, container inputs, container outputs; `local_offset(vr)` | `container/layout.py` |
| `ValueReferenceTable.set_link_vr(link)` (wrote on the link) replaced by `add_link(link)`, which returns the value references | `container/layout.py` |
| No value reference on the rules any more: `ContainerPort.vr`, `ContainerInput.vr`, `Link.vr` removed; `Link.vr_converted` (target type → `None`, filled at build time) becomes `Link.conversions` (target type → conversion name, filled by `add_target`) | `container/rules.py` |
| `make_fmu` allocates a layout at each call and gives it to `make_fmu_xml`, `make_fmu_txt`, `make_datalog` (new `layout` parameter); `FMUContainer.vr_table` removed; `start_time`/`stop_time` no longer overwritten (documented as attributes) | `container/builder.py` |
| `container.txt`: the reserved lines come from the layout (`<VR> 1 1 -1 <local offset>`, `-2` for profiling) instead of the literals `0`, `100663296`, `100663297` and `1..n`; the C runtime reads `<FMU_VR>` as a local storage offset whenever `<FMU_INDEX>` is negative (`container/fmi2.c`, `fmi3.c`) | `container/builder.py` |
| `EmbeddedFMUPort.xml()` computes the default variability without storing it on the port (C4) | `container/embedded.py` |
| `ContainerLayout` exported by `fmu_manipulation_toolbox.container` | `container/__init__.py` |
| Tests: `make_fmu` twice (`xfail` removed), rules and ports unchanged by a build, layout allocation order and local offsets, `xml()` without side effect (checked to fail without the fix) | `tests/unit/test_container_internals.py` |

Visible API change for phase 6 (`CHANGELOG.md`): the removed attributes and methods above (`vr` of the rules,
`Link.vr_converted`, `ValueReferenceTable.set_link_vr`, `FMUContainer.vr_table`) and the new `layout` parameter of
the three `make_*` writers. `FMUContainer.make_fmu` itself is unchanged.

**Suspected bug, to be checked in phase 4** (not reproducible with the FMUs of the golden scenarios): when one link
feeds **several targets of the same converted type**, `make_fmu_txt` appends the converted local variable, and the
link to `links_per_fmu`, once per target. The local lines of `container.txt` would then list the variable twice while
their count (`nb_local`) counts it once, and the conversion table would be duplicated. Phase 3 keeps this behaviour
(identical output).

Checks performed: golden files unchanged (byte comparison, 12 scenarios + determinism); full suite **1988 passed,
2 skipped, 5 xfailed** (clean Python 3.14 environment); `tools/dist_inventory.py --check --untracked`: rules
satisfied; `mkdocs build`: no warning, `ContainerLayout` rendered in the API reference.

### Phase 4 — Rules and simplifications (C7 to C11, D2, D4)

1. `FMUIOList`: one `add` method for inputs and outputs, one writer for both sections; `ValueReferenceTable.add_vr`
   simplified (C7).
2. Auto-wiring with an index of the free inputs by `(name, type)`: linear instead of quadratic (C8).
3. Missing port in a rule: `FMUContainerError` (D2), callers checked (`assembly.py`, GUI, assistant).
4. `EmbeddedFMUPort` built from `ModelVariable` (D4); `EmbeddedFMU` closes its `FMU` once analysed (C11).
5. Records as dataclasses, `Clock` fields named in the right order (B5), dead code and minor items of §1.

*Exit criterion*: golden files unchanged; suite green.

### Phase 5 — Bug fixes (B1 to B3, B6, D5)

1. `default_step_size` with `Fraction` (D5); `sanity_check` with a tolerance (B3).
2. `mark_ruled`: an input port accepts one feeder only (container input or link); an output can still be exposed
   and linked (B6).
3. Remove the `xfail` markers of phase 0.

*Exit criterion*: B1 to B3 and B6 tests pass; golden files unchanged except where a fix changes a deduced step size (reviewed
one by one).

### Phase 6 — User documentation

- `docs/API/container.md`: the package and its public modules (mkdocstrings), so that the API reference keeps
  listing the same classes.
- `docs/user-guide/fmucontainer/container.md`: step size deduction (D5), error on an unknown port (D2); the build
  directory `fmu_directory/<name>` is created and then deleted, so no directory of that name must exist there (B4,
  kept by D3).
- `docs/developer/container-txt-format.md`: the version table stops at 4 while the writer emits version 6; complete
  it, and point to `container/types.py` for the type list and conversions.
- `CHANGELOG.md`: `CHANGED` (**breaking**) for D2; `FIXED` for B1 to B3 and B6; `CHANGED` for the package layout (imports
  unchanged).

*Exit criterion*: the documentation describes the 2.0 behaviour; `mkdocs build` without warning.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| A refactoring changes `container.txt` without anyone noticing (the C runtime reads it, the simulations are skipped without binaries) | Golden files for every scenario (phase 0), byte comparison; simulations in the CI, where the binaries exist |
| Import of a moved name breaks a user script | Re-exports in `container/__init__.py` and a test listing every former name |
| D2 breaks assemblies that worked with a wrong port name | Breaking entry in `CHANGELOG.md`; the error message names the FMU and the port |
| Merge conflicts with the other 2.0 items (FMUPort removal, multiple instances in the GUI) | Do this plan first: D4 covers step 1 of the FMUPort removal; the multi-instance work builds on the new `rules.py` |

## 6. Delivery

One PR per phase. Phase 2 (pure move) in its own commit, merged quickly to limit conflicts. Phases 3 and 4 do not
change the output; phase 5 does, on purpose.
