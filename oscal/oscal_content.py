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
from typing             import Optional, Any, Protocol, runtime_checkable
from datetime           import datetime, timezone
from functools          import wraps
from enum               import Enum, IntEnum
from urllib.parse       import urlparse, urljoin
from urllib.request     import urlopen
from urllib.error       import HTTPError, URLError
from xml.etree          import ElementTree
from dataclasses        import dataclass, field

from ruf_common.logging import LoggableMixin
from ruf_common.network import download_file
from ruf_common.data    import detect_data_format, safe_load, safe_load_xml
from ruf_common.lfs     import getfile, chkdir, putfile, normalize_content
from .oscal_support     import get_support, OSCAL_DEFAULT_XML_NAMESPACE, OSCAL_FORMATS
from .oscal_datatypes   import oscal_date_time_with_timezone
from .oscal_converters  import oscal_xml_to_json, oscal_json_to_xml, oscal_markdown_to_html

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Constants
INDENT = 2 # Number of spaces to use for indentation in pretty-printed output
# URI schemes we recognise but cannot fetch yet
_KNOWN_URI_SCHEMES = {"ftp", "ftps", "sftp", "s3", "gs", "az"}
# URI schemes we can handle with Python stdlib tooling (no third-party SDKs)
_SIMPLE_URI_SCHEMES = {"http", "https", "file", "ftp", "data"}
# OSCAL Default Namespace for XML processing
_NSMAP = {"": OSCAL_DEFAULT_XML_NAMESPACE} # XML namespace map

# Maps each OSCAL model to the XPath locations and attribute names that carry
# references to other OSCAL documents.  Tuple: (element_xpath, attribute_name).
_IMPORT_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "profile": [
        ("/*/import",                                    "href"),
    ],
    "component-definition": [
        ("/*/import-component-definition",               "href"),
        ("/*/component/control-implementation",          "source"),
        ("/*/capability/control-implementation",         "source"),
    ],
    "system-security-plan": [
        ("/*/import-profile",                            "href"),
    ],
    "assessment-plan": [
        ("/*/import-ssp",                                "href"),
    ],
    "plan-of-action-and-milestones": [
        ("/*/import-ssp",                                "href"),
    ],
    "assessment-results": [
        ("/*/import-assessment-plan",                    "href"),
    ],
    "mapping-collection": [
        ("/*/mapping/source",                            "href"),
        ("/*/mapping/target",                            "href"),
    ],
}

# JSON/YAML import patterns.  Each spec is a dict with:
#   path   : key in the model root object that holds the collection
#   key    : key within each item that holds the href value
#   single : True when the path is a single object, not a list (e.g. import-profile)
#   each   : intermediate collection key for two-level nesting (cDef components)
#   subkey : intermediate object key one level inside each item (mapping source/target)
_IMPORT_PATTERNS_DICT: dict[str, list[dict]] = {
    "profile": [
        {"path": "imports",                          "key": "href"},
    ],
    "component-definition": [
        {"path": "import-component-definitions",     "key": "href"},
        {"path": "components",   "each": "control-implementations", "key": "source"},
        {"path": "capabilities", "each": "control-implementations", "key": "source"},
    ],
    "system-security-plan": [
        {"path": "import-profile",           "key": "href", "single": True},
    ],
    "assessment-plan": [
        {"path": "import-ssp",               "key": "href", "single": True},
    ],
    "plan-of-action-and-milestones": [
        {"path": "import-ssp",               "key": "href", "single": True},
    ],
    "assessment-results": [
        {"path": "import-assessment-plan",   "key": "href", "single": True},
    ],
    "mapping-collection": [
        {"path": "mappings", "subkey": "source-resource", "key": "href"},
        {"path": "mappings", "subkey": "target-resource", "key": "href"},
    ],
}

# Conditional origin states — not progressive; freshness is time-based and computed on demand.
class OriginState(Enum):
    LOCAL           = "local"           # Local file system — always accessible
    REMOTE_UNCACHED = "remote-uncached" # Remote content, no local cache copy
    REMOTE_FRESH    = "remote-fresh"    # Remote content, cached and within TTL
    REMOTE_STALE    = "remote-stale"    # Remote content, cached but TTL exceeded

# Progressive content validation states. Each level implies all prior levels passed.
class ContentState(IntEnum):
    NONE             = -1  # No content / uninitialized
    NOT_AVAILABLE    = 0  # Unable to acquire content
    ACQUIRED         = 1  # Content was acquired (non-empty string)
    WELL_FORMED      = 2  # Content is well-formed XML, JSON, or YAML
    VALID            = 3  # Content passes OSCAL schema validation (minimum for viewing/editing)
    IMPORTS_RESOLVED = 4  # All imported OSCAL documents resolved successfully
    # FUTURE: CORE_METASCHEMA_VALID = 5, ADDITIONAL_METASCHEMA_VALID = 6


