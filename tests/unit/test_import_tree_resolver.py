"""
Tests for the import-tree ID resolver (OSCAL.find_in_import_tree / reachable_ids) and
for out-of-scope cross-reference rewriting during profile resolution.
"""
import json
import os

import pytest

from oscal import OSCAL, Catalog, Profile


_HERE = os.path.dirname(__file__)
_JSON = os.path.join(_HERE, "..", "test-data", "json")


# ===========================================================================
# find_in_import_tree — synthetic (precise) coverage
# ===========================================================================
def _catalog_file(tmp_path):
    doc = {"catalog": {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "metadata": {"title": "Src", "last-modified": "2026-01-01T00:00:00Z",
                     "version": "1", "oscal-version": "1.1.3",
                     "roles": [{"id": "sysowner", "title": "System Owner"}],
                     "locations": [{"uuid": "dddddddd-4444-4444-8444-444444444444",
                                    "title": "HQ"}],
                     "parties": [{"uuid": "aaaaaaaa-1111-4111-8111-111111111111",
                                  "type": "organization", "name": "Acme"}],
                     "responsible-parties": [
                         {"role-id": "sysowner",
                          "party-uuids": ["aaaaaaaa-1111-4111-8111-111111111111"]}]},
        "groups": [{"id": "ac", "title": "AC", "controls": [
            {"id": "ac-1", "title": "Policy",
             "params": [{"id": "ac-1_prm_1", "label": "x"}],
             "parts": [{"id": "ac-1_smt", "name": "statement", "prose": "Do it."}]}]}],
        "back-matter": {"resources": [{"uuid": "bbbbbbbb-2222-4222-8222-222222222222",
                                       "title": "Cited"}]},
    }}
    path = os.path.join(str(tmp_path), "cat.json")
    with open(path, "w") as fh:
        json.dump(doc, fh)
    return path


@pytest.fixture
def profile_over_catalog(tmp_path):
    cat = _catalog_file(tmp_path)
    p = Profile.new("P")
    p.add_import(cat, include_all=True)
    p.set_merge(as_is=True)
    return p


class TestFindInImportTree:

    def test_resource_by_uuid(self, profile_over_catalog):
        r = profile_over_catalog.find_in_import_tree("bbbbbbbb-2222-4222-8222-222222222222")
        assert r is not None and r["kind"] == "resource"

    def test_role_by_id(self, profile_over_catalog):
        r = profile_over_catalog.find_in_import_tree("sysowner", kinds=["role"])
        assert r is not None and r["kind"] == "role" and r["element"]["title"] == "System Owner"

    def test_party_by_uuid(self, profile_over_catalog):
        r = profile_over_catalog.find_in_import_tree("aaaaaaaa-1111-4111-8111-111111111111")
        assert r is not None and r["kind"] == "party"

    def test_control_by_id(self, profile_over_catalog):
        r = profile_over_catalog.find_in_import_tree("ac-1", kinds=["control"])
        assert r is not None and r["kind"] == "control"

    def test_param_and_part(self, profile_over_catalog):
        assert profile_over_catalog.find_in_import_tree("ac-1_prm_1", kinds=["param"])["kind"] == "param"
        assert profile_over_catalog.find_in_import_tree("ac-1_smt", kinds=["part"])["kind"] == "part"

    def test_kinds_filter_excludes(self, profile_over_catalog):
        # ac-1 is a control; searching only resources must not find it
        assert profile_over_catalog.find_in_import_tree("ac-1", kinds=["resource"]) is None

    def test_not_found(self, profile_over_catalog):
        assert profile_over_catalog.find_in_import_tree("nope-999") is None

    def test_owning_href(self, profile_over_catalog):
        r = profile_over_catalog.find_in_import_tree("ac-1", kinds=["control"])
        assert r["href"].endswith("cat.json")


class TestReachableIds:

    def test_collects_across_tree(self, profile_over_catalog):
        ids = profile_over_catalog.reachable_ids()
        assert {"ac-1", "ac-1_prm_1", "ac-1_smt",
                "bbbbbbbb-2222-4222-8222-222222222222"} <= ids


