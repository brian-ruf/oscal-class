"""
Unit tests for Catalog and Profile content methods:
    - Catalog.create_control_group()
    - Catalog.create_control()
    - Catalog.get_control_by_id()
    - Catalog.get_group_by_id()
    - Catalog.get_control_list()
    - Profile.control()
"""
import os
from xml.etree import ElementTree

import pytest

from oscal import Catalog, Profile

_HERE = os.path.dirname(__file__)
_DATA = os.path.join(_HERE, "..", "test-data")
_XML_CATALOG = os.path.join(_DATA, "xml", "FedRAMP_rev5_LOW-baseline-resolved-profile_catalog.xml")
_XML_PROFILE = os.path.join(_DATA, "xml", "FedRAMP_rev5_LOW-baseline_profile.xml")


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def empty_cat():
    """Fresh writable catalog with no controls."""
    return Catalog.new("Test Catalog")


@pytest.fixture(scope="module")
def loaded_cat():
    """Loaded FedRAMP LOW catalog (read-only via load, but sufficient for queries)."""
    return Catalog.load(_XML_CATALOG)


@pytest.fixture
def cat_with_group():
    """Catalog that already has one group ('ac') at the root."""
    c = Catalog.new("Catalog With Group")
    c.create_control_group("[root]", "ac", title="Access Control")
    return c


# ===========================================================================
# Catalog.create_control_group()
# ===========================================================================
class TestCreateControlGroup:

    def test_returns_element(self, empty_cat):
        """create_control_group() returns an ElementTree.Element."""
        result = empty_cat.create_control_group("[root]", "ac", title="Access Control")
        assert result is not None
        assert isinstance(result, ElementTree.Element)

    def test_group_has_id_attribute(self, empty_cat):
        """create_control_group() sets the id attribute on the group element."""
        result = empty_cat.create_control_group("[root]", "si", title="System and Info")
        assert result.get("id") == "si"

    def test_group_has_title_child(self, empty_cat):
        """create_control_group() adds a <title> child when title is provided."""
        result = empty_cat.create_control_group("[root]", "ac", title="Access Control")
        title_nodes = [c for c in result if "title" in c.tag]
        assert len(title_nodes) == 1
        assert "Access Control" in title_nodes[0].text

    def test_group_without_title(self, empty_cat):
        """create_control_group() with no title still returns an element."""
        result = empty_cat.create_control_group("[root]", "cm")
        assert result is not None
        assert result.get("id") == "cm"

    def test_group_with_label(self, empty_cat):
        """create_control_group() adds a label prop when label is provided."""
        result = empty_cat.create_control_group("[root]", "pe", label="PE")
        prop_nodes = [c for c in result if "prop" in c.tag]
        label_props = [p for p in prop_nodes if p.get("name") == "label"]
        assert len(label_props) == 1
        assert label_props[0].get("value") == "PE"

    def test_nested_group(self, cat_with_group):
        """create_control_group() can create a sub-group under an existing group."""
        result = cat_with_group.create_control_group("ac", "ac.1", title="AC Sub")
        assert result is not None
        assert result.get("id") == "ac.1"

    def test_invalid_parent_returns_none(self, empty_cat):
        """create_control_group() returns None when the parent id is not found."""
        result = empty_cat.create_control_group("nonexistent-parent", "xx")
        assert result is None

    def test_marks_content_modified(self, empty_cat):
        """create_control_group() marks the catalog as modified."""
        empty_cat.create_control_group("[root]", "ra", title="Risk Assessment")
        assert empty_cat.is_unsaved is True

    def test_group_retrievable_by_id(self, empty_cat):
        """Group created by create_control_group() can be found with get_group_by_id()."""
        empty_cat.create_control_group("[root]", "ir", title="Incident Response")
        found = empty_cat.get_group_by_id("ir")
        assert found is not None

    def test_group_with_overview(self, empty_cat):
        """create_control_group() adds a <part name='overview'> when overview is provided."""
        result = empty_cat.create_control_group("[root]", "sa", overview="System and Services.")
        part_nodes = [c for c in result if "part" in c.tag]
        overview_parts = [p for p in part_nodes if p.get("name") == "overview"]
        assert len(overview_parts) == 1


