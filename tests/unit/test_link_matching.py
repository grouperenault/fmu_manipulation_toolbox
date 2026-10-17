"""Unit tests of the matching engine of the link assistant (``gui/fmucontainer/details/link_matching.py``).

The engine is pure Python: these tests do not need PySide6.
"""

import time

import pytest

from fmu_manipulation_toolbox.gui.fmucontainer.details.link_matching import (
    PortInfo, Checks, SameNameRule, AffixRule, RegexRule, SimilarityRule,
    suggest, link_status, staged_statuses, normalize, with_overlaps, OK, WARNING, ERROR,
    ALREADY_FED, SIZE_MISMATCH, INCOMPATIBLE_TYPE, LOSSY, UNIT_MISMATCH, SIMILAR_NAME, DUPLICATE_TARGET,
)

pytestmark = [pytest.mark.unit]


def out(name, fmi_type="Real", unit="", size=1):
    return PortInfo(name, "output", fmi_type, 2, unit, "", size)


def inp(name, fmi_type="Float64", unit="", size=1):
    return PortInfo(name, "input", fmi_type, 3, unit, "", size)


def pairs(suggestions):
    return {(s.output.name, s.input.name) for s in suggestions}


def test_normalize():
    assert normalize("Throttle_Pos") == normalize("throttle.pos") == "throttlepos"
    assert normalize("wheel.speed[1]") == "wheelspeed1"


@pytest.mark.parametrize("rule, outputs, inputs, expected_strict, expected_ignore_case", [
    (SameNameRule(), ["a.x", "Throttle_Pos"], ["a.x", "throttle.pos"],
     {("a.x", "a.x")}, {("a.x", "a.x"), ("Throttle_Pos", "throttle.pos")}),
    (AffixRule("engine.out.", "ecu.in.engine_"), ["engine.out.speed", "Engine_Out_Torque"],
     ["ecu.in.engine_speed", "ecu.in.engine_torque"],
     {("engine.out.speed", "ecu.in.engine_speed")},
     {("engine.out.speed", "ecu.in.engine_speed"), ("Engine_Out_Torque", "ecu.in.engine_torque")}),
    (AffixRule(from_suffix="_degC", to_suffix="_temp"), ["oil_degC"], ["oil_temp"],
     {("oil_degC", "oil_temp")}, {("oil_degC", "oil_temp")}),
    (RegexRule(r"^sensor\.(\w+)\.(\w+)$", r"sensor_\2_\1"), ["sensor.cam.angle", "SENSOR.crank.speed"],
     ["sensor_angle_cam", "sensor_speed_crank"],
     {("sensor.cam.angle", "sensor_angle_cam")},
     {("sensor.cam.angle", "sensor_angle_cam"), ("SENSOR.crank.speed", "sensor_speed_crank")}),
    (SimilarityRule(0.7), ["chassis.pressure"], ["chassis.press"],
     {("chassis.pressure", "chassis.press")}, {("chassis.pressure", "chassis.press")}),
])
def test_criteria_with_and_without_ignore_case(rule, outputs, inputs, expected_strict, expected_ignore_case):
    outputs = [out(name) for name in outputs]
    inputs = [inp(name) for name in inputs]
    assert pairs(suggest(outputs, inputs, rule, ignore_case=False)) == expected_strict
    assert pairs(suggest(outputs, inputs, rule, ignore_case=True)) == expected_ignore_case


def test_input_proposed_once():
    suggestions = suggest([out("speed"), out("Speed")], [inp("speed")], SameNameRule(), ignore_case=True)
    assert pairs(suggestions) == {("speed", "speed")}


def test_similarity_takes_the_next_free_input():
    suggestions = suggest([out("chassis.pressure1"), out("chassis.pressure2")],
                          [inp("chassis.press1"), inp("chassis.press2")], SimilarityRule(0.7))
    assert pairs(suggestions) == {("chassis.pressure1", "chassis.press1"), ("chassis.pressure2", "chassis.press2")}


def test_excluded_ports_are_not_proposed():
    suggestions = suggest([out("x"), out("y")], [inp("x"), inp("y")], SameNameRule(),
                          excluded_outputs={"x"}, excluded_inputs={"y"})
    assert suggestions == []


def test_invalid_regex_matches_nothing():
    assert suggest([out("x")], [inp("x")], RegexRule("(", "x")) == []


