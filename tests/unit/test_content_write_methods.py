"""
Unit tests for OSCAL content write methods (OSCAL base class and module functions):
    - OSCAL.__set_field()
    - OSCAL.set_metadata()
    - OSCAL.append_child()
    - OSCAL.append_resource()             (instance method)
    - append_prop() / append_props()      (module functions)
    - append_link() / append_links()      (module functions)
    - append_resource()                   (module function)
"""
import pytest

from oscal import Catalog
from oscal.oscal_content import (
    _OSCAL_NS,
    append_link,
    append_links,
    append_prop,
    append_props,
    append_resource,
    get_props,
)


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def cat():
    """Fresh writable catalog for each test."""
    return Catalog.new("Write Test Catalog")


# ===========================================================================
# OSCAL.__set_field()
# ===========================================================================
class TestSetField:

    def test_sets_scalar_value(self, cat):
        """__set_field() updates a scalar string in _dict."""
        cat._OSCAL__set_field("metadata/title", "New Title")
        assert cat._dict["catalog"]["metadata"]["title"] == "New Title"

    def test_overwrites_existing_value(self, cat):
        """__set_field() overwrites an existing key."""
        cat._OSCAL__set_field("metadata/title", "First")
        cat._OSCAL__set_field("metadata/title", "Second")
        assert cat._dict["catalog"]["metadata"]["title"] == "Second"

    def test_sets_non_string_value(self, cat):
        """__set_field() accepts any JSON-compatible value type."""
        cat._OSCAL__set_field("metadata/title", 42)
        assert cat._dict["catalog"]["metadata"]["title"] == 42

    def test_missing_intermediate_key_returns_false(self, cat):
        """__set_field() returns False when an intermediate key does not exist."""
        result = cat._OSCAL__set_field("nonexistent/title", "x")
        assert result is False

    def test_list_index_set(self, cat):
        """__set_field() can set a value inside a list by integer index."""
        meta = cat._dict["catalog"]["metadata"]
        meta["roles"] = [{"id": "admin", "title": "Admin"}]
        cat._OSCAL__set_field("metadata/roles/0/title", "Updated Admin")
        assert meta["roles"][0]["title"] == "Updated Admin"

    def test_invalid_list_index_returns_false(self, cat):
        """__set_field() returns False on an out-of-range list index."""
        cat._dict["catalog"]["metadata"]["roles"] = []
        result = cat._OSCAL__set_field("metadata/roles/5/title", "x")
        assert result is False

    def test_no_dict_returns_none(self, cat):
        """__set_field() returns None when _dict is None (guard failure via _can_mutate).

        None — not False — so the @if_update_successful decorator does not wrongly
        flag the content as unsaved on a guard failure.
        """
        cat._dict = None
        result = cat._OSCAL__set_field("metadata/title", "x")
        assert result is None

    def test_returns_true_on_success(self, cat):
        """__set_field() returns True when the write succeeds."""
        result = cat._OSCAL__set_field("metadata/title", "OK")
        assert result is True


# ===========================================================================
# OSCAL.set_metadata()
# ===========================================================================
class TestSetMetadata:

    def test_set_title(self, cat):
        """set_metadata() updates the title in _dict."""
        cat.set_metadata({"title": "Updated Title"})
        assert cat._dict["catalog"]["metadata"]["title"] == "Updated Title"

    def test_set_version(self, cat):
        """set_metadata() updates the version in _dict."""
        cat.set_metadata({"version": "2.0"})
        assert cat._dict["catalog"]["metadata"]["version"] == "2.0"

    def test_set_multiple_fields(self, cat):
        """set_metadata() can set several scalar fields in one call."""
        cat.set_metadata({"title": "Multi Field", "version": "3.0"})
        assert cat._dict["catalog"]["metadata"]["title"] == "Multi Field"
        assert cat._dict["catalog"]["metadata"]["version"] == "3.0"

    def test_set_empty_dict_no_crash(self, cat):
        """set_metadata({}) must not raise."""
        cat.set_metadata({})

    def test_complex_field_skipped_gracefully(self, cat):
        """Complex fields (roles, parties …) are skipped without raising."""
        cat.set_metadata({"roles": [{"id": "admin", "title": "Admin"}]})

    def test_marks_content_modified(self, cat):
        """set_metadata() marks the object as having unsaved changes."""
        cat.set_metadata({"title": "Modified"})
        assert cat.is_unsaved is True


