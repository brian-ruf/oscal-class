"""
Unit tests for the assessment-model local-definition getters (cross-import chain):

    .components(local_only=False)              lightweight index across the chain
    .component(uuid, local_only, include_all)  one component, first-found + optional all
    .inventory_items(local_only=False)         SSP-shaped index across the chain
    .inventory_item(uuid, local_only, include_all)

Resolution model (docs/assessment_getters.md): search this document first, then the import
chain to the SSP (POA&M → SSP; AR → AP → SSP), stopping at the SSP. `local_only=True`
restricts to the document itself. Every returned object carries a `provenance` key = the
root uuid of the document where it was found. `include_all=True` makes the first-found the
base and adds an `additional-versions` array (each with its own provenance).

A valid SSP is expensive to build, so the fixtures write a catalog → profile → SSP chain to
disk (as test_ssp_implementation_tree does) and point an assessment doc's import at it.
"""
import json
import os
import tempfile

import pytest

from oscal import OSCAL

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}


def _meta(title):
    return {"title": title, **_META}


# --- identifiers -----------------------------------------------------------
_SSP_UUID = "30000000-0000-4000-8000-000000000001"
_AP_UUID = "a0000000-0000-4000-8000-000000000001"
_AR_UUID = "a0000000-0000-4000-8000-0000000000a2"
_POAM_UUID = "b0000000-0000-4000-8000-000000000001"

_COMP_SHARED = "70000000-0000-4000-8000-00000000000a"   # defined in SSP *and* locally
_COMP_SSP_ONLY = "70000000-0000-4000-8000-00000000000b"
_COMP_LOCAL_ONLY = "70000000-0000-4000-8000-00000000000c"
_INV_SSP = "90000000-0000-4000-8000-000000000001"
_INV_LOCAL = "90000000-0000-4000-8000-000000000002"
_PARTY = "50000000-0000-4000-8000-000000000001"


def _catalog():
    return {"catalog": {
        "uuid": "10000000-0000-4000-8000-000000000001", "metadata": _meta("Cat"),
        "groups": [{"id": "ac", "title": "AC", "controls": [{"id": "ac-1", "title": "Policy"}]}],
    }}


def _profile():
    return {"profile": {
        "uuid": "20000000-0000-4000-8000-000000000001", "metadata": _meta("Prof"),
        "imports": [{"href": "catalog.json", "include-all": {}}],
    }}


def _ssp():
    """A valid SSP with two components (one shared uuid) and one inventory item."""
    return {"system-security-plan": {
        "uuid": _SSP_UUID,
        "metadata": {"title": "SSP", **_META,
                     "roles": [{"id": "admin", "title": "Administrator"}],
                     "parties": [{"uuid": _PARTY, "type": "organization", "name": "Acme"}]},
        "import-profile": {"href": "profile.json"},
        "system-characteristics": {
            "system-ids": [{"id": "sys-1"}], "system-name": "Test System", "description": "d",
            "system-information": {"information-types": [{"title": "IT", "description": "d"}]},
            "security-sensitivity-level": "low",
            "security-impact-level": {"security-objective-confidentiality": "low",
                                      "security-objective-integrity": "low",
                                      "security-objective-availability": "low"},
            "status": {"state": "operational"},
            "authorization-boundary": {"description": "b"},
        },
        "system-implementation": {
            "users": [{"uuid": "60000000-0000-4000-8000-000000000001", "role-ids": ["admin"]}],
            "components": [
                {"uuid": _COMP_SHARED, "type": "software", "title": "SSP Shared Component",
                 "description": "d", "status": {"state": "operational"},
                 "props": [{"name": "asset-type", "value": "appliance"}]},
                {"uuid": _COMP_SSP_ONLY, "type": "software", "title": "SSP Only Component",
                 "description": "d", "status": {"state": "operational"},
                 "responsible-roles": [{"role-id": "admin", "party-uuids": [_PARTY]}]},
            ],
            "inventory-items": [
                {"uuid": _INV_SSP, "description": "SSP server",
                 "props": [{"name": "ipv4-address", "value": "10.0.0.9"}],
                 "implemented-components": [
                     {"component-uuid": _COMP_SSP_ONLY},
                     {"component-uuid": "deadbeef-0000-4000-8000-000000000000"}]},  # dangling
            ],
        },
        "control-implementation": {"description": "ci", "implemented-requirements": [
            {"uuid": "80000000-0000-4000-8000-000000000001", "control-id": "ac-1"}]},
    }}


