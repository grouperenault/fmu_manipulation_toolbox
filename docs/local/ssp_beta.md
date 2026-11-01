# Plan: SSP reader to beta

**Created**: 28 October 2026 — **Status**: in progress — **Roadmap**: not listed —
**Origin**: what is missing for the SSP support of `fmucontainer` to be more than "alpha" —
**Follow-up**: [ssp_export.md](ssp_export.md) (SSP export, stable status)

The SSP reader (`Assembly.read_ssp`, `SSDParser`) builds the routing table of a container from
`SystemStructure.ssd`. It ignores, without a word, everything that changes values: parameter values, connection
transformations, units. A real SSP file can therefore give a container that builds and simulates wrong. The goal
of this plan is a reader that either takes an SSP construction into account or says that it does not, and that is
tested with SSP files of several tools. The "alpha" status becomes "beta".

---

## 1. Current state

- `assembly.py`, `Assembly.read_ssp`: logs `This feature is ALPHA stage.`, extracts the `.fmu` files of the archive
  into `<file>.dir` (kept next to the SSP), parses `SystemStructure.ssd`.
- `assembly.py`, `SSDParser`:
  - `System`: nested systems become nested `AssemblyNode`s;
  - `Component`: `source` is read as a relative path (refused outside the archive); `type` and `implementation`
    are not read; a component without `source` is ignored with a warning;
  - `Connector`: declarations are not read;
  - `Connection`: link, exposed input or exposed output; architecture wires kept apart; child elements other than
    the architecture wire annotation are ignored (`LinearTransformation`, mappings...);
  - `ParameterBindings`, `SignalDictionary`, `SignalDictionaryReference`, `Units`, `DefaultExperiment`: ignored;
  - `ElementGeometry`: kept as a GUI hint.
- `container/builder.py`, `FMUContainer.add_input` accepts a port of causality `parameter`: it is exposed as a
  parameter of the container (used by `auto_parameter`, named `<fmu id>.<port name>`).
- `AssemblyNode.add_start_value`: start value of a port of an embedded FMU (`start` block of the JSON).
- `checker.py` validates `modelDescription.xml` with `xmlschema` (already a dependency).
- Tests: `tests/integration/test_ssp.py` (SSD variations), one real file `tests/data/containers/ssp/bouncing.ssp`
  (easySSP). No nested system test.

---

## 2. Decisions

| # | Question | Decision |
|---|---|---|
| D1 | Policy for an SSP construction that is not supported | `AssemblyError` when it would change the result of the container; warning when it has no effect on it. |
| D2 | Connection transformations (`LinearTransformation`, `BooleanMappingTransformation`, `IntegerMappingTransformation`, `EnumerationMappingTransformation`) | Refused: `AssemblyError` naming the connection. The container runtime is not changed. |
| D3 | Values of `ParameterBindings` (`.ssv`, inline or external file) | Each value becomes the start value of the parameter of the embedded FMU, as the `start` block of the JSON. The parameter is **not** exposed, so that an SSP written by fmutool is read back without change ([ssp_export.md](ssp_export.md)). |
| D4 | Exposure of the SSP parameters | Not by the bindings (D3). `auto_parameter` still exposes the parameters, as `<component>.<parameter>`. |
| D5 | `ParameterMapping` (`.ssm`) | Refused (`AssemblyError`, D1): it renames and may transform the values. |
| D6 | Component `type` other than an FMU (`application/x-fmu-sharedlibrary`) | Refused (`AssemblyError`, D1), e.g. `application/x-ssp-definition`. |
| D7 | `SignalDictionary` / `SignalDictionaryReference` | A connection through a signal dictionary is refused (`AssemblyError`, D1). A dictionary that no connection uses: warning. |
| D8 | Units | Connected connectors with different units: `AssemblyError` (SSP implies a conversion, not supported). Otherwise units are ignored, without message. |
| D9 | Step size | `DefaultExperiment` (and the step size annotations of the tools, if a test file has one) **prevails** over the command line: `:step_size` and `-step-size` are only the default. The value used is logged. |
| D10 | Validation against the SSP XSD | Warning: the validation errors are listed as warnings, and the file is read if the parser understands it. |
| D11 | Extraction folder `<file>.dir` | Unchanged: kept next to the SSP. |
| D12 | SSP files of other tools for the tests | Public examples (SSP standard examples, OMSimulator...), added only after their license is checked and recorded next to them. |
| D13 | Component without `source` | **Exception to D1**: still ignored with a warning, together with its connections (unchanged, modeler-bridge, `abbc488`). MIC modeler writes such components when the FMU of an instance is not embedded; refusing them would forbid opening a partial MIC assembly in the Container Builder. |

