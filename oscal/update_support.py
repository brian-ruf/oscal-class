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
group.add_argument("--new", action="store_true", help="Check for new releases (default)")
group.add_argument("--all", action="store_true", help="Refresh with all releases")
group.add_argument("--get-schemas", metavar="VERSION",
                   help="Download XML/JSON schema files; VERSION is 'all' or a specific tag (e.g. v1.2.2)")
args = parser.parse_args()

SUPPORT_DB_PATH  = os.path.abspath(os.path.join(script_dir, "..", "support", "oscal_support.db"))
SUPPORT_ZIP_PATH = os.path.abspath(os.path.join(script_dir, "data", "oscal_support.zip"))
SUPPORT_DIR      = os.path.abspath(os.path.join(script_dir, "..", "support"))

logger.info("Starting support asset update process...")
logger.info("Current working directory: " + os.getcwd())
logger.info("Database absolute path: " + SUPPORT_DB_PATH)

support_obj = configure_support(db_path=SUPPORT_DB_PATH, init_mode="auto")

if args.get_schemas:
    fetch_arg = args.get_schemas
    if fetch_arg != "all" and not fetch_arg.startswith("v"):
        logger.error(f"Invalid --get-schemas value '{fetch_arg}'. Use 'all' or a version tag like 'v1.2.2'.")
        sys.exit(1)
    logger.info(f"Schema download mode: {fetch_arg}")
    if support_obj.download_schemas(SUPPORT_DIR, fetch=fetch_arg):
        logger.info("Schema files downloaded successfully.")
    else:
        logger.error("Schema download failed.")

else:
    update_mode = "all" if args.all else "new"
    logger.info(f"Update mode: {update_mode}")

    if support_obj.update(mode=update_mode):
        logger.info("Support assets updated successfully.")

        if zip_file(SUPPORT_DB_PATH, SUPPORT_ZIP_PATH, overwrite=True):
            logger.info(f"Updated support database compressed and saved to {SUPPORT_ZIP_PATH}.")
        else:
            logger.error("Failed to compress the updated support database.")

    else:
        logger.error("Failed to update support assets.")
