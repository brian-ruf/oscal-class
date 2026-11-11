"""
Unit tests for the assessment-layer step-1 foundation (docs/assessment_getters.md §3–§4):

Module helpers (oscal.oscal_assessment):
    index_local_definitions(doc)        -> {container: {uuid: object}} local index
    _enrich_origins(doc, obj, index)    -> resolve origins[].actors[] + related-tasks[]
    _enrich_subjects(doc, obj, index)   -> resolve subject references (subject-uuid)
    _enrich_related_references(doc, obj) -> resolve related-observations/risks/findings

Intra-document getters (_AssessmentObjectsMixin, on AssessmentResults + POAM):
    .observation() / .risk() / .finding()  (keyed by uuid)

Every library-injected field uses a `resolved-` prefix so it never collides with a real
OSCAL field; resolvers return detached safe copies; dangling references surface a visible
`[Invalid ... Reference]` placeholder rather than vanishing. These operate on the loaded
`_dict` and do not require a fully schema-valid document.
"""
import copy
import json

import pytest

from oscal import OSCAL
from oscal.oscal_assessment import (
    index_local_definitions,
    _enrich_origins,
    _enrich_subjects,
    _enrich_related_references,
    _placeholder,
)

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}

_PARTY = "99999999-0000-4000-8000-000000000001"
_LOCATION = "88888888-0000-4000-8000-000000000001"
_COMP = "66666666-0000-4000-8000-000000000001"
_PLATFORM = "67676767-0000-4000-8000-000000000001"
_USER = "55555555-0000-4000-8000-000000000001"
_INV = "77777777-0000-4000-8000-000000000001"
_TASK = "44444444-0000-4000-8000-000000000001"

_OBS = "30000000-0000-4000-8000-000000000001"
_RISK = "20000000-0000-4000-8000-000000000001"
_FINDING = "40000000-0000-4000-8000-000000000001"
_RESULT = "10000000-0000-4000-8000-000000000001"


def _metadata():
    return {
        "title": "T", **_META,
        "roles": [{"id": "assessor", "title": "Lead Assessor"}],
        "parties": [{"uuid": _PARTY, "type": "organization",
                     "name": "Acme Assessors", "short-name": "Acme"}],
        "locations": [{"uuid": _LOCATION, "title": "HQ Datacenter"}],
    }


def _result_local_definitions():
    return {
        "components": [{"uuid": _COMP, "type": "software", "title": "Scanner Tool",
                        "description": "d", "status": {"state": "operational"}}],
        "inventory-items": [{"uuid": _INV, "description": "Server One"}],
        "users": [{"uuid": _USER, "title": "Operator"}],
        "assessment-assets": {
            "assessment-platforms": [{"uuid": _PLATFORM, "title": "Nessus Platform"}],
        },
        "tasks": [{"uuid": _TASK, "type": "action", "title": "Scan Task"}],
    }


def _ar_dict():
    """A minimal-but-real AssessmentResults with one result carrying local-definitions
    and one observation / risk / finding."""
    return {"assessment-results": {
        "uuid": "aaaaaaaa-0000-4000-8000-000000000001",
        "metadata": _metadata(),
        "import-ap": {"href": "#"},
        "results": [{
            "uuid": _RESULT, "title": "R", "description": "d",
            "start": "2026-01-01T00:00:00Z",
            "local-definitions": _result_local_definitions(),
            "observations": [{
                "uuid": _OBS, "title": "TLS probe", "description": "o",
                "methods": ["EXAMINE"], "collected": "2026-01-01T00:00:00Z",
            }],
            "risks": [{
                "uuid": _RISK, "title": "Weak cipher", "description": "d",
                "statement": "s", "status": "open",
                "related-observations": [{"observation-uuid": _OBS}],
            }],
            "findings": [{
                "uuid": _FINDING, "title": "AC-2 not met", "description": "d",
                "target": {"type": "objective-id", "target-id": "ac-2_obj",
                           "status": {"state": "not-satisfied"}},
                "related-observations": [{"observation-uuid": _OBS}],
                "related-risks": [{"risk-uuid": _RISK}],
            }],
        }],
    }}


def _poam_dict():
    """A minimal-but-real POA&M with top-level observation / risk / finding and a
    poam-item citing all three."""
    return {"plan-of-action-and-milestones": {
        "uuid": "bbbbbbbb-0000-4000-8000-000000000001",
        "metadata": _metadata(),
        "import-ssp": {"href": "#"},
        "local-definitions": {
            "components": [{"uuid": _COMP, "type": "software", "title": "Scanner Tool",
                            "description": "d", "status": {"state": "operational"}}],
            "inventory-items": [{"uuid": _INV, "description": "Server One"}],
        },
        "observations": [{
            "uuid": _OBS, "title": "TLS probe", "description": "o",
            "methods": ["EXAMINE"], "collected": "2026-01-01T00:00:00Z",
        }],
        "risks": [{
            "uuid": _RISK, "title": "Weak cipher", "description": "d",
            "statement": "s", "status": "open",
        }],
        "findings": [{
            "uuid": _FINDING, "title": "AC-2 not met", "description": "d",
            "target": {"type": "objective-id", "target-id": "ac-2_obj",
                       "status": {"state": "not-satisfied"}},
        }],
        "poam-items": [{
            "uuid": "cccccccc-0000-4000-8000-000000000001",
            "title": "Remediate weak cipher", "description": "d",
            "related-findings": [{"finding-uuid": _FINDING}],
            "related-observations": [{"observation-uuid": _OBS}],
            "related-risks": [{"risk-uuid": _RISK}],
        }],
    }}


