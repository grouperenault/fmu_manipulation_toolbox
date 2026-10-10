"""Unit tests for the canonical XML comparison helper (`assert_equivalent_xml`).

The helper replaces line-by-line comparisons of `modelDescription.xml` files so
that a change of serialiser (see `docs/local/done/refactoring.md`) does not break the
suite. These tests make sure it ignores formatting only, never meaning.
"""
import pytest

from _helpers.assertions import VOLATILE_XML_ATTRIBUTES, assert_equivalent_xml

pytestmark = [pytest.mark.unit]

REFERENCE = b"""<?xml version="1.0" encoding="UTF-8"?>
<fmiModelDescription fmiVersion="2.0" modelName="m" guid="{1}">
  <!-- comment -->
  <ModelVariables>
    <ScalarVariable name="u" valueReference="1" causality="input"><Real start="0"></Real></ScalarVariable>
    <ScalarVariable name="y" valueReference="2" causality="output"><Real/></ScalarVariable>
  </ModelVariables>
  <VendorAnnotations><Tool name="T"><Info>x &lt; y</Info></Tool></VendorAnnotations>
</fmiModelDescription>
"""


def test_formatting_is_ignored():
    reformatted = (b"<fmiModelDescription guid='{1}' modelName='m' fmiVersion='2.0'><ModelVariables>"
                   b"<ScalarVariable causality='input' name='u' valueReference='1'><Real start='0'/>"
                   b"</ScalarVariable><ScalarVariable name='y' valueReference='2' causality='output'>"
                   b"<Real></Real></ScalarVariable></ModelVariables><VendorAnnotations><Tool name='T'>"
                   b"<Info>x &#60; y</Info></Tool></VendorAnnotations></fmiModelDescription>")
    assert_equivalent_xml(REFERENCE, reformatted)


def test_volatile_attributes_can_be_ignored():
    other_guid = REFERENCE.replace(b'guid="{1}"', b'guid="{2}"')
    assert_equivalent_xml(REFERENCE, other_guid, ignore_attributes=VOLATILE_XML_ATTRIBUTES)
    with pytest.raises(AssertionError):
        assert_equivalent_xml(REFERENCE, other_guid)


def test_comments_are_compared_on_demand():
    without_comment = REFERENCE.replace(b"<!-- comment -->", b"")
    assert_equivalent_xml(REFERENCE, without_comment)
    with pytest.raises(AssertionError):
        assert_equivalent_xml(REFERENCE, without_comment, with_comments=True)


@pytest.mark.parametrize("old, new", [
    (b'start="0"', b'start="1"'),                         # attribute value
    (b' causality="input"', b""),                         # missing attribute
    (b"x &lt; y", b"x &lt; z"),                           # text
    (b"&lt;", b"&amp;lt;"),                               # escaping level
    (b'<Real start="0"></Real>', b'<Real start="0"/><Annotations/>'),  # extra element
], ids=["attribute", "missing-attribute", "text", "escaping", "extra-element"])
def test_meaningful_differences_are_reported(old, new):
    assert old in REFERENCE
    with pytest.raises(AssertionError, match="not equivalent"):
        assert_equivalent_xml(REFERENCE, REFERENCE.replace(old, new))


def test_element_order_is_significant():
    u = b'<ScalarVariable name="u" valueReference="1" causality="input"><Real start="0"></Real></ScalarVariable>'
    y = b'<ScalarVariable name="y" valueReference="2" causality="output"><Real/></ScalarVariable>'
    swapped = REFERENCE.replace(u, b"@@").replace(y, u).replace(b"@@", y)
    with pytest.raises(AssertionError):
        assert_equivalent_xml(REFERENCE, swapped)
