"""Golden files of the container builder (docs/local/done/container.md, phase 0).

Each scenario builds a container from a description file and compares the generated `container.txt`, `datalog.txt`
and `modelDescription.xml` with references stored next to the input data (`REF-golden-<scenario>-...`). They cover
the configurations that the other tests only exercise through simulations: Model Exchange, mixed CS/ME, LS-BUS,
arrays, multi-threading, profiling, `ts_multiplier`.

The text files are compared line by line, whitespace included; the descriptors are compared in canonical form,
without the attributes that change at every build. Regenerate the references with `--update-refs`, after review.
"""
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly

from _helpers.assertions import VOLATILE_XML_ATTRIBUTES, assert_equivalent_xml, assert_identical_text

pytestmark = [pytest.mark.integration]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: GUID generated at each build (`uuid.uuid4()`, without braces): a nested container shows it in the
#: `container.txt` of its parent. The GUIDs of the embedded FMUs are written with braces and stay compared.
GENERATED_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


@dataclass
class Scenario:
    id: str
    area: str
    description: str
    #: Built containers, by directory of the build (`debug=True` keeps it).
    containers: tuple[str, ...]
    fmi_version: int = 2
    datalog: bool = False
    filename: str | None = None
    assembly_options: dict = field(default_factory=dict)


SCENARIOS = [
    Scenario("me", "me", "bouncing_ball_me.json", ("bouncing_ball_me",)),
    Scenario("me-mt", "me", "bouncing_ball_me.json", ("bouncing_ball_me",), assembly_options={"default_mt": True}),
    Scenario("mix", "me", "bouncing_ball_mix.json", ("bouncing_ball_mix",)),
    Scenario("bus-nodes", "ls-bus", "bus+nodes.json", ("bus+nodes",), fmi_version=3, datalog=True),
    Scenario("nodes-only", "ls-bus", "nodes-only.json", ("nodes-only",), fmi_version=3, datalog=True),
    Scenario("array-2", "array", "array-2.json", ("array-2",)),
    Scenario("array-3", "array", "array-3.json", ("array-3",), fmi_version=3),
    Scenario("mt-2", "containers/mt", "bb.json", ("bb-2",), filename="bb-2.fmu"),
    Scenario("mt-3", "containers/mt", "bb.json", ("bb-3",), fmi_version=3, filename="bb-3.fmu"),
    Scenario("profiling", "containers/VanDerPol", "VanDerPol.json", ("VanDerPol-Container",), datalog=True),
    Scenario("ts-multiplier", "containers/VanDerPol", "VanDerPol-vr.json", ("nested", "VanDerPol-vr2")),
]


def _check(reference: Path, produced: Path, update_refs: bool, compare) -> None:
    assert produced.exists(), f"{produced} was not generated"
    if update_refs:
        shutil.copyfile(produced, reference)
    elif not reference.exists():
        pytest.fail(f"Missing reference {reference}. Generate it with --update-refs.")
    else:
        compare(reference, produced)


def _compare_text(reference: Path, produced: Path) -> None:
    assert_identical_text(reference, produced, ignore=GENERATED_GUID)


def _compare_xml(reference: Path, produced: Path) -> None:
    assert_equivalent_xml(reference, produced, ignore_attributes=VOLATILE_XML_ATTRIBUTES)


@pytest.mark.parametrize("scenario", [pytest.param(s, id=s.id, marks=pytest.mark.area(s.area)) for s in SCENARIOS])
def test_container_golden(area_dir, scenario, update_refs):
    assembly = Assembly(scenario.description, debug=True, **scenario.assembly_options)
    assembly.make_fmu(fmi_version=scenario.fmi_version, datalog=scenario.datalog, filename=scenario.filename)

    references = DATA_DIR / scenario.area
    for container in scenario.containers:
        prefix = f"REF-golden-{scenario.id}" + (f"-{container}" if len(scenario.containers) > 1 else "")
        _check(references / f"{prefix}-container.txt", Path(container) / "resources" / "container.txt",
               update_refs, _compare_text)
        _check(references / f"{prefix}-modelDescription.xml", Path(container) / "modelDescription.xml",
               update_refs, _compare_xml)
        if scenario.datalog and container == scenario.containers[-1]:
            _check(references / f"{prefix}-datalog.txt", Path(container) / "resources" / "datalog.txt",
                   update_refs, _compare_text)


@pytest.mark.area("containers/bouncing_ball")
def test_container_build_is_deterministic(area_dir):
    """Two builds of the same assembly give the same files (the descriptor up to its volatile attributes)."""
    for filename in ("first.fmu", "second.fmu"):
        Assembly("bouncing.csv", debug=True).make_fmu(filename=filename)
    _compare_text(Path("first/resources/container.txt"), Path("second/resources/container.txt"))
    _compare_xml(Path("first/modelDescription.xml"), Path("second/modelDescription.xml"))
