# Refactoring: moving `modelDescription.xml` handling to ElementTree

**Date**: 9 October 2026 — **Branch**: `features/mcp` — **Scope**: `operations.py`, `container.py`, `split.py`, `checker.py`

File names in this plan are relative to the root of the repository.

---

## 1. Why

The code reads and writes `modelDescription.xml` by hand, with two mechanisms:

- **read/rewrite**: `Manipulation` (`operations.py`) parses with `xml.parsers.expat`, element by element, then
  **regenerates** the XML with `print()` calls. Every `FMU.apply_operation()` rewrites the descriptor, even for a read-only
  operation (`-summary`, `-check`, `EmbeddedFMU`);
- **generation**: `container.py` produces the `modelDescription.xml` of the container with f-strings
  (`EmbeddedFMUPort.xml()`, `HEADER_XML_2/3`, `make_fmu_xml()`).

Defects found, most of them reproduced with an empty operation (`OperationAbstract`):

| # | Defect | Where | Fixed by ElementTree? |
|---|---|---|---|
| D1 | Text between tags is not escaped: `x &lt; y` becomes `x < y`, hence invalid XML | `Manipulation.char_data` | ✅ by construction |
| D2 | `<Start value>` of FMI-3 `String`/`Binary` not escaped | `FMUPort.write_xml` | ✅ by construction |
| D3 | Attributes unescaped twice: `a &amp;lt; b` becomes `a &lt; b` | `Manipulation.escape` | ✅ by construction |
| D4 | Sub-elements of a variable lost: `<Annotations>` (FMI-2), `<Alias>` (FMI-3), several `<Start>` (`String` arrays) | `start_element` / `FMUPort.write_xml` | ✅ if the tree is **modified in place** instead of regenerated |
| D5 | Comments and `<?xml?>` declaration dropped. **Not compliant**: FMI-2 §2.2 and FMI-3 §2.4 require the first line to declare the UTF-8 encoding | `Manipulation` | ⚠️ only if explicitly requested (`TreeBuilder(insert_comments=True)`, `xml_declaration=True`) |
| D6 | Consequence of D1/D2: the **second** operation of a chain raises `ExpatError` (e.g. `fmutool -remove-toplevel -check`) | — | ✅ |
| D7 | Container XML not escaped (`description`, `name`… attributes copied as is from the embedded FMUs) | `EmbeddedFMUPort.xml`, `HEADER_XML_*` | ✅ fixed in phase 4 |
| D8 | Container: `encoding="ISO-8859-1"` declared, but the file is opened in `"wt"` **without an encoding**, hence written with the locale encoding (UTF-8 on Linux/macOS, cp1252 on Windows). **Not compliant**: both standards require UTF-8 | `container.py:2020`, `:1465`, `:1502` | ✅ fixed in phase 4 |
| D9 | `-remove-sources` deletes `sources/` but leaves `<SourceFiles>` in the descriptor | `OperationRemoveSources` | ➖ not automatic, but becomes trivial |
| D10 | An operation that removes **every** variable (e.g. `-keep-only-regexp` without a match) produces an empty `<ModelVariables>`, forbidden by both the FMI-2 and FMI-3 XSD. The tool then delivers an invalid FMU without warning | `Manipulation` | ➖ no; an explicit guard is needed (error or warning) |
| D11 | FMI-2: the `derivative` attribute (1-based index of the state, §2.2.7) **is not renumbered** when ports are removed. In `tests/data/me/velocity_me.fmu`, after `rename_from_csv`, `Deriv1` points to itself | `Manipulation` (only `<Unknown index>` and `dependencies` are renumbered) | ➖ no; to be handled in phase 2 |
| D12 | Removing a variable referenced by another one leaves a **dangling reference**: `derivative` (FMI-2 and FMI-3), `previous`, `clocks`, `<Dimension valueReference>` (FMI-3) | `Manipulation` | ➖ no; refuse the operation or remove in cascade (decision in phase 2) |
| D13 | Renaming operations (`-remove-toplevel`, `-trim-until`…) can give **the same name** to several variables, although names (and FMI-3 aliases) must be unique (FMI-3 §2.4 *uniqueNameAttribute*). The XSD does not check it. Seen on 5 FMUs of `tests/data` (`ls-bus/bus`, `split/container-*`) | renaming operations | ➖ no; guard in phase 2 |
| D14 | *(found in phase 2)* The former rewriting dropped the empty `<Start value="">` of FMI-3 `Binary` variables and the `<Dimension start="1">` elements: an array of size 1 became a scalar. Seen on the ls-bus FMUs of `tests/data` | `FMUPort.write_xml` | ✅ fixed in phase 2 (tree modified in place) |
| D15 | *(found in phase 4)* FMI-2 container: the `<Outputs>`/`<InitialUnknowns>` indexes were computed by hand without counting the `ts_multiplier`, `solver` and profiling variables. As soon as one of them was present, `<ModelStructure>` designated **local** variables instead of the outputs (FMI-2 §2.2.8). The `REF-modelDescription-profiling.xml` reference contained this defect | `make_fmu_xml_epilog_2` | ✅ fixed in phase 4 (indexes computed from the position of the elements) |

D1 to D6 and D9 to D14 are reproduced by tests (phases 0 to 2) and **fixed in phase 2**; D7, D8 and D15 are reproduced and
fixed in phase 4. For D10, D12 and D13, the chosen policy is to **refuse** the operation (`OperationError`, FMU left
untouched).

**What ElementTree does not fix** (handled separately): raw `BadZipFile` instead of `FMUError` and clean-up of the temporary
directory in `__del__` (fixed in phase 3), exit status of `-check` always 0 (fixed in phase 5).

