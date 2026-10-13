"""Unit tests of `fmu_manipulation_toolbox.compiler` that do not need a C compiler.

They cover the name of the binaries directory of the host platform, the suffix of the shared library and the
reading of the build description (FMI 2.0 `<SourceFiles>`, FMI 3.0 `sources/buildDescription.xml`) of the
Reference FMUs of `tests/data/compile` (see `docs/local/compile_sources.md`).

The host platform is faked by patching `platform.system()` and `platform.machine()`.
"""
import re
import platform

import pytest

from _helpers.archive import rewrite_fmu

from fmu_manipulation_toolbox import compiler
from fmu_manipulation_toolbox.operations import FMU, OperationError

pytestmark = [pytest.mark.unit]


# --------------------------------------------------------------------------- #
#                               Host platform                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("system, machine, fmi_version, expected", [
    ("Darwin", "arm64", 2, "darwin64"),
    ("Darwin", "arm64", 3, "aarch64-darwin"),
    ("Darwin", "x86_64", 2, "darwin64"),
    ("Darwin", "x86_64", 3, "x86_64-darwin"),
    ("Linux", "x86_64", 2, "linux64"),
    ("Linux", "x86_64", 3, "x86_64-linux"),
    ("Linux", "aarch64", 3, "aarch64-linux"),
    ("Windows", "AMD64", 2, "win64"),
    ("Windows", "AMD64", 3, "x86_64-windows"),
])
def test_host_platform(monkeypatch, system, machine, fmi_version, expected):
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    assert compiler.SourceCompiler.host_platform(fmi_version) == expected


@pytest.mark.parametrize("system, suffix", [("Darwin", ".dylib"), ("Linux", ".so"), ("Windows", ".dll")])
def test_library_suffix(monkeypatch, system, suffix):
    monkeypatch.setattr(platform, "system", lambda: system)
    assert compiler.SourceCompiler.library_suffix() == suffix


# --------------------------------------------------------------------------- #
#                             Build description                                #
# --------------------------------------------------------------------------- #
def _configurations(fmu_filename):
    with FMU(str(fmu_filename)) as fmu:
        md = fmu.model_description
        source_compiler = compiler.SourceCompiler(fmu.tmp_directory, md.fmi_version)
        return source_compiler.build_configurations(md)


@pytest.mark.fmi2
def test_build_configurations_fmi2(data_dir):
    """Co-Simulation and Model Exchange share `BouncingBall` and `all.c`: a single configuration."""
    configurations = _configurations(data_dir / "compile" / "2.0" / "BouncingBall.fmu")
    assert len(configurations) == 1
    configuration = configurations[0]
    assert configuration.model_identifier == "BouncingBall"
    assert [path.name for path in configuration.source_files] == ["all.c"]
    assert all(path.parent.name == "sources" for path in configuration.source_files)


@pytest.mark.fmi3
def test_build_configurations_fmi3(data_dir):
    configurations = _configurations(data_dir / "compile" / "3.0" / "BouncingBall.fmu")
    assert len(configurations) == 1
    configuration = configurations[0]
    assert configuration.model_identifier == "BouncingBall"
    assert [path.name for path in configuration.source_files] == ["fmi3Functions.c", "model.c", "cosimulation.c"]
    assert configuration.definitions == {"FMI_VERSION": "3"}


@pytest.mark.fmi2
def test_no_source_files_fmi2(data_dir, tmp_path):
    """D7: without `<SourceFiles>`, the sources are not guessed."""
    source = data_dir / "compile" / "2.0" / "BouncingBall.fmu"
    with FMU(str(source)) as fmu:
        descriptor = open(fmu.descriptor_filename, "rb").read()
    descriptor = re.sub(rb"\s*<SourceFiles>.*?</SourceFiles>", b"", descriptor, flags=re.DOTALL)
    assert b"SourceFiles" not in descriptor
    fmu_filename = rewrite_fmu(source, tmp_path / "BouncingBall.fmu", replace={"modelDescription.xml": descriptor})

    with pytest.raises(OperationError):
        _configurations(fmu_filename)


@pytest.mark.fmi3
def test_no_build_description_fmi3(data_dir, tmp_path):
    """D7: without `sources/buildDescription.xml`, the sources are not guessed."""
    fmu_filename = rewrite_fmu(data_dir / "compile" / "3.0" / "BouncingBall.fmu", tmp_path / "BouncingBall.fmu",
                               drop=("sources/buildDescription.xml",))
    with pytest.raises(OperationError):
        _configurations(fmu_filename)


@pytest.mark.fmi3
def test_build_configuration_of_the_host_platform(data_dir, tmp_path):
    """A configuration dedicated to the host platform wins over a generic one; other platforms are ignored;
    optional definitions are not set."""
    host = compiler.SourceCompiler.host_platform(3)
    build_description = f"""<?xml version="1.0" encoding="UTF-8"?>
<fmiBuildDescription fmiVersion="3.0">
  <BuildConfiguration modelIdentifier="BouncingBall">
    <SourceFileSet><SourceFile name="model.c"/></SourceFileSet>
  </BuildConfiguration>
  <BuildConfiguration modelIdentifier="BouncingBall" platform="{host}">
    <SourceFileSet>
      <SourceFile name="fmi3Functions.c"/>
      <PreprocessorDefinition name="HOST"/>
      <PreprocessorDefinition name="OPTIONAL" value="1" optional="true"/>
      <IncludeDirectory name="include"/>
    </SourceFileSet>
  </BuildConfiguration>
  <BuildConfiguration modelIdentifier="BouncingBall" platform="other-platform">
    <SourceFileSet><SourceFile name="cosimulation.c"/></SourceFileSet>
  </BuildConfiguration>
</fmiBuildDescription>
""".encode("utf-8")
    fmu_filename = rewrite_fmu(data_dir / "compile" / "3.0" / "BouncingBall.fmu", tmp_path / "BouncingBall.fmu",
                               replace={"sources/buildDescription.xml": build_description})

    configurations = _configurations(fmu_filename)
    assert len(configurations) == 1
    configuration = configurations[0]
    assert [path.name for path in configuration.source_files] == ["fmi3Functions.c"]
    assert configuration.definitions == {"HOST": None}
    assert [path.name for path in configuration.include_directories] == ["include"]


@pytest.mark.fmi3
def test_missing_source_file(data_dir, tmp_path):
    fmu_filename = rewrite_fmu(data_dir / "compile" / "3.0" / "BouncingBall.fmu", tmp_path / "BouncingBall.fmu",
                               drop=("sources/model.c",))
    with pytest.raises(OperationError, match="model.c"):
        _configurations(fmu_filename)
