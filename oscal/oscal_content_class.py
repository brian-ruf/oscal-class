"""
OSCAL Class

A class for creation, manipulation, validation and format convertion of OSCAL content.
All published OSCAL versions, formats and models can be validated and converted. 
Creation and manipulation is OSCAL 1.1.3 compliant.

This class ingests XML, JSON or YAML OSCAL content and validates it in its native format
using the appropriate NIST-published OSCAL schema.

The class converts YAML and JSON to XML for manipulation. New content starts as XML.

The class can export the content back to any of the three supported formats (XML, JSON, YAML).

Conversion between XML and JSON in either direction uses the NIST-published conversion XSLT stylesheets.
Conversion between JSON and YAML in either direction uses internal conversion via Python dictionaries.

Future versions will include direct validation and conversion using the NIST-published OSCAL metaschema.
"""
from loguru import logger
# import re
import os
# from elementpath.xpath3 import XPath3Parser
# from xml.dom import minidom
import json
import yaml
from common.logging import LoggableMixin
from common.data import detect_data_format, safe_load, safe_load_xml
from xml.etree import ElementTree
import elementpath
from common.lfs import getfile, chkfile, chkdir, putfile, normalize_content
# from common.xml_formatter import format_xml_string
from .oscal_support_class import OSCAL_support, OSCAL_DEFAULT_XML_NAMESPACE, OSCAL_FORMATS, SUPPORT_DATABASE_DEFAULT_FILE, SUPPORT_DATABASE_DEFAULT_TYPE
import uuid

INDENT = 2

# Shared OSCAL Support instance (initialized lazily)
_shared_oscal_support = None

