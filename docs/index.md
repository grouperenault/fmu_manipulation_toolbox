---
title: Overview
description: FMU Manipulation Toolbox - Professional tool for analyzing, modifying, and combining FMUs without recompilation
---

# ![](fmu_manipulation_toolbox.png)

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } __Quick Start__

    ---

    Get up and running with FMU Manipulation Toolbox in minutes

    [:octicons-arrow-right-24: Getting Started](tutorials/getting-started.md)

-   :material-package-variant:{ .lg .middle } __Installation__

    ---

    Install on Windows, Linux, or macOS with pip or from source

    [:octicons-arrow-right-24: Installation Guide](installation.md)

-   :material-book-open-variant:{ .lg .middle } __User Guides__

    ---

    Learn to use the GUI, CLI, or Python API

    [:octicons-arrow-right-24: Browse Guides](user-guide/index.md)

-   :material-lightbulb-on:{ .lg .middle } __Examples__

    ---

    Explore practical use cases and ready-to-use solutions

    [:octicons-arrow-right-24: View Examples](examples/examples.md)

</div>

## Overview

FMU Manipulation Toolbox is a comprehensive Python toolkit designed to **analyze, modify, and combine** 
[Functional Mock-up Units (FMUs)](http://fmi-standard.org/){:target="_blank"} without requiring recompilation. Built for engineers and 
developers working with FMI-compliant models, it provides three powerful interfaces:

=== "Graphical Interface"

    ![](gui.png)
    Perfect for interactive, visual manipulation of FMUs with an intuitive point-and-click interface.

=== "Command Line"

    ```bash
    fmutool -input module.fmu -remove-toplevel -output module-flat.fmu
    ```
    
    Ideal for automation, scripting, and integration into build pipelines.

=== "Python API"

    ```python
    from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel
    
    fmu = FMU("module.fmu")
    fmu.apply_operation(OperationStripTopLevel())
    fmu.repack("module-flat.fmu")
    ```
    
    Full programmatic control for complex workflows and custom integrations.


## Key Features

<div class="grid cards" markdown>

-   :material-magnify:{ .lg .middle } __FMU Analysis__

    ---

    - List all ports and their attributes
    - Validate `modelDescription.xml` against XSD schema
    - Check FMI compliance and custom rules
    - Extract statistics and metadata

-   :material-pencil:{ .lg .middle } __FMU Modification__

    ---

    - Rename ports individually or in batch via CSV
    - Filter variables with regular expressions
    - Remove hierarchy levels
    - Modify variable attributes
    - Remove sources

-   :material-link-variant:{ .lg .middle } __FMU Containers__

    ---

    - Combine multiple FMUs into one
    - Define automatic or explicit connections
    - Multi-threading support
    - Performance profiling

-   :material-chip:{ .lg .middle } __Binary Interfaces__

    ---

    - Add 32-bit interface to 64-bit FMU (Windows)
    - Add 64-bit interface to 32-bit FMU (Windows)
    - Frontend mode for separate process execution

</div>

## Supported Platforms & Standards

<div class="grid" markdown>

<div markdown>

### FMI Versions

- [x] FMI 2.0 Co-Simulation
- [x] FMI 3.0 Co-Simulation

</div>

<div markdown>

### Operating Systems

- [x] Windows 10/11 (primary platform)
- [x] Linux (Ubuntu 22.04+)
- [x] macOS (Darwin)

</div>

</div>

## Installation

Install with a single command:

```bash
pip install fmu-manipulation-toolbox
```

!!! tip "Virtual Environment Recommended"
    
    For production use, we recommend installing in a virtual environment to avoid dependency conflicts:
    
    ```bash
    python -m venv fmu_env
    source fmu_env/bin/activate  # On Windows: fmu_env\Scripts\activate
    pip install fmu-manipulation-toolbox
    ```

For detailed installation instructions, platform-specific notes, and troubleshooting, see the 
[Installation Guide](installation.md).

## Quick Example

Here's how to analyze and modify an FMU in just a few lines:

=== "Python"

    ```python
    from fmu_manipulation_toolbox.operations import FMU
    
    # Load and analyze
    fmu = FMU("my_model.fmu")

    # Display informations about the FMU
    fmu.summary()
    
    # Remove internal variables
    operation = OperationRemoveRegexp(r"^_.*")
    fmu.apply_operation(operation)
    
    # Save modified FMU
    fmu.repack("my_model_clean.fmu")
    ```

=== "Command Line"

    ```bash
    # Analyze FMU
    fmutool -input my_model.fmu -summary
    
    # Remove internal variables
    fmutool -input my_model.fmu \
      -remove-regexp "^_.*" \
      -output my_model_clean.fmu
    
    # Verify result
    fmutool -input my_model_clean.fmu -check
    ```

## Why FMU Manipulation Toolbox?

!!! success "Key Benefits"

    **No Recompilation Required**
    :   Modify FMUs without access to source code or compilation toolchain

    **Multiple Interfaces**
    :   Choose the interface that fits your workflow: GUI, CLI, or Python API

    **Open Source**
    :   BSD-2-Clause license allows both commercial and non-commercial use


## What's Next?

<div class="grid cards" markdown>

-   [:octicons-rocket-24: __Getting Started__](tutorials/getting-started.md)
    
    New to FMU Manipulation Toolbox? Start here!

-   [:octicons-book-24: __User Guides__](user-guide/index.md)
    
    Deep dive into GUI, CLI, and Python API

-   [:octicons-light-bulb-24: __Examples__](examples/examples.md)
    
    Learn from practical, real-world scenarios

-   [:octicons-question-24: __Troubleshooting__](help/troubleshooting.md)
    
    Find solutions to common issues

</div>

## Community & Support

<div class="grid" markdown>

<div markdown>

### Get Help

- :material-bug: [Report an Issue](https://github.com/grouperenault/fmu_manipulation_toolbox/issues){:target="_blank"}
- :material-chat-question: [Discussions](https://github.com/grouperenault/fmu_manipulation_toolbox/discussions){:target="_blank"}

</div>

<div markdown>

### Contribute

- :material-source-branch: [Contribution Guidelines](https://github.com/grouperenault/fmu_manipulation_toolbox/blob/main/CONTRIBUTING.md)
- :material-file-document-edit: [Improve Documentation](https://github.com/grouperenault/fmu_manipulation_toolbox/edit/main/docs/){:target="_blank"}
- :material-star: [Star on GitHub](https://github.com/grouperenault/fmu_manipulation_toolbox){:target="_blank"}

</div>

</div>

---

<div align="center" markdown>

**FMU Manipulation Toolbox** is maintained by [Renault Group](https://github.com/grouperenault){:target="_blank"}

[Getting Started](tutorials/getting-started.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/grouperenault/fmu_manipulation_toolbox){ .md-button }

</div>
