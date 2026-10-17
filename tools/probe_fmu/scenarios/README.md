# Comparison scenarios

Scenarios of the importer comparison study (`docs/local/done/importer_comparison.md`, section *Study scenarios*): the
same assemblies of probe FMUs (`tools/probe_fmu`) are run as FMU Containers and as Simulink models, and the
traces written by the probes are compared.

| Scenario | Instances | Purpose |
|---|---|---|
| S1 | `A` = Probe10ms | call sequence of the importer |
| S2 | `A` = Probe10ms | start values |
| S3 | `A`, `B`, `C` = Probe10ms | propagation of the links during the initialization |
| S4a, S4b | `A` = Probe10ms, `B` = Probe20ms, `C` = Probe50ms | three rates |
| S4c, S4d | as S4a, one sub-container per rate (parent at 0.01 s / at its default step) | three rates, container side only (compared with S4s, S4m) |
| S5j, S5s, S5r | `A`, `B`, `C` = Probe10ms | feedthrough, ordering |
| S6s, S6m | `A`, `B`, `C` = Probe10ms | computation time |

## FMU Container side

```bash
python tools/probe_fmu/scenarios/run_container.py -output tmp/importer_comparison          # every scenario
python tools/probe_fmu/scenarios/run_container.py -output tmp/importer_comparison S3 S4a   # some of them
```

The results are not versioned (`tmp/importer_comparison/`, outside of git). For each scenario `<S>`,
`<output>/<S>/container/` holds the traces `A.csv`, `B.csv`, `C.csv`, the outputs of the
container `results.csv`, the log `log.txt` and the wall time `wall.txt`.

## Simulink side (MATLAB R2024b)

### Preparation

1. Compile the three probes on the MATLAB machine (MSVC on Windows):

   ```bash
   fmutool -input Probe10ms.fmu -compile-sources -output Probe10ms-host.fmu
   fmutool -input Probe20ms.fmu -compile-sources -output Probe20ms-host.fmu
   fmutool -input Probe50ms.fmu -compile-sources -output Probe50ms-host.fmu
   ```

2. Build and run the models with the scripts of `simulink/` (MATLAB, folder `tools/probe_fmu/scenarios/simulink`
   on the path):

   ```matlab
   addpath('<repository>/tools/probe_fmu/scenarios/simulink')
   build_scenarios('<folder of the -host.fmu>', '<output>')   % or build_scenarios(..., {'S1', 'S3'})
   run_scenarios('<output>')                                    % or run_scenarios('<output>', {'S1'})
   ```

   - The FMU block only accepts an FMU file name on the MATLAB path (no path): `build_scenarios` adds the folder of
     the `-host.fmu` to the path and records it in `<output>/probe_dir.txt`, read again by `run_scenarios`.
   - `build_scenarios` saves `<output>/<S>/simulink/<S>.slx` and lists in `build_issues.txt` (also printed) the
     calls that failed and the settings to make by hand (input start values of S2 and S3).
   - `run_scenarios` simulates each model with `<output>/<S>/simulink/` as current folder (the probes write their
     traces `A.csv`... in the current directory) and writes there `log.txt` (messages and warnings),
     `wall.txt` (wall time) and `results.csv` (outputs: `name,time,value`); `<output>/version.txt` holds the MATLAB
     version and platform. A failed simulation is reported `FAILED`, without `wall.txt` nor `results.csv`.
   - The Simulink names that MathWorks does not document (library path of the FMU block, order of the `Flat` ports,
     parameter values with `set_param`) are gathered in `probe_simulink_api.m` and marked `UNVERIFIED`: correct
     them there if needed. Each line of a model is named `<from>.<output> -> <to>.<input>`: check on the first
     models that it joins the ports of these names.
   - The scenarios are defined in `probe_scenarios.m` (same content as the table below).

   The tables below describe the models, for a check or a manual build.

### Common settings

