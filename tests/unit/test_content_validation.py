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

from oscal import OSCAL

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
        """Schema-invalid XML sets schema_valid['_tree'] to False (not None)."""
        obj = OSCAL.loads(_XML_SCHEMA_INVALID)
        assert obj.schema_valid["_tree"] is False

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
        """Schema-invalid JSON sets schema_valid['_tree'] to False (JSON is converted to XML before validation)."""
        obj = OSCAL.loads(_JSON_SCHEMA_INVALID)
        assert obj.schema_valid["_tree"] is False

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
        """Schema-invalid YAML sets schema_valid['_tree'] to False (YAML is converted to XML before validation)."""
        obj = OSCAL.loads(_YAML_SCHEMA_INVALID)
        assert obj.schema_valid["_tree"] is False
