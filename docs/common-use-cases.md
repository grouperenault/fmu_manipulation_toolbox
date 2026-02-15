# Common Use Cases

This guide presents practical solutions to frequently encountered problems when manipulating FMUs.

## Table of Contents

- [Migration and Renaming](#migration-and-renaming)
- [Cleaning and Simplification](#cleaning-and-simplification)
- [Extraction and Filtering](#extraction-and-filtering)
- [Validation and Quality Control](#validation-and-quality-control)
- [Portability and Distribution](#portability-and-distribution)

---

## Migration and Renaming

### Case 1: Change Naming Convention

**Problem:** Convert from `CamelCase` to `snake_case` for all ports.

**CLI Solution:**

```bash
# 1. Export list
fmutool -input OldModel.fmu -dump-csv old_names.csv

# 2. Use Python to convert
python convert_names.py old_names.csv new_names.csv

# 3. Apply
fmutool -input OldModel.fmu -rename-from-csv new_names.csv -output new_model.fmu
```

**Python Script `convert_names.py`:**

```python
import pandas as pd
import re

def camel_to_snake(name):
    """Convert CamelCase to snake_case."""
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

# Read CSV
df = pd.read_csv('old_names.csv', sep=';')

# Convert names
df['newName'] = df['name'].apply(camel_to_snake)

# Save
df.to_csv('new_names.csv', sep=';', index=False)
print("✓ Conversion complete")
```

### Case 2: Prefix All Ports

**Problem:** Add `Component1_` prefix to all ports before integration.

**Python API Solution:**

```python
from fmu_manipulation_toolbox.operations import FMU

fmu = FMU("module.fmu")

# Add prefix
for var in fmu.variables:
    var.name = f"Component1_{var.name}"

fmu.repack("module_prefixed.fmu")
```

---

## Cleaning and Simplification

### Case 3: Remove Debug Variables

**Problem:** Remove all debug variables before distribution.

**CLI Solution:**

```bash
# Remove everything containing "debug" or "test"
fmutool -input model_dev.fmu \
  -remove-regexp ".*[Dd]ebug.*" \
  -remove-regexp ".*[Tt]est.*" \
  -output model_release.fmu
```

**Python API Solution:**

```python
from fmu_manipulation_toolbox.operations import FMU

fmu = FMU("model_dev.fmu")

# Filter variables
fmu.variables = [
    v for v in fmu.variables 
    if not any(keyword in v.name.lower() for keyword in ['debug', 'test', '_tmp'])
]

fmu.repack("model_release.fmu")
```

### Case 4: Simplify Deep Hierarchy

**Problem:** Reduce `Level1.Level2.Level3.Variable` hierarchy to `Level3.Variable`.

**Python API Solution:**

```python
from fmu_manipulation_toolbox.operations import FMU

fmu = FMU("deep.fmu")

for var in fmu.variables:
    parts = var.name.split('.')
    if len(parts) > 2:
        # Keep only last 2 levels
        var.name = '.'.join(parts[-2:])

fmu.repack("flat.fmu")
```

---

## Extraction and Filtering

### Case 5: Extract Only Tunable Parameters

**Problem:** Create FMU containing only adjustable parameters.

**CLI Solution:**

```bash
fmutool -input complete_model.fmu \
  -only-parameters \
  -dump-csv parameters.csv
```

**Python API Solution:**

```python
from fmu_manipulation_toolbox.operations import FMU

fmu = FMU("complete_model.fmu")

# Keep only tunable parameters
fmu.variables = [
    v for v in fmu.variables 
    if v.causality == "parameter" and v.variability == "tunable"
]

fmu.repack("tunable_parameters.fmu")
```

### Case 6: Create Specialized Variants

**Problem:** Create 3 FMUs from one: engine, controller, sensors.

**Python API Solution:**

```python
from fmu_manipulation_toolbox.operations import FMU, OperationKeepOnlyRegexp

# Configuration
variants = {
    "engine": r"^Engine\..*",
    "controller": r"^Controller\..*",
    "sensors": r"^Sensor\..*"
}

base_fmu = "vehicle_complete.fmu"

for name, pattern in variants.items():
    # Load base FMU
    fmu = FMU(base_fmu)
    
    # Filter
    operation = OperationKeepOnlyRegexp(pattern)
    fmu.apply_operation(operation)
    
    # Save variant
    fmu.repack(f"{name}.fmu")
    print(f"✓ Created: {name}.fmu with {len(fmu.variables)} variables")
```

---

## Validation and Quality Control

### Case 7: Complete FMU Audit

**Problem:** Verify compliance and generate report.

**Python API Solution:**

```python
from fmu_manipulation_toolbox.operations import FMU
import json
from datetime import datetime

def audit_fmu(fmu_path, report_path):
    """Generate complete audit report."""
    fmu = FMU(fmu_path)
    
    # Collect information
    report = {
        "audit_date": datetime.now().isoformat(),
        "fmu_path": fmu_path,
        "basic_info": {
            "name": fmu.name,
            "guid": fmu.guid,
            "fmi_version": fmu.fmi_version
        },
        "statistics": {
            "total_variables": len(fmu.variables),
            "parameters": fmu.count_parameters(),
            "inputs": fmu.count_inputs(),
            "outputs": fmu.count_outputs()
        },
        "validation": {
            "xml_valid": fmu.validate_model_description()
        },
        "warnings": []
    }
    
    # Additional checks
    if len(fmu.variables) == 0:
        report["warnings"].append("No variables defined")
    
    # Variables without description
    no_desc = [v.name for v in fmu.variables if not getattr(v, 'description', '')]
    if no_desc:
        report["warnings"].append(f"{len(no_desc)} variables without description")
    
    # Save report
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Report generated: {report_path}")

# Usage
audit_fmu("model.fmu", "audit_report.json")
```

### Case 8: CI/CD Pipeline Validation

**Problem:** Automatically validate FMUs in GitLab CI.

**`.gitlab-ci.yml`:**

```yaml
validate_fmus:
  stage: test
  image: python:3.10
  script:
    - pip install fmu-manipulation-toolbox
    - python validate_all.py
  artifacts:
    reports:
      junit: test-results.xml
```

**`validate_all.py`:**

```python
from fmu_manipulation_toolbox.operations import FMU
from pathlib import Path
import sys

def validate_all_fmus(directory):
    """Validate all FMUs in directory."""
    fmu_dir = Path(directory)
    all_valid = True
    
    for fmu_file in fmu_dir.glob("**/*.fmu"):
        print(f"\nValidating {fmu_file.name}...")
        
        try:
            fmu = FMU(str(fmu_file))
            
            if fmu.validate_model_description():
                print(f"  ✓ {fmu_file.name} is valid")
            else:
                print(f"  ✗ {fmu_file.name} is invalid")
                all_valid = False
                
        except Exception as e:
            print(f"  ✗ Error loading: {e}")
            all_valid = False
    
    return 0 if all_valid else 1

if __name__ == "__main__":
    exit_code = validate_all_fmus("./fmus")
    sys.exit(exit_code)
```

---

## Portability and Distribution

### Case 9: Add Multi-Platform Support (Windows)

**Problem:** 32-bit FMU must also work in 64-bit.

**CLI Solution:**

```bash
fmutool -input model_win32.fmu \
  -add-remoting-win64 \
  -output model_dual.fmu
```

### Case 10: Prepare FMU for Distribution

**Problem:** Completely clean FMU before public distribution.

**Complete Solution:**

```bash
fmutool -input internal_model.fmu \
  -remove-regexp "^_.*" \
  -remove-regexp ".*[Dd]ebug.*" \
  -remove-regexp ".*[Tt]est.*" \
  -remove-regexp "^Internal\..*" \
  -remove-sources \
  -output public_model.fmu

# Verify
fmutool -input public_model.fmu -check
```

---

## Batch Processing

### Case 11: Process Multiple FMUs

**Python Script:**

```python
from pathlib import Path
from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel

def batch_process(input_dir, output_dir):
    """Process all FMUs in directory."""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    for fmu_file in input_path.glob("*.fmu"):
        print(f"Processing {fmu_file.name}...")
        
        try:
            fmu = FMU(str(fmu_file))
            
            # Apply transformation
            operation = OperationStripTopLevel()
            fmu.apply_operation(operation)
            
            # Save
            output_file = output_path / fmu_file.name
            fmu.repack(str(output_file))
            
            print(f"  ✓ Success")
        except Exception as e:
            print(f"  ✗ Error: {e}")

# Usage
batch_process("./input", "./output")
```

---

## General Tips

### Recommended Workflow

1. **Always keep original** - Never overwrite source FMU
2. **Test progressively** - Apply and verify one modification at a time
3. **Validate after each step** - Use `-check` or `validate_model_description()`
4. **Document transformations** - Create reusable scripts
5. **Version FMUs** - Use version control system

### Pre-Distribution Checklist

- [ ] Remove internal variables (`^_.*`)
- [ ] Remove debug variables
- [ ] Remove sources if necessary
- [ ] Check FMI compliance (`-check`)
- [ ] Test in target environment
- [ ] Generate documentation
- [ ] Version the FMU

---

**For more examples and support:**
- 📚 [Complete Documentation](../README.md)
- 🐛 [GitHub Issues](https://github.com/grouperenault/fmu_manipulation_toolbox/issues)
