"""Unit tests for error handling and pure port-name transforms in ``operations``.

These protect the *observable* contract of the lightweight operations without
needing a full FMU: invalid inputs must raise the documented, explicit
exceptions (never a silent failure or a leaking low-level error), and the
string-rewriting operations must transform port names exactly as documented.

A minimal on-disk FMU (a zip archive) is built in ``tmp_path`` only where an
actual archive is required; the port transforms are exercised directly on an
``FMUPort`` instance, which is the smallest representative fixture.
"""
import zipfile

import pytest

from fmu_manipulation_toolbox.operations import (
    FMU,
    FMUError,
    FMUPort,
    OperationError,
    OperationRenameFromCSV,
    OperationStripTopLevel,
    OperationMergeTopLevel,
    OperationTrimUntil,
)

pytestmark = [pytest.mark.unit]


def _make_port(name: str) -> FMUPort:
    """Smallest representative port carrying a single ``name`` attribute."""
    port = FMUPort()
    port.push_attrs({"name": name})
    return port


# --------------------------------------------------------------------------- #
#                         FMU archive validation                               #
# --------------------------------------------------------------------------- #
def test_fmu_missing_file_raises_fmuerror(tmp_path):
    with pytest.raises(FMUError) as exc:
        FMU(str(tmp_path / "does-not-exist.fmu"))
    assert "does not exist" in str(exc.value)


def test_fmu_without_descriptor_raises_fmuerror(tmp_path):
    # A valid zip that is not a valid FMU (no modelDescription.xml at the root).
    broken = tmp_path / "broken.fmu"
    with zipfile.ZipFile(broken, "w") as zf:
        zf.writestr("some-other-file.txt", "not a descriptor")

    with pytest.raises(FMUError) as exc:
        FMU(str(broken))
    assert "is not valid" in str(exc.value)


# --------------------------------------------------------------------------- #
#                         OperationRenameFromCSV                                #
# --------------------------------------------------------------------------- #
def test_rename_from_csv_missing_file_raises(tmp_path):
    with pytest.raises(OperationError) as exc:
        OperationRenameFromCSV(str(tmp_path / "absent.csv"))
    assert "not found" in str(exc.value)


def test_rename_from_csv_single_column_raises(tmp_path):
    # A CSV with a single column cannot express a rename mapping and must be
    # reported with the documented "two columns" OperationError (previously a
    # raw IndexError leaked out).
    csv_file = tmp_path / "one-column.csv"
    csv_file.write_text("only_one_column\nanother_row\n")

    with pytest.raises(OperationError) as exc:
        OperationRenameFromCSV(str(csv_file))
    assert "two columns" in str(exc.value)


# --------------------------------------------------------------------------- #
#                         Port-name transforms                                 #
# --------------------------------------------------------------------------- #
def test_strip_top_level_removes_first_segment():
    port = _make_port("Bus1.signal_name")
    assert OperationStripTopLevel().port_attrs(port) == 0
    assert port["name"] == "signal_name"


def test_strip_top_level_without_dot_is_unchanged():
    port = _make_port("signal_name")
    OperationStripTopLevel().port_attrs(port)
    assert port["name"] == "signal_name"


def test_merge_top_level_replaces_only_first_dot():
    port = _make_port("Bus1.sub.signal")
    assert OperationMergeTopLevel().port_attrs(port) == 0
    assert port["name"] == "Bus1_sub.signal"


def test_trim_until_keeps_text_after_separator():
    # Documented behaviour: "prefix__signal" trimmed on "__" yields "signal".
    port = _make_port("prefix__signal")
    assert OperationTrimUntil("__").port_attrs(port) == 0
    assert port["name"] == "signal"


def test_trim_until_without_separator_leaves_name_unchanged():
    port = _make_port("signal")
    OperationTrimUntil("__").port_attrs(port)
    assert port["name"] == "signal"

