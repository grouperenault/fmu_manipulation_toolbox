# Command Line Interface (CLI) Usage Guide

The command line offers complete and precise control over FMU Manipulation Toolbox, ideal for automation and batch processing.

## Available Commands

FMU Manipulation Toolbox provides four main commands:

| Command        | Usage                                        |
|----------------|----------------------------------------------|
| `fmutool`      | FMU analysis and manipulation                |
| `fmucontainer` | FMU container creation                       |
| `fmusplit`     | Extract FMUs from a container                |
| `datalog2pcap` | Convert LS-BUS datalog CSV to PCAPNG (experimental) |

For AI agents, `fmutool-mcp` serves the tools of the [AI assistant](../fmucontainer/ai-assistant.md) to an MCP
client, and `fmutool-agent` offers the same tools as a JSON command line (see [Agent skills](../agent-skills.md)).

## fmutool: Main Command

### Basic Syntax

```bash
fmutool -input <file.fmu> [options]
```

### Required Options

```bash
-input path/to/module.fmu
```

The FMU to analyze or modify.

### Save Options

```bash
-output path/to/module-modified.fmu
```

⚠️ **Important:** Without this option, no modifications are saved!

### Debug Option

```bash
-debug
```

Logs the details of the operations (`DEBUG` lines), e.g. the command lines of the compiler and of the linker with
`-compile-sources`.

## Analysis Operations

### Display FMU Summary

```bash
fmutool -input module.fmu -summary
```

**Output:**
```
FMU Information:
  Name: module
  FMI Version: 2.0
  GUID: {abc-123-def}
  Number of variables: 42
  Number of parameters: 5
  Number of inputs: 10
  Number of outputs: 15
```

### Check FMI Compliance

```bash
fmutool -input module.fmu -check
```

Two built-in checkers are run, followed by the custom ones (see [FMU Checker](checker.md)):

- the **XSD schema** of the FMI version (every violation is reported, not only the first one);
- the **semantic rules** that the schema cannot express: unique names and value references, allowed
  `causality`/`variability`/`initial` combinations, presence of `start` values, references between
  variables and in `<ModelStructure>`.

Each violation is logged as an error. If any checker logs an error, `fmutool` exits with status `7`,
after having performed the other requested actions (e.g. `-output`), so that `-check` can be used in CI.

