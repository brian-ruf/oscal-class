"""
Unit tests for document-revision stamping:

    - OSCAL content gets a fresh root ``uuid`` and ``last-modified`` on ``new()`` and on
      every mutation (the root uuid identifies a document instance and must change when it
      is revised) — so the fixed placeholder uuid in the packaged model stubs never leaks.
    - An *explicit* uuid / last-modified (via set_metadata or put) wins over the auto-stamp.
"""
import time

import pytest

from oscal import Catalog, Profile

# The uuid baked into the packaged profile stub (oscal/data/profile.xml).
_STUB_PROFILE_UUID = "08beb860-3c94-49a6-bc82-5ebb73a55e33"


def _uuid(doc):
    return doc._dict[doc.model]["uuid"]


def _lm(doc):
    return doc._dict[doc.model]["metadata"].get("last-modified")


# ===========================================================================
# new()
# ===========================================================================
class TestNewStampsIdentity:

    def test_new_uuid_is_not_the_stub(self):
        assert _uuid(Profile.new("P")) != _STUB_PROFILE_UUID

    def test_two_new_documents_differ(self):
        assert _uuid(Profile.new("A")) != _uuid(Profile.new("B"))

    def test_new_sets_last_modified(self):
        assert _lm(Catalog.new("C"))

    def test_new_syncs_cached_uuid(self):
        c = Catalog.new("C")
        assert c.uuid == _uuid(c)


# ===========================================================================
# mutation stamps a new revision
# ===========================================================================
class TestMutationStampsIdentity:

    def test_uuid_changes_on_mutation(self):
        c = Catalog.new("C")
        before = _uuid(c)
        c.set_metadata({"title": "Changed"})
        assert _uuid(c) != before

    def test_last_modified_changes_across_a_second(self):
        c = Catalog.new("C")
        before = _lm(c)
        time.sleep(1.1)
        c.set_metadata({"title": "Changed"})
        assert _lm(c) != before

    def test_put_stamps_uuid(self):
        c = Catalog.new("C")
        before = _uuid(c)
        c.put("metadata/version", "9")
        assert _uuid(c) != before

    def test_profile_mutation_stamps(self):
        # Profile overrides _on_content_mutated; it must still stamp (via super()).
        p = Profile.new("P")
        before = _uuid(p)
        p.add_import("cat.json", include_all=True)
        assert _uuid(p) != before

    def test_cached_uuid_stays_synced(self):
        c = Catalog.new("C")
        c.set_metadata({"title": "Changed"})
        assert c.uuid == _uuid(c)


# ===========================================================================
# explicit identity wins over the auto-stamp
# ===========================================================================
class TestExplicitIdentityWins:

    def test_set_metadata_explicit_last_modified_honored(self):
        c = Catalog.new("C")
        c.set_metadata({"last-modified": "2027-05-05T00:00:00Z", "title": "Y"})
        assert _lm(c) == "2027-05-05T00:00:00Z"
        # uuid is still freshly stamped (only what was explicitly set is preserved)
        assert _uuid(c) != _STUB_PROFILE_UUID

    def test_put_explicit_last_modified_honored(self):
        c = Catalog.new("C")
        c.put("metadata/last-modified", "2028-01-01T00:00:00Z")
        assert _lm(c) == "2028-01-01T00:00:00Z"

    def test_put_explicit_uuid_honored(self):
        c = Catalog.new("C")
        c.put("uuid", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
        assert _uuid(c) == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    def test_override_does_not_linger(self):
        c = Catalog.new("C")
        c.set_metadata({"last-modified": "2027-05-05T00:00:00Z"})
        assert c._identity_override == {}
        time.sleep(1.1)
        c.set_metadata({"title": "later"})           # no explicit last-modified now
        assert _lm(c) != "2027-05-05T00:00:00Z"      # bumped to now, not the stale explicit
