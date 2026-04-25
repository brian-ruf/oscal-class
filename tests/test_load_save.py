import sys
from loguru import logger

from oscal import Catalog, Profile
TEST_FILES_DIR = "tests/test-data"

logger.enable("oscal")
logger.remove()
logger.add(
    sys.stdout,
    level="DEBUG",
    # filter="oscal.oscal_controls",
    colorize=True
)

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
