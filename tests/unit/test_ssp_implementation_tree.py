"""
Unit tests for SSP.implementation_tree and SSP.component().

implementation_tree is a flat, UI-oriented view of an SSP's implementation surface
with three array-valued keys:

    leveraged-authorizations -> {"uuid", "title"} per system-implementation entry
    components               -> {"uuid", "title", "type"} (+ "asset-type" when the
                                OSCAL-default-namespace asset-type prop is present)
    controls                 -> the imported profile's controls_tree, each control node
                                overlaid with `implemented` (+ `implemented-requirement-uuid`)
                                from the SSP's root control-implementation

component(uuid) returns a safe copy of a system-implementation component annotated with:
    * implemented-controls   -> control-ids whose implementation cites the component
    * responsible-roles      -> each role's metadata title + full party objects
    * relationships          -> forward relationship links plus the reverse relationships
                                found by scanning the SSP's other components

A full valid SSP is expensive to build, so the end-to-end fixtures write a
catalog -> profile -> SSP chain to disk and load the SSP (cascade-resolving the
import-profile). The asset-type-present branch is exercised on the builder directly,
since the current validator over-rejects the (schema-legal) asset-type prop name due
to its multiply-scoped allowed-values constraint.
"""
import json
import os
import tempfile

import pytest

from oscal.oscal_implementation import SSP

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}
_TREE_KEYS = {"leveraged-authorizations", "components", "controls"}


def _meta(title):
    return {"title": title, **_META}


def _catalog():
    return {"catalog": {
        "uuid": "10000000-0000-4000-8000-000000000001",
        "metadata": _meta("Cat"),
        "groups": [{"id": "ac", "title": "Access Control",
                    "controls": [{"id": "ac-1", "title": "Policy"}]}],
    }}


def _profile():
    return {"profile": {
        "uuid": "20000000-0000-4000-8000-000000000001",
        "metadata": _meta("Prof"),
        "imports": [{"href": "catalog.json", "include-all": {}}],
    }}


def _ssp_doc(with_import=True, with_leveraged=True):
    root = {
        "uuid": "30000000-0000-4000-8000-000000000001",
        "metadata": _meta("SSP"),
        "import-profile": {"href": "profile.json"},
        "system-characteristics": {
            "system-ids": [{"id": "sys-1"}],
            "system-name": "Test System",
            "description": "d",
            "system-information": {"information-types": [{"title": "IT", "description": "d"}]},
            "security-sensitivity-level": "low",
            "security-impact-level": {
                "security-objective-confidentiality": "low",
                "security-objective-integrity": "low",
                "security-objective-availability": "low"},
            "status": {"state": "operational"},
            "authorization-boundary": {"description": "b"},
        },
        "system-implementation": {
            "users": [{"uuid": "60000000-0000-4000-8000-000000000001", "role-ids": ["admin"]}],
            "components": [
                {"uuid": "70000000-0000-4000-8000-000000000001", "type": "this-system",
                 "title": "This System", "description": "d", "status": {"state": "operational"}},
                {"uuid": "70000000-0000-4000-8000-000000000002", "type": "software",
                 "title": "Web App", "description": "d", "status": {"state": "operational"}},
            ],
        },
        "control-implementation": {
            "description": "ci",
            "implemented-requirements": [
                {"uuid": "80000000-0000-4000-8000-000000000001", "control-id": "ac-1"}],
        },
    }
    if with_leveraged:
        root["system-implementation"]["leveraged-authorizations"] = [
            {"uuid": "40000000-0000-4000-8000-000000000001", "title": "Cloud IaaS",
             "party-uuid": "50000000-0000-4000-8000-000000000001",
             "date-authorized": "2026-01-01"}]
    if not with_import:
        root.pop("import-profile")
    return {"system-security-plan": root}


@pytest.fixture
def ssp_chain():
    """A valid SSP loaded from a catalog -> profile -> SSP chain on disk."""
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog()),
                          ("profile.json", _profile()),
                          ("ssp.json", _ssp_doc())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield SSP.load(os.path.join(d, "ssp.json"))


# ===========================================================================
# Attribute existence / shape
# ===========================================================================
class TestAttribute:

    def test_attribute_always_present_with_all_keys(self):
        ssp = SSP.loads(json.dumps({"system-security-plan": {"uuid": "bad"}}))
        assert hasattr(ssp, "implementation_tree")
        assert set(ssp.implementation_tree.keys()) == _TREE_KEYS
        assert all(ssp.implementation_tree[k] == [] for k in _TREE_KEYS)

    def test_built_on_valid_load(self, ssp_chain):
        assert ssp_chain.is_valid
        assert set(ssp_chain.implementation_tree.keys()) == _TREE_KEYS

    def test_invalid_content_empty_tree(self):
        ssp = SSP.loads(json.dumps({"system-security-plan": {"uuid": "bad"}}))
        assert not ssp.is_valid
        assert all(ssp.implementation_tree[k] == [] for k in _TREE_KEYS)


