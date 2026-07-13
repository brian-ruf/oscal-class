"""
Unit tests for cyclic import detection.

Loading a document resolves its imports and cascades down the whole tree
(validate() calls resolve_imports()). Two guards keep that safe:
    - the object registry holds a file loaded via multiple branches once (diamond),
    - an import that resolves back to an ancestor still being resolved is flagged
      ImportState.CYCLIC and not loaded (cycle).

Covers:
    - ImportState.CYCLIC enum member
    - self-import -> CYCLIC
    - A <-> B two-node cycle: forward edge READY, back edge CYCLIC
    - CYCLIC entry carries the ancestor href but no object (not loaded)
    - CYCLIC is non-blocking (state reaches IMPORTS_RESOLVED; not failed/unresolved)
    - diamonds are NOT cyclic: shared descendant stays READY and is one object
"""
import os

import pytest

from oscal import OSCAL
from oscal.oscal_content import ImportState, ContentState
from oscal.oscal_registry import get_registry


_IMPORTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test-data", "xml", "imports",
)


def _path(name):
    return os.path.join(_IMPORTS, name)


@pytest.fixture(autouse=True)
def _clean_registry():
    get_registry().clear()
    yield
    get_registry().clear()


def _statuses(doc):
    return [e["status"] for e in doc.import_list]


# ===========================================================================
# Enum
# ===========================================================================
class TestEnum:

    def test_cyclic_member_exists(self):
        assert ImportState.CYCLIC is not None

    def test_cyclic_value(self):
        assert ImportState.CYCLIC.value == "cyclic"


# ===========================================================================
# Self cycle
# ===========================================================================
class TestSelfCycle:

    def test_self_import_marked_cyclic(self):
        s = OSCAL.load(_path("cyclic_self.xml"))
        assert s.import_list[0]["status"] == ImportState.CYCLIC

    def test_document_still_valid(self):
        s = OSCAL.load(_path("cyclic_self.xml"))
        assert s.is_valid is True

    def test_cyclic_entry_has_no_object(self):
        s = OSCAL.load(_path("cyclic_self.xml"))
        assert s.import_list[0]["object"] is None

    def test_cyclic_entry_records_ancestor_href(self):
        s = OSCAL.load(_path("cyclic_self.xml"))
        assert s.import_list[0]["href_valid"].endswith("cyclic_self.xml")


# ===========================================================================
# Two-node cycle A <-> B
# ===========================================================================
class TestTwoNodeCycle:

    def test_forward_edge_ready(self):
        a = OSCAL.load(_path("cyclic_a.xml"))
        assert a.import_list[0]["status"] == ImportState.READY

    def test_back_edge_cyclic(self):
        a = OSCAL.load(_path("cyclic_a.xml"))
        b = a.import_list[0]["object"]
        assert b.import_list[0]["status"] == ImportState.CYCLIC

    def test_both_documents_valid(self):
        a = OSCAL.load(_path("cyclic_a.xml"))
        b = a.import_list[0]["object"]
        assert a.is_valid and b.is_valid

    def test_terminates(self):
        """The point of the guard: loading completes without runaway."""
        a = OSCAL.load(_path("cyclic_a.xml"))
        assert isinstance(a.import_list, list)


# ===========================================================================
# CYCLIC is non-blocking
# ===========================================================================
class TestCyclicNonBlocking:

    def test_not_in_failed_imports(self):
        s = OSCAL.load(_path("cyclic_self.xml"))
        assert s.failed_imports == []

    def test_not_in_unresolved_imports(self):
        s = OSCAL.load(_path("cyclic_self.xml"))
        assert s.unresolved_imports == []

    def test_reaches_imports_resolved(self):
        s = OSCAL.load(_path("cyclic_self.xml"))
        assert s.content_state == ContentState.IMPORTS_RESOLVED


# ===========================================================================
# Diamonds are not cyclic
# ===========================================================================
class TestDiamondNotCyclic:

    def test_no_cyclic_status_anywhere(self):
        top = OSCAL.load(_path("diamond_top.xml"))
        left = top.import_list[0]["object"]
        right = top.import_list[1]["object"]
        for doc in (top, left, right):
            assert ImportState.CYCLIC not in _statuses(doc)

    def test_shared_descendant_is_one_object(self):
        top = OSCAL.load(_path("diamond_top.xml"))
        left = top.import_list[0]["object"]
        right = top.import_list[1]["object"]
        assert left.import_list[0]["object"] is right.import_list[0]["object"]

    def test_branches_ready(self):
        top = OSCAL.load(_path("diamond_top.xml"))
        assert top.import_list[0]["status"] == ImportState.READY
        assert top.import_list[1]["status"] == ImportState.READY
