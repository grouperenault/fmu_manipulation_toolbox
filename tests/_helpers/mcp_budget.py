"""Context budget of the MCP server (docs/local/done/mcp_optimize.md).

What the server puts in the context of the model, measured in characters: the tool definitions (sent with every
request) and the tool results (kept in the conversation). Tokens are only reported when `tiktoken` is installed,
for the record; the budgets of the tests are in characters (~4 characters per token for this JSON).

Run it directly to print the measurements of the current server::

    python tests/_helpers/mcp_budget.py
"""
import asyncio
import json
import sys
import tempfile
import zipfile
from pathlib import Path

#: Size of the synthetic FMU: the order of magnitude of industrial FMUs.
LARGE_FMU_VARIABLES = 5000

#: Budgets checked by the tests (decision D6); the definitions budget raised from 16 000 for `analyze_assembly`
#: (docs/local/assembly_analysis.md, decision D1).
DEFINITIONS_BUDGET = 17_000
RESULT_BUDGET = 12_000


def make_large_fmu(path: Path, nb_variables: int = LARGE_FMU_VARIABLES, broken: bool = False) -> Path:
    """FMI-2 FMU (descriptor only) with hierarchical names, a unit and a description per variable.

    A quarter of each causality. With `broken`, the inputs and parameters have no start value: one semantic error
    per variable (FMI-2 §2.2.7), as in a large non-compliant FMU.
    """
    variables = []
    for i in range(nb_variables):
        causality = ("input", "output", "parameter", "local")[i % 4]
        extra = ' variability="fixed" initial="exact"' if causality == "parameter" else ""
        start = ' start="0.0"' if causality in ("input", "parameter") and not broken else ""
        variables.append(f'<ScalarVariable name="Subsystem{i // 100}.Block{i % 100}.signal_{i}" valueReference="{i}" '
                         f'causality="{causality}"{extra} description="Signal {i} of block {i % 100} of subsystem '
                         f'{i // 100}"><Real{start} unit="m/s"/></ScalarVariable>')
    outputs = "".join(f'<Unknown index="{i + 1}"/>' for i in range(nb_variables) if i % 4 == 1)
    descriptor = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
                  f'<fmiModelDescription fmiVersion="2.0" modelName="large" guid="{{large}}" '
                  f'generationTool="synthetic"><CoSimulation modelIdentifier="large"/>'
                  f'<DefaultExperiment stepSize="0.01"/><ModelVariables>{"".join(variables)}</ModelVariables>'
                  f'<ModelStructure><Outputs>{outputs}</Outputs><InitialUnknowns>{outputs}</InitialUnknowns>'
                  f'</ModelStructure></fmiModelDescription>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
    return path


def make_fmu(path: Path, inputs: list[str] = (), outputs: list[str] = (), step_size: float = 0.01) -> Path:
    """FMI-2 FMU (descriptor only) with the given Real inputs (start value 0.0) and outputs."""
    variables = [f'<ScalarVariable name="{name}" valueReference="{i}" causality="input"><Real start="0.0"/>'
                 f'</ScalarVariable>' for i, name in enumerate(inputs)]
    variables += [f'<ScalarVariable name="{name}" valueReference="{len(inputs) + i}" causality="output"><Real/>'
                  f'</ScalarVariable>' for i, name in enumerate(outputs)]
    unknowns = "".join(f'<Unknown index="{len(inputs) + i + 1}"/>' for i in range(len(outputs)))
    descriptor = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
                  f'<fmiModelDescription fmiVersion="2.0" modelName="{path.stem}" guid="{{{path.stem}}}" '
                  f'generationTool="synthetic"><CoSimulation modelIdentifier="{path.stem}"/>'
                  f'<DefaultExperiment stepSize="{step_size}"/><ModelVariables>{"".join(variables)}</ModelVariables>'
                  f'<ModelStructure><Outputs>{unknowns}</Outputs><InitialUnknowns>{unknowns}</InitialUnknowns>'
                  f'</ModelStructure></fmiModelDescription>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
    return path