# ===========================================================================
# leveraged-authorizations
# ===========================================================================
class TestLeveragedAuthorizations:

    def test_uuid_and_title(self, ssp_chain):
        la = ssp_chain.implementation_tree["leveraged-authorizations"]
        assert la == [{"uuid": "40000000-0000-4000-8000-000000000001", "title": "Cloud IaaS"}]

    def test_empty_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            for name, doc in [("catalog.json", _catalog()),
                              ("profile.json", _profile()),
                              ("ssp.json", _ssp_doc(with_leveraged=False))]:
                with open(os.path.join(d, name), "w") as fh:
                    json.dump(doc, fh)
            ssp = SSP.load(os.path.join(d, "ssp.json"))
            assert ssp.is_valid
            assert ssp.implementation_tree["leveraged-authorizations"] == []


# ===========================================================================
# components
# ===========================================================================
class TestComponents:

    def test_uuid_title_type(self, ssp_chain):
        comps = ssp_chain.implementation_tree["components"]
        assert comps == [
            {"uuid": "70000000-0000-4000-8000-000000000001", "title": "This System",
             "type": "this-system"},
            {"uuid": "70000000-0000-4000-8000-000000000002", "title": "Web App",
             "type": "software"},
        ]

    def test_asset_type_absent_key_omitted(self, ssp_chain):
        for node in ssp_chain.implementation_tree["components"]:
            assert "asset-type" not in node

    def test_asset_type_present_included(self, ssp_chain):
        # asset-type is schema-legal but the validator over-rejects it, so drive the
        # builder directly on injected content.
        comps = ssp_chain._dict["system-security-plan"]["system-implementation"]["components"]
        comps[1]["props"] = [{"name": "asset-type", "value": "web-server"}]
        ssp_chain._build_implementation_tree()
        node = ssp_chain.implementation_tree["components"][1]
        assert node["asset-type"] == "web-server"

    def test_mutation_refreshes_tree(self, ssp_chain):
        before = len(ssp_chain.implementation_tree["components"])
        ssp_chain.append_component("software", "Extra", "d")
        assert len(ssp_chain.implementation_tree["components"]) == before + 1


# ===========================================================================
# controls (imported profile controls_tree, overlaid with implemented status from the
# root control-implementation implemented-requirements)
# ===========================================================================
class TestControls:

    def test_base_is_profile_controls_tree(self, ssp_chain):
        # The base is the imported profile's controls_tree (group ac -> control ac-1).
        controls = ssp_chain.implementation_tree["controls"]
        assert len(controls) == 1
        assert controls[0]["id"] == "ac" and controls[0]["group"] is True
        assert [c["id"] for c in controls[0]["children"]] == ["ac-1"]

    def test_implemented_overlay(self, ssp_chain):
        # _ssp_doc implements ac-1 -> that control node is marked implemented and carries
        # the implementing requirement's uuid.
        ac1 = ssp_chain.implementation_tree["controls"][0]["children"][0]
        assert ac1["implemented"] is True
        assert ac1["implemented-requirement-uuid"] == "80000000-0000-4000-8000-000000000001"

    def test_group_nodes_not_marked(self, ssp_chain):
        assert "implemented" not in ssp_chain.implementation_tree["controls"][0]

    def test_unimplemented_control_marked_false(self, ssp_chain):
        # Drop the implemented-requirement and rebuild -> the baseline control remains but
        # is no longer implemented.
        ssp_chain._dict["system-security-plan"]["control-implementation"][
            "implemented-requirements"] = []
        ssp_chain._build_implementation_tree()
        ac1 = ssp_chain.implementation_tree["controls"][0]["children"][0]
        assert ac1["implemented"] is False
        assert "implemented-requirement-uuid" not in ac1

    def test_overlay_does_not_leak_into_profile(self, ssp_chain):
        """The overlay keys live only on the tree copy, never on the profile's tree."""
        profile = ssp_chain._imported_profile()

        def _flat(nodes):
            for n in nodes:
                yield n
                yield from _flat(n.get("children", []) or [])
        assert all("implemented" not in n for n in _flat(profile.controls_tree))

    def test_controls_empty_without_import(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ssp.json"), "w") as fh:
                json.dump(_ssp_doc(with_import=False), fh)
            ssp = SSP.load(os.path.join(d, "ssp.json"))
            # No import-profile => import-profile is required, so this is invalid;
            # the tree stays empty rather than raising.
            assert ssp.implementation_tree["controls"] == []


# ===========================================================================
# component(uuid) getter — returns the component plus implemented-controls
# ===========================================================================
_CU1 = "70000000-0000-4000-8000-000000000001"  # cited at requirement level (ac-1)
_CU2 = "70000000-0000-4000-8000-000000000002"  # cited at statement level  (ac-2)
_CU3 = "70000000-0000-4000-8000-000000000003"  # not cited anywhere


def _catalog2():
    return {"catalog": {
        "uuid": "10000000-0000-4000-8000-000000000002",
        "metadata": _meta("Cat"),
        "groups": [{"id": "ac", "title": "AC", "controls": [
            {"id": "ac-1", "title": "One"}, {"id": "ac-2", "title": "Two"}]}],
    }}


def _ssp_with_by_components():
    return {"system-security-plan": {
        "uuid": "30000000-0000-4000-8000-000000000002",
        "metadata": _meta("SSP"),
        "import-profile": {"href": "profile.json"},
        "system-characteristics": {
            "system-ids": [{"id": "sys-1"}], "system-name": "S", "description": "d",
            "system-information": {"information-types": [{"title": "IT", "description": "d"}]},
            "security-sensitivity-level": "low",
            "security-impact-level": {"security-objective-confidentiality": "low",
                "security-objective-integrity": "low", "security-objective-availability": "low"},
            "status": {"state": "operational"},
            "authorization-boundary": {"description": "b"}},
        "system-implementation": {
            "users": [{"uuid": "60000000-0000-4000-8000-000000000001", "role-ids": ["admin"]}],
            "components": [
                {"uuid": _CU1, "type": "this-system", "title": "This System",
                 "description": "d", "status": {"state": "operational"}},
                {"uuid": _CU2, "type": "software", "title": "Web App",
                 "description": "d", "status": {"state": "operational"}},
                {"uuid": _CU3, "type": "software", "title": "Lonely",
                 "description": "d", "status": {"state": "operational"}}]},
        "control-implementation": {"description": "ci", "implemented-requirements": [
            {"uuid": "80000000-0000-4000-8000-000000000001", "control-id": "ac-1",
             "by-components": [{"component-uuid": _CU1,
                                "uuid": "90000000-0000-4000-8000-000000000001",
                                "description": "req-level"}]},
            {"uuid": "80000000-0000-4000-8000-000000000002", "control-id": "ac-2",
             "statements": [{"statement-id": "ac-2_smt",
                             "uuid": "a0000000-0000-4000-8000-000000000001",
                             "by-components": [{"component-uuid": _CU2,
                                                "uuid": "b0000000-0000-4000-8000-000000000001",
                                                "description": "stmt-level"}]}]}]}}}


@pytest.fixture
def ssp_bc():
    """A valid SSP whose control-implementation cites components at both the
    requirement level (ac-1 -> CU1) and the statement level (ac-2 -> CU2)."""
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog2()),
                          ("profile.json", _profile()),
                          ("ssp.json", _ssp_with_by_components())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield SSP.load(os.path.join(d, "ssp.json"))


