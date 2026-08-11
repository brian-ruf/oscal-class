"""
Unit tests for summary-metadata population on OSCAL content load.

Covers OSCAL.initial_validation() populating the summary attributes
(title, version, published, last_modified, remarks, uuid) and the
_populate_summary_from_dict / _populate_summary_from_tree helpers.

Key behaviors under test:
  - last_modified and remarks are populated from parsed content (previously always "").
  - Summary attributes come from the converted JSON on the normal path, so title
    and remarks always hold OSCAL CommonMark (Markdown), never raw XML markup.
  - Markup with an inline element followed by tail text round-trips without the
    tail being duplicated (regression for the _markup_to_md tail bug).
  - When XML->JSON conversion is unavailable, the summary is populated from the XML
    tree as a fallback (so error reports stay complete), still yielding Markdown.
  - Missing metadata fields yield "".
"""
import os
from xml.etree import ElementTree as ET

import pytest

from oscal import OSCAL, Catalog
from oscal.oscal_converter import _markup_to_md

_HERE = os.path.dirname(__file__)
_DATA = os.path.join(_HERE, "..", "test-data")
_JSON_CATALOG = os.path.join(_DATA, "test", "800-53_catalog.json")
_XML_MARKUP_CATALOG = os.path.join(_DATA, "test", "markup_catalog.xml")

_NS = "http://csrc.nist.gov/ns/oscal/1.0"

# JSON catalog: valid structure, but no remarks / last-modified in metadata.
_JSON_NO_OPTIONAL = f"""\
{{
  "catalog": {{
    "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "metadata": {{
      "title": "No Optional Fields",
      "version": "1.0",
      "oscal-version": "1.1.3"
    }}
  }}
}}
"""


# ===========================================================================
# JSON source — summary attributes populate
# ===========================================================================
class TestJsonSummaryPopulation:
    @staticmethod
    @pytest.fixture(scope="class")
    def cat():
        return Catalog.load(_JSON_CATALOG)

    def test_last_modified_populated(self, cat):
        """last_modified is read from metadata (was always '' before)."""
        assert cat.last_modified == "2025-08-26T14:33:16.00000-00:00"

    def test_remarks_populated(self, cat):
        """remarks is read from metadata (was always '' before)."""
        assert cat.remarks != ""
        assert cat.remarks.startswith("This OSCAL representation")

    def test_title_populated(self, cat):
        assert cat.title.startswith("Electronic (OSCAL) Version")

    def test_version_populated(self, cat):
        assert cat.version == "5.2.0"

    def test_uuid_populated(self, cat):
        assert cat.uuid != ""


# ===========================================================================
# Missing optional fields — attributes are ""
# ===========================================================================
class TestMissingOptionalFields:
    @staticmethod
    @pytest.fixture(scope="class")
    def cat():
        return OSCAL.loads(_JSON_NO_OPTIONAL)

    def test_remarks_empty_when_absent(self, cat):
        assert cat.remarks == ""

    def test_last_modified_empty_when_absent(self, cat):
        assert cat.last_modified == ""

    def test_title_still_populated(self, cat):
        assert cat.title == "No Optional Fields"


# ===========================================================================
# XML source with markup — normal path (via XML->JSON conversion)
# ===========================================================================
class TestXmlMarkupSummary:
    @staticmethod
    @pytest.fixture(scope="class")
    def cat():
        return Catalog.load(_XML_MARKUP_CATALOG)

    def test_dict_is_authoritative_tree_released(self, cat):
        """After conversion the dict is populated and the XML tree is released."""
        assert cat._dict is not None
        assert cat._tree is None

    def test_title_is_markdown_not_xml(self, cat):
        """title holds CommonMark; the <em> element becomes *...* markup."""
        assert cat.title == "Minimal *Markup* Catalog"
        assert "<em>" not in cat.title

    def test_title_tail_not_duplicated(self, cat):
        """Regression: tail text after an inline element must appear exactly once."""
        assert cat.title.count("Catalog") == 1

    def test_remarks_is_markdown(self, cat):
        assert "**bold**" in cat.remarks
        assert "[link](https://example.com)" in cat.remarks
        assert "<p>" not in cat.remarks

    def test_last_modified_populated(self, cat):
        assert cat.last_modified == "2026-08-10T12:00:00.000000-00:00"

    def test_valid(self, cat):
        assert cat.is_valid is True


