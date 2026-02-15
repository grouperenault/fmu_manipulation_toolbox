# Installation Guide

This guide walks you through installing **FMU Manipulation Toolbox** on your system.

## System Requirements

### Supported Operating Systems

- ✅ **Windows 10/11** (primary platform, fully tested)
- ✅ **Linux** (Ubuntu 22.04 and compatible distributions)
- ✅ **macOS** (Darwin)

### Required Dependencies

- **Python 3.7 or higher**
- **pip** (Python package manager)

### Optional Dependencies (for compilation from source)

- **C Compiler** compatible with C99 or later
  - Windows: Visual Studio 2019+ or MinGW
  - Linux: GCC 9+ or Clang
  - macOS: Xcode Command Line Tools
- **CMake 3.20 or higher**

## Method 1: Installation via PyPI (Recommended)

This is the simplest and fastest method to install FMU Manipulation Toolbox.

### Standard Installation

```bash
pip install fmu-manipulation-toolbox
```

### Installation with Upgrade

```bash
pip install --upgrade fmu-manipulation-toolbox
```

### Installing a Specific Version

```bash
pip install fmu-manipulation-toolbox==1.9.1
```

### Verify Installation

```bash
# Check installed version
pip show fmu-manipulation-toolbox

# Test commands
fmutool -h
fmutool-gui
fmucontainer -h
```

**Expected Output:**
```
Name: fmu-manipulation-toolbox
Version: 1.9.1
Summary: FMU Manipulation Toolbox
Home-page: https://github.com/grouperenault/fmu_manipulation_toolbox
Author: Renault
License: BSD-2-Clause
```

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

### Step 2: Install Python Dependencies

```bash
pip install -r requirements.txt
```

**Contents of requirements.txt:**
```
lxml>=4.9.0
numpy>=1.21.0
```

### Step 3: Compile C Components

#### On Windows

**With Visual Studio:**
```cmd
mkdir build
cd build
cmake .. -G "Visual Studio 16 2019" -A x64
cmake --build . --config Release
cd ..
```

**With MinGW:**
```cmd
mkdir build
cd build
cmake .. -G "MinGW Makefiles"
cmake --build .
cd ..
```

#### On Linux

```bash
mkdir build
cd build
cmake ..
make
cd ..
```

#### On macOS

```bash
mkdir build
cd build
cmake ..
make
cd ..
```

### Step 4: Install the Package

#### Development Mode Installation (changes take effect immediately)

```bash
pip install -e .
```

#### Standard Installation

```bash
pip install .
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
sudo apt-get install python3-dev build-essential
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
pip search fmu-manipulation-toolbox
# Or visit: https://pypi.org/project/fmu-manipulation-toolbox/
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
pip uninstall fmu-manipulation-toolbox lxml numpy
```

## Supported Python Versions

| Python Version | Support |
|----------------|---------|
| 3.7 | ✅ Supported |
| 3.8 | ✅ Supported |
| 3.9 | ✅ Supported |
| 3.10 | ✅ Supported (Recommended) |
| 3.11 | ✅ Supported |
| 3.12 | ⚠️ In testing |

## Next Steps

Now that FMU Manipulation Toolbox is installed, you can:

1. 🚀 Follow the [Getting Started Guide](getting-started.md)
2. 📖 Consult the [CLI Usage Guide](user-guide/cli-usage.md)
3. 🎨 Discover the [Graphical Interface](user-guide/gui-usage.md)
4. 🐍 Explore the [Python API](user-guide/python-api.md)

## Need Help?

If you encounter installation issues:

1. Check the [Troubleshooting Guide](troubleshooting.md)
2. Review [GitHub Issues](https://github.com/grouperenault/fmu_manipulation_toolbox/issues)
3. Create a new issue with your system details and error message
