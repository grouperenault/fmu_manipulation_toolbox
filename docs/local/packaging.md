# Plan: modern packaging (`pyproject.toml`)

**Created**: 9 October 2026 — **Updated**: 10 October 2026 (phases 0 to 3 done; pre-release 0.0.dev3 published to PyPI) — **Starting branch**: `integration`
**Scope**: `setup.py`, `setup.cfg`, `requirements.txt`, `fmu_manipulation_toolbox/version.py`, `tests/pytest.ini`, the
`ci.yml` and `release.yml` workflows, the user documentation about installation.

File names in this plan are relative to the root of the repository.

---

## 1. Current state

The package is described by a 174-line `setup.py` executed at build time, without any `pyproject.toml`. pip therefore
builds it with the fallback backend of setuptools (`setuptools.build_meta:__legacy__`).

| # | Finding | Where |
|---|---|---|
| C1 | **The version comes from a GitHub Actions environment variable.** `setup.py` reads `GITHUB_REF_NAME` (the tag name), writes a temporary `__version__.py` whose *docstring* is the version, then deletes it. Outside the CI, or when the name does not look like a version, the version is `0.0.dev0`. | `setup.py:7-24`, `version.py` |
| C2 | **The version format check is weak**: `re.match(r"[A-Za-z]?\d+(\.\d)+", version)` accepts only one-digit components after the first one, and only checks the start of the string. | `setup.py:13` |
| C3 | **The displayed version keeps the tag prefix** (`V1.9.4rc4` in the CLI banners and in `generationTool="FMUContainer-V1.9.4rc4"` of the containers), whereas the version published on PyPI is normalized (`1.9.4rc4`). | `version.py`, `container.py` |
| C4 | **The package list is written by hand** (10 sub-packages). It is complete today, but a sub-package added without updating it would be missing from the wheel; only the wheel tests (`smoke-wheel`) would notice, and only if they import it. | `setup.py:30-39` |
| C5 | **The PyPI description is a string written in `setup.py`**, distinct from the README: two texts to maintain. | `setup.py` (`long_description`) |
| C6 | **The dependencies are declared twice**: in `setup.py` (`install_requires`, extras `mcp`, `gui`, `test`, `all`) and in `requirements.txt` (runtime, GUI, MCP and tests mixed). The bounds of `fastmcp` are duplicated. | `setup.py`, `requirements.txt` |
| C7 | **`setup.cfg` only holds a legacy setting** (`[build] build_scripts=build/scripts`). | `setup.cfg` |
| C8 | **The tests do not test the installed package**: `pytest.ini` adds the repository root to the import path (`pythonpath = . ..`), and the CI installs `requirements.txt`. Only `smoke-wheel` installs the wheel. | `tests/pytest.ini`, `ci.yml` |
| C9 | **The wheel is universal (`py3-none-any`) and contains the binaries of every platform.** This is **required** and must be kept: a container built on one OS embeds the C runtime of each target OS (`make_fmu_skeleton` copies `resources/<platform>/container.*` for every platform common to the embedded FMUs), and remoting adds the win32/win64 binaries whatever the host OS. | `container.py` (`get_platforms`, `make_fmu_skeleton`), `remoting.py` |
| C10 | **The binaries are not tracked by git**: the CI compiles them (`build-native.yml`) and puts them in `resources/` before the build. `package_data` lists them one by one. | `setup.py:40-56`, `.gitignore` |
| C11 | *(found in phase 0)* **The sdist ships the 11 prebuilt binaries but none of the C sources** (`container/`, `remoting/`, `fmi/`): it cannot rebuild what it contains, and is close to a repackaged wheel. | `tests/data/packaging/sdist-files.txt` |

**What works and must be kept**: publication through OIDC (*Trusted Publishing*, bound to the `release.yml` file name),
tests gating the publication, `smoke-wheel` on 3 OS, `gui` / `mcp` extras keeping the CLI lightweight.

---

## 2. Goals

