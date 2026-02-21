# Command Line Interface (CLI) Usage Guide

The command line offers complete and precise control over FMU Manipulation Toolbox, ideal for automation and batch processing.

## Available Commands

FMU Manipulation Toolbox provides three main commands:

| Command | Usage |
|---------|-------|
| `fmutool` | FMU analysis and manipulation |
| `fmucontainer` | FMU container creation |
| `fmusplit` | Extract FMUs from a container |

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

## Binary Operations

### Remove Sources

```bash
fmutool -input module.fmu -remove-sources -output module-no-src.fmu
```

**Effect:** The `sources/` folder is removed from the FMU.

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

### Basic Syntax

```bash
fmucontainer -container config.csv -fmu-directory ./fmus
```

### Main Options

```bash
-container filename.csv          # Configuration file
-fmu-directory path/to/fmus      # Directory containing FMUs
-fmi {2|3}                       # FMI version (default: 2)
-output container.fmu            # Container name (optional)
```

### Configuration CSV Format

```csv
fmu;input;output
motor.fmu;controller.command;sensor.speed
controller.fmu;sensor.speed;motor.command
sensor.fmu;motor.torque;controller.feedback
```

### Advanced Options

```bash
# Enable multi-threading
fmucontainer -container system.csv -fmu-directory ./fmus -mt

# Enable profiling
fmucontainer -container system.csv -fmu-directory ./fmus -profile

# Expose parameters
fmucontainer -container system.csv -fmu-directory ./fmus -auto-parameter

# Debug mode
fmucontainer -container system.csv -fmu-directory ./fmus -debug
```

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

# Binaries (Windows)
fmutool -input X.fmu -add-remoting-win64 -output Y.fmu
fmutool -input X.fmu -remove-sources -output Y.fmu

# Containers
fmucontainer -container config.csv -fmu-directory ./fmus
```

## Next Steps

- 🐍 [Python API](python-api.md) - Advanced automation
- 💡 [Examples](../../examples/examples.md) - Detailed use cases
- 🆘 [Troubleshooting](../../help/troubleshooting.md)
