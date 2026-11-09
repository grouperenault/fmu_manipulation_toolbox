# FMI-LS-XCP support

## Context

[FMI-LS-XCP 1.0.0](https://fmi-standard.org/fmi-ls-xcp/1.0.0) describes how an FMU gives access to its internal
variables to an MCD tool (XCP master) with A2L files:

- the manifest `extra/org.fmi-standard.fmi-ls-xcp/fmi-ls-manifest.xml` holds one or more `Interface` elements, each
  one with an A2L file (`definition`, relative URI resolved in `extra/org.fmi-standard.fmi-ls-xcp/` for a source code
  FMU, in `extra/org.fmi-standard.fmi-ls-xcp/<platform>/` for a binary FMU, the platform being named as in
  `binaries/`);
- `containsXCPService="true"`: the FMU implements its own XCP slave, listening on a TCP and/or UDP port;
- `supportsDirectMemoryAccess="true"`: the A2L holds addresses relative to the base of the FMU binary, the importer
  provides the XCP slave;
- `Variable` elements give a role to variables of the FMU: `XCPService{TCP|UDP}{Enable|Port|ListenAddress}`
  (Boolean, UInt16/Integer, String), scalars, declared as fixed `structuralParameter` (FMI 3.0, set in Configuration
  Mode; the service starts at `fmi3ExitConfigurationMode`, or at `fmi3EnterInitializationMode` at the latest), fixed
  `parameter` (the service starts at `fmi2SetupExperiment` / `fmi3EnterInitializationMode`), `constant` output or
  `calculatedParameter` (configuration only announced, not changeable);
- without a variable for a role, the value is the one of the `IF_DATA XCP` of the A2L (port, address), or `true`
  for `Enable`;
- the importer must check that the ports do not collide, and keep the port of the FMU configuration consistent with
  the A2L given to the MCD tool;
- the `/include` mechanism of A2L is forbidden.

Inside a container, the container is the importer of the embedded FMUs. No public FMU implements LS-XCP (checked
2026-11-09: `modelica/fmi-ls-xcp` only holds the specification, the XSD and an example manifest; nothing in
`modelica/Reference-FMUs`, `fmi-ls-bus-examples`, `fmi-ls-ref`).

The runtime does not support the Configuration Mode: `fmi3EnterConfigurationMode` / `fmi3ExitConfigurationMode` of
the container only change its state (`container/fmi3.c`), and are not forwarded to the embedded FMUs. FMI 3.0 forbids
calling `fmi3EnterConfigurationMode` on an FMU without structural parameter (`2_3_common_states.adoc`): the runtime
must know which FMU to put in Configuration Mode, and it only reads `container.txt`.

## Decisions (2026-11-09)

| # | Question | Decision |
|---|----------|----------|
| 1 | Approach | **Passthrough**: the container forwards the XCP services of the embedded FMUs (one `Interface` per forwarded interface in the manifest of the container, A2L copied, role variables exposed). No XCP slave in the container runtime (aggregation discarded for now) |
| 2 | `container.txt` | Format version 9, minimal change: a flag `<has_configuration_mode>` per embedded FMU (section 4), and the value `<RESET>=2` for the start values applied in Configuration Mode (section 7.2) |
| 3 | Port conflict between embedded FMUs | Error at build time (`FMUContainerError`), naming the FMUs, the protocol and the port |
| 4 | Exposure of the role variables | Automatic, named `<fmu id>.<variable>` (convention of `auto_parameter`), declared in the manifest of the container |
| 5 | FMI versions | FMI 2.0 and FMI 3.0, for the embedded FMUs and for the container |
| 6 | Interface with `supportsDirectMemoryAccess` only | Warning, not forwarded to the container |
| 7 | Port of an interface without role variable | Read from the `IF_DATA XCP` of the A2L (`XCP_ON_TCP_IP` / `XCP_ON_UDP_IP`), minimal reader, no full A2L parser |
| 8 | Checker | An LS-XCP checker for `fmutool -check`, in this plan |
| 9 | Test FMUs | A C stub FMU, FMI 2.0 and 3.0, without real XCP service: it logs the configuration it receives and when it "starts" its service |
| 10 | Test FMUs of the Python tests | `.fmu` archives without binaries (descriptor, manifest, A2L) in `tests/data/ls-xcp/`: enough to build a container. The runtime sequence is checked by the native tests only, with the stub FMU built by CMake |
| 11 | Port conflict | Same protocol and same port, whatever the listen addresses (`0.0.0.0` overlaps every address) |
| 12 | `<has_configuration_mode>` | On the Co-Simulation and the Model-Exchange lines of section 4 |
| 13 | FMI 2.0: start values applied after `fmi2SetupExperiment`, where an FMU of LS-XCP starts its service | The early start values are applied **before** `fmi2SetupExperiment`, for all the embedded FMUs (allowed in the state Instantiated of FMI 2.0). Decided 2026-11-09, step 4 |
| 14 | Where the role variables are exposed | In `add_implicit_rule`, always (whatever the `auto_*` options): the assembly records them as its other automatic rules (JSON dump, SSP export, GUI) |
| 15 | Role variable of a type the container cannot expose for its role (FMI-3.0 `UInt16`/`Boolean` in an FMI-2.0 container; FMI-2.0 `Integer` port in an FMI-3.0 container, which would be an `Int32` instead of the `UInt16` of the role) | Warning, not exposed: its value is its start value |
| 16 | Read-only role variables (`constant` output, `calculatedParameter`) | Not exposed (information message): used by the port check only; the manifest of the container has no `Variable` for them |

## Step 0 — Plan

This document.

Commit message:
```
Plan: FMI-LS-XCP support
```

## Step 1 — Reading of the LS-XCP manifest and of the A2L

- `fmu_manipulation_toolbox/ls.py`: `LayeredStandard` detects LS-XCP besides LS-BUS (`standards` lists
  `"LS-XCP"`). New dataclasses `XcpInterface` (`definition`, `types`, `description`, `contains_xcp_service`,
  `supports_direct_memory_access`, `variables: dict[role, name]`) and a reader of the manifest.
- Resolution of the A2L of an interface: source code (manifest directory) or per platform
  (`<platform>/<definition>`); the list of the platforms that have it.
- Minimal reader of `IF_DATA XCP`: for `XCP_ON_TCP_IP` and `XCP_ON_UDP_IP`, the port and the address (`ADDRESS` /
  `HOST_NAME`). Comments (`/* */`, `//`) skipped. Returns `None` for what is missing.
- Unit tests with fabricated manifests and A2L (`tests/data/ls-xcp/`).

Commit message:
```
LS-XCP: read the manifest and the XCP settings of the A2L files
```

## Step 2 — Checker `OperationLsXcpCheck`

- The XSD of LS-XCP (`fmi3LayeredStandardXcpManifest.xsd`, 2-Clause BSD) is shipped in
  `fmu_manipulation_toolbox/resources/fmi-ls-xcp/` with its license.
- Checks, each violation logged as an error (model of `OperationLsBusCheck`):
  - manifest valid against the XSD, `fmi-ls-name` and `fmi-ls-version`;
  - `definition`: relative URI without dot segment; A2L present in the root (source code) or for at least one
    platform of `binaries/`; no `/include` in the A2L;
  - at least one of `containsXCPService` / `supportsDirectMemoryAccess` is `true`;
  - `types`: interface types the FMU provides;
  - `Variable`: the variable exists; a variable in one entry only; a role once per `Interface`; scalar; type of the
    role (Boolean, UInt16 or Integer, String); causality/variability among the four combinations of the
    specification (`structuralParameter` only in FMI 3.0);
  - roles without `containsXCPService`: warning (they have no meaning).
- Registered in `get_checkers()`; unit tests.

Commit message:
```
Checker: rules of FMI-LS-XCP

fmutool -check validates the manifest of FMI-LS-XCP against its XSD, the A2L
files of the interfaces and the role of the variables.
```

## Step 3 — Stub FMUs of the tests

- `container/tests/stub_xcp_fmi2.c` and `container/tests/stub_xcp_fmi3.c`, with the journal of their XCP service in
  `container/tests/stub_xcp.h`; their descriptors, manifest and A2L are those of `tests/data/ls-xcp/stub_xcp_fmi<2|3>`
  (created at step 2 for the checker). Role variables `XCP.TCP.Enable`, `XCP.TCP.Port`, `XCP.TCP.ListenAddress`
  (`parameter` in FMI 2.0, `structuralParameter` in FMI 3.0). The stub journals in `<resources>/xcp.log` the received
  configuration, the refused sets (FMI 2.0: after the start of its service; FMI 3.0: outside of Configuration Mode)
  and when its service starts (`fmi2SetupExperiment`, `fmi3ExitConfigurationMode` or `fmi3EnterInitializationMode`).
- Built by `container/CMakeLists.txt` with the native tests; `test_stub_xcp.c` calls them directly.

Commit message:
```
Tests: stub FMUs implementing FMI-LS-XCP
```

## Step 4 — `container.txt` version 9 and Configuration Mode in the runtime

- Format: `<has_configuration_mode>` (section 4, CS and ME lines), `<RESET>=2` (section 7.2).
  `CONTAINER_TXT_VERSION` = 9 in `types.py` and `container.h`. `split.py` reads version 9.
- Writer (`txt.py`): flag of the FMU when it has a fixed or tunable structural parameter exposed or with a start
  value; every exposed structural parameter gets a start value line `<RESET>=2` (its start value by default), so
  that the runtime knows the list of the structural parameters.
- Runtime (`container.c`, `fmi3.c`, `fmi2.c`):
  - `fmi3EnterConfigurationMode` / `fmi3ExitConfigurationMode` of the container forwarded to the flagged FMUs;
    the `<RESET>=2` start values applied after their `fmi3EnterConfigurationMode`;
  - a `Set` on a container port linked to a structural parameter, while the FMU is not in Configuration Mode, is
    cached (existing cache) instead of forwarded;
  - if the importer did not use the Configuration Mode (FMI 2.0 container, or FMI 3.0 importer that skipped it):
    before the early start values, each flagged FMU goes through `fmi3EnterConfigurationMode`, `<RESET>=2` start
    values, cached values, `fmi3ExitConfigurationMode`.
  - decision 13: before `fmi2SetupExperiment` of each FMU, its configuration (if not done), its early start values,
    then the values set by the importer (cache of the container), which prevail over the start values (before, an
    early start value overwrote a value set by the importer before `fmi2SetupExperiment`). The reset of an embedded
    FMU follows the same sequence. The reference traces of the probe FMU (`tests/data/probe/REF-*.csv`) are
    regenerated for this order.
- Native tests with the stub FMUs (fixtures `xcp_fmi2`, `xcp_fmi3`: call sequence, values received); Python tests of
  the writer; the REF `container.txt` of the tests in version 9.
- Developer docs: `docs/developer/container-txt-format.md` (version 9), `docs/developer/init-fmi-sequence.md`
  (Configuration Mode).

Commit message:
```
Container runtime: forward the Configuration Mode to the embedded FMUs

container.txt version 9: a flag per embedded FMU that has structural
parameters, and the start values applied in Configuration Mode (RESET=2). A
structural parameter set outside of Configuration Mode is cached and applied
in it.
```

## Step 5 — Builder: forwarding of the XCP services

- `LayeredStandard` records, when the FMU is analysed, the A2L files of each interface (paths in the archive) and the
  `IF_DATA XCP` of the first one: the temporary directory of an embedded FMU is removed once it is analysed. The A2L
  files are copied from the archive of the FMU.
- `fmu_manipulation_toolbox/container/xcp.py`:
  - interfaces forwarded: `containsXCPService="true"`, applicable to the interface type under which the FMU is
    embedded (CS or ME). `supportsDirectMemoryAccess` only: warning, not forwarded; in a forwarded interface,
    `supportsDirectMemoryAccess` is not written (the addresses are relative to the binary of the FMU);
  - role variables exposed by `add_implicit_rule` as `<fmu id>.<variable>` (decisions 14 to 16);
  - manifest of the container: one `Interface` per forwarded interface, `definition="<fmu id>/<definition>"`,
    `containsXCPService="true"`, `Variable` with the names exposed on the container (also those exposed by a rule of
    the user). A2L copied in `extra/org.fmi-standard.fmi-ls-xcp/<platform of the container>/<fmu id>/` (platform
    names mapped by OS, `PLATFORM_OS` of `embedded.py`), or at the root for a source code FMU;
  - port check: each enabled service on each protocol it uses (role variables, or a block of the `IF_DATA XCP`),
    port = value given in the description > start value of the role variable > `IF_DATA XCP`; conflict according to
    decision 11 → `FMUContainerError`; port unknown → warning. Covers several instances of the same FMU.
- `add_input` accepts a scalar `structuralParameter` that gives no dimension; it is exposed as `structuralParameter`
  (FMI-3.0 container) or `parameter` (FMI-2.0 container), with a start value `<RESET>=2` by default.
- SSP: the system connector of an exposed structural parameter is a `structuralParameter`; the reader accepts it.
- Python tests: containers built from the test FMUs (manifest, A2L, exposed variables, conflicts, FMI 2.0 / 3.0
  containers, checker on the container, SSP round trip).

Commit message:
```
Container: forward the XCP services of the embedded FMUs (FMI-LS-XCP)

The interfaces of the embedded FMUs with an XCP service are declared in the
manifest of the container, their A2L files copied, and their configuration
variables exposed. A port used by two services is refused at build time.
```

## Step 6 — Documentation

- `docs/user-guide/fmucontainer/ls-xcp.md` (new, in the `mkdocs.yml` navigation next to LS-BUS): what is
  forwarded, naming, port conflicts, Configuration Mode, limits (no direct memory access, no XCP slave in the
  container).
- `docs/user-guide/fmutool/checker.md`: the LS-XCP checker.
- `docs/user-guide/fmucontainer/container.md`: link to the LS-XCP page.
- `CHANGELOG.md`, `README.md` (list of the supported layered standards), `docs/local/ROADMAP.md`.

Commit message:
```
Doc: FMI-LS-XCP support of the container and of the checker
```
