"""
Unit tests for SSP and implementation-specific methods:
    SSP class methods (require system-implementation / control-implementation sections):
    - SSP.append_component()
    - SSP.append_impl_requirement()
    - SSP.add_by_component()   (converted from a module function)

    Module-level entry points:
    - append_component()        (oscal_implementation module fn; delegates to the method)
    - append_impl_requirement() (oscal_implementation module fn; delegates to the method)
    - _append_responsible_role() (internal cross-model helper; returns a safe copy)

Note: SSP.new() produces a minimal SSP template that does NOT contain
system-implementation or control-implementation sections. Methods that
require those sections return None on a fresh SSP. These tests verify
the documented behavior: no exception is raised and the return value
signals failure via None.
"""
import os

import pytest

from oscal import OSCAL
from oscal.oscal_implementation import (
    SSP,
    append_component,
    append_impl_requirement,
    _append_responsible_role,
)

_HERE = os.path.dirname(__file__)
_SSP_FIXTURE = os.path.join(_HERE, "..", "test-data", "sanitized_ssp_oscal.json")


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def fresh_ssp():
    """Minimal SSP from SSP.new() — no system-implementation or control-implementation."""
    return SSP.new("Test SSP")


@pytest.fixture
def ssp_with_ir():
    """A loaded SSP plus the uuid of a freshly added implemented-requirement.

    Returns ``(ssp, impl_requirement_uuid)`` for exercising ``add_by_component``.
    """
    ssp = OSCAL.load(_SSP_FIXTURE)
    ir = ssp.append_impl_requirement("ac-by-comp-test")
    return ssp, ir["uuid"]


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
# SSP.add_by_component() — instance method (converted from a module function)
# ===========================================================================
class TestAddByComponent:

    def test_returns_dict(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        result = ssp.add_by_component(ir_uuid, "comp-uuid", "Description text.")
        assert isinstance(result, dict)

    def test_component_uuid_set(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        result = ssp.add_by_component(ir_uuid, "comp-xyz", "Desc")
        assert result.get("component-uuid") == "comp-xyz"

    def test_generated_uuid(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        result = ssp.add_by_component(ir_uuid, "comp", "Desc")
        assert result.get("uuid") not in (None, "")

    def test_explicit_uuid_used(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        explicit = "cccccccc-3333-4444-8555-666666666666"
        result = ssp.add_by_component(ir_uuid, "comp", "Desc", by_component_uuid=explicit)
        assert result.get("uuid") == explicit

    def test_has_description(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        result = ssp.add_by_component(ir_uuid, "comp", "Description text.")
        assert result.get("description") == "Description text."

    def test_default_status_is_implemented(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        result = ssp.add_by_component(ir_uuid, "comp", "Desc")
        assert result["implementation-status"]["state"] == "implemented"

    def test_custom_status(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        result = ssp.add_by_component(ir_uuid, "comp", "Desc", implementation_status="planned")
        assert result["implementation-status"]["state"] == "planned"

    def test_remarks(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        result = ssp.add_by_component(ir_uuid, "comp", "Desc", remarks="These are remarks.")
        assert result.get("remarks") == "These are remarks."

    def test_appended_to_impl_req(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        ssp.add_by_component(ir_uuid, "comp", "Desc")
        irs = ssp._dict["system-security-plan"]["control-implementation"]["implemented-requirements"]
        target = next(ir for ir in irs if ir["uuid"] == ir_uuid)
        assert len(target.get("by-components", [])) == 1

    def test_unknown_impl_req_returns_none(self, ssp_with_ir):
        ssp, _ = ssp_with_ir
        assert ssp.add_by_component("no-such-uuid", "comp", "Desc") is None

    def test_returns_safe_copy(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        bc = ssp.add_by_component(ir_uuid, "comp", "Desc")
        bc["description"] = "MUTATED"
        irs = ssp._dict["system-security-plan"]["control-implementation"]["implemented-requirements"]
        target = next(ir for ir in irs if ir["uuid"] == ir_uuid)
        assert all(b.get("description") != "MUTATED" for b in target["by-components"])

    def test_marks_unsaved(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        ssp.is_unsaved = False
        ssp.add_by_component(ir_uuid, "comp", "Desc")
        assert ssp.is_unsaved is True

    def test_read_only_guard(self, ssp_with_ir):
        ssp, ir_uuid = ssp_with_ir
        ssp.is_read_only = True
        assert ssp.add_by_component(ir_uuid, "comp", "Desc") is None


# ===========================================================================
# _append_responsible_role() — internal cross-model helper
# ===========================================================================
class TestAppendResponsibleRoleHelper:

    def test_returns_dict(self):
        assert isinstance(_append_responsible_role({}, "isso"), dict)

    def test_role_id_stored(self):
        assert _append_responsible_role({}, "system-owner")["role-id"] == "system-owner"

    def test_appended_to_parent(self):
        parent = {}
        _append_responsible_role(parent, "isso")
        assert len(parent.get("responsible-roles", [])) == 1

    def test_party_uuids_added(self):
        result = _append_responsible_role({}, "isso", party_uuids=["uuid-1111", "uuid-2222"])
        assert result.get("party-uuids") == ["uuid-1111", "uuid-2222"]

    def test_no_party_uuids_by_default(self):
        assert "party-uuids" not in _append_responsible_role({}, "isso")

    def test_remarks_added_when_provided(self):
        assert _append_responsible_role({}, "isso", remarks="Role remarks here.")["remarks"] \
            == "Role remarks here."

    def test_no_remarks_by_default(self):
        assert "remarks" not in _append_responsible_role({}, "isso")

    def test_multiple_roles_on_same_parent(self):
        parent = {}
        _append_responsible_role(parent, "isso")
        _append_responsible_role(parent, "system-owner")
        assert len(parent.get("responsible-roles", [])) == 2

    def test_returns_safe_copy(self):
        parent = {}
        rr = _append_responsible_role(parent, "isso", party_uuids=["u1"])
        rr["party-uuids"].append("INJECT")
        assert parent["responsible-roles"][0]["party-uuids"] == ["u1"]


# ===========================================================================
# Safe-copy ownership: SSP mutators return copies, not live _dict nodes
# ===========================================================================
class TestSSPMutatorReturnsCopy:
    """append_component()/append_impl_requirement() return a detached copy of the
    created node; mutating it must not change the SSP stored in _dict."""

    @staticmethod
    def _loaded_ssp():
        return OSCAL.load(_SSP_FIXTURE)

    def test_append_component_returns_copy(self):
        ssp = self._loaded_ssp()
        comp = ssp.append_component("software", "CopyTestComp", "Desc")
        assert comp is not None
        comp["title"] = "MUTATED"
        stored = ssp._dict["system-security-plan"]["system-implementation"]["components"]
        assert any(c.get("title") == "CopyTestComp" for c in stored)
        assert all(c.get("title") != "MUTATED" for c in stored)

    def test_append_impl_requirement_returns_copy(self):
        ssp = self._loaded_ssp()
        ir = ssp.append_impl_requirement("copy-test-ctl")
        assert ir is not None
        ir["control-id"] = "MUTATED"
        stored = ssp._dict["system-security-plan"]["control-implementation"]["implemented-requirements"]
        assert any(r.get("control-id") == "copy-test-ctl" for r in stored)
        assert all(r.get("control-id") != "MUTATED" for r in stored)


# ===========================================================================
# Mutations mark the document unsaved (is_unsaved)
# ===========================================================================
class TestMutationMarksUnsaved:
    """Every content mutation must set is_unsaved=True — including the module-level
    append_* entry points, which previously mutated _dict without flagging it."""

    @staticmethod
    def _loaded_ssp():
        ssp = OSCAL.load(_SSP_FIXTURE)
        ssp.is_unsaved = False   # baseline: pretend it was just saved
        return ssp

    def test_method_append_component(self):
        ssp = self._loaded_ssp()
        ssp.append_component("software", "C", "D")
        assert ssp.is_unsaved is True

    def test_method_append_impl_requirement(self):
        ssp = self._loaded_ssp()
        ssp.append_impl_requirement("ac-1")
        assert ssp.is_unsaved is True

    def test_module_append_component(self):
        ssp = self._loaded_ssp()
        append_component(ssp, "software", "C", "D")
        assert ssp.is_unsaved is True

    def test_module_append_impl_requirement(self):
        ssp = self._loaded_ssp()
        append_impl_requirement(ssp, "ac-1")
        assert ssp.is_unsaved is True

    def test_module_append_component_respects_read_only(self):
        ssp = self._loaded_ssp()
        ssp.is_read_only = True
        assert append_component(ssp, "software", "C", "D") is None
        assert ssp.is_unsaved is False   # nothing mutated -> stays saved