1. **A single source for the metadata**: `pyproject.toml` (PEP 621), static and readable by tools.
2. **The version comes from git tags** (`setuptools-scm`): no environment variable, no file written then deleted.
3. **A single source for the dependencies**: the extras; `requirements.txt` disappears or becomes a pointer.
4. **The CI tests the installed package**, not the source tree.
5. **Nothing changes for users**: same distribution name, entry points and extras, same wheel content (except for the
   listed, intended differences), same release process.

**Out of scope**: changing the build backend (setuptools remains the right choice: the package is pure Python with data
files), building per-platform wheels (see C9), the supported Python versions (§3, D5).

---

## 3. Decisions to take

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | **PyPI description** | (a) `README.md`; (b) a dedicated file (`docs/pypi.md`); (c) keep the string of `setup.py` | **Decided: (a)** (10 October 2026). The relative images and links of the README need absolute URLs, otherwise they are broken on PyPI (done in phase 1) |
| D2 | **Displayed version** (banners, `generationTool`) | (a) normalized PEP 440 version (`1.9.4rc4`); (b) keep the prefix (`V1.9.4rc4`) | **Decided: (a)** (10 October 2026): it is the one shown by pip and PyPI. Visible change, to be announced in `CHANGELOG.md` (phase 5) |
| D3 | **sdist content** | Today: package, 11 prebuilt binaries, no C sources (C11). With `setuptools-scm`, **every file tracked by git** goes into the sdist by default: 1.5 MB of package, but also 10.8 MB of `tests/`, 3.7 MB of `docs/` and the C sources (`container/`, `remoting/`, `fmi/`, 0.6 MB) | **Decided** (10 October 2026): Python package + C sources; exclude `tests/data`, `docs/`, `.github/` **and the prebuilt binaries**. Consequence: the wheel must be built from the sources, not from the sdist (`python -m build --sdist --wheel`) |
| D4 | **`requirements.txt`** | (a) delete it; (b) reduce it to `-e .[all]` | **Applied: (b)** (10 October 2026, as recommended) for one release, so as not to break habits and documentation, then (a) |
| D5 | **Python versions** | Python 3.9 reached end of life in October 2025 but is still declared and tested (`smoke-wheel`); Python 3.14 is missing from the CI and the classifiers | **Out of this plan**: to be decided separately; this plan only carries over the current `requires-python` (`>=3.9`) |
| D6 | **Test tools** | (a) `test` extra (current); (b) *dependency groups* (PEP 735, `pip install --group test`, pip ≥ 25.1) | **(a)** for now: the extra is documented for users; (b) once the CI can assume a recent pip |

---

## 4. Plan

### Phase 0 — Safety net

1. **Reference inventory of the current package.** A script builds the wheel and the sdist and writes, sorted: the file
   list of each archive and the relevant metadata (`Requires-Dist`, `Provides-Extra`, `Requires-Python`,
   `entry_points.txt`, classifiers). The output of the current `setup.py` is tracked in `tests/data/packaging/`.
2. **Make the tests independent of the version.** Five container references (`REF-*modelDescription*.xml`) contain
   `generationTool="FMUContainer-0.0.dev0"`: they only pass because the tests run on the source tree, without a version.
   Add `generationTool` to `VOLATILE_XML_ATTRIBUTES` (`tests/_helpers/assertions.py`). The other files containing
   `0.0.dev0` (52) are frozen test FMUs: they do not change.

*Exit criterion*: reference inventory tracked; test suite green.

**Status on 10 October 2026: done.**

| Item | File |
|---|---|
| Inventory script: builds the wheel and sdist from a temporary copy of the files tracked by git (untracked local files never leak in); `--placeholder-binaries` creates empty files with the expected names of the 11 CI-built binaries, enough for an inventory of names; `--write DIR` / `--check DIR` (unified diff, exit status 1 on a difference). Requires the `build` package | `tools/dist_inventory.py` |
| Reference inventory of the current `setup.py`: wheel tag (`py3-none-any`), wheel files (122), sdist files (127), metadata (48 lines), entry points (5 console + 4 GUI scripts) | `tests/data/packaging/` |
| `generationTool` added to the volatile XML attributes | `tests/_helpers/assertions.py` |

