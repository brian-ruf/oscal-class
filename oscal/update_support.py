from oscal.oscal_support_class import setup_support
import os
from loguru import logger
from ruf_common.lfs import zip_file

SUPPORT_DB_PATH = os.path.join("..", "support", "oscal_support.db")
SUPPORT_ZIP_PATH = os.path.join("data", "oscal_support.zip")

logger.info("Database absolute path: " + os.path.abspath(SUPPORT_DB_PATH))
supportObj = setup_support(SUPPORT_DB_PATH)


if supportObj.update("all"):
    logger.info("Support assets updated successfully.")

    # Zip the updated support database for distribution
    if zip_file(SUPPORT_DB_PATH, SUPPORT_ZIP_PATH, overwrite=True):
        logger.info(f"Updated support database compressed and saved to {SUPPORT_ZIP_PATH}.")
    else:
        logger.error("Failed to compress the updated support database.")


else:
    logger.error("Failed to update support assets.")
