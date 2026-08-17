"""
Unit tests for Catalog.insert_control() and Catalog.insert_group() — the
faithful-copy insertion path used by profile resolution (and, later, alters).

Covers:
    - inserting a whole control subtree (enhancements, parts, params, links) intact
    - shallow group insert (child groups/controls dropped) vs shallow=False (whole)
    - metaschema validation gate (reject invalid; validate=False bypasses)
    - id-collision, parent-not-found, controls/groups mix guards
    - safe-copy return (no aliasing into _dict)
    - read-only guard
    - round-trip fidelity after inserts
"""
import copy
import os

import pytest

from oscal import Catalog
from oscal.oscal_controls import format_index_errors


_HERE = os.path.dirname(__file__)


# ===========================================================================
# Fixtures / helpers
# ===========================================================================
@pytest.fixture
def cat():
    """Fresh writable catalog."""
    return Catalog.new("Insert Test Catalog")


def _control(cid="ac-1"):
    """A well-formed control with a param, a statement part, and an enhancement."""
    return {
        "id": cid,
        "title": "Policy and Procedures",
        "params": [{"id": f"{cid}_prm_1", "label": "organization-defined personnel"}],
        "props": [{"name": "label", "value": cid.upper()}],
        "parts": [{"id": f"{cid}_smt", "name": "statement", "prose": "Develop and document."}],
        "controls": [
            {
                "id": f"{cid}.1",
                "title": "Enhancement",
                "parts": [{"id": f"{cid}.1_smt", "name": "statement", "prose": "Sub."}],
            }
        ],
    }


def _group(gid="ac"):
    # A group holds EITHER groups OR controls, never both (metaschema choice).
    return {
        "id": gid,
        "class": "family",
        "title": "Access Control",
        "props": [{"name": "label", "value": gid.upper()}],
        "controls": [{"id": f"{gid}-99", "title": "child"}],
    }


# ===========================================================================
# insert_control
# ===========================================================================
class TestInsertControl:

    def test_inserts_and_findable(self, cat):
        assert cat.insert_control("[root]", _control()) is not None
        assert cat.get_control_by_id("ac-1") is not None

    def test_subtree_preserved_whole(self, cat):
        cat.insert_control("[root]", _control())
        got = cat.get_control_by_id("ac-1")
        assert got["params"][0]["id"] == "ac-1_prm_1"
        assert got["parts"][0]["name"] == "statement"
        # nested enhancement carried through intact
        assert cat.get_control_by_id("ac-1.1") is not None

    def test_enhancement_nesting_under_control(self, cat):
        """A control inserted under another control models an enhancement."""
        cat.insert_control("[root]", {"id": "ac-2", "title": "Account Mgmt"})
        assert cat.insert_control("ac-2", {"id": "ac-2.1", "title": "Automated"}) is not None
        parent = cat.get_control_by_id("ac-2")
        assert parent["controls"][0]["id"] == "ac-2.1"

    def test_returns_safe_copy(self, cat):
        cat.insert_control("[root]", {"id": "ac-3", "title": "orig"})
        returned = cat.get_control_by_id("ac-3")
        returned["title"] = "MUTATED"
        assert cat.get_control_by_id("ac-3")["title"] == "orig"

    def test_input_not_aliased(self, cat):
        """Mutating the caller's dict after insert must not change the catalog."""
        src = {"id": "ac-4", "title": "orig"}
        cat.insert_control("[root]", src)
        src["title"] = "CHANGED"
        assert cat.get_control_by_id("ac-4")["title"] == "orig"

    # --- guards ---
    def test_rejects_non_dict(self, cat):
        assert cat.insert_control("[root]", ["not", "a", "dict"]) is None

    def test_rejects_missing_id(self, cat):
        assert cat.insert_control("[root]", {"title": "no id"}) is None

    def test_rejects_duplicate_id(self, cat):
        cat.insert_control("[root]", {"id": "ac-1", "title": "first"})
        assert cat.insert_control("[root]", {"id": "ac-1", "title": "second"}) is None

    def test_rejects_missing_parent(self, cat):
        assert cat.insert_control("nope", {"id": "ac-1", "title": "x"}) is None

    def test_rejects_mix_with_groups(self, cat):
        cat.insert_group("[root]", {"id": "ac", "title": "grp"})
        # root now has a group; a root control would mix (not allowed at any level)
        assert cat.insert_control("[root]", {"id": "ac-1", "title": "x"}) is None

    # --- validation gate ---
    def test_validation_rejects_bad_token_id(self, cat):
        assert cat.insert_control("[root]", {"id": "bad id with spaces", "title": "x"}) is None

    def test_validate_false_bypasses(self, cat):
        assert cat.insert_control("[root]", {"id": "bad id with spaces", "title": "x"},
                                  validate=False) is not None

    def test_read_only_guard(self, cat):
        cat.is_read_only = True
        assert cat.insert_control("[root]", {"id": "ac-1", "title": "x"}) is None


