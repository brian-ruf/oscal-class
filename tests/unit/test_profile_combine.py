"""
Unit tests for profile-resolution combine helpers (Phase B) — the pure id-suffix
and reference-rewrite functions used to keep duplicate controls/groups unique.

Covers:
    - _suffix_control: renames own id + params + parts (recursive), NOT child controls
    - reference rewriting: {{ insert: param, X }} and href "#X" follow the rename
    - unrelated fragment hrefs (resource UUIDs) left intact
    - _suffix_group: renames own id + params + parts only, not child groups/controls
    - _rewrite_refs whitespace tolerance
"""
import re

import pytest

from oscal.oscal_controls import (
    _suffix_control, _suffix_group, _rewrite_refs, _PARAM_INSERT_RE,
)


# ===========================================================================
# _suffix_control
# ===========================================================================
class TestSuffixControl:

    def _ctrl(self):
        return {
            "id": "ac-1",
            "title": "Policy",
            "params": [{"id": "ac-1_prm_1"}, {"id": "ac-1_prm_2"}],
            "parts": [
                {"id": "ac-1_smt", "name": "statement",
                 "prose": "Use {{ insert: param, ac-1_prm_1 }} now.",
                 "parts": [{"id": "ac-1_smt.a", "name": "item", "prose": "sub"}]},
            ],
            "links": [{"href": "#ac-1_smt", "rel": "related"}],
            "controls": [
                {"id": "ac-1.1", "title": "Enh",
                 "params": [{"id": "ac-1.1_prm_1"}]},
            ],
        }

    def test_own_id_renamed(self):
        c = self._ctrl()
        rn = _suffix_control(c, "U")
        assert c["id"] == "ac-1__U"
        assert rn["ac-1"] == "ac-1__U"

    def test_param_ids_renamed(self):
        c = self._ctrl()
        _suffix_control(c, "U")
        assert {p["id"] for p in c["params"]} == {"ac-1_prm_1__U", "ac-1_prm_2__U"}

    def test_part_ids_renamed_recursively(self):
        c = self._ctrl()
        _suffix_control(c, "U")
        assert c["parts"][0]["id"] == "ac-1_smt__U"
        assert c["parts"][0]["parts"][0]["id"] == "ac-1_smt.a__U"

    def test_child_control_id_NOT_renamed(self):
        c = self._ctrl()
        _suffix_control(c, "U")
        # enhancement handled independently -> untouched here
        assert c["controls"][0]["id"] == "ac-1.1"
        assert c["controls"][0]["params"][0]["id"] == "ac-1.1_prm_1"

    def test_param_insert_reference_rewritten(self):
        c = self._ctrl()
        _suffix_control(c, "U")
        assert "{{ insert: param, ac-1_prm_1__U }}" in c["parts"][0]["prose"]

    def test_href_reference_rewritten(self):
        c = self._ctrl()
        _suffix_control(c, "U")
        assert c["links"][0]["href"] == "#ac-1_smt__U"

    def test_unrelated_href_untouched(self):
        c = self._ctrl()
        c["links"].append({"href": "#27847491-5ce1-4f6a-a1e4-9e483782f0ef", "rel": "reference"})
        _suffix_control(c, "U")
        assert c["links"][1]["href"] == "#27847491-5ce1-4f6a-a1e4-9e483782f0ef"

    def test_rename_map_contents(self):
        c = self._ctrl()
        rn = _suffix_control(c, "U")
        assert set(rn) == {"ac-1", "ac-1_prm_1", "ac-1_prm_2", "ac-1_smt", "ac-1_smt.a"}
        # child control ids not in the map
        assert "ac-1.1" not in rn


# ===========================================================================
# _suffix_group
# ===========================================================================
class TestSuffixGroup:

    def _grp(self):
        return {
            "id": "ac",
            "title": "Access Control",
            "params": [{"id": "ac_prm_shared"}],
            "parts": [{"id": "ac_gdn", "name": "guidance",
                       "prose": "See {{ insert: param, ac_prm_shared }}."}],
            "controls": [{"id": "ac-1", "title": "child",
                          "params": [{"id": "ac-1_prm_1"}]}],
            "groups": [{"id": "ac-sub", "title": "sub"}],
        }

    def test_own_id_and_params_renamed(self):
        g = self._grp()
        _suffix_group(g, "U")
        assert g["id"] == "ac__U"
        assert g["params"][0]["id"] == "ac_prm_shared__U"

    def test_part_ids_and_refs_rewritten(self):
        g = self._grp()
        _suffix_group(g, "U")
        assert g["parts"][0]["id"] == "ac_gdn__U"
        assert "{{ insert: param, ac_prm_shared__U }}" in g["parts"][0]["prose"]

    def test_child_controls_and_groups_untouched(self):
        g = self._grp()
        _suffix_group(g, "U")
        assert g["controls"][0]["id"] == "ac-1"
        assert g["controls"][0]["params"][0]["id"] == "ac-1_prm_1"
        assert g["groups"][0]["id"] == "ac-sub"


# ===========================================================================
# _rewrite_refs / regex
# ===========================================================================
class TestRewriteRefs:

    def test_whitespace_variants(self):
        rn = {"p1": "p1__U"}
        for src, want in [
            ("{{ insert: param, p1 }}", "{{ insert: param, p1__U }}"),
            ("{{insert: param,p1}}", "{{insert: param,p1__U}}"),
            ("{{  insert:  param ,  p1  }}", "{{  insert:  param ,  p1__U  }}"),
        ]:
            node = {"prose": src}
            _rewrite_refs(node, rn)
            assert node["prose"] == want

    def test_non_matching_ids_left_alone(self):
        node = {"prose": "{{ insert: param, other }}"}
        _rewrite_refs(node, {"p1": "p1__U"})
        assert node["prose"] == "{{ insert: param, other }}"

    def test_skip_keys_blocks_descent(self):
        node = {"parts": [{"prose": "{{ insert: param, p1 }}"}],
                "controls": [{"parts": [{"prose": "{{ insert: param, p1 }}"}]}]}
        _rewrite_refs(node, {"p1": "p1__U"}, skip_keys=("controls",))
        assert "p1__U" in node["parts"][0]["prose"]
        # controls subtree skipped
        assert node["controls"][0]["parts"][0]["prose"] == "{{ insert: param, p1 }}"
