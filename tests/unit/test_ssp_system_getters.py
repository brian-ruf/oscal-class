"""
Unit tests for the SSP system-characteristics / system-implementation getters:

    system_characteristics()  -> system-characteristics minus the 4 dedicated-getter children
    authorization_boundary()  -> system-characteristics.authorization-boundary assembly
    network_architecture()    -> system-characteristics.network-architecture assembly
    data_flow()               -> system-characteristics.data-flow assembly
    system_information()      -> system-characteristics.system-information
    inventory_items()         -> a simplified index of all inventory-items
    inventory_item(uuid)      -> one inventory-item, implemented-components enriched with .component
    users()                   -> system-implementation.users (whole array)
    user(uuid)                -> one user, with a resolved `roles` sibling of `role-ids`
    protocols()               -> index of components declaring `protocols`

All are read-only getters that must return detached (safe) copies: mutating a result must
not change the document. They operate on the loaded `_dict` directly and do not require a
fully schema-valid SSP.
"""
import copy
import json

import pytest

from oscal import OSCAL

_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}

_COMP_UUID = "66666666-0000-4000-8000-000000000001"
_INV_UUID = "77777777-0000-4000-8000-000000000001"
_USER_UUID = "55555555-0000-4000-8000-000000000001"


def _ssp_dict():
    return {"system-security-plan": {
        "uuid": "30000000-0000-4000-8000-000000000001",
        "metadata": {
            "title": "T", **_META,
            "roles": [
                {"id": "admin", "title": "Administrator", "short-name": "Admin"},
                {"id": "owner", "title": "System Owner"},   # no short-name
            ],
            "parties": [
                {"uuid": "99999999-0000-4000-8000-000000000001",
                 "type": "organization", "name": "Acme Ops", "short-name": "Acme"},
            ],
        },
        "system-characteristics": {
            "system-ids": [{"id": "sys-1"}],
            "system-name": "My System",
            "description": "desc",
            "security-sensitivity-level": "moderate",
            "status": {"state": "operational"},
            "props": [{"name": "foo", "value": "bar"}],
            "responsible-parties": [
                {"role-id": "owner",
                 "party-uuids": ["99999999-0000-4000-8000-000000000001"]},
            ],
            "system-information": {"information-types": [
                {"uuid": "11111111-0000-4000-8000-000000000001", "title": "IT", "description": "d"}]},
            "authorization-boundary": {"description": "AB", "diagrams": [
                {"uuid": "22222222-0000-4000-8000-000000000001", "description": "d"}]},
            "network-architecture": {"description": "NA", "diagrams": [
                {"uuid": "33333333-0000-4000-8000-000000000001"}]},
            "data-flow": {"description": "DF", "diagrams": [
                {"uuid": "44444444-0000-4000-8000-000000000001"}]},
        },
        "system-implementation": {
            "users": [{"uuid": _USER_UUID, "title": "U",
                       "role-ids": ["admin", "owner", "ghost"]}],
            "components": [
                # App: no protocols -> excluded from protocols()
                {"uuid": _COMP_UUID, "type": "software", "title": "App",
                 "description": "d", "status": {"state": "operational"}},
                # Web: protocols + asset-type prop (OSCAL default ns)
                {"uuid": "aaaaaaaa-0000-4000-8000-000000000001", "type": "software",
                 "title": "Web", "description": "d", "status": {"state": "operational"},
                 "props": [{"name": "asset-type", "value": "web-server"}],
                 "protocols": [{"uuid": "p1", "name": "https",
                                "port-ranges": [{"start": 443, "end": 443, "transport": "TCP"}]}]},
                # DB: protocols, no asset-type prop
                {"uuid": "aaaaaaaa-0000-4000-8000-000000000002", "type": "service",
                 "title": "DB", "description": "d", "status": {"state": "operational"},
                 "protocols": [{"name": "postgres", "port-ranges": [{"start": 5432, "end": 5432}]}]},
            ],
            "inventory-items": [{
                "uuid": _INV_UUID, "description": "server one",
                "props": [
                    {"name": "asset-type", "value": "server"},
                    {"name": "ipv4-address", "value": "10.0.0.1"},
                    {"name": "ipv4-address", "value": "10.0.0.2"},   # repeated -> list
                    {"name": "fqdn", "value": "host.example.com"},
                    {"name": "not-recognized", "value": "ignore-me"},
                ],
                "implemented-components": [
                    {"component-uuid": _COMP_UUID},                               # valid
                    {"component-uuid": "deadbeef-0000-4000-8000-000000000000"},   # dangling
                ],
                "responsible-parties": [
                    {"role-id": "admin",
                     "party-uuids": ["99999999-0000-4000-8000-000000000001"]},
                ],
            }],
        },
    }}


@pytest.fixture
def ssp():
    return OSCAL.loads(json.dumps(_ssp_dict()))


def _ssp_without(*top_level_keys):
    d = _ssp_dict()
    for k in top_level_keys:
        d["system-security-plan"].pop(k, None)
    return OSCAL.loads(json.dumps(d))


