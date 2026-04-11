"""
Functions specific to OSCAL implementation objects. (cDef and SSP)
"""
from loguru import logger
from xml.etree import ElementTree

from .oscal_content_class import OSCAL, new_uuid, OSCAL_DEFAULT_XML_NAMESPACE
from .oscal_markdown import oscal_markdown_to_html
from .oscal_content_class import oscal_markdown_to_html_tree


class ComponentDefinition(OSCAL):
    """Class representing an OSCAL Component Definition (cDef) object."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __repr__(self):
        return f"OSCAL Component Definition: {self.content_title}"

    def __str__(self):
        return f"OSCAL Component Definition: {self.content_title}"


class SSP(OSCAL):
    """Class representing an OSCAL System Security Plan (SSP) object.
    Inherits common OSCAL functionality and adds SSP-specific methods
    for managing components, implemented requirements, and by-component statements.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __repr__(self):
        return f"OSCAL SSP: {self.content_title}"

    def __str__(self):
        return f"OSCAL SSP: {self.content_title}"

    # -------------------------------------------------------------------------
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
