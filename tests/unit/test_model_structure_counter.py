"""Unit tests for ``ModelStructureCounter`` (Model-Exchange nx/nz sizing).

These exercise the continuous-state (nx) and event-indicator (nz) counting logic
in isolation, covering FMI-2 (always scalar), FMI-3 scalar, FMI-3 fixed-size
arrays, FMI-3 arrays whose dimension is given by a structural parameter, and the
defensive "assume 1 element" fallbacks (each of which must emit a warning rather
than fail silently or crash).
"""
import logging

import pytest

from fmu_manipulation_toolbox.operations import ModelStructureCounter

pytestmark = [pytest.mark.unit]


# --------------------------------------------------------------------------- #
#                                   FMI 2.0                                     #
# --------------------------------------------------------------------------- #
def test_fmi2_event_indicators_read_from_root_attribute():
    counter = ModelStructureCounter()
    counter.fmi_attrs(2, {"numberOfEventIndicators": "3"})
    assert counter.number_of_event_indicators == 3


def test_fmi2_event_indicators_default_to_zero():
    counter = ModelStructureCounter()
    counter.fmi_attrs(2, {})
    assert counter.number_of_event_indicators == 0


def test_fmi2_derivatives_count_as_continuous_states():
    counter = ModelStructureCounter()
    # Each <Unknown> inside <Derivatives> is one continuous state (scalar).
    counter.model_structure_attrs(2, "Derivatives", {"index": "1"})
    counter.model_structure_attrs(2, "Derivatives", {"index": "2"})
    # Entries from other sections must not affect nx.
    counter.model_structure_attrs(2, "Outputs", {"index": "3"})
    assert counter.number_of_continuous_states == 2


# --------------------------------------------------------------------------- #
#                           FMI 3.0 — nominal sizing                            #
# --------------------------------------------------------------------------- #
def test_fmi3_scalar_derivative_counts_as_one():
    counter = ModelStructureCounter("m.fmu")
    counter.register_port("5", dimensions=[])
    counter.model_structure_attrs(3, "ContinuousStateDerivative", {"valueReference": "5"})
    assert counter.number_of_continuous_states == 1


def test_fmi3_fixed_size_array_derivative_counts_elements():
    counter = ModelStructureCounter("m.fmu")
    counter.register_port("7", dimensions=[("start", 3)])
    counter.model_structure_attrs(3, "ContinuousStateDerivative", {"valueReference": "7"})
    assert counter.number_of_continuous_states == 3


def test_fmi3_array_dimension_from_structural_parameter():
    counter = ModelStructureCounter("m.fmu")
    # Structural parameter vr=2 carries the array size (start=4)...
    counter.register_port("2", dimensions=[], start="4")
    # ...and the derivative vr=7 is an array dimensioned by that parameter.
    counter.register_port("7", dimensions=[("valueReference", 2)])
    counter.model_structure_attrs(3, "ContinuousStateDerivative", {"valueReference": "7"})
    assert counter.number_of_continuous_states == 4


def test_fmi3_event_indicator_array_counts_elements():
    counter = ModelStructureCounter("m.fmu")
    counter.register_port("9", dimensions=[("start", 2)])
    counter.model_structure_attrs(3, "EventIndicator", {"valueReference": "9"})
    assert counter.number_of_event_indicators == 2


# --------------------------------------------------------------------------- #
#                      FMI 3.0 — defensive fallbacks (warn, assume 1)           #
# --------------------------------------------------------------------------- #
def test_fmi3_missing_value_reference_assumes_one_and_warns(caplog):
    counter = ModelStructureCounter("m.fmu")
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        counter.model_structure_attrs(3, "EventIndicator", {})
    assert counter.number_of_event_indicators == 1
    assert "without valueReference" in caplog.text


def test_fmi3_unknown_value_reference_assumes_one_and_warns(caplog):
    counter = ModelStructureCounter("m.fmu")
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        counter.model_structure_attrs(3, "ContinuousStateDerivative", {"valueReference": "404"})
    assert counter.number_of_continuous_states == 1
    assert "unknown variable" in caplog.text


def test_fmi3_unresolvable_structural_parameter_assumes_one_and_warns(caplog):
    counter = ModelStructureCounter("m.fmu")
    # Structural parameter with no resolvable start value.
    counter.register_port("2", dimensions=[], start=None)
    counter.register_port("7", dimensions=[("valueReference", 2)])
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        counter.model_structure_attrs(3, "ContinuousStateDerivative", {"valueReference": "7"})
    assert counter.number_of_continuous_states == 1
    assert "cannot be resolved" in caplog.text