class TestGetResourceByUuid:
    _RES = "bbbbbbbb-2222-4222-8222-222222222222"

    def test_local_hit(self, tmp_path):
        cat = Catalog.load(_catalog_file(tmp_path))
        res = cat.get_resource_by_uuid(self._RES)
        assert res is not None and res["title"] == "Cited"

    def test_cascades_into_imported_document(self, profile_over_catalog):
        # The resource lives in the imported catalog, not the profile's own back-matter.
        res = profile_over_catalog.get_resource_by_uuid(self._RES)
        assert res is not None and res["uuid"] == self._RES

    def test_not_found_returns_none(self, profile_over_catalog):
        assert profile_over_catalog.get_resource_by_uuid("cccccccc-3333-4333-8333-333333333333") is None

    def test_returns_safe_copy(self, tmp_path):
        cat = Catalog.load(_catalog_file(tmp_path))
        res = cat.get_resource_by_uuid(self._RES)
        res["title"] = "MUTATED"
        assert cat.get_resource_by_uuid(self._RES)["title"] == "Cited"

    def test_with_source_returns_locator(self, profile_over_catalog):
        loc = profile_over_catalog.get_resource_by_uuid(self._RES, with_source=True)
        assert loc["element"]["uuid"] == self._RES
        assert loc["kind"] == "resource"
        # owning document is the imported catalog, reached via cascade
        assert loc["object_uuid"] == "11111111-1111-4111-8111-111111111111"
        assert loc["href"].endswith("cat.json")

    def test_local_only_does_not_cascade(self, tmp_path, profile_over_catalog):
        # The resource lives in the imported catalog, not the profile itself.
        assert profile_over_catalog.get_resource_by_uuid(self._RES, local_only=True) is None
        # But the catalog itself finds its own resource under local_only.
        cat = Catalog.load(_catalog_file(tmp_path))
        assert cat.get_resource_by_uuid(self._RES, local_only=True)["title"] == "Cited"


# ===========================================================================
# Metadata cross-reference getters (role / party / location / responsible-party)
# ===========================================================================
_ROLE   = "sysowner"
_PARTY  = "aaaaaaaa-1111-4111-8111-111111111111"
_LOC    = "dddddddd-4444-4444-8444-444444444444"


class TestMetadataScopedGetters:
    """All resolve locally on the catalog and via cascade from the importing profile."""

    def test_role_local_and_cascade(self, tmp_path, profile_over_catalog):
        cat = Catalog.load(_catalog_file(tmp_path))
        assert cat.get_role_by_id(_ROLE)["title"] == "System Owner"
        assert profile_over_catalog.get_role_by_id(_ROLE)["id"] == _ROLE   # cascade

    def test_party_local_and_cascade(self, tmp_path, profile_over_catalog):
        cat = Catalog.load(_catalog_file(tmp_path))
        assert cat.get_party_by_uuid(_PARTY)["name"] == "Acme"
        assert profile_over_catalog.get_party_by_uuid(_PARTY)["uuid"] == _PARTY   # cascade

    def test_location_local_and_cascade(self, tmp_path, profile_over_catalog):
        cat = Catalog.load(_catalog_file(tmp_path))
        assert cat.get_location_by_uuid(_LOC)["title"] == "HQ"
        assert profile_over_catalog.get_location_by_uuid(_LOC)["uuid"] == _LOC   # cascade

    def test_responsible_party_by_role_id(self, tmp_path, profile_over_catalog):
        cat = Catalog.load(_catalog_file(tmp_path))
        rp = cat.get_responsible_party_by_id(_ROLE)
        assert rp is not None and rp["role-id"] == _ROLE and _PARTY in rp["party-uuids"]
        assert profile_over_catalog.get_responsible_party_by_id(_ROLE)["role-id"] == _ROLE  # cascade

    def test_not_found_returns_none(self, profile_over_catalog):
        assert profile_over_catalog.get_role_by_id("nope") is None
        assert profile_over_catalog.get_party_by_uuid("00000000-0000-4000-8000-000000000000") is None
        assert profile_over_catalog.get_location_by_uuid("00000000-0000-4000-8000-000000000000") is None
        assert profile_over_catalog.get_responsible_party_by_id("nope") is None

    def test_kind_isolation(self, profile_over_catalog):
        # a role id must not resolve as a party/location, and vice versa
        assert profile_over_catalog.get_party_by_uuid(_ROLE) is None
        assert profile_over_catalog.get_location_by_uuid(_PARTY) is None

    def test_with_source_locator(self, profile_over_catalog):
        loc = profile_over_catalog.get_role_by_id(_ROLE, with_source=True)
        assert loc["kind"] == "role"
        assert loc["object_uuid"] == "11111111-1111-4111-8111-111111111111"
        assert loc["href"].endswith("cat.json")

    def test_returns_safe_copy(self, tmp_path):
        cat = Catalog.load(_catalog_file(tmp_path))
        cat.get_role_by_id(_ROLE)["title"] = "MUTATED"
        assert cat.get_role_by_id(_ROLE)["title"] == "System Owner"

    def test_local_only_does_not_cascade(self, tmp_path, profile_over_catalog):
        # These metadata items live in the imported catalog, not the profile.
        assert profile_over_catalog.get_role_by_id(_ROLE, local_only=True) is None
        assert profile_over_catalog.get_party_by_uuid(_PARTY, local_only=True) is None
        assert profile_over_catalog.get_location_by_uuid(_LOC, local_only=True) is None
        assert profile_over_catalog.get_responsible_party_by_id(_ROLE, local_only=True) is None
        # The catalog itself still resolves its own metadata under local_only.
        cat = Catalog.load(_catalog_file(tmp_path))
        assert cat.get_role_by_id(_ROLE, local_only=True)["id"] == _ROLE
        assert cat.get_party_by_uuid(_PARTY, local_only=True)["uuid"] == _PARTY
        assert cat.get_location_by_uuid(_LOC, local_only=True)["uuid"] == _LOC
        assert cat.get_responsible_party_by_id(_ROLE, local_only=True)["role-id"] == _ROLE

    def test_local_only_with_source_points_at_self(self, tmp_path):
        cat = Catalog.load(_catalog_file(tmp_path))
        loc = cat.get_role_by_id(_ROLE, with_source=True, local_only=True)
        assert loc["kind"] == "role" and loc["object_uuid"] == "11111111-1111-4111-8111-111111111111"


