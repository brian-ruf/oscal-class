"""
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
"""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
import logging
from importlib import resources
import uuid
import time
from time import sleep
from typing import Optional
from ruf_common.lfs import chkdir, putfile, chkfile
from ruf_common import helper
from ruf_common import database
from ruf_common import network
from .oscal_datatypes import oscal_date_time_with_timezone

logger = logging.getLogger(__name__)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUPPORT_DATABASE_DEFAULT_FILE = "./support/oscal_support.db"
SUPPORT_DATABASE_DEFAULT_TYPE = "sqlite3"
COMPRESS_SUPPORT_FILES_IN_DATABASE = True
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# As defined by NIST:
OSCAL_DEFAULT_XML_NAMESPACE = "http://csrc.nist.gov/ns/oscal/1.0"
NIST_OSCAL_EXTENSION_NAMESPACE = "http://csrc.nist.gov/ns/oscal"
NIST_RMF_EXTENSION_NAMESPACE = "http://csrc.nist.gov/ns/rmf"
OSCAL_FORMATS = ["xml", "json", "yaml", "yml"]

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Release and Support File Patterns
# DEFAULT_EXCLUDE_TAG_PATTERNS = ["-rc", "-milestone"] # Ignore release tags with these substrings.
DEFAULT_EXCLUDE_VERSIONS = ["v1.0.0-rc1", "v1.0.0-rc2", "v1.0.0-milestone1", "v1.0.0-milestone2", "v1.0.0-milestone3"]
METASCHEMA_MIN_VERSION = "v1.1.1"  # NIST did not publish resolved metaschema files before this version
INDEX_REFRESH = 86400  # Seconds before a cached metaschema index entry is considered stale (24 hours)

# Module-level cache for parsed metaschema index objects.
# Key: (version, model)  Value: {"version", "model", "last_retrieved", "index"}
_metaschema_index_cache: dict = {}
METASCHEMA_FILE_PATTERNS = {
    "_metaschema_RESOLVED.xml": "metaschema",   # OSCAL resolved metaschema specification files
}
SCHEMA_FILE_PATTERNS = {
    "_schema.xsd":  "xml-schema",               # OSCAL XML schema validation files
    "_schema.json": "json-schema",              # OSCAL JSON schema validation files
}

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# GitHub root URLs
GitHub_API_root = "https://api.github.com"
GitHub_raw_root = "https://raw.githubusercontent.com"
GitHub_release_root = "https://github.com"
http_header = {"Content-type": "application/json"}

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# NIST OSCAL GitHub and Dcoumentation URLs
OSCAL_repo = "usnistgov/OSCAL" # Official NIST OSCAL GitHub Repository owner and repository name
OSCAL_repo_API = f'{GitHub_API_root}/{OSCAL_repo}/releases'
OSCAL_Release_URL = f"{GitHub_release_root}/{OSCAL_repo}/releases/tag" # /{tag_name}
OSCAL_asset_downloads = f"{GitHub_release_root}/{OSCAL_repo}/tree" # /{tag_name}
OSCAL_documentation = "https://pages.nist.gov/OSCAL-Reference/models" # /{tag_name}

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Data structures for the OSCAL support database
OSCAL_SUPPORT_TABLES={}
OSCAL_SUPPORT_TABLES["oscal_versions"] = {
    "table_name": "oscal_versions",
    "table_fields": [
        {"name": "version"               , "type": "TEXT"   , "attributes": "PRIMARY KEY", "label" : "Release Tag", "description": "The GitHub release tag assocaited with the OSCAL version."},
        {"name": "title"                 , "type": "TEXT"   , "label" : "Release Title", "description": "The title of the released version."},
        {"name": "released"              , "type": "NUMERIC", "label" : "Released", "description": "The date and time the version was released."},
        {"name": "github_location"       , "type": "TEXT"   , "label" : "GitHub Location", "description": "The location of the GitHub release for this version of OSCAL."},
        {"name": "documentation_location", "type": "TEXT"   , "label" : "Documentation Location", "description": "The location of documentation for this version."},
        {"name": "acquired"              , "type": "NUMERIC", "label" : "Acquired", "description": "The date and time the support files were loaded into this system."},
        {"name": "successful"            , "type": "NUMERIC", "label" : "Successful", "description": "Indicates whether all support files were acquired successfully."}
    ]
}
OSCAL_SUPPORT_TABLES["oscal_support"] = {
    "table_name": "oscal_support",
    "table_fields": [
        {"name": "version"         , "type": "TEXT", "attributes": "KEY", "label" : "OSCAL Version","description": "The OSCAL version."},
        {"name": "model"           , "type": "TEXT", "label" : "OSCAL Model", "description": "The OSCAL model name, exactly as it appears in OSCAL syntax."},
        {"name": "type"            , "type": "TEXT", "label" : "Support File Type", "description": "The type of support file."},
        {"name": "filecache_uuid"  , "type": "TEXT", "label" : "Cache UUID", "description": "The filecache UUID of the support file for this OSCAL version and model."}
    ]
}
OSCAL_SUPPORT_TABLES["filecache"] = database.OSCAL_COMMON_TABLES["filecache"]

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OSCAL_DATA_TYPES = {}

_METASCHEMA_NS = "http://csrc.nist.gov/ns/oscal/metaschema/1.0"
_METASCHEMA_PFX = f"{{{_METASCHEMA_NS}}}"


def _extract_root_name(content: str | bytes) -> str | None:
    """Return the OSCAL root-name from a resolved metaschema XML string, or None.

    Document models declare a ``<root-name>`` inside their top-level
    ``<define-assembly>``; shared metaschemas (e.g. assessment-common) do not.
    """
    try:
        text = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
        root = ET.fromstring(text)
        for da in root.findall(f"{_METASCHEMA_PFX}define-assembly"):
            rn = da.find(f"{_METASCHEMA_PFX}root-name")
            if rn is not None and rn.text:
                return rn.text.strip()
        for da in root.findall("define-assembly"):
            rn = da.find("root-name")
            if rn is not None and rn.text:
                return rn.text.strip()
    except Exception:
        pass
    return None


support = None

# ========================================================================
def configure_support(
    support_file=SUPPORT_DATABASE_DEFAULT_FILE,
    db_init_mode="auto",
    *,
    db_path: Optional[str] = None,
    init_mode: Optional[str] = None,
):
    """
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
    """
    if db_path is not None:
        support_file = db_path
    if init_mode is not None:
        db_init_mode = init_mode

    logger.debug(f"Setting up support file: {support_file}")
    global support

    if support is None:
        support = OSCALSupport(support_file, db_init_mode=db_init_mode)
        cycle = 0
        while not support.ready:
            logger.debug("Waiting for support object to be ready...")
            if support.db_state != "unknown":
                logger.debug(f"Support file status {support.db_state}")
                break
            cycle += 1
            if cycle > 20:
                logger.error(f"Support object took too long to be ready.({support.db_state})")
                break
            sleep(0.25)
        if not support.ready:
            logger.error("Support object is not ready.")
        else:
            logger.debug("Support database is ready.")

    return support

