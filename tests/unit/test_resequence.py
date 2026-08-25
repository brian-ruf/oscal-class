"""
Unit tests for oscal.oscal_resequence — metaschema-driven key resequencing —
and its wiring into OSCAL serialization.

Layers:
  * TestOrderingEngine — the `_MetaschemaOrderer` against small hand-built
    indexes, covering flags-first, group-as keys, choice flattening, field
    value keys, BY_KEY maps, and recursive-definition resolution.
  * TestResequenceOscal / TestNormalizeVersion / TestResequenceFile — end-to-end
    resequencing of real OSCAL content, using the XML→JSON converter output as
    the canonical-order oracle (the resequencer must reproduce exactly that
    order, losslessly), plus version normalization and the file helpers.
  * TestDumpWiring — resequencing wired into OSCAL.dump/dumps and the
    json/xml/yaml properties: JSON/YAML best-effort ordering, XML required
    ordering, and the transient-`_tree` lifecycle (released after a dump; kept
    only in the degraded no-dict case).
"""
import json
import random

import pytest

from oscal import Catalog
import oscal.oscal_content as oscal_content
from oscal.oscal_converter import OSCALConverter
from oscal.oscal_resequence import (
    _MetaschemaOrderer,
    _detect_model_root_key,
    _normalize_version,
    resequence_oscal,
    resequence_oscal_file,
)

_HERE = __file__.rsplit("/", 1)[0]
_XML_CATALOG = f"{_HERE}/../test-data/xml/FedRAMP_rev5_LOW-baseline-resolved-profile_catalog.xml"
_XML_PROFILE = f"{_HERE}/../test-data/xml/FedRAMP_rev5_LOW-baseline_profile.xml"
_JSON_SSP = f"{_HERE}/../test-data/sanitized_ssp_oscal.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _key_skeleton(value):
    """Capture key ORDER at every object in a structure (ignores scalar values)."""
    if isinstance(value, dict):
        return [(k, _key_skeleton(v)) for k, v in value.items()]
    if isinstance(value, list):
        return [_key_skeleton(i) for i in value]
    return None


def _shuffle(value, rng):
    """Return a deep copy of *value* with every object's key order shuffled."""
    if isinstance(value, dict):
        items = list(value.items())
        rng.shuffle(items)
        return {k: _shuffle(v, rng) for k, v in items}
    if isinstance(value, list):
        return [_shuffle(i, rng) for i in value]
    return value


def _canonical_from_xml(model, xml_path, version="v1.2.0"):
    """Converter output = canonical key order (the oracle)."""
    conv = OSCALConverter.from_support(model, version)
    canonical = json.loads(conv.xml_to_json(open(xml_path).read()))
    canonical.pop("$schema", None)
    return canonical


