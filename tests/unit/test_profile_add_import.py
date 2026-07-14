"""
Unit tests for Profile.add_import() and its ImportResult return type.

Covers:
    - ImportResult contract (status / entry / resource / .ok / .is_duplicate)
    - placeholder replacement (first add) vs append (subsequent adds)
    - back-matter resource creation, rlink href, best-effort media-type
    - optional title / description / remarks; include_all
    - duplicate detection within this profile's own imports -> blocked as "duplicate",
      returns the conflicting existing entry, adds nothing
    - href required (empty -> error; missing -> TypeError)
    - read-only guard -> error, no mutation
    - dirty-state + JSON round-trip
    - _infer_media_type helper
"""
import pytest

from oscal import Profile
from oscal.oscal_controls import _infer_media_type, ImportResult


# ===========================================================================
# Fixtures / helpers
# ===========================================================================
@pytest.fixture
def prof():
    """Fresh writable profile for each test."""
    return Profile.new("Add Import Test Profile")


def _root(p):
    return p._dict["profile"]


def _resources(p):
    return _root(p).get("back-matter", {}).get("resources", [])


def _imports(p):
    return _root(p).get("imports", [])


def _find_resource(p, uuid):
    return next((r for r in _resources(p) if r.get("uuid") == uuid), None)


# ===========================================================================
# ImportResult contract
# ===========================================================================
class TestReturnContract:

    def test_returns_import_result(self, prof):
        r = prof.add_import("catalog.xml")
        assert isinstance(r, ImportResult)

    def test_ok_true_when_added(self, prof):
        r = prof.add_import("catalog.xml")
        assert r.ok is True
        assert r.status in ("added", "replaced")

    def test_entry_is_fragment_ref(self, prof):
        r = prof.add_import("catalog.xml")
        assert r.entry["href"].startswith("#")

    def test_resource_returned_and_stored(self, prof):
        r = prof.add_import("catalog.xml")
        assert r.resource is not None
        uuid = r.entry["href"].lstrip("#")
        assert r.resource["uuid"] == uuid
        assert _find_resource(prof, uuid) is r.resource


# ===========================================================================
# Placeholder replacement vs append
# ===========================================================================
class TestPlaceholder:

    def test_first_add_replaces_template_placeholder(self, prof):
        """Fresh profile ships an empty '#' import; the first add replaces it."""
        assert any(imp.get("href") == "#" for imp in _imports(prof))
        r = prof.add_import("catalog.xml")
        assert r.status == "replaced"

    def test_first_add_does_not_grow_imports(self, prof):
        before = len(_imports(prof))
        prof.add_import("catalog.xml")
        assert len(_imports(prof)) == before  # placeholder reused

    def test_no_empty_placeholder_remains_after_first_add(self, prof):
        prof.add_import("catalog.xml")
        assert all(str(imp.get("href", "")).strip() not in ("", "#") for imp in _imports(prof))

    def test_second_add_appends(self, prof):
        prof.add_import("catalog.xml")
        r = prof.add_import("profile.json")
        assert r.status == "added"
        assert len(_imports(prof)) == 2


# ===========================================================================
# Media-type inference
# ===========================================================================
class TestMediaType:

    @pytest.mark.parametrize("href,expected", [
        ("catalog.xml", "application/xml"),
        ("catalog.json", "application/json"),
        ("catalog.yaml", "application/yaml"),
        ("catalog.yml", "application/yaml"),
        ("path/to/profile.json", "application/json"),
    ])
    def test_media_type_inferred(self, prof, href, expected):
        r = prof.add_import(href)
        assert r.resource["rlinks"][0]["media-type"] == expected

    def test_unknown_extension_omits_media_type(self, prof):
        r = prof.add_import("some/oscal/catalog")
        assert "media-type" not in r.resource["rlinks"][0]

    def test_rlink_href_matches(self, prof):
        r = prof.add_import("baselines/catalog.json")
        assert r.resource["rlinks"][0]["href"] == "baselines/catalog.json"

    def test_infer_media_type_helper(self):
        assert _infer_media_type("a/b/c.xml") == "application/xml"
        assert _infer_media_type("c.JSON") == "application/json"
        assert _infer_media_type("c.yml") == "application/yaml"
        assert _infer_media_type("c.txt") == ""
        assert _infer_media_type("#fragment-only") == ""


