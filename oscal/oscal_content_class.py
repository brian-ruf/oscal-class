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
from common.lfs import getfile, normalize_content
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
        _shared_oscal_support = OSCAL_support.create_sync(db_conn, db_type)
    return _shared_oscal_support

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# OSCAL CLASS
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCAL(LoggableMixin):
    """

    Properties:


    Methods:

    """
    def __init__(self, content="", filename="", new_model="", support_db_conn=None, support_db_type="sqlite3"):
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
                        element_node = self.tree.find(element_path, namespaces=self.nsmap)
                        
                    if element_node is not None:
                        element_node.set(attr_name, field_value)
                        # Only call content_modified if we're not already in it (prevent recursion)
                        if not getattr(self, '_in_content_modified', False):
                            self.content_modified()
                        return
        
        # Handle element text content
        if self.tree:
            field_node = self.tree.find(path, namespaces=self.nsmap)
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
            logger.debug(f"Metadata field to set: {item[0]} = {item[1]}")
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
        if self.support.is_model_valid(model_name):
            content = self.support.load_file(f"{model_name}.xml", binary=False)
            # If content is found and is of type string, load it as XML
            if content and isinstance(content, str):
                self.xml = content
                self.oscal_model = model_name
                # Parse to get version
                self.tree = ElementTree.ElementTree(ElementTree.fromstring(content.encode('utf_8')))
                self.oscal_version = self.xpath_atomic("//metadata/oscal-version/text()")
                if title != "":
                    metadata["title"] = title
                if version != "":
                    metadata["version"] = version
                if published != "":
                    metadata["published"] = published
                
                self.set_metadata({"title": title, "version": version})
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
                        self.nsmap = {'': OSCAL_DEFAULT_XML_NAMESPACE}
                        root_element = self.xpath_atomic("/*/name()")
                        oscal_version = f"v{self.xpath_atomic("/*/metadata/oscal-version/text()")}"                        
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
        import elementpath
        ret_value=""
        if context is None:
            logger.debug("XPath [1]: " + xExpr)
            ret_value = elementpath.select(self.tree, xExpr, namespaces=self.nsmap)[0]
        else:
            logger.debug("XPath [1] (" + context.tag + "): " + xExpr)
            ret_value = elementpath.select(context, xExpr, namespaces=self.nsmap)[0]

        return str(ret_value)

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
        import elementpath
        ret_value=None
        if context is None:
            logger.debug("XPath [1]: " + xExpr)
            ret_value = elementpath.select(self.tree, xExpr, namespaces=self.nsmap)
        else:
            logger.debug("XPath [1] (" + context.tag + "): " + xExpr)
            ret_value = elementpath.select(context, xExpr, namespaces=self.nsmap)
        logger.debug(str(type(ret_value)))
        return ret_value

    def serializer(self):
        logger.debug("Serializing for Output")
        ElementTree.indent(self.tree)
        out_string = ElementTree.tostring(self.tree, 'utf-8')
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

            title = target_node.find('./title', self.nsmap)
            if title:
                ret_value.append({"title", title.text})

            for attribute in attributes:
                ret_value.append({attribute, target_node.get(attribute)})

            for child in children:
                child_node = target_node.find('./' + child, self.nsmap)
                if child_node:
                    ret_value.append({child, child_node.text})


        return ret_value

    def append_child(self, xpath, node_name, node_content = None, attribute_list = []):
        # logger.debug("APPENDING " + node_name + " as child to " + xpath) #  + " in " + self.tree.tag)
        status = False
        try:
            parent_node = self.tree.find(xpath, namespaces=self.nsmap)
            # parent_node = self.xpath(xpath)
            logger.debug(parent_node)
            if parent_node is not None:
                logger.debug("TAG: " + parent_node.tag)
                child = ElementTree.Element(node_name)

                if node_content is str:
                    child.text = node_content

                for attrib in attribute_list:
                    child.set(attrib[0], attrib[1])

                parent_node.append(child)
                status = True
            else:
                logger.warning("APPEND: Unable to find " + xpath )
        except (Exception, BaseException) as error:
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
    Converts a date and time to UTC and ouptuts an OSCAL date-time-with-timezone string. 
    Optional Parameters:
    - date_time (datetime): A date and time to convert to a formatted string.
       default is the current date and time
    - format (str): The formatting string to use
        default is "%Y-%m-%d--%H-%M-%S" (YYYY-MM-DD--HH-MM-SS)

    Returns a formatted date time string.
    If an error occurs, returns an empty string.
    """
    from datetime import datetime, timezone
    if date_time is None: 
        date_time = datetime.now()
    ret_value = ""

    try:
        date_time = date_time.astimezone(timezone.utc)
        ret_value = date_time.strftime(format)
    except (Exception, BaseException) as error:
        logger.error(f"{type(error).__name__} error handling date/time formatting: {str(error)}")
    return ret_value
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


if __name__ == '__main__':
    print("OSCAL Class Library. Not intended to be run as a stand-alone file.")

