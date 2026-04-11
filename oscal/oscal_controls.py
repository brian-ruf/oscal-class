"""
Functions specific to OSCAL control objects. (Catalog, Profile, and Controls)
"""
from loguru import logger
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree

from .oscal_content_class import OSCAL, append_props, append_links, OSCAL_DEFAULT_XML_NAMESPACE
from .oscal_markdown import oscal_markdown_to_html


class CatalogBase(OSCAL):
    """Base class for OSCAL Catalog-syntax content.
    Provides read-only catalog query methods shared by both Catalog and Controls.
    Inherits common OSCAL functionality (validate, convert, save, serialize, xpath).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __repr__(self):
        return f"OSCAL Catalog: {self.content_title}"

    def __str__(self):
        return f"OSCAL Catalog: {self.content_title}"

    def __len__(self):
        """Return the number of top-level controls in the catalog."""
        controls = self.xpath("//control")
        return len(controls) if controls else 0


class Catalog(CatalogBase):
    """Class representing an editable OSCAL Catalog object.
    Inherits read-only catalog functionality from CatalogBase and adds
    methods for creating and managing controls and control groups.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # -------------------------------------------------------------------------
    def create_control(self, parent_id: str, id: str, title: str = "", params: list = [], props: list = [], links: list = [], label: str = "", sort_id: str = "", alt_identifier: str = "", overview: str = "", statements: list = [], guidance: str = "", example: str = "", objectives: list = [], objects: list = [], methods: list = [], remarks: str = ""):
        """
        Creates a new control under the specified parent group.
        Parameters:
        - parent_id (str): The id of the parent group to which this new control will be added.
        - id (str): The id of the new control.
        - title (str): The title of the new control.
        - params (array): A dictionary of parameters to add to the control.
        - props (array): A dictionary of properties to add to the control.
        - links (array): A dictionary of links to add to the control.
        - overview (str): An overview of the control.
        - statements (dict): The control's requirement statement.
        - guidance (str): Guidance for understanding the new control.
        - objectives (array): A list of assessment objectives for the new control.
        - objects (array): A dictionary of assessment objects to add to the control.
        - methods (array): A dictionary of assessment methods to add to the control.
        - remarks (str): The remarks of the new control.
        """
        logger.info(f"Creating new control with id '{id}' under parent group '{parent_id}'")
        status = False
        control = None
        try:
            parent_xpath = f"//group[@id='{parent_id}']"
            logger.debug(f"Creating control under parent id: {parent_id}")

            parent_nodes = self.xpath(parent_xpath)
            parent_node = parent_nodes[0] if parent_nodes else None
            if parent_node is not None:
                logger.debug("TAG: " + parent_node.tag)
                control = ElementTree.Element(f"{{{OSCAL_DEFAULT_XML_NAMESPACE}}}control")
                control.set("id", id)

                title_node = ElementTree.SubElement(control, "title")
                if title == "":
                    if label != "":
                        title = label
                    else:
                        title = id
                title_node.text = title

                if label != "":
                    label_node = ElementTree.SubElement(control, "prop")
                    label_node.set("name", "label")
                    label_node.set("value", label)

                if sort_id != "":
                    sort_id_node = ElementTree.SubElement(control, "prop")
                    sort_id_node.set("name", "sort-id")
                    sort_id_node.set("value", sort_id)

                if alt_identifier != "":
                    alt_id_node = ElementTree.SubElement(control, "prop")
                    alt_id_node.set("name", "alt-identifier")
                    alt_id_node.set("value", alt_identifier)

                for param in params:
                    param_node = ElementTree.SubElement(control, "param")
                    param_node.set("id", param)

                append_props(control, props)
                append_links(control, links)

                if overview != "":
                    overview_node = ElementTree.SubElement(control, "part")
                    overview_node.set("name", "overview")
                    self.assign_html_string_to_node(overview_node, oscal_markdown_to_html(overview, True))

                if len(statements) > 0:
                    statement_node = ElementTree.SubElement(control, "part")
                    statement_node.set("name", "statement")
                    statement_node.set("id", f"{id}_smt")
                    logger.debug(f"STATEMENTS TYPE: {type(statements)} with {len(statements)} items.")
                    if len(statements) == 1:
                        if isinstance(statements[0], str):
                            logger.debug("Single statement without id detected.")
                            self.assign_html_string_to_node(statement_node, oscal_markdown_to_html(statements[0], True))
                        elif isinstance(statements[0], dict):
                            logger.debug("Single statement with id detected.")
                            statement_item = statements[0]
                            item_node = ElementTree.SubElement(statement_node, "part")
                            item_node.set("name", "item")
                            if statement_item.get('id', "") != "":
                                item_node.set("id", f"{id}_smt_01")
                            self.assign_html_string_to_node(item_node, oscal_markdown_to_html(statement_item['prose'], True))
                    else:
                        smt_cntr = 0
                        for item in statements:
                            smt_cntr += 1
                            statement_child_node = ElementTree.SubElement(statement_node, "part")
                            statement_child_node.set("name", "item")
                            if item.get('id', "") != "":
                                statement_child_node.set("id", f"{id}_smt_{smt_cntr:02d}")
                            self.assign_html_string_to_node(statement_child_node, oscal_markdown_to_html(item['prose'], True))

                if guidance != "":
                    guidance_node = ElementTree.SubElement(control, "part")
                    guidance_node.set("name", "guidance")
                    self.assign_html_string_to_node(guidance_node, oscal_markdown_to_html(guidance, True))

                if example != "":
                    example_node = ElementTree.SubElement(control, "part")
                    example_node.set("name", "example")
                    self.assign_html_string_to_node(example_node, oscal_markdown_to_html(example, True))

                if remarks != "":
                    remarks_node = ElementTree.SubElement(control, "remarks")
                    self.assign_html_string_to_node(remarks_node, oscal_markdown_to_html(remarks, True))
                parent_node.append(control)
                self.content_modified()
                status = True
            else:
                logger.warning(f"CREATE CONTROL: Unable to find parent group with id {parent_id}")
        except Exception as error:
            logger.error(f"Error creating control ({id}): {type(error).__name__} - {str(error)}")

        if not status:
            control = None

        return control

    # -------------------------------------------------------------------------
    def create_control_group(self, parent_id: str, id: str, title: str = "", params: list = [], props: list = [], links: list = [], label: str = "", sort_id: str = "", alt_identifier: str = "", overview: str = "", instruction: str = "", remarks: str = ""):
        """
        Creates a new catalog group.
        Parameters:
        - parent_id (str): The id of the parent group to which this new group will be added.
                           Use '[root]' (case sensitive) to add to the top level of the catalog.
        - id (str): The id of the new group.
        - title (str): The title of the new group.
        - params (dict): A dictionary of parameters to add to the group.
        - props (dict): A dictionary of properties to add to the group.
        - links (dict): A dictionary of links to add to the group.
        - label (str): The label of the new group.
        - sort_id (str): The sort-id of the new group.
        - alt_identifier (str): The alt-identifier of the new group.
        - overview (str): The overview of the new group.
        - instruction (str): The instruction of the new group.
        - remarks (str): The remarks of the new group.
        """
        status = False
        group = None
        if parent_id == "":
            parent_id = "[root]"
        try:
            if parent_id == "[root]":
                logger.debug("Creating group at root level")
                parent_xpath = "/*"
            else:
                parent_xpath = f"//group[@id='{parent_id}']"
                logger.debug(f"Creating group under parent id: {parent_id}")

            parent_nodes = self.xpath(parent_xpath)
            if isinstance(parent_nodes, list) and len(parent_nodes) > 0:
                logger.debug(f"PARENT NODES LEN: {len(parent_nodes)}")
                parent_node = parent_nodes[0]

                logger.debug("TAG: " + parent_node.tag)
                group = ElementTree.Element(f"{{{OSCAL_DEFAULT_XML_NAMESPACE}}}group")
                group.set("id", id)

                if title != "":
                    title_node = ElementTree.SubElement(group, "title")
                    title_node.text = title

                if label != "":
                    label_node = ElementTree.SubElement(group, "prop")
                    label_node.set("name", "label")
                    label_node.set("value", label)

                if sort_id != "":
                    sort_id_node = ElementTree.SubElement(group, "prop")
                    sort_id_node.set("name", "sort-id")
                    sort_id_node.set("value", sort_id)

                if alt_identifier != "":
                    alt_id_node = ElementTree.SubElement(group, "prop")
                    alt_id_node.set("name", "alt-identifier")
                    alt_id_node.set("value", alt_identifier)

                append_props(group, props)
                append_links(group, links)

                if overview != "":
                    overview_node = ElementTree.SubElement(group, "part")
                    overview_node.set("name", "overview")
                    self.assign_html_string_to_node(overview_node, oscal_markdown_to_html(overview, True))

                if instruction != "":
                    instruction_node = ElementTree.SubElement(group, "part")
                    instruction_node.set("name", "instruction")
                    self.assign_html_string_to_node(instruction_node, oscal_markdown_to_html(instruction, True))

                if remarks != "":
                    remarks_node = ElementTree.SubElement(group, "remarks")
                    self.assign_html_string_to_node(remarks_node, oscal_markdown_to_html(remarks, True))

                parent_node.append(group)
                self.content_modified()
                status = True
            else:
                logger.warning(f"CREATE GROUP: Unable to find parent group with id {parent_id}")
        except Exception as error:
            logger.error(f"Error creating group ({id}): {type(error).__name__} - {str(error)}")

        if not status:
            group = None

        return group


