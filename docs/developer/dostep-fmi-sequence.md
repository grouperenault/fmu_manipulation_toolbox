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
    C->>F1: fmi*SetReal/Int/Bool/...<br/>(values set by the importer, then linked inputs)
    C->>F2: fmi*SetReal/Int/Bool/...<br/>(values set by the importer, then linked inputs)

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
        Note over C, F2: Gauss-Seidel sweep in configuration order<br/>(Set inputs → UpdateDiscreteStates → Get outputs per FMU)
        C->>F1: fmi*SetClock(vr, true) <br/>(activated clocks)
        C->>F1: fmi*SetReal/Int/Bool <br/>(inputs + clocked inputs)
        C->>F1: fmi*UpdateDiscreteStates()
        F1-->>C: nextEventTime, more_event
        C->>F1: fmi*GetReal/Int/Bool + fmi*GetClock <br/>(outputs + clocked outputs)

        C->>F2: fmi*SetClock(vr, true) <br/>(activated clocks)
        C->>F2: fmi*SetReal/Int/Bool <br/>(inputs + clocked inputs)
        C->>F2: fmi*UpdateDiscreteStates()
        F2-->>C: nextEventTime, more_event
        C->>F2: fmi*GetReal/Int/Bool + fmi*GetClock <br/>(outputs + clocked outputs)

        C->>C: datalog_log()
    end

    Note over C, F2: Prepare next scheduled event
    C->>F1: fmi3GetIntervalDecimal()
    C->>F2: fmi3GetIntervalDecimal()
    C->>C: compute next_step

    C->>F1: fmi*EnterStepMode()
    C->>F2: fmi*EnterStepMode()
```

## Internal steps and communication step

`container_do_step(t, h)` makes every internal step `[T, T + H]` (`H` = `time_step` × `TS_MULTIPLIER`, the
multiplier read before each step) that ends before `t + h`, each one as in the diagram above. When an internal step
does not fit (communication step not a multiple of the internal step), it stays **pending**
(`container->step_pending`):

- when it becomes pending, every embedded FMU is synchronized with the values set until then (the inputs of `T`);
- while it is pending, nothing is synchronized: the values set by the importer stay in the cache (they are for the
  steps after it), the ports linked to local variables join the set of the deferred ports of the cache; the outputs of the
  embedded FMU's, read by the getters, are those of `T`;
- the call of the importer that reaches `T + H` makes the step, then writes the local variables of the deferred ports
  (`cache_end_pending_step()`: `TS_MULTIPLIER`, reset triggers); the embedded FMU's get their values at their
  next synchronization, for the following steps.

The container is at `t + h` after every call (`reals64[0]`, its time output).

## Values set by the importer

The setters of the container (`fmi2Set*`, `fmi3Set*`, except `fmi3SetClock`) do not call the embedded FMU's: one call
of `cache_set_<type>()` per port writes the **cache** (module `cache.c`), the state to come: the values of the port,
and its links added to the **set** of their FMU (a link is in a set once, `container_vr_t.cache.in_set`). It tells
the setter whether to write the local variables of the port at once: the port has some
(`container_port_t.cache.has_local`, known when the container is loaded) and no step is pending. An FMU gets the
values of its set when it is **synchronized** (`cache_sync_fmu()`, one `fmi*Set` per link, from the cache, in the
order of the calls of the importer):

- before each of its steps, at the exit of the Initialization Mode and at the event iterations (`fmu_set_inputs`);
  in Continuous Time Mode, its real values only (`fmu_set_continuous_inputs`), as its links;
- before it is read by a getter of the container (read after write). A getter on a port set by the importer returns
  the value of the cache (`cache_read_<type>()`), without calling the FMU;
- in its Configuration Mode (its structural parameters only: `container_vr_t.cache.start_reset` is 2), before its
  `fmi2SetupExperiment` and after its reset, where all its cached values join its set again (they prevail over the
  start values; this goes through all the ports, once per phase).

The sets are allocated when the container is loaded, for all the entries they may hold: a synchronization goes
through the set of the FMU only, and costs nothing when it is empty. For an FMU without structural parameter, out of
Continuous Time Mode, every entry is set without being examined.

A value refused by an FMU is reported by the call that synchronizes it (`fmi*DoStep`, `fmi*ExitInitializationMode`,
`fmi*Get*`...), not by `fmi*Set*`. In the multi-thread mode, the synchronization runs in the main thread
(`fmu_set_inputs`): the worker threads only run `fmi*DoStep`.

## Notes

- `fmu_set_inputs` / `fmu_get_outputs` in the C runtime expand into a series of typed FMI calls
  (`fmi2SetReal`, `fmi3SetFloat64`, `fmi3SetBoolean`, …) according to the ports declared in
  `fmu_io`.
- In the **multi-thread parallel** mode, `fmi*DoStep` is executed concurrently on each FMU via
  per-FMU worker threads, synchronized through `mutex_container` / `mutex_fmu`.
- The EVENT MODE phase is entered only when at least one FMU has reported
  `need_event_update`, or when clocks are declared in `clocks_list`.
- Inside the `more_event` loop, FMUs are updated with a **Gauss-Seidel sweep** in configuration
  order: each FMU is driven `Set inputs → fmi*UpdateDiscreteStates → Get outputs` before moving to
  the next one, so a value produced by FMU *i* reaches FMU *i+1* within the same pass and the
  outputs read back reflect the freshly updated discrete state.
- `fmi3GetIntervalDecimal()` is invoked only for FMUs that own scheduled clocks.
