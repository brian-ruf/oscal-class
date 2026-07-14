"""
Unit tests for OSCAL recursive import tree.

Covers:
    - import_tree returns a root dict with 'imports' children
    - import_tree child node structure: mirrors import_list fields + 'imports' key
    - Lazy caching: same root dict object returned on repeated access
    - rebuild_import_tree() invalidates cache and returns a fresh root dict
  - Multi-level nesting: profile → profile → catalog
  - Failed import nodes: status=INVALID, imports=[], failure populated
  - failed_imports property: returns only entries with failure set
"""

import os
import pytest
from oscal import OSCAL
from oscal.oscal_content import ContentState, ImportState

_IMPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test-data", "xml", "imports",
)
_CATALOG = os.path.join(_IMPORTS_DIR, "test_catalog.xml")
_DIRECT  = os.path.join(_IMPORTS_DIR, "test_profile_direct.xml")


# ---------------------------------------------------------------------------
# Shared XML builders
# ---------------------------------------------------------------------------

def _catalog_xml(title: str = "Test Catalog") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-000000000010">
  <metadata>
    <title>{title}</title>
    <last-modified>2026-04-28T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  <group id="g1"><title>Group 1</title>
    <control id="ac-1"><title>AC-1</title></control>
  </group>
</catalog>"""


def _profile_xml(href: str, uuid_suffix: str = "01") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-0000000000{uuid_suffix}">
  <metadata>
    <title>Test Profile {uuid_suffix}</title>
    <last-modified>2026-04-28T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  <import href="{href}"><include-all/></import>
  <merge><combine method="keep"/><as-is>true</as-is></merge>
</profile>"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def catalog():
    """A catalog loaded from disk (no imports)."""
    return OSCAL.load(_CATALOG)


@pytest.fixture
def profile_direct():
    """A profile loaded from disk with one valid direct import."""
    doc = OSCAL.load(_DIRECT)
    doc.resolve_imports()
    return doc


@pytest.fixture
def profile_missing(tmp_path):
    """A profile whose single import target does not exist."""
    p = tmp_path / "profile_missing.xml"
    p.write_text(_profile_xml("/nonexistent/totally_missing_catalog.xml"))
    doc = OSCAL.load(str(p))
    doc.resolve_imports()
    return doc


# ---------------------------------------------------------------------------
# TestImportTreeNoImports — catalog has no imports
# ---------------------------------------------------------------------------

class TestImportTreeNoImports:
    def test_returns_root_dict(self, catalog):
        assert isinstance(catalog.import_tree, dict)

    def test_root_imports_is_empty_list(self, catalog):
        assert catalog.import_tree["imports"] == []

    def test_stable_on_repeated_access(self, catalog):
        assert catalog.import_tree is catalog.import_tree


# ---------------------------------------------------------------------------
# TestImportTreeStructure — shape of a successful one-level tree
# ---------------------------------------------------------------------------

class TestImportTreeStructure:
    def test_has_one_child_node(self, profile_direct):
        assert len(profile_direct.import_tree["imports"]) == 1

    def test_node_has_imports_key(self, profile_direct):
        assert "imports" in profile_direct.import_tree["imports"][0]

    def test_node_imports_is_list(self, profile_direct):
        assert isinstance(profile_direct.import_tree["imports"][0]["imports"], list)

    def test_node_has_href_original(self, profile_direct):
        assert "href_original" in profile_direct.import_tree["imports"][0]

    def test_node_has_status(self, profile_direct):
        assert "status" in profile_direct.import_tree["imports"][0]

    def test_node_has_object(self, profile_direct):
        assert "object" in profile_direct.import_tree["imports"][0]

    def test_node_has_failure(self, profile_direct):
        assert "failure" in profile_direct.import_tree["imports"][0]

    def test_ready_node_status(self, profile_direct):
        assert profile_direct.import_tree["imports"][0]["status"] == ImportState.READY

    def test_catalog_child_has_no_imports(self, profile_direct):
        """A catalog child has no imports of its own."""
        assert profile_direct.import_tree["imports"][0]["imports"] == []

    def test_ready_node_failure_is_none(self, profile_direct):
        assert profile_direct.import_tree["imports"][0]["failure"] is None

    def test_href_original_matches_import_list(self, profile_direct):
        tree_href = profile_direct.import_tree["imports"][0]["href_original"]
        list_href = profile_direct.import_list[0]["href_original"]
        assert tree_href == list_href


# ---------------------------------------------------------------------------
# TestImportTreeCaching — lazy build and invalidation
# ---------------------------------------------------------------------------

class TestImportTreeCaching:
    def test_same_object_on_repeated_access(self, profile_direct):
        t1 = profile_direct.import_tree
        t2 = profile_direct.import_tree
        assert t1 is t2

    def test_internal_cache_set_after_first_access(self, profile_direct):
        _ = profile_direct.import_tree
        assert profile_direct._import_tree is not None

    def test_rebuild_returns_dict(self, profile_direct):
        assert isinstance(profile_direct.rebuild_import_tree(), dict)

    def test_rebuild_returns_new_object(self, profile_direct):
        t1 = profile_direct.import_tree
        t2 = profile_direct.rebuild_import_tree()
        assert t1 is not t2

    def test_rebuild_produces_equivalent_content(self, profile_direct):
        t1 = profile_direct.import_tree
        t2 = profile_direct.rebuild_import_tree()
        assert len(t1["imports"]) == len(t2["imports"])
        assert t1["imports"][0]["href_original"] == t2["imports"][0]["href_original"]
        assert t1["imports"][0]["status"] == t2["imports"][0]["status"]

    def test_resolve_imports_invalidates_cache(self, profile_direct):
        """resolve_imports() clears _import_tree so the next access rebuilds it."""
        t1 = profile_direct.import_tree
        profile_direct.resolve_imports()       # re-resolves and clears cache
        t2 = profile_direct.import_tree
        assert t1 is not t2


# ---------------------------------------------------------------------------
# TestImportTreeRecursive — profile → profile → catalog
# ---------------------------------------------------------------------------

class TestImportTreeRecursive:
    @pytest.fixture
    def three_level(self, tmp_path):
        """
        Writes three files:
          catalog.xml          (leaf, no imports)
          profile2.xml  → catalog.xml
          profile1.xml  → profile2.xml
        Returns profile1 with imports resolved.
        """
        cat_path = tmp_path / "catalog.xml"
        p2_path  = tmp_path / "profile2.xml"
        p1_path  = tmp_path / "profile1.xml"

        cat_path.write_text(_catalog_xml("Leaf Catalog"))
        p2_path.write_text(_profile_xml("catalog.xml",  uuid_suffix="02"))
        p1_path.write_text(_profile_xml("profile2.xml", uuid_suffix="01"))

        doc = OSCAL.load(str(p1_path))
        doc.resolve_imports()
        return doc

    def test_top_level_has_one_node(self, three_level):
        assert len(three_level.import_tree["imports"]) == 1

    def test_top_level_node_is_ready(self, three_level):
        assert three_level.import_tree["imports"][0]["status"] == ImportState.READY

    def test_second_level_has_one_node(self, three_level):
        assert len(three_level.import_tree["imports"][0]["imports"]) == 1

    def test_second_level_node_is_ready(self, three_level):
        child = three_level.import_tree["imports"][0]["imports"][0]
        assert child["status"] == ImportState.READY

    def test_leaf_catalog_has_no_imports(self, three_level):
        leaf = three_level.import_tree["imports"][0]["imports"][0]
        assert leaf["imports"] == []

    def test_leaf_object_model_is_catalog(self, three_level):
        leaf = three_level.import_tree["imports"][0]["imports"][0]
        assert leaf["object"].model == "catalog"


# ---------------------------------------------------------------------------
# TestImportTreeFailedImport — failed node shape
# ---------------------------------------------------------------------------

class TestImportTreeFailedImport:
    def test_tree_has_one_child_node(self, profile_missing):
        assert len(profile_missing.import_tree["imports"]) == 1

    def test_failed_node_status_is_invalid(self, profile_missing):
        assert profile_missing.import_tree["imports"][0]["status"] == ImportState.INVALID

    def test_failed_node_imports_is_empty(self, profile_missing):
        """Cannot recurse into a document that failed to load."""
        assert profile_missing.import_tree["imports"][0]["imports"] == []

    def test_failed_node_failure_is_populated(self, profile_missing):
        assert profile_missing.import_tree["imports"][0]["failure"] is not None

    def test_failed_node_object_is_none(self, profile_missing):
        assert profile_missing.import_tree["imports"][0]["object"] is None


# ---------------------------------------------------------------------------
# TestFailedImportsProperty — failed_imports convenience list
# ---------------------------------------------------------------------------

class TestFailedImportsProperty:
    def test_empty_for_valid_imports(self, profile_direct):
        assert profile_direct.failed_imports == []

    def test_returns_one_entry_for_missing_import(self, profile_missing):
        assert len(profile_missing.failed_imports) == 1

    def test_entry_has_failure_populated(self, profile_missing):
        entry = profile_missing.failed_imports[0]
        assert entry.get("failure") is not None

    def test_entry_status_is_invalid(self, profile_missing):
        entry = profile_missing.failed_imports[0]
        assert entry["status"] == ImportState.INVALID
