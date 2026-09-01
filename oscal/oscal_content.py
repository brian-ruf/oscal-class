"""
oscal_content — OSCAL base class and shared content operations.

Defines the ``OSCAL`` base class used by all eight model classes for creating,
loading, manipulating, validating, and format-converting OSCAL content. All
published OSCAL versions, formats, and models can be validated and converted;
newly published versions can be "learned" by updating the OSCAL Support
database. This module also drives import resolution and Metapath/JSON query
support, and defines the library exception hierarchy (``OSCALError`` and its
subclasses, e.g. ``UnsupportedModelOperation``).

Two supporting modules are imported and re-exported here so existing
``from .oscal_content import ...`` call sites keep working:

* ``oscal_helpers`` — model-agnostic dict/markup helpers (props/links, UUID
  generation/validation, id lookups, depth-limited safe copies).
* ``oscal_source`` — source acquisition and reference/import resolution
  (``OscalRef``, ``load_content``/``load_source``, ``classify_source``, href
  resolution, and the ``ImportState``/``ImportFailureCode``/``ImportLoadError``/
  ``ImportFailure`` types).

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
import logging
from typing             import Optional, Any, Literal, Protocol, runtime_checkable
from dataclasses        import dataclass
from datetime           import datetime
from functools          import wraps
from enum               import Enum, IntEnum
from urllib.parse       import urlparse
from xml.etree          import ElementTree

from ruf_common.data    import detect_data_format, safe_load, safe_load_xml, xpath_atomic
from ruf_common.lfs     import getfile, chkdir, putfile, normalize_content
from .oscal_support     import get_support, OSCAL_DEFAULT_XML_NAMESPACE, OSCAL_FORMATS
from .oscal_datatypes   import oscal_date_time_with_timezone, OSCAL_DATATYPES, normalize_uri_reference
from .oscal_registry    import get_registry
from .oscal_cache       import CacheDirective, CACHE_NEVER
from .oscal_converter   import (
    OSCALConverter, _markup_to_md, OSCALPath, native_path,
)
# Model-agnostic dict/markup helpers live in oscal_helpers; imported (and thereby
# re-exported) here so existing ``from .oscal_content import ...`` call sites in
# the model modules keep working after the extraction.
from .oscal_helpers     import (  # noqa: F401  (re-exported for callers)
    new_uuid, _is_valid_uuid, prune_tree_copy, _collect_ids, _find_part_by_id,
    _find_model_element, append_props, append_prop, get_props, append_links,
    append_link, oscal_markdown_to_html_tree, _format_table_helper,
    MEDIA_TYPES, _infer_media_type,
)
# Source acquisition and reference/import-resolution machinery lives in
# oscal_source; imported (and thereby re-exported) here so existing
# ``from .oscal_content import load_content`` (etc.) call sites in the model
# modules, workspace, and tests keep working after the extraction.
from .oscal_source      import (  # noqa: F401  (re-exported for callers)
    OscalRef, _normalize_refs, ImportState, ImportFailureCode, ImportLoadError,
    ImportFailure, load_content, load_source, classify_source, _resolve_href,
    _canonicalize_ref, _oscal_format_variants, _find_import_candidates,
    _pick_import_target, _remove_import_from_dict, _hrefs_from_dict_spec,
    _backmatter_resource,
)
from .oscal_resequence  import resequence_oscal

logger = logging.getLogger(__name__)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Constants
INDENT = 2 # Number of spaces to use for indentation in pretty-printed output
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
        ("/*/import-ap",                                 "href"),
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
        {"path": "import-ap",                "key": "href", "single": True},
    ],
    "mapping-collection": [
        {"path": "mappings", "subkey": "source-resource", "key": "href"},
        {"path": "mappings", "subkey": "target-resource", "key": "href"},
    ],
}

# Per-model spec for the *primary document import* — the single first-level import
# location that add_import/remove_import operate on. Distinct from _IMPORT_PATTERNS_DICT
# (which enumerates every OSCAL-document reference for resolution): this table describes
# only the top-level import statement(s) and their cardinality.
#   path    : model-root key holding the import(s); None ⇒ the model has no top-level import
#   single  : True when the path is a single object (import-profile/-ssp/-ap), else a list
#   href    : key within an import entry that carries the href
#   min/max : allowed cardinality of the import; max None ⇒ unbounded
# Cardinality rule: when min == max the count is fixed and both add and remove are
# invalid (catalog 0/0, mapping-collection 0/0, SSP/AP/AR 1/1); such imports are set via
# the retry_import modify path. Otherwise add is allowed while count < max and remove
# while count > min (counting only imports with a non-empty, non-"#" href).
_IMPORT_SPEC: dict[str, dict] = {
    "catalog":                       {"path": None,                           "single": False, "href": "href", "min": 0, "max": 0},
    "profile":                       {"path": "imports",                      "single": False, "href": "href", "min": 1, "max": None},
    "component-definition":          {"path": "import-component-definitions", "single": False, "href": "href", "min": 0, "max": None},
    "system-security-plan":          {"path": "import-profile",               "single": True,  "href": "href", "min": 1, "max": 1},
    "assessment-plan":               {"path": "import-ssp",                   "single": True,  "href": "href", "min": 1, "max": 1},
    "assessment-results":            {"path": "import-ap",                    "single": True,  "href": "href", "min": 1, "max": 1},
    "plan-of-action-and-milestones": {"path": "import-ssp",                   "single": True,  "href": "href", "min": 0, "max": 1},
    "mapping-collection":            {"path": None,                           "single": False, "href": "href", "min": 0, "max": 0},
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


# How the content's declared OSCAL version was resolved against available support
# (not progressive; a qualifier on the validation/conversion path).
class VersionSupport(Enum):
    """Whether the content's declared OSCAL version was supported as-is.

    Set during initial validation once the model/version are identified. A
    ``CLOSEST_MATCH`` or ``UNSUPPORTED`` result means the requested version was not
    available locally and could not be acquired from the bundled database or NIST.

    Members:
        EXACT (str): "exact" — the declared OSCAL version's support was available (or
            was successfully acquired); validation/conversion used that exact version.
        CLOSEST_MATCH (str): "closest-match" — the declared version was unavailable;
            the closest available version within the same OSCAL major was substituted.
            ``requested_oscal_version`` and ``resolved_oscal_version`` differ.
        UNSUPPORTED (str): "unsupported" — the declared version/model could not be
            supported at all; the document cannot advance past ``ACQUIRED``.
    """
    EXACT         = "exact"
    CLOSEST_MATCH = "closest-match"
    UNSUPPORTED   = "unsupported"


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
            self._on_content_mutated()
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
# Library exception hierarchy
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCALError(Exception):
    """Base class for every error intentionally raised by the oscal library.

    Catch this at an application boundary to handle any library-originated
    failure uniformly — typically to log the developer-facing detail and show
    the end user a friendly message — without also swallowing unrelated Python
    errors. Instances expose two messages:

    * ``developer_message`` — precise, actionable detail for logs/telemetry.
    * ``user_message`` — a safe, generic sentence suitable for end users.

    ``str(err)`` returns the developer message.
    """

    #: Generic, end-user-safe fallback. Subclasses may override.
    default_user_message = "The requested OSCAL operation could not be completed."

    @property
    def developer_message(self) -> str:
        """str: Precise, actionable detail for developers (the default ``str``)."""
        return super().__str__()

    @property
    def user_message(self) -> str:
        """str: A safe, generic message that omits internal detail."""
        return self.default_user_message


class UnsupportedModelOperation(OSCALError, AttributeError):
    """Raised when a method/attribute valid for *some* OSCAL model is accessed on
    a model that does not define it (e.g. calling ``add_control`` on an SSP).

    Also raised — with an empty ``valid_on`` — for names no OSCAL model defines,
    which almost always indicates a typo.

    This subclasses :class:`AttributeError` as well as :class:`OSCALError` so that
    ``hasattr(obj, name)`` and ``getattr(obj, name, default)`` keep their normal
    semantics (return ``False`` / the default rather than propagating), while the
    error remains catchable as an ``OSCALError``.

    Attributes:
        method (str): The attribute/method name that was accessed.
        model (str): The model name of the instance it was accessed on.
        valid_on (list[str]): Model names that *do* define the name (may be empty).
    """

    default_user_message = "This action isn't available for this type of OSCAL document."

    def __init__(self, method: str, model: str, valid_on: "list[str] | None" = None):
        """Initialize the error.

        Args:
            method (str, required): The attribute/method name that was accessed.
            model (str, required): The model name of the instance it was used on.
            valid_on (list[str], optional): Model names that define ``method``.
        """
        self.method = method
        self.model = model or "OSCAL"
        self.valid_on = sorted(valid_on) if valid_on else []
        super().__init__(self.developer_message)

    @property
    def developer_message(self) -> str:
        """str: Which model was called, the missing operation, and where it's valid."""
        if self.valid_on:
            return (
                f"{self.model!r} model has no operation {self.method!r}; "
                f"it is defined on: {', '.join(self.valid_on)}."
            )
        return (
            f"{self.model!r} model has no operation {self.method!r} "
            f"(no OSCAL model defines it — likely a typo)."
        )


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


