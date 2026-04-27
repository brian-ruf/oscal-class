"""
Unit tests for OSCAL content write methods (OSCAL base class and module functions):
    - OSCAL.set_metadata()
    - OSCAL.append_child()
    - OSCAL.assign_html_string_to_node()
    - OSCAL.append_resource()  (instance method)
    - append_prop() / append_props()  (module functions)
    - append_link() / append_links()  (module functions)
    - append_resource()               (module function)
"""
from xml.etree import ElementTree

import pytest

from oscal import Catalog
from oscal.oscal_content import (
    append_link,
    append_links,
    append_prop,
    append_props,
    append_resource,
)


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def cat():
    """Fresh writable catalog for each test."""
    return Catalog.new("Write Test Catalog")


# ===========================================================================
# OSCAL.set_metadata()
# ===========================================================================
class TestSetMetadata:

    def test_set_title(self, cat):
        """set_metadata() updates the title in the XML tree."""
        cat.set_metadata({"title": "Updated Title"})
        # title is cached on load; verify via XPath into the tree
        result = cat.xpath_atomic("/*/metadata/title/text()")
        assert result == "Updated Title"

    def test_set_version(self, cat):
        """set_metadata() updates the version in the XML tree."""
        cat.set_metadata({"version": "2.0"})
        result = cat.xpath_atomic("/*/metadata/version/text()")
        assert result == "2.0"

    def test_set_multiple_fields(self, cat):
        """set_metadata() can set several scalar fields in one call."""
        cat.set_metadata({"title": "Multi Field", "version": "3.0"})
        assert cat.xpath_atomic("/*/metadata/title/text()") == "Multi Field"
        assert cat.xpath_atomic("/*/metadata/version/text()") == "3.0"

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

    def test_returns_element(self, cat):
        """append_child() returns an Element on success."""
        result = cat.append_child("/*/metadata", "remarks", "Test remark")
        assert result is not None
        assert isinstance(result, ElementTree.Element)

    def test_child_has_correct_tag(self, cat):
        """append_child() creates a node with the requested tag."""
        result = cat.append_child("/*/metadata", "remarks", "Hello")
        assert "remarks" in result.tag

    def test_child_has_content(self, cat):
        """append_child() sets text content when node_content is provided."""
        result = cat.append_child("/*/metadata", "remarks", "My remarks")
        assert result.text == "My remarks"

    def test_child_with_attributes(self, cat):
        """append_child() applies attribute_list entries to the new element."""
        result = cat.append_child("/*/metadata", "link",
                                  attribute_list={"href": "https://example.com", "rel": "reference"})
        assert result is not None
        assert result.get("href") == "https://example.com"
        assert result.get("rel") == "reference"

    def test_bad_xpath_returns_none(self, cat):
        """append_child() returns None when the parent XPath has no match."""
        result = cat.append_child("//nonexistent-parent-xyz", "remarks")
        assert result is None

    def test_marks_content_modified(self, cat):
        """append_child() marks the object as having unsaved changes."""
        cat.append_child("/*/metadata", "remarks", "test")
        assert cat.is_unsaved is True


# ===========================================================================
# OSCAL.assign_html_string_to_node()
# ===========================================================================
class TestAssignHtmlStringToNode:

    def test_plain_text_assigned(self, cat):
        """assign_html_string_to_node() puts plain text into the node."""
        node = ElementTree.Element("remarks")
        cat.assign_html_string_to_node(node, "Simple text")
        assert node.text == "Simple text"

    def test_html_tag_appended_as_child(self, cat):
        """assign_html_string_to_node() appends HTML elements as children."""
        node = ElementTree.Element("remarks")
        cat.assign_html_string_to_node(node, "<p>Hello</p>")
        children = list(node)
        assert len(children) > 0
        assert children[0].tag == "p"

    def test_multiple_html_elements(self, cat):
        """assign_html_string_to_node() handles multiple child elements."""
        node = ElementTree.Element("remarks")
        cat.assign_html_string_to_node(node, "<p>First</p><p>Second</p>")
        children = list(node)
        assert len(children) == 2

    def test_malformed_html_does_not_raise(self, cat):
        """assign_html_string_to_node() should not raise on broken HTML."""
        node = ElementTree.Element("remarks")
        try:
            cat.assign_html_string_to_node(node, "<p>Unclosed")
        except Exception:
            pytest.fail("assign_html_string_to_node raised on malformed HTML")