class TestComponentGetter:

    def test_returns_component_object(self, ssp_bc):
        comp = ssp_bc.component(_CU1)
        assert comp is not None
        assert comp["uuid"] == _CU1
        assert comp["title"] == "This System"
        assert comp["type"] == "this-system"
        # The component's own OSCAL fields are preserved.
        assert comp["status"] == {"state": "operational"}

    def test_missing_uuid_returns_none(self, ssp_bc):
        assert ssp_bc.component("nope") is None

    def test_implemented_controls_requirement_level(self, ssp_bc):
        assert ssp_bc.component(_CU1)["implemented-controls"] == ["ac-1"]

    def test_implemented_controls_statement_level(self, ssp_bc):
        assert ssp_bc.component(_CU2)["implemented-controls"] == ["ac-2"]

    def test_implemented_controls_empty_when_uncited(self, ssp_bc):
        assert ssp_bc.component(_CU3)["implemented-controls"] == []

    def test_getter_returns_safe_copy(self, ssp_bc):
        comp = ssp_bc.component(_CU1)
        comp["title"] = "MUTATED"
        comp["implemented-controls"].append("injected")
        again = ssp_bc.component(_CU1)
        assert again["title"] == "This System"
        assert again["implemented-controls"] == ["ac-1"]

    def test_control_id_deduped_across_citations(self, ssp_bc):
        """A component cited both at the requirement and a statement of the SAME
        control yields that control-id exactly once."""
        ci = ssp_bc._dict["system-security-plan"]["control-implementation"]
        # Add a statement citation for CU1 on ac-1 (already cited at req level).
        ci["implemented-requirements"][0]["statements"] = [
            {"statement-id": "ac-1_smt", "uuid": "c0000000-0000-4000-8000-000000000001",
             "by-components": [{"component-uuid": _CU1,
                                "uuid": "d0000000-0000-4000-8000-000000000001",
                                "description": "dup"}]}]
        assert ssp_bc.component(_CU1)["implemented-controls"] == ["ac-1"]

    def test_component_across_multiple_controls(self, ssp_bc):
        """A component cited on more than one control lists each control-id once,
        in document order."""
        ci = ssp_bc._dict["system-security-plan"]["control-implementation"]
        # Also cite CU1 on ac-2 at the requirement level.
        ci["implemented-requirements"][1]["by-components"] = [
            {"component-uuid": _CU1, "uuid": "e0000000-0000-4000-8000-000000000001",
             "description": "also"}]
        assert ssp_bc.component(_CU1)["implemented-controls"] == ["ac-1", "ac-2"]


