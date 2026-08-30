"""
Unit tests for Profile merge-directive reflection and import-selection editing:

    - ``Profile.merge_directive`` attribute (as-is / flat / custom), populated on load
      and kept in sync after merge edits + round-trips.
    - ``set_merge_directive()`` convenience wrapper (preserves combine / reuses custom).
    - ``get_import_selection()`` — safe-copy fetch of include-all/include-controls/
      exclude-controls for an import identified by any valid href.
    - ``set_import_selection()`` — validated wholesale replacement of those structures,
      including the include-all XOR include-controls choice constraint and scope side
      effects (controls_tree rebuild, resolved catalog dropped).
"""
import copy
import os

import pytest

from oscal import Profile


# ===========================================================================
# Fixtures / helpers
# ===========================================================================
_OVERLAY = os.path.join(os.path.dirname(__file__), "..", "test-data",
                        "overlay-chain", "overlay-profile.json")


@pytest.fixture
def overlay():
    """A loaded profile whose first import (``base-catalog.json``) uses include-controls."""
    return Profile.load(_OVERLAY)


def _imports(p):
    return p._dict["profile"]["imports"]


def _new_with_import(include_all=False):
    """Fresh writable profile with a single import; returns (profile, href)."""
    p = Profile.new("Selection Test Profile")
    r = p.add_import("catalog.json", include_all=include_all)
    return p, r.entry["href"]


# ===========================================================================
# merge_directive attribute
# ===========================================================================
class TestMergeDirectiveAttribute:

    def test_loaded_profile_reflects_as_is(self, overlay):
        assert overlay.merge_directive == "as-is"

    def test_new_profile_defaults_as_is(self):
        assert Profile.new("P").merge_directive == "as-is"

    def test_reflects_flat(self):
        p = Profile.new("P")
        p.add_import("c.json", include_all=True)
        p.set_merge(flat=True)
        assert p.merge_directive == "flat"

    def test_reflects_custom(self):
        p = Profile.new("P")
        p.add_import("c.json", include_all=True)
        p.set_merge(custom={"groups": []})
        assert p.merge_directive == "custom"

    def test_legacy_as_is_false_reported_as_flat(self):
        """A serialized ``as-is: false`` is processed as flat and reported as such."""
        p = Profile.new("P")
        p._dict["profile"]["merge"] = {"as-is": False}
        assert p._refresh_merge_directive() == "flat"

    def test_survives_round_trip(self):
        p = Profile.new("P")
        p.add_import("c.json", include_all=True)
        p.set_merge(flat=True)
        assert Profile.loads(p.dumps()).merge_directive == "flat"


# ===========================================================================
# set_merge_directive()
# ===========================================================================
class TestSetMergeDirective:

    def test_switch_to_flat_updates_attr_and_content(self, overlay):
        assert overlay.set_merge_directive("flat") is not None
        assert overlay.merge_directive == "flat"
        assert "flat" in overlay._dict["profile"]["merge"]

    def test_preserves_existing_combine(self):
        p = Profile.new("P")
        p.add_import("c.json", include_all=True)
        p.set_merge(as_is=True, combine="use-first")
        p.set_merge_directive("flat")
        assert p._dict["profile"]["merge"]["combine"] == {"method": "use-first"}

    def test_combine_override(self):
        p = Profile.new("P")
        p.add_import("c.json", include_all=True)
        p.set_merge(as_is=True, combine="use-first")
        p.set_merge_directive("flat", combine="keep")
        assert p._dict["profile"]["merge"]["combine"] == {"method": "keep"}

    def test_custom_reuses_existing_object(self):
        """Re-issuing 'custom' (e.g. to change combine) keeps the existing custom object."""
        p = Profile.new("P")
        p.add_import("c.json", include_all=True)
        p.set_merge(custom={"groups": [{"id": "g1", "title": "G1"}]})
        # No custom re-supplied — the object already on the profile must be reused.
        r = p.set_merge_directive("custom", combine="keep")
        assert r is not None
        assert p.merge_directive == "custom"
        assert p._dict["profile"]["merge"]["custom"] == {"groups": [{"id": "g1", "title": "G1"}]}
        assert p._dict["profile"]["merge"]["combine"] == {"method": "keep"}

    def test_custom_without_object_fails(self, overlay):
        # overlay has an as-is directive, no custom object to reuse
        assert overlay.set_merge_directive("custom") is None
        assert overlay.merge_directive == "as-is"  # unchanged

    def test_invalid_directive_returns_none(self, overlay):
        assert overlay.set_merge_directive("bogus") is None
        assert overlay.merge_directive == "as-is"

    def test_read_only_guard(self, overlay):
        overlay.is_read_only = True
        assert overlay.set_merge_directive("flat") is None
        assert overlay.merge_directive == "as-is"


