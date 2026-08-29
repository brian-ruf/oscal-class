"""
Unit tests for OSCAL.update_import() — modify the single import of a one-import
model (SSP, AP, AR, POA&M).

Branches covered:
    * empty "#" placeholder / direct URI -> create resource, repoint href ("replaced")
    * existing #uuid + new_resource=True  -> new resource, old one preserved ("replaced")
    * existing #uuid + new_resource=False -> update existing resource in place ("updated")
    * POA&M with no import                -> forwarded to add_import ("added")
    * unsupported models / read-only / missing target -> invalid / error
"""
import pytest

from oscal import OSCAL
from oscal.oscal_content import ImportResult
from oscal.oscal_support import get_support


def _load(model: str) -> OSCAL:
    raw = get_support().load_file(f"{model}.xml", as_bytes=False)
    assert raw
    return OSCAL.loads(raw)


def _resources(doc):
    return doc._dict[doc.model].get("back-matter", {}).get("resources", [])


def _href(doc):
    entries = doc._import_entries()
    return entries[0].get("href") if entries else None


SINGLE_FIXED = ["system-security-plan", "assessment-plan", "assessment-results"]
UNSUPPORTED  = ["catalog", "profile", "component-definition", "mapping-collection"]


# ===========================================================================
# Placeholder / first set: create resource + repoint
# ===========================================================================
class TestPlaceholderToResource:

    @pytest.mark.parametrize("model", SINGLE_FIXED + ["plan-of-action-and-milestones"])
    def test_placeholder_creates_resource_and_repoints(self, model):
        doc = _load(model)
        assert _href(doc) == "#"                      # template placeholder
        r = doc.update_import(title="Target", rlinks=[{"href": "target.xml"}])
        assert r.status == "replaced"
        assert r.ok is True
        assert _href(doc).startswith("#") and len(_href(doc)) > 1
        assert len(_resources(doc)) == 1
        assert r.resource["rlinks"][0]["href"] == "target.xml"

    def test_href_points_at_created_resource(self):
        doc = _load("system-security-plan")
        r = doc.update_import(rlinks=[{"href": "p.xml"}])
        assert _href(doc).lstrip("#") == r.resource["uuid"]


# ===========================================================================
# Direct URI import -> create resource whose rlink is that URI
# ===========================================================================
class TestDirectUri:

    def test_uri_moved_into_resource_rlink(self):
        doc = _load("assessment-plan")
        doc._dict["assessment-plan"]["import-ssp"]["href"] = "https://example.com/ssp.json"
        r = doc.update_import()                        # no rlinks -> fall back to the URI
        assert r.status == "replaced"
        assert r.resource["rlinks"][0]["href"] == "https://example.com/ssp.json"
        assert r.resource["rlinks"][0]["media-type"] == "application/json"
        assert _href(doc).lstrip("#") == r.resource["uuid"]

    def test_supplied_rlinks_override_uri(self):
        doc = _load("assessment-plan")
        doc._dict["assessment-plan"]["import-ssp"]["href"] = "https://example.com/ssp.json"
        r = doc.update_import(rlinks=[{"href": "local.xml", "media-type": "application/xml"}])
        assert r.resource["rlinks"][0]["href"] == "local.xml"