# ===========================================================================
class TestSystemCharacteristics:
    _EXCLUDED = ("system-information", "authorization-boundary",
                 "network-architecture", "data-flow")

    def test_returns_included_children(self, ssp):
        sc = ssp.system_characteristics()
        assert sc["system-name"] == "My System"
        assert sc["description"] == "desc"
        assert sc["security-sensitivity-level"] == "moderate"
        assert sc["props"] == [{"name": "foo", "value": "bar"}]

    def test_excludes_dedicated_children(self, ssp):
        sc = ssp.system_characteristics()
        for key in self._EXCLUDED:
            assert key not in sc

    def test_none_when_section_absent(self):
        assert _ssp_without("system-characteristics").system_characteristics() is None

    def test_responsible_parties_enriched(self, ssp):
        rp = ssp.system_characteristics()["responsible-parties"][0]
        assert rp["title"] == "System Owner"              # role-id 'owner' -> metadata.roles
        assert rp["parties"] == [{                          # party-uuid -> full metadata party
            "uuid": "99999999-0000-4000-8000-000000000001",
            "type": "organization", "name": "Acme Ops", "short-name": "Acme"}]
        assert rp["role-id"] == "owner"                     # originals left intact
        assert rp["party-uuids"] == ["99999999-0000-4000-8000-000000000001"]

    def test_returns_safe_copy(self, ssp):
        sc = ssp.system_characteristics()
        sc["system-name"] = "MUTATED"
        sc["props"][0]["value"] = "MUTATED"
        assert ssp.system_characteristics()["system-name"] == "My System"
        assert ssp.system_characteristics()["props"][0]["value"] == "bar"


# ===========================================================================
class TestDiagramAssemblies:
    @pytest.mark.parametrize("getter,desc", [
        ("authorization_boundary", "AB"),
        ("network_architecture", "NA"),
        ("data_flow", "DF"),
    ])
    def test_returns_assembly(self, ssp, getter, desc):
        node = getattr(ssp, getter)()
        assert node["description"] == desc
        assert isinstance(node["diagrams"], list) and node["diagrams"]

    def test_absent_assembly_returns_none(self):
        d = _ssp_dict()
        d["system-security-plan"]["system-characteristics"].pop("data-flow")
        doc = OSCAL.loads(json.dumps(d))
        assert doc.data_flow() is None
        assert doc.authorization_boundary() is not None

    def test_returns_safe_copy(self, ssp):
        node = ssp.authorization_boundary()
        node["diagrams"][0]["description"] = "MUTATED"
        assert ssp.authorization_boundary()["diagrams"][0]["description"] == "d"


# ===========================================================================
class TestSystemInformation:
    def test_returns_information_types(self, ssp):
        si = ssp.system_information()
        assert "information-types" in si
        assert si["information-types"][0]["title"] == "IT"

    def test_none_when_absent(self):
        d = _ssp_dict()
        d["system-security-plan"]["system-characteristics"].pop("system-information")
        assert OSCAL.loads(json.dumps(d)).system_information() is None

    def test_returns_safe_copy(self, ssp):
        si = ssp.system_information()
        si["information-types"][0]["title"] = "MUTATED"
        assert ssp.system_information()["information-types"][0]["title"] == "IT"


# ===========================================================================
class TestInventoryItemsIndex:
    def test_core_fields(self, ssp):
        entry = ssp.inventory_items()[0]
        assert entry["uuid"] == _INV_UUID
        assert entry["description"] == "server one"

    def test_recognized_props_flattened(self, ssp):
        entry = ssp.inventory_items()[0]
        assert entry["asset-type"] == "server"          # single -> scalar
        assert entry["fqdn"] == "host.example.com"
        assert entry["ipv4-address"] == ["10.0.0.1", "10.0.0.2"]   # repeated -> list

    def test_unrecognized_prop_excluded(self, ssp):
        assert "not-recognized" not in ssp.inventory_items()[0]

    def test_implemented_components_valid_only(self, ssp):
        impl = ssp.inventory_items()[0]["implemented-components"]
        # only the resolvable reference is indexed, with its component title/type
        assert impl == [{"component-uuid": _COMP_UUID, "title": "App", "type": "software"}]

    def test_empty_when_no_inventory(self):
        d = _ssp_dict()
        d["system-security-plan"]["system-implementation"].pop("inventory-items")
        assert OSCAL.loads(json.dumps(d)).inventory_items() == []

    def test_absent_prop_key_omitted(self, ssp):
        entry = ssp.inventory_items()[0]
        assert "mac-address" not in entry and "serial-number" not in entry


