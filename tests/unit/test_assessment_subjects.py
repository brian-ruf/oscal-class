"""
Unit tests for:

* party/location scope confinement (`stop_at_ssp`) on the base getters — an assessment
  model resolving a party/location descends only to the imported SSP, never into the SSP's
  own profile/catalog.
* SSP.components().
* the selection-form `.subjects()` helper on the assessment models (include-subjects
  enrichment + include-all materialization; component type/asset-type; inventory-item title
  derivation).
"""
import json
import os
import tempfile

import pytest

from oscal import OSCAL, SSP

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}


def _meta(t):
    return {"title": t, **_META}


# A party uuid defined in BOTH the catalog and the SSP, with different names, to prove scope.
_PARTY = "aaaaaaaa-0000-4000-8000-000000000001"
_LOC = "dddddddd-0000-4000-8000-000000000001"
_COMP = "70000000-0000-4000-8000-00000000000a"
_INV = "90000000-0000-4000-8000-000000000001"
_USER = "60000000-0000-4000-8000-000000000001"
_SSP_UUID = "30000000-0000-4000-8000-000000000001"


def _catalog():
    return {"catalog": {
        "uuid": "10000000-0000-4000-8000-000000000001",
        "metadata": {"title": "Cat", **_META,
                     "parties": [{"uuid": _PARTY, "type": "organization", "name": "CATALOG Org"}]},
        "groups": [{"id": "ac", "title": "AC", "controls": [{"id": "ac-1", "title": "Policy"}]}],
    }}


def _profile():
    return {"profile": {
        "uuid": "20000000-0000-4000-8000-000000000001", "metadata": _meta("Prof"),
        "imports": [{"href": "catalog.json", "include-all": {}}],
    }}


def _ssp():
    return {"system-security-plan": {
        "uuid": _SSP_UUID,
        "metadata": {"title": "SSP", **_META,
                     "parties": [{"uuid": _PARTY, "type": "organization", "name": "SSP Org"}],
                     "locations": [{"uuid": _LOC, "title": "SSP Datacenter"}]},
        "import-profile": {"href": "profile.json"},
        "system-characteristics": {
            "system-ids": [{"id": "sys-1"}], "system-name": "Test", "description": "d",
            "system-information": {"information-types": [{"title": "IT", "description": "d"}]},
            "security-sensitivity-level": "low",
            "security-impact-level": {"security-objective-confidentiality": "low",
                                      "security-objective-integrity": "low",
                                      "security-objective-availability": "low"},
            "status": {"state": "operational"}, "authorization-boundary": {"description": "b"},
        },
        "system-implementation": {
            "users": [{"uuid": _USER, "title": "Operator", "role-ids": []}],
            "components": [{"uuid": _COMP, "type": "software", "title": "SSP Component",
                            "description": "d", "status": {"state": "operational"},
                            "props": [{"name": "asset-type", "value": "appliance"}]}],
            "inventory-items": [
                {"uuid": _INV, "description": "srv",
                 "props": [{"name": "fqdn", "value": "host.example.com"}],
                 "implemented-components": [{"component-uuid": _COMP}]}],
        },
        "control-implementation": {"description": "ci", "implemented-requirements": [
            {"uuid": "80000000-0000-4000-8000-000000000001", "control-id": "ac-1"}]},
    }}


def _poam(subjects=None):
    root = {"uuid": "bbbbbbbb-0000-4000-8000-000000000001", "metadata": _meta("POAM"),
            "import-ssp": {"href": "ssp.json"},
            "poam-items": [{"uuid": "cccccccc-0000-4000-8000-000000000001",
                            "title": "x", "description": "d"}]}
    return {"plan-of-action-and-milestones": root}


@pytest.fixture
def poam_chain():
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog()), ("profile.json", _profile()),
                          ("ssp.json", _ssp()), ("poam.json", _poam())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield OSCAL.load(os.path.join(d, "poam.json"))


