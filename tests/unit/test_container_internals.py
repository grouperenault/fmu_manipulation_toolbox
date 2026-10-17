"""Unit tests of the container builder internals.

They check the classes of the `container` package one by one: public API, conversions (against the C runtime),
container types, value references, FMI-2 array families, step size, rules API and build.
"""
import importlib
import io
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from fmu_manipulation_toolbox.container import types as container_types
from fmu_manipulation_toolbox.container import (ArrayAggregate, ContainerLayout, EmbeddedFMUPort, FMUContainer,
                                                FMUContainerError, Link, ValueReferenceTable)

pytestmark = [pytest.mark.unit]

REPOSITORY = Path(__file__).resolve().parent.parent.parent
CONVERT_C = REPOSITORY / "container" / "convert.c"


#: Public API of the `fmu_manipulation_toolbox.container` package: these classes must stay importable from it.
PUBLIC_NAMES = ("ArrayAggregate", "AutoWired", "Clock", "ClockList", "ContainerInput", "ContainerPort", "EmbeddedFMU",
                "EmbeddedFMUPort", "FMUContainer", "FMUContainerError", "FMUIOList", "IOReference", "InvolvedFMU",
                "Link", "LocalVariable", "Platform", "Port", "ValueReferenceTable")


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_public_names(name):
    module = importlib.import_module("fmu_manipulation_toolbox.container")
    assert isinstance(getattr(module, name), type)


# --------------------------------------------------------------------------- #
#                         Conversions: Python vs C runtime                      #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not CONVERT_C.is_file(), reason="C sources of the container runtime not available")
def test_conversions_match_the_c_runtime():
    """Every conversion written in `container.txt` is implemented by the runtime (`CASE(...)` of convert.c)."""
    c_names = set(re.findall(r"^\s*CASE\((\w+)\);", CONVERT_C.read_text(), flags=re.MULTILINE))
    assert set(Link.CONVERSION_FUNCTION.values()) == c_names


def test_lossy_conversions_are_prefixed():
    """Conversions to a narrower type, between signed and unsigned, or to boolean are flagged with `_`."""
    assert Link.CONVERSION_FUNCTION["real32/real64"] == "F32_F64"
    assert Link.CONVERSION_FUNCTION["real64/real32"] == "_F64_F32"
    assert Link.CONVERSION_FUNCTION["integer32/uinteger32"] == "_D32_U32"
    assert Link.CONVERSION_FUNCTION["real64/boolean"] == "_F64_B"
    assert Link.CONVERSION_FUNCTION["boolean/real64"] == "B_F64"


# --------------------------------------------------------------------------- #
#                                Container types                                #
# --------------------------------------------------------------------------- #
def test_type_tables_are_shared():
    """The class attributes of `EmbeddedFMUPort` and `Link` are aliases of `container.types` (compatibility)."""
    assert EmbeddedFMUPort.ALL_TYPES is container_types.ALL_TYPES
    assert EmbeddedFMUPort.FMI_TO_CONTAINER is container_types.FMI_TO_CONTAINER
    assert EmbeddedFMUPort.CONTAINER_TO_FMI is container_types.CONTAINER_TO_FMI
    assert Link.CONVERSION_FUNCTION is container_types.CONVERSION_FUNCTION


def test_container_to_fmi_is_the_inverse_in_the_same_order():
    """`split.py` reads the FMI-2 types of the old formats in this order."""
    assert list(container_types.CONTAINER_TO_FMI[2].items()) == [
        ("real64", "Real"), ("integer32", "Integer"), ("string", "String"), ("boolean", "Boolean")]
    assert list(container_types.CONTAINER_TO_FMI[3]) == [
        "real64", "real32", "integer8", "uinteger8", "integer16", "uinteger16", "integer32", "uinteger32",
        "integer64", "uinteger64", "string", "boolean1", "binary", "clock"]
    for fmi_version, table in container_types.FMI_TO_CONTAINER.items():
        assert {v: k for k, v in container_types.CONTAINER_TO_FMI[fmi_version].items()} == table