def get_shared_oscal_support(db_conn=SUPPORT_DATABASE_DEFAULT_FILE, db_type=SUPPORT_DATABASE_DEFAULT_TYPE):
    """
    Get the shared OSCAL Support instance. Creates it if it doesn't exist.
    This ensures only one resource-intensive instance is created and shared
    across all OSCAL content instances.
    
    Args:
        db_conn: Database connection string or path (only used for first initialization)
        db_type: Database type (default: "sqlite3", only used for first initialization)
        
    Returns:
        OSCAL_support: The shared OSCAL Support instance
    """
    global _shared_oscal_support
    if _shared_oscal_support is None:
        if db_conn is None:
            # Use a default in-memory database if no connection specified
            db_conn = ":memory:"
        logger.info("Initializing shared OSCAL Support instance...")
        _shared_oscal_support = OSCAL_support.create(db_conn, db_type)
    return _shared_oscal_support

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# OSCAL CLASS
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCAL(LoggableMixin):
    """

    Properties:


    Methods:

    """
    def __init__(self, content="", filename="", support_db_conn=None, support_db_type=SUPPORT_DATABASE_DEFAULT_TYPE):
        """
        OSCAL Class Constructor
        Must provide at least one of the following parameters:
        - content: A string containing the OSCAL content
        - filename: A path to a file containing the OSCAL content
        - new_model: A string indicating the type of new OSCAL model to create
        - support_db_conn: Database connection string or path for OSCAL Support instance
        - support_db_type: Database type (default: "sqlite3") for OSCAL Support instance

        content and new_model are mutually exclusive.

        Raises:
            ValueError: If no content or filename is provided, or if content cannot be loaded
        """
        # Need at least one of content, filename, or new_model
        if not content and not filename:
            logger.error("No content or filename. Unable to proceed.")
            raise ValueError("No content or filename provided. Unable to proceed.")

        self.content = content
        self.original_location = filename
        self.original_format = ""

        self.oscal_model = ""
        self.oscal_version = ""

        self.well_formed = {}          # A dictionary indicating whether the content is well-formed for each format
        self.well_formed["xml"] = None
        self.well_formed["json"] = None
        self.well_formed["yaml"] = None
        self.schema_valid = {}       # A dictionary indicating whether the content is valid against the schema for each format
        self.schema_valid["xml"] = None
        self.schema_valid["json"] = None
        self.schema_valid["yaml"] = None
        self.metaschema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL Metaschema

        self.imports = []        # A list of imported OSCAL files, by CC-assigned UUID

        self.dict = None # JSON/YAML constructs
        self.tree = None # XML constructs
        self.nsmap = {"": OSCAL_DEFAULT_XML_NAMESPACE} # XML namespace map
        # self.__saxon = None
        self.synced = False # Boolean indicating whether the tree and dict are in sync
        self.unsaved = False # Boolean indicating whether there are unsaved modifications

        self.support = get_shared_oscal_support(support_db_conn, support_db_type)  # Always gets the same instance

        # If just a filename and no content, load the file
        if filename and not content:
            logger.debug(f"Loading OSCAL content from file: {filename}")
            self.filename = filename
            self.content = getfile(filename)
            if not self.content:
                logger.error(f"Unable to get file: {filename}")
                raise ValueError(f"Unable to get file: {filename}")

        # Process content if we have it
        if self.content:
            logger.debug("Processing provided content...")
            self.initial_validation()
        else:
            logger.error("No content available after attempting to load from file.")
            raise ValueError("No content available after attempting to load from file.")

    # -------------------------------------------------------------------------
    def __str__(self):
        return f"OSCAL(model={self.oscal_model}, version={self.oscal_version}, format={self.original_format})"
    # -------------------------------------------------------------------------
    def initial_validation(self):
        """
        Perform initial validation of content, which includes first ensuring the 
        content is a recognized OSCAL format type (xml, json or yaml) and 
        well formed, before passing it to the OSCAL validation method.
        """
        logger.debug("Performing initial validation of content...")
        status = False
        root_element = ""
        oscal_version = ""

        self.original_format = detect_data_format(self.content)
        logger.debug(f"Detected content format: {self.original_format}")
        
        if self.original_format in OSCAL_FORMATS:
            logger.debug(f"{self.original_format} is an OSCAL format.")

            match self.original_format:
                case "xml":
                    self.tree = safe_load_xml(self.content)
                    if self.tree is not None:
                        status = True
                        root_element = self.xpath_atomic("/*/name()")
                        oscal_version = f"v{self.xpath_atomic("/*/metadata/oscal-version/text()")}"
                    else:
                        status = False
                        logger.error("Content is not well-formed XML.")

                case "json", "yaml":
                    self.dict = safe_load(self.content, self.original_format)
                    if self.dict is not None:
                        status = True
                        root_element = next(iter(self.dict.keys())) if self.dict else ""
                        oscal_version = f"v{self.dict.get('metadata', {}).get('oscal-version', '')}"
                    else:
                        status = False
                        logger.error(f"Content is not well-formed {self.original_format.upper()}.")

        else:
            logger.error(f"Content is not one of {OSCAL_FORMATS}.")
            status = False

        if status:
            if oscal_version in self.support.versions:
                self.oscal_version = oscal_version
                if root_element in self.support.enumerate_models(self.oscal_version):
                    self.oscal_model = root_element
                    logger.debug(f"OSCAL model '{self.oscal_model}' and version '{self.oscal_version}' identified.")
                    status = True
                    # **** TODO: VALIDATE ****
                    self.OSCAL_validate()
                else:
                    logger.error("ROOT ELEMENT IS NOT AN OSCAL MODEL: " + root_element)
                    status = False
            else:
                logger.error("OSCAL VERSION IS NOT RECOGNIZED: " + oscal_version)
                status = False

        return status

    # -------------------------------------------------------------------------
    def OSCAL_validate(self) -> bool:
        """
        Validate OSCAL content.
        This assumes the content has already been determined to be well-formed XML, JSON, or YAML,
        and that the OSCAL model and version have been identified.
        Currently uses the appropriate format schema.
        Eventually will use meataschema for direct validation.
        """
        # TODO: Implement actual validation logic here
        logger.debug("Validating OSCAL content...")


        self.valid_oscal = True
        return self.valid_oscal

    # -------------------------------------------------------------------------
    def OSCAL_convert(self, directive):
        """
        Currently does nothing. Will soon accept the following directive values:
        'xml-to-json'
        'xml-to-yaml'
        """
        # TODL: Implement conversion logic here
        pass

    # -------------------------------------------------------------------------
    def save(self, filename: str="", format: str="", pretty_print: bool=False):
        f"""
        Save the current OSCAL content to a file.
        With no parameters, saves to the original location in the original format.
        This will save to any valid filename, even if the file extension does not match the format.
        
        Args:
            filename (str): The path to the file where content will be saved.
            format (str): The format to save the content in {OSCAL_FORMATS}.

        """
        status = False
        if format:
            format = format.lower()
            if format not in OSCAL_FORMATS:
                logger.debug(f"The save format specified ({format}) is not an OSCAL format.")
                return
        else:
            format = self.original_format


        if filename == "":
            filename = self.original_location

        file_path = os.path.dirname(os.path.abspath(filename))
        if not chkdir(file_path, make_if_not_present=True):
            logger.error(f"Directory does not exist and could not be created: {os.path.dirname(file_path)}")
            return
        
        logger.debug(f"Saving content as {filename} in OSCAL {format.upper()} format.")
        match format:
            case "xml":
                self.xml = self.xml_serializer() 
                status = putfile(filename, self.xml)

            case "json":
                self.json = self.to_json()
                status = putfile(filename, self.json)

            case "yaml", "yml":
                self.yaml = self.to_yaml()
                status = putfile(filename, self.yaml)
            case _:
                logger.error(f"Unsupported format for saving: {format}")
                return
        
        if status:
            logger.info(f"OSCAL content saved to {filename} in XML format.")
            self.unsaved = False

        else:
            logger.error(f"Failed to save OSCAL content to {filename} in XML format.")

        return status

    # -------------------------------------------------------------------------
    def content_modified(self):
        """
        Marks the content as modified by updating metadata fields and setting unsaved flag.
        """
        logger.debug("Content modified; updating metadata fields and flags.")
        # Prevent infinite recursion
        if getattr(self, '_in_content_modified', False):
            return
            
        self._in_content_modified = True
        try:
            self.unsaved = True
            self.synced = False
            self.__set_field("/*/metadata/last-modified", oscal_date_time_with_timezone())
            self.__set_field("/*/@uuid", str(uuid.uuid4()))
        finally:
            self._in_content_modified = False
    
    # -------------------------------------------------------------------------
    def __set_field(self, path: str, field_value: str):
        """
        Sets a specific field in the OSCAL content.
        The xpath expression must p9oint to a single element.
        Args:
            field_name (str): The name of the metadata field to set.
            field_value (str): The value to set for the metadata field.
        """
        # logger.debug(f"Setting field or attribute at '{path}' to value '{field_value}'")
        basename = os.path.basename(path)

        if "@" in basename: # Attribute
            base_path = path.rsplit("/", 1)[0] # Remove attribute part
            # logger.debug(f"Setting attribute on '{base_path}' to value '{field_value}'")
            attr_name = basename.replace("@", "")
            parent_nodes = self.xpath(base_path)
            if not parent_nodes or len(parent_nodes) != 1:
                logger.warning(f"XPath '{path}' returned unexpected results or no results. Cannot set attribute.")
                return
            parent_node = parent_nodes[0]  # Extract the first element from the list
            # logger.debug(f"Setting @{attr_name} to {field_value} on {ElementTree.tostring(parent_node, 'utf-8')}")
            try:
                parent_node.set(attr_name, field_value)
                logger.debug(f"Attribute @{attr_name} set to {field_value}")
            except Exception as error:
                logger.error(f"Failed to set attribute @{attr_name} to {field_value}: {str(error)}")
        else: 
            logger.debug(f"Setting field '{path}' to value '{field_value}'")
            current_nodes = self.xpath(path)
            if current_nodes:
                if len(current_nodes) > 1:
                    logger.warning(f"XPath '{path}' returned multiple results. Only the first will be set.")
                elif len(current_nodes) == 0:
                    logger.warning(f"XPath '{path}' returned no results. Cannot set value.")
                    return

                else:
                    current_node = current_nodes[0]
                    logger.debug(f"Current node before setting: {ElementTree.tostring(current_node, 'utf-8')}")
                    current_node.text = field_value
                    logger.debug(f"Current node after setting: {ElementTree.tostring(current_node, 'utf-8')}")


        # Only call content_modified if we're not already in it (prevent recursion)
        if not getattr(self, '_in_content_modified', False):
            self.content_modified()


    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    def set_metadata(self, content={}):
        """
        Sets metadata fields in the OSCAL content.
        Args:
            content (dict): A dictionary containing metadata fields to set.
        """
        for item in content:
            # logger.debug(f"Metadata field to set: {item} = {content[item]}")
            if item in ['revisions', 'document-ids', 'roles', 'locations', 'parties', 'links', 'props', 'responsible-parties']:
                # These are complex fields - skip for now
                logger.warning(f"Setting complex metadata field '{item}' is not yet implemented.")
                continue
            else:
                self.__set_field(f"/*/metadata/{item}", content.get(item, ""))

    # -------------------------------------------------------------------------
    def __setup_saxon(self): # Future - place holder for code for now
        from saxonche import PySaxonProcessor 

        self.__saxon = PySaxonProcessor(license=False)
        try: 
            self.xdm = self.__saxon.parse_xml(xml_text=self.xml)
            # self.__saxon.declare_namespace("", "http://csrc.nist.gov/ns/oscal/1.0")
            self.valid = True
            self.oscal_format = "xml"
        except Exception as error:
            logger.error(f"Content does not appear to be valid XML. Unable to rpoceed. {str(error)}")

        if self.valid:
            self.xp = self.__saxon.new_xpath_processor() # Instantiates XPath processing
            self.__saxon_handle_ns()
            self.xp.set_context(xdm_item=self.xdm) # Sets xpath processing context as the whole file
            temp_ret = self.__saxon_xpath_global("/*/name()")
            if temp_ret is not None:
                self.root_node = temp_ret[0].get_atomic_value().string_value
                logger.debug("ROOT: " + self.root_node)
            self.oscal_version = self.__saxon_xpath_global_single("/*/*:metadata/*:oscal-version/text()")
            logger.debug("OSCAL VERSION: " + self.oscal_version)

    # -------------------------------------------------------------------------
    def __saxon_xml_serializer(self):
        return self.xdm.to_string('utf_8')

    # -------------------------------------------------------------------------
    def __saxon_handle_ns(self):
        node_ = self.xdm
        child = node_.children[0]
        assert child is not None
        namespaces = child.axis_nodes(8)

        for ns in namespaces:
            uri_str = ns.string_value
            ns_prefix = ns.name

            if ns_prefix is not None:
                logger.debug("xmlns:" + ns_prefix + "='" + uri_str + "'")
            else:
                logger.debug("xmlns uri=" + uri_str + "'")
                # set default ns here
                self.xp.declare_namespace("", uri_str)

    # -------------------------------------------------------------------------
    def __saxon_xpath_global(self, expression):
        from saxonche import PyXdmValue
        ret_value = None
        logger.debug("Global Evaluating: " + expression)
        ret = self.xp.evaluate(expression)
        if  isinstance(ret,PyXdmValue):
            logger.debug("--Return Size: " + str(ret.size))
            ret_value = ret
        else:
            logger.debug("--No result")

        return ret_value

    # -------------------------------------------------------------------------
    def __saxon_xpath_global_single(self, expression):
        from saxonche import PyXdmValue
        ret_value = ""
        logger.debug("Global Evaluating Single: " + expression)
        ret = self.xp.evaluate_single(expression)
        if  isinstance(ret, PyXdmValue): # isinstance(ret,PyXdmNode):
            ret_value = ret.string_value
        else:
            logger.debug("--No result")
            logger.debug("TYPE: " + str(type(ret)))

        return ret_value

    # -------------------------------------------------------------------------
    def __saxon_xpath(self, context, expression):
        from saxonche import PyXdmValue
        ret_value = None
        logger.debug("Evaluating: " + expression)
        xp = self.__saxon.new_xpath_processor() # Instantiates XPath processing
        xp.set_context(xdm_item=context)
        ret = xp.evaluate(expression)
        if  isinstance(ret,PyXdmValue):
            logger.debug("--Return Size: " + str(ret.size))
            ret_value = ret
        else:
            logger.debug("--No result")

        return ret_value

    # -------------------------------------------------------------------------
    def __saxon_xpath_single(self, context, expression):
        from saxonche import PyXdmValue
        ret_value = ""
        logger.debug("Evaluating Single: " + expression)
        xp = self.__saxon.new_xpath_processor() # Instantiates XPath processing
        xp.set_context(xdm_item=context)
        ret = xp.evaluate_single(expression)
        if  isinstance(ret, PyXdmValue): # isinstance(ret,PyXdmNode):
            ret_value = ret.string_value
        else:
            logger.debug("--No result")
            logger.debug("TYPE: " + str(type(ret)))

        return ret_value
    # -------------------------------------------------------------------------

    
    def xpath_atomic(self, xExpr, context=None):
        """
        Performs an xpath query that is expected to return a single atomic value,
        Parameters:
        - xExpr (str): An xpath expression
        - context (obj)[optional]: Context object.
        If the context object is present, the xpath expression is run against 
        that context. If absent, the xpath expression is run against the 
        entire document.
        Returns: 
        - str: The atomic value as a string.
        """

        ret_value=""

        if context:
            logger.debug(f"Using provided context for XPath Atomic: {xExpr}")
        else:
            context = self.tree
            logger.debug(f"Using document root as context for XPath Atomic: {xExpr}")

        ret_value = elementpath.select(context, xExpr, namespaces=self.nsmap)[0]
        logger.debug(f"xPath results type: {str(type(ret_value))} with {len(ret_value)} nodes found.")

        return str(ret_value)

    # -------------------------------------------------------------------------
    def xpath(self, xExpr, context=None):
        """
        Performs an xpath query either on the entire XML document 
        or on a context within the document.

        Parameters:
        - xExpr (str): An xpath expression
        - context (obj)[optional]: Context object.
        If the context object is present, the xpath expression is run against
        that context. If absent, the xpath expression is run against the 
        entire document.

        Returns: 
        - None if there is an error or if nothing is found.
        - 
        """
        ret_value=None
        if context:
            logger.debug(f"Using provided context for XPath: {xExpr}")
        else:
            context = self.tree
            logger.debug(f"Using document root as context for XPath: {xExpr}")

        try:

            ret_value = elementpath.select(context, xExpr, namespaces=self.nsmap)
            # logger.debug(f"xPath results type: {str(type(ret_value))} with {len(ret_value)} nodes found.")
        except Exception as error:
            logger.error(f"XPath expression '{xExpr}' failed: {str(error)}")
            ret_value = None

        return ret_value

    # -------------------------------------------------------------------------
    def xml_serializer(self):
        """
        Serializes the current XML tree to a string.
        Returns:
        - str: The serialized XML content as a string.        
        """
        logger.debug("Serializing the XML tree for text output.")
        # Handle both ElementTree and Element objects
        root = self.tree.getroot() if hasattr(self.tree, 'getroot') else self.tree
        ElementTree.indent(root, space=" "* INDENT)

        out_string = ElementTree.tostring(root, 'utf-8')
        # logger.debug("LEN: " + str(len(out_string)))
        out_string = normalize_content(out_string)
        out_string = out_string.replace("ns0:", "")
        out_string = out_string.replace(":ns0", "")
        
        return out_string

    # -------------------------------------------------------------------------
    def json_serializer(self):
        """
        Serializes the current dict to a string.
        Returns:
        - str: The serialized JSON content as a string.        
        """
        logger.debug("Serializing dict for string output as JSON.")
        out_string = json.dumps(self.dict, indent=INDENT, sort_keys=False)
        logger.debug("LEN: " + str(len(out_string)))
        
        return out_string
        
    # -------------------------------------------------------------------------
    def yaml_serializer(self):
        """
        Serializes the current dict to a string.
        Returns:
        - str: The serialized YAML content as a string.        
        """
        logger.debug("Serializing dict for string output as YAML.")
        out_string = yaml.dump(self.dict, indent=INDENT, sort_keys=False)
        logger.debug("LEN: " + str(len(out_string)))
        
        return out_string
    # -------------------------------------------------------------------------
    def lookup(self, xExpr: str, attributes: list=[], children: list=[]):
        """
        Checks for the existence of an element basedon an xpath expression.
        Returns a dict containing any of the following if available: id, uuid, title
        If aditional attributes or children are specified in the function call
        and found to be present, they are included in the dict as well. 
        Parameters:
        - xExpr (str): xpath expression. This should always evaluate to 0 or 1 nodes
        - attributes(list)[Optional]: a list of additional attributes to return
        - children(list)[Optional]: a list of additional children to return

        Return:
        - dict or None
        dict = {
           {'attribute/field name', 'value'},
           {'attribute/field name', 'value'}        
        }
        """
        ret_value = None
        target_node = self.xpath(xExpr)
        if target_node:
            ret_value = {}
            if 'id' in target_node.attrib:
                ret_value.append({"id", target_node.get("id")})
            if 'uuid' in target_node.attrib:
                ret_value.append({"uuid", target_node.get("uuid")})

            # Use elementpath for reliable XPath processing
            title_nodes = elementpath.select(target_node, './title', namespaces=self.nsmap)
            title = title_nodes[0] if title_nodes else None
            if title:
                ret_value.append({"title", title.text})

            for attribute in attributes:
                ret_value.append({attribute, target_node.get(attribute)})

            for child in children:
                # Use elementpath for reliable XPath processing
                child_nodes = elementpath.select(target_node, './' + child, namespaces=self.nsmap)
                child_node = child_nodes[0] if child_nodes else None
                if child_node:
                    ret_value.append({child, child_node.text})


        return ret_value
    # -------------------------------------------------------------------------
    def assign_html_string_to_node(self, parent_node, html_string: str):
        """
        Assigns an HTML string to an XML node, converting it to proper XML structure.
        Parameters:
        - parent_node (ElementTree.Element): The parent XML node to which the HTML content will be added.
        - html_string (str): The HTML string to convert and assign.
        """
        try:
            # Wrap the HTML string in a temporary root element
            wrapped_html = f"<div>{html_string}</div>"
            temp_tree = ElementTree.ElementTree(ElementTree.fromstring(wrapped_html))
            temp_root = temp_tree.getroot()

            # Append each child of the temporary root to the parent node
            for child in temp_root:
                parent_node.append(child)

            logger.debug("HTML string successfully assigned to node.")
        except Exception as error:
            logger.error(f"Error assigning HTML string to node: {type(error).__name__} - {str(error)}")
    # -------------------------------------------------------------------------
    def create_control(self, parent_id, id, title="", params=[], props=[], links=[], label="", sort_id="", alt_identifier="", overview="", statements=[], guidance="", example="", objectives=[], objects=[], methods=[], remarks=""):
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
        status = False
        if self.oscal_model == "catalog":
            try:
                parent_xpath = f"//group[@id='{parent_id}']"
                logger.debug(f"Creating control under parent id: {parent_id}")

                # Use elementpath for reliable XPath processing
                parent_nodes = self.xpath(parent_xpath)
                logger.debug(f"PARENT NODES LEN: {len(parent_nodes)}")
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
                    
                    if len(props) > 0:
                        for prop in props:
                            logger.debug(f"Adding prop: {prop}")
                            prop_node = ElementTree.SubElement(control, "prop")
                            prop_node.set("name", prop['name'])
                            prop_node.set("value", prop['value'])
                            if 'class' in prop:
                                prop_node.set("class", prop.get('class', ''))
                            if 'group' in prop:
                                prop_node.set("group", prop.get('group', ''))
                            if 'ns' in prop:
                                prop_node.set("ns", prop.get('ns', ''))
                            if 'remarks' in prop:
                                remarks_node = ElementTree.SubElement(prop_node, "remarks")
                                self.assign_html_string_to_node(remarks_node, oscal_markdown_to_html(prop.get('remarks', '')))
                        # control.append(prop_node)
                    
                    for link in links:
                        link_node = ElementTree.SubElement(control, "link")
                        link_node.text = link
                    
                    if overview != "":
                        overview_node = ElementTree.SubElement(control, "part")
                        overview_node.set("name", "overview")
                        self.assign_html_string_to_node(overview_node, oscal_markdown_to_html(overview))
                                            
                    
                    if len(statements) > 0:
                        statement_node = ElementTree.SubElement(control, "part")
                        statement_node.set("name", "statement")
                        statement_node.set("id", f"{id}_smt")
                        logger.debug(f"STATEMENTS TYPE: {type(statements)} with {len(statements)} items.")
                        if len(statements)  == 1:
                            # Single statement without id
                            logger.debug("Single statement without id detected.")
                            self.assign_html_string_to_node(statement_node, oscal_markdown_to_html(statements[0]))
                        else:
                            for item in statements:
                                statement_child_node = ElementTree.SubElement(control, "part")
                                statement_child_node.set("name", "item")
                                if item.get('id', "") != "":
                                    statement_child_node.set("id", f"{id}_smt")
                                self.assign_html_string_to_node(statement_node, oscal_markdown_to_html(item['prose']))
                    
                    if guidance != "":
                        guidance_node = ElementTree.SubElement(control, "guidance")
                        self.assign_html_string_to_node(guidance_node, oscal_markdown_to_html(guidance))
                    
                    if example != "":
                        example_node = ElementTree.SubElement(control, "part")
                        example_node.set("name", "example")
                        self.assign_html_string_to_node(example_node, oscal_markdown_to_html(example))
                    
                    if remarks != "":
                        remarks_node = ElementTree.SubElement(control, "remarks")
                        self.assign_html_string_to_node(remarks_node, oscal_markdown_to_html(remarks))
                    parent_node.append(control)
                    self.content_modified()
                    status = True
                else:
                    logger.warning(f"CREATE CONTROL: Unable to find parent group with id {parent_id}" )
            except Exception as error:
                logger.error(f"Error creating control ({id}): {type(error).__name__} - {str(error)}")
        else:
            logger.error("CREATE CONTROL: Current model is not a catalog. Unable to create control.")

        if not status:
            control = None

        return control

    # -------------------------------------------------------------------------
    def create_control_group(self, parent_id, id, title="", params={}, props={}, links={}, label="", sort_id="", alt_identifier="", overview="", instruction="", remarks=""):
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
        if parent_id == "":
            parent_id = "[root]"
        if self.oscal_model == "catalog":
            try:
                if parent_id == "[root]":
                    logger.debug("Creating group at root level")
                    parent_xpath = "/*"
                else:
                    parent_xpath = f"//group[@id='{parent_id}']"
                    logger.debug(f"Creating group under parent id: {parent_id}")

                # Use elementpath for reliable XPath processing
                parent_nodes = self.xpath(parent_xpath)
                logger.debug(f"PARENT NODES LEN: {len(parent_nodes)}")
                parent_node = parent_nodes[0] if parent_nodes else None
                if parent_node is not None:
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

                    if overview != "":
                        overview_node = ElementTree.SubElement(group, "part")
                        overview_node.set("name", "overview")
                        self.assign_html_string_to_node(overview_node, oscal_markdown_to_html(overview))
                        # overview_node.text = oscal_markdown_to_html(overview)

                    if instruction != "":
                        instruction_node = ElementTree.SubElement(group, "part")
                        instruction_node.set("name", "instruction")
                        self.assign_html_string_to_node(instruction_node, oscal_markdown_to_html(instruction))
                        # instruction_node.text = oscal_markdown_to_html(instruction)

                    if remarks != "":
                        remarks_node = ElementTree.SubElement(group, "remarks")
                        self.assign_html_string_to_node(remarks_node, oscal_markdown_to_html(remarks))
                        # remarks_node.text = oscal_markdown_to_html(remarks)

                    parent_node.append(group)
                    self.content_modified()
                    status = True
                else:
                    logger.warning(f"CREATE GROUP: Unable to find parent group with id {parent_id}" )
            except Exception as error:
                logger.error(f"Error creating group ({id}): {type(error).__name__} - {str(error)}")
        else:
            logger.error("CREATE GROUP: Current model is not a catalog. Unable to create group.")

        if not status:
            group = None

        return group

    # -------------------------------------------------------------------------
    def append_child(self, xpath, node_name, node_content = None, attribute_list = []):
        # logger.debug("APPENDING " + node_name + " as child to " + xpath) #  + " in " + self.tree.tag)
        status = False
        try:
            logger.debug("Fetching parent at " + xpath)
            # Use elementpath for reliable XPath processing
            parent_nodes = elementpath.select(self.tree, xpath, namespaces=self.nsmap)
            parent_node = parent_nodes[0] if parent_nodes else None
            # parent_node = self.xpath(xpath)
            logger.debug(parent_node)
            if parent_node is not None:
                logger.debug("TAG: " + parent_node.tag)
                child = ElementTree.Element(node_name)

                logger.debug("SETTING CONTENT")
                if node_content is str:
                    child.text = node_content

                logger.debug("SETTING ATTRIBUTES")
                for attrib in attribute_list:
                    child.set(attrib, attribute_list[attrib])

                parent_node.append(child)
                status = True
            else:
                logger.warning("APPEND: Unable to find " + xpath )
        except Exception as error:
            logger.error("Error appending child (" + node_name + "): " + type(error).__name__ + " - " + str(error))
        
        if status:
            return child
        else:
            return None

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def get_root_element_name(content: str) -> str:
    """
    Returns the name of the root element in the provided XML content string.
    If the content is not well-formed XML, returns an empty string.

    Parameters:
    - content (str): The XML content as a string.

    Returns:
    - str: The name of the root element, or an empty string if not well-formed XML.
    """
    root_name = ""
    try:
        tree = ElementTree.fromstring(content.encode('utf_8'))
        root_name = tree.tag
    except ElementTree.ParseError:
        logger.debug("Content does not appear to be well-formed XML.")
    
    return root_name

