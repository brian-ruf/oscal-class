"""
Unit tests for authoring a Profile's ``modify`` directives:

    - set_parameter()      — upsert a set-parameter with per-field merge (value vs select)
    - add_alter()          — idempotent alter container
    - add_alter_adds()     — append an addition (adds), creating the alter as needed
    - add_alter_removes()  — append a removal (removes), creating the alter as needed
    - remove_alter_adds()  / remove_alter_removes() — selector-matched deletion with cleanup

Authoring builds each structure and validates it through the metaschema staging gate;
control/param ids need not exist in scope (these are directives).
"""
import copy

import pytest

from oscal import Profile


# ===========================================================================
# Fixtures / helpers
# ===========================================================================
@pytest.fixture
def prof():
    p = Profile.new("Modify Authoring Test")
    p.add_import("cat.json", include_all=True)
    p.is_unsaved = False
    return p


def _modify(p):
    return p._dict["profile"].get("modify")


def _setps(p):
    return (_modify(p) or {}).get("set-parameters", [])


def _setp(p, param_id):
    return next((s for s in _setps(p) if s.get("param-id") == param_id), None)


def _alter(p, control_id):
    for a in (_modify(p) or {}).get("alters", []):
        if a.get("control-id") == control_id:
            return a
    return None


# ===========================================================================
# set_parameter()
# ===========================================================================
class TestSetParameter:

    def test_create_minimal(self, prof):
        r = prof.set_parameter("p1", values=["daily"])
        assert r == {"param-id": "p1", "values": ["daily"]}
        assert _setp(prof, "p1") == {"param-id": "p1", "values": ["daily"]}

    def test_create_populates_all_present_fields(self, prof):
        # a set-parameter prop in the OSCAL namespace must be named "marking"
        prof.set_parameter("p1", class_="c", label="L", usage="U",
                           props=[{"name": "marking", "value": "v"}], values=["x"])
        sp = _setp(prof, "p1")
        assert sp["class"] == "c" and sp["label"] == "L" and sp["usage"] == "U"
        assert sp["props"] == [{"name": "marking", "value": "v"}] and sp["values"] == ["x"]

    def test_update_overwrites_present_keeps_absent(self, prof):
        prof.set_parameter("p1", label="L", values=["a"])
        prof.set_parameter("p1", values=["b"])          # label omitted -> unchanged
        sp = _setp(prof, "p1")
        assert sp["values"] == ["b"] and sp["label"] == "L"

    def test_blank_param_id_rejected(self, prof):
        assert prof.set_parameter("", values=["x"]) is None
        assert _modify(prof) is None

    def test_values_and_select_mutually_exclusive(self, prof):
        assert prof.set_parameter("p1", values=["a"], select_choices=["b"]) is None
        assert _modify(prof) is None

    def test_values_replaces_select(self, prof):
        prof.set_parameter("p1", select_cardinality="one", select_choices=["a"])
        prof.set_parameter("p1", values=["v"])
        sp = _setp(prof, "p1")
        assert sp.get("values") == ["v"] and "select" not in sp

    def test_select_replaces_values(self, prof):
        prof.set_parameter("p1", values=["v"])
        prof.set_parameter("p1", select_cardinality="one-or-more", select_choices=["a", "b"])
        sp = _setp(prof, "p1")
        assert sp["select"] == {"how-many": "one-or-more", "choice": ["a", "b"]}
        assert "values" not in sp

    def test_select_partial_merge(self, prof):
        prof.set_parameter("p1", select_cardinality="one", select_choices=["a"])
        prof.set_parameter("p1", select_choices=["a", "b"])     # how-many omitted -> kept
        assert _setp(prof, "p1")["select"] == {"how-many": "one", "choice": ["a", "b"]}

    def test_wrong_type_rejected(self, prof):
        assert prof.set_parameter("p1", props={"not": "a list"}) is None
        assert _modify(prof) is None

    def test_unknown_keys_pruned(self, prof):
        prof.set_parameter("p1", props=[{"name": "marking", "value": "v", "BOGUS": 1}], values=["x"])
        assert _setp(prof, "p1")["props"] == [{"name": "marking", "value": "v"}]

    def test_invalid_select_enum_rejected_and_unchanged(self, prof):
        prof.set_parameter("p1", values=["v"])
        before = copy.deepcopy(_setp(prof, "p1"))
        assert prof.set_parameter("p1", select_cardinality="banana") is None
        assert _setp(prof, "p1") == before          # rollback

    def test_returns_safe_copy(self, prof):
        r = prof.set_parameter("p1", values=["a"])
        r["values"].append("INJECT")
        assert _setp(prof, "p1")["values"] == ["a"]

    def test_marks_unsaved(self, prof):
        prof.set_parameter("p1", values=["a"])
        assert prof.is_unsaved is True

    def test_read_only_guard(self, prof):
        prof.is_read_only = True
        assert prof.set_parameter("p1", values=["a"]) is None
        assert _modify(prof) is None

    def test_round_trip_valid(self, prof):
        prof.set_parameter("p1", label="Freq", values=["daily"],
                           constraints=[{"description": "must be set"}])
        assert Profile.loads(prof.dumps()).is_valid


