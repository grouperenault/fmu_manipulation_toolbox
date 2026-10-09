"""Semantic checker (`OperationSemanticCheck`) and XSD checker (`OperationGenericCheck`).

Phase 5 of `docs/refactoring.md`. Each rule of the semantic checker comes from
the text of FMI 2.0.5 (§2.2.7, §2.2.8) or FMI 3.0.2 (§2.4, §2.4.7, §2.4.8): one
test per rule makes sure it is reported, and the descriptors of the Reference
FMUs and of the FMUs of `tests/data`, which follow the standard, must not
trigger any error.
"""
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.checker import OperationGenericCheck, OperationSemanticCheck, get_checkers
from fmu_manipulation_toolbox.model_description import ModelDescription
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [pytest.mark.unit]

DATA_DIR = Path(__file__).parent.parent / "data"


def semantic_errors(descriptor: bytes):
    check = OperationSemanticCheck()
    check.model_description = ModelDescription.load(descriptor)
    check.closure()
    return check.errors


def fmi2(variables: str, structure: str = "") -> bytes:
    return (f'<fmiModelDescription fmiVersion="2.0" modelName="m" guid="{{x}}"><CoSimulation modelIdentifier="m"/>'
            f'<ModelVariables>{variables}</ModelVariables><ModelStructure>{structure}</ModelStructure>'
            f'</fmiModelDescription>').encode()


def fmi3(variables: str, structure: str = "") -> bytes:
    return (f'<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{{x}}">'
            f'<CoSimulation modelIdentifier="m"/><ModelVariables>{variables}</ModelVariables>'
            f'<ModelStructure>{structure}</ModelStructure></fmiModelDescription>').encode()


def sv(name, vr, child="<Real/>", **attrs) -> str:
    extra = "".join(f' {key}="{value}"' for key, value in attrs.items())
    return f'<ScalarVariable name="{name}" valueReference="{vr}"{extra}>{child}</ScalarVariable>'


# --------------------------------------------------------------------------- #
#                 Descriptors that follow the standard: no error               #
# --------------------------------------------------------------------------- #
def _descriptors():
    for path in sorted(DATA_DIR.rglob("*.fmu")):
        if "refactoring" not in path.parts:
            with zipfile.ZipFile(path) as fmu:
                yield path.relative_to(DATA_DIR).as_posix(), fmu.read("modelDescription.xml")
    for path in sorted((DATA_DIR / "reference-fmus").rglob("modelDescription.xml")):
        yield path.relative_to(DATA_DIR).as_posix(), path.read_bytes()


@pytest.mark.parametrize("name, descriptor", list(_descriptors()), ids=lambda value: value
                         if isinstance(value, str) else "")
def test_conforming_descriptors_have_no_error(name, descriptor):
    assert semantic_errors(descriptor) == []


def test_conforming_minimal_descriptors():
    assert semantic_errors(fmi2(sv("u", 1, '<Real start="0"/>', causality="input") +
                                sv("y", 2, causality="output"),
                                '<Outputs><Unknown index="2" dependencies="1"/></Outputs>')) == []
    assert semantic_errors(fmi3('<Float64 name="u" valueReference="1" causality="input" start="0"/>'
                                '<Float64 name="y" valueReference="2" causality="output"/>',
                                '<Output valueReference="2" dependencies="1"/>')) == []


