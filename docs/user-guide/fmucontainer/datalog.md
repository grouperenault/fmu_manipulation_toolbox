# Container with datalog

To facilitate debugging of FMUs assemblies, the datalog feature is extremely helpful.
![](datalog.png)

You can enable datalog in two ways:

- CLI: add the `-datalog` option to the `fmucontainer` command.
- GUI: in **FMU Container Builder**, open **Configuration** and check **Enable Datalog** before saving.

When enabled, a CSV file is automatically generated.
The file name is derived from the FMU container’s name and contains the values of all signals exchanged during the 
simulation, recorded at each container time step.