# ===========================================================================
# component() responsible-roles enrichment (role title + full party objects)
# ===========================================================================
_RP1 = "eeeeeeee-0000-4000-8000-000000000001"  # person Alice
_RP2 = "eeeeeeee-0000-4000-8000-000000000002"  # org Acme
_RC = "70000000-0000-4000-8000-000000000009"   # the component under test


def _ssp_with_roles():
    doc = _ssp_doc()
    ssp = doc["system-security-plan"]
    ssp["metadata"]["roles"] = [{"id": "admin", "title": "Administrator"},
                                {"id": "owner", "title": "System Owner"}]
    ssp["metadata"]["parties"] = [{"uuid": _RP1, "type": "person", "name": "Alice"},
                                  {"uuid": _RP2, "type": "organization", "name": "Acme"}]
    ssp["system-implementation"]["components"].append(
        {"uuid": _RC, "type": "software", "title": "With Roles", "description": "d",
         "status": {"state": "operational"},
         "responsible-roles": [
             {"role-id": "admin", "party-uuids": [_RP1, _RP2]},
             {"role-id": "owner"},        # no party-uuids
             {"role-id": "ghost"},        # role not in metadata
         ]})
    return doc


@pytest.fixture
def ssp_roles():
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog()),
                          ("profile.json", _profile()),
                          ("ssp.json", _ssp_with_roles())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield SSP.load(os.path.join(d, "ssp.json"))


class TestComponentResponsibleRoles:

    def test_valid(self, ssp_roles):
        assert ssp_roles.is_valid

    def test_role_title_inserted(self, ssp_roles):
        roles = ssp_roles.component(_RC)["responsible-roles"]
        assert roles[0]["title"] == "Administrator"
        assert roles[1]["title"] == "System Owner"

    def test_parties_resolved(self, ssp_roles):
        # each party-uuid resolves to the FULL metadata party object (type, name, …)
        roles = ssp_roles.component(_RC)["responsible-roles"]
        assert roles[0]["parties"] == [{"uuid": _RP1, "type": "person", "name": "Alice"},
                                       {"uuid": _RP2, "type": "organization", "name": "Acme"}]

    def test_no_party_uuids_no_parties_key(self, ssp_roles):
        assert "parties" not in ssp_roles.component(_RC)["responsible-roles"][1]

    def test_unknown_role_empty_title(self, ssp_roles):
        assert ssp_roles.component(_RC)["responsible-roles"][2]["title"] == ""

    def test_component_without_roles_unaffected(self, ssp_roles):
        comp = ssp_roles.component("70000000-0000-4000-8000-000000000001")
        assert "responsible-roles" not in comp

    def test_enrichment_does_not_mutate_stored(self, ssp_roles):
        ssp_roles.component(_RC)
        comps = ssp_roles._dict["system-security-plan"]["system-implementation"]["components"]
        stored = next(c for c in comps if c["uuid"] == _RC)
        assert "title" not in stored["responsible-roles"][0]
        assert "parties" not in stored["responsible-roles"][0]


# ===========================================================================
# component() relationships (component<->component links via implementation_tree)
# ===========================================================================
_LC1 = "70000000-0000-4000-8000-000000000001"  # under test (this-system), has links
_LC2 = "70000000-0000-4000-8000-000000000002"  # target (Web App)
_LC3 = "70000000-0000-4000-8000-000000000003"  # isolated: no links, never cited
_LGHOST = "ffffffff-0000-4000-8000-000000000000"

_REL_KEYS = {"depends-on", "validation", "uses-service", "uses-network", "provided-by",
             "used-by", "dependents", "validates", "provides", "uses"}


def _ssp_with_links():
    doc = _ssp_doc()
    comps = doc["system-security-plan"]["system-implementation"]["components"]
    comps[0]["links"] = [
        {"href": "#" + _LC2, "rel": "depends-on"},
        {"href": "#" + _LGHOST, "rel": "uses-service"},
        {"href": "https://example.com", "rel": "reference"},  # not a relationship rel
    ]
    comps.append({"uuid": _LC3, "type": "software", "title": "Alone", "description": "d",
                  "status": {"state": "operational"}})
    return doc


@pytest.fixture
def ssp_links():
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog()),
                          ("profile.json", _profile()),
                          ("ssp.json", _ssp_with_links())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield SSP.load(os.path.join(d, "ssp.json"))


class TestComponentRelationships:

    def test_valid(self, ssp_links):
        assert ssp_links.is_valid

    def test_all_relationship_keys_present(self, ssp_links):
        rels = ssp_links.component(_LC1)["relationships"]
        assert set(rels.keys()) == _REL_KEYS

    def test_resolved_entry(self, ssp_links):
        rels = ssp_links.component(_LC1)["relationships"]
        assert rels["depends-on"] == [{"uuid": _LC2, "title": "Web App", "type": "software"}]

    def test_unresolved_reference_still_listed(self, ssp_links):
        assert ssp_links.component(_LC1)["relationships"]["uses-service"] == [
            {"uuid": _LGHOST, "title": "", "type": ""}]

    def test_unused_and_non_relationship_rels(self, ssp_links):
        rels = ssp_links.component(_LC1)["relationships"]
        assert rels["validation"] == []
        assert rels["uses-network"] == []
        all_uuids = [e["uuid"] for arr in rels.values() for e in arr]
        assert "https://example.com" not in all_uuids

    def test_reverse_dependents(self, ssp_links):
        # _LC1 depends-on _LC2  =>  _LC2.dependents contains _LC1.
        rels = ssp_links.component(_LC2)["relationships"]
        assert rels["dependents"] == [{"uuid": _LC1, "title": "This System",
                                       "type": "this-system"}]

    def test_isolated_component_all_empty(self, ssp_links):
        rels = ssp_links.component(_LC3)["relationships"]
        assert all(rels[k] == [] for k in rels)


