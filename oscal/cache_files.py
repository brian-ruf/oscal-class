"""
Functions to facilitate caching and retrieval of OSCAL support files.
"""
from datetime import datetime 
import time 
import json
from dotenv import load_dotenv # Library: python-dotenv -- allows handling of .env files
import sys
from pathlib import Path
from loguru import logger


CACHE_LOCATION = "cache"

# Global Datastore 
DATASTORE = "local-cache" # If no path provided, this is created  
                          # on the local file system in the home folder.
GITHUB_ACCESS_TOKEN = "" # An access token for GitHub. Not required for public repos and less than 60 API calls/hour
                         #   Required for private repos or when exceeding 60 API calls/hour (allows up to 5,000 API calls per hour as of Jan 2024)

LOCAL_AVAILABLE = True # if true, useing the local file system is allowed.
GITHUB_AVAILABLE = True # if true, using support files directly from the NIST OSCAL GitHub repo is allowd when caching the support files is not possible.
CACHE_ON_START = False # If true, the application will populate or update its cache folder for all support files across all valid versions of OSCAL

INITIALIZED = False # If true, the support file acquisition mechanism has been successfully initialized.


OUT_ERROR = 4
OUT_WARNING = 2
OUT_MESSAGE = 1
OUT_DEBUG = 0

class OSCAL_Support_Content:
    def __init__(self, oscal_version, oscal_model, oscal_service):
        # status = False
        self.oscal_model = oscal_model
        self.oscal_version = valid_version(oscal_version) # if OSCAL version is valid, returns a normalized representation.
        self.oscal_service = oscal_service # "xml-validation", "json-validation", "xml-to-json", "json-to-xml"
        self.file_name = ""
        self.acquired = False
        # self.xslt = None
        # self.schema = None
        self.content = None
        self.in_memory = False
        self.in_datastore = False
        self.in_github = False
        self.url = ""
        self.log = []

    def __str__(self):
        json_out = {}
        json_out["oscal-model"] = self.oscal_model
        json_out["oscal-version"] = self.oscal_version
        json_out["oscal_service"] = self.oscal_service
        json_out["file-name"] = self.file_name
        json_out["file-acquired"] = self.acquired
        if "validation" in self.oscal_service: json_out["service-type"] = "validation"
        if       "-to-" in self.oscal_service: json_out["service-type"] = "conversion"

    # ==========================================================================
    #  --- Helper Methods ---
    # ==========================================================================
    def logging(self, message, title="", details="", output_type=OUT_DEBUG):
        temp_obj = {}
        temp_obj["timestamp"] = str(datetime.now().strftime(out.TIMESTAMP_FORMAT))
        temp_obj["title"] = title
        temp_obj["INFO"] = message
        temp_obj["details"] = details
        self.log.append(temp_obj)

        if DEBUG_MODE and output_type==OUT_DEBUG: 
            out.output(message)
            out.output(details)
        elif output_type==OUT_ERROR: 
            out.output(message, "ERROR")
            out.output(details, "ERROR")
        elif output_type==OUT_WARNING: 
            out.output(message, "WARNING")
        elif output_type==OUT_MESSAGE: 
            out.output(message, "INFO")


# Initializes the mechanism for acquiring and caching support files
# If force_update is True, this will cache all available OSCAL support 
#     files for all OSCAL versions found in the NIST OSCAL repository.
#
# If wait_for_availability is True, this will try every five seconds
#     until at least one support file acquisition option is available. 
#
# RETURNS: 
#   - True if at least one acquisition option is available.
#   - False otherwise.
#
# May be re-run at any point, such as if caching locations change, or
#     to force a refresh of the cache. 
# 
def support_startup(force_update=False, wait_for_availability=False):
    global INITIALIZED
    out.output("Initializing Support File Acquisition Mechanism")
    INITIALIZED = False
    first_try = True
    while (first_try or (not INITIALIZED and wait_for_availability)):
        if first_try: first_try = False
        INITIALIZED = __caching_setup(force_update)
        if not INITIALIZED:
            if wait_for_availability:
                out.output("Unable to startup cleanly. Will retry in 5 seconds!", "ERROR")
                time.sleep(5)
                # TODO: Check for CTRL-C during sleep and exit if detected
                # sys.exit() 
            else:
                out.output("Unable to startup cleanly. Support files are not available!", "ERROR")

    return INITIALIZED