The replay of the experiments of [FMI-LS-REF](checker.md#validation-of-the-results-fmi-ls-ref) has settings:

| Option | Meaning | Default |
|--------|---------|---------|
| `-ref-rtol` | relative tolerance of the comparison with the references, `>= 0` | `1e-3` |
| `-ref-atol` | absolute tolerance of the comparison with the references, `>= 0` | `1e-6` |
| `-ref-timeout` | time limit of the simulation of each experiment, in seconds, `> 0` | `60` |

```bash
fmutool -input module.fmu -check -ref-rtol 1e-2 -ref-timeout 300
```

They need `-check`. Without it, or with a value out of its range, `fmutool` exits with status `2`.

### List All Ports in CSV

```bash
fmutool -input module.fmu -dump-csv ports_list.csv
```

**Generated CSV content:**
```csv
name;newName;valueReference;causality;variability
Motor.Speed;Motor.Speed;0;input;continuous
Motor.Torque;Motor.Torque;1;output;continuous
Controller.Kp;Controller.Kp;2;parameter;fixed
```

## Modification Operations

### Remove Top-Level Hierarchy

**Before:**
```
System.Motor.Speed
System.Controller.Gain
```

**Command:**
```bash
fmutool -input module.fmu -remove-toplevel -output module-flat.fmu
```

**After:**
```
Motor.Speed
Controller.Gain
```

### Merge First Level

**Before:**
```
System.Motor.Speed
System.Controller.Gain
```

**Command:**
```bash
fmutool -input module.fmu -merge-toplevel -output module-merged.fmu
```

**After:**
```
System_Motor.Speed
System_Controller.Gain
```

### Remove Prefix

**Before:**
```
_internal_Motor_Speed
_internal_Controller_Gain
```

**Command:**
```bash
fmutool -input module.fmu -trim-until _ -output module-trimmed.fmu
```

**After:**
```
internal_Motor_Speed
internal_Controller_Gain
```

### Rename from CSV File

**Step 1: Create CSV**
```bash
fmutool -input module.fmu -dump-csv renaming.csv
```

**Step 2: Edit CSV**

Edit `renaming.csv`:
```csv
name;newName;valueReference;causality;variability
Motor.Speed;Engine.Velocity;0;input;continuous
Motor.Torque;Engine.Force;1;output;continuous
```

**Step 3: Apply modifications**
```bash
fmutool -input module.fmu -rename-from-csv renaming.csv -output module-renamed.fmu
```

**Tip:** Leaving `newName` empty removes the port!

## Filtering Operations

### Filter by Regular Expression

**Keep only matching ports:**
```bash
fmutool -input module.fmu -keep-only-regexp "^Motor\..*" -output module-motor.fmu
```

**Remove matching ports:**
```bash
fmutool -input module.fmu -remove-regexp "^Internal\..*" -output module-clean.fmu
```

### Regular Expression Examples

```bash
# Keep everything starting with "Motor."
-keep-only-regexp "^Motor\..*"

# Remove everything containing "debug"
-remove-regexp ".*debug.*"

# Keep ports ending with "Temperature"
-keep-only-regexp ".*Temperature$"

# Remove ports starting with underscore
-remove-regexp "^_.*"
```

### Remove All Ports

```bash
fmutool -input module.fmu -remove-all -output module-empty.fmu
```

⚠️ **Warning:** This removes ALL ports! Use with filters.

## Filter by Port Type

### Operations on Parameters Only

**List only parameters:**
```bash
fmutool -input module.fmu -only-parameters -dump-csv parameters.csv
```

**Remove all parameters:**
```bash
fmutool -input module.fmu -only-parameters -remove-all -output module-no-params.fmu
```

### Operations on Inputs Only

```bash
# List inputs
fmutool -input module.fmu -only-inputs -dump-csv inputs.csv

# Rename inputs
fmutool -input module.fmu -only-inputs -rename-from-csv new_inputs.csv -output module.fmu
```

### Operations on Outputs Only

```bash
# List outputs
fmutool -input module.fmu -only-outputs -dump-csv outputs.csv

# Filter outputs
fmutool -input module.fmu -only-outputs -keep-only-regexp "^Result\." -output module.fmu
```

### Operations on Local Variables Only

```bash
# List local variables
fmutool -input module.fmu -only-locals -dump-csv locals.csv

# Remove all local variables
fmutool -input module.fmu -only-locals -remove-all -output module-no-locals.fmu
```

### Operations by Type or Variability

`-only-type` and `-only-variability` select the ports by their FMI type and
their variability. Both can be repeated, and combine with the `-only-*`
causality options: a port is processed only if it matches each of them.

```bash
# List the real ports (Real in FMI 2.0; Float32 and Float64 in FMI 3.0)
fmutool -input module.fmu -only-type Real -dump-csv reals.csv

# Remove the parameters that cannot change during the simulation
fmutool -input module.fmu -only-parameters -only-variability fixed -remove-all -output module-tunable.fmu

# Rename the integer inputs only
fmutool -input module.fmu -only-inputs -only-type Integer -rename-from-csv new_names.csv -output module-renamed.fmu
```

- `-only-type` takes an FMI 2.0 type (`Real`, `Integer`, `Boolean`, `String`,
  `Enumeration`) or an FMI 3.0 one (`Float32`, `Float64`, `Int8`…`UInt64`,
  `Boolean`, `String`, `Binary`, `Enumeration`, `Clock`). On an FMI 3.0 FMU, an
  FMI 2.0 type selects its family: `Real` is `Float32` and `Float64`, `Integer`
  every integer type.
- `-only-variability` takes `constant`, `fixed`, `tunable`, `discrete` or
  `continuous`. A port that declares no variability has the default of the
  standard: `continuous` in FMI 2.0; in FMI 3.0, `fixed` for parameters,
  `continuous` for `Float32`/`Float64` and `discrete` for the other types.

## Binary Operations

### Remove Sources

```bash
fmutool -input module.fmu -remove-sources -output module-no-src.fmu
```

**Effect:** The `sources/` folder is removed from the FMU.

### Compile Sources

```bash
fmutool -input module.fmu -compile-sources -output module-compiled.fmu
```

**Effect:** When the FMU embeds its C (or C++) sources but no binary for the current platform, the sources are
compiled and the shared library is added to `binaries/<platform>/` (e.g. `binaries/linux64/` for FMI 2.0,
`binaries/x86_64-linux/` for FMI 3.0). If the binary already exists, nothing is compiled. The sources are kept, and
`modelDescription.xml` is not changed.

```
INFO     | Compiling 'BouncingBall' for x86_64-linux with gcc.
INFO     | Compiling 'sources/fmi3Functions.c'.
INFO     | Compiling 'sources/model.c'.
INFO     | Compiling 'sources/cosimulation.c'.
INFO     | Linking 'BouncingBall.so'.
INFO     | Binary 'binaries/x86_64-linux/BouncingBall.so' is built.
```

**Prerequisite:** a C compiler for the current platform:

| Platform | Compiler |
|----------|----------|
| Windows | Visual Studio, or its *Build Tools*, with the *Desktop development with C++* workload: found automatically. Otherwise, `cl.exe` from the `PATH` (Developer Command Prompt). |
| Linux | `cc` (e.g. `sudo apt-get install build-essential`), or the compiler given by the `CC` environment variable (`CXX` for C++). |
| macOS | `cc` of the Xcode Command Line Tools (`xcode-select --install`), or `CC` / `CXX`. |

**What is compiled:** the files listed by the FMU: `<SourceFiles>` of `modelDescription.xml` (FMI 2.0), or
`sources/buildDescription.xml` (FMI 3.0) with its preprocessor definitions, include directories and libraries.
The FMI headers are provided by FMU Manipulation Toolbox. The shared library is built for the current platform
only (no cross-compilation), with optimizations (`-O2` / `/O2`) and, on Windows, the static C runtime (`/MT`) and `/bigobj` (large object
files, e.g. generated code).

**Additional options:** FMI 2.0 `<SourceFiles>` only lists file names: when the sources need a preprocessor
definition, an include directory or a library, give them with:

| Option | Content | Example |
|--------|---------|---------|
| `-compile-options` | options added to every compilation | `-compile-options="-DFOO=1 -I/opt/include"` |
| `-link-options` | options added to the link, before the libraries | `-link-options=-L/opt/lib` (`/LIBPATH:C:\lib` with Visual Studio) |
| `-link-libraries` | libraries, by name, separated by commas | `-link-libraries foo,bar` (`-lfoo -lbar`, or `foo.lib bar.lib` with Visual Studio) |

```bash
fmutool -input module.fmu -compile-sources -compile-options=-DFOO=1 -link-libraries foo -output module-compiled.fmu
```

They come in addition to what the build description of the FMU gives, and need `-compile-sources` (otherwise:
exit code `2`). The options are written for the compiler in use (shown by the first line of the log, e.g.
`… with gcc.`).

!!! note
    A value that starts with `-` and contains no space must be written with `=`: `-compile-options=-DFOO`, not
    `-compile-options -DFOO` (the command line parser would take `-DFOO` for an option). With several options,
    quotes are enough: `-compile-options "-DFOO -DBAR"`.

**Errors** (exit code `5`, no output FMU): no `sources/` folder, no list of the sources to compile, no compiler
found, or compilation failure. The compiler messages are shown as errors (as warnings when the compilation
succeeds).

**Command lines:** with `-debug`, the command line of each compilation and of the link is logged, with every
option: those of the build description, the additional ones, the include directories and the definitions added by
`fmutool`.

```bash
fmutool -input module.fmu -compile-sources -debug -output module-compiled.fmu
```

**Limits:**

- The presence of the binary is checked, not its architecture: an FMU with an Intel-only `darwin64` binary is not
  recompiled on a Mac with Apple Silicon. Remove the binary first (e.g. with a zip tool) to force the compilation.
- An FMU without list of its sources is not compiled: the sources to use (and the preprocessor definitions they
  need) cannot be guessed.
- FMI 2.0 gives no library to link with nor preprocessor definition: when the compiler or the linker reports a
  missing symbol or definition, use the additional options above.
- `compilerOptions` of `buildDescription.xml` are only used when they are written for the compiler in use (`gcc`,
  `clang` or `cl`).

### Extract Model Descriptor

```bash
fmutool -input module.fmu -extract-descriptor modelDescription.xml
```

**Effect:** Saves the `modelDescription.xml` file to the specified path. This can be combined with other operations.

### Add Binary Interface (Windows)

**Add 64-bit interface to 32-bit FMU:**
```bash
fmutool -input module32.fmu -add-remoting-win64 -output module-dual.fmu
```

**Add 32-bit interface to 64-bit FMU:**
```bash
fmutool -input module64.fmu -add-remoting-win32 -output module-dual.fmu
```

## Combining Operations

Options can be combined for complex transformations:

### Example 1: Clean and Simplify

```bash
fmutool -input module.fmu \
  -remove-regexp "^_internal.*" \
  -remove-toplevel \
  -remove-sources \
  -output module-clean.fmu
```

### Example 2: Filter and Rename

```bash
fmutool -input module.fmu \
  -keep-only-regexp "^Motor\." \
  -rename-from-csv motor_names.csv \
  -output module-motor-renamed.fmu
```

## fmucontainer: Create Containers

For full documentation of the `fmucontainer` command (options, CSV/JSON/SSP formats, Python API),
see the dedicated [FMU Container](../fmucontainer/container.md) page.

### Quick Reference

```bash
# Build container from CSV with 0.1s step size
fmucontainer -container container.csv:0.1

# Build from JSON with FMUs in a specific directory
fmucontainer -container assembly.json -fmu-directory ./my_fmus

# FMI 3.0 with multi-threading and profiling
fmucontainer -container assembly.json -fmi 3 -mt -profile
```

## fmusplit: Extract FMUs from a Container

The `fmusplit` command extracts the embedded FMUs and the assembly description from a container FMU.

### Basic Syntax

```bash
fmusplit -fmu container.fmu
```

This creates a directory `container.dir/` containing:

- All embedded `.fmu` files
- The JSON assembly description (`container.json`)

### Options

| Option | Description |
|---|---|
| `-fmu filename.fmu` | FMU container to split. Can be specified multiple times. |
| `-debug` | Enable verbose logging during the split process. |

### Example

```bash
# Split a single container
fmusplit -fmu my_container.fmu

# Split multiple containers
fmusplit -fmu container1.fmu -fmu container2.fmu
```

!!! note "Terminal-level connections"
    When two FMUs are wired together through compatible terminals (same
    `terminalKind` and `matchingRule`, as declared in each FMU's
    `terminalsAndIcons.xml`), `fmusplit` groups the underlying port-to-port
    links into a single terminal-to-terminal entry in the produced JSON,
    e.g. `[ "node1.fmu", "CanChannel", "bus.fmu", "Node1" ]`. This applies
    in particular to [LS-BUS enabled FMUs](../fmucontainer/ls-bus.md), even
    when the peer FMU does not emit clocks. The result can be re-imported
    into the GUI or fed back into `fmucontainer` unchanged.

## datalog2pcap: Convert Datalog to PCAPNG

!!! warning "Experimental"
    This tool is still experimental. The interface may change in future versions.

The `datalog2pcap` command converts the datalog CSV files of FMU containers holding LS-BUS enabled FMUs (produced with the
`-datalog` option) into PCAPNG files, for all the buses: CAN, LIN, FlexRay and Ethernet. Each bus operation is one packet.

Opening them in Wireshark requires the [FMI-LS-BUS plugin](https://github.com/modelica/fmi-ls-bus/tree/main/wireshark-plugin),
including for CAN: copy `fmi_ls_bus.lua` to the **Personal Lua Plugins** directory shown in **Help > About Wireshark >
Folders**.

### Basic Syntax

```bash
datalog2pcap datalog.csv -fmu container.fmu
```

It writes `datalog.pcapng`. The container gives the type of bus of each column of the CSV file: an operation code does not
tell it, as `0x10` exists on the four buses.

The CSV file may have been written in any locale: with a semicolon between its columns and a decimal comma, or not.

### Options

| Option | Description |
|---|---|
| `datalog.csv` | Datalog CSV file with LS-BUS data and clocks. |
| `-fmu container.fmu` | Container that produced the datalog. Required. |
| `-debug` | Enable verbose logging. |

!!! warning "Migration"
    The option `-can` and the PCAP output are removed.

## Exit Codes

`fmutool`, `fmucontainer` and `fmusplit` share the same exit codes:

| Code | Meaning |
|-----:|---------|
| `0`  | Success |
| `1`  | Unexpected internal error (reported with a Python traceback) |
| `2`  | Invalid command line (also `-input` and `-output` pointing to the same file) |
| `3`  | Input file missing or unreadable |
| `4`  | Invalid input: not an FMU or not a container, invalid assembly, unreadable `modelDescription.xml` |
| `5`  | Operation or build refused or failed (e.g. an operation that would break the FMI standard) |
| `6`  | Output cannot be written |
| `7`  | `-check`: the FMU is not compliant |

!!! note
    Earlier versions exited with negative codes (`-1` to `-6`, seen as `255` to `250` by the shell),
    with a different meaning for each tool: see the changelog.

## Automation and Scripts

### Simple Bash Script

```bash
#!/bin/bash

# Process all FMUs in a directory
for fmu in *.fmu; do
  echo "Processing $fmu..."
  fmutool -input "$fmu" \
    -remove-toplevel \
    -remove-sources \
    -output "processed_$fmu"
done

echo "All FMUs processed!"
```

### Batch Script (Windows)

```batch
@echo off
for %%f in (*.fmu) do (
  echo Processing %%f...
  fmutool -input "%%f" -remove-toplevel -output "processed_%%f"
)
echo All FMUs processed!
```

## Quick Reference

```bash
# Analysis
fmutool -input X.fmu -summary              # Summary
fmutool -input X.fmu -check                # Verification
fmutool -input X.fmu -dump-csv list.csv    # List ports

# Simple modification
fmutool -input X.fmu -remove-toplevel -output Y.fmu
fmutool -input X.fmu -merge-toplevel -output Y.fmu

# Renaming
fmutool -input X.fmu -rename-from-csv names.csv -output Y.fmu

# Filtering
fmutool -input X.fmu -keep-only-regexp "PATTERN" -output Y.fmu
fmutool -input X.fmu -remove-regexp "PATTERN" -output Y.fmu

# By type
fmutool -input X.fmu -only-parameters -dump-csv params.csv
fmutool -input X.fmu -only-inputs -dump-csv inputs.csv
fmutool -input X.fmu -only-outputs -dump-csv outputs.csv
fmutool -input X.fmu -only-locals -dump-csv locals.csv

# Extraction / Binaries (Windows)
fmutool -input X.fmu -extract-descriptor modelDescription.xml
fmutool -input X.fmu -add-remoting-win64 -output Y.fmu
fmutool -input X.fmu -remove-sources -output Y.fmu
fmutool -input X.fmu -compile-sources -debug -output Y.fmu   # Compile, show the command lines

# Containers
fmucontainer -container config.json -fmu-directory ./fmus
fmusplit -fmu container.fmu

# Datalog conversion (experimental)
datalog2pcap datalog.csv -fmu container.fmu
```

## Next Steps

- 🐍 [Python API](python-api.md) - Advanced automation
- 💡 [Examples](../../examples/examples.md) - Detailed use cases
- 🆘 [Troubleshooting](../../help/troubleshooting.md)