# ===========================================================================
# SSP.control() — implemented-requirement by control-id or uuid, with the
# imported profile's control inserted (depth-controlled).
# ===========================================================================
_IR_UUID = "80000000-0000-4000-8000-0000000000c2"


def _catalog_with_enhancements():
    return {"catalog": {
        "uuid": "10000000-0000-4000-8000-000000000002",
        "metadata": _meta("Cat"),
        "groups": [{"id": "ac", "title": "Access Control", "controls": [
            {"id": "ac-2", "title": "Account Management",
             "controls": [{"id": "ac-2.1", "title": "Automated"},
                          {"id": "ac-2.2", "title": "Temporary"}]}]}],
    }}


def _ssp_doc_for_control():
    doc = _ssp_doc()
    doc["system-security-plan"]["control-implementation"]["implemented-requirements"] = [
        {"uuid": _IR_UUID, "control-id": "ac-2", "remarks": "impl notes"}]
    return doc


@pytest.fixture
def ssp_ctrl():
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog_with_enhancements()),
                          ("profile.json", _profile()),
                          ("ssp.json", _ssp_doc_for_control())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield SSP.load(os.path.join(d, "ssp.json"))


class TestControlGetter:

    def test_valid(self, ssp_ctrl):
        assert ssp_ctrl.is_valid

    def test_lookup_by_control_id(self, ssp_ctrl):
        ir = ssp_ctrl.control("ac-2")
        assert ir is not None
        assert ir["uuid"] == _IR_UUID
        assert ir["control-id"] == "ac-2"
        assert ir["remarks"] == "impl notes"

    def test_lookup_by_implemented_requirement_uuid(self, ssp_ctrl):
        ir = ssp_ctrl.control(_IR_UUID)
        assert ir is not None and ir["control-id"] == "ac-2"

    def test_missing_returns_none(self, ssp_ctrl):
        assert ssp_ctrl.control("zz-9") is None
        assert ssp_ctrl.control("00000000-0000-4000-8000-000000000000") is None

    def test_control_inserted_full_depth_by_default(self, ssp_ctrl):
        ctl = ssp_ctrl.control("ac-2")["control"]
        assert ctl["id"] == "ac-2"
        assert [c["id"] for c in ctl["controls"]] == ["ac-2.1", "ac-2.2"]

    def test_depth_zero_control_only(self, ssp_ctrl):
        ctl = ssp_ctrl.control("ac-2", depth=0)["control"]
        assert ctl["id"] == "ac-2"
        assert "controls" not in ctl or ctl["controls"] == []

    def test_depth_one_includes_direct_enhancements(self, ssp_ctrl):
        ctl = ssp_ctrl.control("ac-2", depth=1)["control"]
        assert [c["id"] for c in ctl["controls"]] == ["ac-2.1", "ac-2.2"]

    def test_with_control_false_omits_control_key(self, ssp_ctrl):
        ir = ssp_ctrl.control("ac-2", with_control=False)
        assert ir is not None
        assert "control" not in ir

    def test_control_none_when_not_in_profile(self, ssp_ctrl):
        # An implemented-requirement citing a control absent from the profile:
        # the requirement is returned, control resolves to None.
        ssp_ctrl._dict["system-security-plan"]["control-implementation"][
            "implemented-requirements"].append(
                {"uuid": "80000000-0000-4000-8000-0000000000c9", "control-id": "zz-99"})
        ir = ssp_ctrl.control("zz-99")
        assert ir is not None
        assert ir["control"] is None

    def test_returns_safe_copy(self, ssp_ctrl):
        ir = ssp_ctrl.control("ac-2")
        ir["remarks"] = "MUTATED"
        assert ssp_ctrl.control("ac-2")["remarks"] == "impl notes"


# ===========================================================================
# SSP.leveraged_authorization() — LA by uuid, annotated with party name/short-name
# and the uuids of components that reference it.
# ===========================================================================
_LA_UUID = "40000000-0000-4000-8000-00000000000a"
_LA_PARTY = "50000000-0000-4000-8000-000000000001"
_LA_C_REF1 = "70000000-0000-4000-8000-0000000000f1"
_LA_C_REF2 = "70000000-0000-4000-8000-0000000000f2"


