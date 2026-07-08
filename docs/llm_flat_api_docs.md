# oscal — Library Documentation API Context
**Version:** 3.0.0
**Generated:** 2026-07-07T19:41:51Z
Generated from: `./oscal`

# Module: oscal.oscal_support

oscal_support — OSCAL support-file database and singleton accessor.

Manages the local SQLite database of NIST-published OSCAL support files
(metaschemas and XML/JSON schemas) for every OSCAL version and model, and
provides the ``OSCALSupport`` class along with helpers for validation and
format conversion.

Always obtain the shared instance via ``get_support()`` (optionally configured
first with ``configure_support()`` / ``setup_support()``). This ensures a single
support instance is shared across the application. The OSCAL content classes rely
on this instance to perform validation and conversion.

More information: https://github.com/brian-ruf/oscal-class/blob/main/docs/SUPPORT_MODULE.md

Module constants:
    SUPPORT_DATABASE_DEFAULT_FILE (str): Default path to the support DB
        (``"./support/oscal_support.db"``), resolved relative to the runtime CWD.
    SUPPORT_DATABASE_DEFAULT_TYPE (str): Default database backend (``"sqlite3"``).
    COMPRESS_SUPPORT_FILES_IN_DATABASE (bool): Whether support files are stored
        compressed in the database.
    OSCAL_DEFAULT_XML_NAMESPACE (str): The NIST OSCAL XML namespace URI.
    NIST_OSCAL_EXTENSION_NAMESPACE (str): The NIST OSCAL property/extension namespace URI.
    NIST_RMF_EXTENSION_NAMESPACE (str): The NIST RMF extension namespace URI.
    OSCAL_FORMATS (list): Supported serialization formats
        (``["xml", "json", "yaml", "yml"]``).
    DEFAULT_EXCLUDE_VERSIONS (list): OSCAL release tags excluded by default
        (release candidates and milestones).
    METASCHEMA_MIN_VERSION (str): Earliest version with NIST-published resolved
        metaschema files (``"v1.1.1"``).
    INDEX_REFRESH (int): Seconds before a cached metaschema index entry is stale
        (86400 = 24 hours).
    METASCHEMA_FILE_PATTERNS (dict): Filename-suffix → support-type map for
        metaschema files.
    SCHEMA_FILE_PATTERNS (dict): Filename-suffix → support-type map for XML/JSON
        schema files.
    OSCAL_SUPPORT_TABLES (dict): Schema definitions for the support database tables
        (``oscal_versions``, ``oscal_support``, ``filecache``).
    OSCAL_DATA_TYPES (dict): Data-type registry populated at runtime from parsed
        metaschemas.

## Class: OSCALSupport
Access layer for the local OSCAL support-file database.

Manages a SQLite database of NIST-published support files (metaschemas and
XML/JSON schemas) for every OSCAL version and model, and exposes methods for
querying supported versions/models, retrieving assets, building metaschema
indexes, and updating content from NIST's GitHub releases.

Prefer the module-level ``get_support()`` accessor over instantiating this
class directly, so a single instance is shared across the application.

Note:
    ``OSCAL_support`` is a backward-compatible alias for this class.

### Available Members

#### `def __init__(self, db_conn='./support/oscal_support.db', db_type='sqlite3', db_init_mode='auto', db_compress_files=True)`
Initialize OSCAL support and run startup (table checks / population).

Args:
    db_conn (str, optional): Database connection string or file path.
        Defaults to ``SUPPORT_DATABASE_DEFAULT_FILE``.
    db_type (str, optional): Database backend type (e.g. "sqlite3").
        Defaults to ``SUPPORT_DATABASE_DEFAULT_TYPE``.
    db_init_mode (str, optional): Database initialization mode. Defaults to "auto".
        - "auto": Extract from packaged resources if the file is missing/empty,
          otherwise use the existing file.
        - "extract": Always try to extract from resources; create empty if that fails.
        - "create": Always create an empty database from scratch.
    db_compress_files (bool, optional): Whether to store support files
        compressed in the database. Defaults to
        ``COMPRESS_SUPPORT_FILES_IN_DATABASE``.

#### `def add_asset(self, oscal_version, model_name, asset_type, content, filename=None)`
Add an asset to the support database. If the asset already exists, it will be replaced.
This method supports both string and bytes content types.
If the content is a string, it will be converted to bytes.
If the content is already in bytes, it will be used as is.
Args:
    oscal_version (str, required): The OSCAL version (e.g. "v1.0.0").
    model_name (str, required): The OSCAL model name (e.g. "system-security-plan").
    asset_type (str, required): The asset type (e.g. "xml-schema", "json-schema").
    content (str | bytes, required): The asset content; strings are encoded
        to UTF-8 bytes.
    filename (str, optional): Filename to record for the cached asset.
        Defaults to ``"{model_name}_{asset_type}"``.
Returns:
    bool: True if the asset was added successfully, False otherwise.

#### `def asset(self, oscal_version, model_name, asset_type)`
Backward-compatible wrapper for :meth:`get_asset`.

Args:
    oscal_version (str, required): The OSCAL version (e.g. "v1.0.0").
    model_name (str, required): The OSCAL model name (e.g. "system-security-plan").
    asset_type (str, required): The asset type (e.g. "xml-schema", "json-schema").

Returns:
    Any: The asset content if found, otherwise None.

#### `def download_schemas(self, support_dir: str, fetch: str = 'all') -> bool`
Download XML and JSON schema files to the filesystem.

Files are written to ``{support_dir}/{version}_schemas/`` directories and
are not stored in the support database.

Args:
    support_dir: Root directory under which per-version schema folders are created.
    fetch: ``"all"`` to download every known version, or a specific version
           tag (e.g. ``"v1.2.2"``) to download only that version.
Returns:
    True if all files were saved without error, False otherwise.

#### `def enumerate_models(self, version: str = 'all') -> list[str]`
Backward-compatible wrapper for :meth:`list_models`.

Args:
    version (str, optional): The OSCAL version to enumerate models for, or
        "all". Defaults to "all".

Returns:
    list[str]: Supported model-name strings (may be empty).

#### `def export_support_files(self, export_path='./support_files')`
Export all cached support files to a directory tree, grouped by version.

Args:
    export_path (str, optional): The directory to export support files to.
        Defaults to "./support_files".

Returns:
    bool: True if the export was successful, False otherwise.

#### `def get_asset(self, version, model, asset_type)`
Returns the asset for the specified OSCAL version and model name.
Args:
    version (str): The OSCAL version (e.g., "v1.0.0").
    model (str): The OSCAL model name (e.g., "system-security-plan").
    asset_type (str): The type of asset to retrieve (e.g., "xml-schema", "json-schema").
Returns:
    The asset content if found, None otherwise.

#### `def get_latest_version(self)`
Backward-compatible wrapper for :meth:`latest_version`.

Returns:
    Optional[str]: The latest OSCAL version tag, or None if none are loaded.

#### `def get_metaschema_index(self, version: str, model: str) -> dict | None`
Return the parsed metaschema index dict for the given OSCAL version and model.

Results are held in the module-level ``_metaschema_index_cache`` so that
only one copy of each index lives in memory and survives across calls.
A cached entry is reused until it is older than :data:`INDEX_REFRESH`
seconds (24 hours), at which point it is refreshed from the database.

Args:
    version: OSCAL version string, e.g. ``"v1.1.3"``.
    model:   OSCAL model name, e.g. ``"catalog"``.

Returns:
    The model-specific index dict on success, or ``None`` when the index
    is unavailable.

#### `def is_model_valid(self, model_name, version='all') -> bool`
Backward-compatible wrapper for :meth:`is_valid_model`.

Args:
    model_name (str, required): The OSCAL model name to check.
    version (str, optional): The OSCAL version to check against, or "all".
        Defaults to "all".

Returns:
    bool: True if the model is valid for the version, False otherwise.

#### `def is_valid_model(self, model, version='all') -> bool`
Check if the specified OSCAL model is valid for the given version.
Args:
    model (str): The OSCAL model name to check (e.g., "system-security-plan").
    version (str): The OSCAL version to check against (e.g., "v1.0.0").
Returns:
    bool: True if the model is valid for the specified version, False otherwise.

#### `def is_valid_version(self, version) -> bool`
Check if the specified OSCAL version is valid and supported.
Args:
    version (str): The OSCAL version to check (e.g., "v1.0.0").
Returns:
    bool: True if the version is valid and supported, False otherwise.

#### `def latest_version(self)`
Return the latest supported OSCAL version.

Returns:
    Optional[str]: The highest OSCAL version tag available in the support
        database, or None if none are loaded.

#### `def list_models(self, version: str = 'all') -> list[str]`
Enumerate the supported models for a given OSCAL version.
Args:
    version (str): The OSCAL version to enumerate models for (e.g., "v1.0.0").
Returns:
    list[str]: A list of model-name strings supported for the specified OSCAL version
               (may be empty).

#### `def load_file(self, name, binary=False, *, as_bytes=None)`
Load a file bundled in the ``oscal.data`` package resources, with caching.

Args:
    name (str, required): Filename of the resource within ``oscal.data``.
    binary (bool, optional): If True, return raw bytes; otherwise return
        UTF-8 decoded text. Defaults to False.
    as_bytes (bool, optional): Keyword-only alias for ``binary``; overrides
        it when provided. Defaults to None.

Returns:
    str | bytes | None: The file contents (text or bytes), or None on failure.

#### `def startup(self, check_for_updates=False, refresh_all=False)`
Perform startup tasks required to provide OSCAL support.

Ensures the support database has the required tables and data, populating
it from NIST's GitHub releases when empty, and sets ``self.ready``.

Args:
    check_for_updates (bool, optional): Reserved flag to check for newer
        OSCAL versions during startup. Defaults to False.
    refresh_all (bool, optional): Reserved flag to force a full refresh of
        all support content. Defaults to False.

Returns:
    bool: True if the support capability is ready, False otherwise.

Process:
1 Check for tables
  - If tables do not exist:
    - create tables
    - set state to "empty"
  - If tables exist, check for data
    - If no data, set state to "empty"
    - If data exists, set state to "populated"
2 If state is "empty", check for connection to GitHub
 - If cannot connect to GitHub, EXIT (cannot proceed)
 - If connected to GitHub, update database
   - If update fails, EXIT (cannot proceed)
   - If update succeeds, set state to "populated"
3 If state is "populated" set self.ready to True

#### `def supported(self, oscal_version, assets)`
Check whether the specified OSCAL version and assets are supported.

Note:
    Currently not implemented; always returns False.

Args:
    oscal_version (str, required): The OSCAL version to check (e.g. "v1.0.0").
    assets (list, required): The asset types to check for.

Returns:
    bool: True if the version and assets are supported, False otherwise.

#### `def update(self, mode='new', fetch=None)`
Update OSCAL support content based on a fetch directive.

Args:
    mode (str, optional): The fetch directive. Defaults to "new".
        - "all": Clear and re-fetch all OSCAL versions and support files.
        - "latest"/"new": Check for new OSCAL versions and fetch any found.
        - "vX.Y.Z": Clear and re-fetch a specific OSCAL version.
    fetch (str, optional): Legacy alias for ``mode``; when provided it
        overrides ``mode``. Defaults to None.

Returns:
    bool: True if the update was successful, False otherwise.

## Class: OSCAL_support
Access layer for the local OSCAL support-file database.

Manages a SQLite database of NIST-published support files (metaschemas and
XML/JSON schemas) for every OSCAL version and model, and exposes methods for
querying supported versions/models, retrieving assets, building metaschema
indexes, and updating content from NIST's GitHub releases.

Prefer the module-level ``get_support()`` accessor over instantiating this
class directly, so a single instance is shared across the application.

Note:
    ``OSCAL_support`` is a backward-compatible alias for this class.

### Available Members

#### `def __init__(self, db_conn='./support/oscal_support.db', db_type='sqlite3', db_init_mode='auto', db_compress_files=True)`
Initialize OSCAL support and run startup (table checks / population).

Args:
    db_conn (str, optional): Database connection string or file path.
        Defaults to ``SUPPORT_DATABASE_DEFAULT_FILE``.
    db_type (str, optional): Database backend type (e.g. "sqlite3").
        Defaults to ``SUPPORT_DATABASE_DEFAULT_TYPE``.
    db_init_mode (str, optional): Database initialization mode. Defaults to "auto".
        - "auto": Extract from packaged resources if the file is missing/empty,
          otherwise use the existing file.
        - "extract": Always try to extract from resources; create empty if that fails.
        - "create": Always create an empty database from scratch.
    db_compress_files (bool, optional): Whether to store support files
        compressed in the database. Defaults to
        ``COMPRESS_SUPPORT_FILES_IN_DATABASE``.

#### `def add_asset(self, oscal_version, model_name, asset_type, content, filename=None)`
Add an asset to the support database. If the asset already exists, it will be replaced.
This method supports both string and bytes content types.
If the content is a string, it will be converted to bytes.
If the content is already in bytes, it will be used as is.
Args:
    oscal_version (str, required): The OSCAL version (e.g. "v1.0.0").
    model_name (str, required): The OSCAL model name (e.g. "system-security-plan").
    asset_type (str, required): The asset type (e.g. "xml-schema", "json-schema").
    content (str | bytes, required): The asset content; strings are encoded
        to UTF-8 bytes.
    filename (str, optional): Filename to record for the cached asset.
        Defaults to ``"{model_name}_{asset_type}"``.
Returns:
    bool: True if the asset was added successfully, False otherwise.

#### `def asset(self, oscal_version, model_name, asset_type)`
Backward-compatible wrapper for :meth:`get_asset`.

Args:
    oscal_version (str, required): The OSCAL version (e.g. "v1.0.0").
    model_name (str, required): The OSCAL model name (e.g. "system-security-plan").
    asset_type (str, required): The asset type (e.g. "xml-schema", "json-schema").

Returns:
    Any: The asset content if found, otherwise None.

#### `def download_schemas(self, support_dir: str, fetch: str = 'all') -> bool`
Download XML and JSON schema files to the filesystem.

Files are written to ``{support_dir}/{version}_schemas/`` directories and
are not stored in the support database.

Args:
    support_dir: Root directory under which per-version schema folders are created.
    fetch: ``"all"`` to download every known version, or a specific version
           tag (e.g. ``"v1.2.2"``) to download only that version.
Returns:
    True if all files were saved without error, False otherwise.

#### `def enumerate_models(self, version: str = 'all') -> list[str]`
Backward-compatible wrapper for :meth:`list_models`.

Args:
    version (str, optional): The OSCAL version to enumerate models for, or
        "all". Defaults to "all".

Returns:
    list[str]: Supported model-name strings (may be empty).

#### `def export_support_files(self, export_path='./support_files')`
Export all cached support files to a directory tree, grouped by version.

Args:
    export_path (str, optional): The directory to export support files to.
        Defaults to "./support_files".

Returns:
    bool: True if the export was successful, False otherwise.

#### `def get_asset(self, version, model, asset_type)`
Returns the asset for the specified OSCAL version and model name.
Args:
    version (str): The OSCAL version (e.g., "v1.0.0").
    model (str): The OSCAL model name (e.g., "system-security-plan").
    asset_type (str): The type of asset to retrieve (e.g., "xml-schema", "json-schema").
Returns:
    The asset content if found, None otherwise.

#### `def get_latest_version(self)`
Backward-compatible wrapper for :meth:`latest_version`.

