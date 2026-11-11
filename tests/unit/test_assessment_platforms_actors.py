"""
Unit tests for the assessment-platform getters and the actor() helper + actor population:

    assessment_platforms(local_only)          index: {uuid, type, title, provenance}
    assessment_platform(uuid, ...)            whole object + injected components[] (uses-components)
    actor(actors)                             copy of an actors[] array with tool/assessment-platform/
                                              party objects injected by actor-uuid+type
    observation()/risk()/finding()            every origins[].actors[] replaced via actor()
"""
import json

import pytest

from oscal import OSCAL

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}

_PLAT = "11111111-0000-4000-8000-000000000001"
_COMP = "66666666-0000-4000-8000-000000000001"
_PARTY = "99999999-0000-4000-8000-000000000001"
_OBS = "30000000-0000-4000-8000-000000000001"
_RISK = "20000000-0000-4000-8000-000000000001"
_FIND = "40000000-0000-4000-8000-000000000001"


def _poam_dict():
    return {"plan-of-action-and-milestones": {
        "uuid": "bbbbbbbb-0000-4000-8000-000000000001",
        "metadata": {"title": "P", **_META,
                     "parties": [{"uuid": _PARTY, "type": "organization", "name": "Acme"}]},
        "import-ssp": {"href": "#"},
        "local-definitions": {
            "components": [{"uuid": _COMP, "type": "software", "title": "Scanner",
                            "description": "d", "status": {"state": "operational"}}],
            "assessment-assets": {
                "assessment-platforms": [
                    {"uuid": _PLAT, "title": "Nessus Platform",
                     "uses-components": [{"component-uuid": _COMP},
                                         {"component-uuid": "deadbeef-0000-4000-8000-000000000000"}]},
                ],
            },
        },
        "observations": [
            {"uuid": _OBS, "description": "o", "methods": ["TEST"],
             "collected": "2026-01-01T00:00:00Z",
             "origins": [{"actors": [
                 {"type": "tool", "actor-uuid": _COMP},
                 {"type": "assessment-platform", "actor-uuid": _PLAT},
                 {"type": "party", "actor-uuid": _PARTY},
                 {"type": "party", "actor-uuid": "deadbeef-0000-4000-8000-000000000000"},
             ]}]},
        ],
        "risks": [
            {"uuid": _RISK, "title": "R", "description": "d", "statement": "s", "status": "open",
             "origins": [{"actors": [{"type": "tool", "actor-uuid": _COMP}]}],
             # a *nested* origin (characterization.origin) — actor population must reach it too
             "characterizations": [
                 {"origin": {"actors": [{"type": "party", "actor-uuid": _PARTY}]},
                  "facets": [{"name": "likelihood", "system": "http://example.com", "value": "high"}]}],
             "related-observations": [{"observation-uuid": _OBS}]},
        ],
        "findings": [
            {"uuid": _FIND, "title": "F", "description": "d",
             "target": {"type": "objective-id", "target-id": "x", "status": {"state": "not-satisfied"}},
             "origins": [{"actors": [{"type": "party", "actor-uuid": _PARTY}]}],
             "related-risks": [{"risk-uuid": _RISK}]},
        ],
        "poam-items": [{"uuid": "cccccccc-0000-4000-8000-000000000001", "title": "x", "description": "d"}],
    }}


@pytest.fixture
def poam():
    return OSCAL.loads(json.dumps(_poam_dict()))


class TestAssessmentPlatforms:
    def test_index(self, poam):
        idx = poam.assessment_platforms()
        assert len(idx) == 1
        e = idx[0]
        assert e == {"uuid": _PLAT, "title": "Nessus Platform",
                     "provenance": e["provenance"]}         # no `type` key
        assert e["provenance"]["uuid"] == poam.uuid

    def test_singular_injects_components(self, poam):
        p = poam.assessment_platform(_PLAT)
        assert p["title"] == "Nessus Platform"
        # one resolved component (the dangling uses-component is skipped)
        assert [c["title"] for c in p["components"]] == ["Scanner"]
        assert p["components"][0]["provenance"]["uuid"] == poam.uuid
        assert p["provenance"]["uuid"] == poam.uuid

    def test_unknown_returns_none(self, poam):
        assert poam.assessment_platform("deadbeef-0000-4000-8000-000000000000") is None


class TestActorHelper:
    def test_populates_by_type(self, poam):
        actors = [
            {"type": "tool", "actor-uuid": _COMP},
            {"type": "assessment-platform", "actor-uuid": _PLAT},
            {"type": "party", "actor-uuid": _PARTY},
        ]
        out = poam.actor(actors)
        assert out[0]["tool"]["title"] == "Scanner"
        assert out[1]["assessment-platform"]["title"] == "Nessus Platform"
        assert out[1]["assessment-platform"]["components"][0]["title"] == "Scanner"
        assert out[2]["party"]["name"] == "Acme"

    def test_does_not_mutate_input(self, poam):
        actors = [{"type": "tool", "actor-uuid": _COMP}]
        poam.actor(actors)
        assert "tool" not in actors[0]

    def test_unresolved_actor_adds_nothing(self, poam):
        out = poam.actor([{"type": "party", "actor-uuid": "deadbeef-0000-4000-8000-000000000000"}])
        assert "party" not in out[0]


class TestActorPopulationInGetters:
    def test_observation_populates_actors(self, poam):
        o = poam.observation(_OBS)
        actors = o["origins"][0]["actors"]
        assert actors[0]["tool"]["title"] == "Scanner"
        assert actors[1]["assessment-platform"]["title"] == "Nessus Platform"
        assert actors[2]["party"]["name"] == "Acme"
        assert "party" not in actors[3]                      # dangling -> nothing added

    def test_risk_populates_own_and_injected_observation_actors(self, poam):
        r = poam.risk(_RISK)
        assert r["origins"][0]["actors"][0]["tool"]["title"] == "Scanner"
        # the injected observation also has its actors populated
        inj_obs = r["observations"][0]
        assert inj_obs["origins"][0]["actors"][0]["tool"]["title"] == "Scanner"

    def test_nested_origin_actors_populated_everywhere(self, poam):
        # actor population reaches a *nested* origin (characterization.origin), not just the
        # top-level origins[] — i.e. anywhere an origin's actors[] appears in the hierarchy.
        r = poam.risk(_RISK)
        nested = r["characterizations"][0]["origin"]["actors"][0]
        assert nested["party"]["name"] == "Acme"

    def test_finding_populates_actors_through_injected_risk(self, poam):
        f = poam.finding(_FIND)
        assert f["origins"][0]["actors"][0]["party"]["name"] == "Acme"
        inj_risk = f["risks"][0]
        assert inj_risk["origins"][0]["actors"][0]["tool"]["title"] == "Scanner"
