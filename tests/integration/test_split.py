"""Integration tests for `fmusplit` (splitting a container FMU back into its
embedded FMUs and reconstructing the assembly JSON).

Each test runs in an isolated copy
of ``tests/data/split`` (see the ``area_dir`` fixture); the split outputs land
in ``<container>.dir/`` inside ``tmp_path``.
"""
import json
import sys
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.cli.fmusplit import fmusplit

from _helpers.assertions import assert_identical_files

pytestmark = [pytest.mark.integration, pytest.mark.area("split")]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _run_fmusplit(stem: str):
    sys.argv = ["fmusplit", "-fmu", f"{stem}.fmu"]
    fmusplit()
    return Path(f"{stem}.dir")


@pytest.mark.parametrize("version", [0, 1, 2, 3, 4, 5, 6])
def test_fmusplit_version(area_dir, version):
    """container.txt file-format versions V0..V6 split into gain/integrate/sine."""
    stem = f"container-V{version}"
    out_dir = _run_fmusplit(stem)
    assert (out_dir / "gain.fmu").exists()
    assert (out_dir / "integrate.fmu").exists()
    assert (out_dir / "sine.fmu").exists()
    assert_identical_files(out_dir / f"{stem}.json", f"REF-{stem}.json")


@pytest.mark.fmi3
@pytest.mark.parametrize("dims", ["3", "23", "32"])
def test_fmusplit_array(area_dir, dims):
    """Array-port container connections are detected and linked in the JSON."""
    stem = f"container-array-{dims}"
    out_dir = _run_fmusplit(stem)
    assert_identical_files(out_dir / f"{stem}.json", f"REF-{stem}.json")


@pytest.mark.lsbus
def test_fmusplit_lsbus(area_dir):
    """Terminal-to-terminal (LS-BUS) connections collapse into terminal links."""
    stem = "container-ls-bus"
    out_dir = _run_fmusplit(stem)
    assert_identical_files(out_dir / f"{stem}.json", f"REF-{stem}.json")



@pytest.mark.fmi3
@pytest.mark.area("array")
@pytest.mark.parametrize("dims", ["3", "23", "32"])
def test_fmusplit_array_current_format(area_dir, dims):
    """Containers built with the current container.txt format split like the frozen format 5 ones.

    The per-FMU lines give local storage offsets since format 5: the split must keep every link and name the
    array, not its elements.
    """
    stem = f"container-array-{dims}"
    Assembly(f"array-{dims}.json").make_fmu(fmi_version=3, filename=f"{stem}.fmu")
    out_dir = _run_fmusplit(stem)
    assert_identical_files(out_dir / f"{stem}.json", DATA_DIR / "split" / f"REF-{stem}.json")


@pytest.mark.area("containers/bouncing_ball")
def test_fmusplit_instances_of_one_fmu(area_dir):
    """Each instance is split into its own file, named after the instance: the JSON needs no `path` block and
    rebuilds the same container."""
    Path("two_balls.json").write_text(json.dumps({
        "name": "two_balls.fmu", "auto_link": False, "auto_input": False, "auto_output": False,
        "fmu": ["bb_position.fmu", "bb_velocity.fmu", "bb_position-1.fmu", "bb_velocity-1.fmu"],
        "path": {"bb_position-1.fmu": "bb_position.fmu", "bb_velocity-1.fmu": "bb_velocity.fmu"},
        "link": [["bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset"],
                 ["bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"],
                 ["bb_position-1.fmu", "is_ground", "bb_velocity-1.fmu", "reset"],
                 ["bb_velocity-1.fmu", "velocity", "bb_position-1.fmu", "velocity"]],
        "output": [["bb_position.fmu", "position1", "position"], ["bb_position-1.fmu", "position1", "position_2"]],
    }))
    Assembly("two_balls.json", debug=True).make_fmu()

    out_dir = _run_fmusplit("two_balls")
    for name in ("bb_position.fmu", "bb_velocity.fmu", "bb_position-1.fmu", "bb_velocity-1.fmu"):
        assert (out_dir / name).is_file()
    split = json.loads((out_dir / "two_balls.json").read_text())
    assert sorted(split["fmu"]) == ["bb_position-1.fmu", "bb_position.fmu", "bb_velocity-1.fmu", "bb_velocity.fmu"]
    assert "path" not in split
    assert ["bb_velocity-1.fmu", "velocity", "bb_position-1.fmu", "velocity"] in split["link"]

    Assembly("two_balls.json", fmu_directory=out_dir, debug=True).make_fmu(filename="rebuilt.fmu")
    assert_identical_files("two_balls/resources/container.txt", out_dir / "rebuilt/resources/container.txt")


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.parametrize("fmi_version", [2, 3])
def test_fmusplit_reset_ports(area_dir, fmi_version):
    """The reset triggers come back as rules: an exposed one as an input, one fed by a link (converted to the
    Boolean of an FMI-3 container) as a link; with them, the option `reset_ports`. The JSON rebuilds the same
    container."""
    Path("resettable.json").write_text(json.dumps({
        "name": "resettable.fmu", "auto_link": False, "auto_input": False, "auto_output": False, "reset_ports": True,
        "fmu": ["bb_position.fmu", "bb_velocity.fmu"],
        "input": [["container.bb_position.reset", "bb_position.fmu", "container.reset"]],
        "link": [["bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset"],
                 ["bb_position.fmu", "is_ground", "bb_velocity.fmu", "container.reset"],
                 ["bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"]],
        "output": [["bb_position.fmu", "position1", "position"]],
    }))
    assembly = Assembly("resettable.json", debug=True)
    assembly.make_fmu(fmi_version=fmi_version)
    assembly.write_json("written.json")
    assert json.loads(Path("written.json").read_text())["reset_ports"] is True

    out_dir = _run_fmusplit("resettable")
    split = json.loads((out_dir / "resettable.json").read_text())
    assert split["reset_ports"] is True
    assert ["container.bb_position.reset", "bb_position.fmu", "container.reset"] in split["input"]
    assert ["bb_position.fmu", "is_ground", "bb_velocity.fmu", "container.reset"] in split["link"]
    assert ["bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset"] in split["link"]

    Assembly("resettable.json", fmu_directory=out_dir, debug=True).make_fmu(fmi_version=fmi_version,
                                                                             filename="rebuilt.fmu")
    assert_identical_files("resettable/resources/container.txt", out_dir / "rebuilt/resources/container.txt")
