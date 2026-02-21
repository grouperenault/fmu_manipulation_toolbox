# Common Use Cases

This guide presents practical solutions to frequently encountered problems when manipulating FMUs.


## Migration and Renaming

### Change Naming Convention

**Problem:** Convert from `CamelCase` to `snake_case` for all ports.

=== "CLI Solution"
    
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

---

## Cleaning and Simplification

### Remove Debug Variables

**Problem:** Remove all debug variables before distribution.

=== "CLI Solution"

    ```bash
    # Remove everything containing "debug" or "test"
    fmutool -input model_dev.fmu \
      -remove-regexp ".*[Dd]ebug.*" \
      -remove-regexp ".*[Tt]est.*" \
      -output model_release.fmu
    ```

=== "Python API Solution"

```python
from fmu_manipulation_toolbox.operations import FMU, OperationRemoveRegexp

fmu = FMU("model_dev.fmu")

fmu.apply_operation(OperationRemoveRegexp(r".*[Dd]ebug.*"))
fmu.apply_operation(OperationRemoveRegexp(r".*[Tt]est.*"))

fmu.repack("model_release.fmu")
```


### Simplify Deep Hierarchy

**Problem:** Reduce `Level1.Level2.Level3.Variable` hierarchy to `Level3.Variable`.

=== "CLI Solution"
    ```bash
    fmutool -input deep.fmu \
      -remove-toplevel \
      -remove-toplevel \
      -output flat.fmu
    ```

=== "Python API Solution"
    
    ```python
    from fmu_manipulation_toolbox.operations import FMU, OperationMergeTopLevel
    
    fmu = FMU("deep.fmu")
    
    fmu.apply_operation(OperationMergeTopLevel()) # remove first level
    fmu.apply_operation(OperationMergeTopLevel()) # remove second level
    
    fmu.repack("flat.fmu")
    ```

---

## Extraction and Filtering

### Extract Only Tunable Parameters

**Problem:** Create FMU containing only adjustable parameters.

=== "CLI Solution"
    
    ```bash
    fmutool -input complete_model.fmu \
      -only-parameters \
      -dump-csv parameters.csv
    ```

=== "Python API Solution"

    ```python
    from fmu_manipulation_toolbox.operations import FMU, OperationSaveNamesToCSV
    
    fmu = FMU("complete_model.fmu")
    fmu.apply_operation(OperationSaveNamesToCSV("parameter.csv"), apply_on=["parameter"])
    ```

---

## Portability and Distribution

### Add Multi-Platform Support (Windows)

**Problem:** 32-bit FMU must also work in 64-bit.

=== "CLI Solution"
    
    ```bash
    fmutool -input model_win32.fmu \
      -add-remoting-win64 \
      -output model_dual.fmu
    ```

=== "Python API Solution"
    ```python
    from fmu_manipulation_toolbox.operations import FMU
    from fmu_manipulation_toolbox.remoting import OperationAddRemotingWin64
    
    fmu = FMU("model_win32.fmu")
    fmu.apply_operation(OperationAddRemotingWin64())
    fmu.repack("model_dual.fmu")
    ```


### Prepare FMU for Distribution

**Problem:** Completely clean FMU before public distribution.

=== "CLI Solution"

    ```bash
    fmutool -input internal_model.fmu \
      -remove-all \
      -only-locals \
      -remove-sources \
      -output public_model.fmu
    
    # Verify
    fmutool -input public_model.fmu -check
    ```

=== "Python API Solution"
```python
from fmu_manipulation_toolbox.operations import FMU, OperationRemoveSources, OperationRemoveRegexp
from fmu_manipulation_toolbox.checker import OperationGenericCheck

fmu = FMU("internal_model.fmu")
fmu.apply_operation(OperationRemoveSources())
fmu.apply_operation(OperationRemoveRegexp(r".*"), apply_on=["local"])
fmu.apply_operation(OperationGenericCheck())
fmu.repack("public_model.fmu")
```

---

## General Tips

### Recommended Workflow

1. **Always keep original** - Never overwrite source FMU
2. **Test progressively** - Apply and verify one modification at a time
3. **Validate after each step** - Use `-check` or `OperationGenericCheck()`
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
- 📚 [Complete Documentation](../user-guide/index.md)
- 🐛 [GitHub Issues](https://github.com/grouperenault/fmu_manipulation_toolbox/issues)
