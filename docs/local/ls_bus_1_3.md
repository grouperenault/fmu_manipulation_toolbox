# Plan: support of FMI-LS-BUS 1.3 (CAN, LIN, FlexRay, Ethernet)

**Created**: 3 November 2026 — **Status**: planned — **Branch**: `ls-bus-1.3`, from `feature/ssp` (`1c130ad`) —
**Reference**: [FMI-LS-BUS `v1.3.0-rc.1`](https://github.com/modelica/fmi-ls-bus/releases/tag/v1.3.0-rc.1)

FMI-LS-BUS 1.3 adds LIN, FlexRay and Ethernet to CAN. The container already transports the bus operations: `Tx_Data`
and `Rx_Data` are opaque binaries of dynamic size. What is missing is the scheduling of the clocks, the handling of
nested terminals, and the checks. Most of these gaps predate 1.3. In `v1.3.0-rc.1` itself, the only change that
directly concerns an importer is the periodic `Rx_Clock` (#392).

---

## 1. Current state

"Observed" means reproduced on `1c130ad` with the XML examples of the RC or with FMUs of `tests/data/ls-bus` whose
`modelDescription.xml` was patched. It was checked in the generated `container.txt`: **nothing was simulated**. "Read"
means found by reading the code only.

| # | Gap | Where | Evidence |
|---|---|---|---|
| G1 | Only `countdown` clocks are scheduled. `constant` builds without any warning, and the clock is missing from `importer CLOCKS`. The same condition excludes `changing`, used by the `lowCut` example of the specification | `container/builder.py:1059` | Observed (`constant`), read (others) |
| G2 | The runtime reads `fmi3IntervalUnchanged` as a remaining time, and never reads the shift | `container/container.c:101` | Read |
| G3 | Node `Tx_Clock` `countdown` linked to a bus `Rx_Clock` `triggered`: the bus never receives its clock (0 clock input instead of 1) | `container/builder.py:1072` | Observed |
| G4 | `Terminal.connect` computes the links of the sub-terminals, then returns without them. `Powertrain` of the high-cut example, connected to itself: 0 link for 12 variables, without any message | `terminals.py:40-46` | Observed |
| G5 | `KeyError` when `Configuration` exists on one side only, which the specification allows when it is empty | `terminals.py:34` | Observed |
| G6 | No terminal is found when `GraphicalRepresentation` precedes `Terminals` (valid against the XSD), without any message | `terminals.py:117` | Observed |
| G7 | Nested terminals are flattened by name: a port name used in two Ethernet segments resolves to the last one. The rule `none` of grouping terminals logs an error | `terminals.py:146` | Observed |
| G8 | No check of the MIME type: a LIN node connects to a CAN bus | `container/` | Observed |
| G9 | `datalog2pcap` handles CAN only and writes pcap with linktype 227. The Wireshark plugin of the RC reads pcapng with DLT 252 | `cli/datalog2pcap.py` | Read |
| G10 | No LS-BUS check: `fmi-ls-version` is not read, and neither the manifest nor the terminals are checked | `ls.py`, `checker.py` | Read |
| G11 | The tests of LS-BUS cover CAN only, with FMUs in `1.0.0-beta.1` | `tests/data/ls-bus` | Read |
| G12 | A container has no LS-BUS manifest and no terminal at its root, and `eventHandlingNeeded` is always `false` | `container/fmi3.c`, `container/builder.py` | Observed, read |
| G13 | The documentation says that a Bus Simulation is required, although `test_ls_bus_nodes_only` exists | `docs/user-guide/fmucontainer/ls-bus.md` | Read |

Consumers of `Terminals`, to be kept working by any change of the terminal model: `container/embedded.py`,
`container/builder.py`, `split.py`, `operations.py`, `gui/fmucontainer/graph/node.py`, `assistant/fmutools.py`,
`assistant/headless.py`.

---

## 2. Goals

1. A network of CAN, LIN, FlexRay or Ethernet FMUs works in a container, whatever the clock types allowed by LS-BUS.
2. Every connection of terminals produces all its links, or fails with a clear message: no silent loss.
3. Incompatible buses are refused at build time.
4. FMUs are checked against the rules of LS-BUS.
5. The datalog of any bus type can be opened with the Wireshark plugin of LS-BUS.
6. A container can be used as a Network FMU, connected to a bus outside of it.
7. Nothing changes for the existing CAN assemblies, apart from the new checks.

---

## 3. Decisions

Taken on 3 November 2026:

- **D1 — Clocks**: all the time-based clocks are scheduled (`constant`, `fixed`, `calculated`, `tunable`, `changing`,
  `countdown`), and the shift is read.
- **D2 — `BusNotifications`**: the value is propagated to the parameter of the node when it is known at build time
  (`constant` variable or start value of the bus). A warning is issued when it is known at runtime only.
- **D3 — MIME**: a different bus type is an error that stops the build. A different version of the same bus type is
  a warning.
- **D4 — Scope**: this branch also includes the multi-bus `datalog2pcap`, the LS-BUS checks, the multi-bus test FMUs,
  and the container as a Network FMU.

### Open decisions

To be confirmed by the user before the step concerned starts:

- **O1 (step 2) — Addressing of nested terminals**. Proposal: a path, `Segment1.Port1`. A bare name stays accepted
  when it is unique, and an ambiguous one is an error.
- **O2 (step 2) — Sub-terminal missing on one side**. Proposal: an optional `Configuration` is skipped with a debug
  message; any other missing sub-terminal is an error.
- **O3 (step 8) — `datalog2pcap`**. Proposal: pcapng DLT 252 replaces the pcap output. Alternative: keep the pcap
  output for CAN, as Wireshark decodes it natively.
- **O4 (step 9) — Test FMUs for LIN and Ethernet**. No example exists in `fmi-ls-bus-examples`. Should they be written
  by adapting the FlexRay examples, and where should their sources live?
- **O5 (step 10) — Network FMU**: see section 4.6.

---

## 4. Design

### 4.1 Terminals (`terminals.py`)

- `_parse_source` looks for the `Terminals` element by name instead of reading the first child (G6).
- `Terminals` keeps a tree. Lookup follows O1 (G7).
- `Terminal.connect` adds the links of the sub-terminals to the links of the rule, whatever the rule (G4). It handles
  a missing sub-terminal according to O2 (G5). The rule `none` is a valid rule with no direct link (G7).
- A transceiver terminal without its four members gives a clear error instead of a `KeyError`.
- The name, kind and members of a terminal stay available to the consumers listed in section 1.

### 4.2 Configuration terminals (`container/builder.py`)

`container/rules.py` refuses a target that is not an input, so a regular link cannot carry `BusNotifications`. The
members of a `Configuration` terminal are therefore not returned as links but as **parameter bindings**:

- bus value known at build time: it becomes the start value of the parameter of the node, unless the user set one;
- bus value known at runtime only: warning, the default of the node (`false`) stays;
- node without the parameter: nothing to do, as it is optional.

The same mechanism applies to `DeliveryOnBoundary` (FlexRay).

### 4.3 Clock scheduling (`container/builder.py`, `container/txt.py`, `container/container.c`)

Builder:

- All the time-based clocks of a link are scheduled, not only the first `countdown` (`break` at `builder.py:1059`).
- Every target of a link is fed, except the clock already activated by the schedule. This replaces the test on
  `ls.is_bus` (G3), so it must keep the behaviour of the baseline: the `Tx_Clock` of a Bus Simulation is not set twice.
- Several time-based clocks on one link, or a periodic `Rx_Clock` fed by a Tx clock, must match (#392). A build-time
  warning is issued when the known intervals or shifts differ.

Runtime:

| `intervalVariability` | Interval read | Next tick |
|---|---|---|
| `constant`, `fixed`, `calculated` | Once, after initialization | Previous tick + interval; the first tick is at the shift |
| `tunable` | Once, and again on `fmi3IntervalChanged` | Previous tick + current interval |
| `changing` | After each tick | Previous tick + current interval, if known |
| `countdown` | After each tick | Unchanged behaviour |

- The schedule stores the **next tick time** of each clock, instead of a remaining interval that `Unchanged` would
  make wrong (G2).
- `fmi3IntervalNotYetKnown` and `fmi3IntervalUnchanged` follow FMI 3.0, section 2.2.8, to be re-read at implementation
  time, in particular for the clocks using fractions (`fmi3GetIntervalFraction`, `fmi3GetShiftFraction`).
- `container.txt` gains the `intervalVariability` of each scheduled clock: version 8. `split.py` and
  `docs/developer/container-txt-format.md` follow, and `CONTAINER_TXT_VERSION` changes in `types.py` and
  `container.h`.
- `container_fmu_has_scheduled_clocks()` still refuses to reset an FMU with scheduled clocks: more FMUs may be refused.

### 4.4 MIME checks (`container/embedded.py`, `container/rules.py`)

`EmbeddedFMUPort` reads `mimeType`. A link between two binaries compares the media type of LS-BUS variables (D3). The
comparison only applies to `application/org.fmi-standard.fmi-ls-bus.*`, so that other binaries are not affected.

### 4.5 Datalog and checks

- `datalog2pcap`: the bus type comes from the MIME type or from the terminal, the operation names come from the
  headers of the RC, and `PROTO_NAME` is one of `fmi_ls_bus_can`, `fmi_ls_bus_lin`, `fmi_ls_bus_eth`,
  `fmi_ls_bus_flexray`. The `-can` argument follows O3.
- `ls.py` reads `fmi-ls-version`.
- New check of LS-BUS in `checker.py`, active when the manifest exists:
  - manifest: location and content;
  - bus terminal: `terminalKind`, `matchingRule`, the four members with `variableKind="signal"`, no variable shared
    between two terminals;
  - `Tx_Data` and `Rx_Data`: binaries clocked by the right clock, with the known MIME type;
  - `Rx_Clock`: `triggered` or periodic, and `input`;
  - time-based `Tx_Clock`: warning without `canHandleVariableCommunicationStepSize`;
  - `Configuration` terminal: name, kind and rule.

### 4.6 Container as a Network FMU

To be designed in detail with the user before step 10 (O5). Known questions:

- `fmi3DoStep` sets `eventHandlingNeeded` to `false`: an inner event must reach the outer importer.
- `txt.py` refuses to expose a clocked variable whose clock has no local variable.
- Which clocks does the container declare at its boundary? A `triggered` output, or a time-based input whose interval
  comes from the inner FMU (`fmi3.c:707` already forwards `fmuGetIntervalDecimal`)?
- Generation of `extra/org.fmi-standard.fmi-ls-bus/fmi-ls-manifest.xml` and of the terminals at the root, and of
  `isBusSimulationFMU` when the container holds a Bus Simulation.
- `fmucontainer` assemblies and the GUI: how to expose a terminal. `split.py`: how to read it back.

---

## 5. Steps

Each step ends with the tests of the project passing (`pytest`) and a prepared commit message. Steps 1 to 5 are
independent of the runtime, and could be delivered first.

### Step 1 — Terminals: parsing

- Find `Terminals` by name (G6), with a test using `GraphicalRepresentation`.

Commit message: `Terminals: find the Terminals element by name, whatever precedes it`

### Step 2 — Terminals: tree and sub-terminals

- Requires O1 and O2.
- Keep the links of sub-terminals, handle a missing sub-terminal, accept the rule `none`, address nested terminals
  (G4, G5, G7).
- Tests: the three XML examples of the RC, added to `tests/data`, and Ethernet segments using the same port name.
- Check the consumers of section 1, and the round trip with `fmusplit` on nested terminals.

Commit message: `Terminals: keep the links of nested terminals, and address them without ambiguity`

### Step 3 — Parameter bindings of Configuration terminals

- Implement section 4.2 (D2), for `BusNotifications` and `DeliveryOnBoundary`.
- Tests: value known at build time, value known at runtime, a value set by the user, node without the parameter.

Commit message: `Container builder: propagate the parameters of LS-BUS Configuration terminals`

### Step 4 — Clock of a Bus Simulation fed by a node

- Replace the test on `ls.is_bus` (G3).
- Tests on `container.txt`, and `test_lsbus.py` with its reference logs unchanged.

Commit message: `Container builder: feed the Rx_Clock of a Bus Simulation from a time-based Tx_Clock`

### Step 5 — MIME checks

- Implement section 4.4 (D3). Tests: CAN to LIN refused, `1.0.0-beta.1` to `1.0.0` warned, plain binaries unaffected.

Commit message: `Container builder: refuse links between different LS-BUS types, warn about different versions`

### Step 6 — Runtime: scheduling of the time-based clocks

- Implement section 4.3 (D1): builder, `container.txt` version 8, runtime, `split.py`, developer documentation.
- A test FMU with `constant`, `fixed`, `tunable`, `changing` and shifted clocks, to be simulated: these are the first
  tests of G1 and G2 that observe a behaviour. Check the tick times.
- Run the native tests of `container/tests` and all the integration tests on the three platforms of the CI.

Commit message: `Container runtime: schedule all the time-based clocks of FMI 3.0, shift included`

### Step 7 — LS-BUS checks

- Implement the checks of section 4.5 and `fmi-ls-version` (G10). Tests: valid FMUs and one defect per rule.

Commit message: `Checker: add the rules of FMI-LS-BUS`

### Step 8 — `datalog2pcap` for all the buses

- Requires O3. Implement section 4.5 (G9).
- Tests: one reference capture per bus type, and one manual check with the Wireshark plugin.

Commit message: `datalog2pcap: write pcapng for CAN, LIN, FlexRay and Ethernet`

### Step 9 — Test FMUs for each bus

- Requires O4.
- FlexRay from `fmi-ls-bus-examples`; LIN and Ethernet according to O4; CAN rebuilt with the final MIME version, while
  keeping one `1.0.0-beta.1` FMU for the warning of D3.
- Integration tests per bus: bus and nodes, simulation log and datalog against references (G11). This is the first
  run of LIN, FlexRay and Ethernet through a container: **any failure found here goes back to the step concerned**.

Commit message: `Tests: run LIN, FlexRay and Ethernet networks through a container`

### Step 10 — Container as a Network FMU

- Requires O5: section 4.6 must first be turned into a detailed design and approved, possibly as a plan of its own.
- Test: a container of nodes, connected to a Bus Simulation by an outer container and by another importer.

Commit message: `Container: expose LS-BUS terminals, so that a container can be a Network FMU`

### Step 11 — Follow the final 1.3.0

- Compare the final release with `v1.3.0-rc.1`: MIME versions, headers, operations of `datalog2pcap`, Wireshark plugin.
- Do not merge into a release while the supported version is only an RC, or say so in the documentation.

Commit message: `LS-BUS: align with FMI-LS-BUS 1.3.0`

### Step 12 — User documentation

- `docs/user-guide/fmucontainer/ls-bus.md`: the four buses, the topologies including `nodes-only` (G13), the clock
  types, the MIME rules, `Configuration` terminals, the container as a Network FMU.
- `docs/user-guide/fmutool/cli-usage.md`: `datalog2pcap` and the LS-BUS checks.
- `CHANGELOG.md`, and the knowledge of the assistant if it describes LS-BUS.
- `docs/local/ROADMAP.md`, then move this plan to `docs/local/done`.

Commit message: `Document the support of FMI-LS-BUS 1.3`
