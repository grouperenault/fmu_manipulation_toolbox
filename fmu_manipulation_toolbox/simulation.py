"""Replay of an experiment of FMI-LS-REF with the container runtime.

The FMU is embedded in a temporary FMI-3.0 container (`FMUContainer`, whatever the FMI version of the FMU: the
runtime embeds FMI-2.0 FMUs as well): one input per stimulus, one output per variable to record, the parameters as
start values. The library of the container is then driven through its FMI-3.0 API (ctypes; the logger of FMI 2.0 is
variadic, which ctypes cannot read on every platform):
at each communication point `t_k = start + k * step` (computed, not accumulated), the stimuli interpolated at `t_k`
are set, the outputs are read and recorded at `t_k`, then the container steps to `t_k+1` (convention of fmpy and of
the results of the Reference-FMUs: an output fed through follows its input at the same instant).
When an embedded FMU asks to terminate the simulation, the container stops at the time reached: the simulation ends
there, the outputs of this instant being the last ones recorded.
An array output is recorded as one column per element, named as by the structured naming convention of FMI 3.0
(indices from 1, row-major order): `y[1]`, `y[2]`... or `m[1,1]`, `m[1,2]`...

The simulation runs in a dedicated process (`multiprocessing`, `spawn`): a crash of the FMU or of the runtime, or a
simulation that never returns, fails the replay instead of the calling process, and the libraries loaded by the
simulation are unloaded with its process.
"""
import ctypes
import itertools
import logging
import math
import multiprocessing
import platform
import shutil
import signal
import tempfile
import zipfile
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .compiler import SourceCompiler
from .container import FMUContainer, FMUContainerError
from .experiments import Experiment, Parameter
from .model_description import ModelDescription, ModelVariable
from .timeseries import HOLD, LINEAR, TimeSeries, to_number

logger = logging.getLogger("fmu_manipulation_toolbox")

#: Identifier of the temporary container.
IDENTIFIER = "lsref"


class SimulationError(Exception):
    """An experiment that cannot be replayed."""


class SimulationUnavailable(SimulationError):
    """The container runtime, or the binary of the FMU, is not available for the host platform."""


class SimulationUnsupported(SimulationError):
    """An experiment that the temporary container cannot replay (a stimulus on a boolean input of an FMI-2.0 FMU)."""


@dataclass
class _Port:
    """A port of the temporary container."""
    name: str
    vr: int
    fmi_type: str
    interpolation: str
    shape: tuple[int, ...] | None = ()     # sizes of the dimensions of an array, () for a scalar, None: unknown

    @property
    def size(self) -> int:
        return math.prod(self.shape)

    @property
    def columns(self) -> list[str]:
        """Names of the recorded columns: the name of a scalar, one name per element of an array."""
        if not self.shape:
            return [self.name]
        return [f"{self.name}[{','.join(str(i) for i in index)}]"
                for index in itertools.product(*(range(1, n + 1) for n in self.shape))]


def _time(element, name: str) -> float | None:
    """Time attribute `name` of a `DefaultExperiment`, `None` when absent or not a number."""
    if element is None:
        return None
    try:
        return float(element.get(name))
    except (TypeError, ValueError):
        return None


def experiment_times(experiment: Experiment, model_description: ModelDescription,
                     references: TimeSeries | None) -> tuple[float, float]:
    """Start and stop times of an experiment: those of the experiment, else those of the `DefaultExperiment` of the
    FMU, else the first and the last instants of the references.

    Raises:
        SimulationError: A time cannot be determined.
    """
    default = model_description.default_experiment
    times = []
    for name, value, index in (("startTime", experiment.start_time, 0), ("stopTime", experiment.stop_time, -1)):
        if value is None:
            value = _time(default, name)
        if value is None and references is not None and references.times:
            value = references.times[index]
            logger.info(f"Experiment '{experiment.name}': {name} {value} taken from the references.")
        if value is None:
            raise SimulationError(f"experiment '{experiment.name}': no {name}")
        times.append(value)
    return times[0], times[1]


