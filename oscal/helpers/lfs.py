# Local File System (LFS) Functions
# File and folder-level interactions
import os
import errno
import sys
import json
import logging
from pathlib import Path
from .helper import normalize_content, datetime_string

logger = logging.getLogger(__name__)
# from datetime import datetime

# =============================================================================
#  --- PyInstaller Interactions  ---
# =============================================================================
def resource_path(relative_path: str) -> str:
    """ Get absolute path to resource, works for dev and for PyInstaller """
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

# =============================================================================
#  --- LFS File Level Interactions ---
# =============================================================================

def zip_file(file_to_zip: str, zip_filename: str, overwrite: bool = False, recurse: bool = False) -> bool:
    """
    Creates a zip archive containing files and/or directories.

    Args:
        file_to_zip (str): The path to the file, directory, or pattern you want to zip.
                          Can be a single file, directory path, or glob pattern (e.g., "*.py").
        zip_filename (str): The desired name for the output zip file (e.g., "archive.zip").
        overwrite (bool): If True, overwrites existing zip file. If False, returns error if file exists.
        recurse (bool): If True and file_to_zip is a directory, recursively includes subdirectories.
                       If False, only includes files directly in the specified directory.
    """
    import zipfile
    import glob
    status = False

    try:

        if overwrite:
            if os.path.exists(zip_filename):
                os.remove(zip_filename)
                logger.info(f"'{zip_filename}' exists. Removing.")
        else:
            if os.path.exists(zip_filename):
                logger.error(f"Zip file '{zip_filename}' already exists. Overwrite is blocked.")
                return

        # Collect all files to be zipped
        files_to_zip = []
        
        # Check if it's a pattern (contains wildcards)
        if '*' in file_to_zip or '?' in file_to_zip:
            files_to_zip = glob.glob(file_to_zip, recursive=recurse)
        elif os.path.isfile(file_to_zip):
            # Single file
            files_to_zip = [file_to_zip]
        elif os.path.isdir(file_to_zip):
            # Directory
            if recurse:
                # Recursively walk the directory
                for root, dirs, files in os.walk(file_to_zip):
                    for file in files:
                        files_to_zip.append(os.path.join(root, file))
            else:
                # Only files in the directory (no subdirectories)
                for item in os.listdir(file_to_zip):
                    item_path = os.path.join(file_to_zip, item)
                    if os.path.isfile(item_path):
                        files_to_zip.append(item_path)
        else:
            logger.error(f"Path '{file_to_zip}' not found or is not a valid file/directory/pattern.")
            return False

        if not files_to_zip:
            logger.warning(f"No files found matching '{file_to_zip}'.")
            return False

        # Use a 'with' statement to ensure the zip file is closed automatically
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in files_to_zip:
                # Determine the archive name (relative path within zip)
                if os.path.isdir(file_to_zip):
                    # For directories, preserve relative structure
                    arcname = os.path.relpath(file_path, file_to_zip)
                else:
                    # For files and patterns, use just the filename
                    arcname = os.path.basename(file_path)
                
                zipf.write(file_path, arcname=arcname)
                logger.debug(f"Added {file_path} as {arcname}")
        
        logger.debug(f"Successfully created {zip_filename} containing {len(files_to_zip)} file(s)")
        status = True
    except FileNotFoundError:
        logger.error(f"Error: The file '{file_to_zip}' was not found.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")

    return status

# -----------------------------------------------------------------------------
def putfile(file_name: str, content: str) -> bool:
    """
    Saves content to a file.
    Returns True if successful. 
    Returns False otherwise.
    """
    logger.debug(f"Saving {file_name}")
    status = False
    try:
        with open(file_name, mode='w') as file:
            file.write(content)
            file.close()
        status = True
    except Exception as error:
        logger.error(f"{type(error).__name__} saving {file_name}: {str(error)}")

    return status

# -----------------------------------------------------------------------------
def get_json(file_name: str) -> dict:
    """
    Opens a JSON file and returns the contents as a dict object.
    If an error occurs, an empty dict is returned.
    """
    logger.debug(f"Getting JSON file {file_name}")
    json_data = {}
    try:
        with open(file_name, mode='r') as file:
            json_data = json.load(file)
            file.close()
    except Exception as error:
        logger.error(f"{type(error).__name__} getting JSON file {file_name}: {str(error)}")

    return json_data
# -----------------------------------------------------------------------------
def save_json(data: dict, file_name: str) -> bool:
    """
    Saves a dict object as a JSON file.
    Returns True if successful. 
    Returns False otherwise.
    """
    status = False
    try:
        with open(file_name, mode='w') as file:
            json.dump(data, file, indent=2)
            file.close()
        status = True
    except Exception as error:
        logger.error(f"{type(error).__name__} saving {file_name}: {str(error)}")

    return status
# -----------------------------------------------------------------------------
def chkfile(path: str) -> bool:
    """
    Checks for the existence of a file.
    Returns:
    True if found
    False if not found or an error occurs
    """
    status = False
    try:
        if os.path.isfile(path):
            logger.debug(f"Found {path}")
            status = True
    except OSError as exc:
        if exc.errno == errno.EACCES:
            logger.error(f"Permission denied checking {path}")
        else:
            logger.error(f"Unhandled OS error {str(exc)}")
    except Exception as error:
        logger.error(f"{type(error).__name__} while checking {path}: {str(error)}")

    return status

