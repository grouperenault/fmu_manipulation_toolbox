![](fmu_manipulation_toolbox/resources/fmu_manipulation_toolbox.png)

![](https://raw.githubusercontent.com/grouperenault/fmu_manipulation_toolbox/refs/heads/badges/.github/badges/python-version.svg)
![](https://raw.githubusercontent.com/grouperenault/fmu_manipulation_toolbox/refs/heads/badges/.github/badges/fmi-version.svg)
![](https://raw.githubusercontent.com/grouperenault/fmu_manipulation_toolbox/refs/heads/badges/.github/badges/coverage.svg)
[![PyPI version](https://img.shields.io/pypi/v/fmu-manipulation-toolbox)](https://pypi.org/project/fmu-manipulation-toolbox/)
[![License: BSD-2-Clause](https://img.shields.io/badge/License-BSD--2--Clause-blue.svg)](LICENSE.txt)

---

## Table of Contents

- [Overview](#-overview)
- [Installation](#%EF%B8%8F-installation)
- [Graphical User Interface](#%EF%B8%8F-graphical-user-interface)
- [Command Line Interface](#-command-line-interface)
- [API](#-api)
- [Project Architecture](#-project-architecture)
- [Development](#-development)
- [Contributing](#-contributing)
- [Changelog](#-changelog)
- [License](#-license)

---

# 👀 Overview

FMU Manipulation Toolbox is a python package which helps to analyze, modify or combine
[Functional Mock-up Units (FMUs)](http://fmi-standard.org/) without recompilation. It is highly customizable and comes with
a Python API.

FMU Manipulation Toolbox can be used in different ways:
- Using a Graphical User Interface: suitable for end users
- Using a Command Line Interface: useful for scripting and automation
- Using a Python API: the most efficient option for automation (CI/CD, transformation scripts, ...)

Major features:
- Analyze FMU content: list ports and their attributes, check compliance of `ModelDescription.xml` with XSD, etc.
- Alter FMU by modifying its `modelDescription.xml` file. NOTE: manipulating this file can be risky.
  When possible, it is preferable to communicate with the FMU developer and adapt the FMU generation process.
- Add binary interfaces. Typical use case is porting 32-bit FMUs to 64-bit systems (or vice versa). 
- Combine FMUs into [FMU Containers](docs/user-guide/fmucontainer/container.md) and allow your favourite FMI tool to orchestrate complex assembly of FMUs.

FMI versions 2.0 and 3.0 are supported.

# ⚙️ Installation

Two options available to install FMU Manipulation Toolbox:

- (*Easiest option*) Install from PyPI: `pip install fmu-manipulation-toolbox`. This will install the latest
  version of FMU Manipulation Toolbox and all its dependencies. See [PyPI page](https://pypi.org/project/fmu-manipulation-toolbox/).
- Compile and install from [GitHub repository](https://github.com/grouperenault/fmu_manipulation_toolbox). You will need 
  - Python required packages. See [`requirements.txt`](requirements.txt).
  - C compiler (C99 or later)
  - CMake (>= 3.20)


### Supported platforms

FMU Manipulation Toolbox is packaged for:
- Windows 10/11 (primary platform)
- Linux (Ubuntu 22.04)
- Darwin


# 🖥️ Graphical User Interface

FMU Manipulation Toolbox is released with a GUI. You can launch it with the following command `fmutool-gui`

![GUI](docs/gui.png "GUI")

Button color descriptions:
- red: remove information from the `modelDescription.xml`
- orange: alter `modelDescription.xml`
- green: add component into the FMU or check it
- violet: extract and save
- blue: filter actions scope or exit

**Original FMU is never modified**. Use `Save` button to get modified copy of the original FMU.


# 🔧 Command Line Interface

FMU Manipulation Toolbox comes with the following commands:
- `fmutool`: a versatile analysis and manipulation tool for FMUs. 
- `fmutool-gui`: a graphical interface for `fmutool`.
- `fmucontainer`: to combine FMUs inside FMU Containers.
- `fmusplit`: to extract FMUs from a FMU Container.
- (experimental) `datalog2pcap`: to convert logs from FMU containers to PCAP files.


# 🚀 API

You can write your own FMU manipulation scripts. Once you have installed the fmutool module, 
adding the `import` statement lets you access the API:

```python
from fmu_manipulation_toolbox.operations import ...
```


## Remove Top-Level Bus (if any)

Given an FMU with the following I/O structure
```
├── Parameters
│   ├── Foo
│   │   ├── param_A
│   ├── Bar
├── Generator
│   ├── Input_A
│   ├── Output_B
```

The following transformation will result in:
```
├── Foo
│   ├── param_A
├── Bar
├── Input_A
├── Output_B
```

**Note:** removing the top-level bus can lead to name collisions!

The following code will do this transformation: 
```python
from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel

fmu = FMU(r"bouncing_ball.fmu")
operation = OperationStripTopLevel()
fmu.apply_operation(operation)
fmu.repack(r"bouncing_ball-modified.fmu")
```

### Extract Names and Write a CSV

The following code will dump all FMU scalar names into a CSV:

```python
from fmu_manipulation_toolbox.operations import FMU, OperationSaveNamesToCSV

fmu = FMU(r"bouncing_ball.fmu")
operation = OperationSaveNamesToCSV(r"bouncing_ball.csv")
fmu.apply_operation(operation)
```

The produced CSV contains 2 columns so it can be reused in the next transformation.
The 2 columns are identical.

```csv
name;newName;valueReference;causality;variability
h;h;0;local;continuous
der(h);der(h);1;local;continuous
v;v;2;local;continuous
der(v);der(v);3;local;continuous
g;g;4;parameter;fixed
e;e;5;parameter;tunable
```


## Read CSV and Rename FMU Ports

The CSV file should contain 2 columns:
1. the current name
2. the new name

```python
from fmu_manipulation_toolbox.operations import FMU, OperationRenameFromCSV

fmu = FMU(r"bouncing_ball.fmu")
operation = OperationRenameFromCSV(r"bouncing_ball-modified.csv")
fmu.apply_operation(operation)
fmu.repack(r"bouncing_ball-renamed.fmu")
```

### Available Operations

All operations are located in [`operations.py`](fmu_manipulation_toolbox/operations.py):

| Operation | Description |
|---|---|
| `OperationStripTopLevel` | Remove the top-level bus from the FMU I/O structure |
| `OperationMergeTopLevel` | Merge the top-level bus into the FMU I/O structure |
| `OperationSaveNamesToCSV` | Dump all scalar names into a CSV file |
| `OperationRenameFromCSV` | Rename FMU ports according to a CSV mapping |
| `OperationRemoveRegexp` | Remove variables matching a regular expression |
| `OperationKeepOnlyRegexp` | Keep only variables matching a regular expression |
| `OperationSummary` | Print a summary of the FMU |
| `OperationRemoveSources` | Remove source files embedded in the FMU |
| `OperationTrimUntil` | Trim variable names up to a given separator |

> 📖 Full documentation is available on the [documentation website](https://grouperenault.github.io/fmu_manipulation_toolbox/).


# 🏗️ Project Architecture

```
fmu_manipulation_toolbox/      # Python package
├── cli/                       #   Command Line Interface modules
├── gui/                       #   Graphical User Interface (PySide6)
├── resources/                 #   Pre-built binaries, XSD schemas, icons
├── operations.py              #   FMU operations (rename, filter, etc.)
├── container.py               #   FMU Container logic
├── assembly.py                #   Assembly description parsing
├── checker.py                 #   FMU compliance checker
├── remoting.py                #   32/64-bit remoting support
└── ...
container/                     # C source code for FMU Container runtime
remoting/                      # C source code for Remoting (client/server)
fmi/                           # FMI C headers (2.0 & 3.0)
tests/                         # Test suite (pytest)
docs/                          # Documentation source (MkDocs Material)
```

Key design points:
- **Pure Python manipulation**: analyzing and altering FMUs is done entirely in Python — no compilation required.
- **Native C code**: the FMU Container runtime and the Remoting feature are implemented in C (C99). These are compiled with CMake and shipped as pre-built binaries in `resources/`.
- **FMI 2.0 & 3.0**: both FMI standards are supported across all features.


# 🧑‍💻 Development

### Prerequisites

- Python ≥ 3.9
- C compiler (C99 or later) — only needed for building the container/remoting binaries
- CMake ≥ 3.20 — only needed for building the C code

### Setup

```bash
# Clone the repository
git clone https://github.com/grouperenault/fmu_manipulation_toolbox.git
cd fmu_manipulation_toolbox

# Install dependencies
pip install -r requirements.txt
```

### Building C code (optional)

The container and remoting binaries can be built with CMake:

```bash
cd container
mkdir -p build && cd build
cmake ..
cmake --build .
```

Same process applies for the `remoting/` directory.

### Running tests

```bash
pytest tests/test_suite.py
```

With coverage report:
```bash
pytest tests/test_suite.py --cov=fmu_manipulation_toolbox --cov-report=html
```

### Building documentation locally

The documentation uses [MkDocs Material](https://squidfunk.github.io/mkdocs-material/):

```bash
pip install mkdocs-material
mkdocs serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.


# 🤝 Contributing

Contributions are welcome! Please read the [Contributing Guide](CONTRIBUTING.md) for details on
how to report issues, suggest improvements, and interact with the development team.

> **Note:** For legal reasons, pull requests cannot be accepted. If you have ideas for improvements,
> please create an issue or get in touch with the development team.


# 📋 Changelog

See the [Changelog](CHANGELOG.md) for a detailed list of changes across versions.


# 📄 License

This project is licensed under the **BSD-2-Clause** license. See [LICENSE.txt](LICENSE.txt) for details.

Copyright © 2024-2026 Renault SAS
