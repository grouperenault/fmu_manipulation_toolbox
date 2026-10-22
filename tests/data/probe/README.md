# Reference traces of the probe FMU

`REF-<scenario>-<instance>.csv`: traces of the probes (`tools/probe_fmu`) for the container scenarios S1 to S5
(`tools/probe_fmu/scenarios/S*.json`), written by the current container runtime, without the `wall` column. They are
compared by `tests/integration/test_probe_fmu.py` (regression of the FMI calls of the runtime). Regenerate them after
an intended change of the runtime or of the probe (see the test).
