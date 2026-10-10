"""Context budget of the MCP server (docs/local/mcp_optimize.md, decision D6).

The tool definitions are sent with every request and the tool results stay in the conversation: with a local model
whose context is small, an unbounded result fills the window and the runtime silently drops the beginning of the
conversation. Budgets are in characters (~4 characters per token for this JSON), measured on a synthetic FMU of the
size of industrial ones (`_helpers/mcp_budget.py`). The `xfail` markers are removed by the phases that bring the
server within budget.
"""
import asyncio

import pytest

pytestmark = [pytest.mark.unit]

fastmcp = pytest.importorskip("fastmcp", reason="the optional `mcp` extra is not installed")

from _helpers.mcp_budget import (  # noqa: E402
    DEFINITIONS_BUDGET, LARGE_FMU_VARIABLES, RESULT_BUDGET, make_large_fmu, measure,
)


@pytest.fixture(scope="module")
def texts(tmp_path_factory):
    directory = tmp_path_factory.mktemp("budget")
    make_large_fmu(directory / "large.fmu")
    make_large_fmu(directory / "broken.fmu", broken=True)
    return asyncio.run(measure(directory))


def test_the_fixture_is_large(texts):
    """The measurements are only meaningful on an FMU of industrial size."""
    assert f'"total":{LARGE_FMU_VARIABLES}' in texts["list_fmu_ports"].replace(" ", "")
    assert f'"error_count":{LARGE_FMU_VARIABLES // 2 + 1}' in texts["check_fmu-broken"].replace(" ", "")


@pytest.mark.xfail(strict=True, reason="C4: 18k characters of tool definitions (phase 3)")
def test_tool_definitions(texts):
    assert len(texts["definitions"]) <= DEFINITIONS_BUDGET


OVER_BUDGET = {
    "list_fmu_ports": "C2/C3: 100 ports of ~175 characters per default page (phase 2)",
    "inspect_fmu_file": "C2/C3: 100 ports of ~175 characters per default page (phase 2)",
    "resource fmu://large.fmu/ports": "C2/C3: default page, indented JSON (phase 2)",
}
RESULTS = ["add_fmu", "list_fmu_ports", "inspect_fmu_file", "summarize_fmu", "check_fmu", "check_fmu-broken",
           "get_assembly_json", "resource fmu://large.fmu/ports"]


@pytest.mark.parametrize("name", [
    pytest.param(name, marks=pytest.mark.xfail(strict=True, reason=OVER_BUDGET[name])) if name in OVER_BUDGET
    else name for name in RESULTS])
def test_results_with_default_arguments(texts, name):
    assert len(texts[name]) <= RESULT_BUDGET