# ===========================================================================
# Catalog.create_control()
# ===========================================================================
class TestCreateControl:

    def test_returns_element(self, cat_with_group):
        """create_control() returns an ElementTree.Element."""
        result = cat_with_group.create_control("ac", "ac-1", title="Access Control Policy")
        assert result is not None
        assert isinstance(result, ElementTree.Element)

    def test_control_has_id_attribute(self, cat_with_group):
        """create_control() sets the id attribute."""
        result = cat_with_group.create_control("ac", "ac-2", title="Account Management")
        assert result.get("id") == "ac-2"

    def test_control_has_title(self, cat_with_group):
        """create_control() includes a <title> child."""
        result = cat_with_group.create_control("ac", "ac-3", title="Access Enforcement")
        title_nodes = [c for c in result if "title" in c.tag]
        assert len(title_nodes) == 1
        assert "Access Enforcement" in title_nodes[0].text

    def test_title_defaults_to_id(self, cat_with_group):
        """create_control() uses the id as title when title is empty."""
        result = cat_with_group.create_control("ac", "ac-99")
        title_nodes = [c for c in result if "title" in c.tag]
        assert title_nodes[0].text == "ac-99"

    def test_control_with_label(self, cat_with_group):
        """create_control() adds a label prop when label is provided."""
        result = cat_with_group.create_control("ac", "ac-4", label="AC-4")
        prop_nodes = [c for c in result if "prop" in c.tag]
        label_props = [p for p in prop_nodes if p.get("name") == "label"]
        assert len(label_props) == 1
        assert label_props[0].get("value") == "AC-4"

    def test_control_with_overview(self, cat_with_group):
        """create_control() adds a part[@name='overview'] when overview is provided."""
        result = cat_with_group.create_control("ac", "ac-5", overview="Overview text.")
        part_nodes = [c for c in result if "part" in c.tag]
        overview_parts = [p for p in part_nodes if p.get("name") == "overview"]
        assert len(overview_parts) == 1

    def test_control_with_guidance(self, cat_with_group):
        """create_control() adds a part[@name='guidance'] when guidance is provided."""
        result = cat_with_group.create_control("ac", "ac-6", guidance="Guidance text.")
        part_nodes = [c for c in result if "part" in c.tag]
        guidance_parts = [p for p in part_nodes if p.get("name") == "guidance"]
        assert len(guidance_parts) == 1

    def test_invalid_parent_returns_none(self, cat_with_group):
        """create_control() returns None when the parent group is not found."""
        result = cat_with_group.create_control("nonexistent", "xx-1")
        assert result is None

    def test_control_retrievable_by_id(self, cat_with_group):
        """Control created by create_control() can be found with get_control_by_id()."""
        cat_with_group.create_control("ac", "ac-50", title="Findable Control")
        found = cat_with_group.get_control_by_id("ac-50")
        assert found is not None

    def test_marks_content_modified(self, cat_with_group):
        """create_control() marks the catalog as modified."""
        cat_with_group.create_control("ac", "ac-51", title="Modified")
        assert cat_with_group.is_unsaved is True


# ===========================================================================
# Catalog.get_control_by_id()
# ===========================================================================
class TestGetControlById:

    def test_returns_element_for_known_control(self, loaded_cat):
        """get_control_by_id() finds a known control from a loaded catalog."""
        result = loaded_cat.get_control_by_id("ac-1")
        assert result is not None
        assert isinstance(result, ElementTree.Element)

    def test_returned_element_has_matching_id(self, loaded_cat):
        """get_control_by_id() returns the element whose @id matches."""
        result = loaded_cat.get_control_by_id("ac-2")
        assert result is not None
        assert result.get("id") == "ac-2"

    def test_returns_none_for_unknown_id(self, loaded_cat):
        """get_control_by_id() returns None when no control matches."""
        result = loaded_cat.get_control_by_id("zz-9999")
        assert result is None

    def test_empty_catalog_returns_none(self, empty_cat):
        """get_control_by_id() returns None on a catalog with no controls."""
        result = empty_cat.get_control_by_id("ac-1")
        assert result is None


# ===========================================================================
# Catalog.get_group_by_id()
# ===========================================================================
class TestGetGroupById:

    def test_returns_element_for_known_group(self, loaded_cat):
        """get_group_by_id() finds a known group from a loaded catalog."""
        result = loaded_cat.get_group_by_id("ac")
        assert result is not None
        assert isinstance(result, ElementTree.Element)

    def test_returned_element_has_matching_id(self, loaded_cat):
        """get_group_by_id() returns the element whose @id matches."""
        result = loaded_cat.get_group_by_id("ac")
        assert result.get("id") == "ac"

    def test_returns_none_for_unknown_id(self, loaded_cat):
        """get_group_by_id() returns None when no group matches."""
        result = loaded_cat.get_group_by_id("zz-nonexistent")
        assert result is None

    def test_empty_catalog_returns_none(self, empty_cat):
        """get_group_by_id() returns None on a catalog with no groups."""
        result = empty_cat.get_group_by_id("ac")
        assert result is None


# ===========================================================================
# Catalog.get_control_list()
# ===========================================================================
class TestGetControlList:

    def test_returns_list(self, loaded_cat):
        """get_control_list() returns a list."""
        result = loaded_cat.get_control_list()
        assert isinstance(result, list)

    def test_nonempty_on_loaded_catalog(self, loaded_cat):
        """get_control_list() returns at least one control for a real catalog."""
        result = loaded_cat.get_control_list()
        assert len(result) > 0

    def test_each_item_is_element(self, loaded_cat):
        """Each item returned by get_control_list() is an ElementTree.Element."""
        controls = loaded_cat.get_control_list()
        for c in controls[:5]:  # sample first 5
            assert isinstance(c, ElementTree.Element)

    def test_empty_catalog_returns_empty_list(self, empty_cat):
        """get_control_list() returns [] when there are no controls."""
        result = empty_cat.get_control_list()
        assert result == []

    def test_count_increases_after_create(self, cat_with_group):
        """get_control_list() count increases after create_control()."""
        before = len(cat_with_group.get_control_list())
        cat_with_group.create_control("ac", "ac-100", title="New Control")
        after = len(cat_with_group.get_control_list())
        assert after == before + 1


# ===========================================================================
# Profile.control()
# ===========================================================================
class TestProfileControl:

    def test_unresolved_profile_returns_none(self):
        """Profile.control() returns None when the profile is not yet resolved."""
        profile = Profile.load(_XML_PROFILE)
        result = profile.control("ac-1")
        assert result is None

    def test_unresolved_profile_does_not_raise(self):
        """Profile.control() must not raise when called before resolution."""
        profile = Profile.load(_XML_PROFILE)
        try:
            profile.control("ac-1")
        except Exception:
            pytest.fail("Profile.control() raised unexpectedly on unresolved profile")