# ===========================================================================
# add_alter()
# ===========================================================================
class TestAddAlter:

    def test_creates_empty_alter(self, prof):
        assert prof.add_alter("ac-1") == {"control-id": "ac-1"}
        assert _alter(prof, "ac-1") == {"control-id": "ac-1"}
        assert prof.is_unsaved is True

    def test_idempotent_no_unsaved(self, prof):
        prof.add_alter("ac-1")
        prof.is_unsaved = False
        prof.add_alter("ac-1")
        assert prof.is_unsaved is False
        assert len((_modify(prof) or {}).get("alters", [])) == 1

    def test_read_only_guard(self, prof):
        prof.is_read_only = True
        assert prof.add_alter("ac-1") is None

    def test_returns_safe_copy(self, prof):
        prof.add_alter("ac-1")
        a = prof.add_alter("ac-1")
        a["control-id"] = "MUTATED"
        assert _alter(prof, "ac-1")["control-id"] == "ac-1"


# ===========================================================================
# add_alter_adds()
# ===========================================================================
class TestAddAlterAdds:

    def test_creates_addition_and_alter(self, prof):
        r = prof.add_alter_adds("ac-1", position="after", by_id="ac-1_smt", title="New title")
        assert r["position"] == "after" and r["by-id"] == "ac-1_smt" and r["title"] == "New title"
        assert _alter(prof, "ac-1")["adds"] == [r]

    def test_requires_content(self, prof):
        assert prof.add_alter_adds("ac-1", position="after", by_id="x") is None
        assert _modify(prof) is None          # no empty alter left behind

    def test_wrong_type_rejected(self, prof):
        assert prof.add_alter_adds("ac-1", props="not a list") is None

    def test_prunes_unknown_keys(self, prof):
        r = prof.add_alter_adds("ac-1", by_id="x",
                                parts=[{"id": "p", "name": "guidance",
                                        "prose": "hi", "BOGUS": 1}])
        assert r["parts"] == [{"id": "p", "name": "guidance", "prose": "hi"}]

    def test_appends_to_existing_alter(self, prof):
        prof.add_alter_adds("ac-1", by_id="a", title="T1")
        prof.add_alter_adds("ac-1", by_id="b", title="T2")
        assert len(_alter(prof, "ac-1")["adds"]) == 2
        assert len((_modify(prof) or {}).get("alters", [])) == 1

    def test_invalid_enum_leaves_no_empty_alter(self, prof):
        assert prof.add_alter_adds("ac-1", position="sideways", by_id="x", title="T") is None
        assert _modify(prof) is None

    def test_marks_unsaved_and_safe_copy(self, prof):
        r = prof.add_alter_adds("ac-1", by_id="x", title="T")
        assert prof.is_unsaved is True
        r["title"] = "MUT"
        assert _alter(prof, "ac-1")["adds"][0]["title"] == "T"

    def test_read_only_guard(self, prof):
        prof.is_read_only = True
        assert prof.add_alter_adds("ac-1", by_id="x", title="T") is None


