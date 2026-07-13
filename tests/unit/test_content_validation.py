"""
Negative tests for OSCAL content loading and validation.

Covers:
  - File not found
  - Unsupported / unrecognized format (not XML, JSON, or YAML)
  - Non-UTF-8 encoded file
  - Malformed XML / JSON / YAML (well-formed check fails)
  - Well-formed but OSCAL schema-invalid content (each format)
"""
import os
import tempfile

import pytest

from oscal import OSCAL, Catalog, Profile

# ---------------------------------------------------------------------------
# Fixtures — schema-valid structure but missing required fields
#
# These documents have the correct OSCAL root element and oscal-version so
# they pass model/version detection, but are missing required fields (e.g.
# catalog.uuid and metadata.last-modified) so schema validation fails.
# All use OSCAL v1.1.3, which is present in the test support database.
# ---------------------------------------------------------------------------

_XML_SCHEMA_INVALID = """\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="http://csrc.nist.gov/ns/oscal/1.0">
  <metadata>
    <title>Schema Invalid Catalog</title>
    <version>1.0</version>
    <oscal-version>1.1.3</oscal-version>
  </metadata>
</catalog>
"""

# Missing required catalog.uuid and metadata.last-modified
_JSON_SCHEMA_INVALID = """\
{
  "catalog": {
    "metadata": {
      "title": "Schema Invalid Catalog",
      "version": "1.0",
      "oscal-version": "1.1.3"
    }
  }
}
"""

_YAML_SCHEMA_INVALID = """\
catalog:
  metadata:
    title: Schema Invalid Catalog
    version: "1.0"
    oscal-version: "1.1.3"
"""


# ===========================================================================
# File not found
# ===========================================================================
class TestFileNotFound:
    def test_load_missing_file_returns_object(self):
        """load() on a nonexistent path must not raise — it returns an OSCAL instance."""
        obj = OSCAL.load("/nonexistent/path/missing.json")
        assert obj is not None

    def test_load_missing_file_is_not_valid(self):
        """load() on a nonexistent path produces is_valid=False."""
        obj = OSCAL.load("/nonexistent/path/missing.json")
        assert obj.is_valid is False

    def test_load_missing_file_has_no_model(self):
        """load() on a nonexistent path produces an empty model string."""
        obj = OSCAL.load("/nonexistent/path/missing.json")
        assert obj.model == ""


# ===========================================================================
# Unsupported / unrecognized format
# ===========================================================================
class TestUnsupportedFormat:
    def test_loads_csv_string_is_not_valid(self):
        """Content that is not XML, JSON, or YAML returns is_valid=False."""
        obj = OSCAL.loads("id,title,description\n1,Test,Row one\n2,Other,Row two\n")
        assert obj is not None
        assert obj.is_valid is False
        assert obj.model == ""

    def test_loads_empty_string_is_not_valid(self):
        """An empty string returns is_valid=False."""
        obj = OSCAL.loads("")
        assert obj is not None
        assert obj.is_valid is False

    def test_load_binary_file_is_not_valid(self):
        """A file containing arbitrary binary bytes must not raise and must return is_valid=False."""
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as fh:
            fh.write(b"\xff\xfe\x00\x01binary\xfe\xff" * 16)
            path = fh.name
        try:
            obj = OSCAL.load(path)
            assert obj is not None
            assert obj.is_valid is False
            assert obj.model == ""
        finally:
            os.unlink(path)

    def test_load_latin1_encoded_file_is_not_valid(self):
        """A file written in Latin-1 (not UTF-8) must not raise and must return is_valid=False."""
        latin1_bytes = "<?xml version='1.0'?><nota>\xe9\xe0\xfc</nota>".encode("latin-1")
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as fh:
            fh.write(latin1_bytes)
            path = fh.name
        try:
            obj = OSCAL.load(path)
            assert obj is not None
            assert obj.is_valid is False
        finally:
            os.unlink(path)


