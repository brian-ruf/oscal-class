"""
Functions specific to OSCAL implementation objects. (cDef and SSP)
"""
from loguru import logger
from xml.etree import ElementTree

from .oscal_content import *
from .oscal_markdown import oscal_markdown_to_html
from .oscal_content import oscal_markdown_to_html_tree

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class ComponentDefinition(OSCAL):
    """Class representing an OSCAL Component Definition (cDef) object."""
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class SSP(OSCAL):
    """Class representing an OSCAL System Security Plan (SSP) object.
    Inherits common OSCAL functionality and adds SSP-specific methods
    for managing components, implemented requirements, and by-component statements.
    """
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first


    # -------------------------------------------------------------------------
    @requires(read_only=False)
    @if_update_successful
    def append_component(self, component_type: str, component_title: str, component_description: str, op_status: str = "operational", component_uuid: str = "", props: list = [], links: list = [], remarks: str = "") -> (ElementTree.Element | None):
        """
        Adds a "component" to the SSP's system implementation section.
        """
        if component_uuid == "":
            component_uuid = new_uuid()

        try:
            component_obj = ElementTree.Element("component")
            component_obj.set("uuid", component_uuid)
            component_obj.set("type", component_type)

            description_obj = ElementTree.Element("description")
            description_element = oscal_markdown_to_html_tree(component_description, multiline=True)
            if description_element is not None:
                description_obj.append(description_element)
            component_obj.append(description_obj)

            implementation_status = ElementTree.Element("status")
            implementation_status.set("state", op_status)
            component_obj.append(implementation_status)

            system_implementation_obj = self.xpath("//system-implementation")
            if isinstance(system_implementation_obj, list) and len(system_implementation_obj) > 0:
                system_implementation_obj[0].append(component_obj)
                logger.debug(f"Adding component: {ElementTree.tostring(component_obj, 'utf-8')}")
            else:
                logger.error("Failed to find system-implementation element in SSP.")
                component_obj = None
        except (Exception, BaseException) as error:
            logger.error(f"Error appending component (type={component_type}) {component_title}: " + type(error).__name__ + " - " + str(error))
            component_obj = None

        return component_obj

    # -------------------------------------------------------------------------
    @requires(read_only=False)
    @if_update_successful
    def append_impl_requirement(self, control_id: str, props: list = [], links: list = [], remarks: str = "") -> (ElementTree.Element | None):
        """
        Adds an "implemented-requirement" to the SSP's control implementation section.
        """
        try:
            logger.debug("setting up implemented-requirement")
            impl_req_uuid = new_uuid()
            impl_req_obj = ElementTree.Element("implemented-requirement")
            impl_req_obj.set("uuid", impl_req_uuid)
            impl_req_obj.set("control-id", control_id)

            if remarks:
                logger.debug("Adding remarks")
                remarks_obj = ElementTree.Element("remarks")
                remarks_element = oscal_markdown_to_html_tree(remarks, multiline=True)
                if remarks_element is not None:
                    remarks_obj.append(remarks_element)
                impl_req_obj.append(remarks_obj)

            logger.debug("Fetching control-implementation element.")
            control_implementation_obj = self.xpath("//control-implementation")
            if isinstance(control_implementation_obj, list) and len(control_implementation_obj) > 0:
                logger.debug("Adding implemented-requirement")
                control_implementation_obj[0].append(impl_req_obj)
            else:
                logger.error("Failed to find control-implementation element in SSP.")
        except (Exception, BaseException) as error:
            logger.error(f"Error appending implemented-requirement for control: {control_id}: " + type(error).__name__ + " - " + str(error))
            impl_req_obj = None

        return impl_req_obj

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def append_component(ssp_obj: OSCAL, component_type: str, component_title: str, component_description: str, op_status: str = "operational", component_uuid: str = "", props: list = [], links: list = [], remarks: str = "") -> (ElementTree.Element | None):
    """
    Adds a "component" to an SSP's system implementation section.
    """
    if component_uuid == "":
        component_uuid = new_uuid()

    try:
        component_obj = ElementTree.Element("component") # Create the component element
        component_obj.set("uuid", component_uuid) # Set the component-uuid attribute
        component_obj.set("type", component_type) # Set the uuid attribute

        # Description
        description_obj = ElementTree.Element("description") # Create the description element
        # paragraph = ElementTree.Element("p")  # Need a p element as description is markup multi-line
        # paragraph.text = component_description
        # description.append(paragraph)


        description_element = oscal_markdown_to_html_tree(component_description, multiline=True)
        if description_element is not None:
            description_obj.append(description_element)

        component_obj.append(description_obj)

        # Implementation Status
        implementation_status = ElementTree.Element("status")
        implementation_status.set("state", op_status)
        component_obj.append(implementation_status)

        # TODO: props, links, responsible roles

        # # Responsibe Roles
        # responsible_roles = ElementTree.Element("responsible-role")
        # responsible_roles.set("role-id", "isso")
        # component_obj.append(responsible_roles)

        # # Party UUID
        # party_uuid = ElementTree.Element("party-uuid")
        # party_uuid.text = "11111111-2222-4000-8000-004000000008"
        # responsible_roles.append(party_uuid)

        system_imiplementation_obj = ssp_obj.xpath("//system-implementation")
        if isinstance(system_imiplementation_obj, list) and len(system_imiplementation_obj) > 0:
            system_imiplementation_obj[0].append(component_obj)
            logger.debug(f"Adding component: {ElementTree.tostring(component_obj, 'utf-8')}")
        else:
            logger.error("Failed to find system-implementation element in SSP.")
            component_obj = None
    except (Exception, BaseException) as error:
        logger.error(f"Error appending component (type={component_type}) {component_title}: " + type(error).__name__ + " - " + str(error))
        component_obj = None

    return component_obj