Returns:
    Optional[str]: The latest OSCAL version tag, or None if none are loaded.

#### `def get_metaschema_index(self, version: str, model: str) -> dict | None`
Return the parsed metaschema index dict for the given OSCAL version and model.

Results are held in the module-level ``_metaschema_index_cache`` so that
only one copy of each index lives in memory and survives across calls.
A cached entry is reused until it is older than :data:`INDEX_REFRESH`
seconds (24 hours), at which point it is refreshed from the database.

Args:
    version: OSCAL version string, e.g. ``"v1.1.3"``.
    model:   OSCAL model name, e.g. ``"catalog"``.

Returns:
    The model-specific index dict on success, or ``None`` when the index
    is unavailable.

#### `def is_model_valid(self, model_name, version='all') -> bool`
Backward-compatible wrapper for :meth:`is_valid_model`.

Args:
    model_name (str, required): The OSCAL model name to check.
    version (str, optional): The OSCAL version to check against, or "all".
        Defaults to "all".

Returns:
    bool: True if the model is valid for the version, False otherwise.

#### `def is_valid_model(self, model, version='all') -> bool`
Check if the specified OSCAL model is valid for the given version.
Args:
    model (str): The OSCAL model name to check (e.g., "system-security-plan").
    version (str): The OSCAL version to check against (e.g., "v1.0.0").
Returns:
    bool: True if the model is valid for the specified version, False otherwise.

#### `def is_valid_version(self, version) -> bool`
Check if the specified OSCAL version is valid and supported.
Args:
    version (str): The OSCAL version to check (e.g., "v1.0.0").
Returns:
    bool: True if the version is valid and supported, False otherwise.

#### `def latest_version(self)`
Return the latest supported OSCAL version.

Returns:
    Optional[str]: The highest OSCAL version tag available in the support
        database, or None if none are loaded.

#### `def list_models(self, version: str = 'all') -> list[str]`
Enumerate the supported models for a given OSCAL version.
Args:
    version (str): The OSCAL version to enumerate models for (e.g., "v1.0.0").
Returns:
    list[str]: A list of model-name strings supported for the specified OSCAL version
               (may be empty).

#### `def load_file(self, name, binary=False, *, as_bytes=None)`
Load a file bundled in the ``oscal.data`` package resources, with caching.

Args:
    name (str, required): Filename of the resource within ``oscal.data``.
    binary (bool, optional): If True, return raw bytes; otherwise return
        UTF-8 decoded text. Defaults to False.
    as_bytes (bool, optional): Keyword-only alias for ``binary``; overrides
        it when provided. Defaults to None.

Returns:
    str | bytes | None: The file contents (text or bytes), or None on failure.

#### `def startup(self, check_for_updates=False, refresh_all=False)`
Perform startup tasks required to provide OSCAL support.

Ensures the support database has the required tables and data, populating
it from NIST's GitHub releases when empty, and sets ``self.ready``.

Args:
    check_for_updates (bool, optional): Reserved flag to check for newer
        OSCAL versions during startup. Defaults to False.
    refresh_all (bool, optional): Reserved flag to force a full refresh of
        all support content. Defaults to False.

Returns:
    bool: True if the support capability is ready, False otherwise.

Process:
1 Check for tables
  - If tables do not exist:
    - create tables
    - set state to "empty"
  - If tables exist, check for data
    - If no data, set state to "empty"
    - If data exists, set state to "populated"
2 If state is "empty", check for connection to GitHub
 - If cannot connect to GitHub, EXIT (cannot proceed)
 - If connected to GitHub, update database
   - If update fails, EXIT (cannot proceed)
   - If update succeeds, set state to "populated"
3 If state is "populated" set self.ready to True

#### `def supported(self, oscal_version, assets)`
Check whether the specified OSCAL version and assets are supported.

Note:
    Currently not implemented; always returns False.

Args:
    oscal_version (str, required): The OSCAL version to check (e.g. "v1.0.0").
    assets (list, required): The asset types to check for.

Returns:
    bool: True if the version and assets are supported, False otherwise.

#### `def update(self, mode='new', fetch=None)`
Update OSCAL support content based on a fetch directive.

Args:
    mode (str, optional): The fetch directive. Defaults to "new".
        - "all": Clear and re-fetch all OSCAL versions and support files.
        - "latest"/"new": Check for new OSCAL versions and fetch any found.
        - "vX.Y.Z": Clear and re-fetch a specific OSCAL version.
    fetch (str, optional): Legacy alias for ``mode``; when provided it
        overrides ``mode``. Defaults to None.

Returns:
    bool: True if the update was successful, False otherwise.

## Module Functions

#### `def configure_support(support_file='./support/oscal_support.db', db_init_mode='auto', *, db_path: Optional[str] = None, init_mode: Optional[str] = None)`
Configure and create the shared OSCAL support instance.

Call this before ``get_support()`` and before any OSCAL content is loaded when
non-default settings are needed. If the shared instance already exists, it is
returned unchanged.

Args:
    support_file (str, optional): Path to the support database file.
        Defaults to ``SUPPORT_DATABASE_DEFAULT_FILE``.
    db_init_mode (str, optional): Database initialization mode — ``"auto"``,
        ``"extract"``, or ``"create"``. Defaults to ``"auto"``.
    db_path (str, optional): Keyword-only alias for ``support_file``; overrides
        it when provided.
    init_mode (str, optional): Keyword-only alias for ``db_init_mode``;
        overrides it when provided.

Returns:
    OSCALSupport: The shared support instance.

#### `def get_support()`
Return the shared OSCAL support instance, creating it if necessary.

Creates the instance with default settings (via ``configure_support()``) if it
does not already exist.

Returns:
    OSCALSupport: The shared support instance.

#### `def setup_support(support_file='./support/oscal_support.db', db_init_mode='auto')`
Compatibility wrapper around ``configure_support()`` for update utility scripts.

Args:
    support_file (str, optional): Path to the support database file.
        Defaults to ``SUPPORT_DATABASE_DEFAULT_FILE``.
    db_init_mode (str, optional): Database initialization mode
        (``"auto"``, ``"extract"``, or ``"create"``). Defaults to ``"auto"``.

Returns:
    OSCALSupport: The shared support instance.

# Module: oscal.oscal_content

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

## Class: ContentState
Progressive content-processing state; each level implies all prior levels passed.

Members (ordered by increasing progress):
    NONE (int): -1 — no content / uninitialized.
    NOT_AVAILABLE (int): 0 — content could not be acquired.
    ACQUIRED (int): 1 — content was acquired (non-empty string).
    WELL_FORMED (int): 2 — content is well-formed XML, JSON, or YAML.
    VALID (int): 3 — content passes OSCAL schema validation (minimum for view/edit).
    IMPORTS_RESOLVED (int): 4 — all imported OSCAL documents resolved successfully.

### Available Members

*No public members available.*

## Class: ImportFailure
Structured record of a failed import, carrying enough context for a retry attempt.

Retry sources the calling module may supply:
    - A URI fragment (#uuid) pointing to a back-matter resource
    - A full URI identifying an alternate location for the content
    - The content itself as an XML, JSON, or YAML string

### Available Members

#### `property is_fragment_ref`
True when the original import href is a back-matter fragment reference.

## Class: ImportFailureCode
Typed reason codes describing why an OSCAL import could not be resolved.

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

### Available Members

*No public members available.*

## Class: ImportLoadError
Exception carrying a typed import failure code from ``load_source()`` to ``resolve_imports()``.

Attributes:
    code (ImportFailureCode): The typed reason the import failed.
    uri (str): The URI that failed to load.

### Available Members

#### `def __init__(self, code: 'ImportFailureCode', uri: 'str', message: 'str' = '')`
Initialize the error.

Args:
    code (ImportFailureCode, required): The typed import failure reason.
    uri (str, required): The URI that failed to load.
    message (str, optional): Human-readable detail; a default is derived from
        ``code`` and ``uri`` when omitted.

## Class: ImportState
Resolution state of a single import entry in an OSCAL document's import_list.

Members:
    READY (str): "ready" — content is valid and loaded.
    NOT_LOADED (str): "not-loaded" — content has not been loaded.
    INVALID (str): "invalid" — content could not be loaded or failed validation.
    EXPIRED (str): "expired" — content is valid but the cached copy has expired.
    DUPLICATE (str): "duplicate" — the resolved href is already loaded by an earlier import.
    IGNORED (str): "ignored" — the caller explicitly chose to ignore this import.

### Available Members

*No public members available.*

## Class: OSCAL
Base class for all OSCAL model documents.

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

### Available Members

#### `classmethod def acquire(cls, source: 'str | dict | OscalRef | list')`
Acquire OSCAL content from one or more URI/reference sources.

The sources are treated as an ordered fallback list; the first that
resolves successfully is used.

Args:
    source (str | dict | OscalRef | list, required): The reference(s) to
        acquire. May be a URI/path string, an ``OscalRef``, a reference dict
        containing at least ``"href"``, or a list mixing any of these.

Returns:
    OSCAL: A new instance populated from the first resolvable source.

#### `def append_child(self, path: 'str', child: 'dict') -> 'dict | None'`
Appends a child dict to the list at the given JSON path.

Path segments are '/' separated, relative to the model root.  The leaf
segment names the list key; it is created as an empty list if absent.

Args:
    path (str):  Slash-separated path to the target list relative to the
                 model root, e.g. "metadata/props" or "back-matter/resources".
    child (dict): Dict to append to the list.

Returns:
    dict | None: The appended child on success, None on failure.

#### `def append_resource(self, uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def dump(self, filename: 'str' = '', format: 'str' = '', pretty_print: 'bool' = False) -> 'bool'`
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

#### `def dumps(self, format: 'str' = '', pretty_print: 'bool' = False) -> 'str'`
Serialize the current content to a string in the specified format.
Parameters:
- format (str): The target format for serialization ("xml", "json", or "yaml")
    Defaults to the original format of the content if not specified.
- pretty_print (bool): Whether to pretty-print the output. Defaults to False.

Returns:
- str: The serialized content as a string.

#### `property duplicate_imports`
Return import_list entries detected as duplicates of an earlier import.

Duplicates are non-blocking — they do NOT prevent imports_resolved from
becoming True — but they remain available for the caller to act on via
retry_import (supply a different source), ignore_import, or remove_import.

#### `property failed_imports`
Return import_list entries that failed, each carrying a populated 'failure' field.

These are blocking: while any failed import remains, content_state stays
at VALID and imports_resolved is False.

#### `def find_by_uuid(self, uuid, _seen=None)`
Search the import tree for an imported document containing a matching UUID.

Performs a depth-first search across resolved imports, tracking visited
objects to avoid infinite loops on circular imports.

Args:
    uuid (str, required): The UUID to search for.
    _seen (set | None, optional): Object ids already visited; used internally.
        Defaults to None.

Returns:
    OSCAL | None: The matching imported document, or None if not found.

#### `classmethod def from_string(cls, content: 'str', *, href: 'str | None' = None)`
Explicit constructor for in-memory OSCAL string content.

Args:
    content (str, required): Serialized OSCAL content.
    href (str | None, optional): URI identifying the source. Keyword-only.
        Defaults to None.

Returns:
    OSCAL: A new instance (delegates to :meth:`loads`).

#### `def ignore_import(self, href: 'str') -> 'bool'`
Mark an import as intentionally ignored.

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

#### `property import_tree`
Recursive import tree built lazily on first access and cached.

Returns a root node dict representing this document, with an 'imports'
key holding the first-level imports (each following the same structure
recursively).  The root node fields mirror those of an import_list entry.
Use rebuild_import_tree() to force a fresh traversal.

#### `property imports_resolved`
bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``).

#### `def initial_validation(self, content: 'str') -> 'bool'`
Perform initial validation of content and advance the content state.

Detects the format, checks that the content is a recognized, well-formed
OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
summary metadata, then invokes full OSCAL schema validation. Updates
``self.content_state`` progressively as each stage passes.

Args:
    content (str, required): The raw OSCAL content to validate.

Returns:
    bool: True if initial validation is successful, False otherwise.

#### `property is_acquired`
bool: True once content has been acquired (``content_state >= ACQUIRED``).

#### `property is_cache_expired`
True when remote cached content has exceeded its TTL.

#### `property is_editable`
Can this content be modified?

#### `property is_fresh`
True when content is local or cached and within its TTL.

#### `property is_remote`
bool: True when the content originates from a remote source (not a local file).

#### `property is_stale`
True when remote cached content has exceeded its TTL.

#### `property is_valid`
bool: True when content passes OSCAL validation (``content_state >= VALID``).

#### `property is_well_formed`
bool: True when content is well-formed (``content_state >= WELL_FORMED``).

#### `property json`
Return the content as a JSON string.

#### `def json_query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def json_query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`json_query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using JSON key names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `classmethod def load(cls, source: 'str | os.PathLike | _ReadableSource', *, href: 'str | None' = None)`
Initialize an instance from a local file path or file-like object.

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

#### `classmethod def loads(cls, content: 'str | dict', *, href: 'str | None' = None)`
Initialize an instance from in-memory OSCAL content.

Args:
    content (str | dict, required): OSCAL content already in memory, as a
        serialized string or a dict.
    href (str | None, optional): URI identifying the original content
        source. Keyword-only. Defaults to None.

Returns:
    OSCAL: A new instance populated from the content.

#### `classmethod def new(cls, title: 'str', version: 'str' = '', published: 'str' = '')`
Create a new OSCAL document from a template.

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

#### `classmethod def open(cls, source: 'str | os.PathLike | dict | OscalRef | list | _ReadableSource', *, href: 'str | None' = None)`
Universal constructor — inspects the source type and delegates to
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

#### `property origin_state`
Computed from is_local, is_cached, and TTL. Changes over time for cached remote content.

#### `def query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using OSCAL XML element names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `def rebuild_import_tree(self) -> 'dict'`
Discard the cached import tree and rebuild it from the current import_list.

Returns:
    dict: The freshly built root node of the recursive import tree.

#### `def remove_import(self, href: 'str') -> 'bool'`
Remove an import entry from both import_list and the document content.

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

#### `def resolve_imports(self, base_path: 'str' = '') -> 'list'`
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

#### `def retry_import(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Retry a failed import identified by href, using a replacement source.