# Accepts an OSCAL version number, OSCAL model, and a pre-defined OSCAL "need" request
# This routine determines if the OSCAL version is valid and if the "need" request is recognized
# It then attempts to locate the appropriate support file for the OSCAL version, model, and need
# It looks in memory first, in local cached storage second and finally on the NIST OSCAL GitHub repo last
#     (this is fastest to slowest retrieval)
# As it has to fall back to slower retrieval types it duplicates the file to the faster sources
# It also returns the support file content as soon as it is found.
# Returns:
#   - status: True if successful, False otherwise
#   - file_name: The support file name or an empty string if unsuccessful
#   - content: The support file content itself or an empty string if unsuccessful 
#
def get_support_file(oscal_version, oscal_model, oscal_service):
    global GitHub_raw_root, GitHub_repo
    global GITHUB_AVAILABLE, LOCAL_AVAILABLE

    if not INITIALIZED:
        support_startup()

    if oscal_model == "system-security-plan": oscal_model = "ssp" # NIST deviated from the file naming convention for SSP only

    support_obj = OSCAL_Support_Content(oscal_version, oscal_model, oscal_service)
    folder_available = False

    if support_obj.oscal_version != "":
        match support_obj.oscal_service:
            case "metaschema-root":
                support_obj.file_name = support_obj.oscal_version + "/" + "oscal_complete_metaschema_RESOLVED.xml"
            case "metaschema-file":
                support_obj.file_name = support_obj.oscal_version + "/" + oscal_model
            case "json-validation" | "yaml-validation":
                support_obj.file_name = support_obj.oscal_version + "/" + "oscal_" + support_obj.oscal_model + "_schema.json"
            case "xml-validation":
                support_obj.file_name = support_obj.oscal_version + "/" + "oscal_" + support_obj.oscal_model + "_schema.xsd"
            case "xml-to-json":
                support_obj.file_name = support_obj.oscal_version + "/" + "oscal_" + support_obj.oscal_model + "_xml-to-json-converter.xsl"
            case "json-to-xml":
                support_obj.file_name = support_obj.oscal_version + "/" + "oscal_" + support_obj.oscal_model + "_json-to-xml-converter.xsl"
            case "json-to-yaml", "yaml-to-json", "xml-to-yaml", "yaml-to-xml":
                out.output("Converting between JSON and YAML does not require an OSCAL support file. If converting between YAML and XML, convert to JSON first!", "WARNING")
            case _:
                out.output(support_obj.oscal_service + " is an unrecognized or unhandled OSCAL service.", "WARNING")

        # If we have a valid support file name to retrieve, proceed.
        if support_obj.file_name != "":
            out.output("Fetching " + support_obj.file_name)

            # Is support file in memory?
            if support_obj.file_name in SUPPORT_FILES:
                support_obj = SUPPORT_FILES[support_obj.file_name]
                support_obj.in_memory = True
                support_obj.acquired = True
                # content = SUPPORT_FILES[support_obj.file_name]
                out.output("Found support file in memory")
            else: 
                out.output("Support file not found in memory")

            # If not found in memory, If local cache exists, look there.
            if not support_obj.acquired:
                # First make sure the local cache has a folder for the requested OSCAL version 
                if LOCAL_AVAILABLE:
                    out.output("Trying datastore")
                    folder_available = check_dir(support_obj.oscal_version)
                    if folder_available:
                        out.output("found version folder")
                        # The version folder exists. Now check to see if the file exists.
                        if check_file(support_obj.file_name):
                            support_obj.in_datastore, support_obj.content =  get_file(support_obj.file_name)
                            if support_obj.in_datastore and len(support_obj.content) > 0:
                                out.output("Found file in datastore")
                                support_obj.acquired = True
                                support_obj.in_datastore = True
                        else:
                            out.output("Did not find support file in folder.")
                    else:
                        # There is no folder for the OSCAL version. That means there is definitely no file.
                        # Let's at least create the folder for the version. In case we have files to store there later.
                        folder_available = create_location(support_obj.oscal_version) 
                        out.output("Creating folder for " + support_obj.oscal_version)
                else: 
                    out.output("Support file not found locally")

            out.output(misc.iif(support_obj.acquired, "acquired", "NOT acquired") + " " + misc.iif(support_obj.in_memory, "in memory", "NOT in memory") + " " + misc.iif(support_obj.in_datastore, "in datastore", "NOT in datastore"))
            # if support file not found in memory or local storage, (and if github is available), get file from github
            if GITHUB_AVAILABLE and (not support_obj.acquired):
                out.output("Trying to fetch file directly from GitHub")

                # https://github.com/[owner]/[repo]/releases/download/[tag]/[folder(s)/file]
                support_obj.url = GitHub_release_root + "/" + GitHub_repo + "/releases/download/" + support_obj.file_name
                support_obj.in_github, support_obj.content = network_io.fetch_file(support_obj.url)
                if support_obj.in_github:
                    support_obj.logging("File downloaded from GitHub", "", "Support file size: " + str(len(support_obj.content)))

                    if folder_available: # Folder is only available if datastore is available. So we don't need to also check for the datastore
                        out.output("Storing file in cache: " + support_obj.file_name)
                        store_file(support_obj.file_name, support_obj.content) # The result of the save is irrelevant. We have what we need. This is only to make things faster next time.
                else:
                    out.output("Support file not found in GitHub! (" + support_obj.url + ")", "", "", OUT_ERROR, "WARNING")
        else:
            out.output("Unrecognized or unhandled need. (" + support_obj.oscal_service + ") Could not identify necessary support file.", "WARNING")
    else:
        out.output(support_obj.oscal_version + " is not a recognized OSCAL version. Checking for new version.", "WARNING")
        # TODO: Requery OSCAL repo for new releases. If new release found, update releases file locally and try the above again.

    if support_obj.in_memory or support_obj.in_datastore or support_obj.in_github:
        support_obj.acquired = True
        return support_obj # True, support_obj.file_name, content
    else:
        support_obj.acquired = False
        out.output("Support file not found! (" + support_obj.file_name + ")", "ERROR")
        return None # False, "", ""
    
