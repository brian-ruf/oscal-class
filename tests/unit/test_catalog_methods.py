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
import tempfile

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

    def test_returns_dict(self, empty_cat):
        """create_control_group() returns a dict."""
        result = empty_cat.create_control_group("[root]", "ac", title="Access Control")
        assert result is not None
        assert isinstance(result, dict)

    def test_group_has_id(self, empty_cat):
        """create_control_group() sets the id key on the group dict."""
        result = empty_cat.create_control_group("[root]", "si", title="System and Info")
        assert result.get("id") == "si"

    def test_group_has_title(self, empty_cat):
        """create_control_group() stores title when provided."""
        result = empty_cat.create_control_group("[root]", "ac", title="Access Control")
        assert result.get("title") == "Access Control"

    def test_group_without_title(self, empty_cat):
        """create_control_group() with no title still returns a dict."""
        result = empty_cat.create_control_group("[root]", "cm")
        assert result is not None
        assert result.get("id") == "cm"

    def test_group_with_label(self, empty_cat):
        """create_control_group() adds a label prop when label is provided."""
        result = empty_cat.create_control_group("[root]", "pe", label="PE")
        props = result.get("props", [])
        label_props = [p for p in props if p.get("name") == "label"]
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
        """create_control_group() adds a part with name='overview' when overview is provided."""
        result = empty_cat.create_control_group("[root]", "sa", overview="System and Services.")
        parts = result.get("parts", [])
        overview_parts = [p for p in parts if p.get("name") == "overview"]
        assert len(overview_parts) == 1


# ===========================================================================
# Catalog.create_control()
# ===========================================================================
class TestCreateControl:

    def test_returns_dict(self, cat_with_group):
        """create_control() returns a dict."""
        result = cat_with_group.create_control("ac", "ac-1", title="Access Control Policy")
        assert result is not None
        assert isinstance(result, dict)

    def test_control_has_id(self, cat_with_group):
        """create_control() sets the id key."""
        result = cat_with_group.create_control("ac", "ac-2", title="Account Management")
        assert result.get("id") == "ac-2"

    def test_control_has_title(self, cat_with_group):
        """create_control() stores the title."""
        result = cat_with_group.create_control("ac", "ac-3", title="Access Enforcement")
        assert "Access Enforcement" in result.get("title", "")

    def test_title_defaults_to_id(self, cat_with_group):
        """create_control() uses the id as title when title is empty."""
        result = cat_with_group.create_control("ac", "ac-99")
        assert result.get("title") == "ac-99"

    def test_control_with_label(self, cat_with_group):
        """create_control() adds a label prop when label is provided."""
        result = cat_with_group.create_control("ac", "ac-4", label="AC-4")
        props = result.get("props", [])
        label_props = [p for p in props if p.get("name") == "label"]
        assert len(label_props) == 1
        assert label_props[0].get("value") == "AC-4"

    def test_control_with_overview(self, cat_with_group):
        """create_control() adds a part with name='overview' when overview is provided."""
        result = cat_with_group.create_control("ac", "ac-5", overview="Overview text.")
        parts = result.get("parts", [])
        overview_parts = [p for p in parts if p.get("name") == "overview"]
        assert len(overview_parts) == 1

    def test_control_with_guidance(self, cat_with_group):
        """create_control() adds a part with name='guidance' when guidance is provided."""
        result = cat_with_group.create_control("ac", "ac-6", guidance="Guidance text.")
        parts = result.get("parts", [])
        guidance_parts = [p for p in parts if p.get("name") == "guidance"]
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

    def test_returns_dict_for_known_control(self, loaded_cat):
        """get_control_by_id() finds a known control from a loaded catalog."""
        result = loaded_cat.get_control_by_id("ac-1")
        assert result is not None
        assert isinstance(result, dict)

    def test_returned_dict_has_matching_id(self, loaded_cat):
        """get_control_by_id() returns the dict whose id matches."""
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

    def test_returns_dict_for_known_group(self, loaded_cat):
        """get_group_by_id() finds a known group from a loaded catalog."""
        result = loaded_cat.get_group_by_id("ac")
        assert result is not None
        assert isinstance(result, dict)

    def test_returned_dict_has_matching_id(self, loaded_cat):
        """get_group_by_id() returns the dict whose id matches."""
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

    def test_each_item_is_dict(self, loaded_cat):
        """Each item returned by get_control_list() is a dict."""
        controls = loaded_cat.get_control_list()
        for c in controls[:5]:  # sample first 5
            assert isinstance(c, dict)

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