# -------------------------------------------------------------------------
# -----------------------------------------------------------------------------
def oscal_date_time_with_timezone(date_time = None, format = "%Y-%m-%dT%H:%M:%SZ")-> str:
    """
    Converts a date and time to UTC and outputs an OSCAL date-time-with-timezone string. 
    Optional Parameters:
    - date_time (datetime or str): A date and time to convert to a formatted string.
       Can be a datetime object or a string that can be parsed into datetime.
       Default is the current date and time
    - format (str): The formatting string to use
        default is "%Y-%m-%dT%H:%M:%SZ" (OSCAL standard format)

    Returns a formatted date time string.
    If an error occurs, returns an empty string.
    """
    from datetime import datetime, timezone
    from dateutil import parser as date_parser
    
    if date_time is None: 
        date_time = datetime.now()
    elif isinstance(date_time, str):
        # Parse string into datetime object
        try:
            date_time = date_parser.parse(date_time)
        except Exception as error:
            logger.error(f"{type(error).__name__} error parsing date/time string '{date_time}': {str(error)}")
            return ""
    
    ret_value = ""

    try:
        # Ensure we have timezone info, default to UTC if naive
        if date_time.tzinfo is None:
            date_time = date_time.replace(tzinfo=timezone.utc)
        else:
            date_time = date_time.astimezone(timezone.utc)
        ret_value = date_time.strftime(format)
    except Exception as error:
        logger.error(f"{type(error).__name__} error handling date/time formatting: {str(error)}")
    return ret_value