# Accepts a version_query
# If found, returns the normalized OSCAL version string representation.
# Otherwise returns an empty string
# NOTE: NIST uses Semantic Versioning (https://semver.org/) for all OSCAL versions
def valid_version(version_query):
    global OSCAL_releases
    # messages_out("VERSION QUERY: " + version_query)
    found = False

    # normalize to lower case and ensure there is a starting "v" (ie '1.0.1' becomes 'v1.0.1')
    version_query = version_query.lower()
    if version_query[0] != "v":
        version_query = "v" + version_query

    for entry in OSCAL_releases:
        if entry == version_query:
            found = True
            break 

    if found:
        out.output(version_query + " is a valid OSCAL version.", "INFO")
    else:
        out.output(version_query + " unrecognized OSCAL version.", "INFO")
        version_query = ""

    return version_query

# returns a simple JSON list of recognized OSCAL versions
def all_valid_versions():
    global OSCAL_releases
    json_str = '{"supported-oscal-versions" : ['

    first = True
    for entry in OSCAL_releases:
        if not first:
            json_str = json_str + ', '
        else:
            first = False
        
        json_str = json_str + '"' + entry + '"'

    json_str = json_str + '] }\n' 
    out.output("Recognized OSCAL version: " + json_str, "INFO")

    return json_str

# Gets a file from the appropriate datastore
# Will return an empty string if unsuccessful
def get_file(file_name):
    out.output("get_file: " + file_name)
    global LOCAL_AVAILABLE
    global DATASTORE
    status = False
    ret_value = ""
    file_name = DATASTORE + "/" + file_name

    if LOCAL_AVAILABLE:
        out.output("Fetching " + file_name + " from local file system.", "INFO")
        status, ret_value = lfs.getfile(CACHE_LOCATION + "/" + file_name)
    else:
        out.output("Attempt to load file with no local caching available.", "WARNING")
        status = False
        ret_value = ""

    if status:
        status = len(ret_value) > 0
        ret_value = misc.normalize_content(ret_value)
        out.output(misc.iif(status, "Support file acquired from datastore.", "Could not fetch support file from datastore."))

    return status, ret_value 

# Saves a file in the appropriate datastore
def store_file(file_name, content):
    global LOCAL_AVAILABLE, DATASTORE
    status = False

    file_name = DATASTORE + "/" + file_name

    if LOCAL_AVAILABLE:
        out.output("Saving " + file_name + " to local file system.", "INFO")
        status = lfs.putfile(CACHE_LOCATION + "/" + file_name, content)

    else:
        out.output("Attempt to save file with no local caching available.", "WARNING")
        status = False

    return status 