# -----------------------------------------------------------------------------
def append_impl_requirement(ssp_obj: OSCAL, control_id: str, props: list = [], links: list = [], remarks: str = "") -> (ElementTree.Element | None):
    """
    Adds an "imiplemented-requirement" to an SSP's control implementation section.
    """

    try:
        logger.debug("setting up imiplemented-requirement")
        impl_req_uuid = new_uuid()
        impl_req_obj = ElementTree.Element("implemented-requirement") # Create the component element
        impl_req_obj.set("uuid", impl_req_uuid) # Set the component-uuid attribute
        impl_req_obj.set("control-id", control_id) # Set the uuid attribute

        # TODO: props, links, responsible roles

        # Remarks
        if remarks:
            logger.debug("Adding remarks")
            remarks_obj = ElementTree.Element("remarks") # Create the description element

            remarks_element = oscal_markdown_to_html_tree(remarks, multiline=True)
            if remarks_element is not None:
                remarks_obj.append(remarks_element)
            impl_req_obj.append(remarks_obj)

        logger.debug("Fetching control-implementation element.")
        system_imiplementation_obj = ssp_obj.xpath("//control-implementation")
        if isinstance(system_imiplementation_obj, list) and len(system_imiplementation_obj) > 0:
            logger.debug("Adding implemented-requirement")
            system_imiplementation_obj[0].append(impl_req_obj)
        else:
            logger.error("Failed to find system-implementation element in SSP.")
    except (Exception, BaseException) as error:
        logger.error(f"Error appending implemented-requirement for control: {control_id}: " + type(error).__name__ + " - " + str(error))
        impl_req_obj = None

    return impl_req_obj


# -----------------------------------------------------------------------------
def append_by_component(impl_req_obj: ElementTree.Element, component_uuid: str, description: str, by_component_uuid: str = "", implementation_status: str = "implemented", remarks: str = "") -> (ElementTree.Element | None):
    """
    Adds a "by-component" statement to an SSP's contrtol response statement.

    """
    logger.debug("Appending by-component assembly")
    if by_component_uuid == "":
        logger.debug("Generating new UUID for by-component")
        by_component_uuid = new_uuid()

    try:
        logger.debug("Appending by-component")
        by_component_obj = ElementTree.Element("by-component") # Create the by-component element
        by_component_obj.set("component-uuid", component_uuid) # Set the component-uuid attribute
        by_component_obj.set("uuid", by_component_uuid) # Set the uuid attribute

        logger.debug("Appending by-component description")
        # Description
        description_obj = ElementTree.Element("description") # Create the description element

        description_element = oscal_markdown_to_html_tree(description, multiline=True)
        if description_element is not None:
            description_obj.append(description_element)

        by_component_obj.append(description_obj)

        logger.debug("Appending by-component implementation status")
        # Implementation Status
        implementation_status_obj = ElementTree.Element("implementation-status")
        implementation_status_obj.set("state", implementation_status)
        by_component_obj.append(implementation_status_obj)

        if remarks:
            logger.debug("Adding remarks")
            remarks_obj = ElementTree.Element("remarks") # Create the description element


            remarks_element = oscal_markdown_to_html_tree(remarks, multiline=True)
            if remarks_element is not None:
                remarks_obj.append(remarks_element)
            by_component_obj.append(remarks_obj)

        logger.debug("Appending by-component to implemented-requirement")
        impl_req_obj.append(by_component_obj)
    except (Exception, BaseException) as error:
        logger.error("Error appending by-component: " + type(error).__name__ + " - " + str(error))
        by_component_obj = None

    return by_component_obj

# -----------------------------------------------------------------------------
def append_responsible_role(oscal_obj: ElementTree.Element, role_id: str, party_uuids: list = [], remarks: str = "") -> ElementTree.Element:
    """
    Adds a "responsible-role" statement to an object.
    """
    logger.debug("Appending 'responsible-role' implementation status")
    # Implementation Status
    resp_role_obj = ElementTree.Element("responsible-role")
    resp_role_obj.set("role-id", role_id)
    oscal_obj.append(resp_role_obj)

    for party_uuid in party_uuids:
        party_uuid_obj = ElementTree.Element("party-uuid")
        party_uuid_obj.text = party_uuid
        resp_role_obj.append(party_uuid_obj)

    if remarks != "":
        logger.debug("Adding remarks")
        remarks_obj = ElementTree.Element("remarks") # Create the description element

        remarks_element = oscal_markdown_to_html_tree(remarks, multiline=True)
        if remarks_element is not None:
            remarks_obj.append(remarks_element)
        resp_role_obj.append(remarks_obj)

    return resp_role_obj