def replay(fmu_filename: Path | str, experiment: Experiment, outputs: list[str], stimuli: TimeSeries | None = None,
           parameters: list[Parameter] | None = None, references: TimeSeries | None = None,
           timeout: float | None = None, isolated: bool = True) -> TimeSeries:
    """Replays `experiment` on the FMU `fmu_filename` with the container runtime and records `outputs`.

    Args:
        fmu_filename: The FMU.
        experiment: Its start and stop times and its step size (`None`: see `experiment_times`; step size deduced by
            the container builder). Its `tolerance` is not used: the container runtime also takes the tolerance of
            the initialization as its tolerance on time.
        outputs: Names of the output variables to record.
        stimuli: Values of input variables (linear interpolation for the continuous reals, previous value otherwise).
        parameters: Start values of parameters.
        references: The references, whose instants give the start and stop times when nothing else does.
        timeout: Time limit of the simulation, in seconds (`None`: no limit). Only with `isolated`.
        isolated: Run the simulation in a dedicated process (`False`: in the calling process).

    Returns:
        TimeSeries: The values of `outputs` at each communication point; an array output gives one column per
            element (`y[1]`, `y[2]`..., `m[1,1]`, `m[1,2]`...: indices from 1, row-major order).

    Raises:
        SimulationUnavailable: The container or the FMU has no library for the host platform.
        SimulationUnsupported: A stimulus is on a boolean input of an FMI-2.0 FMU, which the FMI-3.0 container cannot
            expose, or on an array input; an output is an array whose dimension is given by a structural parameter.
        SimulationError: The container cannot be built, the simulation fails, crashes or exceeds `timeout`.
    """
    # Created and removed here: a library loaded by the simulation locks its files on Windows until its process ends.
    directory = Path(tempfile.mkdtemp(prefix="fmutool-lsref-"))
    try:
        arguments = (directory, Path(fmu_filename), experiment, outputs, stimuli, parameters or [], references)
        if isolated:
            return _simulate_in_process(arguments, timeout)
        return _simulate(*arguments)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _simulate(directory: Path, fmu_filename: Path, experiment: Experiment, outputs: list[str],
              stimuli: TimeSeries | None, parameters: list[Parameter], references: TimeSeries | None) -> TimeSeries:
    """The simulation of `replay`, in the temporary directory `directory`."""
    with zipfile.ZipFile(fmu_filename) as archive:
        model_description = ModelDescription.load(archive.read("modelDescription.xml"))
    _check_host_binary(fmu_filename, model_description)
    if stimuli and model_description.fmi_version == 2:
        booleans = {port.get("name") for port in model_description.iter_ports() if port.fmi_type == "Boolean"}
        for name in stimuli.columns:
            if name in booleans:
                raise SimulationUnsupported(f"the stimulus of the FMI-2.0 boolean '{name}' cannot be set through the "
                                            f"FMI-3.0 container")
    start_time, stop_time = experiment_times(experiment, model_description, references)
    if experiment.tolerance is not None:
        logger.info(f"Experiment '{experiment.name}': its tolerance ({experiment.tolerance}) is not used.")

    fmus = directory / "fmus"
    fmus.mkdir()
    shutil.copy(fmu_filename, fmus / fmu_filename.name)
    step_size = _build_container(fmus, fmu_filename.name, experiment, outputs, stimuli, parameters,
                                 directory / f"{IDENTIFIER}.fmu")
    extracted = directory / "container"
    with zipfile.ZipFile(directory / f"{IDENTIFIER}.fmu") as archive:
        archive.extractall(extracted)
    driver = _Driver(extracted)
    try:
        return driver.run(start_time, stop_time, step_size, stimuli, outputs)
    finally:
        driver.unload()


# --------------------------------------------------------------------------- #
#                              Dedicated process                              #
# --------------------------------------------------------------------------- #
#: Exceptions given back by the dedicated process, by name.
_EXCEPTIONS = {cls.__name__: cls for cls in (SimulationError, SimulationUnavailable, SimulationUnsupported)}


