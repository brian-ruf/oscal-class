"""
Unit tests for POAM.poam_tree — the POA&M analog of SSP.implementation_tree /
Catalog.controls_tree.

Shape (all four keys always present, empty by default):
    poam-items[]  : {uuid, title, related-findings[], related-observations[], related-risks[]}
    observations[]: {uuid, title, methods[], types[]}
    findings[]    : {uuid, title, related-observations[], related-risks[]}
    risks[]       : {uuid, title, related-observations[]}

The three `related-*` values are flat lists of the referenced uuid STRINGS (the
finding-uuid / observation-uuid / risk-uuid pulled out of their wrapper objects). The tree
is built from the document's own content, refreshed on validate / content mutation, and is
a detached copy (mutating it must not touch the document).
"""
import copy
import json

import pytest

from oscal import OSCAL

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}

_OBS1 = "30000000-0000-4000-8000-000000000001"
_OBS2 = "30000000-0000-4000-8000-000000000002"
_RISK1 = "20000000-0000-4000-8000-000000000001"
_FIND1 = "40000000-0000-4000-8000-000000000001"
_ITEM1 = "50000000-0000-4000-8000-000000000001"


def _poam_dict():
    return {"plan-of-action-and-milestones": {
        "uuid": "bbbbbbbb-0000-4000-8000-000000000001",
        "metadata": {"title": "T", **_META},
        "import-ssp": {"href": "#"},
        "observations": [
            {"uuid": _OBS1, "title": "TLS probe", "description": "o",
             "methods": ["EXAMINE", "TEST"], "types": ["control-objective"],
             "collected": "2026-01-01T00:00:00Z"},
            {"uuid": _OBS2, "description": "o2",            # no title, no types
             "methods": ["INTERVIEW"], "collected": "2026-01-01T00:00:00Z"},
        ],
        "risks": [
            {"uuid": _RISK1, "title": "Weak cipher", "description": "d",
             "statement": "s", "status": "open",
             "related-observations": [{"observation-uuid": _OBS1},
                                      {"observation-uuid": _OBS2, "remarks": "x"}]},
        ],
        "findings": [
            {"uuid": _FIND1, "title": "AC-2 not met", "description": "d",
             "target": {"type": "objective-id", "target-id": "ac-2_obj",
                        "status": {"state": "not-satisfied"}},
             "related-observations": [{"observation-uuid": _OBS1}],
             "related-risks": [{"risk-uuid": _RISK1}]},
        ],
        "poam-items": [
            {"uuid": _ITEM1, "title": "Remediate weak cipher", "description": "d",
             "related-findings": [{"finding-uuid": _FIND1}],
             "related-observations": [{"observation-uuid": _OBS1},
                                      {"observation-uuid": _OBS2}],
             "related-risks": [{"risk-uuid": _RISK1}]},
        ],
    }}


@pytest.fixture
def poam():
    return OSCAL.loads(json.dumps(_poam_dict()))


class TestPoamTreeShape:
    def test_all_keys_present(self, poam):
        assert set(poam.poam_tree) == {"poam-items", "observations", "findings", "risks"}

    def test_observations_nodes(self, poam):
        obs = poam.poam_tree["observations"]
        assert obs[0] == {"uuid": _OBS1, "title": "TLS probe",
                          "methods": ["EXAMINE", "TEST"], "types": ["control-objective"]}
        # second observation: no title/types -> empty defaults
        assert obs[1] == {"uuid": _OBS2, "title": "", "methods": ["INTERVIEW"], "types": []}

    def test_risk_nodes_flatten_observation_refs(self, poam):
        risk = poam.poam_tree["risks"][0]
        assert risk == {"uuid": _RISK1, "title": "Weak cipher",
                        "related-observations": [_OBS1, _OBS2]}

    def test_finding_nodes_flatten_refs(self, poam):
        fnd = poam.poam_tree["findings"][0]
        assert fnd == {"uuid": _FIND1, "title": "AC-2 not met",
                       "related-observations": [_OBS1], "related-risks": [_RISK1]}

    def test_poam_item_nodes_flatten_all_three(self, poam):
        item = poam.poam_tree["poam-items"][0]
        assert item == {
            "uuid": _ITEM1, "title": "Remediate weak cipher",
            "related-findings": [_FIND1],
            "related-observations": [_OBS1, _OBS2],
            "related-risks": [_RISK1],
        }

    def test_refs_are_plain_uuid_strings(self, poam):
        # No wrapper dicts / no keys survive — just the uuid strings.
        for ref in poam.poam_tree["poam-items"][0]["related-findings"]:
            assert isinstance(ref, str)


class TestPoamTreeLifecycle:
    def test_missing_arrays_yield_empty_lists(self):
        d = _poam_dict()
        pm = d["plan-of-action-and-milestones"]
        for k in ("observations", "risks", "findings", "poam-items"):
            pm.pop(k, None)
        doc = OSCAL.loads(json.dumps(d))
        assert doc.poam_tree == {"poam-items": [], "observations": [],
                                 "findings": [], "risks": []}

    def test_tree_is_detached_copy(self, poam):
        poam.poam_tree["observations"][0]["title"] = "MUTATED"
        poam.poam_tree["poam-items"][0]["related-findings"].append("injected")
        # A rebuild from the untouched document restores the true values.
        rebuilt = poam._build_poam_tree()
        assert rebuilt["observations"][0]["title"] == "TLS probe"
        assert rebuilt["poam-items"][0]["related-findings"] == [_FIND1]

    def test_only_poam_has_tree(self):
        ar = OSCAL.loads(json.dumps({"assessment-results": {
            "uuid": "aaaaaaaa-0000-4000-8000-000000000001",
            "metadata": {"title": "T", **_META}, "import-ap": {"href": "#"},
            "results": [{"uuid": "10000000-0000-4000-8000-000000000001",
                         "title": "R", "description": "d", "start": "2026-01-01T00:00:00Z"}],
        }}))
        assert not hasattr(ar, "poam_tree")
