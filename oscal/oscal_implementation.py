"""
Functions specific to OSCAL implementation objects. (cDef and SSP)
"""
from __future__ import annotations
from loguru import logger
from typing import Any, Optional

from .oscal_content import OSCAL, requires, if_update_successful, new_uuid, append_props, append_links

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class ComponentDefinition(OSCAL):
    """Class representing an OSCAL Component Definition (cDef) object."""
    def _init_common(self):
        super()._init_common()

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class SSP(OSCAL):
    """Class representing an OSCAL System Security Plan (SSP) object.
    Inherits common OSCAL functionality and adds SSP-specific methods
    for managing components, implemented requirements, and by-component statements.
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
        Adds a "component" to the SSP's system implementation section.
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
        return component

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def append_impl_requirement(self, control_id: str, props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
        """
        Adds an "implemented-requirement" to the SSP's control implementation section.
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
        return impl_req

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def append_component(ssp_obj: OSCAL, component_type: str, component_title: str, component_description: str, op_status: str = "operational", component_uuid: str = "", props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
    """
    Adds a "component" to an SSP's system implementation section.
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

        ssp_root = ssp_obj._dict if isinstance(ssp_obj._dict, dict) else {}
        ssp = ssp_root.get("system-security-plan", {})
        if "system-implementation" not in ssp:
            logger.error("Failed to find system-implementation section in SSP.")
            return None
        ssp["system-implementation"].setdefault("components", []).append(component)
        logger.debug(f"Adding component: {component_uuid} ({component_type})")
    except Exception as error:
        logger.error(f"Error appending component (type={component_type}) {component_title}: {type(error).__name__} - {error}")
        component = None
    return component

# -----------------------------------------------------------------------------
def append_impl_requirement(ssp_obj: OSCAL, control_id: str, props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
    """
    Adds an "implemented-requirement" to an SSP's control implementation section.
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

        ssp_root = ssp_obj._dict if isinstance(ssp_obj._dict, dict) else {}
        ssp = ssp_root.get("system-security-plan", {})
        if "control-implementation" not in ssp:
            logger.error("Failed to find control-implementation section in SSP.")
            return None
        ssp["control-implementation"].setdefault("implemented-requirements", []).append(impl_req)
        logger.debug(f"Adding implemented-requirement for control: {control_id}")
    except Exception as error:
        logger.error(f"Error appending implemented-requirement for control {control_id}: {type(error).__name__} - {error}")
        impl_req = None
    return impl_req

# -----------------------------------------------------------------------------
def append_by_component(impl_req_obj: dict, component_uuid: str, description: str, by_component_uuid: str = "", implementation_status: str = "implemented", remarks: str = "") -> Optional[dict]:
    """
    Adds a "by-component" statement to an implemented-requirement dict.
    """
    logger.debug("Appending by-component assembly")
    if by_component_uuid == "":
        logger.debug("Generating new UUID for by-component")
        by_component_uuid = new_uuid()
    try:
        by_component = {
            "component-uuid": component_uuid,
            "uuid": by_component_uuid,
            "description": description,
            "implementation-status": {"state": implementation_status},
        }
        if remarks:
            by_component["remarks"] = remarks

        impl_req_obj.setdefault("by-components", []).append(by_component)
        logger.debug(f"Appended by-component {by_component_uuid}")
    except Exception as error:
        logger.error(f"Error appending by-component: {type(error).__name__} - {error}")
        by_component = None
    return by_component

# -----------------------------------------------------------------------------
def append_responsible_role(oscal_obj: dict, role_id: str, party_uuids: list = [], remarks: str = "") -> dict:
    """
    Adds a "responsible-role" to an OSCAL object dict.
    """
    logger.debug("Appending 'responsible-role'")
    resp_role: dict[str, Any] = {"role-id": role_id}
    if party_uuids:
        resp_role["party-uuids"] = list(party_uuids)
    if remarks:
        resp_role["remarks"] = remarks

    oscal_obj.setdefault("responsible-roles", []).append(resp_role)
    return resp_role
