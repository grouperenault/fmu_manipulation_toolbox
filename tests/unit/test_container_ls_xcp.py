"""Containers of FMUs of FMI-LS-XCP.

The stub FMUs of `tests/data/ls-xcp` (descriptor, manifest and A2L files, without binaries) are enough to build the
container: the runtime is checked by the native tests (`container/tests/test_xcp_container.c`).
"""
from pathlib import Path

import pytest

from _helpers.archive import zip_fmu
from fmu_manipulation_toolbox.container import FMUContainer

pytestmark = [pytest.mark.unit, pytest.mark.lsxcp]

DATA_DIR = Path(__file__).parent.parent / "data" / "ls-xcp"


@pytest.fixture
def xcp_dir(tmp_path, monkeypatch) -> Path:
    for version in (2, 3):
        zip_fmu(DATA_DIR / f"stub_xcp_fmi{version}", tmp_path / f"stub_xcp_fmi{version}.fmu")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _container_txt(container: FMUContainer, name: str = "container") -> list[str]:
    container.make_fmu(f"{name}.fmu", step_size=0.1, debug=True)
    return Path(f"{name}/resources/container.txt").read_text().splitlines()


def _start_values(lines: list[str], type_name: str) -> list[str]:
    header = next(i for i, line in enumerate(lines) if line.startswith("# Start values of") and
                  line.endswith(f"- {type_name}: <FMU_VR> <DIM> <RESET> <VALUE>"))
    nb = int(lines[header + 1].split()[0])
    return lines[header + 2:header + 2 + nb]


def test_structural_parameter_is_set_in_configuration_mode(xcp_dir):
    container = FMUContainer("xcp", xcp_dir, fmi_version=3)
    container.get_fmu("stub_xcp_fmi3.fmu")
    container.add_start_value("stub_xcp_fmi3.fmu", "XCP.TCP.Port", "6000")
    lines = _container_txt(container)
    assert "stub_xcp_fmi3.fmu 3 0 1" in lines           # <has_configuration_mode>
    assert _start_values(lines, "uinteger16") == ["2 1 2 6000"]


def test_parameter_has_no_configuration_mode(xcp_dir):
    container = FMUContainer("xcp", xcp_dir)
    container.get_fmu("stub_xcp_fmi2.fmu")
    container.add_start_value("stub_xcp_fmi2.fmu", "XCP.TCP.Port", "6002")
    lines = _container_txt(container)
    assert "stub_xcp_fmi2.fmu 2 0 0" in lines
    assert _start_values(lines, "integer32") == ["2 1 0 6002"]
