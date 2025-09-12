from loguru import logger
from saxonche import PySaxonProcessor, PyXdmValue, PyXdmNode
import elementpath
from elementpath.xpath3 import XPath3Parser
from xml.etree import ElementTree
from xml.dom import minidom
from common import *
from oscal_support import *
import uuid

# As defined by NIST:
OSCAL_DEFAULT_NAMESPACE = "http://csrc.nist.gov/ns/oscal/1.0"

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# OSCAL CLASS
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCAL:
    """
    OSCAL Class

    Properties:
    - content: The string representing the content as originally passed to the class
    - valid_xml: A boolean indicating whether the content was found to be well-formed XML
    - xml_namespace: The identified default namespace
    - valid_oscal: A boolean indicating whether the content was found to OSCAL schema valid
    - Currently, valid just means a recognized OSCAL model name (root) and OSCAL version (/metadata/oscal-veraion)
    - oscal_format: The recognized OSCAL format ("xml", "json" or "yaml")
    - Currently, the value will only be XML as the class only accepts XML. 
    - Phase 3: Accept all three formats
    - oscal_version: The value in the /metadata/oscal-version field
    - oscal_model: The OSCAL model name exatly as it appears in OSCAL syntax
    ["catalog", "profile", "component-definition", "system-security-plan", "assessment-plan", "assessment-results", "plan-of-action-and-milestones"]
    - doc: The lxml representation of the content

    Methods:
    - OSCAL_validate: Validates the content against the appropriate NIST OSCAL schema
    - OSCAL_convert: Converts the content to a different format
    - xpath: Performs an xpath query on the content
    - serializer: Serializes the content for output
    - lookup: Checks for the existence of an element based on an xpath expression
    - append_child: Appends a child node to the content
    - content_modified: Sets the content as modified
    - __setup_saxon: Sets up the Saxon processor
    - __saxon_serializer: Serializes the content using the Saxon processor
    - __saxon_handle_ns: Handles namespaces using the Saxon processor
    - __saxon_xpath_global: Performs an xpath query on the content using the Saxon processor
    - __saxon_xpath_global_single: Performs an xpath query on the content using the Saxon processor
    - __saxon_xpath: Performs an xpath query on the content using the Saxon processor
    - __saxon_xpath_single: Performs an xpath query on the content using the Saxon processor
    """
    def __init__(self, content):
        self.uuid = uuid.uuid4() # CC-assigned UUID
        self.content = content   # Working XML version of the content retained in memory for processing
        self.oscal_version = ""
        self.oscal_model = ""
        self.imports = []        # A list of imported OSCAL files, by CC-assigned UUID
        self.xml_schema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL XML Schema
        self.json_schema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL JSON Schema
        self.metaschema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL Metaschema
        self.xml = "" # filecache UUID of the XML version of the content
        self.json = "" # filecache UUID of the JSON version of the content
        self.yaml = "" # filecache UUID of the YAML version of the content
        self.original = "" # filecache UUID of the original version of the content
        self.original_location = ""
        self.original_format = ""
        self.original_well_formed = None  # A boolean indicating whether the content is well-formed in its original format

        self.tree = None
        self.nsmap = {"": OSCAL_DEFAULT_NAMESPACE}
        self.__saxon = None
        self.unsaved_modified_content = False 
        self.json_synced = None # Boolean indicating whether the latest XML content has been converted to JSON
        self.yaml_synced = None # Boolean indicating whether the latest XML content has been converted to YAML

        # check for XML validity
        try:
            self.tree = ElementTree.fromstring(content.encode('utf_8'))
            self.valid_xml = True
        except ElementTree.XMLSyntaxError as e:
            logger.debug("CONTENT DOES NOT APPEAR TO BE VALID XML")
            for entry in e.error_log:
                    logger.error(f"Error: {entry.message} (Line: {entry.line}, Column: {entry.column})")


        if self.valid_xml:
            logger.debug("Content appears to be well-formed XML")
            logger.debug(self.tree.tag)
            root_element = self.xpath_atomic("/*/name()")
            logger.debug("ROOT ELEMENT: " + str(root_element))
            if root_element in ["catalog", "profile", "component-definition", "system-security-plan", "assessment-plan", "assessment-results", "plan-of-action-and-milestones"]:
                logger.debug("OSCAL ROOT ELEMENT DETECTED: " + root_element)
                self.oscal_version = self.xpath_atomic("//metadata/oscal-version/text()")
                logger.debug("OSCAL_VERSION: " + str(self.oscal_version))
                if len(self.oscal_version) >= 5: # TODO: Look up value in list of known-valid OSCAL versions
                    self.OSCAL_validate()
            else:
                logger.error("ROOT ELEMENT IS NOT AN OSCAL MODEL: " + root_element)

    # -------------------------------------------------------------------------
    def content_modified(self):
        self.unsaved_modified_content = True
        self.json_synced = False
        self.yaml_synced = False
    
    # -------------------------------------------------------------------------
    def OSCAL_validate(self):
        """
        Currently does nothing.
        Will soon validate OSCAL XML content using the appropriate NIST OLSCAL XML Schema file for the specified OSCAL model and version.
        Eventually will use metaschema definitions to validate.
        """
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
        self.__saxon = PySaxonProcessor(license=False)
        try: 
            self.xdm = self.__saxon.parse_xml(xml_text=content)
            # self.__saxon.declare_namespace("", "http://csrc.nist.gov/ns/oscal/1.0")
            self.valid = True
            self.oscal_format = "xml"
        except:
            logger.error("Content does not appear to be valid XML. Unable to rpoceed")

        if self.valid:
            self.xp = self.__saxon.new_xpath_processor() # Instantiates XPath processing
            self.handle_ns()
            self.xp.set_context(xdm_item=self.xdm) # Sets xpath processing context as the whole file
            temp_ret = self.xpath_global("/*/name()")
            if temp_ret is not None:
                self.root_node = temp_ret[0].get_atomic_value().string_value
                logger.debug("ROOT: " + self.root_node)
            self.oscal_version = self.xpath_global_single("/*/*:metadata/*:oscal-version/text()")
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



# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


if __name__ == '__main__':
    print("OSCAL Class Library. Not intended to be run as a stand-alone file.")

