# Plan: documentation of the release 2.1

**Created**: 22 November 2026 — **Status**: draft, decisions D1 to D7 open — **Branch**: `doc/prepare-release`
(D1) — **Roadmap**: not listed — **Origin**: documentation audit before 2.1 (16 November 2026, the file
`docs/local/doc_audit_2.1.md`, deleted once this plan exists)

The audit of 16 November 2026 checked the user documentation before the release 2.1: `mkdocs build --strict`, each
entry of the changelog since 2.0 searched in the user guide, the screenshots made again and compared pixel by pixel
with the committed ones. It ended with seven recommendations. This plan gathers those that are still open.

### Already done (not in this plan)

| Recommendation of the audit | Done by |
|---|---|
| 1 (part). Screenshots made with PySide6 6.11.2 on macOS 27, check boxes included | `f58d4dc1` (21 November 2026) |
| 2. `fmucontainer-architecture-wire.png` made by `tools/screenshots.py`; canvas menu screenshot independent of FMPy (always shows *Simulate (with FMPy)*) | `d51b296f` |
| 4. *Simulate (with FMPy)* and `QT_FONT_DPI` documented | `33c05b2f` |
| 5. "Key Features" of `docs/index.md`: layered standards, SSP, AI agents, Model-Exchange; FMI 3.0 Model-Exchange checked | `906ad0d4` |

---

## 1. Open items

### O1 — PySide6 6.12.0 on macOS 27: no check boxes (recommendation 1)

With **PySide6 6.12.0** on macOS 27.2, the native `macos` style draws no check indicator in the item views: the
checkable cells of the Container Details panel (`mt`, `auto_link`...), of the FMU Details panel (exposed ports), of
the Configuration panel and of the Link Assistant come out empty in the screenshots. Reproduced on a plain
`QTableView` without the stylesheet of the toolbox, off screen and on screen (`grab()` and `QScreen.grabWindow`).
With PySide6 **6.9.0 and 6.11.2** on the same machine, the check boxes are drawn, off screen too
(`~/Devel/venv3.14`, PySide6 6.11.2, is the environment used for the screenshots).

Not known: whether the GUI itself, used on screen with 6.12.0, shows its check boxes (the GUI used daily has
them, but with which version of PySide6 was not recorded). `pyproject.toml:58` and `:62` ask for
`PySide6 >= 6.8.0`, with no exclusion. `docs/help/contributing.md` (section *Screenshots of the documentation*)
does not mention the version of PySide6.

### O2 — Documentation of what was merged after the audit

The audit covered the changelog up to 16 November 2026. `doc/prepare-release` does not contain the 17 last commits
of `integration` (among them `feature/log-consistency`, merged by `0f8db8e8`) nor `feature/simulink-export` (Simulink
export, documented by `08dd5cb6`). Their documentation has not been audited, and the screenshots made on the branch
do not show their changes to the GUIs.

### O3 — Minimum version of the toolbox for the skills: `2.1a1` → `2.1` (recommendation 6)

Once 2.1 is released. The occurrences of `2.1a1` (22 November 2026):

| File | Occurrences |
|---|---|
| `plugins/fmutool/skills/{fmu-inspect,fmu-edit,fmu-container}/SKILL.md` | `compatibility` field (line 3), `pip install` commands and *Too old?* paragraph (lines 23-33), in each skill |
| `plugins/fmutool/.claude-plugin/plugin.json` | `"version": "2.1.0-a1"` |
| `docs/user-guide/agent-skills.md` | lines 26, 29, 30, 60 |
| `docs/examples/agent-skills-walkthrough.md` | lines 30, 253 |
| `README.md` | line 77 |
| `tests/unit/test_agent_skills.py` | `MIN_TOOLBOX_VERSION = "2.1a1"` (line 202) |

`tests/unit/test_agent_skills.py` checks these occurrences against `MIN_TOOLBOX_VERSION`.
`test_the_plugin_version_follows_the_toolbox_it_needs` expects a pre-release (`([\d.]+)(\w+)`): with `"2.1"` it no
longer matches and must accept a final release (`2.1.0`). Not to change: `CONTRIBUTING.md`,
`docs/help/contributing.md`, `tools/check_release_tag.py`, `tests/unit/test_release_tag.py` (examples of tags), the
`CHANGELOG.md` and the plans in `docs/local/done/`.

### O4 — Launcher screenshot (recommendation 3)

