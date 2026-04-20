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
import elementpath
from typing import Optional, Any
from functools import wraps
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlparse
from xml.etree import ElementTree

from ruf_common.logging import LoggableMixin
from ruf_common.data import detect_data_format, safe_load, safe_load_xml
from ruf_common.lfs import getfile, chkdir, putfile, normalize_content, save_json
from .oscal_support_class import OSCAL_support, OSCAL_DEFAULT_XML_NAMESPACE, OSCAL_FORMATS, SUPPORT_DATABASE_DEFAULT_FILE, SUPPORT_DATABASE_DEFAULT_TYPE
from .oscal_markdown import oscal_markdown_to_html
from .oscal_datatypes import oscal_date_time_with_timezone
from .oscal_converters import oscal_xml_to_json, oscal_json_to_xml

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Constants
INDENT = 2 # Number of spaces to use for indentation in pretty-printed output
# URI schemes we know how to fetch today
_SUPPORTED_URI_SCHEMES = {"http", "https", "file"}
# URI schemes we recognise but cannot fetch yet
_KNOWN_URI_SCHEMES = {"ftp", "ftps", "sftp", "s3", "gs", "az"}
# Valid OSCAL file extensions
_VALID_EXTENSIONS = {".xml", ".json", ".yaml", ".yml"}

