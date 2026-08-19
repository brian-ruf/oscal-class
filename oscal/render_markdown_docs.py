"""
RENDER MARKDOWN DOCS
Converts the hand-written guides in docs/*.md into standalone, styled HTML
pages (docs/*.html) plus a docs/index.html landing page, so they can be
served directly by GitHub Pages without depending on Jekyll or front matter.

Run from anywhere; paths are resolved relative to this file's location.
"""

import re
import sys
import logging
from pathlib import Path

import markdown

_EMPHASIS_RE = re.compile(r"[*_`]{1,2}(.+?)[*_`]{1,2}")

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s - %(message)s",
)
logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent.parent / "docs"
GITHUB_BLOB_BASE = "https://github.com/brian-ruf/oscal-class/blob/main/docs"

_STYLE = """
:root{--bg:#fff;--fg:#1a202c;--muted:#5b6675;--line:#e2e8f0;--accent:#2b6cb0;--code:#f6f8fa}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:var(--fg);background:var(--bg);line-height:1.6}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
nav.top{border-bottom:1px solid var(--line);padding:.8rem 2rem;display:flex;gap:1.2rem;font-size:.9rem;flex-wrap:wrap}
main{max-width:48rem;margin:0 auto;padding:1.5rem 2rem 4rem}
main img{max-width:100%}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:.7rem 1rem;overflow-x:auto}
code{background:var(--code);border-radius:4px;padding:.1rem .3rem}
pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left}
th{background:var(--code)}
blockquote{border-left:3px solid var(--line);margin:1rem 0;padding:.2rem 1rem;color:var(--muted)}
.source-link{font-size:.85rem;color:var(--muted);margin-bottom:1.5rem}
.index-list{list-style:none;padding:0}
.index-list li{margin:.4rem 0;font-size:1.05rem}
"""

_NAV = f'<nav class="top"><a href="index.html">Docs Home</a><a href="api.html">API Reference</a><a href="api-llm.html">API Reference (LLM)</a><a href="{GITHUB_BLOB_BASE}/../..">Repository</a></nav>'


def _page(title: str, body_html: str) -> str:
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{_STYLE}</style></head><body>"
        f"{_NAV}<main>{body_html}</main></body></html>"
    )


def _title_from_markdown(md_path: Path, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return _EMPHASIS_RE.sub(r"\1", stripped[2:].strip())
    return md_path.stem.replace("_", " ").title()


def render_docs(docs_dir: Path) -> bool:
    md_files = sorted(docs_dir.glob("*.md"))
    if not md_files:
        logger.warning(f"No markdown files found in {docs_dir}.")

    converter = markdown.Markdown(extensions=["extra", "toc", "sane_lists"])
    pages = []

    for md_path in md_files:
        text = md_path.read_text(encoding="utf-8")
        title = _title_from_markdown(md_path, text)
        converter.reset()
        body = converter.convert(text)
        source_link = (
            f'<p class="source-link">Source: '
            f'<a href="{GITHUB_BLOB_BASE}/{md_path.name}">{md_path.name}</a> on GitHub</p>'
        )
        html = _page(title, source_link + body)
        out_path = md_path.with_suffix(".html")
        out_path.write_text(html, encoding="utf-8")
        logger.info(f"Rendered {md_path.name} -> {out_path.name}")
        pages.append((title, out_path.name))

    index_items = "\n".join(f'<li><a href="{href}">{title}</a></li>' for title, href in pages)
    index_body = (
        "<h1>oscal-class Documentation</h1>"
        "<p>Guides and reference material for the OSCAL Python library.</p>"
        f'<ul class="index-list">'
        f'<li><a href="api.html">API Reference (human)</a></li>'
        f'<li><a href="api-llm.html">API Reference (LLM-optimized)</a></li>'
        f"{index_items}"
        "</ul>"
    )
    index_html = _page("oscal-class Documentation", index_body)
    (docs_dir / "index.html").write_text(index_html, encoding="utf-8")
    logger.info(f"Wrote index page with {len(pages)} guide(s).")

    return True


if __name__ == "__main__":
    if not render_docs(DOCS_DIR):
        sys.exit(1)
