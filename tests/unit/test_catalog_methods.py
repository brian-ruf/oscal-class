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
from oscal.oscal_controls import _find_part, _find_control, _find_group

_HERE = os.path.dirname(__file__)
_DATA = os.path.join(_HERE, "..", "test-data")
_XML_CATALOG = os.path.join(_DATA, "xml", "FedRAMP_rev5_LOW-baseline-resolved-profile_catalog.xml")
_XML_PROFILE = os.path.join(_DATA, "xml", "FedRAMP_rev5_LOW-baseline_profile.xml")
_NESTED_CATALOG = os.path.join(_DATA, "test", "nested_catalog.json")


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

    def test_group_blocked_when_root_has_controls(self, empty_cat):
        """A top-level control means the root can't also take a group -> None."""
        empty_cat.create_control("[root]", "top-1")
        assert empty_cat.create_control_group("[root]", "grp") is None

    def test_group_blocked_when_group_has_controls(self, empty_cat):
        """A group holding controls cannot also take a subgroup."""
        empty_cat.create_control_group("[root]", "ac")
        empty_cat.create_control("ac", "ac-1")
        assert empty_cat.create_control_group("ac", "ac-sub") is None

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
        """create_control() returns None when the parent group/control is not found."""
        result = cat_with_group.create_control("nonexistent", "xx-1")
        assert result is None

    # --- control-under-control (enhancements) ---

    def test_control_under_control(self, cat_with_group):
        """A control can be nested under another control (an enhancement)."""
        cat_with_group.create_control("ac", "ac-2", title="Account Management")
        enh = cat_with_group.create_control("ac-2", "ac-2.1", title="Automated")
        assert enh is not None
        parent = cat_with_group.get_control_by_id("ac-2")
        assert [c["id"] for c in parent.get("controls", [])] == ["ac-2.1"]

    def test_nested_enhancement_retrievable(self, cat_with_group):
        """get_control_by_id() finds a control nested inside another control."""
        cat_with_group.create_control("ac", "ac-2", title="Account Management")
        cat_with_group.create_control("ac-2", "ac-2.1", title="Automated")
        assert cat_with_group.get_control_by_id("ac-2.1") is not None

    def test_enhancement_under_enhancement(self, cat_with_group):
        """Controls nest to arbitrary depth."""
        cat_with_group.create_control("ac", "ac-2", title="Account Management")
        cat_with_group.create_control("ac-2", "ac-2.1", title="Automated")
        deep = cat_with_group.create_control("ac-2.1", "ac-2.1.1", title="Deep")
        assert deep is not None
        assert cat_with_group.get_control_by_id("ac-2.1.1") is not None

    def test_len_counts_nested_controls(self, cat_with_group):
        """__len__/get_control_list count nested enhancements at all levels."""
        before = len(cat_with_group)
        cat_with_group.create_control("ac", "ac-2", title="Account Management")
        cat_with_group.create_control("ac-2", "ac-2.1", title="Automated")
        assert len(cat_with_group) == before + 2

    # --- top-level controls under [root] ---

    def test_control_at_root(self, empty_cat):
        """A control can be added at the catalog top level via '[root]'."""
        result = empty_cat.create_control("[root]", "top-1", title="Top")
        assert result is not None
        assert [c["id"] for c in empty_cat._dict["catalog"].get("controls", [])] == ["top-1"]

    def test_control_at_root_empty_parent(self, empty_cat):
        """An empty parent id also means the catalog top level."""
        assert empty_cat.create_control("", "top-2") is not None

    # --- no mixing of controls and groups at one level ---

    def test_control_blocked_when_root_has_groups(self, cat_with_group):
        """cat_with_group has a root group; a top-level control would mix -> None."""
        assert cat_with_group.create_control("[root]", "loose") is None

    def test_control_ok_in_empty_group(self, cat_with_group):
        """A control in a group that has no subgroups is fine."""
        assert cat_with_group.create_control("ac", "ac-1") is not None

    def test_control_blocked_when_group_has_subgroups(self, empty_cat):
        """A group holding subgroups cannot also take a control."""
        empty_cat.create_control_group("[root]", "fam")
        empty_cat.create_control_group("fam", "fam.1")
        assert empty_cat.create_control("fam", "loose") is None

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

    def test_returns_safe_copies(self):
        """Mutating a control from get_control_list() does not change the catalog."""
        c = Catalog.load(_NESTED_CATALOG)
        c.get_control_list()[0]["title"] = "MUTATED"
        assert all(ctrl["title"] != "MUTATED" for ctrl in c.get_control_list())

    def test_preserves_internal_identity(self):
        """A single deepcopy keeps an enhancement nested in its parent identical to its
        own standalone entry in the flat list."""
        c = Catalog.load(_NESTED_CATALOG)
        lst = c.get_control_list()
        by_id = {ctrl["id"]: ctrl for ctrl in lst}
        assert by_id["c1"]["controls"][0] is by_id["c1.1"]


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

    @staticmethod
    def _resolved_profile():
        """A real profile with a real nested catalog attached and marked resolved."""
        from oscal.oscal_controls import ResolutionStatus
        profile = Profile.load(_XML_PROFILE)
        profile.catalog = Catalog.load(_NESTED_CATALOG)
        profile.resolution_status = ResolutionStatus.RESOLVED
        return profile

    def test_resolved_forwards_depth(self):
        """control(depth=0) forwards depth to the catalog getter (enhancements pruned)."""
        profile = self._resolved_profile()
        assert "controls" not in profile.control("c1", depth=0)
        assert profile.control("c1", depth=1)["controls"][0]["id"] == "c1.1"

    def test_resolved_returns_safe_copy(self):
        """Mutating control()'s return value does not change the resolved catalog."""
        profile = self._resolved_profile()
        profile.control("c1")["title"] = "MUTATED"
        assert profile.control("c1")["title"] == "Control One"


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

    @staticmethod
    @pytest.fixture(scope="class")
    def xml_roundtrip(tmp_path_factory):
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


