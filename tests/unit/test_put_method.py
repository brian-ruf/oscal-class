"""
Unit tests for OSCAL.put() — the shared, guarded JSON-mutation entry point.

Covers:
    - replace mode: scalar set, overwrite, non-string value, list-index set
    - replace mode: auto-creation of missing intermediate dict containers
    - insert mode: creates an optional array when absent, then appends
    - insert mode: appends to an existing array (order preserved)
    - insert mode: positional (index leaf) rejected
    - invalid mode, empty path, bad/out-of-range indices, non-container traversal
    - guards: read-only and _dict is None both return False without mutating
    - dirty-state bookkeeping: is_unsaved set only on success
    - validate / check_refs opt-in hooks are invoked
    - _ensure_list / _as_index helpers
"""
import pytest

from oscal import Catalog


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def cat():
    """Fresh writable catalog for each test."""
    return Catalog.new("Put Test Catalog")


def _catalog(obj):
    return obj._dict["catalog"]


# ===========================================================================
# replace mode
# ===========================================================================
class TestPutReplace:

    def test_sets_scalar_value(self, cat):
        assert cat.put("metadata/title", "New Title") is True
        assert _catalog(cat)["metadata"]["title"] == "New Title"

    def test_overwrites_existing_value(self, cat):
        cat.put("metadata/title", "First")
        cat.put("metadata/title", "Second")
        assert _catalog(cat)["metadata"]["title"] == "Second"

    def test_sets_non_string_value(self, cat):
        assert cat.put("metadata/title", 42) is True
        assert _catalog(cat)["metadata"]["title"] == 42

    def test_replace_is_default_mode(self, cat):
        """No mode argument behaves as replace."""
        cat.put("metadata/version", "1.2.3")
        assert _catalog(cat)["metadata"]["version"] == "1.2.3"

    def test_list_index_set(self, cat):
        _catalog(cat)["metadata"]["roles"] = [{"id": "admin", "title": "Admin"}]
        assert cat.put("metadata/roles/0/title", "Updated Admin") is True
        assert _catalog(cat)["metadata"]["roles"][0]["title"] == "Updated Admin"

    def test_auto_creates_missing_intermediate_dicts(self, cat):
        """Missing intermediate objects are created (unlike __set_field)."""
        assert "back-matter" not in _catalog(cat)
        result = cat.put("back-matter/custom/nested", "value")
        assert result is True
        assert _catalog(cat)["back-matter"]["custom"]["nested"] == "value"

    def test_out_of_range_list_index_returns_false(self, cat):
        _catalog(cat)["metadata"]["roles"] = []
        assert cat.put("metadata/roles/5/title", "x") is False

    def test_traverse_into_scalar_returns_false(self, cat):
        cat.put("metadata/title", "scalar")
        # title is a string; cannot descend into it
        assert cat.put("metadata/title/deeper", "x") is False


# ===========================================================================
# insert mode
# ===========================================================================
class TestPutInsert:

    def test_creates_missing_array_and_appends(self, cat):
        assert "props" not in _catalog(cat)["metadata"] or isinstance(
            _catalog(cat)["metadata"].get("props"), list
        )
        prop = {"name": "marking", "value": "cui"}
        assert cat.put("metadata/props", prop, mode="insert") is True
        assert prop in _catalog(cat)["metadata"]["props"]

    def test_appends_to_existing_array_in_order(self, cat):
        cat.put("metadata/props", {"name": "a", "value": "1"}, mode="insert")
        cat.put("metadata/props", {"name": "b", "value": "2"}, mode="insert")
        names = [p["name"] for p in _catalog(cat)["metadata"]["props"]]
        assert names[-2:] == ["a", "b"]

    def test_insert_auto_creates_intermediate_then_array(self, cat):
        assert cat.put("back-matter/resources", {"uuid": "u1"}, mode="insert") is True
        assert _catalog(cat)["back-matter"]["resources"] == [{"uuid": "u1"}]

    def test_insert_positional_index_leaf_rejected(self, cat):
        _catalog(cat)["metadata"]["props"] = []
        # index leaf implies positional insert, which is not supported
        assert cat.put("metadata/props/0", {"name": "x"}, mode="insert") is False

    def test_insert_into_non_list_key_returns_false(self, cat):
        # title is a scalar, not an array
        cat.put("metadata/title", "scalar")
        assert cat.put("metadata/title", "x", mode="insert") is False