**Short answer**: yes, start with ElementTree rather than fixing the bugs one by one. Bugs D1 to D4, D6 and D7 all come from
the same choice: writing XML by hand. Fixing them one by one in `Manipulation` would amount to reimplementing an XML
serializer. **On one condition**: first set up the test safety net of phase 0. The existing tests compared files **byte by
byte** (`assert_identical_files`), whereas a change of serializer necessarily changes the bytes (`<X></X>` becomes `<X/>`,
spaces inside tags, etc.) without changing the meaning.

---

## 2. Constraints: the public API to preserve

`OperationAbstract` and `FMUPort` are documented as extension API (`docs/user-guide/fmutool/python-api.md`, custom
checkers loaded dynamically by `checker.py`). They are also used internally:

| Consumer | What it uses |
|---|---|
| `container.py` (`EmbeddedFMU`) | `port_attrs`, `fmu_port.fmi_type = "Integer"` (Enumeration → Integer), `fmu_port.get("start")`, `FMUPort` given to `EmbeddedFMUPort`, `fmu.tmp_directory` |
| `gui/fmueditor` | `fmu_port[key] = value`, **`fmu_port.attrs_list[0][key] = value`**, iteration over `attrs_list` |
| `checker.py` | `fmi_attrs`, then XSD validation of `fmu.descriptor_filename` **on disk** |
| `remoting.py`, `terminals.py` | files of `fmu.tmp_directory` |
| `assistant/fmutools.py` | `FMU(...).apply_operation(...)` |
| Internal operations | `ManipulationSkipTag` (raised from `port_attrs` to remove a port) |

We therefore keep:

- `FMU`: `fmu_filename`, `tmp_directory`, `descriptor_filename`, `fmi_version`, `apply_operation(op, apply_on)`,
  `repack()`, `save_descriptor()`;
- `FMUPort`: `[]`, `get()`, `in`, `fmi_type`, `attrs_list`, `dimensions`;
- `OperationAbstract`: every callback, in the same call order (`fmi_attrs` → variables → `ModelStructure` → `closure`);
- **the descriptor written to disk after every `apply_operation`**, so that the XSD checker and the tools reading
  `tmp_directory` keep working.

With ElementTree, `Element.attrib` is a real `dict`. If `FMUPort.attrs_list` becomes `[sv.attrib, child.attrib]` (FMI-2)
or `[var.attrib]` (FMI-3), the changes made by the operations, including the direct access of `fmueditor` to
`attrs_list[0]`, go **directly into the tree**, without any copy. Changing `fmi_type` amounts to renaming the tag of the
child element.

---

## 3. Plan

### Phase 0 — Safety net (before touching the code)

1. **Canonical comparison**: add `assert_equivalent_xml(a, b)` to `tests/_helpers/assertions.py`, based on
   `xml.etree.ElementTree.canonicalize()` (C14N 2.0, `strip_text=True`). The tests comparing `modelDescription.xml` files
   (`test_operations.py`, `test_container.py`, `test_array.py`, `test_split.py`…) switch to this comparison. Byte-by-byte
   comparisons remain for the other files (`container.txt`, CSV).
2. **Characterization tests**: for every `.fmu` of `tests/data`, apply every built-in operation and check C14N equivalence
   with the **current** output. The references are generated once with the current code and tracked in
   `tests/data/refactoring/`. The test FMUs do not exercise bugs D1 to D4, so these references are reliable.
3. **Regression tests of the bugs**, marked `xfail(strict=True)` until phase 2:
   - round trip with an empty operation: `canonicalize(before) == canonicalize(after)` on a descriptor containing escaped
     text, `<Annotations>`, `<Alias>`, a `String` `<Start>` with `"` and `<`, and a comment;
   - two chained operations on this same descriptor (D6);
   - descriptor always well-formed and **XSD-valid** after every built-in operation.
4. **Baseline measurement**: time and memory of an `apply_operation` on a large synthetic descriptor (~100,000 variables),
   to check in phase 2 that building a full tree stays acceptable.

*Exit criterion*: suite green, new `xfail` tests failing for the expected reasons.

**Status on 9 October 2026: done.**

| Item | File |
|---|---|
| `canonical_xml()`, `assert_equivalent_xml()`, `VOLATILE_XML_ATTRIBUTES` (replaces `assert_identical_files_but_guid`, removed) | `tests/_helpers/assertions.py` |
| Tests of the helper: it ignores formatting, but not an attribute, a text, an escaping level, an extra element or the order of elements | `tests/unit/test_xml_assertions.py` |
| `modelDescription.xml` comparisons switched to C14N | `tests/integration/test_array.py`, `test_container.py` |
| Characterization: 48 FMUs × 8 modifying operations + 4 read-only operations (compared to `noop.xml`), CSV dump and `-summary` report | `tests/integration/test_operations_characterization.py` |
| References (1.2 MB, canonical form, regenerated with `pytest --update-refs`) | `tests/data/refactoring/<fmu>/` |
| XSD validity after every modifying operation (all test FMUs are valid to begin with) | `test_operation_keeps_descriptor_valid` |
| Tests of defects D1 to D6, D9 and `BadZipFile`, as `xfail(strict=True, raises=…)`: each is only accepted with the exception the defect raises | `tests/unit/test_xml_roundtrip.py` |
| Benchmark (outside the suite) | `tests/benchmarks/bench_manipulation.py` |

Checks performed:

- two deliberate mutations of `operations.py` (shifted renumbering, stray attribute in FMI-3) are detected by the
  characterization (257 and 269 failures);
- the 9 cases where `keep_only_regexp` empties `<ModelVariables>` are marked `xfail` (D10) instead of being hidden.

