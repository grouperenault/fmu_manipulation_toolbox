# Plan: reset of an embedded FMU driven from inside the container (`container.<fmu>.reset`)

**Created**: 16 October 2026 — **Status**: reviewed (16 October 2026), not started — **Roadmap**: not listed

An FMU of a container must be able to request the reset (`fmi2Reset` / `fmi3Reset`) of another FMU of the same
container, while the simulation runs. The configuration follows the `ts_multiplier` approach: a container option
creates one reserved boolean input per embedded FMU, `container.<fmu>.reset`, wired from any FMU (GUI:
`configuration` node) or exposed to the importer.

---

## 1. Current state

| Topic | Where | Notes |
|---|---|---|
| Reset of an embedded FMU | `container/fmu.c`: `fmuReset()` | Exists (FMI 2 and 3), never called |
| Reset of the container itself | `container/fmi2.c`: `fmi2Reset()`, `container/fmi3.c`: `fmi3Reset()` | `__NOT_IMPLEMENTED__`: a sub-container cannot be reset |
| Initialization | `container/container.c`: `container_setup_experiment()`, `container_enter_initialization_mode()`, `container_exit_initialization_mode()`, `container_set_start_values()` | Loops over all the FMUs; no per-FMU entry point |
| Start time | `container/fmu.c`: `fmuSetupExperiment()`, `fmuEnterInitializationMode()` | Always `container->start_time` |
| Importer setters | `container/fmi2.c`, `container/fmi3.c`: `FMI_SETTER` | Values of ports linked to an FMU are forwarded directly, never stored |
| ME solver | `container/solver.c`: `solver_leave_event_mode()` | Reads `x` and `z_prev` of **all** the ME FMUs; no per-FMU refresh |
| Reserved variables | `container/layout.py`: `ContainerLayout.allocate()` (`time`, `ts_multiplier`, `solver`, profiling) | `container.ts_multiplier` is exposed by `make_fmu_xml()` |
| Naming of reserved ports | `container/builder.py`: `add_implicit_rule()` (`container.<id>.<port>` for profiling) | |
| GUI | `gui/fmucontainer/graph/node.py`: `ConfigurationNode` (`ts_multiplier_ports`), `gui/fmucontainer/assembly_io.py` (import/export of `container.ts_multiplier` links), `details/container_detail.py`, `details/wire_detail.py` | |
| Assembly / CLI / assistant | `assembly.py` (`ts_multiplier`), `cli/fmucontainer.py` (`-vr`), `assistant/models.py`, `assistant/headless.py`, `assistant/analysis.py` | |
| Split | `split.py` | Reads `container.txt` back |
| `container.txt` format | `docs/developer/container-txt-format.md` | Version 6 |

---

## 2. Goals

1. With the container option `reset_ports`, each embedded FMU gets a reserved input `container.<fmu>.reset`.
2. This input can be fed by a link from any embedded FMU, or exposed as a container input (importer, parent
   container).
3. When it is `true`, the container resets the FMU and initializes it again at the current time, then the
   simulation goes on.
4. A container (sub-container) supports `fmi2Reset` / `fmi3Reset`.
5. Nothing changes when `reset_ports` is not set.

---

## 3. Decisions

Taken on 16 October 2026:

- **D1 — Configuration**: same approach as `ts_multiplier`: a container option and a reserved port, wired from the
  GUI `configuration` node.
- **D2 — Option**: `reset_ports` (JSON key, Python parameter, GUI checkbox). CLI flag: `-reset-ports`.
- **D3 — Ports**: when `reset_ports` is set, one reserved input per embedded FMU (CS and ME, sub-containers
  included), named `container.<fmu>.reset` (`<fmu>`: the FMU id, as for `container.<fmu>.rt_ratio`). Type
  `fmi2Boolean` (`boolean`) in an FMI-2 container, `fmi3Boolean` (`boolean1`) in an FMI-3 container.
