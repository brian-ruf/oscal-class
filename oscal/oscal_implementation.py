"""
oscal_implementation — OSCAL implementation-layer model classes and helpers.

Provides the model classes for the OSCAL implementation models:
``ComponentDefinition`` (reusable control implementations for components) and
``SSP`` (System Security Plan). Both subclass ``OSCAL`` from ``oscal_content``.
Module-level helper functions build the nested SSP assemblies (components,
implemented requirements, by-component statements, responsible roles) and are
also exposed as ``SSP`` methods where appropriate.

Module constants:
    (none exported)
"""
from __future__ import annotations
import copy
import logging
from typing import Any, Optional

from .oscal_content import OSCAL, requires, if_update_successful, new_uuid, append_props, append_links, register_model

logger = logging.getLogger(__name__)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class ComponentDefinition(OSCAL):
    """OSCAL Component Definition (cDef) model.

    Represents reusable component definitions that describe how components
    satisfy controls. Subclasses ``OSCAL``.
    """
    def _init_common(self):
        super()._init_common()

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class SSP(OSCAL):
    """OSCAL System Security Plan (SSP) model.

    Subclasses ``OSCAL`` and adds SSP-specific methods for managing system
    components, implemented requirements, and by-component statements.
    """
    def _init_common(self):
        super()._init_common()

    def _ssp_root(self) -> dict[str, Any]:
        if not isinstance(self._dict, dict):
            return {}
        ssp = self._dict.get("system-security-plan")
        return ssp if isinstance(ssp, dict) else {}

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def append_component(self, component_type: str, component_title: str, component_description: str, op_status: str = "operational", component_uuid: str = "", props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
        """
        Add a component to the SSP's ``system-implementation`` section.

        Args:
            component_type (str, required): The component ``type`` (e.g. "software").
            component_title (str, required): The component title.
            component_description (str, required): The component description.
            op_status (str, optional): Operational ``status.state`` value.
                Defaults to "operational".
            component_uuid (str, optional): UUID for the component. A new UUID is
                generated when empty.
            props (list, optional): Property dicts to add.
            links (list, optional): Link dicts to add.
            remarks (str, optional): Remarks prose (markdown).

        Returns:
            Optional[dict]: The newly created component dict, or None on failure.
        """
        if component_uuid == "":
            component_uuid = new_uuid()
        try:
            component = {
                "uuid": component_uuid,
                "type": component_type,
                "title": component_title,
                "description": component_description,
                "status": {"state": op_status},
            }
            if props:
                append_props(component, props)
            if links:
                append_links(component, links)
            if remarks:
                component["remarks"] = remarks

            ssp = self._ssp_root()
            if "system-implementation" not in ssp:
                logger.error("Failed to find system-implementation section in SSP.")
                return None
            ssp["system-implementation"].setdefault("components", []).append(component)
            logger.debug(f"Adding component: {component_uuid} ({component_type})")
        except Exception as error:
            logger.error(f"Error appending component (type={component_type}) {component_title}: {type(error).__name__} - {error}")
            component = None
        # Return a safe copy — the live component stays in _dict; further edits go through methods.
        return copy.deepcopy(component)

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def append_impl_requirement(self, control_id: str, props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
        """
        Add an implemented-requirement to the SSP's ``control-implementation`` section.

        Args:
            control_id (str, required): The ID of the control being implemented.
            props (list, optional): Property dicts to add.
            links (list, optional): Link dicts to add.
            remarks (str, optional): Remarks prose (markdown).

        Returns:
            Optional[dict]: The newly created implemented-requirement dict (with a
                generated UUID), or None on failure.
        """
        try:
            impl_req = {
                "uuid": new_uuid(),
                "control-id": control_id,
            }
            if props:
                append_props(impl_req, props)
            if links:
                append_links(impl_req, links)
            if remarks:
                impl_req["remarks"] = remarks

            ssp = self._ssp_root()
            if "control-implementation" not in ssp:
                logger.error("Failed to find control-implementation section in SSP.")
                return None
            ssp["control-implementation"].setdefault("implemented-requirements", []).append(impl_req)
            logger.debug(f"Adding implemented-requirement for control: {control_id}")
        except Exception as error:
            logger.error(f"Error appending implemented-requirement for control {control_id}: {type(error).__name__} - {error}")
            impl_req = None
        # Return a safe copy — the live impl-requirement stays in _dict; edits go through methods.
        return copy.deepcopy(impl_req)

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def add_by_component(self, implemented_requirement_uuid: str, component_uuid: str,
                         description: str, by_component_uuid: str = "",
                         implementation_status: str = "implemented",
                         remarks: str = "") -> Optional[dict]:
        """Add a by-component statement to one of the SSP's implemented-requirements.

        The by-component is **built from the supplied scalar fields** — no caller-provided
        dict is stored verbatim — so it is schema-aligned by construction. It is appended
        to the implemented-requirement identified by *implemented_requirement_uuid* and
        returned as a safe copy (the live node stays in ``_dict``; further edits go through
        methods). Through the method decorators this also enforces the read-only guard and
        marks the document unsaved.

        Args:
            implemented_requirement_uuid (str, required): ``uuid`` of the target
                implemented-requirement under ``control-implementation``.
            component_uuid (str, required): UUID of the referenced system component.
            description (str, required): How the component satisfies the requirement.
            by_component_uuid (str, optional): UUID for the by-component; a new one is
                generated when empty.
            implementation_status (str, optional): ``implementation-status.state`` value.
                Defaults to "implemented".
            remarks (str, optional): Remarks prose (markdown).

        Returns:
            Optional[dict]: A safe copy of the new by-component, or None when the SSP has
                no implemented-requirement with that uuid.
        """
        impl_reqs = (self._ssp_root().get("control-implementation", {})
                     .get("implemented-requirements", []))
        target = next((ir for ir in impl_reqs
                       if isinstance(ir, dict)
                       and ir.get("uuid") == implemented_requirement_uuid), None)
        if target is None:
            logger.error("add_by_component: no implemented-requirement with uuid "
                         f"'{implemented_requirement_uuid}'.")
            return None

        by_component: dict[str, Any] = {
            "component-uuid": component_uuid,
            "uuid": by_component_uuid or new_uuid(),
            "description": description,
            "implementation-status": {"state": implementation_status},
        }
        if remarks:
            by_component["remarks"] = remarks

        target.setdefault("by-components", []).append(by_component)
        # Return a safe copy — the live by-component stays in _dict; edits go through methods.
        return copy.deepcopy(by_component)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def append_component(ssp_obj: OSCAL, component_type: str, component_title: str, component_description: str, op_status: str = "operational", component_uuid: str = "", props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
    """
    Add a component to an SSP's ``system-implementation`` section.

    Args:
        ssp_obj (OSCAL, required): The SSP instance to modify.
        component_type (str, required): The component ``type`` (e.g. "software").
        component_title (str, required): The component title.
        component_description (str, required): The component description.
        op_status (str, optional): Operational ``status.state`` value.
            Defaults to "operational".
        component_uuid (str, optional): UUID for the component. A new UUID is
            generated when empty.
        props (list, optional): Property dicts to add.
        links (list, optional): Link dicts to add.
        remarks (str, optional): Remarks prose (markdown).

    Returns:
        Optional[dict]: The newly created component dict, or None on failure.
    """
    # Delegate to the SSP instance method, which performs the mutation and — through its
    # decorators — the read-only guard, dirty-state bookkeeping (``is_unsaved`` /
    # ``last_modified``), and safe-copy return. Kept as a module-level convenience so the
    # two entry points can never drift (previously this duplicated the body and, notably,
    # never marked the document unsaved).
    return ssp_obj.append_component(
        component_type, component_title, component_description,
        op_status=op_status, component_uuid=component_uuid,
        props=props, links=links, remarks=remarks,
    )

# -----------------------------------------------------------------------------
def append_impl_requirement(ssp_obj: OSCAL, control_id: str, props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
    """
    Add an implemented-requirement to an SSP's ``control-implementation`` section.

    Args:
        ssp_obj (OSCAL, required): The SSP instance to modify.
        control_id (str, required): The ID of the control being implemented.
        props (list, optional): Property dicts to add.
        links (list, optional): Link dicts to add.
        remarks (str, optional): Remarks prose (markdown).

    Returns:
        Optional[dict]: The newly created implemented-requirement dict (with a
            generated UUID), or None on failure.
    """
    # Delegate to the SSP instance method (see append_component above): it handles the
    # mutation plus the read-only guard, dirty-state bookkeeping (``is_unsaved`` /
    # ``last_modified``), and safe-copy return, so the two entry points cannot drift.
    return ssp_obj.append_impl_requirement(
        control_id, props=props, links=links, remarks=remarks,
    )

# -----------------------------------------------------------------------------
def _append_responsible_role(parent: dict, role_id: str, party_uuids: list = [], remarks: str = "") -> dict:
    """Append a responsible-role to *parent* and return a safe copy of it.

    Internal helper (underscore-prefixed): ``responsible-role`` appears in many places —
    SSP/cDef components, AP/AR tasks, and ``local-definitions/components`` of AP/AR/POA&M —
    so this stays a small, model-agnostic builder rather than a method. It is **not** a
    public entry point and does no dirty-state or read-only bookkeeping: the *calling
    method* owns those, mutating live ``_dict`` content only after its own guards. The role
    is built from the supplied scalar fields (schema-aligned by construction — no caller
    dict is stored verbatim) and a **copy** is returned, never the live appended object.

    Args:
        parent (dict, required): The live parent dict to add ``responsible-roles`` to.
        role_id (str, required): The ID of the role being assigned.
        party_uuids (list, optional): UUIDs of the parties fulfilling the role.
        remarks (str, optional): Remarks prose (markdown).

    Returns:
        dict: A safe copy of the newly created responsible-role.
    """
    resp_role: dict[str, Any] = {"role-id": role_id}
    if party_uuids:
        resp_role["party-uuids"] = [str(u) for u in party_uuids]
    if remarks:
        resp_role["remarks"] = remarks

    parent.setdefault("responsible-roles", []).append(resp_role)
    # Never hand back the live appended object — callers get a detached copy.
    return copy.deepcopy(resp_role)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Register model classes so OSCAL factory methods return typed instances.
register_model("component-definition", ComponentDefinition)
register_model("system-security-plan", SSP)