The failed import is matched by href (original or previously resolved),
then re-attempted using ``replacement_href`` (resolved relative to this
document's location).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def retry_imports(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Compatibility alias for :meth:`retry_import` (plural method name).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def set_metadata(self, content: 'dict' = {}) -> 'bool'`
Set simple metadata fields on the OSCAL content's ``metadata`` section.

Complex metadata collections (revisions, roles, parties, links, props, etc.)
are not yet supported and are skipped with a warning.

Args:
    content (dict, optional): Mapping of metadata field name to value to set.
        Defaults to an empty dict.

Returns:
    bool: True on success, or None when the content cannot be mutated.

#### `property unresolved_imports`
Return import_list entries that still warrant user attention.

Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
READY (resolved) and IGNORED (explicitly dismissed by the caller).

This is the signal a UI should use to decide whether to keep showing
import-resolution affordances.  It stays non-empty while there is still
something the user can act on — even when ``imports_resolved`` is already
True because the only remaining items are non-blocking duplicates.
Once every entry is READY or IGNORED, this list is empty and the
resolution UI can close.

#### `def validate(self, format: 'str' = '') -> 'bool'`
Validate OSCAL content against the metaschema index in sequenced phases.

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

#### `def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope='successful')`
Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

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

#### `property xml`
Return the content as an XML string, converting from dict if necessary.

#### `property yaml`
Return the content as a YAML string.

## Class: OriginState
Origin/freshness state of a document's source (not progressive).

Freshness is time-based and computed on demand rather than stored.

Members:
    LOCAL (str): "local" — local file system source; always accessible.
    REMOTE_UNCACHED (str): "remote-uncached" — remote source with no local cache copy.
    REMOTE_FRESH (str): "remote-fresh" — remote source cached and within its TTL.
    REMOTE_STALE (str): "remote-stale" — remote source cached but past its TTL.

### Available Members

*No public members available.*

## Class: OscalRef
A single OSCAL source reference: an href with optional media type and hashes.

Attributes:
    href (str): The reference target (URI or path).
    media_type (str | None): Optional media type of the target.
    hashes (list[dict] | None): Optional integrity hashes for the target.
    source_type (str): Classified source type (set by classification; not an init arg).
    source_scheme (str): URI scheme of the source (not an init arg).
    source_supported (bool): Whether the source scheme can be fetched (not an init arg).

### Available Members

*No public members available.*

## Class: _ReadableSource
Protocol for file-like objects that provide read().

### Available Members

#### `def read(self, size: 'int' = -1) -> 'Any'`
Read up to ``size`` bytes/characters from the source (``-1`` reads all).

## Module Functions

#### `def append_link(parent_obj: 'dict', link: 'dict') -> 'dict'`
Append a single link dict to ``parent_obj["links"]``.

Args:
    parent_obj (dict, required): OSCAL JSON object that will receive the link.
    link (dict, required): Link dict. Required key: "href".
        Optional keys: "rel", "media-type", "resource-fragment", "text".

Returns:
    dict: The appended link entry (filtered to recognized keys).

#### `def append_links(parent_obj: 'dict', links: 'list') -> 'None'`
Append multiple link dicts to ``parent_obj["links"]``.

Args:
    parent_obj (dict, required): OSCAL JSON object that will receive the links.
    links (list, required): Link dicts, each with at minimum an "href" key.

Returns:
    None

#### `def append_prop(parent_obj: 'dict', prop: 'dict') -> 'dict'`
Append a single prop dict to ``parent_obj["props"]``.

Args:
    parent_obj (dict, required): OSCAL JSON object that will receive the prop.
    prop (dict, required): Property dict. Required keys: "name", "value".
        Optional keys: "uuid", "ns", "class", "group", "remarks".

Returns:
    dict: The appended prop entry (filtered to recognized keys).

#### `def append_props(parent_obj: 'dict', props: 'list') -> 'None'`
Append multiple prop dicts to ``parent_obj["props"]``.

Args:
    parent_obj (dict, required): OSCAL JSON object that will receive the props.
    props (list, required): Property dicts, each with at minimum "name" and "value".

Returns:
    None

#### `def append_resource(oscal_obj: 'OSCAL', uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def classify_source(ref: 'OscalRef', only_oscal: 'bool' = False) -> 'bool'`
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

#### `def create_new_oscal_content(model_name: 'str', title: 'str', version: 'str' = '', published: 'str' = '', format: 'str' = 'xml') -> 'Optional[OSCAL]'`
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

#### `def if_update_successful(fn)`
Decorator marking content dirty after a successful mutation.

Wraps a mutation method; when it returns a non-None result, sets
``self.is_unsaved = True`` and updates ``self.last_modified``.

Args:
    fn (Callable, required): The mutation method to wrap.

Returns:
    Callable: The wrapped method.

#### `def load_content(source: 'str | dict | OscalRef | list', media_type: 'str' = '', only_oscal: 'bool' = False) -> 'str'`
Load content from one or more sources and return the first successful payload.

Args:
    source (str | dict | OscalRef | list, required): The source(s) to load, as a
        URI/path string, reference dict, ``OscalRef``, or a fallback list of these.
    media_type (str, optional): Expected media type hint. Defaults to "".
    only_oscal (bool, optional): When True, restrict acceptance to OSCAL content.
        Defaults to False.

Returns:
    str: The first successfully loaded content payload, or "" if none load and no
        typed error was raised.

Raises:
    ImportLoadError: When a source fails with a typed reason (the last error is
        re-raised when every source in a list fails).

#### `def load_source(ref: 'OscalRef') -> 'str'`
Fetch or read content from a classified ``OscalRef``.

Args:
    ref (OscalRef, required): A reference that has already been classified
        (via :func:`classify_source`) to set its source type/scheme.

Returns:
    str: The raw content as a string on success.

Raises:
    ImportLoadError: With a typed ``ImportFailureCode`` on any load failure.

#### `def new_uuid() -> 'str'`
Generate a new random (version 4) UUID string.

Returns:
    str: A newly generated UUID in canonical string form.

#### `def oscal_markdown_to_html_tree(markdown_text: 'str', multiline: 'bool' = True) -> 'Optional[ElementTree.Element]'`
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

#### `def requires(**conditions)`
Decorator factory gating a method on instance attribute/property values.

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

#### `def requires_state(min_state: 'ContentState')`
Decorator factory gating a method on a minimum ``ContentState`` level.

The wrapped method runs only when ``self.content_state >= min_state``;
otherwise it logs an error and returns None.

Args:
    min_state (ContentState, required): Minimum content state required to run
        the method.

Returns:
    Callable: A decorator that wraps the target method with the guard.

# Module: oscal.oscal_datatypes

oscal_datatypes — OSCAL Metaschema data type definitions and helpers.

Defines the OSCAL Metaschema primitive data types and their validation
patterns, and provides a helper for producing OSCAL-conformant timezone-aware
date-time strings.

Module constants:
    OSCAL_DATATYPES (dict): Mapping of OSCAL Metaschema data type name (str) to
        a definition dict. Each definition contains the keys ``base-type`` (str),
        ``xml-pattern`` (str regex), ``json-pattern`` (str regex),
        ``recommended-pattern`` (str regex), ``documentation`` (str),
        ``remarks`` (str), and ``links`` (list of {"title", "url"} dicts).
        Covers types such as ``string``, ``token``, ``uuid``, ``uri``,
        ``date-time-with-timezone``, ``integer``, ``boolean``, ``markup-line``,
        and ``markup-multiline``.

## Module Functions

#### `def oscal_date_time_with_timezone(date_time=None, format='%Y-%m-%dT%H:%M:%SZ') -> str`
Convert a date/time to UTC and format it as an OSCAL date-time-with-timezone string.

Args:
    date_time (datetime | str, optional): The date and time to convert. May be a
        ``datetime`` object or an ISO-8601 string parseable into one. Naive values
        are assumed to be UTC. Defaults to the current date and time.
    format (str, optional): The ``strftime`` format string to apply.
        Defaults to ``"%Y-%m-%dT%H:%M:%SZ"`` (the OSCAL standard format).

Returns:
    str: The formatted date-time string, or an empty string if parsing or
        formatting fails.

# Module: oscal.oscal_controls

oscal_controls — OSCAL control-layer model classes.

Provides the editable model classes for the OSCAL control models: ``Catalog``
(defines controls), ``Profile`` (selects and tailors controls into baselines),
and ``Mapping`` (relates controls across frameworks). Each class subclasses
``OSCAL`` from ``oscal_content`` and adds model-specific navigation and
mutation helpers.

Module constants:
    (none exported)

## Class: Catalog
Editable OSCAL Catalog model.

Subclasses ``OSCAL`` and adds methods for creating and navigating controls
and control groups. Read-only guards apply to mutation methods when the
instance state is not editable.

### Available Members

#### `classmethod def acquire(cls, source: 'str | dict | OscalRef | list')`
Acquire OSCAL content from one or more URI/reference sources.

The sources are treated as an ordered fallback list; the first that
resolves successfully is used.

Args:
    source (str | dict | OscalRef | list, required): The reference(s) to
        acquire. May be a URI/path string, an ``OscalRef``, a reference dict
        containing at least ``"href"``, or a list mixing any of these.

Returns:
    OSCAL: A new instance populated from the first resolvable source.

#### `def append_child(self, path: 'str', child: 'dict') -> 'dict | None'`
Appends a child dict to the list at the given JSON path.

Path segments are '/' separated, relative to the model root.  The leaf
segment names the list key; it is created as an empty list if absent.

Args:
    path (str):  Slash-separated path to the target list relative to the
                 model root, e.g. "metadata/props" or "back-matter/resources".
    child (dict): Dict to append to the list.

Returns:
    dict | None: The appended child on success, None on failure.

#### `def append_resource(self, uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def create_control(self, parent_id: str, id: str, title: str = '', params: list = [], props: list = [], links: list = [], label: str = '', sort_id: str = '', alt_identifier: str = '', overview: str = '', statements: list = [], guidance: str = '', example: str = '', objectives: list = [], objects: list = [], methods: list = [], remarks: str = '') -> Optional[dict]`
Create a new control under the specified parent group.

Args:
    parent_id (str, required): ID of the parent group to add the control to.
    id (str, required): ID of the new control.
    title (str, optional): Title of the new control. Defaults to the label,
        or the id, when empty.
    params (list, optional): Parameters to add. Items may be parameter id
        strings or full parameter dicts.
    props (list, optional): Additional property dicts to add.
    links (list, optional): Link dicts to add.
    label (str, optional): Value for the inline ``label`` property.
    sort_id (str, optional): Value for the inline ``sort-id`` property.
    alt_identifier (str, optional): Value for the inline ``alt-identifier`` property.
    overview (str, optional): Prose (markdown) for the ``overview`` part.
    statements (list, optional): Statement items — strings or
        ``{'id':..., 'prose':...}`` dicts.
    guidance (str, optional): Prose (markdown) for the ``guidance`` part.
    example (str, optional): Prose (markdown) for the ``example`` part.
    objectives (list, optional): Assessment objective items.
    objects (list, optional): Assessment object items.
    methods (list, optional): Assessment method items.
    remarks (str, optional): Remarks prose (markdown).

Returns:
    Optional[dict]: The newly created control dict, or None on failure.

#### `def create_control_group(self, parent_id: str, id: str, title: str = '', params: list = [], props: list = [], links: list = [], label: str = '', sort_id: str = '', alt_identifier: str = '', overview: str = '', instruction: str = '', remarks: str = '') -> Optional[dict]`
Create a new catalog group.

Args:
    parent_id (str, required): ID of the parent group, or ``'[root]'`` (or an
        empty string) for the catalog top level.
    id (str, required): ID of the new group.
    title (str, optional): Title of the new group.
    params (list, optional): Parameters to add to the group.
    props (list, optional): Additional property dicts to add.
    links (list, optional): Link dicts to add.
    label (str, optional): Value for the inline ``label`` property.
    sort_id (str, optional): Value for the inline ``sort-id`` property.
    alt_identifier (str, optional): Value for the inline ``alt-identifier`` property.
    overview (str, optional): Prose (markdown) for the ``overview`` part.
    instruction (str, optional): Prose (markdown) for the ``instruction`` part.
    remarks (str, optional): Remarks prose (markdown).

Returns:
    Optional[dict]: The newly created group dict, or None on failure.

#### `def dump(self, filename: 'str' = '', format: 'str' = '', pretty_print: 'bool' = False) -> 'bool'`
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

#### `def dumps(self, format: 'str' = '', pretty_print: 'bool' = False) -> 'str'`
Serialize the current content to a string in the specified format.
Parameters:
- format (str): The target format for serialization ("xml", "json", or "yaml")
    Defaults to the original format of the content if not specified.
- pretty_print (bool): Whether to pretty-print the output. Defaults to False.

Returns:
- str: The serialized content as a string.

#### `property duplicate_imports`
Return import_list entries detected as duplicates of an earlier import.

Duplicates are non-blocking — they do NOT prevent imports_resolved from
becoming True — but they remain available for the caller to act on via
retry_import (supply a different source), ignore_import, or remove_import.

#### `property failed_imports`
Return import_list entries that failed, each carrying a populated 'failure' field.

These are blocking: while any failed import remains, content_state stays
at VALID and imports_resolved is False.

#### `def find_by_uuid(self, uuid, _seen=None)`
Search the import tree for an imported document containing a matching UUID.

Performs a depth-first search across resolved imports, tracking visited
objects to avoid infinite loops on circular imports.

Args:
    uuid (str, required): The UUID to search for.
    _seen (set | None, optional): Object ids already visited; used internally.
        Defaults to None.

Returns:
    OSCAL | None: The matching imported document, or None if not found.

#### `classmethod def from_string(cls, content: 'str', *, href: 'str | None' = None)`
Explicit constructor for in-memory OSCAL string content.

Args:
    content (str, required): Serialized OSCAL content.
    href (str | None, optional): URI identifying the source. Keyword-only.
        Defaults to None.

Returns:
    OSCAL: A new instance (delegates to :meth:`loads`).

#### `def get_control_by_id(self, control_id: str) -> Optional[dict]`
Retrieve a control dict by its ID, searching all groups recursively.

Args:
    control_id (str, required): The ``id`` of the control to find.

Returns:
    Optional[dict]: The matching control dict, or None if not found.

#### `def get_control_list(self) -> list`
Return a flat list of every control dict in the catalog, at all levels.

Returns:
    list: All control dicts found across the catalog and its groups.

#### `def get_group_by_id(self, group_id: str) -> Optional[dict]`
Retrieve a group dict by its ID, searching nested groups recursively.

Args:
    group_id (str, required): The ``id`` of the group to find.

Returns:
    Optional[dict]: The matching group dict, or None if not found.

#### `def ignore_import(self, href: 'str') -> 'bool'`
Mark an import as intentionally ignored.

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

#### `property import_tree`
Recursive import tree built lazily on first access and cached.

Returns a root node dict representing this document, with an 'imports'
key holding the first-level imports (each following the same structure
recursively).  The root node fields mirror those of an import_list entry.
Use rebuild_import_tree() to force a fresh traversal.

#### `property imports_resolved`
bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``).

#### `def initial_validation(self, content: 'str') -> 'bool'`
Perform initial validation of content and advance the content state.

Detects the format, checks that the content is a recognized, well-formed
OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
summary metadata, then invokes full OSCAL schema validation. Updates
``self.content_state`` progressively as each stage passes.

Args:
    content (str, required): The raw OSCAL content to validate.

Returns:
    bool: True if initial validation is successful, False otherwise.

#### `property is_acquired`
bool: True once content has been acquired (``content_state >= ACQUIRED``).

#### `property is_cache_expired`
True when remote cached content has exceeded its TTL.

#### `property is_editable`
Can this content be modified?

#### `property is_fresh`
True when content is local or cached and within its TTL.

#### `property is_remote`
bool: True when the content originates from a remote source (not a local file).

#### `property is_stale`
True when remote cached content has exceeded its TTL.

#### `property is_valid`
bool: True when content passes OSCAL validation (``content_state >= VALID``).

#### `property is_well_formed`
bool: True when content is well-formed (``content_state >= WELL_FORMED``).

#### `property json`
Return the content as a JSON string.

#### `def json_query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def json_query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`json_query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using JSON key names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `classmethod def load(cls, source: 'str | os.PathLike | _ReadableSource', *, href: 'str | None' = None)`
Initialize an instance from a local file path or file-like object.

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

#### `classmethod def loads(cls, content: 'str | dict', *, href: 'str | None' = None)`
Initialize an instance from in-memory OSCAL content.

