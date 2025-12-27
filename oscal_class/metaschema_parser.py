import asyncio
import sys
import json
# from html import escape
# import html
# from urllib.parse import urljoin
from loguru import logger
from oscal_support import *
from xml.etree import ElementTree
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import tostring
from common import *

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# TODO:
# - Add support for metaschema constraints
# - Fix metaschema CHOICE
# TODO: Fix the recursion detection, such as for task/task or part/part.
# TODO: Fix handling of Group-as elements (May be fixed. Need to verify.)
# -------------------------------------------------------------------------

global_counter = 0
global_unhandled_report = []
global_stop_here = False

"""Metaschema Parser for OSCAL
This module provides functionality to parse and process OSCAL metaschema XML files.

While there is some defensive coding, this module assumes metaschema files are valid.

It is not intended to validate metaschema structure or content.
It will ignore unexpected structures.
It will issue a WARNING message if it encounteres expected, but unhandled structures. 

"""
SUPPRESS_XPATH_NOT_FOUND_WARNINGS = True
RUNAWAY_LIMIT = 8000
DEBUG_OBJECT = "choice"

PRUNE_JSON = True  # If true, will remove None values and emnpty arrays from the Resolved JSON Metaschema output
OSCAL_DEFAULT_NAMESPACE = "http://csrc.nist.gov/ns/oscal"
METASCHEMA_DEFAULT_NAMESPACE = "http://csrc.nist.gov/ns/oscal/metaschema/1.0"
METASCHEMA_TOP_IGNNORE = ["schema-name", "schema-version", "short-name", "namespace", "json-base-uri", "remarks", "import"]
METASCHEMA_TOP_KEEP = ["define-assembly", "define-field", "define-flag", "constraint"]
METASCHEMA_PROPS_HANDLED = ["identifier-persistence", "identifier-scope", "identifier-type", "identifier-uniqueness", "value-type"]
METASCHEMA_RULE_PROPS_HANDLED = []
METASCHEMA_INDEX_PROPS_HANDLED = []
METASCHEMA_ROP_NAMESPACE = ["http://csrc.nist.gov/ns/oscal/metaschema/1.0", "http://csrc.nist.gov/ns/metaschema/1.0"]
METASCHEMA_ROOT_ELEMENT = "METASCHEMA"
CONSTRAINT_ROOT_ELEMENT = "metaschema-meta-constraints"
CONSTRAINT_TOP_IGNORE = []
CONSTRAINT_TOP_KEEP = ["context"]

GREEN   = "\033[32m"
BLUE    = "\033[34m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
ORANGE  = "\033[38;5;208m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
PURPLE  = "\033[38;5;129m"
BOLD    = "\033[1m"
RESET   = "\033[0m"

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
async def parse_metaschema(support=None, oscal_version=None) -> int:
    """
    Parse the OSCAL metaschema for a given version.
    This function is used to parse the OSCAL metaschema for a given version.
    Parameters:
    - support (OSCAL_support): The OSCAL support object.
    - oscal_version (str): The OSCAL version to parse. If None, all supported versions are processed.
    Returns:
    - int: 0 if successful, 1 if there was an error.
    """

    status = False
    ret_value = 1

    # If support object is not provided, we have to instantiate it.
    if support is None:
        base_url = "./support/support.oscal"
        support = await setup_support(base_url)

    if support.ready:
        logger.debug("Support file is ready.")
        status = True
    else:
        logger.error("Support object is not ready.")

    # If the support object is ready, we can proceed.
    if status:
        if oscal_version is None: # If no version is specified, process all supported versions.
            logger.info("Processing all supported OSCAL versions.")
            for version in support.versions.keys():
                logger.info(f"Version: {version}")
                status = await parse_metaschema_specific(support, version)
                if not status:
                    logger.error(f"Failed to parse metaschema for version {version}.")
                    break

        elif oscal_version in support.versions: # If a valid version is specified, process only that version.
            logger.info(f"Processing OSCAL version: {oscal_version}")
            status = await parse_metaschema_specific(support, oscal_version)

        else: # If an invalid version is specified, log an error and exit.
            logger.error(f"Specified version {oscal_version} is not supported. Available versions: {', '.join(support.versions.keys())}")
            status = False
    if status:
        ret_value = 0
    else:
        logger.error("Failed to parse metaschema. Exiting with error code 1.")
        ret_value = 1

    return ret_value

# --------------------------------------------------------------------------
async def parse_metaschema_specific(support, oscal_version):
    """
    Parse a specific metaschema model for a given OSCAL version.
    This function is used to parse a specific metaschema model
    for a given OSCAL version.
    Parameters:
    - support (OSCAL_support): The OSCAL support object.
    - oscal_version (str): The OSCAL version to parse.
    - oscal_model (str): The OSCAL model to parse.
    Returns:
    - dict: A dictionary representing the parsed metaschema tree,
            or an empty dictionary if parsing fails.
    """
    global global_counter
    logger.info(f"{CYAN}Parsing OSCAL {oscal_version} metaschema.{RESET}")
    status = True
    metaschema_tree = {}
    metaschema_tree["oscal_version"] = oscal_version
    metaschema_tree["oscal_models"] = {}

    models = await support.enumerate_models(oscal_version)

    for model in models:
        if model != "complete":
            global_counter = 0
            # Fetch the XML content
            logger.info(f"Parsing {model} metaschema.")    
            model_metaschema = await support.asset(oscal_version, model, "metaschema")
            if model_metaschema:
                if status:
                    # **** Commented out for testing. Uncomment when ready to use.
                    parser = await MetaschemaParser.create(model_metaschema, support)
                    status = await parser.top_pass()
                    metaschema_tree["oscal_models"][model] = parser.build_metaschema_tree()
                    if metaschema_tree["oscal_models"][model] is not None and metaschema_tree["oscal_models"][model] != {}:
                        logger.debug(f"Successfully parsed {model} metaschema.") 
                    else:
                        logger.error(f"Failed to parse {oscal_version} {model} metaschema. No data returned.")  
                else:
                    logger.error(f"Failed to setup the {model}. metaschema")
                
                status = True
            else:
                logger.error(f"Failed to fetch {model} metaschema content.")
                status = False

    if status:
        logger.info(f"{GREEN}Successfully parsed all {oscal_version} metaschema models. Adding to support module.{RESET}")
        status = await support.add_asset(oscal_version, "complete", "processed", json.dumps(metaschema_tree, indent=2), filename=f"OSCAL_{oscal_version}_metaschema.json")

        # # save to a JSON file
        output_file = f"{oscal_version}_complete_metaschema.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(metaschema_tree, f, indent=2)



    return status
