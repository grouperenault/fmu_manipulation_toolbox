"""Replay of the experiments of FMI-LS-REF with the container runtime (`fmu_manipulation_toolbox.simulation`), on
the test FMUs of `_helpers/ls_ref.py` compiled for the host platform."""
import logging

import pytest

from _helpers.archive import read_entry, rewrite_fmu
from _helpers.ls_ref import DATA_DIR, ls_ref_fmu, reference_fmu
from fmu_manipulation_toolbox.container import FMUContainer
from fmu_manipulation_toolbox.experiments import Experiment, Parameter, read_parameter_set
from fmu_manipulation_toolbox.model_description import ModelDescription
from fmu_manipulation_toolbox.simulation import (
    SimulationError,
    SimulationUnavailable,
    SimulationUnsupported,
    experiment_times,
    replay,
)
from fmu_manipulation_toolbox.timeseries import TimeSeries, compare, read_csv

pytestmark = [pytest.mark.integration, pytest.mark.lsref, pytest.mark.needs_compiler]

VERSIONS = [pytest.param("2.0", marks=pytest.mark.fmi2), pytest.param("3.0", marks=pytest.mark.fmi3)]
LS_REF = DATA_DIR / "ls-ref"


@pytest.fixture(scope="module")
def fmus(tmp_path_factory):
    """Test FMUs, compiled once: {(version, model, kind): path}, kind "ls-ref" or "reference"."""
    directory = tmp_path_factory.mktemp("ls-ref-fmus")
    built = {}

    def get(version: str, model: str, kind: str = "ls-ref"):
        key = (version, model, kind)
        if key not in built:
            build = ls_ref_fmu if kind == "ls-ref" else reference_fmu
            built[key] = build(version, model, directory / f"{model}-{version}-{kind}.fmu")
        return built[key]
    return get


def _assert_matches(reference: TimeSeries, simulated: TimeSeries, names):
    for name in names:
        result = compare(reference, simulated, name, rtol=1e-3, atol=1e-6)
        assert result.passed, f"{name}: max error {result.max_error} at {result.max_error_time}"


@pytest.mark.parametrize("version", VERSIONS)
def test_bouncing_ball(fmus, version):
    simulated = replay(fmus(version, "BouncingBall"), Experiment("Default", start_time=0, stop_time=3, step_size=0.01),
                       ["h", "v"])
    assert len(simulated.times) == 301 and simulated.times[-1] == pytest.approx(3.0)
    _assert_matches(read_csv(DATA_DIR / "compile" / "REF-BouncingBall.csv"), simulated, ["h", "v"])


@pytest.mark.parametrize("version", VERSIONS)
def test_parameters(fmus, version):
    parameters = read_parameter_set(LS_REF / "bouncingball" / "resources" / "params.ssv")
    simulated = replay(fmus(version, "BouncingBall"), Experiment("e05", start_time=0, stop_time=3, step_size=0.01),
                       ["h", "v"], parameters=parameters)
    _assert_matches(read_csv(LS_REF / "bouncingball" / "REF-e05.csv"), simulated, ["h", "v"])
    default = read_csv(DATA_DIR / "compile" / "REF-BouncingBall.csv")
    assert not compare(default, simulated, "h", rtol=1e-3, atol=1e-6).passed


def test_stimuli(fmus):
    references = read_csv(LS_REF / "feedthrough" / "ref.csv")
    simulated = replay(fmus("3.0", "Feedthrough"), Experiment("Stimuli", start_time=0, stop_time=2, step_size=0.1),
                       list(references.columns), stimuli=read_csv(LS_REF / "feedthrough" / "in.csv"))
    _assert_matches(references, simulated, references.columns)
    # an output fed through follows its input at the same instant: linear for the continuous real, held otherwise
    assert simulated.value("Float64_continuous_output", 0.3) == pytest.approx(3.0)
    assert simulated.value("Int32_output", 0.9) == 0


def test_stimuli_of_fmi2(fmus):
    """The FMI-3.0 container sets the numbers of an FMI-2.0 FMU, not its booleans (they cannot be exposed)."""
    stimuli = read_csv(LS_REF / "feedthrough" / "in.csv")
    experiment = Experiment("Stimuli", start_time=0, stop_time=2, step_size=0.1)
    with pytest.raises(SimulationUnsupported, match="the stimulus of the FMI-2.0 boolean 'Boolean_input'"):
        replay(fmus("2.0", "Feedthrough"), experiment, ["Float64_continuous_output"], stimuli=stimuli)
    del stimuli.columns["Boolean_input"]
    simulated = replay(fmus("2.0", "Feedthrough"), experiment, ["Float64_continuous_output", "Int32_output",
                                                               "Boolean_output"], stimuli=stimuli)
    _assert_matches(read_csv(LS_REF / "feedthrough" / "ref.csv"), simulated, ["Float64_continuous_output",
                                                                              "Int32_output"])
    assert simulated.columns["Boolean_output"] == [False] * 21        # an FMI-2.0 boolean output, exposed