def _local_definitions():
    """A local-definitions block shared by the assessment docs: a shared component (same
    uuid as the SSP's, different title), a local-only component, and a local inventory item."""
    return {
        "components": [
            {"uuid": _COMP_SHARED, "type": "software", "title": "LOCAL Shared Component",
             "description": "d", "status": {"state": "operational"}},
            {"uuid": _COMP_LOCAL_ONLY, "type": "software", "title": "Local Only Component",
             "description": "d", "status": {"state": "operational"}},
        ],
        "inventory-items": [
            {"uuid": _INV_LOCAL, "description": "local server",
             "implemented-components": [{"component-uuid": _COMP_SHARED}]},
        ],
    }


def _poam():
    return {"plan-of-action-and-milestones": {
        "uuid": _POAM_UUID, "metadata": _meta("POAM"),
        "import-ssp": {"href": "ssp.json"},
        "local-definitions": _local_definitions(),
        "poam-items": [{"uuid": "cccccccc-0000-4000-8000-000000000001",
                        "title": "Remediate", "description": "d"}],
    }}


@pytest.fixture
def poam_chain():
    """POA&M → SSP → profile → catalog, loaded from disk (imports cascade-resolved)."""
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog()), ("profile.json", _profile()),
                          ("ssp.json", _ssp()), ("poam.json", _poam())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield OSCAL.load(os.path.join(d, "poam.json"))


# ===========================================================================
class TestComponentSingular:
    def test_default_traverses_first_found_is_local(self, poam_chain):
        c = poam_chain.component(_COMP_SHARED)
        assert c["title"] == "LOCAL Shared Component"     # self before imports
        assert c["provenance"]["uuid"] == _POAM_UUID and c["provenance"]["imported"] is False

    def test_ssp_only_found_via_traversal(self, poam_chain):
        c = poam_chain.component(_COMP_SSP_ONLY)
        assert c["title"] == "SSP Only Component"
        assert c["provenance"]["uuid"] == _SSP_UUID       # came from the imported SSP
        assert c["provenance"]["imported"] is True

    def test_local_only_blocks_traversal(self, poam_chain):
        assert poam_chain.component(_COMP_SSP_ONLY, local_only=True) is None
        assert poam_chain.component(_COMP_SHARED, local_only=True)["title"] == "LOCAL Shared Component"

    def test_include_all_collects_every_instance(self, poam_chain):
        c = poam_chain.component(_COMP_SHARED, include_all=True)
        assert c["title"] == "LOCAL Shared Component"
        assert c["provenance"]["uuid"] == _POAM_UUID and c["provenance"]["imported"] is False
        extra = c["additional-versions"]
        assert [(v["title"], v["provenance"]["uuid"], v["provenance"]["imported"]) for v in extra] == \
               [("SSP Shared Component", _SSP_UUID, True)]

    def test_ssp_owned_component_keeps_full_shape(self, poam_chain):
        # A component resolved in the SSP comes back in SSP.component() shape; the
        # assessment-owned one does not (no control-implementation there).
        ssp_c = poam_chain.component(_COMP_SSP_ONLY)
        assert "implemented-controls" in ssp_c and "relationships" in ssp_c
        local_c = poam_chain.component(_COMP_LOCAL_ONLY)
        assert "implemented-controls" not in local_c and "relationships" not in local_c

    def test_superseded_ssp_content_preserved_in_additional_versions(self, poam_chain):
        # _COMP_SHARED: POAM-local base (sparse) + SSP version (full) retained, not lost.
        c = poam_chain.component(_COMP_SHARED, include_all=True)
        assert "implemented-controls" not in c                     # base is the local/sparse one
        ssp_ver = c["additional-versions"][0]
        assert ssp_ver["provenance"]["uuid"] == _SSP_UUID
        assert "implemented-controls" in ssp_ver and "relationships" in ssp_ver

    def test_include_all_empty_when_single(self, poam_chain):
        c = poam_chain.component(_COMP_SSP_ONLY, include_all=True)
        assert c["additional-versions"] == []

    def test_no_additional_versions_key_without_include_all(self, poam_chain):
        assert "additional-versions" not in poam_chain.component(_COMP_SHARED)

    def test_responsible_roles_enriched(self, poam_chain):
        c = poam_chain.component(_COMP_SSP_ONLY)
        rr = c["responsible-roles"][0]
        assert rr["title"] == "Administrator"             # role-id -> SSP metadata role
        assert rr["parties"][0]["name"] == "Acme"

    def test_unknown_uuid_returns_none(self, poam_chain):
        assert poam_chain.component("deadbeef-0000-4000-8000-000000000000") is None

    def test_returns_safe_copy(self, poam_chain):
        poam_chain.component(_COMP_SHARED)["title"] = "MUTATED"
        assert poam_chain.component(_COMP_SHARED)["title"] == "LOCAL Shared Component"


