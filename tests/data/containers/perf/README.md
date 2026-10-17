# Reference results of the performance work on the container runtime

`REF-results-*.csv` hold the outputs of the containers built by `tests/integration/test_container_perf.py`,
simulated by fmpy (`stop_time=0.05`, `output_interval=0.001`), written with every digit (`%.17g`). They were made
with the runtime **before** the changes of `docs/local/container_perf.md` (grouped FMI calls, targeted coupling of
the Model-Exchange solver): these changes must give the same results, bit for bit.

The FMUs come from `tests/data/compile` (`Feedthrough.fmu`, Reference FMUs v0.0.41) and
`tests/data/containers/VanDerPol`, copied at run time.
