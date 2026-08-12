"""
Unit tests for OSCAL dict-based query methods:
    - OSCAL.query()       — XML-element-name path syntax via OSCALPath/metaschema index
    - OSCAL.query_one()   — convenience wrapper returning the first match
    - OSCAL.json_query()  — JSON-key-name path syntax via NativePath
"""
import os

import pytest

from oscal import OSCAL, Catalog

_HERE = os.path.dirname(__file__)
_DATA = os.path.join(_HERE, "..", "test-data")
_XML_CATALOG = os.path.join(_DATA, "xml", "FedRAMP_rev5_LOW-baseline-resolved-profile_catalog.xml")
_JSON_CATALOG = os.path.join(_DATA, "json", "FedRAMP_rev5_LOW-baseline-resolved-profile_catalog.json")


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture(scope="module")
def catalog():
    """Loaded catalog with known content (XML source converted to dict)."""
    return OSCAL.load(_XML_CATALOG)


@pytest.fixture
def new_catalog():
    """Fresh empty catalog backed entirely by dict."""
    return Catalog.new("Query Test Catalog")


# ===========================================================================
# OSCAL.query()
# ===========================================================================
class TestQuery:

    def test_returns_list(self, catalog):
        """query() always returns a list."""
        result = catalog.query("//group")
        assert isinstance(result, list)

    def test_groups_found(self, catalog):
        """query() finds multiple group elements."""
        result = catalog.query("//group")
        assert len(result) > 0

    def test_title_found(self, catalog):
        """query() retrieves the catalog title via XML-element-name path."""
        result = catalog.query("/*/metadata/title")
        assert len(result) == 1
        assert isinstance(result[0], str)
        assert result[0] != ""

    def test_missing_path_returns_empty_list(self, catalog):
        """query() returns [] when nothing matches."""
        result = catalog.query("//nonexistent-element-xyz")
        assert result == []

    def test_control_by_id(self, catalog):
        """query() can filter by attribute id."""
        result = catalog.query("//control[@id='ac-1']")
        assert len(result) >= 1

    def test_no_dict_returns_empty_list(self):
        """query() returns [] when _dict is None."""
        obj = OSCAL.loads("")
        result = obj.query("/*/metadata/title")
        assert result == []


# ===========================================================================
# OSCAL.query_one()
# ===========================================================================
class TestQueryOne:

    def test_returns_single_value(self, catalog):
        """query_one() returns a single value rather than a list."""
        result = catalog.query_one("/*/metadata/title")
        assert result is not None
        assert isinstance(result, str)

    def test_returns_default_on_miss(self, catalog):
        """query_one() returns the default when nothing matches."""
        result = catalog.query_one("//nonexistent-xyz", default="fallback")
        assert result == "fallback"

    def test_default_is_none_by_default(self, catalog):
        """query_one() default default is None."""
        result = catalog.query_one("//nonexistent-xyz")
        assert result is None


# ===========================================================================
# OSCAL.json_query()
# ===========================================================================
class TestJsonQuery:

    def test_returns_list(self, catalog):
        """json_query() always returns a list."""
        result = catalog.json_query("//groups")
        assert isinstance(result, list)

    def test_title_found(self, catalog):
        """json_query() retrieves the catalog title via JSON-key path."""
        result = catalog.json_query("/*/metadata/title")
        assert len(result) == 1
        assert isinstance(result[0], str)
        assert result[0] != ""

    def test_missing_path_returns_empty_list(self, catalog):
        """json_query() returns [] when nothing matches."""
        result = catalog.json_query("//nonexistent-key-xyz")
        assert result == []

    def test_no_dict_returns_empty_list(self):
        """json_query() returns [] when _dict is None."""
        obj = OSCAL.loads("")
        result = obj.json_query("/*/metadata/title")
        assert result == []


# ===========================================================================
# Safe-copy ownership: public query methods return copies; private return live
# ===========================================================================
class TestQueryReturnsCopies:
    """Public query()/query_one()/json_query()/json_query_one() return detached copies;
    the private _query()/_json_query() expose live references into _dict for internal use."""

    def test_query_results_are_copies(self, catalog):
        groups = catalog.query("//group")
        assert groups and isinstance(groups[0], dict)
        groups[0]["title"] = "MUTATED"
        assert all(g.get("title") != "MUTATED" for g in catalog.query("//group"))

    def test_query_one_result_is_copy(self, catalog):
        catalog.query_one("//group")["title"] = "MUTATED"
        assert catalog.query_one("//group").get("title") != "MUTATED"

    def test_json_query_results_are_copies(self, catalog):
        groups = catalog.json_query("//groups")   # json_query uses JSON key names
        assert groups and isinstance(groups[0], dict)
        groups[0]["title"] = "MUTATED"
        assert all(g.get("title") != "MUTATED" for g in catalog.json_query("//groups"))

    def test_private_query_returns_live_reference(self, catalog):
        live = catalog._query("//group")
        pub = catalog.query("//group")
        assert live and pub
        assert live[0] is not pub[0]                       # public is a copy
        assert live[0] is catalog._dict[catalog.model]["groups"][0]   # private is the live node

    def test_query_one_default_returned_as_is(self, catalog):
        sentinel = object()
        assert catalog.query_one("//nonexistent-xyz", default=sentinel) is sentinel

    def test_json_query_one_default_returned_as_is(self, catalog):
        sentinel = object()
        assert catalog.json_query_one("//nonexistent-xyz", default=sentinel) is sentinel
