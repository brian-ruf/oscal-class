"""
oscal_content — OSCAL base class and shared content operations.

Defines the ``OSCAL`` base class used by all eight model classes for creating,
loading, manipulating, validating, and format-converting OSCAL content. All
published OSCAL versions, formats, and models can be validated and converted;
newly published versions can be "learned" by updating the OSCAL Support
database. This module also provides import-resolution machinery, dict-building
helpers (props/links/resources), and Metapath/JSON query support.

See https://github.com/brian-ruf/oscal-class for more details.

Module constants:
    INDENT (int): Number of spaces used for indentation in pretty-printed output.
    OSCAL_DEFAULT_XML_NAMESPACE (str): The NIST OSCAL XML namespace URI
        (re-exported from ``oscal_support``).
    OSCAL_FORMATS (list): Supported serialization formats
        (re-exported from ``oscal_support``).
    OSCAL_DATATYPES (dict): OSCAL Metaschema data type definitions
        (re-exported from ``oscal_datatypes``).
"""
from __future__         import annotations
import os
import re
import json
import copy
import contextvars
from contextlib         import contextmanager
import yaml
import uuid
import logging
from typing             import Optional, Any, Literal, Protocol, runtime_checkable
from datetime           import datetime
from functools          import wraps
from enum               import Enum, IntEnum
from urllib.parse       import urlparse, urljoin, urlunparse
from urllib.request     import urlopen
from urllib.error       import HTTPError, URLError
from xml.etree          import ElementTree
from dataclasses        import dataclass, field

from ruf_common.network import download_file
from ruf_common.data    import detect_data_format, safe_load, safe_load_xml, xpath_atomic
from ruf_common.lfs     import getfile, chkdir, putfile, normalize_content
from .oscal_support     import get_support, OSCAL_DEFAULT_XML_NAMESPACE, OSCAL_FORMATS
from .oscal_datatypes   import oscal_date_time_with_timezone, OSCAL_DATATYPES
from .oscal_registry    import get_registry
from .oscal_cache       import get_local_cache, CacheDirective, CACHE_NEVER
from .oscal_converter   import (
    oscal_markdown_to_html, OSCALConverter, _html_to_et, _markup_to_md,
    OSCALPath, native_path,
)

logger = logging.getLogger(__name__)

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
    """Origin/freshness state of a document's source (not progressive).

    Freshness is time-based and computed on demand rather than stored.

    Members:
        LOCAL (str): "local" — local file system source; always accessible.
        REMOTE_UNCACHED (str): "remote-uncached" — remote source with no local cache copy.
        REMOTE_FRESH (str): "remote-fresh" — remote source cached and within its TTL.
        REMOTE_STALE (str): "remote-stale" — remote source cached but past its TTL.
    """
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


