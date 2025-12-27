"""
OSCAL Support Class

Provides support for managing OSCAL versions and associated support files.
Includes functionality to fetch OSCAL releases from GitHub, store support files,
and provide local access to these files for OSCAL processing.
"""
import os
from loguru import logger
from importlib import resources
import uuid
from time import sleep
from common.lfs import chkdir, putfile, chkfile
from common import helper 
from common import database
from common import network
from .oscal_datatypes import oscal_date_time_with_timezone

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SUPPORT_DATABASE_DEFAULT_FILE = "./support/oscal_support.db"
SUPPORT_DATABASE_DEFAULT_TYPE = "sqlite3"
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# As defined by NIST:
OSCAL_DEFAULT_XML_NAMESPACE = "http://csrc.nist.gov/ns/oscal/1.0"
NIST_OSCAL_EXTENSION_NAMESPACE = "http://csrc.nist.gov/ns/oscal"
NIST_RMF_EXTENSION_NAMESPACE = "http://csrc.nist.gov/ns/rmf"
OSCAL_FORMATS = ["xml", "json", "yaml", "yml"]
# OSCAL_MODELS = ["catalog", "profile", "component-definition", "system-security-plan", "assessment-plan", "assessment-results", "plan-of-action-and-milestones", "mapping", "shared-responsibility"]

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Release and Support File Patterns
# DEFAULT_EXCLUDE_TAG_PATTERNS = ["-rc", "-milestone"] # Ignore release tags with these substrings.
DEFAULT_EXCLUDE_VERSIONS = ["v1.0.0-rc1", "v1.0.0-rc2", "v1.0.0-milestone1", "v1.0.0-milestone2", "v1.0.0-milestone3"] 
SUPPORT_FILE_PATTERNS    = {
    "_metaschema_RESOLVED.xml":   "metaschema",    # OSCAL specification files
    "_schema.xsd":                "xml-schema",       # OSCAL XML schema validation files
    "_schema.json":               "json-schema",      # OSCAL JSON schema validation files
    "_xml-to-json-converter.xsl": "xml-to-json", # OSCAL XML to JSON converters
    "_json-to-xml-converter.xsl": "json-to-xml" # OSCAL JSON to XML converters
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

# ========================================================================
def setup_support(support_file= SUPPORT_DATABASE_DEFAULT_FILE, db_init_mode="auto"):
    logger.debug(f"Setting up support file: {support_file}")
    
    support = OSCAL_support.create(support_file, db_init_mode=db_init_mode)
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
        logger.debug("Support file is ready.")

    return support

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCAL_support:
    def __init__(self, db_conn=SUPPORT_DATABASE_DEFAULT_FILE, db_type=SUPPORT_DATABASE_DEFAULT_TYPE, db_init_mode="auto"):
        """
        Initialize OSCAL Support.
        
        Args:
            db_conn: Database connection string or path
            db_type: Database type (sqlite3, mysql, etc.)
            db_init_mode: Database initialization mode:
                - "auto": Extract from resources if file missing/empty, otherwise create empty
                - "extract": Always try to extract from resources, create empty if extraction fails
                - "create": Always create empty database from scratch
        """
        self.ready      = False     # Is the support capability available?
        self.db_conn    = db_conn   # The support database connection string or path and filename 
        self.db_type    = db_type   # The support database type (sqlite3, mysql, postgresql, mssql, etc.)
        self.db_init_mode = db_init_mode  # Database initialization mode
        self.db_state   = "unknown" # The state of the support database (unknown, not-present, empty, populated)
        self.versions   = {}        # Supported OSCAL versions available within the support database, and support references
        self.extensions = {}        # Supported OSCAL extensions available within the support database, and support references
        self.backend    = None      # If working within an application, this is the backend object
        self._cache     = {}        # Internal cache for support operations

        logger.debug(f"Initializing OSCAL_support with db_type='{db_type}', db_conn='{db_conn}', db_init_mode='{db_init_mode}'")

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
        logger.debug("Support: __init__")

        # TODO: Enable running in both sync and async contexts
        # self.async_mode = False
        # try:
        #     asyncio.get_running_loop()
        #     self.async_mode = True
        #     self.executor = self._async_execute
        # except RuntimeError:
        #     self.async_mode = False
        #     self.executor = self._sync_execute

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
            with resources.open_binary('oscal.data', 'oscal_support.zip') as default_db:
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
        except Exception as e:
            logger.error(f"Failed to extract default support DB: {e}")
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
    def sync_init(self):
        """Synchronous initialization"""
        logger.debug("Support: sync_init")
        self.ready = self.startup()

    # -------------------------------------------------------------------------
    @classmethod
    def create(cls, db_conn, db_type="sqlite3", db_init_mode="auto"):
        """Synchronous factory method to create and initialize OSCAL_support"""
        logger.debug("Support: create")
        instance = cls(db_conn, db_type, db_init_mode)
        if instance.db is not None:
            instance.sync_init()
        else:
            logger.error("Unable to create support database object.")
            instance.ready = False
        return instance

    # -------------------------------------------------------------------------


    # -------------------------------------------------------------------------
    @classmethod
    def create_auto(cls, db_conn, db_type="sqlite3", db_init_mode="auto"):
        """Auto-detecting factory method - now just returns sync version"""
        logger.debug("Support: create_auto")
        return cls.create(db_conn, db_type, db_init_mode)

    # -------------------------------------------------------------------------
    def startup(self, check_for_updates=False, refresh_all=False):
        """
        Perform startup tasks required to provide OSCAL support.

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
    def update(self, fetch="latest", backend=None):
        """
        Update OSCAL support content based on the fetch directive.
        - "all": Clears all re-fetches all OSCAL versions and support files.
        - "latest": Check for new OSCAL versions and fetch if found.
        - "vX.Y.Z": Clear and re-fetch a specific OSCAL version and its support files.
        Args:
            fetch (str): The directive for fetching OSCAL versions.
                         - "all" for all versions
                         - "latest" for the latest version
                         - "vX.Y.Z" for a specific version
            backend (Optional[Any]): Optional backend object for status updates.
        Returns:
            bool: True if the update was successful, False otherwise.
        """
        status = False
        self.backend = backend
        
        try:
            match fetch:
                case "all":
                    self.__status_messages("Starting full refresh of OSCAL support content...")
                    status = self.__clear_oscal_versions()
                case "latest":
                    self.__status_messages("Checking for new OSCAL versions...")
                    status = True
                case _:
                    if fetch.startswith("v"):
                        self.__status_messages(f"Updating specific version: {fetch}")
                        status = self.__clear_oscal_version(fetch)
                    else:
                        logger.error(f"Invalid update directive: {fetch}")
                        status = False
            
            if status:
                # Get OSCAL versions with periodic status updates
                status = self.__get_oscal_versions(fetch)
            
            # Final reload of versions
            self.__load_versions()
            
            self.__status_messages("Update process completed.")
            
        except Exception as e:
            logger.error(f"Error during update: {e}")
            self.__status_messages(f"Error during update: {str(e)}", "error")
            status = False
            
        return status

    # -------------------------------------------------------------------------
    def asset(self, oscal_version, model_name, asset_type):
        """
        Returns the asset for the specified OSCAL version and model name.
        Args:
            oscal_version (str): The OSCAL version (e.g., "v1.0.0").
            model_name (str): The OSCAL model name (e.g., "system-security-plan").
            asset_type (str): The type of asset to retrieve (e.g., "xml-schema", "json-schema").
        Returns:
            The asset content if found, None otherwise.
        """
        filecache_uuid = None
        asset = None

        if oscal_version in self.versions:
            query = f"SELECT filecache_uuid FROM oscal_support WHERE version = '{oscal_version}' and model = '{model_name}' and type = '{asset_type}'"
            results = self.db.query(query)
            if results is not None:
                filecache_uuid = results[0].get("filecache_uuid", None)
                # logger.debug(f"Found filecache UUID {filecache_uuid} for {oscal_version} and {model_name}.")
                logger.debug(f"Found filecache UUID {filecache_uuid} for {oscal_version} and {model_name}.")
                # Check if the filecache UUID is valid
                if filecache_uuid:
                    # Get the asset from the filecache
                    asset = helper.normalize_content(self.db.retrieve_file(filecache_uuid))
                else:
                    logger.error(f"Unable to find asset for {oscal_version} and {model_name}.")
            else:
                logger.error(f"Unable to find asset for {oscal_version} and {model_name}.")
        else:
            logger.error(f"OSCAL version {oscal_version} is either not valid or not supported.")

        return asset

    # -------------------------------------------------------------------------
    def supported(self, oscal_version, assets):
        """
        Currently not implemented.
        Checks if the specified OSCAL version and assets are supported.
        """
        status = False


        return status

    # -------------------------------------------------------------------------
    def is_model_valid(self, model_name, version="all") -> bool:
        """
        Check if the specified OSCAL model is valid for the given version.
        Args:
            model_name (str): The OSCAL model name to check (e.g., "system-security-plan").
            version (str): The OSCAL version to check against (e.g., "v1.0.0").
        Returns:
            bool: True if the model is valid for the specified version, False otherwise.
        """
        is_valid = False
        models = self.enumerate_models(version)
        if model_name in models:
            is_valid = True
        return is_valid
    # -------------------------------------------------------------------------
    def enumerate_models(self, version: str = "all") -> list[str]:
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
                query = "SELECT DISTINCT model FROM oscal_support WHERE type = 'xml-schema' and model != 'complete'"
            else:
                query = f"SELECT DISTINCT model FROM oscal_support WHERE version = '{version}' and type = 'xml-schema' and model != 'complete'"
            results = self.db.query(query)
            if results is not None:
                for entry in results:
                    models.append(entry.get("model", ""))

            self._cache[CACHE_MODELS_PER_VERSION][version] = models

        return models

    # -------------------------------------------------------------------------
    def add_asset(self, oscal_version, model_name, asset_type, content, filename=None):
        """
        Add an asset to the support database. If the asset already exists, it will be replaced.
        This method supports both string and bytes content types.
        If the content is a string, it will be converted to bytes.
        If the content is already in bytes, it will be used as is.
        Args:
            oscal_version (str): The OSCAL version (e.g., "v1.0.0").
            model_name (str): The OSCAL model name (e.g., "system-security-plan").
            asset_type (str): The type of asset to add (e.g., "xml-schema", "json-schema").
            content (Any): The content of the asset to add.
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
    def get_latest_version(self):
        """Returns the latest supported OSCAL version."""
        latest_version = None
        if self.versions:
            latest_version = sorted(self.versions.keys(), reverse=True)[0]
        return latest_version
    # -------------------------------------------------------------------------
    def __get_oscal_versions(self, fetch="latest"):
        """Pulls OSCAL version information and support files from GitHub and loads it into the database."""
        status = True
        OSCAL_versions: list[str] = []
        fetch_all = (fetch == "all")
        fetch_latest = (fetch == "latest")
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
                
                if not entry.get("draft", False):
                    oscal_version = entry.get("tag_name", "").lower()
                    # self.__status_messages(f"Found non-draft OSCAL Version {oscal_version}...")
                    if (oscal_version not in DEFAULT_EXCLUDE_VERSIONS):
                        # self.__status_messages(f"Found non-excluded OSCAL Version {oscal_version}") 
                        
                        ok_to_continue = (fetch_all or 
                                        (fetch_latest and oscal_version not in self.versions) or
                                        (fetch_one and oscal_version == fetch))

                        if ok_to_continue:
                            self.__status_messages(f"Processing {oscal_version} release...")
                            release_date = entry.get("published_at", "0000-00-00T00:00:00Z")
                            release_name = entry.get("name", "")
                            github_location = f"{OSCAL_Release_URL}/{oscal_version}" 
                            documentation_location = f"{OSCAL_documentation}/{oscal_version}" 
                            self.__clear_oscal_version(oscal_version)
                            
                            # Database operations
                            
                            logger.info(f"Learning {oscal_version}, released {release_date} ...")
                            if self.db.insert("oscal_versions", {
                                "version": oscal_version,
                                "released": release_date,
                                "title": release_name,
                                "github_location": github_location,
                                "documentation_location": documentation_location,
                                "acquired": oscal_date_time_with_timezone()
                            }):
                                OSCAL_versions.append(oscal_version)
                                if "assets" in entry:
                                    # Process assets in chunks
                                    self.__fetch_support_files(oscal_version, entry["assets"])
                            else:
                                logger.error(f"Unable to insert OSCAL version {oscal_version} into support database.")
                        else:
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
        """Process assets sequentially"""
        status = False
        
        # Process assets sequentially
        for asset in assets:
            asset_name = asset.get("name", "")
            for pattern in SUPPORT_FILE_PATTERNS:
                if pattern in asset_name:
                    self.__process_single_asset(version, asset, pattern)
        
        status = True
        return status

    # -------------------------------------------------------------------------
    def __process_single_asset(self, version, asset, pattern):
        """Helper method to process a single asset"""
        asset_name = asset.get("name", "")
        asset_URL = asset.get("browser_download_url", "")
        model_name = asset_name.replace("oscal_", "").replace(pattern, "")

        # Special case for SSP and POAM
        if model_name == "ssp": 
            model_name = "system-security-plan"
        if model_name == "poam": 
            model_name = "plan-of-action-and-milestones"
        
        uuid_value = str(uuid.uuid4())
        
        self.__status_messages(f"Downloading {asset_name}...")
        
        # Perform database inserts
        self.db.insert("oscal_support", {
            "version": version,
            "model": model_name,
            "type": SUPPORT_FILE_PATTERNS[pattern],
            "filecache_uuid": uuid_value
        })
        
        # Download file content synchronously
        content = network.download_file(asset_URL, asset_name)

        if content:
            attributes = {
                "filename": asset_name,
                "original_location": asset_URL,
                "mime_type": "application/octet-stream",
                "file_type": SUPPORT_FILE_PATTERNS[pattern],
                "acquired": oscal_date_time_with_timezone()
            }
            self.db.cache_file(content, uuid_value, attributes)
            self.__status_messages(f"Downloaded [{version}] {asset_name}")
        else:
            self.__status_messages(f"Failed to download {asset_name}", "error")

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
        Export all support files to the specified directory.
        Args:
            export_path (str): The directory to export support files to.
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
    def __status_messages(self, status="", level="info"):
        """Enhanced status message handling"""
        if self.backend is not None:
            self.backend.status_update(status, level)
        logger.info(status)

    # -------------------------------------------------------------------------
    def load_file(self, file_name, binary=False):
        """Load a schema XML file from package data."""
        CACHE_FROM_DATA = "from_data"
        if CACHE_FROM_DATA in self._cache:
            if file_name in self._cache[CACHE_FROM_DATA]:
                return self._cache[CACHE_FROM_DATA][file_name]
        else:
            self._cache[CACHE_FROM_DATA] = {}
        
        try:
            if binary:
                with resources.open_binary("oscal.data", file_name) as f:
                    content = f.read()
                self._cache[CACHE_FROM_DATA][file_name] = content
                logger.debug(f"Loaded binary schema file: {file_name}")
                return content

            else:
                with resources.open_text("oscal.data", file_name) as f:
                    content = f.read()
            
            self._cache[CACHE_FROM_DATA][file_name] = content
            logger.debug(f"Loaded schema file: {file_name}")
            return content
            
        except Exception as e:
            logger.error(f"Failed to load OSCAL support library file {file_name}: {e}")
            return None
    # -------------------------------------------------------------------------



# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':
    print("The OSCAL Support Class is intended to be part of a larger application.")