# ===========================================================================
# add_alter_removes()
# ===========================================================================
class TestAddAlterRemoves:

    def test_creates_removal_and_alter(self, prof):
        r = prof.add_alter_removes("ac-1", by_name="label", by_id="ac-1_smt")
        assert r == {"by-name": "label", "by-id": "ac-1_smt"}
        assert _alter(prof, "ac-1")["removes"] == [r]

    def test_requires_a_selector(self, prof):
        assert prof.add_alter_removes("ac-1") is None
        assert _modify(prof) is None

    def test_marks_unsaved_and_safe_copy(self, prof):
        r = prof.add_alter_removes("ac-1", by_id="x")
        assert prof.is_unsaved is True
        r["by-id"] = "MUT"
        assert _alter(prof, "ac-1")["removes"][0]["by-id"] == "x"

    def test_read_only_guard(self, prof):
        prof.is_read_only = True
        assert prof.add_alter_removes("ac-1", by_id="x") is None


# ===========================================================================
# remove_alter_adds()
# ===========================================================================
class TestRemoveAlterAdds:

    def _seed(self, prof):
        prof.add_alter_adds("ac-1", position="after", by_id="s", title="A")
        prof.add_alter_adds("ac-1", position="before", by_id="s", title="B")
        prof.add_alter_adds("ac-1", by_id="other", title="C")
        prof.is_unsaved = False

    def test_by_id_required(self, prof):
        self._seed(prof)
        assert prof.remove_alter_adds("ac-1", by_id="") is False

    def test_by_id_removes_all_regardless_of_position(self, prof):
        self._seed(prof)
        assert prof.remove_alter_adds("ac-1", by_id="s") is True
        assert [a["by-id"] for a in _alter(prof, "ac-1")["adds"]] == ["other"]
        assert prof.is_unsaved is True

    def test_by_id_and_position_narrows(self, prof):
        self._seed(prof)
        prof.remove_alter_adds("ac-1", by_id="s", position="after")
        positions = [a.get("position") for a in _alter(prof, "ac-1")["adds"]]
        assert "after" not in positions and "before" in positions

    def test_no_match_returns_false(self, prof):
        self._seed(prof)
        assert prof.remove_alter_adds("ac-1", by_id="nope") is False
        assert prof.is_unsaved is False

    def test_cleanup_removes_alter_and_modify(self, prof):
        prof.add_alter_adds("ac-9", by_id="only", title="X")
        assert _modify(prof) is not None
        prof.remove_alter_adds("ac-9", by_id="only")
        assert _modify(prof) is None          # emptied adds -> alter -> alters -> modify

    def test_read_only_guard(self, prof):
        self._seed(prof)
        prof.is_read_only = True
        assert prof.remove_alter_adds("ac-1", by_id="s") is False


# ===========================================================================
# remove_alter_removes()
# ===========================================================================
class TestRemoveAlterRemoves:

    _NS1 = "http://example.com/ns1"
    _NS2 = "http://example.com/ns2"

    def _seed(self, prof):
        prof.add_alter_removes("ac-1", by_class="c1", by_ns=self._NS1)
        prof.add_alter_removes("ac-1", by_class="c1", by_ns=self._NS2)
        prof.add_alter_removes("ac-1", by_class="c2")
        prof.is_unsaved = False

    def test_matches_all_present_selectors(self, prof):
        self._seed(prof)
        assert prof.remove_alter_removes("ac-1", by_class="c1") is True
        assert [r.get("by-class") for r in _alter(prof, "ac-1")["removes"]] == ["c2"]

    def test_narrowing_selector(self, prof):
        self._seed(prof)
        prof.remove_alter_removes("ac-1", by_class="c1", by_ns=self._NS1)
        remaining = [(r.get("by-class"), r.get("by-ns")) for r in _alter(prof, "ac-1")["removes"]]
        assert ("c1", self._NS1) not in remaining and ("c1", self._NS2) in remaining

    def test_no_selector_removes_all(self, prof):
        self._seed(prof)
        assert prof.remove_alter_removes("ac-1") is True
        assert _modify(prof) is None          # all removed -> full cleanup

    def test_no_match_returns_false(self, prof):
        self._seed(prof)
        assert prof.remove_alter_removes("ac-1", by_class="nope") is False
        assert prof.is_unsaved is False

    def test_read_only_guard(self, prof):
        self._seed(prof)
        prof.is_read_only = True
        assert prof.remove_alter_removes("ac-1", by_class="c1") is False