# -------------------------------------------------------------------------
def oscal_markdown_to_html(markdown_text: str, multiline: bool = True) -> str:
    """
    Converts OSCAL markup-line or markup-multiline formatted markdown to HTML.
    
    This function handles the specific markdown subset defined in the NIST Metaschema
    specification for OSCAL markup-line and markup-multiline data types.
    
    Args:
        markdown_text (str): The markdown text to convert
        multiline (bool): If True, handles markup-multiline (supports block elements).
                         If False, handles markup-line (inline elements only).
    
    Returns:
        str: HTML representation of the markdown text
    
    References:
        https://pages.nist.gov/metaschema/specification/datatypes/#markup-multiline 
        https://pages.nist.gov/metaschema/specification/datatypes/#markup-line
    """
    import re
    
    if not markdown_text:
        return ""
    
    # Store escaped characters temporarily
    escape_map = {
        '\\*': '___ESCAPED_ASTERISK___',
        '\\`': '___ESCAPED_BACKTICK___',
        '\\~': '___ESCAPED_TILDE___',
        '\\^': '___ESCAPED_CARET___',
        '\\_': '___ESCAPED_UNDERSCORE___',
        '\\[': '___ESCAPED_LEFT_BRACKET___',
        '\\]': '___ESCAPED_RIGHT_BRACKET___',
        '\\{': '___ESCAPED_LEFT_BRACE___',
        '\\}': '___ESCAPED_RIGHT_BRACE___',
        '\\\\': '___ESCAPED_BACKSLASH___'
    }
    
    html = markdown_text
    for escaped, placeholder in escape_map.items():
        html = html.replace(escaped, placeholder)
    
    # Handle OSCAL parameter insertion syntax: {{ insert: param, pm-9_prm_1 }}
    def replace_param_insertion(match):
        parts = [p.strip() for p in match.group(1).split(',')]
        if len(parts) >= 2:
            insert_type = parts[0].replace('insert:', '').strip()
            id_ref = parts[1].strip()
            return f'<insert type="{insert_type}" id-ref="{id_ref}"/>'
        return match.group(0)
    
    html = re.sub(r'\{\{\s*([^}]+)\s*\}\}', replace_param_insertion, html)
    
    # For markup-line, only apply inline formatting
    if not multiline:
        # Images FIRST (to avoid conflict with links): ![alt text](url "title") -> <img alt="alt text" src="url" title="title"/>
        html = re.sub(r'!\[([^\]]*)\]\(([^")]+)(?:\s+"([^"]*)")?\)', 
                      lambda m: f'<img alt="{m.group(1)}" src="{m.group(2)}"' + 
                               (f' title="{m.group(3)}"' if m.group(3) else '') + '/>', html)
        
        # Links: [text](url "title") -> <a href="url" title="title">text</a>  
        html = re.sub(r'\[([^\]]+)\]\(([^")]+)(?:\s+"([^"]*)")?\)',
                      lambda m: f'<a href="{m.group(2)}"' + 
                               (f' title="{m.group(3)}"' if m.group(3) else '') + 
                               f'>{m.group(1)}</a>', html)
        
        # Strong emphasis (bold) - **text** -> <strong>text</strong>
        html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', html)
        
        # Emphasis (italic) - *text* -> <em>text</em> (avoid matching **)
        html = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', html)
        
        # Inline code - `text` -> <code>text</code>
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
        
        # Superscript - ^text^ -> <sup>text</sup>
        html = re.sub(r'\^([^^]+)\^', r'<sup>\1</sup>', html)
        
        # Subscript - ~text~ -> <sub>text</sub>
        html = re.sub(r'~([^~]+)~', r'<sub>\1</sub>', html)
    else:
        # Handle block-level elements (only for markup-multiline)
        lines = html.split('\n')
        result = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            if not line:
                i += 1
                continue
            
            # Headers - # text -> <h1>text</h1> (and so on)
            if line.startswith('#'):
                level = len(line) - len(line.lstrip('#'))
                if 1 <= level <= 6:
                    header_text = line[level:].strip()
                    result.append(f'<h{level}>{header_text}</h{level}>')
                    i += 1
                    continue
            
            # Code blocks - ```text``` -> <pre>text</pre>
            if line == '```':
                code_lines = []
                i += 1
                while i < len(lines) and lines[i].strip() != '```':
                    code_lines.append(lines[i])
                    i += 1
                if i < len(lines):  # Skip closing ```
                    i += 1
                result.append(f'<pre>{"\n".join(code_lines)}</pre>')
                continue
            
            # Tables
            if '|' in line:
                table_lines = [line]
                j = i + 1
                # Collect all consecutive table lines
                while j < len(lines) and '|' in lines[j].strip():
                    table_lines.append(lines[j].strip())
                    j += 1
                
                if len(table_lines) >= 2:  # At least header and separator
                    table_html = _format_table_helper(table_lines)
                    result.append(table_html)
                    i = j
                    continue
            
            # Blockquotes - > text -> <blockquote>text</blockquote>
            if line.startswith('>'):
                quote_text = line[1:].strip()
                result.append(f'<blockquote>{quote_text}</blockquote>')
                i += 1
                continue
            
            # Lists - unordered
            if line.startswith('-') or line.startswith('*'):
                list_item = line[1:].strip()
                result.append(f'<ul><li>{list_item}</li></ul>')
                i += 1
                continue
            
            # Lists - ordered
            if re.match(r'^\d+\.', line):
                list_item = re.sub(r'^\d+\.\s*', '', line)
                result.append(f'<ol><li>{list_item}</li></ol>')
                i += 1
                continue
            
            # Regular paragraph
            result.append(f'<p>{line}</p>')
            i += 1
        
        html = '\n'.join(result)
        
        # Now apply inline formatting to the result
        # Images FIRST (to avoid conflict with links): ![alt text](url "title") -> <img alt="alt text" src="url" title="title"/>
        html = re.sub(r'!\[([^\]]*)\]\(([^")]+)(?:\s+"([^"]*)")?\)', 
                      lambda m: f'<img alt="{m.group(1)}" src="{m.group(2)}"' + 
                               (f' title="{m.group(3)}"' if m.group(3) else '') + '/>', html)
        
        # Links: [text](url "title") -> <a href="url" title="title">text</a>  
        html = re.sub(r'\[([^\]]+)\]\(([^")]+)(?:\s+"([^"]*)")?\)',
                      lambda m: f'<a href="{m.group(2)}"' + 
                               (f' title="{m.group(3)}"' if m.group(3) else '') + 
                               f'>{m.group(1)}</a>', html)
        
        # Strong emphasis (bold) - **text** -> <strong>text</strong>
        html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', html)
        
        # Emphasis (italic) - *text* -> <em>text</em> (avoid matching **)
        html = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', html)
        
        # Inline code - `text` -> <code>text</code>
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
        
        # Superscript - ^text^ -> <sup>text</sup>
        html = re.sub(r'\^([^^]+)\^', r'<sup>\1</sup>', html)
        
        # Subscript - ~text~ -> <sub>text</sub>
        html = re.sub(r'~([^~]+)~', r'<sub>\1</sub>', html)
    
    # Restore escaped characters
    reverse_escape_map = {
        '___ESCAPED_ASTERISK___': '*',
        '___ESCAPED_BACKTICK___': '`',
        '___ESCAPED_TILDE___': '~',
        '___ESCAPED_CARET___': '^',
        '___ESCAPED_UNDERSCORE___': '_',
        '___ESCAPED_LEFT_BRACKET___': '[',
        '___ESCAPED_RIGHT_BRACKET___': ']',
        '___ESCAPED_LEFT_BRACE___': '{',
        '___ESCAPED_RIGHT_BRACE___': '}',
        '___ESCAPED_BACKSLASH___': '\\'
    }
    
    for placeholder, original in reverse_escape_map.items():
        html = html.replace(placeholder, original)
    
    return html

