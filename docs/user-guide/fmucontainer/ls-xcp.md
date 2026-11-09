# Container with LS-XCP enabled FMUs

[FMI-LS-XCP](https://fmi-standard.org/fmi-ls-xcp/1.0.0) describes how an FMU gives access to its internal variables to
a measurement and calibration tool (MCD tool, XCP master): the FMU declares in its manifest
`extra/org.fmi-standard.fmi-ls-xcp/fmi-ls-manifest.xml` one or more **interfaces**, each one with an A2L file. An
interface either runs its own XCP slave in the FMU (`containsXCPService`), listening on a TCP and/or UDP port, or
allows an external XCP slave to access the memory of the FMU (`supportsDirectMemoryAccess`).

Inside a container, the container is the importer of its embedded FMUs: `fmucontainer` **forwards the XCP services of
the embedded FMUs**. The MCD tool connects to each of them, with the A2L files given by the container.

## What is supported

| Topic | Support |
|---|---|
| Version | FMI-LS-XCP 1.0.0, embedded FMUs FMI 2.0 and 3.0, containers FMI 2.0 and 3.0 |
| XCP service in the FMU (`containsXCPService`) | Forwarded: declared by the container, A2L files copied, configuration exposed |
| Direct memory access only (`supportsDirectMemoryAccess`) | Not forwarded, with a warning: the container provides no XCP slave, and the addresses of the A2L file are relative to the binary of the FMU |
| Several services | One per interface of each embedded FMU: the MCD tool connects to each of them |
| Port conflicts | Two services on the same port of the same protocol are refused when the container is built |

## What the container does

For each forwarded interface, the container:

1. declares an `Interface` in its own manifest, with the definition `<fmu id>/<definition>` (the `<fmu id>` is the name
   of the embedded FMU, without `.fmu`, in lowercase);
2. copies the A2L files in `extra/org.fmi-standard.fmi-ls-xcp/<platform>/<fmu id>/`, for the platforms of the
   container;
3. **exposes the variables that configure the service** (roles `XCPServiceTCPEnable`, `XCPServiceTCPPort`,
   `XCPServiceTCPListenAddress` and their UDP counterparts), as `<fmu id>.<variable>`, whatever the `auto_*`
   options. The importer of the container can then enable or disable each service and choose its port and its listen
   address.

A variable already used by a rule of the description (for instance exposed under another name) keeps that rule: the
manifest of the container refers to the name it is exposed with.

Some variables are not exposed (they keep their start value, or the one given in the description):

- the variables that only **announce** the configuration (`constant` output, `calculatedParameter`): the importer
  cannot change it;
- the variables whose type the container cannot expose for their role: an FMI 3.0 `UInt16` port or `Boolean` in an
  FMI 2.0 container, an FMI 2.0 `Integer` port in an FMI 3.0 container (it would be an `Int32`, FMI-LS-XCP needs a
  `UInt16`). A warning is issued.

## Ports

Each XCP service listens on a port, which must be unique on the machine. When the container is built, the port of
each enabled service is, by priority:

1. the start value of its variable given in the description (`start` block of a JSON file);
2. the start value of its variable in the embedded FMU;
3. the port of the `IF_DATA XCP` of its A2L file.

Two services that use the **same port of the same protocol** are refused, whatever their listen addresses. This is the
case of an FMU embedded several times: set another port for one of its instances.

```json
{
  "name": "two_ecus.fmu",
  "fmu": ["ecu.fmu", "ecu-1.fmu"],
  "path": {"ecu-1.fmu": "ecu.fmu"},
  "start": [["ecu-1.fmu", "XCP.TCP.Port", "5556"]]
}
```

A service disabled by its `Enable` variable is not checked. When the port of a service is unknown, a warning is
issued.

!!! note
    The ports are checked with the values known when the container is built. The importer of the container may change
    them through the exposed variables: it is then responsible for their consistency, and for the port written in the
    A2L files given to the MCD tool, as FMI-LS-XCP requires.

## Configuration Mode

An FMI 3.0 FMU usually declares its configuration variables as **structural parameters**: they can only be set in
*Configuration Mode*, and the FMU starts its XCP service when it leaves it. The container handles it:

- an **FMI 3.0 container** exposes them as structural parameters. When its importer puts it in *Configuration Mode*,
  the container puts these FMUs in *Configuration Mode* too, and forwards the values;
- otherwise (**FMI 2.0 container**, where they are exposed as parameters, or importer that does not use the
  *Configuration Mode*), the container configures these FMUs itself before their initialization, with the values set
  by its importer.

An FMI 2.0 FMU starts its XCP service in `fmi2SetupExperiment`: the container sets its parameters, and the values set
by its importer, before calling it.

## Checking an FMU

`fmutool -check` checks the rules of FMI-LS-XCP of an FMU, see [FMU Checker](../fmutool/checker.md). A container built
by `fmucontainer` follows them too.