# --------------------------------------------------------------------------- #
#                         Each rule is reported                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("descriptor, message", [
    # names and value references
    (fmi2(sv("x", 1, variability="fixed", causality="parameter", child='<Real start="1"/>') +
          sv("x", 2, variability="fixed", causality="parameter", child='<Real start="1"/>')),
     "Name 'x' is used by several variables"),
    (fmi3('<Float64 name="x" valueReference="1" start="0" initial="exact"><Alias name="y"/></Float64>'
          '<Float64 name="y" valueReference="2" start="0" initial="exact"/>'),
     "Name 'y' is used by several variables or aliases"),
    (fmi3('<Float64 name="x" valueReference="1"/><Float64 name="y" valueReference="1"/>'),
     "valueReference 1 is used by 'x' and 'y'"),
    # causality / variability
    (fmi2(sv("p", 1, '<Real start="1"/>', causality="parameter", variability="continuous")),
     "causality='parameter' and variability='continuous' cannot be combined"),
    (fmi2(sv("u", 1, '<Real start="1"/>', causality="input", variability="tunable")),
     "causality='input' and variability='tunable' cannot be combined"),
    (fmi3('<Float64 name="t" valueReference="1" causality="independent" variability="discrete"/>'),
     "causality='independent' and variability='discrete' cannot be combined"),
    (fmi2(sv("s", 1, "<Integer/>")), "a Integer variable cannot be continuous (FMI-2 §2.2.7; the default"),
    (fmi3('<Int32 name="i" valueReference="1" variability="continuous"/>'), "a Int32 variable cannot be continuous"),
    (fmi2(sv("p", 1, '<Real start="1"/>', causality="structuralParameter", variability="fixed")),
     "unknown causality 'structuralParameter'"),
    # initial
    (fmi2(sv("p", 1, '<Real start="1"/>', causality="parameter", variability="fixed", initial="calculated")),
     "initial='calculated' is not allowed with causality='parameter'"),
    (fmi2(sv("u", 1, '<Real start="1"/>', causality="input", initial="exact")),
     "initial must not be set with causality='input'"),
    (fmi3('<Float64 name="t" valueReference="1" causality="independent" initial="exact"/>'),
     "initial must not be set with causality='independent'"),
    # start
    (fmi2(sv("u", 1, causality="input")), "Variable 'u': a start value is required"),
    (fmi2(sv("x", 1, initial="exact")), "Variable 'x': a start value is required"),
    (fmi2(sv("y", 1, '<Real start="0"/>', causality="output", initial="calculated")),
     "a start value is not allowed (initial=calculated)"),
    (fmi2(sv("t", 1, '<Real start="0"/>', causality="independent")),
     "a start value is not allowed (causality=independent)"),
    (fmi3('<Float64 name="p" valueReference="1" causality="parameter"/>'), "Variable 'p': a start value is required"),
    (fmi3('<Float64 name="c" valueReference="1" variability="constant"/>'), "Variable 'c': a start value is required"),
    (fmi3('<String name="s" valueReference="1" causality="input"/>'), "Variable 's': a start value is required"),
    # references and model structure
    (fmi2(sv("x", 1, '<Real start="0"/>', initial="exact") + sv("dx", 2, '<Real derivative="9"/>')),
     "derivative='9' is not a variable index"),
    (fmi3('<Float64 name="dx" valueReference="2" derivative="9"/>'), "derivative='9' is not a valueReference"),
    (fmi2(sv("y", 1, causality="output"), '<Outputs><Unknown index="5"/></Outputs>'),
     "<Unknown index='5'> is not a variable index"),
    (fmi3('<Float64 name="y" valueReference="1" causality="output"/>', '<Output valueReference="7"/>'),
     "<Output valueReference='7'> is not a valueReference"),
    (fmi2(sv("y", 1, causality="output")), "Output 'y' is not listed in <Outputs>"),
    (fmi3('<Float64 name="y" valueReference="1" causality="output"/>'), "Output 'y' is not listed in <Output>"),
    (fmi2(sv("x", 1), '<Outputs><Unknown index="1"/></Outputs>'), "<Outputs> lists 'x', which is not an output"),
    (fmi3('<Float64 name="x" valueReference="1"/>', '<ContinuousStateDerivative valueReference="1"/>'),
     "<ContinuousStateDerivative> lists 'x', which has no derivative attribute"),
    (fmi2(sv("y", 1, causality="output"), '<Outputs><Unknown index="1" dependencies="4"/></Outputs>'),
     "dependency '4' does not refer to a variable"),
    (fmi3('<Float64 name="u" valueReference="1" causality="input" start="0"/>'
          '<Float64 name="y" valueReference="2" causality="output"/>',
          '<Output valueReference="2" dependencies="1" dependenciesKind="constant dependent"/>'),
     "dependencies and dependenciesKind have different lengths"),
], ids=lambda value: value[:40] if isinstance(value, str) else "")
def test_rule_is_reported(descriptor, message):
    errors = semantic_errors(descriptor)
    assert any(message in error for error in errors), errors


def test_clocks_have_no_start_rule():
    assert semantic_errors(fmi3('<Clock name="c" valueReference="1" causality="input" '
                                'intervalVariability="triggered"/>')) == []


# --------------------------------------------------------------------------- #
#                 XSD checker and registry of the checkers                     #
# --------------------------------------------------------------------------- #
def test_generic_check_reports_every_xsd_error(tmp_path, caplog):
    """`iter_errors()` instead of `validate()`, which stopped at the first error."""
    descriptor = fmi2(sv("a", 1, variability="nonsense") + sv("b", 2, causality="nonsense"))
    fmu_filename = tmp_path / "test.fmu"
    with zipfile.ZipFile(fmu_filename, "w") as fmu:
        fmu.writestr("modelDescription.xml", descriptor)
    check = OperationGenericCheck()
    with FMU(str(fmu_filename)) as fmu:
        fmu.apply_operation(check)
    assert check.compliant_with_version is None
    # One error per violation (the wording depends on the xmlschema version, not the offending value).
    assert len([record for record in caplog.records if "nonsense" in record.getMessage()]) == 2


def test_get_checkers_does_not_pile_up():
    assert len(get_checkers()) == len(get_checkers())
    assert OperationSemanticCheck in get_checkers()