- **D4 — Exposure**: the port follows the rules of the inputs of the embedded FMUs:
  - wired by a link: it is a local variable of the container (like every link);
  - not wired: exposed as a container input when `auto_input` is checked (or by an explicit `INPUT` rule);
  - neither wired nor exposed: **warning** at build time (not the error of an unconnected input); the FMU is never
    reset.
- **D5 — Trigger**: a `true` value seen at a synchronization point triggers the reset; the container then writes
  `false` into the input. A source that keeps `true` resets the target **at each step**: the source must emit a
  pulse.
- **D6 — Restart time**: the current time of the container (`fmi2SetupExperiment` / `fmi3EnterInitializationMode`).
- **D7 — Scope**: Co-Simulation and Model-Exchange FMUs.
- **D8 — Failure**: if `fmiXReset` (or the initialization sequence) fails, the container returns an error; no
  fallback to a new instantiation.
- **D9 — Timing**: same rule in every mode (sequential, parallel, multi-threaded): the trigger is read at the
  start of each internal step, in the main thread, and the reset is applied before that step. A trigger set by an
  FMU at step n acts before step n+1.
- **D10 — Cache**: the container stores every value set by the importer on a port forwarded to an embedded FMU
  (parameters and inputs) and sets it again during the re-initialization.
- **D11 — Sub-containers**: `fmi2Reset` / `fmi3Reset` of the container are implemented (section 4.5).
- **D12 — GUI**: the `configuration` node shows one port `<fmu_without_.fmu>.reset` per FMU of each container
  with `reset_ports` checked; inactive ports and red wires behave as for `ts_multiplier`.
- **D13 — Datalog** (16 October 2026): the marker of a reset in the datalog is the variable
  `container.<fmu>.reset` itself (link local variable or exposed input, both already logged). When at least one
  trigger is `true` at the start of an internal step, the container writes one datalog row **before** applying the
  resets, at the current time, so that the `true` value is visible even when it was set by the importer (otherwise
  the trigger is cleared before the first row). Two rows at the same time, as for the event iterations. The CSV
  file goes on during a reset of an embedded FMU.
- **D14 — Datalog after a reset of the container** (16 October 2026): after `fmi2Reset` / `fmi3Reset` of the
  container (section 4.5), the datalog goes on in the same CSV file, appended.
- **D15 — Reset ports of a sub-container** (16 October 2026): in the parent, `auto_input` exposes the
  `container.<x>.reset` inputs of a sub-container under the same name (`_auto_name`), or prefixed by the
  sub-container id when the name is already used.
- **D16 — Self-reset** (16 October 2026): an FMU wired to its own `container.<fmu>.reset` is allowed, with no
  special case.

Taken during the implementation (16 October 2026):

- **D17 — Step 1, ME solver**: `solver_leave_event_mode_fmu(solver, fmu_idx)` does the whole exit of the Event Mode
  for one ME FMU (`EnterContinuousTimeMode`, states, event indicators); `solver_leave_event_mode()` loops over it.
- **D18 — Step 2, cache**: clocks are never cached (a tick is an event, not a value); one slot per container port
  forwarded to an FMU, in a per-type buffer allocated when `container.txt` is read; tested at once through the
  debug log of the container (`[DEBUG] Cache ...`).
- **D19 — Step 3, FMI version**: `container_new()` receives the FMI version of the API that instantiates the
  container; `container.txt` only carries `<LOCAL_OFFSET>`.
- **D20 — Step 3, coupling**: the builder writes version 7 from step 3 on, with `-1` triggers (the runtime embedded
  in a container always reads the format of its builder); `split.py` skips the trigger until step 6; the REF
  `container.txt` files and `docs/developer/container-txt-format.md` are updated at step 3. Step 3 is validated by
  the non-regression tests: the functional tests of the reset come with step 5.
