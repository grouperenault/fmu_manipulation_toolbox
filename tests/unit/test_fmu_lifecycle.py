"""Life cycle of `FMU`: errors when opening, temporary directory clean-up.

Phase 3 of `docs/refactoring.md`: every failure to open an FMU is an
`FMUError`, and the temporary extraction directory is removed by `close()`, at
the end of a `with` block, when the object is garbage-collected, or when
opening fails, instead of relying on `__del__`.
"""
import gc
import tempfile
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.operations import FMU, FMUError, OperationAbstract

pytestmark = [pytest.mark.unit]

DESCRIPTOR = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <CoSimulation modelIdentifier="m"/>
  <ModelVariables><Float64 name="y" valueReference="1" causality="output"/></ModelVariables>
  <ModelStructure><Output valueReference="1"/></ModelStructure>
</fmiModelDescription>
"""


def make_fmu(tmp_path: Path, files=None) -> Path:
    fmu_filename = tmp_path / "test.fmu"
    with zipfile.ZipFile(fmu_filename, "w") as fmu:
        for name, content in (files if files is not None else {"modelDescription.xml": DESCRIPTOR}).items():
            fmu.writestr(name, content)
    return fmu_filename


@pytest.fixture
def created_directories(monkeypatch):
    """Record the temporary directories created by `FMU`."""
    directories = []
    mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        directories.append(Path(mkdtemp(*args, **kwargs)))
        return str(directories[-1])

    monkeypatch.setattr(tempfile, "mkdtemp", recording_mkdtemp)
    return directories


# --------------------------------------------------------------------------- #
#                           Clean-up of the directory                          #
# --------------------------------------------------------------------------- #
def test_context_manager_removes_directory(tmp_path):
    with FMU(str(make_fmu(tmp_path))) as fmu:
        directory = Path(fmu.tmp_directory)
        assert directory.is_dir() and not fmu.closed
    assert not directory.exists()
    assert fmu.closed


def test_context_manager_removes_directory_on_error(tmp_path):
    with pytest.raises(RuntimeError):
        with FMU(str(make_fmu(tmp_path))) as fmu:
            directory = Path(fmu.tmp_directory)
            raise RuntimeError("boom")
    assert not directory.exists()


def test_close_is_idempotent(tmp_path):
    fmu = FMU(str(make_fmu(tmp_path)))
    fmu.close()
    fmu.close()
    assert not Path(fmu.tmp_directory).exists()


def test_garbage_collection_removes_directory(tmp_path):
    fmu = FMU(str(make_fmu(tmp_path)))
    directory = Path(fmu.tmp_directory)
    del fmu
    gc.collect()
    assert not directory.exists()


def test_close_tolerates_a_directory_already_removed(tmp_path):
    import shutil
    fmu = FMU(str(make_fmu(tmp_path)))
    shutil.rmtree(fmu.tmp_directory)
    fmu.close()


@pytest.mark.parametrize("method, args", [
    ("apply_operation", (OperationAbstract(),)),
    ("repack", ("out.fmu",)),
    ("save_descriptor", ("modelDescription.xml",)),
])
def test_closed_fmu_cannot_be_used(tmp_path, method, args):
    fmu = FMU(str(make_fmu(tmp_path)))
    fmu.close()
    with pytest.raises(FMUError, match="is closed"):
        getattr(fmu, method)(*[str(tmp_path / a) if isinstance(a, str) else a for a in args])


# --------------------------------------------------------------------------- #
#                         Errors when opening an FMU                           #
# --------------------------------------------------------------------------- #
def test_not_a_zip_raises_fmu_error(tmp_path, created_directories):
    not_a_zip = tmp_path / "not_a_zip.fmu"
    not_a_zip.write_text("this is not a zip archive")
    with pytest.raises(FMUError, match="not a ZIP archive"):
        FMU(str(not_a_zip))
    assert created_directories and not created_directories[0].exists()


def test_directory_raises_fmu_error(tmp_path, created_directories):
    with pytest.raises(FMUError, match="cannot be read"):
        FMU(str(tmp_path))
    assert not created_directories[0].exists()


def test_missing_file_raises_fmu_error(tmp_path, created_directories):
    with pytest.raises(FMUError, match="does not exist"):
        FMU(str(tmp_path / "missing.fmu"))
    assert not created_directories[0].exists()


def test_missing_descriptor_raises_fmu_error(tmp_path, created_directories):
    with pytest.raises(FMUError, match="modelDescription.xml not found"):
        FMU(str(make_fmu(tmp_path, {"binaries/readme.txt": "no descriptor"})))
    assert not created_directories[0].exists()


@pytest.mark.parametrize("descriptor, match", [
    ("<fmiModelDescription fmiVersion='3.0'><x>a < b</x></fmiModelDescription>", "not well-formed"),
    ("<fmiModelDescription fmiVersion='1.0'/>", "Unsupported fmiVersion"),
    ("<model/>", "expected <fmiModelDescription>"),
], ids=["not-well-formed", "fmi1", "wrong-root"])
def test_unreadable_descriptor_raises_fmu_error(tmp_path, descriptor, match):
    """The descriptor is only parsed by `apply_operation`, which reports an `FMUError` (not an XML error)."""
    with FMU(str(make_fmu(tmp_path, {"modelDescription.xml": descriptor}))) as fmu:
        with pytest.raises(FMUError, match=match):
            fmu.apply_operation(OperationAbstract())