# ===========================================================================
# Argument / path validation
# ===========================================================================
class TestPutArgErrors:

    def test_invalid_mode_returns_false(self, cat):
        assert cat.put("metadata/title", "x", mode="upsert") is False

    def test_invalid_mode_does_not_mutate(self, cat):
        before = _catalog(cat)["metadata"].get("title")
        cat.put("metadata/title", "x", mode="upsert")
        assert _catalog(cat)["metadata"].get("title") == before

    def test_empty_path_returns_false(self, cat):
        assert cat.put("", "x") is False

    def test_slash_only_path_returns_false(self, cat):
        assert cat.put("///", "x") is False


# ===========================================================================
# Guards
# ===========================================================================
class TestPutGuards:

    def test_read_only_returns_false(self, cat):
        cat.is_read_only = True
        assert cat.put("metadata/title", "x") is False

    def test_read_only_does_not_mutate(self, cat):
        before = _catalog(cat)["metadata"].get("title")
        cat.is_read_only = True
        cat.put("metadata/title", "x")
        assert _catalog(cat)["metadata"].get("title") == before

    def test_no_dict_returns_false(self, cat):
        cat._dict = None
        assert cat.put("metadata/title", "x") is False


# ===========================================================================
# Dirty-state bookkeeping
# ===========================================================================
class TestPutDirtyState:

    def test_success_sets_unsaved(self, cat):
        cat.is_unsaved = False
        cat.put("metadata/title", "x")
        assert cat.is_unsaved is True

    def test_success_updates_last_modified(self, cat):
        cat.last_modified = ""
        cat.put("metadata/title", "x")
        assert cat.last_modified != ""

    def test_failure_does_not_set_unsaved(self, cat):
        cat.is_unsaved = False
        cat.put("metadata/title", "x", mode="upsert")  # invalid mode -> failure
        assert cat.is_unsaved is False

    def test_guard_failure_does_not_set_unsaved(self, cat):
        cat.is_unsaved = False
        cat.is_read_only = True
        cat.put("metadata/title", "x")
        assert cat.is_unsaved is False


# ===========================================================================
# Validation / referential-integrity hooks (opt-in)
# ===========================================================================
class TestPutHooks:

    def test_validate_hook_invoked_when_enabled(self, cat, monkeypatch):
        calls = []
        monkeypatch.setattr(
            Catalog, "_validate_write",
            lambda self, path, value, mode: calls.append((path, mode)) or True,
        )
        cat.put("metadata/title", "x", validate=True)
        assert calls == [("metadata/title", "replace")]

    def test_validate_hook_not_invoked_by_default(self, cat, monkeypatch):
        calls = []
        monkeypatch.setattr(
            Catalog, "_validate_write",
            lambda self, path, value, mode: calls.append(path) or True,
        )
        cat.put("metadata/title", "x")
        assert calls == []

    def test_validate_failure_blocks_write(self, cat, monkeypatch):
        monkeypatch.setattr(Catalog, "_validate_write", lambda self, p, v, m: False)
        assert cat.put("metadata/title", "blocked", validate=True) is False

    def test_check_refs_hook_invoked_when_enabled(self, cat, monkeypatch):
        calls = []
        monkeypatch.setattr(
            Catalog, "_check_referential_integrity",
            lambda self, path, value, mode: calls.append(path) or True,
        )
        cat.put("metadata/title", "x", check_refs=True)
        assert calls == ["metadata/title"]

    def test_check_refs_failure_blocks_write(self, cat, monkeypatch):
        monkeypatch.setattr(Catalog, "_check_referential_integrity", lambda self, p, v, m: False)
        assert cat.put("metadata/title", "blocked", check_refs=True) is False


# ===========================================================================
# Helpers: _ensure_list / _as_index
# ===========================================================================
class TestPutHelpers:

    def test_ensure_list_creates_when_absent(self, cat):
        container = {}
        result = cat._ensure_list(container, "props")
        assert result == []
        assert container["props"] is result

    def test_ensure_list_returns_existing(self, cat):
        container = {"props": [{"name": "a"}]}
        result = cat._ensure_list(container, "props")
        assert result == [{"name": "a"}]

    def test_ensure_list_wrong_type_returns_none(self, cat):
        container = {"props": "not-a-list"}
        assert cat._ensure_list(container, "props") is None

    def test_as_index_parses_non_negative_int(self, cat):
        assert cat._as_index("3") == 3
        assert cat._as_index("0") == 0

    def test_as_index_rejects_key_and_negative(self, cat):
        assert cat._as_index("props") is None
        assert cat._as_index("-1") is None


# ===========================================================================
# Round-trip: value written by put survives serialization
# ===========================================================================
class TestPutRoundTrip:

    def test_inserted_prop_present_in_json(self, cat):
        cat.put("metadata/props", {"name": "marking", "value": "cui"}, mode="insert")
        out = cat.dumps(format="json")
        assert "marking" in out
        assert "cui" in out
