"""
Unit tests for the core in-scope collection getters and the metadata ``action`` resolver.

The plural getters (:meth:`OSCAL.resources` / ``roles`` / ``parties`` / ``locations`` /
``responsible_parties`` / ``actions`` — all backed by :meth:`OSCAL._collect_in_scope`) and
the singular :meth:`OSCAL.get_action_by_uuid` live on the base class, so every model shares
them. They walk the same import tree the singular ``get_*_by_*`` getters use.

Covered here:
    * local-only vs ``include_imports`` cascade;
    * the ``source-document`` origin annotation ({uuid, href, imported}) on every item;
    * first-wins de-duplication on the key field (uuid / id / role-id);
    * safe-copy detachment;
    * ``action`` added to the resolver (local + cascade + ``local_only``).
"""
import json
import os

import pytest

from oscal import Catalog, Profile


# --- identifiers used throughout -------------------------------------------
_CAT_UUID = "22222222-2222-4222-8222-222222222222"
_P1 = "aaaaaaaa-1111-4111-8111-111111111111"   # party (organization)
_P2 = "aaaaaaaa-1111-4111-8111-111111111112"   # party (person)
_L1 = "dddddddd-4444-4444-8444-444444444444"   # location
_R1 = "bbbbbbbb-2222-4222-8222-222222222201"   # resource
_R2 = "bbbbbbbb-2222-4222-8222-222222222202"   # resource
_A1 = "ffffffff-6666-4666-8666-666666666661"   # action
_A2 = "ffffffff-6666-4666-8666-666666666662"   # action


def _catalog_file(tmp_path):
    """A catalog carrying every collection kind. Its ``roles`` deliberately repeat the id
    ``owner`` to exercise first-wins de-duplication."""
    doc = {"catalog": {
        "uuid": _CAT_UUID,
        "metadata": {"title": "Rich", "last-modified": "2026-01-01T00:00:00Z",
                     "version": "1", "oscal-version": "1.1.3",
                     "roles": [{"id": "owner", "title": "Owner"},
                               {"id": "owner", "title": "Owner DUP"}],
                     "parties": [{"uuid": _P1, "type": "organization", "name": "Acme"},
                                 {"uuid": _P2, "type": "person", "name": "Pat"}],
                     "locations": [{"uuid": _L1, "title": "HQ"}],
                     "responsible-parties": [{"role-id": "owner", "party-uuids": [_P1]}],
                     "actions": [
                         {"uuid": _A1, "date": "2026-01-01T00:00:00Z", "type": "approval",
                          "system": "http://csrc.nist.gov/ns/oscal"},
                         {"uuid": _A2, "type": "request",
                          "system": "http://csrc.nist.gov/ns/oscal"}]},
        "groups": [{"id": "ac", "title": "AC", "controls": [
            {"id": "ac-1", "title": "Policy",
             "parts": [{"id": "ac-1_smt", "name": "statement", "prose": "Do it."}]}]}],
        "back-matter": {"resources": [{"uuid": _R1, "title": "One"},
                                      {"uuid": _R2, "title": "Two"}]},
    }}
    path = os.path.join(str(tmp_path), "cat.json")
    with open(path, "w") as fh:
        json.dump(doc, fh)
    return path


@pytest.fixture
def cat(tmp_path):
    return Catalog.load(_catalog_file(tmp_path))


@pytest.fixture
def profile_over_catalog(tmp_path):
    p = Profile.new("P")
    p.add_import(_catalog_file(tmp_path), include_all=True)
    p.set_merge(as_is=True)
    return p


# ===========================================================================
# Local collection (this document only)
# ===========================================================================
class TestLocalCollections:

    def test_resources(self, cat):
        assert {r["uuid"] for r in cat.resources()} == {_R1, _R2}

    def test_parties(self, cat):
        assert {p["uuid"] for p in cat.parties()} == {_P1, _P2}

    def test_locations(self, cat):
        assert [loc["uuid"] for loc in cat.locations()] == [_L1]

    def test_responsible_parties(self, cat):
        rps = cat.responsible_parties()
        assert [rp["role-id"] for rp in rps] == ["owner"]

    def test_actions(self, cat):
        assert {a["uuid"] for a in cat.actions()} == {_A1, _A2}

    def test_roles_deduplicated_first_wins(self, cat):
        # Two roles share id "owner"; de-dup keeps the first (title "Owner").
        roles = cat.roles()
        assert [r["id"] for r in roles] == ["owner"]
        assert roles[0]["title"] == "Owner"


