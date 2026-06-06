"""
    OSCAL Class

    A class for creation, manipulation, validation and format convertion of OSCAL content.
    All published OSCAL versions, formats and models can be validated and converted.
    Newly published versions can be "learned" by updating the OSCAL Support database.
    See https://github.com/brian-ruf/oscal-class for more details.

"""
from __future__         import annotations
import os
import re
import json
import yaml
import uuid
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
from ruf_common.data    import detect_data_format, safe_load, safe_load_xml, xpath_atomic
from ruf_common.lfs     import getfile, chkdir, putfile, normalize_content
from .oscal_support     import get_support, OSCAL_DEFAULT_XML_NAMESPACE, OSCAL_FORMATS
from .oscal_datatypes   import oscal_date_time_with_timezone, OSCAL_DATATYPES
from .oscal_converter   import (
    oscal_markdown_to_html, OSCALConverter, _html_to_et,
    OSCALPath, NativePath, native_path,
)

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

def _check_datatype(value: str, datatype: str, location: str, field: str) -> dict | None:
    """Validate a string *value* against an OSCAL *datatype* pattern.

    Returns a structured error dict when the value fails the pattern, or ``None``
    when the value is acceptable (including when no applicable pattern is defined).
    Patterns that fail to compile are silently skipped.
    """
    type_info = OSCAL_DATATYPES.get(datatype)
    if not type_info:
        return None
    pattern = type_info.get("json-pattern", "")
    if not pattern:
        return None
    try:
        if re.fullmatch(pattern, value) is None:
            return {
                "error-type": "invalid-type",
                "location":   location,
                "field":      field,
                "value":      value,
                "expected": {
                    "type":        datatype,
                    "pattern":     pattern,
                    "description": type_info.get("documentation", ""),
                },
            }
    except re.error:
        pass
    return None


_OSCAL_NS = "http://csrc.nist.gov/ns/oscal"


