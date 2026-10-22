# Reference FMUs descriptors

`modelDescription.xml` files of the [Reference FMUs](https://github.com/modelica/Reference-FMUs)
of the Modelica Association Project "FMI", release
[v0.0.41](https://github.com/modelica/Reference-FMUs/releases/tag/v0.0.41) (`Reference-FMUs.zip`).
Only the descriptors are kept (no binaries, no sources). See `LICENSE.txt` (2-Clause BSD).

They are used by `tests/unit/test_model_description.py` to check `model_description.py` against
descriptors written by the standard's authors: FMI-2 `TypeDefinitions`/`SimpleType`, enumerations,
FMI-3 `Alias`, `Binary`/`<Start>`, arrays with structural parameters, `Clock` and a
`ScheduledExecution`-only FMU (`3.0/Clocks`).
