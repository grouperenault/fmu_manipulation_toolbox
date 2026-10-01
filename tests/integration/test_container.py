"""Integration tests for the FMU Container builder (`Assembly` / `FMUContainer`).

Migrated from the legacy ``test_suite.py``. Each test runs in an isolated copy
of its ``tests/data/<area>`` subtree (see the ``area_dir`` fixture); it therefore
``cd``s into that directory and refers to files by their bare, directory-relative
names. Simulation steps that need the platform-specific compiled container binary
keep the original win32 guard; `test_container_mt` is fully ``windows_only``.
"""
import sys
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly
from fmu_manipulation_toolbox.container import FMUContainer

from _helpers.assertions import assert_identical_files, assert_identical_files_but_guid
from _helpers.simulation import assert_simulation

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
    assert_identical_files_but_guid("REF-modelDescription-profiling.xml",
                                    "bouncing-profiling/modelDescription.xml")
    if WIN:
        assert_simulation("bouncing-profiling.fmu")


@pytest.mark.fmi3
@pytest.mark.area("containers/bouncing_ball")
def test_container_bouncing_ball_profiling_3(area_dir):
    assembly = Assembly("bouncing-3.csv", default_profiling=True, debug=True)
    assembly.make_fmu(fmi_version=3)
    assert_identical_files("REF-container-3.txt", "bouncing-3/resources/container.txt")
    assert_identical_files_but_guid("REF-modelDescription-3.xml", "bouncing-3/modelDescription.xml")
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
    assert_identical_files_but_guid("REF-modelDescription.xml", "container-slx/modelDescription.xml")
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

