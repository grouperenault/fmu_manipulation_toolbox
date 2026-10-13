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


# --------------------------------------------------------------------------- #
#                              Command lines                                   #
# --------------------------------------------------------------------------- #
GCC = compiler.Toolchain("gcc", ["gcc"], ["g++"])
MSVC = compiler.Toolchain("msvc", ["cl"], ["cl"])


def _commands(fmu_filename, toolchain, tmp_path):
    with FMU(str(fmu_filename)) as fmu:
        md = fmu.model_description
        source_compiler = compiler.SourceCompiler(fmu.tmp_directory, md.fmi_version)
        configuration = source_compiler.build_configurations(md)[0]
        commands = source_compiler.build_commands(configuration, toolchain, tmp_path, tmp_path / "lib")
        return commands, source_compiler.sources_directory


@pytest.mark.fmi3
def test_gcc_commands_fmi3(data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    commands, sources = _commands(data_dir / "compile" / "3.0" / "BouncingBall.fmu", GCC, tmp_path)
    *compilations, link = commands

    assert [command[-3] for command in compilations] == [str(sources / name) for name in
                                                         ("fmi3Functions.c", "model.c", "cosimulation.c")]
    for command in compilations:
        assert command[:2] == ["gcc", "-c"]
        assert {"-DFMI_VERSION=3", "-DDISABLE_PREFIX", "-DFMI3_OVERRIDE_FUNCTION_PREFIX", "-fPIC"} <= set(command)
        includes = [argument for argument in command if argument.startswith("-I")]
        assert includes == [f"-I{sources}", f"-I{compiler.FMI_HEADERS_DIRECTORY}"]
    assert link[:2] == ["gcc", "-shared"]
    assert link[-1] == "-lm"


@pytest.mark.fmi2
def test_gcc_commands_fmi2(data_dir, tmp_path, monkeypatch):
    """FMI 2.0 headers have no override mechanism: only `DISABLE_PREFIX`."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    commands, sources = _commands(data_dir / "compile" / "2.0" / "BouncingBall.fmu", GCC, tmp_path)
    compilation, link = commands
    assert "-DDISABLE_PREFIX" in compilation
    assert not any("OVERRIDE" in argument for argument in compilation)
    assert link[:2] == ["gcc", "-dynamiclib"]


@pytest.mark.fmi3
def test_msvc_commands(data_dir, tmp_path):
    commands, sources = _commands(data_dir / "compile" / "3.0" / "BouncingBall.fmu", MSVC, tmp_path)
    *compilations, link = commands
    for command in compilations:
        assert {"/c", "/MT", "/TC", "/DFMI_VERSION=3", "/DDISABLE_PREFIX", f"/I{sources}"} <= set(command)
        assert command[-1].startswith("/Fo") and command[-1].endswith(".obj")
    assert {"/LD", "/MT", f"/Fe{tmp_path / 'lib'}"} <= set(link)
    assert "/link" not in link


def _custom_fmu(data_dir, tmp_path, source_file_set: str, libraries: str = ""):
    build_description = f"""<?xml version="1.0" encoding="UTF-8"?>
<fmiBuildDescription fmiVersion="3.0">
  <BuildConfiguration modelIdentifier="BouncingBall">
    {source_file_set}
    <SourceFileSet><SourceFile name="model.c"/></SourceFileSet>
    {libraries}
  </BuildConfiguration>
</fmiBuildDescription>
""".encode("utf-8")
    return rewrite_fmu(data_dir / "compile" / "3.0" / "BouncingBall.fmu", tmp_path / "BouncingBall.fmu",
                       replace={"sources/buildDescription.xml": build_description,
                                "sources/extra.cpp": b"", "sources/extra.c": b""})


@pytest.mark.fmi3
@pytest.mark.parametrize("source_file_set", [
    '<SourceFileSet><SourceFile name="extra.cpp"/></SourceFileSet>',
    '<SourceFileSet language="C++17"><SourceFile name="extra.c"/></SourceFileSet>',
])
def test_cxx_sources(data_dir, tmp_path, source_file_set):
    """D12: C++ by language or by suffix; the C++ compiler links as soon as one source is C++."""
    fmu_filename = _custom_fmu(data_dir, tmp_path, source_file_set)
    (cxx, c, link), _ = _commands(fmu_filename, GCC, tmp_path)
    assert cxx[0] == "g++"
    assert c[0] == "gcc"
    assert link[0] == "g++"

    (cxx, c, link), _ = _commands(fmu_filename, MSVC, tmp_path)
    assert "/TP" in cxx and "/TC" in c


@pytest.mark.fmi3
def test_compiler_options(data_dir, tmp_path, caplog):
    """D13: options are applied only for the compiler they are written for."""
    fmu_filename = _custom_fmu(data_dir, tmp_path, '<SourceFileSet compiler="gcc" compilerOptions="-Wall -DX=&quot;a b&quot;">'
                                                   '<SourceFile name="extra.c"/></SourceFileSet>')
    (with_options, without_options, _), _ = _commands(fmu_filename, GCC, tmp_path)
    assert {"-Wall", "-DX=a b"} <= set(with_options)
    assert "-Wall" not in without_options

    with caplog.at_level("WARNING", logger="fmu_manipulation_toolbox"):
        (compilation, _, _), _ = _commands(fmu_filename, compiler.Toolchain("clang", ["cc"], ["c++"]), tmp_path)
    assert "-Wall" not in compilation
    assert "ignored" in caplog.text


@pytest.mark.fmi3
def test_libraries(data_dir, tmp_path):
    """D14: libraries are linked by name."""
    fmu_filename = _custom_fmu(data_dir, tmp_path, "", '<Library name="foo"/><Library name="bar.lib"/>')
    commands, _ = _commands(fmu_filename, GCC, tmp_path)
    assert "-lfoo" in commands[-1]
    commands, _ = _commands(fmu_filename, MSVC, tmp_path)
    assert commands[-1][-3:] == ["/link", "foo.lib", "bar.lib"]
