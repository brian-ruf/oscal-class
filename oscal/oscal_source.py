"""
oscal_source — OSCAL source acquisition and reference/import resolution.

Standalone machinery for turning a source reference (path, URI, ref dict, or
``OscalRef``) into loaded content, plus the data types used by import
resolution. None of this depends on the OSCAL model classes: the dependency runs
one way — ``OSCAL`` methods in ``oscal_content`` call into here. ``oscal_content``
imports and re-exports these names, so existing
``from .oscal_content import load_content`` (etc.) call sites keep working.

Contents:
    OscalRef / _normalize_refs          — source reference model + normalization.
    ImportState / ImportFailureCode / ImportLoadError / ImportFailure
                                        — import-resolution status/failure types.
    load_content / load_source          — fetch/read content from a reference.
    classify_source                     — classify a reference by path/URI type.
    _resolve_href / _canonicalize_ref / _oscal_format_variants
                                        — href resolution/canonicalization helpers.
    _find_import_candidates / _pick_import_target / _remove_import_from_dict
                                        — import_list lookup and statement removal.
    _hrefs_from_dict_spec / _backmatter_resource
                                        — document href/back-matter extraction.
"""
from __future__       import annotations
import os
import logging
from dataclasses      import dataclass, field
from enum             import Enum
from urllib.parse     import urlparse, urljoin, urlunparse
from urllib.request   import urlopen
from urllib.error     import HTTPError, URLError

from ruf_common.network import download_file
from ruf_common.lfs     import getfile, normalize_content
from .oscal_cache       import get_local_cache, CacheDirective  # noqa: F401  (CacheDirective used in annotations)

logger = logging.getLogger(__name__)

# URI schemes we recognise but cannot fetch yet
_KNOWN_URI_SCHEMES = {"ftp", "ftps", "sftp", "s3", "gs", "az"}
# URI schemes we can handle with Python stdlib tooling (no third-party SDKs)
_SIMPLE_URI_SCHEMES = {"http", "https", "file", "ftp", "data"}


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
