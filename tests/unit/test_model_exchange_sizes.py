"""Unit tests for ``ModelDescription.model_exchange_sizes`` (Model-Exchange nx/nz sizing).

These exercise the continuous-state (nx) and event-indicator (nz) counting logic
on minimal descriptors, covering FMI-2 (always scalar), FMI-3 scalar, FMI-3
fixed-size arrays, FMI-3 arrays whose dimension is given by a structural
parameter, and the defensive "assume 1 element" fallbacks (each of which must
emit a warning rather than fail silently or crash).

The counting used to be done by ``ModelStructureCounter`` from the operation
callbacks; it is now computed from the descriptor tree.
"""
import logging
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.container import EmbeddedFMU
from fmu_manipulation_toolbox.model_description import ModelDescription

pytestmark = [pytest.mark.unit]


def fmi2(structure: str = "", root_attrs: str = "") -> ModelDescription:
    variables = "".join(f'<ScalarVariable name="v{i}" valueReference="{i}"><Real/></ScalarVariable>' for i in range(1, 4))
    return ModelDescription.load(f'<fmiModelDescription fmiVersion="2.0"{root_attrs}><ModelVariables>{variables}'
                                 f'</ModelVariables><ModelStructure>{structure}</ModelStructure>'
                                 f'</fmiModelDescription>'.encode())


def fmi3(variables: str, structure: str) -> ModelDescription:
    return ModelDescription.load(f'<fmiModelDescription fmiVersion="3.0"><ModelVariables>{variables}</ModelVariables>'
                                 f'<ModelStructure>{structure}</ModelStructure></fmiModelDescription>'.encode())


# --------------------------------------------------------------------------- #
#                                   FMI 2.0                                     #
# --------------------------------------------------------------------------- #
def test_fmi2_event_indicators_read_from_root_attribute():
    assert fmi2(root_attrs=' numberOfEventIndicators="3"').model_exchange_sizes() == (0, 3)


def test_fmi2_event_indicators_default_to_zero():
    assert fmi2().model_exchange_sizes() == (0, 0)


def test_fmi2_derivatives_count_as_continuous_states():
    # Each <Unknown> inside <Derivatives> is one continuous state (scalar);
    # entries from other sections must not affect nx.
    md = fmi2('<Outputs><Unknown index="3"/></Outputs>'
              '<Derivatives><Unknown index="1"/><Unknown index="2"/></Derivatives>')
    assert md.model_exchange_sizes() == (2, 0)


# --------------------------------------------------------------------------- #
#                           FMI 3.0 — nominal sizing                            #
# --------------------------------------------------------------------------- #
def test_fmi3_scalar_derivative_counts_as_one():
    md = fmi3('<Float64 name="x" valueReference="5"/>', '<ContinuousStateDerivative valueReference="5"/>')
    assert md.model_exchange_sizes("m.fmu") == (1, 0)


def test_fmi3_fixed_size_array_derivative_counts_elements():
    md = fmi3('<Float64 name="x" valueReference="7"><Dimension start="3"/></Float64>',
              '<ContinuousStateDerivative valueReference="7"/>')
    assert md.model_exchange_sizes("m.fmu") == (3, 0)


def test_fmi3_array_dimension_from_structural_parameter():
    # Structural parameter vr=2 carries the array size (start=4), and the
    # derivative vr=7 is an array dimensioned by that parameter.
    md = fmi3('<UInt64 name="n" valueReference="2" causality="structuralParameter" start="4"/>'
              '<Float64 name="x" valueReference="7"><Dimension valueReference="2"/></Float64>',
              '<ContinuousStateDerivative valueReference="7"/>')
    assert md.model_exchange_sizes("m.fmu") == (4, 0)


def test_fmi3_event_indicator_array_counts_elements():
    md = fmi3('<Float64 name="z" valueReference="9"><Dimension start="2"/></Float64>',
              '<EventIndicator valueReference="9"/>')
    assert md.model_exchange_sizes("m.fmu") == (0, 2)


# --------------------------------------------------------------------------- #
#                      FMI 3.0 — defensive fallbacks (warn, assume 1)           #
# --------------------------------------------------------------------------- #
def test_fmi3_missing_value_reference_assumes_one_and_warns(caplog):
    md = fmi3("", "<EventIndicator/>")
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        assert md.model_exchange_sizes("m.fmu") == (0, 1)
    assert "without valueReference" in caplog.text


def test_fmi3_unknown_value_reference_assumes_one_and_warns(caplog):
    md = fmi3("", '<ContinuousStateDerivative valueReference="404"/>')
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        assert md.model_exchange_sizes("m.fmu") == (1, 0)
    assert "unknown variable" in caplog.text


def test_fmi3_unresolvable_structural_parameter_assumes_one_and_warns(caplog):
    # Structural parameter with no resolvable start value.
    md = fmi3('<UInt64 name="n" valueReference="2" causality="structuralParameter"/>'
              '<Float64 name="x" valueReference="7"><Dimension valueReference="2"/></Float64>',
              '<ContinuousStateDerivative valueReference="7"/>')
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        assert md.model_exchange_sizes("m.fmu") == (1, 0)
    assert "cannot be resolved" in caplog.text


# --------------------------------------------------------------------------- #
#                 Sizes written by the container (EmbeddedFMU)                 #
# --------------------------------------------------------------------------- #
DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.mark.parametrize("fmu, nx, nz", [
    ("array/StateSpace.fmu", 3, 0),                 # FMI-3 array sized by a structural parameter
    ("containers/VanDerPol/VanDerPol.fmu", 2, 0),
    ("me/position_me.fmu", 1, 5),
    ("me/velocity_me.fmu", 1, 1),
    ("operations/bouncing_ball.fmu", 2, 0),
    ("remoting/bouncing_ball-win32.fmu", 2, 1),
])
def test_embedded_fmu_sizes(fmu, nx, nz):
    """`nx`/`nz` written to container.txt (values of the former `ModelStructureCounter`)."""
    embedded = EmbeddedFMU(DATA_DIR / fmu)
    assert (embedded.number_of_continuous_states, embedded.number_of_event_indicators) == (nx, nz)
