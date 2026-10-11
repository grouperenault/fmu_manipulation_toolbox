# Several instances of the same FMU in an assembly

## Context

The GUI refuses to add an FMU that is already in the assembly (`gui/fmucontainer/graph/scene.py`, `add_node`):
"It is not yet possible to include the same FMU more than once" (ROADMAP: "support multiple instances of an FMU into
an Assembly (GUI)"). The limit is not in the GUI only: along the whole chain, the identity of an embedded FMU is its
file name.

| Layer | Today |
|-------|-------|
| GUI | `scene.add_node` refuses a second node on the same resolved path. Nodes, wires (`wire.py`, mappings keyed by `fmu_path.name`), import / export (`assembly_io.py`), details panels and the Qt MCP bridge identify an FMU by `fmu_path.name` (~70 places). Two *different* files with the same base name are accepted, and then collide in the wire mappings. |
| `Assembly` (`assembly.py`) | `AssemblyNode.fmu_names_list` holds strings that are both the name used by `link` / `input` / `output` / `start` / `drop` and the path of the file. `add_fmu` ignores a name already present. |
| JSON | `"fmu": [...]` lists these strings; `_relativize_json` / `_basename_json` rewrite them, and every reference to them, when the file is written. |
| CSV | `FMU;<file>;;;` rows; same string for name and path. |
| SSP (`SSDParser`) | Distinguishes the component name and its `source`, but two components with the same source collapse into one FMU (`add_fmu` deduplicates). |
| Builder (`container/builder.py`) | `get_fmu` caches the FMUs by base name: the same file twice gives one `EmbeddedFMU`. `EmbeddedFMU.name` / `.id` come from the file name and appear in `container.txt` and in generated variable names (`container.<id>.rt_ratio`, `auto_local`, `auto_parameter`). |
| Runtime C | Already instance-ready: each embedded FMU is extracted in its own `resources/NN` (rank in `container.txt`), its library is loaded by full path (`library.c`), the name is only used in logs. Two extractions of one FMU are two independent modules (separate global state). |
| `fmusplit` | Writes one file per FMU entry of `container.txt`, named after it. |
| MCP (headless bridge, Qt bridge, analysis, replay) | FMUs designated by base name; the headless bridge refuses two different files with one base name, and re-adding the same file does not create anything. |

## Decisions (2026-10-11)

| # | Question | Decision |
|---|----------|----------|
| 1 | Copy the FMU file to get a second instance | No |
| 2 | JSON format | Option B: `"fmu"` keeps a list of names; a new optional block `"path"` maps an instance name to its file when they differ. Written only when the assembly has instances, so every existing JSON and every assembly without instance is written as today |
| 3 | Name of the instances | `model.fmu`, then `model-1.fmu`, `model-2.fmu`, … |
| 4 | Number of a new instance | Smallest free number |
| 5 | Renaming an instance in the GUI | No: automatic name only |
| 6 | Scope of the uniqueness of the names in the GUI | The whole scene (sub-containers included) |
| 7 | CSV | Unchanged; `write_csv` refuses an assembly with instances |
| 8 | Embedding in the built container | One extraction per instance (no change of `container.txt` nor of the runtime C) |
| 9 | `fmusplit` | One file per instance (`model.fmu`, `model-1.fmu`), JSON without `"path"` block |
| 10 | MCP `add_fmu` on a file already in the assembly | Creates a new instance and returns its name |
| 11 | SSP | In scope: each component becomes an instance (first one named after the file, then `-1`, `-2`, …) |
| 12 | `replace_fmu` on an instance | This node only; its name is recomputed from the new file (smallest free name) |

Consequences, confirmed by the user (2026-10-11):

- **C1 — Same base name, different files.** Since names are unique over the scene (decision 6) and derived from
  the file name (decision 3), adding `b/model.fmu` when `a/model.fmu` is present also gives `model-1.fmu` (with a
  `"path"` entry). This fixes the current wire collision of the GUI, and replaces the error of the headless MCP
  bridge ("Another file is already embedded as …").
- **C2 — Form of the instance name in the model.** In `Assembly`, the name of an FMU is today a path-like string
  (absolute in the GUI, relativised when written). An instance name is built the same way, as a sibling of its file:
  `/models/model.fmu` → `/models/model-1.fmu`. Relativisation and `basenames_only` then keep working unchanged on the
  names, and only have to also rewrite the values of the `"path"` block. Written JSON:

  ```json
  "fmu": ["model.fmu", "model-1.fmu"],
  "path": {"model-1.fmu": "model.fmu"},
  "link": [["model.fmu", "y", "model-1.fmu", "u"]]
  ```

## Step 1 — Instances in the `Assembly` model and the JSON format

- `AssemblyNode`:
  - `add_fmu(name, path=None)`: `path` defaults to `name` (today's behaviour). Adding a name already present with
    another path raises `AssemblyError`; with the same path it stays a no-op.
  - `fmu_paths: dict[str, str]`: name → path, only for the entries whose path differs from the name; `fmu_path(name)`
    returns the file of a name.
- A shared helper `instance_name(path, used_names) -> str` (module `assembly.py`): the base name of `path` if it is
  not used, otherwise the sibling `<stem>-<n>.fmu` with the smallest free `n`; names compared by base name. It is the
  single implementation used by the GUI, the MCP bridges and the SSP reader.
- JSON: `_json_decode_node` reads the `"path"` block (a dict; each key must be listed in `"fmu"`, otherwise
  `AssemblyError`); `_json_encode_node` writes it only when `fmu_paths` is not empty. `_collect_fmu_names` /
  `_remap_fmu_refs` also handle the values of the block (relative paths, `basenames_only`).
- `AssemblyNode.make_fmu` gives the builder both the name and the path (step 2).
- `write_csv` raises `AssemblyError` when a node has instances ("use the JSON format").

Tests (`unit/`): JSON round trip with and without `"path"` (an assembly without instance is written exactly as
today, checked on the JSON files of `tests/data`); relativisation and `basenames_only` of the block; key of `"path"`
missing from `"fmu"`; same name with two paths; CSV export refused; `instance_name` (free name, smallest free
number, different directories with one base name).

**Result:** `AssemblyNode.add_fmu(fmu_name, fmu_path=None)`, `fmu_paths`, `fmu_path(name)`; `instance_name` in
`assembly.py` (keeps the separator of the given path); `"path"` block read (in any order with `"fmu"`) and written;
`write_csv` refuses instances. `AssemblyNode.make_fmu` is unchanged: until step 2, building an assembly with
instances fails on the missing file of the instance name. 20 tests in `unit/test_assembly_instances.py`. The JSON
written for every description file of `tests/data` (relative and `basenames_only`) is byte-identical before and
after the change. Suite: 1 578 passed, 2 skipped.

Commit message:

```
Separate the name of an embedded FMU from its file in the Assembly model (fmu_instances step 1)

An optional "path" block of the JSON maps an instance name to its file, so that
the same FMU can be embedded several times at one level. JSON files without
instances are read and written as before; the CSV export refuses instances.
```

## Step 2 — Instances in the container builder

- `FMUContainer.get_fmu(fmu_filename, name=None)`: the cache key and the `EmbeddedFMU` name come from `name` (base
  name), defaulting to the file name as today. `EmbeddedFMU(filename, name=None)` takes the instance name; `id` is
  its lowercase stem (`model-1`).
- Every place that uses `fmu.name` / `fmu.id` keeps working on the instance name: `container.txt`, `rt_ratio`
  variables, `auto_local` / `auto_parameter` names, datalog, step size messages.
- The extraction loop (`make_fmu_skeleton`) already extracts one directory per involved FMU: no change expected,
  checked by the tests.
- The assistant replay (`assistant/replay.py`) goes through the same `get_fmu`; it resolves the file of a name with
  the `"path"` block.

Tests: build a container with two instances of `bouncing_ball` linked to each other (`integration/`): two entries in
`container.txt`, two `resources/NN` directories, distinct generated variable names, auto-wiring per instance;
simulation of the result where the container binary is available (`needs_container`, Windows CI), which also checks
that the runtime C loads the two copies of the library independently.

**Result:** `FMUContainer.get_fmu(fmu_filename, name=None)` and `EmbeddedFMU(filename, name=None)`; a name already
loaded from another file raises `FMUContainerError`. `AssemblyNode.make_fmu` loads each FMU with its file and its
name; `replay.py` reads the file of an instance from the `"path"` block. No other change was needed: the extraction
loop, `container.txt` and the generated variables follow the instance name. Tests: 2 in
`unit/test_container_internals.py`, 1 in `unit/test_assistant_analysis.py`, 2 in `integration/test_container.py` —
one builds two independent bouncing balls (simulated and compared on Windows only: these FMUs only have win64
binaries), the other simulates two instances of `containers/mt/1.fmu`, built for every platform (run on macOS). The
`container.txt` references of the existing tests are unchanged. Suite: 1 583 passed, 2 skipped.

Commit message:

```
Embed several instances of one FMU in a container (fmu_instances step 2)

The builder identifies an embedded FMU by its instance name; each instance is
extracted in its own resources directory, so the container.txt format and the
runtime are unchanged.
```

## Step 3 — `fmusplit` and SSP

- `fmusplit`: check (test) that a container with instances is split into one file per instance (`model.fmu`,
  `model-1.fmu`) and a JSON without `"path"` block that rebuilds an equivalent container. Fix only what the test
  shows.
- `SSDParser`: a component whose `source` is already used at this level gets an instance name (`instance_name`),
  and the map component name → FMU name follows it, so that connections reach the right instance.

Tests: build → split → build round trip with instances; SSP archive built in the test with two components sharing
one source.

Commit message:

```
Support FMU instances in fmusplit and in the SSP reader (fmu_instances step 3)
```

## Step 4 — MCP server

- Headless bridge (`assistant/headless.py`): `add_fmu` on a file already in the assembly, or on another file with an
  already used base name (C1), creates an instance named by `instance_name`; the result gives the name. `remove_fmu`,
  `list_fmu_ports`, links and start values work on names; `get_assembly_json` carries the `"path"` block.
- Qt bridge (`gui/fmucontainer/mcp_bridge.py`): same behaviour, through the GUI of step 5 (its tests run in step 5).
- Analysis (`assistant/analysis.py`): `fmu_name` and the lint resolve files through the `"path"` block.
  The unit check of a link (`replay.py`, `_check_units`) reads the ports through `describe(name)` of the bridge:
  it covers instances once the bridges describe them by instance name.
- Know-how and tool descriptions (`assistant/knowledge.py`, `server.py`): `add_fmu` documents that a second add
  creates a new instance and returns its name.

Tests: `unit/test_assistant_headless.py` (second add, same base name), `unit/test_assistant_server_*.py` (contract
and descriptions), `unit/test_assistant_analysis.py` (assembly with a `"path"` block).

Commit message:

```
Create FMU instances from the MCP server (fmu_instances step 4)

add_fmu on a file already in the assembly adds a new instance and returns its
name, as the GUI does.
```

## Step 5 — GUI

- `NodeItem` gets a `name` (instance name) distinct from `fmu_path`; the title shows the name; the details panel
  and the node information dialog show both.
- `scene.add_node`: the duplicate refusal is removed; the name is given by `instance_name` over the names of every
  node of the scene (decision 6).
- Every identification by `fmu_path.name` (wires and their mappings, tree, details, view, Qt MCP bridge) uses
  `node.name` instead.
- `replace_fmu`: the node gets the smallest free name for its new file; wires, start values and exposed ports
  follow the renaming (the existing old name → new name logic).
- `assembly_io.py`: export with `add_fmu(<instance name as sibling path>, <fmu path>)` (C2); import creates each
  node with the name read from the JSON, and resolves nodes by name instead of by resolved path.

Tests (`gui/`, pytest-qt): add the same FMU twice (names, independent wires), save as JSON and reload (names, links,
start values, exposed ports kept), replace the FMU of an instance, remove an instance then add again (smallest free
number), same base name in two directories; `gui/test_assistant_qt_bridge.py`: second `add_fmu`.

Commit message:

```
Allow the same FMU several times in the Container Builder GUI (fmu_instances step 5)

A node has an instance name, distinct from its FMU file: a second add of a file
gets the name <stem>-<n>.fmu, and the wires, start values and exposed ports
follow the node by its name.
```

## Step 6 — Documentation

- `docs/user-guide/fmucontainer/container.md`: "Json Input file" section (`"path"` block, instance names), CSV
  section (no instances), SSP section (components sharing a source), Python API (`add_fmu(name, path)`).
- `docs/user-guide/fmucontainer/gui-usage.md`, "Adding FMU Nodes": adding an FMU twice, naming of the instances,
  replacing the FMU of an instance.
- `docs/user-guide/fmucontainer/ai-assistant.md`: `add_fmu` and instances.
- `docs/local/ROADMAP.md`: tick "support multiple instances of an FMU into an Assembly (GUI)".
- Move this plan to `docs/local/done/`.

Commit message:

```
Document the FMU instances (fmu_instances step 6)
```