def _constraint_conditions_met(constraint: dict, instance: dict) -> bool:
    """Return True when all conditions on a constraint are satisfied by *instance*.

    Condition types:
      namespace   – ``@ns`` flag must be in the allowed namespace values list.
                    Absent ``@ns`` is treated as the OSCAL default namespace per spec.
      flag-equals – a sibling flag must equal a specific value.

    An absent or unrecognised condition type is treated as satisfied (fail-open).
    """
    for cond in constraint.get("conditions", []):
        ctype = cond.get("type")
        if ctype == "namespace":
            # Absent @ns defaults to the OSCAL namespace per OSCAL specification
            ns_val = instance.get("ns") or _OSCAL_NS
            allowed = cond.get("values", [])
            if ns_val not in allowed:
                return False
        elif ctype == "flag-equals":
            flag = cond.get("flag", "")
            expected = cond.get("value", "")
            if instance.get(flag) != expected:
                return False
    return True


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
        if result is not None:
            self.is_unsaved = True
            self.last_modified = oscal_date_time_with_timezone()
        return result
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
        self.import_list: list = []    # Flat list of direct imports (one level)
        self._import_tree: dict | None = None  # Cached recursive import tree (None = not yet built)
        self._dict: dict | None = None # JSON/YAML constructs
        self._tree = None              # XML constructs
        self._oscal_path: OSCALPath | None = None  # Lazily built metaschema-aware path engine

        # Validation Status
        self.validation_status: dict[str, bool | None] = {
            "well-formed":    None,  # content is parseable and OSCAL model/version is identified
            "structure":      None,  # all required fields and hierarchy are present
            "data-types":     None,  # every field/flag value matches its declared OSCAL datatype
            "allowed-values": None,  # every constrained value is within its enumerated set
            "cardinality":    None,  # all arrays satisfy their min-occurs/max-occurs bounds
        }
        self.validation_errors: list[dict] = []  # structured errors from the most recent validate() call
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
        ret_value += "✅" if self.is_valid else "⚠️"

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
                href   = child.get("href_valid") or child.get("href_original", "")
                status = child.get("status", ImportState.NOT_LOADED)
                ret_value += f"\n    [{status}] {href}"
                failure = child.get("failure")
                if failure:
                    ret_value += f" — {failure.message}"
                for item in child.get("href_list", []):
                    item_href   = item.get("href", "")
                    item_status = item.get("status")
                    marker      = "" if item.get("original", True) else " [retry]"
                    if item_status:
                        ret_value += f"\n        [{item_status}]{marker} {item_href}"
                    else:
                        ret_value += f"\n        [not tried]{marker} {item_href}"

        return ret_value

    # -------------------------------------------------------------------------
    @property
    def failed_imports(self) -> list[dict]:
        """Return import_list entries that failed, each carrying a populated 'failure' field."""
        return [e for e in self.import_list if e.get("failure") is not None]

    # -------------------------------------------------------------------------
    def retry_import(self, failed_href: str, replacement_href: str) -> bool:
        """Retry a failed import identified by href.

        The failed import is matched by href (original or previously resolved),
        then re-attempted using replacement_href.
        """
        if not failed_href or not replacement_href:
            logger.warning("retry_import requires both failed_href and replacement_href.")
            return False

        target_entry = None
        for entry in self.import_list:
            failure = entry.get("failure")
            failure_uri = failure.uri if isinstance(failure, ImportFailure) else ""
            if (
                entry.get("href_original") == failed_href
                or entry.get("href_valid") == failed_href
                or failure_uri == failed_href
                or any(item.get("href") == failed_href for item in entry.get("href_list", []))
            ):
                target_entry = entry
                break

        if target_entry is None:
            logger.warning(f"Failed import href '{failed_href}' not found. Cannot retry.")
            return False

        src = self.href or self.href_original
        if src:
            parsed_src = urlparse(src)
            if parsed_src.scheme and len(parsed_src.scheme) > 1:
                base_path = src.rsplit("/", 1)[0] + "/"
            else:
                base_path = os.path.dirname(os.path.abspath(src))
        else:
            base_path = os.getcwd()

        resolved = _resolve_href(base_path, replacement_href)
        logger.info(f"Retrying import '{failed_href}' with replacement '{resolved}'")

        retry_item: dict = {"href": resolved, "original": False}
        try:
            child = OSCAL.acquire(resolved)
            if child.is_valid:
                retry_item["status"]        = ImportState.READY
                target_entry["href_valid"]  = resolved
                target_entry["object"]      = child
                target_entry["is_valid"]    = True
                target_entry["is_local"]    = child.is_local
                target_entry["is_remote"]   = child.is_remote
                target_entry["is_cached"]   = child.is_cached
                target_entry["status"]      = ImportState.READY
                target_entry["failure"]     = None
            else:
                retry_item["status"]       = ImportState.INVALID
                target_entry["href_valid"] = ""
                target_entry["object"]     = None
                target_entry["is_valid"]   = False
                target_entry["status"]     = ImportState.INVALID
                target_entry["failure"]    = ImportFailure(
                    code=ImportFailureCode.CONTENT_INVALID,
                    href_original=target_entry.get("href_original", failed_href),
                    uri=resolved,
                    message="Replacement content loaded but failed OSCAL validation",
                )
        except ImportLoadError as exc:
            retry_item["status"]       = ImportState.INVALID
            target_entry["href_valid"] = ""
            target_entry["object"]     = None
            target_entry["is_valid"]   = False
            target_entry["status"]     = ImportState.INVALID
            target_entry["failure"]    = ImportFailure(
                code=exc.code,
                href_original=target_entry.get("href_original", failed_href),
                uri=exc.uri,
                message=str(exc),
            )
        target_entry.setdefault("href_list", []).append(retry_item)

        self._import_tree = None  # force rebuild on next access
        has_invalid = any(e.get("status") == ImportState.INVALID for e in self.import_list)
        if self.is_valid and not has_invalid:
            self.content_state = ContentState.IMPORTS_RESOLVED
        elif self.content_state >= ContentState.IMPORTS_RESOLVED:
            # A retry that fails must revert the state — imports are no longer fully resolved.
            self.content_state = ContentState.VALID

        return target_entry["status"] == ImportState.READY

    # -------------------------------------------------------------------------
    def retry_imports(self, failed_href: str, replacement_href: str) -> bool:
        """Compatibility alias for callers using the plural method name."""
        return self.retry_import(failed_href, replacement_href)

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

        # --- collect raw hrefs from dict ---
        raw_hrefs: list[str] = []

        if self._dict is None:
            logger.warning("resolve_imports: no content available.")
            return self.import_list

        dict_patterns = _IMPORT_PATTERNS_DICT.get(self.model, [])
        if not dict_patterns:
            logger.debug(f"resolve_imports: no dict patterns defined for model '{self.model}'.")
        root_obj = self._dict.get(self.model, {})
        for spec in dict_patterns:
            raw_hrefs.extend(_hrefs_from_dict_spec(root_obj, spec))

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
                "href_list":     [{"href": raw_href, "original": True}],
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

                # Append back-matter rlinks to href_list; base64 fallback is future work
                for rl in resource_info["rlinks"]:
                    entry["href_list"].append({**rl, "original": True})

                # Stash resource metadata so the failure record can carry it
                entry["resource_uuid"]        = fragment
                entry["resource_title"]       = resource_info.get("title", "")
                entry["resource_description"] = resource_info.get("description", "")

            # --- Try each href_list item in order; use the first that yields valid OSCAL ---
            rlinks_tried: list[str] = []
            last_load_error: ImportLoadError | None = None

            for item in entry["href_list"]:
                if item["href"].startswith("#"):
                    continue
                primary  = _resolve_href(base_path, item["href"])
                attempts = [primary] + [_resolve_href(base_path, v) for v in _oscal_format_variants(item["href"])]
                for resolved in attempts:
                    rlinks_tried.append(resolved)
                    try:
                        child = OSCAL.acquire(resolved)
                        if child.is_valid:
                            item["status"]      = ImportState.READY
                            entry["href_valid"] = resolved
                            entry["object"]     = child
                            entry["is_valid"]   = True
                            entry["is_local"]   = child.is_local
                            entry["is_remote"]  = child.is_remote
                            entry["is_cached"]  = child.is_cached
                            entry["status"]     = ImportState.READY
                            last_load_error     = None
                            break
                        item["status"] = ImportState.INVALID
                        logger.warning(f"resolve_imports: '{resolved}' loaded but failed OSCAL validation.")
                    except ImportLoadError as exc:
                        item["status"]  = ImportState.INVALID
                        last_load_error = exc
                        logger.warning(f"resolve_imports: load error for '{resolved}': {exc}")
                        # Auth/unsupported errors won't improve by trying format variants
                        if exc.code in (ImportFailureCode.REMOTE_AUTH_REQUIRED,
                                        ImportFailureCode.REMOTE_UNSUPPORTED):
                            break
                    except Exception as exc:
                        item["status"] = ImportState.INVALID
                        logger.warning(f"resolve_imports: could not load '{resolved}': {exc}")
                if entry["status"] == ImportState.READY:
                    break

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
                        rlinks_tried=rlinks_tried,
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
            _working_href = self.href or self.href_original
            _root_href_list: list[dict] = [
                {"href": _working_href, "status": ImportState.READY, "original": True}
            ]
            if self.href_original and self.href_original != _working_href:
                _root_href_list.append({"href": self.href_original, "original": True})
            self._import_tree = {
                "href_original": self.href_original,
                "href_valid":    _working_href,
                "href_list":     _root_href_list,
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
                    oscal_root = xpath_atomic(self._tree, _NSMAP, "/*/name()")
                    oscal_version = "v" + xpath_atomic(self._tree, _NSMAP, "/*/metadata/oscal-version/text()")
                    content_title = xpath_atomic(self._tree, _NSMAP, "/*/metadata/title/text()")
                    content_version = xpath_atomic(self._tree, _NSMAP, "/*/metadata/version/text()")
                    content_publication = xpath_atomic(self._tree, _NSMAP, "/*/metadata/published/text()")
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

        self.validation_status["well-formed"] = status
        if status:
            self.content_state = ContentState.WELL_FORMED

        # For XML sources, immediately convert to dict so all manipulation operates on JSON-native data.
        # Once dict is populated the parsed XML tree is released — it can be rebuilt on demand via
        # _build_tree() if XML output is later requested.
        if status and self.original_format == "xml":
            converter = OSCALConverter.from_support(self.model, self.oscal_version, self._support)
            if converter is not None:
                xml_string = self._xml_serializer()
                json_string = converter.xml_to_json(xml_string)
                if json_string is not None:
                    self._dict = json.loads(json_string)
                    self._tree = None
                    logger.debug("XML source converted to dict; XML tree released.")
                else:
                    logger.warning("XML→dict conversion failed; dict-based manipulation unavailable.")
            else:
                logger.warning(f"No metaschema converter for {self.model} {self.oscal_version}; dict unavailable.")

        if status and self._dict is not None:
            self.validate(format="json")

        return status

    # -------------------------------------------------------------------------
    def validate(self, format: str = "") -> bool:
        """Validate OSCAL content against the metaschema index in sequenced phases.

        Phases (each recorded in ``validation_status``):
          structure      – all required fields and hierarchy are present
          data-types     – every leaf value matches its declared OSCAL datatype
          allowed-values – every constrained value is within its enumerated set

        ``validation_status["well-formed"]`` is set by ``initial_validation()``, not here.
        All three phases always run regardless of earlier failures, giving a complete
        picture of issues in a single call.  The format argument is accepted for API
        compatibility but does not alter the validation path — ``_dict`` is always the
        authoritative representation.

        Returns True only when every phase passes (content_state reaches VALID).
        """
        for phase in ("structure", "data-types", "allowed-values", "cardinality"):
            self.validation_status[phase] = None
        self.validation_errors = []

        if format and format not in OSCAL_FORMATS:
            logger.error(f"Validation format '{format}' is not a recognized OSCAL format.")
            return False

        if self._dict is None:
            logger.error("No dict content available for validation.")
            return False

        index = self._support.get_metaschema_index(self.oscal_version, self.model)
        if index is None:
            logger.warning("Metaschema index unavailable; treating all validation phases as passed.")
            for phase in ("structure", "data-types", "allowed-values", "cardinality"):
                self.validation_status[phase] = True
            self.content_state = ContentState.VALID
            if self.content_state < ContentState.IMPORTS_RESOLVED:
                self.resolve_imports()
            return True

        model_nodes  = index.get("nodes")
        model_instance = self._dict.get(self.model)

        if not isinstance(model_instance, dict) or model_nodes is None:
            logger.warning("Cannot locate model root or index nodes; treating all phases as passed.")
            for phase in ("structure", "data-types", "allowed-values", "cardinality"):
                self.validation_status[phase] = True
            self.content_state = ContentState.VALID
            if self.content_state < ContentState.IMPORTS_RESOLVED:
                self.resolve_imports()
            return True

        logger.debug("Validating content against metaschema index (all phases)...")
        errors: list[dict] = []
        self._walk_instance(model_instance, model_nodes, errors, f"/{self.model}")

        struct_errors      = [e for e in errors if e["error-type"] == "missing-required"]
        dtype_errors       = [e for e in errors if e["error-type"] == "invalid-type"]
        av_errors          = [e for e in errors if e["error-type"] == "allowed-values"]
        cardinality_errors = [e for e in errors if e["error-type"] == "cardinality"]

        self.validation_status["structure"]      = (len(struct_errors)      == 0)
        self.validation_status["data-types"]     = (len(dtype_errors)       == 0)
        self.validation_status["allowed-values"] = (len(av_errors)          == 0)
        self.validation_status["cardinality"]    = (len(cardinality_errors) == 0)
        self.validation_errors = errors

        for e in errors:
            logger.debug(
                f"[{e['error-type']}] {e.get('location', '')} "
                f"field={e.get('field', '')} value={e.get('value')!r}"
            )

        _phases = ("structure", "data-types", "allowed-values", "cardinality")
        all_passed = all(self.validation_status[p] for p in _phases)
        if all_passed:
            self.content_state = ContentState.VALID
            logger.debug("All validation phases passed.")
        else:
            self.content_state = ContentState.WELL_FORMED
            failed = [p for p in _phases if not self.validation_status[p]]
            logger.info(f"Validation failed phases: {failed} ({len(errors)} total error(s))")

        if self.is_valid and self.content_state < ContentState.IMPORTS_RESOLVED:
            self.resolve_imports()

        return self.is_valid

    # -------------------------------------------------------------------------
    def _walk_instance(
        self,
        instance: dict,
        node: dict,
        errors: list[dict],
        location: str,
    ) -> None:
        """Recursively walk *instance* against metaschema *node*, collecting structured errors.

        Error types produced:
          ``missing-required``  – a required field or flag is absent
          ``invalid-type``      – a value does not match its declared OSCAL datatype pattern
          ``allowed-values``    – a value is not in its enumerated allowed-values set
          ``cardinality``       – an array has fewer items than min-occurs or more than max-occurs

        All four error types are collected in a single pass so that ``validate()`` can
        partition them by phase after the walk completes.

        Args:
            instance: The JSON dict being validated at the current tree level.
            node:     The metaschema index node describing the expected structure.
            errors:   Accumulator list — errors are appended in-place.
            location: JSON path to *instance* used for error reporting (e.g. "/catalog/metadata").
        """
        if not isinstance(instance, dict) or not isinstance(node, dict):
            return

        children = node.get("children", [])

        # ------------------------------------------------------------------
        # Flags: structure → data-type → allowed-values
        # ------------------------------------------------------------------
        for flag_node in (c for c in children if c.get("structure-type") == "flag"):
            flag_name = flag_node.get("use-name") or flag_node.get("name")
            if not flag_name:
                continue

            if flag_node.get("min-occurs") == "1" and flag_name not in instance:
                errors.append({
                    "error-type": "missing-required",
                    "location":   location,
                    "field":      f"@{flag_name}",
                    "value":      None,
                    "expected":   {},
                })
                continue

            if flag_name not in instance:
                continue

            flag_val = instance[flag_name]

            # Data type check
            datatype = flag_node.get("datatype")
            if datatype and isinstance(flag_val, str) and flag_val:
                err = _check_datatype(flag_val, datatype, location, f"@{flag_name}")
                if err:
                    errors.append(err)

            # Allowed-values check
            for constraint in flag_node.get("constraints", []):
                if constraint.get("type") != "allowed-values":
                    continue
                if constraint.get("allow-other", False):
                    continue
                if not _constraint_conditions_met(constraint, instance):
                    continue
                values = constraint.get("values", [])
                if flag_val not in {v["value"] for v in values}:
                    errors.append({
                        "error-type": "allowed-values",
                        "location":   location,
                        "field":      f"@{flag_name}",
                        "value":      flag_val,
                        "expected": {
                            "one-of": [
                                {"enum": v["value"], "description": v.get("description", "")}
                                for v in sorted(values, key=lambda x: x["value"])
                            ],
                        },
                    })

        # ------------------------------------------------------------------
        # Non-flag children: structure → data-type (fields) → recurse
        # ------------------------------------------------------------------
        for child_node in children:
            stype = child_node.get("structure-type")
            if stype in ("flag", "choice", "any", "recursive"):
                continue
            child_name = child_node.get("use-name") or child_node.get("name")
            if not child_name:
                continue

            json_key   = child_node.get("group-as") or child_name
            child_val  = instance.get(json_key)
            min_occurs = child_node.get("min-occurs", "0")
            max_occurs = child_node.get("max-occurs", "unbounded")
            required   = min_occurs == "1"

            if child_val is None:
                if required:
                    errors.append({
                        "error-type": "missing-required",
                        "location":   location,
                        "field":      child_name,
                        "value":      None,
                        "expected":   {},
                    })
                continue

            child_loc = f"{location}/{json_key}"

            # Data type check for scalar fields
            if stype == "field" and isinstance(child_val, str) and child_val:
                datatype = child_node.get("datatype")
                if datatype:
                    err = _check_datatype(child_val, datatype, location, child_name)
                    if err:
                        errors.append(err)

            # Recurse into assemblies and grouped fields
            if isinstance(child_val, list):
                min_int = int(min_occurs)
                max_int = None if max_occurs == "unbounded" else int(max_occurs)
                actual  = len(child_val)
                if actual < min_int or (max_int is not None and actual > max_int):
                    errors.append({
                        "error-type": "cardinality",
                        "location":   location,
                        "field":      child_name,
                        "value":      actual,
                        "min":        min_int,
                        "max":        max_int,
                    })
                for i, item in enumerate(child_val):
                    if isinstance(item, dict):
                        self._walk_instance(item, child_node, errors, f"{child_loc}[{i}]")
            elif isinstance(child_val, dict):
                self._walk_instance(child_val, child_node, errors, child_loc)

    # -------------------------------------------------------------------------
    def _build_tree(self) -> bool:
        """Build `_tree` from `_dict` using the metaschema-based JSON-to-XML converter."""
        if self._dict is None:
            logger.error("No dict available to build XML tree from.")
            return False
        converter = OSCALConverter.from_support(self.model, self.oscal_version, self._support)
        if converter is None:
            logger.error(f"No metaschema converter for {self.model} {self.oscal_version}; cannot build XML tree.")
            return False
        json_string = json.dumps(self._dict)
        xml_string = converter.json_to_xml(json_string)
        if not xml_string:
            logger.error("JSON-to-XML conversion produced no output.")
            return False
        self._tree = ElementTree.ElementTree(ElementTree.fromstring(xml_string.encode("utf-8")))
        logger.debug("XML tree built from dict.")
        return True

    # -------------------------------------------------------------------------
    @property
    def xml(self) -> str:
        """Return the content as an XML string, converting from dict if necessary."""
        if self._tree is None:
            if not self._build_tree():
                logger.error("Failed to build XML tree for serialization.")
                return ""
        return self._xml_serializer()

    # -------------------------------------------------------------------------
    @property
    def json(self) -> str:
        """Return the content as a JSON string."""
        if self._dict is None:
            logger.error("No content available for JSON serialization.")
            return ""
        return json.dumps(self._dict, indent=INDENT)

    # -------------------------------------------------------------------------
    @property
    def yaml(self) -> str:
        """Return the content as a YAML string."""
        if self._dict is None:
            logger.error("No content available for YAML serialization.")
            return ""
        return yaml.dump(self._dict, sort_keys=False, indent=INDENT)

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def set_metadata(self, content: dict = {}) -> bool:
        """
        Sets metadata fields in the OSCAL content.
        Args:
            content (dict): A dictionary containing metadata fields to set.
        """
        success = False
        if self._dict is None:
            logger.error("No content available to set metadata.")
            return success
        model_obj = self._dict.setdefault(self.model, {})
        if "metadata" not in model_obj:
            logger.warning("No metadata section found in content. Creating.")
            model_obj["metadata"] = {}
        metadata = model_obj["metadata"]
        
        for item in content:
            if item in ['revisions', 'document-ids', 'roles', 'locations', 'parties', 'links', 'props', 'responsible-parties']:
                logger.warning(f"Setting complex metadata field '{item}' is not yet implemented.")
                continue
            metadata[item] = content.get(item, "")
        success = True

        return success

    # -------------------------------------------------------------------------
    @property
    def _path_engine(self) -> OSCALPath | None:
        """Lazily build and cache the metaschema-aware path engine for this model/version."""
        if self._oscal_path is None and self.model and self.oscal_version:
            self._oscal_path = OSCALPath.from_support(
                self.model, self.oscal_version, self._support
            )
        return self._oscal_path

    def query(self, path: str, context: dict | None = None) -> list:
        """
        Query the JSON content using XML element name syntax (via :class:`OSCALPath`).

        Steps use OSCAL XML element names (``control``, ``prop``, ``part``, …)
        and the metaschema index translates them to the correct JSON keys
        (``controls``, ``props``, ``parts``, …) including array/BY_KEY grouping.

        Parameters
        ----------
        path : str
            Path expression using XML element names, e.g.
            ``"//control[@id='ac-2.2']"`` or ``"/*/metadata/title"``.
        context : dict, optional
            Sub-dict to query within.  Defaults to the full document dict
            (``self._dict``).

        Returns a list of matching JSON values, or ``[]`` on error / no match.
        """
        engine = self._path_engine
        if engine is None:
            logger.error("query: OSCALPath engine unavailable — metaschema index may not be loaded.")
            return []
        data = context if context is not None else self._dict
        if data is None:
            logger.error("query: no JSON content available.")
            return []
        return engine.query(path, data)

    def query_one(self, path: str, context: dict | None = None, default=None):
        """Return the first result of :meth:`query`, or *default* when nothing matches."""
        results = self.query(path, context)
        return results[0] if results else default

    def json_query(self, path: str, context: dict | None = None) -> list:
        """
        Query the JSON content using JSON key name syntax (via :class:`NativePath`).

        Steps use the actual JSON key names (``controls``, ``props``, ``parts``, …)
        with no metaschema translation required.  Arrays are iterated
        transparently, so ``//controls[id='ac-2.2']`` navigates directly into
        any ``controls`` array at any depth.

        Parameters
        ----------
        path : str
            Path expression using JSON key names, e.g.
            ``"//controls[id='ac-2.2']"`` or ``"/*/metadata/title"``.
        context : dict, optional
            Sub-dict to query within.  Defaults to the full document dict
            (``self._dict``).

        Returns a list of matching JSON values, or ``[]`` on error / no match.
        """
        data = context if context is not None else self._dict
        if data is None:
            logger.error("json_query: no JSON content available.")
            return []
        return native_path.query(path, data)

    def json_query_one(self, path: str, context: dict | None = None, default=None):
        """Return the first result of :meth:`json_query`, or *default* when nothing matches."""
        results = self.json_query(path, context)
        return results[0] if results else default

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def __set_field(self, path: str, field_value) -> bool:
        """
        Sets a field in the OSCAL content by JSON path.

        Path segments are separated by '/' and are relative to the model root.
        List elements are addressed by integer index.

        Args:
            path (str): Slash-separated path relative to the model root.
                        e.g. "metadata/title" or "back-matter/resources/0/title"
            field_value: Value to set at the target path (any JSON-compatible type).

        Returns:
            bool: True on success, False on any error.
        """
        if self._dict is None:
            logger.error("__set_field: no content available.")
            return False

        parts = path.strip("/").split("/")
        obj = self._dict.get(self.model, {})

        for part in parts[:-1]:
            if isinstance(obj, list):
                try:
                    obj = obj[int(part)]
                except (ValueError, IndexError):
                    logger.error(f"__set_field: invalid list index '{part}' in path '{path}'.")
                    return False
            elif isinstance(obj, dict):
                if part not in obj:
                    logger.error(f"__set_field: key '{part}' not found in path '{path}'.")
                    return False
                obj = obj[part]
            else:
                logger.error(f"__set_field: cannot traverse into {type(obj).__name__} at '{part}' in path '{path}'.")
                return False

        leaf = parts[-1]
        if isinstance(obj, list):
            try:
                obj[int(leaf)] = field_value
            except (ValueError, IndexError):
                logger.error(f"__set_field: invalid list index '{leaf}' in path '{path}'.")
                return False
        elif isinstance(obj, dict):
            obj[leaf] = field_value
        else:
            logger.error(f"__set_field: cannot set field on {type(obj).__name__} at path '{path}'.")
            return False

        logger.debug(f"__set_field: '{path}' = {field_value!r}")
        return True

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    @requires(is_read_only=False)
    @if_update_successful
    def append_child(self, path: str, child: dict) -> dict | None:
        """
        Appends a child dict to the list at the given JSON path.

        Path segments are '/' separated, relative to the model root.  The leaf
        segment names the list key; it is created as an empty list if absent.

        Args:
            path (str):  Slash-separated path to the target list relative to the
                         model root, e.g. "metadata/props" or "back-matter/resources".
            child (dict): Dict to append to the list.

        Returns:
            dict | None: The appended child on success, None on failure.
        """
        if self._dict is None:
            logger.error("append_child: no content available.")
            return None

        parts = path.strip("/").split("/")
        obj = self._dict.get(self.model, {})

        for part in parts[:-1]:
            if isinstance(obj, list):
                try:
                    obj = obj[int(part)]
                except (ValueError, IndexError):
                    logger.error(f"append_child: invalid list index '{part}' in path '{path}'.")
                    return None
            elif isinstance(obj, dict):
                if part not in obj:
                    logger.error(f"append_child: key '{part}' not found in path '{path}'.")
                    return None
                obj = obj[part]
            else:
                logger.error(f"append_child: cannot traverse into {type(obj).__name__} at '{part}' in path '{path}'.")
                return None

        leaf = parts[-1]
        if isinstance(obj, dict):
            target = obj.setdefault(leaf, [])
            if not isinstance(target, list):
                logger.error(f"append_child: '{leaf}' at path '{path}' is {type(target).__name__}, expected list.")
                return None
        elif isinstance(obj, list):
            try:
                target = obj[int(leaf)]
            except (ValueError, IndexError):
                logger.error(f"append_child: invalid list index '{leaf}' in path '{path}'.")
                return None
            if not isinstance(target, list):
                logger.error(f"append_child: target at '{path}' is {type(target).__name__}, expected list.")
                return None
        else:
            logger.error(f"append_child: cannot resolve leaf '{leaf}' on {type(obj).__name__} at path '{path}'.")
            return None

        target.append(child)
        logger.debug(f"append_child: appended to '{path}'.")
        return child

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def append_resource(self, uuid: str = "", title: str = "", description: str = "", props: list = [], rlinks: list = [], base64: str = "", remarks: str = "") -> dict | None:
        """
        Appends a resource to the back-matter section.
        """
        return append_resource(self, uuid, title, description, props, rlinks, base64, remarks)

    # -------------------------------------------------------------------------
    def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope="successful"):
        """Walk the import tree depth-first, calling visitor_fn(entry, depth) for each entry.

        Args:
            visitor_fn: Callable receiving (entry_dict, depth_int).
            depth:      Current recursion depth (used internally for the depth argument).
            _seen:      Set of object ids already visited (used internally to prevent cycles).
            scope:      Which entries to visit — "successful" (default), "failed", or "all".
                        "successful" visits only READY imports and recurses into them.
                        "failed"     visits only INVALID/NOT_LOADED imports (no recursion).
                        "all"        visits every entry; recursion only follows READY imports.
        """
        if _seen is None:
            _seen = set()
        for entry in self.import_list:
            status     = entry.get("status")
            is_success = status == ImportState.READY
            if scope == "successful" and not is_success:
                continue
            if scope == "failed" and is_success:
                continue
            obj = entry.get("object")
            if obj is not None:
                obj_id = id(obj)
                if obj_id in _seen:
                    continue
                _seen.add(obj_id)
            visitor_fn(entry, depth)
            if obj is not None:
                obj.walk_imports(visitor_fn, depth + 1, _seen, scope=scope)

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
            if self._tree is None and not self._build_tree():
                logger.error("Failed to build XML tree for serialization.")
                return ""
            return self._xml_serializer(pretty_print=pretty_print)
        elif format == "json":
            if self._dict is None:
                logger.error("No content available for JSON serialization.")
                return ""
            return self._json_serializer(pretty_print=pretty_print)
        elif format in ("yaml", "yml"):
            if self._dict is None:
                logger.error("No content available for YAML serialization.")
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

    Returns a dict with keys: uuid, title, description, rlinks (list[dict]), has_base64.
    Returns None when no resource with the given UUID exists.
    """
    if doc_obj._dict is None:
        return None

    root_obj  = doc_obj._dict.get(doc_obj.model, {})
    resources = root_obj.get("back-matter", {}).get("resources", [])
    for res in resources:
        if res.get("uuid") == resource_uuid:
            title       = res.get("title", "")
            description = res.get("description", "")
            rlinks: list[dict] = []
            for r in res.get("rlinks", []):
                href = r.get("href", "").strip()
                if not href:
                    continue
                rl: dict = {"href": href}
                if "media-type" in r:
                    rl["media-type"] = r["media-type"]
                if "hashes" in r:
                    rl["hashes"] = r["hashes"]
                rlinks.append(rl)
            has_base64 = bool(res.get("base64"))
            break
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
def append_props(parent_obj: dict, props: list) -> None:
    """
    Appends multiple prop dicts to parent_obj["props"].

    Args:
        parent_obj (dict): OSCAL JSON object that will receive the props.
        props (list[dict]): Property dicts, each with at minimum "name" and "value".
    """
    for prop in props:
        append_prop(parent_obj, prop)

# -------------------------------------------------------------------------
def append_prop(parent_obj: dict, prop: dict) -> dict:
    """
    Appends a prop dict to parent_obj["props"].

    Args:
        parent_obj (dict): OSCAL JSON object that will receive the prop.
        prop (dict): Property dict.  Required keys: "name", "value".
                     Optional keys: "uuid", "ns", "class", "group", "remarks".

    Returns:
        dict: The appended prop entry.
    """
    entry: dict = {}
    for key in ("uuid", "name", "ns", "value", "class", "group", "remarks"):
        if key in prop:
            entry[key] = prop[key]
    parent_obj.setdefault("props", []).append(entry)
    return entry

# -----------------------------------------------------------------------------
def append_links(parent_obj: dict, links: list) -> None:
    """
    Appends multiple link dicts to parent_obj["links"].

    Args:
        parent_obj (dict): OSCAL JSON object that will receive the links.
        links (list[dict]): Link dicts.
    """
    for link in links:
        append_link(parent_obj, link)

# -----------------------------------------------------------------------------
def append_link(parent_obj: dict, link: dict) -> dict:
    """
    Appends a link dict to parent_obj["links"].

    Args:
        parent_obj (dict): OSCAL JSON object that will receive the link.
        link (dict): Link dict.  Required key: "href".
                     Optional keys: "rel", "media-type", "resource-fragment", "text".

    Returns:
        dict: The appended link entry.
    """
    entry: dict = {}
    for key in ("href", "rel", "media-type", "resource-fragment", "text"):
        if key in link:
            entry[key] = link[key]
    parent_obj.setdefault("links", []).append(entry)
    return entry

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
        return _html_to_et(html_str, "")
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
def append_resource(oscal_obj: OSCAL, uuid: str = "", title: str = "", description: str = "", props: list = [], rlinks: list = [], base64: str = "", remarks: str = "") -> dict | None:
    """
    Appends a resource to the back-matter section of the OSCAL JSON content.

    Args:
        oscal_obj:   The OSCAL document to modify.
        uuid:        Resource UUID; generated if not supplied.
        title:       Optional resource title.
        description: Optional resource description.
        props:       Optional list of prop dicts (see append_prop).
        rlinks:      Optional list of rlink dicts with "href" and optional "media-type"/"hashes".
        base64:      Not yet implemented; a warning is logged if supplied.
        remarks:     Optional remarks (OSCAL markup-multiline / markdown string).

    Returns:
        dict | None: The appended resource dict, or None on error.
    """
    if oscal_obj._dict is None:
        logger.error("append_resource: no content available.")
        return None

    resource: dict = {"uuid": uuid or new_uuid()}
    if title:
        resource["title"] = title
    if description:
        resource["description"] = description
    if props:
        append_props(resource, props)
    if rlinks:
        resource["rlinks"] = [
            {k: v for k, v in rl.items() if k in ("href", "media-type", "hashes")}
            for rl in rlinks
        ]
    if base64:
        logger.warning("Base64 content in resource is not yet implemented.")
    if remarks:
        resource["remarks"] = remarks

    root_obj = oscal_obj._dict.setdefault(oscal_obj.model, {})
    root_obj.setdefault("back-matter", {}).setdefault("resources", []).append(resource)
    logger.debug(f"append_resource: resource '{resource['uuid']}' added to back-matter.")
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

