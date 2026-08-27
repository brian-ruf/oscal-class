"""
Unit tests for cardinality-aware add_import / remove_import across every model.

The uniform first-level import API (OSCAL.add_import / OSCAL.remove_import) is legal
only per each model's import cardinality (oscal_content._IMPORT_SPEC):

    catalog                       none     -> add invalid, remove refused
    mapping-collection            none     -> add invalid, remove refused
    system-security-plan          exactly 1 (min==max) -> both invalid
    assessment-plan               exactly 1 (min==max) -> both invalid
    assessment-results            exactly 1 (min==max) -> both invalid   (import-ap)
    plan-of-action-and-milestones 0..1     -> both valid
    profile                       1..*      -> add valid; remove refused at the last
    component-definition          0..*      -> both valid

Documents are instantiated from each model's shipped template (loaded through the
support DB, the same path OSCAL.new uses) so single- and multi-word model classes
alike are exercised with a real, writable document.
"""
import pytest

from oscal import OSCAL
from oscal.oscal_support import get_support


# ---------------------------------------------------------------------------
def _load(model: str) -> OSCAL:
    """A fresh, writable document for *model* from its shipped template."""
    raw = get_support().load_file(f"{model}.xml", as_bytes=False)
    assert raw, f"template for {model} not found"
    return OSCAL.loads(raw)


FIXED_SINGLE = ["system-security-plan", "assessment-plan", "assessment-results"]
NO_IMPORTS   = ["catalog", "mapping-collection"]


# ===========================================================================
# Models with no top-level import: both operations invalid
# ===========================================================================
class TestNoImports:

    @pytest.mark.parametrize("model", NO_IMPORTS)
    def test_add_is_invalid(self, model):
        r = _load(model).add_import("x.xml")
        assert r.is_invalid is True
        assert r.ok is False

    @pytest.mark.parametrize("model", NO_IMPORTS)
    def test_remove_refused(self, model):
        assert _load(model).remove_import("x.xml") is False


# ===========================================================================
# Fixed single-import models (min == max == 1): both operations invalid
# ===========================================================================
class TestFixedSingle:

    @pytest.mark.parametrize("model", FIXED_SINGLE)
    def test_add_is_invalid(self, model):
        r = _load(model).add_import("x.xml")
        assert r.is_invalid is True

    @pytest.mark.parametrize("model", FIXED_SINGLE)
    def test_remove_placeholder_refused(self, model):
        doc = _load(model)
        # template ships a single href="#" placeholder — still may not be removed
        assert doc.remove_import("#") is False

    @pytest.mark.parametrize("model", FIXED_SINGLE)
    def test_import_untouched(self, model):
        doc = _load(model)
        before = doc._import_entries()
        doc.add_import("x.xml")
        doc.remove_import("#")
        assert doc._import_entries() == before


# ===========================================================================
# POA&M: optional single import (0..1)
# ===========================================================================
class TestPoamOptional:

    def test_add_fills_placeholder(self):
        po = _load("plan-of-action-and-milestones")
        r = po.add_import("ssp.xml")
        assert r.ok is True
        assert po._real_import_count() == 1

    def test_add_second_is_invalid_when_full(self):
        po = _load("plan-of-action-and-milestones")
        po.add_import("ssp.xml")
        r = po.add_import("ssp2.xml")
        assert r.is_invalid is True

    def test_remove_placeholder_then_add(self):
        po = _load("plan-of-action-and-milestones")
        assert po.remove_import("#") is True
        assert po._import_entries() == []
        assert po.add_import("ssp.xml").ok is True

    def test_remove_real_import_empties(self):
        po = _load("plan-of-action-and-milestones")
        po.add_import("ssp.xml")
        assert po.remove_import("ssp.xml") is True
        assert po._real_import_count() == 0


# ===========================================================================
# Profile: 1..* (add always ok; remove refused at the last import)
# ===========================================================================
class TestProfileMany:

    def test_first_add_fills_placeholder(self):
        p = _load("profile")
        r = p.add_import("a.xml")
        assert r.status == "replaced"
        assert p._real_import_count() == 1

    def test_remove_last_refused(self):
        p = _load("profile")
        p.add_import("a.xml")
        assert p.remove_import("a.xml") is False
        assert p._real_import_count() == 1

    def test_add_second_then_remove_one(self):
        p = _load("profile")
        p.add_import("a.xml")
        assert p.add_import("b.xml").status == "added"
        assert p._real_import_count() == 2
        assert p.remove_import("a.xml") is True
        assert p._real_import_count() == 1


# ===========================================================================
# Component definition: 0..* (both operations always available)
# ===========================================================================
class TestComponentDefinitionMany:

    def test_add_multiple(self):
        cd = _load("component-definition")
        assert cd.add_import("a.xml").status == "added"
        assert cd.add_import("b.xml").status == "added"
        assert cd._real_import_count() == 2

    def test_remove_down_to_zero(self):
        cd = _load("component-definition")
        cd.add_import("a.xml")
        assert cd.remove_import("a.xml") is True
        assert cd._real_import_count() == 0


# ===========================================================================
# Shared guards
# ===========================================================================
class TestGuards:

    def test_add_empty_href_is_error(self):
        r = _load("profile").add_import("")
        assert r.status == "error"

    def test_add_read_only_is_error(self):
        p = _load("profile")
        p.is_read_only = True
        assert p.add_import("a.xml").status == "error"

    def test_remove_read_only_refused(self):
        cd = _load("component-definition")
        cd.add_import("a.xml")
        cd.is_read_only = True
        assert cd.remove_import("a.xml") is False

    def test_remove_unknown_href_refused(self):
        p = _load("profile")
        p.add_import("a.xml")
        assert p.remove_import("nonexistent.xml") is False