class Controls():
    """A Read-Only class representing the resulting control set 
    associated with importing a profiles and/or catalogs, 
    including overlays. 

    source: The href of the profile/catalog that was imported and resolved to produce this control set.


    """
    def __init__(self, source: str = "", ttl: int = 0, *args, **kwargs):
        self.ttl = ttl # 
        self.processed_datetime = datetime.now(timezone.utc)
        self.import_tree = {}
        self.controls_tree = {}
        self.controls_list = {}

        

    def __repr__(self):
        return f"OSCAL Controls: {self.content_title} (from: {self.source_profile})"

    def __str__(self):
        ret_string = f"OSCAL Controls: {self.content_title}"
        return f"OSCAL Controls: {self.content_title} (from: {self.source_profile})"

    @property
    def is_stale(self) -> bool:
        """Check if the resolved catalog has exceeded its time-to-live."""
        if self.ttl <= 0:
            return False
        elapsed = (datetime.now(timezone.utc) - self.processed_datetime).total_seconds()
        return elapsed > self.ttl

    def refresh(self):
        """Re-resolve the source profile to update the control set.
        Placeholder for profile resolution logic.
        """
        # TODO: Implement profile resolution
        logger.info(f"Refreshing controls from source profile: {self.source_profile}")
        self.processed_datetime = datetime.now(timezone.utc)

    def get_control_by_id(self, control_id: str) -> Optional[ElementTree.Element]:
        """Retrieve a control element by its ID."""
        controls = self.xpath(f"//control[@id='{control_id}']")
        return controls[0] if isinstance(controls, list) and len(controls) > 0 else None

    def _cache_import_tree(self):
        """Internal method to cache the structure of imports for efficient access.
        Placeholder for caching logic.
        """
    def _cache_controls_tree(self): 
        """Internal method to cache the structure of controls for efficient access.
        Placeholder for caching logic.


class Profile(OSCAL):
    """Class representing an OSCAL Profile object.
    Inherits common OSCAL functionality and adds profile-specific methods
    for managing imports and control selections.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.controls = Controls()

    def __repr__(self):
        return f"OSCAL Profile: {self.content_title}"

    def __str__(self):
        return f"OSCAL Profile: {self.content_title}"

    # -------------------------------------------------------------------------
    def add_or_update_import(self, href: str, include_all: bool = False, include_ids=[], include_with_child=False, exclude_ids=[], exclude_with_child=False):
        """
        If an import with the provided href already exists, updates it with the
            provided include details.
        If an import with the provided href does not exist, but an import with an
            empty href (href='#'), updates it with the provided href and include details.
        Otherwise, adds a new import statement with the provided href and include details.

        Parameters:
        - href (str): The href of the profile to import.
        - include_all (bool): Whether to include all controls from the imported profile.
        - include_ids (list): List of control IDs to include.
        - include_with_child (bool): Whether to include child controls.
        - exclude_ids (list): List of control IDs to exclude.
        - exclude_with_child (bool): Whether to exclude child controls.
        """
        logger.debug(f"Adding or updating profile import for href '{href}' with include_all={include_all} and import_ids={include_ids}")

        import_matches = self.xpath(f"/*/import[@href='{href}']")
        import_obj: Optional[ElementTree.Element] = None
        if isinstance(import_matches, list) and len(import_matches) > 0:
            logger.debug(f"Found existing import for href '{href}'. Updating it.")
            if isinstance(import_matches[0], ElementTree.Element):
                import_obj = import_matches[0]
        else:
            import_matches = self.xpath("/*/import[@href='#']")
            if isinstance(import_matches, list) and len(import_matches) > 0:
                logger.debug(f"Found existing import with empty href. Updating it to '{href}'.")
                if isinstance(import_matches[0], ElementTree.Element):
                    import_obj = import_matches[0]
            else:
                logger.debug(f"No existing import found for href '{href}'. Creating new import element.")
                import_obj = ElementTree.Element(f"{{{OSCAL_DEFAULT_XML_NAMESPACE}}}import")

        if import_obj is None:
            logger.error(f"Unable to create or update import for href '{href}'.")
            return False

        if import_obj.get("href", "") != href:
            logger.debug(f"Setting import href to '{href}'.")
            import_obj.set("href", href)

        include_obj = import_obj.find("include-controls")
        if include_obj is not None:
            logger.debug("Removing existing include-controls element")
            import_obj.remove(include_obj)

        include_all_obj = import_obj.find("include-all")
        if include_all and include_all_obj:
            logger.debug("Include-all already present.")
        elif not include_all and include_all_obj:
            logger.debug("Removing existing include-all element")
            import_obj.remove(include_all_obj)
        elif include_all and not include_all_obj:
            logger.debug("Adding include-all element.")
            include_obj = ElementTree.SubElement(import_obj, "include-all")

        if not include_all and len(include_ids) > 0:
            include_obj = ElementTree.SubElement(import_obj, "include-controls")
            if include_with_child:
                include_obj.set("with-child-controls", "yes")
            for control_id in include_ids:
                with_id_obj = ElementTree.SubElement(include_obj, "with-id")
                with_id_obj.text = control_id

        if include_all and len(exclude_ids) > 0:
            exclude_obj = ElementTree.SubElement(import_obj, "exclude-controls")
            if exclude_with_child:
                exclude_obj.set("with-child-controls", "yes")
            for control_id in include_ids:
                with_id_obj = ElementTree.SubElement(exclude_obj, "with-id")
                with_id_obj.text = control_id

        return True

    # -------------------------------------------------------------------------
    def append_with_id(self, href: str, control_ids: list = []) -> bool:
        """
        Adds with-id element to a profile's import statement.
        """
        status = False
        import_matches = self.xpath(f"/*/import[@href='{href}']")
        if isinstance(import_matches, list) and len(import_matches) > 0 and isinstance(import_matches[0], ElementTree.Element):
            import_obj = import_matches[0]
            include_obj = import_obj.find("include-controls")
            if include_obj is None:
                include_obj = ElementTree.SubElement(import_obj, "include-controls")
                status = True
            for control_id in control_ids:
                with_id_obj = ElementTree.SubElement(include_obj, "with-id")
                with_id_obj.text = control_id
        else:
            logger.error(f"Unable to find import for href '{href}'. Cannot append control IDs.")

        return status
