# Migrating an FMU assembly from Simulink to an FMU Container

**Created**: 17 October 2026 — **Status**: draft, open decisions to answer before Step 1 — **Roadmap**: not listed

## Goal

**Deliverable**: a user documentation page explaining how to convert an assembly of FMUs made in Simulink (native
FMU blocks) into an equivalent FMU Container, and what to check so that both give the same results.

To write it from measured facts rather than assumptions, the two importers are first compared with a
**probe FMU**: an FMU that traces every FMI call it receives (function, time, step size, values). Both importers
are seen through the same lens, independently of their own logging. The study (Steps 1–4) is the means; the
documentation (Step 5) is the product.

## Relation with the Simulink export plan

This plan is **independent** of `docs/local/simulink_export.md` (export of a container assembly to Simulink, the
opposite direction): the Simulink models of the study are built by hand (or with a small MATLAB script) by the user.

Conversely, the study answers several `UNVERIFIED` points of the export plan, which can then rely on measured
behaviour:

- how and when Simulink applies the start values of FMU **inputs** and parameters;
- the order of the `Flat` ports of the FMU block (port indices used by `add_line`);
- the effect of `FMUSampleTime` and of the fixed-step solver (the "smallest `step_size`" rule, decision 6 of the
  export plan);
- the CS / ME mode chosen by the block.

The findings on these points are recorded in the report of Step 4 and referenced from `simulink_export.md`.

## Behaviour of the container runtime (expected differences)

| Topic | Container runtime | Where | Simulink (to be confirmed by the study) |
|---|---|---|---|
| Start values | set once after `fmuSetupExperiment` (all), set again after `fmuEnterInitializationMode` (only those flagged `<RESET>`) | `container/container.c:349-430` | set through block parameters; order unknown |
| Links during initialization | **not propagated**: outputs are read only after `fmuExitInitializationMode`, inputs are set at the first step | `container/container.c:420-470` | the block sorted order may propagate outputs to inputs during initialization |
| Time step | one internal step = **LCM** of the fixed steps (or largest variable step); every CS FMU gets `doStep(h = container step)` | `fmu_manipulation_toolbox/container/builder.py:572`, `container/container.c:930` | one sample time per block, fixed-step solver at the **GCD**; a block is stepped at its own rate |
| Data exchange | at each container step only | `container/container.c:596-750` | at each rate hit; rate transitions depend on the tasking mode (single/multi-tasking) |
| Ordering | CS FMUs: set inputs → doStep → get outputs, sequential or parallel (`mt`) | `container/container.c:596` | sorted by direct feedthrough (`ModelStructure` dependencies) |

## Follow-up: propagation of the links during initialization

At its boundary the container is transparent during initialization: an importer `fmi2Set*` on an exposed input is
forwarded at once to the embedded FMU (`container/fmi2.c:225-250`), and an `fmi2Get*` reads the embedded FMU
directly (`container/fmi2.c:182-211`). Only the **internal links** (FMU → FMU) are not propagated before
`ExitInitializationMode`.

- **Impact**: at best, only the values at t=0 differ (the downstream FMU uses the start value of its input). At
  worst, when the initial state of the downstream FMU depends on its input (steady-state initialization,
  parameters calculated from an input, "initial condition from input"), the whole simulation differs.
- **Standard**: FMI 2.0 and 3.0 allow setting inputs and getting `initial="calculated"` outputs in Initialization
  Mode, precisely so that the master solves the initialization of the coupled system.
- **What a propagation needs**: an order (topological sort from `ModelStructure/InitialUnknowns`, already read by
  `fmu_manipulation_toolbox/container/builder.py:854`; no declared dependency = depends on every input); detection
  of algebraic loops at initialization (fixed-point iteration with a limit, or loop cut with a warning); robustness
  against FMUs that handle `Get*` in Initialization Mode badly (read only the linked outputs; see
  `container/container.c:425-432` for ME FMUs); backward compatibility (an option, e.g. `init_propagation`, with a
  default to decide).

**Decision rule**: scenario S3 measures whether Simulink propagates the links during initialization, and in which
order. If it does, a dedicated plan (`docs/local/init_propagation.md`) is opened after Step 4 (option and default,
algebraic loops, FMI 2.0 / 3.0, ME FMUs). Until it is implemented, the migration documentation describes the
difference and its workaround.

## Probe FMU (proposal)

One C source, packaged as several FMUs (or instances) that differ only by their step size.

- **Variables**
  - parameters: `p_real` (fixed), `p_tunable` (tunable), `compute_time` (s, simulated cost of `doStep`),
    `trace_file` (String, path of the trace);
  - inputs: `u_cont` (Real, continuous), `u_disc` (Real, discrete), `u_int` (Integer, discrete),
    `u_bool` (Boolean, discrete), all with start values;
  - outputs: `y_cont` (continuous, direct feedthrough of `u_cont` + function of time), `y_disc` (discrete, value of
    `u_disc` held from the previous step: no feedthrough), `y_int` (step counter), `y_init` (`initial="calculated"`
    from `p_real` and `u_cont` during initialization: shows whether the importer propagates links before
    `ExitInitializationMode`).
  - `ModelStructure`: `y_cont` depends on `u_cont`; `y_disc`, `y_int` have no input dependency.
- **Trace** (CSV, one line per FMI call): wall clock, FMI function, FMU time, `h` for `doStep`, value references and
  values for `Set*`/`Get*`, and a snapshot of all variables at `SetupExperiment`, `EnterInitializationMode`,
  `ExitInitializationMode` (before/after initialization), and the same messages through the FMI logger callback.
