"""The guard of the release workflow (`tools/check_release_tag.py`): which tags may be published."""
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("packaging")

pytestmark = [pytest.mark.unit]

_spec = importlib.util.spec_from_file_location(
    "check_release_tag", Path(__file__).resolve().parents[2] / "tools" / "check_release_tag.py")
check_release_tag = importlib.util.module_from_spec(_spec)
sys.modules["check_release_tag"] = check_release_tag
_spec.loader.exec_module(check_release_tag)


@pytest.mark.parametrize("tag, version", [
    ("V2.1", "2.1"), ("V1.9.4.2", "1.9.4.2"), ("V2.1a1", "2.1a1"), ("V2.1a3", "2.1a3"), ("V2.0b3", "2.0b3"),
    ("V2.0.0rc1", "2.0.0rc1"), ("V2.1.dev0", "2.1.dev0"), ("v2.1", "2.1"),
])
def test_publishable_tags(tag, version):
    assert str(check_release_tag.tag_version(tag)) == version


@pytest.mark.parametrize("tag, message", [
    ("V2.1.dev1", "development release '.dev1'"),
    ("V0.0dev3", "not written in its normalized form"),  # normalized, it would still be a .dev3
    ("V2.1.0.dev3", "development release '.dev3'"),
    ("2.1a1", "does not start with 'V'"),
    ("Vnext", "is not a PEP 440 version"),
    ("V2.1-alpha1", "normalized form: tag 'V2.1a1'"),
    ("V2.1+local", "local part"),
])
def test_refused_tags(tag, message):
    with pytest.raises(check_release_tag.TagError, match=message):
        check_release_tag.tag_version(tag)


def test_a_dev_tag_suggests_a_pre_release():
    with pytest.raises(check_release_tag.TagError, match="'V2.1a1', 'b1' or 'rc1'"):
        check_release_tag.tag_version("V2.1.dev1")


def test_the_command_line_reports_on_stdout(capsys):
    assert check_release_tag.main(["V2.1.dev1", "--no-scm"]) == 1
    assert capsys.readouterr().out.startswith("::error::Release tag refused:")
    assert check_release_tag.main(["V2.1a1", "--no-scm"]) == 0
    assert "publishes version 2.1a1 (pre-release)" in capsys.readouterr().out