# Gets the list of NIST published OSCAL releases and populates global variable OSCAL_releases.
# If this fails, it blocks the use of the NIST GitHub repo as a source of support files.
# - returns an array of strings containing the version numbers
# - returns an empty array if unsuccessful
# STATES: 
# - Don't Pre-cache (CACHE_ON_START=False)
#   - Use local cache if available
#   - If local cache is not available, acquire release info from GitHub repo as needed
# - Pre-cache (CACHE_ON_START=True)
#   - Get release information directly from GitHub.
#   - Fall back to local cache if GitHub not available
# Optional parameter "update":
# - "" (empty): do not update anything
# - "release-only": update only the releases information
# - "update": update the releases info and fetch any new support files
# - "refresh": update the releases info and re-fetch all support files

def get_oscal_release_information(force_update = False):
    global OSCAL_releases_json
    global OSCAL_releases
    global GITHUB_AVAILABLE, LOCAL_AVAILABLE
    global CACHE_ON_START
    global GitHub_API_root, GitHub_repo
    status = False

    need_release_info_from_github = (CACHE_ON_START or force_update)
    have_release_info_from_github = False
    have_release_info_from_cache = False

    out.output("Fetching release metadata.", "INFO")

    if not need_release_info_from_github:
        out.output("Getting release information from cache")
        # If GitHub isn't available, and the cache does not have a local copy
        # of OSCAL_releases.json, there is no way to continue. 
        status, ret = get_file("OSCAL_releases.json")
        # multi_line_out(json.dumps(ret), "OSCAL Releases")
        if status and len(ret) >0: # OSCAL_releases_json != "":
            out.output("Found release information in cache")
            OSCAL_releases_json = json.loads(ret)
            have_release_info_from_cache = True
        else:
            need_release_info_from_github = True
            out.output("The local cache is missing the necessary OSCAL release information. Will attempt to fetch from GitHub.", "ERROR")

    if need_release_info_from_github:
        out.output("Fetching release information from NIST OSCAL GitHub Repository")
        status, ret = network_io.api_get(GitHub_API_root + "/repos/" + GitHub_repo + "/releases", jsonhead)
        if status:
            out.output("API call successful")
            out.output("Releases file size: " + str(len(ret.content)))
            GITHUB_AVAILABLE = True
            OSCAL_releases_json = ret.json()
            have_release_info_from_github = True
            need_release_info_from_github = False
        elif CACHE_ON_START and not need_release_info_from_github:
            out.output("Unable to fetch release information from GitHub.", "WARNING") 

    if have_release_info_from_github and (LOCAL_AVAILABLE):
        out.output("Caching OSCAL release information locally.", "INFO")
        if store_file("OSCAL_releases.json", json.dumps(OSCAL_releases_json)):
            out.output("Successfully cached OSCAL_releases.json", "INFO")
        else:
            out.output("Unable to cache OSCAL_releases.json - attempting to continue.", "WARNING")

    if have_release_info_from_cache or have_release_info_from_github:
        for entry in OSCAL_releases_json:
            out.processing("#")
            if GitHub_Release_Field_Name in entry:
                oscal_version = entry[GitHub_Release_Field_Name].lower()
                if not oscal_version in OSCAL_version_exclude_list:
                    OSCAL_releases.append(entry[GitHub_Release_Field_Name].lower())
    else:
        out.output("GitHub and Local File System are both unavailable. Can't continue.", "ERROR")

    temp = ""
    for item in OSCAL_releases: temp += ": " + item 

    out.output("OSCAL Version(s) Identified" + temp)
    return OSCAL_releases

# -----------------------------------------------------------------------------
def list_relevant_assets(oscal_version):
    print("LISTING RELEVANT ASSETS FOR " + oscal_version)

    for entry in OSCAL_releases_json:
        if GitHub_Release_Field_Name in entry:
            if oscal_version == entry[GitHub_Release_Field_Name].lower():
                # enumerate all assets looking for relevant assets
                for asset in entry["assets"]:
                    for pattern in support_file_patterns:
                        if pattern in asset["name"]:
                            print(asset["name"], asset["browser_download_url"] ) 

def dump_OSCAL_version_info(oscal_version):
    print("JSON OUTPUT FOR " + oscal_version)

    for entry in OSCAL_releases_json:
        if GitHub_Release_Field_Name in entry:
            if oscal_version == entry[GitHub_Release_Field_Name].lower():
                # enumerate all assets looking for relevant assets
                print(json.dumps(entry, indent=3))
                break
    return entry