| Setting | Value |
|---|---|
| Blocks | one **FMU** block (*Simulink Extras / FMU Import*) per instance, named `A`, `B`, `C`, on the `-host.fmu` of the table of the scenario |
| FMU block mode | Co-Simulation (the probes have no Model Exchange interface) |
| FMU block sample time (`FMUSampleTime`) | step size of the probe: 0.01 (Probe10ms), 0.02 (Probe20ms), 0.05 (Probe50ms) |
| FMU block parameters | `trace_file` = `'A.csv'` on `A`, `'B.csv'` on `B`, `'C.csv'` on `C`; the other parameters as given by the scenario, default otherwise |
| Unconnected inputs | left unconnected (Simulink feeds them with 0 and may warn: keep the warning in the log) |
| Unconnected outputs | one root `Outport` each, named `<block>.<output>` (as `auto_output` in the container); without a destination the FMU blocks are removed by the block reduction and nothing is simulated |
| Solver | *Fixed-step*, *discrete (no continuous states)* (`FixedStepDiscrete`), fixed step size 0.01 |
| Tasking mode | single-tasking ("Treat each discrete rate as a separate task" **off**), unless the scenario says multi-tasking |
| Block reduction | off (`BlockReduction`); outputs saved (`SaveOutput`, `yout`, `Dataset`) |
| Stop time | 0.2 s (S6: 1 s) |

The block parameters are those of the dialog of the FMU block (parameters tab). The programmatic names of some of
them (parameter values, input start values) are not documented by MathWorks: set them in the dialog.

### Scenarios

| Scenario | Blocks | Lines (`from → to`) | Block parameters | Settings |
|---|---|---|---|---|
| **S1** | `A` Probe10ms | none | `trace_file` only | common |
| **S2** | `A` Probe10ms | none | `p_real` = 3, `p_tunable` = 0.5, `compute_time` = 0; **input start values** if the dialog offers them: `u_cont` = 2, `u_disc` = 4, `u_int` = 7, `u_bool` = true | common; note where (and whether) the input start values can be given |
| **S3** | `A`, `B`, `C` Probe10ms | `A.y_init → B.u_cont`, `B.y_cont → C.u_cont` | `A`: `p_real` = 3, `u_cont` start = 2 (if possible, see S2); `C`: `p_real` = 2 | common |
| **S4s** | `A` Probe10ms, `B` Probe20ms, `C` Probe50ms | `A.y_time → B.u_cont`, `A.y_int → B.u_int`, `B.y_time → C.u_cont`, `C.y_time → A.u_disc`, `C.y_int → A.u_int` | none | single-tasking (no *Rate Transition* block); keep the rate transition warnings in the log |
| **S4m** | as S4s | as S4s | none | **multi-tasking** ("Treat each discrete rate as a separate task" on); a *Rate Transition* block on each line between different rates, with "Ensure deterministic data transfer" off when the rates are not integer multiples (`B → C`: 0.02 s / 0.05 s) |
| **S5** | `A`, `B`, `C` Probe10ms | `A.y_time → B.u_cont`, `B.y_cont → C.u_cont`, `A.y_time → B.u_disc`, `B.y_disc → C.u_disc` | none | common |
| **S6s** | `A`, `B`, `C` Probe10ms | none | `compute_time` = 0.005, `compute_sleep` = false on each | single-tasking, stop time 1 s |
| **S6m** | as S6s | none | as S6s | multi-tasking, stop time 1 s |

For S6, measure the wall time of the simulation: `tic; sim('S6s'); toc`, and write it in `wall.txt`.

### What to share

For each scenario, the folder `<output>/<S>/simulink/` with:

- the traces `A.csv`, `B.csv`, `C.csv`;
- the model `<S>.slx`;
- the messages of the simulation (Diagnostic Viewer, copied in `log.txt`), including the warnings;
- `wall.txt` for S6;
- `build_issues.txt`, and any deviation from the settings above (e.g. a name corrected in
  `probe_simulink_api.m`, a parameter that could not be set).

Also give the MATLAB version (`ver`) and the platform.
