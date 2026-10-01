"""File-comparison and FMU-introspection assertions shared by the test suite.

The file comparisons normalise trailing blank lines and line endings so that a
spurious final newline does not trigger a failure, while still detecting a
genuine difference in the number of meaningful lines (the legacy ``zip``-based
implementation silently ignored such length differences).
"""
import hashlib
from pathlib import Path
from typing import List, Union

from fmu_manipulation_toolbox.operations import FMU, OperationSaveNamesToCSV

PathLike = Union[str, Path]


def _read_lines(path: PathLike, *, strip: bool) -> List[str]:
    """Read a text file (universal newlines) into a list of lines.

    Each line is either fully stripped (``strip=True``) or only has its trailing
    newline removed (``strip=False``). Trailing blank lines are dropped so that a
    missing/extra final newline is not reported as a mismatch.
    """
    with open(path, mode="rt", newline=None) as f:
        lines = [line.strip() if strip else line.rstrip("\n") for line in f]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def assert_identical_files(filename1: PathLike, filename2: PathLike) -> None:
    """Assert two text files have the same content (whitespace-normalised)."""
    assert Path(filename1).exists(), f"{filename1} does not exist"
    assert Path(filename2).exists(), f"{filename2} does not exist"

    lines1 = _read_lines(filename1, strip=True)
    lines2 = _read_lines(filename2, strip=True)

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


def assert_identical_files_but_guid(filename1: PathLike, filename2: PathLike) -> None:
    """Assert two text files are identical, ignoring lines that carry volatile
    metadata (GUID, author, generation date, instantiation token)."""
    assert Path(filename1).exists(), f"{filename1} does not exist"
    assert Path(filename2).exists(), f"{filename2} does not exist"

    keywords = ("guid", "author", "generationDateAndTime", "instantiationToken")
    lines1 = _read_lines(filename1, strip=False)
    lines2 = _read_lines(filename2, strip=False)

    assert len(lines1) == len(lines2), (
        f"files {filename1} and {filename2} mismatch: "
        f"{len(lines1)} vs {len(lines2)} lines"
    )
    for lineno, (lineA, lineB) in enumerate(zip(lines1, lines2), start=1):
        if any(keyword in lineA for keyword in keywords):
            continue
        assert lineA == lineB, (
            f"files {filename1} and {filename2} mismatch at line {lineno}:\n"
            f"{lineA}\n"
            f"vs.\n\n"
            f"{lineB}"
        )


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

