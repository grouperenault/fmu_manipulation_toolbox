"""Unit tests for FMU operations (modelDescription.xml manipulations).

Each test runs in an isolated copy
of ``tests/data/operations`` (see the ``area_dir`` fixture) so generated files
never pollute the source tree.
"""
import logging
import zipfile

import pytest

from fmu_manipulation_toolbox.operations import (
    FMU,
    OperationStripTopLevel,
    OperationRenameFromCSV,
    OperationRemoveRegexp,
    OperationRemoveSources,
    OperationKeepOnlyRegexp,
    OperationSummary,
)

from _helpers.assertions import assert_names_match_ref

pytestmark = [pytest.mark.unit, pytest.mark.area("operations")]


def _apply_and_match_ref(target_fmu, operation):
    """Apply an operation on the reference FMU, repack it, and compare the
    dumped variable names against the committed REF-* file."""
    fmu = FMU("bouncing_ball.fmu")
    fmu.apply_operation(operation)
    fmu.repack(target_fmu)
    assert_names_match_ref(target_fmu)


def test_strip_top_level(area_dir):
    _apply_and_match_ref("bouncing_ball-no-tl.fmu", OperationStripTopLevel())


def test_save_names_to_csv(area_dir):
    assert_names_match_ref("bouncing_ball.fmu")


def test_rename_from_csv(area_dir):
    _apply_and_match_ref("bouncing_ball-renamed.fmu",
                         OperationRenameFromCSV("bouncing_ball-modified.csv"))


def test_remove_regexp(area_dir):
    _apply_and_match_ref("bouncing_ball-removed.fmu", OperationRemoveRegexp("e"))


def test_keep_only_regexp(area_dir):
    _apply_and_match_ref("bouncing_ball-keeponly.fmu", OperationKeepOnlyRegexp("e"))


# --------------------------------------------------------------------------- #
#                  summary and sources, on a hand-built FMU                    #
# --------------------------------------------------------------------------- #
DESCRIPTOR = """<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="3.0" modelName="m" instantiationToken="{8c4e810f-3df3-4a00-8276-176fa3c9f000}">
  <CoSimulation modelIdentifier="m"/>
  <ModelVariables>
    <Float64 name="CanChannel.Rx_Data" valueReference="1" causality="input" start="0"/>
  </ModelVariables>
  <ModelStructure/>
</fmiModelDescription>
"""

TERMINALS = """<?xml version="1.0" encoding="UTF-8"?>
<fmiTerminalsAndIcons fmiVersion="3.0">
  <Terminals>
    <Terminal terminalKind="org.fmi-ls-bus.network-terminal" matchingRule="org.fmi-ls-bus.transceiver"
              name="CanChannel">
      <TerminalMemberVariable variableName="CanChannel.Rx_Data" memberName="Rx_Data"/>
    </Terminal>
  </Terminals>
</fmiTerminalsAndIcons>
"""


def _make_fmu(tmp_path, files: dict[str, str]) -> str:
    fmu_path = tmp_path / "model.fmu"
    with zipfile.ZipFile(fmu_path, "w") as fmu:
        fmu.writestr("modelDescription.xml", DESCRIPTOR)
        for name, content in files.items():
            fmu.writestr(name, content)
    return str(fmu_path)


def test_summary_lists_resources_extra_data_and_terminals(tmp_path, caplog):
    fmu = FMU(_make_fmu(tmp_path, {"resources/table.csv": "t;x\n",
                                   "extra/org.example/notes.txt": "notes",
                                   "terminalsAndIcons/terminalsAndIcons.xml": TERMINALS}))
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        fmu.apply_operation(OperationSummary())
    report = [record.getMessage() for record in caplog.records]
    assert report[report.index("| Embedded resources:") + 1] == "|  - table.csv"
    assert report[report.index("| Additional (meta-)data:") + 1] == "|  - org.example"
    assert report[report.index("| Terminals:") + 1].startswith("|  - CanChannel (1 signals")


def test_removing_absent_sources_is_reported(tmp_path, caplog):
    fmu = FMU(_make_fmu(tmp_path, {}))
    with caplog.at_level(logging.INFO, logger="fmu_manipulation_toolbox"):
        fmu.apply_operation(OperationRemoveSources())
    assert "This FMU does not embed sources." in caplog.text