# ===========================================================================
# Origin annotation
# ===========================================================================
class TestSourceAnnotation:

    def test_local_items_marked_not_imported(self, cat):
        for res in cat.resources():
            assert res["source-document"] == {"uuid": _CAT_UUID,
                                              "href": cat.href or cat.href_original or "",
                                              "imported": False}

    def test_annotation_present_on_every_kind(self, cat):
        for getter in (cat.resources, cat.roles, cat.parties, cat.locations,
                       cat.responsible_parties, cat.actions):
            for item in getter():
                assert set(item["source-document"]) == {"uuid", "href", "imported"}

    def test_imported_items_marked_imported(self, profile_over_catalog):
        parties = profile_over_catalog.parties(include_imports=True)
        assert parties and all(p["source-document"]["imported"] for p in parties)
        assert all(p["source-document"]["uuid"] == _CAT_UUID for p in parties)


# ===========================================================================
# include_imports cascade
# ===========================================================================
class TestCascade:

    def test_excluded_by_default(self, profile_over_catalog):
        # The profile has no metadata parties/actions of its own.
        assert profile_over_catalog.parties() == []
        assert profile_over_catalog.actions() == []

    def test_included_on_request(self, profile_over_catalog):
        assert {p["uuid"] for p in profile_over_catalog.parties(include_imports=True)} == {_P1, _P2}
        assert {a["uuid"] for a in profile_over_catalog.actions(include_imports=True)} == {_A1, _A2}

    def test_resources_combine_local_and_imported(self, profile_over_catalog):
        # add_import creates one back-matter resource in the profile itself; the catalog
        # contributes two more under cascade.
        local = profile_over_catalog.resources()
        assert len(local) == 1 and local[0]["source-document"]["imported"] is False
        combined = profile_over_catalog.resources(include_imports=True)
        assert len(combined) == 3
        assert {_R1, _R2} <= {r["uuid"] for r in combined}

    def test_roles_cascade(self, profile_over_catalog):
        assert [r["id"] for r in profile_over_catalog.roles(include_imports=True)] == ["owner"]


# ===========================================================================
# Safe-copy detachment
# ===========================================================================
class TestSafeCopy:

    def test_mutation_does_not_leak(self, cat):
        cat.parties()[0]["name"] = "MUTATED"
        assert {p["name"] for p in cat.parties()} == {"Acme", "Pat"}

    def test_annotation_is_not_written_back(self, cat):
        cat.resources()            # adds source-document on the copy only
        stored = cat._dict["catalog"]["back-matter"]["resources"][0]
        assert "source-document" not in stored


# ===========================================================================
# get_action_by_uuid (singular resolver, new kind)
# ===========================================================================
class TestGetActionByUuid:

    def test_local_hit(self, cat):
        a = cat.get_action_by_uuid(_A1)
        assert a is not None and a["type"] == "approval"

    def test_not_found_returns_none(self, cat):
        assert cat.get_action_by_uuid("00000000-0000-4000-8000-000000000000") is None

    def test_cascades_into_import(self, profile_over_catalog):
        assert profile_over_catalog.get_action_by_uuid(_A1) is not None

    def test_local_only_does_not_cascade(self, cat, profile_over_catalog):
        assert profile_over_catalog.get_action_by_uuid(_A1, local_only=True) is None
        assert cat.get_action_by_uuid(_A1, local_only=True)["uuid"] == _A1

    def test_with_source_locator(self, profile_over_catalog):
        loc = profile_over_catalog.get_action_by_uuid(_A1, with_source=True)
        assert loc["kind"] == "action" and loc["object_uuid"] == _CAT_UUID

    def test_kind_isolation(self, cat):
        # an action uuid must not resolve as a party, and vice versa
        assert cat.get_party_by_uuid(_A1) is None
        assert cat.get_action_by_uuid(_P1) is None

    def test_returns_safe_copy(self, cat):
        cat.get_action_by_uuid(_A1)["type"] = "MUTATED"
        assert cat.get_action_by_uuid(_A1)["type"] == "approval"


# ===========================================================================
# find_in_import_tree exposes the action kind
# ===========================================================================
class TestFindActionInImportTree:

    def test_action_kind(self, profile_over_catalog):
        r = profile_over_catalog.find_in_import_tree(_A1, kinds=["action"])
        assert r is not None and r["kind"] == "action"

    def test_kinds_filter_excludes_action(self, cat):
        assert cat.find_in_import_tree(_A1, kinds=["resource"]) is None
