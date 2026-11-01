"""The Claude Code plugin and its skills (`plugins/fmutool/`).

The skills are instructions, not code: these tests keep them true. The
manifests are valid, the skills well formed, their links resolve, every tool
they name exists, the shared reference does not drift from what the MCP server
publishes, the `.zip` files for claude.ai build, and every `fmutool-agent`
example of a skill runs as written on the FMUs of `tests/data`.
"""
import importlib.util
import json
import re
import shlex
import shutil
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from fmu_manipulation_toolbox.assistant.fmutools import OPERATIONS
from fmu_manipulation_toolbox.assistant.knowledge import FMI_CONVENTIONS
from fmu_manipulation_toolbox.assistant.tools import TOOLS
from fmu_manipulation_toolbox.cli.fmutool_agent import check_arguments, run

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "fmutool"
SKILLS = sorted(path.parent.name for path in (PLUGIN / "skills").glob("*/SKILL.md"))

#: Prefixes of the tool names, to find the tools a skill names between backticks.
TOOL_VERBS = ("list_", "inspect_", "add_", "remove_", "expose_", "set_", "unset_", "get_", "analyze_", "save_",
              "summarize_", "check_", "describe_", "dump_", "rename_", "apply_")


def _skill(name: str) -> str:
    return (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with a YAML frontmatter"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _examples(text: str) -> list[list[str]]:
    """The `fmutool-agent` command lines of the `bash` blocks, in order."""
    commands = []
    for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
        commands += [shlex.split(line.strip()) for line in block.splitlines()
                     if line.strip().startswith("fmutool-agent ")]
    return commands


# --------------------------------------------------------------------------- #
#                                  manifests                                  #
# --------------------------------------------------------------------------- #
def test_the_marketplace_lists_the_plugin():
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    (entry,) = marketplace["plugins"]

    assert marketplace["name"] and marketplace["owner"]["name"]
    assert (ROOT / entry["source"] / ".claude-plugin" / "plugin.json").is_file()
    assert json.loads((ROOT / entry["source"] / ".claude-plugin" / "plugin.json").read_text())["name"] == entry["name"]


def test_the_plugin_starts_the_mcp_server_of_the_package():
    servers = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]

    assert servers["fmutool"]["command"] in scripts
    assert "fmutool-agent" in scripts  # the fallback the skills rely on


# --------------------------------------------------------------------------- #
#                                   skills                                    #
# --------------------------------------------------------------------------- #
def test_the_skills_are_those_of_the_plan():
    assert SKILLS == ["fmu-container", "fmu-edit", "fmu-inspect"]


@pytest.mark.parametrize("name", SKILLS)
def test_a_skill_is_well_formed(name):
    fields = _frontmatter(_skill(name))

    assert fields["name"] == name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", name)
    assert 100 < len(fields["description"]) <= 1024
    assert "<" not in fields["description"] and ">" not in fields["description"]


@pytest.mark.parametrize("name", SKILLS)
def test_the_links_of_a_skill_resolve(name):
    for target in re.findall(r"\]\(([^)#]+)\)", _skill(name)):
        if not target.startswith("http"):
            assert (PLUGIN / "skills" / name / target).resolve().is_file(), target


@pytest.mark.parametrize("name", SKILLS)
def test_a_skill_names_existing_tools_only(name):
    text = _skill(name)
    named = {word for word in re.findall(r"`([a-z][a-z0-9_]*)`", text) if word.startswith(TOOL_VERBS)}
    called = {command[1] for command in _examples(text)}

    # The operations of `apply_operation` (`remove_regexp`...) share the verbs of the tools.
    assert named - set(TOOLS) - set(OPERATIONS) == set()
    assert called - set(TOOLS) == set()


@pytest.mark.parametrize("name", SKILLS)
def test_the_arguments_of_the_examples_are_valid(name):
    for command in _examples(_skill(name)):
        tool, arguments = command[1], json.loads(command[command.index("--args") + 1])
        check_arguments(tool, arguments)


def test_the_shared_reference_contains_the_conventions_of_the_server():
    """`fmi://conventions` and the reference of the skills say the same thing: the reference starts with it."""
    reference = (PLUGIN / "references" / "fmi-reference.md").read_text(encoding="utf-8")
    body = FMI_CONVENTIONS.split("\n", 1)[1]

    assert body.strip() in reference