class _Recorder(logging.Handler):
    """Keeps the messages of the dedicated process, to be emitted again by the calling process."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records: list[tuple[int, str]] = []

    def emit(self, record: logging.LogRecord):
        self.records.append((record.levelno, record.getMessage()))


def _is_windows_exception(error: OSError) -> bool:
    """On Windows, ctypes catches the structured exceptions (access violation, ...) of a foreign function and raises
    `OSError("exception: access violation writing 0x...")` or `OSError("exception code 0x...")` instead."""
    return platform.system() == "Windows" and str(error).startswith("exception")


def _child(connection, arguments: tuple, level: int):
    """Body of the dedicated process: the simulation, its result or its exception, and its messages."""
    recorder = _Recorder()
    logger.addHandler(recorder)
    logger.setLevel(level)
    try:
        result = ("ok", _simulate(*arguments))
    except SimulationError as error:
        result = ("error", type(error).__name__, str(error))
    except OSError as error:
        if _is_windows_exception(error):    # the process survives a fault of the FMU, which ctypes turns into OSError
            result = ("error", "SimulationError", f"the simulation crashed ({str(error).removeprefix('exception: ')})")
        else:
            result = ("error", "SimulationError", f"{type(error).__name__}: {error}")
    except Exception as error:      # noqa: BLE001 - any failure of the simulation is reported by the calling process
        result = ("error", "SimulationError", f"{type(error).__name__}: {error}")
    connection.send((result, recorder.records))
    connection.close()


def _exit_reason(exit_code: int | None) -> str:
    """Why the dedicated process ended: a signal (POSIX) or an exit code (Windows: an NTSTATUS, in hexadecimal)."""
    if exit_code is None:
        return "no exit code"
    if exit_code < 0:
        try:
            return f"signal {signal.Signals(-exit_code).name}"
        except ValueError:
            return f"signal {-exit_code}"
    return f"exit code {exit_code:#x}" if exit_code > 0xFFFF else f"exit code {exit_code}"


def _simulate_in_process(arguments: tuple, timeout: float | None) -> TimeSeries:
    """`_simulate` in a dedicated process, killed after `timeout` seconds."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(sender, arguments, logger.getEffectiveLevel()), daemon=True)
    process.start()
    sender.close()      # the end of the child only: its crash closes the pipe
    try:
        if not receiver.poll(timeout):
            process.kill()
            raise SimulationError(f"the simulation did not end within {timeout:g} s: it is stopped")
        try:
            result, records = receiver.recv()
        except EOFError:
            process.join()
            raise SimulationError(f"the simulation crashed ({_exit_reason(process.exitcode)})") from None
    finally:
        receiver.close()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()

    for level, message in records:
        logger.log(level, message)
    if result[0] == "ok":
        return result[1]
    raise _EXCEPTIONS.get(result[1], SimulationError)(result[2])


def _check_host_binary(fmu_filename: Path, model_description: ModelDescription):
    """Raises `SimulationUnavailable` when the FMU has no binary for the host platform."""
    try:
        host = SourceCompiler.host_platform(model_description.fmi_version)
    except Exception as error:      # OperationError: the host platform has no name in this FMI version
        raise SimulationUnavailable(str(error)) from None
    with zipfile.ZipFile(fmu_filename) as archive:
        names = set(archive.namelist())
    identifiers = {element.get("modelIdentifier") for element in model_description.interfaces.values()}
    if not any(f"binaries/{host}/{identifier}{SourceCompiler.library_suffix()}" in names
               for identifier in identifiers if identifier):
        raise SimulationUnavailable(f"the FMU has no binary for the host platform ({host})")