# ===========================================================================
class TestPartyLocationScope:
    def test_default_cascade_reaches_catalog_party(self, poam_chain):
        # the SSP defines the party first (nearer), so even the full cascade finds SSP's.
        assert poam_chain.get_party_by_uuid(_PARTY)["name"] == "SSP Org"

    def test_stop_at_ssp_confines_to_assessment_plus_ssp(self, poam_chain):
        # SSP is the nearest here; stop_at_ssp must still return it and never the catalog's.
        assert poam_chain.get_party_by_uuid(_PARTY, stop_at_ssp=True)["name"] == "SSP Org"

    def test_stop_at_ssp_excludes_deeper_only_party(self):
        # A party that exists ONLY in the catalog is reachable by default but NOT under
        # stop_at_ssp (the cascade does not descend past the SSP).
        with tempfile.TemporaryDirectory() as d:
            cat = _catalog()
            only = "ffffffff-0000-4000-8000-000000000001"
            cat["catalog"]["metadata"]["parties"].append(
                {"uuid": only, "type": "organization", "name": "CATALOG Only"})
            ssp = _ssp()
            ssp["system-security-plan"]["metadata"]["parties"] = []   # SSP has no parties
            for name, doc in [("catalog.json", cat), ("profile.json", _profile()),
                              ("ssp.json", ssp), ("poam.json", _poam())]:
                with open(os.path.join(d, name), "w") as fh:
                    json.dump(doc, fh)
            poam = OSCAL.load(os.path.join(d, "poam.json"))
            assert poam.get_party_by_uuid(only)["name"] == "CATALOG Only"   # full cascade
            assert poam.get_party_by_uuid(only, stop_at_ssp=True) is None    # confined

    def test_location_stop_at_ssp(self, poam_chain):
        assert poam_chain.get_location_by_uuid(_LOC, stop_at_ssp=True)["title"] == "SSP Datacenter"


# ===========================================================================
class TestSSPComponents:
    def test_components_index_shape(self):
        ssp = SSP.loads(json.dumps(_ssp()))
        comps = ssp.components()
        assert comps == [{"uuid": _COMP, "title": "SSP Component", "type": "software",
                          "asset-type": "appliance"}]


# ===========================================================================
class TestSubjectsSelection:
    def test_include_subjects_component(self, poam_chain):
        subs = [{"type": "component",
                 "include-subjects": [{"subject-uuid": _COMP}]}]
        out = poam_chain.subjects(subs)
        inc = out[0]["include-subjects"][0]
        assert inc["title"] == "SSP Component"
        assert inc["type"] == "software"                 # component's own type
        assert inc["asset-type"] == "appliance"

    def test_include_subjects_party_scoped(self, poam_chain):
        subs = [{"type": "party", "include-subjects": [{"subject-uuid": _PARTY}]}]
        out = poam_chain.subjects(subs)
        assert out[0]["include-subjects"][0]["title"] == "SSP Org"   # name, SSP-scoped

    def test_inventory_item_title_from_implemented_component(self, poam_chain):
        subs = [{"type": "inventory-item", "include-subjects": [{"subject-uuid": _INV}]}]
        out = poam_chain.subjects(subs)
        # the inventory-item references _COMP -> borrow its title
        assert out[0]["include-subjects"][0]["title"] == "SSP Component"

    def test_include_all_materializes(self, poam_chain):
        subs = [{"type": "component", "include-all": {}}]
        out = poam_chain.subjects(subs)
        inc = out[0]["include-subjects"]
        assert [e["subject-uuid"] for e in inc] == [_COMP]
        assert inc[0]["title"] == "SSP Component" and inc[0]["type"] == "software"

    def test_does_not_mutate_input(self, poam_chain):
        subs = [{"type": "component", "include-subjects": [{"subject-uuid": _COMP}]}]
        poam_chain.subjects(subs)
        assert "title" not in subs[0]["include-subjects"][0]

    def test_unknown_type_left_alone(self, poam_chain):
        subs = [{"type": "something-else", "include-subjects": [{"subject-uuid": "x"}]}]
        out = poam_chain.subjects(subs)
        assert "title" not in out[0]["include-subjects"][0]