# ===========================================================================
# Optional metadata fields
# ===========================================================================
class TestOptionalFields:

    def test_title_set_when_provided(self, prof):
        r = prof.add_import("catalog.xml", title="Imported Catalog")
        assert r.resource["title"] == "Imported Catalog"

    def test_description_set_when_provided(self, prof):
        r = prof.add_import("catalog.xml", description="A source catalog")
        assert r.resource["description"] == "A source catalog"

    def test_remarks_set_when_provided(self, prof):
        r = prof.add_import("catalog.xml", remarks="see note")
        assert r.resource["remarks"] == "see note"

    def test_optional_fields_absent_by_default(self, prof):
        r = prof.add_import("catalog.xml")
        assert "title" not in r.resource
        assert "description" not in r.resource
        assert "remarks" not in r.resource


# ===========================================================================
# include_all
# ===========================================================================
class TestIncludeAll:

    def test_default_has_no_include_all(self, prof):
        r = prof.add_import("catalog.xml")
        assert "include-all" not in r.entry

    def test_include_all_true_adds_empty_object(self, prof):
        r = prof.add_import("catalog.xml", include_all=True)
        assert r.entry["include-all"] == {}


# ===========================================================================
# Duplicate detection (within this profile's own imports)
# ===========================================================================
class TestDuplicateDetection:

    def test_second_same_href_is_duplicate(self, prof):
        prof.add_import("catalog.xml")
        r = prof.add_import("catalog.xml")
        assert r.is_duplicate is True
        assert r.status == "duplicate"
        assert r.ok is False

    def test_duplicate_returns_conflicting_existing_entry(self, prof):
        first = prof.add_import("catalog.xml")
        dup = prof.add_import("catalog.xml")
        # returns the existing import statement that already targets this href
        assert dup.entry is not None
        assert dup.entry.get("href") == first.entry["href"]

    def test_duplicate_adds_no_new_resource(self, prof):
        prof.add_import("catalog.xml")
        prof.add_import("catalog.xml")
        assert len(_resources(prof)) == 1

    def test_duplicate_adds_no_new_import(self, prof):
        prof.add_import("catalog.xml")
        prof.add_import("catalog.xml")
        assert len(_imports(prof)) == 1

    def test_duplicate_detected_before_resolution(self, prof):
        """Duplicate check reads the profile's own imports, not the resolved tree,
        so it holds even without a prior resolve_imports pass."""
        prof.add_import("catalog.xml")
        prof.import_list = []          # simulate an unresolved state
        prof._import_tree = None
        r = prof.add_import("catalog.xml")
        assert r.is_duplicate is True

    def test_distinct_hrefs_not_duplicate(self, prof):
        prof.add_import("catalog.xml")
        r = prof.add_import("profile.json")
        assert r.is_duplicate is False
        assert r.ok is True


# ===========================================================================
# href validation
# ===========================================================================
class TestHrefRequired:

    def test_empty_href_returns_error(self, prof):
        r = prof.add_import("")
        assert r.status == "error"
        assert r.entry is None

    def test_empty_href_does_not_mutate(self, prof):
        imports_before = len(_imports(prof))
        prof.add_import("")
        assert len(_imports(prof)) == imports_before
        assert _resources(prof) == []

    def test_missing_href_raises_type_error(self, prof):
        with pytest.raises(TypeError):
            prof.add_import()


# ===========================================================================
# Guards
# ===========================================================================
class TestReadOnlyGuard:

    def test_read_only_returns_error(self, prof):
        prof.is_read_only = True
        r = prof.add_import("catalog.xml")
        assert r.status == "error"

    def test_read_only_does_not_mutate(self, prof):
        prof.is_read_only = True
        imports_before = len(_imports(prof))
        prof.add_import("catalog.xml")
        assert len(_imports(prof)) == imports_before
        assert _resources(prof) == []


# ===========================================================================
# ImportResult properties
# ===========================================================================
class TestImportResultProps:

    def test_ok_and_duplicate_flags(self):
        assert ImportResult("added").ok is True
        assert ImportResult("replaced").ok is True
        assert ImportResult("duplicate").ok is False
        assert ImportResult("duplicate").is_duplicate is True
        assert ImportResult("error").ok is False
        assert ImportResult("error").is_duplicate is False


# ===========================================================================
# Dirty state & round-trip
# ===========================================================================
class TestStateAndRoundTrip:

    def test_marks_unsaved(self, prof):
        prof.is_unsaved = False
        prof.add_import("catalog.xml")
        assert prof.is_unsaved is True

    def test_round_trip_json_contains_import_and_resource(self, prof):
        prof.add_import("catalog.xml", title="Imported Catalog")
        out = prof.dumps(format="json")
        assert "Imported Catalog" in out
        assert "application/xml" in out
