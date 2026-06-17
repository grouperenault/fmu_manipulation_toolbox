# FMI API Call Sequence during Container Initialization

> **Audience**: Developers working on the FMU Container C runtime.

This page documents the sequence of [FMI API](https://www.fmi-standard.org) calls that the
container performs on each embedded FMU while the container itself is being initialized by the
importer (co-simulation master).

The container goes through the standard FMI lifecycle states
(`INSTANTIATED` → `INITIALIZATION_MODE` → `STEP_MODE`) and propagates every transition to all
embedded FMUs. The diagram below shows the sequence for the **sequential** execution mode; the
parallel modes follow the same logical order.

!!! note "FMI 2.0 vs FMI 3.0"
    In **FMI 2.0** the importer calls `fmi2SetupExperiment()` and then
    `fmi2EnterInitializationMode()` as two separate calls. In **FMI 3.0** there is no
    `SetupExperiment`: the tolerance and time information is passed directly to
    `fmi3EnterInitializationMode()`. Internally the container routes both flavors through the
    same `container_setup_experiment()` / `container_enter_initialization_mode()` helpers, so the
    sequence below applies to both versions.

```mermaid
sequenceDiagram
    autonumber
    participant I as Importer
    participant C as Container
    participant F1 as FMU #1
    participant F2 as other FMU #2 (… #N)

    Note over I, F2: [INSTANTIATED]
    I->>C: fmi*Instantiate()
    C->>C: container_new()
    C->>C: container_configure()<br/>(read container.txt)
    C->>F1: fmi*Instantiate()<br/>(CoSimulation)
    C->>F2: fmi*Instantiate()<br/>(CoSimulation)

    Note over I, F2: Setup experiment (FMI2: fmi2SetupExperiment)
    I->>C: fmi2SetupExperiment(tolerance, startTime, stopTime)
    C->>C: store tolerance / start_time / stop_time
    C->>F1: fmi2SetupExperiment()<br/>(FMI2 only — no-op in FMI3)
    C->>F2: fmi2SetupExperiment()<br/>(FMI2 only — no-op in FMI3)
    Note Over C, F2: Apply "early" start values
    C->>F1: fmi*SetReal/Int/Bool/...<br/>(start values, early or reset)
    C->>F2: fmi*SetReal/Int/Bool/...<br/>(start values, early or reset)

    Note over I, F2: [INITIALIZATION MODE]
    I->>C: fmi*EnterInitializationMode()
    C->>F1: fmi*EnterInitializationMode()
    C->>F2: fmi*EnterInitializationMode()
    Note Over C, F2: Apply remaining start values
    C->>F1: fmi*SetReal/Int/Bool/...<br/>(remaining start values)
    C->>F2: fmi*SetReal/Int/Bool/...<br/>(remaining start values)

    I->>C: fmi*ExitInitializationMode()
    C->>F1: fmi*ExitInitializationMode()
    C->>F2: fmi*ExitInitializationMode()
    Note Over C, F2: FMUs are now in EVENT MODE

    Note Over C, F2: Read initial outputs
    C->>F1: fmi*GetReal/Int/Bool/...<br/>(outputs + clocked outputs)
    C->>F2: fmi*GetReal/Int/Bool/...<br/>(outputs + clocked outputs)

    Note over C, F2: Resolve discrete states
    loop Do While more_event
        C->>F1: fmi*SetClock(vr, true) + clocked inputs
        C->>F2: fmi*SetClock(vr, true) + clocked inputs
        C->>C: datalog_log()
        C->>F1: fmi*GetClock + clocked outputs
        C->>F2: fmi*GetClock + clocked outputs
        C->>F1: fmi*UpdateDiscreteStates()
        F1-->>C: nextEventTime, more_event
        C->>F2: fmi*UpdateDiscreteStates()
        F2-->>C: nextEventTime, more_event
    end

    Note over C, F2: Prepare first scheduled event
    C->>F1: fmi3GetIntervalDecimal()
    C->>F2: fmi3GetIntervalDecimal()
    C->>C: compute next_step

    Note over I, F2: [STEP MODE]
    C->>F1: fmi*EnterStepMode()
    C->>F2: fmi*EnterStepMode()
    C-->>I: fmi*OK (ready for container_do_step)
```

## Notes

- `fmi*Instantiate` of the **embedded** FMUs happens inside `container_configure()`, which is
  itself called from `fmi2Instantiate` / `fmi3InstantiateCoSimulation`. By the time the importer
  receives the container instance, all embedded FMUs are already instantiated.
- `fmuSetupExperiment()` only emits an FMI call for **FMI 2.0** FMUs
  (`fmi2SetupExperiment`); for **FMI 3.0** FMUs it is a no-op since the equivalent parameters are
  forwarded through `fmi3EnterInitializationMode()`.
- Start values declared in `container.txt` are applied in **two passes**:
  the *early* pass (`container_set_start_values(early=1)`) during setup, and the remaining values
  (`container_set_start_values(early=0)`) once the FMUs are in *Initialization Mode*. Values
  flagged as `reset` are (re)applied in both passes.
- After `fmi*ExitInitializationMode()`, the FMUs are in **EVENT MODE**. The container therefore
  runs one full `container_update_discrete_state()` loop (the same loop used during
  `container_do_step()`) to settle clocks and discrete states before computing the first
  `next_step`.
- `fmi3GetIntervalDecimal()` is invoked only for FMUs that own scheduled clocks.
- Once `fmi*EnterStepMode()` returns, the container is in `STEP_MODE` and ready for the first
  call to `container_do_step()` (see [DoStep FMI Sequence](dostep-fmi-sequence.md)).

