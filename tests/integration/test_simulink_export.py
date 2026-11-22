"""Export of an assembly as a MATLAB script building its Simulink model (step 3 of
`docs/local/simulink_export.md`)."""
import shutil

import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError, AssemblyNode

pytestmark = [pytest.mark.integration]


@pytest.mark.area("containers/bouncing_ball")
def test_script_is_written_next_to_the_fmus(area_dir):
    script = Assembly("bouncing.csv").make_simulink("ball_model.m")
    text = script.read_text(encoding="utf-8")
    assert script.name == "ball_model.m"
    assert text.startswith("function model = ball_model()\n")       # decision 30: the file names the model
    assert "model = 'ball_model';" in text
    assert "addpath(here);" in text                                 # the FMUs are next to the script


@pytest.mark.area("containers/bouncing_ball")
def test_folders_of_the_fmus_are_relative_to_the_script(area_dir):
    (area_dir / "out").mkdir()
    script = Assembly("bouncing.csv").make_simulink(area_dir / "out" / "model")       # `.m` added
    assert script.name == "model.m"
    assert "addpath(fullfile(here, '..'));" in script.read_text(encoding="utf-8")


@pytest.mark.area("containers/bouncing_ball")
def test_fmus_in_a_sub_folder(area_dir):
    (area_dir / "fmus").mkdir()
    for name in ("bb_position.fmu", "bb_velocity.fmu"):
        shutil.move(name, area_dir / "fmus" / name)
    (area_dir / "bouncing.csv").write_text((area_dir / "bouncing.csv").read_text().replace(";bb_", ";fmus/bb_"))
    script = Assembly("bouncing.csv").make_simulink("model.m")
    assert "addpath(fullfile(here, 'fmus'));" in script.read_text(encoding="utf-8")


@pytest.mark.area("containers/ssp")
def test_ssp_blocks_are_named_after_the_fmu_files(area_dir):
    """The FMUs of an SSP file are named by the paths of their extracted files: the blocks are named after the file
    names, and the script holds no path but the relative folders of the FMUs."""
    assembly = Assembly("bouncing.ssp", fmu_directory=area_dir)
    script = assembly.make_simulink("ssp_model.m").read_text(encoding="utf-8")
    assert "add_block('simulink_extras/FMU Import/FMU', [model '/bb_velocity']" in script
    assert "resources//" not in script and str(area_dir.resolve()) not in script
    assert "addpath(fullfile(here, 'bouncing.dir', 'resources'));" in script


@pytest.mark.area("containers/bouncing_ball")
def test_fmus_designated_by_absolute_paths(area_dir):
    """The Container Builder designates the FMUs by absolute paths: the blocks are named after the file names, the
    folders stay relative to the script."""
    assembly = Assembly(fmu_directory=area_dir)
    root = AssemblyNode("abs.fmu", step_size=0.01, auto_link=False, auto_input=False, auto_output=False)
    root.add_fmu(str((area_dir / "bb_position.fmu").resolve()))
    assembly.root = root
    script = assembly.make_simulink("abs_model.m").read_text(encoding="utf-8")
    assert "[model '/bb_position']" in script
    assert str(area_dir.resolve()) not in script and "addpath(here);" in script


@pytest.mark.area("containers/bouncing_ball")
def test_no_absolute_path(area_dir, monkeypatch):
    """The script holds no absolute path: an FMU on another drive (Windows) is refused (decision 28)."""
    script = Assembly("bouncing.csv").make_simulink("model.m").read_text(encoding="utf-8")
    assert str(area_dir) not in script and str(area_dir.resolve()) not in script

    def relpath(path, start):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")
    monkeypatch.setattr("fmu_manipulation_toolbox.simulink.os.path.relpath", relpath)
    with pytest.raises(AssemblyError, match="another drive"):
        Assembly("bouncing.csv").make_simulink("model.m")


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.parametrize("name", ["1model.m", "my-model.m", "a" * 64 + ".m"])
def test_invalid_script_name_is_refused(area_dir, name):
    with pytest.raises(AssemblyError, match="valid MATLAB identifier"):
        Assembly("bouncing.csv").make_simulink(name)
