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

    opt FMI3 container: Configuration Mode of the importer
        I->>C: fmi3EnterConfigurationMode()
        C->>F1: fmi3EnterConfigurationMode()<br/>(FMUs with structural parameters only)
        C->>F1: fmi3SetXXX<br/>(start values RESET=2)
        I->>C: fmi3SetXXX (structural parameters)
        C->>F1: fmi3SetXXX
        I->>C: fmi3ExitConfigurationMode()
        C->>F1: fmi3ExitConfigurationMode()
    end

    Note over I, F2: Setup experiment (FMI2: fmi2SetupExperiment)
    I->>C: fmi2SetupExperiment(tolerance, startTime, stopTime)
    C->>C: store tolerance / start_time / stop_time
    Note Over C, F2: FMU after FMU, before its fmi2SetupExperiment
    C->>F1: fmi3Enter/ExitConfigurationMode()<br/>(structural parameters, if not configured yet)
    C->>F1: fmi*SetReal/Int/Bool/...<br/>(start values, early or reset, then the values set by the importer)
    C->>F1: fmi2SetupExperiment()<br/>(FMI2 only — no-op in FMI3)
    C->>F2: (same sequence)

    Note over I, F2: [INITIALIZATION MODE]
    I->>C: fmi*EnterInitializationMode()
    C->>F1: fmi*EnterInitializationMode()
    C->>F2: fmi*EnterInitializationMode()
    Note Over C, F2: Apply remaining start values
    C->>F1: fmi*SetReal/Int/Bool/...<br/>(remaining start values)
    C->>F2: fmi*SetReal/Int/Bool/...<br/>(remaining start values)
    Note Over I, C: The importer sets the inputs of the container

    I->>C: fmi*ExitInitializationMode()
    Note over C, F2: Propagate the links, FMU after FMU (initialization order of container.txt)
    C->>F1: fmi*SetReal/Int/Bool/...<br/>(linked inputs)
    C->>F1: fmi*ExitInitializationMode()
    C->>F1: fmi*GetReal/Int/Bool/...<br/>(outputs; ME: after its event iteration)
    C->>F2: fmi*SetReal/Int/Bool/...<br/>(linked inputs, from the outputs of F1)
    C->>F2: fmi*ExitInitializationMode()
    C->>F2: fmi*GetReal/Int/Bool/...<br/>(outputs; ME: after its event iteration)
    Note Over C, F2: FMUs are now in EVENT MODE

    Note Over C, F2: Read initial outputs
    C->>F1: fmi*GetReal/Int/Bool/...<br/>(outputs + clocked outputs)
    C->>F2: fmi*GetReal/Int/Bool/...<br/>(outputs + clocked outputs)

    Note over C, F2: Outputs and inputs go in two super-dense time instants
    C->>F1: fmi*UpdateDiscreteStates()
    C->>F2: fmi*UpdateDiscreteStates()
    C->>F1: fmi*SetClock(vr, true) + clocked inputs
    C->>F2: fmi*SetClock(vr, true) + clocked inputs

    Note over C, F2: Resolve discrete states
    loop Do While more_event
        Note over C, F2: From the second pass: UpdateDiscreteStates(), then clocks and clocked inputs
        C->>F1: fmi*UpdateDiscreteStates()
        F1-->>C: nextEventTime, more_event
        C->>F1: fmi*GetClock + clocked outputs
        C->>F2: fmi*UpdateDiscreteStates()
        F2-->>C: nextEventTime, more_event
        C->>F2: fmi*GetClock + clocked outputs
        C->>C: datalog_log()
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
- Start values declared in `container.txt` are applied in **three phases** (`<RESET>` of
  [container.txt](container-txt-format.md#72-start-values)): the structural parameters (`<RESET>=2`) in
  *Configuration Mode*, the *early* values (`<RESET>` 0 and 1) **before** `fmi2SetupExperiment` (an FMU may use its
  parameters there, e.g. to start the XCP service of FMI-LS-XCP), and the values flagged `<RESET>=1` again once the
  FMUs are in *Initialization Mode*. After the early values, the values set by the importer on the container (its
  cache) are set again: they prevail over the start values.
- The FMUs with structural parameters set by the container (`<has_configuration_mode>`) go through their
  *Configuration Mode* once after their instantiation and after each reset: with the *Configuration Mode* of the
  container when its importer uses it (FMI 3.0), otherwise right before their early start values. A value set on a
  structural parameter outside of *Configuration Mode* is kept until then.
- The links between the embedded FMUs are **propagated during the initialization**, as Simulink does
  (`container_exit_fmus_initialization()`, run by `fmi*ExitInitializationMode()` of the container): in the
  *initialization order* written by the builder in `container.txt` (a topological sort of the FMUs by
  their links, see [container.txt Format](container-txt-format.md#4b-initialization-order)), each FMU gets
  its linked inputs, leaves its *Initialization Mode*, then its outputs are read for the FMUs after it.
  An ME FMU is read after its own event iteration (`fmi*UpdateDiscreteStates()` until no more event), never
  before its first update of the discrete states.
- **No output is read in Initialization Mode**: some FMUs (e.g. generated by Simulink) compute their
  outputs only when they leave it. Consequences: an output of the container read by its importer before
  `fmi*ExitInitializationMode()` is not propagated yet; in a loop of links, the first FMU of the loop in
  the configuration is initialized with the value the link has before the propagation (the builder logs a
  warning). Clocks and clocked variables are not propagated. A nested container propagates its own links
  when its parent makes it leave its Initialization Mode.
- After `fmi*ExitInitializationMode()`, the FMUs are in **EVENT MODE**. The container therefore
  runs one full `container_update_discrete_state()` loop (the same loop used during
  `container_do_step()`) to settle clocks and discrete states before computing the first
  `next_step`.
- `fmi3GetIntervalDecimal()` is invoked only for FMUs that own scheduled clocks.
- Once `fmi*EnterStepMode()` returns, the container is in `STEP_MODE` and ready for the first
  call to `container_do_step()` (see [DoStep FMI Sequence](dostep-fmi-sequence.md)).

