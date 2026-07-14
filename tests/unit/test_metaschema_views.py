"""
Unit tests for the metaschema documentation views:
    - metaschema_parser._assign_node_refs  (stable node reference ids)
    - metaschema_gen_docs.render_outline / render_detail
    - OSCALSupport.view_outline / view_detail
"""
import re

import pytest

from oscal import metaschema_gen_docs as views
from oscal.metaschema_parser import _assign_node_refs
from oscal.oscal_support import get_support


# ---------------------------------------------------------------------------
# A small hand-built index (avoids depending on the support DB for most tests)
# ---------------------------------------------------------------------------
def _node(structure_type, name, **kw):
    node = {"structure-type": structure_type, "name": name, "use-name": name,
            "min-occurs": "0", "max-occurs": "1", "constraints": []}
    node.update(kw)
    return node


@pytest.fixture
def index():
    method = _node("flag", "method", datatype="string", formal_name="Method",
                   description=["How to combine."],
                   **{"formal-name": "Method"},
                   constraints=[{
                       "type": "allowed-values", "allow-other": False,
                       "values": [{"value": "keep", "description": "Keep it"},
                                  {"value": "merge", "description": "Merge it", "deprecated": "1.0.1"}],
                   }])
    as_is = _node("field", "as-is", datatype="boolean", min_occurs="1", max_occurs="1",
                  **{"min-occurs": "1", "max-occurs": "1", "formal-name": "As Is"})
    flat = _node("assembly", "flat", min_occurs="1", max_occurs="1",
                 **{"min-occurs": "1", "max-occurs": "1"})
    choice = _node("choice", "CHOICE", children=[flat, as_is])
    groups = _node("assembly", "group", group_as="groups", max_occurs="unbounded",
                   **{"group-as": "groups", "max-occurs": "unbounded"})
    root = _node("assembly", "profile", min_occurs="1", max_occurs="1",
                 **{"min-occurs": "1", "max-occurs": "1", "formal-name": "Profile"},
                 children=[method, choice, groups])
    _assign_node_refs(root, "vTEST/profile")
    return {"nodes": root, "oscal_version": "vTEST", "oscal_model": "profile", "schema_name": "Test"}


# ---------------------------------------------------------------------------
# _assign_node_refs
# ---------------------------------------------------------------------------
class TestAssignRefs:

    def test_root_has_ref_and_no_parent(self, index):
        root = index["nodes"]
        assert root.get("ref")
        assert root.get("parent-ref") is None

    def test_children_reference_parent(self, index):
        root = index["nodes"]
        for child in root["children"]:
            assert child["parent-ref"] == root["ref"]

    def test_all_refs_unique(self, index):
        refs = []

        def walk(n):
            refs.append(n["ref"])
            for c in n.get("children", []):
                walk(c)
        walk(index["nodes"])
        assert len(refs) == len(set(refs))

    def test_refs_deterministic(self):
        a = _node("assembly", "x", children=[_node("flag", "y")])
        b = _node("assembly", "x", children=[_node("flag", "y")])
        _assign_node_refs(a, "seed")
        _assign_node_refs(b, "seed")
        assert a["ref"] == b["ref"]
        assert a["children"][0]["ref"] == b["children"][0]["ref"]


# ---------------------------------------------------------------------------
# render_outline
# ---------------------------------------------------------------------------
class TestOutline:

    def test_is_div_fragment_no_body(self, index):
        html = views.render_outline(index, "xml")
        assert html.startswith('<div class="ms-outline"')
        assert "<html" not in html and "<body" not in html

    def test_every_node_is_clickable(self, index):
        html = views.render_outline(index, "xml")
        refs_in_html = set(re.findall(r'data-ref="([0-9a-f-]{36})"', html))
        # collect refs from the tree
        tree_refs = set()

        def walk(n):
            tree_refs.add(n["ref"])
            for c in n.get("children", []):
                walk(c)
        walk(index["nodes"])
        assert tree_refs <= refs_in_html

    def test_xml_flavor_tokens(self, index):
        html = views.render_outline(index, "xml")
        assert "&lt;profile&gt;" in html   # element
        assert "@method" in html            # flag as attribute
        assert "&lt;choice&gt;" in html

    def test_json_flavor_uses_group_as(self, index):
        html = views.render_outline(index, "json")
        assert ">groups<" in html           # group-as key, not <group>
        assert "&lt;group&gt;" not in html
        assert "(choice)" in html

    def test_cardinality_and_types_present(self, index):
        html = views.render_outline(index, "xml")
        assert "0..*" in html               # groups (unbounded)
        assert "1..1" in html               # as-is
        assert "boolean" in html            # as-is datatype

    def test_choice_meta(self, index):
        html = views.render_outline(index, "xml")
        # flat(min1) + as-is(min1) -> required choice
        assert "select one (required)" in html

    def test_bad_format_is_error(self, index):
        assert 'class="ms-error"' in views.render_outline(index, "toml")

    def test_missing_nodes_is_error(self):
        assert 'class="ms-error"' in views.render_outline({}, "xml")