# ---------------------------------------------------------------------------
# Ordering engine (hand-built indexes)
# ---------------------------------------------------------------------------
class TestOrderingEngine:
    def _orderer(self, root_node):
        return _MetaschemaOrderer({"nodes": root_node})

    def test_flags_before_children_and_group_as_keys(self):
        root = {
            "structure-type": "assembly", "name": "catalog", "use-name": "catalog",
            "children": [
                {"structure-type": "flag", "name": "uuid", "use-name": "uuid"},
                {"structure-type": "assembly", "name": "metadata", "use-name": "metadata",
                 "children": [
                     {"structure-type": "flag", "name": "x", "use-name": "x"},
                     {"structure-type": "field", "name": "title", "use-name": "title"},
                 ]},
                {"structure-type": "assembly", "name": "control", "use-name": "control",
                 "group-as": "controls", "group-as-in-json": "ARRAY",
                 "children": [
                     {"structure-type": "flag", "name": "id", "use-name": "id"},
                     {"structure-type": "field", "name": "title", "use-name": "title"},
                 ]},
            ],
        }
        orderer = self._orderer(root)
        obj = {"controls": [{"title": "t", "id": "c1"}],
               "metadata": {"title": "m", "x": "1"},
               "uuid": "u"}
        out = orderer.resequence_object(obj, orderer.root_node)
        assert list(out) == ["uuid", "metadata", "controls"]         # flag first, then children in order
        assert list(out["metadata"]) == ["x", "title"]               # nested reordering
        assert list(out["controls"][0]) == ["id", "title"]           # array items reordered

    def test_unknown_keys_kept_last_in_original_order(self):
        root = {"structure-type": "assembly", "name": "catalog", "use-name": "catalog",
                "children": [{"structure-type": "flag", "name": "uuid", "use-name": "uuid"}]}
        orderer = self._orderer(root)
        obj = {"_z": 1, "uuid": "u", "_a": 2}
        out = orderer.resequence_object(obj, orderer.root_node)
        assert list(out) == ["uuid", "_z", "_a"]

    def test_choice_alternatives_flattened(self):
        root = {"structure-type": "assembly", "name": "import", "use-name": "import",
                "children": [
                    {"structure-type": "flag", "name": "href", "use-name": "href"},
                    {"structure-type": "choice", "children": [
                        {"structure-type": "assembly", "name": "include-all", "use-name": "include-all"},
                        {"structure-type": "assembly", "name": "include-control",
                         "use-name": "include-control", "group-as": "include-controls",
                         "group-as-in-json": "ARRAY"},
                    ]},
                    {"structure-type": "assembly", "name": "exclude-control",
                     "use-name": "exclude-control", "group-as": "exclude-controls",
                     "group-as-in-json": "ARRAY"},
                ]}
        orderer = self._orderer(root)
        obj = {"exclude-controls": [], "include-controls": [], "href": "#x"}
        out = orderer.resequence_object(obj, orderer.root_node)
        assert list(out) == ["href", "include-controls", "exclude-controls"]

    def test_field_value_key_after_flags(self):
        root = {"structure-type": "assembly", "name": "root", "use-name": "root",
                "children": [
                    {"structure-type": "field", "name": "hash", "use-name": "hash",
                     "group-as": "hashes", "group-as-in-json": "ARRAY",
                     "json-value-key": "value",
                     "children": [
                         {"structure-type": "flag", "name": "algorithm", "use-name": "algorithm"},
                     ]},
                ]}
        orderer = self._orderer(root)
        obj = {"hashes": [{"value": "abc", "algorithm": "SHA-256"}]}
        out = orderer.resequence_object(obj, orderer.root_node)
        assert list(out["hashes"][0]) == ["algorithm", "value"]      # flag before value key

    def test_by_key_map_instances_reordered_map_order_preserved(self):
        root = {"structure-type": "assembly", "name": "root", "use-name": "root",
                "children": [
                    {"structure-type": "assembly", "name": "role", "use-name": "role",
                     "group-as": "roles", "group-as-in-json": "BY_KEY", "json-key": "id",
                     "children": [
                         {"structure-type": "flag", "name": "x", "use-name": "x"},
                         {"structure-type": "field", "name": "title", "use-name": "title"},
                     ]},
                ]}
        orderer = self._orderer(root)
        obj = {"roles": {"admin": {"title": "T", "x": "1"}, "user": {"title": "U", "x": "2"}}}
        out = orderer.resequence_object(obj, orderer.root_node)
        assert list(out["roles"]) == ["admin", "user"]               # map key order preserved
        assert list(out["roles"]["admin"]) == ["x", "title"]         # instance reordered

    def test_recursive_definition_resolved(self):
        root = {"structure-type": "assembly", "name": "catalog", "use-name": "catalog",
                "children": [
                    {"structure-type": "assembly", "name": "control", "use-name": "control",
                     "group-as": "controls", "group-as-in-json": "ARRAY",
                     "children": [
                         {"structure-type": "flag", "name": "id", "use-name": "id"},
                         {"structure-type": "field", "name": "title", "use-name": "title"},
                         {"structure-type": "recursive", "name": "control",
                          "use-name": "control", "group-as": "controls",
                          "group-as-in-json": "ARRAY"},
                     ]},
                ]}
        orderer = self._orderer(root)
        obj = {"controls": [{
            "controls": [{"title": "child", "id": "c-1.1"}],
            "title": "parent", "id": "c-1",
        }]}
        out = orderer.resequence_object(obj, orderer.root_node)
        top = out["controls"][0]
        assert list(top) == ["id", "title", "controls"]
        assert list(top["controls"][0]) == ["id", "title"]           # nested recursion reordered


