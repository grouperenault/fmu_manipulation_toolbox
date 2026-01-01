![](fmu_manipulation_toolbox/resources/fmu_manipulation_toolbox.png)

![](https://raw.githubusercontent.com/grouperenault/fmu_manipulation_toolbox/refs/heads/badges/.github/badges/python-version.svg)
![](https://raw.githubusercontent.com/grouperenault/fmu_manipulation_toolbox/refs/heads/badges/.github/badges/fmi-version.svg)
![](https://raw.githubusercontent.com/grouperenault/fmu_manipulation_toolbox/refs/heads/badges/.github/badges/coverage.svg)

# 👀 Overview

FMU Manipulation Toolbox is a python package which helps to analyze, modify or combine
[Functional Mock-up Units (FMUs)](http://fmi-standard.org/) without recompilation. It is highly customizable and comes with
a Python API.

FMU Manipulation Toolbox can be used in different ways:
- Using a Graphical User Interface: suitable for end users
- Using a Command Line Interface: useful for scripting and automation
- Using a Python API: the most efficient option for automation (CI/CD, transformation scripts, ...))

Major features:
- Analyze FMU content: list ports and their attributes, check compliance of `ModelDescription.xml` with XSD, etc.
- Alter FMU by modifying its `modelDescription.xml` file. NOTE: manipulating this file can be a risky.
  When possible, it is preferable to communicate with the FMU developer and adapt the FMU generation process.
- Add binary interfaces. Typical use case is porting a 32-bit FMUs to 64-bit systems (or vice et versa). 
- Combine FMUs into [FMU Containers](doc/container.md) and allow your favourite FMI tool to orchestrate complex assembly of FMUs.

FMI versions 2.0 and 3.0 are supported.

# ⚙️ Installation

Two options available to install FMU Manipulation Toolbox:

- (*Easiest option*) Install with from PyPI: `pip install fmu-manipulation-toolbox`. This will install the latest
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

![GUI](doc/gui.png "GUI")

Button colors descriptions:
- red: remove information from the `modelDescription.xml`
- orange: alter `modelDescription.xml`
- green: add component into the FMU or check it
- violet: extract and save
- blue: filter actions scope or exit

**Original FMU is never modified**. Use `Save` button to get modified copy of the original FMU.


# 🔧 Command Line Interface

FMU Manipulation Toolbox comes with 2 commands:
- `fmutool`: a versatile analysis and manipulation tool for FMU.
- `fmucontainer`: group FMUs inside FMU Containers. (see [container/README.md](container/README.md))
- `fmusplit: to extract FMUs from a FMU Container.


## Analysis and Manipulation tool:

You can use `fmutool -help` to get usage:

```
usage: fmutool [-h] -input path/to/module.fmu [-output path/to/module-modified.fmu] [-remove-toplevel] [-merge-toplevel]
               [-trim-until prefix] [-remove-regexp regular-expression] [-keep-only-regexp regular-expression]
               [-remove-all] [-dump-csv path/to/list.csv] [-rename-from-csv path/to/translation.csv]
               [-add-remoting-win32] [-add-remoting-win64] [-add-frontend-win32] [-add-frontend-win64]
               [-extract-descriptor path/to/saved-modelDescriptor.xml] [-remove-sources] [-only-parameters]
               [-only-inputs] [-only-outputs] [-summary] [-check]

fmutool is program to manipulate FMU.

optional arguments:
  -h, -help                         display help.
  -input path/to/module.fmu         this option is mandatory to specify the filename of the FMU to be loaded. (default:
                                    None)
  -output path/to/module-modified.fmu
                                    this option is used to specify the filename of the FMU to be created after
                                    manipulations. If it is not provided, no new fmu will be saved and some
                                    manipulations can be lost. (default: None)
  -remove-toplevel                  rename the ports of the input fmu by striping all characters until the first '.'
                                    (toplevel bus). If no '.' is present, the port won't be renamed. Resulting fmu
                                    should be saved by using -output option. Note: before version 1.2.6, this option was
                                    spelled -remove-toplel. (default: None)
  -merge-toplevel                   replace first '.' by an '_' on every port name. (default: None)
  -trim-until prefix                remove a prefix from port name. Example '-trim-until _' : will rename port names of
                                    the FMU by removing part of the name until the first '_'. Prefix can be longer than
                                    a single character. (default: None)
  -remove-regexp regular-expression
                                    remove ports that match the regular-expression. Other ports will be kept. Resulting
                                    fmu should be saved by using -output option. This option is available from version
                                    1.1. See https://en.wikipedia.org/wiki/Regular_expression to have more detail of
                                    expected format. (default: None)
  -keep-only-regexp regular-expression
                                    keep only ports that match the regular-expression. Other ports will be removed.
                                    Resulting fmu should be saved by using -output option. This option is available from
                                    version 1.1. See https://en.wikipedia.org/wiki/Regular_expression to have more
                                    detail of expected format. (default: None)
  -remove-all                       equivalent to '-remove-regexp .*'. Typical use case is to use it with -only-*
                                    options. Example: in order ro suppress all parameters of FMU: -only-parameters
                                    -remove-all (default: None)
  -dump-csv path/to/list.csv        list all names of the ports of the input fmu and store them inside path/to/list.csv.
                                    This file is ';' separated. It contains two columns in order to be easily reused by
                                    -rename-from-csv option. (default: None)
  -rename-from-csv path/to/translation.csv
                                    rename the ports of fmu accordingly to path/to/translation.csv. This file is ';'
                                    separated. It contains two columns. First column contains original names. Second
                                    column contains new names. * If a port is not found in the file, it won't be
                                    renamed. This is working with version > 1.2.6. It is safer to keep ALL port in csv.
                                    * If the new name is empty, the port will be removed. This is working starting
                                    version 1.1. * If a name in the file is not present in input FMU, it will be
                                    ignored. (no warning will be issued). Resulting fmu should be saved by using -output
                                    option. (default: None)
  -add-remoting-win32               this option is windows specific. It will add 'win32' interface to a 'win64' fmu.
                                    Please upgrade to version 1.2.1 before using this option. Resulting fmu should be
                                    saved by using -output option. (default: None)
  -add-remoting-win64               this option is windows specific. It will add 'win64' interface to a 'win32' fmu.
                                    Please upgrade to version 1.2.1 before using this option. Resulting fmu should be
                                    saved by using -output option. (default: None)
  -add-frontend-win32               this option is windows specific. It can be used with 'win32' fmu. At simulation
                                    time, the FMU will spawn a dedicated process tu run the model. This option is
                                    available from version 1.4. Resulting fmu should be saved by using -output option.
                                    (default: None)
  -add-frontend-win64               this option is windows specific. It can be used with 'win64' fmu. At simulation
                                    time, the FMU will spawn a dedicated process tu run the model. This option is
                                    available from version 1.4. Resulting fmu should be saved by using -output option.
                                    (default: None)
  -extract-descriptor path/to/saved-modelDescriptor.xml
                                    save the modelDescription.xml into the specified location. If modification options
                                    (like -rename-from-csv or -remove-toplevel are set), the saved file will contain
                                    modification. This option is available from version 1.1. (default: None)
  -remove-sources                   Remove sources folder from the FMU. This option is available from version 1.3.
                                    (default: None)
  -only-parameters                  apply operation only on ports with causality = 'parameter'. This option is available
                                    from version 1.3. (default: None)
  -only-inputs                      apply operation only on ports with causality = 'parameter'. This option is available
                                    from version 1.3. (default: None)
  -only-outputs                     apply operation only on ports with causality = 'output'. This option is available
                                    from version 1.3. (default: None)
  -summary                          display useful information regarding the FMU. (default: None)
  -check                            performs some check of FMU and display Errors or Warnings. This is useful to avoid
                                    later issues when using the FMU. (default: None)
```

## FMU Containers

```
usage: fmucontainer [-h] [-fmu-directory FMU_DIRECTORY] [-fmi FMI_VERSION]
                    -container filename.{csv|json|ssp},[:step_size] [-debug] [-no-auto-input] [-no-auto-output]
                    [-auto-parameter] [-auto-local] [-no-auto-link] [-mt] [-profile] [-sequential] [-dump-json]

Generate FMU from FMU's

options:
  -h, -help
  -fmu-directory FMU_DIRECTORY      Directory containing initial FMU’s and used to generate containers. If not defined,
                                    current directory is used. (default: .)
  -fmi FMI_VERSION                  Define version of FMI to be used for container interface.Only '2' or '3' is
                                    supported. (default: 2)
  -container filename.{csv|json|ssp},[:step_size]
                                    Description of the container to create. (default: [])
  -debug                            Add lot of useful log during the process. (default: False)
  -no-auto-input                    Create ONLY explicit input. (default: True)
  -no-auto-output                   Create ONLY explicit output. (default: True)
  -auto-parameter                   Expose parameters of the embedded fmu's. (default: False)
  -auto-local                       Expose local variables of the embedded fmu's. (default: False)
  -no-auto-link                     Create ONLY explicit links. (default: True)
  -mt                               Enable Multi-Threaded mode for the generated container. (default: False)
  -profile                          Enable Profiling mode for the generated container. (default: False)
  -sequential                       Use sequential mode to schedule embedded fmu's. (default: False)
  -dump-json                        Dump a JSON file for each container. (default: False)
```

# 🚀 API

You can write your own FMU Manipulation scripts. Once you downloaded fmutool module, 
adding the `import` statement lets you access the API :

```python
from fmu_manipulation_toolbox.operations import ...
```


## remove toplevel bus (if any)

Given a FMU with the following I/O structure
```
├── Parameters
│   ├── Foo
│   │   ├── param_A
│   ├── Bar
├── Generator
│   ├── Input_A
│   ├── Output_B
```

The following transformation will lead into:
```
├── Foo
│   ├── param_A
├── Bar
├── Input_A
├── Output_B
```

**Note:** removing toplevel bus can lead to names collisions !

The following code will do this transformation: 
```python
from fmu_manipulation_toolbox.operations import FMU, OperationStripTopLevel

fmu = FMU(r"bouncing_ball.fmu")
operation = OperationStripTopLevel()
fmu.apply_operation(operation)
fmu.repack(r"bouncing_ball-modified.fmu")
```

### Extract names and write a CSV

The following code will dump all FMU's Scalars names into a CSV:

```python
from fmu_manipulation_toolbox.operations import FMU, OperationSaveNamesToCSV

fmu = FMU(r"bouncing_ball.fmu")
operation = OperationSaveNamesToCSV(r"bouncing_ball.csv")
fmu.apply_operation(operation)
```

The produced CSV contains 2 columns in order to be reused in the next transformation.
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


## Read CSV and rename FMU ports

CSV file should contain 2 columns:
1. the current name
2. the new name

```python
from fmu_manipulation_toolbox.operations import FMU, OperationRenameFromCSV

fmu = FMU(r"bouncing_ball.fmu")
operation = OperationRenameFromCSV(r"bouncing_ball-modified.csv")
fmu.apply_operation(operation)
fmu.repack(r"bouncing_ball-renamed.fmu")
```

More operations exist in [`Operation.py`](fmu_manipulation_toolbox/operations.py)
