"""Integration tests for `fmusplit` (splitting a container FMU back into its
embedded FMUs and reconstructing the assembly JSON).

Migrated from the legacy ``test_suite.py``. Each test runs in an isolated copy
of ``tests/data/split`` (see the ``area_dir`` fixture); the split outputs land
in ``<container>.dir/`` inside ``tmp_path``.
"""
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

    The per-FMU lines give local storage offsets since format 5: format 6 lost a link and named array
    elements instead of the array (container phase 6, B8).
    """
    stem = f"container-array-{dims}"
    Assembly(f"array-{dims}.json").make_fmu(fmi_version=3, filename=f"{stem}.fmu")
    out_dir = _run_fmusplit(stem)
    assert_identical_files(out_dir / f"{stem}.json", DATA_DIR / "split" / f"REF-{stem}.json")
