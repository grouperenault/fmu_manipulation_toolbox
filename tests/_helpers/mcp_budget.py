"""Context budget of the MCP server (docs/local/mcp_optimize.md).

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

#: Budgets checked by the tests (decision D6).
DEFINITIONS_BUDGET = 16_000
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


def main():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        make_large_fmu(directory / "large.fmu")
        make_large_fmu(directory / "broken.fmu", broken=True)
        texts = asyncio.run(measure(directory))
    print(f"{'item':32} {'characters':>10} {'budget':>8} {'tokens':>8}")
    for name, text in texts.items():
        budget = DEFINITIONS_BUDGET if name == "definitions" else RESULT_BUDGET
        count = tokens(text)
        flag = "" if len(text) <= budget else "  over budget"
        print(f"{name:32} {len(text):>10} {budget:>8} {'-' if count is None else count:>8}{flag}")


if __name__ == "__main__":
    sys.exit(main())
