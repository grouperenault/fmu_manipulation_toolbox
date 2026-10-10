"""Computes the version of the package; every other metadata lives in pyproject.toml.

The version comes from the tag name (GITHUB_REF_NAME) when the CI builds a release. This file is meant to disappear
when the version is taken from the git tags by setuptools-scm (docs/local/packaging.md, phase 2).
"""
import os
import re
import sys
from setuptools import setup

# The `setuptools.build_meta` backend, used since pyproject.toml exists, does not put the project directory on the
# import path (the former legacy backend did).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fmu_manipulation_toolbox.version import __version__ as default_version  # noqa: E402

try:
    version = os.environ["GITHUB_REF_NAME"]
except Exception as e:
    print(f"Cannot get repository status: {e}. Defaulting to {default_version}")
    version = default_version

if not re.match(r"[A-Za-z]?\d+(\.\d)+", version):
    print(f"WARNING: Version {version} does not match standard. The publication will fail !")
    version = default_version

VERSION_FILE = "fmu_manipulation_toolbox/__version__.py"

# Create __version__.py
try:
    with open(VERSION_FILE, "wt") as file:
        print(f"'{version}'", file=file)
except Exception as e:
    print(f"Cannot create __version__.py: {e}")

try:
    setup(version=version)
finally:
    # Best-effort cleanup even if `setup()` raised (e.g. invalid arguments,
    # missing dependency): avoid leaving a stray __version__.py behind.
    try:
        os.remove(VERSION_FILE)
    except FileNotFoundError:
        pass
