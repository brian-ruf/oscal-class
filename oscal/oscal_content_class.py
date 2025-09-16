# The OSCAL Python Class
from loguru import logger

from saxonche import *
import jsonschema_rs
import xmlschema
import json
import yaml

from datetime import datetime
import os

from common import * 

NIST_OSCAL_NS = "http://csrc.nist.gov/ns/oscal/1.0"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"  
RECOGNIZED_FORMATS = ["xml", "json", "yaml"]
OSCAL_support_file_patterns = ["_metaschema_RESOLVED.xml", "_schema.xsd", "_schema.json", "_xml-to-json-converter.xsl", "_json-to-xml-converter.xsl", "metaschema.xml"]


OUT_ERROR = 4
OUT_WARNING = 2
OUT_MESSAGE = 1
OUT_DEBUG = 0

# -------------------------------------------------------
# OSCAL_Content - An object for managing OSCAL content 
# -------------------------------------------------------
class OSCAL_Content:
    """
    CLASS OSCAL_Content(file_path_and_name, file_content)

    PARAMETERS:
        - file_path_and_name : (string) Can me just the base file name or include 
                                the full path. Must include ".xml", ".json" or ".yaml" (case insensitive)
        - file_content       : The actual content in string or unicode/utf-8 format

        PROPERTIES:
            .identifier = identifier
            .file_path_and_name = file_path_and_name
            .file_name = os.path.basename(file_path_and_name)
            .original_content = normalize_content(file_content)
            .original_format = ""
            .oscal_model = ""
            .oscal_version = ""
            .log = []
            .xml    = "" # If the native content is XML, this gets populated in XML_Interrogation
            .xml_validation_report = []
            .xml_transform_report = []
            .xml_is_valid   = None
            .json   = "" # If the native content is JSON, this gets populated in JSON_Interrogation
            .json_validation_report = []
            .json_transform_report = []
            .json_is_valid  = None
            .yaml   = "" # If the native content is YAML, this gets populated in YAML_Interrogation
            .yaml_validation_report = []
            .yaml_transform_report = []
            .yaml_is_valid  = None    

        METHODS:
            .logging(message, title="", details="", output_type=OUT_DEBUG)
            .validate(target_format)
            .convert(convert_to, validate=False)
    """
    def __init__(self, file_path_and_name, file_content, identifier=""):
        status = False
        self.identifier = identifier
        self.file_path_and_name = file_path_and_name
        self.file_name = os.path.basename(file_path_and_name)
        self.original_content = misc.normalize_content(file_content)
        self.original_format = ""
        self.oscal_model = ""
        self.oscal_version = ""
        self.log = []
        self.__xdm  = "" # 
        self.xml    = "" # If the native content is XML, this gets populated in XML_Interrogation
        self.xml_validation_report = []
        self.xml_transform_report = []
        self.xml_is_valid   = None
        self.__dict = []
        self.json   = "" # If the native content is JSON, this gets populated in JSON_Interrogation
        self.json_validation_report = []
        self.json_transform_report = []
        self.json_is_valid  = None
        self.yaml   = "" # If the native content is YAML, this gets populated in YAML_Interrogation
        self.yaml_validation_report = []
        self.yaml_transform_report = []
        self.yaml_is_valid  = None

        self.logging("Object creted")
        if self.__format_verification():
            if not self.validate():
                logger.warning("Not valid OSCAL content.")
        else:
            logger.warning("Not a valid XML, JSON, or YAML format.")

    # -------------------------------------------------------
    def __str__(self):
        json_out = {}
        json_out["file-name"] = self.file_name
        json_out["original-format"] = self.original_format
        json_out["oscal-model"] = self.oscal_model
        json_out["oscal-version"] = self.oscal_version
        match self.original_format:
            case "xml":
                json_out["is-valid"] = self.xml_is_valid
                json_out["validation-report"] = self.xml_validation_report
                if self.json != "": json_out["json_transform-report"] = self.json_transform_report
                if self.yaml != "": json_out["yaml_transform-report"] = self.yaml_transform_report
            case "json":
                json_out["is-valid"] = self.json_is_valid
                json_out["validation-report"] = self.json_validation_report
                if self.xml != "": json_out["xml_transform-report"] = self.xml_transform_report
                if self.yaml != "": json_out["yaml_transform-report"] = self.yaml_transform_report
            case "yaml":
                json_out["is-valid"] = self.yaml_is_valid
                json_out["validation-report"] = self.yaml_validation_report
                if self.json != "": json_out["json_transform-report"] = self.json_transform_report
                if self.xml != "": json_out["xml_transform-report"] = self.xml_transform_report

        if self.xml_is_valid: json_out["xml-content"] = "XML format available. Use `.xml` attribute."
        if self.json_is_valid: json_out["json-content"] = "JSON format available. Use `.json` attribute."
        if self.yaml_is_valid: json_out["yaml-content"] = "YAMl format vailable. Use `.yaml` attribute."

        return json_out

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #  --- Helper Methods ---
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def logging(self, message, title="", details="", output_type=OUT_DEBUG):
        temp_obj = {}
        temp_obj["timestamp"] = str(datetime.now().strftime(TIMESTAMP_FORMAT))
        temp_obj["title"] = title
        temp_obj["message"] = message
        temp_obj["details"] = details
        self.log.append(temp_obj)

        if output_type==OUT_DEBUG: logger.debug(message, details)
        if output_type==OUT_ERROR  : logger.error(message, details)
        if output_type==OUT_WARNING: logger.warning(message) # , title, detail)
        if output_type==OUT_MESSAGE: logger.info(message) # , title, detail)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #  --- Core Methods ---
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def __format_verification(self): # Private method
        is_recognized_format = False


        if not is_recognized_format:
            # "<" = OSCAL XML, "{" = OSCAL JSON, "-"
            first_non_ws = misc.get_first_non_whitespace_char(self.original_content)
            match first_non_ws:
                case "<":  #  OSCAL XML
                    self.original_format = "xml"
                    is_recognized_format = True
                case "{":  #  OSCAL JSON
                    self.original_format = "json"
                    is_recognized_format = True
                case _: 
                    if first_non_ws in "-abcdefghijklmnopqrstuvwxyz": # OSCAL YAML
                        self.original_format = "yaml"
                        is_recognized_format = True
                    else:
                        msg_out = "Content is not OSCAL XML, OSCAL JSON, or OSCAL YAML."
                        self.logging(msg_out)
                        logger.error(msg_out)

        if is_recognized_format:
            match self.original_format:
                case "xml":
                    self.xml = self.original_content
                case "json":
                    self.json = self.original_content
                case "yaml":
                    self.yaml = self.original_content
                case _:
                    is_recognized_format = False
                    logger.error("Unable to proceed with validation. Invalid format requested: " + is_recognized_format)
    
        if is_recognized_format:
            msg_out = "Content appears to be " + self.original_format.upper()
            self.logging(msg_out)
        
        return is_recognized_format

    def is_valid(self, target_format=""):
        ret_value = False
        if target_format=="":
            target_format = self.original_format

        match target_format:
            case "xml":
                ret_value = self.xml_is_valid
            case "json":
                ret_value = self.json_is_valid
            case "yaml":
                ret_value = self.yaml_is_valid
            case _:
                logger.error("Unable to confirm content validity. Invalid format: " + target_format)

        return ret_value



    def conversion_report(self, target_format=""):
        ret_value = []

        match target_format:
            case "xml":
                ret_value = self.xml_transform_report
            case "json":
                ret_value = self.json_transform_report
            case "yaml":
                ret_value = self.yaml_transform_report
            case _:
                logger.error("Unable to retrieve conversion report for " + target_format.upper() + " format.")

        return ret_value

    def validation_report(self, target_format=""):
        ret_value = []
        if target_format=="":
            target_format = self.original_format

        match target_format:
            case "xml":
                ret_value = self.xml_validation_report
            case "json":
                ret_value = self.json_validation_report
            case "yaml":
                ret_value = self.yaml_validation_report
            case _:
                logger.error("Unable to retrieve validation report for " + target_format.upper() + " format.")

        return ret_value

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def validate(self, target_format=""):
        """
        Validates the OSCAL content
        1. Looks at file name to determine the declared format type (.xml, .json, or .yaml)
        2. If a supported type, Check within the content for /metadata/oscal-version as appropriate for type
        3. If a recognized OSCAL version numnber is found, use the appropriate OSCAL support file to validate
        """

        start_time = datetime.now()

        self.is_valid = False

        if target_format=="":
            target_format = self.original_format

        match target_format:
            case "xml":
                if self.xml != "":
                    is_valid = self.__XML_validation()
                    self.xml_is_valid = is_valid
                else:
                    self.logging("Unable to validate. " + target_format.upper() + " format does not exist.", "" , "May need to convert to this format before validating.")
                    self.xml_is_valid = False
            case "json":
                if self.json != "":
                    is_valid = self.__JSON_validation()
                    self.json_is_valid = is_valid
                else:
                    self.logging("Unable to validate. " + target_format.upper() + " format does not exist.", "" , "May need to convert to this format before validating.")
                    self.json_is_valid = False
            case "yaml":
                if self.yaml != "":
                    is_valid = self.__YAML_validation()
                    self.yaml_is_valid = is_valid
                else:
                    self.logging("Unable to validate. " + target_format.upper() + " format does not exist.", "" , "May need to convert to this format before validating.")
                    self.json_is_valid = False
            case _:
                logger.error("Unable to proceed with validation. Invalid format requested" + target_format)

        run_time = datetime.now() - start_time
        out_str = "- - - - - - " + target_format.upper() + " is " + misc.iif(is_valid, "valid", "INVALID") +  " (" + str(run_time.total_seconds()) + "s)"
        self.logging(out_str)
        
        return is_valid 

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def __XML_validation(self):
        """
        Validates the OSCAL content in XML format.
        """
        status = False
        ret = None
        # file_content = self.original_content
        # processing_errors = []
        # Setup XML file to be managed with Saxon
        with PySaxonProcessor(license=False) as proc:
            self.logging("Using " + proc.version)
            xp = proc.new_xpath_processor()  # Instantiates XPath processing

            try: 
                self.__xdm = proc.parse_xml(xml_text=self.original_content)
                xp.set_context(xdm_item=self.__xdm)
                ret = xp.evaluate('/*/name()') 
                self.xml = self.content
            except:
                pass # ret is still None. Will be handled below.

            if not (ret is None and xp.exception_occurred):
                if isinstance(ret, PyXdmValue):
                    self.oscal_model = ret[0].get_atomic_value().string_value
                    self.logging("Discovered OSCAL model: " + self.oscal_model)

                    ret = xp.evaluate_single('/*/*:metadata/*:oscal-version/text()')
                    if  isinstance(ret,PyXdmNode):
                        self.oscal_version = ret.string_value
                        self.logging("Declared OSCAL Version: " + self.oscal_version )
                        support_obj = get_support_file(self.oscal_version, self.oscal_model, "xml-validation")
                        if support_obj.acquired:
                            self.logging("SUPPORT FILE: " + support_obj.file_name)
                            status = self.__XML_schema_validation(support_obj.content)
                        else:
                            msg = "Could not fetch appropriate support file."
                            self.xml_validation_report.append("Could not fetch appropriate support file.")
                    else:
                        msg = "Invalid OSCAL content. The oscal-version was not found."
                        self.xml_validation_report.append("Invalid OSCAL content. The oscal-version was not found.")
                else:
                    msg = "OSCAL model NOT deteced!"
                    self.xml_validation_report.append(msg)
            else:
                msg = "XPATH Processing Error: " + str(xpath_processor.error_message)
                self.xml_validation_report.append(msg)

        return status

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # Uses the xmlschema library
    # Accepts XML content and an XSD schema definition
    def __XML_schema_validation(self, xsd_content):
        self.xml_attempted = True
        self.xml_is_valid = False
        try:
            schema_def = xmlschema.XMLSchema(xsd_content)
            schema_def.validate(self.original_content)
            self.xml_is_valid = True
            msg_str = "XML Content is OSCAL Schema Valid!"
            logger.debug(msg_str)
            self.xml_validation_report.append(report_message(idx=0, message=msg_str))
        except xmlschema.validators.exceptions.XMLSchemaValidationError: 
            logger.warning("OSCAL XML schema validation errors.")
            try:
                validation_error_iterator = schema_def.iter_errors(self.original_content)
                for idx, validation_error in enumerate(validation_error_iterator, start=1):
                    self.xml_validation_report.append(report_message(idx, message="", path=validation_error.path, rule=validation_error.message, reason=validation_error.reason))
                    logger.debug( f'[{idx}] path: {validation_error.path} | reason: {validation_error.reason} | message: {validation_error.message}')
                # ret_value["validation-errors"] = error_list
            except (Exception, BaseException) as error:
                msg_str = "Unable to parse XML validation errors."
                logger.error(msg_str, "(" + type(error).__name__ + ") " + str(error))
                self.xml_validation_report.append(report_message(idx=0, message=msg_str))
            except:
                msg_str = "Unrecognized error while parsing XML schema validation errors."
                logger.error(msg_str)
                self.xml_validation_report.append(report_message(idx=0, message=msg_str))
        except:
            msg_str = "Unrecognized error performing OSCAL XML schema validation."
            logger.error(msg_str)
            self.xml_validation_report.append(report_message(idx=0, message=msg_str))

        return self.xml_is_valid

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # JSON VALIDATION
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # Accepts JSON content and a JSON schema definition
    def __JSON_schema_validation(self, json_schema):
        is_valid = False
        if self.original_format == "json": self.json_attempted = True
        if self.original_format == "yaml": self.yaml_attempted = True
        format_lbl = self.original_format.upper()

        # Is the schema defintion based on JSON Validation Standard draft-07 (FedRAMP's current as of Jan 2024)
        # jsonschema-rs only supports draft-03, draft-04, and draft-07. 
        # It may process later drafts depending on what features are used in the schema definition.
        # A different library may be required for more recent schemas. 
        if "$schema" in json_schema:
            if not json_schema["$schema"].find("draft-07"):
                logger.warning("Unsupported schema version. Attempting to continue. (" + json_schema["$schema"] + ")")
        try:
            # Load the schema into the schema processor
            validator = jsonschema_rs.JSONSchema(json_schema)
            try:
                # evaluate the content with the schema
                ret_temp = validator.validate(self.__dict)  
                if (ret_temp == None):
                    is_valid = True
                    if self.original_format == "json": 
                        self.json_is_valid = True
                        msg_str = "JSON Content is OSCAL Schema Valid!"
                        logger.debug(msg_str)
                        if self.original_format == "json": 
                            self.json_validation_report.append(report_message(idx=0, message=msg_str))
                        if self.original_format == "yaml": 
                            self.yaml_validation_report.append(report_message(idx=0, message=msg_str))
                    if self.original_format == "yaml": 
                        self.yaml_is_valid = True
                        msg_str = "YAML Content is OSCAL Schema Valid!"
                        logger.debug(msg_str)
                        if self.original_format == "json": 
                            self.json_validation_report.append(report_message(idx=0, message=msg_str))
                        if self.original_format == "yaml": 
                            self.yaml_validation_report.append(report_message(idx=0, message=msg_str))

            except (Exception, BaseException) as error:
                if type(error).__name__ == "ValidationError":
                    logger.warning(format_lbl + " validation errors found.")
                    validation_error_list = validator.iter_errors(self.__dict)
                    cntr = 1
                    for item in validation_error_list:
                        logger.debug(item.message)
                        # entry_obj = {}
                        # entry_obj["id"] = cntr
                        path_str = ""
                        for path_item in item.instance_path:
                            if isinstance(path_item, str):
                                path_str = path_str + "/" + path_item 
                            elif isinstance(path_item, int):
                                path_str = path_str + "[" + str(path_item) + "]" 
                        entry_item = path_str

                        path_str = ""                        
                        for path_item in item.schema_path:
                            if isinstance(path_item, str):
                                path_str = path_str + "/" + path_item 
                            elif isinstance(path_item, int):
                                path_str = path_str + "[" + str(path_item) + "]" 
                        if self.original_format == "json": 
                            self.json_validation_report.append(report_message(idx=0, message="", path=entry_item, rule=path_str, reason=item.message))
                        if self.original_format == "yaml": 
                            self.yaml_validation_report.append(report_message(idx=0, message="", path=entry_item, rule=path_str, reason=item.message))

                        cntr += 1
                else:
                    msg_str = format_lbl + " validation errors found, but unable to parse."
                    logger.error(msg_str, "(" + type(error).__name__ + ") " + str(error))
                    self.json_validation_report.append(report_message(idx=0, message=msg_str))
                    if self.original_format == "json": 
                        self.json_validation_report.append(report_message(idx=0, message=msg_str))
                    if self.original_format == "yaml": 
                        self.yaml_validation_report.append(report_message(idx=0, message=msg_str))


            except:
                msg_str = "Unrecognized error processing schema for " + format_lbl + " validation."
                logger.error(msg_str)
                if self.original_format == "json": 
                    self.json_validation_report.append(report_message(idx=0, message=msg_str))
                if self.original_format == "yaml": 
                    self.yaml_validation_report.append(report_message(idx=0, message=msg_str))

        except (Exception, BaseException) as error:
            msg_str = "Unable to parse validation errors."
            logger.error(msg_str, "(" + type(error).__name__ + ") " + str(error))
            if self.original_format == "json": 
                self.json_validation_report.append(report_message(idx=0, message=msg_str))
            if self.original_format == "yaml": 
                self.yaml_validation_report.append(report_message(idx=0, message=msg_str))

        except:
            msg_str = "Unrecognized error parsing schema file " + support_file_name + " for " + format_lbl + " validation."
            logger.error(msg_str)
            if self.original_format == "json": 
                self.json_validation_report.append(report_message(idx=0, message=msg_str))
            if self.original_format == "yaml": 
                self.yaml_validation_report.append(report_message(idx=0, message=msg_str))            


        return is_valid

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~===
    def __JSON_validation(self):
        ok_to_continue = False
        status = False

        # Checking if well-fored JSON and setting up for additional validation
        try:
            self.json = self.original_content # json.loads(self.original_content)
            self.__dict = json.loads(self.original_content)
            msg_str = "Appears to be well-formed JSON."
            logger.debug(msg_str)
            self.json_validation_report.append(report_message(idx=0, message=msg_str))
            ok_to_continue = True
        except ValueError:
            msg_str = "Content is not well formed JSON. Unable to proceed."
            logger.debug(msg_str)
            self.json_validation_report.append(report_message(idx=0, message=msg_str))

        # Checking for OSCAL Model and Version
        if ok_to_continue:
            ok_to_continue = False
            self.oscal_model = list(self.__dict.keys())[0]
            if self.oscal_model != "":
                msg_str = "OSCAL Model: " + self.oscal_model
                logger.debug(msg_str)
                self.json_validation_report.append(report_message(idx=0, message=msg_str))
                if "metadata" in self.__dict[self.oscal_model]:
                    if "oscal-version" in self.__dict[self.oscal_model]["metadata"]:
                        self.oscal_version = self.__dict[self.oscal_model]["metadata"]["oscal-version"]
                        ok_to_continue = True
                    else:
                        msg_str = "Did not find oscal-version. Unable to continue."
                        logger.debug(msg_str)
                        self.json_validation_report.append(report_message(idx=0, message=msg_str))
                else:
                    msg_str = "Unable to find OSCAL metadata. Unable to continue."
                    logger.error(msg_str)
                    self.json_validation_report.append(report_message(idx=0, message=msg_str))
                logger.debug("OSCAL Version: " + self.oscal_version)
            else:
                msg_str = "No JSON root element. OSCAL requires a root element with the OSCAL model name. Unable to continue."
                logger.error(msg_str)
                self.json_validation_report.append(report_message(idx=0, message=msg_str))              

        # Getting the correct OSCAL JSON schema validation file, processing it against the content   
        if ok_to_continue:
            support_obj = get_support_file(self.oscal_version, self.oscal_model, "json-validation")
            # status, support_file_name, support_file = get_support_file(self.oscal_version, self.oscal_model, "json-validation")
            if support_obj.acquired:
                status = self.__JSON_schema_validation(json.loads(support_obj.content))

        return status


    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # YAML VALIDATION
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def __YAML_validation(self):
        ok_to_continue = False
        status = False

        # Checking if well-formed YAML and setting up for additional validation
        try:
            self.yaml = self.original_content
            self.__dict = yaml.safe_load(self.original_content)
            msg_str = "Appears to be well-formed YAML."
            logger.debug(msg_str)
            self.yaml_validation_report.append(report_message(idx=0, message=msg_str))
            ok_to_continue = True
        except ValueError:
            msg_str = "Content is not well formed YAML. Unable to proceed."
            logger.debug(msg_str)
            self.yaml_validation_report.append(report_message(idx=0, message=msg_str))

        # Checking for OSCAL Model and Version
        if ok_to_continue:
            ok_to_continue = False
            self.oscal_model = list(self.__dict.keys())[0]
            if self.oscal_model != "":
                msg_str = "OSCAL Model: " + self.oscal_model
                logger.debug(msg_str)
                self.yaml_validation_report.append(report_message(idx=0, message=msg_str))
                if "metadata" in self.__dict[self.oscal_model]:
                    if "oscal-version" in self.__dict[self.oscal_model]["metadata"]:
                        self.oscal_version = self.__dict[self.oscal_model]["metadata"]["oscal-version"]
                        ok_to_continue = True
                    else:
                        msg_str = "Did not find oscal-version. Unable to continue."
                        logger.debug(msg_str)
                        self.yaml_validation_report.append(report_message(idx=0, message=msg_str))
                else:
                    msg_str = "Unable to get root object name or no root object used. Unable to continue."
                    logger.error(msg_str)
                    self.yaml_validation_report.append(report_message(idx=0, message=msg_str))
                logger.debug("OSCAL Version: " + self.oscal_version)
            else:
                msg_str = "No YAML root element. OSCAL requires a root element with the OSCAL model name. Unable to continue."
                logger.error(msg_str)
                self.yaml_validation_report.append(report_message(idx=0, message=msg_str)) 

        # Getting the correct OSCAL YAML schema validation file (which is the JSON schema), processing it against the content   
        if ok_to_continue:
            support_obj = get_support_file(self.oscal_version, self.oscal_model, "json-validation")
            if support_obj.acquired:
                status = self.__JSON_schema_validation(json.loads(support_obj.content))

        return status

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # OSCAL FORMAT CONVERSION METHODS
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # If the OSCAL content exists in YAML format, and that format is valid
    #      convert to JSON and return True
    # If the OSCAL content does not exist in YAML format, or the format is invalid,
    #      return False
    def __oscal_yaml2json(self, validate=False):
        self.logging("Converting OSCAL YAML to OSCAL JSON")
        status = False
        if self.yaml != "": #  and self.yaml_is_valid:
            self.json = yaml2json(self.yaml)
            status = True
            msg_str = "Converted YAML to JSON."
            self.json_transform_report.append(msg_str)
            logger.debug(msg_str)
            if validate: self.validate("json")
        else:
            msg_str = "No valid YAML present. Unable to convert YAML to JSON."
            self.yaml_transform_report.append(msg_str)
            logger.debug(msg_str)
        
        return status

    # If the OSCAL content exists in JSON format, and that format is valid
    #      convert to YAML and return True
    # If the OSCAL content does not exist in JSON format, or the format is invalid,
    #      return False
    def __oscal_json2yaml(self, validate=False):
        self.logging("Converting OSCAL JSON to OSCAL YAML")
        status = False
        if self.json != "" : # and self.json_is_valid:
            self.yaml = json2yaml(self.json)
            status = True
            msg_str = "Converted JSON to YAML."
            self.yaml_transform_report.append(msg_str)
            logger.debug(msg_str)
            if validate: self.validate("yaml")
        else:
            msg_str = "No valid JAON present. Unable to convert JSON to YAML."
            self.yaml_transform_report.append(msg_str)
            logger.debug(msg_str)
        return status

    # If the OSCAL content exists in XML format, and that format is valid
    #      convert to JSON and return True
    # If the OSCAL content does not exist in XML format, or the format is invalid,
    #      return False
    def __oscal_xml2json(self, validate=False):
        self.logging("Converting OSCAL XML to OSCAL JSON")
        if self.xml != "" and self.xml_is_valid:
            support_obj = get_support_file(self.oscal_version, self.oscal_model, "xml-to-json")
            self.json = xslt_transform(self.xml, support_obj.content, "xml")
            if validate: self.validate("json")
        else:
            msg_str = "No valid XML present. Unable to convert XML to JSON."
            self.json_transform_report.append(msg_str)
            logger.debug(msg_str)

    # If the OSCAL content exists in JSON format, and that format is valid
    #      convert to XML and return True
    # If the OSCAL content does not exist in JSON format, or the format is invalid,
    #      return False
    def __oscal_json2xml(self, validate=False):
        self.logging("Converting OSCAL JSON to OSCAL XML")
        if self.json != "" and self.is_valid():
            support_obj = get_support_file(self.oscal_version, self.oscal_model, "json-to-xml")
            self.xml = xslt_transform(self.json, support_obj.content, "json")
            if validate: self.validate("xml")
        else:
            msg_str = "No valid JSON present. Unable to convert JSON to XML."
            self.xml_transform_report.append(msg_str)
            logger.debug(msg_str)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # OSCAL FORMAT CONVERSION MANAGEMENT
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 
    def convert(self, convert_to, validate=False):
        """
        This OSCAL_Content method converts OSCAL content to the specified format
        from any existing format.
        The resulting format of this method is stored within the object.
        This method can only function if the OSCAL_Content object already 
        contains valid OSCAL content in another format. 

        METHOD:
            OSCAL_Content.convert(convert_to, validate=False)

        PARAMETERS:
            - convert_to: (string) Indicates the desired format for the OSCAL content. 
                                   Value must be "xml", "json" or "yaml" (case sensitive)
            - validate  : (boolean) If True, the syntax of the resulting OCAL content 
                                    will be checked by the appropriate schmea. 
                                    Default is False.
        
        RETURNS: Boolean
            True if successful. False otherwise.
            If validate is False:
                .convert will return True if there were no conversion errors.
            If validate is True:
                .convert will return True if there were no conversion errors,
                AND no validation errors.
                                    

        NOTES:

        Conversion may take several seconds for large files.

        NIST only offers XML -> JSON and JSON -> XML converters. Conversions
        between XML and YAML must go "through" the JSON converter as an extra step.
        The result is the following conversion path:
        XML -> JSON -> YAML -> JSON -> XML

        When converting between XML and YAML in either direction, the resulting JSON 
        content will also be stored when it is created.

        This method looks at all formats already stored in the object and performs 
        shortest-path conversion automatically. 

        """
        
        status = False

        match convert_to:
            case "xml":
                # If target format is XML, check for JSON. 
                # Otherwise, convert YAML to JSON first.
                if self.xml == "":
                    if (self.json == "") and self.yaml != "": 
                        self.__oscal_yaml2json()
                    if self.json != "":
                        self.__oscal_json2xml(validate)
                        status = True
                    else:
                        self.logging("Neither valid JSON nor valid YAML available. Unable to convert to XML", "", "", OUT_ERROR)
                else:
                    self.logging("XML already exists. Skipping request.", "", "", OUT_WARNING)
            case "json":
                # If target format is JSON, check for YAML. Otherwise, convert XML to JSON first.
                if self.json == "":
                    if self.yaml != "": 
                        self.__oscal_yaml2json(validate)
                        status = True
                    elif self.xml != "":
                        self.__oscal_xml2json(validate)
                        status = True
                    else:
                        self.logging("Neither valid XML nor valid YAML available. Unable to convert to JSON", "", "", OUT_ERROR)
                else:
                    self.logging("JSON already exists. Skipping request.", "", "", OUT_WARNING)
            case "yaml":
                # If target format is YAML, check for JSON. Otherwise, convert XML to JSON first.
                if self.yaml == "":
                    if (self.json == "") and self.xml != "": 
                        self.__oscal_xml2json()
                    if self.json != "":
                        self.__oscal_json2yaml(validate)
                        status = True
                    else:
                        self.logging("Neither valid JSON nor valid XML available. Unable to convert to YAML", "", "", OUT_ERROR)
                else:
                    self.logging("YAML already exists. Skipping request.", "", "", OUT_WARNING)
            case _:
                self.logging("Unknown conversion directive: " + convert_to, "", "", OUT_ERROR)

        return status

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~===
# CALL THIS FUNCTION FROM OUTSIDE THIS MODULE
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~===
def oscal_services(file_path_and_name, file_content, directives, validate_on_convert=False):
    """oscal_services(file_path_and_name, file_content, directives, validate_on_convert=False)

    Performs support functions on an OSCAL file including validation, format conversion, and profile resolution.
    NOTE: Profile resolution is not yet implemented.

    Parameters:
    - file_path_and_name : (string) Can me just the base file name or include 
                            the full path. Must include ".xml", ".json" or ".yaml" (case insensitive)
    - file_content       : The actual content in string or unicode/utf-8 format
    - directives         : (Array of strings) contains one or more tasks to 
                            perform on the OSCAL content.
    - validate_on_convert: (Optional boolean) If True, re-validate the content
                            for any new format created. 

    RETURNS: 
    - OSCAL_Content object

    The `directives` array is processed in the sequence received.
    VALID values in the `directives` array are:
    - "validate": verify the original content is valid OSCAL syntax.
    - "xml"     : convert the content to XML
    - "json"    : convert the content to JSON
    - "yaml"    : convert the content to YAML
    - "all"     : convert the content into all formats
    - "resolve" : processes a profile and returns the resulting catalog (AKA "Profile Resolution"). Only valid for OSCAL Profile content.
    """
    status = False

    logger.debug("- - - - - - - - - [SUPPORT REQUEST START] - - - - - - - - - -")
    this_file = OSCAL_Content(file_path_and_name, file_content)

    for directive in directives:
        match directive.lower():
            case "validate":
                status = this_file.validate()
            case "json" | "xml" | "yaml" | "all":
                status = this_file.convert(directive, validate_on_convert)
            case "resolve":
                logger.warning("Resolve is not yet implemented")
            case _:
                logger.warning("Unrecognized directive: " + directive)
                # this_file.messages

    logger.debug("- - - - - - - - - [SUPPORT REQUEST COMPLETE] - - - - - - - - - -")
    return this_file

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def report_message(idx=0, message="", path="", rule="", reason=""):
    entry_obj = {}
    entry_obj["id"] = idx
    entry_obj["path"] = path
    entry_obj["rule"] = rule
    entry_obj["reason"] = reason
    entry_obj["message"] = message
    return entry_obj

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~===
# Perform an XSLT Transform on content using Saxon
# This is exposed as a function so it may be called directly
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~===
def xslt_transform(in_file, xslt_file, start_format):
    status = False
    ok_to_continue = False
    return_content = ""
    
    start_time = datetime.now()
    logger.debug("* * * * * * Starting transform")

    xslt_file = normalize_content(xslt_file)
    proc = PySaxonProcessor(license=False)
    logger.debug(proc.version)

    xsltproc = proc.new_xslt30_processor()

    try:
        executable = xsltproc.compile_stylesheet(stylesheet_text=xslt_file) 
        ok_to_continue = True
    except:
        logger.error("Unable to process stylesheet")
        ok_to_continue = False

    if ok_to_continue:
        try:
            if start_format == "xml":
                document = proc.parse_xml(xml_text=in_file) # .decode("utf-8"))
            elif start_format == "json":
                json_xdm_string = proc.make_string_value(in_file)
                executable.set_parameter('json', json_xdm_string)
        except:
            logger.error("Unable to prepare content for transformation")
            ok_to_continue = False

    if ok_to_continue:
        try:
            if start_format == "xml":
                return_content = executable.transform_to_string(xdm_node=document)
            elif start_format == "json":
                return_content = executable.call_template_returning_string('from-json')
        except (Exception, BaseException) as error:
            logger.error("Unable to convert file.", "(" + type(error).__name__ + ") " + str(error))
        except:
            logger.error("Unknown error while converting file.")

    run_time = datetime.now() - start_time
    logger.debug(" * * * * * Finished transform (" + str(run_time.total_seconds()) + "s)")

    return normalize_content(return_content)


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~===
def yaml2json(yaml_content):
    return json.dumps(yaml.safe_load(yaml_content), sort_keys=False, indent=3)