Checks performed:

- with a simulated real version (`__version__.py` = `1.2.3`), the 5 container references failed before the change and
  pass after it; the simulation file was removed afterwards;
- `--check` reports no difference on an unchanged tree, and reports a removed file as a diff;
- full suite: 1921 tests passed.

### Phase 1 — `pyproject.toml`, version still computed by `setup.py`

1. Create `pyproject.toml`:
   - `[build-system]`: `setuptools >= 77` (SPDX license expression, PEP 639);
   - `[project]`: name, description, `readme` (D1), `requires-python`, `license = "BSD-2-Clause"`,
     `license-files = ["LICENSE.txt"]`, authors, keywords, classifiers, URLs, `dependencies`, `optional-dependencies`
     (`mcp`, `gui`, `test`, `all`), `scripts` and `gui-scripts`;
   - `dynamic = ["version"]`: `setup.py` **only** keeps the version computation, to decouple the two changes;
   - `[tool.setuptools.packages.find]`: `include = ["fmu_manipulation_toolbox*"]` replaces the hand-written list (C4);
   - `[tool.setuptools.package-data]`: same patterns as today, binaries included. Keep explicit patterns rather than
     `**/*`: `resources/` may contain stray files (`.DS_Store`, `.gitkeep`).
2. Delete `setup.cfg` (C7) and the `long_description` of `setup.py` (C5).
3. Check with `validate-pyproject` and `twine check --strict dist/*`.

*Exit criterion*: `python tools/dist_inventory.py --placeholder-binaries --check tests/data/packaging` reports no
difference except the intended ones (PyPI description, D1); `smoke-wheel` green on the 3 OS.

**Status on 10 October 2026: done** (`smoke-wheel` confirmed by the release of 0.0.dev3, see phase 2).

| Item | File |
|---|---|
| `pyproject.toml`: static metadata (PEP 621), SPDX license (PEP 639), extras, scripts, package discovery with `namespaces = false`, explicit `package-data`, `include-package-data = false` | `pyproject.toml` |
| `setup.py` reduced to the version computation (`setup(version=...)`), with the same `GITHUB_REF_NAME` logic as before | `setup.py` |
| `setup.cfg` removed | — |
| D1: the PyPI description is the README; its 8 relative references (2 images, 6 links) now use absolute URLs (`raw.githubusercontent.com` for images, GitHub pages for files, the published documentation for the container guide) | `README.md` |
| `--untracked` option of the inventory script, to check new files before adding them to git | `tools/dist_inventory.py` |
| Reference inventory updated to the new state | `tests/data/packaging/` |

Findings during the phase:

- **The project directory is no longer on the import path of `setup.py`.** With a `pyproject.toml`, setuptools uses the
  `setuptools.build_meta` backend instead of the legacy one, which added it. `setup.py` imports
  `fmu_manipulation_toolbox.version` for the default version, so it now inserts its own directory in `sys.path`; this
  disappears with `setup.py` in phase 2.
- **`include-package-data` is true by default with `pyproject.toml`** (it was false with `setup.py`). It made setuptools warn
  that `resources/` and its sub-directories look like packages missing from the configuration. Set back to `false`: the
  data files are listed explicitly anyway.
- **Not only the two images of the README were relative**: 6 links were too (container guide, `requirements.txt`,
  `operations.py`, contributing guide, changelog, license). The anchors of the table of contents (`#…`) are kept: they may
  not work on PyPI, which does not always generate heading ids, but they are harmless.

Checks performed:

- inventory compared with the phase 0 reference: wheel files, wheel tag and entry points **identical**; metadata: only the
  3 intended differences, because PEP 621/639 have no exact equivalent of the former fields — `Author:
  Nicolas.LAURENT@Renault.com` becomes `Author-email: Nicolas LAURENT <Nicolas.LAURENT@Renault.com>`, `Home-page` becomes
  `Project-URL: Homepage`, `License` becomes `License-Expression`; sdist: `pyproject.toml` added (the `setup.cfg` still
  listed is the one setuptools always generates in an sdist);
- `validate-pyproject`: valid; `twine check --strict`: wheel and sdist PASSED (README rendering on PyPI);
- full suite: 1921 tests passed.

### Phase 2 — Version from git tags (`setuptools-scm`)

1. `[build-system] requires` += `setuptools-scm >= 8`; `[tool.setuptools_scm] version_file =
   "fmu_manipulation_toolbox/_version.py"` (generated file, added to `.gitignore`).
2. `version.py`: read `_version.py`, then `importlib.metadata.version("fmu_manipulation_toolbox")`, then `0.0.dev0`
   (source tree without installation).
3. **Check that `V…` tags are read**: the repository tags start with `V` (`V1.9.4rc4`). The default regular expression of
   `setuptools-scm` should accept a `v`/`V` prefix; to be confirmed with `python -m setuptools_scm` on the repository,
   otherwise set `tag_regex`.
4. Delete `setup.py` (C1, C2).
5. CI: `fetch-depth: 0` (or at least the tags) on the jobs that build the package. With a shallow clone, `setuptools-scm`
   does not find the last tag and produces a wrong version.
6. Archives without a git repository ("Source code" of the GitHub releases): add `.git_archival.txt` and the matching line
   in `.gitattributes`, otherwise the version cannot be found outside a clone.
7. Apply D2 and D3 (sdist exclusion patterns), and update the reference inventory on purpose.

*Exit criterion*: on a tag, package version = normalized tag; between two tags, development version
(`1.9.5.devN+g<commit>`); `pip install -e .` gives a version; dry-run release succeeds (§5).

**Status on 10 October 2026: done.** The dry-run release was made on PyPI itself with a development pre-release
(§5): tag `V0.0dev3`, version `0.0.dev3`.

| Item | File |
|---|---|
| `setuptools-scm >= 8` in `[build-system]`; `[tool.setuptools_scm] version_file = "fmu_manipulation_toolbox/_version.py"` (ignored by git) | `pyproject.toml`, `.gitignore` |
| `version.py`: `_version.py`, then `importlib.metadata`, then `0.0.dev0` (source tree neither built nor installed, e.g. the test suite) | `fmu_manipulation_toolbox/version.py` |
| `setup.py` removed | — |
| Version of archives without git (`git archive`, "Source code" of the GitHub releases) | `.git_archival.txt`, `.gitattributes` |
| D3: sdist content | `MANIFEST.in` |
| CI: `fetch-depth: 0` on the job that builds the package; `python -m build --sdist --wheel`; release comment updated | `.github/workflows/ci.yml`, `release.yml` |
| Inventory script: builds in a temporary local clone (setuptools-scm needs the history, and lists the files tracked by git for the sdist), overlaid with the working copy and indexed in the clone (its index is independent); `--sdist --wheel` | `tools/dist_inventory.py` |
| Reference inventory updated | `tests/data/packaging/` |

Findings during the phase:

- **`V…` tags need no configuration**: `setuptools-scm` 10.3.4 reads `V1.9.4.2` as `1.9.4.2` and `V1.9.4rc4` as
  `1.9.4rc4`; between tags it gives e.g. `1.9.4.3.dev77+gb774220fb`.
- **D3 changes how the wheel must be built.** By default, `python -m build` builds the sdist, then the wheel *from the
  sdist*: without binaries in the sdist, the wheel would have none either. The CI and the inventory script now build both
  from the sources. `smoke-wheel` (which checks the binaries in the wheel) guards against a regression.
