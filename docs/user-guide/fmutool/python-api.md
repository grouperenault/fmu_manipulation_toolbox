# Python API Usage Guide

The Python API of **FMU Manipulation Toolbox** allows you to fully automate your FMU manipulation tasks and integrate them into your workflows.

## Installation and Import

```python
# Installation
# pip install fmu-manipulation-toolbox

# Import
from fmu_manipulation_toolbox.operations import (
    FMU,
    OperationStripTopLevel,
    OperationRenameFromCSV,
    OperationSaveNamesToCSV,
    OperationRemoveRegexp,
    OperationKeepOnlyRegexp
)
```

## FMU Class: Fundamentals

### Load an FMU

```python
from fmu_manipulation_toolbox.operations import FMU

# Load the FMU
fmu = FMU("path/to/module.fmu")

# Display summary
fmu.summary()

# List variables
for var in fmu.variables:
    print(f"{var.name}: {var.causality} - {var.variability}")
```

### Save a Modified FMU

```python
# After modifications
fmu.repack("path/to/module-modified.fmu")
```

⚠️ **Important:** The original FMU is never modified. `repack()` creates a new copy.

### FMU Properties

```python
# General information
print(f"Name: {fmu.name}")
print(f"GUID: {fmu.guid}")
print(f"FMI Version: {fmu.fmi_version}")
print(f"Description: {fmu.description}")

# Counters
print(f"Number of variables: {len(fmu.variables)}")
print(f"Number of parameters: {fmu.count_parameters()}")
print(f"Number of inputs: {fmu.count_inputs()}")
print(f"Number of outputs: {fmu.count_outputs()}")
```

### Access Variables

```python
# All variables
all_vars = fmu.variables

# Filter by causality
parameters = [v for v in fmu.variables if v.causality == "parameter"]
inputs = [v for v in fmu.variables if v.causality == "input"]
outputs = [v for v in fmu.variables if v.causality == "output"]

# Search for specific variable
motor_speed = fmu.get_variable("Motor.Speed")
if motor_speed:
    print(f"Found: {motor_speed.name}")
    print(f"  Type: {motor_speed.type}")
    print(f"  Causality: {motor_speed.causality}")
```

## Basic Operations

### Remove Top-Level Hierarchy

```python
from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel

# Load FMU
fmu = FMU("module.fmu")

# Create and apply operation
operation = OperationStripTopLevel()
fmu.apply_operation(operation)

# Save
fmu.repack("module-flat.fmu")
```

**Effect:**
- Before: `System.Motor.Speed`
- After: `Motor.Speed`

### Export Names to CSV

```python
from fmu_manipulation_toolbox.operations import FMU, OperationSaveNamesToCSV

fmu = FMU("module.fmu")

# Create operation
operation = OperationSaveNamesToCSV()

# Apply (collect names)
fmu.apply_operation(operation)

# Write CSV
operation.write_csv("ports_list.csv")
```

### Rename from CSV

```python
from fmu_manipulation_toolbox.operations import FMU, OperationRenameFromCSV

fmu = FMU("module.fmu")

# Load and apply renamings
operation = OperationRenameFromCSV("renaming.csv")
fmu.apply_operation(operation)

# Save
fmu.repack("module-renamed.fmu")
```

### Filter by Regular Expression

```python
from fmu_manipulation_toolbox.operations import FMU, OperationKeepOnlyRegexp

fmu = FMU("module.fmu")

# Keep only Motor.* ports
operation = OperationKeepOnlyRegexp(r"^Motor\..*")
fmu.apply_operation(operation)

fmu.repack("module-motor-only.fmu")
```

**Remove by regexp:**

```python
from fmu_manipulation_toolbox.operations import FMU, OperationRemoveRegexp

fmu = FMU("module.fmu")

# Remove all Internal.* ports
operation = OperationRemoveRegexp(r"^Internal\..*")
fmu.apply_operation(operation)

fmu.repack("module-clean.fmu")
```

## Advanced Operations

### Chain Multiple Operations

```python
from fmu_manipulation_toolbox.operations import (
    FMU,
    OperationRemoveRegexp,
    OperationStripTopLevel,
    OperationRenameFromCSV
)

fmu = FMU("module.fmu")

# Operation 1: Remove internal variables
op1 = OperationRemoveRegexp(r"^_internal.*")
fmu.apply_operation(op1)

# Operation 2: Simplify hierarchy
op2 = OperationStripTopLevel()
fmu.apply_operation(op2)

# Operation 3: Rename
op3 = OperationRenameFromCSV("new_names.csv")
fmu.apply_operation(op3)

# Save final result
fmu.repack("module-transformed.fmu")
```

### Conditional Manipulation

```python
from fmu_manipulation_toolbox.operations import FMU

fmu = FMU("module.fmu")

# Create renaming dictionary
renaming_map = {}

for var in fmu.variables:
    # Rename only parameters
    if var.causality == "parameter":
        new_name = f"param_{var.name}"
        renaming_map[var.name] = new_name
    
    # Add prefix to outputs
    elif var.causality == "output":
        new_name = f"out_{var.name}"
        renaming_map[var.name] = new_name

# Apply renamings
for old_name, new_name in renaming_map.items():
    var = fmu.get_variable(old_name)
    if var:
        var.name = new_name

fmu.repack("module-prefixed.fmu")
```