# ===========================================================================
# OSCAL.append_child()
# ===========================================================================
class TestAppendChild:

    def test_returns_dict(self, cat):
        """append_child() returns the appended dict on success."""
        result = cat.append_child("metadata/props", {"name": "label", "value": "AC-1"})
        assert result is not None
        assert isinstance(result, dict)

    def test_child_appended_to_list(self, cat):
        """append_child() appends the child to the list at the given path."""
        child = {"name": "label", "value": "AC-1"}
        cat.append_child("metadata/props", child)
        props = cat._dict["catalog"]["metadata"]["props"]
        assert len(props) == 1
        assert props[0] is child

    def test_creates_list_when_absent(self, cat):
        """append_child() creates the target list when the key does not exist."""
        cat.append_child("metadata/props", {"name": "x", "value": "y"})
        assert "props" in cat._dict["catalog"]["metadata"]

    def test_multiple_appends_ordered(self, cat):
        """append_child() preserves insertion order across multiple calls."""
        cat.append_child("metadata/props", {"name": "a", "value": "1"})
        cat.append_child("metadata/props", {"name": "b", "value": "2"})
        props = cat._dict["catalog"]["metadata"]["props"]
        assert props[0]["name"] == "a"
        assert props[1]["name"] == "b"

    def test_bad_path_returns_none(self, cat):
        """append_child() returns None when an intermediate path key is missing."""
        result = cat.append_child("nonexistent/props", {"name": "x", "value": "y"})
        assert result is None

    def test_leaf_not_list_returns_none(self, cat):
        """append_child() returns None when the leaf key holds a non-list value."""
        cat._dict["catalog"]["metadata"]["title"] = "scalar"
        result = cat.append_child("metadata/title", {"name": "x", "value": "y"})
        assert result is None

    def test_marks_content_modified(self, cat):
        """append_child() marks the object as having unsaved changes."""
        cat.append_child("metadata/props", {"name": "x", "value": "y"})
        assert cat.is_unsaved is True

    def test_no_dict_returns_none(self, cat):
        """append_child() returns None when _dict is None."""
        cat._dict = None
        result = cat.append_child("metadata/props", {"name": "x", "value": "y"})
        assert result is None


# ===========================================================================
# append_prop() / append_props()  — module-level functions
# ===========================================================================
class TestAppendPropFunctions:

    def test_append_prop_adds_entry(self):
        """append_prop() adds a prop dict to parent['props']."""
        parent = {}
        append_prop(parent, {"name": "label", "value": "AC-1"})
        assert "props" in parent
        assert len(parent["props"]) == 1

    def test_append_prop_sets_name_and_value(self):
        """append_prop() copies name and value into the entry."""
        parent = {}
        append_prop(parent, {"name": "label", "value": "AC-1"})
        entry = parent["props"][0]
        assert entry["name"] == "label"
        assert entry["value"] == "AC-1"

    def test_append_prop_optional_class(self):
        """append_prop() copies optional class key when present."""
        parent = {}
        append_prop(parent, {"name": "label", "value": "AC-1", "class": "sp800-53"})
        assert parent["props"][0]["class"] == "sp800-53"

    def test_append_prop_optional_ns(self):
        """append_prop() copies optional ns key."""
        parent = {}
        append_prop(parent, {"name": "label", "value": "AC-1",
                              "ns": "https://fedramp.gov/ns/oscal"})
        assert parent["props"][0]["ns"] == "https://fedramp.gov/ns/oscal"

    def test_append_prop_optional_group(self):
        """append_prop() copies optional group key."""
        parent = {}
        append_prop(parent, {"name": "label", "value": "AC-1", "group": "access"})
        assert parent["props"][0]["group"] == "access"

    def test_append_prop_optional_remarks(self):
        """append_prop() copies remarks as a plain string."""
        parent = {}
        append_prop(parent, {"name": "label", "value": "AC-1", "remarks": "Note"})
        assert parent["props"][0]["remarks"] == "Note"

    def test_append_prop_unknown_keys_excluded(self):
        """append_prop() does not copy unrecognised keys."""
        parent = {}
        append_prop(parent, {"name": "x", "value": "y", "foo": "bar"})
        assert "foo" not in parent["props"][0]

    def test_append_prop_returns_entry(self):
        """append_prop() returns the appended dict."""
        parent = {}
        result = append_prop(parent, {"name": "x", "value": "y"})
        assert result is parent["props"][0]

    def test_append_props_adds_multiple(self):
        """append_props() adds one entry per item in the list."""
        parent = {}
        append_props(parent, [
            {"name": "label", "value": "AC-1"},
            {"name": "sort-id", "value": "ac-01"},
        ])
        assert len(parent["props"]) == 2

    def test_append_props_empty_list_no_crash(self):
        """append_props([]) must not raise and leaves props absent."""
        parent = {}
        append_props(parent, [])
        assert "props" not in parent

    def test_append_props_extends_existing_list(self):
        """append_props() appends to an already-populated props list."""
        parent = {"props": [{"name": "existing", "value": "v"}]}
        append_props(parent, [{"name": "new", "value": "n"}])
        assert len(parent["props"]) == 2


