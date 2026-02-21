# FMU Containers ?

A FMU Container is classical FMU which embeds other FMU's:

![FMU Container](FMUContainer.png "FMU Container")

From API point of view, an FMUContainer can be seen as
* an FMU which implement the FMI API (either version 2.0 or 3.0)
* an fmi-importer which can load FMUs

FMU Manipulation Toolbox is shipped with `fmucontainer` command which makes easy to nest FMU's into FMU.


# How to create an FMU Container ?

The `fmucontainer` command creates a FMU, named Container, from a description file. This file contains multiple parameters:

- *time_step*: a FMU Container acts as a fixed step time "solver" for its embedded FMU's.
- optional features
  - *multi-threading*: each embedded FMU will use its own thread to parallelize `doStep()` operation.  
  - *profiling*: performance indicators can be calculated by the container to help to identify the bottlenecks among 
    the embedded FMU's.
- routing table
  - Input ports: the list of the Container's inputs. Each input is linked to one input (or more) of one of the embedded FMU's.
  - Output ports: the list of the container's outputs. Each output is linked to one output of one of the embedded FMU's.
  - Connexions between embedded FMU's
  - Explicitly ignored ports (only port with `causality = "output"` can be ignored)
- Automation of routing table
  - *auto_input* exposes automatically the (unconnected) ports of embedded FMU's with `causality = "input"`
  - *auto_output* expose automatically the (unconnected) ports of embedded FMU's with `causality = "output"`
  - *auto_local* expose automatically the ports of embedded FMU's with `causality = "local"`
  - *auto_parameter* expose automatically the ports of embedded FMU's with `causality = "parameter"`
  - *auto_link* links automatically ports of embedded FMU's which are left previously unconnected and have the same
    names and types

Some of these parameters can be defined by Command Line Interface or by the input files.

Several formats are supported as description files:
- a `CSV` format: define only the routing table. Other options should be defined as command line options.
- a `JSON` file: all parameters can be defined in the file. Command line can define default values if the parameter 
  is not present in `JSON` file.
- a `SSP` file. See [ssp-standard.org](https://ssp-standard.org). define only the routing table. Other options are defined with command line.

![Routing](routing.png "Routing table")

## CSV Input file
This is the historic input file format. It has been superseded by the Json input file format.

Example: 
  * Two FMU's to be assembled: `bb_position.fmu` and `bb_velocity.fmu`
  * Container should expose `position1` from `bb_position.fmu` as `position`
  * Container has no input
  * there's two links between embedded FMU's


the `container.csv` file content:

```csv
rule;from_fmu;from_port;to_fmu;to_port
FMU;bb_position.fmu;;;
FMU;bb_velocity.fmu;;;
OUTPUT;bb_position.fmu;position1;;position
LINK;bb_position.fmu;is_ground;bb_velocity.fmu;reset
LINK;bb_velocity.fmu;velocity;bb_position.fmu;velocity
OUTPUT;bb_velocity.fmu;velocity;;
```

Asserting the FMU's and the CSV files are located in current working directory,
the following command will build the container:

```
fmucontainer -container container.csv:0.1
```

Then `container.fmu` should be available.
Note: the optional `:0.1` suffix means the timestep should be `0.1` second.  

## Json Input file

![Routing](container-json.png "Json input file")

```
fmucontainer -container container.json
```

## SSP Input file
 
This feature is still alpha.

The following command 
```
fmucontainer -container my_file.ssp:0.1
```

will 
1. extact FMU's from the SSP file
2. build a container accordingly to the SSP

Note: the optional `:0.1` suffix means the timestep should be `0.1` second.  

# FMI Support

FMI-3.0 current support is limited.
Feel free to [create a ticket](https://github.com/grouperenault/fmu_manipulation_toolbox/issues/new) to
let us know your needs.


## FMI-2.0 Containers
Without any additional option, `fmucontainer` will produce FMI-2.0 containers. These containers may embed
- *FMU 2.0* in cosimulation mode without any particular limitation.
- *FMU 3.0* in cosimulation mode with limitations:
  - Variables with FMI-3.0 specific types can be used for routing but cannot be exposed (as input, output, parameter or local).
    Note: `boolean` is redefined in FMI-3.0. So cannot be exposed from an FMU-3.0.
  - Early Return feature is not supported
  - Arrays are not supported

## FMI-3.0 Containers
To produce FMI-3.0 compliant containers, use option `-fmi 3` in `fmucontainer` command line.
Those containers may embed

- *FMU 2.0* in cosimulation mode with limitations:
  - `boolean` variables can be used for routing but cannot be exposed (as input, output, parameter or local).
   
- *FMU 3.0* in cosimulation mode with limitations:
  - Early Return feature is _not_ supported
  - Arrays are not supported


# Muti-Threading
If enabled through `MT` flag, each FMU will be run using its own thread which
1. fetch its inputs from container buffer which is shared with all FMUs.
2. process `DoStep()`

Synchronization uses a mutex.

# Profiling 
If enabled through `profiling` flag, each call to `DoStep` of each FMU is monitored. The elapsed time
is compared with `currentCommunicationPoint` and a RT ratio is computed. A ratio greater than `1.0` means
this particular FMU is faster than RT.
