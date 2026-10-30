"""
Unit tests for link / back-matter-resource content acquisition and link-resource embedding:

    OSCAL.link_content(href, media_type=, prefer_embedded=)   — universal link resolver
    OSCAL.resource_content(uuid, media_type=, prefer_embedded=) — resource sub-handler
    _media_type_tokens / _media_type_matches                  — media-type preference parsing
    _embed_link_resources (via SSP.authorization_boundary(include_resources=True))

Covers the three content scenarios (full URI, fragment→rlink, fragment→base64), the
prefer_embedded ordering, media-type preference (list / wildcard / total-wildcard / fallback),
acquisition cascade on failure, the four hash-integrity statuses, and the result-dict shape.
All I/O is local-file or in-memory — no network.
"""
import base64
import hashlib
import json

import pytest

from oscal import OSCAL
from oscal.oscal_content import (
    _media_type_tokens, _media_type_matches,
    INTEGRITY_VALID, INTEGRITY_NOT_VALID, INTEGRITY_NO_SUPPORTED_ALGORITHMS,
    INTEGRITY_NO_HASH, INTEGRITY_NOT_APPLICABLE,
)

_PNG = b"\x89PNG\r\n\x1a\n-not-a-real-image-but-binary\x00\xff"
_B64 = base64.b64encode(_PNG).decode()
_GOOD_SHA256 = hashlib.sha256(_PNG).hexdigest()
_BAD_SHA256 = "0" * 64


@pytest.fixture
def img_file(tmp_path):
    p = tmp_path / "diagram.png"
    p.write_bytes(_PNG)
    return str(p)


def _doc(resources, *, links=None):
    """A minimal SSP carrying the given back-matter resources (and optional top-level links)."""
    root = {
        "uuid": "30000000-0000-4000-8000-000000000001",
        "metadata": {"title": "T", "last-modified": "2026-01-01T00:00:00Z",
                     "version": "1.0", "oscal-version": "1.1.3"},
        "back-matter": {"resources": resources},
    }
    if links is not None:
        root["links"] = links
    return OSCAL.loads(json.dumps({"system-security-plan": root}))


# ===========================================================================
class TestMediaTypeTokens:
    def test_none_and_empty(self):
        assert _media_type_tokens(None) is None
        assert _media_type_tokens("") is None

    def test_total_wildcard_is_no_constraint(self):
        assert _media_type_tokens("*") is None
        assert _media_type_tokens("*/*") is None
        # a total wildcard anywhere in a list collapses the whole thing to no-preference
        assert _media_type_tokens("application/pdf, */*") is None

    def test_list_parsed_lowercased_trimmed(self):
        assert _media_type_tokens("Image/PNG, application/pdf ") == ["image/png", "application/pdf"]


class TestMediaTypeMatches:
    def test_no_constraint_matches_anything(self):
        assert _media_type_matches(None, "image/png") is True
        assert _media_type_matches(None, None) is True

    def test_exact_case_insensitive(self):
        assert _media_type_matches(["image/png"], "IMAGE/PNG") is True
        assert _media_type_matches(["image/png"], "image/svg+xml") is False

    def test_parameters_ignored(self):
        assert _media_type_matches(["text/html"], "text/html; charset=utf-8") is True

    def test_subtype_wildcard(self):
        assert _media_type_matches(["image/*"], "image/svg+xml") is True
        assert _media_type_matches(["image/*"], "application/pdf") is False

    def test_typeless_candidate_never_matches_a_constraint(self):
        assert _media_type_matches(["image/*"], None) is False
        assert _media_type_matches(["image/png"], "") is False


# ===========================================================================
class TestResourceContentBase64:
    def test_base64_decoded(self):
        doc = _doc([{"uuid": "r1", "base64": {"filename": "d.png",
                                              "media-type": "image/png", "value": _B64}}])
        r = doc.resource_content("r1")
        assert r["success"] is True
        assert r["source"] == "base64"
        assert r["content"] == _PNG
        assert r["media-type"] == "image/png"
        assert r["filename"] == "d.png"
        assert r["integrity-verification-status"] == INTEGRITY_NO_HASH   # base64 has no hash

    def test_resource_not_found(self):
        doc = _doc([])
        r = doc.resource_content("missing")
        assert r["success"] is False
        assert r["source"] is None
        assert r["integrity-verification-status"] == INTEGRITY_NOT_APPLICABLE
        assert r["failure"]["code"].value == "resource-not-found"

    def test_no_viable_content(self):
        doc = _doc([{"uuid": "r1", "title": "ref only"}])   # neither base64 nor rlinks
        r = doc.resource_content("r1")
        assert r["success"] is False
        assert r["failure"]["code"].value == "resource-no-viable-content"


