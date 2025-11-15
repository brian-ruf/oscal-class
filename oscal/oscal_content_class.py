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
import re
# from elementpath.xpath3 import XPath3Parser
# from xml.dom import minidom
from common.logging import LoggableMixin
from common.data import detect_data_format, is_xml_well_formed, is_json_well_formed, is_yaml_well_formed
from xml.etree import ElementTree
import elementpath
from common.lfs import getfile, normalize_content
# from common.xml_formatter import format_xml_string
from .oscal_support_class import OSCAL_support, OSCAL_DEFAULT_XML_NAMESPACE, OSCAL_FORMATS, SUPPORT_DATABASE_DEFAULT_FILE, SUPPORT_DATABASE_DEFAULT_TYPE
import uuid

INDENT = "  "

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
    def __init__(self, content="", filename="", new_model="", support_db_conn=None, support_db_type=SUPPORT_DATABASE_DEFAULT_TYPE):
        """
        OSCAL Class Constructor
        Must provide at least one of the following parameters:
        - content: A string containing the OSCAL content
        - filename: A path to a file containing the OSCAL content
        - new_model: A string indicating the type of new OSCAL model to create
        - support_db_conn: Database connection string or path for OSCAL Support instance
        - support_db_type: Database type (default: "sqlite3") for OSCAL Support instance
        
        content and new_model are mutually exclusive.
        """
        # self.uuid = uuid.uuid4() # Class-assigned UUID
        self.setup_logging()
        self.content = ""

        self.oscal_model = ""
        self.oscal_version = ""
        self.imports = []        # A list of imported OSCAL files, by CC-assigned UUID
        self.xml_schema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL XML Schema
        self.json_schema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL JSON Schema
        self.metaschema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL Metaschema
        self.xml = "" 
        self.json = "" 
        self.yaml = "" 
        self.well_formed_xml = False
        self.well_formed_json = False
        self.well_formed_yaml = False
        self.valid_xml = False
        self.valid_json = False
        self.valid_yaml = False
        self.valid_oscal = False
        self.original_location = ""
        self.original_format = ""
        self.support = get_shared_oscal_support(support_db_conn, support_db_type)  # Always gets the same instance

        self.tree = None
        self.nsmap = {"": OSCAL_DEFAULT_XML_NAMESPACE}
        self.__saxon = None
        self.unsaved_modified_content = False 
        self.json_synced = None # Boolean indicating whether the latest XML content has been converted to JSON
        self.yaml_synced = None # Boolean indicating whether the latest XML content has been converted to YAML

        # Need at least one of content, filename, or new_model
        if not content and not filename and not new_model:
            logger.error("No content, filename or new model specified. Unable to proceed.")
            return
        
        if content and new_model:
            logger.error("Cannot specify both content and new_model. They are mutually exclusive.")
            return

        # If just a filename and no content, load the file
        if filename and not content:
            self.filename = filename
            content = getfile(filename)
            if not content:
                logger.error(f"Unable to read content from file: {filename}")
        
        if (new_model and not content) and new_model in self.support.enumerate_models():
            logger.debug(f"Creating new OSCAL model: {new_model}")

            self.support = get_shared_oscal_support()
            self.create_new_oscal_content(new_model)
            if self.xml:  # create_new_oscal_content sets self.xml directly
                content = self.xml
                logger.debug(f"Created new OSCAL model: {new_model}")
            else:
                logger.error(f"Unable to create new OSCAL model: {new_model}")

        # Process content if we have it
        if content:
            self.content = content
            self.initial_validation(content)


    # -------------------------------------------------------------------------
    def save(self, filename: str, format: str="xml", pretty_print: bool=False):
        """
        Save the current OSCAL content to a file in the specified format.
        
        Args:
            filename (str): The path to the file where content will be saved.
            format (str): The format to save the content in ("xml", "json", "yaml").
        """
        content_to_save = ""
        match format.lower():
            case "xml":
                if self.xml and (self.unsaved_modified_content or not self.well_formed_xml):
                    self.xml = self.serializer() # ElementTree.tostring(self.tree.getroot(), encoding='utf-8').decode('utf-8')
                    # self.xml = format_xml_string(self.xml) if pretty_print else self.xml
                    self.unsaved_modified_content = False
                content_to_save = self.xml
            case "json":
                if not self.json_synced or self.unsaved_modified_content:
                    # Convert XML to JSON here
                    pass
                content_to_save = self.json
            case "yaml":
                if not self.yaml_synced or self.unsaved_modified_content:
                    # Convert XML to YAML here
                    pass
                content_to_save = self.yaml
            case _:
                logger.error(f"Unsupported format for saving: {format}")
                return
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content_to_save)
            logger.info(f"OSCAL content saved to {filename} in {format} format.")
        except Exception as e:
            logger.error(f"Failed to save OSCAL content to {filename}: {e}")
    # -------------------------------------------------------------------------
    def content_modified(self):
        # Prevent infinite recursion
        if getattr(self, '_in_content_modified', False):
            return
            
        self._in_content_modified = True
        try:
            self.unsaved_modified_content = True
            self.json_synced = False
            self.yaml_synced = False
            self.__set_field("/*/metadata/last-modified", oscal_date_time_with_timezone())
            self.__set_field("/*/@uuid", str(uuid.uuid4()))
        finally:
            self._in_content_modified = False
    
    # -------------------------------------------------------------------------
    def __set_field(self, path: str, field_value: str, create_if_missing=True):
        """
        Sets a specific field in the OSCAL content.
        The xpath expression must p9oint to a single element.
        Args:
            field_name (str): The name of the metadata field to set.
            field_value (str): The value to set for the metadata field.
        """
        # Check if this is an attribute path (contains @attribute)
        if '@' in path:
            # Extract attribute name and element path
            # For paths like "/*/@uuid", we want element "/*" and attribute "uuid"
            attr_match = re.search(r'(.*)/@([^/\]]+)$', path)
            if attr_match:
                element_path = attr_match.group(1)
                attr_name = attr_match.group(2)
                
                if self.tree:
                    # Special handling for root element selector /*
                    if element_path == '/*':
                        element_node = self.tree.getroot()
                    else:
                        # Use elementpath for reliable XPath processing
                        element_nodes = elementpath.select(self.tree, element_path, namespaces=self.nsmap)
                        element_node = element_nodes[0] if element_nodes else None
                        
                    if element_node is not None:
                        element_node.set(attr_name, field_value)
                        # Only call content_modified if we're not already in it (prevent recursion)
                        if not getattr(self, '_in_content_modified', False):
                            self.content_modified()
                        return
        
        # Handle element text content
        if self.tree:
            # Use elementpath for reliable XPath processing
            field_nodes = elementpath.select(self.tree, path, namespaces=self.nsmap)
            field_node = field_nodes[0] if field_nodes else None
            if field_node is not None:
                field_node.text = field_value
                # Only call content_modified if we're not already in it (prevent recursion)
                if not getattr(self, '_in_content_modified', False):
                    self.content_modified()
            elif create_if_missing:
                # Create the missing element based on the element and attributes in the path
                # the path must be absolute, and any attributes found in predecates are created
                # with the assocaited element.

                # Expect an absolute path like /...; tolerate and normalize if needed
                if not path.startswith('/'):
                    logger.warning("XPath not absolute; treating as absolute: " + path)

                # Split into path steps, ignore empty parts caused by leading '/'
                parts = [p for p in path.split('/') if p]

                # Start at document root
                current = self.tree.getroot() if isinstance(self.tree, ElementTree.ElementTree) else self.tree
                if current is None:
                    logger.error("No XML tree available to set field.")
                    return

                # If first part is a wildcard (*) that represents the root element, skip it
                idx = 0
                if parts and parts[0] == '*':
                    idx = 1

                for part in parts[idx:]:
                    # Parse element name and optional predicate(s) inside brackets
                    m = re.match(r"(?P<name>[^\[]+)(\[(?P<pred>.+)\])?$", part.strip())
                    if not m:
                        logger.warning(f"Unrecognized path segment: {part}")
                        continue

                    name = m.group('name')
                    pred = m.group('pred')

                    # Parse predicates (support simple attribute predicates joined by 'and'):
                    # examples supported: @id='val', @uuid="val", @flag
                    predicates = []
                    if pred:
                        for sub in re.split(r"\s+and\s+", pred):
                            sub = sub.strip()
                            ma = re.match(r"@(?P<attr>[\w:-]+)(?:\s*=\s*'(.*?)'|\s*=\s*\"(.*?)\")?$", sub)
                            if ma:
                                attr = ma.group('attr')
                                val = ma.group(2) if ma.group(2) is not None else ma.group(3)
                                predicates.append((attr, val))
                            else:
                                logger.warning(f"Unsupported predicate format: {sub}")

                    # Search for an existing matching child
                    match_node = None
                    for child in list(current):
                        child_local = child.tag.split('}')[-1]  # handle namespace-qualified tags
                        if name != '*' and child_local != name:
                            continue
                        ok = True
                        for (attr, val) in predicates:
                            if val is None:
                                # predicate only requires presence of attribute
                                if child.get(attr) is None:
                                    ok = False
                                    break
                            else:
                                if child.get(attr) != val:
                                    ok = False
                                    break
                        if ok:
                            match_node = child
                            break

                    # If not found, create the element (and set any attribute predicates)
                    if match_node is None:
                        new_tag = name
                        new_elem = ElementTree.Element(new_tag)
                        for (attr, val) in predicates:
                            # If predicate required presence only, create attribute with empty string
                            if val is None:
                                new_elem.set(attr, "")
                            else:
                                new_elem.set(attr, val)
                        current.append(new_elem)
                        match_node = new_elem
                        # Only call content_modified if we're not already in it (prevent recursion)
                        if not getattr(self, '_in_content_modified', False):
                            self.content_modified()

                    # Descend into the matched/created node
                    current = match_node

                # Finally, set the element text
                if current is not None:
                    current.text = field_value
                    # Only call content_modified if we're not already in it (prevent recursion)
                    if not getattr(self, '_in_content_modified', False):
                        self.content_modified()
    # -------------------------------------------------------------------------
    def set_metadata(self, content={}):
        """
        Sets metadata fields in the OSCAL content.
        Args:
            content (dict): A dictionary containing metadata fields to set.
        """
        for item in content:
            logger.debug(f"Metadata field to set: {item} = {content[item]}")
            if item in ['revisions', 'document-ids', 'roles', 'locations', 'parties', 'links', 'props', 'responsible-parties']:
                # These are complex fields - skip for now
                logger.warning(f"Setting complex metadata field '{item}' is not yet implemented.")
                continue
            else:
                self.__set_field(f"/*/metadata/{item}", content.get(item, ""))



    # -------------------------------------------------------------------------
    def create_new_oscal_content(self, model_name: str, title: str="", version: str="", published: str=""):
        """
        Returns minimally valid OSCAL content based on the specified model name.
        Currently this is based on loading a template file from package data.
        In the future, this should be generated based on the latest metaschema definition.
        Args:
            model_name (str): The OSCAL model name (e.g., "system-security-plan").
        """
        # TODO: Generate new content based on newest metaschema definition for the model
        from xml.etree import ElementTree
        metadata = {}

        content = None
        if self.support.is_model_valid(model_name): # is the specified model name an actual OSCAL model?
            content = self.support.load_file(f"{model_name}.xml", binary=False)
            # If content is found and is of type string, load it as XML
            if content and isinstance(content, str):
                self.xml = content
                self.oscal_model = model_name
                # Parse to get version
                self.tree = ElementTree.ElementTree(ElementTree.fromstring(content.encode('utf_8')))
                self.oscal_version = self.xpath_atomic("//metadata/oscal-version/text()")
                # metadata["last-modified"] = oscal_date_time_with_timezone()
                if title != "":
                    metadata["title"] = title
                if version != "":
                    metadata["version"] = version
                if published != "":
                    metadata["published"] = published
                
                if metadata:
                    self.set_metadata(metadata)

                self.content_modified() # mark content as modified to update last-modified and uuid
                return content

        else:
            logger.error(f"Unsupported OSCAL model for new content: {model_name}")
            return None

    # -------------------------------------------------------------------------
    def initial_validation(self, content: str):
        """
        Perform initial validation of content, which includes first ensuring the 
        content is a recognized OSCAL format type (xml, json or yaml) and 
        well formed, before passing it to the OSCAL validation mechanism.
        """
        logger.debug("Performing initial validation of content...")
        status = False
        self.original_format = detect_data_format(content)
        root_element = ""
        oscal_version = ""
        
        if self.original_format in OSCAL_FORMATS:
            logger.debug(f"Content appears to be in {self.original_format} format.")
            match self.original_format:
                case "xml":
                    self.well_formed_xml = is_xml_well_formed(content)
                    if self.well_formed_xml:
                        # get root xml element
                        self.tree = ElementTree.ElementTree(ElementTree.fromstring(content.encode('utf_8')))
                        root_element = self.xpath_atomic("/*/name()")
                        oscal_version = f"v{self.xpath_atomic("/*/metadata/oscal-version/text()")}"
                        status = True
                    else:
                        logger.error("Content is not well-formed XML.")

                case "json":
                    self.well_formed_json = is_json_well_formed(content)
                    if self.well_formed_json:
                        pass
                        #get root element 
                    else:
                        logger.error("Content is not well-formed JSON.")
                case "yaml":
                    self.well_formed_yaml = is_yaml_well_formed(content)
                    if self.well_formed_yaml:
                        pass
                        # get root element
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
                else:
                    logger.error("ROOT ELEMENT IS NOT AN OSCAL MODEL: " + root_element)
                    status = False
            else:
                logger.error("OSCAL VERSION IS NOT RECOGNIZED: " + oscal_version)
                status = False

        logger.debug("ROOT ELEMENT: " + str(root_element))
        if self.support.is_valid_version(oscal_version):
            models = self.support.enumerate_models(version=oscal_version)
            if root_element in models:
                logger.debug("OSCAL ROOT ELEMENT DETECTED: " + root_element)
                self.oscal_version = self.xpath_atomic("//metadata/oscal-version/text()")
                logger.debug("OSCAL_VERSION: " + str(self.oscal_version))
                if len(self.oscal_version) >= 5: # TODO: Look up value in list of known-valid OSCAL versions
                    self.OSCAL_validate()
            else:
                logger.error("ROOT ELEMENT IS NOT AN OSCAL MODEL: " + root_element)

        return status

    # -------------------------------------------------------------------------
    def OSCAL_validate(self):
        """
        Validate OSCAL content.
        This assumes the content has already been determined to be well-formed XML, JSON, or YAML,
        and that the OSCAL model and version have been identified.
        Currently uses the appropriate format schema.
        Eventually will use meataschema for direct validation.
        """
        logger.debug("Validating OSCAL content...")


        self.valid_oscal = True
        pass

    # -------------------------------------------------------------------------
    def OSCAL_convert(self, directive):
        """
        Currently does nothing. Will soon accept the following directive values:
        'xml-to-json'
        'xml-to-yaml'
        """
        pass

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
    def __saxon_serializer(self):
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
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    
    def xpath_atomic(self, xExpr, context=None):
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

        ret_value = elementpath.select(context, xExpr, namespaces=self.nsmap)

        logger.debug(f"xPath results type: {str(type(ret_value))} with {len(ret_value)} nodes found.")

        return ret_value

    def serializer(self):
        logger.debug("Serializing for Output")
        ElementTree.indent(self.tree)
        out_string = ElementTree.tostring(self.tree.getroot(), 'utf-8')
        logger.debug("LEN: " + str(len(out_string)))
        out_string = normalize_content(out_string)
        out_string = out_string.replace("ns0:", "")
        out_string = out_string.replace(":ns0", "")
        
        return out_string
    
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
                    group = ElementTree.Element("group")
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
                        overview_node.text = overview

                    if instruction != "":
                        instruction_node = ElementTree.SubElement(group, "part")
                        instruction_node.set("name", "instruction")
                        instruction_node.text = instruction

                    if remarks != "":
                        remarks_node = ElementTree.SubElement(group, "remarks")
                        remarks_node.text = remarks

                    parent_node.append(group)
                    self.content_modified()
                    status = True
                else:
                    logger.warning(f"CREATE GROUP: Unable to find parent group with id {parent_id}" )
            except Exception as error:
                logger.error(f"Error creating group ({id}): {type(error).__name__} - {str(error)}")
        else:
            logger.error("CREATE GROUP: Current model is not a catalog. Unable to create group.")

        return status

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
def create_new_oscal_content(model_name: str, title: str="", version: str="", published: str="", support_db_conn=None, support_db_type=SUPPORT_DATABASE_DEFAULT_TYPE) -> OSCAL:
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

                if oscal_object is not None:
                    metadata = {}
                    if title != "":
                        metadata["title"] = title
                    if version != "":
                        metadata["version"] = version
                    if published != "":
                        metadata["published"] = published
                
                    if metadata:
                        oscal_object.set_metadata(metadata)

                    oscal_object.content_modified() # mark content as modified to update last-modified and uuid
            except Exception as error:
                logger.error(f"Error creating new OSCAL content for model {model_name}: {type(error).__name__} - {str(error)}")
                oscal_object = None

    else:
        logger.error(f"Unsupported OSCAL model for new content: {model_name}")
    
    return oscal_object


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


if __name__ == '__main__':
    print("OSCAL Class Library. Not intended to be run as a stand-alone file.")