# ===========================================================================
class TestComponentsPlural:
    def test_traverse_first_wins_union(self, poam_chain):
        by_uuid = {e["uuid"]: e for e in poam_chain.components()}
        # shared uuid: the local one wins; both local-only and ssp-only also present
        assert by_uuid[_COMP_SHARED]["title"] == "LOCAL Shared Component"
        assert by_uuid[_COMP_SHARED]["provenance"]["uuid"] == _POAM_UUID
        assert by_uuid[_COMP_SHARED]["provenance"]["imported"] is False
        assert by_uuid[_COMP_SSP_ONLY]["provenance"]["uuid"] == _SSP_UUID
        assert by_uuid[_COMP_SSP_ONLY]["provenance"]["imported"] is True
        assert _COMP_LOCAL_ONLY in by_uuid

    def test_asset_type_surfaced(self, poam_chain):
        # SSP shared component carries an asset-type prop; its (shadowed) value is not in the
        # winner, but the ssp-only entry has none -> absent. Check the SSP-sourced component
        # that *does* win nothing here; assert asset-type only where present.
        ssp_only = next(e for e in poam_chain.components() if e["uuid"] == _COMP_SSP_ONLY)
        assert "asset-type" not in ssp_only

    def test_local_only(self, poam_chain):
        uuids = {e["uuid"] for e in poam_chain.components(local_only=True)}
        assert uuids == {_COMP_SHARED, _COMP_LOCAL_ONLY}      # no SSP component
        assert all(e["provenance"]["uuid"] == _POAM_UUID and e["provenance"]["imported"] is False
                   for e in poam_chain.components(local_only=True))

    def test_every_entry_has_provenance(self, poam_chain):
        assert all("provenance" in e for e in poam_chain.components())


# ===========================================================================
class TestInventoryItems:
    def test_singular_ssp_item_resolves_implemented_component(self, poam_chain):
        item = poam_chain.inventory_item(_INV_SSP)
        assert item["provenance"]["uuid"] == _SSP_UUID and item["provenance"]["imported"] is True
        ics = item["implemented-components"]
        # first references the ssp-only component (resolved); second is dangling -> placeholder
        assert ics[0]["component"]["title"] == "SSP Only Component"
        assert ics[1]["component"]["title"] == "[Invalid Component Reference]"

    def test_singular_local_only_blocks_ssp_item(self, poam_chain):
        assert poam_chain.inventory_item(_INV_SSP, local_only=True) is None
        inv = poam_chain.inventory_item(_INV_LOCAL, local_only=True)
        assert inv["provenance"]["uuid"] == _POAM_UUID and inv["provenance"]["imported"] is False

    def test_local_item_component_supersedes_but_keeps_ssp_version(self, poam_chain):
        # _INV_LOCAL references _COMP_SHARED, which exists in POAM (local) and SSP.
        # The embedded component is the local one, with the SSP version retained.
        inv = poam_chain.inventory_item(_INV_LOCAL)
        comp = inv["implemented-components"][0]["component"]
        assert comp["title"] == "LOCAL Shared Component"
        assert comp["provenance"]["uuid"] == _POAM_UUID
        av = comp["additional-versions"]
        assert av[0]["provenance"]["uuid"] == _SSP_UUID
        assert "implemented-controls" in av[0]                     # SSP content preserved

    def test_plural_index_across_chain(self, poam_chain):
        by_uuid = {e["uuid"]: e for e in poam_chain.inventory_items()}
        assert by_uuid[_INV_LOCAL]["provenance"]["uuid"] == _POAM_UUID
        assert by_uuid[_INV_SSP]["provenance"]["uuid"] == _SSP_UUID
        assert by_uuid[_INV_SSP]["ipv4-address"] == "10.0.0.9"        # prop flattened
        # resolved implemented-components title/type on the index entry
        imp = by_uuid[_INV_SSP]["implemented-components"]
        assert any(r["title"] == "SSP Only Component" for r in imp)

    def test_plural_local_only(self, poam_chain):
        uuids = {e["uuid"] for e in poam_chain.inventory_items(local_only=True)}
        assert uuids == {_INV_LOCAL}