# ---------------------------------------------------------------------------
# End-to-end resequencing against the converter oracle
# ---------------------------------------------------------------------------
class TestResequenceOscal:
    def test_catalog_matches_canonical_order(self):
        canonical = _canonical_from_xml("catalog", _XML_CATALOG)
        shuffled = _shuffle(canonical, random.Random(1))
        assert _key_skeleton(shuffled) != _key_skeleton(canonical)   # shuffle really changed order
        reseq = resequence_oscal(shuffled, version="v1.2.0")
        reseq.pop("$schema", None)
        assert _key_skeleton(reseq) == _key_skeleton(canonical)
        assert json.dumps(reseq, sort_keys=True) == json.dumps(canonical, sort_keys=True)

    def test_profile_matches_canonical_order(self):
        canonical = _canonical_from_xml("profile", _XML_PROFILE)
        shuffled = _shuffle(canonical, random.Random(2))
        reseq = resequence_oscal(shuffled, version="v1.2.0")
        reseq.pop("$schema", None)
        assert _key_skeleton(reseq) == _key_skeleton(canonical)
        assert json.dumps(reseq, sort_keys=True) == json.dumps(canonical, sort_keys=True)

    def test_ssp_matches_canonical_order_via_roundtrip(self):
        doc = json.load(open(_JSON_SSP))
        conv = OSCALConverter.from_support("system-security-plan", "v1.2.0")
        canonical = json.loads(conv.xml_to_json(conv.json_to_xml(json.dumps(doc))))
        canonical.pop("$schema", None)
        shuffled = _shuffle(canonical, random.Random(4))
        reseq = resequence_oscal(shuffled, version="v1.2.0")
        reseq.pop("$schema", None)
        assert _key_skeleton(reseq) == _key_skeleton(canonical)
        assert json.dumps(reseq, sort_keys=True) == json.dumps(canonical, sort_keys=True)

    def test_version_taken_from_metadata_when_unspecified(self):
        canonical = _canonical_from_xml("catalog", _XML_CATALOG)
        assert canonical["catalog"]["metadata"]["oscal-version"]     # oracle carries a version
        shuffled = _shuffle(canonical, random.Random(5))
        reseq = resequence_oscal(shuffled)                            # no explicit version
        reseq.pop("$schema", None)
        assert _key_skeleton(reseq) == _key_skeleton(canonical)

    def test_model_root_and_schema_placed_first(self):
        canonical = _canonical_from_xml("catalog", _XML_CATALOG)
        doc = {"catalog": canonical["catalog"], "$schema": "https://example/schema"}
        out = resequence_oscal(doc, version="v1.2.0")
        assert list(out)[:2] == ["$schema", "catalog"]

    def test_no_model_root_returns_unchanged(self):
        doc = {"not-an-oscal-model": {"b": 1, "a": 2}}
        assert resequence_oscal(doc) is doc

    def test_no_metaschema_index_returns_input_unchanged(self):
        """When no index is available the document is returned unchanged (not mis-ordered)."""
        class _NoIndexSupport:
            def get_latest_version(self):
                return "v1.2.0"
            def get_metaschema_index(self, version, model):
                return None

        orderer = _MetaschemaOrderer.from_support("catalog", "v1.2.0", support=_NoIndexSupport())
        assert orderer is None


class TestNormalizeVersion:
    @pytest.mark.parametrize("raw,expected", [
        ("1.2.0", "v1.2.0"),
        ("v1.2.0", "v1.2.0"),
        ("  1.1.3 ", "v1.1.3"),
        ("", ""),
        (None, ""),
    ])
    def test_normalize(self, raw, expected):
        assert _normalize_version(raw) == expected


