"""
Unit tests for the refresh cascade triggered by add_import / remove_import.

Changing a document's first-level imports must refresh the affected part of the
import tree and reset any model-specific derived state. For a Profile that means:
    * the import_tree reflects the new/removed import,
    * a previously resolved catalog is discarded,
    * resolution_status returns to UNRESOLVED,
    * the controls_tree is rebuilt (no longer marked stale).

Documents are built from real import fixtures so resolution is exercised end to end,
and JSON round-trip fidelity of the added import + resource is asserted.
"""
import os

import pytest

from oscal import OSCAL, Catalog
from oscal.oscal_controls import ResolutionStatus


_HERE        = os.path.dirname(os.path.abspath(__file__))
_IMPORTS_DIR = os.path.join(_HERE, "..", "test-data", "xml", "imports")
_CATALOG_A   = os.path.join(_IMPORTS_DIR, "test_catalog.xml")
_PROFILE_B   = os.path.join(_IMPORTS_DIR, "test_profile_direct.xml")


def _profile_xml(*hrefs: str) -> str:
    imports = "\n  ".join(
        f'<import href="{h}"><include-all/></import>' for h in hrefs
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-0000000000f0">
  <metadata>
    <title>Import Refresh Test Profile</title>
    <last-modified>2026-06-06T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  {imports}
  <merge><combine method="keep"/><as-is>true</as-is></merge>
</profile>"""


@pytest.fixture
def resolved_profile():
    """A profile that resolves to a non-empty catalog."""
    p = OSCAL.loads(_profile_xml(_CATALOG_A))
    assert p.resolve() == ResolutionStatus.RESOLVED
    assert p.catalog is not None
    return p


# ===========================================================================
# Adding an import invalidates a resolved catalog
# ===========================================================================
class TestAddRefresh:

    def test_add_discards_resolved_catalog(self, resolved_profile):
        resolved_profile.add_import(_PROFILE_B)
        assert resolved_profile.catalog is None

    def test_add_resets_resolution_status(self, resolved_profile):
        resolved_profile.add_import(_PROFILE_B)
        assert resolved_profile.resolution_status == ResolutionStatus.UNRESOLVED

    def test_add_rebuilds_controls_tree(self, resolved_profile):
        resolved_profile.add_import(_PROFILE_B)
        # controls_tree was rebuilt eagerly, not left stale
        assert resolved_profile._tree_dirty is False

    def test_add_updates_import_tree(self, resolved_profile):
        before = len(resolved_profile.import_tree["imports"])
        resolved_profile.add_import(_PROFILE_B)
        assert len(resolved_profile.import_tree["imports"]) == before + 1


# ===========================================================================
# Removing an import invalidates a resolved catalog
# ===========================================================================
class TestRemoveRefresh:

    @pytest.fixture
    def resolved_two(self):
        p = OSCAL.loads(_profile_xml(_CATALOG_A, _PROFILE_B))
        assert p.resolve() == ResolutionStatus.RESOLVED
        return p

    def test_remove_discards_resolved_catalog(self, resolved_two):
        resolved_two.remove_import(_PROFILE_B)
        assert resolved_two.catalog is None

    def test_remove_resets_resolution_status(self, resolved_two):
        resolved_two.remove_import(_PROFILE_B)
        assert resolved_two.resolution_status == ResolutionStatus.UNRESOLVED

    def test_remove_updates_import_tree(self, resolved_two):
        before = len(resolved_two.import_tree["imports"])
        resolved_two.remove_import(_PROFILE_B)
        assert len(resolved_two.import_tree["imports"]) == before - 1

    def test_remove_rebuilds_controls_tree(self, resolved_two):
        resolved_two.remove_import(_PROFILE_B)
        assert resolved_two._tree_dirty is False


# ===========================================================================
# Non-derived models: base refresh runs without error and updates the tree
# ===========================================================================
class TestBaseRefresh:

    def test_component_definition_tree_reflects_add(self):
        from oscal.oscal_support import get_support
        cd = OSCAL.loads(get_support().load_file("component-definition.xml", as_bytes=False))
        cd.add_import("some/catalog.xml")
        hrefs = [n.get("href_original") for n in cd.import_tree["imports"]]
        assert any(h and h.startswith("#") for h in hrefs)


# ===========================================================================
# JSON round-trip fidelity of the added import + its resource
# ===========================================================================
class TestRoundTrip:

    def test_added_import_and_resource_round_trip(self):
        p = OSCAL.loads(_profile_xml(_CATALOG_A))
        r = p.add_import("baselines/added.json", title="Added Baseline", version="1.1.0")
        out = p.dumps(format="json")
        assert r.resource["uuid"] in out          # import fragment + resource uuid
        assert "Added Baseline" in out
        assert "application/json" in out
        assert "1.1.0" in out
        # reload and confirm the import survived
        reloaded = OSCAL.loads(out)
        entries = reloaded._import_entries()
        assert any(str(e.get("href", "")).lstrip("#") == r.resource["uuid"] for e in entries)
