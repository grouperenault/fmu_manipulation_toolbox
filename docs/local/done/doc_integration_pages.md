# Publication of the `integration` documentation on GitHub Pages

## Context

The documentation website (`https://grouperenault.github.io/fmu_manipulation_toolbox/`) is built by
`.github/workflows/make_doc.yml` and published only from `main`: the `deploy` job runs `mkdocs gh-deploy --force`,
which replaces the whole content of the `gh-pages` branch with the new build.

The development happens on `integration` (185 commits ahead of `main` on 2026-11-14), so the pages added since the
last release (Agent Skills, LS-XCP, LS-REF, SSP, ...) are not visible online until the next merge into `main`.

GitHub Pages serves a single site per repository: the `integration` documentation has to live in a subfolder of the
same site. Since `gh-deploy --force` wipes the whole branch, the `main` deployment has to change as well, or it would
delete the `integration` subfolder at each run.

Goal: publish the documentation of `integration` at
`https://grouperenault.github.io/fmu_manipulation_toolbox/integration/`, keep every URL of the stable documentation
unchanged, and make the development documentation clearly identifiable.

## Decisions (2026-11-14)

| # | Question | Decision |
|---|----------|----------|
| 1 | Publication scheme | Subfolder `integration/` of the `gh-pages` branch (option A). `mike` (versioned docs, URLs moved under `latest/`) is not used: it would break the existing deep links (README, PyPI, external references) |
| 2 | Identification of the development docs | The `integration` build replaces the "2.0 is out" announcement with a banner "Development version (`integration` branch)" linking to the stable documentation |
| 3 | Base branch of the work | `integration` (the workflow has to be on `integration` to trigger on its pushes). `main` gets the change at the next `integration` → `main` merge |
| 4 | Strict build gate | The `integration` deployment needs the `mkdocs build --strict` job (`needs: build`). The `main` deployment keeps its current behaviour (not gated) |
| 5 | Manual runs (`workflow_dispatch`) | Restricted by branch: the stable deployment runs only for `refs/heads/main`, the development one only for `refs/heads/integration`; a manual run on any other branch only builds (until now, a manual run from any branch published that branch at the root of the site) |

## Design

### Build channel

`mkdocs.yml` gets its channel-dependent values from environment variables (MkDocs `!ENV [NAME, default]` tag), the
defaults being the stable values so that `mkdocs serve` / `mkdocs build` are unchanged locally:

| Key | Variable | Stable (default) | Integration |
|-----|----------|------------------|-------------|
| `site_url` | `DOC_SITE_URL` | `https://grouperenault.github.io/fmu_manipulation_toolbox` | `.../fmu_manipulation_toolbox/integration/` |
| `edit_uri` | `DOC_EDIT_URI` | `edit/main/docs/` | `edit/integration/docs/` |
| `extra.channel` | `DOC_CHANNEL` | `stable` | `integration` |
| `extra.stable_url` | none | `https://grouperenault.github.io/fmu_manipulation_toolbox/` | same |

`overrides/main.html` chooses the content of the `announce` block from `config.extra.channel`: the current "2.0 is
out" announcement for `stable`, the development banner (link to `config.extra.stable_url`) for `integration`.

### Deployment

`mkdocs gh-deploy --force` is replaced by an explicit update of the `gh-pages` branch, so that each channel only
touches its own part of the site:

- **Stable** (push on `main`): `mkdocs build`, check out `gh-pages` in a separate folder, `rsync -a --delete
  --exclude integration/ --exclude .git/ site/ gh-pages/`, keep `.nojekyll`, commit and push if something changed.
- **Integration** (push on `integration`, `needs: build`): `mkdocs build` with the integration variables, `rsync -a
  --delete site/ gh-pages/integration/`, commit and push if something changed.

Both deployment jobs share a concurrency group (`gh-pages`, `cancel-in-progress: false`) so that two pushes to
`gh-pages` are serialized instead of conflicting. The `build` job and its pull request trigger are unchanged.

No third-party action is added: `rsync` and `git` are available on `ubuntu-latest`.

### Side effects

- The root `404.html`, `sitemap.xml` and search index stay those of the stable documentation; the `integration`
  subfolder has its own search index and sitemap (built with its own `site_url`).
- Until the next `integration` → `main` merge, `main` still runs `gh-deploy --force`: a push on `main` in between
  would delete `integration/`, which would come back at the next push on `integration` (or a manual run).

## Steps

### Step 1 — Channel-aware MkDocs configuration and banner

- `mkdocs.yml`: `site_url`, `edit_uri`, `extra.channel`, `extra.stable_url` as in the table above.
- `overrides/main.html`: `announce` block depending on `config.extra.channel`.
- Check: `mkdocs build --strict` without variables (output identical to today apart from the minified HTML of the
  banner block), then with `DOC_CHANNEL=integration DOC_SITE_URL=... DOC_EDIT_URI=...` (banner present, canonical
  URLs and "edit" links pointing to `integration`).

Commit message:

```
Doc: select the documentation channel from environment variables

site_url, edit_uri and the announcement banner now depend on DOC_SITE_URL,
DOC_EDIT_URI and DOC_CHANNEL. The defaults are the stable values, so local
builds are unchanged; the integration channel shows a "development version"
banner linking to the stable documentation.
```

### Step 2 — Deployment of both channels

- `make_doc.yml`: trigger on pushes to `main` and `integration`; `deploy` replaced by `deploy-stable` and
  `deploy-integration` as described above, restricted to `refs/heads/main` and
  `refs/heads/integration` respectively (decision 5).
- Check: `actionlint` if available, dry run of the `rsync` commands locally on a copy of `gh-pages`
  (stable run keeps `integration/`, integration run touches only `integration/`).

Commit message:

```
CI: publish the integration documentation under /integration/

The documentation of the integration branch is deployed to the integration/
folder of gh-pages, after the strict build. The stable deployment no longer
uses `mkdocs gh-deploy --force` and preserves this folder. Both deployments
share a concurrency group so that their pushes to gh-pages are serialized.
```

### Step 3 — First publication and verification

- After the merge into `integration`: check the workflow run, then
  `https://grouperenault.github.io/fmu_manipulation_toolbox/integration/` (banner, navigation, search, "edit"
  links) and that the stable site is unchanged.
- Check in the repository settings that Pages is still "Deploy from a branch: `gh-pages` / root" (not verifiable from
  the sources).

No commit for this step (verification only).

### Step 4 — User documentation

- `README.md`: next to the link to the documentation website, a link to the development documentation
  (`/integration/`); in "Building documentation locally", the `DOC_*` variables used to build the integration
  channel.
- Move this plan to `docs/local/done/`.

Commit message:

```
Doc: mention the development documentation of the integration branch

The README links to the documentation published from the integration branch
and lists the variables used to build it locally.
```
