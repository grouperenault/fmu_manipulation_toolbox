try:
    # Written by setuptools-scm from the git tags when the package is built or installed.
    from fmu_manipulation_toolbox._version import version as __version__
except ImportError:
    try:
        from importlib.metadata import PackageNotFoundError, version as _distribution_version
        __version__ = _distribution_version("fmu_manipulation_toolbox")
    except (ImportError, PackageNotFoundError):
        # Source tree that was neither built nor installed (e.g. the test suite).
        __version__ = "0.0.dev0"

__author__ = "Nicolas.LAURENT@Renault.com"
__copyright__ = "Copyright 2023-2026, Renault SAS"
__license__ = """This code is released under the 2-Clause BSD license. 
See https://github.com/grouperenault/fmu_manipulation_toolbox/blob/main/LICENSE.txt"""