# -------------------------------------------------------------------------
def oscal_html_to_markdown(html_text: str, multiline: bool = True) -> str:
    """
    Converts HTML back to OSCAL markup-line or markup-multiline formatted markdown.
    
    This function handles the reverse conversion from HTML to the specific markdown subset 
    defined in the NIST Metaschema specification for OSCAL markup-line and markup-multiline data types.
    
    Args:
        html_text (str): The HTML text to convert
        multiline (bool): If True, generates markup-multiline (supports block elements).
                         If False, generates markup-line (inline elements only).
    
    Returns:
        str: Markdown representation of the HTML text
    
    References:
        https://pages.nist.gov/metaschema/specification/datatypes/#markup-multiline
        https://pages.nist.gov/metaschema/specification/datatypes/#markup-line
    """
    import re
    
    if not html_text:
        return ""
    
    markdown = html_text.strip()
    
    # Handle OSCAL parameter insertion: <insert type="param" id-ref="id"/> -> {{ insert: param, id }}
    markdown = re.sub(r'<insert\s+type="([^"]+)"\s+id-ref="([^"]+)"\s*/>', 
                      r'{{ insert: \1, \2 }}', markdown)
    
    if multiline:
        # Handle block-level elements first (only for markup-multiline)
        
        # Headers: <h1>text</h1> -> # text
        for level in range(1, 7):
            markdown = re.sub(f'<h{level}>([^<]+)</h{level}>', 
                             f'{"#" * level} \\1\n\n', markdown)
        
        # Code blocks: <pre>code</pre> -> ```code```
        def fix_code_block(match):
            content = match.group(1)
            return f'\n\n```\n{content}\n```\n\n'
        markdown = re.sub(r'<pre>([^<]*)</pre>', fix_code_block, markdown, flags=re.DOTALL)
        
        # Tables: Convert HTML table back to markdown table
        def convert_html_table(match):
            table_html = match.group(0)
            
            # Extract header row
            header_match = re.search(r'<tr>((?:<th[^>]*>[^<]*</th>)+)</tr>', table_html)
            if not header_match:
                return table_html  # Not a valid table structure
            
            header_cells = re.findall(r'<th[^>]*>([^<]*)</th>', header_match.group(1))
            
            # Extract alignment information
            alignments = []
            for th_match in re.finditer(r'<th[^>]*align="([^"]*)"[^>]*>', header_match.group(1)):
                alignments.append(th_match.group(1))
            
            # Extract data rows
            data_rows = []
            for row_match in re.finditer(r'<tr>((?:<td[^>]*>.*?</td>)+)</tr>', table_html, flags=re.DOTALL):
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row_match.group(1), flags=re.DOTALL)
                data_rows.append(cells)
            
            if not header_cells or not data_rows:
                return table_html
            
            # Build markdown table
            table_lines = []
            
            # Header row
            table_lines.append('| ' + ' | '.join(header_cells) + ' |')
            
            # Separator row with alignment
            separators = []
            for i, header in enumerate(header_cells):
                align = alignments[i] if i < len(alignments) else 'left'
                if align == 'center':
                    separators.append(':---:')
                elif align == 'right':
                    separators.append('---:')
                else:
                    separators.append('---')
            table_lines.append('| ' + ' | '.join(separators) + ' |')
            
            # Data rows
            for row in data_rows:
                # Pad row to match header length
                while len(row) < len(header_cells):
                    row.append('')
                table_lines.append('| ' + ' | '.join(row[:len(header_cells)]) + ' |')
            
            return '\n\n' + '\n'.join(table_lines) + '\n\n'
        
        # Match HTML tables
        markdown = re.sub(r'<table>.*?</table>', convert_html_table, markdown, flags=re.DOTALL)
        
        # Blockquotes: <blockquote>text</blockquote> -> > text
        markdown = re.sub(r'<blockquote>([^<]+)</blockquote>', r'\n\n> \1\n\n', markdown)
        
        # Lists - unordered: <ul><li>text</li></ul> -> - text
        markdown = re.sub(r'<ul><li>([^<]+)</li></ul>', r'\n\n- \1\n', markdown)
        
        # Lists - ordered: <ol><li>text</li></ol> -> 1. text
        markdown = re.sub(r'<ol><li>([^<]+)</li></ol>', r'\n\n1. \1\n', markdown)
        
        # Paragraphs: <p>text</p> -> text (with newlines)
        markdown = re.sub(r'<p>([^<]+)</p>', r'\1\n\n', markdown)
    
    # Handle inline formatting (for both markup types)
    
    # Images: <img alt="alt" src="src" title="title"/> -> ![alt](src "title")
    markdown = re.sub(r'<img\s+alt="([^"]*)"\s+src="([^"]+)"\s+title="([^"]*)"\s*/>', 
                      r'![\1](\2 "\3")', markdown)
    markdown = re.sub(r'<img\s+alt="([^"]*)"\s+src="([^"]+)"\s*/>', 
                      r'![\1](\2)', markdown)
    
    # Links: <a href="url" title="title">text</a> -> [text](url "title")
    markdown = re.sub(r'<a\s+href="([^"]+)"\s+title="([^"]*)">([^<]+)</a>', 
                      r'[\3](\1 "\2")', markdown)
    markdown = re.sub(r'<a\s+href="([^"]+)">([^<]+)</a>', 
                      r'[\2](\1)', markdown)
    
    # Strong emphasis: <strong>text</strong> -> **text**
    markdown = re.sub(r'<strong>([^<]+)</strong>', r'**\1**', markdown)
    
    # Emphasis: <em>text</em> -> *text*
    markdown = re.sub(r'<em>([^<]+)</em>', r'*\1*', markdown)
    
    # Inline code: <code>text</code> -> `text`
    markdown = re.sub(r'<code>([^<]+)</code>', r'`\1`', markdown)
    
    # Superscript: <sup>text</sup> -> ^text^
    markdown = re.sub(r'<sup>([^<]+)</sup>', r'^\1^', markdown)
    
    # Subscript: <sub>text</sub> -> ~text~
    markdown = re.sub(r'<sub>([^<]+)</sub>', r'~\1~', markdown)
    
    # Clean up any remaining HTML tags or artifacts
    markdown = re.sub(r'<[^>]+>', '', markdown)
    
    if multiline:
        # For multiline, preserve line structure but clean up excess whitespace
        lines = markdown.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line:
                cleaned_lines.append(line)
            elif cleaned_lines and cleaned_lines[-1]:  # Add empty lines only between content
                cleaned_lines.append('')
        
        # Join lines and clean up multiple consecutive empty lines
        markdown = '\n'.join(cleaned_lines)
        markdown = re.sub(r'\n\n\n+', '\n\n', markdown)
    else:
        # For inline only, collapse whitespace
        markdown = re.sub(r'\s+', ' ', markdown)
    
    markdown = markdown.strip()
    return markdown

