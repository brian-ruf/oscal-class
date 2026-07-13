import sys
import os
import json
import logging

from oscal import OSCAL, Catalog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s - %(message)s",
)
logger = logging.getLogger(__name__)

TEST_FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test-data")

TEST_DATA = [f"{TEST_FILES_DIR}/sanitized_ssp_oscal.json"]



def test_load():
    for test_file in TEST_DATA:
        logger.info(f"Testing load() with file: {test_file}")
        obj = OSCAL.open(test_file)
        print(obj)

        if obj.is_valid:
            logger.info(f"Successfully loaded {test_file}")

        else:
            logger.error(f"Failed to load {test_file}")
            print (f"Validation report: {json.dumps(obj.validation_status, indent=2)}")
            print (f"Validation errors: {json.dumps(obj.validation_errors, indent=2)}")
        print("" + "=" * 25 + " LOAD RESULT " + "=" * 25)
        # if obj.imports_resolved:
        #     # print (f"Imports resolved: {len(obj.import_list)} import(s) found.")
        #     # print (f"Import tree resolved: {obj.import_tree}")
        #     # for entry in obj.import_list:
        #     #     child = entry.get("object")
        #     #     print(f"  Import [{entry['status']}]: {entry['href_original']}")
        #     #     if child:
        #     #         print(f"    → {child.model}: {child.title}")
        # elif obj.is_valid:
        #     print("No imports found.")
        # elif obj.is_acquired and not obj.is_valid:
        #     print("Content was acquired, but is not valid.") # not well formed, or not schema valid
        # elif not obj.is_acquired:
        #     print("Content was not successfully loaded.")


        print("-" * 50)


        # assert obj is not None, f"OSCAL.load() returned None for {test_file}"
        # assert obj.is_valid is True, f"OSCAL.load() returned is_valid=False for {test_file}"
        # assert obj.model != "", f"OSCAL.load() returned empty model string for {test_file}"
        # print("=" * 50)
        del obj

if __name__ == "__main__":
    # Run the test function
    # test_load_save()
    test_load()