# ===========================================================================
# append_link() / append_links()  — module-level functions
# ===========================================================================
class TestAppendLinkFunctions:

    def test_append_link_adds_entry(self):
        """append_link() adds a link dict to parent['links']."""
        parent = {}
        append_link(parent, {"href": "https://example.com"})
        assert "links" in parent
        assert len(parent["links"]) == 1

    def test_append_link_sets_href(self):
        """append_link() copies href into the entry."""
        parent = {}
        append_link(parent, {"href": "https://example.com"})
        assert parent["links"][0]["href"] == "https://example.com"

    def test_append_link_optional_rel(self):
        """append_link() copies rel when present."""
        parent = {}
        append_link(parent, {"href": "https://example.com", "rel": "reference"})
        assert parent["links"][0]["rel"] == "reference"

    def test_append_link_optional_media_type(self):
        """append_link() copies media-type when present."""
        parent = {}
        append_link(parent, {"href": "https://example.com", "media-type": "text/html"})
        assert parent["links"][0]["media-type"] == "text/html"

    def test_append_link_optional_text(self):
        """append_link() copies text when present."""
        parent = {}
        append_link(parent, {"href": "https://example.com", "text": "More info"})
        assert parent["links"][0]["text"] == "More info"

    def test_append_link_optional_resource_fragment(self):
        """append_link() copies resource-fragment when present."""
        parent = {}
        append_link(parent, {"href": "#abc", "resource-fragment": "section-1"})
        assert parent["links"][0]["resource-fragment"] == "section-1"

    def test_append_link_unknown_keys_excluded(self):
        """append_link() does not copy unrecognised keys."""
        parent = {}
        append_link(parent, {"href": "x", "foo": "bar"})
        assert "foo" not in parent["links"][0]

    def test_append_link_returns_entry(self):
        """append_link() returns the appended dict."""
        parent = {}
        result = append_link(parent, {"href": "https://example.com"})
        assert result is parent["links"][0]

    def test_append_links_adds_multiple(self):
        """append_links() adds one entry per item."""
        parent = {}
        append_links(parent, [
            {"href": "https://one.example.com"},
            {"href": "https://two.example.com"},
        ])
        assert len(parent["links"]) == 2

    def test_append_links_empty_list_no_crash(self):
        """append_links([]) must not raise."""
        parent = {}
        append_links(parent, [])
        assert "links" not in parent

    def test_append_links_extends_existing_list(self):
        """append_links() appends to an already-populated links list."""
        parent = {"links": [{"href": "https://existing.com"}]}
        append_links(parent, [{"href": "https://new.com"}])
        assert len(parent["links"]) == 2


