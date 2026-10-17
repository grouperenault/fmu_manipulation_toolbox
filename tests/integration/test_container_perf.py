"""Results of reference containers for the performance work on the runtime (`docs/local/container_perf.md`).

The exchanges of the embedded FMUs (one FMI call per type) and the coupling sweep of the Model-Exchange solver must
not change the results: they are compared bit for bit with REF files made before these changes. `Feedthrough.fmu`
(FMI 3.0) and `VanDerPol.fmu` have binaries for every platform; the FMI-2 `Feedthrough.fmu` is compiled for the host.
"""
import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from fmu_manipulation_toolbox.container import FMUContainer

from _helpers.archive import read_entry, rewrite_fmu
from _helpers.assertions import assert_identical_files
from _helpers.simulation import simulate

pytestmark = [pytest.mark.integration, pytest.mark.needs_fmpy, pytest.mark.needs_container,
              pytest.mark.area("containers/perf")]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: Ports of `Feedthrough.fmu` (`<name>_input` -> `<name>_output`) linked from one instance to the next. No FMI-3
#: `Enumeration`: the container handles it as an `Int32`, where FMI 3.0 accesses it as an `Int64`.
PORTS_3 = ("Float32_continuous", "Float64_continuous", "Float64_discrete", "Int8", "UInt8", "Int16", "UInt16",
           "Int32", "UInt32", "Int64", "UInt64", "Boolean", "String")
PORTS_2 = ("Float64_continuous", "Float64_discrete", "Int32", "Boolean", "String", "Enumeration")


def _me_only(source: str, target: str):
    """Copy of an FMU without its Co-Simulation interface: the container embeds it in Model-Exchange mode."""
    description = read_entry(source, "modelDescription.xml").decode("utf-8")
    description = re.sub(r"<CoSimulation\b.*?/>", "", description, flags=re.DOTALL)
    rewrite_fmu(source, target, replace={"modelDescription.xml": description.encode("utf-8")})


@pytest.fixture
def fmus(area_dir):
    shutil.copy(DATA_DIR / "compile" / "3.0" / "Feedthrough.fmu", "Feedthrough.fmu")
    shutil.copy(DATA_DIR / "containers" / "VanDerPol" / "VanDerPol.fmu", "VanDerPol.fmu")
    _me_only("VanDerPol.fmu", "VanDerPolME.fmu")
    _me_only("Feedthrough.fmu", "FeedthroughME.fmu")
    return area_dir


def _assert_results(name: str, outputs: list[str], start_values: dict | None = None, case: str | None = None):
    """Simulate `<name>.fmu` and compare the outputs, written with every digit, with `REF-results-<case>.csv`
    (`case` defaults to `name`)."""
    case = case or name
    result = simulate(f"{name}.fmu", stop_time=0.05, output_interval=0.001, start_values=start_values or {})
    np.savetxt(f"results-{case}.csv", np.column_stack([result["time"]] + [result[o] for o in outputs]),
               delimiter=",", fmt="%.17g", header=",".join(["time"] + outputs), comments="")
    assert_identical_files(f"results-{case}.csv", f"REF-results-{case}.csv")


def _chain(container: FMUContainer, source: str, names: list[str], ports: tuple[str, ...]):
    """`x0` of `source` feeds every port of the first instance but its string (converted to the type of the port);
    each instance feeds the next."""
    for port in ports:
        if port != "String":
            container.add_link(source, "x0", names[0], f"{port}_input")
    for upstream, downstream in zip(names, names[1:]):
        for port in ports:
            container.add_link(upstream, f"{port}_output", downstream, f"{port}_input")
    for port in ports:
        container.add_output(names[-1], f"{port}_output", port)


@pytest.mark.parametrize("mode", ["parallel", "sequential", "mt"])
def test_many_ports(fmus, mode):
    """Case A: chained instances of Feedthrough, every type of port (point 1)."""
    container = FMUContainer("many", ".", fmi_version=3)
    container.get_fmu("VanDerPol.fmu")
    names = ["Feedthrough.fmu"] + [f"Feedthrough-{i}.fmu" for i in range(1, 4)]
    for name in names:
        container.get_fmu("Feedthrough.fmu", name=name)
    _chain(container, "VanDerPol.fmu", names, PORTS_3)
    container.make_fmu("many.fmu", step_size=0.001, mt=mode == "mt", sequential=mode == "sequential")
    _assert_results("many", [p for p in PORTS_3 if p != "String"], case=f"many-{mode}")