def _options(step_size: float, mt: bool) -> dict:
    """Options of a node as `Assembly.json_encode` writes them, every `auto_*` rule off (explicit assembly)."""
    return {"mt": mt, "profiling": False, "sequential": False, "auto_link": False, "auto_input": False,
            "auto_output": False, "auto_parameter": False, "auto_local": False, "step_size": step_size}


def make_large_assembly(directory: Path) -> dict:
    """Nested assembly of the size of a real one (docs/local/assembly_analysis.md), its FMUs written in `directory`.

    Same shape as the case study of the plan: a scenario driving a vehicle container, which couples a plant with a
    traction sub-container (3 levels, 5 FMUs, ~300 exposed inputs, ~290 exposed outputs, ~290 links), every `auto_*`
    rule off. Port names follow both conventions met in practice: dotted buses (`Sc_2_DV.speed`) and underscore
    prefixes (`SNR_time3`). It also holds the patterns the lint must report: `mt` on two nested levels, a step ratio
    of 100, a fan-out and a stub FMU of constants. As in the JSON of the GUI, the FMUs of the root level are
    referenced by absolute path, the others by name.

    Returns the assembly in the format of `Assembly.json_encode`.
    """
    def path(name: str) -> str:
        return str(directory / name)

    quantities = ["Acceleration", "OverFriction", "Pamb", "Paux", "Pmeca_totalMot_limit", "Pmeca_totalRegen_limit",
                  "Rho", "RoadSlope", "Speed", "SolarIrr", "Tamb", "Wind", "Mass", "Hvac", "Charge"]
    scenario_inputs = ([f"scenario.{q}{p}" for q in quantities for p in range(1, 11)]
                       + [f"SNR_{q}{p}" for q in ("time", "distance", "SOCmin", "SOCmax", "vehicle_state", "phase")
                          for p in range(1, 11)]
                       + [f"run_parameters.{p}" for p in ("maxTimeStep", "tolerance", "fixedStep", "integratorType",
                                                          "errorType", "solverType", "integrationMethod",
                                                          "fixedOrder")])
    sc_2_dv = [f"Sc_2_DV.{s}" for s in ("VehicleSpeedTarget", "road_slope", "Rho", "Paux", "Acceleration",
                                         "VehicleState", "VehiclePhase")]
    dv_2_sc = [f"DV_2_Sc.{s}" for s in ("USOC", "BSOC", "Battery_voltage", "Vehicle_velocity")]
    parameters = [f"DV_Parameters.custom_{i}" for i in range(24)]
    plant_assessment = [f"DV_2_Assessment.plant_{i}" for i in range(19)]
    control_assessment = [f"DV_2_Assessment.control_{i}" for i in range(5)]
    boundary = [f"CS_{i}" for i in range(92)]                    # plant -> level2 (cooling, road...)
    control_traction = [f"Tq_{i}" for i in range(116)]           # level2 (control) -> plant
    carbody_traction = [f"Fx_{i}" for i in range(55)]            # level2 (carbody) -> plant
    stub_traction = ["veh_vel_ms"]                                # level2 (stub) -> plant
    traction = control_traction + carbody_traction + stub_traction
    carbody_to_control = ["veh_vel", "Fslope", "ratio", "Tloss", "MotorFront_Speed", "MotorRear_Speed"]
    stub_to_carbody = ["Tbrk", "Twheel_req", "EM2_torque", "EM2_inertia", "HV_aux_volt", "EM1_inertia", "Dummy_volt"]

    make_fmu(directory / "scenario.fmu", inputs=scenario_inputs + dv_2_sc, outputs=sc_2_dv, step_size=0.5)
    # The plant reads every traction signal, plus a second copy of the first one (fan-out).
    make_fmu(directory / "plant.fmu", inputs=sc_2_dv + [f"in_{name}" for name in traction] + ["in_fanout"],
             outputs=dv_2_sc + parameters + plant_assessment + boundary, step_size=0.5)
    make_fmu(directory / "control.fmu", inputs=boundary[:86] + carbody_to_control,
             outputs=control_traction + control_assessment + ["EM1_torque"], step_size=0.005)
    make_fmu(directory / "carbody.fmu", inputs=boundary[86:] + ["EM1_torque"] + stub_to_carbody,
             outputs=carbody_traction + carbody_to_control + ["veh_vel_kmph"], step_size=0.005)
    make_fmu(directory / "stub.fmu", inputs=["veh_vel_kmph"], outputs=stub_to_carbody + stub_traction,
             step_size=0.005)

    level2 = {
        "name": "level2.fmu", **_options(0.005, mt=True),
        "fmu": ["carbody.fmu", "control.fmu", "stub.fmu"],
        "input": ([[name, "control.fmu", name] for name in boundary[:86]]
                  + [[name, "carbody.fmu", name] for name in boundary[86:]]),
        "output": ([["control.fmu", name, name] for name in control_traction + control_assessment]
                   + [["carbody.fmu", name, name] for name in carbody_traction]
                   + [["stub.fmu", name, name] for name in stub_traction]),
        "link": ([["carbody.fmu", name, "control.fmu", name] for name in carbody_to_control]
                 + [["control.fmu", "EM1_torque", "carbody.fmu", "EM1_torque"],
                    ["carbody.fmu", "veh_vel_kmph", "stub.fmu", "veh_vel_kmph"]]
                 + [["stub.fmu", name, "carbody.fmu", name] for name in stub_to_carbody]),
    }
    vehicle = {
        "name": "vehicle.fmu", **_options(0.5, mt=True),
        "container": [level2],
        "fmu": ["plant.fmu"],
        "input": [[name, "plant.fmu", name] for name in sc_2_dv],
        "output": ([["plant.fmu", name, name] for name in dv_2_sc + parameters + plant_assessment]
                   + [["level2.fmu", name, name] for name in control_assessment]),
        "link": ([["level2.fmu", name, "plant.fmu", f"in_{name}"] for name in traction]
                 + [["level2.fmu", traction[0], "plant.fmu", "in_fanout"]]
                 + [["plant.fmu", name, "level2.fmu", name] for name in boundary]),
    }
    return {
        "name": "large_assembly.fmu", **_options(0.5, mt=False),
        "container": [vehicle],
        "fmu": [path("scenario.fmu")],
        "input": [[name, path("scenario.fmu"), name] for name in scenario_inputs],
        "output": [["vehicle.fmu", name, name] for name in parameters + plant_assessment + control_assessment],
        "link": ([[path("scenario.fmu"), name, "vehicle.fmu", name] for name in sc_2_dv]
                 + [["vehicle.fmu", name, path("scenario.fmu"), name] for name in dv_2_sc]),
    }