## Automation and Scripts

### Batch Processing Script

```python
import os
from pathlib import Path
from fmu_manipulation_toolbox.operations import (
    FMU,
    OperationStripTopLevel,
    OperationRemoveRegexp
)

def process_fmu(input_path, output_path):
    """Process a single FMU."""
    try:
        # Load
        fmu = FMU(input_path)
        
        # Clean
        op1 = OperationRemoveRegexp(r"^_internal.*")
        fmu.apply_operation(op1)
        
        # Simplify
        op2 = OperationStripTopLevel()
        fmu.apply_operation(op2)
        
        # Save
        fmu.repack(output_path)
        
        print(f"✓ Processed: {input_path}")
        return True
        
    except Exception as e:
        print(f"✗ Error with {input_path}: {e}")
        return False

def process_directory(input_dir, output_dir):
    """Process all FMUs in a directory."""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    
    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Process each FMU
    success_count = 0
    fail_count = 0
    
    for fmu_file in input_path.glob("*.fmu"):
        output_file = output_path / f"processed_{fmu_file.name}"
        
        if process_fmu(str(fmu_file), str(output_file)):
            success_count += 1
        else:
            fail_count += 1
    
    print(f"\n=== Summary ===")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")

# Usage
if __name__ == "__main__":
    process_directory("./input_fmus", "./output_fmus")
```

### Parallel Processing

```python
from multiprocessing import Pool
from pathlib import Path
from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel

def process_single_fmu(args):
    """Function to process one FMU (for multiprocessing)."""
    input_path, output_path = args
    
    try:
        fmu = FMU(input_path)
        operation = OperationStripTopLevel()
        fmu.apply_operation(operation)
        fmu.repack(output_path)
        return (input_path, True, None)
    except Exception as e:
        return (input_path, False, str(e))

def parallel_processing(input_dir, output_dir, num_workers=4):
    """Process FMUs in parallel."""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Prepare arguments
    tasks = []
    for fmu_file in input_path.glob("*.fmu"):
        output_file = output_path / f"processed_{fmu_file.name}"
        tasks.append((str(fmu_file), str(output_file)))
    
    # Process in parallel
    with Pool(num_workers) as pool:
        results = pool.map(process_single_fmu, tasks)
    
    # Display results
    for fmu_path, success, error in results:
        if success:
            print(f"✓ {fmu_path}")
        else:
            print(f"✗ {fmu_path}: {error}")

# Usage
parallel_processing("./input_fmus", "./output_fmus", num_workers=4)
```

### Validation in CI/CD Pipeline

```python
from fmu_manipulation_toolbox.operations import FMU
import sys

def validate_fmu(fmu_path):
    """Validate an FMU and return exit code."""
    try:
        fmu = FMU(fmu_path)
        
        # Checks
        is_valid = fmu.validate_model_description()
        
        if not is_valid:
            print(f"✗ ERROR: {fmu_path} is not valid")
            print(fmu.get_validation_errors())
            return 1
        
        # Additional checks
        if len(fmu.variables) == 0:
            print(f"⚠ WARNING: {fmu_path} has no variables")
            return 1
        
        print(f"✓ SUCCESS: {fmu_path} is valid")
        print(f"  - {len(fmu.variables)} variables")
        print(f"  - {fmu.count_parameters()} parameters")
        
        return 0
        
    except Exception as e:
        print(f"✗ ERROR: Cannot load {fmu_path}")
        print(f"  {e}")
        return 1

# Usage in CI/CD
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate.py <fmu_file>")
        sys.exit(1)
    
    exit_code = validate_fmu(sys.argv[1])
    sys.exit(exit_code)
```

## Best Practices

### ✅ Do

```python
# Always verify loading
try:
    fmu = FMU("module.fmu")
except Exception as e:
    print(f"Loading error: {e}")
    sys.exit(1)

# Validate after important modifications
fmu.apply_operation(operation)
if not fmu.validate_model_description():
    print("Warning: Invalid FMU after modification")

# Use absolute paths to avoid issues
from pathlib import Path
fmu_path = Path("module.fmu").resolve()
fmu = FMU(str(fmu_path))
```

### ❌ Avoid

```python
# ❌ Forgetting to apply operation
operation = OperationStripTopLevel()
# fmu.apply_operation(operation)  # FORGOTTEN!
fmu.repack("output.fmu")  # No changes!

# ❌ Modifying original FMU
fmu = FMU("original.fmu")
fmu.apply_operation(operation)
fmu.repack("original.fmu")  # DANGER! Never overwrite original

# ✅ Always create new file
fmu.repack("original_modified.fmu")
```

## Next Steps

- 💡 [Advanced Examples](../../examples/examples.md)
- 🆘 [Troubleshooting](../../help/troubleshooting.md)

## Support

- 📖 [Complete Documentation](../index.md)
- 🐛 [GitHub Issues](https://github.com/grouperenault/fmu_manipulation_toolbox/issues)
