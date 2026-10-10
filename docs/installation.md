# Installation Guide

This guide walks you through installing **FMU Manipulation Toolbox** on your system.

## System Requirements

### Supported Operating Systems

- ✅ **Windows 10/11** (primary platform, fully tested)
- ✅ **Linux** (Ubuntu 22.04 and compatible distributions)
- ✅ **macOS** (Darwin)

### Required Dependencies

- **Python 3.10 or higher** (see [Supported Python Versions](#supported-python-versions))
- **pip** (Python package manager); pip 21.3 or higher for an installation from source in development mode

### Optional Dependencies (for compilation from source)

- **C Compiler** with C23 support (for the container) or C99 (for remoting)
  - Windows: Visual Studio 2022+ or MinGW
  - Linux: GCC 13+ or Clang 16+
  - macOS: Xcode Command Line Tools (with recent Clang)
- **CMake 3.21 or higher**

## Method 1: Installation via PyPI (Recommended)

This is the simplest and fastest method to install FMU Manipulation Toolbox.

### Standard Installation

```bash
pip install fmu-manipulation-toolbox
```

This installs the **CLI** (`fmutool`, `fmucontainer`, `fmusplit`, `datalog2pcap`) and the **Python API**. It does
**not** pull in the GUI toolkit ([PySide6](https://pypi.org/project/PySide6/)), which is a heavy dependency only
needed by the graphical tools.

### Installation with the Graphical User Interfaces

If you also want to use `fmutoolbox`, `fmutool-gui`, `fmueditor` or `fmucontainer-gui`, install the `gui` extra:

```bash
pip install "fmu-manipulation-toolbox[gui]"
```

### Installation with the AI Assistant (MCP server)

The toolbox can expose its FMU Container assembly capabilities to an AI agent through an
[MCP server](user-guide/fmucontainer/ai-assistant.md), either as a standalone command
(`fmutool-mcp`, no GUI needed) or from the Container Builder window. This optional
feature requires the `fastmcp` package, available through the `mcp` extra:

```bash
# Standalone MCP server only (no GUI)
pip install "fmu-manipulation-toolbox[mcp]"

# MCP server + the graphical tools
pip install "fmu-manipulation-toolbox[gui,mcp]"
```

!!! tip "Which install do I need?"

    - **CLI / Python API only** (scripting, CI/CD, servers): `pip install fmu-manipulation-toolbox`
    - **GUI tools** (interactive use): `pip install "fmu-manipulation-toolbox[gui]"`
    - **AI Assistant alone** (MCP server for Claude Desktop, VS Code, ...):
      `pip install "fmu-manipulation-toolbox[mcp]"`
    - **GUI tools + AI Assistant** (MCP server): `pip install "fmu-manipulation-toolbox[gui,mcp]"`

### Installation with Upgrade

```bash
pip install --upgrade "fmu-manipulation-toolbox[gui]"
```

### Installing a Specific Version

```bash
pip install fmu-manipulation-toolbox==1.9.2
```

### Verify Installation

```bash
# Check installed version
pip show fmu-manipulation-toolbox

# Test CLI commands
fmutool -h
fmucontainer -h

# Test GUI commands (requires the `gui` extra, see above)
fmutoolbox         # Launcher with all GUI tools
fmutool-gui        # FMU analysis & modification
fmueditor          # FMU variable editor
fmucontainer-gui   # FMU container builder

# Test the MCP server (requires the `mcp` extra)
fmutool-mcp --help
```

**Expected Output** (excerpt):
```
Name: fmu_manipulation_toolbox
Version: 1.9.4.2
Summary: FMU Manipulation Toolbox is a python package which helps to analyze, modify, validate, combine or split ...
License-Expression: BSD-2-Clause
```

!!! note
    The version is displayed without the `V` prefix of the git tags (`V1.9.4.2` → `1.9.4.2`). A package installed
    from a git checkout gets a development version computed from the last tag, e.g. `1.9.4.3.dev79+g230faf6`.

## Method 2: Installation from Source

This method is recommended if you want to:
- Contribute to the project
- Use the latest development version
- Modify the source code

### Step 1: Clone the Repository

```bash
git clone https://github.com/grouperenault/fmu_manipulation_toolbox.git
cd fmu_manipulation_toolbox
```

### Step 2: Install the Package and its Dependencies

```bash
pip install -e ".[all]"
```

This installs the package in development mode (see [Step 4](#step-4-install-the-package)) with all its extras:

| Extra | Contents |
|-------|----------|
| *(none)* | `xmlschema`, `elementpath`, `colorama`: CLI and Python API |
| `gui` | `PySide6`: graphical tools |
| `mcp` | `fastmcp`, `uvicorn`: MCP server and AI Assistant |
| `test` | `pytest`, `pytest-qt`, `pytest-cov`, `coverage-badge`, `fmpy`, `numpy`, `PySide6` |
| `all` | `gui` + `mcp` + `test` |

The dependencies and their versions are declared in `pyproject.toml`.

!!! note
    `pip install -r requirements.txt` is equivalent: the file only contains `-e .[all]`. The package must be
    installed to run the tests: they import the installed `fmu_manipulation_toolbox`.

### Step 3: Compile C Components

Two native components are written in C and should be compiled. The container requires a C23 compatible compiler, while the remoting
code requires a C99 compatible compiler that should be able to produce 64-bit and 32-bit objects.


#### Container code

The following commands can be used on all supported platforms:
```bash
cd container
mkdir build
cd build
cmake ..
cmake --build .
cd ..
```

#### Remoting code

=== "Windows"
  
    ```bash
    cd remoting
    mkdir build32
    cd build32
    cmake .. -A Win32
    cmake --build .
    cd ..
    mkdir build64
    cd build64
    cmake .. -A x64
    cmake --build .
    cd ..
    ```

=== "Linux"

    ```bash
    cd remoting
    mkdir build32
    cd build32
    cmake .. -DBUILD_32=ON
    cmake --build .
    cd ..
    mkdir build64
    cd build64
    cmake ..
    cmake --build .
    cd ..
    ```

=== "MacOS"
    The remoting code is not supported on MacOS.


### Step 4: Install the Package

#### Development Mode Installation (changes take effect immediately)

Requires pip 21.3 or higher (editable installation of a `pyproject.toml` project). Skip this step if you ran
`pip install -e ".[all]"` at step 2.

```bash
# CLI/API only
pip install -e .

# With GUI and/or test dependencies
pip install -e ".[gui]"
pip install -e ".[gui,test]"
# With the AI Assistant (MCP server)
pip install -e ".[gui,mcp]"
```

#### Standard Installation

```bash
pip install .
# or, with the GUI toolkit:
pip install ".[gui]"
```

## Installation in a Virtual Environment (Recommended)

Using a virtual environment avoids dependency conflicts.

### With venv (Python standard)

```bash
# Create virtual environment
python -m venv fmu_env

# Activate environment
# On Windows:
fmu_env\Scripts\activate
# On Linux/macOS:
source fmu_env/bin/activate

# Install FMU Manipulation Toolbox
pip install fmu-manipulation-toolbox

# Deactivate environment (when done)
deactivate
```

### With conda

```bash
# Create environment
conda create -n fmu_env python=3.10

# Activate environment
conda activate fmu_env

# Install FMU Manipulation Toolbox
pip install fmu-manipulation-toolbox

# Deactivate environment
conda deactivate
```

## Troubleshooting Installation Issues

### Issue: `pip install` fails

**Error:** `error: Microsoft Visual C++ 14.0 or greater is required`

**Windows Solution:**
1. Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/)
2. Or install a pre-compiled version: `pip install fmu-manipulation-toolbox --only-binary :all:`

**Linux Solution:**
```bash
sudo apt-get update
sudo apt-get install python3-dev build-essential gcc-multilib
```

**macOS Solution:**
```bash
xcode-select --install
```

### Issue: Commands not found after installation

**Solution:**

Verify that the Python scripts directory is in your PATH:

```bash
# Find the directory
python -m site --user-base

# Add to PATH
# Windows: Add %APPDATA%\Python\Python3X\Scripts
# Linux/macOS: Add ~/.local/bin to your PATH
```

### Issue: Permission denied (Linux/macOS)

**Solution:**
```bash
# Option 1: User installation
pip install --user fmu-manipulation-toolbox

# Option 2: With sudo (not recommended)
sudo pip install fmu-manipulation-toolbox
```

## Updating

### Check Available Version

```bash
# Check current installed version
pip show fmu-manipulation-toolbox

# Check latest version on PyPI:
# https://pypi.org/project/fmu-manipulation-toolbox/
```

### Update to Latest Version

```bash
pip install --upgrade fmu-manipulation-toolbox
```

### Downgrade to Previous Version

```bash
pip install fmu-manipulation-toolbox==1.9.0
```

## Uninstallation

```bash
pip uninstall fmu-manipulation-toolbox
```

For complete uninstallation (with dependencies):

```bash
pip uninstall fmu-manipulation-toolbox xmlschema elementpath colorama

# If you installed the `gui` and/or `test` extras, also remove:
pip uninstall PySide6 fmpy

# If you installed the `mcp` extra (AI Assistant), also remove:
pip uninstall fastmcp
```

## Supported Python Versions

| Python Version | Support                   |
|----------------|---------------------------|
| 3.9            | ❌ Not supported: version 1.9.4.2 at most |
| 3.10           | ✅ Supported               |
| 3.11           | ✅ Supported               |
| 3.12           | ✅ Supported               |
| 3.13           | ✅ Supported (Recommended) |

!!! note "Python 3.9"
    Python 3.9 reached its end of life in October 2025. Version 2.0 requires Python 3.10 or higher; on Python 3.9,
    `pip install fmu-manipulation-toolbox` automatically installs 1.9.4.2, the last release supporting it.


## Next Steps

Now that FMU Manipulation Toolbox is installed, you can:

1. 🚀 Follow the [Getting Started Guide](tutorials/getting-started.md)
2. 📖 Consult the [CLI Usage Guide](user-guide/fmutool/cli-usage.md)
3. 🎨 Discover the [Graphical Interface](user-guide/fmutool/gui-usage.md)
4. 🐍 Explore the [Python API](user-guide/fmutool/python-api.md)

## Need Help?

If you encounter installation issues:

1. Check the [Troubleshooting Guide](help/troubleshooting.md)
2. Review [GitHub Issues](https://github.com/grouperenault/fmu_manipulation_toolbox/issues)
3. Create a new issue with your system details and error message