Args:
    content (str | dict, required): OSCAL content already in memory, as a
        serialized string or a dict.
    href (str | None, optional): URI identifying the original content
        source. Keyword-only. Defaults to None.

Returns:
    OSCAL: A new instance populated from the content.

#### `classmethod def new(cls, title: 'str', version: 'str' = '', published: 'str' = '')`
Create a new OSCAL document from a template.

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

#### `classmethod def open(cls, source: 'str | os.PathLike | dict | OscalRef | list | _ReadableSource', *, href: 'str | None' = None)`
Universal constructor — inspects the source type and delegates to
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

#### `property origin_state`
Computed from is_local, is_cached, and TTL. Changes over time for cached remote content.

#### `def query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using OSCAL XML element names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `def rebuild_import_tree(self) -> 'dict'`
Discard the cached import tree and rebuild it from the current import_list.

Returns:
    dict: The freshly built root node of the recursive import tree.

#### `def remove_import(self, href: 'str') -> 'bool'`
Remove an import entry from both import_list and the document content.

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

#### `def resolve_imports(self, base_path: 'str' = '') -> 'list'`
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

#### `def retry_import(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Retry a failed import identified by href, using a replacement source.

The failed import is matched by href (original or previously resolved),
then re-attempted using ``replacement_href`` (resolved relative to this
document's location).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def retry_imports(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Compatibility alias for :meth:`retry_import` (plural method name).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def set_metadata(self, content: 'dict' = {}) -> 'bool'`
Set simple metadata fields on the OSCAL content's ``metadata`` section.

Complex metadata collections (revisions, roles, parties, links, props, etc.)
are not yet supported and are skipped with a warning.

Args:
    content (dict, optional): Mapping of metadata field name to value to set.
        Defaults to an empty dict.

Returns:
    bool: True on success, or None when the content cannot be mutated.

#### `property unresolved_imports`
Return import_list entries that still warrant user attention.

Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
READY (resolved) and IGNORED (explicitly dismissed by the caller).

This is the signal a UI should use to decide whether to keep showing
import-resolution affordances.  It stays non-empty while there is still
something the user can act on — even when ``imports_resolved`` is already
True because the only remaining items are non-blocking duplicates.
Once every entry is READY or IGNORED, this list is empty and the
resolution UI can close.

#### `def validate(self, format: 'str' = '') -> 'bool'`
Validate OSCAL content against the metaschema index in sequenced phases.

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

#### `def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope='successful')`
Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

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

#### `property xml`
Return the content as an XML string, converting from dict if necessary.

#### `property yaml`
Return the content as a YAML string.

## Class: Mapping
Class representing an OSCAL Mapping object.
Inherits common OSCAL functionality and adds mapping-specific methods
for managing mappings between controls and other objects.

### Available Members

#### `classmethod def acquire(cls, source: 'str | dict | OscalRef | list')`
Acquire OSCAL content from one or more URI/reference sources.

The sources are treated as an ordered fallback list; the first that
resolves successfully is used.

Args:
    source (str | dict | OscalRef | list, required): The reference(s) to
        acquire. May be a URI/path string, an ``OscalRef``, a reference dict
        containing at least ``"href"``, or a list mixing any of these.

Returns:
    OSCAL: A new instance populated from the first resolvable source.

#### `def append_child(self, path: 'str', child: 'dict') -> 'dict | None'`
Appends a child dict to the list at the given JSON path.

Path segments are '/' separated, relative to the model root.  The leaf
segment names the list key; it is created as an empty list if absent.

Args:
    path (str):  Slash-separated path to the target list relative to the
                 model root, e.g. "metadata/props" or "back-matter/resources".
    child (dict): Dict to append to the list.

Returns:
    dict | None: The appended child on success, None on failure.

#### `def append_resource(self, uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def dump(self, filename: 'str' = '', format: 'str' = '', pretty_print: 'bool' = False) -> 'bool'`
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

#### `def dumps(self, format: 'str' = '', pretty_print: 'bool' = False) -> 'str'`
Serialize the current content to a string in the specified format.
Parameters:
- format (str): The target format for serialization ("xml", "json", or "yaml")
    Defaults to the original format of the content if not specified.
- pretty_print (bool): Whether to pretty-print the output. Defaults to False.

Returns:
- str: The serialized content as a string.

#### `property duplicate_imports`
Return import_list entries detected as duplicates of an earlier import.

Duplicates are non-blocking — they do NOT prevent imports_resolved from
becoming True — but they remain available for the caller to act on via
retry_import (supply a different source), ignore_import, or remove_import.

#### `property failed_imports`
Return import_list entries that failed, each carrying a populated 'failure' field.

These are blocking: while any failed import remains, content_state stays
at VALID and imports_resolved is False.

#### `def find_by_uuid(self, uuid, _seen=None)`
Search the import tree for an imported document containing a matching UUID.

Performs a depth-first search across resolved imports, tracking visited
objects to avoid infinite loops on circular imports.

Args:
    uuid (str, required): The UUID to search for.
    _seen (set | None, optional): Object ids already visited; used internally.
        Defaults to None.

Returns:
    OSCAL | None: The matching imported document, or None if not found.

#### `classmethod def from_string(cls, content: 'str', *, href: 'str | None' = None)`
Explicit constructor for in-memory OSCAL string content.

Args:
    content (str, required): Serialized OSCAL content.
    href (str | None, optional): URI identifying the source. Keyword-only.
        Defaults to None.

Returns:
    OSCAL: A new instance (delegates to :meth:`loads`).

#### `def ignore_import(self, href: 'str') -> 'bool'`
Mark an import as intentionally ignored.

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

#### `property import_tree`
Recursive import tree built lazily on first access and cached.

Returns a root node dict representing this document, with an 'imports'
key holding the first-level imports (each following the same structure
recursively).  The root node fields mirror those of an import_list entry.
Use rebuild_import_tree() to force a fresh traversal.

#### `property imports_resolved`
bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``).

#### `def initial_validation(self, content: 'str') -> 'bool'`
Perform initial validation of content and advance the content state.

Detects the format, checks that the content is a recognized, well-formed
OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
summary metadata, then invokes full OSCAL schema validation. Updates
``self.content_state`` progressively as each stage passes.

Args:
    content (str, required): The raw OSCAL content to validate.

Returns:
    bool: True if initial validation is successful, False otherwise.

#### `property is_acquired`
bool: True once content has been acquired (``content_state >= ACQUIRED``).

#### `property is_cache_expired`
True when remote cached content has exceeded its TTL.

#### `property is_editable`
Can this content be modified?

#### `property is_fresh`
True when content is local or cached and within its TTL.

#### `property is_remote`
bool: True when the content originates from a remote source (not a local file).

#### `property is_stale`
True when remote cached content has exceeded its TTL.

#### `property is_valid`
bool: True when content passes OSCAL validation (``content_state >= VALID``).

#### `property is_well_formed`
bool: True when content is well-formed (``content_state >= WELL_FORMED``).

#### `property json`
Return the content as a JSON string.

#### `def json_query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def json_query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`json_query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using JSON key names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `classmethod def load(cls, source: 'str | os.PathLike | _ReadableSource', *, href: 'str | None' = None)`
Initialize an instance from a local file path or file-like object.

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

#### `classmethod def loads(cls, content: 'str | dict', *, href: 'str | None' = None)`
Initialize an instance from in-memory OSCAL content.

Args:
    content (str | dict, required): OSCAL content already in memory, as a
        serialized string or a dict.
    href (str | None, optional): URI identifying the original content
        source. Keyword-only. Defaults to None.

Returns:
    OSCAL: A new instance populated from the content.

#### `classmethod def new(cls, title: 'str', version: 'str' = '', published: 'str' = '')`
Create a new OSCAL document from a template.

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

#### `classmethod def open(cls, source: 'str | os.PathLike | dict | OscalRef | list | _ReadableSource', *, href: 'str | None' = None)`
Universal constructor — inspects the source type and delegates to
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

#### `property origin_state`
Computed from is_local, is_cached, and TTL. Changes over time for cached remote content.

#### `def query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using OSCAL XML element names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `def rebuild_import_tree(self) -> 'dict'`
Discard the cached import tree and rebuild it from the current import_list.

Returns:
    dict: The freshly built root node of the recursive import tree.

#### `def remove_import(self, href: 'str') -> 'bool'`
Remove an import entry from both import_list and the document content.

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

#### `def resolve_imports(self, base_path: 'str' = '') -> 'list'`
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

#### `def retry_import(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Retry a failed import identified by href, using a replacement source.

The failed import is matched by href (original or previously resolved),
then re-attempted using ``replacement_href`` (resolved relative to this
document's location).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def retry_imports(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Compatibility alias for :meth:`retry_import` (plural method name).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def set_metadata(self, content: 'dict' = {}) -> 'bool'`
Set simple metadata fields on the OSCAL content's ``metadata`` section.

Complex metadata collections (revisions, roles, parties, links, props, etc.)
are not yet supported and are skipped with a warning.

Args:
    content (dict, optional): Mapping of metadata field name to value to set.
        Defaults to an empty dict.

Returns:
    bool: True on success, or None when the content cannot be mutated.

#### `property unresolved_imports`
Return import_list entries that still warrant user attention.

Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
READY (resolved) and IGNORED (explicitly dismissed by the caller).

This is the signal a UI should use to decide whether to keep showing
import-resolution affordances.  It stays non-empty while there is still
something the user can act on — even when ``imports_resolved`` is already
True because the only remaining items are non-blocking duplicates.
Once every entry is READY or IGNORED, this list is empty and the
resolution UI can close.

#### `def validate(self, format: 'str' = '') -> 'bool'`
Validate OSCAL content against the metaschema index in sequenced phases.

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

#### `def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope='successful')`
Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

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

#### `property xml`
Return the content as an XML string, converting from dict if necessary.

#### `property yaml`
Return the content as a YAML string.

## Class: Profile
Class representing an OSCAL Profile object.
Inherits common OSCAL functionality and adds profile-specific methods
for managing imports and control selections.

### Available Members

#### `classmethod def acquire(cls, source: 'str | dict | OscalRef | list')`
Acquire OSCAL content from one or more URI/reference sources.

The sources are treated as an ordered fallback list; the first that
resolves successfully is used.

Args:
    source (str | dict | OscalRef | list, required): The reference(s) to
        acquire. May be a URI/path string, an ``OscalRef``, a reference dict
        containing at least ``"href"``, or a list mixing any of these.

Returns:
    OSCAL: A new instance populated from the first resolvable source.

#### `def append_child(self, path: 'str', child: 'dict') -> 'dict | None'`
Appends a child dict to the list at the given JSON path.

Path segments are '/' separated, relative to the model root.  The leaf
segment names the list key; it is created as an empty list if absent.

Args:
    path (str):  Slash-separated path to the target list relative to the
                 model root, e.g. "metadata/props" or "back-matter/resources".
    child (dict): Dict to append to the list.

Returns:
    dict | None: The appended child on success, None on failure.

#### `def append_resource(self, uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def control(self, control_id: str, with_history: bool = False) -> Optional[dict]`
Retrieve a control by its ID from the resolved catalog.

The profile must be resolved first; returns None with a warning otherwise.

Args:
    control_id (str, required): The ``id`` of the control to retrieve.
    with_history (bool, optional): Reserved for including tailoring history.
        Defaults to False.

Returns:
    Optional[dict]: The control dict, or None if unresolved or not found.

#### `def dump(self, filename: 'str' = '', format: 'str' = '', pretty_print: 'bool' = False) -> 'bool'`
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

#### `def dumps(self, format: 'str' = '', pretty_print: 'bool' = False) -> 'str'`
Serialize the current content to a string in the specified format.
Parameters:
- format (str): The target format for serialization ("xml", "json", or "yaml")
    Defaults to the original format of the content if not specified.
- pretty_print (bool): Whether to pretty-print the output. Defaults to False.

Returns:
- str: The serialized content as a string.

#### `property duplicate_imports`
Return import_list entries detected as duplicates of an earlier import.

Duplicates are non-blocking — they do NOT prevent imports_resolved from
becoming True — but they remain available for the caller to act on via
retry_import (supply a different source), ignore_import, or remove_import.

#### `property failed_imports`
Return import_list entries that failed, each carrying a populated 'failure' field.

These are blocking: while any failed import remains, content_state stays
at VALID and imports_resolved is False.

#### `def find_by_uuid(self, uuid, _seen=None)`
Search the import tree for an imported document containing a matching UUID.

Performs a depth-first search across resolved imports, tracking visited
objects to avoid infinite loops on circular imports.

Args:
    uuid (str, required): The UUID to search for.
    _seen (set | None, optional): Object ids already visited; used internally.
        Defaults to None.

Returns:
    OSCAL | None: The matching imported document, or None if not found.

#### `classmethod def from_string(cls, content: 'str', *, href: 'str | None' = None)`
Explicit constructor for in-memory OSCAL string content.

Args:
    content (str, required): Serialized OSCAL content.
    href (str | None, optional): URI identifying the source. Keyword-only.
        Defaults to None.

Returns:
    OSCAL: A new instance (delegates to :meth:`loads`).

#### `def ignore_import(self, href: 'str') -> 'bool'`
Mark an import as intentionally ignored.

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

#### `property import_tree`
Recursive import tree built lazily on first access and cached.

Returns a root node dict representing this document, with an 'imports'
key holding the first-level imports (each following the same structure
recursively).  The root node fields mirror those of an import_list entry.
Use rebuild_import_tree() to force a fresh traversal.

#### `property imports_resolved`
bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``).

#### `def initial_validation(self, content: 'str') -> 'bool'`
Perform initial validation of content and advance the content state.

Detects the format, checks that the content is a recognized, well-formed
OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
summary metadata, then invokes full OSCAL schema validation. Updates
``self.content_state`` progressively as each stage passes.

Args:
    content (str, required): The raw OSCAL content to validate.

Returns:
    bool: True if initial validation is successful, False otherwise.

#### `property is_acquired`
bool: True once content has been acquired (``content_state >= ACQUIRED``).

#### `property is_cache_expired`
True when remote cached content has exceeded its TTL.

#### `property is_editable`
Can this content be modified?

#### `property is_fresh`
True when content is local or cached and within its TTL.

#### `property is_remote`
bool: True when the content originates from a remote source (not a local file).

#### `property is_stale`
True when remote cached content has exceeded its TTL.

#### `property is_valid`
bool: True when content passes OSCAL validation (``content_state >= VALID``).

#### `property is_well_formed`
bool: True when content is well-formed (``content_state >= WELL_FORMED``).

#### `property json`
Return the content as a JSON string.

#### `def json_query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def json_query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`json_query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using JSON key names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `classmethod def load(cls, source: 'str | os.PathLike | _ReadableSource', *, href: 'str | None' = None)`
Initialize an instance from a local file path or file-like object.

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

#### `classmethod def loads(cls, content: 'str | dict', *, href: 'str | None' = None)`
Initialize an instance from in-memory OSCAL content.

Args:
    content (str | dict, required): OSCAL content already in memory, as a
        serialized string or a dict.
    href (str | None, optional): URI identifying the original content
        source. Keyword-only. Defaults to None.

Returns:
    OSCAL: A new instance populated from the content.

#### `classmethod def new(cls, title: 'str', version: 'str' = '', published: 'str' = '')`
Create a new OSCAL document from a template.

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

#### `classmethod def open(cls, source: 'str | os.PathLike | dict | OscalRef | list | _ReadableSource', *, href: 'str | None' = None)`
Universal constructor — inspects the source type and delegates to
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

