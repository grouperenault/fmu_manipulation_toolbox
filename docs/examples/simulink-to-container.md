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
| FMU blocks of different sample times | one sub-container per sample time, with its own `step_size` (see [One sub-container per sample time](#one-sub-container-per-sample-time)) |
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

Both **propagate the links during the initialization**: an FMU whose initial state, or calculated parameters,
depend on its inputs is initialized with the values of the FMUs upstream (see
[Initialization of the embedded FMU's](../user-guide/fmucontainer/container.md#initialization-of-the-embedded-fmus)).
On a chain of three FMUs whose initial outputs depend on their inputs, the container and Simulink give **the same
initial values and the same values at every step**, once the unconnected inputs have the value Simulink imposes
(see below).

Both follow the same rule: in the order of the connections, each FMU gets its inputs from the FMUs before it,
leaves its Initialization Mode, then its outputs are read. **Simulink** sets the parameters of every FMU block
first, and enters the Initialization Mode of each block just before initializing it; **the container** enters the
Initialization Mode of all its FMUs at once. Neither solves a **loop of links** at the initialization: the
container cuts it before its first FMU in the description (warning at the build).

The [unconnected inputs](#unconnected-inputs) also take part in the initialization: give them the value of
Simulink (0) to get the same initial values. An input left at another start value in the container shifts the
initial values of every FMU downstream.

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
strict implementation) cannot be stepped correctly by such a container: the container reports a warning for each FMU
whose step size does not divide its step. Use one sub-container per sample time.

#### One sub-container per sample time

Each [nested container](../user-guide/fmucontainer/container.md) has its own `step_size` and steps its FMUs with it:
group the FMUs of each Simulink sample time in a sub-container, and connect the sub-containers in the parent
container. For the worked example:

```json
{
  "name": "assembly.fmu",
  "step_size": 0.01,
  "auto_link": false,
  "auto_input": false,
  "auto_output": false,
  "container": [
    {"name": "fast_rate.fmu", "step_size": 0.01, "auto_link": false, "auto_input": false, "auto_output": false,
     "fmu": ["fast.fmu"],
     "input": [["command", "fast.fmu", "command"], ["u", "fast.fmu", "u"]],
     "output": [["fast.fmu", "y", "y"]]},
    {"name": "medium_rate.fmu", "step_size": 0.02, "auto_link": false, "auto_input": false, "auto_output": false,
     "fmu": ["medium.fmu"],
     "input": [["u", "medium.fmu", "u"]],
     "output": [["medium.fmu", "y", "y"]],
     "start": [["medium.fmu", "gain", 2]]},
    {"name": "slow_rate.fmu", "step_size": 0.05, "auto_link": false, "auto_input": false, "auto_output": false,
     "fmu": ["slow.fmu"],
     "input": [["u", "slow.fmu", "u"]],
     "output": [["slow.fmu", "y", "y"], ["slow.fmu", "result", "result"]]}
  ],
  "link": [
    ["fast_rate.fmu", "y", "medium_rate.fmu", "u"],
    ["medium_rate.fmu", "y", "slow_rate.fmu", "u"],
    ["slow_rate.fmu", "y", "fast_rate.fmu", "u"]
  ],
  "input": [["command", "fast_rate.fmu", "command"]],
  "output": [["slow_rate.fmu", "result", "result"]]
}
```

- Every FMU receives **its own step size**, as in Simulink: `fast` 0.01 s, `medium` 0.02 s, `slow` 0.05 s.
- Give the parent container the **fastest sample time** (`step_size` 0.01 s): the sub-containers exchange their
  values as often as the fastest FMU. Without `step_size`, the parent takes the largest step of the
  sub-containers (0.05 s): the fast FMUs then exchange their values only every 0.05 s, and the parent reports that
  the step of the sub-containers does not divide its own.
- **Remaining difference**: a sub-container slower than its parent makes its step at the **last** call of the
  parent in its period, with the inputs of that call, while Simulink steps the block at the **beginning** of its
  period with the inputs of that instant. A value going from a faster FMU to a slower one is therefore more recent
  than in Simulink, by up to one period of the slower FMU minus one step of the parent (in the example, `medium`
  at t = 0.02 s sees the output of `fast` at 0.03 s instead of 0.02 s, and `slow` at t = 0 sees the output of
  `medium` at 0.04 s instead of its initial value). The values going from a slower FMU to a faster one are the
  same as in Simulink (held between the steps of the slower FMU).

In multi-tasking, Simulink also delays the transfers from a slow block to a fast one by one period of the slow
block (deterministic *Rate Transition*). The container has no such delay.

### Delays between FMUs

In Simulink, at each step, an FMU block reads its outputs (as computed by its last step), then sets its inputs
from the outputs of the blocks upstream and steps. An output that an FMU computes from its inputs therefore reaches
the next FMU one step later: along a chain `A → B → C` where `B` passes its input to its output, `C` sees the value
of `A` one step after `B` does, **even when `B` declares a direct dependency** (feedthrough) of this output on its
input.

The **default scheduling of the container** gives the same delays: on such a chain, the inputs received by each FMU
at every step are the same as in Simulink. The `sequential` option steps the FMUs one
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
   [initialization](#initialization) (an unconnected input, a loop of links), a difference that grows points at
   the [sample times](#sample-times) or at a start value.
