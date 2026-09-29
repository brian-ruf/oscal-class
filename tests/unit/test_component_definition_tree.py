"""
Unit tests for ComponentDefinition.implementation_tree — a UI-oriented view of a
component definition. Its ``components`` key is a flat list of the definition's
components and capabilities (aligning with SSP.implementation_tree['components']).

Each node is ``{"uuid", "title", "type", "asset-type", "incorporates"}``:
    * components   -> type is the component's ``type`` flag, title is ``title``.
    * capabilities -> type is the literal ``"capability"``, title is ``name``.
    * ``asset-type`` is the value of the OSCAL-default-namespace ``asset-type`` prop
      when present (checked on components and capabilities), else "".
    * ``incorporates`` lists ``{"uuid", "description"}`` from an
      ``incorporates-components`` collection (checked on components and capabilities),
      else [].
    * Imported component definitions' nodes are appended flat (no nesting).

Also covers the component()/capability() getters, which return safe copies annotated
with: incorporates-components resolution (found + title/type/asset-type),
responsible-roles (role title + party names), and — for component() — a relationships
object holding forward relationship links plus the reverse relationships discovered by
scanning every component in scope (across the import tree).
"""
import json
import os
import tempfile

import pytest

from oscal.oscal_implementation import ComponentDefinition

_NODE_KEYS = {"uuid", "title", "type", "asset-type", "incorporates"}


# ---------------------------------------------------------------------------
def _cdef_doc(uuid, title, components=None, capabilities=None, imports=None):
    """A minimal, schema-valid component-definition dict."""
    root = {
        "uuid": uuid,
        "metadata": {
            "title": title,
            "last-modified": "2026-01-01T00:00:00Z",
            "version": "1.0",
            "oscal-version": "1.1.3",
        },
    }
    if imports:
        root["import-component-definitions"] = imports
    if components:
        root["components"] = components
    if capabilities:
        root["capabilities"] = capabilities
    return {"component-definition": root}


def _load(doc):
    return ComponentDefinition.loads(json.dumps(doc))


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def valid_cdef():
    """A valid cDef with two components (one with an asset-type prop) and a
    capability that incorporates a component."""
    doc = _cdef_doc(
        "11111111-1111-4111-8111-111111111111", "Test cDef",
        components=[
            {"uuid": "aaaaaaaa-0000-4000-8000-000000000001", "type": "software",
             "title": "Web Server", "description": "x",
             "props": [{"name": "asset-type", "value": "appliance"}]},
            {"uuid": "aaaaaaaa-0000-4000-8000-000000000002", "type": "hardware",
             "title": "Router", "description": "y"},
        ],
        capabilities=[
            {"uuid": "cccccccc-0000-4000-8000-000000000001", "name": "Logging",
             "description": "z",
             "incorporates-components": [
                 {"component-uuid": "aaaaaaaa-0000-4000-8000-000000000002",
                  "description": "uses router"},
             ]},
        ],
    )
    return _load(doc)


# ===========================================================================
# Attribute existence / initial state
# ===========================================================================
class TestAttribute:

    def test_attribute_always_present(self):
        """Even invalid content exposes implementation_tree with a components list."""
        cd = _load({"component-definition": {"uuid": "not-a-uuid"}})
        assert hasattr(cd, "implementation_tree")
        assert isinstance(cd.implementation_tree, dict)
        assert isinstance(cd.implementation_tree["components"], list)

    def test_components_key_aligns_with_ssp(self):
        """The only top-level key is ``components`` — SSP adds the others."""
        cd = _load({"component-definition": {"uuid": "not-a-uuid"}})
        assert set(cd.implementation_tree.keys()) == {"components"}

    def test_built_on_valid_load(self, valid_cdef):
        assert valid_cdef.is_valid
        assert len(valid_cdef.implementation_tree["components"]) == 3


