# Container runtime: values set by the importer go through the cache of the ports

## Context

Today a `fmi*Set` of the container acts at once: on the embedded FMU of the port (one `fmuSet*` per link) or on a
local variable, and the value is also copied in the cache of the port (`container_cache_*`). Three mechanisms then
handle the cases where acting at once is wrong:

1. **pending step** (`step_pending`, `port->deferred`, `container_apply_deferred()`): a step that does not fit the
   communication step is computed later with the inputs of its beginning, so the values set meanwhile are kept and
   applied after it;
2. **structural parameters** (FMI-LS-XCP, `FMU_DEFERS_SET` in the setters, `container_set_fmu_cache(..., structural)`):
   set in Configuration Mode only;
3. **cache set again** (`container_set_fmu_cache()`): before `fmi2SetupExperiment` (the values of the importer prevail
   over the start values) and after the reset of an embedded FMU.

The forwarding code is duplicated in the `FMI_SETTER` macros of `fmi2.c` and `fmi3.c`.

Proposal: `fmi*Set` only writes the cache of the port (it already exists) and marks it; the cache is synchronized
with the FMUs at defined points, by one function.

Vocabulary: the **local variables** (`DECLARE_LOCAL` of `container.h`) convey the values between the embedded FMUs
(links, conversions) and are unchanged; the **cache** (`DECLARE_CACHE`) holds the values set by the importer on the
ports linked to embedded FMUs, and becomes the only way from `fmi*Set` to these FMUs.

## Decisions (2026-11-09)

| # | Question | Decision |
|---|----------|----------|
| 1 | Error of an FMU that refuses a value | Reported by the call that synchronizes (`DoStep`, `ExitInitializationMode`, `Get`...), with a message naming the port of the container and the FMU. `fmi*Set` only fails on an invalid value reference |
| 2 | Read after write (`Get` of an FMU after a `Set` of one of its inputs) | The pending values of the FMU are pushed to it before it is read: same result as today |
| 3 | Scope | All the types that have a cache (numeric, strings, binaries); `fmi3SetClock` stays immediate |
| 4 | Branch | `refactor/container-set-buffer`, from `integration` (after the merge of FMI-LS-XCP) |
| 5 | One `fmuSet*` for several value references (one call per type and per FMU) | No: one call per link, as today (cache and links between FMUs) |
| 6 | `container.txt` | Unchanged (version 9): the cache of each linked port already exists; the state of the links is built when the container is loaded |

Kept from FMI-LS-XCP: the values set by the importer prevail over the start values; structural parameters are set in
Configuration Mode only.

## Design

- **State of each link** of a port (`container_vr_t`, a port fans out to several FMUs): `clean`, `pending` (to push at
  the next synchronization of its FMU), `deferred` (set while a step is pending: becomes `pending` when that step is
  done). A counter of pending links per FMU makes a synchronization without pending value free.
- **`fmi*Set`**: a local variable (`fmu_id < 0`) is written as today (deferred while a step is pending); for a link to
  an FMU, the value goes to the cache and the link becomes `pending` (or `deferred`). No call to the FMU.
- **`container_sync_fmu(container, fmu, what)`**: pushes the `pending` links of the FMU, from the cache: its
  structural parameters in Configuration Mode, its other variables otherwise (a structural parameter set after the
  configuration stays pending until the next one, with a warning). A refused value is an error naming the port.
- **Synchronization points**:
  - `fmu_set_inputs(fmu)`: before each step of the FMU (all the modes, multi-thread included: in the thread of the
    FMU, which only clears its own links), at the exit of the Initialization Mode, at the sub-steps of the ME solver;
  - before a `fmi*Get` forwarded to an FMU (decision 2);
  - Configuration Mode of the FMU (structural parameters);
  - before `fmi2SetupExperiment`, after the early start values; after the start values of Initialization Mode
    (`<RESET>=1`), the values set by the importer on the same variables are set again (they prevail);
  - after the reset of an embedded FMU: all its cached links become `pending`;
  - when a step becomes pending (end of `container_do_step`): every FMU is synchronized, so that the pending step
    uses the inputs of its beginning; when it is done, the `deferred` links become `pending`.
- **Removed**: the forwarding in the `FMI_SETTER` macros, `FMU_DEFERS_SET`, `container_apply_deferred()`,
  `container_set_fmu_cache()`. `container.txt` is unchanged (the cache already exists for each linked port).

