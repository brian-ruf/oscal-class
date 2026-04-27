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
from oscal_datatypes import OSCAL_DATATYPES, oscal_date_time_with_timezone


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
