"""
Unit + integration tests for profile modify/alter processing (Phase E):
removes -> adds -> set-parameters, applied per control on source-scope ids,
including ancestor-alter routing into nested controls.
"""
import json
import os

import pytest

from oscal import Profile
from oscal.oscal_controls import (
    _remove_matching, _find_anchor, _add_into, _add_sibling,
    _apply_one_set_parameter, _distinct_key, _cited_param_ids,
)


# ===========================================================================
# Pure helpers
# ===========================================================================
class TestRemoveMatching:

    def _ctl(self):
        return {
            "id": "ac-1",
            "props": [{"name": "label", "value": "AC-1"},
                      {"name": "status", "value": "x", "class": "draft"}],
            "params": [{"id": "ac-1_prm_1"}],
            "parts": [{"id": "ac-1_smt", "name": "statement",
                       "props": [{"name": "label", "value": "a."}],
                       "parts": [{"id": "ac-1_smt.a", "name": "item"}]}],
        }

    def test_remove_by_name(self):
        c = self._ctl()
        n = _remove_matching(c, {"by-name": "label"})
        # both label props (control-level and nested part-level) removed
        assert n == 2
        assert all(p["name"] != "label" for p in c["props"])
        assert "props" not in c["parts"][0]

    def test_remove_by_id_nested_part(self):
        c = self._ctl()
        _remove_matching(c, {"by-id": "ac-1_smt.a"})
        assert c["parts"][0].get("parts", []) == [] or "parts" not in c["parts"][0]

    def test_remove_all_flags_must_match(self):
        c = self._ctl()
        # by-name matches but by-class does not -> no removal
        n = _remove_matching(c, {"by-name": "label", "by-class": "nope"})
        assert n == 0
        # both match -> removed
        n = _remove_matching(c, {"by-name": "status", "by-class": "draft"})
        assert n == 1

    def test_remove_by_item_name(self):
        c = self._ctl()
        n = _remove_matching(c, {"by-item-name": "param"})
        assert n == 1 and "params" not in c


class TestFindAnchorAndAdd:

    def _ctl(self):
        return {"id": "ac-1", "title": "Old",
                "parts": [{"id": "ac-1_smt", "name": "statement",
                           "parts": [{"id": "ac-1_obj", "name": "objective"}]}]}

    def test_find_anchor_nested(self):
        c = self._ctl()
        el, parent, key, idx = _find_anchor(c, "ac-1_obj")
        assert el["id"] == "ac-1_obj" and key == "parts"

    def test_add_into_starting_and_title(self):
        c = self._ctl()
        _add_into(c, {"title": "New", "props": [{"name": "CORE", "value": "true"}]}, "starting")
        assert c["title"] == "New"
        assert c["props"][0]["name"] == "CORE"

    def test_add_into_ending_parts(self):
        c = self._ctl()
        _add_into(c, {"parts": [{"id": "extra", "name": "guidance"}]}, "ending")
        assert c["parts"][-1]["id"] == "extra"

    def test_add_sibling_after(self):
        c = self._ctl()
        el, parent, key, idx = _find_anchor(c, "ac-1_smt")
        _add_sibling(parent, key, idx, {"parts": [{"id": "sib", "name": "guidance"}]}, "after")
        ids = [p["id"] for p in c["parts"]]
        assert ids == ["ac-1_smt", "sib"]

    def test_add_sibling_before(self):
        c = self._ctl()
        el, parent, key, idx = _find_anchor(c, "ac-1_smt")
        _add_sibling(parent, key, idx, {"parts": [{"id": "sib", "name": "guidance"}]}, "before")
        assert [p["id"] for p in c["parts"]] == ["sib", "ac-1_smt"]


class TestSetParameterApplication:

    def test_replace_fields(self):
        param = {"id": "p", "label": "old", "values": ["v0"]}
        _apply_one_set_parameter(param, {"param-id": "p", "label": "new", "values": ["v1", "v2"]})
        assert param["label"] == "new"
        assert param["values"] == ["v1", "v2"]

    def test_values_clears_select_with_warning(self):
        param = {"id": "p", "select": {"choice": ["a", "b"]}}
        warns = _apply_one_set_parameter(param, {"param-id": "p", "values": ["v1"]})
        assert param["values"] == ["v1"] and "select" not in param
        assert warns and "select" in warns[0]

    def test_select_clears_values_with_warning(self):
        param = {"id": "p", "values": ["v0"]}
        warns = _apply_one_set_parameter(param, {"param-id": "p", "select": {"choice": ["a"]}})
        assert param["select"] == {"choice": ["a"]} and "values" not in param
        assert warns

    def test_constraints_appended(self):
        param = {"id": "p", "constraints": [{"description": "existing"}]}
        _apply_one_set_parameter(param, {"param-id": "p", "constraints": [{"description": "added"}]})
        assert [c["description"] for c in param["constraints"]] == ["existing", "added"]

    def test_props_replace_by_distinct_id(self):
        param = {"id": "p", "props": [{"name": "keyword", "value": "old"}]}
        _apply_one_set_parameter(param, {"param-id": "p",
                                         "props": [{"name": "keyword", "value": "new"}]})
        # same distinct id (name+ns+class) -> replaced, not duplicated
        assert param["props"] == [{"name": "keyword", "value": "new"}]

    def test_props_default_ns_equivalence(self):
        # a prop with no ns collides with one explicitly in the OSCAL default ns
        existing = {"name": "k", "value": "old"}
        incoming = {"name": "k", "ns": "http://csrc.nist.gov/ns/oscal", "value": "new"}
        assert _distinct_key(existing, "prop") == _distinct_key(incoming, "prop")