def _ssp_doc_for_la(*, with_party=True):
    doc = _ssp_doc()
    ssp = doc["system-security-plan"]
    if with_party:
        ssp["metadata"]["parties"] = [
            {"uuid": _LA_PARTY, "type": "organization",
             "name": "Amazon Web Services", "short-name": "AWS"}]
    la = {"uuid": _LA_UUID, "title": "AWS GovCloud", "date-authorized": "2026-01-01"}
    if with_party:
        la["party-uuid"] = _LA_PARTY
    ssp["system-implementation"]["leveraged-authorizations"] = [la]
    # Two components reference the LA; the pre-existing ones do not.
    ssp["system-implementation"]["components"].extend([
        {"uuid": _LA_C_REF1, "type": "service", "title": "S3", "description": "d",
         "status": {"state": "operational"},
         "props": [{"name": "leveraged-authorization-uuid", "value": _LA_UUID}]},
        {"uuid": _LA_C_REF2, "type": "service", "title": "EC2", "description": "d",
         "status": {"state": "operational"},
         "props": [{"name": "leveraged-authorization-uuid", "value": _LA_UUID}]},
    ])
    return doc


@pytest.fixture
def ssp_la():
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog()),
                          ("profile.json", _profile()),
                          ("ssp.json", _ssp_doc_for_la())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield SSP.load(os.path.join(d, "ssp.json"))


class TestLeveragedAuthorizationGetter:

    def test_valid(self, ssp_la):
        assert ssp_la.is_valid

    def test_lookup_by_uuid(self, ssp_la):
        la = ssp_la.leveraged_authorization(_LA_UUID)
        assert la is not None
        assert la["uuid"] == _LA_UUID
        assert la["title"] == "AWS GovCloud"

    def test_missing_returns_none(self, ssp_la):
        assert ssp_la.leveraged_authorization("00000000-0000-4000-8000-000000000000") is None

    def test_party_name_and_short_name_resolved(self, ssp_la):
        la = ssp_la.leveraged_authorization(_LA_UUID)
        assert la["name"] == "Amazon Web Services"
        assert la["short-name"] == "AWS"

    def test_component_uuids_collected(self, ssp_la):
        la = ssp_la.leveraged_authorization(_LA_UUID)
        assert sorted(la["component-uuids"]) == sorted([_LA_C_REF1, _LA_C_REF2])

    def test_component_uuids_always_present_and_empty_when_none(self):
        with tempfile.TemporaryDirectory() as d:
            doc = _ssp_doc_for_la()
            # Drop the referencing components' prop so nothing points at the LA.
            comps = doc["system-security-plan"]["system-implementation"]["components"]
            for c in comps:
                c.pop("props", None)
            for name, o in [("catalog.json", _catalog()), ("profile.json", _profile()),
                            ("ssp.json", doc)]:
                with open(os.path.join(d, name), "w") as fh:
                    json.dump(o, fh)
            ssp = SSP.load(os.path.join(d, "ssp.json"))
            la = ssp.leveraged_authorization(_LA_UUID)
            assert la["component-uuids"] == []

    def test_name_short_name_empty_without_party(self):
        with tempfile.TemporaryDirectory() as d:
            for name, o in [("catalog.json", _catalog()), ("profile.json", _profile()),
                            ("ssp.json", _ssp_doc_for_la(with_party=False))]:
                with open(os.path.join(d, name), "w") as fh:
                    json.dump(o, fh)
            ssp = SSP.load(os.path.join(d, "ssp.json"))
            la = ssp.leveraged_authorization(_LA_UUID)
            assert la["name"] == ""
            assert la["short-name"] == ""

    def test_returns_safe_copy(self, ssp_la):
        la = ssp_la.leveraged_authorization(_LA_UUID)
        la["title"] = "MUTATED"
        la["component-uuids"].append("injected")
        again = ssp_la.leveraged_authorization(_LA_UUID)
        assert again["title"] == "AWS GovCloud"
        assert "injected" not in again["component-uuids"]


# ===========================================================================
# SSP.control() — responsible-roles on by-components (requirement-level and
# statement-level) annotated with role title + full party objects.
# ===========================================================================
_CR_IR = "80000000-0000-4000-8000-0000000000d1"
_CR_PARTY = "50000000-0000-4000-8000-0000000000d2"
_CR_COMP = "70000000-0000-4000-8000-000000000001"


def _ssp_doc_for_control_roles():
    doc = _ssp_doc()
    ssp = doc["system-security-plan"]
    ssp["metadata"]["roles"] = [{"id": "admin", "title": "Administrator"},
                                {"id": "isso", "title": "ISSO"}]
    ssp["metadata"]["parties"] = [{"uuid": _CR_PARTY, "type": "person", "name": "Alice"}]
    ssp["control-implementation"]["implemented-requirements"] = [{
        "uuid": _CR_IR, "control-id": "ac-2",
        # requirement-LEVEL responsibility construct (not only on by-components)
        "responsible-roles": [{"role-id": "isso", "party-uuids": [_CR_PARTY]}],
        "by-components": [{
            "component-uuid": _CR_COMP, "uuid": "90000000-0000-4000-8000-0000000000d1",
            "description": "req-bc",
            "responsible-roles": [{"role-id": "admin", "party-uuids": [_CR_PARTY]},
                                  {"role-id": "ghost"}]}],
        "statements": [{
            "statement-id": "ac-2_smt", "uuid": "a0000000-0000-4000-8000-0000000000d1",
            # statement-LEVEL responsibility construct
            "responsible-roles": [{"role-id": "admin"}],
            "by-components": [{
                "component-uuid": _CR_COMP, "uuid": "b0000000-0000-4000-8000-0000000000d1",
                "description": "stmt-bc",
                "responsible-roles": [{"role-id": "isso"}]}]}]}]
    return doc