# ===========================================================================
# get_import_selection()
# ===========================================================================
class TestGetImportSelection:

    def test_returns_include_controls_only(self, overlay):
        sel = overlay.get_import_selection("base-catalog.json")
        assert "include-controls" in sel
        assert "include-all" not in sel
        assert sel["include-controls"][0]["with-ids"][0] == "ac-1"

    def test_unknown_href_returns_none(self, overlay):
        assert overlay.get_import_selection("does-not-exist.json") is None

    def test_returns_safe_copy(self, overlay):
        sel = overlay.get_import_selection("base-catalog.json")
        sel["include-controls"][0]["with-ids"].append("INJECTED")
        again = overlay.get_import_selection("base-catalog.json")
        assert "INJECTED" not in again["include-controls"][0]["with-ids"]

    def test_include_all_import(self):
        p, href = _new_with_import(include_all=True)
        sel = p.get_import_selection(href)
        assert sel == {"include-all": {}}

    def test_locate_by_fragment_href(self):
        """A fresh add_import stores a '#uuid' href; the getter finds it literally."""
        p, href = _new_with_import(include_all=True)
        assert href.startswith("#")
        assert p.get_import_selection(href) is not None

    def test_empty_selection_returns_empty_dict(self):
        p, href = _new_with_import(include_all=True)
        # strip the selection to simulate an import with none
        _imports(p)[0].pop("include-all", None)
        assert p.get_import_selection(href) == {}


# ===========================================================================
# set_import_selection()
# ===========================================================================
class TestSetImportSelection:

    def test_replace_include_controls(self, overlay):
        r = overlay.set_import_selection(
            "base-catalog.json",
            include_controls=[{"with-ids": ["ac-1", "ac-2"]}],
        )
        assert r is not None
        sel = overlay.get_import_selection("base-catalog.json")
        assert sel["include-controls"] == [{"with-ids": ["ac-1", "ac-2"]}]

    def test_switch_to_include_all_drops_include_controls(self, overlay):
        overlay.set_import_selection("base-catalog.json", include_all={})
        sel = overlay.get_import_selection("base-catalog.json")
        assert sel == {"include-all": {}}

    def test_add_exclude_controls(self, overlay):
        overlay.set_import_selection(
            "base-catalog.json",
            include_all={},
            exclude_controls=[{"with-ids": ["ac-2"]}],
        )
        sel = overlay.get_import_selection("base-catalog.json")
        assert sel["exclude-controls"] == [{"with-ids": ["ac-2"]}]

    def test_href_preserved(self, overlay):
        overlay.set_import_selection("base-catalog.json", include_all={})
        assert _imports(overlay)[0]["href"] == "base-catalog.json"

    def test_both_include_forms_rejected(self, overlay):
        before = copy.deepcopy(_imports(overlay)[0])
        r = overlay.set_import_selection(
            "base-catalog.json",
            include_all={},
            include_controls=[{"with-ids": ["ac-1"]}],
        )
        assert r is None
        assert _imports(overlay)[0] == before  # unchanged

    def test_neither_include_form_rejected(self, overlay):
        before = copy.deepcopy(_imports(overlay)[0])
        r = overlay.set_import_selection(
            "base-catalog.json",
            exclude_controls=[{"with-ids": ["ac-1"]}],
        )
        assert r is None
        assert _imports(overlay)[0] == before

    def test_unknown_href_returns_none(self, overlay):
        assert overlay.set_import_selection("nope.json", include_all={}) is None

    @pytest.mark.parametrize("kwargs", [
        {"include_all": ["not", "a", "dict"]},
        {"include_controls": {"not": "a list"}},
        {"include_all": {}, "exclude_controls": "not a list"},
    ])
    def test_wrong_argument_types_rejected(self, overlay, kwargs):
        before = copy.deepcopy(_imports(overlay)[0])
        assert overlay.set_import_selection("base-catalog.json", **kwargs) is None
        assert _imports(overlay)[0] == before

    def test_read_only_guard(self, overlay):
        overlay.is_read_only = True
        before = copy.deepcopy(_imports(overlay)[0])
        assert overlay.set_import_selection("base-catalog.json", include_all={}) is None
        assert _imports(overlay)[0] == before

    def test_returns_safe_copy(self, overlay):
        r = overlay.set_import_selection(
            "base-catalog.json", include_controls=[{"with-ids": ["ac-1"]}])
        r["include-controls"][0]["with-ids"].append("INJECTED")
        sel = overlay.get_import_selection("base-catalog.json")
        assert "INJECTED" not in sel["include-controls"][0]["with-ids"]

    def test_scope_change_rebuilds_tree_and_drops_resolution(self, overlay):
        overlay.resolve()
        assert overlay.catalog is not None
        overlay.set_import_selection(
            "base-catalog.json", include_controls=[{"with-ids": ["ac-1"]}])
        assert overlay.catalog is None          # resolved catalog dropped
        assert overlay._tree_dirty is False     # controls_tree rebuilt eagerly

    def test_round_trip_valid_after_edit(self, overlay):
        overlay.set_import_selection(
            "base-catalog.json", include_controls=[{"with-ids": ["ac-1"]}])
        reloaded = Profile.loads(overlay.dumps())
        assert reloaded.is_valid
        assert reloaded.get_import_selection("base-catalog.json")["include-controls"] \
            == [{"with-ids": ["ac-1"]}]


