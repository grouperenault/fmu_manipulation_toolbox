"""Integration tests for the FMU Container builder (`Assembly` / `FMUContainer`).

Each test runs in an isolated copy
of its ``tests/data/<area>`` subtree (see the ``area_dir`` fixture); it therefore
``cd``s into that directory and refers to files by their bare, directory-relative
names. Simulation steps that need the platform-specific compiled container binary
only run on win32; `test_container_mt` is fully ``windows_only``.
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.container import FMUContainer

from _helpers.assertions import VOLATILE_XML_ATTRIBUTES, assert_equivalent_xml, assert_identical_files
from _helpers.simulation import assert_simulation, simulate

pytestmark = [pytest.mark.integration]

WIN = sys.platform == "win32"


# --------------------------------------------------------------------------- #
#                           bouncing_ball                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/bouncing_ball")
def test_container_bouncing_ball(area_dir):
    assembly = Assembly("bouncing.csv", default_mt=True, debug=True)
    assembly.write_json("bouncing.json")
    assembly.make_fmu()
    assembly.write_csv("bouncing2.csv")
    assert_identical_files("REF-container.txt", "bouncing/resources/container.txt")
    assert_identical_files("REF-bouncing.json", "bouncing.json")
    if WIN:
        assert_simulation("bouncing.fmu")


@pytest.mark.area("containers/bouncing_ball")
def test_container_bouncing_ball_seq(area_dir):
    assembly = Assembly("bouncing-seq.csv", default_mt=True, debug=True, default_sequential=True)
    assembly.write_json("bouncing-seq.json")
    assembly.make_fmu()
    assert_identical_files("REF-container-seq.txt", "bouncing-seq/resources/container.txt")
    assert_identical_files("REF-bouncing-seq.json", "bouncing-seq.json")
    if WIN:
        assert_simulation("bouncing-seq.fmu")


@pytest.mark.area("containers/bouncing_ball")
def test_container_bouncing_ball_profiling(area_dir):
    assembly = Assembly("bouncing-profiling.csv", default_profiling=True, debug=True)
    assembly.write_json("bouncing-profiling.json")
    assembly.make_fmu()
    assert_identical_files("REF-container-profiling.txt", "bouncing-profiling/resources/container.txt")
    assert_identical_files("REF-bouncing-profiling.json", "bouncing-profiling.json")
    assert_equivalent_xml("REF-modelDescription-profiling.xml", "bouncing-profiling/modelDescription.xml",
                          ignore_attributes=VOLATILE_XML_ATTRIBUTES)
    if WIN:
        assert_simulation("bouncing-profiling.fmu")


@pytest.mark.fmi3
@pytest.mark.area("containers/bouncing_ball")
def test_container_bouncing_ball_profiling_3(area_dir):
    assembly = Assembly("bouncing-3.csv", default_profiling=True, debug=True)
    assembly.make_fmu(fmi_version=3)
    assert_identical_files("REF-container-3.txt", "bouncing-3/resources/container.txt")
    assert_equivalent_xml("REF-modelDescription-3.xml", "bouncing-3/modelDescription.xml",
                          ignore_attributes=VOLATILE_XML_ATTRIBUTES)
    if WIN:
        assert_simulation("bouncing-3.fmu")


# --------------------------------------------------------------------------- #
#                                  ssp                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/ssp")
def test_container_ssp(area_dir):
    assembly = Assembly("bouncing.ssp")
    assembly.make_fmu(dump_json=True)
    assert_identical_files("REF-bouncing-dump.json", "bouncing-dump.json")
    if WIN:
        assert_simulation("bouncing.fmu")


# --------------------------------------------------------------------------- #
#                                  arch                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/arch")
def test_container_json_flat(area_dir):
    assembly = Assembly("flat.json")
    assembly.make_fmu(dump_json=True)
    assert_identical_files("REF-flat-dump.json", "flat-dump.json")
    if WIN:
        assert_simulation("flat.fmu")


@pytest.mark.area("containers/arch")
def test_container_subdir_flat(area_dir):
    container = FMUContainer("sub.fmu", fmu_directory=Path("."))
    container.get_fmu("subdir/gain2.fmu")
    container.get_fmu("integrate.fmu")
    container.get_fmu("sine.fmu")
    container.add_implicit_rule()
    container.make_fmu("sub.fmu", step_size=0.5)
    if WIN:
        assert_simulation("sub.fmu")


@pytest.mark.area("containers/arch")
def test_container_json_hierarchical(area_dir):
    assembly = Assembly("hierarchical.json")
    assembly.make_fmu(dump_json=True)
    assert_identical_files("REF-hierarchical-dump.json", "hierarchical-dump.json")
    if WIN:
        assert_simulation("hierarchical.fmu")


@pytest.mark.area("containers/arch")
def test_container_json_reversed(area_dir):
    assembly = Assembly("reversed.json")
    assembly.make_fmu(dump_json=True)
    assert_identical_files("REF-reversed-dump.json", "reversed-dump.json")
    if WIN:
        assert_simulation("reversed.fmu")


# --------------------------------------------------------------------------- #
#                                  start                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/start")
def test_container_start(area_dir):
    assembly = Assembly("slx.json", debug=True)
    assembly.make_fmu()
    assert_identical_files("REF-container.txt", "container-slx/resources/container.txt")
    assert_equivalent_xml("REF-modelDescription.xml", "container-slx/modelDescription.xml",
                          ignore_attributes=VOLATILE_XML_ATTRIBUTES)
    if WIN:
        assert_simulation("container-slx.fmu")


# --------------------------------------------------------------------------- #
#                               VanDerPol                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/VanDerPol")
def test_container_vanderpol(area_dir):
    assert_simulation("VanDerPol.fmu", 0.1)
    assembly = Assembly("VanDerPol.json")
    assembly.make_fmu()
    assert_simulation("VanDerPol-Container.fmu", 0.1)


@pytest.mark.area("containers/VanDerPol")
def test_container_vanderpol_vr(area_dir):
    assembly = Assembly("VanDerPol-vr.json")
    assembly.make_fmu()
    if WIN:
        assert_simulation("VanDerPol-vr2.fmu", 0.1)


# --------------------------------------------------------------------------- #
#                                 fmi3                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.fmi3
@pytest.mark.area("fmi3/passthrough")
def test_fmi3_pt2(area_dir):
    assembly = Assembly("passthrough.json", debug=True)
    assembly.make_fmu(fmi_version=2)
    assert_identical_files("REF-container.txt", "container-passthrough/resources/container.txt")
    if WIN:
        assert_simulation("container-passthrough.fmu")


@pytest.mark.area("containers/bouncing_ball")
def test_container_build_is_deterministic(area_dir):
    """Two builds of the same assembly give the same files (the descriptor up to its volatile attributes)."""
    for filename in ("first.fmu", "second.fmu"):
        Assembly("bouncing.csv", debug=True).make_fmu(filename=filename)
    assert_identical_files("first/resources/container.txt", "second/resources/container.txt")
    assert_equivalent_xml("first/modelDescription.xml", "second/modelDescription.xml",
                          ignore_attributes=VOLATILE_XML_ATTRIBUTES)


# --------------------------------------------------------------------------- #
#                                   mt                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.windows_only
@pytest.mark.area("containers/mt")
def test_container_mt(area_dir):
    assembly = Assembly("bb.json")
    assembly.make_fmu(fmi_version=3, filename="bb-3.fmu")
    assert_simulation("bb-3.fmu", 0.1)

    assembly.make_fmu(fmi_version=2, filename="bb-2.fmu")
    assert_simulation("bb-2.fmu", 0.1)



# --------------------------------------------------------------------------- #
#                      several instances of the same FMU                       #
# --------------------------------------------------------------------------- #
#: Two independent bouncing balls: each instance of `bb_position.fmu` is linked to its own `bb_velocity.fmu`.
TWO_BALLS = {
    "name": "two_balls.fmu", "profiling": True, "auto_link": False, "auto_input": False, "auto_output": False,
    "fmu": ["bb_position.fmu", "bb_velocity.fmu", "bb_position-1.fmu", "bb_velocity-1.fmu"],
    "path": {"bb_position-1.fmu": "bb_position.fmu", "bb_velocity-1.fmu": "bb_velocity.fmu"},
    "link": [["bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset"],
             ["bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"],
             ["bb_position-1.fmu", "is_ground", "bb_velocity-1.fmu", "reset"],
             ["bb_velocity-1.fmu", "velocity", "bb_position-1.fmu", "velocity"]],
    "output": [["bb_position.fmu", "position1", "position"],
               ["bb_position-1.fmu", "position1", "position_2"]],
}


def _declared_fmus(resources: Path) -> list[str]:
    """Names of the embedded FMUs declared by `container.txt`, in order."""
    lines = (resources / "container.txt").read_text().splitlines()
    declarations = lines[lines.index("# NB of embedded FMU's") + 1:]
    return [declarations[1 + 3 * i].split()[0] for i in range(sum(int(n) for n in declarations[0].split()))]


@pytest.mark.area("containers/bouncing_ball")
def test_container_with_instances_of_one_fmu(area_dir):
    """Each instance is a distinct embedded FMU, extracted in its own directory and named after the instance. These
    Simulink FMUs declare `canBeInstantiatedOnlyOncePerProcess`: each instance has its own copy of the library."""
    Path("two_balls.json").write_text(json.dumps(TWO_BALLS))
    Assembly("two_balls.json", debug=True).make_fmu()

    resources = Path("two_balls/resources")
    assert _declared_fmus(resources) == TWO_BALLS["fmu"]
    assert sorted(path.name for path in resources.iterdir() if path.is_dir()) == ["00", "01", "02", "03"]
    assert (resources / "00" / "modelDescription.xml").read_bytes() == \
           (resources / "02" / "modelDescription.xml").read_bytes()

    variables = [variable.get("name") for variable in
                 ET.parse("two_balls/modelDescription.xml").getroot().find("ModelVariables")]
    assert "container.bb_position.rt_ratio" in variables and "container.bb_position-1.rt_ratio" in variables

    if WIN:
        result = simulate("two_balls.fmu", stop_time=10, output=["position", "position_2"])
        assert list(result["position"]) == list(result["position_2"])


def _two_balls(kind: str) -> dict:
    """Two independent bouncing balls made of the FMUs `position_<kind>_multiple.fmu` and
    `velocity_<kind>_multiple.fmu`, which support several instances per process."""
    position, velocity = f"position_{kind}_multiple.fmu", f"velocity_{kind}_multiple.fmu"
    position_1, velocity_1 = f"position_{kind}_multiple-1.fmu", f"velocity_{kind}_multiple-1.fmu"
    return {
        "name": f"two_balls_{kind}.fmu", "auto_link": False, "auto_input": False, "auto_output": False,
        "step_size": 0.1,
        "fmu": [position, velocity, position_1, velocity_1],
        "path": {position_1: position, velocity_1: velocity},
        "link": [[position, "reset", velocity, "reset"], [velocity, "velocity", position, "velocity"],
                 [position_1, "reset", velocity_1, "reset"], [velocity_1, "velocity", position_1, "velocity"]],
        "output": [[position, "position", "position"], [position_1, "position", "position_2"]],
    }


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.parametrize("kind, fmi_version", [("cs2", 2), ("me2", 2), ("cs3", 3)])
def test_container_with_instances_simulates_alike(area_dir, kind, fmi_version):
    """Two instances of FMUs which support several instances per process (Windows binaries only), for each kind of
    FMU: on Windows, both balls bounce alike."""
    assembly = _two_balls(kind)
    Path(f"two_balls_{kind}.json").write_text(json.dumps(assembly))
    Assembly(f"two_balls_{kind}.json", debug=True).make_fmu(fmi_version=fmi_version)

    assert _declared_fmus(Path(f"two_balls_{kind}/resources")) == assembly["fmu"]

    if WIN:
        result = simulate(f"two_balls_{kind}.fmu", stop_time=5, output=["position", "position_2"])
        assert len(result) > 1
        assert list(result["position"]) == list(result["position_2"])


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.area("containers/mt")
def test_container_with_instances_simulates(area_dir):
    """Both instances are loaded from their own directory, instantiated and simulated: the FMUs of this area are
    built for every platform and their libraries share one name (`model`)."""
    Path("twice.json").write_text(json.dumps({
        "name": "twice.fmu", "auto_link": False, "auto_input": False, "auto_output": False, "step_size": 0.01,
        "fmu": ["1.fmu", "1-1.fmu"], "path": {"1-1.fmu": "1.fmu"},
        "output": [["1.fmu", "y0", "first"], ["1-1.fmu", "y0", "second"]],
    }))
    Assembly("twice.json").make_fmu(fmi_version=3)

    result = simulate("twice.fmu", stop_time=1, output=["first", "second"])
    assert result["time"][-1] == pytest.approx(1)