# Populate Cache - 
# Enumerate each OSCAL version found at the NIST OSCAL Repository
# For each version, check for cached support files
# Download any missing support files
# Optional arguments:
# - oscal_version: specifies only a single version of OSCAL to check/get cached copies
#                   defaults to "all", which will check all known OSCAL versions
# - overwrite: If true, forces clearing and re-downloading of support files for a specified
#                    OSCAL version (if oscal_version passed) or all OSCAL versions.
def populate_cache(oscal_version = "all", overwrite = False):
    local_version_list = []

    # if "all" versions specified, setup an array with all known OSCAL versions
    if oscal_version == "all":
        local_version_list = OSCAL_releases
    # if a single OSCAL version is specified, and it's recognized in the list of known OSCAL versions
    elif oscal_version in OSCAL_releases:
        # since we are using a for loop below, make add the one entry to the local_version_list array
        local_version_list.append(oscal_version)
    
    for local_version in local_version_list:
        check_cached_version(local_version, "all", overwrite)

# Accepts a path relative to the datastore location and determines
# whether or not the folder exists in the datastore
def check_dir(path):
    status = False
    if path[0] == "/":
        path = DATASTORE + path
    else:
        path = DATASTORE + "/" + path

    if LOCAL_AVAILABLE:
        status = lfs.chkdir(CACHE_LOCATION + "/" + path)
    return status

def check_file(file_path_and_name):
    status = False
    if file_path_and_name[0] == "/":
        file_path_and_name = DATASTORE + file_path_and_name
    else:
        file_path_and_name = DATASTORE + "/" + file_path_and_name
    
    return status

# check_cached_version
# 
def check_cached_version(oscal_version, model_name="all", overwrite=False):
    version_path = oscal_version
    status = False
    if check_dir(version_path):
        out.output("Version path exists at " + version_path, "INFO")
        status = True
    else:
        out.output("Creating " + version_path, "INFO")
        status = create_location(version_path)
    
    if status:
        out.output("Fetching support files", "INFO")
        release_counter = 0
        for entry in OSCAL_releases_json:
            file_counter = 0
            if GitHub_Release_Field_Name in entry:
                if oscal_version == entry[GitHub_Release_Field_Name].lower():
                    # enumerate all assets looking for relevant assets
                    for asset in entry["assets"]:
                        for pattern in support_file_patterns:
                            if model_name == "all":
                                final_pattern = pattern
                            else:
                                final_pattern = model_name + pattern
                            if final_pattern in asset["name"]:
                                file_path_and_name = version_path + "/" + asset["name"]
                                if check_file(file_path_and_name): 
                                    out.processing(".") # Exists. Skipping
                                else:
                                    cache_file(file_path_and_name, asset["browser_download_url"], overwrite)
                                    out.processing("+") # Does not exist. Caching
                                file_counter += 1 
                                if processing_limit > 0 and file_counter > processing_limit: break
            release_counter += 1
            if processing_limit > 0 and release_counter > processing_limit: break

# Downloads a file and saves it to the local cache
def cache_file(file_path_and_name, file_url, overwrite = False):
    status = False
    out.output("Fetching " + file_url, "INFO")
    status, support_file = network_io.fetch_file(file_url) 

    if status:
        out.output("Saving to " + file_path_and_name, "INFO")
        status = store_file(file_path_and_name, support_file)

    return status

# ============================
# Creates a folder on the cache host (local file system) 
def create_location(path):
    global LOCAL_AVAILABLE
    status = False

    path = DATASTORE + "/" + path

    if LOCAL_AVAILABLE:
        out.output("Creating " + path + " on local file system", "MESSAGES")
        status = lfs.mkdir(CACHE_LOCATION + "/" + path)
    else:
        out.output("Attempt to create folder when no local file system is available.")

    return status

# ----------------------
# Attempts to connect to a datastore.
# Checking access to the local file store if allowed.
def datastore_connect():
    global LOCAL_AVAILABLE, GITHUB_AVAILABLE
    status = False

    status = True
    if LOCAL_AVAILABLE: # local file system caching is allowed
        out.output("Will attempt to use local file system for caching.")
    elif GITHUB_AVAILABLE:
        out.output("Local caching unavailable. Will attempt to use support files directly from GitHub.", "WARNING")
    else:
        status = False

    return status

