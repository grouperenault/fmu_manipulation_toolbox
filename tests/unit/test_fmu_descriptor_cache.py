"""`FMU` parses `modelDescription.xml` once and writes it only when needed.

Phase 5 of `docs/local/done/refactoring.md`: the descriptor tree is shared by the
successive operations applied to an `FMU`, and it is not written back after an
operation declared `read_only`, so that read-only operations (summary, CSV
dump, checker) leave the file exactly as it was in the archive.
"""
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox import model_description
from fmu_manipulation_toolbox.checker import OperationGenericCheck
from fmu_manipulation_toolbox.operations import (FMU, FMUError, OperationAbstract, OperationError,
                                                 OperationSaveNamesToCSV, OperationStripTopLevel, OperationSummary)

pytestmark = [pytest.mark.unit]

# Formatting that a rewrite would change: single quotes, no XML declaration, a comment before the root.
DESCRIPTOR = b"""<!-- written by hand -->
<fmiModelDescription fmiVersion='3.0' modelName='m' instantiationToken='{8c4e810f-3df3-4a00-8276-176fa3c9f000}'>
  <CoSimulation modelIdentifier='m'></CoSimulation>
  <ModelVariables>
    <Float64 name='a.y' valueReference='1' causality='output'></Float64>
    <Float64 name='b.y' valueReference='2' causality='output'></Float64>
    <Float64 name='b.z' valueReference='3' causality='output'></Float64>
  </ModelVariables>
  <ModelStructure><Output valueReference='1'/><Output valueReference='2'/><Output valueReference='3'/></ModelStructure>
</fmiModelDescription>
"""


@pytest.fixture
def fmu(tmp_path):
    fmu_filename = tmp_path / "test.fmu"
    with zipfile.ZipFile(fmu_filename, "w") as archive:
        archive.writestr("modelDescription.xml", DESCRIPTOR)
    with FMU(str(fmu_filename)) as fmu:
        yield fmu


@pytest.fixture
def loads(monkeypatch):
    """Count the parses of a descriptor."""
    calls = []
    load = model_description.ModelDescription.load.__func__

    def counting_load(cls, source):
        calls.append(source)
        return load(cls, source)

    monkeypatch.setattr(model_description.ModelDescription, "load", classmethod(counting_load))
    return calls


class _Rename(OperationAbstract):
    """A user operation: not declared `read_only`, so it is written back."""

    def port_attrs(self, fmu_port) -> int:
        fmu_port["name"] = fmu_port["name"].upper()
        return 0


def _names(fmu: FMU):
    return [variable.get("name") for variable in fmu.model_description.variables()]


@pytest.mark.parametrize("operation", ["summary", "check", "csv"])
def test_read_only_operation_leaves_file_untouched(fmu, tmp_path, operation):
    operations = {
        "summary": OperationSummary,
        "check": OperationGenericCheck,
        "csv": lambda: OperationSaveNamesToCSV(str(tmp_path / "names.csv")),
    }
    fmu.apply_operation(operations[operation]())
    assert Path(fmu.descriptor_filename).read_bytes() == DESCRIPTOR


def test_modifying_operation_writes_file(fmu):
    fmu.apply_operation(_Rename())
    written = Path(fmu.descriptor_filename).read_bytes()
    assert written.startswith(b'<?xml version="1.0" encoding="UTF-8"?>') and b"A.Y" in written


def test_descriptor_is_parsed_once(fmu, loads, tmp_path):
    fmu.apply_operation(OperationSummary())
    fmu.apply_operation(_Rename())
    fmu.apply_operation(OperationSaveNamesToCSV(str(tmp_path / "names.csv")))
    assert len(loads) == 1
    assert "A.Y" in (tmp_path / "names.csv").read_text()


def test_descriptor_changed_on_disk_is_parsed_again(fmu, loads):
    fmu.apply_operation(OperationSummary())
    Path(fmu.descriptor_filename).write_bytes(DESCRIPTOR.replace(b"a.y", b"changed.y"))
    assert "changed.y" in _names(fmu)
    assert len(loads) == 2


def test_refused_operation_does_not_leave_a_half_modified_tree(fmu):
    """Stripping the top level would give 'y' twice: refused (D13) after the ports were renamed in memory."""
    with pytest.raises(OperationError):
        fmu.apply_operation(OperationStripTopLevel())
    assert _names(fmu) == ["a.y", "b.y", "b.z"]
    assert Path(fmu.descriptor_filename).read_bytes() == DESCRIPTOR


def test_model_description_of_closed_fmu_raises(fmu):
    fmu.close()
    with pytest.raises(FMUError, match="is closed"):
        fmu.model_description
