# FMU Containers ?

An FMU Container is classical FMU which embeds other's FMU's. See [FMU Container](../doc/container.md)
for user documentation.

From API point of view, an FMUContainer can be seen as
    * an FMU: see [](container.c) which implements the FMI API
    * an fmi-importer which can load (see [](library.c)) and interact with FMUs (see [](fmu.c))

# Muti-Thread
If enabled through `MT` flag, each FMU has its own thread which
    1. fetch its inputs from container buffer
    2. process `fmi2DoStep()`

Synchronization uses [](thread.c) facilities.  

# Profiling 
If enabled through `profiling` flag, each calls to `fmi2DoStep` of each FMU is monitored. The ellapsed time
is compared with `currentCommunicationPoint` and a RT ratio is computed. A ratio greater than `1.0` means
this particular FMU is faster than RT. 