- **The former wheels shipped `__version__.py`** (written by `setup.py` during the build); the new ones ship `_version.py`.
- **`package.py`** (repository root, tracked): an old script zipping the `build/` directory. It is now part of the sdist
  like every tracked file, and looks obsolete; to be removed or documented (not done, pending a decision).

Checks performed:

- simulation in a temporary clone, binaries present but untracked as in the CI: tag `V9.9.9` → `9.9.9` (wheel and sdist,
  11 binaries in the wheel); tag `V9.9.10rc1` → `9.9.10rc1`; no tag → `9.9.10rc2.dev1+g<commit>`; `git archive` of the tag,
  without git → `9.9.9` (from `.git_archival.txt`);
- displayed version (D2): the `fmutool` banner of the installed wheel shows `version 9.9.9`; an editable install
  (`pip install -e .`) gives `9.9.9`;
- inventory: wheel identical except `__version__.py` → `_version.py`; sdist: C sources (`container/`, `remoting/`, `fmi/`),
  test code, `MANIFEST.in`, `.git_archival.txt`, `.gitattributes`, `CHANGELOG.md`… added, the 11 prebuilt binaries and
  `setup.py` removed, `tests/data`, `docs/` and `.github/` excluded; metadata unchanged;
- both workflows are valid YAML; full suite: 1921 tests passed.

**Release of `0.0.dev3` (10 October 2026).** The tag `V0.0dev3` went through the whole `release.yml` pipeline: native
builds, tests, package, `smoke-wheel` on the 3 OS (the publish job depends on the whole CI), publication to PyPI through
*Trusted Publishing*, GitHub pre-release. Checks on the published files, downloaded from PyPI:

- PyPI metadata: version `0.0.dev3`, `License-Expression: BSD-2-Clause`, `Requires-Python: >=3.9`, the 5 project URLs,
  description = the README (Markdown, absolute image URLs);
- the wheel (1,002,318 bytes) and the sdist (793,710 bytes) are **identical to the reference inventory** on the five
  inventory files (wheel files, wheel tag, metadata, entry points, sdist files);
- the wheel contains the 11 real binaries (none empty) and `_version.py` = `0.0.dev3`;
- the sdist contains 39 C sources, no prebuilt binary, no `tests/data`, no `docs/`;
- the published wheel, installed in a clean environment, shows `FMU Manipulation Toolbox version 0.0.dev3` and `fmucontainer
  -h` works.

`0.0.dev3` is a development pre-release lower than `1.9.4.2`: neither `pip install fmu-manipulation-toolbox` nor
`pip install --pre` select it; only an explicit `==0.0.dev3` does.

### Phase 3 — Dependencies and development environment

1. `requirements.txt` → `-e .[all]` (D4).
2. CI: `pip install -e ".[all]"` instead of `pip install -r requirements.txt`; `pytest.ini`: `pythonpath = .` (the
   installed package replaces the `..`) (C6, C8).

*Exit criterion*: suite green in the CI with the installed package.

**Status on 10 October 2026: done** (green CI on the next push to be confirmed).

| Item | File |
|---|---|
| `requirements.txt` reduced to `-e .[all]`, with a comment (D4); `[all]` holds everything the former file listed, plus `numpy` and `importlib_metadata` (Python < 3.10 only) | `requirements.txt` |
| CI: the three test jobs run `pip install -e ".[all]"` instead of `pip install -r requirements.txt` | `.github/workflows/ci.yml` |
| `pytest.ini`: `pythonpath = .` (only `tests/`, for `_helpers` and `conftest`); the package comes from the installation | `tests/pytest.ini` |
| `*.egg-info` ignored (written by editable installs, like `_version.py`) | `.gitignore` |

Findings during the phase:

- **The test jobs keep a shallow clone.** The editable install runs setuptools-scm, which does not fail on a shallow clone:
  without the tags it gives `0.1.dev1+g<commit>`. This version only shows in the logs of the test jobs, and the container
  references ignore it since phase 0 (`generationTool` is volatile); the job that builds the package fetches the whole
  history (phase 2).