#### `property origin_state`
Computed from is_local, is_cached, and TTL. Changes over time for cached remote content.

#### `def query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using OSCAL XML element names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `def rebuild_import_tree(self) -> 'dict'`
Discard the cached import tree and rebuild it from the current import_list.

Returns:
    dict: The freshly built root node of the recursive import tree.

#### `def remove_import(self, href: 'str') -> 'bool'`
Remove an import entry from both import_list and the document content.

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

#### `def resolve_imports(self, base_path: 'str' = '') -> 'list'`
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

#### `def retry_import(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Retry a failed import identified by href, using a replacement source.

The failed import is matched by href (original or previously resolved),
then re-attempted using ``replacement_href`` (resolved relative to this
document's location).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def retry_imports(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Compatibility alias for :meth:`retry_import` (plural method name).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def set_metadata(self, content: 'dict' = {}) -> 'bool'`
Set simple metadata fields on the OSCAL content's ``metadata`` section.

Complex metadata collections (revisions, roles, parties, links, props, etc.)
are not yet supported and are skipped with a warning.

Args:
    content (dict, optional): Mapping of metadata field name to value to set.
        Defaults to an empty dict.

Returns:
    bool: True on success, or None when the content cannot be mutated.

#### `property unresolved_imports`
Return import_list entries that still warrant user attention.

Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
READY (resolved) and IGNORED (explicitly dismissed by the caller).

This is the signal a UI should use to decide whether to keep showing
import-resolution affordances.  It stays non-empty while there is still
something the user can act on — even when ``imports_resolved`` is already
True because the only remaining items are non-blocking duplicates.
Once every entry is READY or IGNORED, this list is empty and the
resolution UI can close.

#### `def validate(self, format: 'str' = '') -> 'bool'`
Validate OSCAL content against the metaschema index in sequenced phases.

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

#### `def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope='successful')`
Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

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

#### `property xml`
Return the content as an XML string, converting from dict if necessary.

#### `property yaml`
Return the content as a YAML string.

## Class: ResolutionStatus
Lifecycle state of a Profile's control resolution.

Members:
    UNRESOLVED (str): "unresolved" — imports have not yet been resolved.
    RESOLVING (str): "resolving" — resolution is in progress.
    RESOLVED (str): "resolved" — the resolved catalog is available.
    BLOCKED (str): "blocked" — resolution could not complete (e.g. missing import).
    EXPIRED (str): "expired" — a previously resolved catalog is stale.

### Available Members

*No public members available.*

# Module: oscal.oscal_implementation

oscal_implementation — OSCAL implementation-layer model classes and helpers.

Provides the model classes for the OSCAL implementation models:
``ComponentDefinition`` (reusable control implementations for components) and
``SSP`` (System Security Plan). Both subclass ``OSCAL`` from ``oscal_content``.
Module-level helper functions build the nested SSP assemblies (components,
implemented requirements, by-component statements, responsible roles) and are
also exposed as ``SSP`` methods where appropriate.

Module constants:
    (none exported)

## Class: ComponentDefinition
OSCAL Component Definition (cDef) model.

Represents reusable component definitions that describe how components
satisfy controls. Subclasses ``OSCAL``.

### Available Members

#### `classmethod def acquire(cls, source: 'str | dict | OscalRef | list')`
Acquire OSCAL content from one or more URI/reference sources.

The sources are treated as an ordered fallback list; the first that
resolves successfully is used.

Args:
    source (str | dict | OscalRef | list, required): The reference(s) to
        acquire. May be a URI/path string, an ``OscalRef``, a reference dict
        containing at least ``"href"``, or a list mixing any of these.

Returns:
    OSCAL: A new instance populated from the first resolvable source.

#### `def append_child(self, path: 'str', child: 'dict') -> 'dict | None'`
Appends a child dict to the list at the given JSON path.

Path segments are '/' separated, relative to the model root.  The leaf
segment names the list key; it is created as an empty list if absent.

Args:
    path (str):  Slash-separated path to the target list relative to the
                 model root, e.g. "metadata/props" or "back-matter/resources".
    child (dict): Dict to append to the list.

Returns:
    dict | None: The appended child on success, None on failure.

#### `def append_resource(self, uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def dump(self, filename: 'str' = '', format: 'str' = '', pretty_print: 'bool' = False) -> 'bool'`
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

#### `def dumps(self, format: 'str' = '', pretty_print: 'bool' = False) -> 'str'`
Serialize the current content to a string in the specified format.
Parameters:
- format (str): The target format for serialization ("xml", "json", or "yaml")
    Defaults to the original format of the content if not specified.
- pretty_print (bool): Whether to pretty-print the output. Defaults to False.

Returns:
- str: The serialized content as a string.

#### `property duplicate_imports`
Return import_list entries detected as duplicates of an earlier import.

Duplicates are non-blocking — they do NOT prevent imports_resolved from
becoming True — but they remain available for the caller to act on via
retry_import (supply a different source), ignore_import, or remove_import.

#### `property failed_imports`
Return import_list entries that failed, each carrying a populated 'failure' field.

These are blocking: while any failed import remains, content_state stays
at VALID and imports_resolved is False.

#### `def find_by_uuid(self, uuid, _seen=None)`
Search the import tree for an imported document containing a matching UUID.

Performs a depth-first search across resolved imports, tracking visited
objects to avoid infinite loops on circular imports.

Args:
    uuid (str, required): The UUID to search for.
    _seen (set | None, optional): Object ids already visited; used internally.
        Defaults to None.

Returns:
    OSCAL | None: The matching imported document, or None if not found.

#### `classmethod def from_string(cls, content: 'str', *, href: 'str | None' = None)`
Explicit constructor for in-memory OSCAL string content.

Args:
    content (str, required): Serialized OSCAL content.
    href (str | None, optional): URI identifying the source. Keyword-only.
        Defaults to None.

Returns:
    OSCAL: A new instance (delegates to :meth:`loads`).

#### `def ignore_import(self, href: 'str') -> 'bool'`
Mark an import as intentionally ignored.

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

#### `property import_tree`
Recursive import tree built lazily on first access and cached.

Returns a root node dict representing this document, with an 'imports'
key holding the first-level imports (each following the same structure
recursively).  The root node fields mirror those of an import_list entry.
Use rebuild_import_tree() to force a fresh traversal.

#### `property imports_resolved`
bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``).

#### `def initial_validation(self, content: 'str') -> 'bool'`
Perform initial validation of content and advance the content state.

Detects the format, checks that the content is a recognized, well-formed
OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
summary metadata, then invokes full OSCAL schema validation. Updates
``self.content_state`` progressively as each stage passes.

Args:
    content (str, required): The raw OSCAL content to validate.

Returns:
    bool: True if initial validation is successful, False otherwise.

#### `property is_acquired`
bool: True once content has been acquired (``content_state >= ACQUIRED``).

#### `property is_cache_expired`
True when remote cached content has exceeded its TTL.

#### `property is_editable`
Can this content be modified?

#### `property is_fresh`
True when content is local or cached and within its TTL.

#### `property is_remote`
bool: True when the content originates from a remote source (not a local file).

#### `property is_stale`
True when remote cached content has exceeded its TTL.

#### `property is_valid`
bool: True when content passes OSCAL validation (``content_state >= VALID``).

#### `property is_well_formed`
bool: True when content is well-formed (``content_state >= WELL_FORMED``).

#### `property json`
Return the content as a JSON string.

#### `def json_query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def json_query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`json_query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using JSON key names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `classmethod def load(cls, source: 'str | os.PathLike | _ReadableSource', *, href: 'str | None' = None)`
Initialize an instance from a local file path or file-like object.

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

#### `classmethod def loads(cls, content: 'str | dict', *, href: 'str | None' = None)`
Initialize an instance from in-memory OSCAL content.

Args:
    content (str | dict, required): OSCAL content already in memory, as a
        serialized string or a dict.
    href (str | None, optional): URI identifying the original content
        source. Keyword-only. Defaults to None.

Returns:
    OSCAL: A new instance populated from the content.

#### `classmethod def new(cls, title: 'str', version: 'str' = '', published: 'str' = '')`
Create a new OSCAL document from a template.

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

#### `classmethod def open(cls, source: 'str | os.PathLike | dict | OscalRef | list | _ReadableSource', *, href: 'str | None' = None)`
Universal constructor — inspects the source type and delegates to
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

#### `property origin_state`
Computed from is_local, is_cached, and TTL. Changes over time for cached remote content.

#### `def query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using OSCAL XML element names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `def rebuild_import_tree(self) -> 'dict'`
Discard the cached import tree and rebuild it from the current import_list.

Returns:
    dict: The freshly built root node of the recursive import tree.

#### `def remove_import(self, href: 'str') -> 'bool'`
Remove an import entry from both import_list and the document content.

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

#### `def resolve_imports(self, base_path: 'str' = '') -> 'list'`
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

#### `def retry_import(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Retry a failed import identified by href, using a replacement source.

The failed import is matched by href (original or previously resolved),
then re-attempted using ``replacement_href`` (resolved relative to this
document's location).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def retry_imports(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Compatibility alias for :meth:`retry_import` (plural method name).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def set_metadata(self, content: 'dict' = {}) -> 'bool'`
Set simple metadata fields on the OSCAL content's ``metadata`` section.

Complex metadata collections (revisions, roles, parties, links, props, etc.)
are not yet supported and are skipped with a warning.

Args:
    content (dict, optional): Mapping of metadata field name to value to set.
        Defaults to an empty dict.

Returns:
    bool: True on success, or None when the content cannot be mutated.

#### `property unresolved_imports`
Return import_list entries that still warrant user attention.

Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
READY (resolved) and IGNORED (explicitly dismissed by the caller).

This is the signal a UI should use to decide whether to keep showing
import-resolution affordances.  It stays non-empty while there is still
something the user can act on — even when ``imports_resolved`` is already
True because the only remaining items are non-blocking duplicates.
Once every entry is READY or IGNORED, this list is empty and the
resolution UI can close.

#### `def validate(self, format: 'str' = '') -> 'bool'`
Validate OSCAL content against the metaschema index in sequenced phases.

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

#### `def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope='successful')`
Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

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

#### `property xml`
Return the content as an XML string, converting from dict if necessary.

#### `property yaml`
Return the content as a YAML string.

## Class: SSP
OSCAL System Security Plan (SSP) model.

Subclasses ``OSCAL`` and adds SSP-specific methods for managing system
components, implemented requirements, and by-component statements.

### Available Members

#### `classmethod def acquire(cls, source: 'str | dict | OscalRef | list')`
Acquire OSCAL content from one or more URI/reference sources.

The sources are treated as an ordered fallback list; the first that
resolves successfully is used.

Args:
    source (str | dict | OscalRef | list, required): The reference(s) to
        acquire. May be a URI/path string, an ``OscalRef``, a reference dict
        containing at least ``"href"``, or a list mixing any of these.

Returns:
    OSCAL: A new instance populated from the first resolvable source.

#### `def append_child(self, path: 'str', child: 'dict') -> 'dict | None'`
Appends a child dict to the list at the given JSON path.

Path segments are '/' separated, relative to the model root.  The leaf
segment names the list key; it is created as an empty list if absent.

Args:
    path (str):  Slash-separated path to the target list relative to the
                 model root, e.g. "metadata/props" or "back-matter/resources".
    child (dict): Dict to append to the list.

Returns:
    dict | None: The appended child on success, None on failure.

#### `def append_component(self, component_type: 'str', component_title: 'str', component_description: 'str', op_status: 'str' = 'operational', component_uuid: 'str' = '', props: 'list' = [], links: 'list' = [], remarks: 'str' = '') -> 'Optional[dict]'`
Add a component to the SSP's ``system-implementation`` section.

Args:
    component_type (str, required): The component ``type`` (e.g. "software").
    component_title (str, required): The component title.
    component_description (str, required): The component description.
    op_status (str, optional): Operational ``status.state`` value.
        Defaults to "operational".
    component_uuid (str, optional): UUID for the component. A new UUID is
        generated when empty.
    props (list, optional): Property dicts to add.
    links (list, optional): Link dicts to add.
    remarks (str, optional): Remarks prose (markdown).

Returns:
    Optional[dict]: The newly created component dict, or None on failure.

#### `def append_impl_requirement(self, control_id: 'str', props: 'list' = [], links: 'list' = [], remarks: 'str' = '') -> 'Optional[dict]'`
Add an implemented-requirement to the SSP's ``control-implementation`` section.

Args:
    control_id (str, required): The ID of the control being implemented.
    props (list, optional): Property dicts to add.
    links (list, optional): Link dicts to add.
    remarks (str, optional): Remarks prose (markdown).

Returns:
    Optional[dict]: The newly created implemented-requirement dict (with a
        generated UUID), or None on failure.

#### `def append_resource(self, uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def dump(self, filename: 'str' = '', format: 'str' = '', pretty_print: 'bool' = False) -> 'bool'`
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

#### `def dumps(self, format: 'str' = '', pretty_print: 'bool' = False) -> 'str'`
Serialize the current content to a string in the specified format.
Parameters:
- format (str): The target format for serialization ("xml", "json", or "yaml")
    Defaults to the original format of the content if not specified.
- pretty_print (bool): Whether to pretty-print the output. Defaults to False.

Returns:
- str: The serialized content as a string.

#### `property duplicate_imports`
Return import_list entries detected as duplicates of an earlier import.

Duplicates are non-blocking — they do NOT prevent imports_resolved from
becoming True — but they remain available for the caller to act on via
retry_import (supply a different source), ignore_import, or remove_import.

#### `property failed_imports`
Return import_list entries that failed, each carrying a populated 'failure' field.

These are blocking: while any failed import remains, content_state stays
at VALID and imports_resolved is False.

#### `def find_by_uuid(self, uuid, _seen=None)`
Search the import tree for an imported document containing a matching UUID.

Performs a depth-first search across resolved imports, tracking visited
objects to avoid infinite loops on circular imports.

Args:
    uuid (str, required): The UUID to search for.
    _seen (set | None, optional): Object ids already visited; used internally.
        Defaults to None.

Returns:
    OSCAL | None: The matching imported document, or None if not found.

#### `classmethod def from_string(cls, content: 'str', *, href: 'str | None' = None)`
Explicit constructor for in-memory OSCAL string content.

Args:
    content (str, required): Serialized OSCAL content.
    href (str | None, optional): URI identifying the source. Keyword-only.
        Defaults to None.

Returns:
    OSCAL: A new instance (delegates to :meth:`loads`).

#### `def ignore_import(self, href: 'str') -> 'bool'`
Mark an import as intentionally ignored.

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

#### `property import_tree`
Recursive import tree built lazily on first access and cached.

Returns a root node dict representing this document, with an 'imports'
key holding the first-level imports (each following the same structure
recursively).  The root node fields mirror those of an import_list entry.
Use rebuild_import_tree() to force a fresh traversal.

#### `property imports_resolved`
bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``).

#### `def initial_validation(self, content: 'str') -> 'bool'`
Perform initial validation of content and advance the content state.

Detects the format, checks that the content is a recognized, well-formed
OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
summary metadata, then invokes full OSCAL schema validation. Updates
``self.content_state`` progressively as each stage passes.

Args:
    content (str, required): The raw OSCAL content to validate.

Returns:
    bool: True if initial validation is successful, False otherwise.

#### `property is_acquired`
bool: True once content has been acquired (``content_state >= ACQUIRED``).

