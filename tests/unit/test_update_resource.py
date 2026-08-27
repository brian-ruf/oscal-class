"""
Unit tests for OSCAL.update_resource().

update_resource patches an existing local back-matter resource selected by UUID:
    * None            -> field left unchanged
    * scalar ""       -> field removed; other scalar -> replaced
    * list []         -> field removed; other list  -> REPLACES the existing list wholesale
Covers invalid inputs, the destructive array-replace semantics, field clearing,
guards, the safe-copy return, and JSON round-trip fidelity.
"""
import pytest

from oscal import Profile


@pytest.fixture
def prof_with_resource():
    """A profile with one import-backed resource carrying two rlinks and two props."""
    p = Profile.new("Update Resource Test")
    r = p.add_import(
        "catalog.xml",
        title="Original",
        description="Original description",
        version="1.0.0",                      # -> prop name=version
        props=[{"name": "source", "value": "nist"}],
        remarks="original remarks",
    )
    uuid = r.resource["uuid"]
    # Add a second rlink so partial-replacement data loss is observable.
    p.update_resource(uuid, rlinks=[
        {"href": "catalog.xml", "media-type": "application/xml"},
        {"href": "catalog.json", "media-type": "application/json"},
    ])
    return p, uuid


def _live(p, uuid):
    return next(r for r in p._dict["profile"]["back-matter"]["resources"]
                if r["uuid"] == uuid)


# ===========================================================================
# None = leave unchanged
# ===========================================================================
class TestUnchanged:

    def test_omitted_fields_untouched(self, prof_with_resource):
        p, uuid = prof_with_resource
        before = _live(p, uuid).copy()
        p.update_resource(uuid, title="Renamed")
        after = _live(p, uuid)
        assert after["title"] == "Renamed"
        assert after["description"] == before["description"]
        assert after["rlinks"] == before["rlinks"]
        assert after["props"] == before["props"]
        assert after["remarks"] == before["remarks"]

    def test_all_none_is_noop_on_content(self, prof_with_resource):
        p, uuid = prof_with_resource
        before = _live(p, uuid).copy()
        p.update_resource(uuid)
        assert _live(p, uuid) == before


# ===========================================================================
# Scalar replace / clear
# ===========================================================================
class TestScalars:

    def test_title_replaced(self, prof_with_resource):
        p, uuid = prof_with_resource
        p.update_resource(uuid, title="New")
        assert _live(p, uuid)["title"] == "New"

    def test_empty_string_removes_field(self, prof_with_resource):
        p, uuid = prof_with_resource
        p.update_resource(uuid, description="")
        assert "description" not in _live(p, uuid)

    def test_remarks_replaced(self, prof_with_resource):
        p, uuid = prof_with_resource
        p.update_resource(uuid, remarks="updated")
        assert _live(p, uuid)["remarks"] == "updated"


# ===========================================================================
# Array replace (destructive, wholesale)
# ===========================================================================
class TestArrayReplace:

    def test_rlinks_replaced_wholesale(self, prof_with_resource):
        p, uuid = prof_with_resource
        assert len(_live(p, uuid)["rlinks"]) == 2
        p.update_resource(uuid, rlinks=[{"href": "only.yaml", "media-type": "application/yaml"}])
        rlinks = _live(p, uuid)["rlinks"]
        assert len(rlinks) == 1
        assert rlinks[0]["href"] == "only.yaml"

    def test_rlinks_replacement_drops_unlisted_entries(self, prof_with_resource):
        """The documented data-loss hazard: the second rlink is gone."""
        p, uuid = prof_with_resource
        p.update_resource(uuid, rlinks=[{"href": "catalog.xml", "media-type": "application/xml"}])
        hrefs = [rl["href"] for rl in _live(p, uuid)["rlinks"]]
        assert "catalog.json" not in hrefs

    def test_rlink_keys_filtered(self, prof_with_resource):
        p, uuid = prof_with_resource
        p.update_resource(uuid, rlinks=[{"href": "x.xml", "media-type": "application/xml", "bogus": 1}])
        assert "bogus" not in _live(p, uuid)["rlinks"][0]

    def test_props_replaced_wholesale(self, prof_with_resource):
        p, uuid = prof_with_resource
        p.update_resource(uuid, props=[{"name": "keyword", "value": "baseline"}])
        props = _live(p, uuid)["props"]
        assert len(props) == 1
        assert props[0]["name"] == "keyword"

    def test_empty_list_clears_array(self, prof_with_resource):
        p, uuid = prof_with_resource
        p.update_resource(uuid, props=[])
        assert "props" not in _live(p, uuid)


# ===========================================================================
# Invalid inputs & guards
# ===========================================================================
class TestGuards:

    def test_unknown_uuid_returns_none(self, prof_with_resource):
        p, _ = prof_with_resource
        assert p.update_resource("00000000-0000-4000-8000-000000000000", title="x") is None

    def test_unknown_uuid_does_not_mutate(self, prof_with_resource):
        p, uuid = prof_with_resource
        before = _live(p, uuid).copy()
        p.update_resource("00000000-0000-4000-8000-000000000000", title="x")
        assert _live(p, uuid) == before

    def test_empty_uuid_returns_none(self, prof_with_resource):
        p, _ = prof_with_resource
        assert p.update_resource("", title="x") is None

    def test_read_only_returns_none(self, prof_with_resource):
        p, uuid = prof_with_resource
        p.is_read_only = True
        assert p.update_resource(uuid, title="x") is None

    def test_read_only_does_not_mutate(self, prof_with_resource):
        p, uuid = prof_with_resource
        before = _live(p, uuid).copy()
        p.is_read_only = True
        p.update_resource(uuid, title="x")
        assert _live(p, uuid) == before


# ===========================================================================
# Return contract & round-trip
# ===========================================================================
class TestReturnAndRoundTrip:

    def test_returns_safe_copy(self, prof_with_resource):
        p, uuid = prof_with_resource
        ret = p.update_resource(uuid, title="Copy Check")
        assert ret is not _live(p, uuid)
        assert ret == _live(p, uuid)

    def test_marks_unsaved(self, prof_with_resource):
        p, uuid = prof_with_resource
        p.is_unsaved = False
        p.update_resource(uuid, title="Dirty")
        assert p.is_unsaved is True

    def test_noop_when_nothing_updated_still_returns_copy(self, prof_with_resource):
        p, uuid = prof_with_resource
        ret = p.update_resource(uuid)
        assert ret["uuid"] == uuid

    def test_round_trip_json(self, prof_with_resource):
        p, uuid = prof_with_resource
        p.update_resource(uuid, title="Round Trip Title",
                          props=[{"name": "keyword", "value": "roundtrip"}])
        out = p.dumps(format="json")
        assert "Round Trip Title" in out
        assert "roundtrip" in out