- **Computation time**: `doStep` waits `compute_time` seconds of wall clock (busy wait or sleep: open decision).
- **Fixed step**: `canHandleVariableCommunicationStepSize="false"`, `DefaultExperiment stepSize` set per FMU; the
  probe logs every `doStep` whose `h` differs from its step size (reject or accept: open decision).

## Study scenarios (proposal)

1. **S1 – single probe**: baseline of the call sequence of each importer, no link.
2. **S2 – start values**: start values overridden on parameters and inputs; compare the values seen before/after
   initialization.
3. **S3 – initialization chain**: `A.y_init → B.u_cont`; does `B` see `A`'s calculated value at t=0?
4. **S4 – three rates**: probes at three step sizes (e.g. 0.01 s, 0.02 s, 0.05 s: GCD 0.01 s, LCM 0.1 s), chained
   fast → slow and slow → fast; compare the `doStep` times and `h`, and the delay (in steps) between a producer and a
   consumer.
5. **S5 – feedthrough**: `y_cont` (feedthrough) vs `y_disc` (delayed) in a chain; ordering effects.
6. **S6 – computation time**: `compute_time > 0`, sequential vs `mt` in the container, single vs multi-tasking in
   Simulink; total wall time.

Each scenario produces: the probe traces of both importers, the result CSV of the container, the Simulink logged
signals. A Python script aligns the traces and reports the differences (call sequence, values, timing).

## Expected content of the user documentation

- **Mapping of concepts**: FMU block → embedded FMU (`fmu`, instance name); line → link; `Inport`/`Outport` →
  exposed input/output; `Terminator` → dropped port; subsystem → nested container; block parameter / input start
  value → `start`; `FMUSampleTime` and solver step → container `step_size`; several blocks on the same FMU file →
  instances.
- **Step-by-step conversion**: from a Simulink model to a JSON description (or a Container Builder session), with
  a worked example (the three-rate assembly of the study).
- **Behaviour differences and how to handle them** (from the report of Step 4): initialization, start values,
  rates and exchange delays, ordering / feedthrough, computation time and `mt`.
- **Validation checklist**: how to check that the container reproduces the Simulink results (compare logged
  signals, optionally with the probe FMU).

## Open decisions (to answer before Step 1)

1. **Documentation location**: a section of `docs/examples/examples.md` (*Common Use Cases*, problem/solution
   format), a new page with `Examples` turned into a group in `mkdocs.yml` (e.g. *Examples > From Simulink to an
   FMU Container*), or a page in *User Guide > FMU Container*? (Recommendation: a new page, the content is too long
   for a section of the use-cases page.)
2. **Probe FMU for users**: an internal study tool only, or published (shipped with the toolbox / downloadable,
   documented) so that users can check their own migration?
3. **FMI versions**: FMI 2.0 CS only, or FMI 2.0 and 3.0?
4. **Interface**: CS only, or CS and ME?
5. **Implementation**: own minimal FMI implementation (tracing built into every function), or a model written for
   the Reference FMUs framework (patched to trace the calls)?
6. **Three step sizes**: three FMUs built from the same source with different `stepSize`/`modelIdentifier`, or one
   FMU instantiated three times with a step size parameter (the container deduces its step from
   `DefaultExperiment` only)? Which values?
7. **Wrong `h` in `doStep`**: log only, reject (`fmi2Error`), or a parameter choosing between both?
8. **Computation time**: busy wait (consumes CPU, meaningful for `mt`), sleep, or a parameter?
9. **Trace location**: `trace_file` parameter with a default `<instanceName>.csv` in the current directory?
10. **Build on every OS**: CMake project in the repository built by `build-native.yml` (binaries for Windows, Linux,
    macOS packed in the FMUs), sources embedded in the FMU and compiled with `fmutool` compile sources, or both?
11. **Location in the repository**: e.g. `tests/data/probe/` (sources + CMake) and the generated FMUs, or `tools/`?
12. **Comparison script**: in `tools/` (study tool) or also as integration tests on the container side?
13. **MATLAB side**: which release, which Simulink settings (solver, tasking mode); will the user share the Simulink
    traces and logs, or the `.slx` too?

## Steps (draft, to be refined after the decisions)

### Step 1 – Probe FMU sources and build

C sources, `modelDescription.xml` template, CMake project producing the FMUs for the host; packaging script.
Multi-platform binaries (CI `build-native.yml`) per decision 10.

Commit message: `Add the probe FMU tracing the FMI calls of its importer`

### Step 2 – Scenarios on the container side

Container descriptions (JSON) of S1–S6, run with fmpy through `tests/_helpers/simulation.py`, traces saved.

Commit message: `Add the comparison scenarios built as FMU containers`

### Step 3 – Scenarios on the Simulink side (user)

Simulink models of S1–S6 built by hand (or with a small MATLAB script) and run by the user on MATLAB; traces and
logs shared and stored with the container ones.

Commit message: `Add the traces of the comparison scenarios run in Simulink`

### Step 4 – Comparison script and report

Script aligning the traces of both importers; report of the differences in `docs/local`, including the answers to
the `UNVERIFIED` points of `docs/local/simulink_export.md` (referenced from that plan), and the conclusion on the
propagation of the links during initialization (S3): open `docs/local/init_propagation.md` or not, see
*Follow-up: propagation of the links during initialization*.

Commit message: `Compare the traces of the FMU container and Simulink`

### Step 5 – User documentation

Write the migration page (content above, location per decision 1), add it to `mkdocs.yml`, link it from
`docs/user-guide/fmucontainer/container.md`; document the probe FMU if decision 2 publishes it; `CHANGELOG.md`
entry.

Commit message: `Document the migration of a Simulink FMU assembly to an FMU Container`
