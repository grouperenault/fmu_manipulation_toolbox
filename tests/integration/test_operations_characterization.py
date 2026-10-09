"""Characterization tests of the built-in operations (refactoring safety net).

These tests pin down what `FMU.apply_operation` produces today, so that the
switch of `Manipulation` to ElementTree (see `docs/refactoring.md`, phase 2)
can be checked for equivalence. For every FMU of `tests/data` and every
built-in operation, they compare against references stored in
`tests/data/refactoring/<fmu>/`:

- `<case>.xml`: the resulting `modelDescription.xml`, in canonical form
  (compared with `assert_equivalent_xml`, so formatting does not matter);
- `names.csv`: the output of `OperationSaveNamesToCSV`;
- `summary.txt`: the report of `OperationSummary` (volatile lines removed).

Read-only operations (summary, CSV dump, checker, remove-sources) must leave the
descriptor as the no-op operation does; they are compared to `noop.xml`.

The references were generated with the expat-based implementation. Regenerate
them only on purpose, after reviewing the change in behaviour:

    cd tests && pytest integration/test_operations_characterization.py --update-refs
"""
import csv
import functools
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pytest
import xmlschema

from fmu_manipulation_toolbox.checker import OperationGenericCheck
from fmu_manipulation_toolbox.operations import (
    FMU,
    OperationAbstract,
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

from _helpers.assertions import assert_equivalent_xml, assert_identical_files, canonical_xml

pytestmark = [pytest.mark.integration]

DATA_DIR = Path(__file__).parent.parent / "data"
REFS_DIR = DATA_DIR / "refactoring"
XSD_DIR = Path(__file__).parent.parent.parent / "fmu_manipulation_toolbox" / "resources"

FMU_FILES = sorted(path for path in DATA_DIR.rglob("*.fmu") if REFS_DIR not in path.parents)


def _fmu_id(path: Path) -> str:
    return path.relative_to(DATA_DIR).with_suffix("").as_posix().replace("/", "__")


def _names(fmu_path: Path, tmp_path: Path) -> List[str]:
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
MODIFYING_CASES: Dict[str, Tuple[OperationFactory, Optional[List[str]]]] = {
    "noop": (lambda fmu, tmp: OperationAbstract(), None),
    "strip_top_level": (lambda fmu, tmp: OperationStripTopLevel(), None),
    "merge_top_level": (lambda fmu, tmp: OperationMergeTopLevel(), None),
    "trim_until_dot": (lambda fmu, tmp: OperationTrimUntil("."), None),
    "remove_regexp": (lambda fmu, tmp: OperationRemoveRegexp("[a-mA-M]"), None),
    "keep_only_regexp": (lambda fmu, tmp: OperationKeepOnlyRegexp("[a-mA-M]"), None),
    "remove_all_outputs": (lambda fmu, tmp: OperationRemoveRegexp("."), ["output"]),
    "rename_from_csv": (_rename_from_csv, None),
}

#: Operations that must not change the meaning of the descriptor.
READ_ONLY_CASES: Dict[str, OperationFactory] = {
    "summary": lambda fmu, tmp: OperationSummary(),
    "save_names_to_csv": lambda fmu, tmp: OperationSaveNamesToCSV(str(tmp / "dump.csv")),
    "generic_check": lambda fmu, tmp: OperationGenericCheck(),
    "remove_sources": lambda fmu, tmp: OperationRemoveSources(),
}


def _apply(fmu_path: Path, tmp_path: Path, factory: OperationFactory,
           apply_on: Optional[List[str]] = None) -> FMU:
    fmu = FMU(str(fmu_path))
    fmu.apply_operation(factory(fmu_path, tmp_path), apply_on)
    return fmu


def _check_reference(ref_filename: Path, update_refs: bool, write: Callable[[Path], None],
                     compare: Callable[[Path], None]) -> None:
    if update_refs:
        ref_filename.parent.mkdir(parents=True, exist_ok=True)
        write(ref_filename)
    elif not ref_filename.exists():
        pytest.fail(f"Missing reference {ref_filename}. Generate it with --update-refs.")
    else:
        compare(ref_filename)


def _check_xml_reference(fmu: FMU, ref_filename: Path, update_refs: bool) -> None:
    _check_reference(
        ref_filename, update_refs,
        write=lambda ref: ref.write_text(canonical_xml(fmu.descriptor_filename) + "\n", encoding="utf-8"),
        compare=lambda ref: assert_equivalent_xml(ref, fmu.descriptor_filename))


@pytest.mark.parametrize("case", MODIFYING_CASES)
@pytest.mark.parametrize("fmu_path", FMU_FILES, ids=_fmu_id)
def test_modifying_operation(fmu_path, case, tmp_path, update_refs):
    factory, apply_on = MODIFYING_CASES[case]
    fmu = _apply(fmu_path, tmp_path, factory, apply_on)
    _check_xml_reference(fmu, REFS_DIR / _fmu_id(fmu_path) / f"{case}.xml", update_refs)


@pytest.mark.parametrize("case", READ_ONLY_CASES)
@pytest.mark.parametrize("fmu_path", FMU_FILES, ids=_fmu_id)
def test_read_only_operation(fmu_path, case, tmp_path):
    ref_filename = REFS_DIR / _fmu_id(fmu_path) / "noop.xml"
    if not ref_filename.exists():
        pytest.skip(f"{ref_filename} is generated by test_modifying_operation[noop]")
    fmu = _apply(fmu_path, tmp_path, READ_ONLY_CASES[case])
    assert_equivalent_xml(ref_filename, fmu.descriptor_filename)


@pytest.mark.parametrize("fmu_path", FMU_FILES, ids=_fmu_id)
def test_names_csv(fmu_path, tmp_path, update_refs):
    csv_filename = tmp_path / "names.csv"
    _apply(fmu_path, tmp_path, lambda fmu, tmp: OperationSaveNamesToCSV(str(csv_filename)))
    _check_reference(REFS_DIR / _fmu_id(fmu_path) / "names.csv", update_refs,
                     write=lambda ref: ref.write_bytes(csv_filename.read_bytes()),
                     compare=lambda ref: assert_identical_files(ref, csv_filename))


def _normalized_summary(records: List[logging.LogRecord]) -> List[str]:
    """Summary report without the volatile lines; lists are sorted because some
    of them come from `os.listdir`, whose order depends on the file system."""
    volatile = ("| fmu filename = ", "| temporary directory = ")
    lines = [record.getMessage() for record in records if not record.getMessage().startswith(volatile)]
    normalized: List[str] = []
    bullets: List[str] = []
    for line in lines + [""]:
        if line.startswith("|  - "):
            bullets.append(line)
        else:
            normalized.extend(sorted(bullets))
            bullets = []
            normalized.append(line)
    return normalized[:-1]


@pytest.mark.parametrize("fmu_path", FMU_FILES, ids=_fmu_id)
def test_summary(fmu_path, tmp_path, update_refs, caplog):
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        _apply(fmu_path, tmp_path, lambda fmu, tmp: OperationSummary())
    summary = _normalized_summary([r for r in caplog.records if r.name == "fmu_manipulation_toolbox"])
    _check_reference(REFS_DIR / _fmu_id(fmu_path) / "summary.txt", update_refs,
                     write=lambda ref: ref.write_text("\n".join(summary) + "\n", encoding="utf-8"),
                     compare=lambda ref: _assert_lines(ref.read_text(encoding="utf-8").splitlines(), summary))


def _assert_lines(expected: List[str], actual: List[str]) -> None:
    assert actual == expected


# --------------------------------------------------------------------------- #
#                              XSD validity                                    #
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=None)
def _schema(fmi_version: str) -> xmlschema.XMLSchema:
    return xmlschema.XMLSchema(str(XSD_DIR / f"fmi-{fmi_version}" / f"fmi{fmi_version[0]}ModelDescription.xsd"))


def _xsd_errors(descriptor_filename: str, fmi_version: str) -> List[str]:
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
    fmu = _apply(fmu_path, tmp_path, factory, apply_on)
    if not len(ET.parse(fmu.descriptor_filename).getroot().find("ModelVariables")):
        pytest.xfail("D10: removing every variable leaves an empty <ModelVariables>, which the XSD forbids")
    assert _xsd_errors(fmu.descriptor_filename, fmi_version) == []
