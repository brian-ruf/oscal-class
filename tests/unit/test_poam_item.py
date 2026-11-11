"""
Unit tests for POAM.poam_item(uuid) cross-reference injection.

A poam-item gets the same treatment as finding(): every origins[].actors[] populated via
actor(), plus findings[]/observations[]/risks[] injected from its related-findings /
related-observations / related-risks reference lists (each injected object fully resolved).
"""
import json

import pytest

from oscal import OSCAL

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}

_OBS = "30000000-0000-4000-8000-000000000001"
_RISK = "20000000-0000-4000-8000-000000000001"
_FIND = "40000000-0000-4000-8000-000000000001"
_ITEM = "50000000-0000-4000-8000-000000000001"
_COMP = "66666666-0000-4000-8000-000000000001"
_PARTY = "99999999-0000-4000-8000-000000000001"


def _poam_dict():
    return {"plan-of-action-and-milestones": {
        "uuid": "bbbbbbbb-0000-4000-8000-000000000001",
        "metadata": {"title": "P", **_META,
                     "parties": [{"uuid": _PARTY, "type": "organization", "name": "Acme"}]},
        "import-ssp": {"href": "#"},
        "local-definitions": {
            "components": [{"uuid": _COMP, "type": "software", "title": "Scanner",
                            "description": "d", "status": {"state": "operational"}}],
        },
        "observations": [
            {"uuid": _OBS, "title": "obs", "description": "o", "methods": ["TEST"],
             "collected": "2026-01-01T00:00:00Z",
             "origins": [{"actors": [{"type": "tool", "actor-uuid": _COMP}]}]},
        ],
        "risks": [
            {"uuid": _RISK, "title": "risk", "description": "d", "statement": "s", "status": "open",
             "related-observations": [{"observation-uuid": _OBS}]},
        ],
        "findings": [
            {"uuid": _FIND, "title": "finding", "description": "d",
             "target": {"type": "objective-id", "target-id": "x", "status": {"state": "not-satisfied"}},
             "related-observations": [{"observation-uuid": _OBS}],
             "related-risks": [{"risk-uuid": _RISK}]},
        ],
        "poam-items": [
            {"uuid": _ITEM, "title": "Remediate", "description": "d",
             "origins": [{"actors": [{"type": "party", "actor-uuid": _PARTY}]}],
             "related-findings": [{"finding-uuid": _FIND}],
             "related-observations": [{"observation-uuid": _OBS}],
             "related-risks": [{"risk-uuid": _RISK}]},
        ],
    }}


@pytest.fixture
def poam():
    return OSCAL.loads(json.dumps(_poam_dict()))


def test_injects_findings_observations_risks(poam):
    item = poam.poam_item(_ITEM)
    assert [f["uuid"] for f in item["findings"]] == [_FIND]
    assert [o["uuid"] for o in item["observations"]] == [_OBS]
    assert [r["uuid"] for r in item["risks"]] == [_RISK]
    # raw reference arrays preserved
    assert item["related-findings"][0]["finding-uuid"] == _FIND


def test_actors_populated(poam):
    item = poam.poam_item(_ITEM)
    assert item["origins"][0]["actors"][0]["party"]["name"] == "Acme"


def test_injected_objects_are_fully_resolved(poam):
    item = poam.poam_item(_ITEM)
    # the injected finding carries its own observations + risks
    f = item["findings"][0]
    assert {o["uuid"] for o in f["observations"]} == {_OBS}
    assert {r["uuid"] for r in f["risks"]} == {_RISK}
    # the injected observation has its actors populated (tool -> component)
    assert item["observations"][0]["origins"][0]["actors"][0]["tool"]["title"] == "Scanner"


def test_unknown_and_empty_return_none(poam):
    assert poam.poam_item("deadbeef-0000-4000-8000-000000000000") is None
    assert poam.poam_item("") is None


def test_returns_safe_copy(poam):
    poam.poam_item(_ITEM)["title"] = "MUTATED"
    assert poam.poam_item(_ITEM)["title"] == "Remediate"
