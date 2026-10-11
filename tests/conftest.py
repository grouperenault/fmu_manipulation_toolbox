"""Shared pytest configuration and fixtures for the FMU Manipulation Toolbox test suite.

Fixtures defined here are available to every test module. The key idea is that
reference data lives under ``tests/data/<area>/`` (read-only) and every test runs
in an isolated copy inside ``tmp_path`` so the source tree is never polluted.
"""
import os
import platform
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


def _resources_dir() -> Path:
    """Absolute path to the package's ``resources/`` directory (where the
    optional compiled binaries are shipped)."""
    import fmu_manipulation_toolbox as pkg
    return Path(pkg.__file__).parent / "resources"


def _has_container_binary() -> bool:
    """True when the compiled container binary for the current OS is present.

    These binaries are built and shipped by CI (see ``.gitignore``); a plain
    source checkout may not contain them, in which case ``needs_container``
    tests cannot run.
    """
    binary = {
        "Windows": "win64/container.dll",
        "Linux": "linux64/container.so",
        "Darwin": "darwin64/container.dylib",
    }.get(platform.system())
    return bool(binary) and (_resources_dir() / binary).is_file()


def _has_remoting_binaries() -> bool:
    """True when the pre-built Windows remoting binaries are present.

    Remoting bridges a win32 FMU to win64 (and vice-versa) and therefore relies
    on the ``client_sm.dll`` / ``server_sm.exe`` pair shipped for both Windows
    bitnesses in ``resources/``.
    """
    res = _resources_dir()
    required = ("win32/client_sm.dll", "win32/server_sm.exe",
                "win64/client_sm.dll", "win64/server_sm.exe")
    return all((res / rel).is_file() for rel in required)


def pytest_collection_modifyitems(config, items):
    """Attach explicit skips for markers whose prerequisites are unavailable."""
    is_win32 = sys.platform == "win32"
    has_fmpy = _has_fmpy()
    has_container = _has_container_binary()
    has_remoting = _has_remoting_binaries()

    skip_win = pytest.mark.skip(reason="windows_only: runs only on win32")
    skip_fmpy = pytest.mark.skip(reason="needs_fmpy: the `fmpy` package is not installed")
    skip_container = pytest.mark.skip(
        reason="needs_container: the compiled container binary is not available in resources/")
    skip_remoting = pytest.mark.skip(
        reason="needs_remoting: the compiled remoting binaries are not available in resources/")

    for item in items:
        if "windows_only" in item.keywords and not is_win32:
            item.add_marker(skip_win)
        if "needs_fmpy" in item.keywords and not has_fmpy:
            item.add_marker(skip_fmpy)
        if "needs_container" in item.keywords and not has_container:
            item.add_marker(skip_container)
        if "needs_remoting" in item.keywords and not has_remoting:
            item.add_marker(skip_remoting)


