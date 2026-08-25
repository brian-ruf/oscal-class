"""
Unit tests for typed import failure states.

Covers:
    - _is_valid_uuid()
    - _backmatter_resource()
    - ImportFailure dataclass
    - ImportLoadError exception
    - load_source() raises typed ImportLoadError
    - load_content() propagates / raises typed ImportLoadError
    - resolve_imports() fragment failure cases:
          FRAGMENT_INVALID_UUID, RESOURCE_NOT_FOUND, RESOURCE_NO_VIABLE_CONTENT
    - resolve_imports() URI failure cases:
          LOCAL_NOT_FOUND, REMOTE_UNSUPPORTED, REMOTE_AUTH_REQUIRED, REMOTE_UNREACHABLE
    - failed_imports property
    - Successful imports leave failure=None
"""
import os
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from oscal import OSCAL
from oscal.oscal_content import (
    ContentState,
    ImportFailure,
    ImportFailureCode,
    ImportLoadError,
    ImportState,
    OscalRef,
    _backmatter_resource,
    _is_valid_uuid,
    classify_source,
    load_content,
    load_source,
)

# ---------------------------------------------------------------------------
# Shared UUIDs and XML helpers
# ---------------------------------------------------------------------------

_MISSING_UUID = "aabbccdd-0000-4000-a000-000000000099"   # valid format, not in back-matter
_EMPTY_UUID   = "aabbccdd-0000-4000-a000-000000000088"   # resource exists but no rlinks/base64
_RLINK_UUID   = "aabbccdd-0000-4000-a000-000000000077"   # resource exists with rlinks
_TITLE_UUID   = "aabbccdd-0000-4000-a000-000000000066"   # resource with title + description

_IMPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test-data", "xml", "imports",
)
_CATALOG_PATH = os.path.join(_IMPORTS_DIR, "test_catalog.xml")


def _profile_xml(href: str, back_matter_xml: str = "") -> str:
    bm = f"<back-matter>{back_matter_xml}</back-matter>" if back_matter_xml else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-000000000001">
  <metadata>
    <title>Import Failure Test Profile</title>
    <last-modified>2026-04-28T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  <import href="{href}"><include-all/></import>
  <merge><combine method="keep"/><as-is>true</as-is></merge>
  {bm}