# ===========================================================================
# Existing #uuid fragment
# ===========================================================================
class TestFragment:

    @pytest.fixture
    def ssp_with_resource(self):
        doc = _load("system-security-plan")
        r = doc.update_import(title="Orig", rlinks=[{"href": "orig.xml"}],
                              props=[{"name": "source", "value": "a"}])
        return doc, r.resource["uuid"]

    def test_new_resource_true_creates_and_repoints(self, ssp_with_resource):
        doc, old_uuid = ssp_with_resource
        r = doc.update_import(title="New", rlinks=[{"href": "new.xml"}], new_resource=True)
        assert r.status == "replaced"
        assert r.resource["uuid"] != old_uuid
        assert _href(doc).lstrip("#") == r.resource["uuid"]

    def test_new_resource_true_preserves_old_resource(self, ssp_with_resource):
        doc, old_uuid = ssp_with_resource
        doc.update_import(rlinks=[{"href": "new.xml"}], new_resource=True)
        # old resource is NOT deleted (may be referenced elsewhere)
        assert any(res["uuid"] == old_uuid for res in _resources(doc))
        assert len(_resources(doc)) == 2

    def test_new_resource_false_updates_in_place(self, ssp_with_resource):
        doc, old_uuid = ssp_with_resource
        href_before = _href(doc)
        r = doc.update_import(title="Renamed", new_resource=False)
        assert r.status == "updated"
        assert r.is_updated is True
        assert _href(doc) == href_before                 # href unchanged
        assert r.resource["uuid"] == old_uuid            # same resource
        assert r.resource["title"] == "Renamed"
        assert len(_resources(doc)) == 1                 # no new resource

    def test_new_resource_false_wholesale_array_replace(self, ssp_with_resource):
        doc, old_uuid = ssp_with_resource
        doc.update_import(props=[{"name": "keyword", "value": "b"}], new_resource=False)
        res = next(r for r in _resources(doc) if r["uuid"] == old_uuid)
        assert [p["name"] for p in res["props"]] == ["keyword"]  # old "source" prop gone

    def test_new_resource_false_missing_resource_is_error(self):
        doc = _load("assessment-results")
        doc._dict["assessment-results"]["import-ap"]["href"] = "#00000000-0000-4000-8000-000000000000"
        r = doc.update_import(title="x", new_resource=False)
        assert r.status == "error"


# ===========================================================================
# POA&M optional import bootstrap
# ===========================================================================
class TestPoamBootstrap:

    def test_no_import_forwards_to_add_import(self):
        po = _load("plan-of-action-and-milestones")
        assert po.remove_import("#") is True
        assert po._import_entries() == []
        r = po.update_import(title="SSP", rlinks=[{"href": "ssp.xml"}])
        assert r.status == "added"
        assert r.ok is True
        assert _href(po).lstrip("#") == r.resource["uuid"]

    def test_no_import_without_rlink_is_error(self):
        po = _load("plan-of-action-and-milestones")
        po.remove_import("#")
        r = po.update_import(title="SSP")
        assert r.status == "error"


# ===========================================================================
# Guards
# ===========================================================================
class TestGuards:

    @pytest.mark.parametrize("model", UNSUPPORTED)
    def test_unsupported_models_are_invalid(self, model):
        r = _load(model).update_import(title="x")
        assert r.is_invalid is True

    def test_read_only_is_error(self):
        doc = _load("system-security-plan")
        doc.is_read_only = True
        assert doc.update_import(title="x").status == "error"

    def test_returns_import_result(self):
        assert isinstance(_load("system-security-plan").update_import(rlinks=[{"href": "p.xml"}]), ImportResult)

    def test_marks_unsaved(self):
        doc = _load("system-security-plan")
        doc.is_unsaved = False
        doc.update_import(rlinks=[{"href": "p.xml"}])
        assert doc.is_unsaved is True


# ===========================================================================
# Round-trip
# ===========================================================================
class TestRoundTrip:

    def test_update_import_json_round_trip(self):
        doc = _load("system-security-plan")
        # Caller-supplied rlinks are stored verbatim (as in update_resource); pass the
        # media-type explicitly — it is only inferred in the fallback-URI path.
        r = doc.update_import(title="RT Resource",
                              rlinks=[{"href": "profile.json", "media-type": "application/json"}])
        out = doc.dumps(format="json")
        assert r.resource["uuid"] in out
        assert "RT Resource" in out
        assert "application/json" in out
        reloaded = OSCAL.loads(out)
        assert reloaded._import_entries()[0]["href"].lstrip("#") == r.resource["uuid"]
