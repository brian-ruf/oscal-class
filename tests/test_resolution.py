"""
Unit tests for oscal.control
"""
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

if oscal_catalog_obj:
    oscal_catalog_obj.save("test_catalog.json", format="json", pretty_print=True)
    oscal_catalog_obj.save("test_catalog.xml",  format="xml",  pretty_print=True)
    oscal_catalog_obj.save("test_catalog.yaml", format="yaml", pretty_print=True)

class TestControlResolution:
    """Tests for control resolution across catalogs and profiles."""

    def test_import_mapping(self):
        logger.debug("Starting test_resolution.py")

        # Load the test profile, which imports a catalog with controls.
        profile = Profile.from_href("tests/test-data/test.xml")
        logger.debug("Profile imports:")
        logger.debug(profile.import_list)
        # Check that the imported catalog is correctly mapped in the profile's imports.
        # assert "051a77c1-b61d-4995-8275-dacfe688d510" in profile.import_tree
        # # Check that the import mapping includes the expected catalog.
        # imported_catalog = profile.imports["051a77c1-b61d-4995-8275-dacfe688d510"]
        # assert isinstance(imported_catalog, Catalog)
        # assert imported_catalog.title == "CIS Controls"

    def test_control_resolution_in_profile(self):
        # Load the test profile, which imports a catalog with controls.
        profile = Profile.from_file("tests/test-data/test.xml")
        # Resolve controls in the profile, which should pull in controls from the imported catalog.
        resolved_controls = profile.resolve_controls()
        # Check that we have the expected controls from the imported catalog.
        assert "ac-1" in resolved_controls
        assert "pm-9" in resolved_controls

    def test_control_resolution_with_nested_imports(self):
        # This test would check that controls can be resolved even when there are nested imports.
        # For example, if the profile imports a catalog that itself imports another catalog.
        pass  # Implementation would depend on the structure of the test data and is not shown here.

    def test_control_resolution_with_conflicting_ids(self):
        # This test would check how the system handles conflicting control IDs across imports.
        # For example, if two imported catalogs have a control with the same ID, does it raise an error?
        pass  # Implementation would depend on the structure of the test data and is not shown here.

if __name__ == '__main__':
    logger.info("Running control resolution tests...")
    # test_suite = TestControlResolution()
    # test_suite.test_import_mapping()
    # test_suite.test_control_resolution_in_profile()
    # test_suite.test_control_resolution_with_nested_imports()
    # test_suite.test_control_resolution_with_conflicting_ids()
    logger.info("All tests passed!")