# ===========================================================================
class TestInventoryItem:
    def test_returns_entire_object(self, ssp):
        item = ssp.inventory_item(_INV_UUID)
        assert item["uuid"] == _INV_UUID
        assert item["description"] == "server one"
        assert len(item["props"]) == 5   # all props retained, not filtered

    def test_valid_reference_embeds_full_component(self, ssp):
        item = ssp.inventory_item(_INV_UUID)
        comp = item["implemented-components"][0]["component"]
        assert comp["uuid"] == _COMP_UUID
        assert comp["title"] == "App" and comp["type"] == "software"
        assert comp["status"] == {"state": "operational"}   # the ENTIRE component

    def test_invalid_reference_placeholder(self, ssp):
        item = ssp.inventory_item(_INV_UUID)
        comp = item["implemented-components"][1]["component"]
        assert comp == {"title": "[Invalid Component Reference]", "type": "unknown"}

    def test_unknown_uuid_returns_none(self, ssp):
        assert ssp.inventory_item("nope") is None

    def test_responsible_parties_enriched(self, ssp):
        rp = ssp.inventory_item(_INV_UUID)["responsible-parties"][0]
        assert rp["title"] == "Administrator"            # role-id -> metadata.roles title
        assert rp["parties"] == [{                         # party-uuid -> full metadata party
            "uuid": "99999999-0000-4000-8000-000000000001",
            "type": "organization", "name": "Acme Ops", "short-name": "Acme"}]
        assert rp["role-id"] == "admin" and rp["party-uuids"] == [
            "99999999-0000-4000-8000-000000000001"]        # originals untouched

    def test_returns_safe_copy(self, ssp):
        item = ssp.inventory_item(_INV_UUID)
        item["implemented-components"][0]["component"]["title"] = "MUTATED"
        again = ssp.inventory_item(_INV_UUID)
        assert again["implemented-components"][0]["component"]["title"] == "App"


# ===========================================================================
class TestUsers:
    def test_returns_all_users(self, ssp):
        users = ssp.users()
        assert len(users) == 1 and users[0]["uuid"] == _USER_UUID

    def test_empty_when_none(self):
        d = _ssp_dict()
        d["system-security-plan"]["system-implementation"].pop("users")
        assert OSCAL.loads(json.dumps(d)).users() == []

    def test_returns_safe_copy(self, ssp):
        users = ssp.users()
        users[0]["title"] = "MUTATED"
        assert ssp.users()[0]["title"] == "U"


# ===========================================================================
class TestUser:
    def test_role_ids_unchanged(self, ssp):
        u = ssp.user(_USER_UUID)
        assert u["role-ids"] == ["admin", "owner", "ghost"]   # still plain strings

    def test_roles_sibling_resolved(self, ssp):
        u = ssp.user(_USER_UUID)
        assert u["roles"] == [
            {"id": "admin", "title": "Administrator", "short-name": "Admin"},
            {"id": "owner", "title": "System Owner", "short-name": ""},   # no short-name
            {"id": "ghost", "title": "", "short-name": ""},               # unresolved role-id
        ]

    def test_no_roles_key_without_role_ids(self):
        d = _ssp_dict()
        d["system-security-plan"]["system-implementation"]["users"][0].pop("role-ids")
        u = OSCAL.loads(json.dumps(d)).user(_USER_UUID)
        assert "roles" not in u

    def test_unknown_uuid_returns_none(self, ssp):
        assert ssp.user("nope") is None

    def test_does_not_mutate_document(self, ssp):
        u = ssp.user(_USER_UUID)
        u["roles"][0]["title"] = "MUTATED"
        # re-getting resolves fresh; the document's user has no `roles` key at all
        assert ssp.users()[0].get("roles") is None
        assert ssp.user(_USER_UUID)["roles"][0]["title"] == "Administrator"


# ===========================================================================
class TestProtocols:
    _WEB = "aaaaaaaa-0000-4000-8000-000000000001"
    _DB = "aaaaaaaa-0000-4000-8000-000000000002"

    def test_only_protocol_bearing_components(self, ssp):
        pp = ssp.protocols()
        assert {e["uuid"] for e in pp} == {self._WEB, self._DB}   # App (no protocols) excluded

    def test_entry_fields(self, ssp):
        web = next(e for e in ssp.protocols() if e["uuid"] == self._WEB)
        assert web["title"] == "Web"
        assert web["type"] == "software"
        assert web["asset-type"] == "web-server"            # from OSCAL-ns asset-type prop
        assert web["protocols"][0]["name"] == "https"
        assert web["protocols"][0]["port-ranges"][0]["start"] == 443

    def test_asset_type_empty_when_absent(self, ssp):
        db = next(e for e in ssp.protocols() if e["uuid"] == self._DB)
        assert db["asset-type"] == ""                        # no asset-type prop on this component
        assert db["protocols"][0]["name"] == "postgres"

    def test_empty_when_no_components(self):
        d = _ssp_dict()
        d["system-security-plan"]["system-implementation"].pop("components")
        assert OSCAL.loads(json.dumps(d)).protocols() == []

    def test_returns_safe_copy(self, ssp):
        pp = ssp.protocols()
        pp[0]["protocols"][0]["name"] = "MUTATED"
        again = next(e for e in ssp.protocols() if e["uuid"] == pp[0]["uuid"])
        assert again["protocols"][0]["name"] != "MUTATED"
