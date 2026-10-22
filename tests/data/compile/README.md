# Reference FMUs with sources

`BouncingBall.fmu` of the [Reference FMUs](https://github.com/modelica/Reference-FMUs) of the Modelica
Association Project "FMI", release [v0.0.41](https://github.com/modelica/Reference-FMUs/releases/tag/v0.0.41)
(`Reference-FMUs.zip`), unmodified: `2.0/BouncingBall.fmu` (FMI 2.0, `<SourceFiles>` with `all.c`) and
`3.0/BouncingBall.fmu` (FMI 3.0, `sources/buildDescription.xml`). See `LICENSE.txt` (2-Clause BSD).

Neither FMU ships the FMI headers in `sources/`, and both prefix the FMI functions with the model identifier
unless `DISABLE_PREFIX` is defined: they exercise the include path of the FMI headers and the prefix handling of
the compilation.

They are used by `tests/unit/test_compiler.py` and `tests/integration/test_compile_sources.py`. The tests remove
`binaries/` (or other parts) from a copy of these FMUs at run time.

`REF-BouncingBall.csv` holds `time`, `h` and `v` of `3.0/BouncingBall.fmu` simulated by fmpy 0.3.32 with its
original `aarch64-darwin` binary (`stop_time=3`, `output_interval=0.01`).

`Feedthrough.fmu` comes from the same release, unmodified: `2.0/Feedthrough.fmu` and `3.0/Feedthrough.fmu`. Its inputs
and outputs of every type feed through without states. It is used by `tests/integration/test_container_perf.py` and
`tools/bench_container.py` (`docs/local/container_perf.md`): the FMI-3.0 one with its binaries (every platform), the
FMI-2.0 one compiled for the host (its macOS binary is built for `x86_64` only).
