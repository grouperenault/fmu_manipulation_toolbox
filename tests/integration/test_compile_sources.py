"""Integration tests of `OperationCompileSources` (see `docs/local/compile_sources.md`).

The Reference FMUs of `tests/data/compile` are copied without their `binaries/` and compiled for the host
platform; the result is simulated and compared with `REF-BouncingBall.csv`. These FMUs need the FMI headers
of the package and the prefix handling (D5, D10) to give a loadable library.

Each test runs in an isolated copy of `tests/data/compile`.
"""
import logging
import sys

import numpy as np
import pytest

from _helpers.archive import read_entry, rewrite_fmu

from fmu_manipulation_toolbox import compiler
from fmu_manipulation_toolbox.cli.fmutool import fmutool
from fmu_manipulation_toolbox.operations import FMU, OperationError

pytestmark = [pytest.mark.integration, pytest.mark.area("compile")]

FMI_VERSIONS = [pytest.param(2, marks=pytest.mark.fmi2), pytest.param(3, marks=pytest.mark.fmi3)]


def _reference(fmi_version: int) -> str:
    return f"{fmi_version}.0/BouncingBall.fmu"


def _host_binary(fmi_version: int) -> str:
    """Name of the archive entry of the host binary of `BouncingBall`."""
    return (f"binaries/{compiler.SourceCompiler.host_platform(fmi_version)}/"
            f"BouncingBall{compiler.SourceCompiler.library_suffix()}")


def _compile(source: str, destination: str):
    with FMU(source) as fmu:
        fmu.apply_operation(compiler.OperationCompileSources())
        fmu.repack(destination)


def _assert_reference_simulation(fmu_filename: str):
    from _helpers.simulation import simulate

    result = simulate(fmu_filename, stop_time=3, output_interval=0.01)
    reference = np.genfromtxt("REF-BouncingBall.csv", delimiter=",", names=True)
    assert len(result) == len(reference)
    for name in ("time", "h", "v"):
        np.testing.assert_allclose(result[name], reference[name], rtol=1e-6, atol=1e-6, err_msg=name)


# --------------------------------------------------------------------------- #
#                               Compilation                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.needs_compiler
@pytest.mark.parametrize("fmi_version", FMI_VERSIONS)
def test_compile_missing_binary(area_dir, fmi_version):
    rewrite_fmu(_reference(fmi_version), "no-binaries.fmu", drop=("binaries/",))
    _compile("no-binaries.fmu", "compiled.fmu")

    assert read_entry("compiled.fmu", _host_binary(fmi_version))
    # The sources are kept: the FMU can still be compiled for another platform.
    assert read_entry("compiled.fmu", "sources/model.c")


@pytest.mark.slow
@pytest.mark.needs_fmpy
@pytest.mark.needs_compiler
@pytest.mark.parametrize("fmi_version", FMI_VERSIONS)
def test_compiled_fmu_simulates(area_dir, fmi_version):
    rewrite_fmu(_reference(fmi_version), "no-binaries.fmu", drop=("binaries/",))
    _compile("no-binaries.fmu", "compiled.fmu")
    _assert_reference_simulation("compiled.fmu")


@pytest.mark.needs_compiler
@pytest.mark.fmi3
def test_compilation_failure(area_dir, caplog):
    """The compiler output is reported, and no binary is left behind."""
    rewrite_fmu(_reference(3), "broken.fmu", drop=("binaries/",),
                replace={"sources/model.c": b'#error "broken model.c"\n'})
    with FMU("broken.fmu") as fmu, caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        with pytest.raises(OperationError) as exc:
            fmu.apply_operation(compiler.OperationCompileSources())
        fmu.repack("result.fmu")

    assert "broken model.c" in caplog.text + str(exc.value)
    # The compiler output is reported as errors, with paths relative to the FMU.
    errors = [record.getMessage() for record in caplog.records if record.levelno == logging.ERROR]
    # MSVC may print the path with backslashes.
    assert any(message.replace("\\", "/").startswith("sources/model.c") and "broken model.c" in message
               for message in errors), errors
    assert "Compiling 'sources/model.c'." in caplog.text
    assert read_entry("result.fmu", _host_binary(3)) is None


# --------------------------------------------------------------------------- #
#                      Nothing to do / nothing possible                        #
# --------------------------------------------------------------------------- #
@pytest.mark.fmi3
def test_existing_binary_is_kept(area_dir):
    """D3: the host binary of the Reference FMU exists, nothing is compiled (no compiler needed)."""
    original = read_entry(_reference(3), _host_binary(3))
    assert original, f"the Reference FMU has no {_host_binary(3)}"

    _compile(_reference(3), "result.fmu")
    assert read_entry("result.fmu", _host_binary(3)) == original


@pytest.mark.fmi3
def test_no_sources(area_dir):
    rewrite_fmu(_reference(3), "no-sources.fmu", drop=("binaries/", "sources/"))
    with FMU("no-sources.fmu") as fmu:
        with pytest.raises(OperationError):
            fmu.apply_operation(compiler.OperationCompileSources())


# --------------------------------------------------------------------------- #
#                                    CLI                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.needs_compiler
@pytest.mark.fmi2
def test_cli_compile_sources(area_dir):
    rewrite_fmu(_reference(2), "no-binaries.fmu", drop=("binaries/",))
    sys.argv = ["fmutool", "-input", "no-binaries.fmu", "-compile-sources", "-output", "cli-compiled.fmu"]
    fmutool()
    assert read_entry("cli-compiled.fmu", _host_binary(2))
