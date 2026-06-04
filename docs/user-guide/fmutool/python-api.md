# Python API Usage Guide

The Python API of **FMU Manipulation Toolbox** allows you to fully automate your FMU manipulation tasks and integrate them into your workflows.

## Installation and Import

```python
# Installation
# pip install fmu-manipulation-toolbox

# Import
from fmu_manipulation_toolbox.operations import (
    FMU,
    FMUError,
    OperationSummary,
    OperationStripTopLevel,
    OperationMergeTopLevel,
    OperationTrimUntil,
    OperationRenameFromCSV,
    OperationSaveNamesToCSV,
    OperationRemoveRegexp,
    OperationKeepOnlyRegexp,
    OperationRemoveSources,
)
```

## FMU Class: Fundamentals

The `FMU` class is a wrapper around an FMU archive (`.fmu` zip file). It extracts the archive
into a temporary directory and allows you to apply operations to its `modelDescription.xml`
descriptor.

!!! note "Architecture"
    The `FMU` class does **not** expose variables or metadata directly as properties.
    All inspection and modification is done through **operations** — objects that implement
    the visitor pattern and are applied via `fmu.apply_operation(operation)`.

### Load an FMU

```python
from fmu_manipulation_toolbox.operations import FMU, FMUError

try:
    fmu = FMU("path/to/module.fmu")
except FMUError as e:
    print(f"Cannot load FMU: {e}")
```

### Apply an Operation

```python
from fmu_manipulation_toolbox.operations import FMU, OperationSummary

fmu = FMU("module.fmu")

# Create an operation instance
operation = OperationSummary()

# Apply it — this parses modelDescription.xml and invokes the operation's callbacks
fmu.apply_operation(operation)
```

### Save a Modified FMU

```python
# After modifications, create a new FMU file
fmu.repack("path/to/module-modified.fmu")
```

⚠️ **Important:** The original FMU is never modified. `repack()` creates a new archive.

### Extract the Model Descriptor

```python
# Save a copy of the (possibly modified) modelDescription.xml
fmu.save_descriptor("path/to/modelDescription.xml")
```

### Filter Operations by Causality

You can restrict an operation to specific port types using the `apply_on` parameter:

```python
from fmu_manipulation_toolbox.operations import FMU, OperationRemoveRegexp

fmu = FMU("module.fmu")

# Remove matching ports, but only among inputs
operation = OperationRemoveRegexp(r"^debug_.*")
fmu.apply_operation(operation, apply_on=["input"])

fmu.repack("module-clean.fmu")
```

Valid values for `apply_on`: `"parameter"`, `"input"`, `"output"`, `"local"`.

## Available Operations

### Display FMU Summary

```python
from fmu_manipulation_toolbox.operations import FMU, OperationSummary

fmu = FMU("module.fmu")
operation = OperationSummary()
fmu.apply_operation(operation)

# After apply, you can access the port counts:
print(operation.nb_port_per_causality)
# e.g. {'input': 10, 'output': 15, 'parameter': 5, 'local': 12}
```

The summary is logged via the `fmu_manipulation_toolbox` logger.

### Export Names to CSV

```python
from fmu_manipulation_toolbox.operations import FMU, OperationSaveNamesToCSV

fmu = FMU("module.fmu")

# The filename is passed at construction time
operation = OperationSaveNamesToCSV("ports_list.csv")
fmu.apply_operation(operation)
# The CSV file is written during apply_operation and closed automatically.
```

The generated CSV has columns: `name;newName;valueReference;causality;variability;scalarType;startValue`.

### Rename from CSV

```python
from fmu_manipulation_toolbox.operations import FMU, OperationRenameFromCSV

fmu = FMU("module.fmu")

# Load the CSV mapping and apply renamings
operation = OperationRenameFromCSV("renaming.csv")
fmu.apply_operation(operation)

fmu.repack("module-renamed.fmu")
```

The CSV must be semicolon-delimited with at least two columns: original name and new name.
If the new name is empty, the port is removed.

### Remove Top-Level Hierarchy

```python
from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel

fmu = FMU("module.fmu")
operation = OperationStripTopLevel()
fmu.apply_operation(operation)
fmu.repack("module-flat.fmu")
```

**Effect:**

- Before: `System.Motor.Speed`
- After: `Motor.Speed`

### Merge Top-Level Hierarchy

