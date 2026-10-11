"""Invariants of the built-in operations, checked on every FMU of `tests/data`.

- An operation applied to an XSD-valid descriptor produces an XSD-valid one (a refused operation leaves the
  descriptor unchanged, hence valid).
- A read-only operation (summary, CSV dump, checker) leaves the descriptor as a no-op operation does.

The FMUs are discovered automatically: an FMU added anywhere under `tests/data` is checked too, without any
reference file to generate.
"""
import csv
import functools
from pathlib import Path
from collections.abc import Callable

import pytest
import xmlschema

from fmu_manipulation_toolbox.checker import OperationGenericCheck
from fmu_manipulation_toolbox.operations import (
    FMU,
    OperationAbstract,
    OperationError,
    OperationKeepOnlyRegexp,
    OperationMergeTopLevel,
    OperationRemoveRegexp,
    OperationRemoveSources,
    OperationRenameFromCSV,
    OperationSaveNamesToCSV,
    OperationStripTopLevel,
    OperationSummary,
    OperationTrimUntil,
)

from _helpers.assertions import assert_equivalent_xml

pytestmark = [pytest.mark.integration]

DATA_DIR = Path(__file__).parent.parent / "data"
XSD_DIR = Path(__file__).parent.parent.parent / "fmu_manipulation_toolbox" / "resources"

FMU_FILES = sorted(DATA_DIR.rglob("*.fmu"))


def _fmu_id(path: Path) -> str:
    return path.relative_to(DATA_DIR).with_suffix("").as_posix().replace("/", "__")


def _names(fmu_path: Path, tmp_path: Path) -> list[str]:
    csv_filename = tmp_path / "names-for-rename.csv"
    FMU(str(fmu_path)).apply_operation(OperationSaveNamesToCSV(str(csv_filename)))
    with open(csv_filename, newline="") as file:
        return [row[0] for row in csv.reader(file, delimiter=";", quotechar="'")][1:]


def _rename_from_csv(fmu_path: Path, tmp_path: Path) -> OperationAbstract:
    """Rename every port, and remove one port out of three."""
    csv_filename = tmp_path / "rename.csv"
    with open(csv_filename, "w", newline="") as file:
        writer = csv.writer(file, delimiter=";", quotechar="'")
        for i, name in enumerate(_names(fmu_path, tmp_path)):
            writer.writerow([name, "" if i % 3 == 2 else f"renamed_{name}"])
    return OperationRenameFromCSV(str(csv_filename))


OperationFactory = Callable[[Path, Path], OperationAbstract]

#: Operations that modify the descriptor: name -> (factory, apply_on).
MODIFYING_CASES: dict[str, tuple[OperationFactory, list[str] | None]] = {
    "noop": (lambda fmu, tmp: OperationAbstract(), None),
    "strip_top_level": (lambda fmu, tmp: OperationStripTopLevel(), None),
    "merge_top_level": (lambda fmu, tmp: OperationMergeTopLevel(), None),
    "trim_until_dot": (lambda fmu, tmp: OperationTrimUntil("."), None),
    "remove_regexp": (lambda fmu, tmp: OperationRemoveRegexp("[a-mA-M]"), None),
    "keep_only_regexp": (lambda fmu, tmp: OperationKeepOnlyRegexp("[a-mA-M]"), None),
    "remove_all_outputs": (lambda fmu, tmp: OperationRemoveRegexp("."), ["output"]),
    "rename_from_csv": (_rename_from_csv, None),
    "remove_sources": (lambda fmu, tmp: OperationRemoveSources(), None),
}

#: Operations that must not change the meaning of the descriptor.
READ_ONLY_CASES: dict[str, OperationFactory] = {
    "summary": lambda fmu, tmp: OperationSummary(),
    "save_names_to_csv": lambda fmu, tmp: OperationSaveNamesToCSV(str(tmp / "dump.csv")),
    "generic_check": lambda fmu, tmp: OperationGenericCheck(),
}


def _apply(fmu_path: Path, tmp_path: Path, factory: OperationFactory) -> FMU:
    fmu = FMU(str(fmu_path))
    fmu.apply_operation(factory(fmu_path, tmp_path))
    return fmu


# --------------------------------------------------------------------------- #
#                         read-only operations                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", READ_ONLY_CASES)
@pytest.mark.parametrize("fmu_path", FMU_FILES, ids=_fmu_id)
def test_read_only_operation(fmu_path, case, tmp_path):
    expected = _apply(fmu_path, tmp_path, lambda fmu, tmp: OperationAbstract())
    fmu = _apply(fmu_path, tmp_path, READ_ONLY_CASES[case])
    assert_equivalent_xml(expected.descriptor_filename, fmu.descriptor_filename)


# --------------------------------------------------------------------------- #
#                              XSD validity                                    #
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=None)
def _schema(fmi_version: str) -> xmlschema.XMLSchema:
    return xmlschema.XMLSchema(str(XSD_DIR / f"fmi-{fmi_version}" / f"fmi{fmi_version[0]}ModelDescription.xsd"))


def _xsd_errors(descriptor_filename: str, fmi_version: str) -> list[str]:
    return [error.reason or str(error) for error in _schema(fmi_version).iter_errors(descriptor_filename)]


@pytest.mark.parametrize("case", MODIFYING_CASES)
@pytest.mark.parametrize("fmu_path", FMU_FILES, ids=_fmu_id)
def test_operation_keeps_descriptor_valid(fmu_path, case, tmp_path):
    """An operation applied to an XSD-valid FMU must produce an XSD-valid descriptor."""
    original = FMU(str(fmu_path))
    original.apply_operation(OperationSummary())  # sets fmi_version
    fmi_version = f"{original.fmi_version}.0"
    if _xsd_errors(original.descriptor_filename, fmi_version):
        pytest.skip("the original descriptor is not XSD-valid")

    factory, apply_on = MODIFYING_CASES[case]
    fmu = FMU(str(fmu_path))
    try:
        fmu.apply_operation(factory(fmu_path, tmp_path), apply_on)
    except OperationError:
        pass  # refused: the descriptor is left unchanged, hence still valid
    assert _xsd_errors(fmu.descriptor_filename, fmi_version) == []