@pytest.mark.needs_compiler
def test_many_ports_fmi2(fmus):
    """Case A with the FMI-2 Feedthrough, compiled for the host (point 1, FMI 2.0 calls)."""
    from fmu_manipulation_toolbox.compiler import OperationCompileSources
    from fmu_manipulation_toolbox.operations import FMU

    rewrite_fmu(DATA_DIR / "compile" / "2.0" / "Feedthrough.fmu", "no-binaries.fmu", drop=("binaries/",))
    with FMU("no-binaries.fmu") as fmu:
        fmu.apply_operation(OperationCompileSources())
        fmu.repack("Feedthrough2.fmu")

    container = FMUContainer("many2", ".", fmi_version=2)
    container.get_fmu("VanDerPol.fmu")
    names = ["Feedthrough2.fmu"] + [f"Feedthrough2-{i}.fmu" for i in range(1, 4)]
    for name in names:
        container.get_fmu("Feedthrough2.fmu", name=name)
    _chain(container, "VanDerPol.fmu", names, PORTS_2)
    container.make_fmu("many2.fmu", step_size=0.001)
    _assert_results("many2", [p for p in PORTS_2 if p != "String"])


def test_me_uncoupled(fmus):
    """Case B: two Model-Exchange FMUs without coupling (point 2: no sweep)."""
    container = FMUContainer("uncoupled", ".", fmi_version=3)
    container.get_fmu("VanDerPolME.fmu")
    container.get_fmu("VanDerPolME.fmu", name="VanDerPolME-1.fmu")
    container.add_output("VanDerPolME.fmu", "x0", "x0")
    container.add_output("VanDerPolME-1.fmu", "x1", "x1")
    container.make_fmu("uncoupled.fmu", step_size=0.001)
    _assert_results("uncoupled", ["x0", "x1"])


@pytest.mark.parametrize("solver", [0, 1], ids=["euler", "rk4"])
def test_me_coupled(fmus, solver):
    """Case C: Model-Exchange FMUs coupled in chain (point 2: targeted sweep)."""
    container = FMUContainer("coupled", ".", fmi_version=3)
    container.get_fmu("VanDerPolME.fmu")
    container.get_fmu("FeedthroughME.fmu")
    container.get_fmu("FeedthroughME.fmu", name="FeedthroughME-1.fmu")
    container.add_link("VanDerPolME.fmu", "x0", "FeedthroughME.fmu", "Float64_continuous_input")
    container.add_link("VanDerPolME.fmu", "x1", "FeedthroughME.fmu", "Float32_continuous_input")
    container.add_link("FeedthroughME.fmu", "Float64_continuous_output", "FeedthroughME-1.fmu",
                       "Float64_continuous_input")
    container.add_link("FeedthroughME.fmu", "Float32_continuous_output", "FeedthroughME-1.fmu",
                       "Float32_continuous_input")
    container.add_output("FeedthroughME-1.fmu", "Float64_continuous_output", "y")
    container.add_output("FeedthroughME-1.fmu", "Float32_continuous_output", "z")
    container.make_fmu("coupled.fmu", step_size=0.001)
    _assert_results("coupled", ["y", "z"], start_values={"container.solver": solver}, case=f"coupled-{solver}")


def test_me_fed_by_cs(fmus):
    """Case D: a Co-Simulation FMU feeds a Model-Exchange FMU (point 2: inputs set once per step)."""
    container = FMUContainer("mixed", ".", fmi_version=3)
    container.get_fmu("VanDerPol.fmu")
    container.get_fmu("FeedthroughME.fmu")
    container.add_link("VanDerPol.fmu", "x0", "FeedthroughME.fmu", "Float64_continuous_input")
    container.add_output("FeedthroughME.fmu", "Float64_continuous_output", "y")
    container.make_fmu("mixed.fmu", step_size=0.001)
    _assert_results("mixed", ["y"])


def _debug_messages(name: str) -> list[str]:
    messages = []
    simulate(f"{name}.fmu", stop_time=0.002, debug_logging=True,
             logger=lambda *args: messages.append(args[-1].decode("utf-8")))
    return messages


def test_me_couplings_are_found(fmus):
    """The solver refreshes only the ME -> ME couplings, found at configuration (point 2), conversions included."""
    container = FMUContainer("found", ".", fmi_version=3)
    container.get_fmu("VanDerPol.fmu")
    container.get_fmu("VanDerPolME.fmu")
    container.get_fmu("FeedthroughME.fmu")
    container.get_fmu("FeedthroughME.fmu", name="FeedthroughME-1.fmu")
    container.add_link("VanDerPolME.fmu", "x0", "FeedthroughME.fmu", "Float64_continuous_input")
    container.add_link("VanDerPolME.fmu", "x1", "FeedthroughME.fmu", "Float32_continuous_input")   # converted
    container.add_link("VanDerPol.fmu", "x0", "FeedthroughME-1.fmu", "Float64_continuous_input")  # from a CS FMU
    container.add_output("FeedthroughME.fmu", "Float64_continuous_output", "y")
    container.make_fmu("found.fmu", step_size=0.001)

    messages = _debug_messages("found")
    assert "Solver: ME FMU 'VanDerPolME.fmu': 0 coupled continuous input(s), feeds an ME FMU." in messages
    assert "Solver: ME FMU 'FeedthroughME.fmu': 2 coupled continuous input(s), does not feed an ME FMU." in messages
    assert "Solver: ME FMU 'FeedthroughME-1.fmu': 0 coupled continuous input(s), does not feed an ME FMU." \
        in messages
