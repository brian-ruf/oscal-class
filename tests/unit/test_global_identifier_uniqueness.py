"""
Unit tests for the library-defined global identifier-uniqueness check
(:func:`oscal.oscal_references.evaluate_global_identifier_uniqueness`).

OSCAL expects every bare ``@id`` and every ``@uuid`` to be unique within a single document,
but the published metaschema does not encode that as an ``is-unique`` / ``index`` constraint,
so no metaschema-driven validator catches a collision. This library check fills the gap on the
``references`` validation dimension (``rule-source="library"``, never gating ``is_valid``).

Scope rules under test:
    * only the bare ``id`` and ``uuid`` fields count — scoped reference flags
      (``party-uuid``, ``component-uuid``, ``role-id``, ``control-id``, ``param-id``, …) are
      excluded (they legitimately repeat, and may recur across imported files);
    * ``id`` and ``uuid`` are pooled separately (an ``id`` never collides with a ``uuid``);
    * uniqueness is evaluated within one document body only.
"""
import json

import pytest

from oscal.oscal_implementation import ComponentDefinition
from oscal.oscal_references import evaluate_global_identifier_uniqueness


# ---------------------------------------------------------------------------
# Direct function tests
# ---------------------------------------------------------------------------
class TestEvaluateGlobalIdentifierUniqueness:

    def test_all_unique_no_findings(self):
        body = {"uuid": "u1", "groups": [{"id": "g1"}, {"id": "g2", "controls": [{"id": "c1"}]}]}
        assert evaluate_global_identifier_uniqueness(body, "/catalog") == []

    def test_duplicate_uuid_flagged(self):
        body = {"uuid": "dup", "back-matter": {"resources": [{"uuid": "dup"}]}}
        out = evaluate_global_identifier_uniqueness(body, "/catalog")
        assert len(out) == 1
        f = out[0]
        assert f["error-type"] == "duplicate-key"
        assert f["level"] == "ERROR"
        assert f["rule-source"] == "library"
        assert f["rule-id"] == "lib-global-unique-uuid"
        assert f["field"] == "uuid"
        assert f["value"] == "dup"
        # location points at the *second* occurrence; detail names the first.
        assert f["location"] == "/catalog/back-matter/resources[0]/uuid"
        assert "first seen at /catalog/uuid" in f["detail"]

    def test_duplicate_id_flagged(self):
        body = {"groups": [{"id": "ac"}, {"id": "ac"}]}
        out = evaluate_global_identifier_uniqueness(body, "/catalog")
        assert [f["rule-id"] for f in out] == ["lib-global-unique-id"]
        assert out[0]["value"] == "ac"
        assert out[0]["location"] == "/catalog/groups[1]/id"

    def test_three_occurrences_yield_two_findings(self):
        body = {"a": {"uuid": "x"}, "b": {"uuid": "x"}, "c": {"uuid": "x"}}
        out = evaluate_global_identifier_uniqueness(body, "/catalog")
        assert len(out) == 2  # every occurrence after the first

    def test_id_and_uuid_pooled_separately(self):
        # Same string used once as an id and once as a uuid is NOT a collision.
        body = {"uuid": "shared", "groups": [{"id": "shared"}]}
        assert evaluate_global_identifier_uniqueness(body, "/catalog") == []

    def test_scoped_reference_flags_excluded(self):
        # party-uuid / component-uuid / role-id / control-id / param-id repeat legitimately.
        body = {
            "metadata": {"responsible-parties": [
                {"role-id": "admin", "party-uuids": ["p1"]},
                {"role-id": "admin", "party-uuids": ["p1"]},
            ]},
            "components": [
                {"by-components": [{"component-uuid": "k"}, {"component-uuid": "k"}]},
            ],
            "reqs": [{"control-id": "ac-2"}, {"control-id": "ac-2"}],
            "sp": [{"param-id": "prm"}, {"param-id": "prm"}],
        }
        assert evaluate_global_identifier_uniqueness(body, "/x") == []

    def test_non_dict_body_returns_empty(self):
        assert evaluate_global_identifier_uniqueness(None, "/catalog") == []
        assert evaluate_global_identifier_uniqueness([1, 2], "/catalog") == []

    def test_blank_values_ignored(self):
        body = {"uuid": "", "groups": [{"id": ""}, {"id": ""}]}
        assert evaluate_global_identifier_uniqueness(body, "/catalog") == []


# ---------------------------------------------------------------------------
# Integration via a loaded document's references dimension
# ---------------------------------------------------------------------------
_DUP_UUID = "aaaaaaaa-0000-4000-8000-000000000001"


def _cdef(second_component_uuid):
    """A fully valid cDef with two components; the second's uuid is a parameter so the
    duplicate case can be exercised without tripping any other validation phase."""
    return {"component-definition": {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "metadata": {"title": "T", "last-modified": "2026-01-01T00:00:00Z",
                     "version": "1.0", "oscal-version": "1.1.3"},
        "components": [
            {"uuid": _DUP_UUID, "type": "software", "title": "A", "description": "d"},
            {"uuid": second_component_uuid, "type": "software", "title": "B", "description": "d"},
        ]}}


class TestReferencesDimensionIntegration:

    def test_duplicate_uuid_surfaces_on_references_not_is_valid(self):
        cd = ComponentDefinition.loads(json.dumps(_cdef(_DUP_UUID)))
        # The document is structurally valid OSCAL — uniqueness never gates is_valid.
        assert cd.is_valid is True
        # But the references dimension flags the duplicate uuid.
        assert cd.validation_status["references"] is False
        dups = [f for f in cd.reference_findings if f.get("rule-id") == "lib-global-unique-uuid"]
        assert len(dups) == 1
        assert dups[0]["value"] == _DUP_UUID
        assert dups[0]["rule-source"] == "library"
        assert dups[0]["location"] == "/component-definition/components[1]/uuid"

    def test_clean_cdef_has_no_uniqueness_findings(self):
        cd = ComponentDefinition.loads(json.dumps(_cdef("aaaaaaaa-0000-4000-8000-000000000002")))
        assert cd.is_valid is True
        assert cd.validation_status["references"] is True
        assert [f for f in cd.reference_findings if "lib-global-unique" in str(f.get("rule-id"))] == []