`docs/gui-launcher.png` shows the version of the toolbox that made it (`version 2.1a2.dev42+g861cc07c0.d20261114`
at the audit). It must show `2.1`. The tag `V2.1` does not exist yet (last tag: `V2.1a1`).

### O5 — LinkedIn PDF (recommendation 7)

`python tools/make_carousel.py --linkedin --out tmp/release-2.1/linkedin` (needs `pip install segno`).
`tmp/release-2.1/carousel/carousel-fmu-manipulation-toolbox-2.1.pdf` exists (every slide), but no
`tmp/release-2.1/linkedin/` (the short selection of the post). `tmp/` is ignored by git: no commit.

---

## 2. Decisions (open)

None is taken. Each one is to be answered before the step concerned starts.

| # | Question | Items |
|---|---|---|
| D1 | **Branch**: everything on `doc/prepare-release`? Is `integration` (and `feature/simulink-export` once merged) merged into it, and when? | all |
| D2 | O1: check the GUI on screen with PySide6 6.12.0 on macOS 27 first; then exclude 6.12.0 in `pyproject.toml` (`PySide6 >= 6.8.0, != 6.12.0`) if the check boxes are missing, or in any case, or never? Exclude it for macOS only (environment marker)? | O1 |
| D3 | O1: write in `docs/help/contributing.md` which version of PySide6 makes the screenshots, and that each image is to be checked for its check boxes before it is committed? | O1 |
| D4 | O2: audit the documentation of the commits merged after 16 November 2026 (log consistency, Simulink export, the rest of `integration`) in this plan, and make the screenshots again after the merge? | O2 |
| D5 | O3: change the minimum version before the tag `V2.1` (the requirement then names a version not published yet, for the time between the tag and PyPI), or right after the release (the documentation of the tag still says `2.1a1`)? | O3 |
| D6 | O4: how the launcher shows `2.1`: screenshot made from a checkout of the tag `V2.1` (then committed after the release), or the version forced to `2.1` by `tools/screenshots.py` (committed before the tag)? | O4 |
| D7 | O5: make the LinkedIn PDF again, or is the existing carousel PDF the one that is posted? | O5 |

---

## 3. Steps (proposal, to be adjusted to D1)

Each step ends with the tests of the project passing (`pytest`) and `mkdocs build --strict` without warning, and a
prepared commit message.

### Step 1 — PySide6 6.12.0 (O1, D2)

- Run the GUIs on screen with PySide6 6.12.0 on macOS 27 (FMU Container Builder: Container Details, FMU Details,
  Configuration, Link Assistant): check boxes drawn or not. Record the result here.
- `pyproject.toml` according to D2 (both places: the `gui` dependency and the test dependency).

Commit message: `PySide6 6.12.0 excluded: no check boxes in the item views on macOS 27` (if D2 excludes it)

### Step 2 — Documentation merged after the audit (O2, D4) — only if D4 keeps it

- Merge according to D1; each new entry of `CHANGELOG.md` since 16 November 2026 searched in the user guide; gaps
  fixed.
- `tools/screenshots.py` run again (PySide6 6.11.2, `~/Devel/venv3.14`), the images compared with the committed ones,
  each checked for its check boxes; only the changed ones committed.

Commit message: `Doc: features merged after the audit of 16 November 2026; screenshots made again`

### Step 3 — Minimum version 2.1 (O3, D5)

- `MIN_TOOLBOX_VERSION = "2.1"`; `test_the_plugin_version_follows_the_toolbox_it_needs` accepts a final release.
- Every occurrence of the table of O3; `plugin.json`: `"version": "2.1.0"`.

Commit message: `Agent skills: they need fmu-manipulation-toolbox 2.1`

### Step 4 — Launcher screenshot (O4, D6)

- According to D6; the image checked (version `2.1`, nothing else changed).

Commit message: `Screenshot of the launcher with version 2.1`

### Step 5 — LinkedIn PDF (O5, D7) — no commit

- According to D7, into `tmp/release-2.1/linkedin/`.

### Step 6 — User documentation

- `docs/help/contributing.md`, section *Screenshots of the documentation*: according to D3.
- `docs/installation.md` or the requirements of the GUIs, if D2 excludes a version of PySide6.
- `CHANGELOG.md` (*Upstream*): the exclusion of PySide6 6.12.0 if D2 keeps it.
- Then move this plan to `docs/local/done`.

Commit message: `Doc: release 2.1`