# ===========================================================================
# append_prop() / append_props()  — module-level functions
# ===========================================================================
class TestAppendPropFunctions:

    def test_append_prop_adds_child(self):
        """append_prop() adds a <prop> child to the parent element."""
        parent = ElementTree.Element("control")
        append_prop(parent, {"name": "label", "value": "AC-1"})
        children = list(parent)
        assert len(children) == 1
        assert "prop" in children[0].tag

    def test_append_prop_sets_name_and_value(self):
        """append_prop() sets name and value attributes."""
        parent = ElementTree.Element("control")
        append_prop(parent, {"name": "label", "value": "AC-1"})
        prop = list(parent)[0]
        assert prop.get("name") == "label"
        assert prop.get("value") == "AC-1"

    def test_append_prop_optional_class(self):
        """append_prop() sets optional class attribute when present."""
        parent = ElementTree.Element("control")
        append_prop(parent, {"name": "label", "value": "AC-1", "class": "sp800-53"})
        prop = list(parent)[0]
        assert prop.get("class") == "sp800-53"

    def test_append_prop_optional_ns(self):
        """append_prop() sets optional ns attribute."""
        parent = ElementTree.Element("control")
        append_prop(parent, {"name": "label", "value": "AC-1",
                              "ns": "https://fedramp.gov/ns/oscal"})
        prop = list(parent)[0]
        assert prop.get("ns") == "https://fedramp.gov/ns/oscal"

    def test_append_props_adds_multiple(self):
        """append_props() adds one <prop> per entry in the list."""
        parent = ElementTree.Element("control")
        append_props(parent, [
            {"name": "label", "value": "AC-1"},
            {"name": "sort-id", "value": "ac-01"},
        ])
        assert len(list(parent)) == 2

    def test_append_props_empty_list_no_crash(self):
        """append_props([]) must not raise."""
        parent = ElementTree.Element("control")
        append_props(parent, [])
        assert len(list(parent)) == 0


# ===========================================================================
# append_link() / append_links()  — module-level functions
# ===========================================================================
class TestAppendLinkFunctions:

    def test_append_link_adds_child(self):
        """append_link() adds a <link> child to the parent element."""
        parent = ElementTree.Element("control")
        append_link(parent, {"href": "https://example.com"})
        children = list(parent)
        assert len(children) == 1
        assert "link" in children[0].tag

    def test_append_link_sets_href(self):
        """append_link() sets the href attribute."""
        parent = ElementTree.Element("control")
        append_link(parent, {"href": "https://example.com"})
        link = list(parent)[0]
        assert link.get("href") == "https://example.com"

    def test_append_link_optional_rel(self):
        """append_link() sets rel attribute when present."""
        parent = ElementTree.Element("control")
        append_link(parent, {"href": "https://example.com", "rel": "reference"})
        link = list(parent)[0]
        assert link.get("rel") == "reference"

    def test_append_link_optional_text(self):
        """append_link() adds a <text> child when text is provided."""
        parent = ElementTree.Element("control")
        append_link(parent, {"href": "https://example.com", "text": "More info"})
        link = list(parent)[0]
        text_children = [c for c in link if "text" in c.tag]
        assert len(text_children) == 1
        assert text_children[0].text == "More info"

    def test_append_links_adds_multiple(self):
        """append_links() adds one <link> per entry."""
        parent = ElementTree.Element("control")
        append_links(parent, [
            {"href": "https://one.example.com"},
            {"href": "https://two.example.com"},
        ])
        assert len(list(parent)) == 2

    def test_append_links_empty_list_no_crash(self):
        """append_links([]) must not raise."""
        parent = ElementTree.Element("control")
        append_links(parent, [])
        assert len(list(parent)) == 0


# ===========================================================================
# append_resource() — module-level function AND instance method
# ===========================================================================
class TestAppendResourceFunction:

    def test_returns_element(self, cat):
        """Module-level append_resource() returns an Element."""
        result = append_resource(cat, title="Test Resource",
                                 description="A test resource")
        assert result is not None
        assert isinstance(result, ElementTree.Element)

    def test_resource_has_uuid(self, cat):
        """append_resource() assigns a UUID to the resource element."""
        result = append_resource(cat, title="UUID Test")
        assert result.get("uuid") != ""

    def test_resource_explicit_uuid(self, cat):
        """append_resource() uses the provided UUID when given."""
        uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        result = append_resource(cat, uuid=uuid, title="Explicit UUID")
        assert result.get("uuid") == uuid

    def test_resource_has_title(self, cat):
        """append_resource() includes a <title> child."""
        result = append_resource(cat, title="My Resource")
        title_nodes = [c for c in result if "title" in c.tag]
        assert len(title_nodes) == 1
        assert title_nodes[0].text == "My Resource"

    def test_resource_has_description(self, cat):
        """append_resource() includes a <description> child."""
        result = append_resource(cat, description="A description")
        desc_nodes = [c for c in result if "description" in c.tag]
        assert len(desc_nodes) == 1

    def test_instance_method_delegates_to_module_fn(self, cat):
        """Instance append_resource() produces an Element via the module function."""
        result = cat.append_resource(title="Instance Method Test")
        assert result is not None
        assert isinstance(result, ElementTree.Element)

    def test_resource_with_props(self, cat):
        """append_resource() adds <prop> children from the props list."""
        result = append_resource(cat, title="With Props",
                                 props=[{"name": "type", "value": "document"}])
        prop_nodes = [c for c in result if "prop" in c.tag]
        assert len(prop_nodes) == 1
        assert prop_nodes[0].get("name") == "type"
