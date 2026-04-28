"""
Unit tests for OSCAL import resolution (resolve_imports).

Covers:
  - Documents with no imports (catalogs)
  - Direct file-path import hrefs
  - Back-matter fragment imports (#uuid → back-matter resource → rlink)
  - Fragment references with no matching back-matter resource (error path)
  - import_list entry structure
  - content_state advancement to IMPORTS_RESOLVED
"""

import os
import pytest
from oscal import OSCAL, Catalog
from oscal.oscal_content import ContentState, ImportState

_IMPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test-data", "xml", "imports",
)
_CATALOG  = os.path.join(_IMPORTS_DIR, "test_catalog.xml")
_DIRECT   = os.path.join(_IMPORTS_DIR, "test_profile_direct.xml")
_BACKMAT  = os.path.join(_IMPORTS_DIR, "test_profile_backmatter.xml")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def catalog():
    return OSCAL.load(_CATALOG)

@pytest.fixture
def profile_direct():
    return OSCAL.load(_DIRECT)

@pytest.fixture
def profile_backmatter():
    return OSCAL.load(_BACKMAT)


# ---------------------------------------------------------------------------
# Documents with no imports
# ---------------------------------------------------------------------------

class TestNoImports:
    def test_catalog_resolve_returns_empty_list(self, catalog):
        result = catalog.resolve_imports()
        assert result == []

    def test_catalog_imports_resolved_after_load(self, catalog):
        assert catalog.imports_resolved is True

    def test_catalog_content_state_is_imports_resolved(self, catalog):
        assert catalog.content_state == ContentState.IMPORTS_RESOLVED


# ---------------------------------------------------------------------------
# Direct file-path import
# ---------------------------------------------------------------------------

class TestDirectImport:
    def test_returns_one_entry(self, profile_direct):
        result = profile_direct.resolve_imports()
        assert len(result) == 1

    def test_entry_status_ready(self, profile_direct):
        result = profile_direct.resolve_imports()
        assert result[0]["status"] == ImportState.READY

    def test_entry_is_valid(self, profile_direct):
        result = profile_direct.resolve_imports()
        assert result[0]["is_valid"] is True

    def test_child_object_is_catalog(self, profile_direct):
        result = profile_direct.resolve_imports()
        child = result[0]["object"]
        assert child is not None
        assert child.model == "catalog"

    def test_imports_resolved_true(self, profile_direct):
        profile_direct.resolve_imports()
        assert profile_direct.imports_resolved is True

    def test_content_state_advances(self, profile_direct):
        profile_direct.resolve_imports()
        assert profile_direct.content_state == ContentState.IMPORTS_RESOLVED

    def test_href_original_matches_document(self, profile_direct):
        result = profile_direct.resolve_imports()
        assert result[0]["href_original"] == "test_catalog.xml"

    def test_href_valid_is_absolute_path(self, profile_direct):
        result = profile_direct.resolve_imports()
        assert os.path.isabs(result[0]["href_valid"])


# ---------------------------------------------------------------------------
# Back-matter fragment import (#uuid)
# ---------------------------------------------------------------------------

class TestBackmatterImport:
    def test_returns_one_entry(self, profile_backmatter):
        result = profile_backmatter.resolve_imports()
        assert len(result) == 1

    def test_entry_status_ready(self, profile_backmatter):
        result = profile_backmatter.resolve_imports()
        assert result[0]["status"] == ImportState.READY

    def test_entry_is_valid(self, profile_backmatter):
        result = profile_backmatter.resolve_imports()
        assert result[0]["is_valid"] is True

    def test_href_original_is_fragment(self, profile_backmatter):
        result = profile_backmatter.resolve_imports()
        assert result[0]["href_original"].startswith("#")

    def test_href_valid_is_resolved_path(self, profile_backmatter):
        """href_valid must be the rlink href, not the fragment."""
        result = profile_backmatter.resolve_imports()
        href_valid = result[0]["href_valid"]
        assert not href_valid.startswith("#")
        assert "test_catalog" in href_valid

    def test_child_object_is_catalog(self, profile_backmatter):
        result = profile_backmatter.resolve_imports()
        child = result[0]["object"]
        assert child is not None
        assert child.model == "catalog"

    def test_imports_resolved_true(self, profile_backmatter):
        profile_backmatter.resolve_imports()
        assert profile_backmatter.imports_resolved is True

    def test_content_state_advances(self, profile_backmatter):
        profile_backmatter.resolve_imports()
        assert profile_backmatter.content_state == ContentState.IMPORTS_RESOLVED


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestImportErrors:
    def test_fragment_no_matching_resource(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-000000000099">
  <metadata>
    <title>Bad Fragment Profile</title>
    <last-modified>2026-04-28T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  <import href="#no-such-uuid-exists-in-back-matter">
    <include-all/>
  </import>
  <merge>
    <combine method="keep"/>
    <as-is>true</as-is>
  </merge>
</profile>"""
        obj = OSCAL.loads(xml)
        assert obj.is_valid
        result = obj.resolve_imports()
        assert len(result) == 1
        assert result[0]["status"] == ImportState.INVALID
        assert obj.imports_resolved is False
        assert obj.content_state == ContentState.VALID

    def test_import_state_loaded_automatically(self):
        """resolve_imports runs automatically on load; import_list is populated immediately."""
        obj = OSCAL.load(_DIRECT)
        assert obj.import_list != []
        assert obj.imports_resolved is True


# ---------------------------------------------------------------------------
# Entry structure
# ---------------------------------------------------------------------------

class TestImportEntryStructure:
    _REQUIRED_KEYS = {
        "href_original", "href_valid", "status",
        "is_valid", "is_local", "is_remote", "is_cached", "object",
    }

    def test_entry_has_required_keys(self, profile_direct):
        result = profile_direct.resolve_imports()
        assert self._REQUIRED_KEYS.issubset(result[0].keys())

    def test_child_is_local(self, profile_direct):
        result = profile_direct.resolve_imports()
        assert result[0]["is_local"] is True
        assert result[0]["is_remote"] is False
