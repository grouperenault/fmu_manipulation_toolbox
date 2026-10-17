# From Simulink to an FMU Container

This page explains how to turn an assembly of FMUs built in Simulink (FMU blocks of *Simulink Extras / FMU
Import*, Co-Simulation) into an equivalent [FMU Container](../user-guide/fmucontainer/container.md), and what to
check so that both give the same results.

The behaviours described here were measured on MATLAB R2024b with FMI 2.0 Co-Simulation FMUs, by tracing the FMI
calls received by the FMUs in both importers.

## Mapping of the concepts

| Simulink | FMU Container (JSON description) |
|---|---|
| FMU block | an entry of `fmu` |
| Several FMU blocks on the same FMU file | [instances](../user-guide/fmucontainer/container.md#embedding-the-same-fmu-several-times): one name per block in `fmu`, its file in `path` |
| Line between two FMU blocks | `link`: `[from_fmu, output, to_fmu, input]` |
| Root `Inport` feeding FMU inputs | `input`: `[name, fmu, input]` (one entry per FMU input it feeds) |
| Root `Outport` | `output`: `[fmu, output, name]` |
| Output connected to a `Terminator`, or left unconnected | `drop`: `[fmu, output]`, or `auto_output: false` |
| Subsystem | nested container (`container` list) |
| Value of an FMU parameter in the block dialog | `start`: `[fmu, parameter, value]` |
| Start value of an FMU input | `start`: `[fmu, input, value]` |
| Sample time of the FMU block (`FMUSampleTime`) and fixed step of the solver | `step_size` of the container (see [Sample times](#sample-times)) |
| Single-tasking / multi-tasking | no equivalent; `mt` runs the FMUs in parallel threads (see [Computation time](#computation-time)) |

Declare everything explicitly: set `auto_link`, `auto_input` (and possibly `auto_output`) to `false`, so that
the container does not add links or ports that the Simulink model does not have.

## Worked example

A Simulink model with three FMU blocks:

- `fast` (`fast.fmu`, sample time 0.01 s), `medium` (`medium.fmu`, 0.02 s), `slow` (`slow.fmu`, 0.05 s);
- lines `fast/y → medium/u`, `medium/y → slow/u`, `slow/y → fast/u`;
- a root `Inport` `command` feeding `fast/command`, a root `Outport` `result` on `slow/result`;
- in the dialog of `medium`, the parameter `gain` set to 2;
- fixed-step solver, step 0.01 s.

Equivalent container description `assembly.json`:

```json
{
  "name": "assembly.fmu",
  "step_size": 0.01,
  "auto_link": false,
  "auto_input": false,
  "auto_output": false,
  "fmu": ["fast.fmu", "medium.fmu", "slow.fmu"],
  "link": [
    ["fast.fmu", "y", "medium.fmu", "u"],
    ["medium.fmu", "y", "slow.fmu", "u"],
    ["slow.fmu", "y", "fast.fmu", "u"]
  ],
  "input": [["command", "fast.fmu", "command"]],
  "output": [["slow.fmu", "result", "result"]],
  "start": [["medium.fmu", "gain", 2]]
}
```

```bash
fmucontainer -container assembly.json
```

The choice of `step_size` (here the fastest sample time) is discussed in [Sample times](#sample-times).

## Behaviour differences

### Initialization

**Simulink** initializes the FMU blocks one after the other, in the order of their connections: the inputs of a
block are set from the outputs of the blocks upstream, read after *their* initialization, before the block leaves
its Initialization Mode. **The container does not propagate its links during the initialization**: each embedded
FMU is initialized with its inputs at their start values; the values of the links reach the inputs at the first
step.

This matters when an FMU computes its initial state, or calculated parameters, from its inputs: its whole
simulation can then differ. To get the same initialization in the container, give such inputs a start value equal
to the value the upstream FMU produces at the initialization (`start` block).

### Unconnected inputs

**Simulink** sets an unconnected input of an FMU block to **0**, in Initialization Mode and before every step: the
start value declared by the FMU is not used. **The container** keeps the start value of the FMU (or the `start`
value of the description) for an input that is neither connected nor exposed.

To reproduce the Simulink model, give each unconnected input an explicit start value of 0 in the `start` block.

### Parameters

Simulink sets **every** parameter of the FMU (with its default value when the dialog does not change it) before
`fmi2SetupExperiment`; the container only sets the values of the `start` block, after `fmi2SetupExperiment`. For an
FMU that relies on its declared start values, both are equivalent. Simulink also calls `fmi2SetupExperiment` with
a tolerance of 0.001 (the container: 1e-8), which matters only for FMUs that use the tolerance internally.

### Sample times

**Simulink** steps each FMU block at its own sample time, and holds its outputs between two steps when they feed a
block of another rate. **The container** has a single time step: every embedded FMU is stepped with the step of the
container.

- Without `step_size`, the container uses the least common multiple of the step sizes of the FMUs that require a
  fixed step (see [Default time step](../user-guide/fmucontainer/container.md#default-time-step)): in the example,
  0.1 s; every FMU then exchanges its values every 0.1 s, and `fast` receives steps of 0.1 s instead of 0.01 s.
- With `step_size` equal to the fastest sample time (0.01 s in the example), the exchanges happen as often as in
  Simulink, but `medium` and `slow` receive steps of 0.01 s instead of 0.02 s and 0.05 s.

An FMU that cannot handle another step size than its own (`canHandleVariableCommunicationStepSize="false"` and a
strict implementation) has no exact equivalent in a container of several rates: the container reports a warning
for each FMU whose step size does not divide its step. Group the FMUs by rate, or check that each FMU accepts the
step of the container.

In multi-tasking, Simulink also delays the transfers from a slow block to a fast one by one period of the slow
block (deterministic *Rate Transition*). The container has no such delay.

### Delays between FMUs

In Simulink, at each step, an FMU block reads its outputs (as computed by its last step), then sets its inputs
from the outputs of the blocks upstream and steps. An output that an FMU computes from its inputs therefore reaches
the next FMU one step later: along a chain `A → B → C` where `B` passes its input to its output, `C` sees the value
of `A` one step after `B` does, **even when `B` declares a direct dependency** (feedthrough) of this output on its
input.

The **default scheduling of the container** gives the same delays. The `sequential` option steps the FMUs one
after the other in the order of the `fmu` list, each one with the outputs just computed by the previous ones:
along the order of the chain, the delays disappear, which changes the results compared to Simulink. Keep the
default scheduling to reproduce Simulink.

### Computation time

Simulink runs the FMU blocks of one sample time one after the other, even in multi-tasking (one task per rate). The
`mt` option of the container runs each embedded FMU in its own thread: the computation time of FMUs of the same rate
is shared between the cores, without changing the results.

## Validation checklist

1. Same FMU files, same parameter values and start values (including the 0 of the unconnected inputs).
2. `auto_link` and `auto_input` set to `false`; every Simulink line has its `link`.
3. `step_size` chosen per [Sample times](#sample-times); no warning about the step size when the container is built,
   or warnings understood.
4. Default scheduling (no `sequential`).
5. Same stop time; simulate the container (e.g. with `fmpy`) with an output interval equal to its step.
6. Compare the outputs at the common sample times; a difference at the beginning only points at the
   [initialization](#initialization), a difference that grows points at the [sample times](#sample-times) or at a
   start value.