Verified while implementing: the worker threads of the multi-thread mode only run `fmuDoStep`, between two barriers;
`fmu_set_inputs`, hence the synchronization, runs in the main thread. In Continuous Time Mode (ME), only the real
values are synchronized (`fmu_set_continuous_inputs`), as the links: the discrete ones wait for the Event Mode.

## Step 0 — Plan

This document.

Commit message:
```
Plan: values set on the container go through the cache of the ports
```

## Step 1 — Cache and synchronization in the runtime

- `container.h` / `container.c` / `fmu.c` / `fmi2.c` / `fmi3.c` as described in **Design**.
- Native tests (`container/tests`): a value set is not seen by the stub before the synchronization; `Get` after `Set`;
  refused value reported by the synchronizing call; structural parameters (the tests of FMI-LS-XCP still pass). A
  value set while a step is pending is covered by `test_communication_step_*` of `tests/integration/test_probe_fmu.py`
  (each internal step uses the last value set before its beginning), the reset of an FMU by the tests of
  `container-reset`.
- Build with `FMUTOOL_SANITIZE` and `FMUTOOL_WARNINGS_AS_ERRORS`.

Commit message:
```
Container runtime: the values set by the importer go through the cache

fmi*Set only writes the cache of the port; the values are pushed to the
embedded FMUs at defined points (step, exit of the initialization, read of
the FMU, Configuration Mode, reset). It replaces the immediate forwarding, the
deferral of the values set while a step is pending, and the deferral of the
structural parameters.
```

## Step 2 — Regression of the FMI calls

- Python tests (`unit`, `integration`, `gui`, `slow`); reference traces of the probe FMU (`tests/data/probe/REF-*.csv`)
  regenerated if the order of the `Set` changes, the differences reviewed (only the place of the `Set`).
- Variable step size scenarios (`container-vr`) checked against their references.

Commit message:
```
Tests: reference traces of the probe FMU with the values set from the cache
```

## Step 3 — Documentation

- Developer: `docs/developer/init-fmi-sequence.md`, `docs/developer/dostep-fmi-sequence.md` (synchronization points),
  `docs/developer/native-runtime.md`.
- User: `docs/user-guide/fmucontainer/container.md` (an error of an embedded FMU on a value set by the importer is
  reported at the next step or read), `container-vr.md` if needed.
- `CHANGELOG.md`.

Commit message:
```
Doc: values set on the container go through the cache of the ports
```

## Step 4 — Cache: values and set of the variables set by the importer

Review of step 1: a synchronization went through all the ports of the container (O(number of ports) per FMU and per
step), and the links had three states. Decided 2026-11-09: two mechanisms only.

- **Local variables** (unchanged): the variables linked between the embedded FMUs, and those of the container
  (`time`, `ts_multiplier`, reset triggers...).
- **Cache**: the state to come, set by the `fmi*Set` of the importer:
  - the values of each port (as before);
  - for each embedded FMU, the **set of its links that got a `fmi*Set`**: a list allocated when the container is
    loaded (one entry per link to this FMU), and a flag on each link (already in the set);
  - the **set of the ports linked to a local variable** that got a `fmi*Set` while a step is pending.
- No `deferred` state: when a step becomes pending, every FMU is synchronized, so everything that enters the cache
  while it is pending is for after it. The sets of the FMUs are not emptied while a step is pending (steps, reads);
  at its end, the local variables of the set of the ports are written. The configuration, the preparation before
  `fmi2SetupExperiment` and the reset of an FMU always synchronize it.
- `container_sync_fmu()` goes through the set of the FMU only, in the order of the calls of the importer; the
  entries kept (structural parameter out of Configuration Mode, discrete value in Continuous Time Mode) stay in it.
  `container_mark_fmu_cache()` (initialization, configuration, reset) still goes through the ports: once per phase.
- Native test: the FMU gets the values in the order of the calls of the importer. Micro-benchmark with many ports,
  before / after this step.
- Developer documentation and review updated.

Commit message:
```
Container runtime: the cache holds the set of the variables set by the importer

Each embedded FMU has the set of its links that got a value from the importer:
a synchronization goes through it only, in the order of the calls, instead of
all the ports of the container. The links lose their deferred state: nothing is
synchronized while a step is pending.
```