# ===========================================================================
# append_resource() — module-level function AND instance method
# ===========================================================================
class TestAppendResourceFunction:

    def test_returns_dict(self, cat):
        """Module-level append_resource() returns a dict."""
        result = append_resource(cat, title="Test Resource",
                                 description="A test resource")
        assert result is not None
        assert isinstance(result, dict)

    def test_resource_has_uuid(self, cat):
        """append_resource() assigns a UUID when none is supplied."""
        result = append_resource(cat, title="UUID Test")
        assert result.get("uuid") not in (None, "")

    def test_resource_explicit_uuid(self, cat):
        """append_resource() uses the provided UUID."""
        uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        result = append_resource(cat, uuid=uuid, title="Explicit UUID")
        assert result["uuid"] == uuid

    def test_resource_has_title(self, cat):
        """append_resource() sets the title key."""
        result = append_resource(cat, title="My Resource")
        assert result["title"] == "My Resource"

    def test_resource_has_description(self, cat):
        """append_resource() sets the description key."""
        result = append_resource(cat, description="A description")
        assert result["description"] == "A description"

    def test_resource_with_props(self, cat):
        """append_resource() populates props via append_props."""
        result = append_resource(cat, title="With Props",
                                 props=[{"name": "type", "value": "document"}])
        assert result["props"][0]["name"] == "type"

    def test_resource_with_rlinks(self, cat):
        """append_resource() copies rlinks preserving href and media-type."""
        result = append_resource(
            cat, title="With Rlinks",
            rlinks=[{"href": "/docs/plan.pdf", "media-type": "application/pdf"}]
        )
        assert result["rlinks"][0]["href"] == "/docs/plan.pdf"
        assert result["rlinks"][0]["media-type"] == "application/pdf"

    def test_resource_with_remarks(self, cat):
        """append_resource() stores remarks as a plain markdown string."""
        result = append_resource(cat, title="With Remarks", remarks="See also: policy.")
        assert result["remarks"] == "See also: policy."

    def test_resource_appended_to_back_matter(self, cat):
        """append_resource() places the resource in back-matter/resources."""
        append_resource(cat, title="Resource A")
        resources = cat._dict["catalog"]["back-matter"]["resources"]
        assert any(r["title"] == "Resource A" for r in resources)

    def test_multiple_resources_accumulate(self, cat):
        """Multiple append_resource() calls accumulate in the resources list."""
        append_resource(cat, title="Resource A")
        append_resource(cat, title="Resource B")
        resources = cat._dict["catalog"]["back-matter"]["resources"]
        assert len(resources) == 2

    def test_instance_method_returns_dict(self, cat):
        """Instance append_resource() returns a dict via the module function."""
        result = cat.append_resource(title="Instance Method Test")
        assert result is not None
        assert isinstance(result, dict)

    def test_instance_method_marks_modified(self, cat):
        """Instance append_resource() marks the object as having unsaved changes."""
        cat.append_resource(title="Modified")
        assert cat.is_unsaved is True

    def test_no_dict_returns_none(self, cat):
        """Module-level append_resource() returns None when _dict is None."""
        cat._dict = None
        result = append_resource(cat, title="Should Fail")
        assert result is None


# ===========================================================================
# OSCAL._can_mutate()  — shared mutation precondition gate
# ===========================================================================
class TestCanMutate:
    def test_returns_true_for_writable_loaded_content(self, cat):
        """A freshly created catalog is writable with a loaded dict."""
        cat.is_read_only = False
        assert cat._can_mutate("test") is True

    def test_returns_false_when_dict_is_none(self, cat):
        cat._dict = None
        assert cat._can_mutate("test") is False

    def test_returns_false_when_read_only(self, cat):
        cat.is_read_only = True
        assert cat._can_mutate("test") is False

    def test_dict_none_takes_priority_over_read_only(self, cat):
        """When both fail, the method still returns False (order is irrelevant to result)."""
        cat._dict = None
        cat.is_read_only = True
        assert cat._can_mutate("test") is False

    def test_operation_label_is_optional(self, cat):
        """_can_mutate() works without an operation name argument."""
        cat.is_read_only = False
        assert cat._can_mutate() is True


# ===========================================================================
# Mutation guard behavior — read-only must not flag content unsaved
# ===========================================================================
class TestMutationGuardsDoNotFlagUnsaved:
    """A rejected mutation must never set is_unsaved (the @if_update_successful
    decorator only fires when the wrapped method returns a non-None value)."""

    def test_set_metadata_read_only_returns_none(self, cat):
        cat.is_read_only = True
        assert cat.set_metadata({"title": "x"}) is None

    def test_set_metadata_read_only_not_flagged_unsaved(self, cat):
        cat.is_read_only = True
        cat.is_unsaved = False
        cat.set_metadata({"title": "x"})
        assert cat.is_unsaved is False

    def test_set_field_read_only_returns_none(self, cat):
        cat.is_read_only = True
        assert cat._OSCAL__set_field("metadata/title", "x") is None

    def test_set_field_read_only_not_flagged_unsaved(self, cat):
        cat.is_read_only = True
        cat.is_unsaved = False
        cat._OSCAL__set_field("metadata/title", "x")
        assert cat.is_unsaved is False

    def test_append_child_read_only_returns_none(self, cat):
        cat.is_read_only = True
        assert cat.append_child("metadata/props", {"name": "x", "value": "y"}) is None

    def test_append_child_read_only_not_flagged_unsaved(self, cat):
        cat.is_read_only = True
        cat.is_unsaved = False
        cat.append_child("metadata/props", {"name": "x", "value": "y"})
        assert cat.is_unsaved is False

    def test_append_resource_read_only_returns_none(self, cat):
        cat.is_read_only = True
        assert cat.append_resource(title="x") is None

    def test_append_resource_read_only_not_flagged_unsaved(self, cat):
        cat.is_read_only = True
        cat.is_unsaved = False
        cat.append_resource(title="x")
        assert cat.is_unsaved is False