# ---------------------------------------------------------------------------
# render_detail
# ---------------------------------------------------------------------------
class TestDetail:

    def test_detail_has_formal_name_and_description(self, index):
        method = index["nodes"]["children"][0]
        html = views.render_detail(index, method["ref"], "json")
        assert html.startswith('<div class="ms-detail"')
        assert "Method" in html
        assert "How to combine." in html

    def test_detail_datatype_and_regex(self, index):
        method = index["nodes"]["children"][0]  # string flag
        html = views.render_detail(index, method["ref"], "json")
        assert "Data type" in html and "string" in html
        assert "Pattern" in html                       # regex from OSCAL_DATATYPES

    def test_detail_allowed_values(self, index):
        method = index["nodes"]["children"][0]
        html = views.render_detail(index, method["ref"], "xml")
        assert "Allowed values" in html
        assert "keep" in html and "merge" in html
        assert "deprecated" in html                    # merge is deprecated

    def test_detail_parent_link(self, index):
        method = index["nodes"]["children"][0]
        html = views.render_detail(index, method["ref"], "xml")
        # parent is the root; its ref must appear as a link target
        assert index["nodes"]["ref"] in html

    def test_detail_root_has_no_parent(self, index):
        root = index["nodes"]
        html = views.render_detail(index, root["ref"], "xml")
        assert "root — no parent" in html

    def test_detail_children_listed_and_clickable(self, index):
        root = index["nodes"]
        html = views.render_detail(index, root["ref"], "xml")
        for child in root["children"]:
            assert child["ref"] in html

    def test_detail_choice_representation(self, index):
        choice = index["nodes"]["children"][1]
        html = views.render_detail(index, choice["ref"], "xml")
        assert "one of:" in html
        assert "select one (required)" in html

    def test_representation_is_format_flavored(self, index):
        as_is = index["nodes"]["children"][1]["children"][1]  # field as-is
        xml = views.render_detail(index, as_is["ref"], "xml")
        js = views.render_detail(index, as_is["ref"], "json")
        assert "&lt;as-is&gt;" in xml               # <as-is>...</as-is>
        assert "&quot;as-is&quot;:" in js           # "as-is": ... (escaped in <pre>)

    def test_bad_ref_is_error(self, index):
        assert 'class="ms-error"' in views.render_detail(index, "nope", "xml")

    def test_bad_format_is_error(self, index):
        root = index["nodes"]
        assert 'class="ms-error"' in views.render_detail(index, root["ref"], "toml")


# ---------------------------------------------------------------------------
# Support integration (uses the real metaschema index)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def support():
    return get_support()


class TestSupportViews:

    def test_view_outline_real(self, support):
        html = support.view_outline("v1.1.3", "profile", "xml")
        assert html.startswith('<div class="ms-outline"')
        assert "data-ref=" in html

    def test_view_detail_roundtrip(self, support):
        idx = support.get_metaschema_index("v1.1.3", "profile")
        root_ref = idx["nodes"]["ref"]
        html = support.view_detail("v1.1.3", "profile", "xml", root_ref)
        assert html.startswith('<div class="ms-detail"')
        assert "root — no parent" in html

    def test_view_outline_unknown_model(self, support):
        assert 'class="ms-error"' in support.view_outline("v1.1.3", "not-a-model", "xml")

    def test_view_detail_unknown_ref(self, support):
        assert 'class="ms-error"' in support.view_detail("v1.1.3", "profile", "xml", "bad-ref")

    def test_all_three_formats(self, support):
        for fmt in ("xml", "json", "yaml"):
            html = support.view_outline("v1.1.3", "catalog", fmt)
            assert html.startswith('<div class="ms-outline"')
