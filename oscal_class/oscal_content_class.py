"""
    OSCAL Class

    A class for creation, manipulation, validation and format convertion of OSCAL content.
    All published OSCAL versions, formats and models can be validated and converted. 
    Creation and manipulation is OSCAL 1.2.0 compliant where implemented.

    OSCAL XML, JSON and YAML formats are supported.
    This class ingests and validates OSCAL content in its native format using the appropriate 
    NIST-published OSCAL schema.

    Conversion between XML and JSON in either direction uses the NIST-published conversion XSLT stylesheets.
    Conversion between JSON and YAML in either direction uses internal conversion via Python dictionaries.

    In the fFuture this library will perform validation and conversion using the NIST-published 
    OSCAL metaschema definitions, which include additional rules not handled by the XML and JSON schemas.
"""
from loguru import logger
import os
import json
import yaml
import uuid
from typing import Optional

from common.logging import LoggableMixin
from common.data import detect_data_format, safe_load, safe_load_xml
from xml.etree import ElementTree
import elementpath
from common.lfs import getfile, chkdir, putfile, normalize_content, save_json
from .oscal_support_class import OSCAL_support, OSCAL_DEFAULT_XML_NAMESPACE, OSCAL_FORMATS, SUPPORT_DATABASE_DEFAULT_FILE, SUPPORT_DATABASE_DEFAULT_TYPE
from .oscal_markdown import oscal_markdown_to_html
from .oscal_datatypes import oscal_date_time_with_timezone
from .oscal_converters import oscal_xml_to_json, oscal_json_to_xml

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
    def __init__(self, content="", filename="", support_db_conn="", support_db_type=SUPPORT_DATABASE_DEFAULT_TYPE):
        """
        OSCAL Class
        Must provide at least one of the following parameters:
        - content: A string containing the OSCAL content
        - filename: A path to a file containing the OSCAL content
        - support_db_conn: Database connection string or path for OSCAL Support instance
        - support_db_type: Database type (default: "sqlite3") for OSCAL Support instance

        content and new_model are mutually exclusive.

        Raises:
            ValueError: If no content, filename nor new_model is provided
        """
        logger.debug("Initializing OSCAL class instance...")
        # Need at least one of content, filename, or new_model
        if not content and not filename:
            # logger.error("No content, filename nor new_model. Unable to proceed.")
            raise ValueError("No content, filename nor new_model provided. Unable to proceed.")


        # If just a filename and no content, load the file
        if filename and not content:
            logger.debug(f"Loading OSCAL content from file: {filename}")
            self.filename = filename
            content = getfile(filename)
            if not content:
                logger.error(f"Unable to get file: {filename}")
                raise ValueError(f"Unable to get file: {filename}")

        logger.debug("Setting up OSCAL content properties...")

        self.content = content
        self.original_location = filename
        self.original_format = ""

        self.oscal_model = ""
        self.oscal_version = ""
        self.content_title = ""
        self.content_publication = ""
        self.content_version = ""
        self.remarks = ""

        self.dict = None # JSON/YAML constructs
        self.tree = None # XML constructs
        self.nsmap = {"": OSCAL_DEFAULT_XML_NAMESPACE} # XML namespace map
        self.__saxon = None

        self.synced = False # Boolean indicating whether the tree and dict are in sync
        # TODO: Have every function that moddifies content update the unsaved flag
        self.unsaved = True # Boolean indicating whether there are unsaved modifications

        self.well_formed = {}          # A dictionary indicating whether the content is well-formed for each format
        self.well_formed["xml"] = None
        self.well_formed["json"] = None
        self.well_formed["yaml"] = None
        self.schema_valid = {}       # A dictionary indicating whether the content is valid against the schema for each format
        self.schema_valid["xml"] = None
        self.schema_valid["json"] = None
        self.schema_valid["yaml"] = None # YAML schema validation uses the JSON schema
        self.metaschema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL Metaschema

        self.imports = []        # A list of imported OSCAL files, by CC-assigned UUID
        self.support = get_shared_oscal_support(support_db_conn, support_db_type)  # Always gets the same instance

        # Process content if we have it
        if self.content:
            logger.debug("Processing provided content...")
            self.initial_validation()
        else:
            raise ValueError("No content available.")

    # -------------------------------------------------------------------------
    def __str__(self):
        ret_value = "OSCAL:\n"
        ret_value += "=============================================================================\n"
        ret_value += f"= Model: {self.oscal_model}\n"
        ret_value += f"= Version: {self.oscal_version}\n"
        ret_value += "=============================================================================\n"
        ret_value += f"= Title: {self.content_title}\n"
        if self.content_publication:
            ret_value += f"= Publication Date: {self.content_publication}\n"
        if self.content_version:
            ret_value += f"= Content Version: {self.content_version}\n"
        if self.remarks:
            ret_value += "=============================================================================\n"
            ret_value += f" Remarks:\n{self.remarks}\n"
        if self.schema_valid.get(self.original_format, False):
            ret_value += "=============================================================================\n"
            ret_value += "= VALID OSCAL CONTENT\n"
        else:
            ret_value += "=============================================================================\n"
            ret_value += "= INVALID OSCAL CONTENT\n"
        if self.filename:
            ret_value += "=============================================================================\n"
            ret_value += f"= Source File: {self.filename}\n"

        return ret_value
    # -------------------------------------------------------------------------
    def initial_validation(self):
        """
        Perform initial validation of content, which includes first ensuring the 
        content is a recognized OSCAL format type (xml, json or yaml) and 
        well formed, before passing it to the OSCAL validation method.
        Returns:
            bool: True if initial validation is successful, False otherwise
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
                        self.well_formed["xml"] = True
                        root_element = self.xpath_atomic("/*/name()")
                        oscal_version = f"v{self.xpath_atomic("/*/metadata/oscal-version/text()")}"
                        content_title = self.xpath_atomic("/*/metadata/title/text()")
                        content_version = self.xpath_atomic("/*/metadata/version/text()")
                        content_publication = self.xpath_atomic("/*/metadata/published/text()")
                    else:
                        status = False
                        logger.error("Content is not well-formed XML.")

                case "json" | "yaml":
                    self.dict = safe_load(self.content, self.original_format)
                    if self.dict is not None:
                        logger.debug(f"Loaded content into dictionary for format {self.original_format}.")
                        status = True
                        root_element = next(iter(self.dict.keys())) if self.dict else ""
                        oscal_version = f"v{self.dict.get(root_element, {}).get('metadata', {}).get('oscal-version', '')}"
                        content_title = self.dict.get(root_element, {}).get('metadata', {}).get('title', '')
                        content_version = self.dict.get(root_element, {}).get('metadata', {}).get('version', '')
                        content_publication = self.dict.get(root_element, {}).get('metadata', {}).get('published', '')
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
                    self.content_title = content_title
                    self.content_version = content_version
                    self.content_publication = content_publication
                    logger.debug(f"OSCAL model '{self.oscal_model}' and version '{self.oscal_version}' identified.")
                    status = True
                    # **** TODO: VALIDATE ****
                    self.validate()
                else:
                    logger.error("ROOT ELEMENT IS NOT AN OSCAL MODEL: " + root_element)
                    status = False
            else:
                logger.error("OSCAL VERSION IS NOT RECOGNIZED: " + oscal_version)
                status = False

        return status

    # -------------------------------------------------------------------------
    def validate(self, format="") -> bool:
        """
        Validate OSCAL content.
        This assumes the content has already been determined to be well-formed XML, JSON, or YAML,
        and that the OSCAL model and version have been identified.
        Currently uses the appropriate format schema.
        Eventually will use meataschema for direct validation.
        """
        # TODO: Implement actual validation logic here
        logger.debug("Validating OSCAL content...")
        if format == "":
            format = self.original_format

        if format not in OSCAL_FORMATS:
            logger.error(f"The validation format specified ({format}) is not an OSCAL format.")
            self.valid_oscal = False
            return self.valid_oscal

        match format:
            case "xml":
                logger.debug("Validating XML content against schema...")
                xml_schema_content = self.support.asset(self.oscal_version, self.oscal_model, "xml-schema")
                
                if xml_schema_content:
                    try:
                        import xmlschema
                        
                        # Create schema object from string
                        schema = xmlschema.XMLSchema(xml_schema_content)
                        
                        # Validate - returns None if valid, raises exception if invalid
                        xml_string = self.xml_serializer()
                        schema.validate(xml_string)
                        self.schema_valid["xml"] = True
                        logger.debug("XML schema validation passed.")
                        
                    except xmlschema.XMLSchemaValidationError as e:
                        logger.error(f"XML schema validation failed: {e.reason}")
                        self.schema_valid["xml"] = False
                    except Exception as e:
                        logger.error(f"XML schema validation error: {str(e)}")
                        self.schema_valid["xml"] = False
                else:
                    logger.error("Unable to load XML schema for validation.")
                    self.schema_valid["xml"] = False

            case "json" | "yaml":
                logger.debug(f"Validating {format} content against schema...")
                json_schema_content = self.support.asset(self.oscal_version, self.oscal_model, "json-schema")

                if json_schema_content:
                    try:
                        import jsonschema_rs
                        
                        # Parse schema string to dict if needed
                        if isinstance(json_schema_content, str):
                            schema_dict = json.loads(json_schema_content)
                        else:
                            schema_dict = json_schema_content
                        
                        # Validate directly (returns True/raises exception)
                        jsonschema_rs.is_valid(self.dict, schema_dict)  # Quick check
                        # Or for detailed errors:
                        jsonschema_rs.validate(self.dict, schema_dict)
                        
                        self.schema_valid["json"] = True
                        logger.debug("JSON schema validation passed.")
                        
                    except jsonschema_rs.ValidationError as e:
                        logger.error(f"JSON schema validation failed: {e}")
                        self.schema_valid["json"] = False
                    except Exception as e:
                        logger.error(f"JSON schema validation error: {str(e)}")
                        self.schema_valid["json"] = False
                else:
                    logger.error("Unable to load JSON schema for validation.")
                    self.schema_valid["json"] = False


        self.valid_oscal = True
        return self.valid_oscal

    # -------------------------------------------------------------------------
    def convert(self, target_format: str, pretty_print: bool=False) -> None:
        """
        Convert the current OSCAL content to the target format. Options for pretty printing.
        Args:
            target_format: The target format to convert to ("xml", "json", or "yaml")
            pretty_print: Whether to pretty print the output (applies to JSON and YAML)
        """
        from .oscal_converters import oscal_xml_to_json, oscal_json_to_xml
        logger.debug(f"Converting OSCAL content to {target_format} format (pretty_print={pretty_print})...")

        match target_format.lower():
            case "xml":
                if self.original_format == "xml":
                    logger.debug("Content is already in XML format; no conversion needed.")
                    return
                elif self.original_format == "json":
                    # Convert JSON to XML
                    logger.debug("Converting JSON to XML...")
                    xsl_converter=self.support.asset(self.oscal_version, self.oscal_model, "json-to-xml")
                    if not xsl_converter:
                        logger.error("Unable to locate XSLT converter for JSON to XML conversion.")
                        return
                    self.content = oscal_json_to_xml(
                        json_content=self.content,
                        xsl_converter=xsl_converter,
                        validate_json=True
                    )
                    self.original_format = "xml"
                elif self.original_format in ["yaml", "yml"]:
                    # Convert YAML to JSON, then JSON to XML
                    logger.debug("Converting YAML to XML via JSON...")
                    json_content = json.dumps(self.dict, indent=INDENT if pretty_print else None)
                    xsl_converter=self.support.asset(self.oscal_version, self.oscal_model, "json-to-xml")
                    if not xsl_converter:
                        logger.error("Unable to locate XSLT converter for JSON to XML conversion.")
                        return
                    self.content = oscal_json_to_xml(
                        json_content=json_content,
                        xsl_converter=xsl_converter,
                        validate_json=True
                    )
                    self.original_format = "xml"
                else:
                    logger.error(f"Unsupported original format for conversion to XML: {self.original_format}")

            case "json":
                if self.original_format == "json":
                    logger.debug("Content is already in JSON format; no conversion needed.")
                    return
                elif self.original_format == "xml":
                    # Convert XML to JSON
                    logger.debug("Converting XML to JSON...")
                    xsl_converter=self.support.asset(self.oscal_version, self.oscal_model, "xml-to-json")
                    if not xsl_converter:
                        logger.error("Unable to locate XSLT converter for XML to JSON conversion.")
                        return
                    self.content = oscal_xml_to_json(
                        xml_content=self.content,
                        xsl_converter=xsl_converter
                    )
                    self.original_format = "json"
                elif self.original_format in ["yaml", "yml"]:
                    # Convert YAML to JSON
                    logger.debug("Converting YAML to JSON...")
                    self.content = json.dumps(self.dict, indent=INDENT if pretty_print else None)
                    self.original_format = "json"
                else:
                    logger.error(f"Unsupported original format for conversion to JSON: {self.original_format}")

            case "yaml" | "yml":
                if self.original_format in ["yaml", "yml"]:
                    logger.debug("Content is already in YAML format; no conversion needed.")
                    return
                elif self.original_format == "json":
                    # Convert JSON to YAML
                    logger.debug("Converting JSON to YAML...")


    # -------------------------------------------------------------------------
    def save(self, filename: str="", format: str="", pretty_print: bool=False):
        f"""
        Save the current OSCAL content to a file.
        With no parameters, saves to the original location in the original format.
        This will save to any valid filename, even if the file extension does not match the format.
        
        Args:
            filename (str): The path to the file where content will be saved.
            format (str): The format to save the content in {OSCAL_FORMATS}.
            pretty_print (bool): Whether to pretty print the output.

        """
        status = False

        # If a format is passed, ensure it is valid
        if format:
            format = format.lower()
            if format not in OSCAL_FORMATS:
                logger.debug(f"Cannot save in ({format}) format. Not an OSCAL format.")
                return

        # If no format is passed, use the original format
        else:
            format = self.original_format

        # If no format was passed and no original format, cannot proceed
        if format == "":
            logger.error("No format specified for saving OSCAL content.")
            return False

        # If no filename is passed, use the original location
        if filename == "":
            filename = self.original_location

        # If no filename was passed and no original location, cannot proceed
        if filename == "":
            logger.error("No filename specified for saving OSCAL content.")
            return False

        # Ensure the directory exists
        file_path = os.path.dirname(os.path.abspath(filename))
        if not chkdir(file_path, make_if_not_present=True):
            logger.error(f"Directory does not exist and could not be created: {os.path.dirname(file_path)}")
            return False

        logger.debug(f"Saving content as {filename} in OSCAL {format.upper()} format.")
        match format:
            case "xml":
                if not self.tree:
                    xml_output = oscal_json_to_xml(self.dict, 
                                      xsl_converter=self.support.asset(self.oscal_version, self.oscal_model, "json-to-xml"))
                    self.tree = ElementTree.ElementTree(ElementTree.fromstring(xml_out))
                else: 
                    xml_output = self.xml_serializer() 
                status = putfile(filename, xml_output)

            case "json" | "yml" | "yaml":
                if not self.dict:
                    json_output = oscal_xml_to_json(self.content, 
                                      xsl_converter=self.support.asset(self.oscal_version, self.oscal_model, "xml-to-json"))
                    self.dict = json.loads(json_output)

                if self.dict is None:
                    logger.error("No JSON content available to save.")
                    return False

                if format == "json":
                    status = save_json(filename, self.dict) # pretty_print=pretty_print)
                else: # YAML
                    yaml_out = yaml.dump(self.dict, sort_keys=False, indent=INDENT if pretty_print else None)   

                    status = putfile(filename, yaml_out)
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

    """
        # # -------------------------------------------------------------------------
        # def __setup_saxon(self): # Future - place holder for code for now
        #     from saxonche import PySaxonProcessor 

        #     self.__saxon = PySaxonProcessor(license=False)
        #     try: 
        #         self.xdm = self.__saxon.parse_xml(xml_text=self.xml)
        #         # self.__saxon.declare_namespace("", "http://csrc.nist.gov/ns/oscal/1.0")
        #         self.valid = True
        #         self.oscal_format = "xml"
        #     except Exception as error:
        #         logger.error(f"Content does not appear to be valid XML. Unable to rpoceed. {str(error)}")

        #     if self.valid:
        #         self.xp = self.__saxon.new_xpath_processor() # Instantiates XPath processing
        #         self.__saxon_handle_ns()
        #         self.xp.set_context(xdm_item=self.xdm) # Sets xpath processing context as the whole file
        #         temp_ret = self.__saxon_xpath_global("/*/name()")
        #         if temp_ret is not None:
        #             self.root_node = temp_ret[0].get_atomic_value().string_value
        #             logger.debug("ROOT: " + self.root_node)
        #         self.oscal_version = self.__saxon_xpath_global_single("/*/*:metadata/*:oscal-version/text()")
        #         logger.debug("OSCAL VERSION: " + self.oscal_version)

        # # -------------------------------------------------------------------------
        # def __saxon_xml_serializer(self):
        #     return self.xdm.to_string('utf_8')

        # # -------------------------------------------------------------------------
        # def __saxon_handle_ns(self):
        #     node_ = self.xdm
        #     child = node_.children[0]
        #     assert child is not None
        #     namespaces = child.axis_nodes(8)

        #     for ns in namespaces:
        #         uri_str = ns.string_value
        #         ns_prefix = ns.name

        #         if ns_prefix is not None:
        #             logger.debug("xmlns:" + ns_prefix + "='" + uri_str + "'")
        #         else:
        #             logger.debug("xmlns uri=" + uri_str + "'")
        #             # set default ns here
        #             self.xp.declare_namespace("", uri_str)

        # # -------------------------------------------------------------------------
        # def __saxon_xpath_global(self, expression):
        #     from saxonche import PyXdmValue
        #     ret_value = None
        #     logger.debug("Global Evaluating: " + expression)
        #     ret = self.xp.evaluate(expression)
        #     if  isinstance(ret,PyXdmValue):
        #         logger.debug("--Return Size: " + str(ret.size))
        #         ret_value = ret
        #     else:
        #         logger.debug("--No result")

        #     return ret_value

        # # -------------------------------------------------------------------------
        # def __saxon_xpath_global_single(self, expression):
        #     from saxonche import PyXdmValue
        #     ret_value = ""
        #     logger.debug("Global Evaluating Single: " + expression)
        #     ret = self.xp.evaluate_single(expression)
        #     if  isinstance(ret, PyXdmValue): # isinstance(ret,PyXdmNode):
        #         ret_value = ret.string_value
        #     else:
        #         logger.debug("--No result")
        #         logger.debug("TYPE: " + str(type(ret)))

        #     return ret_value

        # # -------------------------------------------------------------------------
        # def __saxon_xpath(self, context, expression):
        #     from saxonche import PyXdmValue
        #     ret_value = None
        #     logger.debug("Evaluating: " + expression)
        #     xp = self.__saxon.new_xpath_processor() # Instantiates XPath processing
        #     xp.set_context(xdm_item=context)
        #     ret = xp.evaluate(expression)
        #     if  isinstance(ret,PyXdmValue):
        #         logger.debug("--Return Size: " + str(ret.size))
        #         ret_value = ret
        #     else:
        #         logger.debug("--No result")

        #     return ret_value

        # # -------------------------------------------------------------------------
        # def __saxon_xpath_single(self, context, expression):
        #     from saxonche import PyXdmValue
        #     ret_value = ""
        #     logger.debug("Evaluating Single: " + expression)
        #     xp = self.__saxon.new_xpath_processor() # Instantiates XPath processing
        #     xp.set_context(xdm_item=context)
        #     ret = xp.evaluate_single(expression)
        #     if  isinstance(ret, PyXdmValue): # isinstance(ret,PyXdmNode):
        #         ret_value = ret.string_value
        #     else:
        #         logger.debug("--No result")
        #         logger.debug("TYPE: " + str(type(ret)))

        #     return ret_value
    """
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
    def get_serialized_content(self, format: str):
        """
        Serializes the current content to a string in the specified format.
        Parameters:
        - format (str): The target format for serialization ("xml", "json", or "yaml")
        
        Returns:
        - str: The serialized content as a string.
        """
        format = format.lower()
        if format not in OSCAL_FORMATS:
            logger.error(f"The requested format for serialization ({format}) is not an OSCAL format.")
            return ""

        if not self.valid_oscal:
            logger.error("Content is not valid OSCAL. Cannot serialize.")
            return ""

        # if format == self.original_format:

        match format:
            case "xml":
                # if self.tree is None:

                return self.xml_serializer()
            case "json":
                return self.json_serializer()
            case "yaml" | "yml":
                return self.yaml_serializer()
            case _:
                logger.error(f"Unsupported format for serialization: {format}")
                return ""



    # -------------------------------------------------------------------------
    def xml_serializer(self):
        """
        Serializes the current XML tree to a string.
        Returns:
        - str: The serialized XML content as a string.        
        """
        logger.debug("Serializing the XML tree for text output.")
        
        # Check if tree exists
        if self.tree is None:
            logger.error("No XML tree available for serialization")
            return ""
        
        # Handle both ElementTree and Element objects
        if isinstance(self.tree, ElementTree.ElementTree):
            root = self.tree.getroot()
        else:
            root = self.tree  # Already an Element
        
        # Additional safety check
        if root is None:
            logger.error("No root element available for serialization")
            return ""

        ElementTree.indent(root, space=" "* INDENT)
        out_string = ElementTree.tostring(root, 'utf-8')
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
    def assign_html_string_to_node(self, parent_node, html_string: str):
        """
        Assigns an HTML string to an XML node, converting it to proper XML structure.
        This properly handles mixed content (text + elements).
        Parameters:
        - parent_node (ElementTree.Element): The parent XML node to which the HTML content will be added.
        - html_string (str): The HTML string to convert and assign.
        """
        try:
            # Wrap the HTML string in a temporary root element
            wrapped_html = f"<div>{html_string}</div>"
            temp_root = ElementTree.fromstring(wrapped_html)

            # Handle mixed content properly
            # First, add any initial text content
            if temp_root.text:
                if parent_node.text is None:
                    parent_node.text = temp_root.text
                else:
                    parent_node.text += temp_root.text

            # Then append each child element with its tail text
            for child in temp_root:
                parent_node.append(child)
                # The tail text is automatically preserved when appending

            logger.debug("HTML string successfully assigned to node.")
        except Exception as error:
            logger.error(f"Error assigning HTML string to node: {type(error).__name__} - {str(error)}")
            logger.error("HTML String: " + html_string)

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
        logger.info(f"Creating new control with id '{id}' under parent group '{parent_id}'")
        status = False
        control = None
        if self.oscal_model == "catalog":
            try:
                parent_xpath = f"//group[@id='{parent_id}']"
                logger.debug(f"Creating control under parent id: {parent_id}")

                # Use elementpath for reliable XPath processing
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
                                            
                    # TODO: Handle child parts
                    # TODO: Handle part titles
                    # TODO: Handle part labels, sort-ids, alt-identifiers
                    # TODO: Handle other part properties
                    # TODO: Handle part references and related
                    # TODO: Handle part links
                    if len(statements) > 0:
                        statement_node = ElementTree.SubElement(control, "part")
                        statement_node.set("name", "statement")
                        statement_node.set("id", f"{id}_smt")
                        logger.debug(f"STATEMENTS TYPE: {type(statements)} with {len(statements)} items.")
                        if len(statements)  == 1:
                            if isinstance(statements[0], str):
                                # Single statement without id
                                logger.debug("Single statement without id detected.")
                                self.assign_html_string_to_node(statement_node, oscal_markdown_to_html(statements[0], True))
                            elif isinstance(statements[0], dict):
                                # Single statement with id
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
                    logger.warning(f"CREATE CONTROL: Unable to find parent group with id {parent_id}" )
            except Exception as error:
                logger.error(f"Error creating control ({id}): {type(error).__name__} - {str(error)}")
        else:
            logger.error("CREATE CONTROL: Current model is not a catalog. Unable to create control.")

        if not status:
            control = None

        return control

    # -------------------------------------------------------------------------
    def create_control_group(self, parent_id, id, title="", params=[], props=[], links=[], label="", sort_id="", alt_identifier="", overview="", instruction="", remarks=""):
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
                if parent_nodes is not None:
                    logger.debug(f"PARENT NODES LEN: {len(parent_nodes)}")
                    parent_node = parent_nodes[0] # if parent_nodes else None

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
        child = None
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
                if isinstance(node_content, str):
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

    # -------------------------------------------------------------------------
    def append_resource(self, uuid=None, title=None, description=None, props=[], rlinks=[], base64=None, remarks=""):
        """
        Appends a resource element to the back-matter section.
        """
        return append_resource(self, uuid, title, description, props, rlinks, base64, remarks)        

    # -------------------------------------------------------------------------
    def add_or_update_profile_import(self, href: str, include_all: bool = False, include_ids =[], include_with_child = False, exclude_ids =[], exclude_with_child = False):
        """
        If an import with the provided href already exists, updates it with the 
            provided include details.
        If an import with the provided href does not exist, but an import with an 
            empty href (href='#'), updates it with the provided href and include details.
        Otherwise, adds a new import statement with the provided href and include details.

        Parameters:
        - href (str): The href of the profile to import.
        - include_all (bool): Whether to include all controls from the imported profile.
        - import_id (str): An optional id for the import element.
        """
        logger.debug(f"Adding or updating profile import for href '{href}' with include_all={include_all} and import_ids={include_ids}")
        # if this isn't a profile, log warning and exit function
        if self.oscal_model != "profile":
            logger.warning(f"Current model is not a profile. Ignoring add_or_update_profile_import. [{href}]")
            return False

        # Find existing import by href. If it doesn't exist, look for empty href.
        # NOTE: This library's new/empty profile includes an import with href='#' by default.
        # If neither is found, create a new import element.
        import_obj = self.xpath(f"/*/import[@href='{href}']")
        if import_obj:
            logger.debug(f"Found existing import for href '{href}'. Updating it.")
            import_obj = import_obj[0]
        else:
            import_obj = self.xpath("/*/import[@href='#']")
            if  import_obj:
                logger.debug(f"Found existing import with empty href. Updating it to '{href}'.")
                import_obj = import_obj[0]
            else:
                logger.debug(f"No existing import found for href '{href}'. Creating new import element.")
                import_obj = ElementTree.Element(f"{{{OSCAL_DEFAULT_XML_NAMESPACE}}}import")
        
        # If unable to find nor create an import element, log error and exit function
        if import_obj is None:
            logger.error(f"Unable to create or update import for href '{href}'.")
            return False

        # Set the href attribute if needed
        if import_obj.get("href", "") != href:
            logger.debug(f"Setting import href to '{href}'.")
            import_obj.set("href", href)

        # Remove existing include/include-all elements
        include_obj = import_obj.find("include-controls")
        if include_obj is not None:
            logger.debug("Removing existing include-controls element")
            import_obj.remove(include_obj)

        # If include-all is specified and present, leave it.
        # If include-all is not specified but present, remove it.
        # If include-all is specified but not present, add it.
        include_all_obj = import_obj.find("include-all")
        if include_all and include_all_obj:
            logger.debug("Include-all already present.")
        elif not include_all and include_all_obj:
            logger.debug("Removing existing include-all element")
            import_obj.remove(include_all_obj)
        elif include_all and not include_all_obj:
            logger.debug("Adding include-all element.")
            include_obj = ElementTree.SubElement(import_obj, "include-all")

        # Add new include/include-all elements
        if not include_all and len(include_ids) > 0:
            include_obj = ElementTree.SubElement(import_obj, "include-controls")
            if include_with_child:
                include_obj.set("with-child-controls", "yes")
            for control_id in include_ids:
                with_id_obj = ElementTree.SubElement(include_obj, "with-id")
                with_id_obj.text = control_id

        # Add new include/include-all elements
        if include_all and len(exclude_ids) > 0:
            exclude_obj = ElementTree.SubElement(import_obj, "exclude-controls")
            if exclude_with_child:
                exclude_obj.set("with-child-controls", "yes")
            for control_id in include_ids:
                with_id_obj = ElementTree.SubElement(exclude_obj, "with-id")
                with_id_obj.text = control_id

        return True
    # -------------------------------------------------------------------------
    def append_profile_with_id(self, href, control_ids=[]):
        """
        Adds with-id element to a profile's import statement.
        """
        import_obj = self.xpath(f"/*/import[@href='{href}']")
        if import_obj:
            import_obj = import_obj[0]
            include_obj = import_obj.find("include-controls")
            if include_obj is None:
                include_obj = ElementTree.SubElement(import_obj, "include-controls")
            for control_id in control_ids:
                with_id_obj = ElementTree.SubElement(include_obj, "with-id")
                with_id_obj.text = control_id
        else:
            logger.error(f"Unable to find import for href '{href}'. Cannot append control IDs.")

        return True

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
def append_props(parent_node, props: list):
    """
    Appends multiple property elements to the provided parent XML node.
    Parameters:
    - parent_node (ElementTree.Element): The parent XML node to which the properties will be added.
    - props (list): A list of dictionaries, each containing property attributes and optional remarks.
    """
    for prop in props:
        append_prop(parent_node, prop)
# -------------------------------------------------------------------------
def append_prop(parent_node, prop: dict):
    """
    Appends a property element to the provided parent XML node.
    Parameters:
    - parent_node (ElementTree.Element): The parent XML node to which the property will be added.
    - prop (dict): A dictionary containing property attributes and optional remarks.
    """
    prop_node = ElementTree.SubElement(parent_node, "prop")
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
        remarks_html = oscal_markdown_to_html(prop.get('remarks', ''), multiline=True)
        if remarks_html:
            try:
                wrapped_html = f"<div>{remarks_html}</div>"
                temp_root = ElementTree.fromstring(wrapped_html)  # Use fromstring directly
                for child in temp_root:
                    remarks_node.append(child)
            except ElementTree.ParseError as e:
                logger.error(f"Error parsing remarks HTML: {e}")
                remarks_node.text = prop.get('remarks', '')
# -----------------------------------------------------------------------------
def append_links(parent_node, links: list):
    """
    Appends multiple link elements to the provided parent XML node.
    Parameters:
    - parent_node (ElementTree.Element): The parent XML node to which the links will be added.
    - links (list): A list of link URLs as strings.
    """
    for link in links:
        append_link(parent_node, link)
# -----------------------------------------------------------------------------
def append_link(parent_node, link: dict):
    """
    Appends a link element to the provided parent XML node.
    Parameters:
    - parent_node (ElementTree.Element): The parent XML node to which the link will be added.
    - link (dict): A dictionary containing link attributes.
    """
    link_node = ElementTree.SubElement(parent_node, "link")
    link_node.set("href", link.get('href', ''))
    if 'rel' in link:
        link_node.set("rel", link.get('rel', ''))
    if 'media-type' in link:
        link_node.set("media-type", link.get('media-type', ''))
    if 'resource-fragment' in link:
        link_node.set("resource-fragment", link.get('resource-fragment', ''))
    if 'text' in link:
        text_node = ElementTree.SubElement(link_node, "text")
        text_node.text = link.get('text', '')
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# NOTE: oscal_date_time_with_timezone is imported from oscal_datatypes (moved there to avoid circular imports)
# -----------------------------------------------------------------------------
def oscal_markdown_to_html_tree(markdown_text: str, multiline: bool = True) -> Optional[ElementTree.Element]:
    """
    Callls oscal_markdown_to_html, which Formats markdown text into HTML
    consistent with the OSCAL XML specification for markup-multiline. 

    Converts the resulting string into an XML object suitable for appending 
    into a a parent XML object.

    Args:
    markdown_text (str): The markdown text to convert
    multiline (bool): If True, handles markup-multiline (supports block elements).
                        If False, handles markup-line (inline elements only).
    
    Returns:
        Optional[ElementTree.Element]: ElementTree XML Element object, or None if conversion fails
    """
    html_str = oscal_markdown_to_html(markdown_text, multiline=multiline)
    if html_str:
        return ElementTree.fromstring(html_str.encode('utf_8'))
    else:
        return None
# -------------------------------------------------------------------------

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
def create_new_oscal_content(model_name: str, title: str, version: str="", published: str="", support_db_conn="", support_db_type=SUPPORT_DATABASE_DEFAULT_TYPE) -> Optional[OSCAL]:
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

# -------------------------------------------------------------------------
def append_resource(oscal_obj, uuid=None, title=None, description=None, props=[], rlinks=[], base64=None, remarks=""):
    """
    Appends a resource element to the back-matter section.
    """
    resource = ElementTree.Element("resource")
    if uuid is None:
        uuid = new_uuid()
    resource.set("uuid", uuid)
    if title is not None:
        title_node = ElementTree.SubElement(resource, "title")
        title_node.text = title
    if description is not None:
        desc_node = ElementTree.SubElement(resource, "description")
        desc_node.text = description
    for prop in props:
        prop_node = ElementTree.SubElement(resource, "prop")
        prop_node.set("name", prop.get("name", ""))
        prop_node.set("value", prop.get("value", ""))
        if "ns" in prop:
            prop_node.set("ns", prop.get("ns", ""))
        if "class" in prop:
            prop_node.set("class", prop.get("class", ""))
        if "group" in prop:
            prop_node.set("group", prop.get("group", ""))
    for rlink in rlinks:
        rlink_node = ElementTree.SubElement(resource, "rlink")
        rlink_node.set("href", rlink.get("href", ""))
        if "media-type" in rlink:
            rlink_node.set("media-type", rlink.get("media-type", ""))
    if base64 is not None:
        logger.warning("Base64 content in resource is not yet implemented.")
    if remarks:
        remarks_obj = ElementTree.SubElement(resource,"remarks") # Create the description element
        remarks_element = oscal_markdown_to_html_tree(remarks, multiline=True)
        if remarks_element is not None:
            remarks_obj.append(remarks_element)
    back_matter = oscal_obj.xpath("//back-matter")

    if back_matter:
        back_matter = back_matter[0]
    else:
        back_matter = ElementTree.Element("back-matter")
        oscal_obj.tree.append(back_matter)

    back_matter.append(resource)

    return resource
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# -----------------------------------------------------------------------------
def append_component(ssp_obj, component_type, component_title, component_description, op_status="operational", component_uuid=None, props=[], links=[], remarks=""):
    """
    Adds a "component" to an SSP's system implementation section.
    """
    if component_uuid is None:
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
        system_imiplementation_obj[0].append(component_obj)
        logger.debug(f"Adding component: {ElementTree.tostring(component_obj, 'utf-8')}")
    except (Exception, BaseException) as error:
        logger.error(f"Error appending component (type={component_type}) {component_title}: " + type(error).__name__ + " - " + str(error))
        component_obj = None

    return component_obj

# -----------------------------------------------------------------------------
def append_impl_requirement(ssp_obj, control_id, props=[], links=[], remarks=""):
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
        if system_imiplementation_obj is not None:
            logger.debug("Adding implemented-requirement")
            system_imiplementation_obj[0].append(impl_req_obj)
        else:
            logger.error("Failed to find system-implementation element in SSP.")
    except (Exception, BaseException) as error:
        logger.error(f"Error appending implemented-requirement for control: {control_id}: " + type(error).__name__ + " - " + str(error))
        impl_req_obj = None

    return impl_req_obj



# -----------------------------------------------------------------------------
def append_by_component(impl_req_obj, component_uuid, description, by_component_uuid=None, implementation_status="implemented", remarks=""):
    """
    Adds a "by-component" statement to an SSP's contrtol response statement.

    """
    logger.debug("Appending by-component assembly")
    if by_component_uuid is None:
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
def append_responsible_role(oscal_obj, role_id, party_uuids=[], remarks=None):
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

    if remarks:
        logger.debug("Adding remarks")
        remarks_obj = ElementTree.Element("remarks") # Create the description element

        remarks_element = oscal_markdown_to_html_tree(remarks, multiline=True)
        if remarks_element is not None:
            remarks_obj.append(remarks_element)
        resp_role_obj.append(remarks_obj)

    return resp_role_obj


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# -------------------------------------------------------------------------
# -----------------------------------------------------------------------------
def serializer(xml_object):
    """
    Converts the XML tree object to string, suitable for saving and inspecting.
    """
    logger.debug("Serializing for output")
    if xml_object is not None:
        ElementTree.indent(xml_object)
        out_string = ElementTree.tostring(xml_object, 'utf-8')
        out_string = normalize_content(out_string)
        out_string = out_string.replace("ns0:", "")
        out_string = out_string.replace(":ns0", "")
        # out_string = out_string.decode('utf-8')
    else:
        out_string = ""

    return out_string
# -----------------------------------------------------------------------------
def new_uuid():
    return str(uuid.uuid4())


if __name__ == '__main__':
    print("OSCAL Class Library. Not intended to be run as a stand-alone file.")

