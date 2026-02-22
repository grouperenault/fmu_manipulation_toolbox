---
title: Getting Started
description: Quick start guide to get up and running with FMU Manipulation Toolbox
---

# Getting Started

This guide will get you up and running with **FMU Manipulation Toolbox** in less than 15 minutes.

## Prerequisites

Before you begin, ensure you have:

- [x] Python 3.9 or higher
- [x] pip (Python package manager)
- [x] An FMU file to work with (or use our examples)

!!! info "What is an FMU?"
    A Functional Mock-up Unit (FMU) is a standardized format for model exchange and co-simulation defined by the
[FMI Standard](https://fmi-standard.org/){:target="_blank"}. FMUs are widely used in automotive, aerospace, and industrial automation.

## Installation

Install FMU Manipulation Toolbox using pip:

```bash
pip install fmu-manipulation-toolbox
```

Verify the installation:

```bash
fmutool --help
```

??? success "Installation successful!"
    
    You should see the help message displaying all available commands. If you encounter issues, check our 
[Troubleshooting Guide](../help/troubleshooting.md).

## Your First FMU Analysis

Let's start by analyzing an existing FMU to understand its structure.

### Step 1: Get FMU Information

=== "Command Line"

    ```bash
    fmutool -input my_model.fmu -summary
    ```
    
    **Expected Output:**
    ```
    FMU Information:
      Name: my_module
      FMI Version: 2.0
      GUID: {12345678-1234-1234-1234-123456789012}
      Number of variables: 42
      Number of parameters: 5
      Number of inputs: 8
      Number of outputs: 12
    ```

=== "Python API"

    ```python
    from fmu_manipulation_toolbox.operations import FMU, OperationSummary
    from fmu_manipulation_toolbox.cli.utils import setup_logger
    
    setup_logger()

    # Load the FMU
    fmu = FMU("my_model.fmu")
    
    # Display summary using logging facilities
    fmu.apply_operation(OperationSummary())
    ```

=== "Graphical Interface"

    ```bash
    fmutool-gui
    ```
    
    1. Click **Load FMU**
    2. Select your FMU file
    3. View the summary in the interface

### Step 2: List All Ports

Export all port information to a CSV file for easy viewing:

```bash
fmutool -input my_module.fmu -dump-csv ports_list.csv
```

Open `ports_list.csv` to see all ports with their attributes:

| name | causality | variability | type | valueReference |
|------|-----------|-------------|------|----------------|
| Motor.Temperature | output | continuous | Real | 0 |
| Motor.Speed | input | continuous | Real | 1 |
| Controller.Gain | parameter | fixed | Real | 2 |

!!! tip "Pro Tip: Excel Integration"
    
    Open the CSV in Excel or LibreOffice Calc for easy filtering and sorting. Use semicolon (`;`) as the delimiter.

## Your First FMU Modification

Now let's modify an FMU by simplifying its port hierarchy.

### Problem: Complex Hierarchy

Your FMU has this structure:

```
System.Motor.Temperature
System.Motor.Speed
System.Controller.Gain
```

You want to simplify it to:

```
Motor.Temperature
Motor.Speed
Controller.Gain
```

### Solution

=== "Command Line"

    ```bash
    fmutool -input my_module.fmu \
      -remove-toplevel \
      -output my_module_simplified.fmu
    ```
    
    Verify the result:
    
    ```bash
    fmutool -input my_module_simplified.fmu -summary
    ```

=== "Python API"

    ```python
    from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel
    
    # Load FMU
    fmu = FMU("my_module.fmu")
    
    # Apply transformation
    operation = OperationStripTopLevel()
    fmu.apply_operation(operation)
    
    # Save result
    fmu.repack("my_module_simplified.fmu")
    ```

=== "Graphical Interface"

    1. Load your FMU
    2. Click **Strip Toplevel** button
    3. Click **Save** and choose output filename

!!! warning "Important: Original FMU Preservation"
    
    The original FMU is **never modified**. All operations create a new copy, ensuring data safety.

## Batch Renaming with CSV

For complex renaming operations, use CSV files.

### Step 1: Generate Renaming Template

```bash
fmutool -input my_module.fmu -dump-csv renaming.csv
```

### Step 2: Edit the CSV

Open `renaming.csv` and modify the `newName` column:

**Before:**
```csv
name;newName;valueReference;causality;variability
Motor.Temp;Motor.Temp;0;output;continuous
Motor.RPM;Motor.RPM;1;input;continuous
```

**After:**
```csv
name;newName;valueReference;causality;variability
Motor.Temp;Engine_Temperature;0;output;continuous
Motor.RPM;Rotation_Speed;1;input;continuous
```

!!! tip "Empty newName = Port Removal"
    
    Leave `newName` empty to remove a port from the FMU.

### Step 3: Apply Renaming

```bash
fmutool -input my_module.fmu \
  -rename-from-csv renaming.csv \
  -output my_module_renamed.fmu
```

## Common Operations

Here are the most frequently used operations:

<div class="grid cards" markdown>

-   :material-filter-variant:{ .lg .middle } __Filter Ports__

    ---

    Keep only ports matching a pattern:
    
    ```bash
    fmutool -input module.fmu \
      -keep-only-regexp "^Motor\..*" \
      -output module_motor.fmu
    ```

-   :material-delete:{ .lg .middle } __Remove Internals__

    ---

    Remove all internal variables:
    
    ```bash
    fmutool -input module.fmu \
      -remove-regexp "^Internal\..*" \
      -output module_clean.fmu
    ```

-   :material-check-circle:{ .lg .middle } __Validate FMU__

    ---

    Check FMI compliance:
    
    ```bash
    fmutool -input module.fmu -check
    ```

-   :material-file-export:{ .lg .middle } __Extract Parameters__

    ---

    List only parameters:
    
    ```bash
    fmutool -input module.fmu \
      -only-parameters \
      -dump-csv parameters.csv
    ```

</div>

## Your First FMU Container

An FMU Container is a standard FMU that **embeds other FMUs** inside it. This is useful to combine
multiple models into a single simulation unit, letting your FMI tool orchestrate a complex assembly as if it
were a single FMU.

### Concept

Imagine you have two FMUs modeling a bouncing ball:

- `bb_position.fmu` — computes the ball position
- `bb_velocity.fmu` — computes the ball velocity

These two FMUs need to exchange data: velocity feeds into position, and a ground-detection signal feeds back.
Instead of wiring them manually in your simulation tool, you can **package them together** as a single FMU Container.

### Step 1: Create a Description File

The easiest way is to use a **CSV file** describing which FMUs to include and how to connect them.

Create a file `container.csv`:

```csv
rule;from_fmu;from_port;to_fmu;to_port
FMU;bb_position.fmu;;;
FMU;bb_velocity.fmu;;;
OUTPUT;bb_position.fmu;position1;;position
LINK;bb_position.fmu;is_ground;bb_velocity.fmu;reset
LINK;bb_velocity.fmu;velocity;bb_position.fmu;velocity
OUTPUT;bb_velocity.fmu;velocity;;
```

Here's what each rule means:

| Rule | Meaning |
|------|---------|
| `FMU` | Declare an embedded FMU |
| `OUTPUT` | Expose a port from an embedded FMU as a container output |
| `LINK` | Connect an output of one embedded FMU to an input of another |

!!! tip "Auto-wiring"
    
    By default, `fmucontainer` will automatically connect ports with matching names (`auto_link`)
    and expose unconnected inputs/outputs (`auto_input`, `auto_output`). You only need to declare
    explicit connections for ports with different names.

### Step 2: Build the Container

=== "Command Line"

    Place your FMUs and the CSV file in the same directory, then run:
    
    ```bash
    fmucontainer -container container.csv:0.1
    ```
    
    The `:0.1` suffix sets the container's internal time step to **0.1 seconds**.
    
    The resulting `container.fmu` is ready to use in any FMI-compatible tool.

=== "With Options"

    You can customize the container creation:
    
    ```bash
    # FMUs are in a specific directory
    fmucontainer -container container.csv:0.1 -fmu-directory ./my_fmus
    
    # Enable multi-threading for parallel execution
    fmucontainer -container container.csv:0.1 -mt
    
    # Generate an FMI 3.0 container
    fmucontainer -container container.csv:0.1 -fmi 3
    ```

=== "JSON Format"

    For more control, use a **JSON description file** instead of CSV:
    
    ```json
    {
      "name": "bouncing.fmu",
      "mt": true,
      "profiling": false,
      "auto_link": true,
      "auto_input": true,
      "auto_output": true,
      "fmu": [
        "bb_position.fmu",
        "bb_velocity.fmu"
      ],
      "output": [
        ["bb_position.fmu", "position1", "position"],
        ["bb_velocity.fmu", "velocity", "velocity"]
      ],
      "link": [
        ["bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset"],
        ["bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"]
      ]
    }
    ```
    
    Then build with:
    
    ```bash
    fmucontainer -container bouncing.json
    ```

### Step 3: Verify the Result

Use `fmutool` to inspect the generated container just like any other FMU:

```bash
fmutool -input container.fmu -summary
```

!!! info "Learn More"
    
    FMU Containers support advanced features like profiling, variable step sizes, and LS-BUS routing.
    See the full [Container documentation](../user-guide/fmucontainer/container.md) for details.

## Essential Commands Reference

| Command                       | Description                |
|-------------------------------|----------------------------|
| `-summary`                    | Display FMU information    |
| `-check`                      | Validate FMI compliance    |
| `-dump-csv file.csv`          | Export ports to CSV        |
| `-remove-toplevel`            | Remove top hierarchy level |
| `-rename-from-csv file.csv`   | Batch rename from CSV      |
| `-keep-only-regexp "pattern"` | Keep matching ports only   |
| `-remove-regexp "pattern"`    | Remove matching ports      |


## Quick Troubleshooting

!!! failure "FMU Won't Load"
    
    **Check the FMU validity:**
    ```bash
    fmutool -input module.fmu -check
    ```
    
    Common causes:
    - Corrupted ZIP archive
    - Invalid `modelDescription.xml`
    - Missing required files

!!! failure "Modifications Not Applied"
    
    **Did you forget the `-output` option?**
    
    ❌ Wrong:
    ```bash
    fmutool -input module.fmu -remove-toplevel
    ```
    
    ✅ Correct:
    ```bash
    fmutool -input module.fmu -remove-toplevel -output module_flat.fmu
    ```

!!! failure "CSV Renaming Error"
    
    Ensure your CSV file:
    
    - [x] Is UTF-8 encoded
    - [x] Uses semicolon (`;`) as delimiter
    - [x] Contains all required columns: `name;newName;...`
    - [x] Includes all ports from the original FMU

## Next Steps

Now that you've mastered the basics, explore more advanced features:

<div class="grid cards" markdown>

-   [:octicons-terminal-24: CLI Guide](../user-guide/fmutool/cli-usage.md)
    
    Master command-line operations

-   [:octicons-code-24: Python API](../user-guide/fmutool/python-api.md)
    
    Automate with Python scripts

-   [:octicons-apps-24: GUI Guide](../user-guide/fmutool/gui-usage.md)
    
    Use the graphical interface

-   [:octicons-light-bulb-24: Use Cases](../examples/examples.md)
    
    Real-world examples

</div>

---

!!! success "Ready to Go!"
    
    You're now equipped with the fundamentals of FMU Manipulation Toolbox. Happy modeling! 🎉

    Need help? [report an issue](https://github.com/grouperenault/fmu_manipulation_toolbox/issues){:target="_blank"}.
