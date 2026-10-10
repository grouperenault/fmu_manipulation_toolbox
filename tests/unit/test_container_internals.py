"""Characterization tests of the container builder internals (docs/local/container.md, phase 0).

They pin the current behaviour of the classes of `container.py` before its refactoring. The tests marked
`xfail(strict=True)` reproduce latent bugs (B1 to B3, B6) and the non-idempotent `make_fmu` (C2): they must start passing
when the bug is fixed, and the marker be removed then.
"""
import importlib
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from fmu_manipulation_toolbox import container_types
from fmu_manipulation_toolbox.container import (ArrayAggregate, EmbeddedFMUPort, FMUContainer, FMUContainerError,
                                                Link, ValueReferenceTable)

pytestmark = [pytest.mark.unit]

REPOSITORY = Path(__file__).resolve().parent.parent.parent
CONVERT_C = REPOSITORY / "container" / "convert.c"


#: Every class importable from `fmu_manipulation_toolbox.container` before its refactoring (phase 2 turns the module
#: into a package: these imports must keep working).
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
    """The class attributes of `EmbeddedFMUPort` and `Link` are aliases of `container_types` (compatibility)."""
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
], ids=["variable", "fixed", "fixed-lcm", "mixed", "none"])
def test_default_step_size(tmp_path, fmus, expected):
    assert _container_with(tmp_path, *fmus).default_step_size() == pytest.approx(expected)


@pytest.mark.xfail(strict=True, reason="B1: one FMU without step size discards the others (TypeError -> 0.1)")
def test_default_step_size_ignores_fmus_without_step_size(tmp_path):
    assert _container_with(tmp_path, (None, True), (0.5, True)).default_step_size() == pytest.approx(0.5)


@pytest.mark.xfail(strict=True, reason="B2: frequencies truncated by int(1.0 / step_size)")
@pytest.mark.parametrize("step_size", [0.3, 2.0])
def test_default_step_size_is_exact(tmp_path, step_size):
    assert _container_with(tmp_path, (step_size, False)).default_step_size() == pytest.approx(step_size)


@pytest.mark.xfail(strict=True, reason="B3: the ratio of the step sizes is compared as a float")
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
def test_duplicate_output_name(bouncing):
    bouncing.add_output("bb_position.fmu", "position1", "out")
    with pytest.raises(FMUContainerError, match="Duplicate OUTPUT out"):
        bouncing.add_output("bb_velocity.fmu", "velocity", "out")


@pytest.mark.area("containers/bouncing_ball")
def test_input_exposed_twice(bouncing):
    bouncing.add_input("v", "bb_position.fmu", "velocity")
    with pytest.raises(FMUContainerError, match="already INPUT"):
        bouncing.add_input("w", "bb_position.fmu", "velocity")


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.xfail(strict=True, reason="B6: an FMU input fed by a container input and by a link is accepted")
def test_input_fed_twice(bouncing):
    bouncing.add_input("v", "bb_position.fmu", "velocity")
    with pytest.raises(FMUContainerError):
        bouncing.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")


@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.parametrize("rule", [
    lambda c: c.add_input("x", "bb_position.fmu", "missing"),
    lambda c: c.add_output("bb_position.fmu", "missing", "x"),
    lambda c: c.drop_port("bb_position.fmu", "missing"),
    lambda c: c.add_link("bb_position.fmu", "missing", "bb_velocity.fmu", "reset"),
    lambda c: c.add_start_value("bb_position.fmu", "missing", "1"),
], ids=["input", "output", "drop", "link", "start"])
def test_missing_port_is_ignored(bouncing, rule, caplog):
    """Current behaviour, to be changed by decision D2 (phase 4): logged and ignored instead of raised."""
    with caplog.at_level(logging.ERROR, logger="fmu_manipulation_toolbox"):
        rule(bouncing)
    assert "does not exist" in caplog.text
    assert not bouncing.rules and not bouncing.start_values


@pytest.mark.area("containers/bouncing_ball")
def test_lossy_link_is_accepted_with_a_warning(bouncing, caplog):
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        bouncing.add_link("bb_velocity.fmu", "velocity", "bb_velocity.fmu", "reset")
    assert "Lossy conversion F64_B" in caplog.text


# --------------------------------------------------------------------------- #
#                                   Build                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.area("containers/bouncing_ball")
@pytest.mark.xfail(strict=True, reason="C2: make_fmu allocates the value references again on the same table")
def test_make_fmu_twice(bouncing):
    bouncing.add_link("bb_position.fmu", "is_ground", "bb_velocity.fmu", "reset")
    bouncing.add_link("bb_velocity.fmu", "velocity", "bb_position.fmu", "velocity")
    bouncing.add_output("bb_position.fmu", "position1", "position")
    bouncing.make_fmu("first.fmu", step_size=0.001, debug=True)
    bouncing.make_fmu("second.fmu", step_size=0.001, debug=True)
    assert Path("first/resources/container.txt").read_text() == Path("second/resources/container.txt").read_text()
