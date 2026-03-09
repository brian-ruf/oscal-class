"""
Unit tests for oscal.oscal_markdown
"""
import sys

import pytest

# Import directly from the module file to avoid triggering oscal/__init__.py,
# which requires ruf_common (a heavy dependency not needed for these tests).
sys.path.insert(0, "oscal")
from oscal_markdown import (
    convert_markup_line,
    convert_markup_multiline,
    escape_for_json,
    oscal_markdown_to_html,
)


class TestConvertMarkupLine:
    """Tests for inline (markup-line) conversion — no wrapping <p> tags."""

    def test_bold(self):
        result = convert_markup_line("This is **bold** text")
        assert "<strong>bold</strong>" in result
        assert not result.startswith("<p>")

    def test_italic(self):
        result = convert_markup_line("This is *italic* text")
        assert "<em>italic</em>" in result

    def test_no_wrapping_paragraph(self):
        result = convert_markup_line("plain text")
        assert not result.startswith("<p>")
        assert not result.endswith("</p>")

    def test_parameter_insertion(self):
        result = convert_markup_line("Value: {{ insert: param, ac-1_prm_1 }}")
        assert 'type="param"' in result
        assert 'id-ref="ac-1_prm_1"' in result
        assert "<insert" in result

    def test_parameter_insertion_with_spaces(self):
        result = convert_markup_line("{{ insert: param,  pm-9_prm_1 }}")
        assert 'id-ref="pm-9_prm_1"' in result

    def test_subscript(self):
        result = convert_markup_line("H~2~O")
        assert "<sub>2</sub>" in result

    def test_superscript(self):
        result = convert_markup_line("E=mc^2^")
        assert "<sup>2</sup>" in result

    def test_combined_subscript_superscript(self):
        result = convert_markup_line("H~2~O and E=mc^2^")
        assert "<sub>2</sub>" in result
        assert "<sup>2</sup>" in result

    def test_plain_text_passthrough(self):
        result = convert_markup_line("just plain text")
        assert "just plain text" in result

    def test_empty_string(self):
        result = convert_markup_line("")
        assert result == ""

    def test_invalid_parameter_syntax_left_as_is(self):
        # Single part — no comma — should not produce <insert>
        result = convert_markup_line("{{ insert: param }}")
        assert "<insert" not in result


class TestConvertMarkupMultiline:
    """Tests for block-level (markup-multiline) conversion."""

    def test_heading_h1(self):
        result = convert_markup_multiline("# Title")
        assert "<h1>" in result
        assert "Title" in result

    def test_heading_h2(self):
        result = convert_markup_multiline("## Section")
        assert "<h2>" in result

    def test_plain_text_gets_paragraph(self):
        result = convert_markup_multiline("Some text here")
        assert "<p>" in result
        assert "Some text here" in result

    def test_unordered_list(self):
        result = convert_markup_multiline("- Item one\n- Item two")
        assert "<ul>" in result
        assert "<li>" in result
        assert "Item one" in result

    def test_ordered_list(self):
        result = convert_markup_multiline("1. First\n2. Second")
        assert "<ol>" in result
        assert "<li>" in result

    def test_bold_in_multiline(self):
        result = convert_markup_multiline("This is **bold**")
        assert "<strong>bold</strong>" in result

    def test_parameter_insertion_in_multiline(self):
        result = convert_markup_multiline(
            "This implements {{ insert: param, ac-1_prm_1 }}."
        )
        assert 'type="param"' in result
        assert 'id-ref="ac-1_prm_1"' in result

    def test_table_has_no_thead(self):
        table_md = "| Col A | Col B |\n|-------|-------|\n| val1  | val2  |"
        result = convert_markup_multiline(table_md)
        assert "<table>" in result
        assert "<thead>" not in result
        assert "<tbody>" not in result

    def test_table_has_tr_and_th(self):
        table_md = "| Col A | Col B |\n|-------|-------|\n| val1  | val2  |"
        result = convert_markup_multiline(table_md)
        assert "<tr>" in result
        assert "<th>" in result

    def test_empty_string(self):
        result = convert_markup_multiline("")
        assert result == ""

    def test_multi_paragraph(self):
        result = convert_markup_multiline("First para\n\nSecond para")
        assert result.count("<p>") >= 2


class TestEscapeForJson:
    def test_backslash_doubled(self):
        result = escape_for_json("back\\slash")
        assert "\\\\" in result

    def test_asterisk_escaped(self):
        result = escape_for_json("bold *text*")
        assert "\\*" in result

    def test_backtick_escaped(self):
        result = escape_for_json("code `snippet`")
        assert "\\`" in result

    def test_tilde_escaped(self):
        result = escape_for_json("sub ~text~")
        assert "\\~" in result

    def test_caret_escaped(self):
        result = escape_for_json("super ^text^")
        assert "\\^" in result

    def test_double_quote_escaped(self):
        result = escape_for_json('say "hello"')
        assert '\\"' in result

    def test_plain_text_unchanged(self):
        result = escape_for_json("plain text here")
        assert result == "plain text here"

    def test_empty_string(self):
        result = escape_for_json("")
        assert result == ""


class TestOscalMarkdownToHtml:
    """Tests for the lower-level oscal_markdown_to_html function."""

    def test_inline_mode_strips_paragraph(self):
        result = oscal_markdown_to_html("text", multiline=False)
        assert not result.startswith("<p>")

    def test_multiline_mode_keeps_paragraph(self):
        result = oscal_markdown_to_html("text", multiline=True)
        assert "<p>" in result

    def test_multiline_heading_not_wrapped_in_p(self):
        result = oscal_markdown_to_html("# Heading", multiline=True)
        assert result.startswith("<h1>")
        assert "<p>" not in result