def test_start_value_types():
    assert container_types.START_VALUE_TYPES == container_types.ALL_TYPES[:-2]
    assert container_types.is_lossy("_F64_F32") and not container_types.is_lossy("F32_F64")


# --------------------------------------------------------------------------- #
#                              Value references                                 #
# --------------------------------------------------------------------------- #
def test_value_references_carry_the_type_in_the_upper_byte():
    table = ValueReferenceTable()
    assert table.add_vr("real64") == 0
    assert table.add_vr("real64") == 1
    assert table.add_vr("real32") == 1 << 24
    assert table.add_vr("integer32") == 6 << 24          # 100663296: the TS multiplier slot of container.txt
    assert table.add_vr("integer32") == (6 << 24) | 1    # 100663297: the solver slot
    assert table.add_vr("clock") == 14 << 24


def test_local_storage_offsets_follow_the_dimensions():
    table = ValueReferenceTable()
    first = table.add_vr("real64", local=True, port_size=3)
    second = table.add_vr("real64", local=True)
    exposed = table.add_vr("real64")                     # not local: no storage
    assert (first, second, exposed) == (0, 1, 2)
    assert table.vr_to_local == {first: 0, second: 3}
    assert table.nb_local("real64") == 2
    assert table.nb_storage("real64") == 4
    assert table.nb_storage("integer32") == 0


# --------------------------------------------------------------------------- #
#                              FMI-2 array families                             #
# --------------------------------------------------------------------------- #
def test_array_element_names():
    assert ArrayAggregate.parse_element_name("x[3]") == ("x", (3,))
    assert ArrayAggregate.parse_element_name("a.b[1,2]") == ("a.b", (1, 2))
    assert ArrayAggregate.parse_element_name("x") is None
    assert ArrayAggregate.parse_element_name("x[1][2]") == ("x[1]", (2,))
    assert ArrayAggregate.parse_element_name("x[1, 2]") is None


def test_array_aggregates_are_row_major():
    names = ["m[2,1]", "m[1,2]", "m[1,1]", "m[2,2]", "m[1,3]", "m[2,3]", "v[0]", "v[1]", "scalar"]
    aggregates = {agg.basename: agg for agg in ArrayAggregate.detect_all(names)}
    assert set(aggregates) == {"m", "v"}
    assert aggregates["m"].dims == (2, 3)
    assert aggregates["m"].ordered_element_names == ["m[1,1]", "m[1,2]", "m[1,3]", "m[2,1]", "m[2,2]", "m[2,3]"]
    assert aggregates["v"].dims == (2,)
    assert (aggregates["m"].size, aggregates["m"].rank, aggregates["m"].shape_str) == (6, 2, "2x3")


@pytest.mark.parametrize("names", [
    ["x[1]", "x[3]"],              # hole
    ["x[2]", "x[3]"],              # does not start at 0 or 1
    ["x[1]", "x[1,2]"],            # mixed ranks
    ["x[1,1]", "x[1,2]", "x[2,1]"],  # incomplete rectangle
], ids=["hole", "start", "ranks", "rectangle"])
def test_array_aggregates_reject_incomplete_families(names):
    assert ArrayAggregate.detect_all(names) == []


def test_array_aggregate_does_not_hide_an_existing_port():
    assert ArrayAggregate.detect_all(["x[1]", "x[2]", "x"], existing_names={"x"}) == []


# --------------------------------------------------------------------------- #
#                                  Step size                                    #
# --------------------------------------------------------------------------- #
def _container_with(tmp_path, *fmus) -> FMUContainer:
    """A container whose embedded FMUs are only described by their step size and capability."""
    container = FMUContainer("test", tmp_path)
    for i, (step_size, variable) in enumerate(fmus):
        container.involved_fmu[f"{i}.fmu"] = SimpleNamespace(
            name=f"{i}.fmu", is_me=False, step_size=step_size,
            capabilities={"canHandleVariableCommunicationStepSize": "true" if variable else "false"})
    return container


