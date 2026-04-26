"""Regression tests for HTML -> markdown conversion in oscal_markup."""
import sys
from pathlib import Path

# Import directly from module file to avoid package-level dependencies.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "oscal"))
from oscal_converters import oscal_html_to_markdown


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