# ===========================================================================
# Node structure and value mapping
# ===========================================================================
class TestNodeShape:

    def test_node_keys(self, valid_cdef):
        for node in valid_cdef.implementation_tree["components"]:
            assert set(node.keys()) == _NODE_KEYS

    def test_component_node_values(self, valid_cdef):
        node = valid_cdef.implementation_tree["components"][0]
        assert node["uuid"] == "aaaaaaaa-0000-4000-8000-000000000001"
        assert node["title"] == "Web Server"
        assert node["type"] == "software"
        assert node["asset-type"] == "appliance"
        assert node["incorporates"] == []

    def test_asset_type_absent_defaults_empty(self, valid_cdef):
        router = valid_cdef.implementation_tree["components"][1]
        assert router["asset-type"] == ""

    def test_capability_node_values(self, valid_cdef):
        cap = valid_cdef.implementation_tree["components"][2]
        # A capability's type is the literal "capability"; its title is its name.
        assert cap["type"] == "capability"
        assert cap["title"] == "Logging"
        assert cap["uuid"] == "cccccccc-0000-4000-8000-000000000001"

    def test_capability_incorporates(self, valid_cdef):
        cap = valid_cdef.implementation_tree["components"][2]
        assert cap["incorporates"] == [
            {"uuid": "aaaaaaaa-0000-4000-8000-000000000002",
             "description": "uses router"},
        ]

    def test_flat_no_children_key(self, valid_cdef):
        """The tree is flat: nodes carry no 'children' key."""
        for node in valid_cdef.implementation_tree["components"]:
            assert "children" not in node


# ===========================================================================
# Proposed / not-yet-schema-valid fields exercised on the node builder directly
# (asset-type on a capability; incorporates-components on a component). These are
# built for forward-compatibility, so they cannot appear in schema-valid content.
# ===========================================================================
class TestProposedFields:

    def test_asset_type_on_capability(self, valid_cdef):
        cap = {"uuid": "c1", "name": "Cap",
               "props": [{"name": "asset-type", "value": "service"}]}
        node = valid_cdef._component_node(cap, cap["name"], "capability")
        assert node["asset-type"] == "service"

    def test_incorporates_on_component(self, valid_cdef):
        comp = {"uuid": "u1", "type": "hardware", "title": "Sensor",
                "incorporates-components": [
                    {"component-uuid": "u2", "description": "d"}]}
        node = valid_cdef._component_node(comp, comp["title"], comp["type"])
        assert node["incorporates"] == [{"uuid": "u2", "description": "d"}]


# ===========================================================================
# Boundary / invalid conditions
# ===========================================================================
class TestBoundary:

    def test_no_components_or_capabilities(self):
        cd = _load(_cdef_doc("22222222-2222-4222-8222-222222222222", "Empty"))
        assert cd.is_valid
        assert cd.implementation_tree["components"] == []

    def test_incorporates_missing_fields_default_empty(self, valid_cdef):
        comp = {"uuid": "u1", "type": "software", "title": "T",
                "incorporates-components": [{}]}
        node = valid_cdef._component_node(comp, comp["title"], comp["type"])
        assert node["incorporates"] == [{"uuid": "", "description": ""}]

    def test_invalid_content_empty_tree(self):
        cd = _load({"component-definition": {"uuid": "not-a-uuid"}})
        assert not cd.is_valid
        assert cd.implementation_tree["components"] == []


# ===========================================================================
# Imported component definitions are merged flat
# ===========================================================================
class TestImportFlatMerge:

    def test_imported_nodes_appended_flat(self):
        with tempfile.TemporaryDirectory() as d:
            child = _cdef_doc(
                "33333333-3333-4333-8333-333333333333", "Child",
                components=[{"uuid": "bbbbbbbb-0000-4000-8000-000000000001",
                             "type": "service", "title": "Auth Service",
                             "description": "child"}],
            )
            with open(os.path.join(d, "child.json"), "w") as fh:
                json.dump(child, fh)

            parent = _cdef_doc(
                "44444444-4444-4444-8444-444444444444", "Parent",
                components=[{"uuid": "dddddddd-0000-4000-8000-000000000001",
                             "type": "software", "title": "App",
                             "description": "parent"}],
                imports=[{"href": "child.json"}],
            )
            parent_path = os.path.join(d, "parent.json")
            with open(parent_path, "w") as fh:
                json.dump(parent, fh)

            cd = ComponentDefinition.load(parent_path)
            assert cd.is_valid
            titles = [n["title"] for n in cd.implementation_tree["components"]]
            # Own component first, then the imported child's component — flat.
            assert titles == ["App", "Auth Service"]
            for node in cd.implementation_tree["components"]:
                assert set(node.keys()) == _NODE_KEYS


