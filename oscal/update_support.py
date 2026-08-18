"""
UPDATE SUPPORT ASSETS
This script updates the OSCAL support assets by downloading the latest versions of OSCAL schemas and related files from the official OSCAL GitHub repository. It can either check for new releases or refresh all

Parameters:
    --new: Check for new releases (default)
    --all: Refresh with all releases
    --version VERSION: Clear and re-fetch a specific release; 
        - VERSION is a specific version tag or 'all'. The leading `v` is required for version tags. Example: `--version v1.2.3`
        - '--version all' to re-fetch all releases (equivalent to `--all`)
    --save-files: Also emit parsed metaschema index files to the local file system (in addition to updating the database).

"""

import sys

from oscal.oscal_support import configure_support
import os
import argparse
import logging
from ruf_common.lfs import zip_file
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s - %(message)s",
)
# This module is an application entry point; surface the oscal library's INFO logs.
logging.getLogger("oscal").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

script_dir = Path(__file__).parent.resolve()

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Update OSCAL support assets.")
group = parser.add_mutually_exclusive_group()
group.add_argument("--new", action="store_true", help="Fetch any new releases (default)")
group.add_argument("--all", action="store_true", help="Clear and re-fetch all releases")
group.add_argument("--version", metavar="VERSION",
                   help="Clear and re-fetch a specific release; VERSION is a specific tag (e.g. v1.2.2)")
parser.add_argument("--save-files", action="store_true",
                    help="Also emit parsed metaschema index files to the local file system "
                         "(in addition to updating the database). Default: database only.")
args = parser.parse_args()

SUPPORT_DB_PATH  = os.path.abspath(os.path.join(script_dir, "..", "support", "oscal_support.db"))
SUPPORT_ZIP_PATH = os.path.abspath(os.path.join(script_dir, "data", "oscal_support.zip"))

logger.info("Starting support asset update process...")
logger.info("Current working directory: " + os.getcwd())
logger.info("Database absolute path: " + SUPPORT_DB_PATH)

support_obj = configure_support(db_path=SUPPORT_DB_PATH, init_mode="auto")

if args.version:
    # A specific release: "all" is an alias for --all; anything else must be a
    # version tag (leading 'v' required) to reach update()'s single-version path.
    if args.version == "all":
        update_mode = "all"
    elif args.version.startswith("v"):
        update_mode = args.version
    else:
        logger.error(f"Invalid --version value '{args.version}'. Use 'all' or a version tag like 'v1.2.2'.")
        sys.exit(1)
elif args.all:
    update_mode = "all"
else:
    update_mode = "new"

logger.info(f"Update mode: {update_mode}")
logger.info(f"Emit metaschema files to file system: {args.save_files}")

if support_obj.update(mode=update_mode, save_to_fs=args.save_files):
    logger.info("Support assets updated successfully.")

    if zip_file(SUPPORT_DB_PATH, SUPPORT_ZIP_PATH, overwrite=True):
        logger.info(f"Updated support database compressed and saved to {SUPPORT_ZIP_PATH}.")
    else:
        logger.error("Failed to compress the updated support database.")
        sys.exit(1)

else:
    logger.error("Failed to update support assets.")
    sys.exit(1)