# ===========================================================================
# set_import_selection() — metaschema sanitization (no blind pass-through)
# ===========================================================================
class TestImportSelectionSanitization:

    def test_unknown_keys_are_dropped_not_stored(self, overlay):
        r = overlay.set_import_selection(
            "base-catalog.json",
            include_controls=[{"with-ids": ["ac-1"], "BOGUS": 123, "evil": {"x": 1}}],
        )
        assert r is not None
        assert r["include-controls"] == [{"with-ids": ["ac-1"]}]

    def test_nested_unknown_keys_dropped(self, overlay):
        r = overlay.set_import_selection(
            "base-catalog.json",
            include_controls=[{"matching": [{"pattern": "ac-*", "NOPE": 1}]}],
        )
        assert r["include-controls"] == [{"matching": [{"pattern": "ac-*"}]}]

    def test_junk_include_all_pruned_to_empty(self, overlay):
        r = overlay.set_import_selection("base-catalog.json",
                                         include_all={"junk": 1, "more": 2})
        assert r["include-all"] == {}

    def test_unknown_top_level_import_key_dropped(self, overlay):
        """The whole import is staged, so a non-schema key on the statement itself is
        dropped while href and the valid selection are kept."""
        _imports(overlay)[0]["BOGUS_TOP"] = "x"
        r = overlay.set_import_selection("base-catalog.json",
                                         include_controls=[{"with-ids": ["ac-1"]}])
        assert r is not None
        assert "BOGUS_TOP" not in r
        assert r["href"] == "base-catalog.json"
        assert "BOGUS_TOP" not in _imports(overlay)[0]

    def test_allowed_keys_and_hierarchy_preserved(self, overlay):
        payload = [{"with-child-controls": "yes",
                    "with-ids": ["ac-1"],
                    "matching": [{"pattern": "ac-*"}]}]
        r = overlay.set_import_selection("base-catalog.json", include_controls=payload)
        assert r["include-controls"] == payload

    def test_array_field_given_scalar_rejected(self, overlay):
        # with-ids is an array; a scalar is a structural error, not silently coerced
        before = copy.deepcopy(_imports(overlay)[0])
        assert overlay.set_import_selection(
            "base-catalog.json", include_controls=[{"with-ids": "ac-1"}]) is None
        assert _imports(overlay)[0] == before

    def test_scalar_field_given_object_rejected(self, overlay):
        before = copy.deepcopy(_imports(overlay)[0])
        assert overlay.set_import_selection(
            "base-catalog.json",
            include_controls=[{"with-ids": [{"nested": "object"}]}]) is None
        assert _imports(overlay)[0] == before

    def test_bad_enum_value_rejected(self, overlay):
        # with-child-controls allows only yes/no (a choice-member field, so this must be
        # validated directly — the import-level walk skips choice members)
        before = copy.deepcopy(_imports(overlay)[0])
        assert overlay.set_import_selection(
            "base-catalog.json",
            include_controls=[{"with-child-controls": "maybe", "with-ids": ["ac-1"]}]) is None
        assert _imports(overlay)[0] == before

    def test_bad_enum_in_exclude_controls_rejected(self, overlay):
        before = copy.deepcopy(_imports(overlay)[0])
        assert overlay.set_import_selection(
            "base-catalog.json",
            include_all={},
            exclude_controls=[{"with-child-controls": "bogus", "with-ids": ["ac-1"]}]) is None
        assert _imports(overlay)[0] == before