@runtime_checkable
class _ReadableSource(Protocol):
    """Protocol for file-like objects that provide read()."""

    def read(self, size: int = -1) -> Any:
        ...

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
def requires_state(min_state: ContentState):
    """Gate a method on a minimum ContentState level."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            if self.content_state < min_state:
                logger.error(
                    f"'{fn.__name__}' requires content_state >= {min_state.name} "
                    f"(current: {self.content_state.name})"
                )
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
        self.is_synced  = False
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
        self.content_state: ContentState = ContentState.NONE  # progressive validation state
        self.is_local    : bool = True  # source is local file (vs http/https)
        self.is_cached   : bool = False # remote content has a local cache copy
        self.is_read_only: bool = True  # local content is read-only (not read-write)
        self.is_unsaved  : bool = True  # True when there are unsaved modifications

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
        self.is_synced   : bool = False # Boolean indicating whether the tree and dict are in sync
        self.import_list: list = []    # Flat list of direct imports (one level)
        self._import_tree: dict | None = None  # Cached recursive import tree (None = not yet built)
        self._dict: dict | None = None # JSON/YAML constructs
        self._tree = None              # XML constructs

        # Validation Status
        self.schema_valid = {}    # A dictionary indicating whether the content is valid against the schema for each format
        self.schema_valid["_tree"]  = None # Will be set to True/False after XML validation, None if not yet validated or not applicable
        self.schema_valid["_dict"] = None # Will be set to True/False after JSON validation, None if not yet validated or not applicable
        self.metaschema_valid = None # A boolean indicating whether the content is valid against the NIST OSCAL Metaschema
        self.errors = {} # A dictionary to hold any acquisition, validation or importing errors encountered during processing

        # Get the OSCAL support object
        self._support = get_support()

        # Call subclass initialization hook (no-op in base; overridden by subclasses)
        self._init_common()

    # -------------------------------------------------------------------------
    def _init_common(self):
        """Subclass initialization hook. Override in model-specific subclasses
        to initialize attributes that are not part of the base OSCAL class.
        Always call super()._init_common() at the start of the override.
        """

    # =========================================================================
    # Content state properties (progressive — each implies all prior levels passed)
    @property
    def is_acquired(self) -> bool:
        return self.content_state >= ContentState.ACQUIRED

    # -------------------------------------------------------------------------
    @property
    def is_well_formed(self) -> bool:
        return self.content_state >= ContentState.WELL_FORMED

    # -------------------------------------------------------------------------
    @property
    def is_valid(self) -> bool:
        return self.content_state >= ContentState.VALID

    # -------------------------------------------------------------------------
    @property
    def imports_resolved(self) -> bool:
        return self.content_state >= ContentState.IMPORTS_RESOLVED

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
    def load(cls, source: str | os.PathLike | _ReadableSource, *, href: str | None = None):
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

        if isinstance(source, _ReadableSource):
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

        instance.href_original = instance._refs[0].href if instance._refs else ""
        content = load_content(instance._refs)
        instance.initial_validation(content)
        return instance

    # -------------------------------------------------------------------------
    @classmethod
    def from_string(cls, content: str, *, href: str | None = None):
        """Explicit constructor for in-memory OSCAL string content."""
        return cls.loads(content, href=href)

    # # -------------------------------------------------------------------------
    # @classmethod
    # def from_dict(cls, content: dict, *, href: str | None = None):
    #     """Explicit constructor for in-memory OSCAL dictionary content."""
    #     return cls.loads(content, href=href)

    # -------------------------------------------------------------------------
    @classmethod
    def open(cls, source: str | os.PathLike | dict | OscalRef | list | _ReadableSource,
             *, href: str | None = None):
        """Universal constructor — inspects the source type and delegates to
        the appropriate loader.

        Delegates to:
            load()    — file-like objects (anything with .read()), PathLike
                        objects, and bare string paths (no URI scheme)
            acquire() — URI strings (http/https/file/ftp/...), OscalRef,
                        reference dicts, and fallback lists

        Args:
            source: Any supported OSCAL source.
            href:   Optional URI label passed through to load() when applicable.
        """
        if isinstance(source, _ReadableSource) or isinstance(source, os.PathLike):
            return cls.load(source, href=href)
        if isinstance(source, str):
            parsed = urlparse(source)
            if parsed.scheme and len(parsed.scheme) > 1:
                return cls.acquire(source)
            return cls.load(source, href=href)
        # OscalRef, dict with href, or list — all handled by acquire
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
        model    = cls.__name__.lower()
        instance = create_new_oscal_content(model, title, version, published)
        if instance is None:
            instance = cls.__new__(cls)
            instance.__init_common__()
            instance._origin = "new"
            instance.model   = model
            return instance
        instance.__class__ = cls
        instance._init_common()
        instance._origin      = "new"
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
        """A concise string representation showing key metadata and validation status."""
        ret_value = ""
        if self.original_format == "xml":
            ret_value += "✅" if self.schema_valid.get("_tree") else "⚠️"
        elif self.original_format in ("json", "yaml"):
            ret_value += "✅" if self.schema_valid.get("_dict") else "⚠️"

        ret_value += f" OSCAL[{self.model}:{self.oscal_version} {self.original_format.upper()}] {self.title})"

        return ret_value

    # -------------------------------------------------------------------------
    def __bool__(self) -> bool:
        """Return True if the content is valid, False otherwise."""
        return self.content_state >= ContentState.VALID

    # -------------------------------------------------------------------------
    def __str__(self):
        """A more detailed string representation showing key metadata and validation status."""
        ret_value = ""
        ret_value += "✅" if self.content_state >= ContentState.VALID else "⚠️"
        ret_value += f" {self.model}:" if self.model else ""
        ret_value += f" {self.title}" if self.title else " [Untitled]"
        ret_value += f" | Version: {self.version}" if self.version else ""
        ret_value += f" | Published: {self.published}" if self.published else ""
        ret_value += f"\nSource File: {self.href_original}" if self.href_original else ""
        if self.content_state < ContentState.VALID:
            next_val = self.content_state.value + 1
            if next_val in ContentState._value2member_map_:
                ret_value += f"\nFailed at: {ContentState(next_val).name}"
        if self.content_state >= ContentState.IMPORTS_RESOLVED:
            ret_value += f"\nImports Resolved: {len(self.import_list)} import(s) found."
            for child in self.import_list:
                if child.get("status") == "failed":
                    ret_value += f"\n    → Error: {child.get('error', 'Unknown error')}"
                else:
                    ret_value += f"\n    → {child.get('object', '')}"

        return ret_value

    # -------------------------------------------------------------------------
    def _build_import_tree(self, new_href: str = "") -> bool:
        """
        Internal method to build a recursive import tree.

        The resulting cached tree is rooted at this OSCAL object and contains
        one child node per imported OSCAL document, recursively.
        """
        root_href = (new_href or self.href or self.href_original).strip()
        if new_href:
            self.href = root_href

        def _node_for(doc: "OSCAL", seen: set[str]) -> dict:
            node_href = (doc.href or doc.href_original).strip()
            node = {
                "href_original": doc.href_original,
                "href_valid":    node_href,
                "status":        ImportState.READY if doc.is_valid else ImportState.INVALID,
                "is_valid":      doc.is_valid,
                "is_local":      doc.is_local,
                "is_remote":     doc.is_remote,
                "is_cached":     doc.is_cached,
                "object":        doc,
                "children":      [],
            }

            # Keep backward compatibility with existing consumers that expect
            # an 'imports' key for child nodes.
            node["imports"] = node["children"]

            node_key = node_href or doc.href_original
            if node_key and node_key in seen:
                logger.warning(f"import_tree: circular reference detected at '{node_key}' — stopping recursion.")
                return node

            next_seen = seen | ({node_key} if node_key else set())
            doc.resolve_imports()

            for entry in doc.import_list:
                child_obj: OSCAL | None = entry.get("object")
                if child_obj is None:
                    continue
                child_node = _node_for(child_obj, next_seen)
                node["children"].append(child_node)

            return node

        if not root_href and not self.href_original:
            logger.warning("_build_import_tree called without an available href.")

        self._import_tree = _node_for(self, set())
        return True

    # -------------------------------------------------------------------------
    @property
    def unresolved_imports(self) -> dict:
        """Return the subset of import_tree entries with FAILED status."""
        return {href: details for href, details in self.import_tree.items() if details.get('status') == 'failed'}

    # -------------------------------------------------------------------------
    @property
    def failed_imports(self) -> list[dict]:
        """Return import_list entries that failed, each carrying a populated 'failure' field."""
        return [e for e in self.import_list if e.get("failure") is not None]

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
    def resolve_imports(self, base_path: str = "") -> list:
        """
        Discover and load every OSCAL document referenced by this document's
        import declarations.  Populates (and returns) self.import_list.

        Recognised import locations by model:
            profile                    → import/@href
            component-definition       → import-component-definition/@href,
                                         component/control-implementation/@source,
                                         capability/control-implementation/@source
            system-security-plan       → import-profile/@href
            assessment-plan            → import-ssp/@href
            plan-of-action-and-milestones → import-ssp/@href
            assessment-results         → import-assessment-plan/@href
            mapping-collection         → mapping/source/@href,
                                         mapping/target/@href

        Args:
            base_path: Directory used to resolve relative hrefs.  Defaults to
                       the directory of this document's own href.

        Returns:
            list[dict]: self.import_list, one entry per discovered reference.
        """
        self.import_list = []
        self._import_tree = None  # invalidate cached tree whenever imports are re-resolved

        # --- resolve base directory for relative hrefs ---
        if not base_path:
            src = self.href or self.href_original
            if src:
                parsed_src = urlparse(src)
                if parsed_src.scheme and len(parsed_src.scheme) > 1:
                    # Real URL (not a Windows drive letter like 'C')
                    base_path = src.rsplit("/", 1)[0] + "/"
                else:
                    base_path = os.path.dirname(os.path.abspath(src))
            else:
                base_path = os.getcwd()

        # --- collect raw hrefs from whichever representation is primary ---
        raw_hrefs: list[str] = []

        if self._tree is not None:
            xml_patterns = _IMPORT_PATTERNS.get(self.model, [])
            if not xml_patterns:
                logger.debug(f"resolve_imports: no XML patterns defined for model '{self.model}'.")
            for element_xpath, attr_name in xml_patterns:
                nodes = self.xpath(element_xpath)
                if not nodes:
                    continue
                for node in nodes:
                    href = node.get(attr_name, "").strip()
                    if href:
                        raw_hrefs.append(href)

        elif self._dict is not None:
            dict_patterns = _IMPORT_PATTERNS_DICT.get(self.model, [])
            if not dict_patterns:
                logger.debug(f"resolve_imports: no dict patterns defined for model '{self.model}'.")
            root_obj = self._dict.get(self.model, {})
            for spec in dict_patterns:
                raw_hrefs.extend(_hrefs_from_dict_spec(root_obj, spec))

        else:
            logger.warning("resolve_imports: no content representation available.")
            return self.import_list

        if not raw_hrefs:
            logger.debug(f"resolve_imports: no import references found in '{self.model}'.")
            if self.content_state >= ContentState.VALID:
                self.content_state = ContentState.IMPORTS_RESOLVED
            return self.import_list

        # --- load each referenced document (shared for both branches) ---
        for raw_href in raw_hrefs:
            entry: dict = {
                "href_original": raw_href,
                "href_valid":    "",
                "status":        ImportState.NOT_LOADED,
                "is_valid":      False,
                "is_local":      None,
                "is_remote":     None,
                "is_cached":     False,
                "object":        None,
                "failure":       None,  # ImportFailure instance when status is INVALID
            }

            # --- Fragment ref: resolve through back-matter ---
            if raw_href.startswith("#"):
                fragment = raw_href[1:]

                if not _is_valid_uuid(fragment):
                    entry["status"]  = ImportState.INVALID
                    entry["failure"] = ImportFailure(
                        code=ImportFailureCode.FRAGMENT_INVALID_UUID,
                        href_original=raw_href,
                        message=f"Fragment '{fragment}' is not a valid UUID",
                    )
                    logger.error(f"resolve_imports: fragment '{raw_href}' is not a valid UUID.")
                    self.import_list.append(entry)
                    continue

                resource_info = _backmatter_resource(self, fragment)

                if resource_info is None:
                    entry["status"]  = ImportState.INVALID
                    entry["failure"] = ImportFailure(
                        code=ImportFailureCode.RESOURCE_NOT_FOUND,
                        href_original=raw_href,
                        resource_uuid=fragment,
                        message=f"No back-matter resource found with UUID '{fragment}'",
                    )
                    logger.error(f"resolve_imports: no back-matter resource with UUID '{fragment}'.")
                    self.import_list.append(entry)
                    continue

                if not resource_info["rlinks"] and not resource_info["has_base64"]:
                    entry["status"]  = ImportState.INVALID
                    entry["failure"] = ImportFailure(
                        code=ImportFailureCode.RESOURCE_NO_VIABLE_CONTENT,
                        href_original=raw_href,
                        resource_uuid=fragment,
                        resource_title=resource_info.get("title", ""),
                        resource_description=resource_info.get("description", ""),
                        message=f"Back-matter resource '{fragment}' has no rlinks or base64 content",
                    )
                    logger.error(f"resolve_imports: resource '{fragment}' has no viable content.")
                    self.import_list.append(entry)
                    continue

                # Build candidates from rlinks in order; base64 fallback is future work
                candidates = []
                for rl in resource_info["rlinks"]:
                    candidates.append(rl)
                    candidates.extend(_oscal_format_variants(rl))

                # Stash resource metadata so the failure record can carry it
                entry["resource_uuid"]        = fragment
                entry["resource_title"]       = resource_info.get("title", "")
                entry["resource_description"] = resource_info.get("description", "")

            else:
                candidates = [_resolve_href(base_path, raw_href)]

            # --- Try each candidate in order; use the first that yields valid OSCAL ---
            rlinks_tried: list[str] = []
            last_load_error: ImportLoadError | None = None

            for candidate in candidates:
                resolved = _resolve_href(base_path, candidate)
                rlinks_tried.append(resolved)
                try:
                    child = OSCAL.acquire(resolved)
                    if child.is_valid:
                        entry["href_valid"] = resolved
                        entry["object"]     = child
                        entry["is_valid"]   = True
                        entry["is_local"]   = child.is_local
                        entry["is_remote"]  = child.is_remote
                        entry["is_cached"]  = child.is_cached
                        entry["status"]     = ImportState.READY
                        last_load_error     = None
                        break
                    logger.warning(f"resolve_imports: '{resolved}' loaded but failed OSCAL validation.")
                except ImportLoadError as exc:
                    last_load_error = exc
                    logger.warning(f"resolve_imports: load error for '{resolved}': {exc}")
                    # Auth/unsupported errors won't improve by trying format variants
                    if exc.code in (ImportFailureCode.REMOTE_AUTH_REQUIRED,
                                    ImportFailureCode.REMOTE_UNSUPPORTED):
                        break
                except Exception as exc:
                    logger.warning(f"resolve_imports: could not load '{resolved}': {exc}")

            if entry["status"] != ImportState.READY:
                entry["status"] = ImportState.INVALID
                failure_code = last_load_error.code if last_load_error else ImportFailureCode.CONTENT_INVALID
                failure_uri  = last_load_error.uri  if last_load_error else (rlinks_tried[-1] if rlinks_tried else "")
                failure_msg  = str(last_load_error) if last_load_error else "All candidates failed OSCAL validation"

                if raw_href.startswith("#"):
                    entry["failure"] = ImportFailure(
                        code=failure_code,
                        href_original=raw_href,
                        resource_uuid=entry.get("resource_uuid", ""),
                        resource_title=entry.get("resource_title", ""),
                        resource_description=entry.get("resource_description", ""),
                        rlinks_tried=rlinks_tried,
                        uri=failure_uri,
                        message=failure_msg,
                    )
                else:
                    entry["failure"] = ImportFailure(
                        code=failure_code,
                        href_original=raw_href,
                        uri=failure_uri,
                        message=failure_msg,
                    )

                logger.error(
                    f"resolve_imports: all candidates for '{raw_href}' failed. "
                    f"Tried: {rlinks_tried}"
                )

            self.import_list.append(entry)

        logger.info(
            f"resolve_imports: {len(self.import_list)} reference(s) found in '{self.model}'."
        )

        failed = sum(1 for e in self.import_list if e["status"] == ImportState.INVALID)
        if self.content_state >= ContentState.VALID and failed == 0:
            self.content_state = ContentState.IMPORTS_RESOLVED

        return self.import_list

    # -------------------------------------------------------------------------
    def _build_import_tree_recursive(self, _path: frozenset | None = None) -> list:
        """Walk import_list recursively and return a nested tree of import entries.

        Each entry is a copy of the flat import_list dict with an added 'imports'
        key containing the same structure for that child's own imports.
        Path-based cycle detection prevents infinite recursion on circular refs.
        """
        if _path is None:
            _path = frozenset()

        result = []
        for entry in self.import_list:
            node = {k: v for k, v in entry.items()}
            child: OSCAL | None = entry.get("object")
            child_href: str = entry.get("href_valid") or entry.get("href_original", "")

            if child is not None and child_href and child_href not in _path:
                node["imports"] = child._build_import_tree_recursive(_path | {child_href})
            else:
                if child_href in _path:
                    logger.warning(f"import_tree: circular reference detected at '{child_href}' — stopping recursion.")
                node["imports"] = []

            result.append(node)
        return result

    # -------------------------------------------------------------------------
    @property
    def import_tree(self) -> dict:
        """Recursive import tree built lazily on first access and cached.

        Returns a root node dict representing this document, with an 'imports'
        key holding the first-level imports (each following the same structure
        recursively).  The root node fields mirror those of an import_list entry.
        Use rebuild_import_tree() to force a fresh traversal.
        """
        if self._import_tree is None:
            self._import_tree = {
                "href_original": self.href_original,
                "href_valid":    self.href_original,
                "status":        ImportState.READY if self.is_valid else ImportState.INVALID,
                "is_valid":      self.is_valid,
                "is_local":      self.is_local,
                "is_remote":     self.is_remote,
                "is_cached":     self.is_cached,
                "object":        self,
                "failure":       None,
                "imports":       self._build_import_tree_recursive(),
            }
        return self._import_tree

    # -------------------------------------------------------------------------
    def rebuild_import_tree(self) -> dict:
        """Discard the cached import tree and rebuild it from the current import_list.

        Returns the freshly built tree.
        """
        self._import_tree = None
        return self.import_tree

    # -------------------------------------------------------------------------
    @property
    def is_remote(self) -> bool:
        return not self.is_local

    # -------------------------------------------------------------------------
    @property
    def is_cache_expired(self) -> bool:
        """True when remote cached content has exceeded its TTL."""
        if self.is_local or not self.is_cached or self.ttl <= 0:
            return False
        return (datetime.now() - self.loaded).total_seconds() > self.ttl

    # -------------------------------------------------------------------------
    @property
    def origin_state(self) -> OriginState:
        """Computed from is_local, is_cached, and TTL. Changes over time for cached remote content."""
        if self.is_local:
            return OriginState.LOCAL
        if not self.is_cached:
            return OriginState.REMOTE_UNCACHED
        return OriginState.REMOTE_STALE if self.is_cache_expired else OriginState.REMOTE_FRESH

    # -------------------------------------------------------------------------
    @property
    def is_fresh(self) -> bool:
        """True when content is local or cached and within its TTL."""
        return self.origin_state in (OriginState.LOCAL, OriginState.REMOTE_FRESH)

    # -------------------------------------------------------------------------
    @property
    def is_stale(self) -> bool:
        """True when remote cached content has exceeded its TTL."""
        return self.origin_state == OriginState.REMOTE_STALE

    # -------------------------------------------------------------------------
    @property
    def is_editable(self) -> bool:
        """Can this content be modified?"""
        return self.content_state >= ContentState.VALID and self.is_local and not self.is_read_only

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
        self.content_state = ContentState.NONE   # reset for each validation attempt
        status = False
        oscal_root = ""
        oscal_version = ""
        content_title = ""
        content_version = ""
        content_publication = ""

        # --- Step: acquired ---
        if not content or not content.strip():
            logger.error("No content to validate — source may be empty or unreadable.")
            self.content_state = ContentState.NOT_AVAILABLE
            return False
        self.content_state = ContentState.ACQUIRED

        # --- Step: well-formed ---
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
            logger.error(f"Content is not a recognized OSCAL format (detected: '{self.original_format}').")
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
                else:
                    logger.error(f"Root element '{oscal_root}' is not a recognized OSCAL model.")
                    status = False
            else:
                logger.error(f"OSCAL version '{oscal_version}' is not recognized.")
                status = False

        if status:
            self.content_state = ContentState.WELL_FORMED

        # TEMPORARY: All content-manipulation methods operate on the XML tree only.
        # Until dict-based equivalents are added, force JSON/YAML content into XML
        # as the primary representation so those methods work regardless of load format.
        # This block runs before validate() so that XML schema validation is used
        # for JSON/YAML content (avoids spurious JSON-schema failures).
        # TO REVERSE: delete this block and the logger.debug line that follows it.
        if status and self.original_format in ("json", "yaml"):
            logger.debug(f"TEMPORARY: Converting {self.original_format.upper()} to XML primary representation.")
            if self._sync():
                self.original_format = "xml"
                logger.debug("TEMPORARY: Primary format switched to XML.")
            else:
                logger.warning("TEMPORARY: dict-to-XML conversion failed; content manipulation methods will not work.")
        # END TEMPORARY

        if status:
            self.validate()

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
            logger.error(f"Validation format '{format}' is not a recognized OSCAL format.")
            self.content_state = ContentState.WELL_FORMED
            return False

        if format == "xml":
            logger.debug("Validating XML content against schema...")
            xml_schema_content = self._support.get_asset(self.oscal_version, self.model, "xml-schema")

            if xml_schema_content:
                import xmlschema
                try:
                    schema = xmlschema.XMLSchema(xml_schema_content)
                    xml_string = self._xml_serializer()
                    schema.validate(xml_string)
                    self.schema_valid["_tree"] = True
                    self.content_state = ContentState.VALID
                    logger.debug("XML schema validation passed.")

                except xmlschema.XMLSchemaValidationError as e:
                    logger.error(f"XML schema validation failed: {e.reason}")
                    self.schema_valid["_tree"] = False
                    self.content_state = ContentState.WELL_FORMED
                except Exception as e:
                    logger.error(f"XML schema validation error: {e}")
                    self.schema_valid["_tree"] = False
                    self.content_state = ContentState.WELL_FORMED
            else:
                logger.error(f"XML schema for {self.model} {self.oscal_version} could not be loaded.")
                self.schema_valid["_tree"] = False
                self.content_state = ContentState.WELL_FORMED

        elif format in ("json", "yaml"):
            logger.debug(f"Validating {format} content against schema...")
            json_schema_content = self._support.get_asset(self.oscal_version, self.model, "json-schema")

            if json_schema_content:
                import jsonschema_rs
                try:
                    if isinstance(json_schema_content, str):
                        schema_dict = json.loads(json_schema_content)
                    else:
                        schema_dict = json_schema_content

                    if isinstance(schema_dict, dict) and isinstance(self._dict, dict):
                        jsonschema_rs.validate(schema_dict, self._dict)
                        self.schema_valid["_dict"] = True
                        self.content_state = ContentState.VALID
                        logger.debug("JSON schema validation passed.")
                    else:
                        logger.error("JSON schema could not be parsed as a dictionary.")
                        self.schema_valid["_dict"] = False
                        self.content_state = ContentState.WELL_FORMED

                except jsonschema_rs.ValidationError as e:
                    logger.error(f"JSON schema validation failed: {e}")
                    self.schema_valid["_dict"] = False
                    self.content_state = ContentState.WELL_FORMED
                except Exception as e:
                    logger.error(f"JSON schema validation error: {e}")
                    self.schema_valid["_dict"] = False
                    self.content_state = ContentState.WELL_FORMED
            else:
                logger.error(f"JSON schema for {self.model} {self.oscal_version} could not be loaded.")
                self.schema_valid["_dict"] = False
                self.content_state = ContentState.WELL_FORMED

        if self.is_valid and self.content_state < ContentState.IMPORTS_RESOLVED:
            self.resolve_imports()

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
    def build_import_tree(self, _seen=None):
        """Build and cache a JSON-serializable nested dict of this object and all imports.

        Reads self.import_list (populated by resolve_imports) and assembles a
        recursive structure.  Result is cached in self.import_tree and returned.
        """
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
                child_node.update(child_obj.build_import_tree(_seen))
            else:
                child_node["model"]    = child_obj.model if child_obj else None
                child_node["title"]    = child_obj.title if child_obj else None
                child_node["circular"] = child_obj is not None
                child_node["imports"]  = []

            node["imports"].append(child_node)

        self._import_tree = node
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
class ImportFailureCode(str, Enum):
    # Fragment / back-matter failures
    FRAGMENT_INVALID_UUID      = "fragment-invalid-uuid"       # Fragment is not a valid UUID
    RESOURCE_NOT_FOUND         = "resource-not-found"          # No back-matter resource with that UUID
    RESOURCE_NO_VIABLE_CONTENT = "resource-no-viable-content"  # Resource has no rlinks or base64
    # Full URI / file failures
    LOCAL_NOT_FOUND            = "local-not-found"             # Local file not found
    REMOTE_UNREACHABLE         = "remote-unreachable"          # Remote host not reachable
    REMOTE_AUTH_REQUIRED       = "remote-auth-required"        # Remote resource requires authentication
    REMOTE_UNSUPPORTED         = "remote-unsupported"          # URI scheme not supported
    # Content failures (source responded, but content is unusable)
    CONTENT_EMPTY              = "content-empty"               # Source returned no content
    CONTENT_INVALID            = "content-invalid"             # Content is not valid OSCAL

# -------------------------------------------------------------------------
class ImportLoadError(Exception):
    """Raised by load_source() to carry a typed import failure code to resolve_imports()."""
    def __init__(self, code: ImportFailureCode, uri: str, message: str = ""):
        self.code = code
        self.uri  = uri
        super().__init__(message or f"{code.value}: {uri}")

# -------------------------------------------------------------------------
@dataclass
class ImportFailure:
    """Structured record of a failed import, carrying enough context for a retry attempt.

    Retry sources the calling module may supply:
        - A URI fragment (#uuid) pointing to a back-matter resource
        - A full URI identifying an alternate location for the content
        - The content itself as an XML, JSON, or YAML string
    """
    code: ImportFailureCode
    href_original: str              # Raw href from the import statement

    # Fragment / back-matter context (populated when href starts with "#")
    resource_uuid: str = ""
    resource_title: str = ""
    resource_description: str = ""
    rlinks_tried: list = field(default_factory=list)  # hrefs attempted before giving up

    # URI context (populated for full-URI failures)
    uri: str = ""

    # Human-readable detail
    message: str = ""

    @property
    def is_fragment_ref(self) -> bool:
        """True when the original import href is a back-matter fragment reference."""
        return self.href_original.startswith("#")

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
    """Load content from one or more sources and return the first successful payload.

    Raises ImportLoadError when a source fails with a typed reason.
    For multi-ref lists the last ImportLoadError is re-raised if all sources fail.
    """
    logger.debug("Loading content from source")
    refs = _normalize_refs(source)
    content = ""

    for ref in refs:
        classify_source(ref, only_oscal=only_oscal)

    last_error: ImportLoadError | None = None

    for ref in refs:
        if not ref.source_supported:
            logger.warning(f"Skipping unsupported source: {ref.href} "
                           f"(type={ref.source_type}, scheme={ref.source_scheme})")
            last_error = ImportLoadError(
                ImportFailureCode.REMOTE_UNSUPPORTED, ref.href,
                f"URI scheme '{ref.source_scheme}' is not supported"
            )
            continue

        try:
            content = load_source(ref)
            if content:
                return content
        except ImportLoadError as exc:
            last_error = exc
            logger.warning(f"Failed to load content from source '{ref.href}': {exc}")

    if last_error:
        raise last_error
    logger.error("No usable content could be loaded from provided sources")
    return ""

def load_source(ref: OscalRef) -> str:
    """Fetch or read content from a classified OscalRef.

    Returns the raw content as a string on success.
    Raises ImportLoadError with a typed ImportFailureCode on any load failure.
    """
    src = ref.href.strip()
    content: str = ""

    try:
        if ref.source_type == "uri" and ref.source_scheme == "file":
            # file:// URI → convert to local path
            parsed = urlparse(src)
            local_path = parsed.path
            if parsed.netloc:
                local_path = f"//{parsed.netloc}{parsed.path}"
            logger.info(f"Loading controls from file:// URI: {local_path}")
            content = getfile(local_path)
            if not content:
                raise ImportLoadError(ImportFailureCode.LOCAL_NOT_FOUND, src,
                                      f"File URI returned no content: {local_path}")

        elif ref.source_type == "uri" and ref.source_scheme in {"http", "https"}:
            logger.info(f"Loading controls from URL: {src}")
            try:
                content = normalize_content(download_file(src, "oscal_remote_content")) 
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise ImportLoadError(ImportFailureCode.REMOTE_AUTH_REQUIRED, src,
                                          f"HTTP {exc.code}: authentication required") from exc
                raise ImportLoadError(ImportFailureCode.REMOTE_UNREACHABLE, src,
                                      f"HTTP {exc.code}: {exc.reason}") from exc
            except (URLError, OSError, ConnectionError) as exc:
                raise ImportLoadError(ImportFailureCode.REMOTE_UNREACHABLE, src, str(exc)) from exc
            except Exception as exc:
                # download_file may raise implementation-specific types; inspect message for auth hints
                msg = str(exc).lower()
                if any(t in msg for t in ("401", "403", "unauthorized", "forbidden")):
                    raise ImportLoadError(ImportFailureCode.REMOTE_AUTH_REQUIRED, src, str(exc)) from exc
                raise ImportLoadError(ImportFailureCode.REMOTE_UNREACHABLE, src, str(exc)) from exc

        elif ref.source_type == "uri" and ref.source_scheme in {"ftp", "data"}:
            logger.info(f"Loading controls from URI via urllib: {src}")
            try:
                with urlopen(src) as response:  # nosec B310 - intentional unauthenticated read
                    payload = response.read()
                content = payload.decode("utf-8", errors="replace")
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise ImportLoadError(ImportFailureCode.REMOTE_AUTH_REQUIRED, src,
                                          f"HTTP {exc.code}: authentication required") from exc
                raise ImportLoadError(ImportFailureCode.REMOTE_UNREACHABLE, src,
                                      f"HTTP {exc.code}: {exc.reason}") from exc
            except (URLError, OSError, ConnectionError) as exc:
                raise ImportLoadError(ImportFailureCode.REMOTE_UNREACHABLE, src, str(exc)) from exc

        elif ref.source_type == "file":
            logger.info(f"Loading controls from file: {src}")
            try:
                content = getfile(src)
            except FileNotFoundError as exc:
                raise ImportLoadError(ImportFailureCode.LOCAL_NOT_FOUND, src,
                                      f"File not found: {src}") from exc
            except OSError as exc:
                raise ImportLoadError(ImportFailureCode.LOCAL_NOT_FOUND, src, str(exc)) from exc
            if not content:
                raise ImportLoadError(ImportFailureCode.LOCAL_NOT_FOUND, src,
                                      f"File returned no content: {src}")

        else:
            raise ImportLoadError(ImportFailureCode.REMOTE_UNSUPPORTED, src,
                                  f"No loader for source type={ref.source_type} scheme={ref.source_scheme}")

    except ImportLoadError:
        raise  # already typed — let it propagate
    except Exception as exc:
        logger.error(f"Unexpected error loading source '{src}': {exc}")
        raise ImportLoadError(ImportFailureCode.CONTENT_EMPTY, src, str(exc)) from exc

    if not content:
        raise ImportLoadError(ImportFailureCode.CONTENT_EMPTY, src,
                              f"Source returned no content: {src}")

    return content

# -------------------------------------------------------------------------
def _hrefs_from_dict_spec(root_obj: dict, spec: dict) -> list[str]:
    """Extract all href strings from a JSON model root object using one pattern spec."""
    hrefs   = []
    item    = root_obj.get(spec["path"])
    if item is None:
        return hrefs
    key    = spec["key"]
    single = spec.get("single", False)
    each   = spec.get("each")
    subkey = spec.get("subkey")

    if single:
        # e.g. import-profile, import-ssp — a single object, not a list
        if isinstance(item, dict):
            v = item.get(key, "").strip()
            if v:
                hrefs.append(v)
    elif each:
        # e.g. components[].control-implementations[].source
        for outer in (item if isinstance(item, list) else []):
            for inner in (outer.get(each, []) if isinstance(outer, dict) else []):
                if isinstance(inner, dict):
                    v = inner.get(key, "").strip()
                    if v:
                        hrefs.append(v)
    elif subkey:
        # e.g. mappings[].source-resource.href / mappings[].target-resource.href
        for entry in (item if isinstance(item, list) else []):
            if isinstance(entry, dict):
                sub = entry.get(subkey)
                if isinstance(sub, dict):
                    v = sub.get(key, "").strip()
                    if v:
                        hrefs.append(v)
    else:
        # e.g. imports[].href, import-component-definitions[].href
        for entry in (item if isinstance(item, list) else []):
            if isinstance(entry, dict):
                v = entry.get(key, "").strip()
                if v:
                    hrefs.append(v)
    return hrefs

# -------------------------------------------------------------------------
_OSCAL_EXTENSIONS = {".xml", ".json", ".yaml", ".yml"}

def _resolve_href(base: str, href: str) -> str:
    """Resolve a (possibly relative) href against a base URL or filesystem path.

    Single-character "schemes" like 'c' are Windows drive letters, not URLs —
    they are treated as local filesystem paths so os.path operations are used
    instead of urljoin, which does not understand backslash separators.
    """
    parsed = urlparse(href)
    if parsed.scheme and len(parsed.scheme) > 1:
        return href  # already an absolute URL
    if base:
        base_parsed = urlparse(base)
        if base_parsed.scheme and len(base_parsed.scheme) > 1:
            return urljoin(base, href)  # base is a real URL
        return os.path.normpath(os.path.join(base, href))
    return os.path.abspath(href)

def _oscal_format_variants(href: str) -> list[str]:
    """Return the same href with each other OSCAL format extension substituted.

    Used as additional fallback candidates when a back-matter rlink can't be
    loaded — e.g. a profile in json/ directory whose rlink points to file.xml
    that exists only as file.json in that same directory.
    """
    base, ext = os.path.splitext(href)
    if ext.lower() not in _OSCAL_EXTENSIONS:
        return []
    return [base + e for e in sorted(_OSCAL_EXTENSIONS) if e != ext.lower()]

# -------------------------------------------------------------------------
def _is_valid_uuid(value: str) -> bool:
    """Return True if value is a well-formed UUID string."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False

# -------------------------------------------------------------------------
def _backmatter_resource(doc_obj, resource_uuid: str) -> dict | None:
    """Return metadata and rlinks for a back-matter resource identified by UUID.

    Returns a dict with keys: uuid, title, description, rlinks (list[str]), has_base64.
    Returns None when no resource with the given UUID exists.
    """
    if doc_obj._tree is not None:
        resource_nodes = doc_obj.xpath(
            f"/*/back-matter/resource[@uuid='{resource_uuid}']"
        )
        if not resource_nodes:
            return None
        title_nodes       = doc_obj.xpath(f"/*/back-matter/resource[@uuid='{resource_uuid}']/title")
        desc_nodes        = doc_obj.xpath(f"/*/back-matter/resource[@uuid='{resource_uuid}']/description")
        rlink_nodes       = doc_obj.xpath(f"/*/back-matter/resource[@uuid='{resource_uuid}']/rlink")
        base64_nodes      = doc_obj.xpath(f"/*/back-matter/resource[@uuid='{resource_uuid}']/base64")

        # title is plain text; description uses markup-multiline (text may be in child <p> nodes)
        title       = (title_nodes[0].text or "").strip() if title_nodes else ""
        description = " ".join(desc_nodes[0].itertext()).strip() if desc_nodes else ""
        rlinks      = [n.get("href", "").strip() for n in (rlink_nodes or []) if n.get("href", "").strip()]
        has_base64  = bool(base64_nodes)

    elif doc_obj._dict is not None:
        root_obj  = doc_obj._dict.get(doc_obj.model, {})
        resources = root_obj.get("back-matter", {}).get("resources", [])
        for res in resources:
            if res.get("uuid") == resource_uuid:
                title       = res.get("title", "")
                description = res.get("description", "")
                rlinks      = [r.get("href", "").strip() for r in res.get("rlinks", []) if r.get("href", "").strip()]
                has_base64  = bool(res.get("base64"))
                break
        else:
            return None
    else:
        return None

    return {
        "uuid":        resource_uuid,
        "title":       title,
        "description": description,
        "rlinks":      rlinks,
        "has_base64":  has_base64,
    }

# -------------------------------------------------------------------------
def _backmatter_rlinks(doc_obj, uuid: str) -> list[str]:
    """Return ordered rlink hrefs for a back-matter resource identified by UUID.

    Searches the XML tree first (primary representation after load), then the
    dict.  Returns an empty list if the resource is not found.
    """
    hrefs: list[str] = []

    if doc_obj._tree is not None:
        nodes = doc_obj.xpath(f"/*/back-matter/resource[@uuid='{uuid}']/rlink")
        if nodes:
            for rlink in nodes:
                href = rlink.get("href", "").strip()
                if href:
                    hrefs.append(href)
    elif doc_obj._dict is not None:
        root_obj = doc_obj._dict.get(doc_obj.model, {})
        resources = root_obj.get("back-matter", {}).get("resources", [])
        for resource in resources:
            if resource.get("uuid") == uuid:
                for rlink in resource.get("rlinks", []):
                    href = rlink.get("href", "").strip()
                    if href:
                        hrefs.append(href)
                break

    return hrefs

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
    Returns a validated base OSCAL instance loaded from a template.
    Currently this is based on loading a template file from package data.
    In the future, this should be generated based on the latest metaschema definition.

    The returned instance is always a base OSCAL object. Callers that need a
    specific model subclass (e.g. Catalog, Profile) are responsible for
    reassigning __class__ and calling _init_common() afterward.

    Args:
        model_name (str): The OSCAL model name (e.g., "catalog", "system-security-plan").
        title (str): The title for the new OSCAL content.
        version (str): Optional content version.
        published (str): Optional publication date.
        format (str): The desired format for the new content ("xml", "json", "yaml"). Defaults to "xml".

    Returns:
        Optional[OSCAL]: A base OSCAL instance loaded from template, or None on failure.
    """
    support = get_support()

    if support.is_valid_model(model_name):
        raw = support.load_file(f"{model_name}.xml", as_bytes=False)
        if raw and isinstance(raw, str):
            oscal = OSCAL.__new__(OSCAL)
            oscal.__init_common__()
            if oscal.initial_validation(raw):
                return oscal
            logger.error(f"Template content failed validation for model: {model_name}")
            return None
        else:
            logger.error(f"Failed to load content for model: {model_name}")
            return None
    else:
        logger.error(f"Unsupported OSCAL model for new content: {model_name}")

    return None

# -----------------------------------------------------------------------------
def new_uuid() -> str:
    return str(uuid.uuid4())

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':
    print("OSCAL Class Module. This is not intended to be run as a stand-alone module.")

