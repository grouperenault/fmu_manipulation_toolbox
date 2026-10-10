"""Context budget of the MCP server (docs/local/done/mcp_optimize.md, decision D6).

The tool definitions are sent with every request and the tool results stay in the conversation: with a local model
whose context is small, an unbounded result fills the window and the runtime silently drops the beginning of the
conversation. Budgets are in characters (~4 characters per token for this JSON), measured on a synthetic FMU of the
size of industrial ones (`_helpers/mcp_budget.py`). The `xfail` markers are removed by the phases that bring the
server within budget.
"""
import asyncio
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

fastmcp = pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")

from _helpers.mcp_budget import (  # noqa: E402
    DEFINITIONS_BUDGET, LARGE_FMU_VARIABLES, RESULT_BUDGET, make_large_assembly, make_large_fmu, measure,
    measure_assembly,
)


@pytest.fixture(scope="module")
def texts(tmp_path_factory):
    directory = tmp_path_factory.mktemp("budget")
    make_large_fmu(directory / "large.fmu")
    make_large_fmu(directory / "broken.fmu", broken=True)
    texts = asyncio.run(measure(directory))
    texts.update(asyncio.run(measure_assembly(make_large_assembly(directory))))
    return texts


def test_the_fixture_is_large(texts):
    """The measurements are only meaningful on an FMU of industrial size."""
    assert f'"total":{LARGE_FMU_VARIABLES}' in texts["list_fmu_ports"].replace(" ", "")
    assert f'"error_count":{LARGE_FMU_VARIABLES // 2 + 1}' in texts["check_fmu-broken"].replace(" ", "")


def _nodes(node):
    yield node
    for child in node.get("container", []):
        yield from _nodes(child)


def test_the_large_assembly_is_consistent(tmp_path):
    """The nested assembly reads back as an `Assembly`, and every port it designates exists.

    A port of a sub-container is one it exposes; a port of an FMU is one of its descriptor.
    """
    from fmu_manipulation_toolbox.assembly import Assembly
    from fmu_manipulation_toolbox.container.embedded import EmbeddedFMU

    assembly = make_large_assembly(tmp_path)
    (tmp_path / "large_assembly.json").write_text(json.dumps(assembly))
    assert Assembly("large_assembly.json", fmu_directory=tmp_path).json_encode() == assembly

    nodes = list(_nodes(assembly))
    assert len(nodes) == 3
    exposed = {node["name"]: ({entry[0] for entry in node.get("input", [])},
                              {entry[2] for entry in node.get("output", [])}) for node in nodes}
    for node in nodes:
        ports = {}
        for fmu in node.get("fmu", []):
            embedded = EmbeddedFMU(tmp_path / fmu)
            ports[Path(fmu).name] = ({name for name, port in embedded.ports.items() if port.causality == "input"},
                                     {name for name, port in embedded.ports.items() if port.causality == "output"})
        for child in node.get("container", []):
            ports[child["name"]] = exposed[child["name"]]

        def check(fmu, port, causality):
            assert port in ports[Path(fmu).name][causality], f"{node['name']}: {fmu}/{port}"

        for _, fmu, port in node.get("input", []):
            check(fmu, port, 0)
        for fmu, port, _ in node.get("output", []):
            check(fmu, port, 1)
        for from_fmu, from_port, to_fmu, to_port in node.get("link", []):
            check(from_fmu, from_port, 1)
            check(to_fmu, to_port, 0)

    assert sum(len(node.get("input", [])) for node in nodes) > 300
    assert sum(len(node.get("link", [])) for node in nodes) > 250


def test_tool_definitions(texts):
    assert len(texts["definitions"]) <= DEFINITIONS_BUDGET


OVER_BUDGET: dict[str, str] = {
    "get_assembly_json-large": "get_assembly_json is not bounded (docs/local/assembly_analysis.md, phase 2)",
    "resource assembly://current-large": "assembly://current is not bounded (docs/local/assembly_analysis.md, "
                                         "phase 2)",
}
RESULTS = ["add_fmu", "list_fmu_ports", "inspect_fmu_file", "summarize_fmu", "check_fmu", "check_fmu-broken",
           "get_assembly_json", "resource fmu://large.fmu/ports", "get_assembly_json-large",
           "resource assembly://current-large"]


@pytest.mark.parametrize("name", [
    pytest.param(name, marks=pytest.mark.xfail(strict=True, reason=OVER_BUDGET[name])) if name in OVER_BUDGET
    else name for name in RESULTS])
def test_results_with_default_arguments(texts, name):
    assert len(texts[name]) <= RESULT_BUDGET