# -------------------------------------------------------------------------
def _format_table_helper(table_lines: list) -> str:
    """Helper function to format markdown table to HTML"""
    if len(table_lines) < 2:
        return ""
    
    # Parse header row
    header_cells = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]
    
    # Parse alignment row
    alignment_row = table_lines[1]
    alignments = []
    for cell in alignment_row.split('|')[1:-1]:
        cell = cell.strip()
        if cell.startswith(':') and cell.endswith(':'):
            alignments.append('center')
        elif cell.endswith(':'):
            alignments.append('right')
        else:
            alignments.append('left')
    
    # Ensure we have alignments for all columns
    while len(alignments) < len(header_cells):
        alignments.append('left')
    
    # Build HTML table
    html = ['<table>']
    
    # Header row
    header_html = '  <tr>'
    for i, cell in enumerate(header_cells):
        align = alignments[i] if i < len(alignments) else 'left'
        header_html += f'<th align="{align}">{cell}</th>'
    header_html += '</tr>'
    html.append(header_html)
    
    # Data rows
    for line in table_lines[2:]:
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.split('|')[1:-1]]
        row_html = '  <tr>'
        for i, cell in enumerate(cells):
            align = alignments[i] if i < len(alignments) else 'left'
            row_html += f'<td align="{align}">{cell}</td>'
        row_html += '</tr>'
        html.append(row_html)
    
    html.append('</table>')
    return '\n'.join(html)