</profile>"""


def _resource_xml(res_uuid: str, rlinks: list = [], title: str = "",
                  description: str = "", has_base64: bool = False) -> str:
    title_el  = f"<title>{title}</title>" if title else ""
    desc_el   = f"<description><p>{description}</p></description>" if description else ""
    base64_el = '<base64 filename="d.xml">dGVzdA==</base64>' if has_base64 else ""

    def _rlink_el(r):
        if isinstance(r, tuple):
            href, mt = r
            return f'<rlink href="{href}" media-type="{mt}"/>'
        return f'<rlink href="{r}"/>'

    rlink_els = "".join(_rlink_el(r) for r in rlinks)
    return (f'<resource uuid="{res_uuid}">'
            f"{title_el}{desc_el}{rlink_els}{base64_el}</resource>")


def _load_profile(href: str, back_matter_xml: str = "") -> OSCAL:
    return OSCAL.loads(_profile_xml(href, back_matter_xml))


# ===========================================================================
# _is_valid_uuid
# ===========================================================================

class TestIsValidUuid:
    def test_standard_v4_uuid(self):
        assert _is_valid_uuid("aabbccdd-0000-4000-a000-000000000001") is True

    def test_all_zeros_uuid(self):
        assert _is_valid_uuid("00000000-0000-0000-0000-000000000000") is True

    def test_uppercase_uuid(self):
        assert _is_valid_uuid("AABBCCDD-0000-4000-A000-000000000001") is True

    def test_invalid_slug(self):
        assert _is_valid_uuid("not-a-uuid") is False

    def test_invalid_trailing_char(self):
        # Last char is 'g' — not valid hex
        assert _is_valid_uuid("e9d6719d-c4a3-4d74-9227-907e22742781g") is False

    def test_empty_string(self):
        assert _is_valid_uuid("") is False

    def test_partial_uuid(self):
        assert _is_valid_uuid("aabbccdd-0000-4000") is False

    def test_no_such_uuid_slug(self):
        assert _is_valid_uuid("no-such-uuid-exists-in-back-matter") is False


# ===========================================================================
# _backmatter_resource
# ===========================================================================

class TestBackmatterResource:
    def _doc_with_resources(self, *resource_xmls: str) -> OSCAL:
        bm = "".join(resource_xmls)
        return OSCAL.loads(_profile_xml(f"#{_RLINK_UUID}", bm))

    def test_returns_none_when_not_found(self):
        doc = OSCAL.loads(_profile_xml(f"#{_MISSING_UUID}"))
        assert _backmatter_resource(doc, _MISSING_UUID) is None

    def test_returns_none_on_wrong_uuid(self):
        doc = self._doc_with_resources(_resource_xml(_RLINK_UUID, rlinks=["/tmp/x.xml"]))
        assert _backmatter_resource(doc, _MISSING_UUID) is None

    def test_returns_uuid(self):
        doc = self._doc_with_resources(_resource_xml(_RLINK_UUID, rlinks=["/tmp/x.xml"]))
        result = _backmatter_resource(doc, _RLINK_UUID)
        assert result is not None
        assert result["uuid"] == _RLINK_UUID

    def test_returns_title(self):
        doc = self._doc_with_resources(
            _resource_xml(_TITLE_UUID, rlinks=["/tmp/x.xml"], title="My Catalog"))
        result = _backmatter_resource(doc, _TITLE_UUID)
        assert result["title"] == "My Catalog"

    def test_returns_description(self):
        doc = self._doc_with_resources(
            _resource_xml(_TITLE_UUID, rlinks=["/tmp/x.xml"], description="Desc text"))
        result = _backmatter_resource(doc, _TITLE_UUID)
        assert result["description"] == "Desc text"

    def test_returns_rlinks_list(self):
        doc = self._doc_with_resources(
            _resource_xml(_RLINK_UUID, rlinks=["/tmp/a.xml", "/tmp/b.xml"]))
        result = _backmatter_resource(doc, _RLINK_UUID)
        assert result["rlinks"] == [{"href": "/tmp/a.xml"}, {"href": "/tmp/b.xml"}]

    def test_returns_rlinks_with_media_type(self):
        doc = self._doc_with_resources(
            _resource_xml(_RLINK_UUID, rlinks=[("/tmp/a.json", "application/json")]))
        result = _backmatter_resource(doc, _RLINK_UUID)
        assert result["rlinks"] == [{"href": "/tmp/a.json", "media-type": "application/json"}]

    def test_returns_has_base64_true(self):
        doc = self._doc_with_resources(_resource_xml(_RLINK_UUID, has_base64=True))
        result = _backmatter_resource(doc, _RLINK_UUID)
        assert result["has_base64"] is True

    def test_returns_has_base64_false(self):
        doc = self._doc_with_resources(_resource_xml(_RLINK_UUID, rlinks=["/tmp/x.xml"]))
        result = _backmatter_resource(doc, _RLINK_UUID)
        assert result["has_base64"] is False

    def test_empty_rlinks_list_when_none(self):
        doc = self._doc_with_resources(_resource_xml(_EMPTY_UUID))
        result = _backmatter_resource(doc, _EMPTY_UUID)
        assert result["rlinks"] == []


# ===========================================================================
# ImportFailure dataclass
# ===========================================================================

class TestImportFailureDataclass:
    def test_is_fragment_ref_true_for_hash_href(self):
        f = ImportFailure(code=ImportFailureCode.RESOURCE_NOT_FOUND,
                          href_original=f"#{_MISSING_UUID}")
        assert f.is_fragment_ref is True

    def test_is_fragment_ref_false_for_full_uri(self):
        f = ImportFailure(code=ImportFailureCode.LOCAL_NOT_FOUND,
                          href_original="/path/to/catalog.xml")
        assert f.is_fragment_ref is False

    def test_default_fields_are_empty(self):
        f = ImportFailure(code=ImportFailureCode.CONTENT_EMPTY, href_original="x")
        assert f.resource_uuid == ""
        assert f.resource_title == ""
        assert f.resource_description == ""
        assert f.rlinks_tried == []
        assert f.uri == ""
        assert f.message == ""

    def test_all_fields_stored(self):
        f = ImportFailure(
            code=ImportFailureCode.RESOURCE_NOT_FOUND,
            href_original=f"#{_MISSING_UUID}",
            resource_uuid=_MISSING_UUID,
            resource_title="Test Title",
            resource_description="Test Desc",
            rlinks_tried=["/a.xml", "/b.xml"],
            uri="/b.xml",
            message="failed",
        )
        assert f.resource_uuid == _MISSING_UUID
        assert f.resource_title == "Test Title"
        assert f.resource_description == "Test Desc"
        assert f.rlinks_tried == ["/a.xml", "/b.xml"]
        assert f.uri == "/b.xml"
        assert f.message == "failed"


# ===========================================================================
# ImportLoadError exception
# ===========================================================================

class TestImportLoadError:
    def test_carries_code(self):
        err = ImportLoadError(ImportFailureCode.LOCAL_NOT_FOUND, "/path/file.xml")
        assert err.code == ImportFailureCode.LOCAL_NOT_FOUND

    def test_carries_uri(self):
        err = ImportLoadError(ImportFailureCode.LOCAL_NOT_FOUND, "/path/file.xml")
        assert err.uri == "/path/file.xml"

    def test_default_message_contains_code_and_uri(self):
        err = ImportLoadError(ImportFailureCode.REMOTE_UNREACHABLE, "https://example.com/x.xml")
        assert "remote-unreachable" in str(err)
        assert "https://example.com/x.xml" in str(err)

    def test_custom_message_used_when_provided(self):
        err = ImportLoadError(ImportFailureCode.LOCAL_NOT_FOUND, "/f.xml", "custom msg")
        assert str(err) == "custom msg"

    def test_is_exception_subclass(self):
        assert issubclass(ImportLoadError, Exception)


# ===========================================================================
# load_source() raises typed errors
# ===========================================================================

class TestLoadSourceTypedErrors:
    def _file_ref(self, path: str) -> OscalRef:
        ref = OscalRef(href=path)
        classify_source(ref)
        return ref

    def test_local_not_found_for_missing_file(self, tmp_path):
        ref = self._file_ref(str(tmp_path / "nonexistent.xml"))
        with pytest.raises(ImportLoadError) as exc_info:
            load_source(ref)
        assert exc_info.value.code == ImportFailureCode.LOCAL_NOT_FOUND

    def test_local_not_found_uri_carries_path(self, tmp_path):
        path = str(tmp_path / "missing.xml")
        ref = self._file_ref(path)
        with pytest.raises(ImportLoadError) as exc_info:
            load_source(ref)
        assert exc_info.value.uri == path

    def test_unsupported_scheme_raises(self):
        ref = OscalRef(href="s3://bucket/catalog.xml")
        ref.source_type   = "uri"
        ref.source_scheme = "s3"
        ref.source_supported = True   # bypass load_content guard; test load_source directly
        with pytest.raises(ImportLoadError) as exc_info:
            load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_UNSUPPORTED

    def test_http_401_raises_auth_required(self):
        ref = OscalRef(href="https://example.com/catalog.xml")
        classify_source(ref)
        http_err = HTTPError("https://example.com/catalog.xml", 401, "Unauthorized", {}, None)
        with patch("oscal.oscal_source.download_file", side_effect=http_err):
            with pytest.raises(ImportLoadError) as exc_info:
                load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_AUTH_REQUIRED

    def test_http_403_raises_auth_required(self):
        ref = OscalRef(href="https://example.com/catalog.xml")
        classify_source(ref)
        http_err = HTTPError("https://example.com/catalog.xml", 403, "Forbidden", {}, None)
        with patch("oscal.oscal_source.download_file", side_effect=http_err):
            with pytest.raises(ImportLoadError) as exc_info:
                load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_AUTH_REQUIRED

    def test_connection_error_raises_unreachable(self):
        ref = OscalRef(href="https://example.com/catalog.xml")
        classify_source(ref)
        with patch("oscal.oscal_source.download_file", side_effect=ConnectionError("timeout")):
            with pytest.raises(ImportLoadError) as exc_info:
                load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_UNREACHABLE

    def test_url_error_raises_unreachable(self):
        ref = OscalRef(href="https://example.com/catalog.xml")
        classify_source(ref)
        with patch("oscal.oscal_source.download_file", side_effect=URLError("no route")):
            with pytest.raises(ImportLoadError) as exc_info:
                load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_UNREACHABLE

    def test_http_500_raises_unreachable(self):
        ref = OscalRef(href="https://example.com/catalog.xml")
        classify_source(ref)
        http_err = HTTPError("https://example.com/catalog.xml", 500, "Server Error", {}, None)
        with patch("oscal.oscal_source.download_file", side_effect=http_err):
            with pytest.raises(ImportLoadError) as exc_info:
                load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_UNREACHABLE


# ===========================================================================
# load_content() propagates ImportLoadError
# ===========================================================================

class TestLoadContentPropagates:
    def test_propagates_local_not_found(self, tmp_path):
        path = str(tmp_path / "missing.xml")
        with pytest.raises(ImportLoadError) as exc_info:
            load_content(path)
        assert exc_info.value.code == ImportFailureCode.LOCAL_NOT_FOUND

    def test_unsupported_scheme_raises(self):
        with pytest.raises(ImportLoadError) as exc_info:
            load_content("s3://bucket/catalog.xml")
        assert exc_info.value.code == ImportFailureCode.REMOTE_UNSUPPORTED

    def test_propagates_auth_error(self):
        http_err = HTTPError("https://example.com/c.xml", 401, "Unauthorized", {}, None)
        with patch("oscal.oscal_source.download_file", side_effect=http_err):
            with pytest.raises(ImportLoadError) as exc_info:
                load_content("https://example.com/c.xml")
        assert exc_info.value.code == ImportFailureCode.REMOTE_AUTH_REQUIRED

    def test_last_error_raised_when_all_refs_fail(self, tmp_path):
        refs = [str(tmp_path / "a.xml"), str(tmp_path / "b.xml")]
        with pytest.raises(ImportLoadError) as exc_info:
            load_content(refs)
        assert exc_info.value.code == ImportFailureCode.LOCAL_NOT_FOUND


# ===========================================================================
# resolve_imports() — fragment failure cases
# ===========================================================================

class TestFragmentFailures:
    # --- FRAGMENT_INVALID_UUID ---

    def test_invalid_uuid_fragment_sets_status_invalid(self):
        obj = _load_profile("#not-a-uuid")
        assert obj.import_list[0]["status"] == ImportState.INVALID

    def test_invalid_uuid_fragment_code(self):
        obj = _load_profile("#not-a-uuid")
        assert obj.import_list[0]["failure"].code == ImportFailureCode.FRAGMENT_INVALID_UUID

    def test_invalid_uuid_fragment_href_original(self):
        obj = _load_profile("#not-a-uuid")
        assert obj.import_list[0]["failure"].href_original == "#not-a-uuid"

    def test_invalid_uuid_fragment_is_fragment_ref(self):
        obj = _load_profile("#not-a-uuid")
        assert obj.import_list[0]["failure"].is_fragment_ref is True

    def test_invalid_uuid_fragment_rlinks_not_tried(self):
        obj = _load_profile("#not-a-uuid")
        assert obj.import_list[0]["failure"].rlinks_tried == []

    # --- RESOURCE_NOT_FOUND ---

    def test_missing_resource_code(self):
        obj = _load_profile(f"#{_MISSING_UUID}")
        assert obj.import_list[0]["failure"].code == ImportFailureCode.RESOURCE_NOT_FOUND

    def test_missing_resource_uuid_in_failure(self):
        obj = _load_profile(f"#{_MISSING_UUID}")
        assert obj.import_list[0]["failure"].resource_uuid == _MISSING_UUID

    def test_missing_resource_is_fragment_ref(self):
        obj = _load_profile(f"#{_MISSING_UUID}")
        assert obj.import_list[0]["failure"].is_fragment_ref is True

    # --- RESOURCE_NO_VIABLE_CONTENT ---

    def test_empty_resource_code(self):
        bm = _resource_xml(_EMPTY_UUID)
        obj = _load_profile(f"#{_EMPTY_UUID}", bm)
        assert obj.import_list[0]["failure"].code == ImportFailureCode.RESOURCE_NO_VIABLE_CONTENT

    def test_empty_resource_carries_uuid(self):
        bm = _resource_xml(_EMPTY_UUID)
        obj = _load_profile(f"#{_EMPTY_UUID}", bm)
        assert obj.import_list[0]["failure"].resource_uuid == _EMPTY_UUID

    def test_empty_resource_carries_title(self):
        bm = _resource_xml(_EMPTY_UUID, title="Reference Catalog")
        obj = _load_profile(f"#{_EMPTY_UUID}", bm)
        assert obj.import_list[0]["failure"].resource_title == "Reference Catalog"

    def test_empty_resource_carries_description(self):
        bm = _resource_xml(_EMPTY_UUID, description="The base catalog")
        obj = _load_profile(f"#{_EMPTY_UUID}", bm)
        assert obj.import_list[0]["failure"].resource_description == "The base catalog"

    def test_empty_resource_rlinks_not_tried(self):
        bm = _resource_xml(_EMPTY_UUID)
        obj = _load_profile(f"#{_EMPTY_UUID}", bm)
        assert obj.import_list[0]["failure"].rlinks_tried == []

    def test_base64_only_resource_is_not_empty(self):
        """A resource with only base64 must NOT trigger RESOURCE_NO_VIABLE_CONTENT."""
        bm = _resource_xml(_EMPTY_UUID, has_base64=True)
        obj = _load_profile(f"#{_EMPTY_UUID}", bm)
        # base64 is viable — failure code must not be NO_VIABLE_CONTENT
        failure = obj.import_list[0].get("failure")
        if failure is not None:
            assert failure.code != ImportFailureCode.RESOURCE_NO_VIABLE_CONTENT

    # --- Rlinks found but all fail to load ---

    def test_rlink_all_fail_code(self):
        bm = _resource_xml(_RLINK_UUID, rlinks=["/tmp/_oscal_test_nonexistent_ZZZ.xml"])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        failure = obj.import_list[0]["failure"]
        assert failure is not None
        assert failure.code == ImportFailureCode.LOCAL_NOT_FOUND

    def test_rlink_all_fail_rlinks_tried_populated(self):
        bm = _resource_xml(_RLINK_UUID, rlinks=["/tmp/_oscal_test_nonexistent_ZZZ.xml"])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        failure = obj.import_list[0]["failure"]
        assert len(failure.rlinks_tried) >= 1

    def test_rlink_all_fail_carries_resource_uuid(self):
        bm = _resource_xml(_RLINK_UUID, rlinks=["/tmp/_oscal_test_nonexistent_ZZZ.xml"])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        assert obj.import_list[0]["failure"].resource_uuid == _RLINK_UUID

    def test_rlink_all_fail_carries_resource_title(self):
        bm = _resource_xml(_RLINK_UUID, rlinks=["/tmp/_oscal_test_nonexistent_ZZZ.xml"],
                           title="My Catalog")
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        assert obj.import_list[0]["failure"].resource_title == "My Catalog"

    def test_rlink_resolved_succeeds_no_failure(self):
        """When the rlink resolves to a valid catalog, failure must be None."""
        bm = _resource_xml(_RLINK_UUID, rlinks=[_CATALOG_PATH])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        assert obj.import_list[0]["status"] == ImportState.READY
        assert obj.import_list[0]["failure"] is None


# ===========================================================================
# resolve_imports() — full URI failure cases
# ===========================================================================

class TestUriFailures:
    def test_local_not_found_code(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent_ABC.xml")
        assert obj.import_list[0]["failure"].code == ImportFailureCode.LOCAL_NOT_FOUND

    def test_local_not_found_uri_in_failure(self):
        href = "/tmp/_oscal_test_nonexistent_ABC.xml"
        obj  = _load_profile(href)
        assert obj.import_list[0]["failure"].uri != ""

    def test_local_not_found_is_not_fragment_ref(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent_ABC.xml")
        assert obj.import_list[0]["failure"].is_fragment_ref is False

    def test_unsupported_scheme_code(self):
        obj = _load_profile("s3://bucket/catalog.xml")
        assert obj.import_list[0]["failure"].code == ImportFailureCode.REMOTE_UNSUPPORTED

    def test_unsupported_scheme_uri_in_failure(self):
        obj = _load_profile("s3://bucket/catalog.xml")
        assert obj.import_list[0]["failure"].uri != ""

    def test_unsupported_scheme_is_not_fragment_ref(self):
        obj = _load_profile("s3://bucket/catalog.xml")
        assert obj.import_list[0]["failure"].is_fragment_ref is False

    def test_remote_auth_required_code(self):
        http_err = HTTPError("https://example.com/c.xml", 401, "Unauthorized", {}, None)
        with patch("oscal.oscal_source.download_file", side_effect=http_err):
            obj = _load_profile("https://example.com/c.xml")
        failure = obj.import_list[0].get("failure")
        assert failure is not None
        assert failure.code == ImportFailureCode.REMOTE_AUTH_REQUIRED

    def test_remote_unreachable_code(self):
        with patch("oscal.oscal_source.download_file", side_effect=ConnectionError("timeout")):
            obj = _load_profile("https://example.com/c.xml")
        failure = obj.import_list[0].get("failure")
        assert failure is not None
        assert failure.code == ImportFailureCode.REMOTE_UNREACHABLE

    def test_remote_failure_uri_matches_href(self):
        http_err = HTTPError("https://example.com/c.xml", 401, "Unauthorized", {}, None)
        with patch("oscal.oscal_source.download_file", side_effect=http_err):
            obj = _load_profile("https://example.com/c.xml")
        assert "example.com" in obj.import_list[0]["failure"].uri

    def test_uri_success_has_no_failure(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        assert all(e["failure"] is None for e in obj.import_list)


# ===========================================================================
# failed_imports property
# ===========================================================================

class TestFailedImportsProperty:
    def test_returns_only_failed_entries(self):
        obj = _load_profile("#not-a-uuid")
        assert len(obj.failed_imports) == 1
        assert obj.failed_imports[0]["failure"] is not None

    def test_empty_when_all_succeed(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        assert obj.failed_imports == []

    def test_each_entry_has_failure_field(self):
        obj = _load_profile("#not-a-uuid")
        for entry in obj.failed_imports:
            assert "failure" in entry

    def test_count_matches_distinct_failures(self):
        """Two import statements both failing must appear as two entries."""
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-000000000002">
  <metadata>
    <title>Multi-Fail Profile</title>
    <last-modified>2026-04-28T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  <import href="#not-a-uuid"><include-all/></import>
  <import href="/tmp/_oscal_test_nonexistent_DEF.xml"><include-all/></import>
  <merge><combine method="keep"/><as-is>true</as-is></merge>
</profile>"""
        obj = OSCAL.loads(xml)
        assert len(obj.failed_imports) == 2

    def test_mixed_success_and_failure_counts(self):
        """One direct success + one missing file = one entry in failed_imports."""
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-000000000003">
  <metadata>
    <title>Mixed Profile</title>
    <last-modified>2026-04-28T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  <import href="{_CATALOG_PATH}"><include-all/></import>
  <import href="/tmp/_oscal_test_nonexistent_GHI.xml"><include-all/></import>
  <merge><combine method="keep"/><as-is>true</as-is></merge>
