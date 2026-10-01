"""File-comparison and FMU-introspection assertions shared by the test suite."""
import hashlib
from pathlib import Path

from fmu_manipulation_toolbox.operations import FMU, OperationSaveNamesToCSV


def assert_identical_files(filename1, filename2):
    assert Path(filename1).exists(), f"{filename1} does not exist"
    assert Path(filename2).exists(), f"{filename2} does not exist"
    with open(filename1, mode="rt", newline=None) as a, open(filename2, mode="rt", newline=None) as b:
        for lineA, lineB in zip(a, b):
            assert lineA.strip() == lineB.strip(), \
                f"file {filename1} and {filename2} missmatch (excl. GUID):\n" \
                f"{lineA.strip()}\n" \
                f"vs.\n\n" \
                f"{lineB.strip()}"


def assert_identical_files_but_guid(filename1, filename2):
    keywords = ("guid", "author", "generationDateAndTime", "instantiationToken")
    with open(filename1, mode="rt", newline=None) as a, open(filename2, mode="rt", newline=None) as b:
        for lineA, lineB in zip(a, b):
            skip = False
            for keyword in keywords:
                if keyword in lineA:
                    skip = True
                    break
            assert skip or lineA == lineB, \
                f"file {filename1} and {filename2} missmatch:\n" \
                f"{lineA}\n" \
                f"vs.\n\n" \
                f"{lineB}"


def assert_md5(filename, expected_md5):
    hash_md5 = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    print(f"{filename}: {expected_md5} {hash_md5.hexdigest()}")
    assert hash_md5.hexdigest() == expected_md5, \
        f"Wrong md5 hash for {filename}. Expected {expected_md5} but got {hash_md5.hexdigest()}"


def assert_file_exist(path):
    assert Path(path).exists()


def assert_names_match_ref(fmu_filename):
    """Dump the FMU variable names to CSV and compare to the REF-* reference."""
    fmu = FMU(fmu_filename)
    csv_filename = Path(fmu_filename).with_suffix(".csv")
    ref_filename = csv_filename.with_stem("REF-" + csv_filename.stem)
    operation = OperationSaveNamesToCSV(csv_filename)
    fmu.apply_operation(operation)
    assert_identical_files(ref_filename, csv_filename)

