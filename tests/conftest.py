"""Shared pytest configuration and fixtures for the FMU Manipulation Toolbox test suite.

Fixtures defined here are available to every test module. The key idea is that
reference data lives under ``tests/data/<area>/`` (read-only) and every test runs
in an isolated copy inside ``tmp_path`` so the source tree is never polluted.
"""
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

# Ensure Qt runs headless (offscreen) for the GUI tests, before any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TESTS_ROOT = Path(__file__).parent
DATA_DIR = TESTS_ROOT / "data"
# Working directories for the tests. Each test gets its own sub-directory here
# (named after the test node id) so that generated artefacts are easy to inspect
# after a run. The whole tree is wiped at the start of every session.
TMP_DIR = TESTS_ROOT / "tmp"


def _sanitize(name: str) -> str:
    """Turn a pytest node id into a filesystem-friendly directory name."""
    return re.sub(r"[^\w.\-]+", "_", name).strip("_")


# --------------------------------------------------------------------------- #
#                                 Fixtures                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def data_dir() -> Path:
    """Absolute path to the read-only reference data directory."""
    return DATA_DIR


@pytest.fixture
def area_dir(request, monkeypatch) -> Path:
    """Copy ``tests/data/<area>`` into ``tests/tmp/<test>`` and chdir into it.

    The area name is taken from the ``@pytest.mark.area("<name>")`` marker on
    the test. Each test gets its own directory under ``tests/tmp/`` (named after
    the test node id), so outputs produced by the test are easy to inspect after
    the run while the committed reference data stays untouched. The ``tests/tmp``
    tree is wiped at the start of every session.
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

    # Per-test working directory, kept after the run to ease debugging.
    base = TMP_DIR / _sanitize(request.node.nodeid)
    dst = base / area
    if base.exists():
        shutil.rmtree(base)
    dst.parent.mkdir(parents=True, exist_ok=True)
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
#                         Session setup / teardown                             #
# --------------------------------------------------------------------------- #
def pytest_sessionstart(session):
    """Wipe the ``tests/tmp`` working tree so each run starts from a clean slate."""
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR, ignore_errors=True)


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


