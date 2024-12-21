## FMU Manipulation Toolbox validation plan

Flowchart of a typical usage of FMU Manipulation Toolbox:
```mermaid
flowchart LR
    fmu_in["Input FMU"]
    fmumanipulationtoolbox[["FMU Manipulation Toolbox"]]
    fmu_out["Output FMU"]
    fmu_in --> fmumanipulationtoolbox
    fmumanipulationtoolbox --> fmu_out
```

Test suite is implemented in [tests directory](../tests).

### FMU Import Compatibility information
FMU Manipulation Toolbox import supports FMI-2.0 and Co-Simulation interface.

#### Tested Exporting Tool
- Amesim 
- Simulink
- [Reference FMUs](https://github.com/modelica/Reference-FMUs)

Automated testsuite use [bouncing_ball.fmu](../tests/operations/bouncing_ball.fmu).


### FMU Export Compatibility information
FMU Manipulation Toolbox export supports FMI-2.0 and implements Co-Simulation interface.

#### Validation Tools
- fmpy

#### Tested Importing Tools
- Amesim
- ControlBuild
- Simulink