@pytest.mark.parametrize("fmus, expected", [
    ([(0.1, True), (0.5, True)], 0.5),             # variable steps: the largest one
    ([(0.1, False), (0.2, False)], 0.2),           # fixed steps: their least common multiple
    ([(0.1, False), (0.25, False)], 0.5),
    ([(0.1, False), (0.5, True)], 0.1),            # variable steps ignored when one is fixed
    ([(None, True), (None, True)], 0.1),           # no step size at all: default
    ([(0.2, False), (0.3, False)], 0.6),           # exact least common multiple, no float rounding
    ([(0.1, False), (0.3, False), (None, False)], 0.3),
], ids=["variable", "fixed", "fixed-lcm", "mixed", "none", "exact-lcm", "exact-without-step"])
def test_default_step_size(tmp_path, fmus, expected):
    assert _container_with(tmp_path, *fmus).default_step_size() == pytest.approx(expected)


def test_default_step_size_ignores_fmus_without_step_size(tmp_path):
    assert _container_with(tmp_path, (None, True), (0.5, True)).default_step_size() == pytest.approx(0.5)


@pytest.mark.parametrize("step_size", [0.3, 2.0])
def test_default_step_size_is_exact(tmp_path, step_size):
    assert _container_with(tmp_path, (step_size, False)).default_step_size() == pytest.approx(step_size)


def test_sanity_check_accepts_a_multiple_step_size(tmp_path, caplog):
    container = _container_with(tmp_path, (0.1, False))
    container.involved_fmu["0.fmu"].ports = {}
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        container.sanity_check(0.3)
    assert "divisible" not in caplog.text


# --------------------------------------------------------------------------- #
#                                 Rules API                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture
def bouncing(area_dir) -> FMUContainer:
    container = FMUContainer("bouncing", area_dir)
    container.get_fmu("bb_position.fmu")
    container.get_fmu("bb_velocity.fmu")
    return container


@pytest.mark.area("containers/bouncing_ball")
def test_instances_of_one_fmu_are_distinct(bouncing):
    """An instance is designated by its name, its identifier comes from it, and its rules apply to it only."""
    instance = bouncing.get_fmu("bb_position.fmu", "bb_position-1.fmu")
    assert instance is not bouncing.involved_fmu["bb_position.fmu"]
    assert (instance.name, instance.id) == ("bb_position-1.fmu", "bb_position-1")
    assert bouncing.get_fmu("bb_position-1.fmu") is instance       # rules designate it by name only
    bouncing.add_output("bb_position-1.fmu", "position1", "position_2")
    assert bouncing.outputs["position_2"].fmu is instance


@pytest.mark.area("containers/bouncing_ball")
def test_auto_rules_with_instances(bouncing):
    """Instances are never auto-linked, and a name already exposed is qualified by the id of the FMU."""
    bouncing.get_fmu("bb_position.fmu", "bb_position-1.fmu")
    bouncing.get_fmu("bb_velocity.fmu", "bb_velocity-1.fmu")
    wired = bouncing.add_implicit_rule(auto_link=True, auto_input=True, auto_output=True)

    assert wired.rule_link == [["bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"]]
    assert sorted(bouncing.outputs) == ["bb_position-1.is_ground", "bb_position-1.position1", "is_ground",
                                        "position1", "velocity"]
    assert bouncing.outputs["velocity"].fmu.name == "bb_velocity-1.fmu"
    assert sorted(bouncing.inputs) == ["bb_position-1.velocity", "bb_velocity-1.reset", "reset"]


