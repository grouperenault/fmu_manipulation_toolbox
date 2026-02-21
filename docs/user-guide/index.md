---
title: User Guide
description: Comprehensive guides for all FMU Manipulation Toolbox features — CLI, Python API, and GUI
---

# User Guide

This section provides in-depth documentation for every feature of **FMU Manipulation Toolbox**. Whether you prefer a
graphical interface, the command line, or a Python script, you'll find guidance here.

## Features at a Glance

FMU Manipulation Toolbox offers five main capabilities:

<div class="grid cards" markdown>

-   :material-magnify:{ .lg .middle } __Analysis__

    ---

    Inspect FMU contents, list ports, validate against XSD schemas, and run compliance checks.

    [:octicons-arrow-right-24: CLI Reference](fmutool/cli-usage.md) · 
    [:octicons-arrow-right-24: Python API](fmutool/python-api.md) · 
    [:octicons-arrow-right-24: GUI](fmutool/gui-usage.md)

-   :material-pencil:{ .lg .middle } __Modification__

    ---

    Rename ports, filter variables, strip hierarchy levels, and batch-edit attributes — all without recompilation.

    [:octicons-arrow-right-24: CLI Reference](fmutool/cli-usage.md) · 
    [:octicons-arrow-right-24: Python API](fmutool/python-api.md) · 
    [:octicons-arrow-right-24: GUI](fmutool/gui-usage.md)

-   :material-link-variant:{ .lg .middle } __FMU Containers__

    ---

    Combine multiple FMUs into a single container with automatic or explicit routing, multi-threading, and profiling.

    [:octicons-arrow-right-24: CLI Reference](fmutool/cli-usage.md) · 
    [:octicons-arrow-right-24: Python API](fmutool/python-api.md)

-   :material-chip:{ .lg .middle } __Remoting__

    ---

    Add cross-bitness interfaces (32 ↔ 64-bit) or run an FMU in a separate process via a frontend wrapper.

    [:octicons-arrow-right-24: CLI Reference](fmutool/cli-usage.md) · 
    [:octicons-arrow-right-24: Python API](fmutool/python-api.md) · 
    [:octicons-arrow-right-24: GUI](fmutool/gui-usage.md)

-   :material-check-decagram:{ .lg .middle } __Checker__

    ---

    Validate FMUs against built-in rules or your own custom checkers.

    [:octicons-arrow-right-24: Checker Guide](fmutool/checker.md)

</div>

## Available Interfaces

All features are accessible through the **Command Line Interface** and the **Python API**.
The **Graphical User Interface** supports a subset of operations, as summarized below:

| Feature | CLI | Python API | GUI |
|---|:---:|:---:|:---:|
| Analysis | :material-check: | :material-check: | :material-check: |
| Modification | :material-check: | :material-check: | :material-check: |
| FMU Containers | :material-check: | :material-check: | :material-close: |
| Remoting | :material-check: | :material-check: | :material-check: |
| Checker | :material-check: | :material-check: | :material-check: |

!!! tip "Which interface should I use?"

    - **GUI** — Best for interactive exploration: loading an FMU, visually inspecting its ports, applying quick
      modifications, or adding remoting interfaces.
    - **CLI** — Ideal for automation, scripting, and CI/CD pipelines. Every feature is available from the command line.
    - **Python API** — Offers full programmatic control for complex workflows, batch processing, and custom
      integrations.

## Guides by Topic

### Understand & Modify FMUs

| Guide | Description |
|---|---|
| [CLI Usage](fmutool/cli-usage.md) | Complete reference for all `fmutool` command-line options |
| [GUI Usage](fmutool/gui-usage.md) | Step-by-step guide to the graphical interface |
| [Python API](fmutool/python-api.md) | Programmatic access to analysis and modification operations |
| [Remoting](fmutool/remoting.md) | Add cross-bitness or frontend interfaces to your FMUs |
| [Checker](fmutool/checker.md) | Built-in and custom FMU validation rules |

### FMU Containers

| Guide | Description |
|---|---|
| [Container Concept](fmucontainer/container.md) | How to combine multiple FMUs into a single container |
| [Variable Step Size](fmucontainer/container-vr.md) | Handling variable step sizes inside containers |
| [Datalog](fmucontainer/datalog.md) | Logging simulation data from containers |
| [LS-BUS Support](fmucontainer/ls-bus.md) | Network bus signal routing in containers |