- **The integration test of the stdio MCP server** sets its own `PYTHONPATH` to the repository root for its subprocess: it
  works with or without installation, unchanged.
- **Local development changes**: running the tests now requires the package to be installed in the environment
  (`pip install -e ".[all]"`, or `pip install -r requirements.txt`, from the repository root); without it, pytest stops
  with `ModuleNotFoundError: No module named 'fmu_manipulation_toolbox'`. To be documented in phase 5.

Checks performed, reproducing the CI: shallow clone of the current changes, macOS binaries added, clean Python 3.14 virtual
environment, `pip install -r requirements.txt`: install succeeds; the package is imported from the clone (editable);
full suite **1921 passed, 2 skipped**, GUI tests included; `git status` stays clean (`_version.py` and `*.egg-info`
ignored).

### Phase 4 — Automatic checks

- In the job that builds the package: `validate-pyproject`, `twine check --strict dist/*`, and
  `tools/dist_inventory.py --check tests/data/packaging` (with the real binaries): any difference fails the job, the
  reference is updated on purpose.
- In `smoke-wheel`, on a tag: the installed version must equal the normalized tag.

*Exit criterion*: a mistake in `package-data` or a wrong version fails the CI before publication.

### Phase 5 — User documentation

- `README.md`: installation and development sections (`requirements.txt` is mentioned there), images with absolute URLs
  if D1 (a) is chosen.
- `docs/installation.md`: `requirements.txt` is described line by line; replace with the extras.
- `CONTRIBUTING.md` and `docs/help/contributing.md`: development installation (`pip install -e ".[all]"`, pip ≥ 21.3 for
  editable installs with `pyproject.toml`), how to run `tools/dist_inventory.py`, how a release gets its version from the
  tag.
- `CHANGELOG.md`: displayed version without the `V` prefix (D2), new sdist content (D3), `requirements.txt` (D4).

*Exit criterion*: no reference to `setup.py` or to the former `requirements.txt` content left in the user documentation.

---

## 5. Dry-run release

Publication cannot be tested locally. Before merging phase 2:

1. push a pre-release tag (`V…rc…`) on a test branch;
2. publish to **TestPyPI** rather than PyPI: TestPyPI *Trusted Publisher* pointing to `release.yml`, and a conditional
   `repository-url` for `pypa/gh-action-pypi-publish`; or a `workflow_dispatch` that stops after the build;
3. install from TestPyPI in a clean environment, on the 3 OS, and run `fmutool -h`, `fmucontainer -h`,
   `fmutool-mcp --help`.

PyPI rejects local versions (`+g<commit>`): a publication outside a tag on TestPyPI needs
`local_scheme = "no-local-version"`.

**Done on 10 October 2026** with a variant: rather than TestPyPI, a development pre-release (`V0.0dev3` → `0.0.dev3`) was
published to PyPI itself, which no default installation selects. Results in phase 2.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| File forgotten in, or wrongly added to, the wheel (binary, XSD, image) | Reference inventory (phase 0) compared at every build (phase 4) |
| Wrong version in the CI (shallow clone) or in a GitHub archive | `fetch-depth: 0`; `.git_archival.txt`; version = tag check in `smoke-wheel` |
| Visible change of the displayed version (`V1.9.4rc4` → `1.9.4rc4`) | Decision D2, `CHANGELOG.md` entry; test references made independent of the version (phase 0) |
| Broken *Trusted Publishing* | The `release.yml` name and the publish job do not change; dry-run release on TestPyPI |
| Editable install with an old pip | PEP 660 needs pip ≥ 21.3: stated in the contribution guide (phase 5) |
| Locally built binaries differ from the CI ones | Unchanged by this plan: the CI inventory uses the CI artifacts |

## 7. Delivery

One PR per phase. Phases 0 and 1 change nothing for users. Phase 2 is the only one touching publication: the dry-run
release (§5) is its merge condition. Phase 3 can follow immediately; phase 4 can ship with phase 2 or later; phase 5
closes the plan.
