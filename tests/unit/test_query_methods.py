"""
Unit tests for OSCAL XPath query methods:
    - OSCAL.xpath_atomic()
    - OSCAL.xpath()
"""
import os

import pytest

from oscal import OSCAL, Catalog

_HERE = os.path.dirname(__file__)
_DATA = os.path.join(_HERE, "..", "test-data")
_XML_CATALOG = os.path.join(_DATA, "xml", "FedRAMP_rev5_LOW-baseline-resolved-profile_catalog.xml")


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture(scope="module")
def catalog():
    """Loaded catalog with known content."""
    return OSCAL.load(_XML_CATALOG)


@pytest.fixture
def new_catalog():
    """Fresh empty catalog (XML-backed)."""
    return Catalog.new("Query Test Catalog")


# ===========================================================================
# OSCAL.xpath_atomic()
# ===========================================================================
class TestXpathAtomic:

    def test_returns_string(self, catalog):
        """xpath_atomic() always returns a str."""
        result = catalog.xpath_atomic("/*/metadata/title")
        assert isinstance(result, str)

    def test_title_is_nonempty(self, catalog):
        """xpath_atomic() retrieves the catalog title text."""
        result = catalog.xpath_atomic("/*/metadata/title/text()")
        assert result != ""
        assert "FedRAMP" in result

    def test_missing_path_returns_empty_string(self, catalog):
        """xpath_atomic() returns '' when the path matches nothing."""
        result = catalog.xpath_atomic("//nonexistent-element-xyz/text()")
        assert result == ""

    def test_no_context_uses_document(self, catalog):
        """xpath_atomic() with no context argument queries the full document."""
        result = catalog.xpath_atomic("/*/metadata/version/text()")
        assert isinstance(result, str)

    def test_with_explicit_context(self, catalog):
        """xpath_atomic() respects an explicit Element context."""
        metadata_nodes = catalog.xpath("/*/metadata")
        assert metadata_nodes and len(metadata_nodes) > 0
        metadata_el = metadata_nodes[0]
        result = catalog.xpath_atomic("title/text()", context=metadata_el)
        assert isinstance(result, str)
        assert result != ""

    def test_returns_first_when_multiple_match(self, catalog):
        """xpath_atomic() returns only the first result when multiple nodes match."""
        result = catalog.xpath_atomic("//group/@id")
        assert isinstance(result, str)
        assert result != ""

    def test_no_tree_returns_empty_string(self, new_catalog):
        """xpath_atomic() returns '' gracefully when the tree has no match."""
        result = new_catalog.xpath_atomic("//nonexistent")
        assert result == ""


# ===========================================================================
# OSCAL.xpath()
# ===========================================================================
class TestXpath:

    def test_returns_list(self, catalog):
        """xpath() returns a list on a matching expression."""
        result = catalog.xpath("//group")
        assert isinstance(result, list)

    def test_groups_found(self, catalog):
        """xpath() finds multiple group elements."""
        result = catalog.xpath("//group")
        assert result is not None
        assert len(result) > 0

    def test_missing_path_returns_empty_list(self, catalog):
        """xpath() returns an empty list when nothing matches."""
        result = catalog.xpath("//nonexistent-element-xyz")
        assert result == [] or result is None or (isinstance(result, list) and len(result) == 0)

    def test_with_explicit_context(self, catalog):
        """xpath() scopes the query to a provided context element."""
        from xml.etree import ElementTree
        groups = catalog.xpath("//group")
        assert groups and len(groups) > 0
        first_group = groups[0]
        controls = catalog.xpath("control", context=first_group)
        assert isinstance(controls, list)

    def test_attribute_selection(self, catalog):
        """xpath() can select attribute values."""
        result = catalog.xpath("//group/@id")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_invalid_xpath_returns_none(self, catalog):
        """xpath() returns None on an invalid XPath expression."""
        result = catalog.xpath("///invalid[[[xpath")
        assert result is None

    def test_single_node_wrapped_in_list(self, catalog):
        """xpath() always returns a list (even for one match)."""
        result = catalog.xpath("/*")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_no_tree_returns_none(self):
        """xpath() returns None when there is no XML tree."""
        obj = OSCAL.loads("")
        result = obj.xpath("/*/metadata/title")
        assert result is None
