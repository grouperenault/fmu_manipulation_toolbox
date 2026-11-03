# Plan: connection transformations

**Created**: 1 November 2026 — **Status**: to do — **Depends on**: [ssp_beta.md](done/ssp_beta.md) (D2),
[ssp_export.md](done/ssp_export.md)

SSP connections may transform the value they carry: `LinearTransformation` (factor, offset) and the mapping tables
`BooleanMappingTransformation`, `IntegerMappingTransformation`, `EnumerationMappingTransformation`. The reader
refuses them today (D2 of the SSP beta plan), because the container cannot apply them. The goal of this plan is a
container that applies them — in its runtime — whatever the description they come from: SSP, JSON, or the Container
Builder.

---

## 1. Current state

- **Reader** (`ssp.py`, `SSDParser._connection_child`): a transformation inside a connection raises an
  `AssemblyError` naming the connection.
- **Assembly model** (`assembly.py`): `Connection(from_port, to_port)`; JSON `link` entries are
  `[from_fmu, from_port, to_fmu, to_port]`; exposed ports are `input`/`output` entries.
- **Builder** (`container/builder.py`, `container/rules.py`): a `Link` has one source and several targets; a type
  conversion (`types.CONVERSION_FUNCTION`) gives **one converted copy per target type**, shared by all the targets of
  that type. `container.txt` has, per FMU, a conversion table `<VR_FROM> <VR_TO> <CONVERSION>`; the exposed inputs
  and outputs are in the `CONTAINER I/O` section.
- **`container.txt` format** is versioned (`CONTAINER_TXT_VERSION`): the runtime refuses another version.
- **Runtime** (`container/convert.c`, `container/container.c`): conversion functions chosen by name
  (`convert_function_get`), applied after each `doStep` of the source FMU.
- **GUI**: the links of a wire are `(from_fmu, from_port, to_fmu, to_port)` tuples (`wire.mappings`), edited in the
  wire details.

---

## 2. Decisions

| # | Question | Decision |
|---|---|---|
| T1 | Transformations supported | **The four** of SSP: `LinearTransformation`, `BooleanMappingTransformation`, `IntegerMappingTransformation`, `EnumerationMappingTransformation`; D2 of the SSP beta plan is lifted (1 November 2026). |
| T2 | Connections concerned | **Links and exposed ports**: between two components, and between a connector of the system and a component (input or output of the container) (1 November 2026). |
| T3 | Model | **A property of a link of the assembly**, also in the JSON description and editable in the Container Builder; written by the SSP export (1 November 2026). |

### To be decided at the start of the step concerned

| # | Question | Step |
|---|---|---|
| T4 | JSON syntax: an optional 5th element of a `link` entry (e.g. `{"linear": {"factor": 2, "offset": 0}}`, `{"map": [[1, 2], ...]}`), or a separate `transform` block keyed by link; and the same for `input`/`output` | 1 |
| T5 | Semantics, from the SSP standard (to be read before deciding): order of the transformation and of the type conversion; types each transformation applies to; unmapped values of a table (kept, default value, error) | 1 |
| T6 | Fan-out: a link with several targets, each with its own transformation — one transformed copy per target (more local variables), or per (type, transformation) | 3 |
| T7 | `container.txt`: transformations as new kinds of entries of the conversion table (parameters on the line), or a new table per FMU; version bump of the format | 3 |
| T8 | Runtime of the exposed ports: transformation when the importer sets a container input / gets a container output (`fmi2SetReal`… paths) | 4 |
| T9 | `EnumerationMappingTransformation`: items mapped by name, converted to values with the type definitions of both FMUs at build time | 3 |
| T10 | Container Builder: where and how a transformation is edited (wire details: a column of the link table, a dialog) | 6 |

---

## 3. Changes

- `assembly.py`: `Connection` (and the exposed ports) carry an optional transformation; JSON read and write; checks
  (types, tables).
- `ssp.py`: the reader reads the transformations instead of refusing them; the writer writes them.
- `container/`: the builder plans the transformed copies and writes them in `container.txt` (format version bumped);
  `convert.c`/`container.c`: affine and table functions, applied on links and on the container I/O.
- `gui/fmucontainer`: transformation of a link in the wire details; import and export.
- Tests: unit (model, JSON, SSP), builder (`container.txt`), native (`container/tests`), simulation (a factor and a
  table, through a link and an exposed port).

---

## 4. Steps

1. **Model and JSON** (T3, T4, T5): transformation of a link and of an exposed port, JSON syntax, checks.
   Commit message: `Transformations of the links of an assembly, in the JSON description`
2. **SSP** (T1, T2): read (D2 lifted) and write the four transformations; round trip tests.
   Commit message: `Read and write the SSP connection transformations`
3. **Builder** (T6, T7, T9): transformed copies, `container.txt` (new format version).
   Commit message: `Plan the transformations of the links in container.txt`
4. **Runtime** (T8): affine and table functions on links and container I/O; native tests.
   Commit message: `Apply the transformations of the links in the container runtime`
5. **Simulation tests**: a factor and a table, on a link and on an exposed port, compared with the expected values.
   Commit message: `Test the transformations by simulation`
6. **Container Builder** (T10): edit, import and export the transformations.
   Commit message: `Edit the transformations of the links in the container builder`
7. **User documentation** (`container.md`: transformations, JSON syntax, SSP; `gui-usage.md`;
   `container-txt-format.md`) and CHANGELOG (new `container.txt` version: containers to be built again).
   Commit message: `Document the transformations of the links`