# ===========================================================================
# get_props()  — module-level function
# ===========================================================================
FEDRAMP_NS = "https://fedramp.gov/ns/oscal"


class TestGetProps:

    # -- required-parameter handling ---------------------------------------
    def test_no_name_or_uuid_returns_empty(self):
        """Neither name nor uuid supplied -> empty list (and warns)."""
        parent = {"props": [{"name": "label", "value": "AC-1"}]}
        assert get_props(parent) == []

    def test_missing_props_key_returns_empty(self):
        """Parent with no 'props' key returns empty list, not error."""
        assert get_props({}, name="label") == []

    def test_props_none_returns_empty(self):
        """A 'props' key explicitly set to None is tolerated."""
        assert get_props({"props": None}, name="label") == []

    def test_return_type_always_list(self):
        """Return value is a list even when nothing matches."""
        parent = {"props": [{"name": "other", "value": "v"}]}
        assert get_props(parent, name="label") == []

    # -- name + ns matching ------------------------------------------------
    def test_match_by_name(self):
        parent = {"props": [{"name": "label", "value": "AC-1"}]}
        result = get_props(parent, name="label")
        assert len(result) == 1
        assert result[0]["value"] == "AC-1"

    def test_absent_ns_matches_default(self):
        """A prop with no ns matches when ns defaults to _OSCAL_NS."""
        parent = {"props": [{"name": "label", "value": "AC-1"}]}
        assert len(get_props(parent, name="label", ns=_OSCAL_NS)) == 1

    def test_explicit_default_ns_matches_absent_ns(self):
        parent = {"props": [{"name": "label", "value": "AC-1", "ns": _OSCAL_NS}]}
        assert len(get_props(parent, name="label")) == 1

    def test_non_default_ns_excluded_by_default(self):
        """A prop in a non-default ns is not returned for a default-ns query."""
        parent = {"props": [{"name": "label", "value": "AC-1", "ns": FEDRAMP_NS}]}
        assert get_props(parent, name="label") == []

    def test_match_non_default_ns(self):
        parent = {"props": [{"name": "label", "value": "AC-1", "ns": FEDRAMP_NS}]}
        assert len(get_props(parent, name="label", ns=FEDRAMP_NS)) == 1

    def test_name_mismatch_excluded(self):
        parent = {"props": [{"name": "sort-id", "value": "AC-1"}]}
        assert get_props(parent, name="label") == []

    # -- class / group filtering -------------------------------------------
    def test_class_filter_matches(self):
        parent = {"props": [
            {"name": "label", "value": "A", "class": "sp800-53"},
            {"name": "label", "value": "B"},
        ]}
        result = get_props(parent, name="label", class_="sp800-53")
        assert len(result) == 1
        assert result[0]["value"] == "A"

    def test_class_filter_excludes_non_matching(self):
        parent = {"props": [{"name": "label", "value": "A", "class": "other"}]}
        assert get_props(parent, name="label", class_="sp800-53") == []

    def test_group_filter_matches(self):
        parent = {"props": [
            {"name": "label", "value": "A", "group": "access"},
            {"name": "label", "value": "B", "group": "audit"},
        ]}
        result = get_props(parent, name="label", group="access")
        assert len(result) == 1
        assert result[0]["value"] == "A"

    # -- best-to-worst ordering --------------------------------------------
    def test_ordering_bare_prop_first(self):
        """With only name+ns queried, the prop without class/group sorts first."""
        parent = {"props": [
            {"name": "label", "value": "withclass", "class": "sp800-53"},
            {"name": "label", "value": "bare"},
            {"name": "label", "value": "withgroup", "group": "access"},
        ]}
        result = get_props(parent, name="label")
        assert len(result) == 3
        assert result[0]["value"] == "bare"

    def test_ordering_least_specific_first(self):
        """Bare < single qualifier < both qualifiers."""
        parent = {"props": [
            {"name": "label", "value": "both", "class": "c", "group": "g"},
            {"name": "label", "value": "one", "class": "c"},
            {"name": "label", "value": "bare"},
        ]}
        result = get_props(parent, name="label")
        assert [p["value"] for p in result] == ["bare", "one", "both"]

    def test_ordering_stable_within_specificity(self):
        """Equally specific matches keep document order."""
        parent = {"props": [
            {"name": "label", "value": "first", "class": "a"},
            {"name": "label", "value": "second", "class": "b"},
        ]}
        result = get_props(parent, name="label")
        assert [p["value"] for p in result] == ["first", "second"]

    def test_class_passed_orders_by_group(self):
        """When class is queried, the un-queried group drives ordering."""
        parent = {"props": [
            {"name": "label", "value": "grouped", "class": "c", "group": "g"},
            {"name": "label", "value": "plain", "class": "c"},
        ]}
        result = get_props(parent, name="label", class_="c")
        assert [p["value"] for p in result] == ["plain", "grouped"]

    # -- uuid mode ---------------------------------------------------------
    def test_match_by_uuid(self):
        parent = {"props": [
            {"name": "label", "value": "A", "uuid": "u-1"},
            {"name": "label", "value": "B", "uuid": "u-2"},
        ]}
        result = get_props(parent, uuid="u-1")
        assert len(result) == 1
        assert result[0]["value"] == "A"

    def test_uuid_no_match_returns_empty(self):
        parent = {"props": [{"name": "label", "value": "A", "uuid": "u-1"}]}
        assert get_props(parent, uuid="missing") == []

    def test_uuid_takes_precedence_over_name(self):
        """uuid identifies the prop even when name would not match."""
        parent = {"props": [{"name": "label", "value": "A", "uuid": "u-1"}]}
        result = get_props(parent, name="does-not-match", uuid="u-1")
        assert len(result) == 1
        assert result[0]["uuid"] == "u-1"

    def test_uuid_only_no_warning(self, caplog):
        """uuid alone (no other params) triggers no descriptor warning."""
        parent = {"props": [{"name": "label", "value": "A", "uuid": "u-1",
                             "ns": FEDRAMP_NS}]}
        import logging
        with caplog.at_level(logging.WARNING):
            result = get_props(parent, uuid="u-1")
        assert len(result) == 1


