"""Integration tests for the reading of `container.txt` by the runtime (`docs/local/container_txt_robustness.md`).

`Feedthrough.fmu` of `tests/data/compile/2.0` is compiled for the host from its sources, with strings of up to 16384
characters (128 in the reference FMU): these tests simulate on every OS.
"""
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.container import FMUContainer
from fmu_manipulation_toolbox.container.types import CONTAINER_TXT_VERSION

from _helpers.archive import read_entry, rewrite_fmu

pytestmark = [pytest.mark.integration, pytest.mark.needs_fmpy, pytest.mark.needs_container,
              pytest.mark.needs_compiler, pytest.mark.area("compile")]

CONTAINER_TXT = "resources/container.txt"


def _make_container(filename: str, string_input: str | None = None) -> str:
    """Container of `Feedthrough.fmu` (FMI 2.0) compiled for the host, `String_output` exposed as `out`."""
    from fmu_manipulation_toolbox.compiler import OperationCompileSources
    from fmu_manipulation_toolbox.operations import FMU

    if not Path("2.0/no-binaries.fmu").exists():
        config = read_entry("2.0/Feedthrough.fmu", "sources/config.h").decode("utf-8")
        assert "#define STRING_MAX_LEN 128\n" in config
        config = config.replace("#define STRING_MAX_LEN 128\n", "#define STRING_MAX_LEN 16384\n")
        rewrite_fmu("2.0/Feedthrough.fmu", "2.0/no-binaries.fmu", drop=("binaries/",),
                    replace={"sources/config.h": config.encode("utf-8")})
        with FMU("2.0/no-binaries.fmu") as fmu:
            fmu.apply_operation(OperationCompileSources())
            fmu.repack("2.0/Feedthrough.fmu")

    container = FMUContainer("feedthrough", "2.0")
    container.get_fmu("Feedthrough.fmu")
    container.add_output("Feedthrough.fmu", "String_output", "out")
    if string_input is not None:
        container.add_start_value("Feedthrough.fmu", "String_input", string_input)
    container.make_fmu(filename, step_size=0.1)
    return f"2.0/{filename}"


def _with_header(filename: str, destination: str, header: str | None) -> str:
    """Copy of the container `filename`, the first line of its `container.txt` replaced by `header` (removed when
    None). The line endings of the file are kept (`\r\n` on Windows)."""
    lines = read_entry(filename, CONTAINER_TXT).decode("utf-8").splitlines(keepends=True)
    first = lines[0].rstrip("\r\n")
    assert first == f"# Version {CONTAINER_TXT_VERSION}"
    lines[0:1] = [] if header is None else [header + lines[0][len(first):]]
    rewrite_fmu(filename, destination, replace={CONTAINER_TXT: "".join(lines).encode("utf-8")})
    return destination


def _instantiate(filename: str):
    """Instantiate the container `filename` (co-simulation); return the instance (None when the instantiation
    failed), its variables and the messages it logged."""
    from fmpy import extract, read_model_description
    from fmpy.simulation import instantiate_fmu

    model_description = read_model_description(filename)
    vrs = {variable.name: variable.valueReference for variable in model_description.modelVariables}
    messages = []

    def fmu_log(*args):
        messages.append(args[-1].decode("utf-8"))

    try:
        fmu = instantiate_fmu(extract(filename), model_description, fmi_type="CoSimulation", logger=fmu_log)
    except Exception:
        fmu = None
    # The logger stays referenced by the instance: see `_helpers.simulation.simulate`.
    fmu_log.keep_alive = fmu
    return fmu, vrs, messages, fmu_log


def _initialize(fmu):
    fmu.setupExperiment(startTime=0)
    fmu.enterInitializationMode()
    fmu.exitInitializationMode()


# --------------------------------------------------------------------------- #
#                              Format version                                   #
# --------------------------------------------------------------------------- #
def test_container_txt_version_is_accepted(area_dir):
    fmu, _, messages, _logger = _instantiate(_make_container("version.fmu"))
    assert fmu is not None, messages
    _initialize(fmu)
    fmu.terminate()
    fmu.freeInstance()


@pytest.mark.parametrize("header, message", [
    (f"# Version {CONTAINER_TXT_VERSION - 1}",
     f"container.txt format version {CONTAINER_TXT_VERSION - 1}, this runtime reads version {CONTAINER_TXT_VERSION}"),
    (None, "container.txt has no format version header"),
])
def test_container_txt_version_is_checked(area_dir, header, message):
    """A `container.txt` of another format version, or without version header, is refused at instantiation."""
    filename = _with_header(_make_container("version.fmu"), "2.0/other-version.fmu", header)
    fmu, _, messages, _logger = _instantiate(filename)
    assert fmu is None
    assert any(message in logged for logged in messages), messages


# --------------------------------------------------------------------------- #
#                                Long lines                                     #
# --------------------------------------------------------------------------- #
def test_container_txt_long_line(area_dir):
    """A string start value longer than the former line buffer (4096 bytes) reaches the embedded FMU unchanged."""
    value = "".join(chr(ord("a") + i % 26) for i in range(10_000))
    filename = _make_container("long.fmu", string_input=value)
    assert value in read_entry(filename, CONTAINER_TXT).decode("utf-8")

    fmu, vrs, messages, _logger = _instantiate(filename)
    assert fmu is not None, messages
    _initialize(fmu)
    fmu.doStep(0.0, 0.1)
    assert fmu.getString([vrs["out"]])[0].decode("utf-8") == value
    fmu.terminate()
    fmu.freeInstance()
