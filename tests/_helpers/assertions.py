"""File-comparison and FMU-introspection assertions shared by the test suite.

The file comparisons normalise trailing blank lines and line endings so that a
spurious final newline does not trigger a failure, while still detecting a
genuine difference in the number of meaningful lines.
"""
import csv
import difflib
import hashlib
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from collections.abc import Iterable

from fmu_manipulation_toolbox.operations import FMU, OperationSaveNamesToCSV

PathLike = str | Path


def _read_lines(path: PathLike) -> list[str]:
    """Read a text file (universal newlines) into a list of stripped lines.

    Trailing blank lines are dropped so that a missing/extra final newline is
    not reported as a mismatch.
    """
    with open(path, mode="rt", newline=None) as f:
        lines = [line.strip() for line in f]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def assert_identical_files(filename1: PathLike, filename2: PathLike) -> None:
    """Assert two text files have the same content (whitespace-normalised)."""
    assert Path(filename1).exists(), f"{filename1} does not exist"
    assert Path(filename2).exists(), f"{filename2} does not exist"

    lines1 = _read_lines(filename1)
    lines2 = _read_lines(filename2)

    assert len(lines1) == len(lines2), (
        f"files {filename1} and {filename2} mismatch: "
        f"{len(lines1)} vs {len(lines2)} lines"
    )
    for lineno, (lineA, lineB) in enumerate(zip(lines1, lines2), start=1):
        assert lineA == lineB, (
            f"files {filename1} and {filename2} mismatch at line {lineno}:\n"
            f"{lineA}\n"
            f"vs.\n\n"
            f"{lineB}"
        )


def assert_equivalent_csv(filename1: PathLike, filename2: PathLike, real_columns: Iterable[str] = ("time",),
                          rel_tol: float = 1e-12) -> None:
    """Assert two CSV files (e.g. datalogs) have the same header and rows. The values of `real_columns` are compared
    with the relative tolerance `rel_tol`: written with every digit, their last bit depends on the platform (fused
    multiply-add or not); every other field must be identical."""
    assert Path(filename1).exists(), f"{filename1} does not exist"
    assert Path(filename2).exists(), f"{filename2} does not exist"

    with open(filename1, newline="") as file1, open(filename2, newline="") as file2:
        rows1 = [row for row in csv.reader(file1) if row]
        rows2 = [row for row in csv.reader(file2) if row]

    assert rows1 and rows2 and rows1[0] == rows2[0], f"files {filename1} and {filename2} have different headers"
    assert len(rows1) == len(rows2), (
        f"files {filename1} and {filename2} mismatch: {len(rows1)} vs {len(rows2)} rows"
    )
    reals = {index for index, name in enumerate(rows1[0]) if name in set(real_columns)}
    for lineno, (row1, row2) in enumerate(zip(rows1[1:], rows2[1:]), start=2):
        assert len(row1) == len(row2), f"files {filename1} and {filename2} mismatch at line {lineno}"
        for index, (value1, value2) in enumerate(zip(row1, row2)):
            same = (math.isclose(float(value1), float(value2), rel_tol=rel_tol, abs_tol=rel_tol)
                    if index in reals else value1 == value2)
            assert same, (
                f"files {filename1} and {filename2} mismatch at line {lineno}, column '{rows1[0][index]}': "
                f"{value1} vs. {value2}"
            )


#: Attributes of `modelDescription.xml` that change on every container build, or with the version of the
#: toolbox (`generationTool` carries it: "FMUContainer-<version>").
VOLATILE_XML_ATTRIBUTES = ("guid", "author", "generationDateAndTime", "instantiationToken", "generationTool")


def canonical_xml(source: PathLike | bytes, *, ignore_attributes: Iterable[str] = (),
                  with_comments: bool = False) -> str:
    """Return a canonical, line-oriented form of an XML document.

    Whitespace-only text is dropped, the remaining text is stripped, the tree is
    re-indented and then serialised with C14N 2.0 (sorted attributes, normalised
    quoting and empty elements). Two documents with the same meaning thus give
    the same string whatever the serialiser that produced them, and a mismatch
    can be reported as a readable line diff.

    Args:
        source: Path to the XML file, or its raw bytes.
        ignore_attributes: Attribute names removed from every element before
            comparison (e.g. `VOLATILE_XML_ATTRIBUTES`).
        with_comments: Keep comments (they are dropped otherwise).
    """
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=with_comments))
    if isinstance(source, bytes):
        parser.feed(source)
        root = parser.close()
    else:
        root = ET.parse(source, parser=parser).getroot()

    for element in root.iter():
        for name in ignore_attributes:
            element.attrib.pop(name, None)
        element.text = element.text.strip() or None if element.text else None
        element.tail = element.tail.strip() or None if element.tail else None
    ET.indent(root)
    return ET.canonicalize(ET.tostring(root, encoding="unicode"), with_comments=with_comments)


def assert_equivalent_xml(filename1: PathLike | bytes, filename2: PathLike | bytes, *,
                          ignore_attributes: Iterable[str] = (), with_comments: bool = False) -> None:
    """Assert two XML documents are equivalent once canonicalised.

    Unlike `assert_identical_files`, formatting differences (indentation,
    attribute order, `<X></X>` vs `<X/>`, quoting, XML declaration) are not
    reported: only the meaning of the documents is compared. See `canonical_xml`.
    """
    canonical1 = canonical_xml(filename1, ignore_attributes=ignore_attributes, with_comments=with_comments)
    canonical2 = canonical_xml(filename2, ignore_attributes=ignore_attributes, with_comments=with_comments)
    if canonical1 != canonical2:
        name1 = "<bytes>" if isinstance(filename1, bytes) else str(filename1)
        name2 = "<bytes>" if isinstance(filename2, bytes) else str(filename2)
        diff = "\n".join(difflib.unified_diff(canonical1.splitlines(), canonical2.splitlines(),
                                              fromfile=name1, tofile=name2, lineterm=""))
        raise AssertionError(f"XML documents {name1} and {name2} are not equivalent:\n{diff}")


def assert_md5(filename: PathLike, expected_md5: str) -> None:
    hash_md5 = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    assert hash_md5.hexdigest() == expected_md5, (
        f"Wrong md5 hash for {filename}. "
        f"Expected {expected_md5} but got {hash_md5.hexdigest()}"
    )


def assert_file_exist(path: PathLike) -> None:
    assert Path(path).exists(), f"{path} does not exist"


def assert_names_match_ref(fmu_filename: PathLike) -> None:
    """Dump the FMU variable names to CSV and compare to the REF-* reference.

    Note: this helper has a side effect (it writes ``<stem>.csv``); it is kept
    here for convenience as it is shared by the operations tests.
    """
    fmu = FMU(fmu_filename)
    csv_filename = Path(fmu_filename).with_suffix(".csv")
    ref_filename = csv_filename.with_stem("REF-" + csv_filename.stem)
    fmu.apply_operation(OperationSaveNamesToCSV(csv_filename))
    assert_identical_files(ref_filename, csv_filename)