- **D21 — Step 3, clocks**: the reset of an FMU with clocks scheduled by the container (`clocks_list`) is not
  supported: the runtime returns an error. FMUs with clocked inputs only (LS-BUS) are supported.
- **D22 — Step 4, container reset**: the local variables go back to their values after the instantiation (0,
  `false`, empty strings and binaries, `ts_multiplier` = 1, solver = 0), the importer cache is emptied;
  `solver_configure()` frees its buffers before allocating them again (it runs at each `ExitInitializationMode`).
  Tested with fmpy (low level, `fmpy.simulation.instantiate_fmu`) on a container of `VanDerPol.fmu`.
- **D23 — Step 5, clearing of the trigger** (replaces the clearing of D5): the trigger stays `true` during the step
  where it resets the FMU (an input of another FMU fed by the same link receives `true`), and goes back to `false`
  at the end of the `doStep()`, whoever set it (importer or embedded FMU). Consequence: an FMU that keeps its output
  `true` resets the target every other step.
- **D24 — Step 5, fan-out**: one link or one container input may drive the reset ports of several FMUs; the
  runtime reads all the triggers before the first reset. One container input may also feed regular inputs.
- **D25 — Step 5, validation**: only the start values are refused on `container.reset`; no check of the mixing of
  reset ports and regular inputs, no build warning for the FMUs with scheduled clocks, no exclusion from
  `auto_link`.
- **D26 — Step 5, builder**: `FMUContainer(..., reset_ports=True)` adds the virtual port when the FMU is loaded
  (`get_fmu`); an exposed reset input gets a slot of local storage without value reference, allocated after
  every other variable (`ContainerLayout.reset_inputs`); `add_input` with an empty name and `auto_input` name it
  `container.<id>.reset`.
- **D27 — Step 6, fmusplit**: an exposed trigger comes back as an `input` rule, a trigger fed by a link as a `link`
  rule (to `container.reset`); `reset_ports` is restored only when at least one trigger is wired: without any,
  nothing in `container.txt` tells the option (documented limitation, no effect on the simulation).
- **D28 — Step 6, assistant**: `reset_ports` is a container option (`set_container_options`); the replay of the
  lint creates its `FMUContainer` with the option of the container, so that a link to `container.reset` is not
  reported as invalid. The SSP import does not set it (as `ts_multiplier`).

---

## 4. Design

### 4.1 Python model (`container/`)

- `FMUContainer(..., reset_ports=False)`: the option must be known **before** the rules (links, `auto_input`),
  because it adds ports to the embedded FMUs. `Assembly` passes it when it creates the `FMUContainer`.
- `EmbeddedFMU`: when the container has `reset_ports`, a virtual port `container.reset` is added to `ports`:
  causality `input`, type `boolean` / `boolean1` (FMI version of the **container**), flag `is_reset = True`, no
  value reference of the FMU. Links with conversion (e.g. an FMI-3 `boolean1` output to an FMI-2 container) use the
  existing conversion tables.
- Links: `add_link(A, "out", B, "container.reset")` is a regular link. `ContainerLayout.allocate()` is unchanged
  for the links.
- Exposure: `add_implicit_rule()` exposes an unruled reset port as `container.<id>.reset` (special case next to
  profiling, D3). An exposed reset input is stored locally: `ContainerLayout` allocates one local slot per exposed
  reset port, and its line in the container I/O table is `<VR> 1 1 -1 <LOCAL_OFFSET>` (as `ts_multiplier`).
- `sanity_check()`: warning for a reset port neither linked nor exposed (D4).
- `make_fmu_txt()`: a link to a reset port is **not** written as an input of the target FMU (no FMU value
  reference); instead, the target gets a reset trigger (section 4.2).
- `make_fmu_xml()`: the exposed reset inputs are declared `causality="input"`, `variability="discrete"`,
  `start="false"`.
- `Assembly` / JSON: key `reset_ports` on a container node; a link to `(<fmu>, "container.reset")` is a regular
  link, kept as is in JSON/CSV.

