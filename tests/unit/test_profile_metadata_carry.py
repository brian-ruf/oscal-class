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
