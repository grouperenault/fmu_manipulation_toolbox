"""Analysis of an assembly for the Simulink export (step 1 of `docs/local/done/simulink_export.md`)."""
import logging
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError, AssemblyNode
from fmu_manipulation_toolbox.simulink import (
    ConstantBlock,
    FmuBlock,
    SimulinkExporter,
    SubsystemBlock,
    TerminatorBlock,
    gcd_of_steps,
    matlab_name,
)

pytestmark = [pytest.mark.unit]


def _node(name, **options):
    return AssemblyNode(name, auto_link=False, auto_input=False, auto_output=False, **options)


@pytest.fixture
def ball(data_dir):
    return data_dir / "containers" / "bouncing_ball"


def test_flat_assembly(ball):
    model = SimulinkExporter(Assembly("bouncing.csv", fmu_directory=ball)).analyse()
    assert model.name == "bouncing"
    assert set(model.fmu_files) == {"bb_position.fmu", "bb_velocity.fmu"}
    position = model.root.blocks["bb_position"]
    assert isinstance(position, FmuBlock)
    assert position.inputs == ["velocity"] and position.outputs == ["is_ground", "position1"]
    lines = {(line.source, line.source_port, line.target, line.target_port) for line in model.root.lines}
    assert ("bb_position", 1, "bb_velocity", 1) in lines and ("bb_position", 2, "position", 1) in lines


def test_reset_ports_give_a_resettable_subsystem(ball, caplog):
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        assembly = Assembly("bouncing-reset.csv", fmu_directory=ball, default_reset_ports=True)
        model = SimulinkExporter(assembly).analyse()
    assert model.root.blocks["bb_velocity"].resettable
    assert not model.root.blocks["bb_position"].resettable
    assert any(line.target_port == "Reset" for line in model.root.lines)
    message = "Reset of FMU 'bb_position.fmu' is neither linked nor exposed: the FMU will never be reset."
    assert message in caplog.messages


def test_nested_multi_rate(ball):
    assembly = Assembly(fmu_directory=ball)
    root, child = _node("nested.fmu", step_size=0.05), _node("sub.fmu", step_size=0.02)
    child.add_fmu("bb_velocity.fmu")
    child.add_input("bounce", "bb_velocity.fmu", "reset")
    child.add_output("bb_velocity.fmu", "velocity", "v")
    root.add_sub_node(child)
    root.add_fmu("bb_position.fmu")
    root.add_link("bb_position.fmu", "is_ground", "sub.fmu", "bounce")
    root.add_link("sub.fmu", "v", "bb_position.fmu", "velocity")
    assembly.root = root
    model = SimulinkExporter(assembly).analyse()
    assert model.fixed_step == pytest.approx(0.01)         # GCD of 0.05 and 0.02 (decision 18)
    sub = model.root.blocks["sub"]
    assert isinstance(sub, SubsystemBlock) and sub.system.inports == ["bounce"]
    assert sub.system.blocks["bb_velocity"].sample_time == 0.02
    assert model.root.blocks["bb_position"].sample_time == 0.05
    # position1 is not connected: a Terminator (decision 22)
    assert any(isinstance(block, TerminatorBlock) for block in model.root.blocks.values())


def test_unconnected_input_gets_a_constant_and_parameters_their_value(ball):
    assembly = Assembly(fmu_directory=ball)
    root = _node("start.fmu", step_size=0.01)
    root.add_fmu("bb_position.fmu")
    root.add_start_value("bb_position.fmu", "velocity", "2.5")
    assembly.root = root
    model = SimulinkExporter(assembly).analyse()
    constants = [block for block in model.root.blocks.values() if isinstance(block, ConstantBlock)]
    assert [constant.value.value for constant in constants] == ["2.5"]