```python
from fmu_manipulation_toolbox.operations import FMU, OperationMergeTopLevel

fmu = FMU("module.fmu")
operation = OperationMergeTopLevel()
fmu.apply_operation(operation)
fmu.repack("module-merged.fmu")
```

**Effect:**

- Before: `System.Motor.Speed`
- After: `System_Motor.Speed`

### Trim Until Separator

```python
from fmu_manipulation_toolbox.operations import FMU, OperationTrimUntil

fmu = FMU("module.fmu")
operation = OperationTrimUntil("_")
fmu.apply_operation(operation)
fmu.repack("module-trimmed.fmu")
```

**Effect:**

- Before: `_internal_Motor_Speed`
- After: `internal_Motor_Speed`

### Filter by Regular Expression

**Keep only matching ports:**

```python
from fmu_manipulation_toolbox.operations import FMU, OperationKeepOnlyRegexp

fmu = FMU("module.fmu")
operation = OperationKeepOnlyRegexp(r"^Motor\..*")
fmu.apply_operation(operation)
fmu.repack("module-motor-only.fmu")
```

**Remove matching ports:**

```python
from fmu_manipulation_toolbox.operations import FMU, OperationRemoveRegexp

fmu = FMU("module.fmu")
operation = OperationRemoveRegexp(r"^Internal\..*")
fmu.apply_operation(operation)
fmu.repack("module-clean.fmu")
```

### Remove Sources

```python
from fmu_manipulation_toolbox.operations import FMU, OperationRemoveSources

fmu = FMU("module.fmu")
operation = OperationRemoveSources()
fmu.apply_operation(operation)
fmu.repack("module-no-src.fmu")
```

## Remoting Operations

```python
from fmu_manipulation_toolbox.operations import FMU
from fmu_manipulation_toolbox.remoting import (
    OperationAddRemotingWin32,
    OperationAddRemotingWin64,
    OperationAddFrontendWin32,
    OperationAddFrontendWin64,
)

fmu = FMU("module32.fmu")

# Add 64-bit remoting interface to a 32-bit FMU
operation = OperationAddRemotingWin64()
fmu.apply_operation(operation)
fmu.repack("module-dual.fmu")
```

!!! note
    Remoting operations are only supported for FMI 2.0 FMUs on Windows.

## Checker Operations

```python
from fmu_manipulation_toolbox.operations import FMU
from fmu_manipulation_toolbox.checker import get_checkers

fmu = FMU("module.fmu")

# Run all registered checkers (XSD validation, etc.)
for checker_class in get_checkers():
    checker = checker_class()
    fmu.apply_operation(checker)
```

## Chain Multiple Operations

```python
from fmu_manipulation_toolbox.operations import (
    FMU,
    OperationRemoveRegexp,
    OperationStripTopLevel,
    OperationRenameFromCSV,
)

fmu = FMU("module.fmu")

# Operation 1: Remove internal variables
op1 = OperationRemoveRegexp(r"^_internal.*")
fmu.apply_operation(op1)

# Operation 2: Simplify hierarchy
op2 = OperationStripTopLevel()
fmu.apply_operation(op2)

# Operation 3: Rename from CSV
op3 = OperationRenameFromCSV("new_names.csv")
fmu.apply_operation(op3)

# Save final result
fmu.repack("module-transformed.fmu")
```

## Writing Custom Operations

You can create your own operation by subclassing `OperationAbstract`:

```python
from fmu_manipulation_toolbox.operations import FMU, OperationAbstract, FMUPort

class OperationCountPorts(OperationAbstract):
    """Count ports by type."""

    def __init__(self):
        self.counts = {}

    def port_attrs(self, fmu_port: FMUPort) -> int:
        fmi_type = fmu_port.fmi_type
        self.counts[fmi_type] = self.counts.get(fmi_type, 0) + 1
        return 0  # 0 = keep port, non-zero = remove port

    def closure(self):
        """Called after all ports have been processed."""
        print(f"Port type counts: {self.counts}")
```

### Available Callbacks

| Method | Called When |
|--------|------------|
| `fmi_attrs(attrs)` | `<fmiModelDescription>` element is parsed |
| `cosimulation_attrs(attrs)` | `<CoSimulation>` element is parsed |
| `experiment_attrs(attrs)` | `<DefaultExperiment>` element is parsed |
| `port_attrs(fmu_port) -> int` | Each port/variable. Return `0` to keep, non-zero to remove |
| `closure()` | After the full descriptor has been parsed |