# ===========================================================================
# Validity after programmatic edits
# ===========================================================================
class TestCatalogEditValidity:
    """Verify that a catalog remains OSCAL-valid after groups and controls are added."""

    @pytest.fixture
    def edited_cat(self):
        """Fresh catalog with one group and two controls."""
        c = Catalog.new("Validity Test Catalog")
        c.create_control_group("[root]", "ac", title="Access Control", label="AC", sort_id="ac")
        c.create_control("ac", "ac-1", title="AC Policy", label="AC-1",
                         sort_id="ac-01",
                         statements=["Establish and maintain an access control policy."],
                         guidance="Include scope and responsibilities.")
        c.create_control("ac", "ac-2", title="Account Management", label="AC-2",
                         sort_id="ac-02",
                         statements=["Manage information system accounts."])
        return c

    def test_valid_after_add_group(self):
        """Catalog passes validate() immediately after create_control_group()."""
        c = Catalog.new("Validity Test")
        c.create_control_group("[root]", "si", title="System and Information Integrity")
        assert c.validate() is True
        assert c.is_valid is True

    def test_valid_after_add_control(self, edited_cat):
        """Catalog passes validate() after controls are added."""
        assert edited_cat.validate() is True
        assert edited_cat.is_valid is True

    def test_validation_errors_empty_after_valid(self, edited_cat):
        """validation_errors is empty when validate() passes."""
        edited_cat.validate()
        assert edited_cat.validation_errors == []

    def test_group_found_after_add(self, edited_cat):
        """get_group_by_id() finds the added group."""
        result = edited_cat.get_group_by_id("ac")
        assert result is not None
        assert result.get("id") == "ac"

    def test_controls_found_after_add(self, edited_cat):
        """get_control_by_id() finds each added control."""
        assert edited_cat.get_control_by_id("ac-1") is not None
        assert edited_cat.get_control_by_id("ac-2") is not None

    def test_control_count(self, edited_cat):
        """__len__ returns the total control count after edits."""
        assert len(edited_cat) == 2


# ===========================================================================
# JSON round-trip: edit → dump JSON → reload → verify
# ===========================================================================
class TestCatalogJsonRoundtrip:
    """Verify group/control data and OSCAL validity survive a JSON save/reload cycle."""

    @pytest.fixture
    def roundtrip(self, tmp_path):
        """
        Build a catalog with one group and one control, save as JSON, reload,
        and return (original, reloaded) as a tuple.
        """
        src = Catalog.new("Roundtrip Test")
        src.create_control_group("[root]", "ac", title="Access Control", label="AC")
        src.create_control("ac", "ac-1", title="AC Policy", label="AC-1",
                           guidance="Implement an AC policy.")
        assert src.validate() is True, "Source catalog must be valid before dump"

        path = str(tmp_path / "catalog.json")
        assert src.dump(path, format="json") is True, "dump() must succeed"

        reloaded = Catalog.load(path)
        return src, reloaded

    def test_reloaded_is_valid_after_load(self, roundtrip):
        """Reloaded catalog has is_valid True immediately after load."""
        _, reloaded = roundtrip
        assert reloaded.is_valid is True

    def test_reloaded_passes_validate(self, roundtrip):
        """Reloaded catalog passes an explicit validate() call."""
        _, reloaded = roundtrip
        assert reloaded.validate() is True

    def test_group_survives_json_roundtrip(self, roundtrip):
        """get_group_by_id() finds the group in the reloaded catalog."""
        _, reloaded = roundtrip
        group = reloaded.get_group_by_id("ac")
        assert group is not None
        assert group.get("id") == "ac"
        assert group.get("title") == "Access Control"

    def test_control_survives_json_roundtrip(self, roundtrip):
        """get_control_by_id() finds the control in the reloaded catalog."""
        _, reloaded = roundtrip
        ctrl = reloaded.get_control_by_id("ac-1")
        assert ctrl is not None
        assert ctrl.get("id") == "ac-1"
        assert ctrl.get("title") == "AC Policy"

    def test_props_survive_json_roundtrip(self, roundtrip):
        """Label props added to the control survive the JSON round-trip."""
        _, reloaded = roundtrip
        ctrl = reloaded.get_control_by_id("ac-1")
        props = ctrl.get("props", [])
        label_props = [p for p in props if p.get("name") == "label"]
        assert len(label_props) == 1
        assert label_props[0].get("value") == "AC-1"

    def test_control_count_preserved(self, roundtrip):
        """len() on the reloaded catalog matches the original."""
        src, reloaded = roundtrip
        assert len(reloaded) == len(src)

    def test_reloaded_is_not_read_only(self, roundtrip):
        """Reloaded catalog is editable (not read-only)."""
        _, reloaded = roundtrip
        assert reloaded.is_read_only is False