# ===========================================================================
# adds + removes coexist; partial cleanup
# ===========================================================================
class TestMixedCleanup:

    def test_removing_adds_keeps_alter_when_removes_remain(self, prof):
        prof.add_alter_adds("ac-1", by_id="s", title="A")
        prof.add_alter_removes("ac-1", by_name="label")
        prof.remove_alter_adds("ac-1", by_id="s")
        alter = _alter(prof, "ac-1")
        assert alter is not None and "adds" not in alter and "removes" in alter

    def test_round_trip_valid_with_both(self, prof):
        prof.add_alter_adds("ac-1", by_id="ac-1_smt", position="after",
                            parts=[{"id": "ac-1_gd", "name": "guidance", "prose": "do X"}])
        prof.add_alter_removes("ac-1", by_name="label")
        prof.set_parameter("ac-1_prm_1", values=["daily"])
        assert Profile.loads(prof.dumps()).is_valid


# ===========================================================================
# get_set_parameter() / get_alter()
# ===========================================================================
class TestModifyGetters:

    def test_get_set_parameter(self, prof):
        prof.set_parameter("p1", label="L", values=["daily"])
        assert prof.get_set_parameter("p1") == {"param-id": "p1", "label": "L", "values": ["daily"]}

    def test_get_set_parameter_unknown_is_none(self, prof):
        assert prof.get_set_parameter("nope") is None

    def test_get_set_parameter_is_safe_copy(self, prof):
        prof.set_parameter("p1", values=["daily"])
        prof.get_set_parameter("p1")["values"].append("INJECT")
        assert _setp(prof, "p1")["values"] == ["daily"]

    def test_get_alter(self, prof):
        prof.add_alter_adds("ac-1", by_id="s", title="T")
        assert prof.get_alter("ac-1") == {"control-id": "ac-1", "adds": [{"by-id": "s", "title": "T"}]}

    def test_get_alter_unknown_is_none(self, prof):
        assert prof.get_alter("nope") is None

    def test_get_alter_is_safe_copy(self, prof):
        prof.add_alter_adds("ac-1", by_id="s", title="T")
        prof.get_alter("ac-1")["adds"][0]["title"] = "MUT"
        assert _alter(prof, "ac-1")["adds"][0]["title"] == "T"


# ===========================================================================
# remove_set_parameter()
# ===========================================================================
class TestRemoveSetParameter:

    def test_removes_matching(self, prof):
        prof.set_parameter("p1", values=["a"])
        prof.set_parameter("p2", values=["b"])
        prof.is_unsaved = False
        assert prof.remove_set_parameter("p1") is True
        assert [s["param-id"] for s in _setps(prof)] == ["p2"]
        assert prof.is_unsaved is True

    def test_no_match_returns_false(self, prof):
        prof.set_parameter("p1", values=["a"])
        prof.is_unsaved = False
        assert prof.remove_set_parameter("nope") is False
        assert prof.is_unsaved is False

    def test_blank_param_id_returns_false(self, prof):
        assert prof.remove_set_parameter("") is False

    def test_cleanup_drops_modify(self, prof):
        prof.set_parameter("only", values=["x"])
        prof.remove_set_parameter("only")
        assert _modify(prof) is None

    def test_cleanup_keeps_coexisting_alters(self, prof):
        prof.set_parameter("sp", values=["x"])
        prof.add_alter_adds("ac-1", by_id="s", title="T")
        prof.remove_set_parameter("sp")
        assert "set-parameters" not in _modify(prof) and "alters" in _modify(prof)

    def test_read_only_guard(self, prof):
        prof.set_parameter("p1", values=["a"])
        prof.is_read_only = True
        assert prof.remove_set_parameter("p1") is False
