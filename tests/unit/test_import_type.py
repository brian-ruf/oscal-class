"""
Unit tests for import *type* enforcement on add_import / update_import.

Only appropriate imported models are accepted per importing model:

    profile, system-security-plan   -> catalog, profile
    component-definition            -> component-definition   (import-component-definition
                                       only; control-implementation @source imports are a
                                       separate future mechanism)
    assessment-plan                 -> system-security-plan
    plan-of-action-and-milestones   -> system-security-plan
    assessment-results              -> assessment-plan
    catalog, mapping-collection     -> none (no addable imports)

Cardinality still routes which method applies: list/0..1 models (profile, cDef, POA&M)
use add_import; fixed single-import models (SSP, AP, AR) use update_import. Type is
enforced in both. Each model's shipped template is written to disk and used as a real,
loadable import target (absolute paths, since a template loaded from a string has no
href to resolve relative hrefs against).
"""
import os
import tempfile

import pytest

from oscal import OSCAL
from oscal.oscal_support import get_support

_MODELS = ["catalog", "profile", "component-definition", "system-security-plan",
           "assessment-plan", "assessment-results", "plan-of-action-and-milestones",
           "mapping-collection"]


def _fresh(model: str) -> OSCAL:
    """A fresh, writable document for *model* from its shipped template."""
    raw = get_support().load_file(f"{model}.xml", as_bytes=False)
    assert raw, f"template for {model} not found"
    return OSCAL.loads(raw)


@pytest.fixture(scope="module")
def target():
    """Map model name -> absolute path of that model's template written to disk."""
    with tempfile.TemporaryDirectory() as d:
        paths = {}
        for model in _MODELS:
            raw = get_support().load_file(f"{model}.xml", as_bytes=False)
            p = os.path.join(d, f"{model}.xml")
            with open(p, "w") as fh:
                fh.write(raw)
            paths[model] = p
        yield paths


# ===========================================================================
# add_import — list / 0..1 models (profile, component-definition, POA&M)
# ===========================================================================
class TestAddImportType:

    @pytest.mark.parametrize("imported", ["catalog", "profile"])
    def test_profile_accepts_catalog_and_profile(self, target, imported):
        # "added" (appended) or "replaced" (filled the template's placeholder import).
        r = _fresh("profile").add_import(target[imported])
        assert r.ok and r.status in ("added", "replaced")

    @pytest.mark.parametrize("imported", ["component-definition", "system-security-plan",
                                          "assessment-plan"])
    def test_profile_rejects_others(self, target, imported):
        r = _fresh("profile").add_import(target[imported])
        assert r.is_invalid and not r.ok

    def test_cdef_accepts_cdef(self, target):
        r = _fresh("component-definition").add_import(target["component-definition"])
        assert r.ok and r.status in ("added", "replaced")

    @pytest.mark.parametrize("imported", ["catalog", "profile", "system-security-plan"])
    def test_cdef_rejects_non_cdef(self, target, imported):
        r = _fresh("component-definition").add_import(target[imported])
        assert r.is_invalid and not r.ok

    def test_poam_accepts_ssp(self, target):
        assert _fresh("plan-of-action-and-milestones").add_import(
            target["system-security-plan"]).status in ("added", "replaced")

    @pytest.mark.parametrize("imported", ["catalog", "profile", "assessment-plan"])
    def test_poam_rejects_non_ssp(self, target, imported):
        r = _fresh("plan-of-action-and-milestones").add_import(target[imported])
        assert r.is_invalid and not r.ok


# ===========================================================================
# update_import — fixed single-import models (SSP, AP, AR) + POA&M repoint
# ===========================================================================
class TestUpdateImportType:

    def _update(self, model, imported_path):
        return _fresh(model).update_import(rlinks=[{"href": imported_path}])

    @pytest.mark.parametrize("imported", ["catalog", "profile"])
    def test_ssp_accepts_catalog_and_profile(self, target, imported):
        assert self._update("system-security-plan", target[imported]).ok

    @pytest.mark.parametrize("imported", ["assessment-plan", "component-definition"])
    def test_ssp_rejects_others(self, target, imported):
        r = self._update("system-security-plan", target[imported])
        assert r.is_invalid and not r.ok

    def test_ap_accepts_ssp(self, target):
        assert self._update("assessment-plan", target["system-security-plan"]).ok

    @pytest.mark.parametrize("imported", ["catalog", "assessment-plan"])
    def test_ap_rejects_non_ssp(self, target, imported):
        assert self._update("assessment-plan", target[imported]).is_invalid

    def test_ar_accepts_ap(self, target):
        assert self._update("assessment-results", target["assessment-plan"]).ok

    @pytest.mark.parametrize("imported", ["system-security-plan", "catalog"])
    def test_ar_rejects_non_ap(self, target, imported):
        assert self._update("assessment-results", target[imported]).is_invalid


# ===========================================================================
# Message clarity + unresolvable target passes the gate (flagged later instead)
# ===========================================================================
class TestGateBehavior:

    def test_invalid_message_names_models(self, target):
        r = _fresh("assessment-plan").update_import(rlinks=[{"href": target["catalog"]}])
        assert r.is_invalid
        assert "system-security-plan" in r.message and "catalog" in r.message

    def test_unresolvable_href_not_rejected_by_type_gate(self):
        # The type cannot be determined, so the gate lets it through; resolve_imports
        # marks it as a failed import rather than the gate calling it a type violation.
        r = _fresh("profile").add_import("does-not-exist-anywhere.json")
        assert not r.is_invalid            # not a type rejection
