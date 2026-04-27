import sys

from oscal.oscal_support import configure_support
import os
import argparse
from loguru import logger
from ruf_common.lfs import zip_file
from pathlib import Path

logger.enable("oscal")
logger.remove()
logger.add(sys.stderr, level="INFO")

script_dir = Path(__file__).parent.resolve()

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Update OSCAL support assets.")
group = parser.add_mutually_exclusive_group()
group.add_argument("--new", action="store_true", help="Check for new releases (default)")
group.add_argument("--all", action="store_true", help="Refresh with all releases")
args = parser.parse_args()

# Determine update mode: "all" if --all is passed, otherwise "new" (default)
update_mode = "all" if args.all else "new"

logger.info("Starting support asset update process...")
logger.info("Current working directory: " + os.getcwd())

SUPPORT_DB_PATH = os.path.abspath(os.path.join(script_dir, "..", "support", "oscal_support.db"))
SUPPORT_ZIP_PATH = os.path.abspath(os.path.join(script_dir, "data", "oscal_support.zip"))

logger.info("Database absolute path: " + SUPPORT_DB_PATH)
logger.info(f"Update mode: {update_mode}")
support_obj = configure_support(db_path=SUPPORT_DB_PATH, init_mode="auto")


if support_obj.update(mode=update_mode):
    logger.info("Support assets updated successfully.")

    # Zip the updated support database for distribution
    if zip_file(SUPPORT_DB_PATH, SUPPORT_ZIP_PATH, overwrite=True):
        logger.info(f"Updated support database compressed and saved to {SUPPORT_ZIP_PATH}.")
    else:
        logger.error("Failed to compress the updated support database.")


else:
    logger.error("Failed to update support assets.")