@dataclass
class ImportResult:
    """Outcome of an :meth:`OSCAL.add_import` or :meth:`OSCAL.update_import` call.

    Attributes:
        status (str): One of "added", "replaced", "updated", "duplicate", "invalid", or
            "error". "added"/"replaced"/"updated" are the success cases (``ok`` is True):
            "added"/"replaced" come from :meth:`add_import` (new entry vs placeholder
            filled), while :meth:`update_import` returns "replaced" when it repointed the
            import at a new/other resource and "updated" when it modified the existing
            resource in place. "duplicate" means the href already appears among this
            document's own imports. "invalid" means the operation is not permitted by this
            model's import cardinality (e.g. a catalog has no imports). "error" is a
            bad-input or read-only failure.
        entry (dict | None): The import entry — the newly added/replaced/updated entry, or
            the conflicting existing import for "duplicate".
        resource (dict | None): The back-matter resource referenced by the import
            (created, reused, or updated). None for "duplicate"/"invalid"/"error".
        message (str): Human-readable detail, primarily for the non-success statuses.
    """
    status: str
    entry: Optional[dict] = None
    resource: Optional[dict] = None
    message: str = ""

    @property
    def ok(self) -> bool:
        """bool: True when an import was added, replaced, or updated."""
        return self.status in ("added", "replaced", "updated")

    @property
    def is_duplicate(self) -> bool:
        """bool: True when the href already matched one of this document's imports."""
        return self.status == "duplicate"

    @property
    def is_invalid(self) -> bool:
        """bool: True when the model's import cardinality forbids the operation."""
        return self.status == "invalid"

    @property
    def is_updated(self) -> bool:
        """bool: True when an existing resource was modified in place (update_import)."""
        return self.status == "updated"


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# OSCAL CLASS
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCAL:
    """Base class for all OSCAL model documents.

    Provides loading, saving, validation, format conversion (XML/JSON/YAML),
    import resolution, and query support shared by every OSCAL model. Content is
    held internally as a JSON-primary dict (``self._dict``); the XML tree
    (``self._tree``) is a transient, derived view built on demand for XML
    serialization and released afterward (it persists only in the degraded case
    where XML was loaded but could not be converted to a dict). Do not instantiate
    directly; use the factory classmethods ``load``, ``loads``, or ``new``, or a
    model subclass.

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

    Cross-model operation guard:
        Many mutation/query methods are only valid for certain models (e.g.
        ``resolve`` on a Profile, ``append_component`` on an SSP). Calling one on a
        model that does not define it does not raise a bare ``AttributeError``:
        ``__getattr__`` raises :class:`UnsupportedModelOperation` (an ``OSCALError``
        and ``AttributeError``) reporting which models — if any — define the name,
        logs that detail, and records it on ``self.errors``. Use :meth:`supports`
        to check before calling. Applications catch :class:`OSCALError` at their
        boundary and show the user ``err.user_message`` instead of internals.

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
        # OSCAL-version support resolution (see VersionSupport). requested = the version
        # the content declares; resolved = the version whose support was actually used
        # (differs only for CLOSEST_MATCH).
        self.version_support        : VersionSupport = VersionSupport.EXACT
        self.requested_oscal_version: str = ""
        self.resolved_oscal_version : str = ""
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
        # Explicit uuid/last-modified set by the current mutation; consumed by the
        # post-mutation revision stamp so an explicit value wins over the auto-stamp.
        self._identity_override: dict = {}

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
            "version_support":         self.version_support.value,
            "requested_oscal_version": self.requested_oscal_version,
            "resolved_oscal_version":  self.resolved_oscal_version,
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
        self.requested_oscal_version = state.get("requested_oscal_version", self.requested_oscal_version)
        self.resolved_oscal_version = state.get("resolved_oscal_version", self.resolved_oscal_version)
        raw_vs = state.get("version_support")
        if raw_vs is not None:
            try:
                self.version_support = VersionSupport(raw_vs)
            except ValueError:
                pass

    # =========================================================================
    # Cross-model operation guard
    # -------------------------------------------------------------------------
    def supports(self, name: str) -> bool:
        """Return True if this model exposes ``name`` as a method or attribute.

        Lets callers look before they leap when an operation is only valid for
        some OSCAL models::

            if doc.supports("add_control"):
                doc.add_control(...)

        Only class-level (shared, model-defined) members count; per-instance
        attributes set at runtime are ignored, so the check reflects the model's
        capabilities rather than incidental state.

        Args:
            name (str, required): The method/attribute name to test.

        Returns:
            bool: True if the model defines ``name``.
        """
        return hasattr(type(self), name)

    def __getattr__(self, name: str):
        """Turn access to an undefined member into an actionable, catchable error.

        Python calls this only when normal attribute lookup fails, so it adds no
        overhead to valid calls. Rather than the bare ``AttributeError`` Python
        would raise, it reports *which* OSCAL models (if any) define ``name`` —
        distinguishing a wrong-model call from a typo — logs that detail for
        developers, and raises :class:`UnsupportedModelOperation`. Applications
        catch :class:`OSCALError` at their boundary to keep running and show the
        end user ``err.user_message`` instead of internals.

        Args:
            name (str, required): The attribute name that could not be found.

        Raises:
            UnsupportedModelOperation: For any non-dunder missing attribute.
            AttributeError: For missing dunder names, so protocol probing
                (copy/deepcopy/pickle) fails normally.
        """
        # Let dunder probing (copy, deepcopy, pickle, etc.) fail the normal way,
        # and avoid recursion before __init_common__ has populated instance state.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)

        model = self.__dict__.get("model") or type(self).__name__
        valid_on = [
            m for m, cls in _MODEL_REGISTRY.items() if hasattr(cls, name)
        ]
        error = UnsupportedModelOperation(name, model, valid_on)

        # Capture for developers two ways: the library logger, and the instance's
        # own error record (when initialized) so a caller can inspect it later.
        logger.error(error.developer_message)
        errors = self.__dict__.get("errors")
        if isinstance(errors, dict):
            errors.setdefault("unsupported_operations", []).append(
                {"method": name, "model": model, "valid_on": error.valid_on}
            )

        raise error

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

        Aligns with Python's conventional ``load(...)`` behavior (cf. ``json.load`` /
        ``pickle.load``): the source is a **local** path or a file-like object. Use
        ``loads(...)`` for in-memory strings/dicts, and ``acquire(...)`` for URI/reference
        sources (``http``/``https``/``file``/``ftp``/…) — ``load`` does not fetch remotely.

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
            # load() reads local sources only. A string carrying a real URI scheme (length
            # > 1, so a Windows drive letter like "C:" is still a path) is a remote source —
            # flag the misuse clearly instead of silently reading a nonexistent file and
            # reporting "format unknown"; the caller should use acquire().
            if isinstance(source, str):
                scheme = urlparse(source).scheme
                if scheme and len(scheme) > 1:
                    logger.error(f"load() received a URL ('{source}') but reads local files only; "
                                 "use acquire() for http/https/file/URI sources.")
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
        # The template ships a fixed placeholder uuid (shared by every new document of a
        # model); give this instance its own identity so it never leaks into real content.
        instance._stamp_revision()
        return instance

    # -------------------------------------------------------------------------
    def dump(self, filename: str="", format: str="", pretty_print: bool=False) -> bool:
        """
        Write the current OSCAL content to a file.
        With no parameters, saves to the original location in the original format.
        This will save to any valid filename, even if the file extension does not match the format.
        Output keys/elements are emitted in canonical metaschema order (see :meth:`dumps`).

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
        """Remove a first-level import statement from this document.

        Operates only on this document's own imports, never on descendants. The
        import *statement* is deleted from ``self._dict``; any back-matter resource
        it referenced via a URI fragment (``href="#uuid"``) is intentionally
        preserved. The affected part of the import tree is refreshed and any
        model-specific derived state (e.g. a Profile's resolved catalog) is reset
        via :meth:`_after_imports_changed`.

        Cardinality is enforced from :data:`_IMPORT_SPEC`:

        * Models with no top-level import (catalog, mapping-collection) — invalid.
        * Fixed-cardinality models where ``min == max`` (SSP/AP/AR require exactly
          one) — invalid; change that import with :meth:`retry_import` instead.
        * Otherwise the removal is rejected when it would drop the count of *real*
          imports (non-empty, non-``"#"`` href) below the model's minimum. Removing
          an empty placeholder is always allowed for variable-cardinality models.

        Args:
            href: Any href that identifies the import — its literal href (including
                a ``"#uuid"`` fragment or an empty ``""``/``"#"`` placeholder), or
                the resolved target href of the back-matter resource it references.

        Returns:
            True if an import was found and removed; False if not found, the
            cardinality forbids removal, or the content is read-only.
        """
        if not self._can_mutate("remove_import"):
            return False

        spec = _IMPORT_SPEC.get(self.model)
        if not spec or spec["path"] is None:
            logger.warning(f"remove_import: the {self.model} model has no top-level imports.")
            return False
        if spec["min"] == spec["max"]:
            logger.warning(
                f"remove_import: the {self.model} model requires exactly {spec['min']} "
                "import(s); its import is fixed — modify it with retry_import instead."
            )
            return False

        # Prefer an import_list entry (resolution-aware: DUPLICATE/INVALID are targeted
        # over READY when several share an href) so problematic imports are removed and
        # any prior retry_import fix on a sibling is preserved. Fall back to the raw
        # content when nothing is resolved yet (e.g. removing an empty placeholder).
        list_target = _pick_import_target(_find_import_candidates(self.import_list, href))
        if list_target is not None:
            target_href = str(list_target.get("href_original", "")).strip()
        else:
            raw_target = self._find_import_entry(href)
            if raw_target is None:
                logger.warning(f"remove_import: href '{href}' not found in this document's imports.")
                return False
            target_href = str(raw_target.get(spec["href"], "")).strip()

        is_placeholder = target_href in ("", "#")
        if not is_placeholder and self._real_import_count() - 1 < spec["min"]:
            logger.warning(
                f"remove_import: the {self.model} model requires at least {spec['min']} "
                f"import(s); '{href}' cannot be removed."
            )
            return False

        if list_target is not None:
            idx = self.import_list.index(list_target)
            dict_removed = _remove_import_from_dict(self._dict, self.model, self.import_list, list_target)
            # Keep the cached tree in step (import_list[i] ↔ import_tree.imports[i]).
            if self._import_tree is not None:
                tree_imports = self._import_tree.get("imports", [])
                if idx < len(tree_imports):
                    tree_imports.pop(idx)
            self.import_list.remove(list_target)
        else:
            dict_removed = self._remove_import_entry(spec, raw_target)
            self._import_tree = None

        if not dict_removed:
            logger.warning(
                f"remove_import: import statement for '{href}' could not be located "
                "in document content."
            )
            return False

        self.is_unsaved = True
        self._after_imports_changed()
        logger.info(f"remove_import: '{href}' removed from {self.model}.")
        return True

    # -------------------------------------------------------------------------
    # First-level import manipulation (add / remove) — shared across all models.
    # -------------------------------------------------------------------------
    def add_import(self, href: str, uuid: str = "", title: str = "", description: str = "",
                   props: list = [], version: str = "", remarks: str = "", *,
                   include_all: bool = False) -> ImportResult:
        """Add a first-level import to this document, backed by a back-matter resource.

        Uniform across every model; legality is governed by :data:`_IMPORT_SPEC`:

        * Models with no top-level import (catalog, mapping-collection) — ``invalid``.
        * Fixed-cardinality models where ``min == max`` (SSP/AP/AR) — ``invalid``; set
          their single import with :meth:`retry_import` instead of add/remove.
        * Otherwise an import is added while the count of *real* imports is below the
          model's ``max`` (unbounded when ``max`` is None).

        The import references a back-matter ``resource`` by UUID fragment
        (``href="#<uuid>"``): if a resource whose ``rlink`` already targets ``href``
        exists it is reused, otherwise one is created via :meth:`append_resource` with
        which this method shares its resource parameters (``uuid``/``title``/
        ``description``/``props``/``remarks``). The ``href`` becomes the resource's
        single ``rlink`` (with a best-effort ``media-type`` inferred from it), and
        ``version`` is appended to ``props`` as a ``prop`` named ``"version"``. An empty
        placeholder import (href ``""``/``"#"``) is filled in place; otherwise the entry
        is appended (list models) or set (single-import models). After placement the
        import tree and any derived state are refreshed via :meth:`_after_imports_changed`.

        Args:
            href (str, required): Reference to the imported OSCAL file (XML/JSON/YAML);
                becomes the created resource's ``rlink`` href.
            uuid (str, optional): UUID for the created resource; generated when empty.
                Ignored when an existing resource is reused. Mirrors :meth:`append_resource`.
            title (str, optional): Title for the created resource.
            description (str, optional): Description for the created resource.
            props (list, optional): Property dicts for the created resource; ``version``
                (below) is appended to these. Mirrors :meth:`append_resource`.
            version (str, optional): Convenience — appended to ``props`` as a ``prop``
                named ``"version"`` (resources have no native version field).
            remarks (str, optional): Remarks (markdown) for the created resource.
            include_all (bool, optional): Keyword-only, profile-only. When True a new
                profile import selects all controls via ``include-all`` instead of the
                default empty ``include-controls``/``with-ids`` placeholder. Ignored by
                models whose imports carry no selection. Defaults to False.

        Returns:
            ImportResult: ``status`` of "added", "replaced", "duplicate", "invalid",
                or "error", with the relevant ``entry`` and ``resource``.
        """
        if not href:
            logger.error("add_import: 'href' is required.")
            return ImportResult("error", message="'href' is required.")

        if not self._can_mutate("add_import"):
            return ImportResult("error", message="content is read-only or unavailable.")

        spec = _IMPORT_SPEC.get(self.model)
        if not spec or spec["path"] is None:
            return ImportResult(
                "invalid",
                message=f"the {self.model} model has no top-level imports; add_import is not applicable.",
            )
        if spec["min"] == spec["max"]:
            return ImportResult(
                "invalid",
                message=(f"the {self.model} model requires exactly {spec['min']} import(s); "
                         "its import is fixed — modify it with retry_import instead of add/remove."),
            )
        if spec["max"] is not None and self._real_import_count() >= spec["max"]:
            return ImportResult(
                "invalid",
                message=(f"the {self.model} model allows at most {spec['max']} import(s); "
                         "remove one before adding another."),
            )

        # Block duplicates among this document's own imports.
        existing = self._find_duplicate_import(href)
        if existing is not None:
            logger.error(f"add_import: '{href}' is already imported by this {self.model}.")
            return ImportResult("duplicate", entry=existing, message=f"'{href}' is already imported.")

        # Reuse a back-matter resource already targeting this href, else create one
        # through the shared append_resource path. The href becomes the resource's
        # single rlink and version is folded into props.
        resource = self._find_resource_by_href(href)
        if resource is None:
            rlink: dict[str, Any] = {"href": href}
            media_type = _infer_media_type(href)
            if media_type:
                rlink["media-type"] = media_type
            else:
                logger.debug(f"add_import: could not infer media-type for '{href}'.")
            res_props = list(props or [])
            if version:
                res_props.append({"name": "version", "value": version})
            created = self.append_resource(
                uuid=uuid, title=title, description=description,
                props=res_props, rlinks=[rlink], remarks=remarks,
            )
            if created is None:
                logger.error(f"add_import: failed to add back-matter resource for '{href}'.")
                return ImportResult("error", message="failed to add back-matter resource.")
            # append_resource returns a safe copy; carry the live stored resource so the
            # import fragment and the ImportResult reference the same object.
            resource = self._find_resource_by_href(href) or created

        import_entry: dict[str, Any] = {spec["href"]: f"#{resource['uuid']}"}
        import_entry.update(self._new_import_body(include_all=include_all))

        status = self._place_import_entry(spec, import_entry)
        if status is None:
            logger.error(f"add_import: failed to place import entry for '{href}'.")
            return ImportResult("error", message="failed to place import entry.")

        # Refresh the import tree so the new import is loaded/validated, then reset
        # any model-specific derived state.
        self._import_tree = None
        self.resolve_imports()
        self._after_imports_changed()
        logger.info(f"add_import: {status} import '{href}' as resource {resource['uuid']}.")
        return ImportResult(status, entry=import_entry, resource=resource)

    # -------------------------------------------------------------------------
    def update_import(self, *, title: Optional[str] = None, description: Optional[str] = None,
                      props: Optional[list] = None, rlinks: Optional[list] = None,
                      remarks: Optional[str] = None, new_resource: bool = True) -> ImportResult:
        """Modify the single import of a one-import model (SSP, AP, AR, or POA&M).

        These models carry exactly one import (POA&M: at most one), so :meth:`add_import`
        and :meth:`remove_import` do not apply — this is how their import is changed. It
        takes the same resource fields as :meth:`update_resource` (``title``,
        ``description``, ``props``, ``rlinks``, ``remarks`` — ``None`` leaves a field
        unchanged; arrays replace wholesale) plus ``new_resource``. The behavior depends
        on what the existing import points at:

        * **No import yet** (only possible for POA&M): the call is forwarded to
          :meth:`add_import` (``new_resource`` does not apply and is omitted); the import
          target's href is taken from the first supplied ``rlink``.
        * **Import is a direct URI** (or an empty ``""``/``"#"`` placeholder): a new
          back-matter resource is created (via :meth:`append_resource`) — its ``rlink`` is
          the supplied ``rlinks`` when given, otherwise the existing URI — and the import's
          href is repointed to that resource's ``#uuid``. (``new_resource`` does not apply:
          there is no backing resource to update.) Status: "replaced".
        * **Import is a ``#uuid`` fragment**:

          - ``new_resource=True`` (default): a brand-new resource with a new UUID is
            created via :meth:`append_resource` from the supplied fields, and the import's
            href is repointed to it. The prior resource is **left in place** — it is not
            deleted, because other content may reference it (including OSCAL documents not
            currently loaded that import this one and cite that resource by UUID). Because
            the new resource is built only from the fields you pass, supply ``rlinks`` (and
            any props) for the new target; read the old resource first with
            :meth:`get_resource_by_uuid` if you want to carry values forward. Status:
            "replaced".
          - ``new_resource=False``: the existing resource is edited in place via
            :meth:`update_resource` (same wholesale array-replacement semantics and
            data-loss caveats — see that method). The import's href is unchanged. Status:
            "updated".

        Args:
            title (str | None, optional): Resource title; ``""`` removes it.
            description (str | None, optional): Resource description; ``""`` removes it.
            props (list | None, optional): Replacement property dicts.
            rlinks (list | None, optional): Replacement ``rlink`` dicts (``href`` plus
                optional ``media-type``/``hashes``). Also the source of the import target's
                href when creating a resource or bootstrapping a POA&M import.
            remarks (str | None, optional): Resource remarks (markdown); ``""`` removes it.
            new_resource (bool, optional): When the import already references a ``#uuid``
                resource, True (default) creates a new resource and repoints; False edits
                the existing resource in place. Ignored for the direct-URI/placeholder and
                no-import cases. Defaults to True.

        Returns:
            ImportResult: ``status`` "added"/"replaced"/"updated" on success (``ok`` True),
                or "invalid"/"error" otherwise, carrying the import ``entry`` and the
                created/updated ``resource``.
        """
        if not self._can_mutate("update_import"):
            return ImportResult("error", message="content is read-only or unavailable.")

        spec = _IMPORT_SPEC.get(self.model)
        if not spec or spec["path"] is None or spec["max"] != 1:
            return ImportResult(
                "invalid",
                message=("update_import applies only to single-import models "
                         "(system-security-plan, assessment-plan, assessment-results, "
                         "plan-of-action-and-milestones)."),
            )

        key = spec["href"]
        entries = self._import_entries()

        # No import present. Only POA&M (min 0) can legitimately be here; bootstrap via
        # add_import using the href from the supplied rlink.
        if not entries:
            if spec["min"] != 0:
                return ImportResult("error", message=f"the {self.model} is missing its required import.")
            target_href = str(rlinks[0].get("href", "")).strip() if rlinks else ""
            if not target_href:
                return ImportResult(
                    "error",
                    message="no existing import and no rlink href supplied to create one.",
                )
            return self.add_import(
                target_href, title=title or "", description=description or "",
                props=list(props or []), remarks=remarks or "",
            )

        imp = entries[0]
        current = str(imp.get(key, "")).strip()

        if current.startswith("#") and len(current) > 1 and not new_resource:
            # Edit the existing resource in place; the import href is unchanged.
            resource = self.update_resource(
                current[1:], title=title, description=description,
                props=props, rlinks=rlinks, remarks=remarks,
            )
            if resource is None:
                return ImportResult(
                    "error",
                    message=f"could not update resource '{current[1:]}' referenced by the import.",
                )
            status = "updated"
        else:
            # Create a new resource and repoint the import's href at it. Covers: an
            # existing #uuid fragment with new_resource=True, a direct-URI import, and an
            # empty/# placeholder. The prior resource (if any) is intentionally preserved.
            fallback_uri = current if (current and not current.startswith("#")) else ""
            resource = self._make_import_resource(rlinks, title, description, props, remarks, fallback_uri)
            if resource is None:
                return ImportResult("error", message="failed to create back-matter resource for the import.")
            if not self.put(f"{spec['path']}/{key}", f"#{resource['uuid']}"):
                return ImportResult("error", message="failed to repoint the import href.")
            status = "replaced"

        self._import_tree = None
        self.resolve_imports()
        self._after_imports_changed()
        entry_copy = copy.deepcopy(self._import_entries()[0]) if self._import_entries() else None
        logger.info(f"update_import: {status} import for {self.model}.")
        return ImportResult(status, entry=entry_copy, resource=resource)

    # -------------------------------------------------------------------------
    def _make_import_resource(self, rlinks: Optional[list], title: Optional[str],
                              description: Optional[str], props: Optional[list],
                              remarks: Optional[str], fallback_uri: str) -> Optional[dict]:
        """Create a back-matter resource for an import target via :meth:`append_resource`.

        The resource's ``rlinks`` are the supplied *rlinks* (key-filtered) when given,
        else a single rlink to *fallback_uri* (with inferred media-type) when non-empty,
        else none. Returns the created resource (safe copy), or None on failure.
        """
        if rlinks:
            rls = [
                {k: v for k, v in rl.items() if k in ("href", "media-type", "hashes")}
                for rl in rlinks
            ]
        elif fallback_uri:
            rl: dict[str, Any] = {"href": fallback_uri}
            media_type = _infer_media_type(fallback_uri)
            if media_type:
                rl["media-type"] = media_type
            rls = [rl]
        else:
            rls = []
        return self.append_resource(
            title=title or "", description=description or "",
            props=list(props or []), rlinks=rls, remarks=remarks or "",
        )

    # -------------------------------------------------------------------------
    def _new_import_body(self, include_all: bool = False) -> dict:
        """Extra keys to seed a new import entry beyond its href.

        Base returns ``{}`` (most models' imports carry no body);
        :class:`~oscal.oscal_controls.Profile` overrides this to supply a control
        selection. ``include_all`` is honored only by models that support it.
        """
        return {}

    # -------------------------------------------------------------------------
    def _import_root(self) -> dict:
        """The live model-root dict (``self._dict[self.model]``), or ``{}``."""
        if isinstance(self._dict, dict):
            root = self._dict.get(self.model)
            if isinstance(root, dict):
                return root
        return {}

    # -------------------------------------------------------------------------
    def _import_entries(self) -> list[dict]:
        """Raw first-level import entry dicts currently present in the content.

        A single-object import location (import-profile/-ssp/-ap) is wrapped in a
        one-element list; a missing or empty location yields ``[]``.
        """
        spec = _IMPORT_SPEC.get(self.model)
        if not spec or spec["path"] is None:
            return []
        item = self._import_root().get(spec["path"])
        if spec["single"]:
            return [item] if isinstance(item, dict) else []
        return [e for e in item if isinstance(e, dict)] if isinstance(item, list) else []

    # -------------------------------------------------------------------------
    def _real_import_count(self) -> int:
        """Count first-level imports with a real (non-empty, non-``"#"``) href."""
        spec = _IMPORT_SPEC.get(self.model)
        key = spec["href"] if spec else "href"
        return sum(1 for e in self._import_entries()
                   if str(e.get(key, "")).strip() not in ("", "#"))

    # -------------------------------------------------------------------------
    def _find_import_entry(self, href: str) -> Optional[dict]:
        """Return the raw first-level import entry identified by *href*, or None.

        Matches an import whose literal href equals *href* (covering ``""``/``"#"``
        placeholders and ``"#uuid"`` fragments), or whose referenced back-matter
        resource resolves to the same target as *href*.
        """
        spec = _IMPORT_SPEC.get(self.model)
        if not spec:
            return None
        key = spec["href"]
        entries = self._import_entries()

        # 1) literal href match (placeholders, fragments, or direct href).
        for imp in entries:
            if str(imp.get(key, "")).strip() == str(href).strip():
                return imp

        # 2) resolved-target match (import references a resource whose rlink → href).
        resolved = self._resolve_import_href(href)
        resources = self._import_root().get("back-matter", {}).get("resources", [])
        res_by_uuid = {r.get("uuid"): r for r in resources if isinstance(r, dict)}
        for imp in entries:
            imp_href = str(imp.get(key, "")).strip()
            if imp_href.startswith("#"):
                res = res_by_uuid.get(imp_href[1:])
                for rlink in (res.get("rlinks", []) if res else []):
                    if self._resolve_import_href(str(rlink.get("href", ""))) == resolved:
                        return imp
            elif imp_href and self._resolve_import_href(imp_href) == resolved:
                return imp
        return None

    # -------------------------------------------------------------------------
    def _remove_import_entry(self, spec: dict, target: dict) -> bool:
        """Delete the *target* import entry from the content per its model *spec*."""
        path = spec["path"]
        root = self._import_root()
        if spec["single"]:
            if root.get(path) is target or root.get(path) == target:
                del root[path]
                return True
            return False
        container = root.get(path)
        if isinstance(container, list):
            for i, imp in enumerate(container):
                if imp is target:
                    container.pop(i)
                    return True
        return False

    # -------------------------------------------------------------------------
    def _place_import_entry(self, spec: dict, import_entry: dict) -> Optional[str]:
        """Insert *import_entry* into the content, replacing an empty placeholder.

        Returns "replaced" when an existing placeholder/single-import slot was
        overwritten, "added" when a new entry was appended/created, or None on failure.
        """
        path = spec["path"]
        key = spec["href"]
        if spec["single"]:
            existed = path in self._import_root()
            if not self.put(path, import_entry, mode="replace"):
                return None
            return "replaced" if existed else "added"

        imports = self._import_root().get(path, [])
        placeholder_idx = next(
            (i for i, imp in enumerate(imports)
             if isinstance(imp, dict) and str(imp.get(key, "")).strip() in ("", "#")),
            None,
        )
        if placeholder_idx is not None:
            if not self.put(f"{path}/{placeholder_idx}", import_entry, mode="replace"):
                return None
            return "replaced"
        if not self.put(path, import_entry, mode="insert"):
            return None
        return "added"

    # -------------------------------------------------------------------------
    def _find_resource_by_href(self, href: str) -> Optional[dict]:
        """Return a back-matter resource whose ``rlink`` resolves to *href*, or None."""
        resolved = self._resolve_import_href(href)
        for res in self._import_root().get("back-matter", {}).get("resources", []):
            if not isinstance(res, dict):
                continue
            for rlink in res.get("rlinks", []):
                if isinstance(rlink, dict) and \
                        self._resolve_import_href(str(rlink.get("href", ""))) == resolved:
                    return res
        return None

    # -------------------------------------------------------------------------
    def _find_duplicate_import(self, href: str) -> Optional[dict]:
        """Return this document's own import that already targets *href*, or None.

        Fragment imports (``href="#uuid"``) are followed through back-matter to their
        ``rlink`` target(s); direct imports are compared by resolved href. Empty
        placeholders never count as duplicates.
        """
        spec = _IMPORT_SPEC.get(self.model)
        if not spec or spec["path"] is None:
            return None
        key = spec["href"]
        resolved_new = self._resolve_import_href(href)
        resources = self._import_root().get("back-matter", {}).get("resources", [])
        res_by_uuid = {r.get("uuid"): r for r in resources if isinstance(r, dict)}

        for imp in self._import_entries():
            imp_href = str(imp.get(key, "")).strip()
            if imp_href in ("", "#"):
                continue
            targets: list[str] = []
            if imp_href.startswith("#"):
                res = res_by_uuid.get(imp_href[1:])
                for rlink in (res.get("rlinks", []) if res else []):
                    rl_href = str(rlink.get("href", "")).strip()
                    if rl_href:
                        targets.append(self._resolve_import_href(rl_href))
            else:
                targets.append(self._resolve_import_href(imp_href))
            if resolved_new in targets:
                return imp
        return None

    # -------------------------------------------------------------------------
    def _after_imports_changed(self) -> None:
        """Refresh derived state after a first-level import was added or removed.

        Base behavior: recompute content_state from the (already updated) import_list,
        then fire :meth:`_on_content_mutated` so any model-specific derived state resets.
        The caller is responsible for bringing the import tree itself up to date first —
        :meth:`add_import` re-resolves so the new import is loaded, while
        :meth:`remove_import` patches import_list/import_tree in place (preserving any
        prior :meth:`retry_import` fix on a sibling). Subclasses with derived structures
        (e.g. :class:`~oscal.oscal_controls.Profile` with its controls_tree / resolved
        catalog) override this to rebuild them.
        """
        self._refresh_content_state()
        self._on_content_mutated()

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
    def _document_signature(self) -> tuple:
        """Return the required-metadata signature used to distinguish documents that
        share a root UUID: ``(title, oscal-version, last-modified, version)``.

        Two documents with the same UUID and the same signature are the same document
        (a legitimate duplicate import); a differing signature means a UUID collision
        between genuinely different documents.
        """
        return (self.title, self.oscal_version, self.last_modified, self.version)

    # -------------------------------------------------------------------------
    def _reassign_uuid(self, new_uuid_value: str) -> None:
        """Reassign this document's root UUID (both ``_dict`` and cached attributes).

        Used to recover from a root-UUID collision between distinct documents so
        resolution can continue. Importers reference documents by href (or back-matter
        resource uuid), not by root uuid, so changing the root uuid is safe here.
        """
        if isinstance(self._dict, dict) and isinstance(self._dict.get(self.model), dict):
            self._dict[self.model]["uuid"] = new_uuid_value
        self.uuid = new_uuid_value
        self._identity = (new_uuid_value, self.last_modified, self.published) if new_uuid_value else None

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
                        # Same identity key. Confirm it is truly the same document by
                        # comparing required metadata (title, oscal-version, last-modified,
                        # version). If they match, it is a legitimate duplicate import and
                        # we reuse the shared instance.
                        if child._document_signature() == existing._document_signature():
                            logger.info(
                                f"registry: '{canonical}' is the same content as an "
                                "already-loaded object (identity hit) — reusing."
                            )
                            self._registry.alias_href(canonical, existing)
                            return existing
                        # Otherwise two genuinely different documents share a root UUID.
                        # Reassign this (subsequent) one a fresh uuid so resolution can
                        # continue, and warn — the content should be corrected.
                        old_uuid = child.uuid
                        replacement = new_uuid()
                        child._reassign_uuid(replacement)
                        key = child._identity_key()
                        logger.warning(
                            f"registry: root UUID collision — '{canonical}' shares uuid "
                            f"'{old_uuid}' with a different document (metadata differs). "
                            f"Reassigned it to '{replacement}' to continue; fix the "
                            "source content to use unique UUIDs."
                        )
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
            assessment-results         → import-ap/@href
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
        # Register self by content identity before resolving imports. Root-UUID collision
        # detection in :meth:`_acquire_shared` only fires against *already-registered*
        # objects; a root document is loaded (not acquired) and so is otherwise never
        # registered. Without this, a profile that imports another document sharing its
        # root uuid (e.g. a FedRAMP profile importing a sibling/tailoring profile emitted
        # with the same uuid) would not get that import uuid-reassigned — and
        # ``get_oscal_object`` would then resolve the import's controls back to this
        # document, breaking the fetch (previously a stack overflow; now "not found").
        registered_self = self._register_self_by_identity()
        self._registry.enter_resolving(self_canonical)
        try:
            return self._resolve_imports_inner(base_path, cache_directive)
        finally:
            self._registry.exit_resolving(self_canonical)
            # Drop the transient self-registration so the registry keeps its role as a
            # shared-import cache (roots are loaded, not shared) — the reassignment of any
            # colliding child has already been applied and persists on that child.
            if registered_self:
                self._registry.forget(self)

    # -------------------------------------------------------------------------
    def _register_self_by_identity(self) -> bool:
        """Transiently register this document under its content-identity key (key-only).

        Enables :meth:`_acquire_shared` to detect an imported document that collides with
        this document's own root uuid while its imports resolve. Registers by key only
        (not href) so collision/identity dedup sees it without altering href fast-path
        resolution. Returns True when it added a registration (so the caller drops it
        afterward); False when there is no identity key or an entry already exists.
        """
        key = self._identity_key()
        if key is None or self._registry.get(key=key) is not None:
            return False
        self._registry.register(self, key=key)
        return True

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

        # --- Defensive normalization ---
        # Accept bytes (decode as UTF-8, which also strips a BOM via 'utf-8-sig') and strip
        # a leading UTF-8 BOM from str input. Content handed in from an external fetch (an API
        # response with no file extension, a re-encoded file) is detected by its actual data;
        # a stray BOM otherwise misdetects JSON as YAML, and raw bytes crash format detection.
        if isinstance(content, (bytes, bytearray)):
            content = bytes(content).decode("utf-8-sig", errors="replace")
            logger.debug("Content was bytes; decoded as UTF-8 for detection.")
        elif isinstance(content, str) and content[:1] == "\ufeff":
            content = content.lstrip("\ufeff")
            logger.debug("Stripped a leading UTF-8 BOM from string content.")

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
            self.requested_oscal_version = oscal_version
            resolved_version = oscal_version

            # If the declared version has no local support, try to acquire it (bundled DB,
            # then NIST) or substitute the closest same-major version — reflecting the
            # outcome in version_support (see OSCALSupport.ensure_version).
            if oscal_version not in self._support.versions:
                resolved_version, outcome = self._support.ensure_version(oscal_version)
                if outcome == "closest-match":
                    self.version_support = VersionSupport.CLOSEST_MATCH
                    logger.warning(
                        f"OSCAL version '{oscal_version}' is unavailable; validating and "
                        f"converting against the closest available version '{resolved_version}'."
                    )
                elif outcome == "unavailable":
                    self.version_support = VersionSupport.UNSUPPORTED
                    self.resolved_oscal_version = ""
                    logger.error(
                        f"OSCAL version '{oscal_version}' is not supported and could not be acquired."
                    )
                    status = False

            if status:
                self.oscal_version = resolved_version
                self.resolved_oscal_version = resolved_version
                if oscal_root in self._support.list_models(self.oscal_version):
                    self.model = oscal_root
                    logger.debug(
                        f"OSCAL model '{self.model}' identified (declared version "
                        f"'{self.requested_oscal_version}', using support version '{self.oscal_version}')."
                    )
                    status = True
                else:
                    logger.error(
                        f"Root element '{oscal_root}' is not a recognized OSCAL model "
                        f"for version '{self.oscal_version}'."
                    )
                    self.version_support = VersionSupport.UNSUPPORTED
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
                # Defensively repair a non-conformant URI (e.g. backslashes/spaces) in place
                # so the content becomes valid rather than merely flagged.
                if datatype in ("uri", "uri-reference"):
                    fixed = normalize_uri_reference(flag_val)
                    if fixed != flag_val:
                        logger.warning(f"Repaired non-conformant {datatype} @{flag_name} at {location}: {flag_val!r} -> {fixed!r}")
                        instance[flag_name] = flag_val = fixed
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
                    # Defensively repair a non-conformant URI value in place (see flags above).
                    if datatype in ("uri", "uri-reference"):
                        fixed = normalize_uri_reference(child_val)
                        if fixed != child_val:
                            logger.warning(f"Repaired non-conformant {datatype} {child_name} at {location}: {child_val!r} -> {fixed!r}")
                            instance[json_key] = child_val = fixed
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
        """Return the content as an XML string in canonical element order.

        Rebuilds from the current dict via the metaschema converter (reflecting
        the latest edits, in schema-required element order) and retains no tree.
        """
        return self._serialize_xml()

    # -------------------------------------------------------------------------
    @property
    def json(self) -> str:
        """Return the content as a JSON string in canonical key order."""
        if self._dict is None:
            logger.error("No content available for JSON serialization.")
            return ""
        return json.dumps(self._ordered_dict(), indent=INDENT)

    # -------------------------------------------------------------------------
    @property
    def yaml(self) -> str:
        """Return the content as a YAML string in canonical key order."""
        if self._dict is None:
            logger.error("No content available for YAML serialization.")
            return ""
        return yaml.dump(self._ordered_dict(), sort_keys=False, indent=INDENT)

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
        # An explicit last-modified must survive the post-mutation revision stamp.
        if "last-modified" in content:
            self._identity_override["last-modified"] = metadata["last-modified"]
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
    def _on_content_mutated(self) -> None:
        """Hook invoked after a successful content mutation.

        Stamps a new document revision (see :meth:`_stamp_revision`): any change to OSCAL
        content assigns a fresh root ``uuid`` and ``last-modified``, since the root uuid
        identifies *this instance* of the document and must change when it is revised.
        Subclasses override to react to edits — e.g.
        :class:`~oscal.oscal_controls.Profile` also invalidates a stale resolved catalog —
        and must call ``super()._on_content_mutated()``. Called by
        :func:`if_update_successful`-decorated mutators and by :meth:`put` on success.
        """
        self._stamp_revision()

    # -------------------------------------------------------------------------
    def _stamp_revision(self) -> None:
        """Assign a fresh root ``uuid`` and ``last-modified``, in content and on the cache.

        The OSCAL root ``uuid`` identifies a specific instance/revision of a document, so
        every mutation (and :meth:`new`) yields a new one, alongside a refreshed
        ``metadata/last-modified``. Writes ``_dict`` directly — never through :meth:`put`
        or a mutator — so it does not re-enter :meth:`_on_content_mutated`. A no-op when
        content or its model root is unavailable.
        """
        if not isinstance(self._dict, dict):
            return
        root = self._dict.get(self.model)
        if not isinstance(root, dict):
            return
        # A mutation that *explicitly* set the root uuid or last-modified wins over the
        # auto-stamp (e.g. set_metadata({"last-modified": ...}) or put("uuid", ...)); such
        # values are recorded in _identity_override by the mutating call and consumed here.
        override = getattr(self, "_identity_override", None) or {}
        self._identity_override = {}
        new_id = override.get("uuid") or new_uuid()
        stamp = override.get("last-modified") or oscal_date_time_with_timezone()
        root["uuid"] = new_id
        meta = root.get("metadata")
        if isinstance(meta, dict):
            meta["last-modified"] = stamp
        # Keep the cached identity in sync with the content.
        self.uuid = new_id
        self.last_modified = stamp
        self._identity = (new_id, stamp, self.published) if new_id else None

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

        # An explicit write of the root uuid or metadata/last-modified must survive the
        # post-mutation revision stamp (see _stamp_revision).
        if path == "uuid":
            self._identity_override["uuid"] = value
        elif path == "metadata/last-modified":
            self._identity_override["last-modified"] = value

        # Dirty-state bookkeeping (done inline so a False return never marks unsaved).
        self.is_unsaved = True
        self.last_modified = oscal_date_time_with_timezone()
        self._on_content_mutated()
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
    @if_update_successful
    def update_resource(self, uuid: str, *, title: Optional[str] = None,
                        description: Optional[str] = None, props: Optional[list] = None,
                        rlinks: Optional[list] = None, remarks: Optional[str] = None) -> dict | None:
        """Update fields of an existing ``back-matter`` resource, selected by ``uuid``.

        Only a resource defined in THIS document's own ``back-matter`` is editable
        (imported resources are not). Each field is optional and independent:

        * ``None`` (the default) leaves that field untouched.
        * A scalar (``title``/``description``/``remarks``) replaces the current value;
          an empty string removes the field entirely.
        * An array (``props``/``rlinks``) **replaces the existing array wholesale** — the
          old list is discarded and the supplied list becomes the new one. Passing an
          empty list removes the field.

        .. warning::
            Array replacement is destructive and total, not a merge. Whatever you pass
            for ``props`` or ``rlinks`` becomes the *complete* new list; every entry not
            present in your list is permanently dropped. A resource frequently carries
            entries you did not author and may not be aware of — for example multiple
            ``rlinks`` pointing at format variants (``.xml``/``.json``) of the same file,
            ``rlinks`` bearing ``hashes`` for integrity, a ``base64`` payload, or ``props``
            added by other tools or pipelines. Supplying a partial list here silently
            deletes all of those. There is no undo.

            **Recommended pattern:** read the current resource first with
            :meth:`get_resource_by_uuid`, mutate the copy it returns (append to / edit the
            existing ``props``/``rlinks`` rather than rebuilding them from scratch), then
            pass those full arrays back to this method. That way you extend the resource
            instead of overwriting it, and nothing you did not intend to touch is lost::

                res = doc.get_resource_by_uuid(uuid)          # safe copy of the whole resource
                res["rlinks"].append({"href": "catalog.json",
                                      "media-type": "application/json"})
                doc.update_resource(uuid, rlinks=res["rlinks"])   # full list, nothing dropped

        Args:
            uuid (str, required): UUID of the local back-matter resource to update.
            title (str | None, optional): New title; ``""`` removes it. ``None`` = unchanged.
            description (str | None, optional): New description; ``""`` removes it.
            props (list | None, optional): Replacement property dicts (see
                :func:`append_props`). ``[]`` removes all props. ``None`` = unchanged.
            rlinks (list | None, optional): Replacement ``rlink`` dicts (``href`` plus
                optional ``media-type``/``hashes``). ``[]`` removes all rlinks.
            remarks (str | None, optional): New remarks (markdown); ``""`` removes them.

        Returns:
            dict | None: A safe copy of the updated resource, or None when the content is
                read-only, ``uuid`` is empty, or no local resource with that UUID exists.
        """
        if not self._can_mutate("update_resource"):
            return None
        if not uuid:
            logger.error("update_resource: 'uuid' is required.")
            return None

        resources = self._import_root().get("back-matter", {}).get("resources", [])
        resource = next(
            (r for r in resources if isinstance(r, dict) and r.get("uuid") == uuid), None
        )
        if resource is None:
            logger.warning(f"update_resource: no local back-matter resource with uuid '{uuid}'.")
            return None

        # Scalars: None = unchanged; truthy = set; "" = remove.
        for field, value in (("title", title), ("description", description), ("remarks", remarks)):
            if value is None:
                continue
            if value:
                resource[field] = value
            else:
                resource.pop(field, None)

        # Arrays: None = unchanged; otherwise replace the whole list ([] removes it).
        if props is not None:
            resource.pop("props", None)
            if props:
                append_props(resource, props)  # normalizes ns defaults per prop
        if rlinks is not None:
            if rlinks:
                resource["rlinks"] = [
                    {k: v for k, v in rl.items() if k in ("href", "media-type", "hashes")}
                    for rl in rlinks
                ]
            else:
                resource.pop("rlinks", None)

        logger.debug(f"update_resource: resource '{uuid}' updated.")
        # Return a safe copy — the live resource stays in _dict; further edits go through methods.
        return copy.deepcopy(resource)

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
    # Kinds of element the import-tree resolver can locate, mapped to how they are
    # identified (uuid vs id). Extensible for model-specific needs.
    _RESOLVE_KINDS = ("resource", "role", "party", "location", "responsible-party",
                      "control", "group", "param", "part")

    def find_in_import_tree(self, fragment_id: str, kinds=None, _seen=None) -> Optional[dict]:
        """Resolve an id/uuid by searching this document and its import tree.

        OSCAL cross-references (``href="#..."``) can point at content that lives in an
        imported document — a back-matter ``resource`` (by uuid), a metadata ``role`` (by
        id), ``party`` (by uuid), ``location`` (by uuid), or ``responsible-party`` (by
        role-id), or a ``control``/``group``/``param``/``part`` (by id). This walks
        ``self`` first, then each imported document depth-first (de-duplicated,
        cycle-safe), and returns the first match together with the document that owns it.

        Args:
            fragment_id (str, required): The bare id/uuid to resolve (no leading ``#``).
            kinds (Iterable[str] | None, optional): Restrict the search to these element
                kinds (subset of :attr:`_RESOLVE_KINDS`); ``None`` searches all.
            _seen (set | None, optional): Internal cycle-guard.

        Returns:
            Optional[dict]: ``{"element", "kind", "id", "object_uuid", "href"}`` — a safe
                copy of the found element, its kind, the owning document's root uuid and
                resolved href — or None when not found anywhere in the tree.
        """
        if _seen is None:
            _seen = set()
        if id(self) in _seen:
            return None
        _seen.add(id(self))

        local = self._find_local_element(fragment_id, kinds)
        if local is not None:
            local["object_uuid"] = self.uuid
            local["href"] = self.href or self.href_original or ""
            return local

        for entry in self.import_list:
            obj = entry.get("object")
            if obj is None:
                continue
            found = obj.find_in_import_tree(fragment_id, kinds, _seen)
            if found is not None:
                return found
        return None

    # -------------------------------------------------------------------------
    def _lookup_in_scope(self, fragment_id: str, kind: str, with_source: bool = False,
                         local_only: bool = False):
        """Resolve one element ``kind`` by id/uuid in this doc (and, by default, its imports).

        Shared implementation for the ``get_*`` cross-reference getters. Looks in THIS
        document first; unless ``local_only`` is set it then cascades depth-first through
        the import tree (de-duplicated, cycle-safe) via :meth:`find_in_import_tree`,
        returning the first match.

        Args:
            fragment_id (str, required): The bare id/uuid to resolve (no ``#``).
            kind (str, required): The element kind to search (a member of
                :attr:`_RESOLVE_KINDS`).
            with_source (bool, optional): When False (default) return a safe copy of the
                element only; when True return the full locator
                ``{"element", "kind", "id", "object_uuid", "href"}`` — the element plus
                the owning document's root uuid and resolved href (useful for
                dereferencing an element's own relative references, e.g. rlinks).
            local_only (bool, optional): When True, search only THIS document's own
                content and do not fall back to imported documents. Defaults to False.

        Returns:
            Optional[dict]: The element (or full locator when ``with_source``), or None.
        """
        if local_only:
            found = self._find_local_element(fragment_id, kinds=[kind])
            if found is not None:
                found["object_uuid"] = self.uuid
                found["href"] = self.href or self.href_original or ""
        else:
            found = self.find_in_import_tree(fragment_id, kinds=[kind])
        if found is None:
            return None
        return found if with_source else found["element"]

    # -------------------------------------------------------------------------
    def get_parameter_by_id(self, param_id: str, with_source: bool = False) -> Optional[dict]:
        """Return a parameter defined anywhere in scope, or None.

        Searches this document and its import tree for a ``param`` with the given id —
        covering parameters defined at control, group, or catalog level (and reached
        through imported catalogs/profiles). Subclasses may override to prefer resolved
        content. See :meth:`_lookup_in_scope` for the ``with_source`` locator form.
        """
        return self._lookup_in_scope(param_id, "param", with_source)

    # -------------------------------------------------------------------------
    def get_resource_by_uuid(self, resource_uuid: str, with_source: bool = False,
                             local_only: bool = False) -> Optional[dict]:
        """Return a back-matter resource defined anywhere in scope, or None.

        Looks in THIS document's ``back-matter`` first; on a local miss the search
        cascades out through the immediately imported documents and continues depth-first
        along every branch (de-duplicated and cycle-safe) until a ``resource`` whose
        ``uuid`` matches is found or every branch is exhausted. This lets a cross-reference
        (``href="#uuid"``) resolve even when the resource is defined in an imported
        document rather than locally. Subclasses may override to prefer resolved content.

        Args:
            resource_uuid (str, required): The bare resource UUID to resolve (no ``#``).
            with_source (bool, optional): Return the full locator (element + owning
                ``object_uuid``/``href``) instead of the bare resource; useful for
                resolving the resource's relative rlink hrefs. Defaults to False.
            local_only (bool, optional): Search only THIS document, never imports.
                Defaults to False.

        Returns:
            Optional[dict]: A safe copy of the matching resource (or locator), or None.
        """
        return self._lookup_in_scope(resource_uuid, "resource", with_source, local_only)

    # -------------------------------------------------------------------------
    def get_role_by_id(self, role_id: str, with_source: bool = False,
                       local_only: bool = False) -> Optional[dict]:
        """Return a metadata ``role`` (by id) defined anywhere in scope, or None.

        Looks in THIS document's ``metadata.roles`` first, then (unless ``local_only``)
        cascades depth-first through the import tree until a role with the given id is
        found or every branch is exhausted — so a ``role-id`` reference resolves even when
        the role is defined in an imported document. See :meth:`_lookup_in_scope` for
        ``with_source`` and ``local_only``.
        """
        return self._lookup_in_scope(role_id, "role", with_source, local_only)

    # -------------------------------------------------------------------------
    def get_party_by_uuid(self, party_uuid: str, with_source: bool = False,
                          local_only: bool = False) -> Optional[dict]:
        """Return a metadata ``party`` (by uuid) defined anywhere in scope, or None.

        Looks in THIS document's ``metadata.parties`` first, then (unless ``local_only``)
        cascades depth-first through the import tree until a party with the given uuid is
        found or every branch is exhausted. See :meth:`_lookup_in_scope` for
        ``with_source`` and ``local_only``.
        """
        return self._lookup_in_scope(party_uuid, "party", with_source, local_only)

    # -------------------------------------------------------------------------
    def get_location_by_uuid(self, location_uuid: str, with_source: bool = False,
                             local_only: bool = False) -> Optional[dict]:
        """Return a metadata ``location`` (by uuid) defined anywhere in scope, or None.

        Looks in THIS document's ``metadata.locations`` first, then (unless ``local_only``)
        cascades depth-first through the import tree until a location with the given uuid
        is found or every branch is exhausted. See :meth:`_lookup_in_scope` for
        ``with_source`` and ``local_only``.
        """
        return self._lookup_in_scope(location_uuid, "location", with_source, local_only)

    # -------------------------------------------------------------------------
    def get_responsible_party_by_id(self, role_id: str, with_source: bool = False,
                                    local_only: bool = False) -> Optional[dict]:
        """Return a metadata ``responsible-party`` (by role-id) in scope, or None.

        A ``responsible-party`` is keyed by the ``role-id`` it fulfills. Looks in THIS
        document's ``metadata.responsible-parties`` first, then (unless ``local_only``)
        cascades depth-first through the import tree until one with the given role-id is
        found or every branch is exhausted. See :meth:`_lookup_in_scope` for
        ``with_source`` and ``local_only``.

        Note: this targets metadata-level ``responsible-parties`` only. The
        ``responsible-role`` assemblies embedded throughout implementation/assessment
        models are model-specific and handled by a separate, later cascade.
        """
        return self._lookup_in_scope(role_id, "responsible-party", with_source, local_only)

    # -------------------------------------------------------------------------
    def reachable_ids(self, _seen=None) -> set:
        """Return every ``id``/``uuid`` value in this document and its import tree.

        Used to decide whether a cross-reference resolves somewhere in scope. The walk
        is de-duplicated and cycle-safe across the import graph.
        """
        if _seen is None:
            _seen = set()
        if id(self) in _seen:
            return set()
        _seen.add(id(self))
        ids: set[str] = set()
        _collect_ids(self._dict, ids)
        for entry in self.import_list:
            obj = entry.get("object")
            if obj is not None:
                ids |= obj.reachable_ids(_seen)
        return ids

    # -------------------------------------------------------------------------
    def _find_local_element(self, fragment_id: str, kinds=None) -> Optional[dict]:
        """Find an element identified by ``fragment_id`` in THIS document only (no imports)."""
        wanted = tuple(kinds) if kinds else self._RESOLVE_KINDS
        root = self._dict.get(self.model, {}) if isinstance(self._dict, dict) else {}
        if not isinstance(root, dict):
            return None

        if "resource" in wanted:
            for res in root.get("back-matter", {}).get("resources", []):
                if isinstance(res, dict) and res.get("uuid") == fragment_id:
                    return {"element": copy.deepcopy(res), "kind": "resource", "id": fragment_id}
        metadata = root.get("metadata", {}) if isinstance(root.get("metadata"), dict) else {}
        if "role" in wanted:
            for role in metadata.get("roles", []):
                if isinstance(role, dict) and role.get("id") == fragment_id:
                    return {"element": copy.deepcopy(role), "kind": "role", "id": fragment_id}
        if "party" in wanted:
            for party in metadata.get("parties", []):
                if isinstance(party, dict) and party.get("uuid") == fragment_id:
                    return {"element": copy.deepcopy(party), "kind": "party", "id": fragment_id}
        if "location" in wanted:
            for loc in metadata.get("locations", []):
                if isinstance(loc, dict) and loc.get("uuid") == fragment_id:
                    return {"element": copy.deepcopy(loc), "kind": "location", "id": fragment_id}
        if "responsible-party" in wanted:
            # responsible-party is keyed by the role it fulfills (role-id), not a uuid.
            for rp in metadata.get("responsible-parties", []):
                if isinstance(rp, dict) and rp.get("role-id") == fragment_id:
                    return {"element": copy.deepcopy(rp), "kind": "responsible-party", "id": fragment_id}
        if any(k in wanted for k in ("control", "group", "param", "part")):
            found = _find_model_element(root, fragment_id, wanted)
            if found is not None:
                return found
        return None


    # -------------------------------------------------------------------------
    def dumps(self, format: str = "", pretty_print: bool = False) -> str:
        """
        Serialize the current content to a string in the specified format.

        Keys/elements are emitted in canonical NIST metaschema order: XML element
        order is schema-required and always canonical; JSON/YAML key order is
        canonical on a best-effort basis (see :meth:`_ordered_dict`).

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
            # XML element order is schema-significant (canonical order is required
            # for valid OSCAL XML). _serialize_xml rebuilds from the current dict
            # via the metaschema converter (canonical order + latest edits) and
            # releases the transient tree afterward.
            return self._serialize_xml(pretty_print=pretty_print)
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
    def _serialize_xml(self, pretty_print: bool = False) -> str:
        """Serialize to XML in canonical element order, retaining no XML tree.

        The XML tree is a transient, derived view of the JSON-primary ``self._dict``
        needed only at serialization time. Normal path: (re)build it from the
        current dict via the metaschema converter (canonical element order, and
        always reflecting the latest edits), serialize, then release it so it does
        not inflate the object's footprint (e.g. when persisting save-state).

        Degraded path: when no dict is available (XML was loaded but XML→JSON
        conversion produced no dict), the retained tree is the *only*
        representation of the content, so it is serialized in place and kept.

        Args:
            pretty_print (bool): Whether to pretty-print the output.

        Returns:
            str: The serialized XML, or "" when there is no content to serialize.
        """
        if self._dict is not None:
            if not self._build_tree():
                logger.error("Failed to build XML tree for serialization.")
                return ""
            out = self._xml_serializer(pretty_print=pretty_print)
            self._tree = None  # release the transient tree; rebuilt on demand next time
            return out
        if self._tree is not None:
            # Degraded fallback: no dict, tree is the sole representation — keep it.
            return self._xml_serializer(pretty_print=pretty_print)
        logger.error("No content available for XML serialization.")
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
    def _ordered_dict(self) -> dict | None:
        """Return a canonically key-ordered copy of ``self._dict`` for output.

        Reorders keys to the NIST metaschema canonical order (via
        :func:`~oscal.oscal_resequence.resequence_oscal`) so serialized JSON/YAML
        is emitted in canonical order. Best-effort: if resequencing is
        unavailable (e.g. no metaschema index for the model/version) or fails,
        the original ``self._dict`` is returned unchanged — key ordering in
        JSON/YAML is presentational, not semantic, so output is never blocked.
        Returns None only when there is no content.
        """
        if self._dict is None:
            return None
        try:
            return resequence_oscal(self._dict, version=self.oscal_version)
        except Exception as exc:  # never let cosmetic ordering break serialization
            logger.warning(f"Key resequencing skipped for {self.model} output: {exc}")
            return self._dict

    # -------------------------------------------------------------------------
    def _json_serializer(self, pretty_print: bool = False) -> str:
        """
        Serializes the current dict to a string, in canonical key order.
        Parameters:
        - pretty_print (bool): Whether to pretty-print the output. Defaults to False.
        Returns:
        - str: The serialized JSON content as a string.
        """
        logger.debug("Serializing dict for string output as JSON.")
        out_string = json.dumps(self._ordered_dict(), indent=INDENT if pretty_print else None, sort_keys=False)
        logger.debug("LEN: " + str(len(out_string)))

        return out_string

    # -------------------------------------------------------------------------
    def _yaml_serializer(self, pretty_print: bool = False) -> str:
        """
        Serializes the current dict to a string, in canonical key order.
        Parameters:
        - pretty_print (bool): Whether to pretty-print the output. Defaults to False.
        Returns:
        - str: The serialized YAML content as a string.
        """
        logger.debug("Serializing dict for string output as YAML.")
        out_string: str = yaml.dump(self._ordered_dict(), indent=INDENT if pretty_print else None, sort_keys=False)  # type: ignore[assignment]
        logger.debug("LEN: " + str(len(out_string)))

        return out_string

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Module-level functions that operate on an OSCAL document instance
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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

    The supplied ``title`` (and ``version``/``published`` when given) overwrite the
    template's placeholder metadata, so ``Catalog.new("X")`` / ``Profile.new("X")`` set
    the document title as expected.

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
                # Apply the requested metadata onto the template (the template ships
                # with placeholder title/version, which callers expect to override).
                if isinstance(oscal._dict, dict):
                    meta = oscal._dict.get(model_name, {}).get("metadata")
                    if isinstance(meta, dict):
                        if title:
                            meta["title"] = title
                        if version:
                            meta["version"] = version
                        if published:
                            meta["published"] = published
                return oscal
            logger.error(f"Template content failed validation for model: {model_name}")
            return None
        else:
            logger.error(f"Failed to load content for model: {model_name}")
            return None
    else:
        logger.error(f"Unsupported OSCAL model for new content: {model_name}")

    return None

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':
    print("OSCAL Class Module. This is not intended to be run as a stand-alone module.")