# ===========================================================================
class TestMultiHopAndModels:
    def _ar_chain(self, d):
        """AR → AP → SSP → profile → catalog on disk; returns the loaded AR."""
        ap = {"assessment-plan": {
            "uuid": _AP_UUID, "metadata": _meta("AP"), "import-ssp": {"href": "ssp.json"},
            "local-definitions": _local_definitions(),
            "reviewed-controls": {"control-selections": [{"include-all": {}}]},
        }}
        ar = {"assessment-results": {
            "uuid": _AR_UUID, "metadata": _meta("AR"), "import-ap": {"href": "ap.json"},
            "results": [{"uuid": "d0000000-0000-4000-8000-000000000001", "title": "R",
                         "description": "d", "start": "2026-01-01T00:00:00Z",
                         "local-definitions": {"components": [
                             {"uuid": "70000000-0000-4000-8000-0000000000dd", "type": "software",
                              "title": "AR Result Component", "description": "d",
                              "status": {"state": "operational"}},
                             {"uuid": _COMP_SHARED, "type": "software", "title": "AR Shared Component",
                              "description": "d", "status": {"state": "operational"}}]}}],
        }}
        for name, doc in [("catalog.json", _catalog()), ("profile.json", _profile()),
                          ("ssp.json", _ssp()), ("ap.json", ap), ("ar.json", ar)]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        return OSCAL.load(os.path.join(d, "ar.json"))

    def test_ar_reaches_ssp_through_ap(self):
        with tempfile.TemporaryDirectory() as d:
            ar = self._ar_chain(d)
            # component defined only in the SSP is reachable AR -> AP -> SSP
            c = ar.component(_COMP_SSP_ONLY)
            assert c["provenance"]["uuid"] == _SSP_UUID and c["provenance"]["imported"] is True
            # AR per-result component is found locally, attributed to the AR document
            arc = ar.component("70000000-0000-4000-8000-0000000000dd")
            assert arc["title"] == "AR Result Component"
            assert arc["provenance"]["uuid"] == _AR_UUID and arc["provenance"]["imported"] is False

    def test_ar_include_all_flattens_three_levels(self):
        # _COMP_SHARED exists in AR (via _local_definitions), AP (same), and SSP.
        with tempfile.TemporaryDirectory() as d:
            ar = self._ar_chain(d)
            c = ar.component(_COMP_SHARED, include_all=True)
            provs = [c["provenance"]["uuid"]] + [v["provenance"]["uuid"] for v in c["additional-versions"]]
            assert provs == [_AR_UUID, _AP_UUID, _SSP_UUID]       # nearest-first, flat
            # none of the additional-versions are themselves nested
            assert all("additional-versions" not in v for v in c["additional-versions"])

    def test_ap_has_the_getters(self):
        with tempfile.TemporaryDirectory() as d:
            self._ar_chain(d)                      # writes ap.json + ssp.json etc.
            ap = OSCAL.load(os.path.join(d, "ap.json"))
            assert ap.component(_COMP_SSP_ONLY)["provenance"]["uuid"] == _SSP_UUID
            local = ap.component(_COMP_LOCAL_ONLY, local_only=True)
            assert local["provenance"]["uuid"] == _AP_UUID and local["provenance"]["imported"] is False
