"""
Unit tests for OSCAL class state flags.
"""

from oscal import Catalog
from oscal.oscal_content import ContentState


class TestOscalStateFlags:
    def test_is_star_flags_present(self):
        obj = Catalog.new("State Flag Test")
        assert hasattr(obj, "is_valid")
        assert hasattr(obj, "is_local")
        assert hasattr(obj, "is_cached")
        assert hasattr(obj, "is_read_only")
        assert hasattr(obj, "is_synced")
        assert hasattr(obj, "is_unsaved")

    def test_read_only_is_settable(self):
        obj = Catalog.new("Read Only Test")
        obj.is_read_only = False
        assert obj.is_read_only is False

        obj.is_read_only = True
        assert obj.is_read_only is True

    def test_local_remote_inverse(self):
        obj = Catalog.new("Local Remote Test")

        obj.is_local = True
        assert obj.is_remote is False

        obj.is_local = False
        assert obj.is_remote is True

    def test_is_valid_reflects_content_state(self):
        obj = Catalog.new("Content State Test")
        assert obj.is_valid is True
        assert obj.content_state >= ContentState.VALID

        obj.content_state = ContentState.WELL_FORMED
        assert obj.is_valid is False

        obj.content_state = ContentState.VALID
        assert obj.is_valid is True