# ===========================================================================
# XML round-trip: load XML → validate → dump XML → reload → verify
# ===========================================================================
class TestCatalogXmlRoundtrip:
    """Verify that a catalog loaded from XML survives an XML save/reload cycle."""

    @pytest.fixture(scope="class")
    def xml_roundtrip(self, tmp_path_factory):
        """
        Load the FedRAMP LOW catalog from XML, dump to a new XML file, reload,
        and return (original, reloaded) as a tuple.
        """
        src = Catalog.load(_XML_CATALOG)
        assert src.is_valid, "Source XML catalog must be valid before dump"

        path = str(tmp_path_factory.mktemp("xml") / "catalog_rt.xml")
        assert src.dump(path, format="xml") is True, "dump() must succeed"

        reloaded = Catalog.load(path)
        return src, reloaded

    def test_source_passes_validate_before_dump(self, xml_roundtrip):
        """Loaded XML catalog is OSCAL-valid before serialization."""
        src, _ = xml_roundtrip
        assert src.validate() is True
        assert src.is_valid is True

    def test_reloaded_is_valid_after_load(self, xml_roundtrip):
        """Reloaded XML catalog has is_valid True immediately after load."""
        _, reloaded = xml_roundtrip
        assert reloaded.is_valid is True

    def test_reloaded_passes_validate(self, xml_roundtrip):
        """Reloaded XML catalog passes an explicit validate() call."""
        _, reloaded = xml_roundtrip
        assert reloaded.validate() is True

    def test_reloaded_model_is_catalog(self, xml_roundtrip):
        """Reloaded content is identified as a catalog."""
        _, reloaded = xml_roundtrip
        assert reloaded.model == "catalog"

    def test_known_group_survives_xml_roundtrip(self, xml_roundtrip):
        """A known group ('ac') is still findable after XML round-trip."""
        _, reloaded = xml_roundtrip
        group = reloaded.get_group_by_id("ac")
        assert group is not None
        assert group.get("id") == "ac"

    def test_known_control_survives_xml_roundtrip(self, xml_roundtrip):
        """A known control ('ac-1') is still findable after XML round-trip."""
        _, reloaded = xml_roundtrip
        ctrl = reloaded.get_control_by_id("ac-1")
        assert ctrl is not None
        assert ctrl.get("id") == "ac-1"

    def test_control_count_preserved(self, xml_roundtrip):
        """Control count is unchanged after XML round-trip."""
        src, reloaded = xml_roundtrip
        assert len(reloaded) == len(src)

    def test_control_list_all_dicts(self, xml_roundtrip):
        """Every control in the reloaded catalog is a dict."""
        _, reloaded = xml_roundtrip
        for ctrl in reloaded.get_control_list():
            assert isinstance(ctrl, dict)
