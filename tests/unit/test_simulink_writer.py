"""MATLAB script of the Simulink export (step 2 of `docs/local/simulink_export.md`)."""
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError, AssemblyNode
from fmu_manipulation_toolbox.simulink import (
    MatlabWriter,
    SimulinkExporter,
    StartValue,
    block_path_part,
    matlab_string,
    render_value,
)

pytestmark = [pytest.mark.unit]

REFERENCE = Path(__file__).parent.parent / "data" / "containers" / "bouncing_ball" / "REF-bouncing.m"


@pytest.fixture
def ball(data_dir):
    return data_dir / "containers" / "bouncing_ball"


def _script(assembly: Assembly, folders=(".",)) -> str:
    return MatlabWriter(SimulinkExporter(assembly).analyse(), list(folders), assembly.root.name).render()


def test_escaping():
    assert matlab_string("it's") == "'it''s'"
    assert block_path_part("a/b") == "a//b"


@pytest.mark.parametrize("value, type_name, context, expected", [
    ("1", "boolean", "parameter", "on"), ("false", "boolean1", "parameter", "off"),
    ("true", "boolean", "constant", "true"), ("A.csv", "string", "parameter", "A.csv"),
    ("A.csv", "string", "constant", '"A.csv"'), ("3", "integer32", "parameter", "3"),
    ("0.1", "real64", "parameter", "0.1"), ("2", "real32", "constant", "2.0"),
])
def test_render_value(value, type_name, context, expected):
    assert render_value(StartValue(value, type_name), context) == expected


@pytest.mark.parametrize("value, type_name", [("maybe", "boolean"), ("x", "real64"), ("1.5", "integer32")])
def test_render_value_errors(value, type_name):
    with pytest.raises(AssemblyError):
        render_value(StartValue(value, type_name), "parameter")


def test_reference_script(ball):
    """Snapshot of the script of `bouncing.csv`: to be generated again when the script changes on purpose."""
    script = _script(Assembly("bouncing.csv", fmu_directory=ball))
    assert script == REFERENCE.read_text(encoding="utf-8")


def test_model_settings_and_path(ball):
    assembly = Assembly("bouncing.csv", fmu_directory=ball)
    assembly.root.start_time, assembly.root.stop_time = 0.0, 3.0
    script = _script(assembly, ["fmus", "../shared/fmus"])
    assert script.startswith("function model = bouncing()\n")
    assert "addpath(fullfile(here, 'fmus'));" in script
    assert "addpath(fullfile(here, '..', 'shared', 'fmus'));" in script
    assert "'SolverType', 'Fixed-step', 'FixedStep', '0.001', 'EnableMultiTasking', 'off', 'BlockReduction', 'off', " \
           "'StartTime', '0.0', 'StopTime', '3.0'" in script
    assert "'PreLoadFcn'" in script and script.rstrip().endswith("end")


def test_resettable_subsystem(ball):
    script = _script(Assembly("bouncing-reset.csv", fmu_directory=ball, default_reset_ports=True))
    assert "add_block('built-in/ResetPort', [[model '/bb_velocity'] '/Reset']" in script
    assert "'ResetTriggerType', 'level'" in script
    assert "add_line(model, 'bb_position/1', 'bb_velocity/Reset', 'autorouting', 'on');  % UNVERIFIED" in script
    # the FMU block exists before the lines that reach it
    assert script.index("[[model '/bb_velocity'] '/FMU']") < script.index("'reset/1', 'FMU/1'")


def test_subsystem_ports_exist_before_the_lines_of_the_parent(ball):
    assembly = Assembly(fmu_directory=ball)
    root = AssemblyNode("nested.fmu", step_size=0.01, auto_link=False, auto_input=False, auto_output=False)
    child = AssemblyNode("sub.fmu", step_size=0.01, auto_link=False, auto_input=False, auto_output=False)
    child.add_fmu("bb_velocity.fmu")
    child.add_input("bounce", "bb_velocity.fmu", "reset")
    child.add_output("bb_velocity.fmu", "velocity", "v")
    root.add_sub_node(child)
    root.add_fmu("bb_position.fmu")
    root.add_link("bb_position.fmu", "is_ground", "sub.fmu", "bounce")
    root.add_link("sub.fmu", "v", "bb_position.fmu", "velocity")
    root.add_start_value("bb_position.fmu", "velocity", "1.5")
    assembly.root = root
    script = _script(assembly)
    assert script.index("[[model '/sub'] '/bounce']") < script.index("'bb_position/1', 'sub/1'")
    assert "set_param([model '/bb_position'], 'velocity', '1.5');  % UNVERIFIED" in script
