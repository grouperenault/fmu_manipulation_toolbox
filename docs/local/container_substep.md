# Communication steps that are not a multiple of the container step

**Created**: 17 October 2026 — **Status**: Step 1 done (17 October 2026), Step 2 to start — **Roadmap**: not listed

## Context

The importer comparison study (`docs/local/importer_comparison_report.md`, finding 4) tried the multi-rate
assemblies of Simulink as one sub-container per sample time. Every FMU then receives its own step size, but the
values exchanged between rates are not those of Simulink. The cause is a defect of `container_do_step`
(`container/container.c:1096`) with respect to the FMI contract of `doStep`, when the communication step `h` given by
the importer is not a multiple of the internal step `H` of the container (`time_step` × `ts_multiplier`):

- **`h` < `H`** (parent at 0.01 s, sub-container at 0.02 s): `local_steps` is 0, the container returns `OK`
  **without advancing** (its time stays at `t`). At the next call it makes its whole step `t → t + H` with the
  inputs received at `t + h`: inputs of a later instant are applied to an interval that started before.
- **`h` > `H`, not a multiple** (parent at 0.05 s, sub-container at 0.02 s): the container makes 2 steps, returns
  `OK` at 0.04 instead of 0.05 (warning "should be divisible"); the next call starts again from 0.04 with the inputs
  of 0.05.

In both cases the container returns `OK` without being at `t + h`, whereas FMI 2.0 / 3.0 require `doStep(t, h)` to
advance the FMU to `t + h`, with the inputs set before the call valid over `[t, t + h]`. The container declares
`canHandleVariableCommunicationStepSize="true"` (`fmu_manipulation_toolbox/container/builder.py:743`), so it accepts
any `h`. When `h` is an exact multiple of `H`, the behaviour is correct.

Measured consequence (S4 with one sub-container per rate, parent at 0.01 s): `B` (0.02 s) sees at t = 0.02 s the
output of `A` at 0.03 s instead of 0.02 s; `C` (0.05 s) sees at t = 0 the output of `B` at 0.04 s instead of its
initial value. Simulink (single-tasking) steps each block at the beginning of its period with the inputs of that
instant and publishes its outputs at the end of the period.

## Goal

Option (a) of the study: a container whose communication step is not a multiple of its internal step behaves as an
FMU with a fixed internal step sampled by its importer, like a block of Simulink:

- the inputs received at the **beginning** of each internal step `[T, T + H]` are the ones used for this step;
- the outputs computed by this step are **published at `T + H`**; between `T` and `T + H` the container returns the
  outputs of the previous internal step (zero-order hold);
- every `doStep(t, h)` returns with the container at `t + h`.

With one sub-container per sample time and the parent at the fastest sample time, the values exchanged between the
rates would then be those of Simulink single-tasking (`tools/probe_fmu`, scenario S4 with sub-containers, compared
with the Simulink traces of S4s).

## Options of implementation

The setters of the container forward the values of the importer at once to the embedded FMUs, and the getters read
the embedded FMUs directly (`container/fmi2.c`, `container/fmi3.c`): the inputs of the beginning of a step and the
held outputs need a buffer.

- **(a1) Step early, publish late**: at the first call of an internal step (container time `T` = `t`), the container
  makes its internal step `T → T + H` at once with the current inputs, and keeps a copy of the outputs of `T` that its
  getters return until the communication point reaches `T + H`. The values set by the importer during the step are
  forwarded as today: they are used by the next internal step (the importer sets them again before it).
- **(a2) Step late, inputs latched**: the container makes its internal step at the call that reaches `T + H`, as
  today, but with the inputs latched at `T`: the setters of the importer are buffered while an internal step is
  pending, and applied at its beginning.

## Decisions (2026-10-17)

1. **Implementation (a2), step late, inputs latched**: the internal step `[T, T + H]` is still made at the call of
   the importer that reaches `T + H` (the outputs are held meanwhile: the embedded FMUs are not stepped). The values
   set by the importer while an internal step is pending are kept and applied at the beginning of the next internal
   step; the step uses the values of `T`.
2. **Events**: same treatment for every container (CS FMUs with event mode, ME FMUs, clocks / LS-BUS): the internal
   step and its events are handled as today at the final call; only the inputs are latched.
3. **`h` > `H`, not a multiple**: the last partial interval is a pending internal step (same mechanism); the
   container is at `t + h` after every call, and the warning "should be divisible" is removed.
4. **`ts_multiplier`**: read at the beginning of each internal step (latched like the other inputs): it gives the
   length `H` of this step.
5. **Default time step of a container** whose FMUs all handle a variable step: unchanged (the largest of their
   steps); the documentation recommends the fastest sample time for the parent of sub-containers of different rates.
6. **Capability**: `canHandleVariableCommunicationStepSize` stays `"true"`.
7. **Branch**: a new branch from `importer-comparison` (name to give).

## Steps (draft, to be refined after the decisions)

### Step 1 – Runtime

`container_do_step` per decisions 1–4: pending internal step, latched inputs or held outputs, container time at
`t + h` after every call; the getters and setters of `container/fmi2.c` / `container/fmi3.c` per decision 1.

Done: `container/container.c` (`container_do_step` loops over the internal steps that end before `t + h`, the
multiplier read before each one; `step_pending` when a step does not fit; `container_apply_deferred` after the
pending step), `container/container.h` (`step_pending`, `container_port_t.deferred`), the setters of
`container/fmi2.c` / `container/fmi3.c` (numbers, strings, binaries; clocks unchanged) defer while a step is
pending; the cache of the importer values covers every port with a link (FMU or local variable). Check: S4 with one
sub-container per rate and the parent at 0.01 s gives, for the 5 links, the inputs of the Simulink traces of S4s
at every step; with the parent at its default step (0.05 s), the link from the fast to the medium FMU exchanges
every 0.05 s only (decision 5). The REF results of the test suite are unchanged.

Commit message: `Handle communication steps that are not a multiple of the container step`

### Step 2 – Tests

- Probe scenario S4 with one sub-container per rate (parent at 0.01 s and at the default step): each probe gets its
  own step size, and the inputs seen at each step are those of the Simulink traces of S4s
  (`tools/compare_traces.py`); reference traces in `tests/data/probe`.
- A container driven with `h` < `H` and with `h` not a multiple of `H` (fmpy, `FMU2Slave`): time at `t + h`, outputs
  held, inputs of the beginning of the step.
- The REF results of the test suite: unchanged when `h` is a multiple of `H`.

Commit message: `Test communication steps that are not a multiple of the container step`

### Step 3 – User documentation

- `docs/user-guide/fmucontainer/container.md`: communication step and internal step of a container (sub-containers
  of different steps).
- `docs/developer/dostep-fmi-sequence.md`: the sequence of a pending internal step.
- `docs/examples/simulink-to-container.md`: *One sub-container per sample time*, the remaining difference removed.
- `docs/local/importer_comparison_report.md`: TL;DR point 3 and finding 4.
- `CHANGELOG.md`: 🟠 **FIXED** entry (FMU Container).

Commit message: `Document the communication steps that are not a multiple of the container step`
