"""Unit tests of the matching engine of the link assistant (``gui/fmucontainer/details/link_matching.py``).

The engine is pure Python: these tests do not need PySide6.
"""

import pytest

from fmu_manipulation_toolbox.gui.fmucontainer.details.link_matching import (
    PortInfo, Checks, SameNameRule, AffixRule, RegexRule, SimilarityRule,
    suggest, link_status, staged_statuses, normalize, OK, WARNING, ERROR,
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


@pytest.mark.parametrize("output, input, checks, level", [
    (out("x"), inp("x"), None, OK),
    (out("x"), inp("x", "Int32"), None, WARNING),                     # lossy conversion
    (out("x"), inp("x", "String"), None, ERROR),                      # no conversion
    (out("x"), inp("x", "String"), Checks(compatible_type=False), WARNING),
    (out("x", unit="degC"), inp("x", unit="K"), None, WARNING),
    (out("x", unit="degC"), inp("x", unit="K"), Checks(same_unit=True), ERROR),
    (out("x", size=4), inp("x", size=2), None, ERROR),
    (out("x", size=4), inp("x", size=4), None, OK),
])
def test_link_status(output, input, checks, level):
    assert link_status(output, input, checks=checks).level == level


def test_fed_input_is_proposed_with_an_error():
    suggestions = suggest([out("x")], [inp("x")], SameNameRule(), fed={"x"})
    assert suggestions[0].status.level == ERROR and not suggestions[0].checked


def test_similar_name_is_a_warning():
    suggestions = suggest([out("chassis.pressure")], [inp("chassis.press")], SimilarityRule(0.7))
    assert suggestions[0].status.level == WARNING and suggestions[0].checked


def test_staged_statuses_detect_two_feeders():
    statuses = staged_statuses([(out("a"), inp("x")), (out("b"), inp("x")), (out("c"), inp("y"))])
    assert [status.level for status in statuses] == [ERROR, ERROR, OK]
