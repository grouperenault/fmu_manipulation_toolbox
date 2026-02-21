# Troubleshooting Guide

This guide helps you resolve common issues with **FMU Manipulation Toolbox**.

## Installation Issues


### ❌ Command fmutool not found

**Symptom:**
```
'fmutool' is not recognized as an internal or external command
```

**Cause:** Python scripts directory is not in PATH.

**Solution:**

**Windows:**
```cmd
# Find scripts path
python -m site --user-base
# Add %APPDATA%\Python\Python3X\Scripts to your PATH

# Or use directly:
python -m fmu_manipulation_toolbox.fmutool -h
```

**Linux/macOS:**
```bash
# Add to PATH in ~/.bashrc or ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"

# Reload
source ~/.bashrc
```


## Modification Issues

### ❌ Modifications not applied

**Symptom:** Output FMU is identical to original.

**Cause:** Missing `-output` option

**Solution:**
```bash
# ❌ INCORRECT (no save)
fmutool -input module.fmu -remove-toplevel

# ✅ CORRECT
fmutool -input module.fmu -remove-toplevel -output module-modified.fmu
```

### ❌ CSV renaming error

**Symptom:**
```
Error: Port 'xyz' not found in CSV file
```

**Solutions:**

1. **Incorrect CSV format**

```bash
# Generate correct CSV first
fmutool -input module.fmu -dump-csv ports.csv

# Verify format (must contain: name;newName;...)
head ports.csv
```

2. **File encoding**

CSV must be **UTF-8** encoded with **semicolon (;)** separator

3. **Missing names in CSV**

```bash
# Regenerate complete CSV
fmutool -input module.fmu -dump-csv ports_complete.csv
```

### ❌ Name collision after modification

**Symptom:**
```
Error: Duplicate variable name after renaming: 'Temperature'
```

**Cause:** Two different variables have the same new name.

**Solution:**

Check your renaming CSV:
```csv
# ❌ INCORRECT (two variables → same name)
Motor.Temperature;Temperature;0;output;continuous
Controller.Temperature;Temperature;1;output;continuous

# ✅ CORRECT (distinct names)
Motor.Temperature;Motor_Temperature;0;output;continuous
Controller.Temperature;Controller_Temperature;1;output;continuous
```

## GUI Issues

### ❌ GUI won't launch

**Symptom:**
```
ModuleNotFoundError: No module named 'PySide6'
```

**Solution:**

```bash
pip install PySide6
```


## Python API Issues

### ❌ Operations don't modify the FMU

**Wrong code:**
```python
from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel

fmu = FMU("module.fmu")
operation = OperationStripTopLevel()
# ❌ Operation not applied!
fmu.repack("output.fmu")
```

**Correct code:**
```python
from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel

fmu = FMU("module.fmu")
operation = OperationStripTopLevel()
fmu.apply_operation(operation)  # ✅ Apply the operation!
fmu.repack("output.fmu")
```

## Need More Help?

1. Check the [complete documentation](../user-guide/index.md)
2. Search [GitHub Issues](https://github.com/grouperenault/fmu_manipulation_toolbox/issues)
3. Create a new issue with system details and error message

---

**Last updated:** February 2026