# --------------------------------------------------------------------------- #
#                          the examples run as written                        #
# --------------------------------------------------------------------------- #
@pytest.fixture
def workspace(data_dir, tmp_path, monkeypatch):
    """The FMUs the examples name, in the current directory."""
    shutil.copy(data_dir / "compile" / "3.0" / "BouncingBall.fmu", tmp_path / "model.fmu")
    for name in ("bb_position.fmu", "bb_velocity.fmu"):
        shutil.copy(data_dir / "fmi3" / "bouncing_ball" / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FMUCONTAINER_MCP_ROOT", raising=False)
    return tmp_path


def _run_examples(name, capsys):
    for command in _examples(_skill(name)):
        code = run(command[1:])
        result = json.loads(capsys.readouterr().out)
        assert code == 0, (command, result)


@pytest.mark.parametrize("name", ["fmu-inspect", "fmu-edit"])
def test_the_examples_of_a_skill_run(name, workspace, capsys):
    _run_examples(name, capsys)


@pytest.mark.needs_container
def test_the_examples_of_the_container_skill_run(workspace, capsys):
    _run_examples("fmu-container", capsys)

    assert (workspace / "container.fmu").is_file()
    assert (workspace / "container.json").is_file()


# --------------------------------------------------------------------------- #
#                            the .zip for claude.ai                           #
# --------------------------------------------------------------------------- #
def test_the_skills_build_as_self_contained_zips(tmp_path):
    spec = importlib.util.spec_from_file_location("build_skill_zips", ROOT / "tools" / "build_skill_zips.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_skill_zips"] = module
    spec.loader.exec_module(module)

    archives = module.build(output=tmp_path)

    assert sorted(archive.stem for archive in archives) == SKILLS
    for archive in archives:
        with zipfile.ZipFile(archive) as zip_file:
            names = set(zip_file.namelist())
            text = zip_file.read(f"{archive.stem}/SKILL.md").decode("utf-8")
        assert "../../" not in text
        for target in re.findall(r"\]\(([^)#]+)\)", text):
            assert f"{archive.stem}/{target}" in names, target


# --------------------------------------------------------------------------- #
#                      the version of the toolbox they need                    #
# --------------------------------------------------------------------------- #
#: The oldest release of the toolbox with what the skills use (`fmutool-agent`, `describe_port`, the filters).
MIN_TOOLBOX_VERSION = "2.1.dev1"

#: Pages telling how to install the toolbox for the skills.
INSTALL_PAGES = ("docs/user-guide/agent-skills.md", "docs/examples/agent-skills-walkthrough.md")


@pytest.mark.parametrize("name", SKILLS)
def test_a_skill_declares_the_version_it_needs(name):
    text = _skill(name)
    compatibility = _frontmatter(text)["compatibility"]

    assert f"{MIN_TOOLBOX_VERSION} or later" in compatibility
    assert f'"fmu-manipulation-toolbox>={MIN_TOOLBOX_VERSION}"' in compatibility
    # The installed version is checked by a tool it brought, not by its number (a source install is `2.1.devN`).
    assert "`describe_port`" in text and "describe_port" in TOOLS


@pytest.mark.parametrize("path", [f"plugins/fmutool/skills/{name}/SKILL.md" for name in SKILLS] + list(INSTALL_PAGES))
def test_every_installation_asks_for_that_version(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    commands = re.findall(r"pip install[^`\n]*fmu-manipulation-toolbox[^`\n]*", text)

    assert commands, path
    for command in commands:
        assert f">={MIN_TOOLBOX_VERSION}" in command, command


def test_the_plugin_version_follows_the_toolbox_it_needs():
    version = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]
    release, _, dev = MIN_TOOLBOX_VERSION.partition(".dev")

    assert version == f"{release}.0-dev.{dev}"  # semver of the PEP 440 version


def test_the_installed_toolbox_is_recent_enough():
    packaging_version = pytest.importorskip("packaging.version")
    from fmu_manipulation_toolbox.version import __version__

    assert packaging_version.Version(__version__) >= packaging_version.Version(MIN_TOOLBOX_VERSION)
