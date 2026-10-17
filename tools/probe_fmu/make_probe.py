"""Generate the probe FMUs of the importer comparison study (docs/local/importer_comparison.md).

The three FMUs Probe10ms, Probe20ms and Probe50ms are FMI 2.0 Co-Simulation FMUs with sources only: the same
`probe.c` and a `probe_config.h` giving their GUID and step size. Compile them for the host with
`fmutool -input Probe10ms.fmu -compile-sources -output Probe10ms-host.fmu`.

The generation is reproducible: the GUIDs derive from the model names and the archive entries have a fixed date.

Usage: python make_probe.py [-output DIRECTORY]   (default: the directory of this script)
"""
import argparse
import uuid
import zipfile
from xml.sax.saxutils import quoteattr
from pathlib import Path

HERE = Path(__file__).parent

#: Model name -> step size (s).
PROBES = {"Probe10ms": 0.01, "Probe20ms": 0.02, "Probe50ms": 0.05}

#: Namespace of the GUIDs (uuid5 of the model name).
GUID_NAMESPACE = uuid.UUID("6f1c9d0e-3b7a-4c2e-9a51-7d0e2b4f8c13")

#: Fixed date of the archive entries (reproducible archives).
ZIP_DATE = (2026, 10, 17, 0, 0, 0)

#: name, vr, type, causality, variability, start (None: initial="calculated"), description
VARIABLES = [
    ("p_real", 0, "Real", "parameter", "fixed", "1.0", "Parameter used by y_init"),
    ("p_tunable", 1, "Real", "parameter", "tunable", "0.0", "Offset of y_cont"),
    ("compute_time", 2, "Real", "parameter", "fixed", "0.0", "Wall time spent in each fmi2DoStep (s)"),
    ("compute_sleep", 3, "Boolean", "parameter", "fixed", "false", "Sleep instead of busy wait in fmi2DoStep"),
    ("strict_step", 4, "Boolean", "parameter", "fixed", "false", "Reject a step size different from stepSize"),
    ("trace_file", 5, "String", "parameter", "fixed", "",
     "Path of the trace (empty: <instanceName>.csv in the current directory)"),
    ("u_cont", 10, "Real", "input", "continuous", "0.0", "Continuous input"),
    ("u_disc", 11, "Real", "input", "discrete", "0.0", "Discrete input"),
    ("u_int", 12, "Integer", "input", "discrete", "0", "Discrete Integer input"),
    ("u_bool", 13, "Boolean", "input", "discrete", "false", "Discrete Boolean input"),
    ("y_cont", 20, "Real", "output", "continuous", None, "u_cont + p_tunable (direct feedthrough)"),
    ("y_disc", 21, "Real", "output", "discrete", None, "u_disc latched at the start of the last step"),
    ("y_int", 22, "Integer", "output", "discrete", None,
     "Number of steps done + 1000 * u_int latched at the start of the last step"),
    ("y_bool", 23, "Boolean", "output", "discrete", None, "u_bool latched at the start of the last step"),
    ("y_init", 24, "Real", "output", "discrete", None,
     "p_real + u_cont, computed in Initialization Mode, frozen at fmi2ExitInitializationMode"),
    ("y_time", 25, "Real", "output", "continuous", None, "Time of the FMU"),
]

#: Output -> (dependencies in <Outputs>, dependencies in <InitialUnknowns>), as variable names.
DEPENDENCIES = {
    "y_cont": (["u_cont"], ["p_tunable", "u_cont"]),
    "y_disc": ([], []),
    "y_int": ([], []),
    "y_bool": ([], []),
    "y_init": ([], ["p_real", "u_cont"]),
    "y_time": ([], []),
}


def guid(model_name: str) -> str:
    return "{" + str(uuid.uuid5(GUID_NAMESPACE, model_name)) + "}"


