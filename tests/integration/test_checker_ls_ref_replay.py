"""Numerical validation of FMI-LS-REF by the checker (`OperationLsRefCheck`): the experiments are replayed with the
container runtime and compared with their references, on the test FMUs of `_helpers/ls_ref.py` compiled for the
host platform."""
import logging
import sys

import pytest

from _helpers.archive import read_entry, rewrite_fmu
from _helpers.ls_ref import REF, compiled_fmu, ls_ref_files, ls_ref_fmu, reference_fmu
from fmu_manipulation_toolbox import checker
from fmu_manipulation_toolbox.checker import OperationLsRefCheck
from fmu_manipulation_toolbox.cli.fmutool import fmutool
from fmu_manipulation_toolbox.cli.utils import ExitCode
from fmu_manipulation_toolbox.container import FMUContainer
from fmu_manipulation_toolbox.operations import FMU
from fmu_manipulation_toolbox.simulation import SimulationError

pytestmark = [pytest.mark.integration, pytest.mark.lsref, pytest.mark.needs_compiler]

VERSIONS = [pytest.param("2.0", marks=pytest.mark.fmi2), pytest.param("3.0", marks=pytest.mark.fmi3)]


@pytest.fixture(scope="module")
def fmus(tmp_path_factory):
    """Test FMUs, compiled once: {(version, model, kind): path}, kind "ls-ref" or "reference"."""
    directory = tmp_path_factory.mktemp("ls-ref-check")
    built = {}

    def get(version: str, model: str, kind: str = "ls-ref"):
        key = (version, model, kind)
        if key not in built:
            build = ls_ref_fmu if kind == "ls-ref" else reference_fmu
            built[key] = build(version, model, directory / f"{model}-{version}-{kind}.fmu")
        return built[key]
    return get


def _check(path, caplog) -> OperationLsRefCheck:
    check = OperationLsRefCheck()
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        with FMU(path) as fmu:
            fmu.apply_operation(check)
    return check


def _patched(source, destination, entry: str, old: str, new: str):
    text = read_entry(source, entry).decode()
    assert old in text
    return rewrite_fmu(source, destination, replace={entry: text.replace(old, new).encode()})


@pytest.mark.parametrize("version", VERSIONS)
def test_bouncing_ball(fmus, version, caplog):
    check = _check(fmus(version, "BouncingBall"), caplog)
    assert check.errors == []
    for experiment in ("Default", "Restitution 0.5"):
        assert f"Experiment '{experiment}' of 'experiments.xml': the 2 output(s) match the references" in caplog.text


def test_stimuli(fmus, caplog):
    check = _check(fmus("3.0", "Feedthrough"), caplog)
    assert check.errors == []
    assert "Experiment 'Stimuli' of 'experiments.xml': the 3 output(s) match the references" in caplog.text


def test_boolean_stimulus_of_fmi2(fmus, caplog):
    """The FMI-3.0 container cannot set an FMI-2.0 boolean input: the experiment is not replayed (warning)."""
    check = _check(fmus("2.0", "Feedthrough"), caplog)
    assert check.errors == []
    assert "Experiment 'Stimuli' of 'experiments.xml': not replayed: the stimulus of the FMI-2.0 boolean " \
           "'Boolean_input' cannot be set through the FMI-3.0 container." in caplog.text


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("model", ["BouncingBall", "Feedthrough"])
def test_result_of_the_reference_fmus(fmus, version, model, caplog):
    check = _check(fmus(version, model, "reference"), caplog)
    assert check.errors == []
    assert f"Experiment 'DefaultExperiment' of '{model}_out.csv': the " in caplog.text


def test_reference_that_differs(fmus, tmp_path, caplog):
    path = _patched(fmus("3.0", "Feedthrough"), tmp_path / "Feedthrough.fmu", f"{REF}/ref.csv", "1.5,5,5,true",
                    "1.5,5.1,5,false")
    errors = _check(path, caplog).errors
    assert "Experiment 'Stimuli' of 'experiments.xml': output 'Float64_continuous_output' differs from the references " \
           "at t=1.5: expected 5.1, simulated 5.0 (maximal error 0.1 at t=1.5)." in errors
    assert "Experiment 'Stimuli' of 'experiments.xml': output 'Boolean_output' differs from the references at t=1.5: " \
           "expected false, simulated true (maximal error 1 at t=1.5)." in errors


def test_strings_are_compared_exactly(tmp_path, caplog):
    files = ls_ref_files("Feedthrough")
    files[f"{REF}/in.csv"] = "time,String_input\n0,a\n1,b\n"
    files[f"{REF}/ref.csv"] = "time,String_output\n0,a\n0.5,a\n1,b\n2,c\n"
    path = compiled_fmu("3.0", "Feedthrough", tmp_path / "Feedthrough.fmu", files)
    errors = _check(path, caplog).errors
    assert errors == ["Experiment 'Stimuli' of 'experiments.xml': output 'String_output' differs from the references "
                      "at t=2: expected c, simulated b."]


def test_experiment_without_references(fmus, tmp_path, caplog):
    path = _patched(fmus("3.0", "Feedthrough"), tmp_path / "Feedthrough.fmu", f"{REF}/experiments.xml",
                    '<References source="ref.csv"/>', "")
    assert _check(path, caplog).errors == []
    assert "Experiment 'Stimuli' of 'experiments.xml': simulated, no references to compare." in caplog.text


def test_experiment_that_fails(fmus, monkeypatch, caplog):
    def failing_replay(*args, **kwargs):
        raise SimulationError("fmi3DoStep failed (status 3)")

    monkeypatch.setattr(checker, "replay", failing_replay)
    errors = _check(fmus("3.0", "BouncingBall"), caplog).errors
    assert errors == [f"Experiment '{name}' of 'experiments.xml': cannot be replayed: fmi3DoStep failed (status 3)."
                      for name in ("Default", "Restitution 0.5")]


def test_runtime_unavailable(fmus, monkeypatch, caplog):
    monkeypatch.setattr(FMUContainer, "get_platforms", lambda self, verbose=True: iter(()))
    check = _check(fmus("3.0", "BouncingBall"), caplog)
    assert check.errors == []
    assert "The experiments of FMI-LS-REF are not replayed: the container runtime has no library" in caplog.text


@pytest.mark.parametrize("patch, code", [(False, ExitCode.SUCCESS), (True, ExitCode.CHECK_FAILED)],
                         ids=["matches", "differs"])
def test_cli_check(fmus, tmp_path, monkeypatch, patch, code):
    path = fmus("3.0", "BouncingBall")
    if patch:   # e = 0.5 compared with the references of e = 0.7
        path = _patched(path, tmp_path / "BouncingBall.fmu", f"{REF}/experiments.xml", 'source="REF-e05.csv"',
                        'source="REF-BouncingBall.csv"')
    monkeypatch.setattr(sys, "argv", ["fmutool", "-input", str(path), "-check"])
    if code == ExitCode.SUCCESS:
        fmutool()
    else:
        with pytest.raises(SystemExit) as exit_info:
            fmutool()
        assert exit_info.value.code == code