"""
- Handle hrefs that are URI fragments referencing back-matter/resources within the same file
    - Eventually will need to handle href/URI fragments that reference back-matter/resources in an imported file via the import list/tree
- Handle hrefs that point to local files, remote URLs, and file:// URIs
- Classify the source based on its href and determine how to load it
- Remote files have a default TTL of 24 hours (configurable). file:// URIs have no TTL.
- For remote URLs, implement caching with expiration based on TTL
- Build an import tree that captures the structure of imports and their resolution status
- Provide methods to retry failed imports with new hrefs
- Implement properties to derive the effective state of the content based on its characteristics

!!! See Claude chat on project file stores.

"""

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def requires(**conditions):
    """Gate a method on boolean instance attributes or properties.

    Usage:
        @requires(writable=True)
        @requires(remote=True, cached=True)
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            for attr, expected in conditions.items():
                actual = getattr(self, attr, None)
                if actual != expected:
                    logger.error(f"'{fn.__name__}' on {self.model} requires {attr}={expected} (got {actual})")
                    return None
            return fn(self, *args, **kwargs)
        return wrapper
    return decorator

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def if_update_successful(fn):
    """Updates tracking attributes after a successful content modification."""
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        result = fn(self, *args, **kwargs)
            self.synced = False 
            self.unsaved = True 
            self.last_modified = oscal_date_time_with_timezone()

        return result
    return wrapper

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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
            content: The raw content as a string in its original format
            filename: The original filename or source URI (if applicable)
            original_format: The original format of the content (xml, json, yaml)
            state: The current state of the content (editable, read-only, locked)
            model: The identified OSCAL model (e.g., "catalog", "profile")
            version: The OSCAL version from the metadata (if available)
            title: The title from the metadata (if available)
            published: The publication date from the metadata (if available)
            version: The version from the metadata (if available)
            self.import_list = [
                {
                    "href_original": "https://example.com/profile.xml", # href specifd in the content
                    "href_valid"   : "https://example.com/root.xml",    # valid href (may be same as original or may be different if original could not be loaded)
                    "href_local"   : "file://example.com/root.xml",     # local copy (cached copy if remote) 
                    "valid": True,                                    # whether the content was successfully loaded and validated
                    "remote": True,                                    # whether the source is remote (http/https) or local file
                    "cached": True,                                    # whether a remote source has a local cache copy
                    "writable": False,                                  # whether the local source is writable (vs read-only)
                    "expires": "2024-01-01T00:00:00Z",                        # expiration timestamp for cached content (if applicable)
                    "model" : "profile",                                # "profile" or "catalog"
                    "status": ImportStatus.FAILED,
                    "error" : "",                               # why it failed (empty if loaded)
                    "object": OSCAL object if loaded, else None,
                    "import_list": [ ... ]
                } 
            ] # An array of dictionaries representing imported OSCAL content

        Methods:


    """
    def __init__(self, content: str = "", href: str = "", new: str = "", ttl: int = 0, support_db_conn: str = "", support_db_type: str = SUPPORT_DATABASE_DEFAULT_TYPE):
        """
            OSCAL Class
            Must provide at least one of the following parameters:
            - content: A string containing the OSCAL content
            - href: A URI or path to a file containing the OSCAL content
            - new: The type of OSCAL content to create (e.g., "catalog", "profile")

            - support_db_conn: Database connection string or path for OSCAL Support instance
            - support_db_type: Database type (default: "sqlite3") for OSCAL Support instance

            content and new are mutually exclusive.

            Raises:
                ValueError: If no content, filename nor new_model is provided
        """
        logger.debug("Initializing OSCAL class instance...")
        # Need at least one of content, href, or new_model
        if not content and not href:
            # logger.error("No content, href nor new_model. Unable to proceed.")
            raise ValueError("No content, href nor new_model provided. Unable to proceed.")

        # If just a href and no content, load the file
        if href and not content:
            logger.debug(f"Loading OSCAL content from href: {href}")
            self.href = href
            content = getfile(href)
            if not content:
                logger.error(f"Unable to get file: {href}")
                raise ValueError(f"Unable to get file: {href}")

        logger.debug("Setting up OSCAL content properties...")

        self.href_original: str = href # Original href as provided
        self.href_valid   : str = ""   # valid href (may be different than original)
        self.href_local   : str = ""   # local copy (cached copy if remote)
        self.valid   : bool = False    # content passed OSCAL validation
        self.remote  : bool = False    # source is http/https (vs local file)
        self.cached  : bool = False    # remote content has a local cache copy
        self.writable: bool = True     # local content is read-write (not read-only)

        self.content        : str = content
        self.original_format: str = ""
        self.model          : str = ""
        self.uuid           : str = ""
        self.oscal_version  : str = ""
        self.title          : str = ""
        self.published      : str = ""
        self.version        : str = ""
        self.remarks        : str = ""

        self.import_list: list = [] # An array of dictionaries 
        self.dict: dict | None = None # JSON/YAML constructs
        self.tree = None # XML constructs
        self.nsmap = {"": OSCAL_DEFAULT_XML_NAMESPACE} # XML namespace map
        self.__saxon = None


        self.synced = False # Boolean indicating whether the tree and dict are in sync
        self.unsaved = True # Boolean indicating whether there are unsaved modifications
        self.last_modified = "" # Timestamp of last modification
        self.loaded = datetime.now() # Timestamp of when the content was loaded
        self.ttl = ttl # Time to live for cached content, in seconds (0 or negative means no expiration)

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
    def __repr__(self):        
        
        return f"OSCAL[{self.model}:{self.oscal_version} {self.original_format.upper()}] {'VALID' if self.schema_valid else 'INVALID'} {self.title})"
    # -------------------------------------------------------------------------
    def __str__(self):
        ret_value = ""
        ret_value += "✅" if self.schema_valid else "⚠️"
        ret_value += f" {self.title}" if self.title else " [Untitled]"
        ret_value += f" [{self.model}]" if self.model else ""
        ret_value += f" {self.version}" if self.version else ""
        ret_value += f" {self.content_publication}" if self.content_publication else ""
        ret_value += f"\nSource File: {self.href_original}" if self.href_original else ""

        return ret_value
    # -------------------------------------------------------------------------
    def _load_source(self) -> str:
        """Fetch or read content from self.source based on classification.

        Returns the raw file content as a string, or empty string on failure.
        """
        src = self.source.strip()
        content = ""

        try:
            if self.source_type == "uri" and self.source_scheme == "file":
                # file:// URI → convert to local path
                local_path = urlparse(src).path
                logger.info(f"Loading controls from file:// URI: {local_path}")
                content = getfile(local_path)
            elif self.source_type == "uri" and self.source_scheme in {"http", "https"}:
                logger.info(f"Loading controls from URL: {src}")
                content = network.geturl(src)
            elif self.source_type == "file":
                logger.info(f"Loading controls from file: {src}")
                content = getfile(src)
            else:
                logger.warning(f"No loader implemented for source: {src} "
                               f"(type={self.source_type}, scheme={self.source_scheme})")
                return ""
        except Exception as e:
            logger.error(f"Failed to load source '{src}': {e}")
            return ""

        if not content:
            logger.error(f"Source returned no content: {src}")
            return ""

        return content
    # -------------------------------------------------------------------------
    def _classify_source(self):
        """Classify self.source as a URI, local/network file path, or unknown.

        Sets self.source_type, self.source_scheme, and self.source_supported.
        Logs a warning for any source type we recognise but cannot handle yet,
        and for anything we cannot classify at all.
        """
        src = self.source.strip()

        # --- Windows UNC path (\\server\share\...) ---
        if src.startswith("\\\\"):
            self.source_type = "file"
            self.source_scheme = ""
            self.source_supported = self._has_valid_extension(src)
            if not self.source_supported:
                logger.warning(f"UNC path does not end with a supported extension "
                               f"({', '.join(self._VALID_EXTENSIONS)}): {src}")
            return

        # --- Try parsing as a URI ---
        parsed = urlparse(src)

        if parsed.scheme and len(parsed.scheme) > 1:
            # Has a multi-char scheme → treat as URI
            # (single-char "scheme" is likely a Windows drive letter, e.g. C:)
            self.source_type = "uri"
            self.source_scheme = parsed.scheme.lower()

            if self.source_scheme in self._SUPPORTED_URI_SCHEMES:
                self.source_supported = self._has_valid_extension(parsed.path)
                if not self.source_supported:
                    logger.warning(f"URI does not end with a supported extension "
                                   f"({', '.join(self._VALID_EXTENSIONS)}): {src}")
            elif self.source_scheme in self._KNOWN_URI_SCHEMES:
                self.source_supported = False
                logger.warning(f"URI scheme '{self.source_scheme}' is recognised "
                               f"but not yet supported: {src}")
            else:
                self.source_supported = False
                logger.warning(f"Unknown URI scheme '{self.source_scheme}': {src}")
            return

        # --- Local / network file path (POSIX, Windows drive-letter, relative) ---
        self.source_type = "file"
        self.source_scheme = ""
        self.source_supported = self._has_valid_extension(src)
        if not self.source_supported:
            logger.warning(f"File path does not end with a supported extension "
                           f"({', '.join(self._VALID_EXTENSIONS)}): {src}")
    # -------------------------------------------------------------------------
    @staticmethod
    def _has_valid_extension(path: str) -> bool:
        """Return True if *path* ends with .xml, .json, .yaml, or .yml (case-insensitive)."""
        # Use PurePosixPath to extract suffix; works on URL paths too
        suffix = PurePosixPath(path).suffix.lower()
        return suffix in Controls._VALID_EXTENSIONS
    # -------------------------------------------------------------------------
    def _build_import_tree(self, new_href: str = "") -> Boolean:
        """
        Internal method to build the structure of imports for efficient access.
        """
        status = False
        tree_obj = {
            "href_original": self.source,
            "href": self.source,
            "type": "",
            "status": "",
            "error": "",
            "children": [],
            "object": None
        }
        # classify and load the source
        if self.source != "":
            logger.debug(f"Building Import Tree for {self.source}")
            self._classify_source()
            if self.source_supported:
                logger.debug(f"Source classified as type '{self.source_type}' with scheme '{self.source_scheme}'. Attempting to load content.")
                content = self._load_source()
                if content:
                    oscal_file = OSCAL(content=content)
                    if oscal_file.is_valid():
                        tree_obj["object"] = oscal_file
                        tree_obj["type"] = oscal_file.content_type
                        tree_obj["status"] = "loaded"
                        logger.debug(f"Successfully loaded content for '{self.source}'. Detected type: {tree_obj['type']}")
                        status = True
                    else:
                        tree_obj["status"] = "invalid"
                        tree_obj["error"] = "Content loaded but failed OSCAL validation"
                        logger.error(f"Loaded content from '{self.source}' is not valid OSCAL: {oscal_file.validation_errors}")
                else:
                    tree_obj["status"] = "failed"
                    tree_obj["error"] = "Failed to load content from source"
                    logger.error(f"Failed to load content from '{self.source}'. No content returned.")
            else:
                tree_obj["status"] = "unsupported"
                tree_obj["error"] = "Source type or scheme is not supported for loading"
                logger.warning(f"Unsupported source — cannot load: {self.source} "
                               f"(type={self.source_type}, scheme={self.source_scheme})")


        if status and tree_obj["type"] == "profile":
            pass # TODO: recursively process imports and build the full import tree

        return status
    # -------------------------------------------------------------------------
    @property
    def unresolved_imports(self) -> dict:
        """Return the subset of import_tree entries with FAILED status."""
        return {href: details for href, details in self.import_tree.items() if details.get('status') == 'failed'}

    # -------------------------------------------------------------------------
    def retry_import(self, failed_href: str, replacement_href: str) -> bool:
        """Retry a failed import by replacing its href and re-attempting resolution.
        Returns True if the retry was initiated, False if the failed_href was not found.
        """
        if failed_href in self.import_tree:
            logger.info(f"Retrying import for '{failed_href}' with replacement '{replacement_href}'")
            self.import_tree[failed_href]['href'] = replacement_href
            self.import_tree[failed_href]['status'] = 'retrying'
            return True
        else:
            logger.warning(f"Failed import href '{failed_href}' not found in import tree. Cannot retry.")
            return False

    # -------------------------------------------------------------------------
    @property
    def cache_expired(self) -> bool:
        """Only meaningful when remote and cached."""
        if not self.remote or not self.cached or self.ttl <= 0:
            return False
        return (datetime.now() - self.loaded).total_seconds() > self.ttl

    # -------------------------------------------------------------------------
    @property
    def editable(self) -> bool:
        """Can this content be modified?"""
        return self.valid and not self.remote and self.writable

    # -------------------------------------------------------------------------
    @property
    def state(self) -> str:
        """Derive the effective state from the independent dimensions."""
        if not self.valid:
            return "invalid"
        if self.remote:
            if not self.cached:
                return "not-cached"
            if self.cache_expired:
                return "expired"
            return "read-only"
        # local
        return "editable" if self.writable else "read-only"
    # -------------------------------------------------------------------------
    @property
    def is_stale(self) -> bool:
        """Check if the resolved catalog has exceeded its time-to-live."""
        if self.ttl <= 0:
            return False
        elapsed = (datetime.now(timezone.utc) - self.processed_datetime).total_seconds()
        return elapsed > self.ttl
    # -------------------------------------------------------------------------
    def refresh(self):
        """Re-resolve the source profile to update the control set.
        Placeholder for profile resolution logic.
        """
        logger.info(f"Refreshing content from source file: {self.source_profile}")
        self.processed_datetime = datetime.now(timezone.utc)
    # -------------------------------------------------------------------------
    def initial_validation(self) -> bool:
        """
        Perform initial validation of content, which includes first ensuring the
        content is a recognized OSCAL format type (xml, json or yaml) and
        well formed, before passing it to the OSCAL validation method.
        Returns:
            bool: True if initial validation is successful, False otherwise
        """
        logger.debug("Performing initial validation of content...")
        status = False
        oscal_root = ""
        oscal_version = ""
        content_title = ""
        content_version = ""
        content_publication = ""

        self.original_format = detect_data_format(self.content)
        logger.debug(f"Detected content format: {self.original_format}")

        if self.original_format in OSCAL_FORMATS:
            logger.debug(f"{self.original_format} is an OSCAL format.")

            if self.original_format == "xml":
                self.tree = safe_load_xml(self.content)
                if self.tree is not None:
                    status = True
                    self.well_formed["xml"] = True
                    oscal_root = self.xpath_atomic("/*/name()")
                    oscal_version = "v" + self.xpath_atomic("/*/metadata/oscal-version/text()")
                    content_title = self.xpath_atomic("/*/metadata/title/text()")
                    content_version = self.xpath_atomic("/*/metadata/version/text()")
                    content_publication = self.xpath_atomic("/*/metadata/published/text()")
                else:
                    status = False
                    logger.error("Content is not well-formed XML.")

            elif self.original_format in ("json", "yaml"):
                loaded = safe_load(self.content, self.original_format)
                if isinstance(loaded, dict):
                    self.dict = loaded
                    logger.debug(f"Loaded content into dictionary for format {self.original_format}.")
                    status = True
                    oscal_root = next(iter(self.dict.keys())) if self.dict else ""
                    root_obj = self.dict.get(oscal_root, {})
                    metadata = root_obj.get('metadata', {}) if isinstance(root_obj, dict) else {}
                    oscal_version = f"v{metadata.get('oscal-version', '')}"
                    content_title = metadata.get('title', '')
                    content_version = metadata.get('version', '')
                    content_publication = metadata.get('published', '')
                else:
                    status = False
                    logger.error(f"Content is not well-formed {self.original_format.upper()}.")

        else:
            logger.error(f"Content is not one of {OSCAL_FORMATS}.")
            status = False

        if status:
            if oscal_version in self.support.versions:
                self.oscal_version = oscal_version
                if oscal_root in self.support.enumerate_models(self.oscal_version):
                    self.model = oscal_root
                    self.title = content_title
                    self.version = content_version
                    self.published = content_publication
                    logger.debug(f"OSCAL model '{self.model}' and version '{self.oscal_version}' identified.")
                    status = True
                    # **** TODO: VALIDATE ****
                    self.validate()
                else:
                    logger.error("ROOT ELEMENT IS NOT AN OSCAL MODEL: " + oscal_root)
                    status = False
            else:
                logger.error("OSCAL VERSION IS NOT RECOGNIZED: " + oscal_version)
                status = False

        return status

    # -------------------------------------------------------------------------
    def validate(self, format: str = "") -> bool:
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

        if format == "xml":
            logger.debug("Validating XML content against schema...")
            xml_schema_content = self.support.asset(self.oscal_version, self.model, "xml-schema")

            if xml_schema_content:
                import xmlschema
                try:

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

        elif format in ("json", "yaml"):
            logger.debug(f"Validating {format} content against schema...")
            json_schema_content = self.support.asset(self.oscal_version, self.model, "json-schema")

            if json_schema_content:
                import jsonschema_rs
                try:

                    # Parse schema string to dict if needed
                    if isinstance(json_schema_content, str):
                        schema_dict = json.loads(json_schema_content)
                    else:
                        schema_dict = json_schema_content

                    # Ensure schema_dict is valid before validation
                    if isinstance(schema_dict, dict) and isinstance(self.dict, dict):

                        # Validate (raises exception with details if invalid)
                        jsonschema_rs.validate(self.dict, schema_dict)  # Does not return a value

                        self.schema_valid["json"] = True
                        self.schema_valid["yaml"] = True  # YAML uses JSON schema
                        logger.debug("JSON schema validation passed.")
                    else:
                        logger.error("Loaded JSON schema is not a valid dictionary.")
                        self.schema_valid["json"] = False
                        self.schema_valid["yaml"] = False

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

        _target = target_format.lower()
        if _target == "xml":
            if self.original_format == "xml":
                logger.debug("Content is already in XML format; no conversion needed.")
                return
            elif self.original_format == "json":
                # Convert JSON to XML
                logger.debug("Converting JSON to XML...")
                xsl_converter=self.support.asset(self.oscal_version, self.model, "json-to-xml")
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
                xsl_converter=self.support.asset(self.oscal_version, self.model, "json-to-xml")
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

        elif _target == "json":
            if self.original_format == "json":
                logger.debug("Content is already in JSON format; no conversion needed.")
                return
            elif self.original_format == "xml":
                # Convert XML to JSON
                logger.debug("Converting XML to JSON...")
                xsl_converter=self.support.asset(self.oscal_version, self.model, "xml-to-json")
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

        elif _target in ("yaml", "yml"):
            if self.original_format in ["yaml", "yml"]:
                logger.debug("Content is already in YAML format; no conversion needed.")
                return
            elif self.original_format == "json":
                # Convert JSON to YAML
                logger.debug("Converting JSON to YAML...")


    # -------------------------------------------------------------------------
    def save(self, filename: str="", format: str="", pretty_print: bool=False) -> bool:
        f"""
        Save the current OSCAL content to a file.
        With no parameters, saves to the original location in the original format.
        This will save to any valid filename, even if the file extension does not match the format.

        Args:
            filename (str): The path to the file where content will be saved.
            format (str): The format to save the content in {OSCAL_FORMATS}.
            pretty_print (bool): Whether to pretty print the output.

        Returns:
            bool: True if save is successful, False otherwise
        """
        status = False

        # If a format is passed, ensure it is valid
        if format:
            format = format.lower()
            if format not in OSCAL_FORMATS:
                logger.debug(f"Cannot save in ({format}) format. Not an OSCAL format.")
                return False

        # If no format is passed, use the original format
        else:
            format = self.original_format

        # If no format was passed and no original format, cannot proceed
        if format == "":
            logger.error("No format specified for saving OSCAL content.")
            return False

        # If no filename is passed, use the original location
        if filename == "":
            filename = self.href

        # If no filename was passed and no original location, cannot proceed
        if filename == "":
            logger.error("No filename specified for saving OSCAL content.")
            return False

        # Ensure the directory exists
        file_path = os.path.dirname(os.path.abspath(filename))
        if not chkdir(file_path, make_if_not_present=True):
            logger.error(f"Directory does not exist and could not be created: {os.path.dirname(file_path)}")
            return False

        self.set_metadata({
            "uuid": str(uuid.uuid4()),
            "last-modified": oscal_date_time_with_timezone()
        })

        logger.debug(f"Saving content as {filename} in OSCAL {format.upper()} format.")
        if format == "xml":
            if self.dict and self.support and not self.tree:
                xsl_converter=self.support.asset(self.oscal_version, self.model, "json-to-xml")
                if isinstance(xsl_converter, str):
                    json_content = json.dumps(self.dict)
                    xml_output = oscal_json_to_xml(
                        json_content=json_content,
                        xsl_converter=xsl_converter,
                        validate_json=True
                    )
                    self.tree = ElementTree.ElementTree(ElementTree.fromstring(xml_output))
                else:
                    logger.error("Unable to locate XSLT converter for JSON to XML conversion. Cannot serialize XML.")
                    return False
            else:
                xml_output = self.xml_serializer()
            status = putfile(filename, xml_output)

        elif format in ("json", "yml", "yaml"):
            logger.debug("Preparing to save JSON/YAML content...")

            if not self.dict:
                xsl_converter=self.support.asset(self.oscal_version, self.model, "xml-to-json")
                if isinstance(xsl_converter, str):
                    json_output = oscal_xml_to_json(self.content, xsl_converter=xsl_converter)
                    logger.debug(f"Converted XML content to JSON: {json_output[:100]}...")  # Log a snippet of the JSON output
                    self.dict = json.loads(json_output)
                else:
                    logger.error("Unable to locate XSLT converter for XML to JSON conversion. Cannot serialize JSON.")
                    return False

            if self.dict is None:
                logger.error("No JSON content available to save.")
                return False

            if format == "json":
                logger.debug("Saving content in JSON format...")
                status = save_json(self.dict, filename) # pretty_print=pretty_print)
            else: # YAML
                logger.debug("Saving content in YAML format...")
                yaml_out = yaml.dump(self.dict, sort_keys=False, indent=INDENT if pretty_print else None)

                status = putfile(filename, yaml_out)
        else:
            logger.error(f"Unsupported format for saving: {format}")
            return False

        if status:
            logger.info(f"OSCAL content saved to {filename} in XML format.")
            self.unsaved = False

        else:
            logger.error(f"Failed to save OSCAL content to {filename} in XML format.")

        return status

    # -------------------------------------------------------------------------
    def set_metadata(self, content: dict = {}):
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
                if self.tree is not None:
                    self.__set_field(f"/*/metadata/{item}", content.get(item, ""))
                elif self.dict is not None:
                    if "metadata" not in self.dict:
                        self.dict["metadata"] = {}
                        logger.warning("No metadata section found in content. Creating.")
                    self.dict["metadata"][item] = content.get(item, "")                

    # -------------------------------------------------------------------------
    def xpath_atomic(self, xExpr: str, context: ElementTree.Element | ElementTree.ElementTree | None = None) -> str:
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

        ret_value = ""

        if context is not None:
            logger.debug(f"Using provided context for XPath Atomic: {xExpr}")
        else:
            context = self.tree
            logger.debug(f"Using document root as context for XPath Atomic: {xExpr}")

        if context is None:
            logger.error("No XML context available for XPath Atomic query.")
            return ""

        results = elementpath.select(context, xExpr, namespaces=self.nsmap)
        if not results:
            logger.debug(f"No XPath Atomic results found for expression: {xExpr}")
            return ""

        ret_value = results[0]
        logger.debug(f"xPath atomic result type: {str(type(ret_value))}")

        return str(ret_value)

    # -------------------------------------------------------------------------
    def xpath(self, xExpr: str, context: ElementTree.Element | ElementTree.ElementTree | None = None) -> Optional[list[Any]]:
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
        ret_value: Optional[list[Any]] = None
        if context is not None:
            logger.debug(f"Using provided context for XPath: {xExpr}")
        else:
            context = self.tree
            logger.debug(f"Using document root as context for XPath: {xExpr}")

        if context is None:
            logger.error("No XML context available for XPath query.")
            return None

        try:

            result = elementpath.select(context, xExpr, namespaces=self.nsmap)
            if result is None:
                ret_value = None
            elif isinstance(result, list):
                ret_value = result
            else:
                ret_value = [result]
            # logger.debug(f"xPath results type: {str(type(ret_value))} with {len(ret_value)} nodes found.")
        except Exception as error:
            logger.error(f"XPath expression '{xExpr}' failed: {str(error)}")
            ret_value = None

        return ret_value

    # -------------------------------------------------------------------------
    @requires(editable=True)
    @if_update_successful
    def __set_field(self, path: str, field_value: str):
        """
        Sets a specific field in the OSCAL content.
        The xpath expression must point to a single element.
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
            if parent_nodes is None or len(parent_nodes) != 1:
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


    # -------------------------------------------------------------------------
    @requires(editable=True)
    @if_update_successful
    def assign_html_string_to_node(self, parent_node: ElementTree.Element, html_string: str):
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
    @requires(editable=True)
    @if_update_successful
    def append_child(self, xpath: str, node_name: str, node_content: str = "", attribute_list: list = []) -> (ElementTree.Element | None):
        # logger.debug("APPENDING " + node_name + " as child to " + xpath) #  + " in " + self.tree.tag)
        status = False
        child = None
        try:
            logger.debug("Fetching parent at " + xpath)
            # Use elementpath for reliable XPath processing
            parent_nodes = elementpath.select(self.tree, xpath, namespaces=self.nsmap)
            parent_node = None
            if isinstance(parent_nodes, list) and len(parent_nodes) > 0:
                parent_node = parent_nodes[0]
            # parent_node = self.xpath(xpath)
            logger.debug(parent_node)
            if parent_node is not None:
                logger.debug("TAG: " + parent_node.tag)
                child = ElementTree.Element(node_name)

                logger.debug("SETTING CONTENT")
                if node_content != "":
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
    @requires(editable=True)
    @if_update_successful
    def append_resource(self, uuid: str = "", title: str = "", description: str = "", props: list = [], rlinks: list = [], base64: str = "", remarks: str = "") -> ElementTree.Element:
        """
        Appends a resource element to the back-matter section.
        """
        return append_resource(self, uuid, title, description, props, rlinks, base64, remarks)

    # -------------------------------------------------------------------------
    def get_serialized_content(self, format: str) -> str:
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

        if format == "xml":
            # if self.tree is None:
            return self.xml_serializer()
        elif format == "json":
            return self.json_serializer()
        elif format in ("yaml", "yml"):
            return self.yaml_serializer()
        else:
            logger.error(f"Unsupported format for serialization: {format}")
            return ""

    # -------------------------------------------------------------------------
    def xml_serializer(self) -> str:
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
        out_bytes = ElementTree.tostring(root, 'utf-8')
        out_string = normalize_content(out_bytes)
        if out_string is None:
            return ""
        out_string = out_string.replace("ns0:", "")
        out_string = out_string.replace(":ns0", "")

        return out_string

    # -------------------------------------------------------------------------
    def json_serializer(self) -> str:
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
    def yaml_serializer(self) -> str:
        """
        Serializes the current dict to a string.
        Returns:
        - str: The serialized YAML content as a string.
        """
        logger.debug("Serializing dict for string output as YAML.")
        out_string: str = yaml.dump(self.dict, indent=INDENT, sort_keys=False)  # type: ignore[assignment]
        logger.debug("LEN: " + str(len(out_string)))

        return out_string



# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# class OSCALState(str, Enum):
#     READY        = "ready"        # The content is valid
#     NOT_LOADED   = "not-loaded"   # The content has not been loaded
#     INVALID      = "invalid"      # The content is not valid
#     EXPIRED      = "expired"      # The content is valid, but cached copy has expired

# -------------------------------------------------------------------------
"""
    - valid or not_valid (self.valid)
    - local or remote (self.remote)
        - if remote (always read-only):
            - cached locally or not (self.cached)
                - if cached locally:
                    - cache is valid or expired
        - if local:
            - read-only or read-write