# ===========================================================================
# Catalog.add_part() / set_part_title()
# ===========================================================================
class TestParts:

    @pytest.fixture
    def cat_with_control(self):
        c = Catalog.new("Parts Test")
        c.create_control_group("[root]", "ac", title="Access Control")
        c.create_control("ac", "ac-1", title="Policy")
        return c

    def test_add_part_to_control(self, cat_with_control):
        part = cat_with_control.add_part("ac-1", "guidance", prose="Some guidance")
        assert part is not None
        assert part["name"] == "guidance"
        ctrl = cat_with_control.get_control_by_id("ac-1")
        assert ctrl["parts"][0]["prose"] == "Some guidance"

    def test_multiple_guidance_parts_allowed(self, cat_with_control):
        cat_with_control.add_part("ac-1", "guidance", prose="one")
        cat_with_control.add_part("ac-1", "guidance", prose="two")
        names = [p["name"] for p in cat_with_control.get_control_by_id("ac-1")["parts"]]
        assert names.count("guidance") == 2

    def test_add_part_to_group(self, cat_with_control):
        part = cat_with_control.add_part("ac", "overview", title="Fam", prose="About")
        grp = cat_with_control.get_group_by_id("ac")
        assert grp["parts"][0]["name"] == "overview"
        assert grp["parts"][0]["title"] == "Fam"

    def test_add_part_with_title_and_attrs(self, cat_with_control):
        part = cat_with_control.add_part(
            "ac-1", "objective", title="Obj", ns="http://example.com/ns",
            part_class="sp800-53a", part_id="ac-1_obj",
        )
        assert part["title"] == "Obj"
        assert part["ns"] == "http://example.com/ns"
        assert part["class"] == "sp800-53a"
        assert part["id"] == "ac-1_obj"

    def test_nested_part_under_part(self, cat_with_control):
        cat_with_control.add_part("ac-1", "statement", part_id="ac-1_smt")
        child = cat_with_control.add_part("ac-1_smt", "item", prose="an item", part_id="ac-1_smt_1")
        assert child is not None
        parent = _find_part(cat_with_control._dict["catalog"], "ac-1_smt")
        assert [p["name"] for p in parent.get("parts", [])] == ["item"]

    def test_add_part_missing_name_returns_none(self, cat_with_control):
        assert cat_with_control.add_part("ac-1", "") is None

    def test_add_part_unknown_parent_returns_none(self, cat_with_control):
        assert cat_with_control.add_part("nonexistent", "guidance") is None

    def test_add_part_marks_unsaved(self, cat_with_control):
        cat_with_control.is_unsaved = False
        cat_with_control.add_part("ac-1", "guidance", prose="g")
        assert cat_with_control.is_unsaved is True

    # --- set_part_title ---

    def test_set_part_title(self, cat_with_control):
        cat_with_control.add_part("ac-1", "guidance", prose="g", part_id="ac-1_g")
        result = cat_with_control.set_part_title("ac-1_g", "Guidance Title")
        assert result["title"] == "Guidance Title"
        assert _find_part(cat_with_control._dict["catalog"], "ac-1_g")["title"] == "Guidance Title"

    def test_remove_part_title(self, cat_with_control):
        cat_with_control.add_part("ac-1", "guidance", title="T", prose="g", part_id="ac-1_g")
        cat_with_control.set_part_title("ac-1_g", "")
        assert "title" not in _find_part(cat_with_control._dict["catalog"], "ac-1_g")

    def test_set_part_title_unknown_returns_none(self, cat_with_control):
        assert cat_with_control.set_part_title("nope") is None

    # --- leaf-part rule: guidance may not have child parts ---

    def test_guidance_created_without_children(self, cat_with_control):
        assert cat_with_control.add_part("ac-1", "guidance", prose="g") is not None

    def test_add_child_to_guidance_blocked(self, cat_with_control):
        cat_with_control.add_part("ac-1", "guidance", prose="g", part_id="ac-1_g")
        assert cat_with_control.add_part("ac-1_g", "item", prose="x") is None

    def test_guidance_with_inline_parts_blocked(self, cat_with_control):
        assert cat_with_control.add_part("ac-1", "guidance", parts=[{"name": "item"}]) is None

    def test_non_leaf_part_may_have_children(self, cat_with_control):
        cat_with_control.add_part("ac-1", "statement", part_id="ac-1_smt")
        assert cat_with_control.add_part("ac-1_smt", "item", prose="i") is not None
        assert cat_with_control.add_part("ac-1", "statement", parts=[{"name": "item"}]) is not None


