"""
Unit tests for SSP and implementation-specific methods:
    SSP class methods (require system-implementation / control-implementation sections):
    - SSP.append_component()
    - SSP.append_impl_requirement()

    Module-level functions (take raw dict or SSP object):
    - append_component()      (oscal_implementation module fn)
    - append_impl_requirement() (oscal_implementation module fn)
    - append_by_component()
    - append_responsible_role()

Note: SSP.new() produces a minimal SSP template that does NOT contain
system-implementation or control-implementation sections. Methods that
require those sections return None on a fresh SSP. These tests verify
the documented behavior: no exception is raised and the return value
signals failure via None.
"""
import pytest

from oscal.oscal_implementation import (
    SSP,
    append_by_component,
    append_component,
    append_impl_requirement,
    append_responsible_role,
)


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def fresh_ssp():
    """Minimal SSP from SSP.new() — no system-implementation or control-implementation."""
    return SSP.new("Test SSP")


@pytest.fixture
def impl_req_dict():
    """A bare implemented-requirement dict for use with append_by_component."""
    return {
        "uuid": "aaaaaaaa-bbbb-4ccc-8ddd-ffffffffffff",
        "control-id": "ac-1",
    }


# ===========================================================================
# SSP.append_component() — instance method
# ===========================================================================
class TestSSPAppendComponent:

    def test_does_not_raise_on_fresh_ssp(self, fresh_ssp):
        """SSP.append_component() must not raise even when system-implementation is absent."""
        try:
            fresh_ssp.append_component("software", "My Component", "A test component")
        except Exception:
            pytest.fail("SSP.append_component() raised unexpectedly on a fresh SSP")

    def test_returns_none_without_system_implementation(self, fresh_ssp):
        """SSP.append_component() returns None when system-implementation section is missing."""
        result = fresh_ssp.append_component("software", "My Component", "A test component")
        assert result is None

    def test_accepts_op_status(self, fresh_ssp):
        """SSP.append_component() accepts an op_status argument without raising."""
        try:
            fresh_ssp.append_component("software", "Comp", "Desc", op_status="planned")
        except Exception:
            pytest.fail("SSP.append_component() raised on op_status argument")

    def test_accepts_custom_uuid(self, fresh_ssp):
        """SSP.append_component() accepts a custom uuid without raising."""
        uuid = "11111111-2222-4333-8444-555555555555"
        try:
            fresh_ssp.append_component("software", "Comp", "Desc", component_uuid=uuid)
        except Exception:
            pytest.fail("SSP.append_component() raised on custom uuid")


# ===========================================================================
# SSP.append_impl_requirement() — instance method
# ===========================================================================
class TestSSPAppendImplRequirement:

    def test_does_not_raise_on_fresh_ssp(self, fresh_ssp):
        """SSP.append_impl_requirement() must not raise even when control-implementation is absent."""
        try:
            fresh_ssp.append_impl_requirement("ac-1")
        except Exception:
            pytest.fail("SSP.append_impl_requirement() raised unexpectedly on a fresh SSP")

    def test_returns_dict_or_none(self, fresh_ssp):
        """SSP.append_impl_requirement() returns a dict or None (not raises)."""
        result = fresh_ssp.append_impl_requirement("ac-2")
        assert result is None or isinstance(result, dict)

    def test_accepts_remarks(self, fresh_ssp):
        """SSP.append_impl_requirement() accepts remarks without raising."""
        try:
            fresh_ssp.append_impl_requirement("ac-3", remarks="Remark text.")
        except Exception:
            pytest.fail("SSP.append_impl_requirement() raised on remarks argument")


# ===========================================================================
# Module-level append_component()
# ===========================================================================
class TestModuleAppendComponent:

    def test_does_not_raise_on_fresh_ssp(self, fresh_ssp):
        """Module-level append_component() must not raise on a fresh SSP."""
        try:
            append_component(fresh_ssp, "software", "My Component", "A test component")
        except Exception:
            pytest.fail("Module-level append_component() raised unexpectedly")

    def test_returns_none_without_system_implementation(self, fresh_ssp):
        """Module-level append_component() returns None when system-implementation is absent."""
        result = append_component(fresh_ssp, "software", "My Component", "Desc")
        assert result is None

    def test_accepts_op_status_argument(self, fresh_ssp):
        """Module-level append_component() accepts op_status without raising."""
        try:
            append_component(fresh_ssp, "firmware", "Comp", "Desc", op_status="under-development")
        except Exception:
            pytest.fail("Module-level append_component() raised on op_status argument")

    def test_accepts_custom_uuid(self, fresh_ssp):
        """Module-level append_component() accepts an explicit UUID without raising."""
        uuid = "22222222-3333-4444-8555-666666666666"
        try:
            append_component(fresh_ssp, "software", "Comp", "Desc", component_uuid=uuid)
        except Exception:
            pytest.fail("Module-level append_component() raised on custom uuid")


# ===========================================================================
# Module-level append_impl_requirement()
# ===========================================================================
class TestModuleAppendImplRequirement:

    def test_does_not_raise_on_fresh_ssp(self, fresh_ssp):
        """Module-level append_impl_requirement() must not raise on a fresh SSP."""
        try:
            append_impl_requirement(fresh_ssp, "ac-1")
        except Exception:
            pytest.fail("Module-level append_impl_requirement() raised unexpectedly")

    def test_returns_dict_or_none(self, fresh_ssp):
        """Module-level append_impl_requirement() returns a dict or None (not raises)."""
        result = append_impl_requirement(fresh_ssp, "ac-2")
        assert result is None or isinstance(result, dict)

    def test_accepts_remarks(self, fresh_ssp):
        """Module-level append_impl_requirement() accepts remarks without raising."""
        try:
            append_impl_requirement(fresh_ssp, "ac-3", remarks="Test remark.")
        except Exception:
            pytest.fail("Module-level append_impl_requirement() raised on remarks")


