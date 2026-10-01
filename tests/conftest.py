"""Shared pytest configuration and fixtures for the FMU Manipulation Toolbox test suite.

Fixtures defined here are available to every test module. The key idea is that
reference data lives under ``tests/data/<area>/`` (read-only) and every test runs
in an isolated copy inside ``tmp_path`` so the source tree is never polluted.
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

# Ensure Qt runs headless (offscreen) for the GUI tests, before any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TESTS_ROOT = Path(__file__).parent
DATA_DIR = TESTS_ROOT / "data"


# --------------------------------------------------------------------------- #
#                                 Fixtures                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def data_dir() -> Path:
    """Absolute path to the read-only reference data directory."""
    return DATA_DIR


@pytest.fixture
def area_dir(request, tmp_path, monkeypatch) -> Path:
    """Copy ``tests/data/<area>`` into ``tmp_path`` and chdir into it.

    The area name is taken from the ``@pytest.mark.area("<name>")`` marker on
    the test. Outputs produced by the test therefore land in ``tmp_path`` and
    the committed reference data stays untouched.
    """
    marker = request.node.get_closest_marker("area")
    if marker is None or not marker.args:
        raise RuntimeError(
            f"{request.node.name}: the `area_dir` fixture requires a "
            f"`@pytest.mark.area(\"<name>\")` marker."
        )
    area = marker.args[0]
    src = DATA_DIR / area
    if not src.is_dir():
        raise RuntimeError(f"Reference data directory not found: {src}")

    dst = tmp_path / area
    shutil.copytree(src, dst)
    monkeypatch.chdir(dst)
    return dst


@pytest.fixture(autouse=True)
def clean_argv():
    """Save and restore ``sys.argv`` around every test (CLI tests mutate it)."""
    saved = sys.argv
    try:
        yield
    finally:
        sys.argv = saved


# --------------------------------------------------------------------------- #
#                         Environment-based skipping                           #
# --------------------------------------------------------------------------- #
def _has_fmpy() -> bool:
    try:
        import fmpy  # noqa: F401
        return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    """Attach explicit skips for markers whose prerequisites are unavailable."""
    is_win32 = sys.platform == "win32"
    has_fmpy = _has_fmpy()

    skip_win = pytest.mark.skip(reason="windows_only: runs only on win32")
    skip_fmpy = pytest.mark.skip(reason="needs_fmpy: the `fmpy` package is not installed")

    for item in items:
        if "windows_only" in item.keywords and not is_win32:
            item.add_marker(skip_win)
        if "needs_fmpy" in item.keywords and not has_fmpy:
            item.add_marker(skip_fmpy)