def test_errors(ball, data_dir):
    assembly = Assembly(fmu_directory=ball)
    assembly.root = _node("ts.fmu", step_size=0.01, ts_multiplier=True)
    with pytest.raises(AssemblyError, match="ts_multiplier"):
        SimulinkExporter(assembly).analyse()
    root = _node("bad.fmu", step_size=0.01)
    root.add_fmu("bb_position.fmu")
    root.add_output("bb_position.fmu", "missing", "x")
    assembly.root = root
    with pytest.raises(AssemblyError, match="does not exist"):
        SimulinkExporter(assembly).analyse()
    with pytest.raises(AssemblyError, match="input clocks"):     # decision 27
        SimulinkExporter(Assembly("bus+nodes.json", fmu_directory=data_dir / "ls-bus")).analyse()


def test_helpers():
    assert gcd_of_steps([0.02, 0.05]) == pytest.approx(0.01)
    assert matlab_name("bouncing-ball.fmu") == "bouncing_ball"
    assert matlab_name("2x.fmu") == "model_2x"
    assert Path(matlab_name("a" * 80 + ".fmu")).name == "a" * 63


def test_two_files_with_the_same_name_are_refused(ball, tmp_path):
    """The FMU block designates an FMU by its file name only (decision 28)."""
    other = tmp_path / "other"
    other.mkdir()
    (other / "bb_position.fmu").write_bytes((ball / "bb_position.fmu").read_bytes())
    assembly = Assembly(fmu_directory=ball)
    root = _node("same.fmu", step_size=0.01)
    root.add_fmu("bb_position.fmu")
    root.add_fmu("bb_position-1.fmu", str(other / "bb_position.fmu"))
    assembly.root = root
    with pytest.raises(AssemblyError, match="have the same file name"):
        SimulinkExporter(assembly).analyse()


def test_exposed_parameter_has_no_port(data_dir, tmp_path, caplog):
    """A parameter exposed as an input of the container (e.g. by `auto_parameter`) has no port on the FMU block: it
    is not exposed, with a warning (decision 31)."""
    import zipfile
    with zipfile.ZipFile(tmp_path / "Feedthrough.fmu", "w") as archive:
        archive.write(data_dir / "reference-fmus" / "2.0" / "Feedthrough" / "modelDescription.xml",
                      "modelDescription.xml")
    assembly = Assembly(fmu_directory=tmp_path)
    root = _node("feed.fmu", step_size=0.1)
    root.add_fmu("Feedthrough.fmu")
    root.add_input("p", "Feedthrough.fmu", "Float64_fixed_parameter")
    assembly.root = root
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        model = SimulinkExporter(assembly).analyse()
    assert model.root.inports == []
    assert "'feed.fmu': 'Feedthrough.fmu/Float64_fixed_parameter' is a parameter: the FMU block of Simulink has no " \
           "port for it, it is not exposed." in caplog.messages


def test_loops_are_broken_by_a_unit_delay(ball):
    """The FMU blocks have a direct feedthrough for Simulink: the loop bb_position → bb_velocity → bb_position gets a
    Unit Delay on the line that closes it, with the start value of its source (decision 34)."""
    from fmu_manipulation_toolbox.simulink import DelayBlock
    model = SimulinkExporter(Assembly("bouncing.csv", fmu_directory=ball)).analyse()
    delays = [block for block in model.root.blocks.values() if isinstance(block, DelayBlock)]
    assert len(delays) == 1
    assert delays[0].sample_time == 0.001
    lines = {(line.source, line.target) for line in model.root.lines}
    assert ("bb_position", "bb_velocity") in lines                      # the first link stays direct
    assert ("bb_velocity", delays[0].name) in lines and (delays[0].name, "bb_position") in lines
    assert ("bb_velocity", "bb_position") not in lines


def test_no_delay_without_loop(ball):
    from fmu_manipulation_toolbox.simulink import DelayBlock
    assembly = Assembly(fmu_directory=ball)
    root = _node("chain.fmu", step_size=0.01)
    root.add_fmu("bb_position.fmu")
    root.add_fmu("bb_velocity.fmu")
    root.add_link("bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset")
    assembly.root = root
    model = SimulinkExporter(assembly).analyse()
    assert not any(isinstance(block, DelayBlock) for block in model.root.blocks.values())
