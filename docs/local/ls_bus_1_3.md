# Plan: support of FMI-LS-BUS 1.3 (CAN, LIN, FlexRay, Ethernet)

**Created**: 3 November 2026 — **Status**: in progress — **Branch**: `ls-bus-1.3`, from `feature/ssp` (`1c130ad`) —
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
| G12 | The documentation says that a Bus Simulation is required, although `test_ls_bus_nodes_only` exists | `docs/user-guide/fmucontainer/ls-bus.md` | Read |

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
6. Existing CAN assemblies keep working. The accepted changes are the new checks, the mandatory path of nested
   terminals (D5), and the output of `datalog2pcap` (D7).

---

## 3. Decisions

Taken on 3 November 2026:

- **D1 — Clocks**: all the time-based clocks are scheduled (`constant`, `fixed`, `tunable`, `changing`, `countdown`), and
  the shift is read. FMI 3.0 has no `calculated` variability, contrary to the first version of this plan.
- **D2 — `BusNotifications`**: the value is propagated to the parameter of the node when it is known at build time
  (`constant` variable or start value of the bus). A warning is issued when it is known at runtime only.
- **D3 — MIME**: a different bus type is an error that stops the build. A different version of the same bus type is
  a warning.
- **D4 — Scope**: this branch also includes the multi-bus `datalog2pcap`, the LS-BUS checks and the multi-bus test FMUs.
- **D5 — Addressing of nested terminals**: the full path is mandatory, with a dot as separator: `Seg1.P1`. A bare name
  never designates a nested terminal, even when it is unique. Top-level terminals keep their name. This breaks the
  assemblies that link a sub-terminal by its bare name, which needs a clear error message and a migration note.
- **D6 — Sub-terminal missing on one side**: it depends on the `matchingRule` of the terminal:
  - `bus`: ignored, like the members of this rule;
  - `plug` and `sequence`: error;
  - `org.fmi-ls-bus.transceiver`: `Configuration` may be missing, anything else is an error.
  - `none` (grouping terminals): error, so that a port of a group cannot stay unconnected without notice.
- **D7 — `datalog2pcap`**: pcapng with DLT 252 replaces the pcap output for all the buses, and `-can` is removed. Reading
  the captures requires the Wireshark plugin of LS-BUS, including for CAN.
- **D10 — Type of bus in `datalog2pcap`**: the operation codes do not tell it (`0x10` exists on the four buses) and the CSV
  does not change: `datalog2pcap datalog.csv -fmu container.fmu` reads it from the MIME types of the container.
- **D8 — Test FMUs for LIN and Ethernet**: they are contributed to `modelica/fmi-ls-bus-examples`, and only their binaries
  are copied to `tests/data`.
- **D9 — Container boundary, out of scope**: a container holds the whole network and exposes no clock. Using a container
  as a Network FMU connected to an outer bus is not part of this plan, and the user documentation states this limit.

---

## 4. Design

### 4.1 Terminals (`terminals.py`)

- `_parse_source` looks for the `Terminals` element by name instead of reading the first child (G6).
- `Terminals` keeps a tree. Lookup follows D5: top-level name or full path (G7). A bare name matching a nested terminal
  gives an error that suggests its full path.
- `Terminal.connect` adds the links of the sub-terminals to the links of the rule, whatever the rule (G4). It handles
  a missing sub-terminal according to D6 (G5). The rule `none` is a valid rule with no direct link (G7).
- A transceiver terminal without its four members gives a clear error instead of a `KeyError`.
- The name, kind and members of a terminal stay available to the consumers listed in section 1.
- Iterating over `Terminals` gives the connectable terminals with their full path. `Configuration` terminals are handled
  with their Bus Terminal (section 4.2), so the GUI does not offer them.
- `split.py` generates full paths, so that the round trip still rebuilds the same container.

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
| `constant`, `fixed` | Once, in Initialization Mode, unless declared | Previous tick + interval; the first tick is at the shift |
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