Baseline measurement (`python tests/benchmarks/bench_manipulation.py`). The *ET parse+write* line is not an operation: it
is a plain ElementTree read/write of the same file, to estimate the cost of a full tree right away.

Python 3.14.8 — macOS-26.6.1-arm64-arm-64bit-Mach-O — best of 3 runs

| FMI | Variables | Descriptor | Operation | Time | Peak memory (tracemalloc) |
|---|---:|---:|---|---:|---:|
| 2.0 | 1,000 | 0.2 MB | noop | 0.01 s | 0.4 MB |
| 2.0 | 1,000 | 0.2 MB | remove 10% | 0.01 s | 0.4 MB |
| 2.0 | 1,000 | 0.2 MB | *ET parse+write (estimate)* | 0.00 s | 1.5 MB |
| 2.0 | 10,000 | 1.8 MB | noop | 0.05 s | 1.3 MB |
| 2.0 | 10,000 | 1.8 MB | remove 10% | 0.05 s | 1.4 MB |
| 2.0 | 10,000 | 1.8 MB | *ET parse+write (estimate)* | 0.05 s | 11.6 MB |
| 2.0 | 100,000 | 18.2 MB | noop | 0.54 s | 10.4 MB |
| 2.0 | 100,000 | 18.2 MB | remove 10% | 0.53 s | 11.1 MB |
| 2.0 | 100,000 | 18.2 MB | *ET parse+write (estimate)* | 0.47 s | 113.8 MB |
| 3.0 | 1,000 | 0.1 MB | noop | 0.00 s | 0.4 MB |
| 3.0 | 1,000 | 0.1 MB | remove 10% | 0.00 s | 0.4 MB |
| 3.0 | 1,000 | 0.1 MB | *ET parse+write (estimate)* | 0.00 s | 1.1 MB |
| 3.0 | 10,000 | 1.3 MB | noop | 0.04 s | 1.3 MB |
| 3.0 | 10,000 | 1.3 MB | remove 10% | 0.04 s | 1.4 MB |
| 3.0 | 10,000 | 1.3 MB | *ET parse+write (estimate)* | 0.03 s | 9.2 MB |
| 3.0 | 100,000 | 13.0 MB | noop | 0.45 s | 10.4 MB |
| 3.0 | 100,000 | 13.0 MB | remove 10% | 0.45 s | 11.1 MB |
| 3.0 | 100,000 | 13.0 MB | *ET parse+write (estimate)* | 0.34 s | 89.0 MB |

**Reading**: time is not an issue; the full tree is even slightly faster. Memory is more of one: about 6 times the size of
the descriptor (114 MB for 18 MB), against ~10 MB with SAX. Acceptable for a desktop or CI tool, but the point to watch.

### Phase 1 — `ModelDescription` core

New module `fmu_manipulation_toolbox/model_description.py`, without any dependency on the rest:

- `ModelDescription.load(path)`: parses with `ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))`.
  Also records the namespace prefixes found (`iterparse` on `start-ns`, then `ET.register_namespace`), so that vendor
  annotations do not come out as `ns0:`;
- `fmi_version`, `root`, `model_variables`, `model_structure`, `parent_of(element)`;
- `iter_ports()`: one `FMUPort` per variable (FMI-2: `ScalarVariable` + typed child; FMI-3: typed element, `<Dimension>`,
  `<Start>`);
- `save(path)`: `tree.write(path, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)`, the encoding
  expected by the FMI standard.

Dedicated unit tests: FMI-2 and FMI-3 loading, C14N round trip, namespaces, comments.