</profile>"""
        obj = OSCAL.loads(xml)
        assert len(obj.import_list) == 2
        assert len(obj.failed_imports) == 1
        assert obj.failed_imports[0]["failure"].code == ImportFailureCode.LOCAL_NOT_FOUND


# ===========================================================================
# Entry structure — failure field always present
# ===========================================================================

class TestEntryFailureField:
    def test_failure_field_present_on_success(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        for entry in obj.import_list:
            assert "failure" in entry

    def test_failure_field_none_on_success(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        for entry in obj.import_list:
            assert entry["failure"] is None

    def test_failure_field_present_on_invalid(self):
        obj = _load_profile("#not-a-uuid")
        assert "failure" in obj.import_list[0]

    def test_failure_field_is_import_failure_instance(self):
        obj = _load_profile("#not-a-uuid")
        assert isinstance(obj.import_list[0]["failure"], ImportFailure)

    def test_imports_not_resolved_when_any_fail(self):
        obj = _load_profile("#not-a-uuid")
        assert obj.imports_resolved is False
        assert obj.content_state == ContentState.VALID

    def test_imports_resolved_when_all_succeed(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        assert obj.imports_resolved is True
        assert obj.content_state == ContentState.IMPORTS_RESOLVED


# ===========================================================================
# href_list structure
# ===========================================================================

class TestHrefList:
    def test_direct_href_has_original_true(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        entry = obj.import_list[0]
        assert entry["href_list"][0]["original"] is True

    def test_direct_href_list_starts_with_raw_href(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        entry = obj.import_list[0]
        assert entry["href_list"][0]["href"] == "/tmp/_oscal_test_nonexistent.xml"

    def test_failed_item_gets_status_invalid(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        entry = obj.import_list[0]
        # At least one item in href_list must have been tried and stamped INVALID
        statuses = [item.get("status") for item in entry["href_list"] if "status" in item]
        assert ImportState.INVALID in statuses

    def test_fragment_initial_item_is_raw_href(self):
        bm = _resource_xml(_RLINK_UUID, rlinks=["/tmp/_oscal_test_nonexistent.xml"])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        entry = obj.import_list[0]
        assert entry["href_list"][0]["href"] == f"#{_RLINK_UUID}"
        assert entry["href_list"][0]["original"] is True

    def test_fragment_rlinks_appended_with_original_true(self):
        bm = _resource_xml(_RLINK_UUID, rlinks=["/tmp/a.xml", "/tmp/b.xml"])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        entry = obj.import_list[0]
        rlink_hrefs = [item["href"] for item in entry["href_list"][1:]]
        assert "/tmp/a.xml" in rlink_hrefs
        assert "/tmp/b.xml" in rlink_hrefs
        for item in entry["href_list"][1:]:
            assert item.get("original") is True

    def test_fragment_initial_item_has_no_status(self):
        """The #uuid placeholder is skipped — it never gets a status stamped on it."""
        bm = _resource_xml(_RLINK_UUID, rlinks=["/tmp/_oscal_test_nonexistent.xml"])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        entry = obj.import_list[0]
        assert "status" not in entry["href_list"][0]

    def test_successful_item_gets_status_ready(self):
        bm = _resource_xml(_RLINK_UUID, rlinks=[_CATALOG_PATH])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        entry = obj.import_list[0]
        rlink_items = [i for i in entry["href_list"] if not i["href"].startswith("#")]
        assert any(i.get("status") == ImportState.READY for i in rlink_items)

    def test_items_after_first_success_have_no_status(self):
        """href_list items that were never attempted carry no status key."""
        bm = _resource_xml(_RLINK_UUID, rlinks=[_CATALOG_PATH, "/tmp/never_tried.xml"])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        entry = obj.import_list[0]
        # Find the never-tried item (last rlink)
        last_item = [i for i in entry["href_list"] if "/tmp/never_tried.xml" in i["href"]]
        assert len(last_item) == 1
        assert "status" not in last_item[0]