@pytest.fixture
def ssp_ctrl_roles():
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog_with_enhancements()),
                          ("profile.json", _profile()),
                          ("ssp.json", _ssp_doc_for_control_roles())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield SSP.load(os.path.join(d, "ssp.json"))


class TestControlResponsibleRoles:

    def test_valid(self, ssp_ctrl_roles):
        assert ssp_ctrl_roles.is_valid

    def _req_bc_roles(self, ssp):
        return ssp.control("ac-2", with_control=False)["by-components"][0]["responsible-roles"]

    def _stmt_bc_roles(self, ssp):
        ir = ssp.control("ac-2", with_control=False)
        return ir["statements"][0]["by-components"][0]["responsible-roles"]

    def test_requirement_by_component_role_title(self, ssp_ctrl_roles):
        assert self._req_bc_roles(ssp_ctrl_roles)[0]["title"] == "Administrator"

    def test_requirement_by_component_parties(self, ssp_ctrl_roles):
        assert self._req_bc_roles(ssp_ctrl_roles)[0]["parties"] == [
            {"uuid": _CR_PARTY, "type": "person", "name": "Alice"}]

    def test_no_party_uuids_no_parties_key(self, ssp_ctrl_roles):
        # Second req-level role has no party-uuids -> no parties key.
        assert "parties" not in self._req_bc_roles(ssp_ctrl_roles)[1]

    def test_requirement_level_responsible_roles_enriched(self, ssp_ctrl_roles):
        # The responsibility construct on the requirement ITSELF (not just by-components)
        # is now resolved by the recursive enrichment.
        ir = ssp_ctrl_roles.control("ac-2", with_control=False)
        rr = ir["responsible-roles"][0]
        assert rr["title"] == "ISSO"
        assert rr["parties"] == [{"uuid": _CR_PARTY, "type": "person", "name": "Alice"}]

    def test_statement_level_responsible_roles_enriched(self, ssp_ctrl_roles):
        ir = ssp_ctrl_roles.control("ac-2", with_control=False)
        assert ir["statements"][0]["responsible-roles"][0]["title"] == "Administrator"

    def test_unknown_role_empty_title(self, ssp_ctrl_roles):
        assert self._req_bc_roles(ssp_ctrl_roles)[1]["title"] == ""

    def test_statement_by_component_role_title(self, ssp_ctrl_roles):
        assert self._stmt_bc_roles(ssp_ctrl_roles)[0]["title"] == "ISSO"

    def test_enrichment_does_not_mutate_stored(self, ssp_ctrl_roles):
        ssp_ctrl_roles.control("ac-2", with_control=False)
        ci = ssp_ctrl_roles._dict["system-security-plan"]["control-implementation"]
        stored_role = ci["implemented-requirements"][0]["by-components"][0]["responsible-roles"][0]
        assert "title" not in stored_role
        assert "parties" not in stored_role


# ===========================================================================
# SSP.control() — set-parameters applied to the inserted control (shared with
# profile resolution via _apply_set_parameters_to_control).
# ===========================================================================
_SP_IR = "80000000-0000-4000-8000-0000000000e1"


def _catalog_with_params():
    return {"catalog": {
        "uuid": "10000000-0000-4000-8000-000000000003",
        "metadata": _meta("Cat"),
        "groups": [{"id": "ac", "title": "AC", "controls": [
            {"id": "ac-2", "title": "Account Management",
             "params": [{"id": "ac-2_prm_1", "values": ["original"]}],
             "controls": [{"id": "ac-2.1", "title": "Automated",
                           "params": [{"id": "ac-2.1_prm_1", "select": {"choice": ["x", "y"]}}]}]}]}],
    }}


def _ssp_doc_with_set_parameters():
    doc = _ssp_doc()
    doc["system-security-plan"]["control-implementation"]["implemented-requirements"] = [{
        "uuid": _SP_IR, "control-id": "ac-2",
        "set-parameters": [
            {"param-id": "ac-2_prm_1", "values": ["30 days"]},
            {"param-id": "ac-2.1_prm_1", "values": ["enh-val"]}]}]
    return doc


@pytest.fixture
def ssp_setparams():
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog_with_params()),
                          ("profile.json", _profile()),
                          ("ssp.json", _ssp_doc_with_set_parameters())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield SSP.load(os.path.join(d, "ssp.json"))


