# Probe FMU

Internal tool of the importer comparison study (`docs/local/importer_comparison.md`): FMI 2.0 Co-Simulation FMUs
that trace every FMI call they receive, so that two importers (FMU Container, Simulink, ...) running the same
assembly can be compared through the same lens.

| File | Content |
|---|---|
| `probe.c` | the whole FMI 2.0 Co-Simulation implementation (C99, no dependency) |
| `make_probe.py` | generates the three FMUs below (reproducible: GUIDs from the model names, fixed archive dates) |
| `Probe10ms.fmu`, `Probe20ms.fmu`, `Probe50ms.fmu` | generated FMUs, **sources only**; `DefaultExperiment stepSize` 0.01 s, 0.02 s, 0.05 s |

After a change of `probe.c` or `make_probe.py`, regenerate the FMUs with `python tools/probe_fmu/make_probe.py`
(`tests/integration/test_probe_fmu.py` checks that they are up to date).

## Compilation

The FMUs ship their sources only. Compile them for the host (Windows, Linux or macOS) with the toolbox:

```bash
fmutool -input Probe10ms.fmu -compile-sources -output Probe10ms-host.fmu
```

## Variables

| VR | Name | Type | Causality | Variability | Start | Behaviour |
|---|---|---|---|---|---|---|
| 0 | `p_real` | Real | parameter | fixed | 1.0 | used by `y_init` |
| 1 | `p_tunable` | Real | parameter | tunable | 0.0 | offset of `y_cont` |
| 2 | `compute_time` | Real | parameter | fixed | 0.0 | wall time spent in each `fmi2DoStep` (s) |
| 3 | `compute_sleep` | Boolean | parameter | fixed | false | sleep instead of busy wait (busy wait consumes the CPU) |
| 4 | `strict_step` | Boolean | parameter | fixed | false | `fmi2DoStep` with `h` ≠ step size: `false` = warning, step done with `h`; `true` = `fmi2Error` |
| 5 | `trace_file` | String | parameter | fixed | "" | path of the trace; empty = `<instanceName>.csv` in the current directory |
| 10 | `u_cont` | Real | input | continuous | 0.0 | |
| 11 | `u_disc` | Real | input | discrete | 0.0 | |
| 12 | `u_int` | Integer | input | discrete | 0 | |
| 13 | `u_bool` | Boolean | input | discrete | false | |
| 20 | `y_cont` | Real | output | continuous | | `u_cont + p_tunable` (direct feedthrough) |
| 21 | `y_disc` | Real | output | discrete | | `u_disc` latched at the start of the last step (0 before the first step) |
| 22 | `y_int` | Integer | output | discrete | | number of steps done + 1000 × `u_int` latched at the start of the last step |
| 23 | `y_bool` | Boolean | output | discrete | | `u_bool` latched at the start of the last step (false before the first step) |
| 24 | `y_init` | Real | output | discrete | | `p_real + u_cont`, computed on each get until `fmi2ExitInitializationMode`, then frozen |
| 25 | `y_time` | Real | output | continuous | | time of the FMU |

`y_init` shows whether the importer propagates the links during the initialization: in a chain
`A.y_cont → B.u_cont`, `B.y_init` is `B.p_real + A.y_cont` only if the importer set `B.u_cont` before
`fmi2ExitInitializationMode`.

## Trace

CSV file, header `seq,wall,function,status,time,h,vr,name,value,note`:

| Column | Content |
|---|---|
| `seq` | number of the FMI call (shared by the lines of one call) |
| `wall` | seconds since `fmi2Instantiate` (monotonic wall clock) |
| `function` | FMI function, or `SNAPSHOT` |
| `status` | status returned by the call |
| `time` | time of the FMU at the call |
| `h` | communication step size (`fmi2DoStep` only) |
| `vr`, `name`, `value` | one line per value of `fmi2Get*` / `fmi2Set*`; for `fmi2DoStep`, one line per input seen by the step (`note` = `input`) |
| `note` | details: `h != step_size`, `currentCommunicationPoint=... != time`, refused value reference, snapshot label |

- **Snapshots** of every variable (`function` = `SNAPSHOT`, label in `note`): `before_setup_experiment`,
  `before_initialization` (at `fmi2EnterInitializationMode`), `after_initialization` (at
  `fmi2ExitInitializationMode`, after `y_init` is frozen), `terminate`.
- The file is opened by `fmi2EnterInitializationMode` (when `trace_file` is known); the lines of the calls made
  before are buffered and written first. It is closed by `fmi2FreeInstance` (written even when the initialization
  is never reached).
- With debug logging on (`fmi2SetDebugLogging`), each line is also sent to the FMI logger (category `probe`). The
  warnings (`h` ≠ step size) and errors are always sent (`logStatusWarning`, `logStatusError`).

`fmi2Reset` restores the start values and keeps the trace file open. The FMU state, directional derivatives, input
and output derivatives and the status functions are not supported: they return `fmi2Error` and are traced.