# -------------------------------------------------------------------------
def get_support():
    """
    Return the shared OSCAL support instance, creating it if necessary.

    Creates the instance with default settings (via ``configure_support()``) if it
    does not already exist.

    Returns:
        OSCALSupport: The shared support instance.
    """
    logger.debug("Fetching the support object instance.")
    global support

    if support is None:
        support = configure_support()

    return support


def setup_support(support_file=SUPPORT_DATABASE_DEFAULT_FILE, db_init_mode="auto"):
    """Compatibility wrapper around ``configure_support()`` for update utility scripts.

    Args:
        support_file (str, optional): Path to the support database file.
            Defaults to ``SUPPORT_DATABASE_DEFAULT_FILE``.
        db_init_mode (str, optional): Database initialization mode
            (``"auto"``, ``"extract"``, or ``"create"``). Defaults to ``"auto"``.

    Returns:
        OSCALSupport: The shared support instance.
    """
    return configure_support(support_file=support_file, db_init_mode=db_init_mode)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCALSupport:
    """Access layer for the local OSCAL support-file database.

    Manages a SQLite database of NIST-published support files (metaschemas and
    XML/JSON schemas) for every OSCAL version and model, and exposes methods for
    querying supported versions/models, retrieving assets, building metaschema
    indexes, and updating content from NIST's GitHub releases.

    Prefer the module-level ``get_support()`` accessor over instantiating this
    class directly, so a single instance is shared across the application.

    Note:
        ``OSCAL_support`` is a backward-compatible alias for this class.
    """
    def __init__(self, db_conn=SUPPORT_DATABASE_DEFAULT_FILE, db_type=SUPPORT_DATABASE_DEFAULT_TYPE, db_init_mode="auto", db_compress_files=COMPRESS_SUPPORT_FILES_IN_DATABASE):
        """
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
        """
        self.ready      = False     # Is the support capability available?
        self.db_conn    = db_conn   # The support database connection string or path and filename
        self.db_type    = db_type   # The support database type (sqlite3, mysql, postgresql, mssql, etc.)
        self.db_init_mode = db_init_mode  # Database initialization mode
        self.db_compress_files = db_compress_files  # Whether to compress support files in the database
        self.db_state   = "unknown" # The state of the support database (unknown, not-present, empty, populated)
        self.versions   = {}        # Supported OSCAL versions available within the support database, and support references
        self.extensions = {}        # Supported OSCAL extensions available within the support database, and support references
        self.backend    = None      # If working within an application, this is the backend object
        self._cache     = {}        # Internal cache for support operations
        self._update_stats = None   # Populated during update(); None when not running an update

        logger.debug(f"Initializing OSCALSupport with db_type='{db_type}', db_conn='{db_conn}', db_init_mode='{db_init_mode}'")

        # Handle database initialization based on mode and type
        should_extract = False
        should_create = False
        extract_reason = ""

        if db_type == "sqlite3":
            if db_conn is None or db_conn.strip() == "":
                # No database specified, use default
                logger.debug("Using default database configuration")
                db_conn = SUPPORT_DATABASE_DEFAULT_FILE
                self.db_conn = db_conn  # Update the instance variable
                logger.debug(f"Using default database file: {db_conn}")
            else:
                # Database path specified
                logger.debug(f"Using specified database file: {db_conn}")
                self.db_conn = db_conn  # Ensure instance variable is set

            # Determine what action to take based on mode
            file_exists = chkfile(db_conn)
            file_size = os.path.getsize(db_conn) if file_exists else 0

            logger.debug(f"Database file status: exists={file_exists}, size={file_size} bytes")

            if self.db_init_mode == "create":
                # Always create from scratch
                should_create = True
                logger.debug("Mode 'create': Will create database from scratch")
            elif self.db_init_mode == "extract":
                # Always try to extract, create if extraction fails
                should_extract = True
                extract_reason = "mode 'extract' specified"
            elif self.db_init_mode == "auto":
                # Auto-detect based on file status
                if not file_exists:
                    should_extract = True
                    extract_reason = "file does not exist"
                elif file_size == 0:
                    should_extract = True
                    extract_reason = "file exists but is empty (0 bytes)"
                else:
                    logger.debug(f"Database file {db_conn} exists and has content ({file_size} bytes)")
            else:
                logger.error(f"Invalid db_init_mode: '{self.db_init_mode}'. Using 'auto' mode.")
                self.db_init_mode = "auto"
                # Rerun the auto logic
                if not file_exists:
                    should_extract = True
                    extract_reason = "file does not exist (fallback to auto)"
                elif file_size == 0:
                    should_extract = True
                    extract_reason = "file exists but is empty (fallback to auto)"

            # Handle extraction
            if should_extract:
                extraction_successful = self._extract_database(db_conn, extract_reason)

                # If extraction failed and we're in extract mode, fall back to create
                if not extraction_successful and self.db_init_mode == "extract":
                    logger.warning("Extraction failed, falling back to creating empty database")
                    should_create = True

            # Handle creation from scratch
            if should_create:
                self._create_empty_database(db_conn)

            # If neither extraction nor creation was needed/requested
            if not should_extract and not should_create:
                logger.debug("No database initialization needed")
        else:
            logger.debug(f"Not using SQLite database (db_type='{db_type}'), skipping extraction")

        logger.debug(f"Final database connection: {self.db_conn}")
        self.db = database.Database(self.db_type, self.db_conn)

        # TODO: Enable running in both sync and async contexts
        # self.async_mode = False
        # try:
        #     asyncio.get_running_loop()
        #     self.async_mode = True
        #     self.executor = self._async_execute
        # except RuntimeError:
        #     self.async_mode = False
        #     self.executor = self._sync_execute

        self.startup()
    # -------------------------------------------------------------------------
    def __repr__(self) -> str:
        return f"<OSCALSupport {'✅' if self.ready else '❌'} {self.db_conn} ({self.db_type}) db_init_mode='{self.db_init_mode}' db_state='{self.db_state}' versions={list(self.versions.keys())}>"
    # -------------------------------------------------------------------------
    def __str__(self) -> str:
        return f"OSCAL Support: {list(self.versions.keys())}\n{'✅' if self.ready else '❌'} {self.db_conn} ({self.db_type}'): {self.db_state}"
    # -------------------------------------------------------------------------
    def _extract_database(self, db_conn, reason):
        """
        Extract the default database from package resources.
        Returns True if extraction was successful, False otherwise.
        """
        logger.debug(f"Database extraction needed: {reason}")

        # Ensure the directory exists
        db_dir = os.path.dirname(db_conn)
        if db_dir != "":
            chkdir(db_dir, make_if_not_present=True)

        # unzip the default database from package resources
        import zipfile
        try:
            logger.debug("Opening oscal_support.zip from oscal.data...")
            with resources.files("oscal.data").joinpath("oscal_support.zip").open("rb") as default_db:
                with zipfile.ZipFile(default_db) as z:
                    member = "oscal_support.db"
                    if member in z.namelist():
                        # Get file info to check size
                        file_info = z.getinfo(member)
                        logger.debug(f"Extracting {member} (compressed: {file_info.compress_size} bytes, uncompressed: {file_info.file_size} bytes)")

                        # Read all content from the zip member
                        with z.open(member) as src:
                            content = src.read()
                            logger.debug(f"Read {len(content)} bytes from zip member")

                            # Write content to destination file
                            with open(db_conn, "wb") as dst:
                                bytes_written = dst.write(content)
                                logger.debug(f"Wrote {bytes_written} bytes to {db_conn}")

                        if len(content) > 0:
                            logger.info(f"Successfully extracted default support DB to {db_conn} ({len(content)} bytes)")
                            return True
                        else:
                            logger.error(f"Extracted file {member} is empty (0 bytes)")
                            return False
                    else:
                        logger.error(f"{member} not found inside oscal_support.zip")
                        logger.debug(f"Available files in zip: {z.namelist()}")
                        return False
        except FileNotFoundError:
            logger.warning("No pre-built support database found — a new one will be initialized.")
            return False
        except Exception as e:
            logger.warning(f"Could not extract default support DB: {e} — a new one will be initialized.")
            import traceback
            logger.debug(f"Exception details: {traceback.format_exc()}")
            return False

    # -------------------------------------------------------------------------
    def _create_empty_database(self, db_conn):
        """
        Create an empty database that will be populated later.
        This removes any existing file and creates a fresh empty database.
        """
        logger.debug(f"Creating empty database from scratch: {db_conn}")

        # Ensure the directory exists
        db_dir = os.path.dirname(db_conn)
        if db_dir != "":
            chkdir(db_dir, make_if_not_present=True)

        # Remove existing file if it exists
        if chkfile(db_conn):
            try:
                os.remove(db_conn)
                logger.debug(f"Removed existing database file: {db_conn}")
            except Exception as e:
                logger.error(f"Failed to remove existing database file {db_conn}: {e}")
                return False

        # Create empty file - the Database class will initialize it with proper tables
        try:
            with open(db_conn, 'w'):
                pass  # Create empty file
            logger.info(f"Created empty database file: {db_conn}")
            return True
        except Exception as e:
            logger.error(f"Failed to create empty database file {db_conn}: {e}")
            return False

    # -------------------------------------------------------------------------
    def startup(self, check_for_updates=False, refresh_all=False):
        """
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
        """
        logger.debug("Support: startup")
        status = False

        if not self.db_state or self.db_state == "unknown":
            # status = await self.__check_for_tables()
            status = self.db.check_for_tables(OSCAL_SUPPORT_TABLES)

            logger.debug(f"Support database tables check status: {status}")

            if status: # Tables exist
                # TODO: Check database structure against current
                #       structure and modify fields as needed.
                status = self.__load_versions()
                if status:
                    self.db_state = "populated"
                    self.ready = True
                else:
                    self.db_state = "empty"
            else:
                logger.error("Unable to initiate OSCAL support capability. Exiting.")
                self.ready = False

        if self.db_state == "empty":
            status = self.__get_oscal_versions()

            if status:
                self.db_state = "populated"
                self.ready = True
            else:
                logger.error("Unable to update OSCAL support capability. Exiting.")
                self.ready = False

        return status

    # -------------------------------------------------------------------------
    def update(self, mode="new", fetch=None, save_to_fs=False): # , backend=None):
        """
        Update OSCAL support content based on a fetch directive.

        Args:
            mode (str, optional): The fetch directive. Defaults to "new".
                - "all": Clear and re-fetch all OSCAL versions and support files.
                - "latest"/"new": Check for new OSCAL versions and fetch any found.
                - "vX.Y.Z": Clear and re-fetch a specific OSCAL version.
            fetch (str, optional): Legacy alias for ``mode``; when provided it
                overrides ``mode``. Defaults to None.
            save_to_fs (bool, optional): When True, also emit the parsed
                metaschema index files to the local file system in addition to
                updating the database. When False (default), only the database
                is updated. Defaults to False.

        Returns:
            bool: True if the update was successful, False otherwise.
        """
        status = False
        if fetch is not None:
            mode = fetch

        fetch = mode

        self._update_stats = {
            "versions_processed": [],
            "versions_skipped":   [],
            "files_fetched":      0,
            "files_fetch_failed": [],   # (version, filename)
            "files_saved":        0,
            "files_save_failed":  [],   # (version, filename)
            "metaschema_built":   [],
            "metaschema_skipped": [],
            "metaschema_failed":  [],
        }

        try:
            if fetch == "all":
                self.__status_messages("Starting full refresh of OSCAL support content...")
                status = self.__clear_oscal_versions()
                if status:
                    self.__vacuum_database()
            elif fetch == "latest" or fetch == "new":
                self.__status_messages("Checking for new OSCAL versions...")
                status = True
            else:
                if fetch.startswith("v"):
                    self.__status_messages(f"Updating specific version: {fetch}")
                    status = self.__clear_oscal_version(fetch)
                else:
                    logger.error(f"Invalid update directive: {fetch}")
                    status = False

            if status:
                status = self.__get_oscal_versions(fetch, save_to_fs=save_to_fs)

            self.__load_versions()
            self.__status_messages("Update process completed.")
            self.__report_update_stats()

        except Exception as e:
            logger.error(f"Error during update: {e}")
            self.__status_messages(f"Error during update: {str(e)}", "error")
            status = False

        return status

    # -------------------------------------------------------------------------
    def get_asset(self, version, model, asset_type):
        """
        Returns the asset for the specified OSCAL version and model name.
        Args:
            version (str): The OSCAL version (e.g., "v1.0.0").
            model (str): The OSCAL model name (e.g., "system-security-plan").
            asset_type (str): The type of asset to retrieve (e.g., "xml-schema", "json-schema").
        Returns:
            The asset content if found, None otherwise.
        """
        filecache_uuid = None
        asset = None

        if version in self.versions:
            query = f"SELECT filecache_uuid FROM oscal_support WHERE version = '{version}' and model = '{model}' and type = '{asset_type}'"
            results = self.db.query(query)
            if results:
                filecache_uuid = results[0].get("filecache_uuid", None)
                # logger.debug(f"Found filecache UUID {filecache_uuid} for {oscal_version} and {model_name}.")
                logger.debug(f"Found filecache UUID {filecache_uuid} for {version} and {model}.")
                # Check if the filecache UUID is valid
                if filecache_uuid:
                    # Get the asset from the filecache
                    asset = helper.normalize_content(self.db.retrieve_file(filecache_uuid))
                else:
                    logger.error(f"Unable to find asset for {version} and {model}.")
            else:
                logger.error(f"Unable to find asset for {version} and {model}.")
        else:
            logger.error(f"OSCAL version {version} is either not valid or not supported.")

        return asset

    # -------------------------------------------------------------------------
    def asset(self, oscal_version, model_name, asset_type):
        """Backward-compatible wrapper for :meth:`get_asset`.

        Args:
            oscal_version (str, required): The OSCAL version (e.g. "v1.0.0").
            model_name (str, required): The OSCAL model name (e.g. "system-security-plan").
            asset_type (str, required): The asset type (e.g. "xml-schema", "json-schema").

        Returns:
            Any: The asset content if found, otherwise None.
        """
        return self.get_asset(oscal_version, model_name, asset_type)

    # -------------------------------------------------------------------------
    def get_metaschema_index(self, version: str, model: str) -> dict | None:
        """
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
        """
        key = (version, model)
        now = time.time()

        entry = _metaschema_index_cache.get(key)
        if entry and (now - entry["last_retrieved"]) < INDEX_REFRESH:
            logger.debug(f"Metaschema index cache hit for {version}/{model}.")
            return entry["index"]

        logger.debug(f"Metaschema index cache miss for {version}/{model} — fetching from database.")

        # Try the per-model entry first (new format).
        raw = self.get_asset(version, model, "processed")

        # Fall back to the legacy combined "complete" entry and migrate on first hit.
        if not raw:
            logger.debug(f"Per-model index not found for {version}/{model}; trying legacy 'complete' entry.")
            complete_raw = self.get_asset(version, "complete", "processed")
            if complete_raw:
                try:
                    complete_index = json.loads(complete_raw)
                    model_index = complete_index.get("oscal_models", {}).get(model)
                    if model_index is not None:
                        model_json = json.dumps(model_index, indent=2)
                        stored = self.add_asset(version, model, "processed", model_json, filename=f"{model}.json")
                        if stored:
                            logger.info(f"Migrated {version}/{model} from legacy 'complete' index to per-model entry.")
                        raw = model_json
                except json.JSONDecodeError as exc:
                    logger.error(f"Could not parse legacy 'complete' metaschema index for {version}: {exc}")

        if not raw:
            logger.error(f"No processed metaschema index found for {version}/{model}. Run the metaschema parser to populate support assets.")
            return None

        try:
            model_index = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(f"Could not parse metaschema index for {version}/{model}: {exc}")
            return None

        if not model_index:
            logger.error(f"Empty metaschema index for {version}/{model}.")
            return None

        # Ensure json-path (node-level) and condition (constraint-level) are present.
        # Indexes built before these features were added lack these keys; annotate lazily.
        nodes = model_index.get("nodes")
        if nodes and isinstance(nodes, dict):
            from .metaschema_parser import (
                _annotate_ns_conditions,
                _assign_node_refs,
                _compute_json_paths,
                _index_uses_stale_allow_other_key,
                _migrate_flags_to_children,
                _reroute_unresolved_constraints,
            )

            # Detect indexes built by an older parser that stored "allow-others" (plural)
            # instead of the current "allow-other" key.  The stored value may also be
            # incorrect (e.g. False when the metaschema says allow-other="yes").
            # Rebuild only this model's index from the raw metaschema XML.
            if _index_uses_stale_allow_other_key(nodes):
                logger.info(
                    f"Stale metaschema index for {version}/{model} "
                    "(deprecated 'allow-others' key) — rebuilding from raw metaschema."
                )
                from .metaschema_parser import _rebuild_model_index
                fresh_index = _rebuild_model_index(self, version, model)
                if fresh_index is not None:
                    _metaschema_index_cache.pop(key, None)
                    model_index = fresh_index
                    nodes = model_index.get("nodes")
                else:
                    logger.warning(
                        f"Rebuild failed for {version}/{model} — continuing with stale index. "
                        "Allowed-values constraints may be overly strict."
                    )

            _migrate_flags_to_children(nodes)
            _reroute_unresolved_constraints(nodes)
            _annotate_ns_conditions(nodes)
            _compute_json_paths(nodes, "")
            _assign_node_refs(nodes, f"{version}/{model}")

        _metaschema_index_cache[key] = {
            "version": version,
            "model": model,
            "last_retrieved": now,
            "index": model_index,
        }
        logger.debug(f"Metaschema index cached for {version}/{model}.")
        return _metaschema_index_cache[key]["index"]

    # -------------------------------------------------------------------------
    def view_outline(self, version: str, model: str, format: str) -> str:
        """Return an HTML ``<div>`` outline of a model's metaschema structure.

        The outline is a clickable tree rendered in the requested format's syntax
        (``"xml"``, ``"json"``, or ``"yaml"``), annotated with data types and
        cardinality. Each element links to its node by a stable reference id, for use
        with :meth:`view_detail`. Intended for a front-end: the HTML is a fragment
        (wrapped in a ``<div>``), never a full page.

        Args:
            version (str, required): OSCAL version, e.g. ``"v1.1.3"``.
            model (str, required): OSCAL model name, e.g. ``"catalog"``.
            format (str, required): ``"xml"``, ``"json"``, or ``"yaml"``.

        Returns:
            str: An outline ``<div>`` fragment, or a ``<div class="ms-error">`` when
                the model/version/format is unknown or the index is unavailable.
        """
        from . import metaschema_gen_docs as views

        if not self.is_valid_model(model, version):
            return views.error_html(f"Unknown OSCAL model '{model}' for version '{version}'.")
        index = self.get_metaschema_index(version, model)
        if index is None:
            return views.error_html(f"No metaschema index available for {version}/{model}.")
        return views.render_outline(index, format, version=version, model=model)

    # -------------------------------------------------------------------------
    def view_detail(self, version: str, model: str, format: str, reference_uuid: str) -> str:
        """Return an HTML ``<div>`` detail view of a single metaschema node.

        Given a node's reference id (as produced by :meth:`view_outline`), returns its
        formal name and description, a format-appropriate representation, data type and
        regex (where available), constraints, and its immediate parent and children —
        each parent/child clickable by its own reference id.

        Args:
            version (str, required): OSCAL version, e.g. ``"v1.1.3"``.
            model (str, required): OSCAL model name, e.g. ``"catalog"``.
            format (str, required): ``"xml"``, ``"json"``, or ``"yaml"``.
            reference_uuid (str, required): The node reference id to describe.

        Returns:
            str: A detail ``<div>`` fragment, or a ``<div class="ms-error">`` when the
                model/version/format or reference is unknown.
        """
        from . import metaschema_gen_docs as views

        if not self.is_valid_model(model, version):
            return views.error_html(f"Unknown OSCAL model '{model}' for version '{version}'.")
        index = self.get_metaschema_index(version, model)
        if index is None:
            return views.error_html(f"No metaschema index available for {version}/{model}.")
        return views.render_detail(index, reference_uuid, format)

    # -------------------------------------------------------------------------
    def supported(self, oscal_version, assets):
        """
        Check whether the specified OSCAL version and assets are supported.

        Note:
            Currently not implemented; always returns False.

        Args:
            oscal_version (str, required): The OSCAL version to check (e.g. "v1.0.0").
            assets (list, required): The asset types to check for.

        Returns:
            bool: True if the version and assets are supported, False otherwise.
        """
        status = False


        return status

    # -------------------------------------------------------------------------
    def is_valid_model(self, model, version="all") -> bool:
        """
        Check if the specified OSCAL model is valid for the given version.
        Args:
            model (str): The OSCAL model name to check (e.g., "system-security-plan").
            version (str): The OSCAL version to check against (e.g., "v1.0.0").
        Returns:
            bool: True if the model is valid for the specified version, False otherwise.
        """
        is_valid = False
        models = self.list_models(version)
        if model in models:
            is_valid = True
        return is_valid

    # -------------------------------------------------------------------------
    def is_model_valid(self, model_name, version="all") -> bool:
        """Backward-compatible wrapper for :meth:`is_valid_model`.

        Args:
            model_name (str, required): The OSCAL model name to check.
            version (str, optional): The OSCAL version to check against, or "all".
                Defaults to "all".

        Returns:
            bool: True if the model is valid for the version, False otherwise.
        """
        return self.is_valid_model(model_name, version)

    # -------------------------------------------------------------------------
    def list_models(self, version: str = "all") -> list[str]:
        """
        Enumerate the supported models for a given OSCAL version.
        Args:
            version (str): The OSCAL version to enumerate models for (e.g., "v1.0.0").
        Returns:
            list[str]: A list of model-name strings supported for the specified OSCAL version
                       (may be empty).
        """
        models: list[str] = []

        if version == "all" or version in self.versions:

            CACHE_MODELS_PER_VERSION = "models_per_version"
            if CACHE_MODELS_PER_VERSION in self._cache:
                if version in self._cache[CACHE_MODELS_PER_VERSION]:
                    return self._cache[CACHE_MODELS_PER_VERSION][version]
            else:
                self._cache[CACHE_MODELS_PER_VERSION] = {}

            if version == "all":
                doc_query = "SELECT DISTINCT model FROM oscal_support WHERE type = 'document-model' and model != 'complete'"
                xml_query = "SELECT DISTINCT model FROM oscal_support WHERE type = 'xml-schema' and model != 'complete'"
            else:
                # NIST did not publish resolved metaschema files before v1.1.1, so no
                # model rows exist for earlier versions. The library reuses the v1.1.1
                # models for all prior versions; query that version instead.
                query_version = version
                if helper.compare_semver(version, METASCHEMA_MIN_VERSION) < 0:
                    query_version = METASCHEMA_MIN_VERSION
                doc_query = f"SELECT DISTINCT model FROM oscal_support WHERE version = '{query_version}' and type = 'document-model' and model != 'complete'"
                xml_query = f"SELECT DISTINCT model FROM oscal_support WHERE version = '{query_version}' and type = 'xml-schema' and model != 'complete'"

            results = self.db.query(doc_query)
            if not results:
                results = self.db.query(xml_query)
            if results is not None:
                for entry in results:
                    models.append(entry.get("model", ""))

            self._cache[CACHE_MODELS_PER_VERSION][version] = models

        return models

    # -------------------------------------------------------------------------
    def enumerate_models(self, version: str = "all") -> list[str]:
        """Backward-compatible wrapper for :meth:`list_models`.

        Args:
            version (str, optional): The OSCAL version to enumerate models for, or
                "all". Defaults to "all".

        Returns:
            list[str]: Supported model-name strings (may be empty).
        """
        return self.list_models(version)

    # -------------------------------------------------------------------------
    def add_asset(self, oscal_version, model_name, asset_type, content, filename=None):
        """
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
        """
        status = False
        logger.debug(f"Add asset {model_name} ({asset_type}) for version {oscal_version}.")
        if isinstance(content, str):
            # If content is a string, convert it to bytes
            content = content.encode('utf-8')
            status = True  # Content is now in bytes
        elif isinstance(content, bytes):
            status = True  # Content is already in bytes
        else:
            logger.error(f"Content for {model_name} ({asset_type}) must be bytes or a string. Received type: {type(content)}")
        # Check if the version is valid

        if status and self.is_valid_version(oscal_version):
            status = True
        else:
            logger.error(f"OSCAL version {oscal_version} is not valid or supported.")
            status = False

        if status:
            filecache_uuid = None
            attributes = {}
            attributes["filename"] = filename if filename else f"{model_name}_{asset_type}"
            attributes["original_location"] = ""
            attributes["mime_type"] = "application/octet-stream"
            attributes["file_type"] = asset_type
            attributes["acquired"] = oscal_date_time_with_timezone()


            # Check if the asset already exists
            query = f"SELECT filecache_uuid FROM oscal_support WHERE version = '{oscal_version}' and model = '{model_name}' and type = '{asset_type}'"
            results = self.db.query(query)
            if results is not None and len(results) > 0:
                filecache_uuid = results[0].get("filecache_uuid", None)
                if filecache_uuid:
                    logger.debug(f"Asset {model_name} ({asset_type}) for version {oscal_version} already exists with UUID {filecache_uuid}.")
            else:
                logger.debug(f"No existing asset found for {model_name} ({asset_type}) for version {oscal_version}. Proceeding to insert.")

            if filecache_uuid:
                # If the asset already exists, update it
                logger.debug(f"Updating existing asset {model_name} ({asset_type}) for version {oscal_version} with UUID {filecache_uuid}.")

                # Cache the file content
                if self.db.cache_file(content, filecache_uuid, attributes):
                    status = True
                    logger.info(f"Updated asset {model_name} ({asset_type}) for version {oscal_version}.")
                else:
                    logger.error(f"Failed to cache updated file for {model_name} ({asset_type}) for version {oscal_version}.")
            else:
                logger.debug(f"Adding new asset {model_name} ({asset_type}) for version {oscal_version} with UUID {filecache_uuid}.")
                filecache_uuid = str(uuid.uuid4())

                # Cache the file content
                if self.db.cache_file(content, filecache_uuid, attributes):
                    status = True
                    self.db.insert("oscal_support", {
                        "version": oscal_version,
                        "model": model_name,
                        "type": asset_type,
                        "filecache_uuid": filecache_uuid
                    })

                    logger.info(f"Added asset {model_name} ({asset_type}) for version {oscal_version}.")
                else:
                    logger.error(f"Failed to cache file for {model_name} ({asset_type}) for version {oscal_version}.")

        return status

    # -------------------------------------------------------------------------
    def is_valid_version(self, version) -> bool:
        """
        Check if the specified OSCAL version is valid and supported.
        Args:
            version (str): The OSCAL version to check (e.g., "v1.0.0").
        Returns:
            bool: True if the version is valid and supported, False otherwise.
        """
        return version in self.versions

    # -------------------------------------------------------------------------
    def __load_versions(self):
        """
        Load supported OSCAL versions and support references into memory.
        """
        status = False

        logger.debug("Loading OSCAL versions into memory.")

        query = "SELECT * FROM oscal_versions ORDER BY released DESC"
        results = self.db.query(query)
        if results is not None:
            for entry in results:
                self.versions[entry["version"]] = {
                    "title"                 : entry.get("title", ""),
                    "released"              : entry.get("released", ""),
                    "github_location"       : entry.get("github_location", ""),
                    "documentation_location": entry.get("documentation_location", ""),
                    "acquired"              : entry.get("acquired", ""),
                    "successful"            : entry.get("successful", None),
                }
            status = True

        return status

    # -------------------------------------------------------------------------
    def latest_version(self):
        """Return the latest supported OSCAL version.

        Returns:
            Optional[str]: The highest OSCAL version tag available in the support
                database, or None if none are loaded.
        """
        latest_version = None
        if self.versions:
            latest_version = sorted(self.versions.keys(), reverse=True)[0]
        return latest_version

    # -------------------------------------------------------------------------
    def get_latest_version(self):
        """Backward-compatible wrapper for :meth:`latest_version`.

        Returns:
            Optional[str]: The latest OSCAL version tag, or None if none are loaded.
        """
        return self.latest_version()
    # -------------------------------------------------------------------------
    def __get_oscal_versions(self, fetch="latest", save_to_fs=False):
        """Pulls OSCAL version information and support files from GitHub and loads it into the database."""
        status = True
        OSCAL_versions: list[str] = []
        fetch_all = (fetch == "all")
        fetch_latest = (fetch == "latest" or fetch == "new")
        fetch_one = (fetch.startswith("v"))

        self.__status_messages("Fetching OSCAL release informaiton from GitHub...")

        response = network.api_get(GitHub_API_root + "/repos/" + OSCAL_repo + "/releases")
        self.__status_messages("Fetching OSCAL release information from GitHub...done.")

        if response is not None and response.ok:
            repo_releases: list[dict] = response.json()
            total_releases = len(repo_releases)

            self.__status_messages(f"Found {total_releases} releases in the OSCAL GitHub repository.")
            for idx, entry in enumerate(repo_releases, 1):
                self.__status_messages(f"Inspecting release {idx} of {total_releases}...")
                # Progress indicator (no need for asyncio.sleep in sync mode)

                oscal_version = entry.get("tag_name", "").lower()
                if not entry.get("draft", False):
                    # self.__status_messages(f"Found non-draft OSCAL Version {oscal_version}...")
                    if (oscal_version not in DEFAULT_EXCLUDE_VERSIONS):
                        # self.__status_messages(f"Found non-excluded OSCAL Version {oscal_version}")

                        ok_to_continue = (fetch_all or
                                        (fetch_latest and oscal_version not in self.versions) or
                                        (fetch_one and oscal_version == fetch))

                        if ok_to_continue:
                            if self._update_stats is not None:
                                self._update_stats["versions_processed"].append(oscal_version)
                            self.__status_messages(f"Processing {oscal_version} release...")
                            release_date = entry.get("published_at", "0000-00-00T00:00:00Z")
                            release_name = entry.get("name", "")
                            github_location = f"{OSCAL_Release_URL}/{oscal_version}"
                            documentation_location = f"{OSCAL_documentation}/{oscal_version}"
                            self.__clear_oscal_version(oscal_version)

                            # Database operations

                            logger.info(f"Learning {oscal_version}, released {release_date} ...")
                            acquired_ts = oscal_date_time_with_timezone()
                            if self.db.insert("oscal_versions", {
                                "version": oscal_version,
                                "released": release_date,
                                "title": release_name,
                                "github_location": github_location,
                                "documentation_location": documentation_location,
                                "acquired": acquired_ts,
                            }):
                                # Register in memory immediately so list_models() can find it
                                # during __build_metaschema_index() later in this same loop.
                                self.versions[oscal_version] = {
                                    "title":                  release_name,
                                    "released":               release_date,
                                    "github_location":        github_location,
                                    "documentation_location": documentation_location,
                                    "acquired":               acquired_ts,
                                    "successful":             None,
                                }
                                OSCAL_versions.append(oscal_version)
                                if "assets" in entry:
                                    self.__fetch_support_files(oscal_version, entry["assets"])
                                    if helper.compare_semver(oscal_version, METASCHEMA_MIN_VERSION) >= 0:
                                        self.__build_metaschema_index(oscal_version, save_to_fs=save_to_fs)
                                    else:
                                        if self._update_stats is not None:
                                            self._update_stats["metaschema_skipped"].append(oscal_version)
                                        self.__status_messages(f"Skipping metaschema index for {oscal_version} (resolved metaschema not published before {METASCHEMA_MIN_VERSION}).")
                            else:
                                logger.error(f"Unable to insert OSCAL version {oscal_version} into support database.")
                        else:
                            if self._update_stats is not None:
                                self._update_stats["versions_skipped"].append(oscal_version)
                            if fetch_one and oscal_version != fetch:
                                self.__status_messages(f"Skipping {oscal_version} release. Not the version specified.")
                            elif fetch_latest and oscal_version in self.versions:
                                self.__status_messages(f"Skipping {oscal_version} release. Already have this version.")
                            else:
                                self.__status_messages(f"Skipping {oscal_version} release.")
                    else:
                        self.__status_messages(f"Skipping excluded OSCAL Version {oscal_version}...")
                else:
                    self.__status_messages(f"Skipping draft OSCAL Version {oscal_version}...")

        else:
            logger.error("Unable to fetch release information from GitHub.")
            status = False

        if status:
            self.__status_messages("OSCAL version information loaded successfully.")
            self.__status_messages(f"Learned {len(OSCAL_versions)} OSCAL versions.")
            self.__status_messages(f"OSCAL versions: {', '.join(OSCAL_versions)}")

        return status

    # -------------------------------------------------------------------------
    def __fetch_support_files(self, version, assets):
        """Download and store metaschema files for *version* into the database."""
        for asset in assets:
            asset_name = asset.get("name", "")
            for pattern in METASCHEMA_FILE_PATTERNS:
                if pattern in asset_name:
                    self.__process_single_asset(version, asset, pattern)
        return True

    # -------------------------------------------------------------------------
    def __process_single_asset(self, version, asset, pattern):
        """Helper method to process a single asset"""
        asset_name = asset.get("name", "")
        asset_URL = asset.get("browser_download_url", "")
        model_name = asset_name.replace("oscal_", "").replace(pattern, "")

        # Special cases for SSP, POAM, and Component
        if model_name == "ssp":
            model_name = "system-security-plan"
        if model_name == "poam":
            model_name = "plan-of-action-and-milestones"
        if model_name == "component":
            model_name = "component-definition"

        uuid_value = str(uuid.uuid4())

        self.__status_messages(f"Downloading {asset_name}...")

        # Perform database inserts
        self.db.insert("oscal_support", {
            "version": version,
            "model": model_name,
            "type": METASCHEMA_FILE_PATTERNS[pattern],
            "filecache_uuid": uuid_value
        })

        # Download file content synchronously
        content = network.download_file(asset_URL, asset_name)

        if content:
            if self._update_stats is not None:
                self._update_stats["files_fetched"] += 1
            attributes = {
                "filename": asset_name,
                "original_location": asset_URL,
                "mime_type": "application/octet-stream",
                "file_type": METASCHEMA_FILE_PATTERNS[pattern],
                "acquired": oscal_date_time_with_timezone(),
                "compressed": COMPRESS_SUPPORT_FILES_IN_DATABASE
            }
            saved = self.db.cache_file(content, uuid_value, attributes)
            if saved:
                if self._update_stats is not None:
                    self._update_stats["files_saved"] += 1
                self.__status_messages(f"Downloaded [{version}] {asset_name}")

                # If this is a metaschema, check for root-name to identify document models
                if METASCHEMA_FILE_PATTERNS[pattern] == "metaschema":
                    root_name = _extract_root_name(content)
                    if root_name:
                        self.db.insert("oscal_support", {
                            "version": version,
                            "model": root_name,
                            "type": "document-model",
                            "filecache_uuid": uuid_value,
                        })
                        logger.debug(f"Registered '{root_name}' as a document model for {version}.")

                        # When root-name differs from the filename-derived model name
                        # (e.g. root-name='mapping-collection', file key='mapping'),
                        # insert a metaschema alias so lookups by root-name also work.
                        if root_name != model_name:
                            self.db.insert("oscal_support", {
                                "version": version,
                                "model": root_name,
                                "type": "metaschema",
                                "filecache_uuid": uuid_value,
                            })
                            logger.debug(f"Added metaschema alias '{root_name}' → '{model_name}' for {version}.")
            else:
                if self._update_stats is not None:
                    self._update_stats["files_save_failed"].append((version, asset_name))
                self.__status_messages(f"Failed to save [{version}] {asset_name}", "error")
        else:
            if self._update_stats is not None:
                self._update_stats["files_fetch_failed"].append((version, asset_name))
            self.__status_messages(f"Failed to download {asset_name}", "error")

    # -------------------------------------------------------------------------
    def __build_metaschema_index(self, version, save_to_fs=False):
        """Parse the metaschema for *version* and store the processed index.

        Uses a lazy import to avoid the circular dependency between
        oscal_support and metaschema_parser.

        When *save_to_fs* is True, the parsed metaschema index files are also
        emitted to the local file system; otherwise only the database is updated.
        """
        self.__status_messages(f"Building metaschema index for {version}...")
        try:
            from .metaschema_parser import parse_metaschema_specific  # lazy import
            ok = parse_metaschema_specific(self, version, save_to_fs=save_to_fs)
            if ok:
                if self._update_stats is not None:
                    self._update_stats["metaschema_built"].append(version)
                self.__status_messages(f"Metaschema index for {version} built successfully.")
            else:
                if self._update_stats is not None:
                    self._update_stats["metaschema_failed"].append(version)
                self.__status_messages(f"Metaschema index for {version} failed to build.", "error")
        except Exception as e:
            if self._update_stats is not None:
                self._update_stats["metaschema_failed"].append(version)
            logger.error(f"Error building metaschema index for {version}: {e}")
            self.__status_messages(f"Error building metaschema index for {version}: {e}", "error")

    # -------------------------------------------------------------------------
    def __vacuum_database(self) -> None:
        """Reclaim free space in the database after a bulk delete.

        Only executed for SQLite databases — VACUUM is a SQLite-specific DDL
        statement that rewrites the database file in place and is not
        appropriate (or available) on enterprise databases such as PostgreSQL
        or MySQL.

        VACUUM must run outside any open transaction, so it is issued directly
        on the underlying connection rather than through db_execute().
        """
        if self.db_type != "sqlite3":
            logger.debug(f"Skipping VACUUM: not applicable for db_type '{self.db_type}'.")
            return

        if self.db is None or self.db.conn is None:
            logger.warning("Cannot VACUUM: database connection is not open.")
            return

        try:
            self.__status_messages("Compressing database (VACUUM)...")
            self.db.conn.execute("VACUUM")
            logger.info("Database VACUUM completed successfully.")
            self.__status_messages("Database compression complete.")
        except Exception as e:
            logger.warning(f"VACUUM failed (non-fatal): {e}")

    # -------------------------------------------------------------------------
    def __clear_oscal_version(self, version):
        """
        Clear all support content for the specified OSCAL version.
        """
        status = False

        sql_commands = [
            # "BEGIN TRANSACTION;",
            f"""
            WITH uuids_to_delete AS (
                SELECT filecache_uuid
                FROM oscal_support
                WHERE version = '{version}'
            )
            DELETE FROM filecache
            WHERE uuid IN (SELECT filecache_uuid FROM uuids_to_delete);""",
            f"DELETE FROM oscal_support WHERE version = '{version}';",
            f"DELETE FROM oscal_versions WHERE version = '{version}';"
            # "COMMIT;"
        ]

        status = self.db.db_execute(sql_commands)

        if status:
            logger.info(f"Successfully deleted support information for version {version}")
        else:
            logger.error(f"Unable to deleted support information for version {version}")

        return status

    # -------------------------------------------------------------------------
    def __clear_oscal_versions(self):
        """
        Clear all support content for all OSCAL versions.
        """
        status = False
        if self.versions:
            for version in self.versions:
                status = self.__clear_oscal_version(version)
                self.__status_messages(f"Clearing support content for version {version}")
                if not status:
                    break
        else:
            status = True
        return status

    # -------------------------------------------------------------------------
    def export_support_files(self, export_path="./support_files"):
        """
        Export all cached support files to a directory tree, grouped by version.

        Args:
            export_path (str, optional): The directory to export support files to.
                Defaults to "./support_files".

        Returns:
            bool: True if the export was successful, False otherwise.
        """
        status = False

        if self.versions:

            export_path = os.path.abspath(export_path)
            logger.debug(f"Export path expanded to: {export_path}")

            status = chkdir(export_path, make_if_not_present=True)
            if status:
                logger.debug(f"OSCAL support files present. Exporting support files to {export_path}...")

                for version in self.versions:
                    version_path = os.path.join(export_path, version)
                    if chkdir(version_path, make_if_not_present=True):
                        logger.debug(f"Exporting support files for version {version} to {version_path}...")


                        # Query all records for this version from oscal_support table
                        query = f"SELECT * FROM oscal_support WHERE version = '{version}'"
                        support_records = self.db.query(query)

                        if support_records:
                            for record in support_records:
                                model = record.get('model', '')
                                asset_type = record.get('type', '')
                                filecache_uuid = record.get('filecache_uuid', '')
                                filename = self.db.retrieve_file_name(filecache_uuid)
                                if filename:
                                    filename = os.path.join(version_path, filename)
                                    try:
                                        content = self.db.retrieve_file(filecache_uuid)
                                        if content is not None:
                                            content = helper.normalize_content(content)
                                            status = putfile(filename, content)
                                            if status:
                                                logger.debug(f"Exported {model} ({asset_type}) to {filename}.")
                                            else:
                                                logger.error(f"Failed to write asset to {filename}.")
                                        else:
                                            logger.error(f"No content found for UUID {filecache_uuid}.")
                                    except Exception as e:
                                        logger.error(f"Failed to write asset to {filename}: {e}")
                                        status = False
                                else:
                                    logger.error(f"Asset not found for {model} ({asset_type}) in version {version}.")
                    else:
                        logger.error(f"Unable to create or access version directory: {version_path}")
                        status = False
            else:
                logger.error(f"Unable to create or access export directory: {export_path}")
                status = False
        else:
            logger.error("No OSCAL versions available to export.")
            status = False

        return status
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    def download_schemas(self, support_dir: str, fetch: str = "all") -> bool:
        """Download XML and JSON schema files to the filesystem.

        Files are written to ``{support_dir}/{version}_schemas/`` directories and
        are not stored in the support database.

        Args:
            support_dir: Root directory under which per-version schema folders are created.
            fetch: ``"all"`` to download every known version, or a specific version
                   tag (e.g. ``"v1.2.2"``) to download only that version.
        Returns:
            True if all files were saved without error, False otherwise.
        """
        support_dir = os.path.abspath(support_dir)

        if fetch != "all":
            if fetch not in self.versions:
                logger.error(f"Version '{fetch}' is not in the support database.")
                return False
            logger.info(f"Downloading schema files for {fetch} to {support_dir} ...")
        else:
            logger.info(f"Downloading schema files for all versions to {support_dir} ...")

        response = network.api_get(GitHub_API_root + "/repos/" + OSCAL_repo + "/releases")
        if response is None or not response.ok:
            logger.error("Unable to fetch release information from GitHub.")
            return False

        downloaded = 0
        failed = 0

        for entry in response.json():
            oscal_version = entry.get("tag_name", "").lower()
            if oscal_version not in self.versions:
                continue
            if fetch != "all" and oscal_version != fetch:
                continue

            version_dir = os.path.join(support_dir, "schemas", oscal_version)
            if not chkdir(version_dir, make_if_not_present=True):
                logger.error(f"Unable to create directory: {version_dir}")
                failed += 1
                continue

            logger.info(f"Downloading schemas for {oscal_version} ...")
            d, f = self.__fetch_schema_files(oscal_version, entry.get("assets", []), version_dir)
            downloaded += d
            failed += f

        logger.info(f"Schema download complete — {downloaded} file(s) saved, {failed} failure(s).")
        return failed == 0

    # -------------------------------------------------------------------------
    def __fetch_schema_files(self, version, assets, output_dir: str) -> tuple:
        """Download schema files from *assets* and write them to *output_dir*.

        Returns:
            (downloaded_count, failed_count)
        """
        downloaded = 0
        failed = 0

        for asset in assets:
            asset_name = asset.get("name", "")
            for pattern in SCHEMA_FILE_PATTERNS:
                if pattern in asset_name:
                    url = asset.get("browser_download_url", "")
                    content = network.download_file(url, asset_name)
                    if content:
                        content = helper.normalize_content(content)
                        dest = os.path.join(output_dir, asset_name)
                        if putfile(dest, content):
                            logger.info(f"  [{version}] Saved {asset_name}")
                            downloaded += 1
                        else:
                            logger.error(f"  [{version}] Failed to save {asset_name}")
                            failed += 1
                    else:
                        logger.error(f"  [{version}] Failed to download {asset_name}")
                        failed += 1

        return downloaded, failed

    # -------------------------------------------------------------------------
    def __report_update_stats(self):
        """Log a summary of the update run collected in self._update_stats."""
        stats = self._update_stats
        if stats is None:
            return

        lines = [
            "=" * 48,
            "Update Summary",
            "=" * 48,
            f"  Versions processed:    {len(stats['versions_processed'])}",
            f"  Versions skipped:      {len(stats['versions_skipped'])}",
            f"  Files downloaded:      {stats['files_fetched']}",
            f"  Files saved:           {stats['files_saved']}",
            f"  Download failures:     {len(stats['files_fetch_failed'])}",
            f"  Save failures:         {len(stats['files_save_failed'])}",
            f"  Metaschema built:      {len(stats['metaschema_built'])}",
            f"  Metaschema skipped:    {len(stats['metaschema_skipped'])}",
            f"  Metaschema failed:     {len(stats['metaschema_failed'])}",
        ]

        if stats["files_fetch_failed"]:
            lines.append("\n  Download failures:")
            for version, filename in stats["files_fetch_failed"]:
                lines.append(f"    [{version}] {filename}")

        if stats["files_save_failed"]:
            lines.append("\n  Save failures:")
            for version, filename in stats["files_save_failed"]:
                lines.append(f"    [{version}] {filename}")

        if stats["metaschema_failed"]:
            lines.append("\n  Metaschema build failures:")
            for version in stats["metaschema_failed"]:
                lines.append(f"    {version}")

        lines.append("=" * 48)
        self.__status_messages("\n".join(lines))

    # -------------------------------------------------------------------------
    def __status_messages(self, status="", level="info"):
        """Enhanced status message handling"""
        if self.backend is not None:
            self.backend.status_update(status, level)
        logger.info(status)

    # -------------------------------------------------------------------------
    def load_file(self, name, binary=False, *, as_bytes=None):
        """Load a file bundled in the ``oscal.data`` package resources, with caching.

        Args:
            name (str, required): Filename of the resource within ``oscal.data``.
            binary (bool, optional): If True, return raw bytes; otherwise return
                UTF-8 decoded text. Defaults to False.
            as_bytes (bool, optional): Keyword-only alias for ``binary``; overrides
                it when provided. Defaults to None.

        Returns:
            str | bytes | None: The file contents (text or bytes), or None on failure.
        """
        if as_bytes is not None:
            binary = as_bytes

        CACHE_FROM_DATA = "from_data"
        if CACHE_FROM_DATA in self._cache:
            if name in self._cache[CACHE_FROM_DATA]:
                return self._cache[CACHE_FROM_DATA][name]
        else:
            self._cache[CACHE_FROM_DATA] = {}

        try:
            if binary:
                content = resources.files("oscal.data").joinpath(name).read_bytes()
                self._cache[CACHE_FROM_DATA][name] = content
                logger.debug(f"Loaded binary schema file: {name}")
                return content

            else:
                content = resources.files("oscal.data").joinpath(name).read_text(encoding="utf-8")

            self._cache[CACHE_FROM_DATA][name] = content
            logger.debug(f"Loaded schema file: {name}")
            return content

        except Exception as e:
            logger.error(f"Failed to load OSCAL support library file {name}: {e}")
            return None
    # -------------------------------------------------------------------------


# Backwards-compatible class alias
OSCAL_support = OSCALSupport

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':
    print("The OSCAL Support Class is intended to be part of a larger application.")