### 4.2 `container.txt` — version 7

New per-FMU sub-section, after the conversion table of each FMU:

```
# Reset trigger of <fmu_name>: <LOCAL_OFFSET>
<LOCAL_OFFSET>
```

`<LOCAL_OFFSET>`: offset in the local storage of `boolean` (FMI-2 container) or `boolean1` (FMI-3 container);
`-1` when the FMU has no trigger (option not set, or port neither linked nor exposed). The offset is the one of the
link local variable (or of its converted copy), or the one of the reserved slot of the exposed input.

`split.py` reads version 7 and rebuilds `reset_ports`, the links to `container.reset` and the exposed reset inputs.

### 4.3 C runtime: reset of one embedded FMU

New `container_reset_fmu(container, i)` (`container.c`), called by `container_do_step()` at the start of each
internal step, in the main thread, for each FMU whose trigger is `true`, in declaration order (D9). Before the
first reset of the step, `datalog_log()` writes one row (D13).

1. `fmuReset()`; error → the container returns an error (D8).
2. FMI 2: `fmuSetupExperiment()` with `startTime = container->time` (D6): `fmuSetupExperiment()` and
   `fmuEnterInitializationMode()` take the start time as a parameter instead of reading `container->start_time`.
3. Start values (early set) of this FMU only: `container_set_start_values()` is split into a per-FMU function.
4. Values cached from the importer (D10, section 4.4) for this FMU.
5. `fmuEnterInitializationMode()` (FMI 3: `startTime = container->time`), start values with `<RESET>` = 1,
   `fmu_set_inputs()` and `fmu_set_clocked_inputs()` (current values of the links).
6. `fmuExitInitializationMode()`.
7. Leave the event mode as at the initialization:
   - CS with event mode: event iteration for this FMU, then step mode;
   - ME: event iteration (`NewDiscreteStates`), `EnterContinuousTimeMode`, then new
     `solver_refresh_fmu(solver, fmu_idx)` that reads `x` and `z_prev` of this FMU only (as
     `solver_leave_event_mode()`).
8. `fmu_get_outputs()` and `fmu_get_clocked_outputs()`, so that the next step uses the outputs after the reset.
9. Write `false` into the trigger (D5).
10. If the FMU has clocks: compute the next event time again (`container_set_next_event_time()`).

### 4.4 C runtime: cache of the importer values (D10)

- `FMI_SETTER` (`fmi2.c`, `fmi3.c`): when a port is forwarded to an embedded FMU (`fmu_id >= 0`), the value is
  also stored in a per-FMU cache (value reference, type, value; arrays and strings included), last value wins.
- The cache is replayed at step 4 of section 4.3, for the target FMU only.
- The cache is cleared by `fmi2Reset` / `fmi3Reset` of the container (section 4.5).

### 4.5 C runtime: `fmi2Reset` / `fmi3Reset` of the container (D11)

- `container_reset()`: `fmuReset()` on every embedded FMU (error → error); state back to
  `CONTAINER_STATE_INSTANTIATED`; time, step counters, local variables (links, reserved slots: `ts_multiplier` = 1,
  solver = 0, reset triggers = `false`), clocks, profiling and the importer cache back to their values after
  instantiation; the ME solver is configured again at the next `ExitInitializationMode`.
- The importer then runs the usual sequence (`SetupExperiment` / `EnterInitializationMode` / ...).

### 4.6 GUI

- `container_detail.py`: checkbox `reset_ports`.
- `ConfigurationNode`: `reset_ports` (port name → active), next to `ts_multiplier_ports`; ports
  `<fmu_without_.fmu>.reset`, type Boolean; shown as soon as a container has `reset_ports` checked (D12). Same
  rules as `ts_multiplier`: inactive port and red wire when unchecked, cleanup of the node.