- `datalog2pcap`: the bus type comes from the MIME type of the container (D10), and `PROTO_NAME` is one of `fmi_ls_bus_can`, `fmi_ls_bus_lin`, `fmi_ls_bus_eth`,
  `fmi_ls_bus_flexray`. The output is pcapng with DLT 252 and `-can` is removed (D7).
- `ls.py` reads `fmi-ls-version`.
- New check of LS-BUS in `checker.py`, active when the manifest exists:
  - manifest: location and content;
  - bus terminal: `terminalKind`, `matchingRule`, the four members with `variableKind="signal"`, no variable shared
    between two terminals;
  - `Tx_Data` and `Rx_Data`: binaries clocked by the right clock, with the known MIME type;
  - `Rx_Clock`: `triggered` or periodic, and `input`;
  - time-based `Tx_Clock`: warning without `canHandleVariableCommunicationStepSize`;
  - `Configuration` terminal: name, kind and rule.

---

## 5. Steps

Each step ends with the tests of the project passing (`pytest`) and a prepared commit message. Steps 1 to 5 are
independent of the runtime, and could be delivered first.

### Step 1 — Terminals: parsing

- Find `Terminals` by name (G6), with a test using `GraphicalRepresentation`.

Commit message: `Terminals: find the Terminals element by name, whatever precedes it`

### Step 2 — Terminals: tree and sub-terminals

- Keep the links of sub-terminals, handle a missing sub-terminal, accept the rule `none`, address nested terminals
  (G4, G5, G7).
- Tests: the three XML examples of the RC, added to `tests/data`, Ethernet segments using the same port name, a bare name
  of a nested terminal refused, and each rule of D6 with a missing sub-terminal in both directions of connection.
- Check the consumers of section 1, and the round trip with `fmusplit` on nested terminals.

Commit message: `Terminals: keep the links of nested terminals, and address them by their full path`

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

- Implement section 4.5 (G9, D7).
- `test_datalog.py`: replace `-can` and the MD5 of `REF-nodes-only-datalog.pcap` with a new reference.
- Tests: one reference capture per bus type, and one manual check with the Wireshark plugin.

Commit message: `datalog2pcap: write pcapng for CAN, LIN, FlexRay and Ethernet`

### Step 9 — Test FMUs for each bus

- Contribute the LIN and Ethernet FMUs to `modelica/fmi-ls-bus-examples` (D8): an external review, which can delay this
  step. A pull request to that repository is outward-facing, so it needs the agreement of the user when it is opened.
- FlexRay, LIN and Ethernet binaries from `fmi-ls-bus-examples`, for the platforms of the CI; CAN rebuilt with the final MIME version, while
  keeping one `1.0.0-beta.1` FMU for the warning of D3.
- Integration tests per bus: bus and nodes, simulation log and datalog against references (G11). This is the first
  run of LIN, FlexRay and Ethernet through a container: **any failure found here goes back to the step concerned**.

Commit message: `Tests: run LIN, FlexRay and Ethernet networks through a container`

### Step 10 — Follow the final 1.3.0

- Compare the final release with `v1.3.0-rc.1`: MIME versions, headers, operations of `datalog2pcap`, Wireshark plugin.
- Do not merge into a release while the supported version is only an RC, or say so in the documentation.

Commit message: `LS-BUS: align with FMI-LS-BUS 1.3.0`

### Step 11 — User documentation

- `docs/user-guide/fmucontainer/ls-bus.md`: the four buses, the topologies including `nodes-only` (G12), the clock
  types, the MIME rules, `Configuration` terminals, the full path of nested terminals with a migration note (D5), and the limit
  of D9: a container holds the whole network.
- `docs/user-guide/fmutool/cli-usage.md`: `datalog2pcap` (pcapng, removal of `-can`, installation of the Wireshark plugin)
  and the LS-BUS checks.
- `CHANGELOG.md`, and the knowledge of the assistant if it describes LS-BUS.
- `docs/local/ROADMAP.md`, then move this plan to `docs/local/done`.

Commit message: `Document the support of FMI-LS-BUS 1.3`