# ===========================================================================
# retry_import — href_list and href_valid behaviour
# ===========================================================================

class TestRetryImport:
    def test_retry_success_appends_to_href_list(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        entry = obj.import_list[0]
        hrefs = [i["href"] for i in entry["href_list"]]
        assert _CATALOG_PATH in hrefs

    def test_retry_success_item_has_original_false(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        entry = obj.import_list[0]
        retry_items = [i for i in entry["href_list"] if not i.get("original", True)]
        assert len(retry_items) == 1
        assert retry_items[0]["status"] == ImportState.READY

    def test_retry_success_returns_true(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        result = obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        assert result is True

    def test_retry_success_sets_status_ready(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        assert obj.import_list[0]["status"] == ImportState.READY

    def test_retry_success_clears_failure(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        assert obj.import_list[0]["failure"] is None

    def test_retry_success_sets_href_valid(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        assert obj.import_list[0]["href_valid"] != ""

    def test_retry_success_populates_object(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        assert obj.import_list[0]["object"] is not None

    def test_retry_success_advances_content_state(self):
        """A successful retry that resolves the last failed import must advance content_state."""
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        assert obj.content_state == ContentState.VALID
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        assert obj.content_state == ContentState.IMPORTS_RESOLVED

    def test_retry_success_sets_imports_resolved(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        assert obj.imports_resolved is True

    def test_retry_failure_returns_false(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        result = obj.retry_import("/tmp/_oscal_test_nonexistent.xml", "/tmp/_still_nonexistent.xml")
        assert result is False

    def test_retry_failure_clears_href_valid(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", "/tmp/_still_nonexistent.xml")
        assert obj.import_list[0]["href_valid"] == ""

    def test_retry_failure_appends_invalid_item(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", "/tmp/_still_nonexistent.xml")
        entry = obj.import_list[0]
        retry_items = [i for i in entry["href_list"] if not i.get("original", True)]
        assert len(retry_items) == 1
        assert retry_items[0]["status"] == ImportState.INVALID

    def test_retry_failure_sets_status_invalid(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", "/tmp/_still_nonexistent.xml")
        assert obj.import_list[0]["status"] == ImportState.INVALID

    def test_retry_failure_sets_new_failure(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", "/tmp/_still_nonexistent.xml")
        assert obj.import_list[0]["failure"] is not None

    def test_retry_failure_does_not_advance_content_state(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        assert obj.content_state == ContentState.VALID
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", "/tmp/_still_nonexistent.xml")
        assert obj.content_state == ContentState.VALID

    def test_retry_failure_reverts_imports_resolved_state(self):
        """If a retry causes a previously IMPORTS_RESOLVED state to break, state reverts to VALID."""
        # Start with a fully resolved profile
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        assert obj.content_state == ContentState.IMPORTS_RESOLVED
        # Now retry with a bad path — the import goes INVALID again
        obj.retry_import(_CATALOG_PATH, "/tmp/_now_bad.xml")
        assert obj.content_state == ContentState.VALID
        assert obj.imports_resolved is False

    def test_partial_retry_success_does_not_advance_state(self):
        """Fixing one of two failed imports must not advance to IMPORTS_RESOLVED."""
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-000000000005">
  <metadata>
    <title>Partial Retry Profile</title>
    <last-modified>2026-04-28T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  <import href="/tmp/_oscal_partial_retry_a.xml"><include-all/></import>
  <import href="/tmp/_oscal_partial_retry_b.xml"><include-all/></import>
  <merge><combine method="keep"/><as-is>true</as-is></merge>
</profile>"""
        obj = OSCAL.loads(xml)
        assert obj.content_state == ContentState.VALID
        # Fix only the first import
        obj.retry_import("/tmp/_oscal_partial_retry_a.xml", _CATALOG_PATH)
        # Second import still invalid — must not advance to IMPORTS_RESOLVED
        assert obj.content_state == ContentState.VALID
        assert obj.imports_resolved is False

    def test_retry_unknown_href_returns_false(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        result = obj.retry_import("/tmp/completely_unknown.xml", _CATALOG_PATH)
        assert result is False

    def test_retry_matches_by_href_list_item(self):
        """retry_import should find entry when failed_href matches an href_list item."""
        bm = _resource_xml(_RLINK_UUID, rlinks=["/tmp/_oscal_test_rlink_nonexistent.xml"])
        obj = _load_profile(f"#{_RLINK_UUID}", bm)
        result = obj.retry_import("/tmp/_oscal_test_rlink_nonexistent.xml", _CATALOG_PATH)
        assert result is True


# ===========================================================================
# retry_import — import_tree reflects updated status
# ===========================================================================

class TestRetryImportTree:
    def test_tree_reflects_success_status(self):
        """import_tree must show READY after a successful retry."""
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        tree_entry = obj.import_tree["imports"][0]
        assert tree_entry["status"] == ImportState.READY

    def test_tree_reflects_success_clears_failure(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        tree_entry = obj.import_tree["imports"][0]
        assert tree_entry["failure"] is None

    def test_tree_reflects_success_has_child_imports(self):
        """A successfully retried import must expose its own import subtree."""
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        tree_entry = obj.import_tree["imports"][0]
        assert "imports" in tree_entry

    def test_tree_reflects_failure_status(self):
        """import_tree must show INVALID after a failed retry."""
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", "/tmp/_still_nonexistent.xml")
        tree_entry = obj.import_tree["imports"][0]
        assert tree_entry["status"] == ImportState.INVALID

    def test_tree_reflects_failure_carries_failure_object(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", "/tmp/_still_nonexistent.xml")
        tree_entry = obj.import_tree["imports"][0]
        assert isinstance(tree_entry["failure"], ImportFailure)

    def test_tree_reflects_failure_empty_imports(self):
        """A failed import entry must have an empty imports list in the tree."""
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", "/tmp/_still_nonexistent.xml")
        tree_entry = obj.import_tree["imports"][0]
        assert tree_entry["imports"] == []

    def test_tree_is_rebuilt_after_retry(self):
        """Each retry must force a fresh tree; stale cached tree must not be returned."""
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        # Access tree before retry to populate the cache
        _ = obj.import_tree
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        # Tree must now reflect the new status, not the pre-retry snapshot
        assert obj.import_tree["imports"][0]["status"] == ImportState.READY

    def test_tree_href_list_includes_retry_item(self):
        """The retry href must appear in the import entry's href_list within the tree."""
        obj = _load_profile("/tmp/_oscal_test_nonexistent.xml")
        obj.retry_import("/tmp/_oscal_test_nonexistent.xml", _CATALOG_PATH)
        tree_entry = obj.import_tree["imports"][0]
        retry_hrefs = [i["href"] for i in tree_entry.get("href_list", [])]
        assert any(_CATALOG_PATH in h for h in retry_hrefs)


# ===========================================================================
# import_tree — root node href_list
# ===========================================================================

class TestImportTreeRootNode:
    def test_root_node_has_href_list(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        assert "href_list" in obj.import_tree

    def test_root_href_list_contains_working_href(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        hrefs = [i["href"] for i in obj.import_tree["href_list"]]
        assert obj.href in hrefs or obj.href_original in hrefs

    def test_root_href_list_working_href_has_status_ready(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        tree = obj.import_tree
        ready_items = [i for i in tree["href_list"] if i.get("status") == ImportState.READY]
        assert len(ready_items) >= 1

    def test_root_href_list_items_have_original_true(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        for item in obj.import_tree["href_list"]:
            assert item.get("original") is True

    def test_root_href_list_single_item_when_hrefs_match(self):
        """When href and href_original are the same, only one item in the list."""
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        if obj.href == obj.href_original:
            assert len(obj.import_tree["href_list"]) == 1


# ===========================================================================
# walk_imports — scope parameter
# ===========================================================================

class TestWalkImports:
    def _two_import_profile(self) -> OSCAL:
        """Profile with one successful and one failing import."""
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-000000000004">
  <metadata>
    <title>Walk Test Profile</title>
    <last-modified>2026-04-28T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  <import href="{_CATALOG_PATH}"><include-all/></import>
  <import href="/tmp/_oscal_test_walk_nonexistent.xml"><include-all/></import>
  <merge><combine method="keep"/><as-is>true</as-is></merge>
</profile>"""
        return OSCAL.loads(xml)

    def test_default_scope_visits_only_successful(self):
        obj = self._two_import_profile()
        visited = []
        obj.walk_imports(lambda e, d: visited.append(e["status"]))
        assert all(s == ImportState.READY for s in visited)

    def test_scope_failed_visits_only_failed(self):
        obj = self._two_import_profile()
        visited = []
        obj.walk_imports(lambda e, d: visited.append(e["status"]), scope="failed")
        assert len(visited) >= 1
        assert all(s == ImportState.INVALID for s in visited)

    def test_scope_all_visits_both(self):
        obj = self._two_import_profile()
        visited = []
        obj.walk_imports(lambda e, d: visited.append(e["status"]), scope="all")
        statuses = set(visited)
        assert ImportState.READY in statuses
        assert ImportState.INVALID in statuses

    def test_scope_all_count_matches_import_list(self):
        obj = self._two_import_profile()
        visited = []
        obj.walk_imports(lambda e, d: visited.append(1), scope="all")
        # Top level: 2 imports; successful one may recurse into its own imports
        assert len(visited) >= 2

    def test_successful_scope_does_not_visit_failed(self):
        obj = self._two_import_profile()
        visited_hrefs = []
        obj.walk_imports(lambda e, d: visited_hrefs.append(e.get("href_original", "")))
        assert "/tmp/_oscal_test_walk_nonexistent.xml" not in visited_hrefs

    def test_failed_scope_does_not_visit_successful(self):
        obj = self._two_import_profile()
        visited_hrefs = []
        obj.walk_imports(
            lambda e, d: visited_hrefs.append(e.get("href_original", "")),
            scope="failed",
        )
        assert _CATALOG_PATH not in visited_hrefs

    def test_walk_provides_depth(self):
        obj = OSCAL.load(os.path.join(_IMPORTS_DIR, "test_profile_direct.xml"))
        depths = []
        obj.walk_imports(lambda e, d: depths.append(d))
        assert all(d == 0 for d in depths)  # direct imports are depth 0


# ===========================================================================
# Non-fragment failure rlinks_tried
# ===========================================================================

class TestNonFragmentRlinksTried:
    def test_direct_href_failure_has_rlinks_tried(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent_XYZ.xml")
        failure = obj.import_list[0]["failure"]
        assert failure is not None
        assert len(failure.rlinks_tried) >= 1

    def test_direct_href_failure_rlinks_tried_contains_attempted_path(self):
        obj = _load_profile("/tmp/_oscal_test_nonexistent_XYZ.xml")
        failure = obj.import_list[0]["failure"]
        assert any("_oscal_test_nonexistent_XYZ" in r for r in failure.rlinks_tried)