#### `property is_cache_expired`
True when remote cached content has exceeded its TTL.

#### `property is_editable`
Can this content be modified?

#### `property is_fresh`
True when content is local or cached and within its TTL.

#### `property is_remote`
bool: True when the content originates from a remote source (not a local file).

#### `property is_stale`
True when remote cached content has exceeded its TTL.

#### `property is_valid`
bool: True when content passes OSCAL validation (``content_state >= VALID``).

#### `property is_well_formed`
bool: True when content is well-formed (``content_state >= WELL_FORMED``).

#### `property json`
Return the content as a JSON string.

#### `def json_query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def json_query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`json_query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using JSON key names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `classmethod def load(cls, source: 'str | os.PathLike | _ReadableSource', *, href: 'str | None' = None)`
Initialize an instance from a local file path or file-like object.

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

#### `classmethod def loads(cls, content: 'str | dict', *, href: 'str | None' = None)`
Initialize an instance from in-memory OSCAL content.

Args:
    content (str | dict, required): OSCAL content already in memory, as a
        serialized string or a dict.
    href (str | None, optional): URI identifying the original content
        source. Keyword-only. Defaults to None.

Returns:
    OSCAL: A new instance populated from the content.

#### `classmethod def new(cls, title: 'str', version: 'str' = '', published: 'str' = '')`
Create a new OSCAL document from a template.

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

#### `classmethod def open(cls, source: 'str | os.PathLike | dict | OscalRef | list | _ReadableSource', *, href: 'str | None' = None)`
Universal constructor — inspects the source type and delegates to
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

#### `property origin_state`
Computed from is_local, is_cached, and TTL. Changes over time for cached remote content.

#### `def query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using OSCAL XML element names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `def rebuild_import_tree(self) -> 'dict'`
Discard the cached import tree and rebuild it from the current import_list.

Returns:
    dict: The freshly built root node of the recursive import tree.

#### `def remove_import(self, href: 'str') -> 'bool'`
Remove an import entry from both import_list and the document content.

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

#### `def resolve_imports(self, base_path: 'str' = '') -> 'list'`
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

#### `def retry_import(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Retry a failed import identified by href, using a replacement source.

The failed import is matched by href (original or previously resolved),
then re-attempted using ``replacement_href`` (resolved relative to this
document's location).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def retry_imports(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Compatibility alias for :meth:`retry_import` (plural method name).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def set_metadata(self, content: 'dict' = {}) -> 'bool'`
Set simple metadata fields on the OSCAL content's ``metadata`` section.

Complex metadata collections (revisions, roles, parties, links, props, etc.)
are not yet supported and are skipped with a warning.

Args:
    content (dict, optional): Mapping of metadata field name to value to set.
        Defaults to an empty dict.

Returns:
    bool: True on success, or None when the content cannot be mutated.

#### `property unresolved_imports`
Return import_list entries that still warrant user attention.

Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
READY (resolved) and IGNORED (explicitly dismissed by the caller).

This is the signal a UI should use to decide whether to keep showing
import-resolution affordances.  It stays non-empty while there is still
something the user can act on — even when ``imports_resolved`` is already
True because the only remaining items are non-blocking duplicates.
Once every entry is READY or IGNORED, this list is empty and the
resolution UI can close.

#### `def validate(self, format: 'str' = '') -> 'bool'`
Validate OSCAL content against the metaschema index in sequenced phases.

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

#### `def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope='successful')`
Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

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

#### `property xml`
Return the content as an XML string, converting from dict if necessary.

#### `property yaml`
Return the content as a YAML string.

## Module Functions

#### `def append_by_component(impl_req_obj: 'dict', component_uuid: 'str', description: 'str', by_component_uuid: 'str' = '', implementation_status: 'str' = 'implemented', remarks: 'str' = '') -> 'Optional[dict]'`
Add a by-component statement to an implemented-requirement dict.

Args:
    impl_req_obj (dict, required): The implemented-requirement dict to modify.
    component_uuid (str, required): UUID of the referenced system component.
    description (str, required): Description of how the component satisfies
        the requirement.
    by_component_uuid (str, optional): UUID for the by-component entry. A new
        UUID is generated when empty.
    implementation_status (str, optional): ``implementation-status.state`` value.
        Defaults to "implemented".
    remarks (str, optional): Remarks prose (markdown).

Returns:
    Optional[dict]: The newly created by-component dict, or None on failure.

#### `def append_component(ssp_obj: 'OSCAL', component_type: 'str', component_title: 'str', component_description: 'str', op_status: 'str' = 'operational', component_uuid: 'str' = '', props: 'list' = [], links: 'list' = [], remarks: 'str' = '') -> 'Optional[dict]'`
Add a component to an SSP's ``system-implementation`` section.

Args:
    ssp_obj (OSCAL, required): The SSP instance to modify.
    component_type (str, required): The component ``type`` (e.g. "software").
    component_title (str, required): The component title.
    component_description (str, required): The component description.
    op_status (str, optional): Operational ``status.state`` value.
        Defaults to "operational".
    component_uuid (str, optional): UUID for the component. A new UUID is
        generated when empty.
    props (list, optional): Property dicts to add.
    links (list, optional): Link dicts to add.
    remarks (str, optional): Remarks prose (markdown).

Returns:
    Optional[dict]: The newly created component dict, or None on failure.

#### `def append_impl_requirement(ssp_obj: 'OSCAL', control_id: 'str', props: 'list' = [], links: 'list' = [], remarks: 'str' = '') -> 'Optional[dict]'`
Add an implemented-requirement to an SSP's ``control-implementation`` section.

Args:
    ssp_obj (OSCAL, required): The SSP instance to modify.
    control_id (str, required): The ID of the control being implemented.
    props (list, optional): Property dicts to add.
    links (list, optional): Link dicts to add.
    remarks (str, optional): Remarks prose (markdown).

Returns:
    Optional[dict]: The newly created implemented-requirement dict (with a
        generated UUID), or None on failure.

#### `def append_responsible_role(oscal_obj: 'dict', role_id: 'str', party_uuids: 'list' = [], remarks: 'str' = '') -> 'dict'`
Add a responsible-role entry to an OSCAL object dict.

Args:
    oscal_obj (dict, required): The parent OSCAL dict to add the role to.
    role_id (str, required): The ID of the role being assigned.
    party_uuids (list, optional): UUIDs of the parties fulfilling the role.
    remarks (str, optional): Remarks prose (markdown).

Returns:
    dict: The newly created responsible-role dict.

# Module: oscal.oscal_assessment

oscal_assessment — OSCAL assessment-layer model classes.

Provides the model classes for the OSCAL assessment models: ``AssessmentPlan``
(Security Assessment Plan / SAP), ``AssessmentResults`` (Security Assessment
Results / SAR), and ``POAM`` (Plan of Action and Milestones). Each subclasses
``OSCAL`` from ``oscal_content`` and inherits its common load/save/validate and
query behavior.

Module constants:
    (none exported)

## Class: AssessmentPlan
OSCAL Assessment Plan (AP / SAP) model.

Represents an assessment plan that defines the scope, assets, activities,
and tasks for a security assessment. Subclasses ``OSCAL``.

### Available Members

#### `classmethod def acquire(cls, source: 'str | dict | OscalRef | list')`
Acquire OSCAL content from one or more URI/reference sources.

The sources are treated as an ordered fallback list; the first that
resolves successfully is used.

Args:
    source (str | dict | OscalRef | list, required): The reference(s) to
        acquire. May be a URI/path string, an ``OscalRef``, a reference dict
        containing at least ``"href"``, or a list mixing any of these.

Returns:
    OSCAL: A new instance populated from the first resolvable source.

#### `def append_child(self, path: 'str', child: 'dict') -> 'dict | None'`
Appends a child dict to the list at the given JSON path.

Path segments are '/' separated, relative to the model root.  The leaf
segment names the list key; it is created as an empty list if absent.

Args:
    path (str):  Slash-separated path to the target list relative to the
                 model root, e.g. "metadata/props" or "back-matter/resources".
    child (dict): Dict to append to the list.

Returns:
    dict | None: The appended child on success, None on failure.

#### `def append_resource(self, uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def dump(self, filename: 'str' = '', format: 'str' = '', pretty_print: 'bool' = False) -> 'bool'`
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

#### `def dumps(self, format: 'str' = '', pretty_print: 'bool' = False) -> 'str'`
Serialize the current content to a string in the specified format.
Parameters:
- format (str): The target format for serialization ("xml", "json", or "yaml")
    Defaults to the original format of the content if not specified.
- pretty_print (bool): Whether to pretty-print the output. Defaults to False.

Returns:
- str: The serialized content as a string.

#### `property duplicate_imports`
Return import_list entries detected as duplicates of an earlier import.

Duplicates are non-blocking — they do NOT prevent imports_resolved from
becoming True — but they remain available for the caller to act on via
retry_import (supply a different source), ignore_import, or remove_import.

#### `property failed_imports`
Return import_list entries that failed, each carrying a populated 'failure' field.

These are blocking: while any failed import remains, content_state stays
at VALID and imports_resolved is False.

#### `def find_by_uuid(self, uuid, _seen=None)`
Search the import tree for an imported document containing a matching UUID.

Performs a depth-first search across resolved imports, tracking visited
objects to avoid infinite loops on circular imports.

Args:
    uuid (str, required): The UUID to search for.
    _seen (set | None, optional): Object ids already visited; used internally.
        Defaults to None.

Returns:
    OSCAL | None: The matching imported document, or None if not found.

#### `classmethod def from_string(cls, content: 'str', *, href: 'str | None' = None)`
Explicit constructor for in-memory OSCAL string content.

Args:
    content (str, required): Serialized OSCAL content.
    href (str | None, optional): URI identifying the source. Keyword-only.
        Defaults to None.

Returns:
    OSCAL: A new instance (delegates to :meth:`loads`).

#### `def ignore_import(self, href: 'str') -> 'bool'`
Mark an import as intentionally ignored.

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

#### `property import_tree`
Recursive import tree built lazily on first access and cached.

Returns a root node dict representing this document, with an 'imports'
key holding the first-level imports (each following the same structure
recursively).  The root node fields mirror those of an import_list entry.
Use rebuild_import_tree() to force a fresh traversal.

#### `property imports_resolved`
bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``).

#### `def initial_validation(self, content: 'str') -> 'bool'`
Perform initial validation of content and advance the content state.

Detects the format, checks that the content is a recognized, well-formed
OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
summary metadata, then invokes full OSCAL schema validation. Updates
``self.content_state`` progressively as each stage passes.

Args:
    content (str, required): The raw OSCAL content to validate.

Returns:
    bool: True if initial validation is successful, False otherwise.

#### `property is_acquired`
bool: True once content has been acquired (``content_state >= ACQUIRED``).

#### `property is_cache_expired`
True when remote cached content has exceeded its TTL.

#### `property is_editable`
Can this content be modified?

#### `property is_fresh`
True when content is local or cached and within its TTL.

#### `property is_remote`
bool: True when the content originates from a remote source (not a local file).

#### `property is_stale`
True when remote cached content has exceeded its TTL.

#### `property is_valid`
bool: True when content passes OSCAL validation (``content_state >= VALID``).

#### `property is_well_formed`
bool: True when content is well-formed (``content_state >= WELL_FORMED``).

#### `property json`
Return the content as a JSON string.

#### `def json_query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def json_query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`json_query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using JSON key names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `classmethod def load(cls, source: 'str | os.PathLike | _ReadableSource', *, href: 'str | None' = None)`
Initialize an instance from a local file path or file-like object.

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

#### `classmethod def loads(cls, content: 'str | dict', *, href: 'str | None' = None)`
Initialize an instance from in-memory OSCAL content.

Args:
    content (str | dict, required): OSCAL content already in memory, as a
        serialized string or a dict.
    href (str | None, optional): URI identifying the original content
        source. Keyword-only. Defaults to None.

Returns:
    OSCAL: A new instance populated from the content.

#### `classmethod def new(cls, title: 'str', version: 'str' = '', published: 'str' = '')`
Create a new OSCAL document from a template.

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

#### `classmethod def open(cls, source: 'str | os.PathLike | dict | OscalRef | list | _ReadableSource', *, href: 'str | None' = None)`
Universal constructor — inspects the source type and delegates to
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

#### `property origin_state`
Computed from is_local, is_cached, and TTL. Changes over time for cached remote content.

#### `def query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using OSCAL XML element names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `def rebuild_import_tree(self) -> 'dict'`
Discard the cached import tree and rebuild it from the current import_list.

Returns:
    dict: The freshly built root node of the recursive import tree.

#### `def remove_import(self, href: 'str') -> 'bool'`
Remove an import entry from both import_list and the document content.

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

#### `def resolve_imports(self, base_path: 'str' = '') -> 'list'`
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

#### `def retry_import(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Retry a failed import identified by href, using a replacement source.

The failed import is matched by href (original or previously resolved),
then re-attempted using ``replacement_href`` (resolved relative to this
document's location).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def retry_imports(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Compatibility alias for :meth:`retry_import` (plural method name).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def set_metadata(self, content: 'dict' = {}) -> 'bool'`
Set simple metadata fields on the OSCAL content's ``metadata`` section.

Complex metadata collections (revisions, roles, parties, links, props, etc.)
are not yet supported and are skipped with a warning.

Args:
    content (dict, optional): Mapping of metadata field name to value to set.
        Defaults to an empty dict.

Returns:
    bool: True on success, or None when the content cannot be mutated.

#### `property unresolved_imports`
Return import_list entries that still warrant user attention.

Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
READY (resolved) and IGNORED (explicitly dismissed by the caller).

This is the signal a UI should use to decide whether to keep showing
import-resolution affordances.  It stays non-empty while there is still
something the user can act on — even when ``imports_resolved`` is already
True because the only remaining items are non-blocking duplicates.
Once every entry is READY or IGNORED, this list is empty and the
resolution UI can close.

#### `def validate(self, format: 'str' = '') -> 'bool'`
Validate OSCAL content against the metaschema index in sequenced phases.

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

#### `def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope='successful')`
Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

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

#### `property xml`
Return the content as an XML string, converting from dict if necessary.

#### `property yaml`
Return the content as a YAML string.

## Class: AssessmentResults
OSCAL Assessment Results (AR / SAR) model.

Represents the findings, observations, and risks produced by executing an
assessment plan. Subclasses ``OSCAL``.

### Available Members

#### `classmethod def acquire(cls, source: 'str | dict | OscalRef | list')`
Acquire OSCAL content from one or more URI/reference sources.

The sources are treated as an ordered fallback list; the first that
resolves successfully is used.

Args:
    source (str | dict | OscalRef | list, required): The reference(s) to
        acquire. May be a URI/path string, an ``OscalRef``, a reference dict
        containing at least ``"href"``, or a list mixing any of these.

Returns:
    OSCAL: A new instance populated from the first resolvable source.

#### `def append_child(self, path: 'str', child: 'dict') -> 'dict | None'`
Appends a child dict to the list at the given JSON path.

Path segments are '/' separated, relative to the model root.  The leaf
segment names the list key; it is created as an empty list if absent.

Args:
    path (str):  Slash-separated path to the target list relative to the
                 model root, e.g. "metadata/props" or "back-matter/resources".
    child (dict): Dict to append to the list.

Returns:
    dict | None: The appended child on success, None on failure.

#### `def append_resource(self, uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def dump(self, filename: 'str' = '', format: 'str' = '', pretty_print: 'bool' = False) -> 'bool'`
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

#### `def dumps(self, format: 'str' = '', pretty_print: 'bool' = False) -> 'str'`
Serialize the current content to a string in the specified format.
Parameters:
- format (str): The target format for serialization ("xml", "json", or "yaml")
    Defaults to the original format of the content if not specified.
- pretty_print (bool): Whether to pretty-print the output. Defaults to False.

Returns:
- str: The serialized content as a string.

#### `property duplicate_imports`
Return import_list entries detected as duplicates of an earlier import.

Duplicates are non-blocking — they do NOT prevent imports_resolved from
becoming True — but they remain available for the caller to act on via
retry_import (supply a different source), ignore_import, or remove_import.

#### `property failed_imports`
Return import_list entries that failed, each carrying a populated 'failure' field.

These are blocking: while any failed import remains, content_state stays
at VALID and imports_resolved is False.

#### `def find_by_uuid(self, uuid, _seen=None)`
Search the import tree for an imported document containing a matching UUID.

Performs a depth-first search across resolved imports, tracking visited
objects to avoid infinite loops on circular imports.

Args:
    uuid (str, required): The UUID to search for.
    _seen (set | None, optional): Object ids already visited; used internally.
        Defaults to None.

Returns:
    OSCAL | None: The matching imported document, or None if not found.

#### `classmethod def from_string(cls, content: 'str', *, href: 'str | None' = None)`
Explicit constructor for in-memory OSCAL string content.

Args:
    content (str, required): Serialized OSCAL content.
    href (str | None, optional): URI identifying the source. Keyword-only.
        Defaults to None.

Returns:
    OSCAL: A new instance (delegates to :meth:`loads`).

#### `def ignore_import(self, href: 'str') -> 'bool'`
Mark an import as intentionally ignored.

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

#### `property import_tree`
Recursive import tree built lazily on first access and cached.

Returns a root node dict representing this document, with an 'imports'
key holding the first-level imports (each following the same structure
recursively).  The root node fields mirror those of an import_list entry.
Use rebuild_import_tree() to force a fresh traversal.

#### `property imports_resolved`
bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``).