"""


# -------------------------------------------------------------------------
def append_props(parent_node: ElementTree.Element, props: list):
    """
    Appends multiple property elements to the provided parent XML node.
    Parameters:
    - parent_node (ElementTree.Element): The parent XML node to which the properties will be added.
    - props (list): A list of dictionaries, each containing property attributes and optional remarks.
    """
    for prop in props:
        append_prop(parent_node, prop)
# -------------------------------------------------------------------------
def append_prop(parent_node: ElementTree.Element, prop: dict):
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
def append_links(parent_node: ElementTree.Element, links: list):
    """
    Appends multiple link elements to the provided parent XML node.
    Parameters:
    - parent_node (ElementTree.Element): The parent XML node to which the links will be added.
    - links (list): A list of link URLs as strings.
    """
    for link in links:
        append_link(parent_node, link)
# -----------------------------------------------------------------------------
def append_link(parent_node: ElementTree.Element, link: dict):
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
def append_resource(oscal_obj: OSCAL, uuid: str = "", title: str = "", description: str = "", props: list = [], rlinks: list = [], base64: str = "", remarks: str = "") -> ElementTree.Element:
    """
    Appends a resource element to the back-matter section.
    """
    resource = ElementTree.Element("resource")
    if uuid == "":
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

    if back_matter and isinstance(back_matter, list) and len(back_matter) > 0:
        back_matter = back_matter[0]
    else:
        back_matter = ElementTree.Element("back-matter")
        if oscal_obj.tree is not None:
            if isinstance(oscal_obj.tree, ElementTree.ElementTree):
                root_node = oscal_obj.tree.getroot()
            else:
                root_node = oscal_obj.tree

            if root_node is not None:
                root_node.append(back_matter)

    back_matter.append(resource)

    return resource
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# -----------------------------------------------------------------------------

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# -------------------------------------------------------------------------
# -----------------------------------------------------------------------------
def serializer(xml_object: ElementTree.Element) -> str:
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
def new_uuid() -> str:
    return str(uuid.uuid4())


if __name__ == '__main__':
    print("OSCAL Content Class Module. This is not intended to be run as a stand-alone module.")

