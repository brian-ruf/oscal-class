"""
Metadata carry-forward during profile resolution.

Roles, parties, locations, and responsible-parties from the profile and its
imports are copied into the resolved catalog's metadata:

  * roles / parties / locations : use-first on identity (id / uuid / uuid)
  * responsible-parties         : accumulate party-uuids per role-id

The canonical case: two imports both declare a ``creator`` role-id; the resolved
catalog has one ``creator`` role and one ``creator`` responsible-party whose
party-uuids gather both sources' parties.
"""

import json
import os

import pytest

from oscal import Profile


def _catalog(uuid, *, role_title, party_uuid, party_name, location_uuid=None):
    md = {
        "title": f"Cat {uuid[0]}",
        "last-modified": "2026-01-01T00:00:00Z",
        "version": "1",
        "oscal-version": "1.1.3",
        "roles": [{"id": "creator", "title": role_title}],
        "parties": [{"uuid": party_uuid, "type": "organization", "name": party_name}],
        "responsible-parties": [{"role-id": "creator", "party-uuids": [party_uuid]}],
    }
    if location_uuid:
        md["locations"] = [{"uuid": location_uuid, "title": "Site"}]
    return {"catalog": {
        "uuid": uuid, "metadata": md,
        "groups": [{"id": "ac", "title": "AC", "controls": [{"id": "ac-1", "title": "Policy"}]}],
    }}


_PA = "aaaaaaaa-1111-4111-8111-111111111111"
_PB = "bbbbbbbb-2222-4222-8222-222222222222"
_LOC = "cccccccc-3333-4333-8333-333333333333"


def _write(tmp_path, name, doc):
    path = os.path.join(str(tmp_path), name)
    with open(path, "w") as fh:
        json.dump(doc, fh)
    return path


@pytest.fixture
def merged(tmp_path):
    a = _write(tmp_path, "a.json",
               _catalog("11111111-1111-4111-8111-111111111111",
                        role_title="Creator A", party_uuid=_PA, party_name="Org A",
                        location_uuid=_LOC))
    b = _write(tmp_path, "b.json",
               _catalog("22222222-2222-4222-8222-222222222222",
                        role_title="Creator B", party_uuid=_PB, party_name="Org B"))
    p = Profile.new("Merged")
    p.set_metadata({"title": "Merged"})
    p.add_import(a, include_all=True)
    p.add_import(b, include_all=True)
    p.set_merge(as_is=True, combine="use-first")
    p.resolve()
    return p


def _meta(prof):
    return prof.catalog._dict["catalog"]["metadata"]


class TestMetadataCarry:

    def test_resolved_catalog_valid(self, merged):
        assert merged.catalog.is_valid

    def test_roles_use_first_on_collision(self, merged):
        roles = _meta(merged).get("roles", [])
        assert [r["id"] for r in roles] == ["creator"]          # single, deduped
        assert roles[0]["title"] == "Creator A"                 # first source wins

    def test_parties_accumulate_by_uuid(self, merged):
        uuids = {p["uuid"] for p in _meta(merged).get("parties", [])}
        assert uuids == {_PA, _PB}

    def test_locations_carried(self, merged):
        locs = {loc["uuid"] for loc in _meta(merged).get("locations", [])}
        assert locs == {_LOC}

    def test_responsible_parties_accumulate_party_uuids(self, merged):
        rps = _meta(merged).get("responsible-parties", [])
        assert [rp["role-id"] for rp in rps] == ["creator"]     # single entry
        assert set(rps[0]["party-uuids"]) == {_PA, _PB}         # both parties gathered

    def test_no_duplicate_party_uuids(self, tmp_path):
        # Same party-uuid in both sources must not duplicate within party-uuids.
        a = _write(tmp_path, "a.json",
                   _catalog("11111111-1111-4111-8111-111111111111",
                            role_title="A", party_uuid=_PA, party_name="Org A"))
        b = _write(tmp_path, "b.json",
                   _catalog("22222222-2222-4222-8222-222222222222",
                            role_title="B", party_uuid=_PA, party_name="Org A"))
        p = Profile.new("M")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True, combine="use-first")
        p.resolve()
        rps = _meta(p).get("responsible-parties", [])
        assert rps[0]["party-uuids"] == [_PA]                   # not [_PA, _PA]
        assert [pp["uuid"] for pp in _meta(p).get("parties", [])] == [_PA]


# ===========================================================================
# Same UUID across sources = same content -> use first (parties/locations/resources)
# ===========================================================================
_SHARED_PARTY = "44444444-4444-4444-8444-444444444444"
_SHARED_LOC = "55555555-5555-4555-8555-555555555555"
_SHARED_RES = "66666666-6666-4666-8666-666666666666"


def _catalog_shared(uuid, tag):
    """A catalog whose party/location/resource use the SHARED uuids but tag-specific
    content, plus a control link that references the shared resource so it is carried."""
    return {"catalog": {
        "uuid": uuid,
        "metadata": {
            "title": f"Cat {tag}", "last-modified": "2026-01-01T00:00:00Z",
            "version": "1", "oscal-version": "1.1.3",
            "parties": [{"uuid": _SHARED_PARTY, "type": "organization", "name": f"Org-{tag}"}],
            "locations": [{"uuid": _SHARED_LOC, "title": f"Loc-{tag}"}],
        },
        "groups": [{"id": "ac", "title": "AC", "controls": [
            {"id": f"ac-{tag}", "title": f"Ctrl {tag}",
             "links": [{"href": f"#{_SHARED_RES}", "rel": "reference"}]}]}],
        "back-matter": {"resources": [{"uuid": _SHARED_RES, "title": f"Res-{tag}"}]},
    }}


class TestSameUuidUseFirst:
    """When two like items (party/location/resource) share a UUID, the first wins."""

    @pytest.fixture
    def resolved(self, tmp_path):
        a = _write(tmp_path, "sa.json", _catalog_shared("77777777-7777-4777-8777-777777777777", "A"))
        b = _write(tmp_path, "sb.json", _catalog_shared("88888888-8888-4888-8888-888888888888", "B"))
        p = Profile.new("Shared")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True, combine="use-first")
        p.resolve()
        return p

    def test_valid(self, resolved):
        assert resolved.catalog.is_valid

    def test_party_use_first(self, resolved):
        parties = _meta(resolved).get("parties", [])
        assert [p["uuid"] for p in parties] == [_SHARED_PARTY]   # single, deduped
        assert parties[0]["name"] == "Org-A"                     # first source wins

    def test_location_use_first(self, resolved):
        locs = _meta(resolved).get("locations", [])
        assert [loc["uuid"] for loc in locs] == [_SHARED_LOC]
        assert locs[0]["title"] == "Loc-A"

    def test_resource_use_first(self, resolved):
        res = resolved.catalog._dict["catalog"].get("back-matter", {}).get("resources", [])
        assert [r["uuid"] for r in res] == [_SHARED_RES]         # single, deduped
        assert res[0]["title"] == "Res-A"