# ===========================================================================
# Malformed content — well-formed check fails before OSCAL validation
# ===========================================================================
class TestMalformedContent:
    def test_malformed_xml_does_not_raise(self):
        """Syntactically broken XML must not raise an exception."""
        OSCAL.loads("<catalog><metadata><title>Unclosed</metadata>")

    def test_malformed_xml_is_not_valid(self):
        """Syntactically broken XML returns is_valid=False."""
        obj = OSCAL.loads("<catalog><metadata><title>Unclosed</metadata>")
        assert obj.is_valid is False
        assert obj.model == ""

    def test_malformed_json_does_not_raise(self):
        """Syntactically broken JSON must not raise an exception."""
        OSCAL.loads('{"catalog": {"metadata": {"title": "Bad" missing_comma}}}')

    def test_malformed_json_is_not_valid(self):
        """Syntactically broken JSON returns is_valid=False."""
        obj = OSCAL.loads('{"catalog": {"metadata": {"title": "Bad" missing_comma}}}')
        assert obj.is_valid is False
        assert obj.model == ""

    def test_malformed_yaml_does_not_raise(self):
        """YAML with a parse error must not raise an exception."""
        OSCAL.loads("catalog:\n  metadata:\n    title: [unclosed bracket\n")

    def test_malformed_yaml_is_not_valid(self):
        """YAML with a parse error returns is_valid=False."""
        obj = OSCAL.loads("catalog:\n  metadata:\n    title: [unclosed bracket\n")
        assert obj.is_valid is False
        assert obj.model == ""


# ===========================================================================
# Well-formed and OSCAL-shaped, but schema-invalid
# ===========================================================================
class TestSchemaInvalidContent:
    """Content that passes format detection and model/version identification
    but fails OSCAL schema validation (e.g., missing required fields)."""

    def test_xml_schema_invalid_does_not_raise(self):
        """Well-formed OSCAL-shaped XML that is schema-invalid must not raise."""
        OSCAL.loads(_XML_SCHEMA_INVALID)

    def test_xml_schema_invalid_model_is_identified(self):
        """Even schema-invalid XML should identify its model before failing."""
        obj = OSCAL.loads(_XML_SCHEMA_INVALID)
        assert obj.model == "catalog"

    def test_xml_schema_invalid_is_not_valid(self):
        """Schema-invalid XML returns is_valid=False."""
        obj = OSCAL.loads(_XML_SCHEMA_INVALID)
        assert obj.is_valid is False

    def test_xml_schema_valid_flag_is_false(self):
        """Schema-invalid XML sets validation_status['structure'] to False."""
        obj = OSCAL.loads(_XML_SCHEMA_INVALID)
        assert obj.validation_status["structure"] is False

    def test_json_schema_invalid_does_not_raise(self):
        """Well-formed OSCAL-shaped JSON that is schema-invalid must not raise."""
        OSCAL.loads(_JSON_SCHEMA_INVALID)

    def test_json_schema_invalid_model_is_identified(self):
        """Even schema-invalid JSON should identify its model before failing."""
        obj = OSCAL.loads(_JSON_SCHEMA_INVALID)
        assert obj.model == "catalog"

    def test_json_schema_invalid_is_not_valid(self):
        """Schema-invalid JSON returns is_valid=False."""
        obj = OSCAL.loads(_JSON_SCHEMA_INVALID)
        assert obj.is_valid is False

    def test_json_schema_valid_flag_is_false(self):
        """Schema-invalid JSON sets validation_status['structure'] to False."""
        obj = OSCAL.loads(_JSON_SCHEMA_INVALID)
        assert obj.validation_status["structure"] is False

    def test_yaml_schema_invalid_does_not_raise(self):
        """Well-formed OSCAL-shaped YAML that is schema-invalid must not raise."""
        OSCAL.loads(_YAML_SCHEMA_INVALID)

    def test_yaml_schema_invalid_model_is_identified(self):
        """Even schema-invalid YAML should identify its model before failing."""
        obj = OSCAL.loads(_YAML_SCHEMA_INVALID)
        assert obj.model == "catalog"

    def test_yaml_schema_invalid_is_not_valid(self):
        """Schema-invalid YAML returns is_valid=False."""
        obj = OSCAL.loads(_YAML_SCHEMA_INVALID)
        assert obj.is_valid is False

    def test_yaml_schema_valid_flag_is_false(self):
        """Schema-invalid YAML sets validation_status['structure'] to False."""
        obj = OSCAL.loads(_YAML_SCHEMA_INVALID)
        assert obj.validation_status["structure"] is False