#### `def initial_validation(self, content: 'str') -> 'bool'`
Perform initial validation of content and advance the content state.

Detects the format, checks that the content is a recognized, well-formed
OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
summary metadata, then invokes full OSCAL schema validation. Updates
``self.content_state`` progressively as each stage passes.

Args:
    content (str, required): The raw OSCAL content to validate.

Returns:
    bool: True if initial validation is successful, False otherwise.

#### `property is_acquired`
bool: True once content has been acquired (``content_state >= ACQUIRED``).

#### `property is_cache_expired`
True when remote cached content has exceeded its TTL.

#### `property is_editable`
Can this content be modified?

#### `property is_fresh`
True when content is local or cached and within its TTL.

#### `property is_remote`
bool: True when the content originates from a remote source (not a local file).

#### `property is_stale`
True when remote cached content has exceeded its TTL.

#### `property is_valid`
bool: True when content passes OSCAL validation (``content_state >= VALID``).

#### `property is_well_formed`
bool: True when content is well-formed (``content_state >= WELL_FORMED``).

#### `property json`
Return the content as a JSON string.

#### `def json_query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def json_query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`json_query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using JSON key names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `classmethod def load(cls, source: 'str | os.PathLike | _ReadableSource', *, href: 'str | None' = None)`
Initialize an instance from a local file path or file-like object.

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

#### `classmethod def loads(cls, content: 'str | dict', *, href: 'str | None' = None)`
Initialize an instance from in-memory OSCAL content.

Args:
    content (str | dict, required): OSCAL content already in memory, as a
        serialized string or a dict.
    href (str | None, optional): URI identifying the original content
        source. Keyword-only. Defaults to None.

Returns:
    OSCAL: A new instance populated from the content.

#### `classmethod def new(cls, title: 'str', version: 'str' = '', published: 'str' = '')`
Create a new OSCAL document from a template.

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

#### `classmethod def open(cls, source: 'str | os.PathLike | dict | OscalRef | list | _ReadableSource', *, href: 'str | None' = None)`
Universal constructor — inspects the source type and delegates to
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

#### `property origin_state`
Computed from is_local, is_cached, and TTL. Changes over time for cached remote content.

#### `def query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using OSCAL XML element names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `def rebuild_import_tree(self) -> 'dict'`
Discard the cached import tree and rebuild it from the current import_list.

Returns:
    dict: The freshly built root node of the recursive import tree.

#### `def remove_import(self, href: 'str') -> 'bool'`
Remove an import entry from both import_list and the document content.

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

#### `def resolve_imports(self, base_path: 'str' = '') -> 'list'`
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

#### `def retry_import(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Retry a failed import identified by href, using a replacement source.

