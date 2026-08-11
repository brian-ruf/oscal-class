"""
Unit tests for the API documentation generator (oscal.gendocs):
    - collect_api      (introspection model)
    - render_llm_html / render_human_html
    - generate_docs    (CLI-facing orchestration)
"""
import os
import re
from html.parser import HTMLParser

import pytest

import oscal
from oscal import gendocs


def _pkg_dir():
    return os.path.dirname(oscal.__file__)


def _assert_parses(text):
    class _P(HTMLParser):
        def error(self, message):
            raise ValueError(message)
    _P().feed(text)


@pytest.fixture(scope="module")
def api():
    return gendocs.collect_api(_pkg_dir())


# ---------------------------------------------------------------------------
class TestCollectApi:

    def test_has_expected_modules(self, api):
        names = [m["name"] for m in api["modules"]]
        assert "oscal.oscal_content" in names
        assert "oscal.oscal_support" in names

    def test_finds_class_and_members(self, api):
        found = None
        for module in api["modules"]:
            for cls in module["classes"]:
                if cls["name"] == "OSCAL":
                    found = cls
        assert found is not None, "OSCAL class not discovered"
        assert any(m["name"] == "load" for m in found["members"])

    def test_members_carry_kind_and_signature(self, api):
        for module in api["modules"]:
            for cls in module["classes"]:
                for member in cls["members"]:
                    assert member["kind"] in {"method", "classmethod", "staticmethod", "property"}
                    if member["kind"] != "property":
                        assert member["signature"].startswith("(")

    def test_generated_timestamp_is_utc(self, api):
        assert api["generated"].endswith("Z")


# ---------------------------------------------------------------------------
class TestRenderLlm:

    def test_parses_and_has_markers(self, api):
        html = gendocs.render_llm_html(api)
        _assert_parses(html)
        assert html.startswith("<!DOCTYPE html>")
        assert 'content="llm"' in html
        assert "data-fqname=" in html and "data-kind=" in html
        assert '<section id="index">' in html

    def test_every_index_link_resolves(self, api):
        html = gendocs.render_llm_html(api)
        ids = set(re.findall(r'id="([^"]+)"', html))
        links = set(re.findall(r'href="#([^"]+)"', html))
        assert links, "expected in-page links"
        assert links <= ids, f"dangling anchors: {sorted(links - ids)[:5]}"

    def test_stable_fqname_anchors(self, api):
        html = gendocs.render_llm_html(api)
        assert 'id="oscal.oscal_content.OSCAL.load"' in html


# ---------------------------------------------------------------------------
class TestRenderHuman:

    def test_parses_and_has_markers(self, api):
        html = gendocs.render_human_html(api)
        _assert_parses(html)
        assert 'content="human"' in html
        assert 'class="sidebar"' in html and 'id="filter"' in html
        assert 'name="viewport"' in html
        assert "<script>" in html and "addEventListener" in html

    def test_kind_badges_present(self, api):
        html = gendocs.render_human_html(api)
        assert 'class="badge' in html


# ---------------------------------------------------------------------------
class TestGenerateDocs:

    def test_writes_llm_file_and_creates_dirs(self, tmp_path):
        out = tmp_path / "nested" / "api-llm.html"
        assert gendocs.generate_docs(_pkg_dir(), str(out), "llm") is True
        assert out.exists()
        assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")

    def test_writes_human_file(self, tmp_path):
        out = tmp_path / "api-human.html"
        assert gendocs.generate_docs(_pkg_dir(), str(out), "human") is True
        assert 'class="sidebar"' in out.read_text(encoding="utf-8")

    def test_unknown_mode_returns_false(self, tmp_path):
        assert gendocs.generate_docs(_pkg_dir(), str(tmp_path / "x.html"), "bogus") is False


# ---------------------------------------------------------------------------
class TestCli:

    def test_main_generates(self, tmp_path):
        out = tmp_path / "cli.html"
        rc = gendocs.main(["--mode", "llm", "--output", str(out), "--package", _pkg_dir()])
        assert rc == 0
        assert out.exists()

    def test_main_requires_mode_and_output(self):
        with pytest.raises(SystemExit):
            gendocs.main(["--package", _pkg_dir()])