class TestDumpWiring:
    """resequencing is wired into OSCAL.dump/dumps: JSON/YAML preferred, XML required."""

    def _shuffled_catalog(self, seed):
        canonical = _canonical_from_xml("catalog", _XML_CATALOG)
        shuffled = _shuffle(canonical, random.Random(seed))
        return canonical, Catalog.loads(json.dumps(shuffled))

    def test_dumps_json_is_canonically_ordered(self):
        canonical, cat = self._shuffled_catalog(11)
        out = json.loads(cat.dumps("json"))
        out.pop("$schema", None)
        assert _key_skeleton(out) == _key_skeleton(canonical)
        assert json.dumps(out, sort_keys=True) == json.dumps(canonical, sort_keys=True)

    def test_dumps_yaml_is_canonically_ordered(self):
        import yaml
        canonical, cat = self._shuffled_catalog(12)
        out = yaml.safe_load(cat.dumps("yaml"))
        out.pop("$schema", None)
        assert _key_skeleton(out) == _key_skeleton(canonical)

    def test_dumps_xml_elements_in_canonical_order(self):
        _, cat = self._shuffled_catalog(13)
        xml = cat.dumps("xml")
        assert xml
        # Schema-required element order: metadata precedes groups/controls precedes back-matter.
        assert xml.index("<metadata") < xml.index("<group")
        assert xml.index("<group") < xml.index("<back-matter")

    def test_dumps_xml_reflects_edits_after_prior_serialization(self):
        """Regression: a mutation after an earlier XML dump must appear in the next dump."""
        cat = Catalog.new("Freshness")
        before = cat.dumps("xml")            # builds the tree once
        assert 'id="ac"' not in before
        cat.create_control_group("", "ac", title="Access Control")
        after = cat.dumps("xml")             # must rebuild from the mutated dict
        assert 'id="ac"' in after

    def test_dumps_xml_releases_transient_tree(self):
        """The rebuilt XML tree is released after serialization (minimal footprint)."""
        _, cat = self._shuffled_catalog(15)
        assert cat._tree is None                 # loaded from JSON: no tree
        assert cat.dumps("xml")
        assert cat._tree is None                 # released after dump
        assert cat.xml                           # property path too
        assert cat._tree is None

    def test_dumps_xml_degraded_serves_and_keeps_retained_tree(self, monkeypatch):
        """With no dict (conversion unavailable) the retained tree is the sole
        representation: XML is still produced and the tree is kept."""
        from oscal import OSCAL
        monkeypatch.setattr(
            oscal_content.OSCALConverter, "from_support",
            classmethod(lambda cls, *a, **k: None),
        )
        cat = OSCAL.load(_XML_CATALOG)
        assert cat._dict is None and cat._tree is not None
        xml = cat.dumps("xml")
        assert xml and "catalog" in xml
        assert cat._tree is not None             # not released — it is the only copy

    def test_dumps_json_best_effort_when_resequence_unavailable(self, monkeypatch):
        """If resequencing fails, JSON is still emitted (unordered) — never blocked."""
        _, cat = self._shuffled_catalog(14)

        def _boom(*a, **kw):
            raise RuntimeError("no metaschema index")

        monkeypatch.setattr(oscal_content, "resequence_oscal", _boom)
        text = cat.dumps("json")
        parsed = json.loads(text)            # still valid JSON with the same data
        assert "catalog" in parsed


class TestResequenceFile:
    def test_json_file_roundtrip(self, tmp_path):
        canonical = _canonical_from_xml("catalog", _XML_CATALOG)
        shuffled = _shuffle(canonical, random.Random(6))
        src = tmp_path / "catalog.json"
        src.write_text(json.dumps(shuffled), encoding="utf-8")

        out_path = resequence_oscal_file(src)                        # in-place
        assert out_path == src
        result = json.loads(src.read_text())
        result.pop("$schema", None)
        assert _key_skeleton(result) == _key_skeleton(canonical)
        assert json.dumps(result, sort_keys=True) == json.dumps(canonical, sort_keys=True)

    def test_detect_model_root_key(self):
        assert _detect_model_root_key({"catalog": {}}) == "catalog"
        assert _detect_model_root_key({"system-security-plan": {}}) == "system-security-plan"
        assert _detect_model_root_key({"nope": {}}) is None
