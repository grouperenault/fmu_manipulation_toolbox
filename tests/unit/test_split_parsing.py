"""Unit tests for ``split`` parsing helpers and error branches.

These cover the container-description reader without needing a full, valid
container FMU: the header flag/format validation, the truncated-file guard, the
``get_nb`` helper, and the robustness of ``FMUSplitter.close`` when construction
failed before the zip handle was assigned (regression test for the
unraisable-exception-in-``__del__`` defect).
"""
import io
import zipfile

import pytest

from fmu_manipulation_toolbox.split import (
    FMUSplitter,
    FMUSplitterError,
    FMUSplitterDescription,
)

pytestmark = [pytest.mark.unit]


# --------------------------------------------------------------------------- #
#                        header / format validation                            #
# --------------------------------------------------------------------------- #
def test_header_with_uninterpretable_flags_raises():
    desc = FMUSplitterDescription(handle=None)
    # A flags line with exactly two tokens matches neither the legacy (1 token)
    # nor the modern (>=3 tokens) layout and must be rejected explicitly.
    container_txt = io.BytesIO(b"Container Version 3\n1 0\n")
    with pytest.raises(FMUSplitterError) as exc:
        desc.parse_txt_file_header(container_txt, "resources/container.txt")
    assert "Cannot interpret flags" in str(exc.value)


def test_get_line_on_truncated_file_raises():
    # A file containing only comments yields no usable line.
    only_comments = io.BytesIO(b"# a comment\n# another comment\n")
    with pytest.raises(FMUSplitterError) as exc:
        FMUSplitterDescription.get_line(only_comments)
    assert "truncated" in str(exc.value)


def test_get_line_skips_comments_and_returns_first_payload():
    stream = io.BytesIO(b"# header comment\n   actual payload  \n")
    assert FMUSplitterDescription.get_line(stream) == "actual payload"


@pytest.mark.parametrize("line, expected", [("3 something", 3), ("5", 5)])
def test_get_nb_parses_count(line, expected):
    assert FMUSplitterDescription.get_nb(line) == expected


# --------------------------------------------------------------------------- #
#                            FMUSplitter guards                                 #
# --------------------------------------------------------------------------- #
def test_split_non_container_fmu_raises(tmp_path):
    plain = tmp_path / "plain.fmu"
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("modelDescription.xml", "<fmiModelDescription/>")

    with pytest.raises(FMUSplitterError) as exc:
        FMUSplitter(str(plain))
    assert "not an FMU Container" in str(exc.value)


def test_close_is_safe_when_zip_was_never_assigned():
    # Regression: if __init__ fails before assigning ``self.zip`` (e.g. the FMU
    # file does not exist), __del__ -> close() must not raise.
    splitter = FMUSplitter.__new__(FMUSplitter)  # bypass __init__
    splitter.close()  # must be a no-op, not an AttributeError



# --------------------------------------------------------------------------- #
#                 modelDescription.xml of the embedded FMUs                    #
# --------------------------------------------------------------------------- #
def _description_with(descriptor: str) -> FMUSplitterDescription:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("embedded/modelDescription.xml", descriptor)
    desc = FMUSplitterDescription(handle=zipfile.ZipFile(buffer))
    desc.parse_model_description("embedded", "embedded.fmu")
    return desc


def test_fmi3_variable_without_causality_is_local():
    """`causality` is optional (default "local"): the former expat parser raised KeyError."""
    desc = _description_with(
        '<fmiModelDescription fmiVersion="3.0"><ModelVariables>'
        '<Float64 name="x" valueReference="5"/><Enumeration name="e" valueReference="6" declaredType="E"/>'
        '</ModelVariables></fmiModelDescription>')
    assert desc.vr_to_name["embedded.fmu"]["real64"][5] == {"name": "x", "causality": "local"}
    assert desc.vr_to_name["embedded.fmu"]["integer32"][6] == {"name": "e", "causality": "local"}


def test_fmi2_type_definitions_are_not_variables():
    desc = _description_with(
        '<fmiModelDescription fmiVersion="2.0"><TypeDefinitions><SimpleType name="T"><Real/></SimpleType>'
        '</TypeDefinitions><ModelVariables><ScalarVariable name="u" valueReference="1" causality="input">'
        '<Enumeration declaredType="E"/></ScalarVariable></ModelVariables></fmiModelDescription>')
    assert desc.vr_to_name["embedded.fmu"]["real64"] == {}
    assert desc.vr_to_name["embedded.fmu"]["integer32"] == {1: {"name": "u", "causality": "input"}}


def test_unreadable_embedded_descriptor_raises():
    with pytest.raises(FMUSplitterError, match="not well-formed"):
        _description_with("<fmiModelDescription fmiVersion='2.0'><x>a < b</x></fmiModelDescription>")
