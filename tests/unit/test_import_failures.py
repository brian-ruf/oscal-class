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
    title_el   = f"<title>{title}</title>" if title else ""
    desc_el    = f"<description><p>{description}</p></description>" if description else ""
    rlink_els  = "".join(f'<rlink href="{r}"/>' for r in rlinks)
    base64_el  = '<base64 filename="d.xml">dGVzdA==</base64>' if has_base64 else ""
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
        assert result["rlinks"] == ["/tmp/a.xml", "/tmp/b.xml"]

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
        with patch("oscal.oscal_content.download_file", side_effect=http_err):
            with pytest.raises(ImportLoadError) as exc_info:
                load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_AUTH_REQUIRED

    def test_http_403_raises_auth_required(self):
        ref = OscalRef(href="https://example.com/catalog.xml")
        classify_source(ref)
        http_err = HTTPError("https://example.com/catalog.xml", 403, "Forbidden", {}, None)
        with patch("oscal.oscal_content.download_file", side_effect=http_err):
            with pytest.raises(ImportLoadError) as exc_info:
                load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_AUTH_REQUIRED

    def test_connection_error_raises_unreachable(self):
        ref = OscalRef(href="https://example.com/catalog.xml")
        classify_source(ref)
        with patch("oscal.oscal_content.download_file", side_effect=ConnectionError("timeout")):
            with pytest.raises(ImportLoadError) as exc_info:
                load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_UNREACHABLE

    def test_url_error_raises_unreachable(self):
        ref = OscalRef(href="https://example.com/catalog.xml")
        classify_source(ref)
        with patch("oscal.oscal_content.download_file", side_effect=URLError("no route")):
            with pytest.raises(ImportLoadError) as exc_info:
                load_source(ref)
        assert exc_info.value.code == ImportFailureCode.REMOTE_UNREACHABLE

    def test_http_500_raises_unreachable(self):
        ref = OscalRef(href="https://example.com/catalog.xml")
        classify_source(ref)
        http_err = HTTPError("https://example.com/catalog.xml", 500, "Server Error", {}, None)
        with patch("oscal.oscal_content.download_file", side_effect=http_err):
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
        with patch("oscal.oscal_content.download_file", side_effect=http_err):
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
        with patch("oscal.oscal_content.download_file", side_effect=http_err):
            obj = _load_profile("https://example.com/c.xml")
        failure = obj.import_list[0].get("failure")
        assert failure is not None
        assert failure.code == ImportFailureCode.REMOTE_AUTH_REQUIRED

    def test_remote_unreachable_code(self):
        with patch("oscal.oscal_content.download_file", side_effect=ConnectionError("timeout")):
            obj = _load_profile("https://example.com/c.xml")
        failure = obj.import_list[0].get("failure")
        assert failure is not None
        assert failure.code == ImportFailureCode.REMOTE_UNREACHABLE

    def test_remote_failure_uri_matches_href(self):
        http_err = HTTPError("https://example.com/c.xml", 401, "Unauthorized", {}, None)
        with patch("oscal.oscal_content.download_file", side_effect=http_err):
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