class TestControlSetParameters:

    def test_valid(self, ssp_setparams):
        assert ssp_setparams.is_valid

    def test_top_level_param_value_applied(self, ssp_setparams):
        ctl = ssp_setparams.control("ac-2")["control"]
        assert ctl["params"][0]["values"] == ["30 days"]

    def test_enhancement_param_value_applied(self, ssp_setparams):
        # set-parameters apply across the returned subtree (nested enhancements too);
        # setting values on a select-param clears the select (mutual exclusion).
        enh = ssp_setparams.control("ac-2")["control"]["controls"][0]
        assert enh["params"][0]["values"] == ["enh-val"]
        assert "select" not in enh["params"][0]

    def test_does_not_mutate_imported_profile(self, ssp_setparams):
        ssp_setparams.control("ac-2")
        stored = ssp_setparams._imported_profile().get_control_by_id("ac-2")
        assert stored["params"][0]["values"] == ["original"]

    def test_no_set_parameters_leaves_control_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            doc = _ssp_doc_with_set_parameters()
            doc["system-security-plan"]["control-implementation"][
                "implemented-requirements"][0].pop("set-parameters")
            for name, o in [("catalog.json", _catalog_with_params()),
                            ("profile.json", _profile()), ("ssp.json", doc)]:
                with open(os.path.join(d, name), "w") as fh:
                    json.dump(o, fh)
            ssp = SSP.load(os.path.join(d, "ssp.json"))
            ctl = ssp.control("ac-2")["control"]
            assert ctl["params"][0]["values"] == ["original"]

    def test_no_effect_when_with_control_false(self, ssp_setparams):
        ir = ssp_setparams.control("ac-2", with_control=False)
        assert "control" not in ir


# ===========================================================================
# SSP.control() — by-component title/type/asset-type from implementation_tree.
# ===========================================================================
_BC_IR = "80000000-0000-4000-8000-0000000000f1"
_BC_C1 = "70000000-0000-4000-8000-000000000001"   # this-system / "This System"
_BC_C2 = "70000000-0000-4000-8000-000000000002"   # software / "Web App"
_BC_GHOST = "ffffffff-0000-4000-8000-000000000000"


def _ssp_doc_for_by_component():
    doc = _ssp_doc()   # components: _BC_C1 (this-system), _BC_C2 (software)
    doc["system-security-plan"]["control-implementation"]["implemented-requirements"] = [{
        "uuid": _BC_IR, "control-id": "ac-1",
        "by-components": [
            {"component-uuid": _BC_C1, "uuid": "90000000-0000-4000-8000-0000000000f1",
             "description": "req-bc"},
            {"component-uuid": _BC_GHOST, "uuid": "90000000-0000-4000-8000-0000000000f2",
             "description": "dangling"}],
        "statements": [{
            "statement-id": "ac-1_smt", "uuid": "a0000000-0000-4000-8000-0000000000f1",
            "by-components": [
                {"component-uuid": _BC_C2, "uuid": "b0000000-0000-4000-8000-0000000000f1",
                 "description": "stmt-bc"}]}]}]
    return doc


@pytest.fixture
def ssp_bc_annot():
    with tempfile.TemporaryDirectory() as d:
        for name, doc in [("catalog.json", _catalog()),
                          ("profile.json", _profile()),
                          ("ssp.json", _ssp_doc_for_by_component())]:
            with open(os.path.join(d, name), "w") as fh:
                json.dump(doc, fh)
        yield SSP.load(os.path.join(d, "ssp.json"))


class TestControlByComponentAnnotation:

    def test_valid(self, ssp_bc_annot):
        assert ssp_bc_annot.is_valid

    def test_requirement_by_component_title_and_type(self, ssp_bc_annot):
        bc = ssp_bc_annot.control("ac-1", with_control=False)["by-components"][0]
        assert bc["component-uuid"] == _BC_C1
        assert bc["title"] == "This System"
        assert bc["type"] == "this-system"

    def test_statement_by_component_title_and_type(self, ssp_bc_annot):
        ir = ssp_bc_annot.control("ac-1", with_control=False)
        bc = ir["statements"][0]["by-components"][0]
        assert bc["title"] == "Web App"
        assert bc["type"] == "software"

    def test_dangling_component_uuid_yields_empty(self, ssp_bc_annot):
        bc = ssp_bc_annot.control("ac-1", with_control=False)["by-components"][1]
        assert bc["title"] == ""
        assert bc["type"] == ""

    def test_asset_type_omitted_when_absent(self, ssp_bc_annot):
        # The SSP's components carry no asset-type prop, so the key is not added.
        bc = ssp_bc_annot.control("ac-1", with_control=False)["by-components"][0]
        assert "asset-type" not in bc

    def test_annotation_does_not_mutate_stored(self, ssp_bc_annot):
        ssp_bc_annot.control("ac-1", with_control=False)
        ci = ssp_bc_annot._dict["system-security-plan"]["control-implementation"]
        stored_bc = ci["implemented-requirements"][0]["by-components"][0]
        assert "title" not in stored_bc
        assert "type" not in stored_bc
