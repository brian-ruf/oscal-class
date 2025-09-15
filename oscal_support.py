import os
from loguru import logger
import uuid
from time import sleep
from typing import Any, Optional
from common import helper 
from common import database
from common import network
from output import *
import asyncio

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
async def setup_support(support_file= "./support/support.oscal"):
    debug(f"Setting up support file: {support_file}")
    
    support = await OSCAL_support.create(support_file)
    cycle = 0
    while not support.ready:
        debug("Waiting for support object to be ready...")
        if support.db_state != "unknown":
            debug(f"Support file status {support.db_state}")
            break
        cycle += 1
        if cycle > 20:
            error(f"Support object took too long to be ready.({support.db_state})")
            break
        sleep(0.25)
    if not support.ready:
        error("Support object is not ready.")
    else:
        debug("Support file is ready.")

    return support

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class OSCAL_support:
    def __init__(self, db_conn, db_type="sqlite3"):
        self.ready      = False     # Is the support capability available?
        self.db_conn    = db_conn   # The support database connection string or path and filename 
        self.db_type    = db_type   # The support database type (sqlite3, mysql, postgresql, mssql, etc.)
        self.db_state   = "unknown" # The state of the support database (unknown, not-present, empty, populated)
        self.versions   = {}        # Supported OSCAL versions available within the support database, and support references
        self.extensions = {}        # Supported OSCAL extensions available within the support database, and support references
        self.backend    = None      # If working within an application, this is the backend object
        self.also_files = False     # If True, also save support files directly to the file system. 
                                    #    Files are always saved to the database.

        self.db = database.Database(self.db_type, self.db_conn)
        debug("Support: __init__")

    # -------------------------------------------------------------------------
    async def async_init(self):
        debug("Support: async_init")
        self.ready = await self.startup()

    # -------------------------------------------------------------------------
    @classmethod
    async def create(cls, db_conn, db_type="sqlite3"):
        """Async factory method to create and initialize OSCAL_support"""
        debug("Support: create")
        self = cls(db_conn, db_type)
        # if self.db is not None:
        #     self.ready = await self.startup()
        if self.db is not None:
            await self.async_init()
        else:
            error("Unable to create support database object.")
            self.ready = False

        return self

    # -------------------------------------------------------------------------
    async def startup(self, check_for_updates=False, refresh_all=False):
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
        debug("Support: startup")
        status = False

        if not self.db_state or self.db_state == "unknown": 
            # status = await self.__check_for_tables()
            status = await self.db.check_for_tables(OSCAL_SUPPORT_TABLES)

            debug(f"Support database tables check status: {status}")

            if status: # Tables exist
                # TODO: Check database structure against current
                #       structure and modify fields as needed.
                status = await self.__load_versions()
                if status:
                    self.db_state = "populated"
                    self.ready = True
                else:
                    self.db_state = "empty"
            else:
                error("Unable to initiate OSCAL support capability. Exiting.")
                self.ready = False

        if self.db_state == "empty":
            status = await self.__get_oscal_versions()

            if status:
                self.db_state = "populated"
                self.ready = True
            else:
                error("Unable to update OSCAL support capability. Exiting.")
                self.ready = False
       
        return status

    # -------------------------------------------------------------------------
    async def update(self, fetch="latest", backend=None):
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
                    status = await self.__clear_oscal_versions()
                case "latest":
                    self.__status_messages("Checking for new OSCAL versions...")
                    status = True
                case _:
                    if fetch.startswith("v"):
                        self.__status_messages(f"Updating specific version: {fetch}")
                        status = await self.__clear_oscal_version(fetch)
                    else:
                        error(f"Invalid update directive: {fetch}")
                        status = False
            
            if status:
                # Get OSCAL versions with periodic status updates
                status = await self.__get_oscal_versions(fetch)
            
            # Final reload of versions
            await self.__load_versions()
            
            self.__status_messages("Update process completed.")
            
        except Exception as e:
            error(f"Error during update: {e}")
            self.__status_messages(f"Error during update: {str(e)}", "error")
            status = False
            
        return status

    # -------------------------------------------------------------------------
    async def asset(self, oscal_version, model_name, asset_type):
        """
        Returns the asset for the specified OSCAL version and model name.
        Args:
            oscal_version (str): The OSCAL version (e.g., "v1.0.0").
            model_name (str): The OSCAL model name (e.g., "system-security-plan").
            asset_type (str): The type of asset to retrieve (e.g., "xml-schema", "json-schema").
        Returns:
            The asset content if found, None otherwise.
        """
        status = False
        filecache_uuid = None
        asset = None

        if oscal_version in self.versions:
            query = f"SELECT filecache_uuid FROM oscal_support WHERE version = '{oscal_version}' and model = '{model_name}' and type = '{asset_type}'"
            results = await self.db.query(query)
            if results is not None:
                filecache_uuid = results[0].get("filecache_uuid", None)
                # debug(f"Found filecache UUID {filecache_uuid} for {oscal_version} and {model_name}.")
                debug(f"Found filecache UUID {filecache_uuid} for {oscal_version} and {model_name}.")
                # Check if the filecache UUID is valid
                if filecache_uuid:
                    # Get the asset from the filecache
                    asset = helper.normalize_content(await self.db.retrieve_file(filecache_uuid))
                else:
                    error(f"Unable to find asset for {oscal_version} and {model_name}.")
            else:
                error(f"Unable to find asset for {oscal_version} and {model_name}.")
        else:
            error(f"OSCAL version {oscal_version} is either not valid or not supported.")

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
    async def enumerate_models(self, version):
        """
        Enumerate the supported models for a given OSCAL version.
        Args:
            version (str): The OSCAL version to enumerate models for (e.g., "v1.0.0").
        Returns:
            list: A list of model names supported for the specified OSCAL version.
            If the version is not found, an empty list is returned.
        """
        models = []

        if version in self.versions:
            query = f"SELECT DISTINCT model FROM oscal_support WHERE version = '{version}' and type = 'xml-schema' and model != 'complete'"
            results = await self.db.query(query)
            if results is not None:
                # debug(f"Found {len(results)} models for version {version}.")
                # debug(f"Models: {results}")
                for entry in results:
                    models.append(entry.get("model", ""))

        return models

    # -------------------------------------------------------------------------
    async def add_asset(self, oscal_version, model_name, asset_type, content, filename=None):
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
        debug(f"Add asset {model_name} ({asset_type}) for version {oscal_version}.")
        if isinstance(content, str):
            # If content is a string, convert it to bytes
            content = content.encode('utf-8')
            status = True  # Content is now in bytes
        elif isinstance(content, bytes):
            status = True  # Content is already in bytes
        else:
            error(f"Content for {model_name} ({asset_type}) must be bytes or a string. Received type: {type(content)}")
        # Check if the version is valid

        if status and self.is_valid_version(oscal_version):
            status = True
        else:
            error(f"OSCAL version {oscal_version} is not valid or supported.")
            status = False

        if status:
            filecache_uuid = None
            attributes = {}
            attributes["filename"] = filename if filename else f"{model_name}_{asset_type}"
            attributes["original_location"] = ""
            attributes["mime_type"] = "application/octet-stream"
            attributes["file_type"] = asset_type
            attributes["acquired"] = helper.oscal_date_time_with_timezone()


            # Check if the asset already exists
            query = f"SELECT filecache_uuid FROM oscal_support WHERE version = '{oscal_version}' and model = '{model_name}' and type = '{asset_type}'"
            results = await self.db.query(query)
            if results is not None and len(results) > 0:
                filecache_uuid = results[0].get("filecache_uuid", None)
                if filecache_uuid:
                    debug(f"Asset {model_name} ({asset_type}) for version {oscal_version} already exists with UUID {filecache_uuid}.")
            else:
                debug(f"No existing asset found for {model_name} ({asset_type}) for version {oscal_version}. Proceeding to insert.")

            if filecache_uuid:
                # If the asset already exists, update it
                debug(f"Updating existing asset {model_name} ({asset_type}) for version {oscal_version} with UUID {filecache_uuid}.")

                # Cache the file content
                if await self.db.cache_file(content, filecache_uuid, attributes):
                    status = True
                    info(f"Updated asset {model_name} ({asset_type}) for version {oscal_version}.")
                else:
                    error(f"Failed to cache updated file for {model_name} ({asset_type}) for version {oscal_version}.")
            else:
                debug(f"Adding new asset {model_name} ({asset_type}) for version {oscal_version} with UUID {filecache_uuid}.")
                filecache_uuid = str(uuid.uuid4())

                # Cache the file content
                if await self.db.cache_file(content, filecache_uuid, attributes):
                    status = True
                    await self.db.insert("oscal_support", {
                        "version": oscal_version,
                        "model": model_name,
                        "type": asset_type,
                        "filecache_uuid": filecache_uuid
                    })

                    info(f"Added asset {model_name} ({asset_type}) for version {oscal_version}.")
                else:
                    error(f"Failed to cache file for {model_name} ({asset_type}) for version {oscal_version}.")

        return status

    # -------------------------------------------------------------------------
    def is_valid_version(self, version):
        """
        Check if the specified OSCAL version is valid and supported.
        Args:
            version (str): The OSCAL version to check (e.g., "v1.0.0").
        Returns:
            bool: True if the version is valid and supported, False otherwise.
        """
        return version in self.versions

    # -------------------------------------------------------------------------
    async def __load_versions(self):     
        """
        Load supported OSCAL versions and support references into memory.
        """
        status = False

        debug("Loading OSCAL versions into memory.")
        query = "SELECT * FROM oscal_versions ORDER BY released DESC"
        results = await self.db.query(query)
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
    async def __get_oscal_versions(self, fetch="latest"):
        """Pulls OSCAL version information and support files from GitHub and loads it into the database."""
        status = True
        OSCAL_versions = []
        fetch_all = (fetch == "all")
        fetch_latest = (fetch == "latest")
        fetch_one = (fetch.startswith("v"))
        
        self.__status_messages("Fetching OSCAL release informaiton from GitHub...")
        
        # Add small delay to allow UI updates
        await asyncio.sleep(0)
        
        repo_releases = await network.async_api_get(GitHub_API_root + "/repos/" + OSCAL_repo + "/releases")
        self.__status_messages("Fetching OSCAL release information from GitHub...done.")

        if repo_releases is not None:
            total_releases = len(repo_releases)
            
            self.__status_messages(f"Found {total_releases} releases in the OSCAL GitHub repository.")
            for idx, entry in enumerate(repo_releases, 1):
                self.__status_messages(f"Inspecting release {idx} of {total_releases}...")
                # Yield control periodically
                if idx % 2 == 0:  # More frequent yields
                    await asyncio.sleep(0)
                
                if not entry.get("draft", False):
                    oscal_version = entry.get("tag_name", "").lower()
                    self.__status_messages(f"Found non-draft OSCAL Version {oscal_version}...")
                    if (oscal_version not in DEFAULT_EXCLUDE_VERSIONS):
                        self.__status_messages(f"Found non-excluded OSCAL Version {oscal_version}") 
                        
                        ok_to_continue = (fetch_all or 
                                        (fetch_latest and oscal_version not in self.versions) or
                                        (fetch_one and oscal_version == fetch))

                        if ok_to_continue:
                            self.__status_messages(f"Processing {oscal_version} release...")
                            release_date = entry.get("published_at", "0000-00-00T00:00:00Z")
                            release_name = entry.get("name", "")
                            github_location = f"{OSCAL_Release_URL}/{oscal_version}" 
                            documentation_location = f"{OSCAL_documentation}/{oscal_version}" 
                            await self.__clear_oscal_version(oscal_version)
                            
                            # Split up the database operations to allow more UI updates
                            await asyncio.sleep(0)
                            
                            info(f"Learning {oscal_version}, released {release_date} ...")
                            if await self.db.insert("oscal_versions", {
                                "version": oscal_version,
                                "released": release_date,
                                "title": release_name,
                                "github_location": github_location,
                                "documentation_location": documentation_location,
                                "acquired": helper.oscal_date_time_with_timezone()
                            }):
                                OSCAL_versions.append(oscal_version)
                                if "assets" in entry:
                                    # Process assets in chunks
                                    await self.__get_support_files(oscal_version, entry["assets"])
                            else:
                                error(f"Unable to insert OSCAL version {oscal_version} into support database.")
                        else:
                            self.__status_messages(f"Skipping {oscal_version} release.")
                    else:
                        self.__status_messages(f"Skipping excluded OSCAL Version {oscal_version}...")
                
                # Add small delay after processing each version
                await asyncio.sleep(0)
        else:
            error("Unable to fetch release information from GitHub.") 
            status = False

        if status:
            self.__status_messages("OSCAL version information loaded successfully.")
            self.__status_messages(f"Learned {len(OSCAL_versions)} OSCAL versions.")
            self.__status_messages(f"OSCAL versions: {', '.join(OSCAL_versions)}")

        return status

    # -------------------------------------------------------------------------
    async def __get_support_files(self, version, assets):
        """Modified to use async network operations and process in chunks"""
        status = False
        chunk_size = 3  # Process assets in chunks of 3
        
        # Split assets into chunks
        for i in range(0, len(assets), chunk_size):
            chunk = assets[i:i + chunk_size]
            tasks = []
            
            for asset in chunk:
                asset_name = asset.get("name", "")
                for pattern in SUPPORT_FILE_PATTERNS:
                    if pattern in asset_name:
                        tasks.append(self.__process_single_asset(version, asset, pattern))
            
            # Process chunk of assets concurrently
            if tasks:
                await asyncio.gather(*tasks)
                # Allow UI update after each chunk
                await asyncio.sleep(0)
        
        status = True
        return status

    # -------------------------------------------------------------------------
    async def __process_single_asset(self, version, asset, pattern):
        """Helper method to process a single asset"""
        status = False
        asset_name = asset.get("name", "")
        asset_URL = asset.get("browser_download_url", "")
        model_name = asset_name.replace("oscal_", "").replace(pattern, "")

        # Special case for SSP and POAM
        if model_name == "ssp": model_name = "system-security-plan"
        if model_name == "poam": model_name = "plan-of-action-and-milestones"
        
        uuid_value = str(uuid.uuid4())
        
        self.__status_messages(f"Downloading {asset_name}...")
        
        # Perform database inserts
        await self.db.insert("oscal_support", {
            "version": version,
            "model": model_name,
            "type": SUPPORT_FILE_PATTERNS[pattern],
            "filecache_uuid": uuid_value
        })
        
        # Download file content asynchronously
        content = await network.async_download_file(asset_URL, asset_name)

        if content:
            attributes = {
                "filename": asset_name,
                "original_location": asset_URL,
                "mime_type": "application/octet-stream",
                "file_type": SUPPORT_FILE_PATTERNS[pattern],
                "acquired": helper.oscal_date_time_with_timezone()
            }
            await self.db.cache_file(content, uuid_value, attributes)
            self.__status_messages(f"Downloaded [{version}] {asset_name}")
        else:
            self.__status_messages(f"Failed to download {asset_name}", "error")

    # -------------------------------------------------------------------------
    async def __clear_oscal_version(self, version):
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

        status = await self.db.db_execute(sql_commands)

        if status: 
            info(f"Successfully deleted support information for version {version}")
        else:
            error(f"Unable to deleted support information for version {version}")

        return status
    
    # -------------------------------------------------------------------------
    async def __clear_oscal_versions(self):
        """
        Clear all support content for all OSCAL versions.
        """
        status = False
        if self.versions:
            for version in self.versions:
                status = await self.__clear_oscal_version(version)
                self.__status_messages(f"Clearing support content for version {version}")
                if not status:
                    break
        else:
            status = True
        return status

    # -------------------------------------------------------------------------
    async def export_support_files(self, export_path="./support_files"):
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
            debug(f"Export path expanded to: {export_path}")

            status = lfs.chkdir(export_path, make_if_not_present=True)
            if status:
                debug(f"OSCAL support files present. Exporting support files to {export_path}...")

                for version in self.versions:
                    version_path = os.path.join(export_path, version)
                    if lfs.chkdir(version_path, make_if_not_present=True):
                        debug(f"Exporting support files for version {version} to {version_path}...")


                        # Query all records for this version from oscal_support table
                        query = f"SELECT * FROM oscal_support WHERE version = '{version}'"
                        support_records = await self.db.query(query)
                        
                        if support_records:
                            for record in support_records:
                                model = record.get('model', '')
                                asset_type = record.get('type', '')
                                filecache_uuid = record.get('filecache_uuid', '')
                                filename = await self.db.retrieve_file_name(filecache_uuid)
                                if filename:
                                    filename = os.path.join(version_path, filename)
                                    try:
                                        content = await self.db.retrieve_file(filecache_uuid)
                                        if content is not None:
                                            content = helper.normalize_content(content)
                                            status = lfs.putfile(filename, content)
                                            if status:
                                                debug(f"Exported {model} ({asset_type}) to {filename}.")
                                            else:
                                                error(f"Failed to write asset to {filename}.")
                                        else:
                                            error(f"No content found for UUID {filecache_uuid}.")
                                    except Exception as e:
                                        error(f"Failed to write asset to {filename}: {e}")
                                        status = False
                                else:
                                    error(f"Asset not found for {model} ({asset_type}) in version {version}.")
                    else:
                        error(f"Unable to create or access version directory: {version_path}")
                        status = False
            else:
                error(f"Unable to create or access export directory: {export_path}")
                status = False
        else:
            error("No OSCAL versions available to export.")
            status = False

        return status
    # -------------------------------------------------------------------------
    def __status_messages(self, status="", level="info"):
        """Enhanced status message handling"""
        if self.backend is not None:
            self.backend.status_update(status, level)
        info(status)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':
    print("The OSCAL Support Class is intended to be part of a larger application.")
