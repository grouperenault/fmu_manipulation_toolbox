# FMI API Call Sequence during `container_do_step()`

> **Audience**: Developers working on the FMU Container C runtime.

This page documents the sequence of [FMI API](https://www.fmi-standard.org) calls that the
container performs on each embedded FMU during a single call to `container_do_step()`.

!!! info "Prerequisite"
    This page covers the **simulation loop**. For the sequence that brings the container up to
    `STEP_MODE` (instantiation and initialization), see the
    [Initialization FMI Sequence](init-fmi-sequence.md).

The container alternates between **STEP MODE** (continuous-time advancement via `fmi*DoStep`)
and **EVENT MODE** (discrete state updates and clock handling). The diagram below illustrates
the sequence for the **sequential** execution mode; the parallel modes (mono-thread and
multi-thread) follow the same logical order but interleave the `Set` / `DoStep` / `Get` phases
across all FMUs.

```mermaid
sequenceDiagram
   autonumber
    participant C as Container
    participant F1 as FMU #1
    participant F2 as other FMU #2 (… #N)

    Note over C, F2: [STEP MODE]
    C->>C: datalog_log()
    C->>F1: fmi*SetReal/Int/Bool/...<br/>(set inputs)
    C->>F2: fmi*SetReal/Int/Bool/...<br/>(set inputs)

    C->>F1: fmi*DoStep(time, next_step)
    F1-->>C: status + need_event_update

    C->>F2: fmi*DoStep(time, next_step)
    F2-->>C: status + need_event_update

    C->>F1: fmi*GetReal/Int/Bool/...<br/>(get outputs)
        C->>F2: fmi*GetReal/Int/Bool/...<br/>(get outputs)
    C->>C: time += next_step

    Note over C, F2: [EVENT MODE]    
    C->>F1: fmi*EnterEventMode()
    C->>F2: fmi*EnterEventMode()

    Note Over C, F2: Activate time based clocks
    C->>F1: fmi3SetClock(vr, true) <br/>for time based clocks 
    C->>F2: fmi3SetClock(vr, true) <br/>for time based clocks
    
    C->>F1: fmi*SetReal/Int/Bool/...<br/>(corresponding clocked inputs)
    C->>F2: fmi*SetReal/Int/Bool/...<br/>(corresponding clocked inputs)
    
    C->>F1: fmi*GetClock <br/>(output clocks)
    C->>F1: fmi*GetReal/Int/Bool <br/>(clocked outputs)

    C->>F2: fmi*GetClock <br/>(output clocks)
    C->>F2: fmi*GetReal/Int/Bool <br/>(clocked outputs)

    loop Do While more_event
        C->>F1: fmi*SetClock(vr, true) <br/>(activated clocks)
        C->>F1: fmi*SetReal/Int/Bool (corresponding clocked inputs)
        C->>F2: fmi*SetClock(vr, true) <br/>(activated clocks)
        C->>F2: fmi*SetReal/Int/Bool (corresponding clocked inputs)

        C->>C: datalog_log()

        C->>F1: fmi*GetClock <br/>(triggered clocks)
        C->>F1: fmi*GetReal/Int/Bool (corresponding clocked outputs)
        C->>F2: fmi*GetClock <br/>(triggered clocks)
        C->>F2: fmi*GetReal/Int/Bool (corresponding clocked outputs)

        C->>F1: fmi*UpdateDiscreteStates()
        F1-->>C: nextEventTime, more_event
 
        C->>F2: fmi*UpdateDiscreteStates()
        F2-->>C: nextEventTime, more_event
    end

    Note over C, F2: Prepare next scheduled event
    C->>F1: fmi3GetIntervalDecimal()
    C->>F2: fmi3GetIntervalDecimal()
    C->>C: compute next_step

    C->>F1: fmi*EnterStepMode()
    C->>F2: fmi*EnterStepMode()
```

## Notes

- `fmu_set_inputs` / `fmu_get_outputs` in the C runtime expand into a series of typed FMI calls
  (`fmi2SetReal`, `fmi3SetFloat64`, `fmi3SetBoolean`, …) according to the ports declared in
  `fmu_io`.
- In the **multi-thread parallel** mode, `fmi*DoStep` is executed concurrently on each FMU via
  per-FMU worker threads, synchronized through `mutex_container` / `mutex_fmu`.
- The EVENT MODE phase is entered only when at least one FMU has reported
  `need_event_update`, or when clocks are declared in `clocks_list`.
- `fmi3GetIntervalDecimal()` is invoked only for FMUs that own scheduled clocks.