# ===========================================================================
# Catalog.controls_tree  (light group/control hierarchy for UI navigation)
# ===========================================================================
class TestControlsTree:

    # --- attribute existence / initial state ---

    def test_attribute_exists_on_new(self, empty_cat):
        """A new (empty) catalog exposes controls_tree as an empty list."""
        assert hasattr(empty_cat, "controls_tree")
        assert empty_cat.controls_tree == []

    def test_built_on_valid_load(self, loaded_cat):
        """Loading a valid catalog builds a non-empty controls_tree."""
        assert loaded_cat.is_valid
        assert isinstance(loaded_cat.controls_tree, list)
        assert len(loaded_cat.controls_tree) > 0

    # --- node structure ---

    def test_node_shape(self, loaded_cat):
        """Every node has exactly the documented keys."""
        node = loaded_cat.controls_tree[0]
        assert set(node.keys()) == {"id", "label", "title", "group", "children"}

    def test_node_types(self, loaded_cat):
        node = loaded_cat.controls_tree[0]
        assert isinstance(node["id"], str)
        assert isinstance(node["label"], str)
        assert isinstance(node["title"], str)
        assert isinstance(node["group"], bool)
        assert isinstance(node["children"], list)

    # --- add group / control updates the tree ---

    def test_add_group_updates_tree(self, empty_cat):
        empty_cat.create_control_group("[root]", "ac", title="Access Control", label="AC")
        ids = [n["id"] for n in empty_cat.controls_tree]
        assert ids == ["ac"]
        node = empty_cat.controls_tree[0]
        assert node["group"] is True
        assert node["label"] == "AC"
        assert node["title"] == "Access Control"

    def test_add_control_updates_tree(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Policy", label="AC-1")
        group_node = cat_with_group.controls_tree[0]
        child_ids = [c["id"] for c in group_node["children"]]
        assert child_ids == ["ac-1"]
        child = group_node["children"][0]
        assert child["group"] is False
        assert child["label"] == "AC-1"

    def test_control_at_root(self, empty_cat):
        """A control added at the catalog root appears as a top-level node."""
        empty_cat.create_control("[root]", "ac-1", title="Policy", label="AC-1")
        node = empty_cat.controls_tree[0]
        assert node["id"] == "ac-1"
        assert node["group"] is False

    # --- nesting: control enhancements are nested children ---

    def test_enhancement_nested(self, empty_cat):
        empty_cat.create_control("[root]", "ac-2", title="Account Mgmt", label="AC-2")
        empty_cat.create_control("ac-2", "ac-2.1", title="Automated", label="AC-2(1)")
        parent = empty_cat.controls_tree[0]
        assert [c["id"] for c in parent["children"]] == ["ac-2.1"]
        assert parent["children"][0]["label"] == "AC-2(1)"

    def test_nested_groups(self, empty_cat):
        empty_cat.create_control_group("[root]", "fam", title="Family")
        empty_cat.create_control_group("fam", "sub", title="Subfamily", label="SUB")
        top = empty_cat.controls_tree[0]
        assert top["id"] == "fam"
        assert [c["id"] for c in top["children"]] == ["sub"]
        assert top["children"][0]["group"] is True

    # --- label determination via get_props (default ns, no class/group) ---

    def test_label_from_prop(self, empty_cat):
        empty_cat.create_control_group("[root]", "ac", title="Access Control", label="AC")
        assert empty_cat.controls_tree[0]["label"] == "AC"

    def test_missing_label_is_empty_string(self, empty_cat):
        """A group/control with no label prop yields an empty-string label, not None."""
        empty_cat.create_control_group("[root]", "ac", title="Access Control")
        assert empty_cat.controls_tree[0]["label"] == ""

    def test_first_label_used_when_multiple(self, empty_cat):
        """When several matching label props exist, the first (best match) is used."""
        empty_cat.create_control_group("[root]", "ac", title="Access Control")
        # Two label props in the default namespace, no class/group. Set on the LIVE
        # group (create_* returns a safe copy).
        _find_group(empty_cat._catalog_root().get("groups", []), "ac")["props"] = [
            {"name": "label", "value": "FIRST"},
            {"name": "label", "value": "SECOND"},
        ]
        empty_cat._build_controls_tree()
        assert empty_cat.controls_tree[0]["label"] == "FIRST"

    # --- validity behaviour ---

    def test_invalid_catalog_has_empty_tree(self, loaded_cat):
        """Re-validating while not valid empties the tree; validity restores it."""
        from oscal.oscal_content import ContentState
        loaded_cat.content_state = ContentState.WELL_FORMED
        # Corrupt the dict so validation fails, then confirm the tree is emptied.
        saved = loaded_cat._dict
        loaded_cat._dict = {"catalog": {"not": "valid"}}
        loaded_cat.validate()
        try:
            assert not loaded_cat.is_valid
            assert loaded_cat.controls_tree == []
        finally:
            loaded_cat._dict = saved
            loaded_cat.validate()  # restore for other tests sharing this module fixture


# ===========================================================================
# Catalog.set_title() / Catalog.set_label()  (control/group, by id)
# ===========================================================================
class TestSetTitle:

    def test_set_control_title(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Old")
        assert cat_with_group.set_title("ac-1", "New") is not None
        assert cat_with_group.get_control_by_id("ac-1")["title"] == "New"

    def test_set_group_title(self, cat_with_group):
        assert cat_with_group.set_title("ac", "Access Control (rev)") is not None
        assert cat_with_group.get_group_by_id("ac")["title"] == "Access Control (rev)"

    def test_title_updates_tree(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Old", label="AC-1")
        cat_with_group.set_title("ac-1", "New")
        assert cat_with_group.controls_tree[0]["children"][0]["title"] == "New"

    def test_empty_title_rejected(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Keep")
        assert cat_with_group.set_title("ac-1", "") is None
        assert cat_with_group.get_control_by_id("ac-1")["title"] == "Keep"

    def test_unknown_id_returns_none(self, cat_with_group):
        assert cat_with_group.set_title("nope", "X") is None


class TestSetLabel:

    def test_update_existing_plain_label(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Policy", label="AC-1")
        assert cat_with_group.set_label("ac-1", "AC-01") is not None
        assert cat_with_group.controls_tree[0]["children"][0]["label"] == "AC-01"

    def test_create_label_when_missing(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Policy")  # no label
        assert cat_with_group.controls_tree[0]["children"][0]["label"] == ""
        cat_with_group.set_label("ac-1", "AC-1")
        assert cat_with_group.controls_tree[0]["children"][0]["label"] == "AC-1"
        props = [p for p in cat_with_group.get_control_by_id("ac-1")["props"] if p["name"] == "label"]
        assert props == [{"name": "label", "value": "AC-1"}]

    def test_set_group_label(self, cat_with_group):
        cat_with_group.set_label("ac", "AC")
        assert cat_with_group.controls_tree[0]["label"] == "AC"

    def test_empty_removes_matching_label(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Policy", label="AC-1")
        cat_with_group.set_label("ac-1", "")
        assert cat_with_group.controls_tree[0]["children"][0]["label"] == ""
        # 'props' key removed entirely when it becomes empty
        assert "props" not in cat_with_group.get_control_by_id("ac-1")

    def test_plain_request_ignores_qualified_label(self, cat_with_group):
        """A class-qualified label does not satisfy a default (no class/group) set;
        a new plain label is created and the qualified one is left intact."""
        cat_with_group.create_control("ac", "ac-1", title="Policy")
        # Set the qualified label on the LIVE control (create_* returns a safe copy).
        _find_control(cat_with_group._catalog_root(), "ac-1")["props"] = [
            {"name": "label", "value": "CLS", "class": "sort"}]
        cat_with_group.set_label("ac-1", "PLAIN")
        labels = {(p.get("value"), p.get("class"))
                  for p in cat_with_group.get_control_by_id("ac-1")["props"] if p["name"] == "label"}
        assert labels == {("PLAIN", None), ("CLS", "sort")}
        assert cat_with_group.controls_tree[0]["children"][0]["label"] == "PLAIN"

    def test_qualified_request_targets_qualified_label(self, cat_with_group):
        ctrl = cat_with_group.create_control("ac", "ac-1", title="Policy")
        ctrl["props"] = [{"name": "label", "value": "CLS", "class": "sort"}]
        cat_with_group.set_label("ac-1", "CLS2", class_="sort")
        labels = [(p.get("value"), p.get("class"))
                  for p in cat_with_group.get_control_by_id("ac-1")["props"] if p["name"] == "label"]
        assert labels == [("CLS2", "sort")]

    def test_qualified_create_when_missing(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Policy", label="AC-1")  # plain only
        cat_with_group.set_label("ac-1", "G1", group="grp")
        props = cat_with_group.get_control_by_id("ac-1")["props"]
        assert {"name": "label", "value": "G1", "group": "grp"} in props
        # plain label untouched
        assert {"name": "label", "value": "AC-1"} in props

    def test_unknown_id_returns_none(self, cat_with_group):
        assert cat_with_group.set_label("nope", "X") is None


# ===========================================================================
# Catalog.remove()  (by id; cascade + referential-integrity locks; reports)
# ===========================================================================
class TestRemove:

    @pytest.fixture
    def cat_tree(self):
        """Catalog: group 'ac' > controls 'ac-1', 'ac-2'; 'ac-2' has enhancement 'ac-2.1'.
        All controls are plain (no parts)."""
        c = Catalog.new("T")
        c.create_control_group("[root]", "ac", title="Access Control", label="AC")
        c.create_control("ac", "ac-1", title="Policy", label="AC-1")
        c.create_control("ac", "ac-2", title="Account Mgmt", label="AC-2")
        c.create_control("ac-2", "ac-2.1", title="Enh", label="AC-2(1)")
        return c

    # --- leaf removal (success) ---

    def test_remove_leaf_success(self, cat_tree):
        report = cat_tree.remove("ac-1")
        assert report == {"removed": True, "removed_ids": ["ac-1"], "dangling_refs": []}
        assert cat_tree.get_control_by_id("ac-1") is None

    def test_remove_updates_tree(self, cat_tree):
        cat_tree.remove("ac-1")
        group_children = [c["id"] for c in cat_tree.controls_tree[0]["children"]]
        assert "ac-1" not in group_children

    def test_leaf_cascade_flag_harmless(self, cat_tree):
        assert cat_tree.remove("ac-1", cascade=True)["removed"] is True

    def test_empty_list_key_removed(self):
        c = Catalog.new("T")
        c.create_control("[root]", "a", title="A")
        c.remove("a")
        assert "controls" not in c._catalog_root()

    # --- cascade lock ---

    def test_cascade_block_lists_immediate_children(self, cat_tree):
        report = cat_tree.remove("ac")           # group with two controls
        assert report["removed"] is False
        assert report["blocked_by"] == ["cascade"]
        assert report["children"] == ["ac-1", "ac-2"]     # immediate only, not ac-2.1
        assert cat_tree.get_group_by_id("ac") is not None  # nothing removed

    def test_cascade_block_on_enhancement(self, cat_tree):
        report = cat_tree.remove("ac-2")         # control with one enhancement
        assert report["blocked_by"] == ["cascade"]
        assert report["children"] == ["ac-2.1"]

    def test_cascade_success_subtree(self, cat_tree):
        report = cat_tree.remove("ac-2", cascade=True)
        assert report["removed"] is True
        assert set(report["removed_ids"]) == {"ac-2", "ac-2.1"}

    def test_cascade_success_group_all(self, cat_tree):
        report = cat_tree.remove("ac", cascade=True)
        assert set(report["removed_ids"]) == {"ac", "ac-1", "ac-2", "ac-2.1"}
        assert cat_tree.controls_tree == []

    # --- parts count as immediate children / removed ids ---

    def test_part_blocks_cascade(self):
        c = Catalog.new("T")
        c.create_control("[root]", "x", title="X", statements=["a statement"])
        report = c.remove("x")                    # x has a statement part (id 'x_smt')
        assert report["blocked_by"] == ["cascade"]
        assert "x_smt" in report["children"]

    def test_idless_part_shown_by_name(self):
        c = Catalog.new("T")
        c.create_control("[root]", "x", title="X", overview="some overview")  # id-less part
        report = c.remove("x")
        assert report["children"] == ["(part:overview)"]

    def test_part_ids_in_removed(self):
        c = Catalog.new("T")
        c.create_control("[root]", "x", title="X", statements=["a statement"])
        report = c.remove("x", cascade=True)
        assert set(report["removed_ids"]) == {"x", "x_smt"}

    # --- referential-integrity lock ---

    def _linked_pair(self):
        c = Catalog.new("T")
        c.create_control("[root]", "a", title="A")
        c.create_control("[root]", "b", title="B")
        # Build the reference on the LIVE tree (getters now return safe copies).
        _find_control(c._catalog_root(), "a").setdefault("links", []).append({"href": "#b", "rel": "related"})
        return c

    def test_reference_blocks_delete(self):
        c = self._linked_pair()
        report = c.remove("b")                     # b is referenced by a
        assert report["removed"] is False
        assert report["blocked_by"] == ["referential-integrity"]
        assert report["referenced_ids"] == ["b"]
        assert c.get_control_by_id("b") is not None

    def test_unreferenced_leaf_not_blocked(self):
        c = self._linked_pair()
        # 'a' links out but is not itself referenced -> deletable
        assert c.remove("a")["removed"] is True

    def test_ignore_references_deletes_and_reports_dangling(self):
        c = self._linked_pair()
        report = c.remove("b", ignore_references=True)
        assert report["removed"] is True
        assert {"in": "a", "href": "#b", "rel": "related"} in report["dangling_refs"]
        # reference is reported, not stripped
        assert c.get_control_by_id("a")["links"] == [{"href": "#b", "rel": "related"}]

    def test_internal_reference_does_not_block(self, cat_tree):
        """A link from inside the removed subtree to another node in the subtree is
        not an external reference and must not block the cascade delete."""
        _find_control(cat_tree._catalog_root(), "ac-2").setdefault("links", []).append(
            {"href": "#ac-2.1", "rel": "related"})
        report = cat_tree.remove("ac-2", cascade=True)
        assert report["removed"] is True

    def test_referenced_part_blocks(self):
        c = Catalog.new("T")
        c.create_control("[root]", "x", title="X", statements=["s"])   # part id 'x_smt'
        c.create_control("[root]", "y", title="Y")
        _find_control(c._catalog_root(), "y").setdefault("links", []).append({"href": "#x_smt", "rel": "related"})
        report = c.remove("x", cascade=True)       # cascade allowed, but part is referenced
        assert report["blocked_by"] == ["referential-integrity"]
        assert report["referenced_ids"] == ["x_smt"]

    # --- both locks at once ---

    def test_both_locks_reported(self):
        # Two sibling groups; a control in 'h' references a control in 'g'.
        c = Catalog.new("T")
        c.create_control_group("[root]", "g", title="G")
        c.create_control("g", "c", title="C")
        c.create_control_group("[root]", "h", title="H")
        c.create_control("h", "e", title="E")
        _find_control(c._catalog_root(), "e").setdefault("links", []).append({"href": "#c", "rel": "related"})
        report = c.remove("g")            # g has child c (cascade) AND c is referenced by e
        assert set(report["blocked_by"]) == {"cascade", "referential-integrity"}
        assert report["children"] == ["c"]
        assert report["referenced_ids"] == ["c"]

    # --- misc / no-op safety ---

    def test_unknown_id_returns_none(self, cat_tree):
        assert cat_tree.remove("nope") is None

    def test_no_dangling_when_none(self, cat_tree):
        assert cat_tree.remove("ac-1")["dangling_refs"] == []

    def test_block_does_not_mark_unsaved(self, cat_tree):
        cat_tree.is_unsaved = False
        cat_tree.remove("ac")            # blocked by cascade
        assert cat_tree.is_unsaved is False

    def test_success_marks_unsaved(self, cat_tree):
        cat_tree.is_unsaved = False
        cat_tree.remove("ac-1")
        assert cat_tree.is_unsaved is True


# ===========================================================================
# Profile.set_merge()  (combine + flat/as-is/custom directives)
# ===========================================================================
class TestSetMerge:

    @pytest.fixture
    def prof(self):
        return Profile.new("Test Profile")

    def _merge(self, prof):
        return prof._dict["profile"].get("merge")

    # --- exactly one of flat / as-is / custom ---

    def test_none_chosen_rejected(self, prof):
        assert prof.set_merge() is None

    def test_two_chosen_rejected(self, prof):
        assert prof.set_merge(flat=True, as_is=True) is None

    def test_all_three_rejected(self, prof):
        assert prof.set_merge(flat=True, as_is=True, custom={}) is None

    def test_combine_alone_rejected(self, prof):
        assert prof.set_merge(combine="merge") is None

    # --- flat / as-is / custom ---

    def test_flat(self, prof):
        assert prof.set_merge(flat=True) == {"flat": {}}
        assert self._merge(prof) == {"flat": {}}

    def test_as_is_true(self, prof):
        assert prof.set_merge(as_is=True) == {"as-is": True}

    def test_as_is_false_is_a_choice(self, prof):
        # as_is=False still selects the as-is directive (value False)
        assert prof.set_merge(as_is=False) == {"as-is": False}

    def test_custom(self, prof):
        obj = {"groups": [{"id": "g1", "title": "G1"}]}
        assert prof.set_merge(custom=obj) == {"custom": obj}

    # --- combine (optional, any choice), canonical order ---

    def test_combine_with_choice_order(self, prof):
        m = prof.set_merge(as_is=True, combine="merge")
        assert list(m.keys()) == ["combine", "as-is"]
        assert m["combine"] == {"method": "merge"}

    def test_combine_methods_accepted(self, prof):
        for method in ("use-first", "merge", "keep"):
            assert prof.set_merge(flat=True, combine=method)["combine"] == {"method": method}

    # --- validation / rejection leaves prior merge intact ---

    def test_invalid_combine_rejected(self, prof):
        prof.set_merge(flat=True)
        before = self._merge(prof)
        assert prof.set_merge(flat=True, combine="bogus") is None
        assert self._merge(prof) == before

    def test_invalid_custom_rejected(self, prof):
        prof.set_merge(flat=True)
        before = self._merge(prof)
        # order must be one of keep/ascending/descending
        assert prof.set_merge(custom={"insert-controls": [{"order": "bogus"}]}) is None
        assert self._merge(prof) == before

    def test_custom_wrong_type_rejected(self, prof):
        assert prof.set_merge(custom="nope") is None

    def test_as_is_wrong_type_rejected(self, prof):
        assert prof.set_merge(as_is=1) is None       # int, not bool

    def test_combine_wrong_type_rejected(self, prof):
        assert prof.set_merge(flat=True, combine=123) is None

    # --- overwrite + schema validity + dirty flag ---

    def test_overwrites_existing_merge(self, prof):
        prof.set_merge(as_is=True)
        prof.set_merge(flat=True)
        assert self._merge(prof) == {"flat": {}}

    @pytest.mark.parametrize("kwargs", [
        {"flat": True},
        {"as_is": True},
        {"as_is": True, "combine": "keep"},
        {"custom": {"groups": [{"id": "g1", "title": "G1"}]}},
    ])
    def test_written_merge_is_schema_valid(self, prof, kwargs):
        prof.set_merge(**kwargs)
        assert prof.validate() is True

    def test_success_marks_unsaved(self, prof):
        prof.is_unsaved = False
        prof.set_merge(flat=True)
        assert prof.is_unsaved is True

    def test_rejection_does_not_mark_unsaved(self, prof):
        prof.is_unsaved = False
        prof.set_merge()          # rejected (no choice)
        assert prof.is_unsaved is False


# ===========================================================================
# get_control_by_id / get_group_by_id — depth pruning + safe-copy ownership
# ===========================================================================
class TestGetterDepthAndCopy:
    """The by-id getters return depth-pruned SAFE COPIES.

    depth prunes only nested child groups/controls; the node's own intrinsic
    content (props, parts, params, links) is always returned in full. The return
    value is detached — mutating it must never change the catalog.
    """

    @pytest.fixture
    def cat(self):
        return Catalog.load(_NESTED_CATALOG)

    # -- control depth ----------------------------------------------------
    def test_control_default_depth_full_subtree(self, cat):
        """depth=None (default) returns the full enhancement subtree."""
        c1 = cat.get_control_by_id("c1")
        assert c1["controls"][0]["id"] == "c1.1"
        assert c1["controls"][0]["controls"][0]["id"] == "c1.1.1"

    def test_control_depth0_strips_enhancements(self, cat):
        c1 = cat.get_control_by_id("c1", depth=0)
        assert "controls" not in c1

    def test_control_depth0_keeps_intrinsic_content(self, cat):
        """parts/props remain even when enhancements are pruned."""
        c1 = cat.get_control_by_id("c1", depth=0)
        assert "parts" in c1 and "props" in c1
        assert c1["title"] == "Control One"

    def test_control_depth1_keeps_one_level(self, cat):
        c1 = cat.get_control_by_id("c1", depth=1)
        assert c1["controls"][0]["id"] == "c1.1"
        assert "controls" not in c1["controls"][0]   # grandchild pruned

    def test_control_depth2_keeps_two_levels(self, cat):
        c1 = cat.get_control_by_id("c1", depth=2)
        assert c1["controls"][0]["controls"][0]["id"] == "c1.1.1"

    # -- group depth ------------------------------------------------------
    def test_group_depth0_strips_children(self, cat):
        g1 = cat.get_group_by_id("g1", depth=0)
        assert "groups" not in g1 and "controls" not in g1
        assert "props" in g1                          # intrinsic retained

    def test_group_depth1_prunes_grandchildren(self, cat):
        g1 = cat.get_group_by_id("g1", depth=1)
        assert g1["groups"][0]["id"] == "g1a"
        assert "controls" not in g1["groups"][0]      # g1a's controls pruned

    def test_group_depth1_controls_enhancements_pruned(self, cat):
        g2 = cat.get_group_by_id("g2", depth=1)
        assert g2["controls"][0]["id"] == "c1"
        assert "controls" not in g2["controls"][0]    # c1's enhancements pruned

    # -- safe-copy ownership ---------------------------------------------
    def test_returned_control_is_a_copy(self, cat):
        """Mutating a returned control does not change the catalog."""
        c1 = cat.get_control_by_id("c1")
        c1["title"] = "MUTATED"
        c1["props"][0]["value"] = "MUTATED"
        fresh = cat.get_control_by_id("c1")
        assert fresh["title"] == "Control One"
        assert fresh["props"][0]["value"] == "C1"

    def test_returned_group_is_a_copy(self, cat):
        g1 = cat.get_group_by_id("g1")
        g1["groups"][0]["controls"][0]["title"] = "MUTATED"
        fresh = cat.get_group_by_id("g1")
        assert fresh["groups"][0]["controls"][0]["title"] == "Deep Control"

    def test_full_depth_returned_control_is_a_copy(self, cat):
        """Even the default full-subtree return is detached, not a live reference."""
        assert cat.get_control_by_id("c1") is not cat.get_control_by_id("c1")

    # -- edge cases -------------------------------------------------------
    def test_missing_id_returns_none(self, cat):
        assert cat.get_control_by_id("nope") is None
        assert cat.get_group_by_id("nope", depth=0) is None

    def test_negative_depth_raises(self, cat):
        with pytest.raises(ValueError):
            cat.get_control_by_id("c1", depth=-1)
        with pytest.raises(ValueError):
            cat.get_group_by_id("g1", depth=-1)


# ===========================================================================
# Mutator returns are safe copies (create_*/add_part/set_*)
# ===========================================================================
class TestMutatorReturnsCopy:
    """Creation/mutation methods return a detached copy of the affected node;
    mutating the return value must not change the catalog."""

    def test_create_control_returns_copy(self, cat_with_group):
        ctrl = cat_with_group.create_control("ac", "ac-1", title="Policy")
        ctrl["title"] = "MUTATED"
        assert cat_with_group.get_control_by_id("ac-1")["title"] == "Policy"

    def test_create_control_group_returns_copy(self, empty_cat):
        grp = empty_cat.create_control_group("[root]", "ac", title="Access Control")
        grp["title"] = "MUTATED"
        assert empty_cat.get_group_by_id("ac")["title"] == "Access Control"

    def test_add_part_returns_copy(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Policy")
        part = cat_with_group.add_part("ac-1", name="guidance", prose="Original.")
        part["prose"] = "MUTATED"
        ctrl = cat_with_group.get_control_by_id("ac-1")
        assert ctrl["parts"][0]["prose"] == "Original."

    def test_set_title_returns_copy(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Policy")
        returned = cat_with_group.set_title("ac-1", "New Title")
        returned["title"] = "MUTATED"
        assert cat_with_group.get_control_by_id("ac-1")["title"] == "New Title"

    def test_set_label_returns_copy(self, cat_with_group):
        cat_with_group.create_control("ac", "ac-1", title="Policy")
        returned = cat_with_group.set_label("ac-1", "AC-1")
        returned["props"] = []
        labels = [p for p in cat_with_group.get_control_by_id("ac-1")["props"]
                  if p["name"] == "label"]
        assert any(p["value"] == "AC-1" for p in labels)