# ===========================================================================
# find_in_import_tree — FedRAMP (real chain: baseline -> tailoring profile -> 800-53)
# ===========================================================================
@pytest.fixture(scope="module")
def low():
    return OSCAL.load(os.path.join(_JSON, "FedRAMP_rev5_LOW-baseline_profile.json"))


@pytest.fixture(scope="module")
def resolved_low():
    prof = OSCAL.load(os.path.join(_JSON, "FedRAMP_rev5_LOW-baseline_profile.json"))
    prof.resolve()
    return prof


class TestFindInImportTreeFedramp:

    def test_resolves_resource_in_800_53(self, low):
        r = low.find_in_import_tree("27847491-5ce1-4f6a-a1e4-9e483782f0ef", kinds=["resource"])
        assert r is not None and r["kind"] == "resource"

    def test_resolves_control_in_800_53(self, low):
        # pm-9 is not in the LOW baseline but resolves down the import tree
        r = low.find_in_import_tree("pm-9", kinds=["control"])
        assert r is not None and r["href"].endswith(".xml")


# ===========================================================================
# Out-of-scope cross-reference rewriting
# ===========================================================================
class TestOutOfScopeRewrite:

    def test_out_of_scope_related_link_rewritten(self, resolved_low):
        ac1 = resolved_low.get_control_by_id("ac-1", depth=0)
        related = {ln["href"] for ln in ac1.get("links", []) if ln.get("rel") == "related"}
        # pm-9 is not in LOW -> rewritten to a source URI ending in #pm-9
        assert any(h.startswith("file:") and h.endswith("#pm-9") for h in related)

    def test_in_scope_related_link_kept(self, resolved_low):
        ac1 = resolved_low.get_control_by_id("ac-1", depth=0)
        related = {ln["href"] for ln in ac1.get("links", []) if ln.get("rel") == "related"}
        # ia-1 IS in the LOW baseline -> left as a bare fragment
        assert "#ia-1" in related

    def test_prose_markdown_link_rewritten(self, resolved_low):
        # au-2 prose references out-of-scope enhancements like cm-5.1
        au2 = json.dumps(resolved_low.get_control_by_id("au-2", depth=0))
        assert "](file:" in au2 and "#cm-5.1)" in au2

    def test_resource_refs_not_rewritten(self, resolved_low):
        # carried back-matter resource references stay as bare fragments
        ac1 = resolved_low.get_control_by_id("ac-1", depth=0)
        ref = {ln["href"] for ln in ac1.get("links", []) if ln.get("rel") == "reference"}
        assert any(h.startswith("#") for h in ref)
