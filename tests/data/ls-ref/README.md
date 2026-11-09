# FMI-LS-REF test data

- `fmi-ls-manifest.xml`, `smoke.xml`: manifest and experiment file read by `tests/unit/test_ls_ref.py`.
- `bouncingball/`, `feedthrough/`: LS-REF files that `tests/_helpers/ls_ref.py` puts in a copy of the Reference-FMUs
  of `tests/data/compile` (their `resources/` directory goes to the `resources/` of the FMU, the other files to
  `extra/org.fmi-standard.fmi-ls-ref/`); the FMU is compiled for the host platform.
  - BouncingBall: experiment `Default` compared with `tests/data/compile/REF-BouncingBall.csv`, experiment
    `Restitution 0.5` (parameter set `resources/params.ssv`, `e = 0.5`) compared with `REF-e05.csv`.
    `REF-e05.csv` holds `time`, `h` and `v` of `tests/data/compile/3.0/BouncingBall.fmu` simulated by fmpy 0.3.32 with
    its original `aarch64-darwin` binary (`stop_time=3`, `output_interval=0.01`, `start_values={"e": 0.5}`).
  - Feedthrough: stimuli on three inputs (`in.csv`: a continuous real interpolated linearly, an integer and a boolean
    held), and the expected outputs (`ref.csv`).