@pytest.mark.parametrize("first, second, columns", [
    ("y[1]", "y[2]", ["y[1]", "y[2]"]),
    ("m[1,1]", "m[1,2]", ["m[1,1]", "m[1,2]"]),
], ids=["vector", "matrix"])
def test_array_output(fmus, tmp_path, first, second, columns):
    """An array output gives one column per element, named as by FMI 3.0: the two real outputs of the FMI-2.0
    Feedthrough, renamed as the elements of an array (value references 8 and 10), are aggregated by the container into
    one array output.

    The container exposes an FMI-2.0 aggregate through a local variable, updated after each step: an element fed
    through follows its input one step later than the scalar output, read once the inputs are set."""
    path = fmus("2.0", "Feedthrough")
    text = read_entry(path, "modelDescription.xml").decode()
    text = text.replace('name="Float64_continuous_output"', f'name="{first}"')
    text = text.replace('name="Float64_discrete_output" valueReference="10" causality="output" variability="discrete"',
                        f'name="{second}" valueReference="10" causality="output"')
    array = rewrite_fmu(path, tmp_path / "array.fmu", replace={"modelDescription.xml": text.encode()})
    stimuli = TimeSeries(times=[0.0, 1.0], columns={"Float64_continuous_input": [1.0, 2.0],
                                                    "Float64_discrete_input": [3.0, 3.0]})
    experiment = Experiment("Array", start_time=0, stop_time=1, step_size=0.5)
    simulated = replay(array, experiment, [first.split("[")[0]], stimuli=stimuli)
    scalars = replay(path, experiment, ["Float64_continuous_output", "Float64_discrete_output"], stimuli=stimuli)
    assert list(simulated.columns) == columns
    assert scalars.columns["Float64_continuous_output"] == pytest.approx([1.0, 1.5, 2.0])
    assert simulated.columns[columns[0]] == pytest.approx([1.0, 1.0, 1.5])
    assert simulated.columns[columns[1]] == scalars.columns["Float64_discrete_output"] == pytest.approx([3.0] * 3)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("model", ["BouncingBall", "Feedthrough"])
def test_result_of_the_reference_fmus(fmus, version, model, tmp_path):
    """The result of the Reference-FMUs, replayed with their DefaultExperiment (no time in the experiment): its
    numbers, booleans and enumerations (not its strings and binaries) of the outputs the FMU has."""
    path = fmus(version, model, "reference")
    csv_file = tmp_path / f"{model}_out.csv"
    csv_file.write_bytes(read_entry(path, f"extra/org.fmi-standard.fmi-ls-ref/{model}_out.csv"))
    references = read_csv(csv_file)
    ports = {port.get("name"): port
             for port in ModelDescription.load(read_entry(path, "modelDescription.xml")).iter_ports()}
    outputs = [name for name in references.columns
               if name in ports and ports[name].causality == "output" and ports[name].fmi_type not in ("Binary",
                                                                                                        "String")]
    simulated = replay(path, Experiment("DefaultExperiment"), outputs, references=references)
    _assert_matches(references, simulated, outputs)


def test_experiment_times(tmp_path):
    with_default = ModelDescription.load(b'<fmiModelDescription fmiVersion="3.0" modelName="m" '
                                         b'instantiationToken="t"><DefaultExperiment startTime="1" stopTime="5"/>'
                                         b'</fmiModelDescription>')
    without_default = ModelDescription.load(b'<fmiModelDescription fmiVersion="3.0" modelName="m" '
                                            b'instantiationToken="t"/>')
    references = TimeSeries(times=[0.5, 2.5], columns={})
    assert experiment_times(Experiment("e", start_time=0, stop_time=2), with_default, references) == (0, 2)
    assert experiment_times(Experiment("e"), with_default, references) == (1, 5)
    assert experiment_times(Experiment("e"), without_default, references) == (0.5, 2.5)
    with pytest.raises(SimulationError, match="experiment 'e': no stopTime"):
        experiment_times(Experiment("e", start_time=0), without_default, None)


def test_step_size_deduced(fmus, caplog):
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        simulated = replay(fmus("3.0", "BouncingBall"), Experiment("Default", start_time=0, stop_time=1), ["h"])
    assert "Experiment 'Default': step size 0.01 deduced from the FMU." in caplog.text
    assert len(simulated.times) == 101


def test_tolerance_is_not_used(fmus, caplog):
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        replay(fmus("3.0", "BouncingBall"), Experiment("T", start_time=0, stop_time=0.1, step_size=0.01,
                                                       tolerance=1e-6), ["h"])
    assert "Experiment 'T': its tolerance (1e-06) is not used." in caplog.text


def test_builder_messages_are_debug(fmus, caplog):
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        replay(fmus("3.0", "Feedthrough"), Experiment("T", start_time=0, stop_time=0.1, step_size=0.1),
               ["Int32_output"])
    assert "is not connected" not in caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_bad_parameter(fmus):
    with pytest.raises(SimulationError, match="cannot build the container of experiment 'T'"):
        replay(fmus("3.0", "BouncingBall"), Experiment("T", start_time=0, stop_time=0.1, step_size=0.01), ["h"],
               parameters=[Parameter("unknown", "Real", "1")])


def test_runtime_unavailable(fmus, monkeypatch):
    """In the calling process: the patch of the builder does not reach a dedicated process."""
    monkeypatch.setattr(FMUContainer, "get_platforms", lambda self, verbose=True: iter(()))
    with pytest.raises(SimulationUnavailable, match="the container runtime has no library"):
        replay(fmus("3.0", "BouncingBall"), Experiment("T", start_time=0, stop_time=0.1, step_size=0.01), ["h"],
               isolated=False)
