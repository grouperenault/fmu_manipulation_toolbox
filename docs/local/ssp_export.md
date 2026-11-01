# Plan: SSP export, stable SSP support

**Created**: 28 October 2026 — **Status**: to do — **Roadmap**: not listed —
**Origin**: what is missing for the SSP support of `fmucontainer` to be more than "alpha" —
**Depends on**: [ssp_beta.md](done/ssp_beta.md) (the reader must read back what is exported)

An assembly can be read from an SSP file but only written as JSON (or CSV): the Container Builder imports an SSP
and exports JSON, and the architecture wires and the geometry are lost. The goal of this plan is an SSP export
that the reader of fmutool reads back without loss, and that other tools can open. The SSP support becomes stable
("beta" status removed).

---

## 1. Current state

- `assembly.py`: `Assembly.write_json` (and the CSV writer) write the assembly; no SSP writer.
- JSON keys of a node: `name`, `fmu`, `path`, `container`, `step_size`, `mt`, `profiling`, `sequential`,
  `auto_link`, `auto_input`, `auto_output`, `auto_parameter`, `auto_local`, `ts_multiplier`, `reset_ports`,
  `input`, `output`, `link`, `start`.
- `AssemblyNode`: `architecture_wires` and `fmu_geometry` are read from SSP files, used by the Container Builder
  only, not written in the JSON.
- `cli/fmucontainer.py`: `-dump-json` writes `<input>-dump.json` after the build.
- `gui/fmucontainer`: **Export as JSON** (`assembly_io.save_as_json`) and **Save as FMU Container**.
- After [ssp_beta.md](done/ssp_beta.md): the reader takes parameter values as start values, without exposing them (D3
  of that plan), reads `DefaultExperiment`, and validates against the SSP XSD.

---

## 2. Decisions

| # | Question | Decision |
|---|---|---|
| E1 | What is written | Components, connectors, connections, exposed inputs and outputs of each system, nested systems; start values as `ParameterBindings`; architecture wires and geometry (`ElementGeometry`, positions of the Container Builder nodes); the container options in an annotation. |
| E2 | Container options (`step_size`, `mt`, `profiling`, `sequential`, `auto_*`, `ts_multiplier`, `reset_ports`) | Written in an `ssc:Annotation` of type `fmu_manipulation_toolbox...` on each system, so that the file is read back without loss. The step size is also written in `DefaultExperiment`. |
| E3 | Precedence of the options of the annotation when reading | The annotation **prevails** over the command line, as the step size (D9 of [ssp_beta.md](done/ssp_beta.md)). |
| E4 | SSP version written | A parameter, SSP 1.0 by default (SSP 2.0 on request). |
| E5 | Entry points | `Assembly.write_ssp()` (API), a `fmucontainer` option on the model of `-dump-json` (e.g. `-dump-ssp`), and the Container Builder. |
| E6 | FMUs | Copied into the archive under `resources/`, keeping the `path` of the instances: components sharing one FMU share one file. |
| E7 | Start values on read back | Written as `ParameterBindings`, read back as start values without exposure (D3 of [ssp_beta.md](done/ssp_beta.md)): the round trip keeps the container. |

---

## 3. Changes

### 3.1 SSP writer (`assembly.py`)

- `Assembly.write_ssp(filename, ssp_version="1.0")`: `SystemStructure.ssd` (namespaces `ssd`, `ssc`, `ssv`) and the
  FMUs (E6).
- Connectors: declared on each component from the variables of the FMU used by the links, inputs, outputs and
  start values (kind and type from the model description); on each system for its exposed ports.
- Start values: `ParameterBindings` with an inline `ssv:ParameterSet`.
- Architecture wires: the convention of `docs/user-guide/fmucontainer/container.md#architecture-wires`.
- Geometry: `ElementGeometry` from `fmu_geometry`.
- Options: annotation (E2), with a format version, and its namespace documented as the architecture wires one.
- The written file is valid against the XSD (D10 of [ssp_beta.md](done/ssp_beta.md)).

### 3.2 Reader

- Read the options annotation (E2, E3).

### 3.3 Command line (E5)

- `fmucontainer`: new option, `<input>-dump.ssp` after the build.

### 3.4 Container Builder (E5)

- **Export as SSP** next to **Export as JSON**: the positions of the nodes become the geometry, the architecture
  wires are kept.

---

## 4. Steps

1. **SSP writer** (E1, E2, E4, E6) and read back of the options (E3): round trip tests (SSP → assembly → SSP →
   assembly, same assembly; JSON → SSP → container, same container), XSD validation of the written files.
   Commit message: `Write assemblies as SSP files`
2. **Command line option** (E5). CLI test.
   Commit message: `Add an SSP dump to fmucontainer`
3. **Export as SSP** in the Container Builder (E5): geometry and architecture wires. GUI tests.
   Commit message: `Export assemblies as SSP in the container builder`
4. **Stable status**: "beta" removed from the code and the documentation.
   Commit message: `Mark the SSP support as stable`
5. **User documentation** (`container.md`: SSP export, options annotation; `gui-usage.md`: Export as SSP; CLI
   option) and CHANGELOG.
   Commit message: `Document the SSP export`