@pytest.mark.area("containers/bouncing_ball")
def test_one_name_cannot_designate_two_files(bouncing):
    bouncing.get_fmu("bb_position.fmu", "model-1.fmu")
    with pytest.raises(FMUContainerError, match="already designates"):
        bouncing.get_fmu("bb_velocity.fmu", "model-1.fmu")


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.parametrize("rule, message", [
    (lambda c: c.add_input("x", "bb_position.fmu", "position1"), "as INPUT of the container"),
    (lambda c: c.add_output("bb_position.fmu", "velocity", "v"), "as OUTPUT of the container"),
    (lambda c: c.drop_port("bb_position.fmu", "velocity"), "trying to DROP input"),
    (lambda c: c.add_link("bb_position.fmu", "velocity", "bb_velocity.fmu", "reset"), "instead of OUTPUT"),
    (lambda c: c.add_link("bb_position.fmu", "position1", "bb_velocity.fmu", "velocity"), "instead of INPUT"),
    (lambda c: c.add_start_value("bb_position.fmu", "velocity", "fast"), "not conforming to real64"),
    (lambda c: c.add_start_value("bb_position.fmu", "velocity", "1 2"), "dimension 1"),
], ids=["input-causality", "output-causality", "drop-causality", "link-from-input", "link-to-output",
        "start-format", "start-dimension"])
def test_rule_errors(bouncing, rule, message):
    with pytest.raises(FMUContainerError, match=message):
        rule(bouncing)


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.parametrize("value, expected", [(True, "true"), (False, "false"), ("true", "true"), ("0", "0")])
def test_boolean_start_value(bouncing, value, expected):
    """A Python bool (JSON true/false) is accepted as the start value of a Boolean port."""
    bouncing.add_start_value("bb_velocity.fmu", "reset", value)
    assert list(bouncing.start_values.values()) == [expected]


