"""Experiment files of MA-HS-Experiments, referred to by FMI-LS-REF (draft of the Modelica Association).

An experiment file (`<Experiments>`) holds transient experiments: start and stop times, step size, tolerance, and the
files of their parameters (SSV), stimuli and references (time series), given by URIs relative to the experiment file.
"""
import xml.etree.ElementTree as ET

from dataclasses import dataclass, field
from pathlib import Path

from .ls import resolve_uri

#: Namespace of the experiment files.
NAMESPACE = "http://modelica.org/HSExperiments1/HSExperiments"

#: Default MIME type of the parameters of an experiment: SSV file of SSP.
PARAMETERS_TYPE = "application/x-ssp-parameter-set"

#: Default MIME type of the stimuli and of the references of an experiment.
TIME_SERIES_TYPE = "text/csv"


class ExperimentsError(Exception):
    """An experiment file that cannot be read."""


@dataclass
class ExperimentSource:
    """The file of the parameters, of the stimuli or of the references of an experiment.

    Attributes:
        source (str): URI of the file, relative to the experiment file.
        type (str): MIME type of the file.
        path (Path | None): The file, when it was found in the FMU.
        problem (str | None): Why the file was not found (see
            [resolve_uri][fmu_manipulation_toolbox.ls.resolve_uri]).
    """
    source: str
    type: str
    path: Path | None = None
    problem: str | None = None


@dataclass
class Experiment:
    """A `TransientExperiment` of an experiment file. The times are `None` when they are not given.

    Attributes:
        name (str): Name of the experiment.
        description (str | None): Human-readable description.
        start_time (float | None): Start time, in seconds.
        stop_time (float | None): Stop time, in seconds.
        step_size (float | None): Step size, in seconds.
        tolerance (float | None): Tolerance.
        parameters (ExperimentSource | None): Parameters of the experiment.
        stimuli (ExperimentSource | None): Stimuli of the experiment.
        references (ExperimentSource | None): Reference results of the experiment.
    """
    name: str
    description: str | None = None
    start_time: float | None = None
    stop_time: float | None = None
    step_size: float | None = None
    tolerance: float | None = None
    parameters: ExperimentSource | None = None
    stimuli: ExperimentSource | None = None
    references: ExperimentSource | None = None


@dataclass
class Experiments:
    """An experiment file (`Experiments` element).

    Attributes:
        name (str): Name of the set of experiments.
        description (str | None): Human-readable description.
        experiments (list[Experiment]): Its experiments, in the order of the file.
    """
    name: str
    description: str | None = None
    experiments: list[Experiment] = field(default_factory=list)


def _local_name(element: ET.Element) -> str:
    """Name of an element without its namespace."""
    return element.tag.rsplit("}", 1)[-1]


def _float(element: ET.Element, name: str) -> float | None:
    """Value of the attribute `name` of an experiment, `None` when it is absent."""
    value = element.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        raise ExperimentsError(f"experiment '{element.get('name')}': {name}='{value}' is not a number") from None


def read_experiments(filename: Path | str, root: Path | str) -> Experiments:
    """Reads the experiment file `filename` of the extracted FMU `root`.

    The elements are matched by their local name: the namespace and the XSD are checked by the checker of LS-REF.
    The sources are resolved against the directory of the file (see
    [resolve_uri][fmu_manipulation_toolbox.ls.resolve_uri]).

    Raises:
        ExperimentsError: The file is not well-formed XML, its root is not `Experiments`, or a time is not a number.
    """
    filename = Path(filename)
    try:
        element = ET.parse(filename).getroot()
    except ET.ParseError as error:
        raise ExperimentsError(f"cannot parse '{filename.name}': {error}") from None
    if _local_name(element) != "Experiments":
        raise ExperimentsError(f"'{filename.name}': root element is '{_local_name(element)}', not 'Experiments'")

    experiments = Experiments(name=element.get("name", ""), description=element.get("description"))
    for child in element:
        if _local_name(child) != "TransientExperiment":
            continue
        experiment = Experiment(name=child.get("name", ""), description=child.get("description"),
                                start_time=_float(child, "startTime"), stop_time=_float(child, "stopTime"),
                                step_size=_float(child, "stepSize"), tolerance=_float(child, "tolerance"))
        for source_element in child:
            kind = _local_name(source_element)
            if kind not in ("Parameters", "Stimuli", "References"):
                continue
            source = ExperimentSource(source=source_element.get("source", ""),
                                      type=source_element.get("type",
                                                              PARAMETERS_TYPE if kind == "Parameters"
                                                              else TIME_SERIES_TYPE))
            source.path, source.problem = resolve_uri(source.source, filename.parent, root)
            setattr(experiment, kind.lower(), source)
        experiments.experiments.append(experiment)
    return experiments
