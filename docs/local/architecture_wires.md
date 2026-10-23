# Plan: architecture wires in SSP files

**Created**: 23 October 2026 — **Status**: in progress, step 1 done — **Roadmap**: not listed —
**Origin**: SSP files produced at the architecture stage, before the exchanged variables are known

An SSP file can describe a system at the architecture stage: components (FMUs, or SSP 2.0 components without
`source`) and the dependencies between them, before the exchanged variables are defined. Such a dependency is not
a variable link: it only says that component A feeds component B (or both ways, or without direction), with a free
text comment. Today `SSDParser` turns every `ssd:Connection` into a variable link, so such a file either fails to
build or produces wrong links.

The goal is a documented, tool-neutral convention for these "architecture wires", read by fmutool: the SSP reader
does not turn them into variable links, and the container builder shows them as hints while the user defines the
real links.

---

## 1. Convention

An architecture wire between components `A` and `B` is written as:

- one synthetic `ssd:Connector` on each component. Its name is free; the recommended form is
  `aw.<peer component name>`;
- connector `kind`: `output` on the start side and `input` on the end side for a directed wire, `unspecified`
  on both sides otherwise;
- one `ssd:Connection` between these connectors, carrying:
  - an annotation of type `fmu_manipulation_toolbox.architecture-wire`, whose content is
    `<aw:Wire formatVersion="1" orientation="directed|bidirectional|undirected"/>`, namespace
    `urn:fmu_manipulation_toolbox:architecture-wire:1`. `directed` means start -> end;
  - optionally the standard `description` attribute: the comment of the wire (Markdown, new lines as `&#10;`);
  - optionally `ssd:ConnectionGeometry` (waypoints).

The annotation type does not use the reverse domain name notation: SSP 2.0 only recommends it (SHOULD); the
package name is unique enough and the reserved prefixes (`org.modelica`, `org.ssp-standard`) are not used.

Example:

```xml
<ssd:Connection startElement="Engine" startConnector="aw.Gearbox"
                endElement="Gearbox" endConnector="aw.Engine"
                description="Torque and speed sent to the gearbox.">
  <ssd:Annotations>
    <ssc:Annotation type="fmu_manipulation_toolbox.architecture-wire">
      <aw:Wire xmlns:aw="urn:fmu_manipulation_toolbox:architecture-wire:1"
               formatVersion="1" orientation="directed"/>
    </ssc:Annotation>
  </ssd:Annotations>
</ssd:Connection>
```

---

## 2. Current state

- `assembly.py`, `SSDParser.start_element`: every `Connection` start tag calls `add_link` / `add_input` /
  `add_output` immediately. Child elements (annotations) are not seen at that time.
- `assembly.py`, `Assembly.read_ssp`: FMUs are extracted **flattened** (`file.filename = Path(file.filename).name`)
  and `SSDParser` keeps only the base name of `Component/@source`. Two FMUs with the same base name in different
  directories of `resources/` overwrite each other.
- `SSDParser` names the embedded FMUs after their file (`instance_name`), not after `Component/@name`.
- `gui/fmucontainer/__main__.py`, `main()`: `sys.argv` is not used; a file can only be opened from the GUI.
- `gui/fmucontainer/graph/wire.py`, `WireItem`: a wire already joins two nodes and groups the variable links between
  them.

---

## 3. Decisions

| # | Question | Decision |
|---|---|---|
| D1 | How does the container builder show an architecture wire? | As a `WireItem` between the two nodes. While the wire has no variable link it is drawn dashed, with the arrowheads of its orientation; its description is shown in the wire details panel. The user adds links with the existing link assistant; once the wire has links, it is drawn as a regular wire (arrowheads derived from the links). If the SSP also contains variable links between the same two components, they share the same `WireItem`. |
| D2 | What happens to architecture wires on *Export as JSON* / *Save as FMU Container*? | Dropped: they are wiring hints, like the layout and the waypoints that the JSON description does not keep either. |
| D3 | FMU resources with the same base name in different `resources/` sub-directories | FMUs are extracted keeping their path relative to the archive root; `Component/@source` is resolved as is. |
| D4 | Name of the FMU nodes read from an SSP | `<Component/@name>.fmu` (e.g. `Engine-1.fmu`), the file path being kept apart (`AssemblyNode.add_fmu(fmu_name, fmu_path)`). |
| D5 | Components without `source` (SSP 2.0) | Skipped with a warning naming the component; the connections attached to them are skipped too; the rest of the file is loaded. |
| D6 | File types accepted on the `fmucontainer-gui` command line | Every type the GUI can open (`.ssp`, `.json`, `.csv`, container `.fmu`), through the same code path as the *Load* / *Import* buttons. |

---

## 4. Changes

### 4.1 SSP reader (`assembly.py`)

- `Assembly.read_ssp`: extract the FMUs keeping their relative path (D3).
- `SSDParser`:
  - `Component`: FMU name `<name>.fmu`, FMU path = extracted `source` (D3, D4); without `source`, warning and
    component ignored (D5);
  - `Connection`: decision moved to the end tag. With the architecture wire annotation, the wire (start, end,
    orientation, description) is stored on the `AssemblyNode` instead of a link; connections touching an ignored
    component are skipped (D5). Waypoints are not kept: the container builder does not read the SSP geometry
    (nodes are placed automatically), so they would have no meaning there.
- `AssemblyNode`: new list of architecture wires, not used by the container build and not written by `write_json`
  (D2).

### 4.2 Container builder (`gui/fmucontainer/`)

- `__main__.py`, `main()`: optional file argument, opened like *Load* / *Import* according to its type (D6).
- `assembly_io.py`, `_import_data`: create or complete the `WireItem` of each architecture wire, with its
  orientation and description (D1).
- `graph/wire.py`, `WireItem`: architecture orientation and description; dashed pen and arrowheads from the
  orientation while `mappings` is empty (D1). Colors and pen styles go to `graph/constants.py`.
- `details/wire_detail.py`: show the description of the wire (D1).

### 4.3 Documentation

- `docs/user-guide/fmucontainer/container.md`, SSP section: the architecture wire convention, node naming (D4),
  components without `source` (D5).
- Command line argument of `fmucontainer-gui` (D6).
- CHANGELOG.

---

## 5. Steps

1. **SSP reader**: architecture wires recognized and kept apart from variable links; D3, D4, D5 applied. Unit tests
   with SSP files mixing variable links and architecture wires, FMUs with the same base name in different
   directories, and a component without `source`.
   Commit message: `Recognize architecture wires in SSP files`
2. **Command line argument** of `fmucontainer-gui` (D6). GUI test (pytest-qt).
   Commit message: `Open a description file given to fmucontainer-gui`
3. **Display of architecture wires** in the container builder (D1, D2). GUI tests.
   Commit message: `Show architecture wires as hints in the container builder`
4. **User documentation** and CHANGELOG.
   Commit message: `Document architecture wires in SSP files`
