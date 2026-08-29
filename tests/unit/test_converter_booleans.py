"""
Unit tests for boolean serialization in the JSON→XML converter.

OSCAL/XML booleans are lexically lowercase (`true` / `false`). The internal JSON
representation stores Python `bool`, so the converter must emit `true`/`false`, not
`str(True)` → `"True"` (which fails schema validation). Regression for a profile whose
`merge/as-is` boolean field was exported as `True`.
"""
import pytest

from oscal import OSCAL
from oscal.oscal_converter import _scalar_to_xml_text


# ---------------------------------------------------------------------------
def _profile_xml(as_is="true"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-0000000000b0">
  <metadata>
    <title>Boolean Serialization Test</title>
    <last-modified>2026-06-06T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.3</oscal-version>
  </metadata>
  <import href="#11111111-2222-4333-8444-555555555555"><include-all/></import>
  <merge><combine method="keep"/><as-is>{as_is}</as-is></merge>
  <back-matter>
    <resource uuid="11111111-2222-4333-8444-555555555555"><rlink href="catalog.xml"/></resource>
  </back-matter>
</profile>"""


# ===========================================================================
# Helper
# ===========================================================================
class TestScalarToXmlText:

    def test_true_is_lowercase(self):
        assert _scalar_to_xml_text(True) == "true"

    def test_false_is_lowercase(self):
        assert _scalar_to_xml_text(False) == "false"

    def test_int_unchanged(self):
        # bool is a subclass of int — make sure a real int is not mistaken for one
        assert _scalar_to_xml_text(5) == "5"

    def test_str_unchanged(self):
        assert _scalar_to_xml_text("keep") == "keep"


# ===========================================================================
# Field boolean (merge/as-is) round-trip
# ===========================================================================
class TestBooleanField:

    def test_dict_stores_python_bool(self):
        p = OSCAL.loads(_profile_xml("true"))
        assert p._dict["profile"]["merge"]["as-is"] is True

    @pytest.mark.parametrize("literal,expected", [("true", "<as-is>true</as-is>"),
                                                  ("false", "<as-is>false</as-is>")])
    def test_xml_output_is_lowercase(self, literal, expected):
        out = OSCAL.loads(_profile_xml(literal)).dumps(format="xml")
        assert expected in out
        assert "<as-is>True</as-is>" not in out
        assert "<as-is>False</as-is>" not in out

    def test_dumped_xml_is_schema_valid(self):
        out = OSCAL.loads(_profile_xml("true")).dumps(format="xml")
        assert OSCAL.loads(out).is_valid

    def test_json_output_keeps_boolean(self):
        # JSON serialization keeps the native boolean (json.dumps → lowercase true)
        out = OSCAL.loads(_profile_xml("true")).dumps(format="json")
        assert '"as-is": true' in out