def json2yaml(json_content):
    logger.debug(str(type(json_content)))
    return yaml.dump(json.loads(json_content), sort_keys=False, indent=3)


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~===
#  --- MAIN: Only runs if the module is executed stand-alone. ---
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~===
if __name__ == '__main__':
    # Execute when the module is not initialized from an import statement.
    logger.info("--- START ---")

    logger.info("This contains functions that process OSCAL syntax validation and format conversions.")
    logger.info("Import this file until your content and use it by calling:")
    logger.info(oscal_services.__doc__)
    logger.info("")
    logger.info("It will return the following object:")
    logger.info(OSCAL_Content.__doc__)

    data_loc = "../../../oscal-support/src/test/data/usnistgov_oscal-content/v1.2.1/"
    test_files = ["examples_ssp_xml_ssp-example.xml", "examples_ssp_xml_ssp-example[with-error].xml"]
    for test_file_name in test_files:

        status, test_file = LFS_get_file(data_loc + test_file_name)
        if status:
            oscal_obj = oscal_services(test_file_name, test_file, ["validate"])
            print("")
            print("=== DONE ===")
            print(iif(oscal_obj.is_valid(), "VALID", "not valid"))
            print("LEN XML : " + str(len(oscal_obj.xml)))
            print("LEN JSON: " + str(len(oscal_obj.json)))
            print("LEN YAML: " + str(len(oscal_obj.yaml)))

    logger.info("--- END ---", linefeed=True)
