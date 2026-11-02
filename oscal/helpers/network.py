import requests
import socket
import logging
from typing import Optional
from . import helper

logger = logging.getLogger(__name__)


def check_internet_connection() -> bool:
    try:
        # Try to connect to a reliable host
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False

def api_get(endpoint, http_headers={"Content-type": "application/json"}, timeout_seconds=10):
    """
        Calls a REST API and returns the response.
        endpoint: The full URL to the REST endpoint
        http_headers: optional headers to include in the request
            If not provided, this funciton requests a JSON response.
    """
    rest_ret: Optional[requests.Response] = None
    rest_ret = None
    try:
        rest_ret = requests.get(endpoint, headers=http_headers, timeout=timeout_seconds)

    except requests.exceptions.HTTPError as err:
        logger.error(f"HTTP Error: {type(err).__name__}: {str(err)}\n--for GET {endpoint}")
    except requests.exceptions.Timeout:
        logger.error(f"TIMEOUT Error: Waited {str(timeout_seconds)}\n--for GET {endpoint} .")
    except requests.exceptions.TooManyRedirects as err:
        logger.error(f"Too many redirects. {type(err).__name__}: {str(err)}\n--for GET {endpoint}")
    except requests.exceptions.RequestException as err:
        logger.error(f"Unrecognized request error {type(err).__name__}: {str(err)}\n--for GET {endpoint}")
    except Exception as err:
        logger.error(f"Unrecognized error {type(err).__name__}: {str(err)}\n--for GET {endpoint}")

    if rest_ret is not None:
        if rest_ret.status_code != 200:
            logger.error(f"HTTP Error: {str(rest_ret.status_code)} {rest_ret.text}\n--for GET {endpoint}")
        logger.debug(f"GET {endpoint} returned {rest_ret.status_code}")

    return rest_ret

def download_file(url, filename):
    """
    Downloads a file from a URL and saves it to the specified filename.
    """
    ret_value: str = ""
    try:
        response = requests.get(url)
        ret_value = helper.normalize_content(response.content)
        # with open(filename, "wb") as file:
        #     file.write(response.content)
    except requests.exceptions.RequestException as err:
        logger.error(f"Error downloading file: {str(err)}")
    except Exception as err:
        logger.error(f"Unrecognized error downloading file: {str(err)}")
        
    return ret_value

# =============================================================================
#  --- MAIN: Only runs if the module is executed stand-alone. ---
# =============================================================================
if __name__ == '__main__':
    print("Network Module. Not intended to be run as a stand-alone file.")