# ===========================================================================
# component() / capability() getters (incorporates resolved against tree)
# ===========================================================================
@pytest.fixture
def cdef_with_incorporates():
    """A capability that incorporates one existing component and one missing uuid."""
    doc = _cdef_doc(
        "55555555-5555-4555-8555-555555555555", "cDef",
        components=[
            {"uuid": "aaaaaaaa-0000-4000-8000-000000000001", "type": "software",
             "title": "Web Server", "description": "x",
             "props": [{"name": "asset-type", "value": "appliance"}]},
            {"uuid": "aaaaaaaa-0000-4000-8000-000000000002", "type": "hardware",
             "title": "Router", "description": "y"},
        ],
        capabilities=[
            {"uuid": "cccccccc-0000-4000-8000-000000000001", "name": "Logging",
             "description": "z",
             "incorporates-components": [
                 {"component-uuid": "aaaaaaaa-0000-4000-8000-000000000001",
                  "description": "found web"},
                 {"component-uuid": "deadbeef-0000-4000-8000-000000000000",
                  "description": "missing one"},
             ]},
        ],
    )
    return _load(doc)


class TestGetters:

    def test_component_by_uuid(self, cdef_with_incorporates):
        comp = cdef_with_incorporates.component("aaaaaaaa-0000-4000-8000-000000000001")
        assert comp is not None
        assert comp["title"] == "Web Server"
        assert comp["type"] == "software"

    def test_capability_by_uuid(self, cdef_with_incorporates):
        cap = cdef_with_incorporates.capability("cccccccc-0000-4000-8000-000000000001")
        assert cap is not None
        assert cap["name"] == "Logging"

    def test_missing_uuid_returns_none(self, cdef_with_incorporates):
        assert cdef_with_incorporates.component("nope") is None
        assert cdef_with_incorporates.capability("nope") is None

    def test_component_getter_does_not_return_capability(self, cdef_with_incorporates):
        # A capability uuid is not a component, and vice versa.
        assert cdef_with_incorporates.component("cccccccc-0000-4000-8000-000000000001") is None
        assert cdef_with_incorporates.capability("aaaaaaaa-0000-4000-8000-000000000001") is None

    def test_incorporates_found_entry_enriched(self, cdef_with_incorporates):
        cap = cdef_with_incorporates.capability("cccccccc-0000-4000-8000-000000000001")
        found = cap["incorporates-components"][0]
        assert found["found"] is True
        assert found["title"] == "Web Server"
        assert found["type"] == "software"
        assert found["asset-type"] == "appliance"
        # uuid and description left as-is.
        assert found["component-uuid"] == "aaaaaaaa-0000-4000-8000-000000000001"
        assert found["description"] == "found web"

    def test_incorporates_missing_entry_marked_not_found(self, cdef_with_incorporates):
        cap = cdef_with_incorporates.capability("cccccccc-0000-4000-8000-000000000001")
        missing = cap["incorporates-components"][1]
        assert missing["found"] is False
        # No enrichment keys added; uuid/description untouched.
        assert "title" not in missing
        assert "type" not in missing
        assert "asset-type" not in missing
        assert missing["component-uuid"] == "deadbeef-0000-4000-8000-000000000000"
        assert missing["description"] == "missing one"

    def test_component_without_incorporates_unaffected(self, cdef_with_incorporates):
        comp = cdef_with_incorporates.component("aaaaaaaa-0000-4000-8000-000000000002")
        assert "incorporates-components" not in comp

    def test_getter_returns_safe_copy(self, cdef_with_incorporates):
        comp = cdef_with_incorporates.component("aaaaaaaa-0000-4000-8000-000000000002")
        comp["title"] = "MUTATED"
        again = cdef_with_incorporates.component("aaaaaaaa-0000-4000-8000-000000000002")
        assert again["title"] == "Router"

    def test_incorporates_resolves_across_import(self):
        """A parent capability incorporating an imported component resolves via the
        flat implementation_tree['components'] (which includes imported nodes)."""
        with tempfile.TemporaryDirectory() as d:
            child = _cdef_doc(
                "66666666-6666-4666-8666-666666666666", "Child",
                components=[{"uuid": "bbbbbbbb-0000-4000-8000-000000000001",
                             "type": "service", "title": "Auth Service",
                             "description": "child",
                             "props": [{"name": "asset-type", "value": "saas"}]}],
            )
            with open(os.path.join(d, "child.json"), "w") as fh:
                json.dump(child, fh)
            parent = _cdef_doc(
                "77777777-7777-4777-8777-777777777777", "Parent",
                capabilities=[{"uuid": "eeeeeeee-0000-4000-8000-000000000001",
                               "name": "Uses Auth", "description": "p",
                               "incorporates-components": [
                                   {"component-uuid": "bbbbbbbb-0000-4000-8000-000000000001",
                                    "description": "imported ref"}]}],
                imports=[{"href": "child.json"}],
            )
            parent_path = os.path.join(d, "parent.json")
            with open(parent_path, "w") as fh:
                json.dump(parent, fh)

            cd = ComponentDefinition.load(parent_path)
            cap = cd.capability("eeeeeeee-0000-4000-8000-000000000001")
            entry = cap["incorporates-components"][0]
            assert entry["found"] is True
            assert entry["title"] == "Auth Service"
            assert entry["type"] == "service"
            assert entry["asset-type"] == "saas"


