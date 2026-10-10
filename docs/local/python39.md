# Plan: drop Python 3.9 support

**Created**: 10 October 2026 — **Updated**: 10 October 2026 (phases 1 to 4 done) — **Starting branch**: `packaging` (after phase 5 of `packaging.md`) — **Roadmap**: 2.0

Python 3.9 reached its end of life in October 2025. The test tooling already requires 3.10 (`pytest >= 9`): the test
jobs run on 3.10 and 3.13 only, and 3.9 is exercised by a single job, `smoke-wheel`, which installs the wheel and runs
the entry points. The MCP server (`mcp` extra) already requires 3.10.

---

## 1. Current state

| # | Finding | Location |
|---|---|---|
| C1 | `requires-python = ">=3.9"` and the `Programming Language :: Python :: 3.9` classifier | `pyproject.toml` |
| C2 | Dependency `importlib_metadata >= 8.7.0; python_version<'3.10'`, only used by `get_checkers()` | `pyproject.toml`, `fmu_manipulation_toolbox/checker.py:331` |
| C3 | Markers `python_version>='3.10'` on `fastmcp` and `uvicorn` (`mcp` extra): redundant once 3.10 is the minimum | `pyproject.toml` |
| C4 | `smoke-wheel` matrix `["3.9", "3.13"]`, with a comment explaining why 3.9 is kept | `.github/workflows/ci.yml:296` |
| C5 | The packaging reference holds `Requires-Python: >=3.9`, the 3.9 classifier and the three markers | `tests/data/packaging/metadata.txt` |
| C6 | The docstring of the MCP server and its `McpUnavailableError` message mention Python 3.9 / "Python >= 3.10" | `fmu_manipulation_toolbox/assistant/server.py:7`, `:266` |
| C7 | 587 annotations with `typing.List`, `Dict`, `Tuple`, `Optional`, `Union`, ... in 41 files; with 3.10, `list[...]` and `X \| None` work at runtime | whole code base |
| C8 | User documentation: "Python 3.9 or higher", `importlib_metadata` on 3.9, a 3.9 row in the supported versions table, "Python 3.10+" for the MCP server in eight places | `README.md`, `docs/installation.md`, `docs/tutorials/getting-started.md`, `docs/user-guide/fmucontainer/ai-assistant.md` |

No other version-dependent code: `checker.py` holds the only `sys.version_info` test.

---

## 2. Goals

1. The package declares and supports Python ≥ 3.10; pip on 3.9 keeps installing the last compatible release
   (1.9.4.2) instead of a broken one.
2. No compatibility code or dependency left for 3.9.
3. The CI tests the oldest supported version everywhere (3.10).
4. The documentation states one minimum version for the whole package, MCP server included.

---

## 3. Decisions

Decided on 10 October 2026: **D1 (b)**, the annotations are modernized now (phase 4); **D2 (a)**; **D3 (a)**, planned
in `python314.md` for a later execution.

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | Modernize the annotations (C7)? | (a) not in this plan; (b) mechanically (`pyupgrade --py310-plus` or `ruff --select UP`) in a dedicated phase | **(a)**: 587 changes in 41 files would conflict with the planned refactoring of `container.py` and with the FMUPort removal; new code may use the 3.10 syntax, and a mechanical pass can follow those refactorings |
| D2 | Maintenance of the 3.9 line? | (a) none: 1.9.4.2 is the last 3.9 release; (b) a `1.9.x` branch for fixes | **(a)**: 3.9 is end-of-life; `requires-python` makes pip pick 1.9.4.2 automatically |
| D3 | Add Python 3.14 (classifier, CI)? | (a) not in this plan; (b) here | **(a)**: independent change, and the GUI tests already segfault under 3.13 on the Linux runner; to be planned separately (`python314.md`) |

---

## 4. Plan

### Phase 1 — Metadata and CI

1. `pyproject.toml`: `requires-python = ">=3.10"`; remove the 3.9 classifier; remove the `importlib_metadata`
   dependency; remove the `python_version>='3.10'` markers of `fastmcp` and `uvicorn` (C1 to C3).
