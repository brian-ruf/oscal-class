import sys
from loguru import logger

from oscal import OSCAL, Catalog, Profile
TEST_FILES_DIR = "tests/test-data"
TEST_DATA = f"{TEST_FILES_DIR}/json/FedRAMP_rev5_catalog_tailoring_profile.jso"

logger.enable("oscal")
logger.remove()
logger.add(
    sys.stdout,
    level="DEBUG",
    # filter="oscal.oscal_controls",
    colorize=True
)

def test_load_save():
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
        print(oscal_catalog_obj.serialize("xml", pretty_print=True))
        print("-" * 25 + " JSON " + "-" * 25)
        print(oscal_catalog_obj.serialize("json", pretty_print=True))
        print("-" * 25 + " YAML " + "-" * 25)
        print(oscal_catalog_obj.serialize("yaml", pretty_print=True))
        print("=" * 50)


        oscal_catalog_obj.save("test_catalog.json", format="json", pretty_print=True)
        oscal_catalog_obj.save("test_catalog.xml",  format="xml",  pretty_print=True)
        oscal_catalog_obj.save("test_catalog.yaml", format="yaml", pretty_print=True)
    else:
        logger.error("Failed to create OSCAL Catalog object for testing.")


    del oscal_catalog_obj


def test_load_url():
    url = "https://raw.githubusercontent.com/usnistgov/oscal-content/refs/heads/main/examples/ssp/json/oscal_leveraged-example_ssp-min.json"
    url = [{"href": TEST_DATA, "media-type": "application/oscal+json"}, {"href": "https://raw.githubusercontent.com/usnistgov/oscal-content/refs/heads/main/examples/ssp/json/oscal_leveraged-example_ssp-min.json", "media-type": "application/oscal+json"}]
    # url = [{"href": "./ssp.json", "media-type": "application/oscal+json"}]
    # url = {"href": "./ssp.json", "media-type": "application/oscal+json"}
    loaded_ssp = OSCAL.load(url)
    # if loaded_ssp is not None:
    #     print("=" * 25 + " LOADED SSP FROM URL " + "=" * 25)
    #     print(loaded_ssp.serialize("xml", pretty_print=True))
    #     print("=" * 50)
    #     print(loaded_ssp.serialize("json", pretty_print=True))
    #     print("=" * 50)
    #     print(loaded_ssp.serialize("yaml", pretty_print=True))
    #     print("=" * 50)
    # else:
    #     logger.error(f"Failed to load OSCAL Catalog from URL: {url}")
    del loaded_ssp

if __name__ == "__main__":
    # Run the test function
    # test_load_save()
    test_load_url()
