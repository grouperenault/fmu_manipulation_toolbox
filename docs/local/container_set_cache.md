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