# ===========================================================================
# component() responsible-roles enrichment (role title + party names)
# ===========================================================================
_P1 = "eeeeeeee-0000-4000-8000-000000000001"  # person Alice
_P2 = "eeeeeeee-0000-4000-8000-000000000002"  # org Acme


@pytest.fixture
def cdef_with_roles():
    doc = {"component-definition": {
        "uuid": "88888888-8888-4888-8888-888888888888",
        "metadata": {
            "title": "cDef", "last-modified": "2026-01-01T00:00:00Z",
            "version": "1.0", "oscal-version": "1.1.3",
            "roles": [{"id": "admin", "title": "Administrator"},
                      {"id": "owner", "title": "System Owner"}],
            "parties": [{"uuid": _P1, "type": "person", "name": "Alice"},
                        {"uuid": _P2, "type": "organization", "name": "Acme"}],
        },
        "components": [
            {"uuid": "aaaaaaaa-0000-4000-8000-000000000001", "type": "software",
             "title": "Web Server", "description": "x",
             "responsible-roles": [
                 {"role-id": "admin", "party-uuids": [_P1, _P2]},
                 {"role-id": "owner"},          # no party-uuids
                 {"role-id": "ghost"},          # role not defined in metadata
             ]},
            {"uuid": "aaaaaaaa-0000-4000-8000-000000000002", "type": "hardware",
             "title": "Router", "description": "y"},   # no responsible-roles
        ],
    }}
    return _load(doc)


class TestResponsibleRoles:

    def test_role_title_inserted(self, cdef_with_roles):
        comp = cdef_with_roles.component("aaaaaaaa-0000-4000-8000-000000000001")
        roles = comp["responsible-roles"]
        assert roles[0]["title"] == "Administrator"
        assert roles[1]["title"] == "System Owner"

    def test_parties_array_resolved(self, cdef_with_roles):
        comp = cdef_with_roles.component("aaaaaaaa-0000-4000-8000-000000000001")
        assert comp["responsible-roles"][0]["parties"] == [
            {"uuid": _P1, "name": "Alice"},
            {"uuid": _P2, "name": "Acme"},
        ]

    def test_no_party_uuids_no_parties_key(self, cdef_with_roles):
        comp = cdef_with_roles.component("aaaaaaaa-0000-4000-8000-000000000001")
        assert "parties" not in comp["responsible-roles"][1]

    def test_unknown_role_id_empty_title(self, cdef_with_roles):
        comp = cdef_with_roles.component("aaaaaaaa-0000-4000-8000-000000000001")
        assert comp["responsible-roles"][2]["title"] == ""

    def test_component_without_responsible_roles_unaffected(self, cdef_with_roles):
        comp = cdef_with_roles.component("aaaaaaaa-0000-4000-8000-000000000002")
        assert "responsible-roles" not in comp

    def test_enrichment_does_not_mutate_stored(self, cdef_with_roles):
        cdef_with_roles.component("aaaaaaaa-0000-4000-8000-000000000001")
        stored = cdef_with_roles._dict["component-definition"]["components"][0]
        assert "title" not in stored["responsible-roles"][0]
        assert "parties" not in stored["responsible-roles"][0]


# ===========================================================================
# component() relationships (forward + reverse component<->component links)
# ===========================================================================
_RU1 = "aaaaaaaa-0000-4000-8000-000000000001"  # the component under test (has links)
_RU2 = "aaaaaaaa-0000-4000-8000-000000000002"  # target (has asset-type)
_RU3 = "aaaaaaaa-0000-4000-8000-000000000003"  # target (no asset-type)
_RISO = "aaaaaaaa-0000-4000-8000-0000000000f0"  # isolated: no links, never cited
_RGHOST = "ffffffff-0000-4000-8000-000000000000"  # not in the tree