class TestCitedParamIds:

    def test_finds_inserts(self):
        c = {"parts": [{"prose": "Do {{ insert: param, ac-1_prm_1 }} and "
                                 "{{ insert: param, ac-1_prm_2 }}."}]}
        assert _cited_param_ids(c) == {"ac-1_prm_1", "ac-1_prm_2"}


# ===========================================================================
# Integration — modify applied through resolution & JIT
# ===========================================================================
def _source_catalog():
    return {"catalog": {
        "uuid": "22222222-2222-4222-8222-222222222222",
        "metadata": {"title": "Src", "last-modified": "2026-01-01T00:00:00Z",
                     "version": "1", "oscal-version": "1.1.3"},
        "groups": [{"id": "ac", "class": "family", "title": "AC", "controls": [
            {"id": "ac-1", "title": "Policy",
             "props": [{"name": "label", "value": "AC-1"}],
             "params": [{"id": "ac-1_prm_1", "label": "freq", "values": ["annually"]},
                        {"id": "ac-1_prm_2", "label": "role"}],
             "parts": [{"id": "ac-1_smt", "name": "statement", "prose": "Do the thing."}]},
            {"id": "ac-2", "title": "Accounts", "controls": [
                {"id": "ac-2.1", "title": "Automated",
                 "parts": [{"id": "ac-2.1_smt", "name": "statement", "prose": "Auto."}]}]},
        ]}],
    }}


def _profile_with_modify(tmp_path, modify):
    import json as _json
    path = os.path.join(str(tmp_path), "src.json")
    with open(path, "w") as fh:
        _json.dump(_source_catalog(), fh)
    p = Profile.new("Mod")
    p.add_import(path, include_all=True)
    p.set_merge(as_is=True)
    p._dict["profile"]["modify"] = modify
    p._tree_dirty = True
    p._build_controls_tree()
    return p


class TestModifyIntegration:

    def test_remove_then_add_and_setparam(self, tmp_path):
        p = _profile_with_modify(tmp_path, {
            "set-parameters": [
                {"param-id": "ac-1_prm_1", "values": ["every 3 years"]},
                {"param-id": "ac-1_prm_2", "constraints": [{"description": "admins"}]},
            ],
            "alters": [{"control-id": "ac-1",
                        "removes": [{"by-name": "label"}],
                        "adds": [
                            {"position": "starting", "by-id": "ac-1",
                             "props": [{"name": "CORE", "value": "true"}]},
                            {"position": "after", "by-id": "ac-1_smt",
                             "parts": [{"id": "ac-1_gdn", "name": "guidance", "prose": "G."}]},
                        ]}],
        })
        p.resolve()
        ac1 = p.get_control_by_id("ac-1")
        # remove: label prop gone; add: CORE prop present (by-id == control)
        names = [pr["name"] for pr in ac1.get("props", [])]
        assert "label" not in names and "CORE" in names
        # add: guidance part after statement
        part_ids = [pt["id"] for pt in ac1["parts"]]
        assert part_ids == ["ac-1_smt", "ac-1_gdn"]
        # set-parameters: values replaced; constraints appended
        prm = {pr["id"]: pr for pr in ac1["params"]}
        assert prm["ac-1_prm_1"]["values"] == ["every 3 years"]
        assert prm["ac-1_prm_2"]["constraints"][0]["description"] == "admins"

    def test_jit_matches_resolved(self, tmp_path):
        p = _profile_with_modify(tmp_path, {
            "alters": [{"control-id": "ac-1",
                        "adds": [{"position": "starting", "by-id": "ac-1",
                                  "props": [{"name": "CORE", "value": "true"}]}]}]})
        jit = p.get_control_by_id("ac-1")           # unresolved
        p.resolve()
        resolved = p.get_control_by_id("ac-1")      # from catalog
        assert jit == resolved
        assert any(pr["name"] == "CORE" for pr in jit["props"])

    def test_ancestor_alter_routes_into_child(self, tmp_path):
        # An alter on the PARENT control ac-2 with a by-id targeting the CHILD ac-2.1's
        # statement part must apply when materializing ac-2.1.
        p = _profile_with_modify(tmp_path, {
            "alters": [{"control-id": "ac-2",
                        "adds": [{"position": "starting", "by-id": "ac-2.1_smt",
                                  "props": [{"name": "from-ancestor", "value": "yes"}]}]}]})
        p.resolve()
        child = p.get_control_by_id("ac-2.1")
        smt = child["parts"][0]
        assert any(pr["name"] == "from-ancestor" for pr in smt.get("props", []))
        # the parent itself is unchanged by that child-targeted add
        parent = p.get_control_by_id("ac-2", depth=0)
        assert "props" not in parent or all(pr["name"] != "from-ancestor" for pr in parent["props"])

    def test_multiple_alters_same_control(self, tmp_path):
        p = _profile_with_modify(tmp_path, {
            "alters": [
                {"control-id": "ac-1", "adds": [{"position": "ending", "by-id": "ac-1",
                                                 "props": [{"name": "one", "value": "1"}]}]},
                {"control-id": "ac-1", "adds": [{"position": "ending", "by-id": "ac-1",
                                                 "props": [{"name": "two", "value": "2"}]}]},
            ]})
        p.resolve()
        names = [pr["name"] for pr in p.get_control_by_id("ac-1")["props"]]
        assert "one" in names and "two" in names
