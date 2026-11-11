"""Test FMUs of FMI-LS-REF (`_helpers/ls_ref.py`): compiled for the host platform, they follow the static rules of
the checker, with the experiments to replay that they declare."""
import pytest

from _helpers.archive import read_entry
from _helpers.ls_ref import ls_ref_fmu, reference_fmu
from fmu_manipulation_toolbox.checker import OperationLsRefCheck
from fmu_manipulation_toolbox.compiler import SourceCompiler
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [pytest.mark.integration, pytest.mark.lsref, pytest.mark.needs_compiler]

VERSIONS = [pytest.param("2.0", marks=pytest.mark.fmi2), pytest.param("3.0", marks=pytest.mark.fmi3)]


def _check(path) -> OperationLsRefCheck:
    check = OperationLsRefCheck()
    with FMU(path) as fmu:
        fmu.apply_operation(check)
    return check


def _host_binary(version: str, model: str) -> str:
    fmi_version = int(version[0])
    return f"binaries/{SourceCompiler.host_platform(fmi_version)}/{model}{SourceCompiler.library_suffix()}"


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("model, experiments", [
    ("BouncingBall", [("Default", ["h", "v"]), ("Restitution 0.5", ["h", "v"])]),
    ("Feedthrough", [("Stimuli", ["Float64_continuous_output", "Int32_output", "Boolean_output"])]),
])
def test_ls_ref_fmu(tmp_path, version, model, experiments):
    fmu = ls_ref_fmu(version, model, tmp_path / f"{model}.fmu")
    assert read_entry(fmu, _host_binary(version, model))
    check = _check(fmu)
    assert check.errors == []
    assert [(replay.experiment.name, replay.outputs) for replay in check.experiments] == experiments


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("model", ["BouncingBall", "Feedthrough"])
def test_reference_fmu(tmp_path, version, model):
    fmu = reference_fmu(version, model, tmp_path / f"{model}.fmu")
    assert read_entry(fmu, _host_binary(version, model))
    check = _check(fmu)
    assert check.errors == []
    assert [replay.experiment.name for replay in check.experiments] == ["DefaultExperiment"]