The failed import is matched by href (original or previously resolved),
then re-attempted using ``replacement_href`` (resolved relative to this
document's location).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def retry_imports(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Compatibility alias for :meth:`retry_import` (plural method name).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def set_metadata(self, content: 'dict' = {}) -> 'bool'`
Set simple metadata fields on the OSCAL content's ``metadata`` section.

Complex metadata collections (revisions, roles, parties, links, props, etc.)
are not yet supported and are skipped with a warning.

Args:
    content (dict, optional): Mapping of metadata field name to value to set.
        Defaults to an empty dict.

Returns:
    bool: True on success, or None when the content cannot be mutated.

#### `property unresolved_imports`
Return import_list entries that still warrant user attention.

Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
READY (resolved) and IGNORED (explicitly dismissed by the caller).

This is the signal a UI should use to decide whether to keep showing
import-resolution affordances.  It stays non-empty while there is still
something the user can act on — even when ``imports_resolved`` is already
True because the only remaining items are non-blocking duplicates.
Once every entry is READY or IGNORED, this list is empty and the
resolution UI can close.

#### `def validate(self, format: 'str' = '') -> 'bool'`
Validate OSCAL content against the metaschema index in sequenced phases.

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

#### `def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope='successful')`
Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

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

#### `property xml`
Return the content as an XML string, converting from dict if necessary.

#### `property yaml`
Return the content as a YAML string.

## Class: POAM
OSCAL Plan of Action and Milestones (POA&M) model.

Represents tracked security findings and their planned remediation
milestones. Subclasses ``OSCAL``.

### Available Members

#### `classmethod def acquire(cls, source: 'str | dict | OscalRef | list')`
Acquire OSCAL content from one or more URI/reference sources.

The sources are treated as an ordered fallback list; the first that
resolves successfully is used.

Args:
    source (str | dict | OscalRef | list, required): The reference(s) to
        acquire. May be a URI/path string, an ``OscalRef``, a reference dict
        containing at least ``"href"``, or a list mixing any of these.

Returns:
    OSCAL: A new instance populated from the first resolvable source.

#### `def append_child(self, path: 'str', child: 'dict') -> 'dict | None'`
Appends a child dict to the list at the given JSON path.

Path segments are '/' separated, relative to the model root.  The leaf
segment names the list key; it is created as an empty list if absent.

Args:
    path (str):  Slash-separated path to the target list relative to the
                 model root, e.g. "metadata/props" or "back-matter/resources".
    child (dict): Dict to append to the list.

Returns:
    dict | None: The appended child on success, None on failure.

#### `def append_resource(self, uuid: 'str' = '', title: 'str' = '', description: 'str' = '', props: 'list' = [], rlinks: 'list' = [], base64: 'str' = '', remarks: 'str' = '') -> 'dict | None'`
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

#### `def dump(self, filename: 'str' = '', format: 'str' = '', pretty_print: 'bool' = False) -> 'bool'`
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

#### `def dumps(self, format: 'str' = '', pretty_print: 'bool' = False) -> 'str'`
Serialize the current content to a string in the specified format.
Parameters:
- format (str): The target format for serialization ("xml", "json", or "yaml")
    Defaults to the original format of the content if not specified.
- pretty_print (bool): Whether to pretty-print the output. Defaults to False.

Returns:
- str: The serialized content as a string.

#### `property duplicate_imports`
Return import_list entries detected as duplicates of an earlier import.

Duplicates are non-blocking — they do NOT prevent imports_resolved from
becoming True — but they remain available for the caller to act on via
retry_import (supply a different source), ignore_import, or remove_import.

#### `property failed_imports`
Return import_list entries that failed, each carrying a populated 'failure' field.

These are blocking: while any failed import remains, content_state stays
at VALID and imports_resolved is False.

#### `def find_by_uuid(self, uuid, _seen=None)`
Search the import tree for an imported document containing a matching UUID.

Performs a depth-first search across resolved imports, tracking visited
objects to avoid infinite loops on circular imports.

Args:
    uuid (str, required): The UUID to search for.
    _seen (set | None, optional): Object ids already visited; used internally.
        Defaults to None.

Returns:
    OSCAL | None: The matching imported document, or None if not found.

#### `classmethod def from_string(cls, content: 'str', *, href: 'str | None' = None)`
Explicit constructor for in-memory OSCAL string content.

Args:
    content (str, required): Serialized OSCAL content.
    href (str | None, optional): URI identifying the source. Keyword-only.
        Defaults to None.

Returns:
    OSCAL: A new instance (delegates to :meth:`loads`).

#### `def ignore_import(self, href: 'str') -> 'bool'`
Mark an import as intentionally ignored.

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

#### `property import_tree`
Recursive import tree built lazily on first access and cached.

Returns a root node dict representing this document, with an 'imports'
key holding the first-level imports (each following the same structure
recursively).  The root node fields mirror those of an import_list entry.
Use rebuild_import_tree() to force a fresh traversal.

#### `property imports_resolved`
bool: True when all imports resolved (``content_state >= IMPORTS_RESOLVED``).

#### `def initial_validation(self, content: 'str') -> 'bool'`
Perform initial validation of content and advance the content state.

Detects the format, checks that the content is a recognized, well-formed
OSCAL format (XML, JSON, or YAML), identifies the model/version and extracts
summary metadata, then invokes full OSCAL schema validation. Updates
``self.content_state`` progressively as each stage passes.

Args:
    content (str, required): The raw OSCAL content to validate.

Returns:
    bool: True if initial validation is successful, False otherwise.

#### `property is_acquired`
bool: True once content has been acquired (``content_state >= ACQUIRED``).

#### `property is_cache_expired`
True when remote cached content has exceeded its TTL.

#### `property is_editable`
Can this content be modified?

#### `property is_fresh`
True when content is local or cached and within its TTL.

#### `property is_remote`
bool: True when the content originates from a remote source (not a local file).

#### `property is_stale`
True when remote cached content has exceeded its TTL.

#### `property is_valid`
bool: True when content passes OSCAL validation (``content_state >= VALID``).

#### `property is_well_formed`
bool: True when content is well-formed (``content_state >= WELL_FORMED``).

#### `property json`
Return the content as a JSON string.

#### `def json_query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def json_query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`json_query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using JSON key names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `classmethod def load(cls, source: 'str | os.PathLike | _ReadableSource', *, href: 'str | None' = None)`
Initialize an instance from a local file path or file-like object.

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

#### `classmethod def loads(cls, content: 'str | dict', *, href: 'str | None' = None)`
Initialize an instance from in-memory OSCAL content.

Args:
    content (str | dict, required): OSCAL content already in memory, as a
        serialized string or a dict.
    href (str | None, optional): URI identifying the original content
        source. Keyword-only. Defaults to None.

Returns:
    OSCAL: A new instance populated from the content.

#### `classmethod def new(cls, title: 'str', version: 'str' = '', published: 'str' = '')`
Create a new OSCAL document from a template.

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

#### `classmethod def open(cls, source: 'str | os.PathLike | dict | OscalRef | list | _ReadableSource', *, href: 'str | None' = None)`
Universal constructor — inspects the source type and delegates to
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

#### `property origin_state`
Computed from is_local, is_cached, and TTL. Changes over time for cached remote content.

#### `def query(self, path: 'str', context: 'dict | None' = None) -> 'list'`
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

#### `def query_one(self, path: 'str', context: 'dict | None' = None, default=None)`
Return the first result of :meth:`query`, or ``default`` when nothing matches.

Args:
    path (str, required): Path expression using OSCAL XML element names.
    context (dict | None, optional): Sub-dict to query within. Defaults to the
        full document dict.
    default (Any, optional): Value to return when there is no match.
        Defaults to None.

Returns:
    Any: The first matching JSON value, or ``default``.

#### `def rebuild_import_tree(self) -> 'dict'`
Discard the cached import tree and rebuild it from the current import_list.

Returns:
    dict: The freshly built root node of the recursive import tree.

#### `def remove_import(self, href: 'str') -> 'bool'`
Remove an import entry from both import_list and the document content.

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

#### `def resolve_imports(self, base_path: 'str' = '') -> 'list'`
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

#### `def retry_import(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Retry a failed import identified by href, using a replacement source.

The failed import is matched by href (original or previously resolved),
then re-attempted using ``replacement_href`` (resolved relative to this
document's location).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def retry_imports(self, failed_href: 'str', replacement_href: 'str') -> 'bool'`
Compatibility alias for :meth:`retry_import` (plural method name).

Args:
    failed_href (str, required): The href of the failed import to retry.
    replacement_href (str, required): The replacement href to attempt.

Returns:
    bool: True if the import was successfully resolved on retry, False otherwise.

#### `def set_metadata(self, content: 'dict' = {}) -> 'bool'`
Set simple metadata fields on the OSCAL content's ``metadata`` section.

Complex metadata collections (revisions, roles, parties, links, props, etc.)
are not yet supported and are skipped with a warning.

Args:
    content (dict, optional): Mapping of metadata field name to value to set.
        Defaults to an empty dict.

Returns:
    bool: True on success, or None when the content cannot be mutated.

#### `property unresolved_imports`
Return import_list entries that still warrant user attention.

Includes failed imports (INVALID) and duplicates (DUPLICATE).  Excludes
READY (resolved) and IGNORED (explicitly dismissed by the caller).

This is the signal a UI should use to decide whether to keep showing
import-resolution affordances.  It stays non-empty while there is still
something the user can act on — even when ``imports_resolved`` is already
True because the only remaining items are non-blocking duplicates.
Once every entry is READY or IGNORED, this list is empty and the
resolution UI can close.

#### `def validate(self, format: 'str' = '') -> 'bool'`
Validate OSCAL content against the metaschema index in sequenced phases.

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

#### `def walk_imports(self, visitor_fn, depth=0, _seen=None, *, scope='successful')`
Walk the import tree depth-first, calling ``visitor_fn(entry, depth)`` for each entry.

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

#### `property xml`
Return the content as an XML string, converting from dict if necessary.

#### `property yaml`
Return the content as a YAML string.

# Module: oscal.metaschema_parser

metaschema_parser — parse NIST resolved-metaschema XML into a structural index.

Parses OSCAL resolved-metaschema XML files into a dictionary representation of the
metaschema structure (assemblies, fields, flags, attributes, child elements, and
allowed-value constraints). The resulting index drives XML↔JSON conversion and
validation elsewhere in the library.

While there is some defensive coding, this module assumes metaschema files are
valid; it does not validate metaschema structure or content. It ignores unexpected
structures and logs a WARNING when it encounters expected but unhandled structures.

Module constants:
    SUPPRESS_XPATH_NOT_FOUND_WARNINGS (bool): Suppress warnings when an XPath yields
        no match.
    RUNAWAY_LIMIT (int): Maximum recursion/iteration count before aborting as a
        runaway.
    DEBUG_OBJECT (str): Name of a definition to trace for debugging ("" disables).
    PRUNE_JSON (bool): Remove None values and empty arrays from the resolved JSON output.
    OSCAL_DEFAULT_NAMESPACE (str): The NIST OSCAL namespace URI.
    METASCHEMA_DEFAULT_NAMESPACE (str): The NIST Metaschema namespace URI.
    METASCHEMA_TOP_IGNNORE (list): Top-level metaschema elements to ignore.
    METASCHEMA_TOP_KEEP (list): Top-level metaschema elements to process.
    METASCHEMA_PROPS_HANDLED (list): Metaschema ``prop`` names handled on definitions.
    METASCHEMA_RULE_PROPS_HANDLED (list): Metaschema ``prop`` names handled on rules.
    METASCHEMA_INDEX_PROPS_HANDLED (list): Metaschema ``prop`` names handled on indexes.
    METASCHEMA_ROP_NAMESPACE (list): Recognized metaschema property namespace URIs.
    METASCHEMA_ROOT_ELEMENT (str): Root element name of a metaschema document
        ("METASCHEMA").
    CONSTRAINT_ROOT_ELEMENT (str): Root element name of a meta-constraints document.
    CONSTRAINT_TOP_IGNORE (list): Top-level constraint elements to ignore.
    CONSTRAINT_TOP_KEEP (list): Top-level constraint elements to process.
    GREEN, BLUE, YELLOW, RED, ORANGE, MAGENTA, CYAN, PURPLE, BOLD, RESET (str):
        ANSI terminal escape codes used for colorized diagnostic output.

## Class: MetaschemaParser
Parses a single OSCAL resolved-metaschema XML document into a structural index.

Holds the parsed metaschema tree and namespace/model context, resolves imported
metaschemas, and walks assemblies, fields, and flags to build the nested index
(nodes, attributes, allowed-value constraints) consumed by the converter and
validator. Prefer the :meth:`create` classmethod to construct instances.

### Available Members

#### `def __init__(self, metaschema, support, import_inventory=[], oscal_version='')`
Initialize a parser for one metaschema document.

Args:
    metaschema (str, required): The resolved-metaschema XML content to parse.
    support (OSCALSupport, required): The OSCAL support object used to fetch
        imported metaschemas and store results.
    import_inventory (list, optional): Names of metaschemas already being
        processed, used to prevent circular imports. Defaults to [].
    oscal_version (str, optional): The OSCAL version this metaschema belongs
        to. Defaults to "".

#### `def build_metaschema_tree(self)`
Build the full structural index for this metaschema's model.

Recursively walks the root assembly to produce the node tree, applies
constraints against a synthesized XML skeleton, prunes empty values, and
annotates namespace conditions and JSON paths.

Returns:
    dict: The metaschema index — model metadata plus a ``nodes`` tree — or an
        empty dict on error or when the root assembly cannot be found.

#### `classmethod def create(cls, metaschema, support, import_inventory=[], oscal_version='')`
Construct a ``MetaschemaParser`` (preferred factory over direct instantiation).

Args:
    metaschema (str, required): The resolved-metaschema XML content to parse.
    support (OSCALSupport, required): The OSCAL support object.
    import_inventory (list, optional): Names of metaschemas already being
        processed, to prevent circular imports. Defaults to [].
    oscal_version (str, optional): The OSCAL version. Defaults to "".

Returns:
    MetaschemaParser: A new parser instance.

#### `def get_markup_content(self, xExpr, context=None)`
Run an XPath query and return its markup content as a string.

Handles results that are either plain strings or nodes containing HTML
(markup) formatting, returning a string in either case.

Args:
    xExpr (str, required): An XPath expression.
    context (Element, optional): Node to evaluate the expression against.
        Defaults to None (whole document).

Returns:
    str: The matched content as a string (markup preserved as HTML).

#### `def graceful_accumulate(self, current_value, xExpr, context=None)`
Prepend a resolved markup value onto an accumulating list of values.

Used where a field/assembly reference's values must be added to (rather than
replace) any values already defined on the referenced define-field/assembly.

Args:
    current_value (list, required): The existing accumulated values; wrapped in
        a list if not already one.
    xExpr (str, required): XPath expression yielding the markup value to add.
    context (Element, optional): Node to evaluate against. Defaults to None.

Returns:
    list: ``current_value`` with the resolved value inserted at the front (when
        non-empty).

#### `def graceful_override(self, current_value, xExpr, context=None)`
Return an overriding value when present, otherwise keep the current value.

Used where a field/assembly reference's value must replace any value already
defined on the referenced define-field/assembly.

Args:
    current_value (Any, required): The existing value to keep if no override
        is found.
    xExpr (str, required): XPath expression yielding the overriding value.
    context (Element, optional): Node to evaluate against. Defaults to None.

Returns:
    Any: The resolved override value if non-empty, otherwise ``current_value``.

#### `def handle_attributes(self, metaschema_node, definition_obj: xml.etree.ElementTree.Element, structure_type, name, parent)`
Map an XML definition's attributes onto a metaschema node.

Translates attributes such as ``as-type`` (datatype), ``required``,
``min-occurs``/``max-occurs`` (cardinality), ``collapsible``, ``deprecated``,
``default``, and ``in-xml`` (XML wrapping) into node fields. Unhandled
attributes are logged as warnings.

Args:
    metaschema_node (dict, required): The node being built; updated in place.
    definition_obj (ET.Element, required): The XML definition element.
    structure_type (str, required): The definition's structure type.
    name (str, required): The definition name.
    parent (str, required): The parent path.

Returns:
    dict: The updated ``metaschema_node``.

#### `def handle_children(self, name, structure_type, metaschema_node, context, handle_choice=0)`
Resolve the child model of an assembly (fields, assemblies, choices, any).

Walks the assembly's ``model`` (or a specific ``choice`` group), recursing to
build each child node and constructing synthetic nodes for ``choice``/``any``.

Args:
    name (str, required): The definition name being processed.
    structure_type (str, required): "define-assembly" or "choice".
    metaschema_node (dict, required): The parent node (provides path/source).
    context (Element, required): The XML context to search within.
    handle_choice (int, optional): 1-based index of the choice group to process
        when ``structure_type`` is "choice". Defaults to 0.

Returns:
    list: The resolved child node dicts.

#### `def handle_constraints(self, metaschema_node, definition_obj, structure_type, name, parent)`
Process ``<constraint><allowed-values>`` elements from a definition object.

Targets are handled as follows: ``.`` or absent applies to the current node;
``@flag-name`` applies to the named flag child; complex Metapath targets are
resolved against the XML skeleton (or stored with the unresolved target
preserved). Multiple allowed-values sets for the same target are cumulative;
``allow-other`` conflicts resolve with 'yes' winning and emit a warning.

Args:
    metaschema_node (dict, required): The node being built; updated in place.
    definition_obj (ET.Element, required): The XML definition element.
    structure_type (str, required): The definition's structure type.
    name (str, required): The definition name.
    parent (str, required): The parent path.

Returns:
    dict: The updated ``metaschema_node``.

#### `def handle_flags(self, metaschema_node, definition_obj, structure_type, name, parent)`
Resolve the flags defined or referenced by a field or assembly.

Finds each ``define-flag``/``flag`` child, recurses to build its node, and
collects the results.

Args:
    metaschema_node (dict, required): The parent node being built (used for
        path context).
    definition_obj (ET.Element, required): The field/assembly XML definition.
    structure_type (str, required): The parent's structure type.
    name (str, required): The parent definition name.
    parent (str, required): The parent path.

Returns:
    list: The resolved flag node dicts (empty when none are present).

#### `def handle_group_as(self, metaschema_node, definition_obj: xml.etree.ElementTree.Element, structure_type, name, parent)`
Apply a definition's ``group-as`` element to a metaschema node.

Reads the ``group-as`` name and its ``in-xml``/``in-json`` grouping
attributes and records them (and XML wrapping) on the node.

Args:
    metaschema_node (dict, required): The node being built; updated in place.
    definition_obj (ET.Element, required): The XML definition element.
    structure_type (str, required): The definition's structure type.
    name (str, required): The definition name (for logging).
    parent (str, required): The parent path (used to build wrapped paths).

Returns:
    dict: The updated ``metaschema_node``.

#### `def handle_props(self, metaschema_node, definition_obj, structure_type, name, parent)`
Map a definition's ``prop`` elements onto a metaschema node.

Recognized props (``METASCHEMA_PROPS_HANDLED`` in the OSCAL namespace) are
promoted to dedicated node keys; any other prop is appended to the node's
``props`` list as ``{"name", "value", "namespace"}``.

Args:
    metaschema_node (dict, required): The node being built; updated in place.
    definition_obj (ET.Element, required): The XML definition element.
    structure_type (str, required): The definition's structure type.
    name (str, required): The definition name.
    parent (str, required): The parent path.

Returns:
    dict: The updated ``metaschema_node``.

#### `def initialize_metaschema_index(self)`
Create a new, fully-keyed metaschema index-constraint dict with default values.

Called before each index constraint is populated, to guarantee a consistent
key set (id, level, name, target, handled props, etc.).

Returns:
    dict: A new index dict with all expected keys initialized.

#### `def initialize_metaschema_node(self)`
Create a new, fully-keyed metaschema index node with default (empty) values.

Called as each node is created, including the top-level node, to guarantee a
consistent key set (path, name, datatype, cardinality, children, constraints,
handled props, etc.).

Returns:
    dict: A new node dict with all expected keys initialized.

#### `def initialize_metaschema_rule(self)`
Create a new, fully-keyed metaschema rule with default (empty) values.

Called before each rule (e.g. an allowed-values constraint) is populated, to
guarantee a consistent key set (id, level, datatype, allowed-values,
allow-other, test, message, cardinality, etc.).

Returns:
    dict: A new rule dict with all expected keys initialized.

#### `def look_in_imports(self, name, structure_type, parent='', ignore_local=False, already_searched=None)`
Search imported metaschemas for a definition by name and structure type.

Args:
    name (str, required): The definition name to find.
    structure_type (str, required): The structure type to match
        (e.g. "define-assembly", "define-field", "define-flag").
    parent (str, optional): Parent path for the resolved node. Defaults to "".
    ignore_local (bool, optional): Passed through to recursion; ignore local
        definitions in the imported metaschema. Defaults to False.
    already_searched (list | None, optional): Definition names already visited,
        to prevent cycles. Defaults to None.

Returns:
    dict | None: The resolved node from the imported metaschema, or None if not
        found.

#### `def recurse_metaschema(self, name, structure_type='define-assembly', parent='', ignore_local=False, already_searched=None, context=None, skip_children=False, use_name=None)`
Recursively build a metaschema index node and its descendants.

Processes the XML definition for ``name`` and extracts a node dict describing
its attributes, flags, and child elements, recursing into referenced
definitions.

Args:
    name (str, required): The definition/element name to process (e.g. a model
        or field name).
    structure_type (str, optional): The kind of definition — "define-assembly",
        "define-field", "define-flag", or an inline assembly/field/flag.
        Defaults to "define-assembly".
    parent (str, optional): Name of the parent definition, for logging/paths.
        Defaults to "".
    ignore_local (bool, optional): When True, ignore local (non-exported)
        definitions; set True when recursing into an imported metaschema so its
        private locals are not exposed. Defaults to False.
    already_searched (list | None, optional): Definition names already visited,
        to prevent infinite recursion. Defaults to None.
    context (Element, optional): XML context node to search within.
        Defaults to None.
    skip_children (bool, optional): When True, do not recurse into child
        elements. Defaults to False.
    use_name (str | None, optional): Override for the node's effective
        (use-)name. Defaults to None.

Returns:
    dict: The metaschema index node for ``name`` (with nested children).

#### `def set_default_values(self, metaschema_node, definition_obj, structure_type, name, parent)`
Fill in default node values required by the metaschema specification.

Applies spec defaults for any unset attributes — datatype ("string"),
cardinality (0..1, or 1..1 for the root), ``json-collapsible``,
``deprecated``, ``default``, and XML wrapping for fields/assemblies.

Args:
    metaschema_node (dict, required): The node being built; updated in place.
    definition_obj (ET.Element, required): The XML definition element.
    structure_type (str, required): The definition's structure type.
    name (str, required): The definition name.
    parent (str, required): The parent path; an empty value marks the root node.

Returns:
    dict: The updated ``metaschema_node``.

#### `def setup_imports(self)`
Identify ``import`` elements and load each as a nested ``MetaschemaParser``.

Imported metaschemas are fetched from the support database and stored in
``self.imports`` keyed by model name for later cross-metaschema lookups.

Returns:
    None

#### `def str_node(self, node)`
Build a human-readable summary of a parsed metaschema index node.

Args:
    node (dict, required): An index node produced by the parser, carrying
        keys such as ``formal-name``, ``use-name``, ``min-occurs``,
        ``max-occurs``, ``datatype``, ``children``, and ``constraints``.

Returns:
    str: A multi-line, human-readable description of the node.

#### `def top_pass(self)`
Perform the first parsing pass: deserialize XML and read top-level metadata.

Parses the metaschema content, then extracts the model name, schema name,
OSCAL version, namespace, and JSON base URI, and sets up imports.

Returns:
    bool: True if the XML was well-formed and parsed, False otherwise.

#### `def xpath(self, xExpr, context=None) -> xml.etree.ElementTree.Element | list[xml.etree.ElementTree.Element] | None`
Run an XPath query and return the matching element(s).

Args:
    xExpr (str, required): An XPath expression.
    context (Element, optional): Node to evaluate the expression against.
        When None, the expression runs against the whole document.
        Defaults to None.

Returns:
    ET.Element | list[ET.Element] | None: A single element, a list of
        elements, or None on error / no match.

#### `def xpath_atomic(self, xExpr, context=None)`
Run an XPath query and return the first result as a string.

Args:
    xExpr (str, required): An XPath expression.
    context (Element, optional): Node to evaluate the expression against.
        When None, the expression runs against the whole document.
        Defaults to None.

Returns:
    str: The first matching result as a string, or "" on error / no match.

## Module Functions

#### `def clean_none_values_recursive(dictionary)`
Recursively drop None values and empty containers from a dict.

Removes key/value pairs whose value is None, and prunes empty nested dicts and
lists (including dicts nested inside lists), returning a new cleaned dict.

Args:
    dictionary (dict, required): The dictionary to clean.

Returns:
    dict: A new dictionary with None values and empty containers removed.

#### `def parse_metaschema(support=None, oscal_version=None) -> int`
Parse and store the OSCAL metaschema index for one or all supported versions.

Args:
    support (OSCALSupport, optional): The OSCAL support object. Currently the
        shared instance is fetched internally via ``get_support()`` regardless
        of this argument. Defaults to None.
    oscal_version (str, optional): The OSCAL version to parse. When None, all
        supported versions are processed. Defaults to None.

Returns:
    int: 0 on success, 1 on error (process-style exit code).

#### `def parse_metaschema_specific(support, oscal_version)`
Parse and store every model index for a specific OSCAL version.

Each model index is stored separately in the support database as
``(version, model, "processed")`` and written to
``support/<version>/<model>.json`` alongside the support database.

Args:
    support (OSCALSupport, required): The OSCAL support object providing
        metaschema assets and asset storage.
    oscal_version (str, required): The OSCAL version to parse.

Returns:
    bool: True if all models parsed and stored successfully, False otherwise.