# Every array key emitted under relationships: forward rels + reverse keys.
_REL_KEYS = {"depends-on", "validation", "uses-service", "uses-network", "provided-by",
             "used-by", "dependents", "validates", "provides", "uses"}


@pytest.fixture
def cdef_with_links():
    doc = _cdef_doc(
        "99999999-9999-4999-8999-999999999999", "cDef",
        components=[
            {"uuid": _RU1, "type": "software", "title": "App", "description": "x",
             "links": [
                 {"href": "#" + _RU2, "rel": "depends-on"},
                 {"href": "#" + _RU3, "rel": "uses-service"},
                 {"href": "#" + _RGHOST, "rel": "depends-on"},
                 {"href": "https://example.com", "rel": "reference"},   # not a relationship rel
                 {"href": "#" + _RU2, "rel": "validation"},
                 {"href": "#" + _RU3, "rel": "provided-by"},
                 {"href": "#" + _RU2, "rel": "used-by"},
             ]},
            {"uuid": _RU2, "type": "validation", "title": "Validator", "description": "y",
             "props": [{"name": "asset-type", "value": "scanner"}]},
            {"uuid": _RU3, "type": "service", "title": "DB", "description": "z"},
            {"uuid": _RISO, "type": "software", "title": "Alone", "description": "i"},
        ],
    )
    return _load(doc)


class TestRelationshipsForward:

    def test_all_relationship_keys_present(self, cdef_with_links):
        rels = cdef_with_links.component(_RU1)["relationships"]
        assert set(rels.keys()) == _REL_KEYS

    def test_unused_rel_is_empty_array(self, cdef_with_links):
        assert cdef_with_links.component(_RU1)["relationships"]["uses-network"] == []

    def test_resolved_entry_with_asset_type(self, cdef_with_links):
        rels = cdef_with_links.component(_RU1)["relationships"]
        assert rels["validation"] == [
            {"uuid": _RU2, "title": "Validator", "type": "validation", "asset-type": "scanner"}]

    def test_resolved_entry_without_asset_type_omits_key(self, cdef_with_links):
        entry = cdef_with_links.component(_RU1)["relationships"]["uses-service"][0]
        assert entry == {"uuid": _RU3, "title": "DB", "type": "service"}
        assert "asset-type" not in entry

    def test_unresolved_reference_still_listed(self, cdef_with_links):
        depends = cdef_with_links.component(_RU1)["relationships"]["depends-on"]
        assert {"uuid": _RGHOST, "title": "", "type": ""} in depends
        assert len(depends) == 2

    def test_new_forward_rel_types(self, cdef_with_links):
        rels = cdef_with_links.component(_RU1)["relationships"]
        assert [e["uuid"] for e in rels["provided-by"]] == [_RU3]
        assert [e["uuid"] for e in rels["used-by"]] == [_RU2]

    def test_non_relationship_rel_ignored(self, cdef_with_links):
        rels = cdef_with_links.component(_RU1)["relationships"]
        all_uuids = [e["uuid"] for arr in rels.values() for e in arr]
        assert "https://example.com" not in all_uuids

    def test_isolated_component_all_empty(self, cdef_with_links):
        rels = cdef_with_links.component(_RISO)["relationships"]
        assert all(rels[k] == [] for k in rels)

    def test_forward_resolves_across_import(self):
        """A forward relationship link to an imported component resolves via the tree."""
        with tempfile.TemporaryDirectory() as d:
            child = _cdef_doc(
                "12121212-1212-4212-8212-121212121212", "Child",
                components=[{"uuid": _RU3, "type": "service", "title": "Imported DB",
                             "description": "c",
                             "props": [{"name": "asset-type", "value": "saas"}]}],
            )
            with open(os.path.join(d, "child.json"), "w") as fh:
                json.dump(child, fh)
            parent = _cdef_doc(
                "13131313-1313-4313-8313-131313131313", "Parent",
                components=[{"uuid": _RU1, "type": "software", "title": "App",
                             "description": "x",
                             "links": [{"href": "#" + _RU3, "rel": "uses-service"}]}],
                imports=[{"href": "child.json"}],
            )
            parent_path = os.path.join(d, "parent.json")
            with open(parent_path, "w") as fh:
                json.dump(parent, fh)
            cd = ComponentDefinition.load(parent_path)
            entry = cd.component(_RU1)["relationships"]["uses-service"][0]
            assert entry == {"uuid": _RU3, "title": "Imported DB", "type": "service",
                             "asset-type": "saas"}


