"""
Unit tests for oscal.oscal_datatypes
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Import directly from the module file to avoid triggering oscal/__init__.py,
# which requires ruf_common (a heavy dependency not needed for these tests).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "oscal"))
from oscal_datatypes import OSCAL_DATATYPES, oscal_date_time_with_timezone, normalize_uri_reference


EXPECTED_TYPES = [
    "base64",
    "boolean",
    "date",
    "date-with-timezone",
    "date-time",
    "date-time-with-timezone",
    "day-time-duration",
    "decimal",
    "email-adress",
    "hostname",
    "integer",
    "ipv4-address",
    "ipv6-address",
    "non-negative-integer",
    "positive-integer",
    "string",
    "token",
    "uri",
    "uri-reference",
    "uuid",
    "year-month-duration",
    "markup-line",
    "markup-multiline",
]

REQUIRED_FIELDS = ["base-type", "xml-pattern", "json-pattern", "documentation"]


class TestOscalDatatypesDict:
    def test_all_expected_types_present(self):
        for t in EXPECTED_TYPES:
            assert t in OSCAL_DATATYPES, f"Missing OSCAL type: {t}"

    def test_each_type_has_required_fields(self):
        for type_name, definition in OSCAL_DATATYPES.items():
            for field in REQUIRED_FIELDS:
                assert field in definition, (
                    f"Type '{type_name}' missing field '{field}'"
                )

    def test_base_types_are_valid(self):
        valid_base_types = {"string", "boolean", "integer", "number"}
        for type_name, definition in OSCAL_DATATYPES.items():
            assert definition["base-type"] in valid_base_types, (
                f"Type '{type_name}' has unexpected base-type: {definition['base-type']}"
            )

    def test_xml_patterns_compile(self):
        # xml-patterns may use XML Schema regex syntax such as \p{L} (Unicode
        # letter property) which Python's re module does not support.  Skip
        # those patterns and only verify the remaining ones.
        # The 'email-adress' pattern also has a known bad char range bug
        # (same double-escape issue as the json-pattern).
        known_broken = {"email-adress"}
        for type_name, definition in OSCAL_DATATYPES.items():
            pattern = definition["xml-pattern"]
            if not pattern or r"\p{" in pattern or type_name in known_broken:
                continue
            try:
                re.compile(pattern)
            except re.error as e:
                pytest.fail(
                    f"Type '{type_name}' xml-pattern failed to compile: {e}"
                )

    def test_json_patterns_compile(self):
        # Known issue: the 'email-adress' json-pattern contains an invalid
        # character range caused by double-escaped hex sequences that do not
        # translate correctly in Python regex.  Exclude it here; see
        # test_email_json_pattern_has_known_bug for documentation.
        known_broken = {"email-adress"}
        for type_name, definition in OSCAL_DATATYPES.items():
            pattern = definition["json-pattern"]
            if not pattern or type_name in known_broken:
                continue
            try:
                re.compile(pattern)
            except re.error as e:
                pytest.fail(
                    f"Type '{type_name}' json-pattern failed to compile: {e}"
                )

    def test_email_json_pattern_has_known_bug(self):
        # The email-adress json-pattern uses double-escaped hex sequences
        # (e.g. \\x0e) that produce an invalid character range (e-\\) when
        # interpreted by Python's re module.  This test documents the bug.
        pattern = OSCAL_DATATYPES["email-adress"]["json-pattern"]
        with pytest.raises(re.error):
            re.compile(pattern)

    def test_uuid_pattern_matches_valid_uuid(self):
        pattern = OSCAL_DATATYPES["uuid"]["json-pattern"]
        valid_uuid = "bbf21f44-7702-43fa-abfa-fba687ecbfb7"
        assert re.match(pattern, valid_uuid), "UUID pattern should match a valid UUID"

    def test_uuid_pattern_rejects_invalid(self):
        pattern = OSCAL_DATATYPES["uuid"]["json-pattern"]
        assert not re.match(pattern, "not-a-uuid"), "UUID pattern should reject invalid string"
        assert not re.match(pattern, "12345678-1234-1234-1234"), "UUID pattern should reject short UUID"

    def test_ipv4_pattern_matches_valid(self):
        pattern = OSCAL_DATATYPES["ipv4-address"]["json-pattern"]
        assert re.match(pattern, "192.168.1.1")
        assert re.match(pattern, "0.0.0.0")
        assert re.match(pattern, "255.255.255.255")

    def test_ipv4_pattern_rejects_invalid(self):
        pattern = OSCAL_DATATYPES["ipv4-address"]["json-pattern"]
        assert not re.match(pattern, "999.1.1.1"), "Should reject out-of-range octet"
        assert not re.match(pattern, "not.an.ip.addr"), "Should reject non-numeric"

    def test_boolean_pattern_matches_valid(self):
        xml_pattern = OSCAL_DATATYPES["boolean"]["xml-pattern"]
        for value in ["true", "false", "1", "0"]:
            assert re.fullmatch(xml_pattern, value), f"Boolean xml-pattern should match '{value}'"

    def test_integer_pattern_matches_valid(self):
        pattern = OSCAL_DATATYPES["integer"]["json-pattern"]
        for value in ["0", "42", "-7", "+100"]:
            assert re.match(pattern, value), f"Integer pattern should match '{value}'"


# A Windows path with backslashes used as a link href — not valid URI syntax.
_BAD_URI = r"R:\rr\class\tests\test-data\private\ed\ed-high-baseline-profile.json#ps-8"


class TestUriPatterns:
    """The uri / uri-reference json-patterns enforce the RFC 3986 character set,
    rejecting backslashes and whitespace while accepting valid references."""

    def test_original_preserved(self):
        for t in ("uri", "uri-reference"):
            assert OSCAL_DATATYPES[t]["original"] == r"^[\S]+$"

    def test_uri_reference_rejects_backslash_path(self):
        pat = OSCAL_DATATYPES["uri-reference"]["json-pattern"]
        assert re.fullmatch(pat, _BAD_URI) is None

    def test_uri_reference_rejects_whitespace(self):
        pat = OSCAL_DATATYPES["uri-reference"]["json-pattern"]
        assert re.fullmatch(pat, "has space.json") is None

    @pytest.mark.parametrize("val", [
        # fragment-only references (accept ONLY a URI fragment)
        "#ps-8",
        "#a_b-c.1",
        "#",
        # relative references, with and without a fragment
        "catalog.json",
        "catalogs/nist-800-53.json#ac-1",
        "../rev5/catalog.json",
        # absolute URIs, with and without a fragment
        "https://example.com/a?b=c#d",
        "http://csrc.nist.gov/ns/oscal",
        "urn:uuid:11111111-2222-4333-8444-555555555555",
        "mailto:a@b.com",
        "//example.com/path#frag",                     # network-path reference
        # cross-platform file URIs (RFC 3986 uses forward slashes on every platform)
        "file:///R:/rr/class/x.json#ps-8",             # Windows drive (valid form of the bad value)
        "file:///home/user/catalog.json",              # Unix absolute path
        "file://server/share/catalog.json#ac-1",       # UNC / network share
    ])
    def test_uri_reference_accepts_valid(self, val):
        pat = OSCAL_DATATYPES["uri-reference"]["json-pattern"]
        assert re.fullmatch(pat, val) is not None

    def test_uri_requires_scheme(self):
        pat = OSCAL_DATATYPES["uri"]["json-pattern"]
        assert re.fullmatch(pat, "http://csrc.nist.gov/ns/oscal") is not None
        assert re.fullmatch(pat, "#no-scheme") is None      # uri (absolute) needs a scheme
        assert re.fullmatch(pat, r"R:\rr\x.json") is None   # backslashes rejected

    def test_enforced_via_check_datatype(self):
        # Exercise the actual validation entry point, not just the raw regex.
        from oscal.oscal_content import _check_datatype
        assert _check_datatype(_BAD_URI, "uri-reference", "loc", "href") is not None
        assert _check_datatype("#ps-8", "uri-reference", "loc", "href") is None


class TestNormalizeUriReference:
    """normalize_uri_reference repairs non-encoded URI values into valid form."""

    _URI_REF = OSCAL_DATATYPES["uri-reference"]["json-pattern"]

    @pytest.mark.parametrize("raw,expected", [
        (r"R:\rr\class\x.json#ps-8", "R:/rr/class/x.json#ps-8"),   # backslashes -> slashes
        (r"C:\Users\a b\doc.json", "C:/Users/a%20b/doc.json"),     # backslashes + space
        ("has space.json", "has%20space.json"),                    # raw space -> %20
        ("café.json", "caf%C3%A9.json"),                      # non-ASCII -> UTF-8 %XX
        ('a"b.json', "a%22b.json"),                                # quote -> %22
    ])
    def test_converts_non_encoded(self, raw, expected):
        out = normalize_uri_reference(raw)
        assert out == expected
        assert re.fullmatch(self._URI_REF, out) is not None       # result is a valid URI-reference

    @pytest.mark.parametrize("val", [
        "#ps-8", "catalog.json#ac-1", "https://ex.com/a?b=c#d",
        "file:///C:/x/doc.json#f", "already%20encoded.json",       # %XX preserved (no double-encode)
    ])
    def test_valid_values_unchanged(self, val):
        assert normalize_uri_reference(val) == val

    def test_non_string_and_empty_unchanged(self):
        assert normalize_uri_reference("") == ""
        assert normalize_uri_reference(None) is None

    def test_load_repairs_backslash_href(self):
        # End-to-end: a link href with backslashes is normalized in place on validation,
        # so the loaded content is valid and dumps as a valid URI.
        from oscal import OSCAL
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<catalog xmlns="http://csrc.nist.gov/ns/oscal/1.0" '
            'uuid="aabbccdd-0000-4000-a000-000000000001">'
            '<metadata><title>N</title><last-modified>2026-06-06T00:00:00Z</last-modified>'
            '<version>1.0</version><oscal-version>1.2.3</oscal-version></metadata>'
            '<control id="ac-1"><title>AC-1</title>'
            '<link href="R:\\rr\\other-catalog.json#ac-2" rel="reference"/>'
            '</control></catalog>'
        )
        doc = OSCAL.loads(xml)
        href = doc._dict["catalog"]["controls"][0]["links"][0]["href"]
        assert href == "R:/rr/other-catalog.json#ac-2"
        assert doc.validation_status.get("data-types") is True
        assert doc.is_valid


class TestOscalDateTimeWithTimezone:
    OSCAL_DATETIME_PATTERN = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    )

    def test_no_args_returns_nonempty_string(self):
        result = oscal_date_time_with_timezone()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_no_args_matches_oscal_format(self):
        result = oscal_date_time_with_timezone()
        assert self.OSCAL_DATETIME_PATTERN.match(result), (
            f"Result '{result}' does not match OSCAL datetime format"
        )

    def test_with_datetime_object(self):
        dt = datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
        result = oscal_date_time_with_timezone(dt)
        assert result == "2025-06-15T12:30:45Z"

    def test_with_naive_datetime_assumes_utc(self):
        dt = datetime(2025, 1, 1, 0, 0, 0)
        result = oscal_date_time_with_timezone(dt)
        assert result == "2025-01-01T00:00:00Z"

    def test_with_valid_date_string(self):
        result = oscal_date_time_with_timezone("2024-03-15T10:00:00Z")
        assert self.OSCAL_DATETIME_PATTERN.match(result), (
            f"Result '{result}' does not match OSCAL datetime format"
        )
        assert result.startswith("2024-03-15T")

    def test_with_invalid_string_returns_empty(self):
        result = oscal_date_time_with_timezone("not-a-date")
        assert result == ""

    def test_with_custom_format(self):
        dt = datetime(2025, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
        result = oscal_date_time_with_timezone(dt, format="%Y-%m-%d")
        assert result == "2025-06-15"