# -----------------------------------------------------------------------------
def getfile(file_name: str, normalize: bool = True, mode: str = "rb") -> str:
    """
    Opens a file and returns the contents. Handles errors gracefully.
    If no optional parameters are passed, this will open the file as binary
    and convert the content to string.
    - file_name (str): the file to open.
    - normalize (bool): 
       - If True, always convert the contents to string. 
       - if False, will return the binary contents.
    - mode: indicates the file mode to use when opening

    Returns:
    If the file is not found, or an error occurs, an empty string is returned.
    Otherwise, the file content is returned in accordance with the "normalize"
    boolean parameter above.
    """
    logger.debug(f"Getting {file_name}")
    status = False
    ret_value = ""
    if chkfile(file_name):
        try:
            file = open(file_name, mode)
            ret_value = file.read()
            if normalize:
                ret_value = normalize_content(ret_value)
            status = True
            file.close()
        except OSError:
            logger.error(f"Could not open/read {file_name}")
        except Exception:
            logger.error(f"Unrecognized error while getting {file_name}")
    else:
        logger.debug(f"Unable to find {file_name}")
    
    if status:
        logger.debug(f"Success getting {file_name}")
    else:
        ret_value = ""

    return ret_value

# -----------------------------------------------------------------------------
def getjsonfile(file_name: str) -> dict:
    """
    Gets a JSON file from the local file system

    Returns a dict object
    
    Returns an empty dict object if the file does not exist or 
       an error occurs.
    """
    json_results = {}
    json_string = getfile(file_name)
    try:
        if json_string:
            json_results = json.loads(json_string)
    except Exception as error:
        logger.error(f"{type(error).__name__} error deserializing {file_name}: { str(error)}")
    return json_results

# -----------------------------------------------------------------------------
def backup_file(filename: str) -> bool:
    """
    Creates a backup of the specified file by duplicating it in its current
       location and appending the date and time to the root file name.
       Example: 
          /appdata/config.json is copied to
          /appdata/config_2025-01-05--13-59-59.json
    """
    status = False
    if chkfile(filename):
        p = Path(filename)
        newname = f"{p.stem}_{datetime_string()}{p.suffix}"
        logger.debug(f"Renaming [{filename}] to [{newname}]")
        p.rename(Path(p.parent, newname ))
        status = True
    else:
        logger.warning(f"File not found: {filename}")
    return status

# =============================================================================
#  --- LFS Folder Level Interactions ---
# =============================================================================

def get_app_location() -> str:
    """Returns the location of the application."""
    # This must be determined differently if running a pyinstaller executable
    #    as compared to running a Python script with the Python executable.
    # See discussion here:
    # https://stackoverflow.com/questions/404744/determining-application-path-in-a-python-exe-generated-by-pyinstaller
    application_path = ""
    # Detect if running within a PyInstaller created applcation
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable) # Need to use this for one-file EXE
        # application_path = sys._MEIPASS # Recommended, but does not work with one-file EXE
    else: # native Python script
        application_path = os.path.dirname(os.path.abspath(sys.argv[0]))

    # logger.debug(f"APP LOCATION {application_path}")
    return application_path

# -----------------------------------------------------------------------------
def chkdir(path: str, make_if_not_present: bool = False) -> bool:
    """
    Checks for the existence of a folder.

    Returns:
    - True if the path already exists
    - True if the path didn't exist, but was created successfully
    - False otherwise
    """
    # logger.debug(f"Checking for {path}")
    status = False
    try:
        if  os.path.exists(path):
            status = True
            # logger.debug(f"Found {path}")
        else:
            # logger.debug(f"Not Found: {path}")
            if make_if_not_present:
                logger.debug(f"Making {path}")
                status = mkdir(path)
    except OSError as exc:
        if exc.errno == errno.EACCES:
            logger.error(f"Permission denied checking {path} ")
        else:
            logger.error(f"Unhandled OS error {str(exc)}")
    except Exception as error:
        logger.error(f"{type(error).__name__} while checking {path}: {str(error)}")

    # print ("Status: " + out.iif(status, "TRUE", "FALSE"))
    return status


# -----------------------------------------------------------------------------
def mkdir(path: str) -> bool:
    """
    Creates any folders needed to ensure the specified path exists.
    Returns:
    - True if the path already exists
    - True if the path didn't exist, but was created successfully
    - False otherwise
    """
    status = False
    if  chkdir(path):
        status = True
    else:
        logger.debug(f"Making {path}")    
        try:
            os.makedirs(path)
            status = True
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                # If the error is only because the folder already exists, we can ignore. 
                status = True
            else:
                if exc.errno == errno.EACCES:
                    logger.error(f"Permission denied for {path}")
                elif exc.errno == errno.ENOSPC:
                    logger.error(f"No space left for {path}")
                elif exc.errno == errno.EROFS:
                    logger.error(f"Read-only file system for {path}")
                else:
                    logger.error(f"Unhandled OS error {str(exc)}")
        except Exception as error:
            logger.error(f"Error making folder {path} ({type(error).__name__}): {str(error)}")

    return status

# =============================================================================
#  --- MAIN: Only runs if the module is executed stand-alone. ---
# =============================================================================
if __name__ == '__main__':
    print("Local File System (LFS) Library. Not intended to be run as a stand-alone file.")
