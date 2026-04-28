import sys
import os
from loguru import logger


from oscal import OSCAL, Catalog

TEST_FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test-data")

TEST_DATA = [f"{TEST_FILES_DIR}/bad_test.xml", 
             f"{TEST_FILES_DIR}/test.xml",
             f"{TEST_FILES_DIR}/json/FedRAMP_rev5_catalog_tailoring_profile.json",
             "https://raw.githubusercontent.com/OSCAL-Foundation/fedramp-resources/refs/heads/main/baselines/rev5/json/FedRAMP_rev5_LOW-baseline_profile.json"
             ]

def hold():
    oscal_catalog_obj = Catalog.new("Test Catalog", version="DRAFT-1.0", published="2026-03-02T00:00:00Z")

    oscal_catalog_obj.create_control_group("", "ac", "Access Control", 
                                        props=[{"name":"label", "value": "AC"}, 
                                                {"name":"sort-id", "value": "001"}])

    oscal_catalog_obj.create_control("ac", "ac-1", "Access Control Policy and Procedures",
                                        props=[{"name":"label", "value": "AC-1"}, 
                                                {"name":"sort-id", "value": "001-001"}],
                                                statements=["The organization develops, documents, and disseminates an access control policy that addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance."],
                                                )

    oscal_catalog_obj.create_control("ac", "ac-2", "Access Control Enforcement",
                                        props=[{"name":"label", "value": "AC-2"}, 
                                                {"name":"sort-id", "value": "001-002"}],
                                                statements=["The organization enforces access control policies through technical and administrative mechanisms."],
                                                )

    if oscal_catalog_obj is not None:
        print("=" * 25 + " SERIALIZATION OUTPUT " + "=" * 25)
        print("-" * 25 + " XML " + "-" * 25)
        print(oscal_catalog_obj.dumps("xml", pretty_print=True))
        print("-" * 25 + " JSON " + "-" * 25)
        print(oscal_catalog_obj.dumps("json", pretty_print=True))
        print("-" * 25 + " YAML " + "-" * 25)
        print(oscal_catalog_obj.dumps("yaml", pretty_print=True))
        print("=" * 50)


        oscal_catalog_obj.dump("test_catalog.json", format="json", pretty_print=True)
        oscal_catalog_obj.dump("test_catalog.xml",  format="xml",  pretty_print=True)
        oscal_catalog_obj.dump("test_catalog.yaml", format="yaml", pretty_print=True)
    else:
        logger.error("Failed to create OSCAL Catalog object for testing.")


    del oscal_catalog_obj



def test_load():
    for test_file in TEST_DATA:
        logger.info(f"Testing load() with file: {test_file}")
        obj = OSCAL.open(test_file)
        if obj:
            logger.info(f"Successfully loaded {test_file}")
        else:
            logger.error(f"Failed to load {test_file}")

        print("" + "=" * 25 + " LOAD RESULT " + "=" * 25)
        print(obj)
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