# ===========================================================================
# insert_group
# ===========================================================================
class TestInsertGroup:

    def test_shallow_drops_children(self, cat):
        g = cat.insert_group("[root]", _group())
        assert g is not None
        assert "controls" not in g and "groups" not in g
        # intrinsic content kept
        assert g["title"] == "Access Control"
        assert cat.get_group_by_id("ac") is not None
        assert cat.get_control_by_id("ac-99") is None  # child was dropped

    def test_deep_insert_keeps_children(self, cat):
        g = cat.insert_group("[root]", _group(), shallow=False)
        assert g is not None
        assert cat.get_control_by_id("ac-99") is not None

    def test_nested_group_under_group(self, cat):
        cat.insert_group("[root]", {"id": "ac", "title": "Access Control"})
        assert cat.insert_group("ac", {"id": "ac-sub", "title": "Sub"}) is not None
        assert cat.get_group_by_id("ac-sub") is not None

    def test_fill_after_shallow(self, cat):
        cat.insert_group("[root]", _group())            # shallow
        assert cat.insert_control("ac", _control("ac-1")) is not None
        assert cat.get_control_by_id("ac-1") is not None

    def test_returns_safe_copy(self, cat):
        cat.insert_group("[root]", {"id": "ac", "title": "orig"})
        returned = cat.get_group_by_id("ac")
        returned["title"] = "MUTATED"
        assert cat.get_group_by_id("ac")["title"] == "orig"

    # --- guards ---
    def test_rejects_missing_id(self, cat):
        assert cat.insert_group("[root]", {"title": "no id"}) is None

    def test_rejects_duplicate_id(self, cat):
        cat.insert_group("[root]", {"id": "ac", "title": "first"})
        assert cat.insert_group("[root]", {"id": "ac", "title": "second"}) is None

    def test_rejects_missing_parent(self, cat):
        assert cat.insert_group("nope", {"id": "ac", "title": "x"}) is None

    def test_rejects_mix_with_controls(self, cat):
        cat.insert_control("[root]", {"id": "ac-1", "title": "x"})
        assert cat.insert_group("[root]", {"id": "ac", "title": "grp"}) is None

    def test_validation_rejects_missing_title(self, cat):
        # group requires a title per metaschema
        assert cat.insert_group("[root]", {"id": "ac"}) is None

    def test_read_only_guard(self, cat):
        cat.is_read_only = True
        assert cat.insert_group("[root]", {"id": "ac", "title": "x"}) is None


# ===========================================================================
# Round-trip fidelity
# ===========================================================================
class TestRoundTrip:

    def test_json_round_trip_after_inserts(self, cat):
        cat.insert_group("[root]", _group())
        cat.insert_control("ac", _control("ac-1"))
        assert cat.validate() is True
        reloaded = Catalog.loads(cat.dumps(format="json"))
        assert reloaded.get_control_by_id("ac-1") is not None
        assert reloaded.get_control_by_id("ac-1.1") is not None
        assert reloaded.get_group_by_id("ac") is not None


# ===========================================================================
# format_index_errors helper
# ===========================================================================
class TestFormatIndexErrors:

    def test_empty(self):
        assert format_index_errors([]) == ""

    def test_renders_fields(self):
        errs = [{"error-type": "invalid-type", "location": "/catalog/control",
                 "field": "@id", "value": "bad id"}]
        out = format_index_errors(errs)
        assert "invalid-type" in out and "@id" in out and "bad id" in out
