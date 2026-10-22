"""Unit tests for ``Assembly`` input-validation / parsing error paths.

The assembly layer must reject malformed or unsupported descriptions with an
explicit ``AssemblyError`` carrying a stable, human-readable reason — never a
leaking low-level exception and never a silent success. These tests build tiny
descriptor files in ``tmp_path`` and assert on the exception type plus a stable
fragment of its message.
"""

import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError

pytestmark = [pytest.mark.unit]


def test_invalid_fmu_directory_raises(tmp_path):
    missing = tmp_path / "no_such_dir"
    with pytest.raises(AssemblyError) as exc:
        Assembly("whatever.json", fmu_directory=missing)
    assert "FMU directory is not valid" in str(exc.value)


def test_unsupported_description_extension_raises(tmp_path):
    (tmp_path / "desc.txt").write_text("rule;from_fmu;from_port;to_fmu;to_port\n")
    with pytest.raises(AssemblyError) as exc:
        Assembly("desc.txt", fmu_directory=tmp_path)
    assert "Not supported file format" in str(exc.value)


def test_read_without_filename_raises(tmp_path):
    assembly = Assembly(fmu_directory=tmp_path)  # no description → nothing read
    with pytest.raises(AssemblyError) as exc:
        assembly.read()
    assert "Filename should be specified" in str(exc.value)


def test_csv_with_bad_header_raises(tmp_path):
    (tmp_path / "bad.csv").write_text("not;the;expected;header;columns\n")
    with pytest.raises(AssemblyError) as exc:
        Assembly("bad.csv", fmu_directory=tmp_path)
    assert "Header" in str(exc.value)


def test_malformed_json_raises(tmp_path):
    (tmp_path / "bad.json").write_text("{ this is not valid json ")
    with pytest.raises(AssemblyError) as exc:
        Assembly("bad.json", fmu_directory=tmp_path)
    assert "Cannot read json" in str(exc.value)


def test_write_with_unsupported_extension_raises(tmp_path):
    assembly = Assembly(fmu_directory=tmp_path)
    with pytest.raises(AssemblyError) as exc:
        assembly.write("output.txt")
    assert "format unsupported" in str(exc.value)