# ===========================================================================
# set_import_selection() — staging/rollback + required-content guarantees
# ===========================================================================
class TestImportSelectionStagingAndRequired:

    def test_partial_invalid_commits_nothing(self, overlay):
        """A valid include paired with an invalid exclude must roll back entirely —
        the valid part is not partially committed."""
        before = copy.deepcopy(_imports(overlay)[0])
        r = overlay.set_import_selection(
            "base-catalog.json",
            include_controls=[{"with-ids": ["ac-1"]}],            # valid
            exclude_controls=[{"with-child-controls": "BAD"}],   # invalid enum
        )
        assert r is None
        assert _imports(overlay)[0] == before   # atomic rollback

    def test_rejection_does_not_drop_resolution(self, overlay):
        """A rejected edit must not have side effects (resolution stays intact)."""
        overlay.resolve()
        assert overlay.catalog is not None
        overlay.set_import_selection("base-catalog.json",
                                     include_controls=[{"with-ids": "scalar-not-array"}])
        assert overlay.catalog is not None   # unchanged — no commit happened

    def test_neither_include_form_is_a_minimum_requirement(self, overlay):
        """An import must select via include-all or include-controls; neither fails even
        when a valid exclude-controls is supplied."""
        before = copy.deepcopy(_imports(overlay)[0])
        r = overlay.set_import_selection(
            "base-catalog.json",
            exclude_controls=[{"with-ids": ["ac-1"]}],   # valid on its own
        )
        assert r is None
        assert _imports(overlay)[0] == before

    def test_empty_call_fails_minimum_requirement(self, overlay):
        """No selection at all leaves neither include form present -> rejected."""
        before = copy.deepcopy(_imports(overlay)[0])
        assert overlay.set_import_selection("base-catalog.json") is None
        assert _imports(overlay)[0] == before

    def test_input_object_not_mutated_by_staging(self, overlay):
        """Staging works on a copy: the caller's dict is never pruned in place."""
        payload = [{"with-ids": ["ac-1"], "BOGUS": 1}]
        overlay.set_import_selection("base-catalog.json", include_controls=payload)
        assert payload == [{"with-ids": ["ac-1"], "BOGUS": 1}]   # caller's object intact


# ===========================================================================
# _stage_against_index — the general staging gate, exercised directly
# ===========================================================================
class TestStagingGate:

    @pytest.fixture
    def import_node(self, overlay):
        return overlay._import_index_node()

    def _child(self, overlay, node, key):
        return overlay._find_child_node(node, key)

    def test_prunes_and_reports_dropped(self, overlay, import_node):
        node = self._child(overlay, import_node, "include-controls")
        clean, dropped, errors = overlay._stage_against_index(
            {"with-ids": ["ac-1"], "BOGUS": 1}, node, "/inc")
        assert clean == {"with-ids": ["ac-1"]}
        assert dropped == ["/inc/BOGUS"]
        assert errors == []

    def test_does_not_mutate_input(self, overlay, import_node):
        node = self._child(overlay, import_node, "include-controls")
        src = {"with-ids": ["ac-1"], "BOGUS": 1}
        overlay._stage_against_index(src, node, "/inc")
        assert src == {"with-ids": ["ac-1"], "BOGUS": 1}

    def test_reports_shape_error_without_validating(self, overlay, import_node):
        node = self._child(overlay, import_node, "include-controls")
        clean, dropped, errors = overlay._stage_against_index(
            {"with-ids": "scalar"}, node, "/inc")
        assert errors and errors[0]["error-type"] == "invalid-type"

    def test_validates_required_choice_member_contents(self, overlay, import_node):
        """The gate reaches into a present choice branch that _walk_instance skips."""
        _, _, errors = overlay._stage_against_index(
            {"href": "x", "include-controls": [{"with-child-controls": "maybe",
                                                "with-ids": ["ac-1"]}]},
            import_node, "/import")
        assert any(e["error-type"] == "allowed-values" for e in errors)