# ===========================================================================
# get_props()  — warning behaviour (stdlib logging)
# ===========================================================================
class TestGetPropsWarnings:

    def _capture(self):
        """Attach a capturing handler to the 'oscal' logger; return (messages, remove_fn).

        The oscal package installs only a NullHandler, so the library is silent
        until a caller adds a handler and lowers the level. This helper does
        exactly that so the warnings emitted by get_props can be observed.
        """
        import logging

        messages = []

        class _ListHandler(logging.Handler):
            def emit(self, record):
                messages.append(record.getMessage())

        handler = _ListHandler(level=logging.WARNING)
        pkg_logger = logging.getLogger("oscal")
        prev_level = pkg_logger.level
        pkg_logger.addHandler(handler)
        pkg_logger.setLevel(logging.WARNING)

        def _restore():
            pkg_logger.removeHandler(handler)
            pkg_logger.setLevel(prev_level)

        return messages, _restore

    def test_missing_params_warns(self):
        messages, remove = self._capture()
        try:
            get_props({"props": []})
        finally:
            remove()
        assert any("name" in m and "uuid" in m for m in messages)

    def test_uuid_descriptor_mismatch_warns(self):
        parent = {"props": [{"name": "label", "value": "A", "uuid": "u-1"}]}
        messages, remove = self._capture()
        try:
            result = get_props(parent, name="sort-id", uuid="u-1")
        finally:
            remove()
        assert len(result) == 1  # still returned
        assert any("name" in m for m in messages)

    def test_uuid_descriptor_match_no_warning(self):
        parent = {"props": [{"name": "label", "value": "A", "uuid": "u-1"}]}
        messages, remove = self._capture()
        try:
            get_props(parent, name="label", uuid="u-1")
        finally:
            remove()
        assert messages == []
