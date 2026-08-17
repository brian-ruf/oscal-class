"""Regression tests for HTML -> markdown conversion in oscal_markup."""
from oscal.oscal_converter import oscal_html_to_markdown


def test_insert_self_closing_standard_order():
    html = '<insert type="param" id-ref="ac-1_prm_1"/>'
    assert oscal_html_to_markdown(html, multiline=False) == "{{ insert: param, ac-1_prm_1 }}"


def test_insert_self_closing_reversed_order():
    html = '<insert id-ref="ac-1_prm_1" type="param"/>'
    assert oscal_html_to_markdown(html, multiline=False) == "{{ insert: param, ac-1_prm_1 }}"


def test_insert_single_quoted_attrs():
    html = "<insert id-ref='ac-1_prm_1' type='param' />"
    assert oscal_html_to_markdown(html, multiline=False) == "{{ insert: param, ac-1_prm_1 }}"


def test_insert_empty_paired_tag():
    html = '<insert type="param" id-ref="ac-1_prm_1"></insert>'
    assert oscal_html_to_markdown(html, multiline=False) == "{{ insert: param, ac-1_prm_1 }}"


def test_insert_with_extra_attributes():
    html = '<insert class="x" id-ref="ac-1_prm_1" data-role="p" type="param" />'
    assert oscal_html_to_markdown(html, multiline=False) == "{{ insert: param, ac-1_prm_1 }}"


# ---------------------------------------------------------------------------
# <q> (inline quotation) must render as literal double quotes, not be dropped.
# ---------------------------------------------------------------------------
def test_q_element_becomes_quotes_inline():
    assert oscal_html_to_markdown("the value can be <q>none.</q>", multiline=False) \
        == 'the value can be "none."'


def test_q_element_becomes_quotes_multiline():
    assert oscal_html_to_markdown("<p>the value can be <q>none.</q></p>", multiline=True) \
        == 'the value can be "none."'


# ---------------------------------------------------------------------------
# Adjacent paragraphs must keep their break even when they contain inline markup.
# ---------------------------------------------------------------------------
def test_paragraphs_with_inline_markup_keep_break():
    html = "<p>First para with <q>quote</q>.</p><p>Second para.</p>"
    assert oscal_html_to_markdown(html, multiline=True) == 'First para with "quote".\n\nSecond para.'


def test_plain_paragraphs_keep_break():
    html = "<p>First.</p><p>Second.</p>"
    assert oscal_html_to_markdown(html, multiline=True) == "First.\n\nSecond."