@pytest.mark.parametrize("output, input, checks, level, codes", [
    (out("x"), inp("x"), None, OK, ()),
    (out("x"), inp("x", "Int32"), None, WARNING, (LOSSY,)),
    (out("x"), inp("x", "String"), None, ERROR, (INCOMPATIBLE_TYPE,)),
    (out("x"), inp("x", "String"), Checks(compatible_type=False), WARNING, (INCOMPATIBLE_TYPE,)),
    (out("x", unit="degC"), inp("x", unit="K"), None, WARNING, (UNIT_MISMATCH,)),
    (out("x", unit="degC"), inp("x", unit="K"), Checks(same_unit=True), ERROR, (UNIT_MISMATCH,)),
    (out("x", unit="degC"), inp("x", "Int32", unit="K"), None, WARNING, (LOSSY, UNIT_MISMATCH)),
    (out("x", size=4), inp("x", size=2), None, ERROR, (SIZE_MISMATCH,)),
    (out("x", size=4), inp("x", size=4), None, OK, ()),
    # An Enumeration is handled as an integer by the container (`EmbeddedFMU.port_attrs`).
    (out("x", "Enumeration"), inp("x", "Int32"), None, OK, ()),
    (out("x", "Enumeration"), inp("x", "Float64"), None, WARNING, (LOSSY,)),   # as integer32 → real64
    # FMI 3.0 accesses an Enumeration as an Int64.
    (PortInfo("x", "output", "Enumeration", 3), inp("x", "Int64"), None, OK, ()),
    (PortInfo("x", "output", "Enumeration", 3), inp("x", "Int32"), None, WARNING, (LOSSY,)),   # integer64 → 32
    (out("x", "Integer"), PortInfo("x", "input", "Enumeration", 3), None, OK, ()),             # integer32 → 64
])
def test_link_status(output, input, checks, level, codes):
    status = link_status(output, input, checks=checks)
    assert (status.level, status.codes) == (level, codes)


def test_fed_input_is_proposed_with_an_error():
    suggestions = suggest([out("x")], [inp("x")], SameNameRule(), fed={"x"})
    assert suggestions[0].status.codes == (ALREADY_FED,) and not suggestions[0].checked


def test_similar_name_is_a_warning():
    suggestions = suggest([out("chassis.pressure")], [inp("chassis.press")], SimilarityRule(0.7))
    assert suggestions[0].status.codes == (SIMILAR_NAME,) and suggestions[0].checked


def test_staged_statuses_detect_two_feeders():
    statuses = staged_statuses([(out("a"), inp("x")), (out("b"), inp("x")), (out("c"), inp("y"))])
    assert [status.codes for status in statuses] == [(DUPLICATE_TARGET,), (DUPLICATE_TARGET,), ()]


AGGREGATES = {"u": ["u[1]", "u[2]"]}


def test_with_overlaps():
    assert with_overlaps({"u"}, AGGREGATES) == {"u", "u[1]", "u[2]"}
    assert with_overlaps({"u[2]"}, AGGREGATES) == {"u", "u[2]"}
    assert with_overlaps({"x"}, AGGREGATES) == {"x"}


def test_aggregate_and_element_are_the_same_input():
    links = [(out("y", size=2), inp("u", size=2)), (out("z"), inp("u[1]")), (out("w"), inp("v"))]
    assert [status.codes for status in staged_statuses(links, aggregates=AGGREGATES)] == \
        [(DUPLICATE_TARGET,), (DUPLICATE_TARGET,), ()]


SUBSYSTEMS = ("intake", "exhaust", "turbo", "injection", "cooling", "lube", "crank", "cam", "egr", "throttle")
QUANTITIES = ("speed", "torque", "pressure", "temperature", "mass_flow", "position", "voltage", "current", "angle",
              "ratio")


def _large_ports(count):
    """`count` outputs `engine.out.<signal>`; the inputs are `ecu.in.engine_<signal>` for one half (found by a prefix
    or a regex) and the abbreviated `engine.out.<signal without its last letter>` for the other half (found by
    "Similar names" only)."""
    signals = [f"{subsystem}{index}_{quantity}" for index in range(count // 100 + 1)
               for subsystem in SUBSYSTEMS for quantity in QUANTITIES][:count]
    outputs = [out(f"engine.out.{signal}") for signal in signals]
    inputs = [inp(f"ecu.in.engine_{signal}" if k % 2 else f"engine.out.{signal[:-1]}")
              for k, signal in enumerate(signals)]
    abbreviated = {(f"engine.out.{signal}", f"engine.out.{signal[:-1]}") for k, signal in enumerate(signals)
                   if not k % 2}
    return outputs, inputs, abbreviated


@pytest.mark.parametrize("rule", [
    SameNameRule(),
    AffixRule("engine.out.", "ecu.in.engine_"),
    RegexRule(r"^engine\.out\.(.*)$", r"ecu.in.engine_\1"),
    SimilarityRule(0.8),
])
def test_2000_ports_in_a_reasonable_time(rule):
    outputs, inputs, abbreviated = _large_ports(2000)
    start = time.perf_counter()
    found = pairs(suggest(outputs, inputs, rule))
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"{rule.kind}: {elapsed:.2f} s"
    expected = {(output.name, output.name.replace("engine.out.", "ecu.in.engine_"))
                for k, output in enumerate(outputs) if k % 2}
    if isinstance(rule, SameNameRule):
        assert found == set()
    elif isinstance(rule, SimilarityRule):
        # Every abbreviated name is found, and nothing wrong (a few long names of the other half may also match).
        assert abbreviated <= found and found <= abbreviated | expected
    else:
        assert found == expected