class _DebugOnly(logging.Filter):
    """Turns every message into a debug message."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.levelno, record.levelname = logging.DEBUG, "DEBUG"
        return True


@contextmanager
def _quiet_builder():
    """The messages of the builder of the temporary container are details of the replay: debug messages. Its
    errors on the inputs of the FMU that have no stimulus do not concern the experiment; an error that prevents
    building the container raises an `FMUContainerError`."""
    debug_only = _DebugOnly()
    logger.addFilter(debug_only)
    try:
        yield
    finally:
        logger.removeFilter(debug_only)


def _build_container(fmus: Path, fmu_name: str, experiment: Experiment, outputs: list[str],
                     stimuli: TimeSeries | None, parameters: list[Parameter], destination: Path) -> float:
    """Builds the temporary container; returns its step size."""
    step_size = experiment.step_size
    try:
        with _quiet_builder():
            container = FMUContainer(IDENTIFIER, fmus, fmi_version=3)
            container.get_fmu(fmu_name)
            for name in (stimuli.columns if stimuli else []):
                container.add_input(name, fmu_name, name)
            for name in outputs:
                container.add_output(fmu_name, name, name)
            for parameter in parameters:
                container.add_start_value(fmu_name, parameter.name, parameter.value)
            if step_size is None:
                step_size = container.default_step_size()
            container.make_fmu(destination, step_size=step_size)
    except FMUContainerError as error:
        raise SimulationError(f"cannot build the container of experiment '{experiment.name}': {error}") from None
    if experiment.step_size is None:
        logger.info(f"Experiment '{experiment.name}': step size {step_size} deduced from the FMU.")
    return step_size


# --------------------------------------------------------------------------- #
#                      FMI-3.0 driver of the container                        #
# --------------------------------------------------------------------------- #
#: C types of the FMI types of the ports, and the name of the function that sets or gets them.
FMI3_TYPES = {
    "Float64": (ctypes.c_double, "Float64"), "Float32": (ctypes.c_float, "Float32"),
    "Int8": (ctypes.c_int8, "Int8"), "UInt8": (ctypes.c_uint8, "UInt8"),
    "Int16": (ctypes.c_int16, "Int16"), "UInt16": (ctypes.c_uint16, "UInt16"),
    "Int32": (ctypes.c_int32, "Int32"), "UInt32": (ctypes.c_uint32, "UInt32"),
    "Int64": (ctypes.c_int64, "Int64"), "UInt64": (ctypes.c_uint64, "UInt64"),
    "Enumeration": (ctypes.c_int64, "Int64"), "Boolean": (ctypes.c_bool, "Boolean"),
    "String": (ctypes.c_char_p, "String"),
}

FMI3_LOG_MESSAGE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p)


class _Driver:
    """FMI-3.0 Co-Simulation driver of an extracted container."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.model_description = ModelDescription.load(directory / "modelDescription.xml")
        self.messages: deque[str] = deque(maxlen=20)
        self.library = self._load_library()
        self.instance = None
        self.ports = {port.get("name"): self._port(port) for port in self.model_description.iter_ports()}
        self._log_message = FMI3_LOG_MESSAGE(self._fmi3_log_message)     # must live as long as the instance

    def _load_library(self) -> ctypes.CDLL:
        suffix = SourceCompiler.library_suffix()
        libraries = sorted((self.directory / "binaries").glob(f"*/{IDENTIFIER}{suffix}"))
        if not libraries:
            raise SimulationUnavailable(f"the container runtime has no library for {platform.system()}")
        try:
            return ctypes.CDLL(str(libraries[0]))
        except OSError as error:
            raise SimulationUnavailable(f"cannot load the container runtime: {error}") from None

    @staticmethod
    def _port(variable: ModelVariable) -> _Port:
        continuous = variable.variability == "continuous" and variable.has_type(("Float64", "Float32"))
        dimensions = variable.dimensions
        shape = tuple(size for kind, size in dimensions) if all(kind == "start" for kind, _ in dimensions) else None
        return _Port(variable.get("name"), int(variable.get("valueReference")), variable.fmi_type,
                     LINEAR if continuous else HOLD, shape)

    def _fmi3_log_message(self, environment, status, category, message):
        text = message.decode("utf-8", "replace") if message else ""
        self.messages.append(text)
        logger.debug(f"Container [{status}]: {text}")

    def _last_messages(self) -> str:
        last = "; ".join(message for message in self.messages if message)[-500:]
        return f": {last}" if last else ""

    def _call(self, name: str, *arguments):
        function = getattr(self.library, name)
        function.restype = ctypes.c_int
        status = function(ctypes.c_void_p(self.instance), *arguments)
        if status > 1:      # fmi3Error, fmi3Fatal
            raise SimulationError(f"{name} failed (status {status}){self._last_messages()}")

    # ----------------------------------------------------------------- run
    def run(self, start_time: float, stop_time: float, step_size: float, stimuli: TimeSeries | None,
            outputs: list[str]) -> TimeSeries:
        nb_steps = math.floor((stop_time - start_time) / step_size + 1e-9)
        if not math.isclose(start_time + nb_steps * step_size, stop_time, rel_tol=1e-9, abs_tol=1e-12):
            logger.info(f"The stop time {stop_time} is not a multiple of the step size {step_size}: the simulation "
                        f"stops at {start_time + nb_steps * step_size}.")
        inputs = [self.ports[name] for name in (stimuli.columns if stimuli else [])]
        recorded = [self.ports[name] for name in outputs]
        for port in inputs:
            if port.shape != ():
                raise SimulationUnsupported(f"the stimulus of the array '{port.name}' cannot be set")
        for port in recorded:
            if port.shape is None:
                raise SimulationUnsupported(f"the dimension of the array '{port.name}' is given by a structural "
                                            f"parameter")
        result = TimeSeries(columns={column: [] for port in recorded for column in port.columns})

        self._instantiate()
        self._call("fmi3EnterInitializationMode", ctypes.c_bool(False), ctypes.c_double(0.0),
                   ctypes.c_double(start_time), ctypes.c_bool(True), ctypes.c_double(stop_time))
        self._set_inputs(inputs, stimuli, start_time)
        self._call("fmi3ExitInitializationMode")
        self._record_outputs(result, recorded, start_time)
        for k in range(nb_steps):
            last_time = self._do_step(start_time + k * step_size, step_size)
            if last_time is not None:
                # The container ends the simulation where an FMU asked for it: the outputs of this instant end it.
                logger.info(f"The container terminates the simulation at {last_time} (requested by an FMU).")
                self._record_outputs(result, recorded, last_time)
                break
            time = start_time + (k + 1) * step_size
            self._set_inputs(inputs, stimuli, time)
            self._record_outputs(result, recorded, time)
        self._call("fmi3Terminate")
        return result

    def unload(self):
        if self.instance:
            self.library.fmi3FreeInstance(ctypes.c_void_p(self.instance))
            self.instance = None

    def _instantiate(self):
        function = self.library.fmi3InstantiateCoSimulation
        function.restype = ctypes.c_void_p
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_bool, ctypes.c_bool,
                             ctypes.c_bool, ctypes.c_bool, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                             FMI3_LOG_MESSAGE, ctypes.c_void_p]
        token = self.model_description.root.get("instantiationToken", "")
        resources = str(self.directory / "resources") + "/"
        self.instance = function(b"lsref", token.encode(), resources.encode(), False, True, False, False, None, 0,
                                 None, self._log_message, None)
        if not self.instance:
            raise SimulationError(f"the container cannot be instantiated{self._last_messages()}")

    def _do_step(self, time: float, step_size: float) -> float | None:
        """Steps the container: `None`, or the time reached when it terminates the simulation."""
        event, terminate, early = ctypes.c_bool(), ctypes.c_bool(), ctypes.c_bool()
        last_time = ctypes.c_double()
        self._call("fmi3DoStep", ctypes.c_double(time), ctypes.c_double(step_size), ctypes.c_bool(True),
                   ctypes.byref(event), ctypes.byref(terminate), ctypes.byref(early), ctypes.byref(last_time))
        return last_time.value if terminate.value else None

    @staticmethod
    def _types(port: _Port) -> tuple:
        if port.fmi_type not in FMI3_TYPES:
            raise SimulationError(f"variable '{port.name}': type {port.fmi_type} is not supported")
        return FMI3_TYPES[port.fmi_type]

    @staticmethod
    def _c_value(c_type, value):
        if c_type is ctypes.c_char_p:
            return c_type(str(value).encode("utf-8"))
        number = to_number(value)
        if c_type in (ctypes.c_double, ctypes.c_float):
            return c_type(number)
        if c_type is ctypes.c_bool:
            return c_type(number != 0)
        return c_type(int(round(number)))

    def _set_inputs(self, inputs: list[_Port], stimuli: TimeSeries | None, time: float):
        for port in inputs:
            c_type, function = self._types(port)
            value = self._c_value(c_type, stimuli.value(port.name, time, port.interpolation))
            vr = ctypes.c_uint32(port.vr)
            self._call(f"fmi3Set{function}", ctypes.byref(vr), ctypes.c_size_t(1), ctypes.byref(value),
                       ctypes.c_size_t(1))

    def _record_outputs(self, result: TimeSeries, outputs: list[_Port], time: float):
        result.times.append(time)
        for port in outputs:
            c_type, function = self._types(port)
            values = (c_type * port.size)()
            vr = ctypes.c_uint32(port.vr)
            self._call(f"fmi3Get{function}", ctypes.byref(vr), ctypes.c_size_t(1), values,
                       ctypes.c_size_t(port.size))
            for column, value in zip(port.columns, values):
                if c_type is ctypes.c_char_p:
                    result.columns[column].append((value or b"").decode("utf-8", "replace"))
                else:
                    result.columns[column].append(value)