@pytest.fixture
def ar():
    return OSCAL.loads(json.dumps(_ar_dict()))


@pytest.fixture
def poam():
    return OSCAL.loads(json.dumps(_poam_dict()))


# ===========================================================================
class TestIndexLocalDefinitions:
    def test_indexes_every_container_kind(self, ar):
        idx = index_local_definitions(ar)
        assert set(idx) == {"components", "assessment-platforms", "users",
                            "inventory-items", "tasks"}
        assert idx["components"][_COMP]["title"] == "Scanner Tool"
        assert idx["assessment-platforms"][_PLATFORM]["title"] == "Nessus Platform"
        assert idx["users"][_USER]["title"] == "Operator"
        assert idx["inventory-items"][_INV]["description"] == "Server One"
        assert idx["tasks"][_TASK]["title"] == "Scan Task"

    def test_finds_objects_nested_under_result(self, ar):
        # These live under results[].local-definitions, not top-level: the sweep is
        # path-agnostic and still finds them.
        assert _COMP in index_local_definitions(ar)["components"]

    def test_empty_maps_when_absent(self, poam):
        idx = index_local_definitions(poam)
        assert idx["components"][_COMP]["title"] == "Scanner Tool"
        assert idx["users"] == {}          # POA&M local-definitions has no users
        assert idx["tasks"] == {}


# ===========================================================================
class TestEnrichOrigins:
    def _origins(self):
        return {"origins": [{
            "actors": [
                {"type": "party", "actor-uuid": _PARTY, "role-id": "assessor"},
                {"type": "tool", "actor-uuid": _COMP},
                {"type": "assessment-platform", "actor-uuid": _PLATFORM},
                {"type": "party", "actor-uuid": "deadbeef-0000-4000-8000-000000000000"},
            ],
            "related-tasks": [
                {"task-uuid": _TASK},
                {"task-uuid": "deadbeef-0000-4000-8000-000000000000"},
            ],
        }]}

    def test_actor_resolution_by_type(self, ar):
        obj = self._origins()
        _enrich_origins(ar, obj, index_local_definitions(ar))
        actors = obj["origins"][0]["actors"]
        assert actors[0]["resolved-title"] == "Acme Assessors"
        assert actors[0]["resolved-role"] == "Lead Assessor"
        assert actors[1]["resolved-title"] == "Scanner Tool"
        assert actors[2]["resolved-title"] == "Nessus Platform"

    def test_dangling_actor_gets_placeholder(self, ar):
        obj = self._origins()
        _enrich_origins(ar, obj, index_local_definitions(ar))
        assert obj["origins"][0]["actors"][3]["resolved-title"] == _placeholder("party")

    def test_related_task_resolution_and_placeholder(self, ar):
        obj = self._origins()
        _enrich_origins(ar, obj, index_local_definitions(ar))
        rts = obj["origins"][0]["related-tasks"]
        assert rts[0]["resolved-title"] == "Scan Task"
        assert rts[1]["resolved-title"] == _placeholder("task")

    def test_raw_fields_left_intact(self, ar):
        obj = self._origins()
        _enrich_origins(ar, obj, index_local_definitions(ar))
        a0 = obj["origins"][0]["actors"][0]
        assert a0["actor-uuid"] == _PARTY and a0["role-id"] == "assessor"

    def test_no_resolved_role_without_role_id(self, ar):
        obj = self._origins()
        _enrich_origins(ar, obj, index_local_definitions(ar))
        assert "resolved-role" not in obj["origins"][0]["actors"][1]


