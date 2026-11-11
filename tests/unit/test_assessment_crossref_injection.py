"""
Unit tests for cross-reference injection on the assessment intra-document getters:

    finding(uuid)      -> injects observations[] (related-observations) + risks[] (related-risks)
    risk(uuid)         -> injects observations[] (related-observations)
    observation(uuid)  -> resolves subjects[] by type (component/party/user/resource/...) and
                          relevant-evidence[] fragment hrefs -> back-matter resource

All cited objects are resolved via the model's own getters (local + import chain). A
path-based `_seen` guard prevents infinite recursion on a malformed (cyclic) document, even
though valid OSCAL cannot express a cycle here.
"""
import json
import os
import tempfile

import pytest

from oscal import OSCAL

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}

_OBS1 = "30000000-0000-4000-8000-000000000001"
_OBS2 = "30000000-0000-4000-8000-000000000002"
_RISK1 = "20000000-0000-4000-8000-000000000001"
_FIND1 = "40000000-0000-4000-8000-000000000001"
_COMP = "66666666-0000-4000-8000-000000000001"
_PARTY = "99999999-0000-4000-8000-000000000001"
_RES = "88888888-0000-4000-8000-000000000001"


def _poam_dict():
    return {"plan-of-action-and-milestones": {
        "uuid": "bbbbbbbb-0000-4000-8000-000000000001",
        "metadata": {"title": "P", **_META,
                     "parties": [{"uuid": _PARTY, "type": "organization", "name": "Acme Assessors"}]},
        "import-ssp": {"href": "#"},
        "local-definitions": {
            "components": [{"uuid": _COMP, "type": "software", "title": "Scanner",
                            "description": "d", "status": {"state": "operational"}}],
        },
        "observations": [
            {"uuid": _OBS1, "title": "TLS probe", "description": "o", "methods": ["TEST"],
             "collected": "2026-01-01T00:00:00Z",
             "subjects": [
                 {"subject-uuid": _COMP, "type": "component"},
                 {"subject-uuid": _PARTY, "type": "party"},
                 {"subject-uuid": "deadbeef-0000-4000-8000-000000000000", "type": "component"},
             ],
             "relevant-evidence": [
                 {"href": "#" + _RES, "description": "scan log"},
                 {"href": "https://example.com/external", "description": "external"},
             ]},
            {"uuid": _OBS2, "description": "o2", "methods": ["INTERVIEW"],
             "collected": "2026-01-01T00:00:00Z"},
        ],
        "risks": [
            {"uuid": _RISK1, "title": "Weak cipher", "description": "d", "statement": "s",
             "status": "open",
             "related-observations": [{"observation-uuid": _OBS1}, {"observation-uuid": _OBS2}]},
        ],
        "findings": [
            {"uuid": _FIND1, "title": "AC-2 not met", "description": "d",
             "target": {"type": "objective-id", "target-id": "ac-2_obj",
                        "status": {"state": "not-satisfied"}},
             "related-observations": [{"observation-uuid": _OBS1}],
             "related-risks": [{"risk-uuid": _RISK1}]},
        ],
        "poam-items": [{"uuid": "cccccccc-0000-4000-8000-000000000001",
                        "title": "x", "description": "d"}],
        "back-matter": {"resources": [
            {"uuid": _RES, "title": "Scan Log", "rlinks": [{"href": "scan.txt"}]}]},
    }}


@pytest.fixture
def poam():
    return OSCAL.loads(json.dumps(_poam_dict()))


class TestFindingInjection:
    def test_injects_observations_and_risks(self, poam):
        f = poam.finding(_FIND1)
        assert [o["uuid"] for o in f["observations"]] == [_OBS1]
        assert [r["uuid"] for r in f["risks"]] == [_RISK1]
        # raw reference arrays are left intact alongside the injected objects
        assert f["related-observations"][0]["observation-uuid"] == _OBS1
        assert f["related-risks"][0]["risk-uuid"] == _RISK1

    def test_nested_risk_carries_its_own_observations(self, poam):
        f = poam.finding(_FIND1)
        injected_risk = f["risks"][0]
        assert {o["uuid"] for o in injected_risk["observations"]} == {_OBS1, _OBS2}

    def test_injected_observation_is_fully_resolved(self, poam):
        # the finding's injected observation has its subjects resolved too
        f = poam.finding(_FIND1)
        obs = f["observations"][0]
        comp_subj = next(s for s in obs["subjects"] if s["type"] == "component"
                         and s["subject-uuid"] == _COMP)
        assert comp_subj["component"]["title"] == "Scanner"


class TestRiskInjection:
    def test_injects_observations(self, poam):
        r = poam.risk(_RISK1)
        assert {o["uuid"] for o in r["observations"]} == {_OBS1, _OBS2}

    def test_cycle_guard_returns_bare_when_seen(self, poam):
        # Directly exercising the path-guard: the uuid already on the path -> no injection.
        bare = poam.risk(_RISK1, _seen=frozenset({_RISK1}))
        assert "observations" not in bare


class TestObservationInjection:
    def test_subject_component_resolved(self, poam):
        o = poam.observation(_OBS1)
        comp = next(s for s in o["subjects"] if s["subject-uuid"] == _COMP)
        assert comp["component"]["title"] == "Scanner"
        assert comp["component"]["provenance"]["uuid"] == poam.uuid

    def test_subject_party_resolved(self, poam):
        o = poam.observation(_OBS1)
        party = next(s for s in o["subjects"] if s["type"] == "party")
        assert party["party"]["name"] == "Acme Assessors"

    def test_dangling_subject_placeholder(self, poam):
        o = poam.observation(_OBS1)
        bad = next(s for s in o["subjects"]
                   if s["subject-uuid"] == "deadbeef-0000-4000-8000-000000000000")
        assert bad["component"]["title"] == "[Invalid Component Reference]"

    def test_evidence_fragment_resolves_resource(self, poam):
        o = poam.observation(_OBS1)
        frag_ev = next(e for e in o["relevant-evidence"] if e["href"].startswith("#"))
        assert frag_ev["resource"]["title"] == "Scan Log"

    def test_evidence_external_href_untouched(self, poam):
        o = poam.observation(_OBS1)
        ext = next(e for e in o["relevant-evidence"] if e["href"].startswith("http"))
        assert "resource" not in ext

    def test_observation_without_subjects_or_evidence(self, poam):
        o = poam.observation(_OBS2)
        assert o["uuid"] == _OBS2 and "subjects" not in o
