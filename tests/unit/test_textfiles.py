"""Text files are UTF-8 on every platform (`textfiles.py`).

Opening a text file without an explicit encoding uses cp1252 on most Windows
installations: an assembly CSV with a non-ASCII name, written in UTF-8, was
misread there (seen on the Windows CI with `test_container_xml.py`). These
tests pin the rule down; the round trips below do not depend on the locale of
the machine that runs them.
"""
import csv
import logging
import zipfile

import pytest

from fmu_manipulation_toolbox.operations import FMU, OperationRenameFromCSV, OperationSaveNamesToCSV
from fmu_manipulation_toolbox.textfiles import open_text, read_text

pytestmark = [pytest.mark.unit]

TEXT = "name;débit µ ≤ 1\n"


def test_utf8_is_read(tmp_path):
    path = tmp_path / "f.csv"
    path.write_bytes(TEXT.encode("utf-8"))
    assert read_text(path) == TEXT


def test_utf8_with_bom_is_read(tmp_path):
    """Excel adds a byte order mark when it saves a CSV as UTF-8."""
    path = tmp_path / "f.csv"
    path.write_bytes(TEXT.encode("utf-8-sig"))
    assert read_text(path) == TEXT


def test_non_utf8_file_is_read_with_a_warning(tmp_path, caplog):
    path = tmp_path / "f.csv"
    path.write_bytes("name;débit\n".encode("cp1252"))
    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        assert read_text(path).startswith("name;d")
    assert "is not encoded in UTF-8" in caplog.text


def test_open_text_keeps_line_endings_for_csv(tmp_path):
    path = tmp_path / "f.csv"
    path.write_bytes('a;"x\r\ny"\r\nb;z\r\n'.encode("utf-8"))
    assert list(csv.reader(open_text(path), delimiter=";")) == [["a", "x\r\ny"], ["b", "z"]]


DESCRIPTOR = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{x}">
  <CoSimulation modelIdentifier="m"/>
  <ModelVariables>
    <Float64 name="débit" valueReference="1" causality="output"/>
    <Float64 name="µ" valueReference="2" causality="output"/>
  </ModelVariables>
  <ModelStructure><Output valueReference="1"/><Output valueReference="2"/></ModelStructure>
</fmiModelDescription>
"""


def test_names_csv_round_trip_with_non_ascii_names(tmp_path):
    """Dump the names, rename them in the CSV, apply the CSV: the non-ASCII names must be found again."""
    fmu_filename = tmp_path / "m.fmu"
    with zipfile.ZipFile(fmu_filename, "w") as fmu:
        fmu.writestr("modelDescription.xml", DESCRIPTOR)
    dump = tmp_path / "names.csv"
    with FMU(str(fmu_filename)) as fmu:
        fmu.apply_operation(OperationSaveNamesToCSV(str(dump)))
    assert "débit" in dump.read_bytes().decode("utf-8")  # written in UTF-8, whatever the platform

    rename = tmp_path / "rename.csv"
    rename.write_bytes("débit;flow\nµ;mu\n".encode("utf-8-sig"))
    with FMU(str(fmu_filename)) as fmu:
        fmu.apply_operation(OperationRenameFromCSV(str(rename)))
        assert [v.get("name") for v in fmu.model_description.variables()] == ["flow", "mu"]