class TestResourceContentRlink:
    def test_local_rlink_fetched(self, img_file):
        doc = _doc([{"uuid": "r1", "rlinks": [{"href": img_file, "media-type": "image/png"}]}])
        r = doc.resource_content("r1")
        assert r["success"] is True
        assert r["source"] == "rlink"
        assert r["content"] == _PNG
        assert r["original-href"] == img_file and r["href"] == img_file

    def test_hash_valid(self, img_file):
        doc = _doc([{"uuid": "r1", "rlinks": [
            {"href": img_file, "hashes": [{"algorithm": "SHA-256", "value": _GOOD_SHA256}]}]}])
        assert doc.resource_content("r1")["integrity-verification-status"] == INTEGRITY_VALID

    def test_hash_not_valid_is_non_gating(self, img_file):
        doc = _doc([{"uuid": "r1", "rlinks": [
            {"href": img_file, "hashes": [{"algorithm": "SHA-256", "value": _BAD_SHA256}]}]}])
        r = doc.resource_content("r1")
        assert r["success"] is True                 # content still delivered
        assert r["content"] == _PNG
        assert r["integrity-verification-status"] == INTEGRITY_NOT_VALID

    def test_hash_unsupported_algorithm(self, img_file):
        doc = _doc([{"uuid": "r1", "rlinks": [
            {"href": img_file, "hashes": [{"algorithm": "MD5", "value": "abc"}]}]}])
        assert doc.resource_content("r1")["integrity-verification-status"] \
            == INTEGRITY_NO_SUPPORTED_ALGORITHMS

    def test_first_supported_hash_wins(self, img_file):
        # MD5 (unsupported) is skipped; the first SUPPORTED hash (SHA-256) decides.
        doc = _doc([{"uuid": "r1", "rlinks": [{"href": img_file, "hashes": [
            {"algorithm": "MD5", "value": "ignored"},
            {"algorithm": "SHA-256", "value": _GOOD_SHA256}]}]}])
        assert doc.resource_content("r1")["integrity-verification-status"] == INTEGRITY_VALID


class TestResourceContentSelection:
    def _both(self, img_file, b64_type="image/png", rlink_type="image/svg+xml"):
        return _doc([{"uuid": "r1",
                      "base64": {"filename": "d.png", "media-type": b64_type, "value": _B64},
                      "rlinks": [{"href": img_file, "media-type": rlink_type}]}])

    def test_prefer_embedded_true(self, img_file):
        assert self._both(img_file).resource_content("r1", prefer_embedded=True)["source"] == "base64"

    def test_prefer_embedded_false(self, img_file):
        assert self._both(img_file).resource_content("r1", prefer_embedded=False)["source"] == "rlink"

    def test_media_type_overrides_prefer_order(self, img_file):
        # prefer_embedded=True would pick base64, but only the rlink is svg → media_type wins.
        r = self._both(img_file).resource_content("r1", media_type="image/svg+xml", prefer_embedded=True)
        assert r["source"] == "rlink"

    def test_media_type_miss_falls_back_to_prefer_order(self, img_file):
        # Neither source is pdf → fall back to the prefer_embedded order (base64 first).
        r = self._both(img_file).resource_content("r1", media_type="application/pdf", prefer_embedded=True)
        assert r["source"] == "base64"

    def test_media_type_list_matches_any(self, img_file):
        r = self._both(img_file).resource_content("r1", media_type="application/pdf, image/svg+xml",
                                                  prefer_embedded=True)
        assert r["source"] == "rlink"

    def test_cascade_skips_failing_source(self, tmp_path):
        # prefer_embedded=False puts the (missing-file) rlink first; it fails to acquire, so
        # the cascade falls through to the viable base64. Not a failure — just the next source.
        missing = str(tmp_path / "nope.png")
        doc = _doc([{"uuid": "r1",
                     "base64": {"filename": "d.png", "media-type": "image/png", "value": _B64},
                     "rlinks": [{"href": missing, "media-type": "image/png"}]}])
        r = doc.resource_content("r1", prefer_embedded=False)
        assert r["success"] is True and r["source"] == "base64" and r["content"] == _PNG

    def test_all_sources_fail(self, tmp_path):
        missing = str(tmp_path / "nope.png")
        doc = _doc([{"uuid": "r1", "rlinks": [{"href": missing}]}])
        r = doc.resource_content("r1")
        assert r["success"] is False
        assert r["failure"]["code"].value == "local-not-found"


