"""
Unit tests for the import-selection authoring API on Profile:

* set_import_selection(..., include_with_children=, exclude_with_children=)  — boolean
  convenience for the with-child-controls flag (True->"yes", False->"no", None->leave).
* add_import_include / add_import_exclude  — append one select-control-by-id (ids and/or
  matching, own with_children; matching {pattern, remarks} preserved; empty placeholder
  dropped; include-all -> include-controls on first include add).
* remove_import_include / remove_import_exclude  — remove by (with-ids set + matching
  patterns) identity; no-op on no match; last effective include refused (atomic); exclude
  key dropped when emptied.
* preview_import_selection  — committed or hypothetical dry-run of resolved control ids.
"""
import json
import os
import tempfile

import pytest

from oscal import Profile

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1", "oscal-version": "1.1.3"}


def _catalog():
    return {"catalog": {
        "uuid": "10000000-0000-4000-8000-000000000001",
        "metadata": {"title": "C", **_META},
        "groups": [{"id": "ac", "title": "AC", "controls": [
            {"id": "ac-1", "title": "P", "controls": [{"id": "ac-1.1", "title": "E"}]},
            {"id": "ac-2", "title": "A"},
            {"id": "ac-20", "title": "Twenty"}]}]}}


@pytest.fixture
def prof():
    """A profile importing a catalog (not resolved yet); yields (profile, href)."""
    with tempfile.TemporaryDirectory() as d:
        cpath = os.path.join(d, "c.json")
        with open(cpath, "w") as fh:
            json.dump(_catalog(), fh)
        p = Profile.new("P")
        p.add_import(cpath, include_all=False)
        p.set_merge(as_is=True)
        yield p, cpath


def _inc(p, href):
    return p.get_import_selection(href).get("include-controls", [])


def _exc(p, href):
    return p.get_import_selection(href).get("exclude-controls")


# ===========================================================================
class TestSetBooleans:
    def test_include_true_sets_yes(self, prof):
        p, h = prof
        r = p.set_import_selection(h, include_controls=[{"with-ids": ["ac-1"]}],
                                   include_with_children=True)
        assert r["include-controls"][0]["with-child-controls"] == "yes"

    def test_include_false_sets_explicit_no(self, prof):
        p, h = prof
        r = p.set_import_selection(h, include_controls=[{"with-ids": ["ac-1"]}],
                                   include_with_children=False)
        assert r["include-controls"][0]["with-child-controls"] == "no"

    def test_none_leaves_as_authored(self, prof):
        p, h = prof
        r = p.set_import_selection(h, include_controls=[{"with-ids": ["ac-1"],
                                                         "with-child-controls": "yes"}])
        assert r["include-controls"][0]["with-child-controls"] == "yes"
        r2 = p.set_import_selection(h, include_controls=[{"with-ids": ["ac-1"]}])
        assert "with-child-controls" not in r2["include-controls"][0]

    def test_exclude_boolean(self, prof):
        p, h = prof
        r = p.set_import_selection(h, include_all={}, exclude_controls=[{"with-ids": ["ac-2"]}],
                                   exclude_with_children=True)
        assert r["exclude-controls"][0]["with-child-controls"] == "yes"