def model_description(model_name: str, step_size: float) -> str:
    index = {name: i for i, (name, *_) in enumerate(VARIABLES, start=1)}

    variables = []
    for name, vr, type_name, causality, variability, start, description in VARIABLES:
        if start is None:
            attributes, element = ' initial="calculated"', f"<{type_name}/>"
        else:
            attributes, element = "", f'<{type_name} start="{start}"/>'
        variables.append(f'    <!-- {index[name]} -->\n'
                         f'    <ScalarVariable name="{name}" valueReference="{vr}" causality="{causality}" '
                         f'variability="{variability}"{attributes} description={quoteattr(description)}>\n'
                         f'      {element}\n'
                         f'    </ScalarVariable>')

    def unknown(name: str, dependencies: list[str]) -> str:
        indexes = " ".join(str(index[dependency]) for dependency in dependencies)
        return f'      <Unknown index="{index[name]}" dependencies="{indexes}"/>'

    outputs = "\n".join(unknown(name, deps[0]) for name, deps in DEPENDENCIES.items())
    initial_unknowns = "\n".join(unknown(name, deps[1]) for name, deps in DEPENDENCIES.items())
    variables_text = "\n".join(variables)

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription
  fmiVersion="2.0"
  modelName="{model_name}"
  guid="{guid(model_name)}"
  description="Probe FMU tracing the FMI calls of its importer (step size {step_size} s)"
  generationTool="FMU Manipulation Toolbox - tools/probe_fmu/make_probe.py"
  variableNamingConvention="flat"
  numberOfEventIndicators="0">

  <CoSimulation
    modelIdentifier="{model_name}"
    needsExecutionTool="false"
    canHandleVariableCommunicationStepSize="false"
    canInterpolateInputs="false"
    maxOutputDerivativeOrder="0"
    canRunAsynchronuously="false"
    canBeInstantiatedOnlyOncePerProcess="false"
    canNotUseMemoryManagementFunctions="true"
    canGetAndSetFMUstate="false"
    canSerializeFMUstate="false"
    providesDirectionalDerivative="false">
    <SourceFiles>
      <File name="probe.c"/>
    </SourceFiles>
  </CoSimulation>

  <LogCategories>
    <Category name="probe" description="One message per line of the trace"/>
    <Category name="logStatusWarning" description="Warnings (step size different from stepSize)"/>
    <Category name="logStatusError" description="Errors"/>
  </LogCategories>

  <DefaultExperiment startTime="0" stopTime="1" stepSize="{step_size}"/>

  <ModelVariables>
{variables_text}
  </ModelVariables>

  <ModelStructure>
    <Outputs>
{outputs}
    </Outputs>
    <InitialUnknowns>
{initial_unknowns}
    </InitialUnknowns>
  </ModelStructure>
</fmiModelDescription>
'''


def probe_config(model_name: str, step_size: float) -> str:
    return (f"/* Generated by make_probe.py: configuration of {model_name}. */\n"
            f"#ifndef PROBE_CONFIG_H\n"
            f"#define PROBE_CONFIG_H\n\n"
            f'#define PROBE_MODEL_NAME "{model_name}"\n'
            f'#define PROBE_GUID "{guid(model_name)}"\n'
            f"#define PROBE_STEP_SIZE {step_size!r}\n\n"
            f"#endif\n")


def make_fmu(model_name: str, step_size: float, output_directory: Path) -> Path:
    filename = output_directory / f"{model_name}.fmu"
    entries = {
        "modelDescription.xml": model_description(model_name, step_size),
        "sources/probe.c": (HERE / "probe.c").read_text(encoding="utf-8"),
        "sources/probe_config.h": probe_config(model_name, step_size),
    }
    with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content.encode("utf-8"))
    return filename


def main():
    parser = argparse.ArgumentParser(description="Generate the probe FMUs (sources only).")
    parser.add_argument("-output", type=Path, default=HERE, metavar="DIRECTORY",
                        help="Directory of the generated FMUs (default: the directory of this script).")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for model_name, step_size in PROBES.items():
        print(f"Generated {make_fmu(model_name, step_size, args.output)}")


if __name__ == "__main__":
    main()