# ===========================================================================
# append_by_component()
# ===========================================================================
class TestAppendByComponent:

    def test_returns_dict(self, impl_req_dict):
        """append_by_component() returns a dict."""
        comp_uuid = "aaaaaaaa-1111-4222-8333-444444444444"
        result = append_by_component(impl_req_dict, comp_uuid, "Description text.")
        assert result is not None
        assert isinstance(result, dict)

    def test_component_uuid_set(self, impl_req_dict):
        """append_by_component() stores the component-uuid."""
        comp_uuid = "bbbbbbbb-2222-4333-8444-555555555555"
        result = append_by_component(impl_req_dict, comp_uuid, "Desc")
        assert result.get("component-uuid") == comp_uuid

    def test_uuid_set(self, impl_req_dict):
        """append_by_component() sets a uuid on the result."""
        result = append_by_component(impl_req_dict, "comp-uuid", "Desc")
        assert result.get("uuid") not in (None, "")

    def test_explicit_uuid_used(self, impl_req_dict):
        """append_by_component() uses the provided by_component_uuid."""
        explicit_uuid = "cccccccc-3333-4444-8555-666666666666"
        result = append_by_component(impl_req_dict, "comp-uuid", "Desc",
                                     by_component_uuid=explicit_uuid)
        assert result.get("uuid") == explicit_uuid

    def test_has_description(self, impl_req_dict):
        """append_by_component() stores the description string."""
        result = append_by_component(impl_req_dict, "comp-uuid", "Description text.")
        assert result.get("description") == "Description text."

    def test_has_implementation_status(self, impl_req_dict):
        """append_by_component() adds an implementation-status dict."""
        result = append_by_component(impl_req_dict, "comp-uuid", "Desc")
        assert "implementation-status" in result

    def test_implementation_status_default_is_implemented(self, impl_req_dict):
        """append_by_component() defaults implementation_status to 'implemented'."""
        result = append_by_component(impl_req_dict, "comp-uuid", "Desc")
        assert result["implementation-status"]["state"] == "implemented"

    def test_custom_implementation_status(self, impl_req_dict):
        """append_by_component() sets a custom implementation_status."""
        result = append_by_component(impl_req_dict, "comp-uuid", "Desc",
                                     implementation_status="planned")
        assert result["implementation-status"]["state"] == "planned"

    def test_remarks_added_when_provided(self, impl_req_dict):
        """append_by_component() stores remarks when provided."""
        result = append_by_component(impl_req_dict, "comp-uuid", "Desc",
                                     remarks="These are remarks.")
        assert result.get("remarks") == "These are remarks."

    def test_appended_to_impl_req(self, impl_req_dict):
        """append_by_component() appends itself to impl_req's by-components list."""
        before = len(impl_req_dict.get("by-components", []))
        append_by_component(impl_req_dict, "comp-uuid", "Desc")
        after = len(impl_req_dict.get("by-components", []))
        assert after == before + 1


# ===========================================================================
# append_responsible_role()
# ===========================================================================
class TestAppendResponsibleRole:

    def test_returns_dict(self):
        """append_responsible_role() returns a dict."""
        parent = {}
        result = append_responsible_role(parent, "isso")
        assert result is not None
        assert isinstance(result, dict)

    def test_role_id_stored(self):
        """append_responsible_role() stores the role-id."""
        parent = {}
        result = append_responsible_role(parent, "system-owner")
        assert result.get("role-id") == "system-owner"

    def test_appended_to_parent(self):
        """append_responsible_role() appends the role to parent's responsible-roles list."""
        parent = {}
        before = len(parent.get("responsible-roles", []))
        append_responsible_role(parent, "isso")
        after = len(parent.get("responsible-roles", []))
        assert after == before + 1

    def test_party_uuids_added(self):
        """append_responsible_role() stores the party-uuids list."""
        parent = {}
        uuids = ["uuid-1111", "uuid-2222"]
        result = append_responsible_role(parent, "isso", party_uuids=uuids)
        assert result.get("party-uuids") == ["uuid-1111", "uuid-2222"]

    def test_no_party_uuids_by_default(self):
        """append_responsible_role() with no party_uuids omits the key."""
        parent = {}
        result = append_responsible_role(parent, "isso")
        assert "party-uuids" not in result

    def test_remarks_added_when_provided(self):
        """append_responsible_role() stores remarks when provided."""
        parent = {}
        result = append_responsible_role(parent, "isso", remarks="Role remarks here.")
        assert result.get("remarks") == "Role remarks here."

    def test_no_remarks_by_default(self):
        """append_responsible_role() with no remarks omits the key."""
        parent = {}
        result = append_responsible_role(parent, "isso")
        assert "remarks" not in result

    def test_multiple_roles_on_same_parent(self):
        """append_responsible_role() can be called multiple times on the same parent."""
        parent = {}
        append_responsible_role(parent, "isso")
        append_responsible_role(parent, "system-owner")
        assert len(parent.get("responsible-roles", [])) == 2
