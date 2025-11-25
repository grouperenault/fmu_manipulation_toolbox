# FMU Manipulation Toolbox changelog
This package was formerly known as `fmutool`.

# Version 1.9.1
* FIXED: `fmucontainer` handle correctly start/stop in <DefaultExperiment>

# Version 1.9
* CHANGE: `remoting` code rewrite to (drastically) improve performance
* ADDED: `fmusplit` command to split container into FMU's and provide a json file
* ADDED: `fmucontainer` support of `-sequential` mode
* ADDED: FMI-3.0 early support. Use `-fmi 3` option for `fmucontainer`
* FIXED: `fmucontainer` MT mode on Linux and Darwin
* FIXED: `fmutool` command line for various operations
* FIXED: `fmutool` handle correctly <ModelStructure>: remove empty tags
* CHANGE: (API) `fmu_operations` and `fmu_container` packages are renamed `operations` and `container`
* CHANGE: (API) Introduction of `FMUPort` and `port_attrs` method to replace `scalar_attrs` and `scalar_type`
* CHANGE: (API) `FMUException` and `OperationException`  classes are renamed `FMUError` and `OperationError`
* CHANGE: (CI/CT) Add some simulation steps

# Version 1.8.4.2
* FIXED: `fmucontainer` re-set start values for causality=input after fmi2EnterInitialization as workaround for some FMUs.

# Version 1.8.4.1
* FIXED: `fmucontainer` store embedded FMUs into shorter named directories to avoid windows-long-path-issue
* FIXED: `fmucontainer` can refer to FMU located in subdirectory
* FIXED: `fmucontainer` profiling reported incorrect values

# Version 1.8.4
* CHANGE: `fmucontainer` option `-dump` saves explicitly auto-wiring data. Auto-wiring is off for SSP format.

# Version 1.8.3
* FIXED: `fmucontainer` supports correctly auto-link for 1-to-n links

# Version 1.8.2.2
* ADDED: `fmucontainer` support fmi2Strings
* FIXED: `fmucontainer` freeInstance correctly frees memory

## Version 1.8.2.1
* FIXED: `fmucontainer` exposed parameters name (using fmu name instead of fmu's model identifier)
* FIXED: `fmucontainer` support for long path (on Windows)

## Version 1.8.2
* FIXED: `fmucontainer` identifier (for coSimulation) does not contain ".fmu" anymore
* ADDED: `fmucontainer` log more information when embedded FMU cannot be loaded
* ADDED: `fmucontainer` startTime and stopTime are deduced from the 1st embedded FMU
* ADDED: `fmucontainer` support `-auto-local` option to expose local variables of the embedded FMU
* ADDED: `fmucontainer` support new option `-auto-parameter` (parameters are not exposed by default)
* FIXED: `fmutool` support "apply on" filter correctly
* DEV: preliminary version of GUI for `fmucontainer`

## Version 1.8.1
* FIXED: `fmucontainer` read links from `.json` input files
* CHANGE: switch to PyQT6 and add minor GUI improvements

## Version 1.8
* CHANGE: Python Package in now known as `fmu-manipulation-toolbox`
* ADDED: `fmucontainer` support `canHandleVariableCommunicationStepSize`
* ADDED: `fmucontainer` support `.ssp` or `.json` as input files
* ADDED: `fmucontainer` new `-dump` option to save container description 

## Version 1.7.4
* ADDED: `fmucontainer` Linux support
* ADDED: `-fmu-directory` option defaults to "." if not set
* FIXED: `fmucontainer` ensures that FMUs are compliant with version 2.0 of FMU Standard
* FIXED: `fmucontainer` handles the lack of DefaultExperiment section in modelDescription.xml


## Version 1.7.3
* ADDED: `fmucontainer` supports `-profile` option to expose RT ratio of embedded FMUs during simulation
* ADDED: Ability to expose local variables of embedded FMUs at container level
* FIXED: `fmucontainer` handles missing causality and handle better variability

## Version 1.7.2
* FIXED: handle `<ModelStructure>` section for `fmucontainer`
* FIXED: brought back `-h` option to get help for `fmucontainer`
* CHANGED: make compatibility with python >= 3.9

## Version 1.7.1
* FIXED: add missing *.xsd file that prevented checker to work
* CHANGED: Checker use API instead of environment variable to declare custom checkers.

## Version 1.7
* ADDED: FMUContainer tool

## Version 1.6.2
* ADDED: Ability to add your own FMU Checker.
* ADDED: SaveNamesToCSV will dump scalar types and start values.
* CHANGED: Default (Generic) Checker checks the `modelDescription.xml` conformity against the XSD specification file.

## Version 1.6.1
* FIXED: publication workflow is fully automated.
* FIXED: `fmutool` script is now part of the distribution.
* CHANGED: minor enhancement in the README file

## Version 1.6
* First public release