# ===========================================================================
# Fallback path — XML->JSON conversion unavailable
# ===========================================================================
class TestXmlSummaryFallback:
    @pytest.fixture
    def cat(self, monkeypatch):
        """Force the converter lookup to fail so conversion yields no dict; the
        summary must then be populated from the XML tree."""
        from oscal import oscal_content

        monkeypatch.setattr(
            oscal_content.OSCALConverter,
            "from_support",
            classmethod(lambda cls, *a, **k: None),
        )
        return Catalog.load(_XML_MARKUP_CATALOG)

    def test_conversion_did_not_produce_dict(self, cat):
        assert cat._dict is None
        assert cat._tree is not None  # tree retained for the fallback / error report

    def test_title_markdown_from_tree(self, cat):
        """Fallback still yields Markdown (not raw XML) with no tail duplication."""
        assert cat.title == "Minimal *Markup* Catalog"

    def test_remarks_markdown_from_tree(self, cat):
        assert "**bold**" in cat.remarks
        assert "[link](https://example.com)" in cat.remarks

    def test_last_modified_from_tree(self, cat):
        assert cat.last_modified == "2026-08-10T12:00:00.000000-00:00"

    def test_uuid_from_tree(self, cat):
        assert cat.uuid == "11111111-2222-3333-4444-555555555555"


# ===========================================================================
# XML <-> JSON round-trip fidelity for markup fields
# ===========================================================================
class TestMarkupRoundTrip:
    def test_xml_to_json_to_xml_preserves_markup(self, tmp_path):
        """Load markup XML, dump JSON, reload — markup survives intact."""
        src = Catalog.load(_XML_MARKUP_CATALOG)
        path = str(tmp_path / "rt.json")
        assert src.dump(path, format="json") is True
        reloaded = Catalog.load(path)
        assert reloaded.title == src.title == "Minimal *Markup* Catalog"
        assert reloaded.remarks == src.remarks

    def test_json_to_xml_to_json_preserves_markup(self, tmp_path):
        """Load markup XML (now dict-native), dump XML, reload from XML — markup survives."""
        src = Catalog.load(_XML_MARKUP_CATALOG)
        path = str(tmp_path / "rt.xml")
        assert src.dump(path, format="xml") is True
        reloaded = Catalog.load(path)
        assert reloaded.title == "Minimal *Markup* Catalog"
        assert "**bold**" in reloaded.remarks

    def test_control_title_and_prose_markup_survive(self, tmp_path):
        """Markup in control title (markup-line) and part prose (markup-multiline)
        survives an XML->JSON->XML->JSON round-trip without tail duplication."""
        src = Catalog.load(_XML_MARKUP_CATALOG)
        xml_path = str(tmp_path / "rt.xml")
        assert src.dump(xml_path, format="xml") is True
        reloaded = Catalog.load(xml_path)
        ctrl = reloaded._dict["catalog"]["controls"][0]
        assert ctrl["title"] == "Example *Control* One"
        assert ctrl["parts"][0]["prose"] == "The system **must** enforce policy and log all events."


# ===========================================================================
# _markup_to_md — direct regression for tail-text handling
# ===========================================================================
class TestMarkupToMdTail:
    def test_inline_element_tail_not_duplicated(self):
        """<em>Markup</em> followed by ' Catalog' tail must not duplicate the tail."""
        el = ET.fromstring(
            f'<title xmlns="{_NS}">Minimal <em>Markup</em> Catalog</title>'
        )
        assert _markup_to_md(el, "markup-line") == "Minimal *Markup* Catalog"

    def test_multiple_inline_tails(self):
        """Multiple inline elements each keep their own trailing text exactly once."""
        el = ET.fromstring(
            f'<title xmlns="{_NS}">a <em>b</em> c <strong>d</strong> e</title>'
        )
        assert _markup_to_md(el, "markup-line") == "a *b* c **d** e"

    def test_no_children_plain_text(self):
        el = ET.fromstring(f'<title xmlns="{_NS}">plain text</title>')
        assert _markup_to_md(el, "markup-line") == "plain text"

    def test_empty_element_returns_empty(self):
        el = ET.fromstring(f'<remarks xmlns="{_NS}"></remarks>')
        assert _markup_to_md(el, "markup-multiline") == ""
