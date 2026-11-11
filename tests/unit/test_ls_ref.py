"""Reading of FMI-LS-REF: manifest (`LayeredStandard`), URIs (`resolve_uri`) and experiment files
(`read_experiments`)."""
import shutil
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.experiments import ExperimentsError, read_experiments
from fmu_manipulation_toolbox.ls import LayeredStandard, RefLabel, resolve_uri

pytestmark = [pytest.mark.unit, pytest.mark.lsref]

DATA_DIR = Path(__file__).parent.parent / "data" / "ls-ref"
REF_DIR = Path("extra") / "org.fmi-standard.fmi-ls-ref"


def _fmu_directory(tmp_path: Path) -> Path:
    """An extracted FMU with the manifest of `tests/data/ls-ref`, its smoke tests and some of the files they use."""
    fmu = tmp_path / "fmu"
    ref = fmu / REF_DIR
    ref.mkdir(parents=True)
    for name in ("fmi-ls-manifest.xml", "smoke.xml"):
        shutil.copy(DATA_DIR / name, ref / name)
    (ref / "validation tests.xml").write_text("<Experiments name='v'/>")
    (ref / "test1-in.csv").write_text("time\n0\n")
    (fmu / "resources").mkdir()
    (fmu / "resources" / "uncertainty.xml").write_text("<Experiments name='u'/>")
    (fmu / "resources" / "params.ssv").write_text("<ParameterSet/>")
    (tmp_path / "outside.txt").write_text("outside")
    return fmu


def test_fmu_without_ls_ref(tmp_path):
    ls = LayeredStandard(tmp_path)
    assert "LS-REF" not in ls.standards
    assert ls.ref_related == []


def test_manifest_is_read(tmp_path):
    ls = LayeredStandard(_fmu_directory(tmp_path))
    assert ls.standards == ["LS-REF"]
    assert ls.ref_version == "1.0.0-alpha.1"
    smoke, validation, uncertainty, parameters, documentation, outside = ls.ref_related

    assert smoke.type == "application/x-ma-hs-experiments"
    assert smoke.description == "Smoke tests"
    assert smoke.labels == [RefLabel("os:any", "Any platform")]
    assert smoke.is_experiment and smoke.sub_roles == [] and smoke.sub_role == "smoke-test"
    assert smoke.path == "extra/org.fmi-standard.fmi-ls-ref/smoke.xml" and smoke.problem is None

    assert validation.sub_role == "validation"
    assert validation.path == "extra/org.fmi-standard.fmi-ls-ref/validation tests.xml"   # percent-decoded
    assert uncertainty.sub_role == "uncertainty-analysis"
    assert uncertainty.path == "resources/uncertainty.xml"                                 # dot segments inside

    assert not parameters.is_experiment and parameters.main_role == "parameter"
    assert parameters.path is None and parameters.problem == "missing file"
    assert documentation.problem == "absolute URI"
    assert outside.problem == "outside of the FMU"


def test_broken_manifest_is_reported(tmp_path, caplog):
    ref = tmp_path / REF_DIR
    ref.mkdir(parents=True)
    (ref / "fmi-ls-manifest.xml").write_text("<broken")
    ls = LayeredStandard(tmp_path)
    assert ls.standards == ["LS-REF"]
    assert ls.ref_related == []
    assert "Cannot parse the manifest of LS-REF" in caplog.text


@pytest.mark.parametrize("uri, problem", [
    ("file:///tmp/a.csv", "absolute URI"),
    ("//host/a.csv", "absolute URI"),
    ("/a.csv", "absolute URI"),
    ("C:/a.csv", "absolute URI"),
    ("../../../a.csv", "outside of the FMU"),
    ("absent.csv", "missing file"),
    ("", "missing file"),
])
def test_uri_not_resolved(tmp_path, uri, problem):
    base = tmp_path / "extra" / "ls"
    base.mkdir(parents=True)
    assert resolve_uri(uri, base, tmp_path) == (None, problem)


def test_uri_resolved(tmp_path):
    base = tmp_path / "extra" / "ls"
    base.mkdir(parents=True)
    (tmp_path / "resources").mkdir()
    (tmp_path / "resources" / "a b.csv").write_text("time\n")
    path, problem = resolve_uri("./../../resources/a%20b.csv", base, tmp_path)
    assert problem is None
    assert path.samefile(tmp_path / "resources" / "a b.csv")


def test_experiments_are_read(tmp_path):
    fmu = _fmu_directory(tmp_path)
    experiments = read_experiments(fmu / REF_DIR / "smoke.xml", fmu)
    assert experiments.name == "Smoke tests"
    assert experiments.description == "Smoke tests of the tests"
    test1, test2 = experiments.experiments

    assert (test1.name, test1.description) == ("Test1", "Steady state")
    assert (test1.start_time, test1.stop_time, test1.step_size, test1.tolerance) == (0.0, 10.0, 0.001, 0.004)
    assert test1.parameters is None
    assert test1.stimuli.type == "text/csv" and test1.stimuli.problem is None
    assert test1.stimuli.path.samefile(fmu / REF_DIR / "test1-in.csv")
    assert test1.references.source == "test1-ref.csv" and test1.references.problem == "missing file"

    assert test2.description is None
    assert (test2.start_time, test2.stop_time, test2.step_size, test2.tolerance) == (None, None, None, None)
    assert test2.parameters.type == "application/x-ssp-parameter-set"
    assert test2.parameters.path.samefile(fmu / "resources" / "params.ssv")
    assert test2.stimuli is None
    assert test2.references.type == "application/hdf5"


@pytest.mark.parametrize("content, message", [
    ("<broken", "cannot parse"),
    ("<Other name='x'/>", "root element is 'Other'"),
    ("<Experiments name='x'><TransientExperiment name='T' stopTime='ten'/></Experiments>",
     "experiment 'T': stopTime='ten' is not a number"),
])
def test_bad_experiments(tmp_path, content, message):
    filename = tmp_path / "experiments.xml"
    filename.write_text(content)
    with pytest.raises(ExperimentsError, match=message):
        read_experiments(filename, tmp_path)
