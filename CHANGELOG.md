# FMU Manipulation Toolbox changelog
This package was formerly know as `fmutool`.


## Version 1.8
* CHANGE: Package in now known as `fmu_manipulation`
* ADDED: `fmucontainer` support `canHandleVariableCommunicationStepSize`
* ADDED: `fmucontainer` support `.spp` or `.json` as input files
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
