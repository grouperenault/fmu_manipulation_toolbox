"""Static rules of FMI-LS-REF (`OperationLsRefCheck`).

`Feedthrough.fmu` of `tests/data/compile` (FMI 2.0 and 3.0), without its own `extra/`, gets an LS-REF manifest, an
experiment file and the files it refers to, following the standard: one rule is broken in each test by a change of
these files. The FMUs have no binary: the experiments are not replayed (warning), see
`tests/integration/test_checker_ls_ref_replay.py` for the replay.
"""
import logging
from pathlib import Path

import pytest

from _helpers.archive import rewrite_fmu
from fmu_manipulation_toolbox.checker import OperationLsRefCheck, get_checkers
from fmu_manipulation_toolbox.operations import FMU

pytestmark = [pytest.mark.unit, pytest.mark.lsref]

DATA_DIR = Path(__file__).parent.parent / "data"
REF = "extra/org.fmi-standard.fmi-ls-ref"

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<fmiReferences
    xmlns:fmi-ls="http://fmi-standard.org/fmi-ls-manifest"
    fmi-ls:fmi-ls-name="org.fmi-standard.fmi-ls-ref"
    fmi-ls:fmi-ls-version="1.0.0-alpha.1"
    fmi-ls:fmi-ls-description="Layered Standard providing information on related files included in an FMU.">
    <Related type="application/x-ma-hs-experiments" source="experiments.xml" role="experiment"/>
    <Related type="text/plain" source="notes.txt" role="document"/>
</fmiReferences>
"""

EXPERIMENTS = """<?xml version="1.0" encoding="UTF-8"?>
<Experiments name="Smoke tests" xmlns="http://modelica.org/HSExperiments1/HSExperiments">
    <TransientExperiment name="Feedthrough" startTime="0" stopTime="1" stepSize="0.1">
        <Parameters source="../../resources/params.ssv"/>
        <Stimuli source="in.csv"/>
        <References source="ref.csv"/>
    </TransientExperiment>
</Experiments>
"""

PARAMETERS = """<?xml version="1.0" encoding="UTF-8"?>
<ssv:ParameterSet xmlns:ssv="http://ssp-standard.org/SSP1/SystemStructureParameterValues" version="1.0" name="p">
    <ssv:Parameters>
        <ssv:Parameter name="Float64_fixed_parameter"><ssv:Real value="2"/></ssv:Parameter>
    </ssv:Parameters>