# ===========================================================================
class TestToggleWithChildren:
    def _prepared(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"])
        p.add_import_exclude(h, ids=["ac-2"])
        return p, h

    def test_include_only_leaves_exclude_untouched(self, prof):
        p, h = self._prepared(prof)
        r = p.set_import_with_children(h, include=True)
        assert r["include-controls"][0]["with-child-controls"] == "yes"
        assert "with-child-controls" not in r["exclude-controls"][0]   # independent

    def test_exclude_only_leaves_include_untouched(self, prof):
        p, h = self._prepared(prof)
        r = p.set_import_with_children(h, exclude=True)
        assert r["exclude-controls"][0]["with-child-controls"] == "yes"
        assert "with-child-controls" not in r["include-controls"][0]   # independent

    def test_both_independently(self, prof):
        p, h = self._prepared(prof)
        r = p.set_import_with_children(h, include=True, exclude=False)
        assert r["include-controls"][0]["with-child-controls"] == "yes"
        assert r["exclude-controls"][0]["with-child-controls"] == "no"

    def test_selection_otherwise_preserved(self, prof):
        p, h = self._prepared(prof)
        r = p.set_import_with_children(h, include=True)
        assert r["include-controls"][0]["with-ids"] == ["ac-1"]
        assert r["exclude-controls"][0]["with-ids"] == ["ac-2"]        # exclude not dropped

    def test_false_sets_explicit_no(self, prof):
        p, h = self._prepared(prof)
        r = p.set_import_with_children(h, include=False)
        assert r["include-controls"][0]["with-child-controls"] == "no"

    def test_both_none_is_noop_none(self, prof):
        p, h = self._prepared(prof)
        assert p.set_import_with_children(h) is None

    def test_no_import_returns_none(self, prof):
        p, _h = prof
        assert p.set_import_with_children("nope.json", include=True) is None


# ===========================================================================
class TestAdd:
    def test_add_include_drops_placeholder(self, prof):
        p, h = prof
        assert _inc(p, h) == [{"with-ids": []}]           # add_import seeded placeholder
        r = p.add_import_include(h, ids=["ac-1"], with_children=True)
        assert r["include-controls"] == [{"with-ids": ["ac-1"], "with-child-controls": "yes"}]

    def test_add_two_includes_accumulate(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"])
        p.add_import_include(h, ids=["ac-2"])
        assert [e.get("with-ids") for e in _inc(p, h)] == [["ac-1"], ["ac-2"]]

    def test_matching_remarks_preserved(self, prof):
        p, h = prof
        r = p.add_import_include(h, matching=[{"pattern": "ac-*", "remarks": "all ac"}])
        assert r["include-controls"][-1]["matching"] == [{"pattern": "ac-*", "remarks": "all ac"}]

    def test_matching_string_shorthand(self, prof):
        p, h = prof
        r = p.add_import_include(h, matching=["ac-2"])
        assert r["include-controls"][-1]["matching"] == [{"pattern": "ac-2"}]

    def test_with_children_none_omits(self, prof):
        p, h = prof
        r = p.add_import_include(h, ids=["ac-1"])
        assert "with-child-controls" not in r["include-controls"][-1]

    def test_add_exclude_preserves_include(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"])
        r = p.add_import_exclude(h, ids=["ac-2"], with_children=False)
        assert [e.get("with-ids") for e in r["include-controls"]] == [["ac-1"]]
        assert r["exclude-controls"] == [{"with-ids": ["ac-2"], "with-child-controls": "no"}]

    def test_include_add_converts_include_all(self, prof):
        p, h = prof
        p.set_import_selection(h, include_all={})
        r = p.add_import_include(h, ids=["ac-1"])
        assert "include-all" not in r and r["include-controls"] == [{"with-ids": ["ac-1"]}]

    def test_requires_ids_or_matching(self, prof):
        p, h = prof
        assert p.add_import_include(h) is None

    def test_bad_ids_type_rejected(self, prof):
        p, h = prof
        assert p.add_import_include(h, ids="ac-1") is None


# ===========================================================================
class TestRemove:
    def test_remove_include_by_ids(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"])
        p.add_import_include(h, ids=["ac-2"])
        r = p.remove_import_include(h, ids=["ac-1"])
        assert [e.get("with-ids") for e in r["include-controls"]] == [["ac-2"]]

    def test_remove_ignores_flag_and_remarks(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"], with_children=True)   # entry has the flag
        p.add_import_include(h, ids=["ac-2"])
        r = p.remove_import_include(h, ids=["ac-1"])               # removed without the flag
        assert [e.get("with-ids") for e in r["include-controls"]] == [["ac-2"]]

    def test_remove_by_matching_pattern(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"])
        p.add_import_include(h, matching=[{"pattern": "ac-*", "remarks": "x"}])
        r = p.remove_import_include(h, matching=["ac-*"])          # identity by pattern only
        assert len(r["include-controls"]) == 1 and r["include-controls"][0]["with-ids"] == ["ac-1"]

    def test_no_match_is_noop(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"])
        assert p.remove_import_include(h, ids=["zz-9"]) is None
        assert [e.get("with-ids") for e in _inc(p, h)] == [["ac-1"]]   # unchanged

    def test_remove_last_include_refused_atomic(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"])
        before = _inc(p, h)
        assert p.remove_import_include(h, ids=["ac-1"]) is None
        assert _inc(p, h) == before                               # rolled back

    def test_remove_exclude_drops_key_when_empty(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"])
        p.add_import_exclude(h, ids=["ac-2"])
        r = p.remove_import_exclude(h, ids=["ac-2"])
        assert "exclude-controls" not in r                        # last exclusion -> key gone
        assert [e.get("with-ids") for e in r["include-controls"]] == [["ac-1"]]


# ===========================================================================
class TestPreview:
    def test_committed_preview(self, prof):
        p, h = prof
        p.add_import_include(h, ids=["ac-1"], with_children=True)
        p.resolve()
        assert p.preview_import_selection(h)["selected"] == ["ac-1", "ac-1.1"]

    def test_hypothetical_greedy_glob_visible(self, prof):
        p, h = prof
        p.resolve()
        res = p.preview_import_selection(h, include_controls=[{"matching": [{"pattern": "ac-2*"}]}])
        assert res["selected"] == ["ac-2", "ac-20"]               # the * over-match is visible

    def test_hypothetical_with_children_overlay(self, prof):
        p, h = prof
        p.resolve()
        res = p.preview_import_selection(h, include_controls=[{"with-ids": ["ac-1"]}],
                                         include_with_children=True)
        assert res["selected"] == ["ac-1", "ac-1.1"]

    def test_preview_works_before_profile_resolve(self, prof):
        # add_import already loads the source catalog, so preview needs no profile.resolve();
        # the committed selection here is the empty placeholder -> nothing selected.
        p, h = prof
        assert p.preview_import_selection(h) == {"selected": [], "warnings": []}
        # and a hypothetical still resolves against the loaded source
        res = p.preview_import_selection(h, include_controls=[{"with-ids": ["ac-1"]}])
        assert res["selected"] == ["ac-1"]

    def test_unknown_href_returns_none(self, prof):
        p, _h = prof
        assert p.preview_import_selection("nope.json") is None