# ============================
# Once the datastore connection is valid, make sure the actual location is viable. 
def check_datastore_location():
    global DATASTORE, LOCAL_AVAILABLE, GITHUB_AVAILABLE
    datastore_found = False

    if LOCAL_AVAILABLE:
        out.output("Checking for '/" + DATASTORE + "' on local file system", "INFO")

        if not lfs.chkdir(CACHE_LOCATION + "/" + DATASTORE):
            LOCAL_AVAILABLE = lfs.mkdir(CACHE_LOCATION + "/" + DATASTORE)

    if not LOCAL_AVAILABLE:
        out.output("Unable to create '" + DATASTORE + "'. Caching disabled. Using GitHub Directly.", "WARNING")

# ============================
def __caching_setup(force_update = False):
    global LOCAL_AVAILABLE, GITHUB_AVAILABLE
    global CACHE_ON_START
    global DATASTORE

    out.output("- - - - - - - - - - [SUPPORT INITIALIZATION] - - - - - - - - - -", "INFO")
    out.output("Setting up cache and ensuring support file availability.", "INFO")
    # Look for a local .env file and load those environment variables if available
    load_dotenv()

    status = False

    LOCAL_AVAILABLE = True

    if force_update:
        CACHE_ON_START = True
    else:
        if misc.handle_environment_variables('CACHE_ON_START', verbose= False, error_only=False) == "yes":
            CACHE_ON_START = True
            out.output("CACHE_ON_START set to 'yes'. Will cache all support files if a cache location is available.", "INFO")
        else: 
            CACHE_ON_START = False

    GITHUB_API_TOKEN = misc.handle_environment_variables('GITHUB_API_TOKEN', verbose= False, error_only=False)

    DATASTORE = misc.handle_environment_variables("DATASTORE")
    if DATASTORE != "":
        temp = DATASTORE
        # convert backslashes to slashes
        # DATASTORE = DATASTORE.replace("\\", "/")
        # If no leading slash, add one. 
        # Local fs is always relative to the home folder, which will be prepended in that scenario. 
        if DATASTORE[0] == "/":
            DATASTORE = DATASTORE[1:] + DATASTORE[:2]
        if temp == DATASTORE:
            out.output("DATASTORE folder name specified as '" + temp + "'.", "INFO")
        else:
            out.output("DATASTORE folder name specified as '" + temp + "' and normalized to '" + DATASTORE + "'", "INFO")
    else:
        out.output("No DATASTORE value provided. Using 'local-cache'", "WARNING")
        DATASTORE = "local-cache"

    # Try local file system
    datastore_connect()

    # if local file system is vaible, verify/setup the cache folder
    if LOCAL_AVAILABLE:
        check_datastore_location()
    
    # Even if no data store is available, we still may be able to use GitHub directly
    # If this is successful, it gets the list of NIST published OSCAL releases and populates 
    #            the global variable OSCAL_releases.
    # If this fails, it blocks the use of the NIST GitHub repo as a source of support files.
    get_oscal_release_information()

    # If we have a datastore available and CACHE_ON_START was set to "yes", we need
    #    to populate the cache with all available support files from the NIST repo
    if (LOCAL_AVAILABLE) and CACHE_ON_START:
        populate_cache()

    # We need either direct GitHub access to operate.
    # If at least one is avaialable we can continue. Return True.
    # If none are available, setup failed. Return False.

    out.output("- - - - - - -  [SUPPORT INITIALIZATION COMPLETE] - - - - - - - -", "INFO")
    return (LOCAL_AVAILABLE or GITHUB_AVAILABLE)

# =============================================================================
#  --- MAIN: Only runs if the module is executed stand-alone. ---
# =============================================================================
if __name__ == '__main__':
    # Execute when the module is not initialized from an import statement.
    started = datetime.now()
    out.output("--- START ---", "INFO")

    # signal.signal(signal.SIGINT, signal_handler)
    # print('Press Ctrl+C')
    # signal.pause()

    support_startup()

    # if False: # CACHE_ON_START:
    #     if get_support_files(oscal_version, oscal_model):
    #         out.output("Support files successfully cached.", "INFO")
    #     else:
    #         out.output("Problem caching support files. Will use directly from GitHub as needed.", "WARNING")

    # list_relevant_assets("v1.0.0")
    # populate_cache()
    # dump_OSCAL_version_info("v1.0.0-rc2")

    out.output("Local FS: " + str(LOCAL_AVAILABLE) + ", GitHub: " + str(GITHUB_AVAILABLE), "INFO")

    runtime = datetime.now() - started
    out.output("--- END --- (" + str(runtime.total_seconds()) + " seconds)", "INFO")
