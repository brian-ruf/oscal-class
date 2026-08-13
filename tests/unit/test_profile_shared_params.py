"""
Tests for shared/aggregate parameter handling (#1): a parameter cited in a control
but defined outside it is also in scope — acquired, set-parameters applied, and either
embedded (JIT) or hoisted to the resolved catalog root (resolve). Citations are followed
transitively.
"""
import json
import os

import pytest

from oscal import Profile, Catalog


def _source_catalog():
    # ac-1 cites cat-level param `shared-1`; `shared-1` in turn cites `shared-2`.
    return {"catalog": {
        "uuid": "33333333-3333-4333-8333-333333333333",
        "metadata": {"title": "Src", "last-modified": "2026-01-01T00:00:00Z",
                     "version": "1", "oscal-version": "1.1.3"},
        "params": [
            {"id": "shared-1", "label": "shared one",
             "select": {"choice": ["a", "{{ insert: param, shared-2 }}"]}},
            {"id": "shared-2", "label": "shared two"},
            {"id": "unused-9", "label": "never cited"},
        ],
        "groups": [{"id": "ac", "title": "AC", "controls": [
            {"id": "ac-1", "title": "Policy",
             "params": [{"id": "ac-1_prm_1", "label": "local"}],
             "parts": [{"id": "ac-1_smt", "name": "statement",
                        "prose": "Use {{ insert: param, ac-1_prm_1 }} and "
                                 "{{ insert: param, shared-1 }}."}]},
        ]}],
    }}


@pytest.fixture
def prof(tmp_path):
    path = os.path.join(str(tmp_path), "src.json")
    with open(path, "w") as fh:
        json.dump(_source_catalog(), fh)
    p = Profile.new("Shared")
    p.add_import(path, include_all=True)
    p.set_merge(as_is=True)
    return p


class TestGetParameterById:

    def test_finds_catalog_level_param(self, prof):
        p = prof.get_parameter_by_id("shared-1")
        assert p is not None and p["id"] == "shared-1"

    def test_missing_returns_none(self, prof):
        assert prof.get_parameter_by_id("nope") is None


class TestJIT:

    def test_cited_param_embedded_in_control(self, prof):
        ac1 = prof.get_control_by_id("ac-1")          # unresolved -> embed
        pids = {p["id"] for p in ac1["params"]}
        # local param + cited shared-1 + transitively-cited shared-2
        assert {"ac-1_prm_1", "shared-1", "shared-2"} <= pids
        # an un-cited catalog param is NOT pulled in
        assert "unused-9" not in pids


class TestResolve:

    def test_cited_params_hoisted_to_root(self, prof):
        prof.resolve()
        assert prof.catalog.is_valid
        root_params = {p["id"] for p in prof.catalog._dict["catalog"].get("params", [])}
        assert {"shared-1", "shared-2"} <= root_params
        assert "unused-9" not in root_params
        # the control keeps only its own local param
        ac1 = prof.get_control_by_id("ac-1")
        assert {p["id"] for p in ac1["params"]} == {"ac-1_prm_1"}

    def test_setparameter_applied_to_shared(self, prof):
        prof._dict["profile"]["modify"] = {
            "set-parameters": [{"param-id": "shared-2", "values": ["resolved-value"]}]}
        prof._tree_dirty = True
        prof._build_controls_tree()
        prof.resolve()
        shared2 = prof.get_parameter_by_id("shared-2")
        assert shared2["values"] == ["resolved-value"]

    def test_no_duplicate_hoist(self, prof):
        prof.resolve()
        ids = [p["id"] for p in prof.catalog._dict["catalog"].get("params", [])]
        assert len(ids) == len(set(ids))
