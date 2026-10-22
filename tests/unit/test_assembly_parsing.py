"""Unit tests for ``Assembly`` descriptor parsing (CSV rules & nested JSON).

These exercise the largest logic module without building a real container: the
parsers only populate the in-memory ``AssemblyNode`` tree, so we can assert on
the resulting topology (embedded FMUs, exposed inputs/outputs, links, start
values, dropped ports, sub-containers) and on the parsers' resilience to
malformed lines. A CSV and a JSON round-trip guarantee that writing then
re-reading a description preserves the assembly.
"""
import pytest

from fmu_manipulation_toolbox.assembly import Assembly, AssemblyError, Port

pytestmark = [pytest.mark.unit]


def _assembly_from(tmp_path, name: str, text: str) -> Assembly:
    (tmp_path / name).write_text(text)
    return Assembly(name, fmu_directory=tmp_path)


# --------------------------------------------------------------------------- #
#                          CSV rules → node topology                           #
# --------------------------------------------------------------------------- #
CSV_ALL_RULES = """rule;from_fmu;from_port;to_fmu;to_port
FMU;a.fmu;;;
FMU;b.fmu;;;
INPUT;;ext_in;a.fmu;u
OUTPUT;b.fmu;y;;ext_out
LINK;a.fmu;y1;b.fmu;u1
START;a.fmu;p;3.14;
DROP;b.fmu;z;;
"""


def test_csv_rules_populate_every_topology_element(tmp_path):
    root = _assembly_from(tmp_path, "a.csv", CSV_ALL_RULES).root

    assert root.fmu_names_list == ["a.fmu", "b.fmu"]
    assert root.input_ports == {Port("a.fmu", "u"): "ext_in"}
    assert root.output_ports == {Port("b.fmu", "y"): "ext_out"}
    assert len(root.links) == 1
    assert str(root.links[0]) == "a.fmu/y1 -> b.fmu/u1"
    assert root.start_values == {Port("a.fmu", "p"): "3.14"}
    assert root.drop_ports == [Port("b.fmu", "z")]


def test_csv_input_defaults_exposed_name_to_port_name(tmp_path):
    # When the exposed input name (from_port) is left empty it defaults to the
    # embedded port name.
    csv = ("rule;from_fmu;from_port;to_fmu;to_port\n"
           "FMU;a.fmu;;;\n"
           "INPUT;;;a.fmu;u\n")
    root = _assembly_from(tmp_path, "d.csv", csv).root
    assert root.input_ports == {Port("a.fmu", "u"): "u"}


def test_csv_malformed_lines_are_skipped_but_parsing_continues(tmp_path, caplog):
    csv = (
        "rule;from_fmu;from_port;to_fmu;to_port\n"
        "# a comment is ignored\n"
        "FMU;good.fmu;;;\n"
        "FMU;;;;\n"              # missing FMU name → error, skipped
        "BOGUS;x;y;z;w\n"       # unknown rule → error, skipped
        "INPUT;only;three\n"    # wrong column count → error, skipped
        "FMU;second.fmu;;;\n"
    )
    root = _assembly_from(tmp_path, "resilient.csv", csv).root

    # The two valid FMU rules survive; the three invalid lines are dropped.
    assert root.fmu_names_list == ["good.fmu", "second.fmu"]
    assert "Missing FMU information" in caplog.text
    assert "unexpected rule" in caplog.text
    assert "expecting 5 columns" in caplog.text


# --------------------------------------------------------------------------- #
#                            nested JSON decoding                              #
# --------------------------------------------------------------------------- #
NESTED_JSON = """{
  "name": "top.fmu",
  "container": [
    {"name": "sub.fmu", "fmu": ["a.fmu", "b.fmu"],
     "link": [["a.fmu", "y", "b.fmu", "u"]]}
  ],
  "fmu": ["c.fmu"],
  "link": [["c.fmu", "y", "sub.fmu", "in"]]
}
"""


def test_json_nested_container_builds_child_node(tmp_path):
    root = _assembly_from(tmp_path, "nested.json", NESTED_JSON).root

    assert root.name == "top.fmu"
    assert root.fmu_names_list == ["c.fmu"]
    assert list(root.children) == ["sub.fmu"]

    child = root.children["sub.fmu"]
    assert child.parent is root
    assert child.fmu_names_list == ["a.fmu", "b.fmu"]
    assert str(child.links[0]) == "a.fmu/y -> b.fmu/u"
    assert str(root.links[0]) == "c.fmu/y -> sub.fmu/in"


def test_json_unexpected_keyword_is_logged_not_fatal(tmp_path, caplog):
    json_text = '{"name": "x.fmu", "fmu": ["a.fmu"], "unknown_key": 42}'
    root = _assembly_from(tmp_path, "x.json", json_text).root
    assert root.fmu_names_list == ["a.fmu"]  # parsing still succeeded
    assert "unexpected keyword" in caplog.text


def test_json_keyword_wrong_type_raises(tmp_path):
    json_text = '{"name": "x.fmu", "input": "not-a-list"}'
    with pytest.raises(AssemblyError) as exc:
        _assembly_from(tmp_path, "x.json", json_text)
    assert "should define a list" in str(exc.value)


def test_json_link_wrong_arity_raises(tmp_path):
    # A link needs four fields; three must be reported explicitly.
    json_text = '{"name": "x.fmu", "link": [["a.fmu", "y", "b.fmu"]]}'
    with pytest.raises(AssemblyError) as exc:
        _assembly_from(tmp_path, "x.json", json_text)
    assert "right number of fields" in str(exc.value)


# --------------------------------------------------------------------------- #
#                                round-trips                                   #
# --------------------------------------------------------------------------- #
def test_csv_round_trip_preserves_topology(tmp_path):
    original = _assembly_from(tmp_path, "rt.csv", CSV_ALL_RULES)
    original.write_csv("rt-out.csv")
    reread = Assembly("rt-out.csv", fmu_directory=tmp_path)

    assert reread.root.fmu_names_list == original.root.fmu_names_list
    assert reread.root.input_ports == original.root.input_ports
    assert reread.root.output_ports == original.root.output_ports
    assert reread.root.start_values == original.root.start_values
    assert reread.root.drop_ports == original.root.drop_ports
    assert [str(c) for c in reread.root.links] == [str(c) for c in original.root.links]


def test_json_round_trip_preserves_nested_assembly(tmp_path):
    original = _assembly_from(tmp_path, "nested.json", NESTED_JSON)
    original.write_json("nested-out.json")
    reread = Assembly("nested-out.json", fmu_directory=tmp_path)

    assert reread.json_encode() == original.json_encode()