def tokens(text: str) -> int | None:
    """Tokens of `text` with `cl100k_base` (same order as the Qwen tokenizer), or `None` without `tiktoken`."""
    try:
        import tiktoken
    except ImportError:
        return None
    return len(tiktoken.get_encoding("cl100k_base").encode(text))


def definitions_text(tools) -> str:
    """What a client gives the model for each tool: name, description and input schema (output schema excluded)."""
    return json.dumps([{"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema}
                       for tool in tools])


def result_text(result) -> str:
    """Text content of a tool result (the `structuredContent` copy is not counted: a client forwards one of them)."""
    return "".join(getattr(content, "text", "") for content in result.content)


def default_calls(directory: Path) -> dict[str, tuple[str, dict]]:
    """Calls with default arguments on the large FMUs of `directory` (`large.fmu` added to the assembly first)."""
    large, broken = str(directory / "large.fmu"), str(directory / "broken.fmu")
    return {
        "add_fmu": ("add_fmu", {"path": large}),
        "list_fmu_ports": ("list_fmu_ports", {"fmu": "large.fmu"}),
        "inspect_fmu_file": ("inspect_fmu_file", {"path": large}),
        "summarize_fmu": ("summarize_fmu", {"path": large}),
        "check_fmu": ("check_fmu", {"path": large}),
        "check_fmu-broken": ("check_fmu", {"path": broken}),
        "get_assembly_json": ("get_assembly_json", {}),
    }


async def measure(directory: Path) -> dict[str, str]:
    """Texts of the tool definitions and of the default calls, the large FMUs being in `directory`."""
    import fastmcp
    from fmu_manipulation_toolbox.assistant import PathPolicy, build_server
    from fmu_manipulation_toolbox.assistant.headless import HeadlessAssemblyBridge

    texts: dict[str, str] = {}
    server = build_server(HeadlessAssemblyBridge(), policy=PathPolicy(directory))
    async with fastmcp.Client(server) as client:
        texts["definitions"] = definitions_text(await client.list_tools())
        for name, (tool, arguments) in default_calls(directory).items():
            texts[name] = result_text(await client.call_tool(tool, arguments))
        texts["resource fmu://large.fmu/ports"] = (await client.read_resource("fmu://large.fmu/ports"))[0].text
    return texts


async def measure_assembly(assembly: dict, directory: Path) -> dict[str, str]:
    """Texts of the assembly tools on `assembly` (see `make_large_assembly`), its FMUs being in `directory`.

    The headless bridge only builds flat assemblies: its `get_assembly_json` is replaced to serve a nested one, as
    the GUI bridge does.
    """
    import fastmcp
    from fmu_manipulation_toolbox.assistant import build_server
    from fmu_manipulation_toolbox.assistant.headless import HeadlessAssemblyBridge

    class NestedAssemblyBridge(HeadlessAssemblyBridge):
        def get_assembly_json(self):
            return assembly

        def list_fmu_ports(self, fmu):
            """Every FMU of the nested assembly, read from its directory, as the GUI bridge does."""
            from fmu_manipulation_toolbox.assistant.headless import describe_fmu
            return describe_fmu(directory / fmu)

    texts: dict[str, str] = {}
    async with fastmcp.Client(build_server(NestedAssemblyBridge())) as client:
        texts["get_assembly_json-large"] = result_text(await client.call_tool("get_assembly_json", {}))
        for node in ("vehicle.fmu", "level2.fmu"):
            texts[f"get_assembly_json-large {node}"] = result_text(
                await client.call_tool("get_assembly_json", {"node": node}))
        texts["get_assembly_json-large link page"] = result_text(
            await client.call_tool("get_assembly_json", {"node": "vehicle.fmu", "section": "link"}))
        texts["resource assembly://current-large"] = (await client.read_resource("assembly://current"))[0].text
        for mode in ("summary", "lint"):
            texts[f"analyze_assembly-large {mode}"] = result_text(
                await client.call_tool("analyze_assembly", {"mode": mode}))
    return texts


def main():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        make_large_fmu(directory / "large.fmu")
        make_large_fmu(directory / "broken.fmu", broken=True)
        texts = asyncio.run(measure(directory))
        texts.update(asyncio.run(measure_assembly(make_large_assembly(directory), directory)))
    print(f"{'item':32} {'characters':>10} {'budget':>8} {'tokens':>8}")
    for name, text in texts.items():
        budget = DEFINITIONS_BUDGET if name == "definitions" else RESULT_BUDGET
        count = tokens(text)
        flag = "" if len(text) <= budget else "  over budget"
        print(f"{name:32} {len(text):>10} {budget:>8} {'-' if count is None else count:>8}{flag}")


if __name__ == "__main__":
    sys.exit(main())
