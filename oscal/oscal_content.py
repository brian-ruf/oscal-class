"""
    OSCAL Class

    A class for creation, manipulation, validation and format convertion of OSCAL content.
    All published OSCAL versions, formats and models can be validated and converted.
    Newly published versions can be "learned" by updating the OSCAL Support database.
    See https://github.com/brian-ruf/oscal-class for more details.

"""
from __future__         import annotations
import os
import json
import yaml
import uuid
import elementpath
from loguru             import logger
from typing             import Optional, Any
from datetime           import datetime, timezone
from functools          import wraps
from datetime           import datetime
from enum               import Enum
from pathlib            import PurePosixPath, PureWindowsPath
from urllib.parse       import urlparse
from urllib.request     import urlopen
from xml.etree          import ElementTree
from dataclasses        import dataclass, field

from ruf_common.logging import LoggableMixin
from ruf_common.network import download_file
from ruf_common.data    import detect_data_format, safe_load, safe_load_xml
from ruf_common.lfs     import getfile, chkdir, putfile, normalize_content, save_json
from .oscal_support     import get_support, OSCAL_DEFAULT_XML_NAMESPACE, OSCAL_FORMATS
from .oscal_datatypes   import oscal_date_time_with_timezone
from .oscal_converters  import oscal_xml_to_json, oscal_json_to_xml, oscal_markdown_to_html, oscal_markdown_to_html

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Constants
INDENT = 2 # Number of spaces to use for indentation in pretty-printed output
# URI schemes we know how to fetch today
_SUPPORTED_URI_SCHEMES = {"http", "https", "file"}
# URI schemes we recognise but cannot fetch yet
_KNOWN_URI_SCHEMES = {"ftp", "ftps", "sftp", "s3", "gs", "az"}
# URI schemes we can handle with Python stdlib tooling (no third-party SDKs)
_SIMPLE_URI_SCHEMES = {"http", "https", "file", "ftp", "data"}
# OSCAL Default Namespace for XML processing
_NSMAP = {"": OSCAL_DEFAULT_XML_NAMESPACE} # XML namespace map

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Factory Methods and Initializers
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def requires(**conditions):
    """Gate a method on boolean instance attributes or properties.

    Usage:
        @requires(writable=True)
        @requires(is_remote=True, is_cached=True)
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

# -----------------------------------------------------------------------------
def if_update_successful(fn):
    """Updates tracking attributes after a successful content modification."""
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        result = fn(self, *args, **kwargs)
        self.is_synced = False
        self.is_unsaved = True
        self.last_modified = oscal_date_time_with_timezone()
        return result
    return wrapper

# -----------------------------------------------------------------------------
def sync_first(fn):
    """Ensure content is synced before performing the operation."""
    logger.debug(f"Applying @sync_first decorator to '{fn.__name__}'")
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        if not self._sync():
            logger.warning(f"Unable to find required format convertion for '{fn.__name__}' on '{self.model}'.")
            return None
        return fn(self, *args, **kwargs)
    return wrapper

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# OSCAL CLASS
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCAL(LoggableMixin):
    """
        Attributes (Content Location):
            href_original: The original href as provided (e.g., in an import statement)
            is_valid_href: True if the href is accessible and the content was loaded successfully
            href         : Working href (may differ from href_original after redirect/retry)

        Attributes (Class States):
            is_valid    : True if the content passed OSCAL validation, False otherwise
            is_local    : True if the source is a local file, False if it's remote (http/https)
            is_cached   : True if remote content has a local cache copy, False otherwise
            is_read_only: True if local content is read-only, False if it's read-write
            is_synced   : True if the in-memory tree/dict is in sync with the raw content, False if there are unsaved changes
            is_unsaved  : True if there are unsaved modifications, False otherwise

        Attributes (Caching and Expiration):
            loaded: Timestamp of when the content was loaded (datetime object)
            ttl: Time to live for cached content in seconds (0 or less means never expire)

        Attributes (Content and Summary):
            content        : The raw content as a string in its original format
            original_format: The original format of the content (xml, json, yaml)
            model          : The identified OSCAL model (e.g., "catalog", "profile")
            oscal_version  : The OSCAL version from the metadata (if available)
            last_modified  : The last modified date from the metadata (if available)
            title          : The title from the metadata (if available)
            published      : The publication date from the metadata (if available)
            version        : The version from the metadata (if available)
            remarks        : Any remarks from the metadata (if available)

        Attributes (Processing Objects):
            self.import_list = [] # An array of dictionaries representing imported OSCAL content

        Properties:
            is_editable: True if the content can be modified, False otherwise

    """
    def __init_common__(self, ttl: int = 0, support_db_conn: str = "", support_db_type: str = ""):

        logger.debug("Initializing common OSCAL class properties...")

        # Content Location
        self._origin      : str = ""     # Origin of the content (e.g. "load", "acquire", "new")
        self.href         : str = ""     # Working href
        self.href_original: str = ""     # The original href as provided (e.g., in an import statement)
        self.is_valid_href: bool = False # True if the href is accessible and the contant was able to be fetched.
        self._refs: list[OscalRef] = []

        # Class States
        self.is_valid    : bool = False # content passed OSCAL validation
        self.is_local    : bool = True  # source is local file (vs http/https)
        self.is_cached   : bool = False # remote content has a local cache copy
        self.is_read_only: bool = True  # local content is read-only (not read-write)
        self.is_synced   : bool = False # Boolean indicating whether the tree and dict are in sync
        self.is_unsaved  : bool = True  # Boolean indicating whether there are unsaved modifications

        # Caching and Expiration
        self.loaded: datetime = datetime.now() # Timestamp of when the content was loaded
        self.ttl: int = 0 # Seconds (0 or less = forever): Time to live for cached content

        # Content and Summary
        # self.original_content: str = "" # The raw content as a string in its original format
        self.original_format : str = ""
        self.model           : str = ""
        self.oscal_version   : str = ""
        self.last_modified   : str = "" 
        self.title           : str = ""
        self.published       : str = ""
        self.version         : str = ""
        self.remarks         : str = ""

        # Processing Objects
        self.import_list: list = []    # An array of dictionaries 
        self.import_tree: dict = {}    # A dictionary representing the structure of imports for efficient access
        self._dict: dict | None = None # JSON/YAML constructs
        self._tree = None              # XML constructs

        # Validation Status
        self.schema_valid = {}    # A dictionary indicating whether the content is valid against the schema for each format
        self.schema_valid["_tree"]  = None # Will be set to True/False after XML validation, None if not yet validated or not applicable
        self.schema_valid["_dict"] = None # Will be set to True/False after JSON validation, None if not yet validated or not applicable
        self.metaschema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL Metaschema

        # Get the OSCAL support object 
        self._support = get_support() 

    # -------------------------------------------------------------------------
    # Backward-compatible state aliases
    @property
    def valid(self) -> bool:
        return self.is_valid

    @valid.setter
    def valid(self, value: bool):
        self.is_valid = value

    @property
    def local(self) -> bool:
        return self.is_local

    @local.setter
    def local(self, value: bool):
        self.is_local = value

    @property
    def remote(self) -> bool:
        return self.is_remote

    @remote.setter
    def remote(self, value: bool):
        self.is_local = not value

    @property
    def cached(self) -> bool:
        return self.is_cached

    @cached.setter
    def cached(self, value: bool):
        self.is_cached = value

    @property
    def read_only(self) -> bool:
        return self.is_read_only

    @read_only.setter
    def read_only(self, value: bool):
        self.is_read_only = value

    @property
    def synced(self) -> bool:
        return self.is_synced

    @synced.setter
    def synced(self, value: bool):
        self.is_synced = value

    @property
    def unsaved(self) -> bool:
        return self.is_unsaved

    @unsaved.setter
    def unsaved(self, value: bool):
        self.is_unsaved = value

    @property
    def is_remote(self) -> bool:
        return not self.is_local

    # -------------------------------------------------------------------------
    @classmethod
    def loads(cls, content: str | dict, *, href: str | None = None):
        """Initialize from in-memory OSCAL content.
        
        Args:
            content: OSCAL content already available in memory (string or dictionary).
            href: Optional URI identifying the original content source.
        """
        instance = cls.__new__(cls)
        instance.__init_common__()
        instance._origin       = "loads"
        instance.href_original = href if href else ""

        normalized_content = json.dumps(content) if isinstance(content, dict) else content
        if instance.initial_validation(normalized_content):
            instance.is_read_only = False

        return instance

    # -------------------------------------------------------------------------
    @classmethod
    def load(cls, source: str | os.PathLike | Any, *, href: str | None = None):
        """Initialize from a local file path or file-like object.

        This aligns with Python's conventional `load(...)` behavior.
        Use `loads(...)` for in-memory strings/dicts, and `acquire(...)` for
        URI/reference resolution and fallback sources.
        """
        instance = cls.__new__(cls)
        instance.__init_common__()
        instance._origin = "load"

        content = ""
        resolved_href = href if href else ""

        if hasattr(source, "read"):
            payload = source.read()
            if isinstance(payload, (bytes, bytearray)):
                content = payload.decode("utf-8", errors="replace")
            else:
                content = str(payload)
            if not resolved_href:
                resolved_href = str(getattr(source, "name", ""))
        elif isinstance(source, (str, os.PathLike)):
            path = os.fspath(source)
            content = getfile(path)
            if not resolved_href:
                resolved_href = path
        else:
            raise TypeError(
                f"load() expected path-like or file-like object — got {type(source).__name__}"
            )

        instance.href_original = resolved_href
        if instance.initial_validation(content):
            instance.is_read_only = False

        return instance

    # -------------------------------------------------------------------------
    @classmethod
    def acquire(cls, source: str | dict | OscalRef | list):
        """
        Acquire OSCAL content from one or more URI/reference sources.

        Accepts:
            - str               : URI or path-like href
            - OscalRef          : already-typed ref
            - dict              : reference dict with at least "href"
            - list[...]         : mixed list of any of the above

        Returns self to allow method chaining.
        """

        instance = cls.__new__(cls)
        instance.__init_common__()
        instance._origin       = "acquire"
        instance._refs = _normalize_refs(source)

        content = load_content(instance._refs) 
        
        instance.initial_validation(content)
        return instance

    # -------------------------------------------------------------------------
    @classmethod
    def from_string(cls, content: str, *, href: str | None = None):
        """Explicit constructor for in-memory OSCAL string content."""
        return cls.loads(content, href=href)

    # -------------------------------------------------------------------------
    @classmethod
    def from_dict(cls, content: dict, *, href: str | None = None):
        """Explicit constructor for in-memory OSCAL dictionary content."""
        return cls.loads(content, href=href)

    # -------------------------------------------------------------------------
    @classmethod
    def from_file(cls, source: str | os.PathLike | Any, *, href: str | None = None):
        """Explicit constructor for local file path or file-like object."""
        return cls.load(source, href=href)

    # -------------------------------------------------------------------------
    @classmethod
    def from_uri(cls, source: str | dict | OscalRef | list):
        """Explicit constructor for URI/reference acquisition."""
        return cls.acquire(source)

    # -------------------------------------------------------------------------
    @classmethod
    def new(cls, title: str, version: str = "", published: str = ""):
        """Create a new OSCAL document from a template.
        
        Must be called on a specific model class (Catalog.new(), Profile.new(), etc.),
        not on OSCAL directly.
        
        Args:
            title:   Document title (stored in metadata).
            version: Document version (stored in metadata).
            published: Document publication date (stored in metadata).
            **kwargs: Additional metadata fields (e.g. published, last_modified).
        """
        if cls is OSCAL:
            raise TypeError(
                "OSCAL.new() requires a specific model class. "
                "Use Catalog.new(), Profile.new(), etc."
            )
        instance = cls.__new__(cls)
        instance.__init_common__()
        instance._origin     = "new"
        instance.model       = cls.__name__.lower()  # e.g. "catalog", "profile"
        content     = create_new_oscal_content(instance.model, title, version, published)
        if instance.initial_validation(content):
            instance.is_read_only = False
        return instance

    # -------------------------------------------------------------------------
    def dump(self, filename: str="", format: str="", pretty_print: bool=False) -> bool:
        """
        Write the current OSCAL content to a file.
        With no parameters, saves to the original location in the original format.
        This will save to any valid filename, even if the file extension does not match the format.

        Args:
            filename (str): The path to the file where content will be saved.
            format (str): The format to save the content in {OSCAL_FORMATS}.
            pretty_print (bool): Whether to pretty print the output.

        Returns:
            bool: True if write is successful, False otherwise
        """
        status = False
        content = ""

        # if no format is passed, use the original format if it is valid
        if format == "":
            logger.debug("No format specified for dump; will use original format if valid.")
            format = self.original_format
            if format not in OSCAL_FORMATS:
                logger.error(f"No format specified and original format ({format}) is not a valid OSCAL format. Cannot save without a valid format.")
                return False

        # if no filename is passed, use the original location if available
        if filename == "":
            logger.debug("No filename specified for dump; will use original location if available.")
            filename = self.href if self.href else self.href_original
            if filename == "":
                logger.error("No filename specified and no valid original location available. Cannot save without a filename.")
                return False

        # Ensure the directory exists
        file_path = os.path.dirname(os.path.abspath(filename))
        if not chkdir(file_path, make_if_not_present=True):
            logger.error(f"Directory does not exist and could not be created: {os.path.dirname(file_path)}")
            return False

        logger.debug(f"Writing content as {filename} in OSCAL {format.upper()} format.")
        content = self.dumps(format=format, pretty_print=pretty_print)

        if not content:
            logger.error(f"Serialization to {format.upper()} produced no content. Cannot save.")
            return False

        status = putfile(filename, content)

        if status:
            logger.info(f"Content successfully written to {filename}.")
        else:
            logger.error(f"Failed to write content to {filename}.")

        return status

    # -------------------------------------------------------------------------
    def __repr__(self):
        ret_value = ""
        if self.original_format == "xml":
            ret_value += "✅" if self.schema_valid["_tree"] else "⚠️"
        elif self.original_format in ("json", "yaml"):
            ret_value += "✅" if self.schema_valid["_dict"] else "⚠️"

        ret_value += f" OSCAL[{self.model}:{self.oscal_version} {self.original_format.upper()}] {self.title})"

        return ret_value

    # -------------------------------------------------------------------------
    def __str__(self):
        ret_value = ""
        if self.original_format == "xml":
            ret_value += "✅" if self.schema_valid["_tree"] else "⚠️"
        elif self.original_format in ("json", "yaml"):
            ret_value += "✅" if self.schema_valid["_dict"] else "⚠️"
        ret_value += f" {self.title}" if self.title else " [Untitled]"
        ret_value += f" [{self.model}]" if self.model else ""
        ret_value += f" {self.version}" if self.version else ""
        ret_value += f" {self.published}" if self.published else ""
        ret_value += f"\nSource File: {self.href_original}" if self.href_original else ""

        return ret_value

    # -------------------------------------------------------------------------
    def _build_import_tree(self, new_href: str = "") -> bool:
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
            classify_source() 
            if self.source_supported:
                logger.debug(f"Source classified as type '{self.source_type}' with scheme '{self.source_scheme}'. Attempting to load content.")
                content = load_source() 
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
    def is_cache_expired(self) -> bool:
        """Only meaningful when remote and cached."""
        if self.is_local or not self.is_cached or self.ttl <= 0:
            return False
        return (datetime.now() - self.loaded).total_seconds() > self.ttl

    # -------------------------------------------------------------------------
    @property
    def is_editable(self) -> bool:
        """Can this content be modified?"""
        return self.is_valid and self.is_local and not self.is_read_only

    # -------------------------------------------------------------------------
    @property
    def state(self) -> str:
        """Derive the effective state from the independent dimensions."""
        if not self.is_valid:
            return "invalid"
        if self.is_remote:
            if not self.is_cached:
                return "not-cached"
            if self.is_cache_expired:
                return "expired"
            return "read-only"
        # local
        return "read-write" if self.is_local and not self.is_read_only else "read-only"

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
    def initial_validation(self, content: str) -> bool:
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

        self.original_format = detect_data_format(content)
        logger.debug(f"Detected content format: {self.original_format}")

        if self.original_format in OSCAL_FORMATS:
            logger.debug(f"{self.original_format} is an OSCAL format.")

            if self.original_format == "xml":
                self._tree = safe_load_xml(content)
                if self._tree is not None:
                    status = True
                    oscal_root = self.xpath_atomic("/*/name()")
                    oscal_version = "v" + self.xpath_atomic("/*/metadata/oscal-version/text()")
                    content_title = self.xpath_atomic("/*/metadata/title/text()")
                    content_version = self.xpath_atomic("/*/metadata/version/text()")
                    content_publication = self.xpath_atomic("/*/metadata/published/text()")
                else:
                    status = False
                    logger.error("Content is not well-formed XML.")

            elif self.original_format in ("json", "yaml"):
                loaded = safe_load(content, self.original_format)
                if isinstance(loaded, dict):
                    self._dict = loaded
                    logger.debug(f"Loaded content into dictionary for format {self.original_format}.")
                    status = True
                    oscal_root = next(iter(self._dict.keys())) if self._dict else ""
                    root_obj = self._dict.get(oscal_root, {})
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
            if oscal_version in self._support.versions:
                self.oscal_version = oscal_version
                if oscal_root in self._support.list_models(self.oscal_version):
                    self.model = oscal_root
                    self.title = content_title
                    self.version = content_version
                    self.published = content_publication
                    logger.debug(f"OSCAL model '{self.model}' and version '{self.oscal_version}' identified.")
                    status = True
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

        if format == "":
            format = self.original_format

        if format not in OSCAL_FORMATS:
            logger.error(f"The validation format specified ({format}) is not an OSCAL format.")
            self.is_valid = False
            return self.is_valid

        if format == "xml":
            logger.debug("Validating XML content against schema...")
            xml_schema_content = self._support.get_asset(self.oscal_version, self.model, "xml-schema")

            if xml_schema_content:
                import xmlschema
                try:
                    # Create schema object from string
                    schema = xmlschema.XMLSchema(xml_schema_content)

                    # Validate - returns None if valid, raises exception if invalid
                    xml_string = self._xml_serializer()
                    schema.validate(xml_string)
                    self.schema_valid["_tree"] = True
                    self.is_valid = True
                    logger.debug("XML schema validation passed.")

                except xmlschema.XMLSchemaValidationError as e:
                    logger.error(f"XML schema validation failed: {e.reason}")
                    self.schema_valid["_tree"] = False
                    self.is_valid = False
                except Exception as e:
                    logger.error(f"XML schema validation error: {str(e)}")
                    self.schema_valid["_tree"] = False
                    self.is_valid = False
            else:
                logger.error("Unable to load XML schema for validation.")
                self.schema_valid["_tree"] = False
                self.is_valid = False

        elif format in ("json", "yaml"):
            logger.debug(f"Validating {format} content against schema...")
            json_schema_content = self._support.get_asset(self.oscal_version, self.model, "json-schema")

            if json_schema_content:
                import jsonschema_rs
                try:
                    # Parse schema string to dict if needed
                    if isinstance(json_schema_content, str):
                        schema_dict = json.loads(json_schema_content)
                    else:
                        schema_dict = json_schema_content

                    # Ensure schema_dict is valid before validation
                    if isinstance(schema_dict, dict) and isinstance(self._dict, dict):

                        # Validate (raises exception with details if invalid)
                        jsonschema_rs.validate(schema_dict, self._dict)  # schema first, instance second

                        self.schema_valid["_dict"] = True
                        self.is_valid = True
                        logger.debug("JSON schema validation passed.")
                    else:
                        logger.error("Loaded JSON schema is not a valid dictionary.")
                        self.schema_valid["_dict"] = False
                        self.is_valid = False

                except jsonschema_rs.ValidationError as e:
                    logger.error(f"JSON schema validation failed: {e}")
                    self.schema_valid["_dict"] = False
                    self.is_valid = False
                except Exception as e:
                    logger.error(f"JSON schema validation error: {str(e)}")
                    self.schema_valid["_dict"] = False
                    self.is_valid = False
            else:
                logger.error("Unable to load JSON schema for validation.")
                self.schema_valid["_dict"] = False
                self.is_valid = False

        return self.is_valid

    # -------------------------------------------------------------------------
    def _sync(self, target_format: str = "") -> bool:
        """
        This method syncronizes the _tree and _dict from whichever is primary to 
        whichever is secondary.

        If target_format is specified, this will compare the original and 
        specified formats, and it will only sync if necessary to ensure 
        the target_format is in sync with the source format.
        """
        logger.debug("Syncing content if necessary...")
        status = False
        if not self.is_synced:
            # If the target format doesn't make sennse, log an error and return False
            if target_format and target_format not in OSCAL_FORMATS:
                logger.error(f"Target format specified for sync is not an OSCAL format: {target_format}")
                return False
            
            if target_format == "xml" and self.original_format == "xml":
                logger.debug("Target format is XML and original format is XML; no sync needed.")
                status = True
            
            if target_format in ("json", "yaml") and self.original_format in ("json", "yaml"):
                logger.debug(f"Target format is {target_format.upper()} and original format is {self.original_format.upper()}; no sync needed.")
                status = True
            
            if self.original_format == "xml":
                if self._tree is not None:
                    logger.debug("Converting XML tree to dictionary for JSON/YAML representation...")
                    xsl_converter=self._support.get_asset(self.oscal_version, self.model, "xml-to-json")
                    if not xsl_converter:
                        logger.error("Unable to locate XSLT converter for XML to JSON conversion. Cannot convert to dict.")
                        return False
                    xml_string = self._xml_serializer()
                    json_string = oscal_xml_to_json(xml_string, xsl_converter=xsl_converter)
                    self._dict = json.loads(json_string)
                    self.is_synced = True
                    logger.debug("Conversion from XML to dict successful.")
                    status= True
                else:
                    logger.error("No XML tree available to convert to dict.")
            elif self.original_format in ("json", "yaml"):
                if self._dict is not None:
                    logger.debug("Converting dictionary to XML tree for XML representation...")
                    xsl_converter=self._support.get_asset(self.oscal_version, self.model, "json-to-xml")
                    if not xsl_converter:
                        logger.error("Unable to locate XSLT converter for JSON to XML conversion. Cannot convert to XML tree.")
                        return False
                    json_string = json.dumps(self._dict)
                    xml_string = oscal_json_to_xml(json_string, xsl_converter=xsl_converter, validate_json=True)
                    self._tree = ElementTree.ElementTree(ElementTree.fromstring(xml_string))
                    self.is_synced = True
                    logger.debug("Conversion from dict to XML successful.")
                    status = True
                else:
                    logger.error("No dictionary available to convert to XML tree.")
            else:
                logger.error(f"Unsupported original format for conversion: {self.original_format}")
        else:
            logger.debug("Content is already synced; no conversion needed.")
            status = True
    
        return status
    # -------------------------------------------------------------------------
    @property
    def xml(self) -> str:
        """Return the content as an XML string, converting if necessary."""

        if self.original_format in ("json", "yaml"):
            if not self.is_synced:
                if not self._sync():
                    logger.error("Failed to sync content for XML serialization.")
                    return ""
        elif self.original_format != "xml":
            logger.error(f"Unsupported original format for XML serialization: {self.original_format}")
            return ""

        return self._xml_serializer()

    # -------------------------------------------------------------------------
    @property
    def json(self) -> str:
        """Return the content as a JSON string, converting if necessary."""

        if self.original_format == "xml":
            if not self.is_synced:
                if not self._sync():
                    logger.error("Failed to sync content for JSON serialization.")
                    return ""
        elif self.original_format not in ("json", "yaml"):
            logger.error(f"Unsupported original format for JSON serialization: {self.original_format}")
            return ""

        return json.dumps(self._dict, indent=INDENT)

    # -------------------------------------------------------------------------
    @property
    def yaml(self) -> str:
        """Return the content as a YAML string, converting if necessary."""

        if self.original_format == "xml":
            if not self.is_synced:
                if not self._sync():
                    logger.error("Failed to sync content for YAML serialization.")
                    return ""
        elif self.original_format not in ("json", "yaml"):
            logger.error(f"Unsupported original format for YAML serialization: {self.original_format}")
            return ""

        return yaml.dump(self._dict, sort_keys=False, indent=INDENT)

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
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
                if self._tree is not None:
                    self.__set_field(f"/*/metadata/{item}", content.get(item, ""))
                elif self._dict is not None:
                    if "metadata" not in self._dict:
                        self._dict["metadata"] = {}
                        logger.warning("No metadata section found in content. Creating.")
                    self._dict["metadata"][item] = content.get(item, "")                

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
            context = self._tree
            logger.debug(f"Using document root as context for XPath Atomic: {xExpr}")

        if context is None:
            logger.error("No XML context available for XPath Atomic query.")
            return ""

        results = elementpath.select(context, xExpr, namespaces=_NSMAP)
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
            context = self._tree
            logger.debug(f"Using document root as context for XPath: {xExpr}")

        if context is None:
            logger.error("No XML context available for XPath query.")
            return None
        try:
            result = elementpath.select(context, xExpr, namespaces=_NSMAP)
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
    @requires(is_read_only=False)
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
    @requires(is_read_only=False)
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
    @requires(is_read_only=False)
    @if_update_successful
    def append_child(self, xpath: str, node_name: str, node_content: str = "", attribute_list: list = []) -> (ElementTree.Element | None):
        # logger.debug("APPENDING " + node_name + " as child to " + xpath) #  + " in " + self._tree.tag)
        status = False
        child = None
        try:
            logger.debug("Fetching parent at " + xpath)
            # Use elementpath for reliable XPath processing
            parent_nodes = elementpath.select(self._tree, xpath, namespaces=_NSMAP)
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
    @requires(is_read_only=False)
    @if_update_successful
    def append_resource(self, uuid: str = "", title: str = "", description: str = "", props: list = [], rlinks: list = [], base64: str = "", remarks: str = "") -> ElementTree.Element:
        """
        Appends a resource element to the back-matter section.
        """
        return append_resource(self, uuid, title, description, props, rlinks, base64, remarks)

    # -------------------------------------------------------------------------
    def import_tree(self, _seen=None):
        """Return a JSON-serializable nested dict of this object and all imports."""
        if _seen is None:
            _seen = set()
        _seen.add(id(self))

        node = {
            "model":         self.model,
            "title":         self.title,
            "published":     self.published,
            "version":       self.version,
            "last_modified": self.last_modified,
            "oscal_version": self.oscal_version,
            "remarks":       self.remarks,
            "imports":       []
        }

        for entry in self.import_list:
            child_obj = entry["object"]
            child_node = {
                "href_original": entry.get("href_original"),
                "href_valid":    entry.get("href_valid"),
                "status":        str(entry.get("status")),
                "valid":         entry.get("valid"),
                "is_valid":      entry.get("is_valid", entry.get("valid")),
                "local":         entry.get("local"),
                "is_local":      entry.get("is_local", entry.get("local")),
                "remote":        entry.get("remote"),
                "is_remote":     entry.get("is_remote", entry.get("remote")),
                "cached":        entry.get("cached"),
                "is_cached":     entry.get("is_cached", entry.get("cached")),
            }
            if child_obj is not None and id(child_obj) not in _seen:
                child_node.update(child_obj.import_tree(_seen))
            else:
                child_node["model"]    = child_obj.model if child_obj else None
                child_node["title"]    = child_obj.title if child_obj else None
                child_node["circular"] = child_obj is not None
                child_node["imports"]  = []

            node["imports"].append(child_node)

        self.import_tree = node
        return node

    # -------------------------------------------------------------------------
    def walk_imports(self, visitor_fn, depth=0, _seen=None):
        """
        Walks the import tree, applying the visitor function to each entry.
        This is a depth-first traversal that tracks seen objects to avoid infinite loops."""
        if _seen is None:
            _seen = set()
        for entry in self.import_list:
            obj = entry["object"]
            if obj is None:
                continue
            obj_id = id(obj)
            if obj_id in _seen:
                continue
            _seen.add(obj_id)
            visitor_fn(entry, depth)
            obj.walk_imports(visitor_fn, depth + 1, _seen)

    # -------------------------------------------------------------------------
    def find_by_uuid(self, uuid, _seen=None):
        """
        Method to search the import tree for an object with a matching UUID. 
        This is a depth-first search that tracks seen objects to avoid infinite loops.
        """
        if _seen is None:
            _seen = set()
        for entry in self.import_list:
            obj = entry["object"]
            if obj is None:
                continue
            obj_id = id(obj)
            if obj_id in _seen:
                continue
            _seen.add(obj_id)
            result = obj.find_by_uuid(uuid, _seen)
            if result:
                return result
        return None


    # -------------------------------------------------------------------------
    def dumps(self, format: str = "", pretty_print: bool = False) -> str:
        """
        Serialize the current content to a string in the specified format.
        Parameters:
        - format (str): The target format for serialization ("xml", "json", or "yaml")
            Defaults to the original format of the content if not specified.
        - pretty_print (bool): Whether to pretty-print the output. Defaults to False.

        Returns:
        - str: The serialized content as a string.
        """
        if format == "":
            format = self.original_format

        format = format.lower()
        if format not in OSCAL_FORMATS:
            logger.error(f"The requested format for serialization ({format}) is not an OSCAL format.")
            return ""

        if format == "xml":
            if not self._sync(target_format="xml"):
                logger.error("Failed to sync content for XML serialization.")
                return ""
            return self._xml_serializer(pretty_print=pretty_print)
        elif format == "json":
            if not self._sync(target_format="json"):
                logger.error("Failed to sync content for JSON serialization.")
                return ""
            return self._json_serializer(pretty_print=pretty_print)
        elif format in ("yaml", "yml"):
            if not self._sync(target_format="yaml"):
                logger.error("Failed to sync content for YAML serialization.")
                return ""
            return self._yaml_serializer(pretty_print=pretty_print)
        else:
            logger.error(f"Unsupported format for serialization: {format}")
            return ""

    # -------------------------------------------------------------------------
    def _xml_serializer(self, pretty_print: bool = False) -> str:
        """
        Serializes the current XML tree to a string.
        Parameters:
        - pretty_print (bool): Whether to pretty-print the output. Defaults to False.
        Returns:
        - str: The serialized XML content as a string.
        """
        logger.debug("Serializing the XML tree for text output.")

        # Check if tree exists
        if self._tree is None:
            logger.error("No XML tree available for serialization")
            return ""

        # Handle both ElementTree and Element objects
        if isinstance(self._tree, ElementTree.ElementTree):
            root = self._tree.getroot()
        else:
            root = self._tree  # Already an Element

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
    def _json_serializer(self, pretty_print: bool = False) -> str:
        """
        Serializes the current dict to a string.
        Parameters:
        - pretty_print (bool): Whether to pretty-print the output. Defaults to False.
        Returns:
        - str: The serialized JSON content as a string.
        """
        logger.debug("Serializing dict for string output as JSON.")
        out_string = json.dumps(self._dict, indent=INDENT if pretty_print else None, sort_keys=False)
        logger.debug("LEN: " + str(len(out_string)))

        return out_string

    # -------------------------------------------------------------------------
    def _yaml_serializer(self, pretty_print: bool = False) -> str:
        """
        Serializes the current dict to a string.
        Parameters:
        - pretty_print (bool): Whether to pretty-print the output. Defaults to False.
        Returns:
        - str: The serialized YAML content as a string.
        """
        logger.debug("Serializing dict for string output as YAML.")
        out_string: str = yaml.dump(self._dict, indent=INDENT if pretty_print else None, sort_keys=False)  # type: ignore[assignment]
        logger.debug("LEN: " + str(len(out_string)))

        return out_string

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Data Classes
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class ImportState(str, Enum):
    READY        = "ready"        # The content is valid
    NOT_LOADED   = "not-loaded"   # The content has not been loaded
    INVALID      = "invalid"      # The content is not valid
    EXPIRED      = "expired"      # The content is valid, but cached copy has expired

# -------------------------------------------------------------------------
@dataclass
class OscalRef:
    """A single resolved reference: an href with an optional media type."""
    href: str
    media_type: str | None = None
    hashes: list[dict] | None = None        # promoted from _extra
    source_type: str = field(default="unknown", init=False, repr=False, compare=False)
    source_scheme: str = field(default="", init=False, repr=False, compare=False)
    source_supported: bool = field(default=False, init=False, repr=False, compare=False)
    _extra: dict = field(default_factory=dict, repr=False, compare=False)

    def __repr__(self) -> str:
        if self.media_type:
            return f"OscalRef({self.href!r}, {self.media_type!r})"
        return f"OscalRef({self.href!r})"

        # {"href": "<original_href>", "media-type": "<media_type>", "valid": True/False, "error": "<error_message_if_invalid>"}

# -------------------------------------------------------------------------
def _normalize_refs(source: str | dict | OscalRef | list) -> list[OscalRef]:
    if isinstance(source, str):
        return [OscalRef(href=source)]
    if isinstance(source, OscalRef):
        return [source]
    if isinstance(source, dict):
        href = source.get("href")
        if not href:
            raise ValueError(f"ref dict missing required 'href' key: {source!r}")
        known = {"href", "media-type", "hashes"}
        return [OscalRef(
            href=href,
            media_type=source.get("media-type"),
            hashes=source.get("hashes"),
            _extra={k: v for k, v in source.items() if k not in known}
        )]
    if isinstance(source, list):
        return [_normalize_refs(item)[0] for item in source]
    raise TypeError(
        f"acquire() expected str, dict, OscalRef, or list — got {type(source).__name__}"
    )

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Functions
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def load_content(source: str | dict | OscalRef | list, media_type: str = "", only_oscal: bool = False) -> str:
    """Load content from one or more sources and return the first successful payload."""
    logger.debug("Loading content from source")
    refs = _normalize_refs(source)

    for ref in refs:
        classify_source(ref, only_oscal=only_oscal)

    # Try each ref in order and return the first successfully loaded content.
    for ref in refs:
        if not ref.source_supported:
            logger.warning(f"Skipping unsupported source: {ref.href} "
                           f"(type={ref.source_type}, scheme={ref.source_scheme})")
            continue

        content = load_source(ref)
        if content:
            return content

        logger.warning(f"Failed to load content from source: {ref.href}")

    logger.error("No usable content could be loaded from provided sources")
    return ""

def load_source(ref: OscalRef) -> str:
    """Fetch or read content from a classified OscalRef.

    Returns the raw file content as a string, or empty string on failure.
    """
    src = ref.href.strip()
    content = ""

    try:
        if ref.source_type == "uri" and ref.source_scheme == "file":
            # file:// URI → convert to local path
            parsed = urlparse(src)
            local_path = parsed.path
            if parsed.netloc:
                # file://server/share/path -> //server/share/path
                local_path = f"//{parsed.netloc}{parsed.path}"
            logger.info(f"Loading controls from file:// URI: {local_path}")
            content = getfile(local_path)
        elif ref.source_type == "uri" and ref.source_scheme in {"http", "https"}:
            logger.info(f"Loading controls from URL: {src}")
            content = download_file(src, "oscal_remote_content")
        elif ref.source_type == "uri" and ref.source_scheme in {"ftp", "data"}:
            # Keep this stdlib-only for simple, unauthenticated URI access.
            logger.info(f"Loading controls from URI via urllib: {src}")
            with urlopen(src) as response:  # nosec B310 - intentional unauthenticated read
                payload = response.read()
            content = payload.decode("utf-8", errors="replace")
        elif ref.source_type == "file":
            logger.info(f"Loading controls from file: {src}")
            content = getfile(src)
        else:
            logger.warning(f"No loader implemented for source: {src} "
                            f"(type={ref.source_type}, scheme={ref.source_scheme})")
            return ""
    except Exception as e:
        logger.error(f"Failed to load source '{src}': {e}")
        return ""

    if not content:
        logger.error(f"Source returned no content: {src}")
        return ""

    return content

# -------------------------------------------------------------------------
def load_uri(cls, uri: str, media_type: str = "") -> dict:
    """Load content from a URI.
        
    Args:
        uri: URI or list of URIs identifying content to load.
    """


# -------------------------------------------------------------------------
def classify_source(ref: OscalRef, only_oscal: bool = False) -> bool:
    """
    Classify a source reference by path/URI type and Python stdlib accessibility.

    This classification intentionally does not use file extensions because many
    valid content endpoints (for example APIs) do not have predictable suffixes.

    ref: The OscalRef object containing the URI to classify. 
        This function will set the source_type, source_scheme, and 
        source_supported fields on the ref object based on the classification.

    only_oscal: Reserved for future content-shape validation. It currently does
        not change source classification behavior.
    """
    uri = ref.href.strip()

    if not uri:
        ref.source_type = "unknown"
        ref.source_scheme = ""
        ref.source_supported = False
        logger.warning("Empty source href cannot be classified")
        return False

    # --- Windows UNC path (\\server\share\...) ---
    if uri.startswith("\\\\"): # Note: Windows UNC paths start with double backslashes (these are escaped in Python strings, so we check for "\\\\")
        ref.source_type = "file"
        ref.source_scheme = ""
        ref.source_supported = True
        return True

    # --- UNC-like file path written with forward slashes (//server/share/...) ---
    if uri.startswith("//"):
        ref.source_type = "file"
        ref.source_scheme = ""
        ref.source_supported = True
        return True

    # --- Try parsing as a URI ---
    parsed = urlparse(uri)

    if parsed.scheme and len(parsed.scheme) > 1:
        # Has a multi-char scheme → treat as URI
        # (single-char "scheme" is likely a Windows drive letter, e.g. C:)
        ref.source_type = "uri"
        ref.source_scheme = parsed.scheme.lower()

        if ref.source_scheme in _SIMPLE_URI_SCHEMES:
            ref.source_supported = True
        elif ref.source_scheme in _KNOWN_URI_SCHEMES:
            ref.source_supported = False
            logger.warning(f"URI scheme '{ref.source_scheme}' is recognised "
                            f"but not yet supported: {uri}")
        else:
            ref.source_supported = False
            logger.warning(f"Unknown URI scheme '{ref.source_scheme}': {uri}")
        return True

    # --- Local / network file path (POSIX, Windows drive-letter, relative) ---
    ref.source_type = "file"
    ref.source_scheme = ""
    ref.source_supported = True

    return True

# -------------------------------------------------------------------------
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
        if oscal_obj._tree is not None:
            if isinstance(oscal_obj._tree, ElementTree.ElementTree):
                root_node = oscal_obj._tree.getroot()
            else:
                root_node = oscal_obj._tree

            if root_node is not None:
                root_node.append(back_matter)

    back_matter.append(resource)

    return resource

# -----------------------------------------------------------------------------
def create_new_oscal_content(model_name: str, title: str, version: str = "", published: str = "", format: str = "xml" ) -> Optional[OSCAL]:
    """
    Returns minimally valid OSCAL content as the
    appropriate model-specific subclass (e.g., Catalog, Profile, SSP).
    Currently this is based on loading a template file from package data.
    In the future, this should be generated based on the latest metaschema definition.

    Args:
        model_name (str): The OSCAL model name (e.g., "catalog", "system-security-plan").
        title (str): The title for the new OSCAL content.
        version (str): Optional content version.
        published (str): Optional publication date.
        format (str): The desired format for the new content ("xml", "json", "yaml"). Defaults to "xml".

    Returns:
        Optional[OSCAL]: The appropriate OSCAL subclass instance, or None on failure.
    """
    oscal_object = None
    support = get_support()

    if support.is_valid_model(model_name):
        content = support.load_file(f"{model_name}.xml", as_bytes=False)
        if content and isinstance(content, str):
            return content
        else:
            logger.error(f"Failed to load content for model: {model_name}")
            return ""
    else:
        logger.error(f"Unsupported OSCAL model for new content: {model_name}")

    return ""

# -----------------------------------------------------------------------------
def new_uuid() -> str:
    return str(uuid.uuid4())

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':
    print("OSCAL Class Module. This is not intended to be run as a stand-alone module.")