**Consistency with the FMI-2 and FMI-3 specifications.** The module must follow what the specifications published on
[fmi-standard.org](https://fmi-standard.org/) say, not only what the current code does, which grew with the FMUs met over
time. For each version:

1. **Identify the reference version**: find the exact minor version of the bundled XSDs (`resources/fmi-2.0/`,
   `resources/fmi-3.0/`; their headers do not state it), compare it with the latest published version of each standard
   (2.0.x and 3.0.x), and update the XSDs if needed, in a separate PR.
2. **Build a conformity matrix** in this document: element or attribute of the standard → section of the specification →
   handling by `model_description.py` → test covering it. Points to check at least:

   | Topic | FMI-2 | FMI-3 |
   |---|---|---|
   | Variables | `<ScalarVariable>` with exactly one typed child (`Real`, `Integer`, `Boolean`, `String`, `Enumeration`), then optional `<Annotations>` | One element per type (`Float32`/`Float64`, `Int8`…`UInt64`, `Boolean`, `String`, `Binary`, `Enumeration`, `Clock`); children `<Dimension>`, `<Start>` (`String`/`Binary`), `<Alias>`, `<Annotations>` |
   | Type definitions | `<TypeDefinitions>/<SimpleType>` with children **named like** the variable types: must not be taken for variables | `<TypeDefinitions>` with `Float64Type`, `EnumerationType`… |
   | Arrays | — | `<Dimension start>` or `<Dimension valueReference>` (structural parameter); multi-valued `start` attribute for numeric types |
   | `ModelStructure` | `<Outputs>`, `<Derivatives>`, `<InitialUnknowns>` → `<Unknown index dependencies dependenciesKind>`, **1-based** `index` in the order of `<ModelVariables>` | `<Output>`, `<ContinuousStateDerivative>`, `<ClockedState>`, `<InitialUnknown>`, `<EventIndicator>`, referenced by `valueReference` |
   | Interface types | `<ModelExchange>`, `<CoSimulation>` | same + **`<ScheduledExecution>`**, which no `OperationAbstract` callback handles today |
   | Order of the root elements | The one imposed by the XSD: serialization must not change it | same |
   | Encoding, XML declaration, namespaces | What the specification requires or recommends for the file | same |
   | Side files | — | `terminalsAndIcons/terminalsAndIcons.xml`, `buildDescription.xml`, layered standards (`extra/`): outside `ModelDescription`, but must not be broken |

3. **Test on FMUs covering the standard**, not only on those of `tests/data`: consider the
   [Reference FMUs](https://github.com/modelica/Reference-FMUs) of the Modelica project (FMI-2 and FMI-3, BSD-2 license),
   which exercise arrays, clocks, `Binary`, `ScheduledExecution`, etc. Each case of the matrix is covered by a test, and every
   descriptor loaded then saved stays **XSD-valid** and C14N-equivalent.
4. **Record the deviations**: any behaviour of the current code contradicting the specification is added to the defect
   table (D11…), with the phase fixing it. It is not reproduced silently.

*Exit criterion*: complete conformity matrix, with no unjustified "not handled" entry; tests green on the FMUs of
`tests/data` and on the chosen reference sample.

**Status on 9 October 2026: done.**

| Item | File |
|---|---|
| `ModelDescription` / `ModelVariable` / `ModelDescriptionError` module, without any dependency on the rest of the package | `fmu_manipulation_toolbox/model_description.py` |
| Descriptors of the Reference FMUs v0.0.41 (6 FMI-2, 9 FMI-3, 76 KB, BSD-2 license) | `tests/data/reference-fmus` |
| Tests of the module (296): loading, errors, C14N round trip **with comments**, UTF-8 declaration, XSD validity kept, structure, compatibility with `FMUPort` | `tests/unit/test_model_description.py` |
| Tests of the deviations from the standard D11 to D13, as `xfail(strict=True)` | `tests/unit/test_operations_conformity.py` |

Design choices:

- `iter_ports()` returns `ModelVariable` objects, not `FMUPort`: importing `operations.py` would create a cycle in phase 2.
  `ModelVariable` exposes the same interface (`[]`, `get()`, `in`, `fmi_type`, `attrs_list`, `dimensions`), but
  `attrs_list` holds the `attrib` of the tree elements. In phase 2, `FMUPort` becomes `ModelVariable` (alias or subclass,
  because of the `isinstance(attrs, FMUPort)` of `EmbeddedFMUPort`);
- the FMI-3 `<Start>` elements (`String`/`Binary`) appear as `{"start": value}` levels, as in `FMUPort`, but reads and
  writes go to the `<Start>` element itself;
- `test_model_variable_reads_like_fmu_port` compares, variable by variable, what `ModelVariable` and the current `FMUPort`
  read on the 63 descriptors. They are identical, including the convention "a single `<Dimension start="1">` = scalar";
- the XML declaration is written by hand (`<?xml version="1.0" encoding="UTF-8"?>`, double quotes as in the example of the
  specification), because ElementTree would write single quotes;
- comments and processing instructions **before or after** the root: `TreeBuilder` ignores them, so they are captured
  separately (`prolog`, `epilog`);
- namespaces: the prefixes are registered right before writing (the ElementTree registry is global).

Checks performed: three deliberate mutations of the module (`<Start>` levels omitted, comments outside the root misplaced,
dimension convention) are detected (6, 1 and 3 failures).

**Reference version of the XSDs** (file-by-file comparison with the sources of `modelica/fmi-standard`):

| Standard | Bundled XSDs | Latest published version | Difference |
|---|---|---|---|
| FMI 2.0 | **2.0.4** (identical file by file) | 2.0.5 | Only the header comments (copyright, version number): no schema difference. Update possible for traceability, not urgent |
| FMI 3.0 | **3.0.2** (identical) | 3.0.2 | None |

**Conformity matrix** (FMI 2.0.5 / FMI 3.0.2; section numbers computed from the asciidoc sources of
`modelica/fmi-standard` at tags `v2.0.5` and `v3.0.2`):

| Rule of the standard | Source | `model_description.py` | Test |
|---|---|---|---|
| First line: XML declaration, **UTF-8 mandatory** | FMI-2 §2.2, FMI-3 §2.4 | Declaration always written, output always UTF-8 whatever the input encoding | `test_saved_file_starts_with_utf8_declaration`, `test_non_utf8_input_is_saved_in_utf8` |
| The order of the elements is meaningful (FMI-2 index, FMI-3 state vector) | FMI-2 §2.2, FMI-3 §2.4 | Tree modified in place, order kept | `test_roundtrip_is_equivalent` (C14N, order is meaningful) |
| FMI-2 variables: `<ScalarVariable>` + one typed child, optional `<Annotations>` | FMI-2 §2.2.7 | `variables()`, `ModelVariable.typed_element`; annotations kept | `edge/fmi2-variable-annotations` |
| FMI-2 `<TypeDefinitions>/<SimpleType>`: same tag names as the variable types | FMI-2 §2.2.3 | Only the children of `<ModelVariables>` are variables | `test_fmi2_type_definitions_are_not_variables` (Reference FMU `2.0/Feedthrough`) |
| FMI-3 variables: 15 types, including `Binary` and `Clock` | FMI-3 §2.4.7 | `FMI3_VARIABLE_TYPES` | Reference FMUs `3.0/Feedthrough`, `3.0/Clocks` |
| FMI-3 arrays: `<Dimension start>` or `<Dimension valueReference>` | FMI-3 §2.4.7.2 | `ModelVariable.dimensions` | Reference FMU `3.0/StateSpace`, `test_model_variable_dimension_of_one_is_scalar` |
| FMI-3 `start` of `String`/`Binary`: sequence of `<Start value>` elements | FMI-3 §2.4.7.5 | `_StartValue` levels, all kept | `test_model_variable_fmi3_start_elements` |
| FMI-3 aliases `<Alias name>` | FMI-3 §2.4.7.3 | Kept (tree modified in place) | `edge/fmi3-alias`, Reference FMU `3.0/BouncingBall` |
| **Unique** variable and alias names | FMI-3 §2.4 *uniqueNameAttribute*, FMI-2 §2.2.7 | Outside the scope of the module (read/write) | Deviation of the operations: **D13** |
| FMI-2 `ModelStructure`: 1-based `<Unknown index>` | FMI-2 §2.2.8 | `model_structure_entries()` → `(section, <Unknown>)` | `test_fmi2_model_structure_entries` |
| FMI-3 `ModelStructure`: `Output`, `ContinuousStateDerivative`, `ClockedState`, `InitialUnknown`, `EventIndicator` by `valueReference` | FMI-3 §2.4.8 | `model_structure_entries()` → `(tag, element)` | `test_fmi3_model_structure_entries` |
| FMI-2 `derivative` = **index** of the state | FMI-2 §2.2.7 | Exposed as is (attribute) | Deviation of the operations: **D11** |
| References between FMI-3 variables (`derivative`, `previous`, `clocks`, `<Dimension valueReference>`) | FMI-3 §2.4.7 | Exposed as is | Deviation of the operations: **D12** |
| Interface types: at least one of `ModelExchange`, `CoSimulation`, `ScheduledExecution` (FMI-3) | FMI-3 §2.4.1 | `interfaces` (all three) | `test_interfaces` (including `3.0/Clocks`, `ScheduledExecution` **only**) |
| FMI-3 `<Annotations>/<Annotation type>`: arbitrary XML content, namespaces allowed | FMI-3 §2.4 | Prefixes kept | `test_namespace_prefixes_are_kept` |
| Side files (`terminalsAndIcons.xml`, `buildDescription.xml`, `extra/`) | FMI-3 §2.4.9, §2.4.10, §2.5 | Out of scope: not touched | — |
| *"It is not allowed to change the start values in the modelDescription.xml"* (FMI-3; *"not recommended"* in FMI-2) | FMI-3 §2.4.7.5, FMI-2 §2.2.7 | Out of scope | Checked: neither `fmueditor` nor the operations change `start` values (the container applies them at run time) |

Known, justified limits:

- a **default namespace** (`xmlns="…"` without a prefix) in an annotation is written back with a generated prefix (`ns0:`).
  It is equivalent XML, but not identical text. ElementTree cannot do better; no case met in the 63 descriptors;
- the textual form changes (`<X></X>` → `<X/>`, quotes, position of the `xmlns` declarations), without changing the meaning;
- the characterization reference `tests/data/refactoring/me__velocity_me/rename_from_csv.xml` contains defect D11. It will
  have to be regenerated on purpose when phase 2 fixes it.

### Phase 2 — `Manipulation` rewritten on the tree

`Manipulation.manipulate()` keeps its signature, but now:

1. loads the `ModelDescription`;
2. calls `fmi_attrs`, `cosimulation_attrs`, `modelexchange_attrs`, `experiment_attrs` on the `attrib` of the relevant
   elements;
3. walks the variables: `port_attrs(FMUPort)`. If the operation asks for a removal (non-zero value or `ManipulationSkipTag`),
   the element is removed from `<ModelVariables>` and the renumbering table is recorded (`port_translation`,
   `port_removed_vr`);
4. walks `<ModelStructure>` with the same logic as today (`unknown_attrs`, `handle_structure`). The current `delayed_tag`
   mechanism removing empty sections becomes a plain clean-up afterwards;
5. `closure()`, then `save()` to `descriptor_filename`.

`escape()`, `char_data`, `skip_until`, `delayed_tag*` and `FMUPort.write_xml()` are then removed. `push_attrs` and the
`dimensions` setter are kept as deprecated aliases (`DeprecationWarning`), in case user scripts call them.

Along the way, removing `<SourceFiles>` in `OperationRemoveSources` becomes simple (D9).

*Exit criterion*: the `xfail` tests of phase 0 pass (the `xfail` markers are removed), the characterization tests are
C14N-equivalent, and the benchmark meets, on 100,000 variables: time ≤ 1.5 × the SAX baseline, memory ≤ 8 × the size of
the descriptor.

**Status on 9 October 2026: done.**

| Item | File |
|---|---|
| `Manipulation` rewritten on `ModelDescription`: callbacks in document order, tree modified in place, batched removals | `fmu_manipulation_toolbox/operations.py` |
| `FMUPort` becomes a subclass of `ModelVariable`. Detached `FMUPort()` and `push_attrs()` remain available with a `DeprecationWarning`; `write_xml()`, `escape()` and the expat parser are removed | `operations.py` |
| `OperationAbstract.model_description`: access to the whole tree for what the callbacks cannot express | `operations.py` |
| `PrefixedAttributes`: the callbacks still receive `xsi:noNamespaceSchemaLocation`, not `{http://…}noNamespaceSchemaLocation` | `model_description.py` |
| D9: `OperationRemoveSources` also removes `<SourceFiles>`, and now acts on Model Exchange-only FMUs | `operations.py` |
| Refusal for D10, D12, D13 and renumbering for D11; strict tests (no more `xfail`) | `tests/unit/test_operations_conformity.py` |
| `xfail` of D1 to D6 and D9 removed; tests of D14 added | `tests/unit/test_xml_roundtrip.py` |
| Characterization references updated (see below); `remove_sources` moves to the modifying operations; a refused operation has a `<case>.error` reference | `tests/integration/test_operations_characterization.py`, `tests/data/refactoring/` |
| Documentation: callbacks, `model_description`, refusals; API page of the module; `CHANGELOG.md` | `docs/user-guide/fmutool/python-api.md`, `docs/API/model_description.md`, `mkdocs.yml` |

**Review of the modified characterization references.** Every change is explained by a fixed defect; nothing else moved:

| Change | Count | Cause |
|---|---:|---|
| `<case>.xml` replaced by `<case>.error` "remove every variable" | 9 | D10 (`keep_only_regexp`) |
| `<case>.xml` replaced by `<case>.error` "still referenced" | 10 | D12: states (`derivative`), structural parameters (`Dimension`), clocks (`clocks`) |
| `<case>.xml` replaced by `<case>.error` "same name" | 10 | D13 (`strip_top_level`, `trim_until_dot` on 5 FMUs) |
| `derivative` renumbered (and checked: it points to the right state) | 6 | D11 |
| `<Start value="">` and `<Dimension start="1">` restored | 14 files | D14 (ls-bus FMUs) |
| `xmlns:xsi = …` line missing from the `summary.txt` report | 3 | `xmlns` declarations are not attributes |
| New `remove_sources.xml`: equal to `noop.xml` except for `<SourceFiles>` | 48 (2 with `<SourceFiles>`) | D9 |

A script checked the invariants on the 403 accepted outputs: no dangling reference, no duplicate name introduced, no empty
`<ModelVariables>`, every FMI-2 `derivative` points to the same state as before the operation.

Checks performed:

- the 21 new defect tests **fail on the phase 1 code** (commit `8e63a40`) and pass on phase 2. The 5 tests passing on both
  are safeguards: plain round trip, refusal limited to what the operation itself breaks (duplicates and dangling references
  already present in the original FMU are not reported);
- the full suite passes (1763 tests, 1 remaining `xfail`: `BadZipFile`, phase 3), including with
  `-W error::DeprecationWarning`: the package no longer uses the deprecated API.

**Benchmark** (criterion: time ≤ 1.5 × the SAX baseline, memory ≤ 8 × the size of the descriptor, on 100,000 variables):

Python 3.14.8 — macOS-26.6.1-arm64-arm-64bit-Mach-O — best of 3 runs

| FMI | Variables | Descriptor | Operation | Time | Peak memory (tracemalloc) |
|---|---:|---:|---|---:|---:|
| 2.0 | 1,000 | 0.2 MB | noop | 0.01 s | 1.5 MB |
| 2.0 | 1,000 | 0.2 MB | remove 10% | 0.01 s | 1.5 MB |
| 2.0 | 1,000 | 0.2 MB | *ET parse+write (estimate)* | 0.00 s | 1.5 MB |
| 2.0 | 10,000 | 1.8 MB | noop | 0.06 s | 12.6 MB |
| 2.0 | 10,000 | 1.8 MB | remove 10% | 0.07 s | 13.3 MB |
| 2.0 | 10,000 | 1.8 MB | *ET parse+write (estimate)* | 0.04 s | 11.6 MB |
| 2.0 | 100,000 | 18.2 MB | noop | 0.63 s | 126.2 MB |
| 2.0 | 100,000 | 18.2 MB | remove 10% | 0.72 s | 133.7 MB |
| 2.0 | 100,000 | 18.2 MB | *ET parse+write (estimate)* | 0.48 s | 113.8 MB |
| 3.0 | 1,000 | 0.1 MB | noop | 0.00 s | 1.2 MB |
| 3.0 | 1,000 | 0.1 MB | remove 10% | 0.00 s | 1.2 MB |
| 3.0 | 1,000 | 0.1 MB | *ET parse+write (estimate)* | 0.00 s | 1.1 MB |
| 3.0 | 10,000 | 1.3 MB | noop | 0.04 s | 10.1 MB |
| 3.0 | 10,000 | 1.3 MB | remove 10% | 0.05 s | 10.2 MB |
| 3.0 | 10,000 | 1.3 MB | *ET parse+write (estimate)* | 0.03 s | 9.2 MB |
| 3.0 | 100,000 | 13.0 MB | noop | 0.50 s | 101.4 MB |
| 3.0 | 100,000 | 13.0 MB | remove 10% | 0.54 s | 102.5 MB |
| 3.0 | 100,000 | 13.0 MB | *ET parse+write (estimate)* | 0.35 s | 89.0 MB |

| 100,000 variables | SAX baseline | Phase 2 | Ratio | Memory / descriptor |
|---|---:|---:|---:|---:|
| FMI 2.0, noop | 0.54 s | 0.63 s | 1.17 | 6.9 × |
| FMI 2.0, remove 10 % | 0.53 s | 0.72 s | 1.36 | 7.3 × |
| FMI 3.0, noop | 0.45 s | 0.50 s | 1.11 | 7.8 × |
| FMI 3.0, remove 10 % | 0.45 s | 0.54 s | 1.20 | 7.9 × |

Criterion met. Two corrections were needed: the first version took 4.8 s for `remove 10 %`, because `Element.remove()` is
linear and was called once per removed element; removals are now batched. FMI-3 memory is close to the limit: it is the
cost of the ElementTree tree itself (6.8 × for a plain read/write).

### Phase 3 — Life cycle of `FMU` (independent, small)

- `zipfile.BadZipFile` → `FMUError`;
- `FMU` becomes a context manager (`__enter__`/`__exit__`), and the clean-up uses `weakref.finalize` instead of `__del__`;
- the CLI also catches `ET.ParseError` and turns it into a clear message.

**Status on 9 October 2026: done.**

| Item | File |
|---|---|
| Opening: `BadZipFile`, directory (`IsADirectoryError`/`PermissionError`), missing file, missing descriptor → `FMUError`; the temporary directory is removed at once on failure | `operations.py` (`FMU`) |
| `weakref.finalize` replaces `__del__`: the clean-up also happens at interpreter exit, and no longer raises if the directory is already gone | `operations.py` |
| `close()`, `closed`, `__enter__`/`__exit__`; a closed `FMU` raises `FMUError` ("is closed") instead of a file-not-found error | `operations.py` |
| `with FMU(...)` where the lifetime is bounded: `fmutool` CLI, MCP tools (`fmutools.py`, `headless.py`), GUI graph nodes. The objects living as long as their owner (`EmbeddedFMU`, FMU shown by the `fmutool` GUI) keep the automatic clean-up | `cli/fmutool.py`, `assistant/`, `gui/fmucontainer/graph/node.py` |
| CLI: an unreadable descriptor arrives as `FMUError` since phase 2 (no longer as `ET.ParseError`); the operation loop now catches it (exit status −6, renumbered in phase 5) | `cli/fmutool.py` |
| Tests: life cycle (`tests/unit/test_fmu_lifecycle.py`, 16 tests) and 3 new CLI cases (not a zip file → −4, unreadable descriptor → −6, refused operation → −6; codes renumbered in phase 5); last `xfail` removed | `tests/` |
| Documentation: Python API guide, `CHANGELOG.md` | `docs/user-guide/fmutool/python-api.md`, `CHANGELOG.md` |

Checks performed: 14 of the new tests fail on the phase 2 code; the other 11 are existing tests or cases that were already
correct (missing file, phase 2 refusal). Full suite: 1781 tests, **no `xfail` left**.

Not handled here, as planned: the exit status of `-check` (always 0) and the negative CLI exit codes, left to phase 5.

### Phase 4 — Container generation on ElementTree

- `EmbeddedFMUPort.xml()` returns an `ET.Element` instead of a string;
- `make_fmu_xml()` builds the tree (FMI-2/FMI-3 header, `ModelVariables`, `ModelStructure`) and writes it with `save()` from
  the phase 1 module. This fixes D7 and D8;
- test references: `REF-*modelDescription*.xml` compared with C14N (phase 0), ignoring the volatile attributes (`guid`,
  `generationDateAndTime`…) listed in `VOLATILE_XML_ATTRIBUTES`;
- add a test with an embedded FMU whose `description` contains `&`, `"` and non-ASCII characters.

**Status on 9 October 2026: done.**

| Item | File |
|---|---|
| `EmbeddedFMUPort.xml()` returns an `ET.Element` (or `None` if the type cannot be exposed) instead of a string | `container.py` |
| `make_fmu_xml()` builds the whole tree (header, `CoSimulation`, `LogCategories`, `DefaultExperiment`, variables, `ModelStructure`) and writes it with `ModelDescription.save()`: UTF-8, XML declaration. `HEADER_XML_2/3` and `make_fmu_xml_epilog_2/3` are removed | `container.py` |
| D15: FMI-2 indexes computed from the actual position of the outputs; `<Outputs>`/`<InitialUnknowns>` sections written only when they have entries (an empty section is forbidden by the XSD) | `container.py` |
| Tests of D7/D8 (FMI-2 and FMI-3: description, output name and author with `&`, `<`, `"`, non-ASCII characters; UTF-8 declaration; XSD validity) and D15 (profiling, `ts_multiplier`, both, none; FMI-3) | `tests/integration/test_container_xml.py` |
| Corrected reference: `<Unknown index>` 4, 5 → 6, 7 (D15), the only difference found on the 5 container references | `tests/data/containers/bouncing_ball/REF-modelDescription-profiling.xml` |

Checks performed: on the phase 3 code, 5 of the 7 new tests fail (the other 2 are cases that were already correct: FMI-2
without an added port, FMI-3); D7 reproduced separately (`description="Position & "height" < 10 m"` → `ParseError`). Full
suite: 1788 tests.

### Phase 5 — Finishing

- `split.py`: replace its read-only expat parser with `ModelDescription`. No known bug; the benefit is consistency;
- `checker.py`: rely on the tree to add semantic rules (unique valueReferences/names, `ModelStructure` indexes,
  causality/variability/initial combinations), replace `validate()` with `iter_errors()`, and make `-check` return a
  non-zero exit status;
- CLI: replace the negative exit codes (`sys.exit(-3)` gives 253 on POSIX) with documented positive codes. This breaks
  scripts testing these values: to be announced in `CHANGELOG.md`;
- only rewrite the descriptor when it was modified (modification flag), then parse it once per FMU instead of once per
  operation. **Warning**: `EmbeddedFMU` currently changes `fmi_type` (Enumeration → Integer) during an operation supposed
  to be read-only. Check that nothing depends on this change being written to disk before changing this behaviour.

**Status on 9 October 2026: done.**

| Work item | Result | Files |
|---|---|---|
| `split.py` | expat parser replaced with `ModelDescription`. Also fixes a `KeyError` on an FMI-3 variable without `causality` (default: `local`). An unreadable descriptor raises `FMUSplitterError` | `split.py`, `tests/unit/test_split_parsing.py` |
| Write only when modified, parse once | `FMU.model_description` keeps the tree; it is parsed again if the file changes on disk (time, size). New `OperationAbstract.read_only` attribute (default `False`, always safe). Operations marked: `OperationSummary`, `OperationSaveNamesToCSV`, both checkers, `EmbeddedFMU`, and the GUI and MCP collectors. After a failure, refusal included, the cached tree is discarded | `operations.py`, `tests/unit/test_fmu_descriptor_cache.py` |
| Checker | `iter_errors()`: every XSD error. New `OperationSemanticCheck` (rules of FMI 2.0.5 §2.2.7–2.2.8 and FMI 3.0.2 §2.4–2.4.8, read again in the sources of the specification). `get_checkers()` no longer piles up the entry-point checkers | `checker.py`, `tests/unit/test_checker_semantic.py` |
| Exit codes | Table shared by the three CLIs (`ExitCode`): 2 usage, 3 input unreadable, 4 invalid input, 5 operation refused or failed, 6 output cannot be written, 7 `-check` non-compliant | `cli/`, `tests/integration/test_cli_errors.py`, `docs/user-guide/fmutool/cli-usage.md` |

Checks performed:

- **`EmbeddedFMU`**: the container re-extracts every embedded FMU from its original archive (`make_fmu_skeleton`), never
  from the extracted descriptor. The Enumeration → Integer change can therefore stay in memory: `EmbeddedFMU` is marked
  `read_only`;
- **semantic checker**: no error on the 63 descriptors (`tests/data` and Reference FMUs), and each of the 29 tested
  violation cases (at least one per rule) is reported;
- **measured gain** on 100,000 variables: `-summary` goes from 0.84 s to 0.56 s, and `summary + merge + summary` from
  2.86 s to 1.31 s;
- the full suite passes: 1898 tests.

**Addendum: removal of `ModelStructureCounter`.** This class rebuilt `nx`/`nz` from the callbacks (`register_port`,
`model_structure_attrs`). It is replaced by `ModelDescription.model_exchange_sizes()`, which computes the same values on the
tree, with the same warnings. `OperationSummary`, `EmbeddedFMU` and the `summarize_fmu` MCP tool use it. Checks: `EmbeddedFMU`
values identical to those of the former code on the 48 FMUs of `tests/data` (6 non-zero, pinned in
`tests/unit/test_model_exchange_sizes.py`); `summary.txt` characterization reports unchanged; the tests of the former class
are carried over (`git mv`).

---

## 4. Risks

| Risk | Mitigation |
|---|---|
| Change of textual form (spaces, `<X/>`, prefix order) breaking third-party tools doing textual diffs | C14N in tests; `ET` keeps the attribute order and the text/`tail`, so the textual diff stays small |
| Namespaces written back as `ns0:` | Prefixes recorded at load time (phase 1) and dedicated test |
| Memory on very large descriptors | Benchmark in phases 0/2; if needed, `iterparse` for read-only operations (phase 5) |
| User scripts depending on internals of `Manipulation` | Only `OperationAbstract`/`FMUPort` are documented; deprecated aliases for `push_attrs`/`dimensions`; `CHANGELOG.md` entry |
| Malicious XML (entity bomb) | Unchanged risk compared with today (same expat parser). libexpat ≥ 2.4.1 protects against exponential expansion; check `pyexpat.version_info` on the target platforms, or use `defusedxml` |

## 5. Delivery

One PR per phase. Phase 0 can be merged alone without risk. Phases 1 and 2 are the core of the change. Phases 3 and 4 are
independent of each other and can proceed in parallel once phase 1 is merged.

## 6. Notes for a future plan

Outside the scope of this refactoring: to be taken up at the **next major version**.

### Removal of `FMUPort`

Since phase 2, `FMUPort` is only a subclass of `ModelVariable`. It only adds the deprecated "detached" mode: `FMUPort()`
without an element, `push_attrs()` and the `dimensions` setter. The name stays for now, because it is part of the
documented public API (`python-api.md`, custom checkers) and `container.py` tests `isinstance(attrs, FMUPort)`.

At the major version:

1. use `ModelVariable` internally: `isinstance(attrs, ModelVariable)` in `EmbeddedFMUPort` (`container.py`), type
   annotations of `fmueditor`, `checker.py` and the built-in operations;
2. present `ModelVariable` as the reference type in `python-api.md`;
3. remove the detached mode, `push_attrs()` and the `dimensions` setter (deprecated since phase 2);
4. reduce `FMUPort` to an alias (`FMUPort = ModelVariable`) with a `DeprecationWarning` at import, then remove it in a later
   version;
5. `CHANGELOG.md` entry (API break); adapt `tests/unit/test_operations_errors.py`, which tests the detached mode.

### SSD parser of `assembly.py` — done on 9 October 2026

`SSDParser` read SSD files (SSP) with expat, without namespace processing: tags were recognized by their literal prefix
(`'ssd:Connection'`, `'ssd:System'`…). Finding: a valid SSD with another prefix or a default namespace produced no system,
and `read_ssp` failed with `AttributeError`.

Result: `ET.iterparse` and qualified names (`SSDParser.SSD_NAMESPACE`, SSP 1.0). The root element is checked; an SSD in
another namespace, not well-formed, or referring to an unknown element raises `AssemblyError`. `start_element()` and
`end_element()` now receive the local name (`"Connection"`) instead of the prefixed one (`"ssd:Connection"`). Tests:
`tests/integration/test_ssp.py` (variants of the easySSP `bouncing.ssp` with another prefix and a default namespace,
compared with the same JSON reference; three error cases). The 5 tests fail on the former code. Still to do: test with SSD
files written by tools other than easySSP.

### Comparison of cached descriptors

The cache of `FMU.model_description` is invalidated when the modification time or the size of `modelDescription.xml`
changes. On a file system with a coarse resolution (one second), an external rewrite of the same size within the same
second would go unnoticed. No code of the package writes this file by other means: only to be watched if that changes.
