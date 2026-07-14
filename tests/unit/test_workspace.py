"""
Unit tests for oscal_workspace.Workspace.

Covers:
    Core:
        - registry injection: documents load under the workspace's own registry
        - shared roots: opening the same source twice returns the same object
        - isolation: the same source in two workspaces yields different objects
        - document tracking, close / close_all
        - new() creates and tracks a document
        - project metadata (title, remarks, extensible attributes)
    Save / load:
        - round-trips project metadata
        - round-trips documents (roots + imports) with content and state
        - rehydrated import tree is self-contained (child content present, no refetch)
        - save requires a path
"""
import os

import pytest

from oscal import OSCAL, Workspace, Catalog, Profile
from oscal.oscal_content import ImportState, ContentState, use_actor


_IMPORTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test-data", "xml", "imports",
)
_PROFILE = os.path.join(_IMPORTS, "test_profile_direct.xml")


# ===========================================================================
# Core
# ===========================================================================
class TestInjectionAndSharing:

    def test_document_bound_to_workspace_registry(self):
        ws = Workspace(title="A")
        doc = ws.open(_PROFILE)
        assert doc._registry is ws.registry
        assert doc._workspace is ws

    def test_import_loaded_under_workspace_registry(self):
        ws = Workspace()
        prof = ws.open(_PROFILE)
        cat = prof.import_list[0]["object"]
        assert cat._registry is ws.registry     # child injected too
        assert len(ws.registry) >= 1

    def test_reopen_same_source_returns_same_object(self):
        ws = Workspace()
        assert ws.open(_PROFILE) is ws.open(_PROFILE)

    def test_isolation_across_workspaces(self):
        wsA, wsB = Workspace(), Workspace()
        assert wsA.open(_PROFILE) is not wsB.open(_PROFILE)


class TestTracking:

    def test_documents_lists_open_roots(self):
        ws = Workspace()
        ws.open(_PROFILE)
        assert [d.model for d in ws.documents] == ["profile"]

    def test_close_removes_document(self):
        ws = Workspace()
        doc = ws.open(_PROFILE)
        ws.close(doc)
        assert ws.documents == []

    def test_reopen_after_close_is_fresh(self):
        ws = Workspace()
        d1 = ws.open(_PROFILE)
        ws.close(d1)
        d2 = ws.open(_PROFILE)
        assert d2 is not d1

    def test_close_all(self):
        ws = Workspace()
        ws.open(_PROFILE)
        ws.close_all()
        assert ws.documents == []

    def test_new_creates_and_tracks(self):
        ws = Workspace()
        cat = ws.new(Catalog, "My Catalog")
        assert cat.model == "catalog"
        assert cat in ws.documents
        assert cat._registry is ws.registry


class TestMetadata:

    def test_metadata_fields(self):
        ws = Workspace(title="Proj", path="/tmp/p.db")
        ws.remarks = "note"
        ws.attributes["client"] = "acme"
        assert ws.title == "Proj"
        assert ws.path == "/tmp/p.db"
        assert ws.remarks == "note"
        assert ws.attributes == {"client": "acme"}


# ===========================================================================
# Save / load
# ===========================================================================
class TestSaveLoad:

    @pytest.fixture
    def saved(self, tmp_path):
        path = str(tmp_path / "project.oscalws")
        ws = Workspace(title="Round Trip", path=path)
        ws.remarks = "a note"
        ws.attributes["k"] = "v"
        ws.open(_PROFILE)
        ws.save()
        return path

    def test_save_creates_file(self, saved):
        assert os.path.exists(saved)

    def test_save_requires_path(self):
        ws = Workspace()
        with pytest.raises(ValueError):
            ws.save()

    def test_metadata_round_trips(self, saved):
        ws = Workspace.load(saved)
        assert ws.title == "Round Trip"
        assert ws.remarks == "a note"
        assert ws.attributes == {"k": "v"}

    def test_documents_round_trip(self, saved):
        ws = Workspace.load(saved)
        assert [d.model for d in ws.documents] == ["profile"]

    def test_document_state_preserved(self, saved):
        ws = Workspace.load(saved)
        prof = ws.documents[0]
        assert prof.is_valid
        assert prof.title == "Import Resolution Test Profile (Direct)"

    def test_import_status_preserved(self, saved):
        ws = Workspace.load(saved)
        prof = ws.documents[0]
        assert prof.import_list[0]["status"] == ImportState.READY

    def test_child_rehydrated_self_contained(self, saved):
        """The imported catalog's content is restored from the project file itself."""
        ws = Workspace.load(saved)
        prof = ws.documents[0]
        child = prof.import_list[0]["object"]
        assert child is not None
        assert child.model == "catalog"
        assert child._dict is not None            # content present, no refetch needed

    def test_import_tree_rebuilt(self, saved):
        ws = Workspace.load(saved)
        prof = ws.documents[0]
        assert len(prof.import_tree["imports"]) == 1