---

## 3. Changes

### 3.1 Unsupported constructions (`assembly.py`)

- `SSDParser`: recognize, inside a `Connection`, the transformation elements (D2); `ParameterMapping` (D5);
  `Component/@type` (D6); `SignalDictionary`, `SignalDictionaryReference` (D7). Error messages name the SSD element
  (component, connection) and the file.
- Units (D8): read `ssc:Units` and the `unit` of the connectors of each side of a connection.

### 3.2 Connectors

- Read the `Connector` declarations of components and systems.
- Check each connection against the FMUs: the connector exists as a variable of the FMU, with a compatible kind.
  The builder already refuses a wrong causality or type; the check at read time gives a message naming the SSD
  component and connector.
- Not checked: the connections of architecture wires (their connectors, `aw.<peer instance>` in the files of MIC
  modeler, are not variables of the FMUs) and the connectors of the components without `source` (D13: no FMU to
  check them against, and they are ignored).
- A connector of the system that no connection uses is not exposed (unchanged), with a debug message.

### 3.3 Parameters (D3, D4, D5)

- `ParameterBindings` of components and systems, `ParameterValues` inline (`ssv:ParameterSet`) or in an external
  `.ssv` file of the archive (`source`), with the optional `prefix`.
- Order of the bindings: the SSP rule (a later binding overrides an earlier one) — to be checked in the standard
  and written in the code comments.
- Each value: `add_start_value` on the embedded FMU (D3), the parameter is not exposed (D4).
- Value types: `Real`, `Integer`, `Boolean`, `String`, `Enumeration` (by name, converted with the FMU
  description); a parameter unknown in the FMU: `AssemblyError`.

### 3.4 Step size (D9)

- Read `DefaultExperiment` of the SSD. `Assembly`: the SSP value replaces `default_step_size`; log which one is
  used.

### 3.5 XSD validation (D10)

- Add the XSD of SSP 1.0 (and 2.0 if they differ) under `resources/ssp-1.0/` (`resources/ssp-2.0/`), with their
  license (to be checked).
- Validate `SystemStructure.ssd` with `xmlschema` before parsing; each error is a warning.

### 3.6 Tests with SSP files of other tools (D12)

- Find public SSP files (SSP standard examples, OMSimulator, ...), check and record their license, add them to
  `tests/data/containers/ssp/`. At least one nested system.
- Non-regression of modeler-bridge: an SSP written by MIC modeler (architecture wires, connector declarations with
  units, a component without `source`), once checked that it can be published in fmutool. It must still be read:
  wires kept, component without `source` ignored with a warning (D13), and no error from D8 when its units agree.
- Integration tests: build the container; simulate it when the FMUs exist for the host.

### 3.7 Status

- `read_ssp`: remove the `ALPHA` warning; docstring and documentation say "beta".

---

## 4. Steps

1. **Unsupported constructions** (D1, D2, D5, D6, D7, D8; D13 kept): errors and warnings, unit tests with modified
   SSDs, including one checking that a component without `source` is still only a warning.
   Commit message: `Refuse the SSP constructions that would change the container`
   **Done** (1 November 2026): `SSDParser` reads the connector declarations (`SSDConnector`: kind, type, unit)
   and the `ssc:Units`; the unit check waits for the end of the file (`Units` follows the systems). A connection
   with `suppressUnitConversion="true"` is not checked. Tests: `tests/unit/test_ssp_reader.py`.
2. **Connectors**: declarations read, connections checked against the FMUs. Unit tests.
   Commit message: `Check the SSP connections against the variables of the FMUs`
3. **Parameters** (D3, D4): start values from `.ssv`, inline and external. Unit tests, and a simulation test that
   the start value is used.
   Commit message: `Read the parameter values of SSP files`
4. **Step size** (D9) from `DefaultExperiment`. Unit tests of the precedence.
   Commit message: `Take the step size of an SSP file from its default experiment`
5. **XSD validation** (D10). Unit test with an invalid SSD that is still read.
   Commit message: `Validate SSP files against the SSP schema`
6. **SSP files of other tools** (D12), and an SSP written by MIC modeler (non-regression of modeler-bridge, D13):
   files, licenses, integration tests. The issues found are fixed in this step or listed here before going on.
   Commit message: `Test the SSP reader with SSP files of other tools`
7. **Beta status**: `ALPHA` warning removed.
   Commit message: `Mark the SSP reader as beta`
8. **User documentation** (`docs/user-guide/fmucontainer/container.md`, SSP section: supported and refused
   constructions, parameters, step size, validation; `gui-usage.md` if the import changes) and CHANGELOG.
   Commit message: `Document the SSP reader`