@pytest.mark.area("containers/bouncing_ball")
def test_duplicate_output_name(bouncing):
    bouncing.add_output("bb_position.fmu", "position1", "out")
    with pytest.raises(FMUContainerError, match="Duplicate OUTPUT out"):
        bouncing.add_output("bb_velocity.fmu", "velocity", "out")


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.parametrize("first, second, message", [
    (lambda c: c.add_input("v", "bb_position.fmu", "velocity"),
     lambda c: c.add_input("w", "bb_position.fmu", "velocity"), "the container input 'v'"),
    (lambda c: c.add_input("v", "bb_position.fmu", "velocity"),
     lambda c: c.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"), "the container input 'v'"),
    (lambda c: c.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"),
     lambda c: c.add_input("v", "bb_position.fmu", "velocity"), "a link from Port bb_velocity.fmu/velocity"),
    (lambda c: c.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity"),
     lambda c: c.add_link("bb_position.fmu", "position1", "bb_position.fmu", "velocity"),
     "a link from Port bb_velocity.fmu/velocity"),
], ids=["input-input", "input-link", "link-input", "link-link"])
def test_input_fed_twice(bouncing, first, second, message):
    """An input of an embedded FMU has one feeder, a container input or a link."""
    first(bouncing)
    with pytest.raises(FMUContainerError, match=f"Port bb_position.fmu/velocity is already fed by {message}"):
        second(bouncing)


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.parametrize("rule", [
    lambda c: c.add_input("x", "bb_position.fmu", "missing"),
    lambda c: c.add_output("bb_position.fmu", "missing", "x"),
    lambda c: c.drop_port("bb_position.fmu", "missing"),
    lambda c: c.add_link("bb_position.fmu", "missing", "bb_velocity.fmu", "reset"),
    lambda c: c.add_start_value("bb_position.fmu", "missing", "1"),
], ids=["input", "output", "drop", "link", "start"])
def test_missing_port_is_an_error(bouncing, rule):
    """A rule on a missing port raises instead of being logged and ignored."""
    with pytest.raises(FMUContainerError, match="Port 'bb_position.fmu/missing' does not exist"):
        rule(bouncing)
    assert not bouncing.rules and not bouncing.start_values


@pytest.mark.area("containers/bouncing_ball")
def test_missing_fmu_is_an_error(bouncing):
    with pytest.raises(FMUContainerError, match="Cannot add input 'x': Cannot load 'missing.fmu'"):
        bouncing.add_input("x", "missing.fmu", "u")


@pytest.mark.area("containers/bouncing_ball")
def test_lossy_link_is_accepted_with_a_warning(bouncing, caplog):
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        bouncing.add_link("bb_velocity.fmu", "velocity", "bb_velocity.fmu", "reset")
    assert "Lossy conversion F64_B" in caplog.text


# --------------------------------------------------------------------------- #
#                                   Build                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/bouncing_ball")
def test_make_fmu_twice(bouncing):
    bouncing.add_link("bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset")
    bouncing.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    bouncing.add_output("bb_position.fmu", "position1", "position")
    bouncing.make_fmu("first.fmu", step_size=0.001, debug=True)
    bouncing.make_fmu("second.fmu", step_size=0.001, debug=True)
    assert Path("first/resources/container.txt").read_text() == Path("second/resources/container.txt").read_text()


@pytest.mark.area("containers/bouncing_ball")
def test_make_fmu_leaves_the_rules_unchanged(bouncing):
    """The value references live in the layout of each build; start and stop times stay unset."""
    bouncing.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    bouncing.add_input("reset", "bb_velocity.fmu", "reset")
    bouncing.add_output("bb_position.fmu", "position1", "position")
    ports = {name: dict(vars(port)) for name, port in bouncing.involved_fmu["bb_position.fmu"].ports.items()}
    bouncing.make_fmu("container.fmu", step_size=0.001)
    assert (bouncing.start_time, bouncing.stop_time) == (None, None)
    assert {name: dict(vars(port)) for name, port in bouncing.involved_fmu["bb_position.fmu"].ports.items()} == ports


def test_layout_allocation_order():
    """Reserved variables first, then the links, then the container inputs and outputs."""
    layout = ContainerLayout.allocate([], {}, {}, nb_profiling=2)
    assert (layout.time, layout.ts_multiplier, layout.solver, layout.profiling) == (0, 6 << 24, (6 << 24) | 1, [1, 2])
    assert [layout.local_offset(vr) for vr in (layout.time, *layout.profiling, layout.ts_multiplier, layout.solver)] \
        == [0, 1, 2, 0, 1]


def test_port_xml_has_no_side_effect():
    """The default variability is computed for the XML element only."""
    port = EmbeddedFMUPort("real64", {"name": "x", "valueReference": 1, "causality": "output"})
    variable = port.xml(7, fmi_version=3)
    assert variable.get("variability") == "continuous" and variable.get("valueReference") == "7"
    assert port.variability is None


def _fake_fmu(name: str, ports):
    """Just enough of an EmbeddedFMU for the rules API and the container.txt writer."""
    return SimpleNamespace(
        name=name, id=name[:-4], fmi_version=2, is_me=False, terminals={}, ls=SimpleNamespace(is_bus=False),
        model_identifier=name[:-4], guid="{guid}", has_event_mode=False,
        ports={port_name: EmbeddedFMUPort(type_name, {"name": port_name, "valueReference": vr, "causality": causality})
               for port_name, type_name, causality, vr in ports})


def test_one_converted_copy_per_target_type(tmp_path):
    """A link feeding two inputs of the same converted type gets one converted copy and one conversion."""
    container = FMUContainer("test", tmp_path)
    container.involved_fmu["a.fmu"] = _fake_fmu("a.fmu", [("y", "real64", "output", 1)])
    container.involved_fmu["b.fmu"] = _fake_fmu("b.fmu", [("u1", "boolean", "input", 1), ("u2", "boolean", "input", 2)])
    container.add_link("a.fmu", "y", "b.fmu", "u1")
    container.add_link("a.fmu", "y", "b.fmu", "u2")
    layout = ContainerLayout.allocate(container.links.values(), container.inputs, container.outputs)
    txt = io.StringIO()
    container.make_fmu_txt(txt, 0.1, False, False, False, layout)
    lines = txt.getvalue().splitlines()

    converted = layout.converted[next(iter(container.links.values()))]["boolean"]
    boolean = lines.index("# boolean")
    assert lines[boolean + 1:boolean + 3] == ["1 1", f"{converted} 1 1 -1 0"]
    assert lines[boolean + 3] == "# boolean1"
    table = lines.index("# Conversion table of a.fmu: <VR_FROM> <VR_TO> <CONVERSION>")
    assert lines[table + 1:table + 3] == ["1", f"{layout.links[next(iter(container.links.values()))]} {converted} _F64_B"]
    assert lines[table + 3:table + 5] == ["# Reset trigger of a.fmu: <LOCAL_OFFSET>", "-1"]
    assert lines[table + 5].startswith("# Inputs of b.fmu")
    # Both inputs read the same converted copy (local offset 0 of the booleans).
    inputs = lines.index("# Inputs of b.fmu - boolean: <LOCAL_OFFSET> <DIM> <FMU_VR>")
    assert lines[inputs + 1:inputs + 4] == ["2", "0 1 1", "0 1 2"]


# --------------------------------------------------------------------------- #
#                         Reset ports (container.reset)                         #
# --------------------------------------------------------------------------- #
@pytest.fixture
def resettable(area_dir) -> FMUContainer:
    container = FMUContainer("bouncing", area_dir, reset_ports=True)
    container.get_fmu("bb_position.fmu")
    container.get_fmu("bb_velocity.fmu")
    return container


def _container_txt(container: FMUContainer) -> tuple[ContainerLayout, list[str]]:
    layout = ContainerLayout.allocate(container.links.values(), container.inputs, container.outputs)
    txt = io.StringIO()
    container.make_fmu_txt(txt, 0.1, False, False, False, layout)
    return layout, txt.getvalue().splitlines()


def _reset_trigger(lines: list[str], fmu_name: str) -> int:
    return int(lines[lines.index(f"# Reset trigger of {fmu_name}: <LOCAL_OFFSET>") + 1])


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.parametrize("fmi_version, type_name", [(2, "boolean"), (3, "boolean1")])
def test_reset_ports_option(area_dir, fmi_version, type_name):
    """Each embedded FMU gets a `container.reset` input of the Boolean type of the container, with the option only."""
    container = FMUContainer("bouncing", area_dir, fmi_version=fmi_version, reset_ports=True)
    port = container.get_fmu("bb_position.fmu").ports["container.reset"]
    assert (port.is_reset, port.causality, port.type_name) == (True, "input", type_name)

    assert "container.reset" not in FMUContainer("plain", area_dir).get_fmu("bb_position.fmu").ports


@pytest.mark.area("containers/bouncing_ball")
def test_reset_ports_exposed_by_auto_input(resettable):
    """auto_input exposes each reset port as `container.<id>.reset`, stored locally: the runtime reads it there."""
    resettable.add_link("bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset")
    resettable.add_implicit_rule(auto_input=True, auto_output=False, auto_link=False)
    assert {"container.bb_position.reset", "container.bb_velocity.reset"} <= set(resettable.inputs)

    layout, lines = _container_txt(resettable)
    offsets = []
    for fmu in ("bb_position", "bb_velocity"):
        name = f"container.{fmu}.reset"
        offset = layout.reset_inputs[name]
        assert f"{layout.inputs[name]} 1 1 -1 {offset}" in lines
        assert _reset_trigger(lines, f"{fmu}.fmu") == offset
        offsets.append(offset)
    assert len(set(offsets)) == 2


@pytest.mark.area("containers/bouncing_ball")
def test_reset_port_fed_by_a_link(resettable):
    """A link to a reset port is read by the container from its local variable, and never set to the FMU."""
    resettable.add_link("bb_position.fmu", "is_ground", "bb_velocity.fmu", "container.reset")
    layout, lines = _container_txt(resettable)

    link = next(iter(resettable.links.values()))
    assert _reset_trigger(lines, "bb_velocity.fmu") == layout.local_offset(layout.links[link])
    assert _reset_trigger(lines, "bb_position.fmu") == -1
    inputs = lines.index("# Inputs of bb_velocity.fmu - boolean: <LOCAL_OFFSET> <DIM> <FMU_VR>")
    assert lines[inputs + 1] == "0"


@pytest.mark.area("containers/bouncing_ball")
def test_reset_input_fans_out(resettable):
    """One container input may reset several FMUs, and feed regular inputs too: the reset ports share one local
    variable, listed first."""
    for fmu_name, port_name in (("bb_position.fmu", "container.reset"), ("bb_velocity.fmu", "container.reset"),
                                ("bb_velocity.fmu", "reset")):
        resettable.add_input("reset_all", fmu_name, port_name)
    layout, lines = _container_txt(resettable)

    offset = layout.reset_inputs["reset_all"]
    reset_vr = resettable.involved_fmu["bb_velocity.fmu"].ports["reset"].vr
    assert f"{layout.inputs['reset_all']} 1 2 -1 {offset} 1 {reset_vr}" in lines
    assert _reset_trigger(lines, "bb_position.fmu") == _reset_trigger(lines, "bb_velocity.fmu") == offset


def test_reset_port_does_not_replace_a_real_port(tmp_path):
    """An FMU with a real port named `container.reset` cannot be embedded with reset_ports: the port is not hidden."""
    container = FMUContainer("test", tmp_path, reset_ports=True)
    fmu = _fake_fmu("a.fmu", [("container.reset", "boolean", "input", 1)])
    with pytest.raises(FMUContainerError, match="reserves this name"):
        container.add_reset_port(fmu)
    assert not fmu.ports["container.reset"].is_reset


@pytest.mark.area("containers/bouncing_ball")
def test_default_reset_input_name_is_not_merged(resettable):
    """Exposed without explicit name, a reset is not merged into a container input of the same name; an explicit
    name still feeds several ports."""
    resettable.add_input("container.bb_velocity.reset", "bb_position.fmu", "container.reset")
    with pytest.raises(FMUContainerError, match="already has a variable"):
        resettable.add_input("", "bb_velocity.fmu", "container.reset")
    with pytest.raises(FMUContainerError, match="already has a variable"):
        resettable.add_implicit_rule(auto_input=True, auto_output=False, auto_link=False)

    resettable.add_input("container.bb_velocity.reset", "bb_velocity.fmu", "container.reset")
    assert len(resettable.inputs["container.bb_velocity.reset"].cport_list) == 2


@pytest.mark.area("containers/bouncing_ball")
def test_reset_port_has_no_start_value(resettable):
    with pytest.raises(FMUContainerError, match="drives the reset"):
        resettable.add_start_value("bb_position.fmu", "container.reset", "true")


@pytest.mark.area("containers/bouncing_ball")
def test_unwired_reset_port_is_a_warning(resettable, caplog):
    """A reset port neither linked nor exposed is reported as a warning, not as an unconnected input."""
    with caplog.at_level(logging.DEBUG, logger="fmu_manipulation_toolbox"):
        resettable.sanity_check(0.1)
    assert "Reset of FMU 'bb_velocity.fmu' is neither linked nor exposed" in caplog.text
    assert "container.reset' is not connected" not in caplog.text


@pytest.mark.area("containers/bouncing_ball")
def test_reset_input_in_model_description(resettable):
    resettable.add_input("", "bb_velocity.fmu", "container.reset")
    resettable.make_fmu("reset.fmu", step_size=0.001, debug=True)

    variables = {variable.get("name"): variable
                 for variable in ET.parse("reset/modelDescription.xml").getroot().find("ModelVariables")}
    variable = variables["container.bb_velocity.reset"]
    assert (variable.get("causality"), variable.get("variability")) == ("input", "discrete")
    assert variable.find("Boolean").get("start") == "false"