## Step 5 — `container_port_t`: interface of the port and its cache

`container_port_t` describes the interface of a port (dimension, links to the FMUs or to local variables: used by
the setters, the getters, the clocks) and holds its cache (offset of its values, number of values set, membership of
the deferred ports). Decided 2026-11-09: the fields of the cache are grouped in a sub-structure `cache`
(`port->cache.offset`, `port->cache.nb`, `port->cache.deferred`), with no change of behaviour. The cache stays
allocated for every linked port (outputs included): knowing the inputs would need a new format of `container.txt`.

Commit message:
```
Container runtime: the fields of the cache of a port in a sub-structure
```

## Review (2026-11-09, after step 4)

Step 2 needed no commit: the whole test suite passed without change after step 1, the reference traces of the probe
FMU included (the scenarios set no value between two synchronizations).

Two mechanisms remain: the **local variables** (links between the FMUs, variables of the container) and the **cache**
(state to come: the values of the ports, the set of the links of each FMU that got a `fmi*Set`, the set of the ports
of local variables set while a step is pending).

### Maintainability

- One way from `fmi*Set` to the embedded FMUs: the places that call `fmuSet*` for a value of the importer go from 10
  (setters of `fmi2.c` and `fmi3.c` for numbers, strings and binaries, `container_apply_deferred()` for 3 kinds,
  `container_set_fmu_cache()` for 2) to 1 (`container_sync_entry()`).
- The setters no longer know the pending step nor the structural parameters: they write the cache, add the port to
  the sets, and write the local variables.
- No state per link but the membership of a set (`in_set`), and the structural flag computed when the container is
  loaded. No `deferred` state: nothing is synchronized while a step is pending.
- The synchronization points are explicit and documented (`docs/developer/dostep-fmi-sequence.md`); the values reach
  an FMU in the order of the calls of the importer.
- Size, against `integration`: +461 / −326 lines in the runtime (`fmi2.c` −28, `fmi3.c` −37, `fmu.c` +10, `fmu.h` −5,
  `container.h` +42, `container.c` +153): the sets (types, allocation, dispatch by type) and their comments.

### Performance

Micro-benchmarks, `-O3`, best of 3, macOS arm64, stub FMU whose `fmi2SetReal` does nothing (the overhead of the
runtime only), per step:

| Loop | `integration` | Steps 1-3 | Step 4 |
|---|---|---|---|
| 1 port: `fmi2DoStep` | 3.3 ns | 3.3 ns | 3.4 ns |
| 1 port: `fmi2SetReal` + `fmi2DoStep` | 6.4 ns | 6.4 ns | 6.1 ns |
| 1 port: `fmi2SetReal` + `fmi2GetReal` + `fmi2DoStep` | 10.0 ns | 10.4 ns | 12.9 ns |
| 1000 ports, none set | 181 ns | 581 ns | 20-33 ns |
| 1000 ports, 1 set | 190 ns | 607 ns | 28-33 ns |
| 1000 ports, 10 set | 227 ns | 664 ns | 78 ns |
| 1000 ports, all set | 3.75 µs | 7.2 µs | 5.6 µs |

- The steps no longer go through all the ports: `integration` went through them at the end of each pending step
  (`container_apply_deferred()`, frequent when the communication points are computed by additions of floats), steps
  1-3 through all their links.
- When the importer sets every port at every step, the cost per value grows by about 1.8 ns (the value is written in
  the cache, then set from it, instead of being set at once): negligible against the `fmi*Set` of a real FMU.
- A read after a write costs a synchronization (about 3 ns).
- A value set several times between two steps reaches the FMU once.

### Test suite

- Native tests: 3 new (`cache_read_after_write`, `cache_refused_value`, `cache_order_of_the_calls`), 1 adjusted
  (`xcp_fmi2_before_setup`: the value set by the importer reaches the FMU once, before `fmi2SetupExperiment`, instead of
  twice). The fixture `xcp_fmi2` exposes `XCP.TCP.Enable` and `XCP.TCP.ListenAddress` too.
- Python tests: unchanged, all passing (2685, `slow` and GUI included); reference traces of the probe FMU unchanged.
- The deferral of a value set while a step is pending is covered by `test_communication_step_*` of
  `tests/integration/test_probe_fmu.py` only (`slow`: fmpy and a C compiler); no native test of it.