# ===========================================================================
class TestEnrichSubjects:
    def _subjects(self):
        return {"subjects": [
            {"subject-uuid": _COMP, "type": "component"},
            {"subject-uuid": _INV, "type": "inventory-item"},
            {"subject-uuid": _USER, "type": "user"},
            {"subject-uuid": _PARTY, "type": "party"},
            {"subject-uuid": _LOCATION, "type": "location"},
            {"subject-uuid": "deadbeef-0000-4000-8000-000000000000", "type": "component"},
        ]}

    def test_resolution_by_type(self, ar):
        obj = self._subjects()
        _enrich_subjects(ar, obj, index_local_definitions(ar))
        s = obj["subjects"]
        assert s[0]["resolved-title"] == "Scanner Tool"
        assert s[1]["resolved-title"] == "Server One"       # inventory-item -> description
        assert s[2]["resolved-title"] == "Operator"
        assert s[3]["resolved-title"] == "Acme Assessors"
        assert s[4]["resolved-title"] == "HQ Datacenter"

    def test_dangling_subject_placeholder(self, ar):
        obj = self._subjects()
        _enrich_subjects(ar, obj, index_local_definitions(ar))
        assert obj["subjects"][5]["resolved-title"] == _placeholder("component")

    def test_authored_title_preserved(self, ar):
        obj = {"subjects": [{"subject-uuid": _COMP, "type": "component",
                             "title": "Author's own label"}]}
        _enrich_subjects(ar, obj, index_local_definitions(ar))
        s = obj["subjects"][0]
        assert s["title"] == "Author's own label"            # never overwritten
        assert s["resolved-title"] == "Scanner Tool"         # added as a sibling

    def test_selection_form_untouched(self, ar):
        # An assessment-subject selection form has no subject-uuid of its own; its inner
        # include/exclude entries (which DO have subject-uuid) are still reached.
        obj = {"subjects": [{"type": "component",
                             "include-subjects": [{"subject-uuid": _COMP, "type": "component"}]}]}
        _enrich_subjects(ar, obj, index_local_definitions(ar))
        outer = obj["subjects"][0]
        assert "resolved-title" not in outer
        assert outer["include-subjects"][0]["resolved-title"] == "Scanner Tool"


# ===========================================================================
class TestEnrichRelatedReferences:
    def test_related_observation_resolution(self, ar):
        obj = {"related-observations": [{"observation-uuid": _OBS}]}
        _enrich_related_references(ar, obj)
        assert obj["related-observations"][0]["resolved-title"] == "TLS probe"

    def test_related_risk_resolution(self, ar):
        obj = {"related-risks": [{"risk-uuid": _RISK}]}
        _enrich_related_references(ar, obj)
        ref = obj["related-risks"][0]
        assert ref["resolved-title"] == "Weak cipher"
        assert ref["resolved-status"] == "open"

    def test_related_finding_resolution(self, poam):
        obj = {"related-findings": [{"finding-uuid": _FINDING}]}
        _enrich_related_references(poam, obj)
        ref = obj["related-findings"][0]
        assert ref["resolved-title"] == "AC-2 not met"
        assert ref["resolved-status"] == "not-satisfied"       # target.status.state

    def test_dangling_references_placeholder(self, ar):
        bad = "deadbeef-0000-4000-8000-000000000000"
        obj = {"related-observations": [{"observation-uuid": bad}],
               "related-risks": [{"risk-uuid": bad}]}
        _enrich_related_references(ar, obj)
        assert obj["related-observations"][0]["resolved-title"] == _placeholder("observation")
        assert obj["related-risks"][0]["resolved-title"] == _placeholder("risk")
        assert obj["related-risks"][0]["resolved-status"] == ""


# ===========================================================================
class TestIntraDocumentGetters:
    def test_ar_resolves_with_result_uuid(self, ar):
        obs = ar.observation(_OBS)
        assert obs["title"] == "TLS probe"
        assert obs["result-uuid"] == _RESULT          # owning result annotated
        assert ar.risk(_RISK)["result-uuid"] == _RESULT
        assert ar.finding(_FINDING)["result-uuid"] == _RESULT

    def test_poam_resolves_without_result_uuid(self, poam):
        obs = poam.observation(_OBS)
        assert obs["title"] == "TLS probe"
        assert "result-uuid" not in obs
        assert poam.risk(_RISK)["title"] == "Weak cipher"
        assert poam.finding(_FINDING)["title"] == "AC-2 not met"

    @pytest.mark.parametrize("getter", ["observation", "risk", "finding"])
    def test_unknown_uuid_returns_none(self, ar, getter):
        assert getattr(ar, getter)("deadbeef-0000-4000-8000-000000000000") is None

    @pytest.mark.parametrize("getter", ["observation", "risk", "finding"])
    def test_empty_uuid_returns_none(self, ar, getter):
        assert getattr(ar, getter)("") is None

    def test_returns_safe_copy(self, ar):
        obs = ar.observation(_OBS)
        obs["title"] = "MUTATED"
        assert ar.observation(_OBS)["title"] == "TLS probe"

    def test_assessment_plan_has_no_object_getters(self):
        ap = OSCAL.loads(json.dumps({"assessment-plan": {
            "uuid": "dddddddd-0000-4000-8000-000000000001",
            "metadata": _metadata(), "import-ssp": {"href": "#"},
            "reviewed-controls": {"control-selections": [{}]},
        }}))
        # AssessmentPlan does not inherit the mixin; the cross-model guard makes the call
        # raise UnsupportedModelOperation (an AttributeError subclass).
        assert not hasattr(ap, "observation")