# ===========================================================================
class TestLinkContent:
    def test_full_uri_local_path_direct(self, img_file):
        # Scenario 1: href is a path/URI, not a fragment → fetched directly.
        doc = _doc([])
        r = doc.link_content(img_file)
        assert r["success"] is True
        assert r["source"] == "href"
        assert r["content"] == _PNG
        assert r["integrity-verification-status"] == INTEGRITY_NO_HASH

    def test_fragment_to_base64(self):
        doc = _doc([{"uuid": "r1", "base64": {"media-type": "image/png", "value": _B64}}])
        r = doc.link_content("#r1")
        assert r["success"] is True and r["source"] == "base64"

    def test_fragment_to_rlink(self, img_file):
        doc = _doc([{"uuid": "r1", "rlinks": [{"href": img_file}]}])
        r = doc.link_content("#r1")
        assert r["success"] is True and r["source"] == "rlink"

    def test_dangling_fragment(self):
        doc = _doc([{"uuid": "r1", "base64": {"value": _B64}}])
        r = doc.link_content("#does-not-exist")
        assert r["success"] is False
        assert r["original-href"] == "#does-not-exist"
        assert r["failure"]["code"].value == "resource-not-found"

    def test_missing_local_full_path(self, tmp_path):
        doc = _doc([])
        r = doc.link_content(str(tmp_path / "absent.png"))
        assert r["success"] is False
        assert r["source"] == "href"
        assert r["failure"]["code"].value == "local-not-found"

    def test_empty_href(self):
        r = _doc([]).link_content("")
        assert r["success"] is False


# ===========================================================================
class TestDiagramsIncludeResources:
    def _ssp_with_diagram_links(self, img_file):
        return OSCAL.loads(json.dumps({"system-security-plan": {
            "uuid": "30000000-0000-4000-8000-000000000001",
            "metadata": {"title": "T", "last-modified": "2026-01-01T00:00:00Z",
                         "version": "1.0", "oscal-version": "1.1.3"},
            "system-characteristics": {
                "system-ids": [{"id": "s"}], "system-name": "N", "description": "d",
                "security-sensitivity-level": "low", "status": {"state": "operational"},
                "system-information": {"information-types": [{"title": "IT", "description": "d"}]},
                "authorization-boundary": {
                    "description": "AB",
                    "links": [{"href": "#res-embedded", "rel": "diagram"}],
                    "diagrams": [{"uuid": "d1", "links": [
                        {"href": "#res-embedded", "rel": "diagram"},
                        {"href": "https://example.org/x.png", "rel": "alt"},
                        {"href": "#dangling", "rel": "alt"}]}]},
            },
            "back-matter": {"resources": [
                {"uuid": "res-embedded", "base64": {
                    "filename": "d.png", "media-type": "image/png", "value": _B64}}]},
        }}))

    def test_off_by_default(self, img_file):
        ab = self._ssp_with_diagram_links(img_file).authorization_boundary()
        assert "resource" not in ab["links"][0]

    def test_embeds_resource_with_base64_stub(self, img_file):
        ab = self._ssp_with_diagram_links(img_file).authorization_boundary(include_resources=True)
        res = ab["links"][0]["resource"]
        assert res["uuid"] == "res-embedded"
        # base64 kept as a stub: filename/media-type retained, value stripped
        assert res["base64"]["filename"] == "d.png"
        assert res["base64"]["media-type"] == "image/png"
        assert "value" not in res["base64"]

    def test_embeds_into_nested_diagram_links(self, img_file):
        ab = self._ssp_with_diagram_links(img_file).authorization_boundary(include_resources=True)
        assert "resource" in ab["diagrams"][0]["links"][0]

    def test_non_fragment_and_dangling_links_untouched(self, img_file):
        ab = self._ssp_with_diagram_links(img_file).authorization_boundary(include_resources=True)
        http_link, dangling_link = ab["diagrams"][0]["links"][1], ab["diagrams"][0]["links"][2]
        assert "resource" not in http_link       # full URI, not a resource fragment
        assert "resource" not in dangling_link    # fragment resolves to no resource