# --------------------------------------------------------------------------
def clean_none_values_recursive(dictionary):
    """
    Recursively remove all key/value pairs where the value is None from dictionaries,
    including nested dictionaries.
    """
    result = {}
    for k, v in dictionary.items():
        if v is None:
            continue
        elif isinstance(v, dict):
            cleaned = clean_none_values_recursive(v)
            if cleaned:  # Only add non-empty dictionaries
                result[k] = cleaned
        elif isinstance(v, list):
            cleaned_list = []
            for item in v:
                if isinstance(item, dict):
                    cleaned_item = clean_none_values_recursive(item)
                    if cleaned_item:  # Only add non-empty dictionaries
                        cleaned_list.append(cleaned_item)
                elif item is not None:
                    cleaned_list.append(item)
            if cleaned_list:  # Only add non-empty lists
                result[k] = cleaned_list
        else:
            result[k] = v
    return result

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class MetaschemaParser:
    def __init__(self, metaschema, support, import_inventory=[], oscal_version=""):
        logger.debug(f"Initializing MetaschemaParser")
        self.content = metaschema
        self.valid_xml = False
        self.top_level = False
        self.xml_namespace = ""
        self.oscal_version = oscal_version
        self.oscal_model = ""
        self.schema_name = ""
        self.oscal_namespace = ""
        self.json_base_uri = ""
        self.tree = None
        self.nsmap = {"": METASCHEMA_DEFAULT_NAMESPACE}
        self.support = support
        self.imports = {} # list of imports {"metaschema_file_name.xml": MetaschemaParser_Object, ...}
        self.import_inventory = import_inventory

    # -------------------------------------------------------------------------
    @classmethod
    async def create(cls, metaschema, support, import_inventory=[], oscal_version=""):
        logger.debug(f"Creating MetaschemaParser")
        ret_value = None
        ret_value = cls(metaschema, support, import_inventory, oscal_version)
        return ret_value

    # -------------------------------------------------------------------------
    def __str__(self):
        """String representation of the MetaschemaParser."""
        ret_value = ""
        ret_value += f"Schema: {self.schema_name}\n"
        ret_value += f"Model: {self.oscal_model}\n"
        ret_value += f"Version: {self.oscal_version}\n"
        ret_value += f"XML Namespace: {self.nsmap}\n"
        ret_value += f"Valid XML: {misc.iif(self.valid_xml, "Yes", "No")}\n"
        return ret_value
    
    # -------------------------------------------------------------------------
    def str_node(self, node):
        """String representation of the MetaschemaParser."""
        ret_value = ""
        ret_value += f"{node["formal-name"]}: {node["use-name"]}"
        if node["name"] != node["use-name"]:
            ret_value += f" ({node["name"]})"
        if node["deprecated"] is True:
            ret_value += f" ** Deprecated**"
        if node["sunsetting"] is not None:
            ret_value += f" Sunsetting: {node["sunsetting"]}"
        ret_value += "\n"

        if node["min-occurs"] == "0":
            if node["max-occurs"] == "1":
                ret_value += f"[0 or 1]"
            elif node["max-occurs"] == "unbounded":
                ret_value += f"[0 or more]"
            elif node["max-occurs"] is not None:
                ret_value += f"[0 to {node["max-occurs"]}]"
        elif node["min-occurs"] == "1":
            if node["max-occurs"] == "1":
                ret_value += f"[exactly 1]"
            elif node["max-occurs"] == "unbounded":
                ret_value += f"[1 or more]"
            elif node["max-occurs"] is not None:
                ret_value += f"[{node["min-occurs"]} to {node["max-occurs"]}]"
        else:
            if node["min-occurs"] is not None and node["max-occurs"] is not None:
                ret_value += f"[{node["min-occurs"]} to {node["max-occurs"]}]"
            else:
                ret_value += f"[Cardinality not specified]"
        ret_value += f" {node["structure-type"]} "
        ret_value += f" [{node["datatype"]}]"
        ret_value += f"Path: {node["path"]}\n"

        if node["default"] is not None:
            ret_value += f"Default: {node["default"]}\n"
        if node["description"] is not None:
            ret_value += f"Description: {node["description"]}\n"
        if node["remarks"] is not None:
            ret_value += f"Remarks: {node["remarks"]}\n"
        if node["example"] is not None:
            ret_value += f"Example: {node["example"]}\n"
        if node["flags"] is not None:
            ret_value += f"Flags: {len(node["flags"])}\n"
        if node["source"] is not None:
            ret_value += f"Source: {', '.join(node["source"])}\n"
        if node["children"] is not None:
            ret_value += f"Children: {len(node["children"])}\n"
        if node["props"] is not None:
            ret_value += f"Props: {', '.join(node["props"])}\n"

        if node["group-as"] is not None:
            ret_value += f"Group As: "
            if node["group-as-in-json"] is not None:
                ret_value += f" JSON: {node["group-as-in-json"]}"  
            if node["group-as-in-xml"] is not None:
                ret_value += f" XML: {node["group-as-in-xml"]}"
            ret_value += "\n"

        # if node["json-array-name"]:
        #     ret_value += f"JSON Array Name: {node["json-array-name"]} "
        # if node["json-value-key"]:
        #     ret_value += f" JSON Value Key: {node["json-value-key"]}"
        # if node["json-value-key-flag"]:
        #     ret_value += f" JSON Value Key Flag: {node["json-value-key-flag"]}"
        # ret_value += "\n"

        if node["wrapped-in-xml"] is not None:
            if node["wrapped-in-xml"]:
                ret_value += f"In XML: WRAPPED\n"
            else:
                ret_value += f"In XML: UNWRAPPED\n"
            ret_value += "\n"
        if node["rules"] is not None:
            ret_value += f"Rules: {len(node["rules"])}\n"
        return ret_value

    # -------------------------------------------------------------------------
    async def top_pass(self):
        """Perform the first pass of parsing."""
        logger.debug("Performing top pass")

        try:
            self.tree = data.deserialize_xml(self.content, METASCHEMA_DEFAULT_NAMESPACE)
            self.valid_xml = True
            logger.debug(f"XML Valid! Content length: {len(self.content)}")
        except ElementTree.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            self.valid_xml = False

        if self.valid_xml:
            self.oscal_model = self.xpath_atomic("/METASCHEMA/define-assembly/root-name/text()")
            if self.oscal_model:
                self.top_level = True
            else:
                self.oscal_model = self.xpath_atomic("/METASCHEMA/short-name/text()")
                if not self.oscal_model:
                    self.oscal_model = "unnamed-imported-metaschema"
            self.schema_name = self.xpath_atomic("/METASCHEMA/schema-name/text()")
            if self.oscal_version == "":
                self.oscal_version = f"v{self.xpath_atomic("/METASCHEMA/schema-version/text()")}"
                logger.info(f"DEBUG: Setting version to {self.oscal_version} for {self.oscal_model}")

            self.oscal_namespace = self.xpath_atomic("/METASCHEMA/namespace/text()")
            self.json_base_uri = self.xpath_atomic("/METASCHEMA/json-base/text()")

            await self.setup_imports()
            # await self.handle_imports()
        else:        
            logger.error("Invalid XML content.")

        return self.valid_xml

    # -------------------------------------------------------------------------
    async def setup_imports(self):
        """Identify import elements and set them up as import objects."""
        logger.debug(f"Setting up imports for {self.oscal_model}")
        import_directives = data.xpath(self.tree, self.nsmap, '/./METASCHEMA/import/@href')
        logger.debug(f"Imports: {self.imports}")

        if import_directives is not None:
            if not isinstance(import_directives, list):
                logger.debug(f"Import directives is not None and not a list: {import_directives}")
                import_directives = [import_directives]

            for imp_file in import_directives:
                logger.debug(f"Import file: {imp_file}")
                if imp_file:
                    # logger.info(f"Processing import: {imp_file}")
                    if False: # imp_file in self.import_inventory:
                        logger.info(f"Import {imp_file} already processed.")
                    else:
                        logger.debug(f"Processing {imp_file}  ...")
                        self.import_inventory.append(imp_file)
                        model_name = imp_file
                        if model_name.startswith("oscal_"):
                            model_name = model_name[len("oscal_"):]
                        if model_name.endswith("_metaschema_RESOLVED.xml"):
                            model_name = model_name[:-len("_metaschema_RESOLVED.xml")]

                        logger.debug(f"Model name: {model_name}")
                        import_content = await self.support.asset(self.oscal_version, model_name, "metaschema")
                        if import_content:
                            logger.debug(f"Version: {self.oscal_version} Model: {model_name} Content length: {len(import_content)}")
                            import_obj = await MetaschemaParser.create(import_content, self.support, self.import_inventory, self.oscal_version)
                            status = await import_obj.top_pass()
                            logger.debug(f"Import status: {status}")
                            if status:
                                self.imports[model_name] = import_obj
                                # self.imports.append({imp_file: import_obj})
                                logger.debug(f"Imports[0] for {imp_file}: {misc.iif(import_obj.top_level, "TOP", "NOT TOP")}")
                            else:
                                logger.error(f"Invalid Import file: {imp_file}")
        # logger.info(f"IMPORTS FOR {self.oscal_model}: {self.imports}")
        # logger.info(f"IMPORTS FOR {self.oscal_model}: {self.import_inventory}")

    # -------------------------------------------------------------------------
    def xpath_atomic(self, xExpr, context=None):
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
        - an empty string if there is an error or if nothing is found.
        - The first result of the xpath expression as a string.
        """

        return data.xpath_atomic(self.tree, self.nsmap, xExpr, context)

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
        - an element object or a list of element objects if the xpath expression
        is successful.
        """
        

        return data.xpath(self.tree, self.nsmap, xExpr, context)

    # -------------------------------------------------------------------------
    def get_markup_content(self, xExpr, context=None):
        """
        Performs an xpath query where the response is expected to be either
        just a string, or a node with HTML formatting.
        Returns the content as a stirng either way.
        """
        return data.get_markup_content(self.tree, self.nsmap, xExpr, context)

    # -------------------------------------------------------------------------
    def build_metaschema_tree(self):
        """
        Build the metaschema tree.
        """
        logger.debug(f"Resolving the metaschema tree for {self.oscal_model}")
        metaschema_tree = {}

        try:
            context = self.xpath("/METASCHEMA")
            metschema_tree = {}
            metaschema_tree = {}
            metaschema_tree["oscal_model"] = self.oscal_model
            metaschema_tree["oscal_version"] = self.oscal_version
            metaschema_tree["schema_name"] = self.schema_name
            metaschema_tree["oscal_namespace"] = self.oscal_namespace
            metaschema_tree["json_base_uri"] = self.json_base_uri
            metaschema_tree["import_inventory"] = self.import_inventory

            metaschema_tree["nodes"] = self.recurse_metaschema(self.oscal_model, "define-assembly", context=context)

        except Exception as e:
            metaschema_tree = {}
            logger.error(f"Error building metaschema tree: {e}")
            
        try:    
            if metaschema_tree:
                if PRUNE_JSON:
                    # Clean up the metaschema tree by removing None values and empty arrays
                    metaschema_tree["nodes"] = clean_none_values_recursive(metaschema_tree["nodes"])

                prefix = f"OSCAL_{self.oscal_version}_{self.oscal_model}"



                # output_file = f"{prefix}_unhandled_report.json"
                # with open(output_file, 'w', encoding='utf-8') as f:
                #     json.dump(global_unhandled_report, f, indent=2)


        except Exception as e:
            logger.error(f"Error saving metaschema tree: {e}")
        logger.debug(f"Metaschema tree built for {self.oscal_model} with {len(metaschema_tree.get('nodes', []))} nodes.")

        return metaschema_tree

    # -------------------------------------------------------------------------
    def initialize_metaschema_node(self):
        """
        Initialize a new node for the metaschema tree.
        This function sets up the initial structure of a metaschema tree node.
        It is called as each node is created, including the top level node.
        """

        # Reset the metaschema tree
        metaschema_node = {}
        metaschema_node["path"] = None
        metaschema_node["use-name"] = None
        metaschema_node["name"] = None
        metaschema_node["structure-type"] = None
        metaschema_node["datatype"] = None
        metaschema_node["min-occurs"] = None
        metaschema_node["max-occurs"] = None
        metaschema_node["default"] = None
        metaschema_node["pattern"] = None
        metaschema_node["formal-name"] = None
        metaschema_node["wrapped-in-xml"] = None
        metaschema_node["group-as"] = None
        metaschema_node["group-as-in-json"] = None
        metaschema_node["group-as-in-xml"] = None
        metaschema_node["json-array-name"] = None
        metaschema_node["json-value-key"] = None
        metaschema_node["json-value-key-flag"] = None
        metaschema_node["json-collapsible"] = None
        metaschema_node["deprecated"] = None
        metaschema_node["sunsetting"] = None
        metaschema_node["sequence"] = 0
        metaschema_node["source"] = []
        for prop_name in METASCHEMA_PROPS_HANDLED:
            metaschema_node[prop_name] = None
        metaschema_node["props"] = []
        metaschema_node["description"] = []
        metaschema_node["remarks"] = []
        metaschema_node["example"] = []
        metaschema_node["flags"] = []
        metaschema_node["children"] = []
        metaschema_node["constraints"] = []

        return metaschema_node

    # -------------------------------------------------------------------------
    def initialize_metaschema_rule(self):
        """
        Initialize a new metaschema rule.
        This function sets up the initial structure of a metaschema rule.
        It is called before each rule is created.
        """

        # Reset the metaschema tree
        metaschema_rule = {}
        metaschema_rule["id"] = None
        metaschema_rule["level"] = None
        metaschema_rule["name"] = None
        metaschema_rule["formal-name"] = None
        metaschema_rule["rule-type"] = None
        metaschema_rule["datatype"] = None
        metaschema_rule["default"] = None
        metaschema_rule["pattern"] = None
        metaschema_rule["allowed-values"] = {}
        metaschema_rule["allow-others"] = None
        metaschema_rule["extensible"] = None
        metaschema_rule["test"] = None
        metaschema_rule["message"] = None
        metaschema_rule["help-url"] = None
        metaschema_rule[""] = None
        metaschema_rule[""] = None
        metaschema_rule[""] = None
        metaschema_rule[""] = None
        metaschema_rule[""] = None


        metaschema_rule["min-occurs"] = None
        metaschema_rule["max-occurs"] = None

        metaschema_rule["deprecated"] = None
        metaschema_rule["sunsetting"] = None
        metaschema_rule["sequence"] = 0
        metaschema_rule["source"] = []
        for prop_name in METASCHEMA_RULE_PROPS_HANDLED:
            metaschema_rule[prop_name] = None
        metaschema_rule["props"] = []
        metaschema_rule["description"] = []
        metaschema_rule["remarks"] = []

        metaschema_rule["example"] = []
        metaschema_rule[""] = []

        return metaschema_rule

    # -------------------------------------------------------------------------
    def initialize_metaschema_index(self):
        """
        Initialize a new metaschema index.
        This function sets up the initial structure of a metaschema index.
        It is called before each index is created.
        """

        # Reset the metaschema tree
        metaschema_index = {}
        metaschema_index["id"] = None
        metaschema_index["level"] = None
        metaschema_index["name"] = None
        metaschema_index["target"] = None
        metaschema_index["formal-name"] = None
        metaschema_index["sequence"] = 0
        metaschema_index["source"] = []
        for prop_name in METASCHEMA_INDEX_PROPS_HANDLED:
            metaschema_index[prop_name] = None
        metaschema_index["props"] = []
        metaschema_index["pattern"] = None
        metaschema_index["description"] = []
        metaschema_index["remarks"] = []


    # ------------------------------------------------------------------------- 
    def recurse_metaschema(self, name, structure_type="define-assembly", parent="", ignore_local=False, already_searched=[], context=None, skip_children=False, use_name=None):
        """
        Recursively build the metaschema tree.
        This function processes the XML tree and extracts significant nodes
        based on the defined rules. It creates a dictionary representation of the
        metaschema structure, including attributes and child elements.
        Parameters:
        - oscal_model (str): The OSCAL model name.
        - structure_type (str): The type of structure to process (define-assembly, define-field, define-flag, assembly-field-flag).
        - ignore_local (bool): Flag to ignore local elements.
        Returns:
        - dict: A dictionary representation of the metaschema tree.


        NOTE: ignore_local should be true when performing this function on an imported
        metaschema. This is because the imported metaschema may have local elements
        that are not intended to be exposed to the importing metaschema file. 
        """
        global global_counter, global_unhandled_report, global_stop_here
        global_counter += 1
        logger.debug(f"{GREEN}[{global_counter}] Working in {self.oscal_model} on {structure_type}:{name} at [{parent}]{RESET}")

        # Create the metaschema tree (etablishes consistent sequence for keys that should always be present)
        metaschema_node = self.initialize_metaschema_node()
        metaschema_node["sequence"] = global_counter

        # ===== REASONS TO STOP PROCESSING BEFORE COMPLETION ==========================
        if global_counter > RUNAWAY_LIMIT:
            logger.error(f"Recursion limit reached. Exiting.")
            global_stop_here = True
            return metaschema_node

        if global_stop_here:
            logger.info(f"DEBUG: Stopping Early.")
            return None

        # .............................................................................
        # If this metaschema file was already searched, don't check it again
        if self.oscal_model in already_searched:
            logger.debug(f"Already searched {self.oscal_model}. Search List: {already_searched}. For {structure_type} {name}")
            return None
        else:
            already_searched.append(self.oscal_model)

        if DEBUG_OBJECT == name:
            logger.info(f"DEBUG: Working on {structure_type}: {name} in {self.oscal_model} under {parent}")
        if structure_type in ["field", "flag", "assembly"]:
            logger.debug(f"Looking for the {structure_type} definition for {name}")
            metaschema_node = self.recurse_metaschema(name, f"define-{structure_type}", parent=parent, already_searched=[], context=None) 

        # .............................................................................
        # Setup xpath query
        # xpath_query = f"{misc.iif(context, ".", "/METASCHEMA")}/{structure_type}"
        xpath_query = f"./{structure_type}"
        no_local = misc.iif(ignore_local, " and not(@scope='local')", "")
        xpath_query += f"[@{misc.iif(structure_type in ["field", "flag", "assembly"], "ref", "name")}='{name}'{no_local}]"
        if use_name is not None:
            xpath_query += f"[./use-name='{use_name}']"
        if DEBUG_OBJECT == name:
            logger.info(f"DEBUG: Looking for {structure_type}: {name} in {self.oscal_model} with xpath: {xpath_query}")

        result = self.xpath(xpath_query, context)
    
        if result is None:
            if structure_type in ["define-assembly", "define-field", "define-flag"]:
                if context is not None:
                    metaschema_node = self.recurse_metaschema(name, structure_type, parent=parent, ignore_local=False, already_searched=[], context=None)
                else:
                    # If nothing was found, look in the imported files
                    logger.debug(f"Did not find <{structure_type}: '{name}' ... > in {self.oscal_model}")
                    metaschema_node = self.look_in_imports(name, structure_type, parent=parent, ignore_local=ignore_local, already_searched=already_searched)
            else:
                # assembly, field, and flag should always be found in the passed context.
                pass
        else:
            # .............................................................................
            if isinstance(result, list):
                # Duplicate definitions are not allowed in metaschema, so this would only happen if the metaschema was invliad.
                logger.warning(f"Found multiple {structure_type} objects named '{name}'. Using the first one found. [{xpath_query} ({context})]")
                definition_obj = result[0]
            else:
                # A single element was found as expected
                definition_obj = result
            logger.debug(f"Found: <{structure_type} name='{name}' ... >")

            metaschema_node["name"]                = name # should always be present
            metaschema_node["structure-type"]      = structure_type.replace("define-", "")
            metaschema_node["use-name"]            = self.graceful_override(metaschema_node["use-name"], "./use-name/text()", definition_obj)
            if metaschema_node["use-name"] is None or metaschema_node["use-name"] == "":
                metaschema_node["use-name"] = metaschema_node["name"]
            if metaschema_node["path"] is None or metaschema_node["path"] == "":
                if structure_type in ["define-assembly", "assembly", "define-field", "field"]:
                   metaschema_node["path"] = f"{parent}/{metaschema_node["use-name"]}"
                elif structure_type in ["define-flag", "flag"]:
                    metaschema_node["path"] = f"{parent}/@{metaschema_node["use-name"]}"

            metaschema_node["formal-name"]         = self.graceful_override(metaschema_node["formal-name"],         "./formal-name/text()", definition_obj)
            # metaschema_node["json-key"]            = self.graceful_override(metaschema_node["json-key"],            "./json-key/text()", definition_obj)
            metaschema_node["json-value-key"]      = self.graceful_override(metaschema_node["json-value-key"],      "./json-value-key/text()", definition_obj)
            metaschema_node["json-value-key-flag"] = self.graceful_override(metaschema_node["json-value-key-flag"], "./json-value-key-flag/text()", definition_obj)

            metaschema_node["description"] = self.graceful_accumulate(metaschema_node["description"], "./description", definition_obj)
            metaschema_node["remarks"]     = self.graceful_accumulate(metaschema_node["remarks"]    , "./remarks", definition_obj)
            metaschema_node["example"]     = self.graceful_accumulate(metaschema_node["example"]    , "./example", definition_obj)


            # Handle metaschmea attributes, such as @datatype, @min-occurs, @max-occurs
            metaschema_node = self.handle_attributes(metaschema_node, definition_obj, structure_type, name, parent)
            if metaschema_node is None or metaschema_node == {}:
                logger.error(f"Lost data handling attributes for {structure_type} / {name}.")
                return {} 
            
            # Set default values where appropriate
            metaschema_node = self.set_default_values(metaschema_node, definition_obj, structure_type, name, parent)
            if metaschema_node is None or metaschema_node == {}:
                logger.error(f"Lost data setting defaults for {structure_type} / {name}.")
                return {} 
            
            # Handle group-as element, which is used to indicate how fields or assemblies should be grouped
            metaschema_node = self.handle_group_as(metaschema_node, definition_obj, structure_type, name, parent)
            if metaschema_node is None or metaschema_node == {}:
                logger.error(f"Lost data handling group-as for {structure_type} / {name}.")
                return {}

            # Handle props 
            metaschema_node = self.handle_props(metaschema_node, definition_obj, structure_type, name, parent)
            if metaschema_node is None or metaschema_node == {}:
                logger.error(f"Lost data handling props for {structure_type} / {name}.")
                return {} 

            # Identify which metaschema file this object is from
            if "source" in metaschema_node:
                metaschema_node["source"].append(self.oscal_model)
            else:
                metaschema_node["source"] = [self.oscal_model]  

            if not misc.has_repeated_ending(metaschema_node["path"], f"/{metaschema_node["use-name"]}", frequency=2):
                metaschema_node["flags"]    = self.handle_flags(metaschema_node, definition_obj, structure_type, name, parent)
                logger.debug(f"Back from handle flags in {self.oscal_model} for {structure_type} / {name} in {parent}")
                metaschema_node["children"] = self.handle_children(name, structure_type, metaschema_node, definition_obj)
                logger.debug(f"Back from handle model")
            else:
                # It is one of several known circular references that needs to be handled.
                logger.debug(f"Circular Reference protection: {name} is the same as the parent at {metaschema_node["path"]}")
                metaschema_node["structure-type"] = "recursive"
                metaschema_node["description"] = "<b>Recursive: See parent</b>"
                metaschema_node["children"] = []
                metaschema_node["flags"] = []

        # .............................................................................

        if metaschema_node is None or metaschema_node == {}:
            logger.debug(f"Did not find {structure_type} / {name} in {self.oscal_model} or any imports.")
        else:
            if DEBUG_OBJECT == name:
                logger.info(f"****: Found {structure_type} / {name} in {self.oscal_model} with path: {metaschema_node["path"]}")
                logger.info(f"****: metaschema_node: {self.str_node(metaschema_node)}")

        return metaschema_node

    # -------------------------------------------------------------------------
    def handle_group_as(self, metaschema_node, definition_obj, structure_type, name, parent):
        """
        Handle the group-as element for the metaschema tree.
        This function processes the group-as element and its attributes,
        setting them in the metaschema tree.
        """
        logger.debug(f"Handling group-as for {structure_type} {name}")

        temp_group_as = self.xpath(f"./group-as", definition_obj)
        if temp_group_as is not None:
            if structure_type in ["define-assembly", "assembly", "define-field", "field"]:
                logger.debug(f"Found group-as for {structure_type} {name}")
                if temp_group_as.attrib:
                    logger.debug(f"Has attributes.")
                    metaschema_node["group-as"] = temp_group_as.attrib.get("name", "")
                    if "in-xml" in temp_group_as.attrib:
                        logger.debug(f"Found in-xml attribute: {temp_group_as.attrib.get('in-xml')}")
                        if temp_group_as.attrib.get("in-xml") in ["GROUPED"]:
                            metaschema_node["wrapped-in-xml"] = temp_group_as.attrib.get("name", "")
                            metaschema_node["path"] = f"{parent}/{temp_group_as.attrib.get("name", "")}/{metaschema_node["use-name"]}"
                        elif temp_group_as.attrib.get("in-xml") in ["UNGROUPED"]:
                            pass
                        else:
                            logger.warning(f"Unexpected in-xml value: {temp_group_as.attrib.get('in-xml')}")
                        metaschema_node["group-as-in-xml"] = temp_group_as.attrib.get("in-xml")
                    if "in-json" in temp_group_as.attrib:
                        logger.debug(f"Found in-json attribute: {temp_group_as.attrib.get('in-json')}")
                        metaschema_node["group-as-in-json"] = temp_group_as.attrib.get("in-json")
            else:
                logger.warning(f"Group-as found where it is not expected: {structure_type} {name}")

        return metaschema_node

    # -------------------------------------------------------------------------
    def graceful_accumulate(self, current_value, xExpr, context=None):
        """
        Handle graceful accumulation for the metaschema tree where a field or assembly ref
        values need to be added to any existing defined-field or define-assembly values.
        """
        logger.debug(f"Handling graceful accumulation for {xExpr}")

        temp_value = self.get_markup_content(xExpr, context)
        if temp_value is not None and temp_value != "":
            if not isinstance(current_value, list):
                current_value = []
            current_value.insert(0, temp_value)

        return current_value

    # -------------------------------------------------------------------------
    def graceful_override(self, current_value, xExpr, context=None):
        """
        Handle graceful overrides for the metaschema tree where a field or assembly ref
        values need to replace any existing defined-field or define-assembly values.
        """
        ret_value = None
        logger.debug("Handling graceful overrides")
        temp_value = self.xpath_atomic(xExpr, context)
        if temp_value != "":
            ret_value = temp_value
        else:
            ret_value = current_value

        return ret_value

    # -------------------------------------------------------------------------
    def set_default_values(self, metaschema_node, definition_obj, structure_type, name, parent):
        """
        Set default values for the metaschema tree.
        This function sets default values for various attributes in the metaschema tree
        based on the structure type and other conditions.
        """
        logger.debug("Setting default values")
        # Set default values for metaschema tree
        if metaschema_node is not None:

            # If any of these have not been defined by this point, set them to default 
            # values per the metaschema specification.
            metaschema_node.setdefault("datatype", "string")
            if metaschema_node.get("datatype") is None:
                metaschema_node["datatype"] = "string"
            if metaschema_node.get("min-occurs") is None:
                metaschema_node["min-occurs"] = "0"
            if metaschema_node.get("max-occurs") is None:
                metaschema_node["max-occurs"] = "1"
            if parent == "": # special case for the root element, which is identified because it has no parent.
                metaschema_node["min-occurs"] = "1"
                metaschema_node["max-occurs"] = "1"

            if metaschema_node.get("is-collapsible") is None:
                metaschema_node["is-collapsible"] = False
            if metaschema_node.get("deprecated") is None:
                metaschema_node["deprecated"] = False
            if metaschema_node.get("default") is None:
                metaschema_node["default"] = None # Explicitly makes present and sets to None

            if structure_type in ["define-field", "field", "define-assembly", "assembly"]:
                if metaschema_node.get("wrapped-in-xml") is None:
                    metaschema_node["wrapped-in-xml"] = True

        return metaschema_node

    # -------------------------------------------------------------------------
    def look_in_imports(self, name, structure_type, parent="", ignore_local=False, already_searched=[]):
        """
        Look for a metaschema definition in the imported files.
        This function searches through the imported metaschema files to find
        a specific definition by name and structure type.
        """
        logger.debug(f"Looking for {structure_type} {name} in imports")
        metaschema_node = None

        # Cycle through each of the imported metaschema files
        for item in self.imports:
            import_file = item
            parser_object = self.imports[import_file]
            metaschema_node = parser_object.recurse_metaschema(name, structure_type, parent=parent, ignore_local=True, already_searched=already_searched, context=None)
            if metaschema_node is not None and metaschema_node != {}:
                break

        # Check if we got a meaningful result, not just an empty dict or None
        if metaschema_node is not None and metaschema_node.get("structure-type")!= "":
            logger.debug(f"FOUND in {import_file}: {structure_type}: {name}")
            if name == DEBUG_OBJECT:
                logger.info(f"DEBUG: FOUND in {import_file}: {structure_type}: {name}")
        # else:
        #     # Reset metaschema_node to None so we continue searching
        #     metaschema_node = None

        if metaschema_node is None and not ignore_local: # ignore_local is only false at the top level
            logger.debug(f"Did not find {structure_type}: {name} in {self.oscal_model} nor any imports. Parent: {parent}")

        return metaschema_node

    # -------------------------------------------------------------------------
    def handle_flags(self, metaschema_node, definition_obj, structure_type, name, parent):
        """Handle Flags defined or referenced in the Field or Assembly"""
        logger.debug(f"Handling flags for {structure_type} {name}")
        
        hold_flags = metaschema_node.get("flags", [])

        temp_flags = self.xpath(f"./(define-flag | flag)", definition_obj)
        if temp_flags is not None:
            logger.debug(f"Found {len(temp_flags)} flags in {structure_type} {name}")
            if not structure_type in ["define-assembly", "assembly", "define-field", "field"]:
                logger.warning(f"Flags are only allowed in define-assembly, assembly, define-field, field. Not in {structure_type} {name}")

            if not isinstance(temp_flags, list): # more than one
                temp_flags = [temp_flags]

            for flag in temp_flags:
                flag_structure_type = flag.tag.split('}')[-1]  # Remove namespace
                flag_name = ""
                if "ref" in flag.attrib:
                    flag_name = flag.attrib['ref']
                elif "name" in flag.attrib: 
                    flag_name = flag.attrib['name']
                else:
                    logger.error (f"Flag: {flag_structure_type} contains neither @name nor @ref")

                if flag_name:
                    # print(f"\rBuilding: {metaschema_node["path"]}/@{flag_name}", end="", flush=True)
                    meta_object = self.recurse_metaschema(flag_name, flag_structure_type, parent=metaschema_node["path"], already_searched=[], context=definition_obj)
                    if meta_object is not None and meta_object != {}:
                        hold_flags.append(meta_object)
        else:
            logger.debug(f"No flags found within {structure_type} {name}")
        
        return hold_flags

    # -------------------------------------------------------------------------
    def handle_attributes(self, metaschema_node, definition_obj, structure_type, name, parent):
        """
        Handle attributes for the metaschema tree.
        This function processes the attributes of the given XML element and
        updates the metaschema tree accordingly.
        """
        logger.debug("Handling attributes")

        if definition_obj.attrib:
            for attr_name, attr_value in definition_obj.attrib.items():
                logger.debug(f"{structure_type} ({name}) Attribute: {attr_name} = {attr_value}")
                match attr_name:
                    case "name" | "ref" | "scope":
                        pass # Already captured: name, ref. Ignoring: scope
                    case "as-type": # for fields and flags
                        metaschema_node["datatype"] = attr_value or metaschema_node["datatype"]
                    case "required": # For flags
                        if attr_value == "yes":
                            metaschema_node["min-occurs"] = "1"
                            metaschema_node["max-occurs"] = "1"
                        elif attr_value == "no":
                            metaschema_node["min-occurs"] = "0" 
                            metaschema_node["max-occurs"] = "1" 
                    case "min-occurs": # For fields and assemblies
                        metaschema_node["min-occurs"] = attr_value or metaschema_node["min-occurs"]
                    case "max-occurs": # For fields and assemblies
                        metaschema_node["max-occurs"] = attr_value or metaschema_node["max-occurs"]
                    case "collapsible": # For fields
                        if attr_value == "yes":
                            metaschema_node["is-collapsible"] = True
                        elif attr_value == "no": # default is "no"
                            metaschema_node["is-collapsible"] = False
                        logger.debug(f"Collapsible: {metaschema_node['is-collapsible']}")
                        unhandled = {"path": metaschema_node["path"], "structure": metaschema_node["structure-type"], attr_name: attr_value}
                        global_unhandled_report.append(unhandled)
                    case "deprecated":
                        if misc.compare_semver(attr_value, self.oscal_version) <= 0:
                            metaschema_node["deprecated"] = True
                        else:
                            metaschema_node["sunsetting"] = attr_value
                    case "default":
                        if structure_type in ["define-field", "define-flag"]:
                            metaschema_node["default"] = attr_value
                        else:
                            logger.warning(f"Unexpected attribute: <define-{structure_type} name='{name}' {attr_name}='{attr_value}'")
                    case "in-xml":
                        if structure_type in ["define-field", "field", "define-assembly", "assembly"]:
                            if attr_value in ["WRAPPED", "WITH_WRAPPER"]:
                                metaschema_node["wrapped-in-xml"] = True
                            else:
                                metaschema_node["wrapped-in-xml"] = False
                        else:
                            logger.warning(f"Unexpected attribute: <define-{structure_type} name='{name}' {attr_name}='{attr_value}'")
                    case _:
                        logger.warning(f"Unexpected attribute: <{structure_type} ({name}) {attr_name}='{attr_value}'")

        return metaschema_node

    # -------------------------------------------------------------------------
    def handle_props(self, metaschema_node, definition_obj, structure_type, name, parent):
        """
        Handle props for the metaschema tree.
        This function processes the props of the given metaschema construct and
        updates the current metaschema node accordingly.
        Expected props are have their own node keys. Any unexpected prop is added
        to the props array. 

        metaschema_node["props"] = [{"name" : "", "value": "", "namespace": ""}, ...]

        """
        logger.debug("Handling metaschema props")
        hold_props = metaschema_node.get("props", [])

        props = self.xpath('./prop', definition_obj)

        if props is not None:
            if not isinstance(props, list):
                props = [props]
            for prop in props:
                prop_name = prop.attrib.get("name", "")
                prop_value = prop.attrib.get("value", "")
                prop_namespace = prop.attrib.get("namespace", "")

                if prop_name in METASCHEMA_PROPS_HANDLED and prop_namespace == "": # TODO handle default namespace
                    metaschema_node[prop_name] = prop_value
                else:
                    prop_obj = {
                        "name": prop_name,
                        "value": prop_value,
                        "namespace": prop_namespace}
                    hold_props.append(prop_obj)

        else:
            logger.debug(f"No props found in {structure_type} {name}")

        metaschema_node["props"] = hold_props
        return metaschema_node
    
    # -------------------------------------------------------------------------
    def handle_children(self, name, structure_type, metaschema_node, context, handle_choice=0):
        """Handle model specification for defined assemblies"""
        global global_unhandled_report, global_counter
        hold_children = metaschema_node.get("children", [])
        choice_count = 0
        child_use_name = None

        if structure_type == "define-assembly":
            xExpr = f"./model"
        elif structure_type == "choice":
            logger.debug(f"Handling choice {handle_choice} for {metaschema_node['path']}")
            xExpr = f"(./model/choice)[{handle_choice}]"
            # logger.debug(f"{xExpr} for {structure_type} {name} in {metaschema_node["path"]}")
        else:
            xExpr = f""

        if xExpr != "":
            children = self.xpath(xExpr, context)
            if children is not None:
                for child in children:
                    child_structure_type = child.tag.split('}')[-1]  # Remove namespace
                    if child_structure_type in ["field", "assembly", "define-field", "define-assembly", "choice", "any"]:
                        if child_structure_type in ["define-field", "define-assembly"]:
                            child_name = child.attrib.get("name", "")
                        elif child_structure_type in ["field", "assembly"]:
                            child_name = child.attrib.get("ref", "")
                            child_use_name = self.graceful_override(child_use_name, "./use-name/text()", child)
                        elif child_structure_type in ["choice", "any"]:
                            logger.debug(f"FOUND {child_structure_type} in {metaschema_node["path"]}")
                            child_name = f"{child_structure_type.upper()}"

                        # print(f"\r[{global_counter}] {ORANGE}Building: {metaschema_node["path"]}/{child_name} [{child.attrib}]", end="", flush=True)
                        print(f"{ORANGE}[{global_counter}] Building: {metaschema_node["path"]}/{child_name} ") # , end="", flush=True)

                        if child_structure_type in ["define-field", "define-assembly", "field", "assembly"]:

                            meta_object = self.recurse_metaschema(child_name, child_structure_type, parent=metaschema_node["path"], ignore_local=False, context=children, already_searched=[], use_name=child_use_name)
                            if meta_object is not None and meta_object != {}:
                                hold_children.append(meta_object)
                            else:
                                logger.warning(f"Unexpected empty return at {metaschema_node["path"]} for child: {child_structure_type} {child_name}")


                        elif child_structure_type == "choice":
                            choice_count += 1
                            logger.debug(f"Handling choice {choice_count} for {metaschema_node["path"]}")
                            temp_object = {}
                            temp_object["name"] = f"CHOICE"
                            temp_object["structure-type"] = "choice"
                            temp_object["path"] = metaschema_node["path"] 
                            temp_object["source"] = metaschema_node["source"]
                            temp_object["children"] = self.handle_children(child_name, child_structure_type, temp_object, context=context, handle_choice=choice_count)

                            hold_children.append(temp_object)

                        elif child_structure_type == "any":
                            temp_object = {}
                            temp_object["name"] = f"ANY"
                            temp_object["structure-type"] = "any"
                            temp_object["path"] = metaschema_node["path"] + f"/*"
                            temp_object["source"] = metaschema_node["source"]
                            hold_children.append(temp_object)
                            global_unhandled_report.append({"path": metaschema_node["path"], "structure": metaschema_node["structure-type"], "child": child_structure_type})

                    else:
                        logger.error(f"Unexpected child structure type: {child_structure_type} in model for {structure_type} {name}")
            else:
                logger.debug(f"No children found in model for {structure_type} {name}")
        return hold_children

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == "__main__":
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        colorize=True
    )

    logger.add(
        "output.log",
        level="DEBUG",  # Log everything to file
        colorize=False,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True
    )

    try:
        exit_code = asyncio.run(parse_metaschema(oscal_version="v1.1.3"))
        if exit_code == 0:
            logger.info("Application exited successfully.")
        elif exit_code == 1:
            logger.warning("Application exited with warnings.")
        else:
            logger.error(f"Unexpected exit value of type {str(type(exit_code))}")
        sys.exit(exit_code)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