class TestRelationshipsReverse:

    def test_depends_on_reverses_to_dependents(self, cdef_with_links):
        # _RU1 depends-on _RU2  =>  _RU2.dependents contains _RU1.
        rels = cdef_with_links.component(_RU2)["relationships"]
        assert rels["dependents"] == [{"uuid": _RU1, "title": "App", "type": "software"}]

    def test_validation_reverses_to_validates(self, cdef_with_links):
        rels = cdef_with_links.component(_RU2)["relationships"]
        assert rels["validates"] == [{"uuid": _RU1, "title": "App", "type": "software"}]

    def test_uses_service_reverses_to_used_by(self, cdef_with_links):
        # _RU1 uses-service _RU3  =>  _RU3.used-by contains _RU1.
        rels = cdef_with_links.component(_RU3)["relationships"]
        assert {"uuid": _RU1, "title": "App", "type": "software"} in rels["used-by"]

    def test_provided_by_reverses_to_provides(self, cdef_with_links):
        # _RU1 provided-by _RU3  =>  _RU3.provides contains _RU1.
        rels = cdef_with_links.component(_RU3)["relationships"]
        assert rels["provides"] == [{"uuid": _RU1, "title": "App", "type": "software"}]

    def test_used_by_reverses_to_uses(self, cdef_with_links):
        # _RU1 used-by _RU2  =>  _RU2.uses contains _RU1.
        rels = cdef_with_links.component(_RU2)["relationships"]
        assert rels["uses"] == [{"uuid": _RU1, "title": "App", "type": "software"}]

    def test_reverse_discovers_across_import(self):
        """A reverse relationship is found even when the citing component is imported."""
        target = "aaaaaaaa-0000-4000-8000-0000000000a0"
        citer = "bbbbbbbb-0000-4000-8000-0000000000b0"
        with tempfile.TemporaryDirectory() as d:
            child = _cdef_doc(
                "14141414-1414-4414-8414-141414141414", "Child",
                components=[{"uuid": citer, "type": "service", "title": "Citer",
                             "description": "c",
                             "links": [{"href": "#" + target, "rel": "depends-on"}]}],
            )
            with open(os.path.join(d, "child.json"), "w") as fh:
                json.dump(child, fh)
            parent = _cdef_doc(
                "15151515-1515-4515-8515-151515151515", "Parent",
                components=[{"uuid": target, "type": "software", "title": "Target",
                             "description": "t"}],
                imports=[{"href": "child.json"}],
            )
            parent_path = os.path.join(d, "parent.json")
            with open(parent_path, "w") as fh:
                json.dump(parent, fh)
            cd = ComponentDefinition.load(parent_path)
            # The imported Citer depends-on the parent's Target -> Target.dependents.
            assert cd.component(target)["relationships"]["dependents"] == [
                {"uuid": citer, "title": "Citer", "type": "service"}]

    def test_used_by_merges_forward_and_reverse_without_duplicate(self):
        """``used-by`` collects both X's own ``used-by`` links and other components'
        ``uses-service``/``uses-network`` citations of X — the same component once."""
        x = "aaaaaaaa-0000-4000-8000-0000000000e1"
        y = "aaaaaaaa-0000-4000-8000-0000000000e2"
        doc = _cdef_doc(
            "16161616-1616-4616-8616-161616161616", "cDef",
            components=[
                {"uuid": x, "type": "software", "title": "X", "description": "x",
                 "links": [{"href": "#" + y, "rel": "used-by"}]},        # forward: X used-by Y
                {"uuid": y, "type": "service", "title": "Y", "description": "y",
                 "links": [{"href": "#" + x, "rel": "uses-service"}]},    # reverse: Y uses X
            ],
        )
        cd = _load(doc)
        # Forward (X used-by Y) and reverse (Y uses-service X) both mean "X is used by Y".
        assert cd.component(x)["relationships"]["used-by"] == [
            {"uuid": y, "title": "Y", "type": "service"}]