2. `ci.yml`: `smoke-wheel` on `["3.10", "3.13"]`; reword the comments of the four matrices ("oldest supported"
   rather than "oldest testable") (C4).
3. Packaging reference: review the difference of `tools/dist_inventory.py --check`, then
   `--write tests/data/packaging --placeholder-binaries` (C5).

*Exit criterion*: `validate-pyproject`, inventory check with the new reference, full test suite green.

**Status on 10 October 2026: done** (decisions D1 to D3 taken as recommended; green CI on the next push to be confirmed).

| Item | File |
|---|---|
| `requires-python = ">=3.10"`; 3.9 classifier, `importlib_metadata` dependency and `python_version>='3.10'` markers of the `mcp` extra removed | `pyproject.toml` |
| `smoke-wheel` on 3.10 and 3.13; the four matrix comments now read "Oldest supported and newest Python" | `.github/workflows/ci.yml` |
| Reference updated after review: only the classifier, `Requires-Python` and the three `Requires-Dist` lines changed | `tests/data/packaging/metadata.txt` |

Checks performed:

- `validate-pyproject pyproject.toml`: valid; `tools/dist_inventory.py --check`: the difference listed above, then
  "Inventory unchanged, rules satisfied." after `--write`;
- clean Python 3.9 environment: `pip install` of the new wheel is refused ("requires a different Python: 3.9.13 not in
  '>=3.10'"), so pip falls back to 1.9.4.2 when installing from PyPI;
- clean Python 3.14 environment, `pip install -e ".[all]"`: full suite **1921 passed, 2 skipped**.

`checker.py` still holds the `sys.version_info < (3, 10)` branch importing `importlib_metadata`: it is dead code
from now on (never taken on 3.10+), removed in phase 2.

### Phase 2 — Code

1. `checker.py`: `from importlib.metadata import entry_points` at module level, without the version test (C2).
   `entry_points(group=...)` is available since 3.10.
2. `assistant/server.py`: docstring (fastmcp stays imported lazily because the `mcp` extra is optional, not because of
   the Python version) and error message without "Python >= 3.10" (C6).
3. Search again for `3.9`, `3.10`, `version_info` in the code and the tests.

*Exit criterion*: no Python version test left in the package; suite green, `get_checkers()` tests included.

**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| `from importlib.metadata import entry_points` at module level; the `sys.version_info` branch and the `import sys` it was the only user of removed | `fmu_manipulation_toolbox/checker.py` |
| Module docstring: fastmcp is imported lazily because the `mcp` extra is optional; `McpUnavailableError` message without "Python >= 3.10" | `fmu_manipulation_toolbox/assistant/server.py` |

Checks performed: `git grep -E "3\.9|3\.10|version_info|importlib_metadata"` on the package, the tests and the tools
finds nothing; `get_checkers()` returns `OperationGenericCheck` and `OperationSemanticCheck`; clean Python 3.14
environment, `pip install -e ".[all]"`: full suite **1921 passed, 2 skipped**.

### Phase 3 — User documentation

- `README.md`: prerequisites "Python ≥ 3.10"; the `mcp` extra no longer needs its own version note.
- `docs/installation.md`: minimum version, extras table (no `importlib_metadata`), supported versions table without
  3.9, the "Python 3.10+" notes of the MCP sections; a note that Python 3.9 users get 1.9.4.2.
- `docs/tutorials/getting-started.md`, `docs/user-guide/fmucontainer/ai-assistant.md`: minimum version.
- `CHANGELOG.md`: `CHANGED` (**breaking**) entry: Python ≥ 3.10 required; 1.9.4.2 is the last release supporting 3.9.

*Exit criterion*: `git grep -n "3\.9"` outside `CHANGELOG.md` history, `docs/local/` and test data finds nothing
about the supported Python versions.


**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| Prerequisites "Python ≥ 3.10"; no version note left on the `mcp` extra | `README.md` |
| Minimum version linked to the supported versions table; 3.9 row "Not supported: version 1.9.4.2 at most" and a note explaining that pip installs 1.9.4.2 on 3.9; extras table without `importlib_metadata`; the six "Python 3.10+" notes of the MCP sections removed | `docs/installation.md` |
| Minimum version | `docs/tutorials/getting-started.md`, `docs/user-guide/fmucontainer/ai-assistant.md` |
| `CHANGED` (**breaking**) entry | `CHANGELOG.md` |

Exit criterion checked: outside `CHANGELOG.md`, `docs/local/` and the test data, `3.9` only appears in the supported
versions table and its note; `3.10` only as the minimum version and in the conda example.


### Phase 4 — Annotations in the Python 3.10 syntax (D1)

Added after the decision on D1. Mechanical rewrite, without change of behaviour:

1. Replace the 16 `from typing import *` by explicit imports (the names reported by ruff `F405`), so that the
   rewrite tools can resolve the names.
2. `ruff check --target-version py310 --select UP006,UP007,UP035,UP045 --fix`: `List[...]` → `list[...]`,
   `Optional[X]` → `X | None`, `Union[X, Y]` → `X | Y`, `Callable`, `Iterable`, ... from `collections.abc`.
3. Remove the `typing` imports left unused (`F401`, restricted to them); rewrite by hand what ruff leaves (type
   aliases assigned at module level).

No user documentation change: the API reference is generated from the code.

*Exit criterion*: ruff `UP006`, `UP007`, `UP035`, `UP045` find nothing; every module imports; suite green.

**Status on 10 October 2026: done.**

| Item | Files |
|---|---|
| The 16 `from typing import *` replaced by explicit imports (`help.py` used no `typing` name: line removed) | `assembly.py`, `checker.py`, `container.py`, `help.py`, `ls.py`, `operations.py`, `split.py`, `terminals.py`, `cli/datalog2pcap.py`, `gui/helper.py`, `gui/fmucontainer/details/*`, `gui/fmucontainer/tree/*` |
| 594 annotations rewritten by ruff, unused `typing` imports removed (41 files: package, tests, `tools/dist_inventory.py`) | whole code base |
| By hand: the aliases `StartValue`, `PathOrBytes`, `PathLike` (twice) as `X \| Y`; `LastDirectory.update(path: str \| Path \| None)` instead of `Union[str, "Path"] \| None` | `assistant/models.py`, `model_description.py`, `textfiles.py`, `tests/_helpers/assertions.py`, `gui/helper.py` |
| `gui/fmutool/__main__.py` got `Optional` through `from fmu_manipulation_toolbox.operations import *`, which no longer exports it: annotation rewritten by hand (`list[str] \| None`) | `gui/fmutool/__main__.py` |

Checks performed: ruff `UP006`, `UP007`, `UP035`, `UP045` and `F821`: nothing; no `List[`, `Dict[`, `Optional[`,
`Union[` left in the code (only in a comment and a test docstring); every module of the package imports (GUI included,
`QT_QPA_PLATFORM=offscreen`); clean Python 3.14 environment: full suite **1921 passed, 2 skipped**. Python 3.10 itself
is only exercised by the CI (no local interpreter).

Left as found (out of scope): the star import of `operations` in `gui/fmutool/__main__.py` (it also brings `logging`),
and three unused imports reported by `F401` (`gui/helper.py`: `QMainWindow`; `tests/unit/test_assembly_errors.py`:
`Path`; `gui/fmucontainer/graph/__init__.py`: `_DragWireItem`).

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| Users on 3.9 | `requires-python` makes pip select 1.9.4.2; breaking entry in `CHANGELOG.md` and note in the installation guide |
| A dependency no longer installable on 3.10 | Unchanged: the test jobs already run on 3.10 |
| Forgotten 3.9 reference in the metadata | The packaging reference (`metadata.txt`) is compared at every CI build |

## 6. Delivery

One PR for phases 1 to 3 (small change), merged before the 2.0 release; phase 4 in its own commit, so that it can be
reviewed (or reverted) apart from the functional changes.