# ===========================================================================
# Typed instances
# ===========================================================================
class TestTypedInstances:

    def test_factory_returns_typed(self):
        cat = OSCAL.load(os.path.join(_IMPORTS, "test_catalog.xml"))
        assert isinstance(cat, Catalog)
        prof = OSCAL.load(_PROFILE)
        assert isinstance(prof, Profile)

    def test_imported_child_is_typed(self):
        prof = OSCAL.load(_PROFILE)
        assert isinstance(prof.import_list[0]["object"], Catalog)

    def test_workspace_open_returns_typed(self):
        ws = Workspace()
        assert isinstance(ws.open(_PROFILE), Profile)

    def test_reloaded_document_is_typed(self, tmp_path):
        path = str(tmp_path / "p.oscalws")
        ws = Workspace(path=path)
        ws.open(_PROFILE)
        ws.save()
        ws2 = Workspace.load(path)
        assert isinstance(ws2.documents[0], Profile)


# ===========================================================================
# Derived-state persistence
# ===========================================================================
class TestStatePersistence:

    @pytest.fixture
    def reloaded(self, tmp_path):
        path = str(tmp_path / "p.oscalws")
        ws = Workspace(path=path)
        ws.open(_PROFILE)
        ws.save()
        return Workspace.load(path)

    def test_validation_status_persisted(self, reloaded):
        prof = reloaded.documents[0]
        # would be all-None if recomputed-not-restored; persisted as the real results
        assert prof.validation_status["structure"] is True
        assert all(v is True for v in prof.validation_status.values())

    def test_profile_resolution_state_persisted(self, reloaded):
        from oscal.oscal_controls import ResolutionStatus
        prof = reloaded.documents[0]
        assert prof.resolution_status == ResolutionStatus.UNRESOLVED

    def test_export_import_state_roundtrip(self):
        cat = OSCAL.load(os.path.join(_IMPORTS, "test_catalog.xml"))
        state = cat._export_state()
        assert "validation_status" in state and "is_unsaved" in state
        other = OSCAL.load(os.path.join(_IMPORTS, "test_catalog.xml"))
        other.validation_status = {}
        other._import_state(state)
        assert other.validation_status == cat.validation_status


# ===========================================================================
# In-memory write locks (multi-view)
# ===========================================================================
class TestWriteLocks:

    @pytest.fixture
    def ws_doc(self):
        ws = Workspace()
        return ws, ws.open(_PROFILE)

    def test_unlocked_is_editable(self, ws_doc):
        ws, doc = ws_doc
        assert doc.is_read_only is False
        assert ws.is_locked(doc) is False

    def test_holder_can_mutate(self, ws_doc):
        ws, doc = ws_doc
        with ws.as_actor("A"):
            assert ws.lock(doc) is True
            assert ws.lock_holder(doc) == "A"
            assert doc.put("metadata/title", "by A") is True

    def test_other_actor_sees_read_only(self, ws_doc):
        ws, doc = ws_doc
        with ws.as_actor("A"):
            ws.lock(doc)
        with ws.as_actor("B"):
            assert doc.is_read_only is True
            assert doc.put("metadata/title", "by B") is False

    def test_other_actor_cannot_acquire(self, ws_doc):
        ws, doc = ws_doc
        with ws.as_actor("A"):
            ws.lock(doc)
        with ws.as_actor("B"):
            assert ws.lock(doc) is False

    def test_no_actor_context_blocked_when_locked(self, ws_doc):
        ws, doc = ws_doc
        with ws.as_actor("A"):
            ws.lock(doc)
        assert doc.is_read_only is True          # unattributed caller can't override a lock

    def test_release_reenables_others(self, ws_doc):
        ws, doc = ws_doc
        with ws.as_actor("A"):
            ws.lock(doc)
            ws.unlock(doc)
        with ws.as_actor("B"):
            assert doc.put("metadata/title", "by B") is True

    def test_other_actor_cannot_release(self, ws_doc):
        ws, doc = ws_doc
        with ws.as_actor("A"):
            ws.lock(doc)
        with ws.as_actor("B"):
            assert ws.unlock(doc) is False
            assert ws.lock_holder(doc) == "A"

    def test_lock_requires_actor(self, ws_doc):
        ws, doc = ws_doc
        with pytest.raises(ValueError):
            ws.lock(doc)                          # no actor context, none passed

    def test_close_releases_lock(self, ws_doc):
        ws, doc = ws_doc
        with ws.as_actor("A"):
            ws.lock(doc)
        ws.close(doc)
        assert ws.is_locked(doc) is False

    def test_non_workspace_doc_unaffected(self):
        solo = OSCAL.load(os.path.join(_IMPORTS, "test_catalog.xml"))
        assert solo.is_read_only is False
        with use_actor("anyone"):
            assert solo.is_read_only is False     # no workspace -> no lock enforcement