The `fmu_port` argument is an `FMUPort` object that supports dict-like access to attributes:

```python
def port_attrs(self, fmu_port: FMUPort) -> int:
    name = fmu_port["name"]
    causality = fmu_port.get("causality", "local")
    value_ref = fmu_port["valueReference"]
    fmi_type = fmu_port.fmi_type  # e.g. "Real", "Float64", "Integer"

    # Modify in place
    fmu_port["name"] = "new_" + name

    return 0
```

## Automation and Scripts

### Batch Processing Script

```python
from pathlib import Path
from fmu_manipulation_toolbox.operations import (
    FMU,
    FMUError,
    OperationStripTopLevel,
    OperationRemoveRegexp,
)

def process_fmu(input_path, output_path):
    """Process a single FMU."""
    try:
        fmu = FMU(str(input_path))

        op1 = OperationRemoveRegexp(r"^_internal.*")
        fmu.apply_operation(op1)

        op2 = OperationStripTopLevel()
        fmu.apply_operation(op2)

        fmu.repack(str(output_path))
        print(f"✓ Processed: {input_path}")
        return True

    except FMUError as e:
        print(f"✗ Error with {input_path}: {e}")
        return False

def process_directory(input_dir, output_dir):
    """Process all FMUs in a directory."""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    success_count = 0
    fail_count = 0

    for fmu_file in input_path.glob("*.fmu"):
        output_file = output_path / f"processed_{fmu_file.name}"
        if process_fmu(fmu_file, output_file):
            success_count += 1
        else:
            fail_count += 1

    print(f"\n=== Summary ===")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")

if __name__ == "__main__":
    process_directory("./input_fmus", "./output_fmus")
```

### Parallel Processing

```python
from multiprocessing import Pool
from pathlib import Path
from fmu_manipulation_toolbox.operations import FMU, FMUError, OperationStripTopLevel

def process_single_fmu(args):
    """Function to process one FMU (for multiprocessing)."""
    input_path, output_path = args

    try:
        fmu = FMU(input_path)
        operation = OperationStripTopLevel()
        fmu.apply_operation(operation)
        fmu.repack(output_path)
        return (input_path, True, None)
    except FMUError as e:
        return (input_path, False, str(e))

def parallel_processing(input_dir, output_dir, num_workers=4):
    """Process FMUs in parallel."""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    tasks = []
    for fmu_file in input_path.glob("*.fmu"):
        output_file = output_path / f"processed_{fmu_file.name}"
        tasks.append((str(fmu_file), str(output_file)))

    with Pool(num_workers) as pool:
        results = pool.map(process_single_fmu, tasks)

    for fmu_path, success, error in results:
        if success:
            print(f"✓ {fmu_path}")
        else:
            print(f"✗ {fmu_path}: {error}")

# Usage
parallel_processing("./input_fmus", "./output_fmus", num_workers=4)
```

## Best Practices

### ✅ Do

```python
# Always handle loading errors
from fmu_manipulation_toolbox.operations import FMU, FMUError

try:
    fmu = FMU("module.fmu")
except FMUError as e:
    print(f"Loading error: {e}")
    sys.exit(1)

# Use absolute paths to avoid issues
from pathlib import Path
fmu_path = Path("module.fmu").resolve()
fmu = FMU(str(fmu_path))

# Chain operations in the correct order
# (remove first, then rename the remaining ports)
```

### ❌ Avoid

```python
# ❌ Forgetting to apply the operation
operation = OperationStripTopLevel()
# fmu.apply_operation(operation)  # FORGOTTEN!
fmu.repack("output.fmu")  # No changes applied!

# ❌ Overwriting the original FMU
fmu = FMU("original.fmu")
fmu.apply_operation(operation)
fmu.repack("original.fmu")  # DANGER! Never overwrite the source file

# ✅ Always create a new file
fmu.repack("original_modified.fmu")
```

## Next Steps

- 💡 [Advanced Examples](../../examples/examples.md)
- 🆘 [Troubleshooting](../../help/troubleshooting.md)

## Support

- 📖 [Complete Documentation](../index.md)
- 🐛 [GitHub Issues](https://github.com/grouperenault/fmu_manipulation_toolbox/issues)
