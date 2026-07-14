"""
Unit tests for the is_canonical attribute and its read-only enforcement.

Canonical/published content is always read-only (most-restrictive-wins): setting
is_canonical=True forces is_read_only True regardless of the writable flag, which
blocks every mutation path (both the @requires(is_read_only=False) gate and the
_can_mutate() gate).
"""
import pytest

from oscal import Catalog, Profile


@pytest.fixture
def cat():
    return Catalog.new("Canonical Test Catalog")


@pytest.fixture
def prof():
    return Profile.new("Canonical Test Profile")


# ===========================================================================
# Default state
# ===========================================================================
class TestDefaults:

    def test_default_not_canonical(self, cat):
        assert cat.is_canonical is False

    def test_default_editable(self, cat):
        assert cat.is_read_only is False
        assert cat.is_editable is True


# ===========================================================================
# Canonical forces read-only
# ===========================================================================
class TestCanonicalForcesReadOnly:

    def test_canonical_sets_read_only(self, cat):
        cat.is_canonical = True
        assert cat.is_read_only is True

    def test_canonical_not_editable(self, cat):
        cat.is_canonical = True
        assert cat.is_editable is False

    def test_most_restrictive_wins(self, cat):
        """Even with the writable flag explicitly False, canonical stays read-only."""
        cat.is_canonical = True
        cat.is_read_only = False   # goes to the backing flag; canonical still wins
        assert cat.is_read_only is True

    def test_clearing_canonical_restores_writable(self, cat):
        cat.is_canonical = True
        cat.is_canonical = False
        assert cat.is_read_only is False
        assert cat.is_editable is True


# ===========================================================================
# Mutations blocked when canonical
# ===========================================================================
class TestMutationsBlocked:

    def test_put_blocked(self, cat):
        cat.is_canonical = True
        assert cat.put("metadata/title", "X") is False

    def test_put_does_not_mutate(self, cat):
        before = cat._dict["catalog"]["metadata"].get("title")
        cat.is_canonical = True
        cat.put("metadata/title", "X")
        assert cat._dict["catalog"]["metadata"].get("title") == before

    def test_append_resource_blocked(self, cat):
        cat.is_canonical = True
        assert cat.append_resource(title="R") is None

    def test_set_metadata_blocked(self, cat):
        cat.is_canonical = True
        assert cat.set_metadata({"version": "9"}) is None

    def test_create_control_group_blocked(self, cat):
        """@requires(is_read_only=False) gate is honored via the property."""
        cat.is_canonical = True
        assert cat.create_control_group("[root]", "grp-1") is None

    def test_add_import_blocked(self, prof):
        prof.is_canonical = True
        result = prof.add_import("catalog.xml")
        assert result.status == "error"


# ===========================================================================
# Non-canonical read-only flag still works independently
# ===========================================================================
class TestWritableFlagIndependent:

    def test_read_only_flag_blocks_when_not_canonical(self, cat):
        cat.is_read_only = True
        assert cat.is_canonical is False
        assert cat.put("metadata/title", "X") is False

    def test_writable_when_neither_set(self, cat):
        assert cat.put("metadata/title", "OK") is True
