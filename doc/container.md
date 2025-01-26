# FMU Containers ?

A FMU Container is classical FMU which embeds other's FMU's.
![FMU Container](../doc/FMUContainer.png "FMU Container")
FMU Manipulation Toolbox ships `fmucontainer` command which makes easy to embed FMU's into FMU.


# How to create an FMU Container ?

The `fmucontainer` command creates container from a description file. This file contains multiple parameters:

- time step: a FMU Container acts as a fixed step time "solver" for its embedded FMU's.
- optional features
  - multi-threading: 
  - profiling
- routing table
  - Input ports
  - Output ports
  - Connexions between embedded FMU's
  - Explicitly ignored ports (only port with causality = "output" can be ignored)
- Automatic routing table
  - expose automatically ports of embedded FMU's with causality = "input"
  - expose automatically ports of embedded FMU's with causality = "output"
  - link automatically ports of embedded FMU's which are left previously unconnected and have the same names and types

Some of these parameters can be defined by Command Line Interface or by input files.

Several formats are supported as description files:
- a `CSV` format: define only the routing table. Other options are defined as command line options.
- a `JSON` file: all parameters can be defined in the file. Command line can define default values if the parameter 
  is not present in `JSON` file.
- a `SSP` file. See [ssp-standard.org](https://ssp-standard.org). define only the routing table. Other options are defined with command line.

![Routing](../doc/routing.png "Routing table")

## CSV Input file

Example :
```csv
rule;from_fmu;from_port;to_fmu;to_port
FMU;bb_position.fmu;;;
FMU;bb_velocity.fmu;;;
OUTPUT;bb_position.fmu;position1;;position
LINK;bb_position.fmu;is_ground;bb_velocity.fmu;reset
LINK;bb_velocity.fmu;velocity;bb_position.fmu;velocity
OUTPUT;bb_velocity.fmu;velocity;;
```

## Json Input file



## SSP Input file



