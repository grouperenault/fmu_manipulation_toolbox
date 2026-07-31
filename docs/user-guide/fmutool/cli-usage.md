# Command Line Interface (CLI) Usage Guide

The command line offers complete and precise control over FMU Manipulation Toolbox, ideal for automation and batch processing.

## Available Commands

FMU Manipulation Toolbox provides four main commands:

| Command        | Usage                                        |
|----------------|----------------------------------------------|
| `fmutool`      | FMU analysis and manipulation                |
| `fmucontainer` | FMU container creation                       |
| `fmusplit`     | Extract FMUs from a container                |
| `datalog2pcap` | Convert CAN datalog CSV to PCAP (experimental) |

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

**Output:**
```
Checking FMU: module.fmu
✓ modelDescription.xml is valid
✓ Schema validation passed
⚠ Warning: Variable 'temp' has no description
✓ All value references are unique
```

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

## Binary Operations

### Remove Sources

```bash
fmutool -input module.fmu -remove-sources -output module-no-src.fmu
```

**Effect:** The `sources/` folder is removed from the FMU.

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

## datalog2pcap: Convert Datalog to PCAP

!!! warning "Experimental"
    This tool is still experimental. The interface may change in future versions.

The `datalog2pcap` command converts CAN bus datalog CSV files (produced by FMU containers with
the `-datalog` option and LS-BUS enabled FMUs) into PCAP files for analysis in tools like
Wireshark.

### Basic Syntax

```bash
datalog2pcap -can datalog.csv
```

### Options

| Option | Description |
|---|---|
| `-can filename.csv` | Datalog CSV file with CAN data and clocks. |
| `-debug` | Enable verbose logging. |

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

# Containers
fmucontainer -container config.json -fmu-directory ./fmus
fmusplit -fmu container.fmu

# Datalog conversion (experimental)
datalog2pcap -can datalog.csv
```

## Next Steps

- 🐍 [Python API](python-api.md) - Advanced automation
- 💡 [Examples](../../examples/examples.md) - Detailed use cases
- 🆘 [Troubleshooting](../../help/troubleshooting.md)