# -------------------------------------------------------------------------
def create_new_oscal_content(model_name: str, title: str, version: str="", published: str="", support_db_conn=None, support_db_type=SUPPORT_DATABASE_DEFAULT_TYPE) -> OSCAL:
    """
    Returns minimally valid OSCAL content based on the specified model name.
    Currently this is based on loading a template file from package data.
    In the future, this should be generated based on the latest metaschema definition.
    Args:
        model_name (str): The OSCAL model name (e.g., "system-security-plan").
    """
    # TODO: Generate new content based on newest metaschema definition for the model
    oscal_object = None
    support = get_shared_oscal_support(db_conn=support_db_conn, db_type=support_db_type)

    if support.is_model_valid(model_name): # is the specified model name an actual OSCAL model?
        content = support.load_file(f"{model_name}.xml", binary=False)
        # If content is found and is of type string, load it as XML
        if content and isinstance(content, str):

            try:
                oscal_object = OSCAL(content=content)
                logger.debug(f"Created new OSCAL content for model {model_name}")

                if oscal_object is not None:
                    metadata = {}
                    if title != "":
                        metadata["title"] = title
                    if version != "":
                        metadata["version"] = version
                    if published != "":
                        metadata["published"] = oscal_date_time_with_timezone(published)
                
                    if metadata:
                        oscal_object.set_metadata(metadata)

                    oscal_object.content_modified() # mark content as modified to update last-modified and uuid
            except ValueError as ve:
                logger.error(f"ValueError creating new OSCAL content for model {model_name}: {str(ve)}")
                oscal_object = None

            except Exception as error:
                logger.error(f"Error creating new OSCAL content for model {model_name}: {type(error).__name__} - {str(error)}")
                oscal_object = None

    else:
        logger.error(f"Unsupported OSCAL model for new content: {model_name}")
    
    return oscal_object


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


if __name__ == '__main__':
    print("OSCAL Class Library. Not intended to be run as a stand-alone file.")