# ===========================================================================
# Choice directive — metaschema choice members are mutually exclusive
# ===========================================================================
class TestChoiceValidation:

    def test_validation_status_has_choice_key(self):
        p = Profile.new("Choice Test")
        p.validate()
        assert "choice" in p.validation_status

    def test_valid_choice_passes(self):
        p = Profile.new("Choice Test")
        p.set_merge(as_is=True)          # exactly one member -> valid
        p.validate()
        assert p.validation_status["choice"] is True
        assert p.is_valid

    def test_two_members_violate_choice(self):
        p = Profile.new("Choice Test")
        p._dict["profile"]["merge"] = {"flat": {}, "as-is": True}   # two members
        p.validate()
        assert p.validation_status["choice"] is False
        assert p.is_valid is False
        errs = [e for e in p.validation_errors if e["error-type"] == "choice"]
        assert errs
        assert errs[0]["location"] == "/profile/merge"
        assert set(errs[0]["field"]) == {"flat", "as-is"}

    def test_three_members_violate_choice(self):
        p = Profile.new("Choice Test")
        p._dict["profile"]["merge"] = {"flat": {}, "as-is": True, "custom": {}}
        p.validate()
        assert p.validation_status["choice"] is False

    def test_optional_choice_with_zero_members_ok(self):
        """A choice member set may be empty when the choice is optional — e.g. a
        param with neither 'values' nor 'select' must not be flagged."""
        c = Catalog.new("Choice Test")
        c.create_control("[root]", "ac-1", title="A", params=["ac-1_prm_1"])
        c.validate()
        assert c.validation_status["choice"] is True

    def test_single_member_choice_ok(self):
        p = Profile.new("Choice Test")
        p.set_merge(flat=True)
        p.validate()
        assert p.validation_status["choice"] is True


# ===========================================================================
# Choice cardinality — required/optional & bounded/unbounded driven by members
# ===========================================================================
class TestChoiceCardinality:

    def test_required_choice_missing_member_fails(self):
        """profile 'merge' is a required choice (flat|as-is|custom); none present -> error."""
        p = Profile.new("Card")
        p._dict["profile"]["merge"] = {"combine": {"method": "keep"}}  # no flat/as-is/custom
        p.validate()
        assert p.validation_status["choice"] is False
        assert p.is_valid is False
        errs = [e for e in p.validation_errors if e["error-type"] == "choice"]
        assert errs and errs[0]["location"] == "/profile/merge"
        assert errs[0]["expected"] == {"select-one-of": ["flat", "as-is", "custom"]}

    def test_required_choice_single_member_ok(self):
        p = Profile.new("Card")
        p.set_merge(custom={})
        p.validate()
        assert p.validation_status["choice"] is True

    def test_bounded_required_choice_rejects_two(self):
        p = Profile.new("Card")
        p._dict["profile"]["merge"] = {"as-is": True, "custom": {}}
        p.validate()
        assert p.validation_status["choice"] is False

    def test_optional_choice_empty_group_ok(self):
        """catalog group's (groups|controls) choice is optional -> empty group is valid."""
        c = Catalog.new("Card")
        c.create_control_group("[root]", "empty", title="Empty Group")
        c.validate()
        assert c.validation_status["choice"] is True
        assert c.is_valid

    def test_unbounded_choice_allows_many_members(self):
        """The (groups|controls) choice is unbounded — many controls is fine."""
        c = Catalog.new("Card")
        c.create_control_group("[root]", "g", title="G")
        c.create_control("g", "c-1", title="C1")
        c.create_control("g", "c-2", title="C2")
        c.validate()
        assert c.validation_status["choice"] is True
        assert c.is_valid

    def test_unbounded_choice_still_mutually_exclusive(self):
        """max-occurs=unbounded bounds items *within* a branch, not combining branches:
        a group holding BOTH groups and controls violates the (groups|controls) choice."""
        c = Catalog.new("Card")
        c._dict["catalog"]["groups"] = [{
            "id": "g", "title": "G",
            "groups": [{"id": "g-sub", "title": "Sub"}],
            "controls": [{"id": "c-1", "title": "C1"}],
        }]
        c.validate()
        assert c.validation_status["choice"] is False
        errs = [e for e in c.validation_errors if e["error-type"] == "choice"]
        assert any(set(e["field"]) == {"groups", "controls"} for e in errs)