</ssv:ParameterSet>
"""

FILES = {
    f"{REF}/fmi-ls-manifest.xml": MANIFEST,
    f"{REF}/experiments.xml": EXPERIMENTS,
    f"{REF}/in.csv": "time,Float64_continuous_input,Int32_input\n0,0,1\n1,1,2\n",
    f"{REF}/ref.csv": "time,Float64_continuous_output\n0,0\n1,1\n",
    f"{REF}/notes.txt": "notes",
    "resources/params.ssv": PARAMETERS,
}


@pytest.fixture(params=["2.0", "3.0"])
def version(request) -> str:
    return request.param


def _fmu(tmp_path: Path, version: str, changes: dict[str, tuple[str, str] | str | None] | None = None) -> Path:
    """Feedthrough of FMI `version` with the files of LS-REF; `changes` maps an entry to a (old, new) replacement of
    its text, to a new text, or to None to drop it."""
    files = dict(FILES)
    for entry, change in (changes or {}).items():
        if change is None:
            files.pop(entry)
        elif isinstance(change, tuple):
            assert change[0] in files[entry]
            files[entry] = files[entry].replace(*change)
        else:
            files[entry] = change
    return rewrite_fmu(DATA_DIR / "compile" / version / "Feedthrough.fmu", tmp_path / "Feedthrough.fmu",
                       drop=("extra/", "binaries/"), replace={entry: text.encode() for entry, text in files.items()})


def _check(path: Path) -> OperationLsRefCheck:
    check = OperationLsRefCheck()
    with FMU(path) as fmu:
        fmu.apply_operation(check)
    return check


def _has(errors: list[str], expected: str) -> bool:
    return any(expected in error for error in errors)


def test_checker_is_registered():
    assert OperationLsRefCheck in get_checkers()


def test_fmu_follows_the_standard(tmp_path, version, caplog):
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        check = _check(_fmu(tmp_path, version))
    assert check.errors == []
    assert [(replay.experiment.name, replay.outputs) for replay in check.experiments] == \
        [("Feedthrough", ["Float64_continuous_output"])]
    assert "No error against FMI-LS-REF" in caplog.text
    assert "The experiments of FMI-LS-REF are not replayed: the FMU has no binary for the host platform" in caplog.text


def test_fmu_without_ls_ref(tmp_path, version, caplog):
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        check = _check(rewrite_fmu(DATA_DIR / "compile" / version / "Feedthrough.fmu", tmp_path / "Feedthrough.fmu",
                                   drop=("extra/",)))
    assert check.errors == [] and check.experiments == []
    assert "FMI-LS-REF not present." in caplog.text
    assert "error against FMI-LS-REF" not in caplog.text


def test_broken_manifest(tmp_path):
    errors = _check(_fmu(tmp_path, "3.0", {f"{REF}/fmi-ls-manifest.xml": "<broken"})).errors
    assert _has(errors, "Cannot parse the manifest of FMI-LS-REF")


def test_manifest_against_xsd(tmp_path):
    errors = _check(_fmu(tmp_path, "3.0", {f"{REF}/fmi-ls-manifest.xml": ('role="document"', 'role="notes"')})).errors
    assert _has(errors, "Manifest of FMI-LS-REF: attribute role='notes'")


def test_unknown_experiment_sub_role(tmp_path):
    errors = _check(_fmu(tmp_path, "3.0", {f"{REF}/fmi-ls-manifest.xml": ('role="experiment"',
                                                                          'role="experiment/regression"')})).errors
    assert _has(errors, "unknown experiment sub-role 'regression'")


def test_missing_related_file_is_a_warning(tmp_path, caplog):
    check = _check(_fmu(tmp_path, "3.0", {f"{REF}/notes.txt": None}))
    assert check.errors == []
    assert "Related file 'notes.txt' of FMI-LS-REF: missing file, it is ignored." in caplog.text


def test_absolute_uri_is_a_warning(tmp_path, caplog):
    check = _check(_fmu(tmp_path, "3.0", {f"{REF}/fmi-ls-manifest.xml": ('source="notes.txt"',
                                                                         'source="https://example.com/notes.txt"')}))
    assert check.errors == []
    assert "absolute URI, it is ignored" in caplog.text


def test_experiment_file_of_another_type(tmp_path, caplog):
    check = _check(_fmu(tmp_path, "3.0", {f"{REF}/fmi-ls-manifest.xml": ("application/x-ma-hs-experiments",
                                                                         "application/xml")}))
    assert check.errors == [] and check.experiments == []
    assert "experiment file of type 'application/xml'" in caplog.text


def test_experiments_against_xsd(tmp_path):
    errors = _check(_fmu(tmp_path, "3.0", {f"{REF}/experiments.xml": ('stepSize="0.1"', 'step="0.1"')})).errors
    assert _has(errors, "experiments.xml' of FMI-LS-REF:")


def test_bad_times(tmp_path):
    check = _check(_fmu(tmp_path, "3.0", {f"{REF}/experiments.xml": ('startTime="0" stopTime="1" stepSize="0.1"',
                                                                     'startTime="1" stopTime="1" stepSize="0"')}))
    assert _has(check.errors, "startTime 1.0 is not before stopTime 1.0")
    assert _has(check.errors, "stepSize 0.0 is not positive")
    assert check.experiments == []


def test_missing_file_of_a_replayed_experiment(tmp_path):
    errors = _check(_fmu(tmp_path, "3.0", {f"{REF}/ref.csv": None})).errors
    assert _has(errors, "the references 'ref.csv' cannot be used: missing file")


def test_missing_file_of_an_uncertainty_analysis(tmp_path, caplog):
    check = _check(_fmu(tmp_path, "3.0", {f"{REF}/ref.csv": None,
                                          f"{REF}/fmi-ls-manifest.xml": ('role="experiment"',
                                                                         'role="experiment/uncertainty-analysis"')}))
    assert check.errors == [] and check.experiments == []
    assert "the references 'ref.csv' cannot be used: missing file" in caplog.text


def test_unsupported_type_of_references(tmp_path, caplog):
    check = _check(_fmu(tmp_path, "3.0", {f"{REF}/experiments.xml": ('<References source="ref.csv"/>',
                                                                     '<References source="ref.csv" '
                                                                     'type="application/hdf5"/>')}))
    assert check.errors == [] and check.experiments == []
    assert "the references 'ref.csv' are of type 'application/hdf5', only 'text/csv' is supported" in caplog.text


def test_bad_csv(tmp_path):
    errors = _check(_fmu(tmp_path, "3.0", {f"{REF}/in.csv": "t,Int32_input\n0,1\n"})).errors
    assert _has(errors, "the first column is 't', not 'time'")


def test_stimuli_on_outputs_and_unknown_variables(tmp_path, version):
    errors = _check(_fmu(tmp_path, version, {f"{REF}/in.csv": "time,Int32_output,unknown\n0,1,2\n"})).errors
    assert _has(errors, "the stimuli 'in.csv' give the variable 'Int32_output', which is a output, not an input")
    assert _has(errors, "the stimuli 'in.csv' give the variable 'unknown', which does not exist")


def test_references_on_inputs(tmp_path, version):
    errors = _check(_fmu(tmp_path, version, {f"{REF}/ref.csv": "time,Int32_input\n0,1\n"})).errors
    assert _has(errors, "the references 'ref.csv' give the variable 'Int32_input', which is a input, not an output")


def test_parameters_on_outputs(tmp_path, version):
    errors = _check(_fmu(tmp_path, version, {"resources/params.ssv": ("Float64_fixed_parameter",
                                                                      "Float64_continuous_output")})).errors
    assert _has(errors, "give the variable 'Float64_continuous_output', which is a output: only parameters")


def test_parameters_on_inputs_with_start(tmp_path, version):
    assert _check(_fmu(tmp_path, version, {"resources/params.ssv": ("Float64_fixed_parameter",
                                                                    "Float64_continuous_input")})).errors == []


def test_bad_parameter_set(tmp_path):
    errors = _check(_fmu(tmp_path, "3.0", {"resources/params.ssv": "<ParameterSet/>"})).errors
    assert _has(errors, "'params.ssv' has no ssv:ParameterSet")


@pytest.mark.parametrize("model", ["BouncingBall", "Feedthrough"])
def test_reference_fmus(tmp_path, version, model, caplog):
    """The Reference-FMUs give the output of their default experiment (role `result`), without description of the
    manifest; the FMI-2.0 Feedthrough has columns of variables it does not have (those of FMI 3.0)."""
    check = _check(rewrite_fmu(DATA_DIR / "compile" / version / f"{model}.fmu", tmp_path / f"{model}.fmu",
                               drop=("binaries/",)))
    assert check.errors == []
    assert "Manifest of FMI-LS-REF: missing required attribute 'fmi-ls-description' (at /fmiReferences)" \
        in caplog.text
    replay, = check.experiments
    assert replay.related.main_role == "result"
    assert replay.experiment.name == "DefaultExperiment"
    assert replay.experiment.references.source == f"{model}_out.csv"
    if model == "BouncingBall":
        assert (replay.experiment.start_time, replay.experiment.stop_time, replay.experiment.step_size) == \
            (0.0, 3.0, 0.01)
        assert replay.outputs == ["h", "v"]
    else:
        assert "the column 'Binary_output' is" in caplog.text
        assert "Binary_output" not in replay.outputs and "Float64_continuous_output" in replay.outputs
        assert ("Int8_output" in replay.outputs) == (version == "3.0")


def test_result_without_output(tmp_path, caplog):
    check = _check(_fmu(tmp_path, "3.0", {
        f"{REF}/fmi-ls-manifest.xml": ('<Related type="text/plain" source="notes.txt" role="document"/>',
                                       '<Related type="text/csv" source="out.csv" role="result"/>'),
        f"{REF}/out.csv": "time,Int32_input\n0,1\n"}))
    assert check.errors == []
    assert [replay.related.main_role for replay in check.experiments] == ["experiment"]
    assert "the column 'Int32_input' is not an output of the FMU" in caplog.text
    assert "no output to compare, it is not replayed" in caplog.text


def test_bad_result(tmp_path):
    errors = _check(_fmu(tmp_path, "3.0", {
        f"{REF}/fmi-ls-manifest.xml": ('<Related type="text/plain" source="notes.txt" role="document"/>',
                                       '<Related type="text/csv" source="out.csv" role="result"/>'),
        f"{REF}/out.csv": "time,Int32_output\n1,1\n0,2\n"})).errors
    assert _has(errors, "time 0.0 before the previous one")
