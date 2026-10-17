# Reference results of the performance work on the container runtime

`REF-results-*.csv` hold the outputs of the containers built by `tests/integration/test_container_perf.py`,
simulated by fmpy (`stop_time=0.05`, `output_interval=0.001`), written with every digit (`%.17g`). They were made on
macOS (Apple silicon) with the runtime **before** the changes of `docs/local/done/container_perf.md` (targeted
coupling of the Model-Exchange solver): these changes give the same results, bit for bit on one machine. The tests
compare them within a tolerance (`1e-12`, relative and absolute): the embedded FMUs run their own binaries on each
platform, whose results may differ in the last digit.

The FMUs come from `tests/data/compile` (`Feedthrough.fmu`, Reference FMUs v0.0.41) and
`tests/data/containers/VanDerPol`, copied at run time.