- `assembly_io.py`: export of a wire `configuration/<fmu>.reset` as a link to `(<fmu>, "container.reset")` in the
  container that owns `<fmu>`; reverse translation at import.
- `wire_detail.py`: inactive reset ports flagged as the inactive `ts_multiplier` ports.

---

## 5. Steps

Each step ends with the tests of the project passing (`pytest`), and a prepared commit message.

### Step 1 — Runtime: per-FMU initialization and start time

- `fmuSetupExperiment()` / `fmuEnterInitializationMode()` take the start time.
- Per-FMU split of `container_set_start_values()`; `solver_refresh_fmu()`.
- No change of behaviour.

Commit message: `Container runtime: per-FMU initialization helpers and explicit start time`

### Step 2 — Runtime: cache of the importer values

- Cache in the setters (section 4.4); C test in `container/test_fmi.c` if relevant.

Commit message: `Container runtime: cache the values set by the importer on embedded FMU ports`

### Step 3 — Runtime: `container.txt` version 7 and `container_reset_fmu()`

- Reading of the reset trigger section (version 7; versions ≤ 6 read without trigger).
- `container_reset_fmu()` (section 4.3), called at the start of each internal step in every mode.
- Datalog row written before the resets of a step (D13).

Commit message: `Container runtime: reset an embedded FMU on its container.<fmu>.reset trigger`

### Step 4 — Runtime: `fmi2Reset` / `fmi3Reset` of the container

- `container_reset()` (section 4.5).

Commit message: `Container runtime: implement fmi2Reset and fmi3Reset`

### Step 5 — Builder: `reset_ports`

- `FMUContainer(reset_ports=...)`, virtual port `container.reset`, `add_implicit_rule()`, `sanity_check()`,
  `ContainerLayout`, `make_fmu_xml()`, `make_fmu_txt()` (version 7).
- `docs/developer/container-txt-format.md`: version 7.
- Unit tests (`tests/unit/test_container_internals.py`): port creation, naming, exposure, warning, `container.txt`.

Commit message: `Container builder: add the reset_ports option and container.<fmu>.reset inputs`

### Step 6 — Assembly, CLI, assistant, split

- `assembly.py` (`reset_ports`, default and JSON key), `cli/fmucontainer.py` (`-reset-ports`),
  `assistant/models.py`, `assistant/headless.py`, `assistant/analysis.py`, `split.py` (version 7).
- Tests: JSON round trip, split of a version 7 container.

Commit message: `Add reset_ports to the assembly, the CLI, the assistant and fmusplit`

### Step 7 — Integration tests

- Container where an output of one FMU resets another FMU (CS FMI 2, CS FMI 3, ME), sequential and multi-threaded
  modes; exposed reset input driven by the importer; reset of a sub-container (`fmi2Reset` / `fmi3Reset`); failure
  of `fmiXReset` → error.
- Datalog (D13): the `true` value of `container.<fmu>.reset` appears in the CSV, for a trigger fed by a link and
  for an exposed trigger set by the importer.
- Golden files (`tests/integration/test_container_golden.py`) for a container with `reset_ports`.

Commit message: `Tests: reset of embedded FMUs and of containers`

### Step 8 — GUI

- Section 4.6; GUI tests next to the `ts_multiplier` ones.

Commit message: `FMU Container Builder: wire container.<fmu>.reset from the configuration node`

### Step 9 — User documentation

- `docs/user-guide/fmucontainer/container.md`: option `reset_ports`, `-reset-ports`, ports `container.<fmu>.reset`,
  semantics (D5, D6, D9, D10), limits (FMUs that do not support `fmiXReset` or a start time other than 0).
- `docs/user-guide/fmucontainer/gui-usage.md`: checkbox and `configuration` node.
- `docs/API/container.md` if needed; `CHANGELOG.md`.
- Move this plan to `docs/local/done`.

Commit message: `Document the reset of embedded FMUs (reset_ports)`

