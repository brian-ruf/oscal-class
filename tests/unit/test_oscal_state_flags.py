"""
Unit tests for OSCAL class state flags and compatibility aliases.
"""

from oscal import Catalog


class TestOscalStateFlags:
    def test_is_star_flags_present(self):
        obj = Catalog.new("State Flag Test")
        assert hasattr(obj, "is_valid")
        assert hasattr(obj, "is_local")
        assert hasattr(obj, "is_cached")
        assert hasattr(obj, "is_read_only")
        assert hasattr(obj, "is_synced")
        assert hasattr(obj, "is_unsaved")

    def test_read_only_alias_round_trip(self):
        obj = Catalog.new("Read Only Alias")
        obj.is_read_only = False
        assert obj.read_only is False

        obj.read_only = True
        assert obj.is_read_only is True

    def test_local_remote_inverse_aliases(self):
        obj = Catalog.new("Local Remote Alias")

        obj.is_local = True
        assert obj.is_remote is False
        assert obj.local is True

        obj.remote = True
        assert obj.is_remote is True
        assert obj.is_local is False
        assert obj.local is False

    def test_valid_alias_round_trip(self):
        obj = Catalog.new("Valid Alias")
        obj.is_valid = True
        assert obj.valid is True

        obj.valid = False
        assert obj.is_valid is False