_OSCAL_NS = "http://csrc.nist.gov/ns/oscal" # OSCAL default namespace for props, parts and any other `ns` qualified elements.


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
    """Progressive content-processing state; each level implies all prior levels passed.

    Members (ordered by increasing progress):
        NONE (int): -1 — no content / uninitialized.
        NOT_AVAILABLE (int): 0 — content could not be acquired.
        ACQUIRED (int): 1 — content was acquired (non-empty string).
        WELL_FORMED (int): 2 — content is well-formed XML, JSON, or YAML.
        VALID (int): 3 — content passes OSCAL schema validation (minimum for view/edit).
        IMPORTS_RESOLVED (int): 4 — all imported OSCAL documents resolved successfully.
    """
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
        """Read up to ``size`` bytes/characters from the source (``-1`` reads all)."""
        ...

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Factory Methods and Initializers
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def requires(**conditions):
    """Decorator factory gating a method on instance attribute/property values.

    The wrapped method runs only when every ``attr == expected`` condition holds
    on ``self``; otherwise it logs an error and returns None.

    Args:
        **conditions: Mapping of instance attribute/property name to its required
            value (e.g. ``writable=True``, ``is_remote=True``).

    Returns:
        Callable: A decorator that wraps the target method with the guard.

    Example:
        >>> @requires(is_read_only=False)
        ... def mutate(self): ...
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
    """Decorator factory gating a method on a minimum ``ContentState`` level.

    The wrapped method runs only when ``self.content_state >= min_state``;
    otherwise it logs an error and returns None.

    Args:
        min_state (ContentState, required): Minimum content state required to run
            the method.

    Returns:
        Callable: A decorator that wraps the target method with the guard.
    """
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
    """Decorator marking content dirty after a successful mutation.

    Wraps a mutation method; when it returns a non-None result, sets
    ``self.is_unsaved = True`` and updates ``self.last_modified``.

    Args:
        fn (Callable, required): The mutation method to wrap.

    Returns:
        Callable: The wrapped method.
    """
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        result = fn(self, *args, **kwargs)
        if result is not None:
            self.is_unsaved = True
            self.last_modified = oscal_date_time_with_timezone()
        return result
    return wrapper

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Model-class registry — model name → subclass, populated by the model modules
# (oscal_controls, oscal_implementation, oscal_assessment) at import time. Kept
# here (rather than importing the subclasses) to avoid an import cycle; lets the
# base factory methods return the correct typed instance.
_MODEL_REGISTRY: dict[str, type] = {}


def register_model(model_name: str, cls: type) -> None:
    """Register an OSCAL model subclass so factory methods return typed instances.

    Args:
        model_name (str, required): The OSCAL model name (e.g. "catalog").
        cls (type, required): The ``OSCAL`` subclass implementing that model.
    """
    _MODEL_REGISTRY[model_name] = cls


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Current actor (view/session) — identifies who is performing mutations, so a
# Workspace's write locks can be enforced per view on shared documents.
_current_actor: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "oscal_current_actor", default=None
)


def current_actor() -> "str | None":
    """Return the current actor (view/session) id, or None when unset.

    Returns:
        str | None: The actor id activated by :func:`use_actor`, else None.
    """
    return _current_actor.get()


@contextmanager
def use_actor(actor: "str | None"):
    """Set the current actor for the duration of the ``with`` block.

    Mutations performed inside the block are attributed to ``actor``; a document
    write-locked by a *different* actor is read-only within the block.

    Args:
        actor (str | None, required): The actor (view/session) id.

    Yields:
        str | None: The activated actor id.
    """
    token = _current_actor.set(actor)
    try:
        yield actor
    finally:
        _current_actor.reset(token)


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# OSCAL CLASS
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCAL:
    """Base class for all OSCAL model documents.

    Provides loading, saving, validation, format conversion (XML/JSON/YAML),
    import resolution, and query support shared by every OSCAL model. Content is
    held internally as a JSON-primary dict (``self._dict``) with an XML tree
    (``self._tree``) maintained for conversion. Do not instantiate directly; use
    the factory classmethods ``load``, ``loads``, or ``new``, or a model subclass.

        Attributes (Content Location):
            href_original: The original href as provided (e.g., in an import statement)
            is_valid_href: True if the href is accessible and the content was loaded successfully
            href         : Working href (may differ from href_original after redirect/retry)

        Attributes (Class States):
            is_valid    : True if the content passed OSCAL validation, False otherwise
            is_local    : True if the source is a local file, False if it's remote (http/https)
            is_cached   : True if remote content has a local cache copy, False otherwise
            is_canonical: True if this is canonical/published content; forces read-only
            is_read_only: True if the content may not be mutated (property; True whenever
                          is_canonical is set, else reflects the loader/caller flag)
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
        self.is_canonical: bool = False # canonical/published content — always read-only
        self._is_read_only: bool = True # backing store for the is_read_only property
        self.is_unsaved  : bool = True  # True when there are unsaved modifications

        # Caching and Expiration
        self.loaded: datetime = datetime.now() # Timestamp of when the content was loaded
        self.ttl: int = 0 # Seconds (0 or less = forever): Time to live for cached content

        # Content and Summary
        # self.original_content: str = "" # The raw content as a string in its original format
        self.original_format : str = ""
        self.model           : str = ""
        self.oscal_version   : str = ""
        self.uuid            : str = ""   # root document UUID (as loaded)
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
        # Object registry (identity map) — composite content-identity key captured at load,
        # shared instance used to dedup imports across the tree. Default is the process-global.
        self._identity: tuple | None = None
        self._registry = get_registry()
        self._workspace = None  # back-reference to the owning Workspace, if any

        # Validation Status
        self.validation_status: dict[str, bool | None] = {
            "well-formed":    None,  # content is parseable and OSCAL model/version is identified
            "structure":      None,  # all required fields and hierarchy are present
            "data-types":     None,  # every field/flag value matches its declared OSCAL datatype
            "allowed-values": None,  # every constrained value is within its enumerated set
            "cardinality":    None,  # all arrays satisfy their min-occurs/max-occurs bounds
            "choice":         None,  # every choice is mutually exclusive (at most one member) and has a member when one is required
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

    # -------------------------------------------------------------------------
    def _upgrade_to_model_class(self) -> "OSCAL":
        """Re-class a base ``OSCAL`` instance to its model subclass, if registered.

        The factory methods (``load``/``loads``/``acquire``) create a base ``OSCAL``
        because the model isn't known until the content is parsed. Once
        ``self.model`` is identified, this swaps ``__class__`` to the registered
        subclass (e.g. ``Catalog``) and runs its ``_init_common`` hook so
        subclass-specific attributes are set up. A no-op when already a subclass
        (e.g. ``Catalog.load``) or when the model is unregistered.

        Returns:
            OSCAL: ``self`` (possibly re-classed to a model subclass).
        """
        if type(self) is OSCAL:
            klass = _MODEL_REGISTRY.get(self.model)
            if klass is not None and klass is not OSCAL:
                self.__class__ = klass
                self._init_common()
        return self

    # -------------------------------------------------------------------------
    def _export_state(self) -> dict:
        """Return a JSON-serializable snapshot of derived state for persistence.

        Captures state that would otherwise have to be re-determined after a
        workspace save/reload — currently validation results and dirty-state.
        Subclasses override this (calling ``super()._export_state()``) to add their
        own derived attributes and, in future, computed indexes.

        Returns:
            dict: The persistable derived state.
        """
        return {
            "validation_status": self.validation_status,
            "validation_errors": self.validation_errors,
            "errors":            self.errors,
            "is_unsaved":        self.is_unsaved,
            "last_modified":     self.last_modified,
        }

    # -------------------------------------------------------------------------
    def _import_state(self, state: dict) -> None:
        """Restore derived state produced by :meth:`_export_state`.

        Args:
            state (dict, required): The persisted state dict (may be empty).
        """
        if not state:
            return
        self.validation_status = state.get("validation_status", self.validation_status)
        self.validation_errors = state.get("validation_errors", [])
        self.errors = state.get("errors", {})
        self.is_unsaved = state.get("is_unsaved", self.is_unsaved)
        self.last_modified = state.get("last_modified", self.last_modified)

    # =========================================================================
    # Content state properties (progressive — each implies all prior levels passed)
    @property
    def is_acquired(self) -> bool:
        """bool: True once content has been acquired (``content_state >= ACQUIRED``)."""
        return self.content_state >= ContentState.ACQUIRED

    # -------------------------------------------------------------------------
    @property
    def is_well_formed(self) -> bool:
        """bool: True when content is well-formed (``content_state >= WELL_FORMED``)."""
        return self.content_state >= ContentState.WELL_FORMED

    # -------------------------------------------------------------------------
    @property
    def is_valid(self) -> bool:
        """bool: True when content passes OSCAL validation (``content_state >= VALID``)."""
        return self.content_state >= ContentState.VALID

    # -------------------------------------------------------------------------
    @property
    def imports_resolved(self) -> bool:
        """bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``)."""
        return self.content_state >= ContentState.IMPORTS_RESOLVED

    # -------------------------------------------------------------------------
    @classmethod
    def loads(cls, content: str | dict, *, href: str | None = None):
        """Initialize an instance from in-memory OSCAL content.

        Args:
            content (str | dict, required): OSCAL content already in memory, as a
                serialized string or a dict.
            href (str | None, optional): URI identifying the original content
                source. Keyword-only. Defaults to None.

        Returns:
            OSCAL: A new instance populated from the content.
        """
        instance = cls.__new__(cls)
        instance.__init_common__()
        instance._origin       = "loads"
        instance.href_original = href if href else ""

        normalized_content = json.dumps(content) if isinstance(content, dict) else content
        if instance.initial_validation(normalized_content):
            instance.is_read_only = False

        return instance._upgrade_to_model_class()

    # -------------------------------------------------------------------------
    @classmethod
    def load(cls, source: str | os.PathLike | _ReadableSource, *, href: str | None = None):
        """Initialize an instance from a local file path or file-like object.

        Aligns with Python's conventional ``load(...)`` behavior. Use ``loads(...)``
        for in-memory strings/dicts, and ``acquire(...)`` for URI/reference
        resolution and fallback sources.

        Args:
            source (str | os.PathLike | file-like, required): A filesystem path or an
                object with a ``read()`` method.
            href (str | None, optional): URI label identifying the source; defaults to
                the path or the object's ``name``. Keyword-only. Defaults to None.

        Returns:
            OSCAL: A new instance populated from the loaded content.

        Raises:
            TypeError: If ``source`` is neither path-like nor file-like.
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

        return instance._upgrade_to_model_class()

    # -------------------------------------------------------------------------
    @classmethod
    def acquire(cls, source: str | dict | OscalRef | list, *, cache: "CacheDirective | None" = None):
        """
        Acquire OSCAL content from one or more URI/reference sources.

        The sources are treated as an ordered fallback list; the first that
        resolves successfully is used.

        Args:
            source (str | dict | OscalRef | list, required): The reference(s) to
                acquire. May be a URI/path string, an ``OscalRef``, a reference dict
                containing at least ``"href"``, or a list mixing any of these.
            cache (CacheDirective | None, optional): Caching directive applied to
                remote fetches (e.g. ``CacheDirective.never()``,
                ``CacheDirective.refresh_now()``). Keyword-only. Defaults to the
                standard 24h behavior.

        Returns:
            OSCAL: A new instance populated from the first resolvable source.
        """

        instance = cls.__new__(cls)
        instance.__init_common__()
        instance._origin       = "acquire"
        instance._refs = _normalize_refs(source)

        instance.href_original = instance._refs[0].href if instance._refs else ""
        content = load_content(instance._refs, cache_directive=cache)
        instance.initial_validation(content)
        return instance._upgrade_to_model_class()

    # -------------------------------------------------------------------------
    @classmethod
    def from_string(cls, content: str, *, href: str | None = None):
        """Explicit constructor for in-memory OSCAL string content.

        Args:
            content (str, required): Serialized OSCAL content.
            href (str | None, optional): URI identifying the source. Keyword-only.
                Defaults to None.

        Returns:
            OSCAL: A new instance (delegates to :meth:`loads`).
        """
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
            source (str | os.PathLike | dict | OscalRef | list | file-like, required):
                Any supported OSCAL source. String values with a URI scheme are
                acquired; bare paths and file-like objects are loaded.
            href (str | None, optional): URI label passed through to ``load()`` when
                applicable. Keyword-only. Defaults to None.

        Returns:
            OSCAL: A new instance from the appropriate loader.
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

        Must be called on a specific model class (``Catalog.new()``,
        ``Profile.new()``, etc.), not on ``OSCAL`` directly.

        Args:
            title (str, required): Document title (stored in metadata).
            version (str, optional): Document version (stored in metadata).
                Defaults to "".
            published (str, optional): Publication date (stored in metadata).
                Defaults to "".

        Returns:
            OSCAL: A new editable instance of the model subclass.

        Raises:
            TypeError: If called on the ``OSCAL`` base class instead of a subclass.
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
            filename (str, optional): Path to write to. Defaults to the original
                source location when empty.
            format (str, optional): Output format — one of ``OSCAL_FORMATS``
                ("xml", "json", "yaml", "yml"). Defaults to the original format when empty.
            pretty_print (bool, optional): Whether to pretty-print the output.
                Defaults to False.

        Returns:
            bool: True if the write succeeded, False otherwise.
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
    def _import_entry_view(self, entry: dict) -> dict:
        """Safe copy of an import_list entry, shaped like an import_tree node.

        The live ``object`` is replaced by ``object_uuid`` plus the six object-summary
        fields (see :attr:`import_tree` for the full field schema); only the recursive
        ``imports`` key is omitted, since these are flat entry lists. Callers cannot
        mutate resolution state through the copy, and the (potentially large) imported
        documents stay out of the payload; use :meth:`get_oscal_object` with
        ``object_uuid`` to obtain the live document when one is actually needed.
        """
        obj = entry.get("object")
        view = {k: v for k, v in entry.items() if k != "object"}
        view["object_uuid"] = obj.uuid if obj is not None else None
        view.update(self._object_summary(obj))
        return copy.deepcopy(view)

    # -------------------------------------------------------------------------
    @property
    def failed_imports(self) -> list[dict]:
        """Return import_list entries that failed, each carrying a populated 'failure' field.

        These are blocking: while any failed import remains, content_state stays
        at VALID and imports_resolved is False.

        Each entry is a safe copy shaped like an :attr:`import_tree` node (same field
        schema, but a flat list without the recursive ``imports`` key). Exception: a
        failed import never acquires its document, so for every entry here ``object_uuid``
        is always ``None`` and the six summary fields (``model``, ``title``,
        ``oscal_version``, ``version``, ``published``, ``last_modified``) are always ``""``.
        """
        return [self._import_entry_view(e) for e in self.import_list if e.get("failure") is not None]

    # -------------------------------------------------------------------------
    @property
    def duplicate_imports(self) -> list[dict]:
        """Return import_list entries detected as duplicates of an earlier import.

        Duplicates are non-blocking — they do NOT prevent imports_resolved from
        becoming True — but they remain available for the caller to act on via
        retry_import (supply a different source), ignore_import, or remove_import.

        Each entry is a safe copy shaped like an :attr:`import_tree` node (same field
        schema, but a flat list without the recursive ``imports`` key). Exception: a
        duplicate entry holds no document of its own (the original READY entry carries
        it), so for every entry here ``object_uuid`` is always ``None`` and the six
        summary fields (``model``, ``title``, ``oscal_version``, ``version``,
        ``published``, ``last_modified``) are always ``""``.
        """
        return [self._import_entry_view(e) for e in self.import_list
                if e.get("status") == ImportState.DUPLICATE]

    # -------------------------------------------------------------------------
    @property
    def unresolved_imports(self) -> list[dict]:
        """Return import_list entries that still warrant user attention.

        Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
        READY (resolved) and IGNORED (explicitly dismissed by the caller).

        This is the signal a UI should use to decide whether to keep showing
        import-resolution affordances.  It stays non-empty while there is still
        something the user can act on — even when ``imports_resolved`` is already
        True because the only remaining items are non-blocking duplicates.
        Once every entry is READY or IGNORED, this list is empty and the
        resolution UI can close.

        Each entry is a safe copy shaped like an :attr:`import_tree` node (same field
        schema, but a flat list without the recursive ``imports`` key). Exception:
        unresolved entries (failed or duplicate) never carry a loaded document, so for
        every entry here ``object_uuid`` is always ``None`` and the six summary fields
        (``model``, ``title``, ``oscal_version``, ``version``, ``published``,
        ``last_modified``) are always ``""``.
        """
        actionable = (ImportState.INVALID, ImportState.DUPLICATE)
        return [self._import_entry_view(e) for e in self.import_list
                if e.get("status") in actionable]

    # -------------------------------------------------------------------------
    def retry_import(self, failed_href: str, replacement_href: str) -> bool:
        """Retry a failed import identified by href, using a replacement source.

        The failed import is matched by href (original or previously resolved),
        then re-attempted using ``replacement_href`` (resolved relative to this
        document's location).

        Args:
            failed_href (str, required): The href of the failed import to retry.
            replacement_href (str, required): The replacement href to attempt.

        Returns:
            bool: True if the import was successfully resolved on retry, False otherwise.
        """
        if not failed_href or not replacement_href:
            logger.warning("retry_import requires both failed_href and replacement_href.")
            return False

        candidates = _find_import_candidates(self.import_list, failed_href)
        if not candidates:
            logger.warning(f"Failed import href '{failed_href}' not found. Cannot retry.")
            return False
        target_entry = _pick_import_target(candidates)

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

        # Reject immediately if the replacement resolves to a file already held by a
        # different READY import.  The target_entry itself is excluded from the check
        # so that retrying with the same file that was previously successful (e.g.
        # restoring an entry after it was accidentally overwritten) is not blocked.
        already_loaded: set[str] = {
            e["href_valid"]
            for e in self.import_list
            if e.get("status") == ImportState.READY
            and e is not target_entry
            and e.get("href_valid")
        }
        if resolved in already_loaded:
            retry_item: dict = {"href": resolved, "original": False, "status": ImportState.INVALID}
            target_entry["href_valid"] = ""
            target_entry["object"]     = None
            target_entry["is_valid"]   = False
            target_entry["status"]     = ImportState.INVALID
            target_entry["failure"]    = ImportFailure(
                code=ImportFailureCode.ALREADY_IMPORTED,
                href_original=target_entry.get("href_original", failed_href),
                uri=resolved,
                message=f"'{resolved}' is already loaded by another import in this document.",
            )
            target_entry.setdefault("href_list", []).append(retry_item)
            self._import_tree = None
            self._refresh_content_state()
            return False

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
        self._import_tree = None
        self._refresh_content_state()
        return target_entry["status"] == ImportState.READY

    # -------------------------------------------------------------------------
    def retry_imports(self, failed_href: str, replacement_href: str) -> bool:
        """Compatibility alias for :meth:`retry_import` (plural method name).

        Args:
            failed_href (str, required): The href of the failed import to retry.
            replacement_href (str, required): The replacement href to attempt.

        Returns:
            bool: True if the import was successfully resolved on retry, False otherwise.
        """
        return self.retry_import(failed_href, replacement_href)

    # -------------------------------------------------------------------------
    def _refresh_content_state(self) -> None:
        """Recompute content_state after import_list has been mutated.

        Advances to IMPORTS_RESOLVED when no INVALID entries remain.
        Reverts to VALID when an entry that was previously resolved has become INVALID.
        DUPLICATE and IGNORED entries are treated as non-blocking.
        """
        has_invalid = any(e.get("status") == ImportState.INVALID for e in self.import_list)
        if self.is_valid and not has_invalid:
            self.content_state = ContentState.IMPORTS_RESOLVED
        elif self.content_state >= ContentState.IMPORTS_RESOLVED:
            self.content_state = ContentState.VALID

    # -------------------------------------------------------------------------
    def ignore_import(self, href: str) -> bool:
        """Mark an import as intentionally ignored.

        The entry remains in import_list with status IGNORED.  Like DUPLICATE,
        IGNORED entries are treated as non-blocking: once all remaining entries
        are READY, DUPLICATE, or IGNORED, content_state advances to
        IMPORTS_RESOLVED.

        Typical use: the caller presents a DUPLICATE entry to the user and the
        user explicitly chooses to ignore it rather than supply a replacement.

        The same priority ordering used by retry_import applies when multiple
        entries share the same href — DUPLICATE and INVALID are preferred over
        READY.

        Args:
            href: Any href that identifies the entry (href_original, href_valid,
                  failure.uri, or an href_list item href).

        Returns:
            True if an entry was found and updated, False if no match was found.
        """
        candidates = _find_import_candidates(self.import_list, href)
        if not candidates:
            logger.warning(f"ignore_import: href '{href}' not found in import_list.")
            return False

        target = _pick_import_target(candidates)
        target["status"]  = ImportState.IGNORED
        target["failure"] = None

        # Update the cached tree node in-place rather than discarding the tree.
        # import_list[i] corresponds to import_tree["imports"][i], so the index
        # is the reliable key.
        if self._import_tree is not None:
            idx = self.import_list.index(target)
            tree_imports = self._import_tree.get("imports", [])
            if idx < len(tree_imports):
                tree_imports[idx]["status"]  = ImportState.IGNORED
                tree_imports[idx]["failure"] = None

        self._refresh_content_state()
        logger.info(f"ignore_import: '{href}' marked as IGNORED.")
        return True

    # -------------------------------------------------------------------------
    def remove_import(self, href: str) -> bool:
        """Remove an import entry from both import_list and the document content.

        The import *statement* is deleted from ``self._dict``, placing the
        document in an edited and unsaved state.  Any back-matter resource
        referenced by the import via a URI fragment (``href="#uuid"``) is
        intentionally preserved — only the import element itself is removed.

        The cached import_tree is updated in-place (same object, one node
        shorter).  content_state is recomputed: if the removed entry was the
        last thing blocking resolution, content_state advances to
        IMPORTS_RESOLVED.

        The same priority ordering used by retry_import applies when multiple
        entries share the same href — DUPLICATE and IGNORED are preferred over
        INVALID which is preferred over READY — so the problematic entry is
        always targeted.

        Args:
            href: Any href that identifies the entry (href_original, href_valid,
                  failure.uri, or an href_list item href).

        Returns:
            True if an entry was found and removed, False if not found or the
            content is read-only.
        """
        if not self._can_mutate("remove_import"):
            return False

        candidates = _find_import_candidates(self.import_list, href)
        if not candidates:
            logger.warning(f"remove_import: href '{href}' not found in import_list.")
            return False

        target = _pick_import_target(candidates)
        idx = self.import_list.index(target)

        # Remove the import statement from the dict first, while import_list
        # is still intact so _remove_import_from_dict can count preceding
        # entries to identify which dict occurrence to remove.
        dict_removed = _remove_import_from_dict(self._dict, self.model, self.import_list, target)
        if not dict_removed:
            logger.warning(
                f"remove_import: import statement for '{target.get('href_original')}' "
                "could not be located in document content."
            )

        # Update the cached tree in-place before removing from import_list.
        if self._import_tree is not None:
            tree_imports = self._import_tree.get("imports", [])
            if idx < len(tree_imports):
                tree_imports.pop(idx)

        self.import_list.remove(target)

        if dict_removed:
            self.is_unsaved = True

        self._refresh_content_state()
        logger.info(f"remove_import: '{target.get('href_original')}' removed.")
        return True

    # -------------------------------------------------------------------------
    def _identity_key(self) -> tuple | None:
        """Return this document's composite content-identity key, or None.

        The key is ``(root-uuid, last-modified, published)``, captured during
        :meth:`initial_validation`. Two objects with the same key are the same
        content revision regardless of format or location. Returns None when the
        root UUID is unavailable (the object then does not participate in dedup).

        Returns:
            tuple | None: The identity key, or None.
        """
        return self._identity

    # -------------------------------------------------------------------------
    def _acquire_shared(self, resolved: str, cache_directive: "CacheDirective | None" = None) -> "OSCAL":
        """Load — or reuse from the registry — the OSCAL object for a resolved href.

        Checks the object registry by canonical href first (reuses without a fetch);
        on a miss, loads via :meth:`acquire`, and if the loaded content matches an
        already-registered content identity (e.g. the same catalog reached by a
        different href or format), reuses that instance and drops the freshly loaded
        duplicate. Newly loaded, identity-bearing objects are registered.

        A ``refresh`` or ``CACHE_NEVER`` cache directive **bypasses the in-memory
        registry** (both the href fast-path and identity dedup) so the content is
        genuinely reloaded (hitting the disk cache with the directive); the freshly
        loaded object then replaces the registry entry.

        Args:
            resolved (str, required): The resolved (absolute) href to load.
            cache_directive (CacheDirective | None, optional): Caching directive
                applied to the fetch. Defaults to the standard 24h behavior.

        Returns:
            OSCAL: The shared or newly loaded object.

        Raises:
            ImportLoadError: Propagated from :meth:`acquire` when the content cannot
                be loaded.
        """
        canonical = _canonicalize_ref(resolved)
        # A refresh/never directive must reload the content, so it bypasses the
        # in-memory registry (both the href fast-path and identity dedup below).
        force_reload = cache_directive is not None and (
            cache_directive.refresh or cache_directive.ttl == CACHE_NEVER
        )

        if not force_reload:
            hit = self._registry.get(href=canonical)
            if hit is not None:
                logger.debug(f"registry: reusing object for '{canonical}' (href hit).")
                return hit

        child = OSCAL.acquire(resolved, cache=cache_directive)
        child._registry = self._registry

        if child.is_valid:
            key = child._identity_key()
            if key is not None:
                if not force_reload:
                    existing = self._registry.get(key=key)
                    if existing is not None:
                        logger.info(
                            f"registry: '{canonical}' is the same content as an "
                            "already-loaded object (identity hit) — reusing."
                        )
                        self._registry.alias_href(canonical, existing)
                        return existing
                self._registry.register(child, key=key, href=canonical)
            else:
                logger.debug(f"registry: '{canonical}' has no identity key; not deduped.")
        return child

    # -------------------------------------------------------------------------
    def resolve_imports(self, base_path: str = "", *, cache_directive: "CacheDirective | None" = None) -> list:
        """
        Discover and load every OSCAL document referenced by this document's
        import declarations.  Populates (and returns) self.import_list.

        Because ``validate()`` resolves imports, loading a document cascades this
        depth-first down the whole import tree. Two guards prevent runaway on shared
        or circular graphs: the object registry ensures a file loaded via multiple
        branches (a diamond) is held once, and an import that resolves back to an
        ancestor still being resolved (a cycle) is marked ``ImportState.CYCLIC`` and
        not loaded — the ancestor stays valid and recursion stops there.

        A ``cache_directive`` is applied to this document's direct imports; a
        ``refresh`` or ``CACHE_NEVER`` directive bypasses the in-memory registry so
        the imported content is genuinely reloaded rather than reused.

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
            base_path (str, optional): Directory used to resolve relative hrefs.
                Defaults to the directory of this document's own href.
            cache_directive (CacheDirective | None, optional): Caching directive
                applied to this document's direct import fetches. Keyword-only.
                Defaults to the standard 24h behavior.

        Returns:
            list[dict]: self.import_list, one entry per discovered reference.
        """
        self_canonical = _canonicalize_ref(self.href or self.href_original)
        self._registry.enter_resolving(self_canonical)
        try:
            return self._resolve_imports_inner(base_path, cache_directive)
        finally:
            self._registry.exit_resolving(self_canonical)

    # -------------------------------------------------------------------------
    def _resolve_imports_inner(self, base_path: str = "", cache_directive: "CacheDirective | None" = None) -> list:
        """Core of :meth:`resolve_imports`, wrapped for cycle-stack management."""
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
        loaded_hrefs: set[str] = set()  # tracks resolved hrefs already loaded this pass
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
            cyclic = False

            for item in entry["href_list"]:
                if item["href"].startswith("#"):
                    continue
                primary  = _resolve_href(base_path, item["href"])
                attempts = [primary] + [_resolve_href(base_path, v) for v in _oscal_format_variants(item["href"])]
                for resolved in attempts:
                    # Cycle guard: this href resolves to an ancestor still being resolved
                    # higher on the stack. Flag CYCLIC and do not load (avoids a loop).
                    if self._registry.is_resolving(_canonicalize_ref(resolved)):
                        cyclic = True
                        entry["href_valid"] = resolved
                        break
                    rlinks_tried.append(resolved)
                    try:
                        child = self._acquire_shared(resolved, cache_directive)
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
                if cyclic or entry["status"] == ImportState.READY:
                    break

            if cyclic:
                entry["status"] = ImportState.CYCLIC
                logger.info(
                    f"resolve_imports: '{raw_href}' resolves to an ancestor still being "
                    f"resolved ('{entry['href_valid']}') — marking CYCLIC."
                )
            elif entry["status"] != ImportState.READY:
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

            else:
                # Loaded successfully — check whether this resolved href was already loaded
                # by an earlier import in this same document.  If so, mark DUPLICATE and
                # release the object rather than holding a second reference.
                if entry["href_valid"] in loaded_hrefs:
                    entry["status"]    = ImportState.DUPLICATE
                    entry["object"]    = None
                    entry["is_valid"]  = False
                    entry["is_local"]  = None
                    entry["is_remote"] = None
                    entry["is_cached"] = False
                    logger.info(
                        f"resolve_imports: '{raw_href}' resolves to already-imported "
                        f"'{entry['href_valid']}' — marking DUPLICATE."
                    )
                else:
                    loaded_hrefs.add(entry["href_valid"])

            self.import_list.append(entry)

        logger.info(
            f"resolve_imports: {len(self.import_list)} reference(s) found in '{self.model}'."
        )

        failed = sum(1 for e in self.import_list if e["status"] == ImportState.INVALID)
        if self.content_state >= ContentState.VALID and failed == 0:
            self.content_state = ContentState.IMPORTS_RESOLVED

        return self.import_list

    # -------------------------------------------------------------------------
    @staticmethod
    def _object_summary(obj: "OSCAL | None") -> dict:
        """Summary metadata for an imported object, embedded in each import-tree node.

        Because the tree no longer carries the live object, it surfaces the key
        identifying fields the caller would otherwise reach through it. Populated only
        when the object was successfully acquired; otherwise every value is an empty
        string. ``oscal_version`` is the clean OSCAL version (the internal ``v`` prefix
        on ``OSCAL.oscal_version`` is stripped) to match the raw ``version``/``published``
        values.
        """
        if obj is None:
            return {"model": "", "title": "", "oscal_version": "",
                    "version": "", "published": "", "last_modified": ""}
        oscal_version = obj.oscal_version[1:] if obj.oscal_version.startswith("v") else obj.oscal_version
        return {
            "model":         obj.model,
            "title":         obj.title,
            "oscal_version": oscal_version,
            "version":       obj.version,
            "published":     obj.published,
            "last_modified": obj.last_modified,
        }

    # -------------------------------------------------------------------------
    def _build_import_tree_recursive(self, _path: frozenset | None = None) -> list:
        """Walk import_list recursively and return a nested tree of import nodes.

        Each node is a copy of the flat import_list entry with the live ``object``
        replaced by ``object_uuid`` plus the summary fields from
        :meth:`_object_summary`, and an added ``imports`` key holding the same
        structure for that child's own imports. See :attr:`import_tree` for the full
        node schema. Path-based cycle detection prevents infinite recursion on
        circular refs.
        """
        if _path is None:
            _path = frozenset()

        result = []
        for entry in self.import_list:
            child: OSCAL | None = entry.get("object")
            # The tree carries only the object's UUID, never the live OSCAL object —
            # keeping the (potentially large) documents out of the serialized tree.
            # Use get_oscal_object(uuid) to fetch the live instance when needed.
            node = {k: v for k, v in entry.items() if k != "object"}
            node["object_uuid"] = child.uuid if child is not None else None
            node.update(self._object_summary(child))
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

        Returns a root node dict representing this document, with an ``imports`` key
        holding the first-level imports; each import is a node of the same shape,
        recursively. The tree is a SAFE COPY of the cached structure — mutating it does
        not affect the cache; use :meth:`rebuild_import_tree` to force a fresh traversal.

        The tree carries no live OSCAL objects, so it stays small and safe to
        serialize/transmit. Instead, each node identifies its document by UUID and
        summary metadata; call :meth:`get_oscal_object` with ``object_uuid`` to obtain
        the live instance when one is actually needed.

        Each node (root and every import) has these keys:

        * ``href_original`` (str): the import href as written in the source document.
        * ``href_valid`` (str): the resolved href actually loaded, if any.
        * ``href_list`` (list[dict]): every href attempted, with per-attempt status.
        * ``status`` (ImportState): READY, INVALID, DUPLICATE, or IGNORED.
        * ``is_valid`` / ``is_local`` / ``is_remote`` / ``is_cached`` (bool): provenance.
        * ``object_uuid`` (str | None): the imported document's root UUID, or None when
          it was not acquired. Pass to :meth:`get_oscal_object` for the live object.
        * ``model`` (str): the imported document's model type (e.g. "catalog").
        * ``title`` (str): the imported document's metadata title.
        * ``oscal_version`` (str): the OSCAL version (no ``v`` prefix, e.g. "1.1.3").
        * ``version`` (str): the document's own metadata version.
        * ``published`` (str): the metadata publication timestamp (RFC-3339), if present.
        * ``last_modified`` (str): the metadata last-modified timestamp (RFC-3339).
        * ``failure`` (ImportFailure | None): the failure record when ``status`` is
          INVALID, else None.
        * ``imports`` (list[dict]): child import nodes (empty when none or unacquired).

        The six summary fields (``model``, ``title``, ``oscal_version``, ``version``,
        ``published``, ``last_modified``) are populated only when the object was
        successfully acquired; otherwise each is an empty string ``""``.

        This is the single source of truth for the node/entry field schema. The import
        getters :attr:`failed_imports`, :attr:`duplicate_imports`, and
        :attr:`unresolved_imports` return these same per-entry fields as flat lists
        (without the recursive ``imports`` key). Note that those getters only ever hold
        failed or duplicate entries, which carry no loaded document — so in their results
        ``object_uuid`` is always ``None`` and the six summary fields are always ``""``.
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
                "object_uuid":   self.uuid,
                **self._object_summary(self if self.is_acquired else None),
                "failure":       None,
                "imports":       self._build_import_tree_recursive(),
            }
        return copy.deepcopy(self._import_tree)

    # -------------------------------------------------------------------------
    def rebuild_import_tree(self) -> dict:
        """Discard the cached import tree and rebuild it from the current import_list.

        Returns:
            dict: The freshly built root node of the recursive import tree.
        """
        self._import_tree = None
        return self.import_tree

    # -------------------------------------------------------------------------
    def _import_base_path(self) -> str:
        """Base directory (or base URL) used to resolve this document's relative import hrefs.

        Mirrors the base-path logic in :meth:`resolve_imports`.

        Returns:
            str: The directory of this document's own href, or the current working
                directory when the document has no source location.
        """
        src = self.href or self.href_original
        if src:
            parsed = urlparse(src)
            if parsed.scheme and len(parsed.scheme) > 1:
                return src.rsplit("/", 1)[0] + "/"
            return os.path.dirname(os.path.abspath(src))
        return os.getcwd()

    # -------------------------------------------------------------------------
    def _resolve_import_href(self, href: str) -> str:
        """Resolve a (possibly relative) import href against this document's base path.

        Args:
            href (str, required): The href to resolve.

        Returns:
            str: The resolved absolute path or URL.
        """
        return _resolve_href(self._import_base_path(), href)

    # -------------------------------------------------------------------------
    @property
    def is_remote(self) -> bool:
        """bool: True when the content originates from a remote source (not a local file)."""
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
    def is_read_only(self) -> bool:
        """bool: True when the content may not be mutated (most-restrictive-wins).

        Read-only when any of these hold: the underlying writable flag is set,
        the content is canonical/published (``is_canonical``), or the document is
        write-locked by a *different* actor in its workspace (see
        :meth:`_locked_by_other`). Because every mutation gate checks this property,
        canonical status and workspace locks are enforced uniformly.
        """
        return self._is_read_only or self.is_canonical or self._locked_by_other()

    @is_read_only.setter
    def is_read_only(self, value: bool) -> None:
        self._is_read_only = bool(value)

    # -------------------------------------------------------------------------
    def _locked_by_other(self) -> bool:
        """Return True when this document is write-locked by a different actor.

        Consults the owning workspace's lock manager (if any) against the current
        actor (:func:`current_actor`). Always False for documents not owned by a
        workspace, or when no lock is held, or when the current actor holds the lock.

        Returns:
            bool: True when another actor holds the write lock.
        """
        ws = self._workspace
        if ws is None:
            return False
        try:
            holder = ws.lock_holder(self)
        except Exception:
            return False
        return holder is not None and holder != current_actor()

    # -------------------------------------------------------------------------
    @property
    def is_editable(self) -> bool:
        """Can this content be modified?"""
        return self.content_state >= ContentState.VALID and self.is_local and not self.is_read_only

    # -------------------------------------------------------------------------
    def initial_validation(self, content: str) -> bool:
        """
        Perform initial validation of content and advance the content state.

        Detects the format, checks that the content is a recognized, well-formed
        OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
        summary metadata, then invokes full OSCAL schema validation. Updates
        ``self.content_state`` progressively as each stage passes.

        Args:
            content (str, required): The raw OSCAL content to validate.

        Returns:
            bool: True if initial validation is successful, False otherwise.
        """
        logger.debug("Performing initial validation of content...")
        self.content_state = ContentState.NONE   # reset for each validation attempt
        status = False
        oscal_root = ""
        oscal_version = ""

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
                    # Only the model (root element) and OSCAL version are read from XML here —
                    # both are required to select the metaschema converter below. All summary
                    # metadata is populated after XML→JSON conversion so it carries the JSON
                    # (CommonMark) text form; the XML tree is consulted only as a fallback if
                    # conversion fails (see _populate_summary_from_tree).
                    oscal_root = xpath_atomic(self._tree, _NSMAP, "/*/name()")
                    oscal_version = "v" + xpath_atomic(self._tree, _NSMAP, "/*/metadata/oscal-version/text()")
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
        if status and self.original_format == "xml":
            converter = OSCALConverter.from_support(self.model, self.oscal_version, self._support)
            if converter is not None:
                xml_string = self._xml_serializer()
                json_string = converter.xml_to_json(xml_string)
                if json_string is not None:
                    self._dict = json.loads(json_string)
                    logger.debug("XML source converted to dict.")
                else:
                    logger.warning("XML→dict conversion failed; dict-based manipulation unavailable.")
            else:
                logger.warning(f"No metaschema converter for {self.model} {self.oscal_version}; dict unavailable.")

        # Populate summary metadata attributes. Normal path: from the converted JSON dict, so all
        # text — including the markup fields title and remarks — keeps its JSON (CommonMark) form.
        # Once the dict is authoritative the parsed XML tree is released (rebuildable on demand via
        # _build_tree()). Fallback: if conversion did not produce a dict, read from the XML tree so
        # error reports stay as complete as possible; markup fields are converted to CommonMark there
        # too, so title/remarks always hold Markdown regardless of path.
        if status:
            if self._dict is not None:
                self._populate_summary_from_dict()
                if self.original_format == "xml":
                    self._tree = None
                    logger.debug("XML tree released after summary extraction.")
            elif self._tree is not None:
                logger.warning("Populating summary metadata from XML tree (conversion unavailable).")
                self._populate_summary_from_tree()

        if status and self._dict is not None:
            self.validate(format="json")

        return status

    # -------------------------------------------------------------------------
    def _populate_summary_from_dict(self) -> None:
        """Populate summary metadata attributes from the JSON dict (``self._dict``).

        This is the normal path used for every successfully-parsed document (JSON/YAML
        sources, and XML sources after XML→JSON conversion). All text — including the
        markup fields ``title`` and ``remarks`` — is taken verbatim from the JSON, so it
        keeps its OSCAL CommonMark (Markdown) form. Also builds the composite
        content-identity key used by the object registry.
        """
        root_obj = self._dict.get(self.model, {}) if isinstance(self._dict, dict) else {}
        metadata = root_obj.get('metadata', {}) if isinstance(root_obj, dict) else {}
        self.title         = metadata.get('title', '')
        self.version       = metadata.get('version', '')
        self.published     = metadata.get('published', '')
        self.last_modified = metadata.get('last-modified', '')
        self.remarks       = metadata.get('remarks', '')
        self.uuid          = root_obj.get('uuid', '') if isinstance(root_obj, dict) else ''
        # Composite content-identity key for the object registry: same tuple means the
        # same content revision regardless of format or location.
        self._identity = (self.uuid, self.last_modified, self.published) if self.uuid else None

    # -------------------------------------------------------------------------
    def _populate_summary_from_tree(self) -> None:
        """Fallback: populate summary metadata attributes from the XML tree (``self._tree``).

        Used only when XML→JSON conversion did not produce a dict, so that error reports
        remain as complete as possible. The markup fields ``title`` (markup-line) and
        ``remarks`` (markup-multiline) are converted to OSCAL CommonMark so the attributes
        always hold Markdown, consistent with the normal path. Plain-value fields are read
        as text.
        """
        self.title         = self._markup_from_tree("title", "markup-line")
        self.version       = xpath_atomic(self._tree, _NSMAP, "/*/metadata/version/text()")
        self.published     = xpath_atomic(self._tree, _NSMAP, "/*/metadata/published/text()")
        self.last_modified = xpath_atomic(self._tree, _NSMAP, "/*/metadata/last-modified/text()")
        self.remarks       = self._markup_from_tree("remarks", "markup-multiline")
        self.uuid          = xpath_atomic(self._tree, _NSMAP, "/*/@uuid")
        self._identity = (self.uuid, self.last_modified, self.published) if self.uuid else None

    # -------------------------------------------------------------------------
    def _markup_from_tree(self, field: str, datatype: str) -> str:
        """Return metadata markup field ``field`` from the XML tree as OSCAL CommonMark.

        Locates ``/*/metadata/<field>`` in ``self._tree`` and converts its markup content
        to Markdown via :func:`_markup_to_md`. Returns ``""`` when the element is absent.
        """
        element = self._tree.find(f"{{*}}metadata/{{*}}{field}")
        if element is None:
            return ""
        return _markup_to_md(element, datatype)

    # -------------------------------------------------------------------------
    def validate(self, format: str = "") -> bool:
        """Validate OSCAL content against the metaschema index in sequenced phases.

        Phases (each recorded in ``validation_status``):
          structure      – all required fields and hierarchy are present
          data-types     – every leaf value matches its declared OSCAL datatype
          allowed-values – every constrained value is within its enumerated set
          cardinality    – every array satisfies its min-occurs/max-occurs bounds
          choice         – every choice is mutually exclusive (at most one member present) and has a member when one is required

        ``validation_status["well-formed"]`` is set by ``initial_validation()``, not here.
        All phases always run regardless of earlier failures, giving a complete picture
        of issues in a single call.  The format argument is accepted for API
        compatibility but does not alter the validation path — ``_dict`` is always the
        authoritative representation.

        Returns True only when every phase passes (content_state reaches VALID).
        """
        for phase in ("structure", "data-types", "allowed-values", "cardinality", "choice"):
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
            for phase in ("structure", "data-types", "allowed-values", "cardinality", "choice"):
                self.validation_status[phase] = True
            self.content_state = ContentState.VALID
            if self.content_state < ContentState.IMPORTS_RESOLVED:
                self.resolve_imports()
            return True

        model_nodes  = index.get("nodes")
        model_instance = self._dict.get(self.model)

        if not isinstance(model_instance, dict) or model_nodes is None:
            logger.warning("Cannot locate model root or index nodes; treating all phases as passed.")
            for phase in ("structure", "data-types", "allowed-values", "cardinality", "choice"):
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
        choice_errors      = [e for e in errors if e["error-type"] == "choice"]

        self.validation_status["structure"]      = (len(struct_errors)      == 0)
        self.validation_status["data-types"]     = (len(dtype_errors)       == 0)
        self.validation_status["allowed-values"] = (len(av_errors)          == 0)
        self.validation_status["cardinality"]    = (len(cardinality_errors) == 0)
        self.validation_status["choice"]         = (len(choice_errors)      == 0)
        self.validation_errors = errors

        for e in errors:
            logger.debug(
                f"[{e['error-type']}] {e.get('location', '')} "
                f"field={e.get('field', '')} value={e.get('value')!r}"
            )

        _phases = ("structure", "data-types", "allowed-values", "cardinality", "choice")
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
          ``choice``            – a choice has more than one member present (mutually exclusive), or none where one is required

        All error types are collected in a single pass so that ``validate()`` can
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

        # ------------------------------------------------------------------
        # Choice groups: mutually exclusive members (at most one), and a member
        # required when every member is min-occurs="1"
        # ------------------------------------------------------------------
        for choice_node in (c for c in children if c.get("structure-type") == "choice"):
            self._check_choice(instance, choice_node, errors, location)

    # -------------------------------------------------------------------------
    def _check_choice(self, instance: dict, choice_node: dict,
                      errors: list[dict], location: str) -> None:
        """Enforce a metaschema ``choice``: mutually exclusive use of its members.

        Per the Metaschema specification, a ``choice`` "permits the mutually exclusive
        use of a non-empty set of named model instances." So **at most one** of its
        members (branches) may be present. This holds regardless of a member's
        ``max-occurs``: ``max-occurs`` bounds how many items may appear *within* the
        chosen branch (validated by that member's own array cardinality), not whether
        branches may be combined. Present-ness is therefore counted per distinct member
        key, not by summing array lengths.

        Whether a selection is *required* is derived from the members: when every
        member is ``min-occurs="1"`` a branch must be chosen (e.g. profile ``merge`` →
        one of flat/as-is/custom; ``timing`` → one of on-date/within-date-range/
        at-frequency), so zero branches present is an error. When some member is
        ``min-occurs="0"`` the choice is optional (e.g. a ``param`` with neither
        ``values`` nor ``select``, or an empty catalog ``group``), so zero is allowed.

        Nested choices are flattened into the same mutually-exclusive group.

        Args:
            instance (dict, required): The JSON object that owns the choice.
            choice_node (dict, required): The index node of structure-type ``"choice"``.
            errors (list, required): Accumulator for ``"choice"`` errors.
            location (str, required): JSON path to ``instance`` for error reporting.
        """
        members: list[dict] = []

        def _collect(node: dict) -> None:
            for m in node.get("children", []):
                if m.get("structure-type") == "choice":
                    _collect(m)  # flatten nested choices into one group
                else:
                    members.append(m)

        _collect(choice_node)
        if not members:
            return

        keys = [(m.get("group-as") or m.get("use-name") or m.get("name")) for m in members]
        required = all((m.get("min-occurs") or "0") == "1" for m in members)
        present = [k for k in keys if k and k in instance]

        if required and len(present) == 0:
            errors.append({
                "error-type": "choice",
                "location":   location,
                "field":      keys,
                "value":      0,
                "expected":   {"select-one-of": keys},
            })
        elif len(present) > 1:
            errors.append({
                "error-type": "choice",
                "location":   location,
                "field":      present,
                "value":      len(present),
                "expected":   {"mutually-exclusive": keys},
            })

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
    def _can_mutate(self, operation: str = "") -> bool:
        """Shared precondition gate for every method that mutates the in-memory dict.

        Verifies the typical circumstances required to allow a mutation:
          - dict content is loaded (``_dict`` is not None)
          - content is not read-only
          - (future) account-specific access control permits the operation

        Mutation methods should call this at the top and abort when it returns
        False, before making any change to ``self._dict``.

        Args:
            operation: Optional name of the calling operation, used only to make
                       log messages clearer.

        Returns:
            True when mutation is permitted, False otherwise (with a logged reason).
        """
        label = f"{operation}: " if operation else ""
        if self._dict is None:
            logger.error(f"{label}no dict content available to mutate.")
            return False
        if self.is_read_only:
            logger.error(f"{label}content is read-only; mutation not permitted.")
            return False
        # Future: account-specific access control checks belong here, e.g.
        #   if not self._access_control_allows(operation):
        #       logger.error(f"{label}operation not permitted for current account.")
        #       return False
        return True

    # -------------------------------------------------------------------------
    @if_update_successful
    def set_metadata(self, content: dict = {}) -> bool:
        """
        Set simple metadata fields on the OSCAL content's ``metadata`` section.

        Complex metadata collections (revisions, roles, parties, links, props, etc.)
        are not yet supported and are skipped with a warning.

        Args:
            content (dict, optional): Mapping of metadata field name to value to set.
                Defaults to an empty dict.

        Returns:
            bool: True on success, or None when the content cannot be mutated.
        """
        if not self._can_mutate("set_metadata"):
            return None
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

    def _query(self, path: str, context: dict | None = None) -> list:
        """Live-reference implementation of :meth:`query` (returns nodes inside ``self._dict``).

        Internal callers that need to mutate matched nodes in place use this directly;
        external callers use the public :meth:`query`, which returns safe copies.
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

    def query(self, path: str, context: dict | None = None) -> list:
        """
        Query the JSON content using XML element name syntax (via :class:`OSCALPath`).

        Steps use OSCAL XML element names (``control``, ``prop``, ``part``, …)
        and the metaschema index translates them to the correct JSON keys
        (``controls``, ``props``, ``parts``, …) including array/BY_KEY grouping.

        The returned list contains SAFE COPIES — mutating a result does not change the
        document; use the model's mutation methods for persistent edits. A single deep
        copy of the whole result set preserves internal identity between overlapping
        matches.

        Parameters
        ----------
        path : str
            Path expression using XML element names, e.g.
            ``"//control[@id='ac-2.2']"`` or ``"/*/metadata/title"``.
        context : dict, optional
            Sub-dict to query within.  Defaults to the full document dict
            (``self._dict``).

        Returns a list of matching JSON values (as copies), or ``[]`` on error / no match.
        """
        return copy.deepcopy(self._query(path, context))

    def query_one(self, path: str, context: dict | None = None, default=None):
        """Return the first result of :meth:`query` as a safe copy, or ``default``.

        Args:
            path (str, required): Path expression using OSCAL XML element names.
            context (dict | None, optional): Sub-dict to query within. Defaults to the
                full document dict.
            default (Any, optional): Value to return when there is no match. Returned
                as-is (not copied). Defaults to None.

        Returns:
            Any: A safe copy of the first matching JSON value, or ``default``.
        """
        results = self._query(path, context)
        return copy.deepcopy(results[0]) if results else default

    def _json_query(self, path: str, context: dict | None = None) -> list:
        """Live-reference implementation of :meth:`json_query` (nodes inside ``self._dict``).

        Internal callers that need to mutate matched nodes in place use this directly;
        external callers use the public :meth:`json_query`, which returns safe copies.
        """
        data = context if context is not None else self._dict
        if data is None:
            logger.error("json_query: no JSON content available.")
            return []
        return native_path.query(path, data)

    def json_query(self, path: str, context: dict | None = None) -> list:
        """
        Query the JSON content using JSON key name syntax (via :class:`NativePath`).

        Steps use the actual JSON key names (``controls``, ``props``, ``parts``, …)
        with no metaschema translation required.  Arrays are iterated
        transparently, so ``//controls[id='ac-2.2']`` navigates directly into
        any ``controls`` array at any depth.

        The returned list contains SAFE COPIES — mutating a result does not change the
        document; use the model's mutation methods for persistent edits.

        Parameters
        ----------
        path : str
            Path expression using JSON key names, e.g.
            ``"//controls[id='ac-2.2']"`` or ``"/*/metadata/title"``.
        context : dict, optional
            Sub-dict to query within.  Defaults to the full document dict
            (``self._dict``).

        Returns a list of matching JSON values (as copies), or ``[]`` on error / no match.
        """
        return copy.deepcopy(self._json_query(path, context))

    def json_query_one(self, path: str, context: dict | None = None, default=None):
        """Return the first result of :meth:`json_query` as a safe copy, or ``default``.

        Args:
            path (str, required): Path expression using JSON key names.
            context (dict | None, optional): Sub-dict to query within. Defaults to the
                full document dict.
            default (Any, optional): Value to return when there is no match. Returned
                as-is (not copied). Defaults to None.

        Returns:
            Any: A safe copy of the first matching JSON value, or ``default``.
        """
        results = self._json_query(path, context)
        return copy.deepcopy(results[0]) if results else default

    # -------------------------------------------------------------------------
    @staticmethod
    def _as_index(segment: str) -> int | None:
        """Return a non-negative int for a numeric path segment, else None.

        Args:
            segment (str, required): A single slash-path segment.

        Returns:
            int | None: The parsed non-negative index, or None when the segment is
                not a non-negative integer (i.e. it names a dict key).
        """
        try:
            idx = int(segment)
        except (ValueError, TypeError):
            return None
        return idx if idx >= 0 else None

    # -------------------------------------------------------------------------
    def _ensure_list(self, container: dict, key: str) -> list | None:
        """Return the list at ``container[key]``, creating an empty one if absent.

        Mirrors ``dict.setdefault`` but guarantees the result is a list. This is the
        shared "optional OSCAL array" guard: many OSCAL arrays (``props``, ``links``,
        ``controls`` …) are optional, so writes must create them on first use.

        Args:
            container (dict, required): The parent object to read/create the list on.
            key (str, required): The array key.

        Returns:
            list | None: The (possibly newly created) list, or None if ``key`` exists
                but is not a list.
        """
        target = container.setdefault(key, [])
        if not isinstance(target, list):
            logger.error(f"_ensure_list: '{key}' is {type(target).__name__}, expected list.")
            return None
        return target

    # -------------------------------------------------------------------------
    def put(
        self,
        path: str,
        value,
        mode: Literal["replace", "insert"] = "replace",
        *,
        validate: bool = False,
        check_refs: bool = False,
    ) -> bool:
        """
        Write a value into the JSON content at a slash-separated path.

        This is the shared, guarded entry point for JSON mutations. It centralizes the
        defensive behavior that would otherwise be repeated at every call site:
        the read-only / content guard (:meth:`_can_mutate`), auto-creation of missing
        intermediate objects and optional OSCAL arrays, and dirty-state bookkeeping
        (``is_unsaved`` / ``last_modified``).

        Path segments are ``'/'`` separated and relative to the model root (e.g.
        ``"metadata/title"`` or ``"metadata/roles/0/title"``). A numeric segment
        indexes a list; any other segment names a dict key. Missing intermediate dict
        keys are created automatically.

        Args:
            path (str, required): Slash-separated path relative to the model root.
            value (Any, required): The JSON-compatible value to write.
            mode (str, optional): ``"replace"`` (default) sets the value at ``path``;
                ``"insert"`` treats the leaf as an optional array — creating it if
                absent — and appends ``value`` to it.
            validate (bool, optional): When True, run metaschema-driven datatype/regex
                and allowed-value checks before writing (see :meth:`_validate_write`).
                Currently a permissive extension point. Defaults to False.
            check_refs (bool, optional): When True, run referential-integrity checks
                before writing (see :meth:`_check_referential_integrity`). Currently a
                permissive extension point. Defaults to False.

        Returns:
            bool: True on success, False on any failure (guard, bad path/index,
                validation, or type mismatch). No mutation occurs on failure.
        """
        if not self._can_mutate("put"):
            return False

        if mode not in ("replace", "insert"):
            logger.error(f"put: invalid mode '{mode}'; expected 'replace' or 'insert'.")
            return False

        parts = [p for p in path.strip("/").split("/") if p != ""]
        if not parts:
            logger.error("put: empty path.")
            return False

        if validate and not self._validate_write(path, value, mode):
            return False
        if check_refs and not self._check_referential_integrity(path, value, mode):
            return False

        # Walk to the parent of the leaf, auto-creating missing intermediate dicts.
        obj = self._dict.setdefault(self.model, {})
        for depth, part in enumerate(parts[:-1]):
            if isinstance(obj, list):
                idx = self._as_index(part)
                if idx is None or idx >= len(obj):
                    logger.error(f"put: invalid list index '{part}' in path '{path}'.")
                    return False
                obj = obj[idx]
            elif isinstance(obj, dict):
                if part not in obj:
                    # Auto-vivify a dict. A following numeric segment would require a
                    # pre-existing list, which we will not fabricate by index.
                    if self._as_index(parts[depth + 1]) is not None:
                        logger.error(
                            f"put: cannot auto-create list for index '{parts[depth + 1]}' in path '{path}'."
                        )
                        return False
                    obj[part] = {}
                obj = obj[part]
            else:
                logger.error(f"put: cannot traverse into {type(obj).__name__} at '{part}' in path '{path}'.")
                return False

        leaf = parts[-1]

        if mode == "insert":
            if not isinstance(obj, dict):
                logger.error(f"put: insert requires a dict parent at '{path}', got {type(obj).__name__}.")
                return False
            if self._as_index(leaf) is not None:
                logger.error(f"put: positional insert (index leaf '{leaf}') is not supported; use an array key.")
                return False
            target = self._ensure_list(obj, leaf)
            if target is None:
                logger.error(f"put: '{leaf}' at '{path}' is not a list; cannot insert.")
                return False
            target.append(value)
        else:  # replace
            if isinstance(obj, dict):
                obj[leaf] = value
            elif isinstance(obj, list):
                idx = self._as_index(leaf)
                if idx is None or idx >= len(obj):
                    logger.error(f"put: invalid list index '{leaf}' in path '{path}'.")
                    return False
                obj[idx] = value
            else:
                logger.error(f"put: cannot set value on {type(obj).__name__} at path '{path}'.")
                return False

        # Dirty-state bookkeeping (done inline so a False return never marks unsaved).
        self.is_unsaved = True
        self.last_modified = oscal_date_time_with_timezone()
        logger.debug(f"put[{mode}]: '{path}' = {value!r}")
        return True

    # -------------------------------------------------------------------------
    def _validate_write(self, path: str, value, mode: str) -> bool:
        """Extension point for metaschema-driven datatype/regex/allowed-value checks.

        Invoked by :meth:`put` when ``validate=True``. Currently permissive (always
        returns True). Future work: resolve the metaschema node for ``path`` and run
        :func:`_check_datatype` and allowed-value checks against ``value``.

        Args:
            path (str, required): The slash path being written.
            value (Any, required): The value being written.
            mode (str, required): The write mode ("replace" or "insert").

        Returns:
            bool: True when the write is permitted (permissive stub for now).
        """
        return True

    # -------------------------------------------------------------------------
    def _check_referential_integrity(self, path: str, value, mode: str) -> bool:
        """Extension point for referential-integrity checks on a write.

        Invoked by :meth:`put` when ``check_refs=True``. Currently permissive (always
        returns True). Future work: verify that reference values (e.g. ``control-id``,
        ``party-uuids``, resource UUIDs) resolve to existing targets.

        Args:
            path (str, required): The slash path being written.
            value (Any, required): The value being written.
            mode (str, required): The write mode ("replace" or "insert").

        Returns:
            bool: True when the write is permitted (permissive stub for now).
        """
        return True

    # -------------------------------------------------------------------------
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
            bool: True on success, None/False on any error.
        """
        if not self._can_mutate("__set_field"):
            return None

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
        if not self._can_mutate("append_child"):
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
        # Return a safe copy — the live child stays in _dict; further edits go through methods.
        return copy.deepcopy(child)

    # -------------------------------------------------------------------------
    @if_update_successful
    def append_resource(self, uuid: str = "", title: str = "", description: str = "", props: list = [], rlinks: list = [], base64: str = "", remarks: str = "") -> dict | None:
        """
        Append a resource to the document's ``back-matter`` section.

        Args:
            uuid (str, optional): Resource UUID. A new UUID is generated when empty.
            title (str, optional): Resource title.
            description (str, optional): Resource description.
            props (list, optional): Property dicts to add.
            rlinks (list, optional): Resource-link (``rlink``) dicts to add.
            base64 (str, optional): Base64-encoded inline content.
            remarks (str, optional): Remarks prose (markdown).

        Returns:
            dict | None: The newly created resource dict, or None on failure.
        """
        if not self._can_mutate("append_resource"):
            return None
        # Return a safe copy — the live resource stays in _dict; further edits go through methods.
        return copy.deepcopy(append_resource(self, uuid, title, description, props, rlinks, base64, remarks))

    # -------------------------------------------------------------------------
    def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope="successful"):
        """Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

        Args:
            visitor_fn (Callable, required): Callable receiving ``(entry_dict, depth_int)``.
            depth (int, optional): Current recursion depth; used internally. Defaults to 0.
            _seen (set | None, optional): Object ids already visited; used internally to
                prevent cycles. Defaults to None.
            scope (str, optional): Keyword-only. Which entries to visit — "successful"
                (default) visits only READY imports and recurses into them; "failed" visits
                only INVALID/NOT_LOADED imports without recursion; "all" visits every entry,
                recursing only into READY imports.

        Returns:
            None
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
    def get_oscal_object(self, uuid, _seen=None):
        """Return the LIVE imported OSCAL document whose root UUID matches ``uuid``.

        Searches this document and its resolved imports depth-first, de-duplicating
        objects shared across multiple import paths (the same large catalog reached
        two ways is visited once). This underpins the import mechanism's object reuse
        and is the companion to :attr:`import_tree`: the tree carries each node's
        ``object_uuid``; pass one here to obtain the corresponding live instance.

        Unlike the model getters, this returns the LIVE object (not a copy) — it is a
        document handle meant for working with that instance through its own methods.

        Args:
            uuid (str, required): The root UUID of the document to locate.
            _seen (set | None, optional): Object ids already visited; used internally
                for cycle-safety. Defaults to None.

        Returns:
            OSCAL | None: The matching live document, or None if not found.
        """
        if _seen is None:
            _seen = set()
        if id(self) in _seen:
            return None
        _seen.add(id(self))
        if self.uuid == uuid:
            return self
        for entry in self.import_list:
            obj = entry.get("object")
            if obj is None:
                continue
            result = obj.get_oscal_object(uuid, _seen)
            if result is not None:
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
    """Resolution state of a single import entry in an OSCAL document's import_list.

    Members:
        READY (str): "ready" — content is valid and loaded.
        NOT_LOADED (str): "not-loaded" — content has not been loaded.
        INVALID (str): "invalid" — content could not be loaded or failed validation.
        EXPIRED (str): "expired" — content is valid but the cached copy has expired.
        DUPLICATE (str): "duplicate" — the resolved href is already loaded by an earlier import.
        IGNORED (str): "ignored" — the caller explicitly chose to ignore this import.
        CYCLIC (str): "cyclic" — this import resolves to one of its own ancestors; the
            ancestor stays valid and recursion stops here to prevent an infinite loop.
    """
    READY        = "ready"        # The content is valid and loaded
    NOT_LOADED   = "not-loaded"   # The content has not been loaded
    INVALID      = "invalid"      # The content could not be loaded or failed validation
    EXPIRED      = "expired"      # The content is valid, but cached copy has expired
    DUPLICATE    = "duplicate"    # The resolved href is already loaded by an earlier import
    IGNORED      = "ignored"      # Caller explicitly chose to ignore this import (duplicate or otherwise)
    CYCLIC       = "cyclic"       # Resolves to an ancestor — recursion stops to avoid a loop

# -------------------------------------------------------------------------
class ImportFailureCode(str, Enum):
    """Typed reason codes describing why an OSCAL import could not be resolved.

    Grouped by failure category — fragment/back-matter, full-URI/file,
    content, and duplicate/retry. Members:
        FRAGMENT_INVALID_UUID (str): Fragment reference is not a valid UUID.
        RESOURCE_NOT_FOUND (str): No back-matter resource matches the UUID.
        RESOURCE_NO_VIABLE_CONTENT (str): Resource has neither rlinks nor base64 content.
        LOCAL_NOT_FOUND (str): Local file was not found.
        REMOTE_UNREACHABLE (str): Remote host could not be reached.
        REMOTE_AUTH_REQUIRED (str): Remote resource requires authentication.
        REMOTE_UNSUPPORTED (str): URI scheme is not supported.
        CONTENT_EMPTY (str): Source returned no content.
        CONTENT_INVALID (str): Content is not valid OSCAL.
        ALREADY_IMPORTED (str): Retry href resolves to a file already loaded elsewhere.
    """
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
    # Duplicate / retry failures
    ALREADY_IMPORTED           = "already-imported"            # Retry href resolves to a file already loaded by another import

# -------------------------------------------------------------------------
class ImportLoadError(Exception):
    """Exception carrying a typed import failure code from ``load_source()`` to ``resolve_imports()``.

    Attributes:
        code (ImportFailureCode): The typed reason the import failed.
        uri (str): The URI that failed to load.
    """
    def __init__(self, code: ImportFailureCode, uri: str, message: str = ""):
        """Initialize the error.

        Args:
            code (ImportFailureCode, required): The typed import failure reason.
            uri (str, required): The URI that failed to load.
            message (str, optional): Human-readable detail; a default is derived from
                ``code`` and ``uri`` when omitted.
        """
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
    """A single OSCAL source reference: an href with optional media type and hashes.

    Attributes:
        href (str): The reference target (URI or path).
        media_type (str | None): Optional media type of the target.
        hashes (list[dict] | None): Optional integrity hashes for the target.
        source_type (str): Classified source type (set by classification; not an init arg).
        source_scheme (str): URI scheme of the source (not an init arg).
        source_supported (bool): Whether the source scheme can be fetched (not an init arg).
    """
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
# Import-resolution shared helpers
# Placed after the data classes so ImportState and ImportFailure are available.
# -------------------------------------------------------------------------

# Priority order for selecting which entry to target when multiple import_list
# entries match the same href.  Non-READY statuses are preferred so that
# ignore/remove/retry operations act on the problematic entry, not the working one.
_IMPORT_RETRY_PRIORITY: tuple = (
    ImportState.DUPLICATE,
    ImportState.IGNORED,
    ImportState.INVALID,
    ImportState.NOT_LOADED,
    ImportState.EXPIRED,
    ImportState.READY,
)


def _find_import_candidates(import_list: list, href: str) -> list:
    """Return all import_list entries whose href matches in any of the tracked fields.

    Matches against: href_original, href_valid, failure.uri, or any href_list item href.
    """
    candidates = []
    for entry in import_list:
        failure = entry.get("failure")
        failure_uri = failure.uri if isinstance(failure, ImportFailure) else ""
        if (
            entry.get("href_original") == href
            or entry.get("href_valid") == href
            or failure_uri == href
            or any(item.get("href") == href for item in entry.get("href_list", []))
        ):
            candidates.append(entry)
    return candidates


def _pick_import_target(candidates: list) -> dict | None:
    """Return the highest-priority candidate from a list of matching import_list entries."""
    if not candidates:
        return None
    for status in _IMPORT_RETRY_PRIORITY:
        hit = next((e for e in candidates if e.get("status") == status), None)
        if hit is not None:
            return hit
    return candidates[0]


def _remove_import_from_dict(
    doc_dict: dict,
    model: str,
    import_list: list,
    target: dict,
) -> bool:
    """Remove the import *statement* corresponding to *target* from *doc_dict*.

    Only the import element itself is removed.  If the import referenced a
    back-matter resource via a URI fragment (``href="#uuid"``), that resource
    is left intact.

    When multiple import statements share the same ``href_original`` (the
    duplicate scenario), the preceding-entry count is used to determine which
    occurrence in the array to remove, preserving the others.

    Returns True if the element was located and removed, False otherwise.
    """
    href = target.get("href_original", "")
    root = doc_dict.get(model, {})
    if not isinstance(root, dict):
        return False

    # Count import_list entries that precede *target* and share the same
    # href_original.  That count tells us how many occurrences of this href
    # to skip in the dict array before removing.
    target_idx = import_list.index(target)
    n_to_keep = sum(
        1 for e in import_list[:target_idx]
        if e.get("href_original") == href
    )

    def _pop_nth(arr: list, key: str) -> bool:
        """Remove the (n_to_keep)-th element in *arr* whose *key* equals *href*."""
        kept = 0
        for i, item in enumerate(arr):
            if isinstance(item, dict) and item.get(key) == href:
                if kept >= n_to_keep:
                    arr.pop(i)
                    return True
                kept += 1
        return False

    if model == "profile":
        return _pop_nth(root.get("imports", []), "href")

    elif model == "component-definition":
        # Top-level import-component-definitions
        if _pop_nth(root.get("import-component-definitions", []), "href"):
            return True
        # Nested control-implementation sources within components
        for comp in root.get("components", []):
            if isinstance(comp, dict):
                if _pop_nth(comp.get("control-implementations", []), "source"):
                    return True
        # Nested control-implementation sources within capabilities
        for cap in root.get("capabilities", []):
            if isinstance(cap, dict):
                if _pop_nth(cap.get("control-implementations", []), "source"):
                    return True
        return False

    elif model == "system-security-plan":
        if "import-profile" in root:
            del root["import-profile"]
            return True
        return False

    elif model in ("assessment-plan", "plan-of-action-and-milestones"):
        if "import-ssp" in root:
            del root["import-ssp"]
            return True
        return False

    elif model == "assessment-results":
        if "import-assessment-plan" in root:
            del root["import-assessment-plan"]
            return True
        return False

    elif model == "mapping-collection":
        for mapping in root.get("mappings", []):
            if isinstance(mapping, dict):
                src = mapping.get("source-resource", {})
                if isinstance(src, dict) and src.get("href") == href:
                    del mapping["source-resource"]
                    return True
                tgt = mapping.get("target-resource", {})
                if isinstance(tgt, dict) and tgt.get("href") == href:
                    del mapping["target-resource"]
                    return True
        return False

    return False


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
def load_content(source: str | dict | OscalRef | list, media_type: str = "", only_oscal: bool = False,
                 cache_directive: "CacheDirective | None" = None) -> str:
    """Load content from one or more sources and return the first successful payload.

    Args:
        source (str | dict | OscalRef | list, required): The source(s) to load, as a
            URI/path string, reference dict, ``OscalRef``, or a fallback list of these.
        media_type (str, optional): Expected media type hint. Defaults to "".
        only_oscal (bool, optional): When True, restrict acceptance to OSCAL content.
            Defaults to False.
        cache_directive (CacheDirective | None, optional): Caching directive applied
            to remote fetches. Defaults to the standard 24h behavior.

    Returns:
        str: The first successfully loaded content payload, or "" if none load and no
            typed error was raised.

    Raises:
        ImportLoadError: When a source fails with a typed reason (the last error is
            re-raised when every source in a list fails).
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
            content = load_source(ref, cache_directive)
            if content:
                return content
        except ImportLoadError as exc:
            last_error = exc
            logger.warning(f"Failed to load content from source '{ref.href}': {exc}")

    if last_error:
        raise last_error
    logger.error("No usable content could be loaded from provided sources")
    return ""

def load_source(ref: OscalRef, cache_directive: "CacheDirective | None" = None) -> str:
    """Fetch or read content from a classified ``OscalRef``.

    Args:
        ref (OscalRef, required): A reference that has already been classified
            (via :func:`classify_source`) to set its source type/scheme.
        cache_directive (CacheDirective | None, optional): Caching directive applied
            to remote (http/https) fetches. Defaults to the standard 24h behavior.

    Returns:
        str: The raw content as a string on success.

    Raises:
        ImportLoadError: With a typed ``ImportFailureCode`` on any load failure.
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
            # Apply the cache directive, then serve from the on-disk cache when a
            # reusable copy exists; otherwise fetch and populate/refresh the cache.
            cache_key = _canonicalize_ref(src)
            cache = get_local_cache()
            cached = cache.get(cache_key, cache_directive)
            if cached is not None:
                logger.info(f"Loading controls from local cache: {src}")
                content = cached
            else:
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
                if content:
                    cache.put(cache_key, content, cache_directive)

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


def _canonicalize_ref(href: str) -> str:
    """Canonicalize a resolved href for object-registry identity.

    Produces a stable key for the same location: URLs get lower-cased scheme/host
    and their fragment stripped; local paths are resolved with ``os.path.realpath``
    (collapsing symlinks and ``..``). Format differences are intentionally *not*
    normalized away — ``catalog.xml`` and ``catalog.json`` are different files and
    keep distinct href keys (content-identity dedup handles the format-variant case).

    Args:
        href (str, required): A resolved (absolute) href or path.

    Returns:
        str: The canonicalized key, or "" when ``href`` is empty.
    """
    if not href:
        return ""
    parsed = urlparse(href)
    if parsed.scheme and len(parsed.scheme) > 1 and parsed.scheme.lower() != "file":
        return urlunparse((
            parsed.scheme.lower(), parsed.netloc.lower(),
            parsed.path, parsed.params, parsed.query, "",
        ))
    try:
        return os.path.realpath(href)
    except Exception:
        return href

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

    Sets the ``source_type``, ``source_scheme``, and ``source_supported`` fields on
    ``ref`` in place. Classification intentionally does not use file extensions,
    because many valid content endpoints (e.g. APIs) lack predictable suffixes.

    Args:
        ref (OscalRef, required): The reference to classify; mutated in place.
        only_oscal (bool, optional): Reserved for future content-shape validation;
            currently does not affect classification. Defaults to False.

    Returns:
        bool: True if the reference was classified (even if unsupported), False only
            when the href is empty.
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
def prune_tree_copy(node: dict | None, depth: int | None = None,
                    child_keys: tuple = ("groups", "controls")) -> dict | None:
    """Return a SAFE COPY of *node* with nested structural children limited to *depth*.

    Shared, model-agnostic helper for the node getters (catalog/profile groups and
    controls; assessment ``tasks`` once implemented). The returned value shares no
    references with *node*, so callers may read, mutate, or serialize it without
    affecting the source document — mutation of live content must go through the
    OSCAL-standard-enforcing methods, never through a getter's return value.

    Only the collections named in *child_keys* are treated as structural children
    subject to depth pruning. The node's own intrinsic content (e.g. ``props``,
    ``links``, ``params``, ``parts``, ``title``) is always copied in full.

        depth = None  -> unlimited: a full deep copy of the entire subtree (the
                         default; mirrors the historical getter behavior).
        depth = 0     -> node only: the *child_keys* collections are omitted.
        depth = N     -> N levels of structural children retained, each recursively
                         pruned at ``depth - 1``.

    Args:
        node (dict | None, required): The group/control/task dict to copy, or None.
        depth (int | None, optional): Structural-child depth limit. Defaults to None.
        child_keys (tuple, optional): Keys treated as structural children. Defaults
            to ("groups", "controls"). Use ("tasks",) for assessment tasks.

    Returns:
        dict | None: A detached copy, or None when *node* is None.

    Raises:
        ValueError: If *depth* is a negative integer.
    """
    if node is None:
        return None
    if depth is None:
        return copy.deepcopy(node)
    if depth < 0:
        raise ValueError(f"depth must be None or a non-negative integer, got {depth}")

    result: dict = {}
    for key, value in node.items():
        if key in child_keys:
            continue                      # pruned / handled below by depth
        result[key] = copy.deepcopy(value)
    if depth > 0:
        for key in child_keys:
            children = node.get(key)
            if isinstance(children, list):
                result[key] = [prune_tree_copy(child, depth - 1, child_keys)
                               for child in children]
    return result


# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
def append_props(parent_obj: dict, props: list) -> None:
    """
    Append multiple prop dicts to ``parent_obj["props"]``.

    Args:
        parent_obj (dict, required): OSCAL JSON object that will receive the props.
        props (list, required): Property dicts, each with at minimum "name" and "value".

    Returns:
        None
    """
    for prop in props:
        append_prop(parent_obj, prop)

# -------------------------------------------------------------------------
def append_prop(parent_obj: dict, prop: dict) -> dict:
    """
    Append a single prop dict to ``parent_obj["props"]``.

    Args:
        parent_obj (dict, required): OSCAL JSON object that will receive the prop.
        prop (dict, required): Property dict. Required keys: "name", "value".
            Optional keys: "uuid", "ns", "class", "group", "remarks".

    Returns:
        dict: The appended prop entry (filtered to recognized keys).
    """
    entry: dict = {}
    for key in ("uuid", "name", "ns", "value", "class", "group", "remarks"):
        if key in prop:
            entry[key] = prop[key]
    parent_obj.setdefault("props", []).append(entry)
    return entry

# -------------------------------------------------------------------------
def get_props(parent_obj: dict, name: str | None = None, uuid: str | None = None,
              ns: str = _OSCAL_NS, class_: str | None = None,
              group: str | None = None) -> list:
    """
    Retrieve matching prop dicts from ``parent_obj["props"]``.

    Either ``name`` or ``uuid`` must be supplied. The return value is always a
    list — empty when nothing matches (or when the required parameters are
    missing) — never ``None``.

    An absent ``ns`` on a prop is treated as the OSCAL default namespace
    (``_OSCAL_NS``), matching the way ``ns`` defaults on this function's own
    ``ns`` parameter. Correct default-``ns`` handling is essential: a prop with
    no ``ns`` is considered to be in the OSCAL namespace.

    Matching behaviour:
      * ``uuid`` supplied: every prop whose ``uuid`` equals ``uuid`` is
        returned. If any descriptor parameter (``name``, a non-default ``ns``,
        ``class_`` or ``group``) is also supplied and does not match a returned
        prop, a warning is logged, but the prop is still returned.
      * ``uuid`` not supplied: ``name`` is required. Props are matched on
        ``name`` **and** effective ``ns``. When ``class_`` and/or ``group`` are
        supplied they must also match. When ``class_``/``group`` are *not*
        supplied, all name+ns matches are returned, ordered best match first:
        props carrying fewer of the un-queried qualifiers (``class``/``group``)
        sort ahead of more-specific props. Document order is preserved among
        equally specific matches.

    Args:
        parent_obj (dict, required): OSCAL JSON object holding a ``props`` list.
        name (str, optional): Prop ``name`` to match. Required if ``uuid`` is
            not given.
        uuid (str, optional): Prop ``uuid`` to match. Required if ``name`` is
            not given.
        ns (str, optional): Namespace to match; defaults to ``_OSCAL_NS``.
        class_ (str, optional): Prop ``class`` to match. Maps to the ``"class"``
            key (``class`` is a reserved word in Python).
        group (str, optional): Prop ``group`` to match.

    Returns:
        list: Matching prop dicts (possibly empty), ordered best match first.
    """
    if uuid is None and name is None:
        logger.warning("get_props() requires either 'name' or 'uuid'; neither "
                       "was provided. Returning an empty list.")
        return []

    props = parent_obj.get("props", []) or []

    def _eff_ns(prop: dict) -> str:
        # Absent @ns defaults to the OSCAL namespace per OSCAL specification.
        return prop.get("ns") or _OSCAL_NS

    # -- uuid mode: uuid identifies the prop; other params only validate ------
    if uuid is not None:
        matches = [p for p in props if p.get("uuid") == uuid]
        descriptors_given = (name is not None or class_ is not None
                             or group is not None or ns != _OSCAL_NS)
        if descriptors_given:
            for p in matches:
                mismatched = []
                if name is not None and p.get("name") != name:
                    mismatched.append("name")
                if _eff_ns(p) != ns:
                    mismatched.append("ns")
                if class_ is not None and p.get("class") != class_:
                    mismatched.append("class")
                if group is not None and p.get("group") != group:
                    mismatched.append("group")
                if mismatched:
                    logger.warning(f"get_props() matched prop uuid={uuid!r} but "
                                   f"the following supplied parameter(s) did not "
                                   f"match the prop: {', '.join(mismatched)}.")
        return matches

    # -- name mode: match on name + effective ns (+ class/group if given) -----
    results = [p for p in props
               if p.get("name") == name and _eff_ns(p) == ns
               and (class_ is None or p.get("class") == class_)
               and (group is None or p.get("group") == group)]

    # Order best match first: props carrying fewer of the un-queried
    # qualifiers (class/group) are the closer match. Stable sort keeps
    # document order among equally specific props.
    unqueried = [q for q, given in (("class", class_), ("group", group))
                 if given is None]
    if unqueried:
        results.sort(key=lambda p: sum(1 for q in unqueried
                                       if p.get(q) not in (None, "")))
    return results

# -----------------------------------------------------------------------------
def append_links(parent_obj: dict, links: list) -> None:
    """
    Append multiple link dicts to ``parent_obj["links"]``.

    Args:
        parent_obj (dict, required): OSCAL JSON object that will receive the links.
        links (list, required): Link dicts, each with at minimum an "href" key.

    Returns:
        None
    """
    for link in links:
        append_link(parent_obj, link)

# -----------------------------------------------------------------------------
def append_link(parent_obj: dict, link: dict) -> dict:
    """
    Append a single link dict to ``parent_obj["links"]``.

    Args:
        parent_obj (dict, required): OSCAL JSON object that will receive the link.
        link (dict, required): Link dict. Required key: "href".
            Optional keys: "rel", "media-type", "resource-fragment", "text".

    Returns:
        dict: The appended link entry (filtered to recognized keys).
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
    Convert OSCAL markdown text to an HTML ElementTree element.

    Calls ``oscal_markdown_to_html`` to format the markdown into HTML consistent
    with the OSCAL XML specification for markup-line / markup-multiline, then parses
    the resulting string into an XML element suitable for appending into a parent
    XML object.

    Args:
        markdown_text (str, required): The markdown text to convert.
        multiline (bool, optional): If True, handle markup-multiline (block elements);
            if False, handle markup-line (inline elements only). Defaults to True.

    Returns:
        Optional[ElementTree.Element]: The parsed XML element, or None if conversion fails.
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
    """Generate a new random (version 4) UUID string.

    Returns:
        str: A newly generated UUID in canonical string form.
    """
    return str(uuid.uuid4())

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':
    print("OSCAL Class Module. This is not intended to be run as a stand-alone module.")

