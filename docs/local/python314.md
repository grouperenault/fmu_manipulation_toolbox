# Plan: support Python 3.14

**Created**: 10 October 2026 — **Status**: not started, for a later execution — **Origin**: decision D3 of
`done/python39.md`

Python 3.14 was released in October 2025. The package does not declare it (no classifier) and the CI does not test it:
every matrix stops at 3.13. Locally, the full suite already passes on 3.14 (macOS, clean environment with
`pip install -e ".[all]"`: 1921 passed, 2 skipped, on 10 October 2026), with PySide6 6.12, FMPy 0.3.32,
fastmcp 4.1, pydantic 2.14, numpy 2.5 and xmlschema 4.3.

---

## 1. Current state

| # | Finding | Location |
|---|---|---|
| C1 | Classifiers stop at `Programming Language :: Python :: 3.13` | `pyproject.toml` |
| C2 | The four matrices (`tests-windows`, `tests-linux`, `tests-macos`, `smoke-wheel`) run on `["3.10", "3.13"]` | `.github/workflows/ci.yml` |
| C3 | Several steps are pinned to the newest leg by its number: coverage badge (`tests-windows`), package build and checks, artifact upload (`tests-linux`) | `.github/workflows/ci.yml` (`matrix.python-version == '3.13'`) |
| C4 | The GUI tests segfault under 3.13 on the Linux runner (QtWebEngine): the 3.13 Linux leg runs `pytest -m "not gui"` | `.github/workflows/ci.yml`, step *Test with pytest* of `tests-linux` |
| C5 | `release.yml` reuses `ci.yml` (no Python version of its own); `build-native.yml` sets up no Python; `make_doc.yml` uses `3.x` | `.github/workflows/` |
| C6 | Supported versions table ends with "3.13 — Supported (Recommended)" | `docs/installation.md` |
| C7 | The packaging reference lists the classifiers | `tests/data/packaging/metadata.txt` |

---

## 2. Goals

1. Python 3.14 is declared and tested on the three OS, by the test jobs and by `smoke-wheel`.
2. The "newest Python" can be bumped later by changing one value, not every `== '3.13'` condition.
3. The GUI tests keep running at least once per OS where they are stable.

---

## 3. Decisions to take

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | Matrices | (a) `["3.10", "3.14"]` (oldest and newest, as today); (b) `["3.10", "3.13", "3.14"]` | **(a)**: same cost as today; 3.11 to 3.13 are covered by being between the two bounds |
| D2 | GUI tests on the newest Linux leg | (a) try them on 3.14 and keep the exclusion only if they still crash; (b) keep excluding them on the newest Linux leg | **(a)**, measured in phase 1: the crash was observed with 3.13 and older PySide6 versions |
| D3 | Recommended version in the documentation | (a) 3.14; (b) stay on 3.13 | **(a)** once the CI is green on 3.14 on the three OS |
| D4 | Free-threaded build (`3.14t`) | (a) not in this plan; (b) an extra experimental leg | **(a)**: PySide6 and fmpy are not validated free-threaded; to be reconsidered separately |

---

## 4. Plan

### Phase 1 — Trial in the CI

1. On a work branch, add 3.14 to the matrices (D1) without removing anything, and run the GUI tests on the 3.14 Linux
   leg (D2).
2. Record the results per OS and job: dependency installation (wheels available for PySide6, fmpy, numpy on the
   three runners), test suite, GUI tests, `smoke-wheel`.

*Exit criterion*: a list of the failures, each with its cause (our code, a dependency, the runner).

### Phase 2 — Fixes

Fix what phase 1 found in our code. For a dependency without 3.14 support: raise its minimum version if a fixed one
exists, otherwise document the limitation (and, as a last resort, skip the affected tests on 3.14 with an explicit
reason).

*Exit criterion*: green CI on 3.14 on the three OS.

### Phase 3 — Metadata and CI

1. `pyproject.toml`: add the `Programming Language :: Python :: 3.14` classifier (C1); update the packaging reference
   (`tools/dist_inventory.py --write`, after review) (C7).
2. `ci.yml`: final matrices (D1); the newest version defined once (e.g. a workflow-level `env: NEWEST_PYTHON: "3.14"`
   used by the `if:` conditions) instead of the literal `'3.13'` (C3); GUI exclusion removed or moved to 3.14 with
   an updated comment (C4).
3. Check that `release.yml`, `build-native.yml` and `make_doc.yml` need no change (C5).

*Exit criterion*: green CI; `metadata.txt` lists 3.14; no literal Python version left in the `if:` conditions.

### Phase 4 — User documentation

- `docs/installation.md`: 3.14 row in the supported versions table, recommended version (D3).
- `CHANGELOG.md`: `ADDED` entry: Python 3.14 supported.

*Exit criterion*: the documentation lists the versions declared by the classifiers.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| A dependency has no 3.14 wheel on one runner | Detected in phase 1, before any change of the metadata |
| GUI tests crash on 3.14 under Linux, as on 3.13 | Keep the exclusion on that leg only (still exercised on Windows) |
| Coverage badge or package step silently disabled by the matrix change | Conditions use a single `NEWEST_PYTHON` value (phase 3) |

## 6. Delivery

One PR, after the `done/python39.md` plan. Phase 1 needs CI runs, so it cannot be done locally only.
