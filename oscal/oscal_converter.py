"""
OSCAL XML ↔ JSON converter driven by the metaschema index.

Uses the index produced by MetaschemaParser.build_metaschema_tree() to convert
OSCAL content between XML and JSON serializations without external XSLT tooling.

Key conventions reflected from the index:
  structure-type  "assembly"         — element with child elements and/or flags
                  "field"            — element with text/markup value and optional flags
                  "flag"             — XML attribute / JSON property (scalar)
                  "choice"           — mutually exclusive alternatives; children list
                                       the options; cardinality lives on each option
                  "recursive"        — same assembly as an ancestor; resolve via name
                  "any"              — extension point; unmodeled content is preserved
  group-as-in-xml "GROUPED"          — child elements appear inside a wrapper element
                  "UNGROUPED"        — child elements repeat as direct siblings
  group-as-in-json "ARRAY"           — always a JSON array
                   "SINGLETON_OR_ARRAY" — one object or an array
                   "BY_KEY"          — JSON object keyed by the flag named in json-key
  json-value-key  name of the JSON key that carries a field's text value
  json-key        flag whose value becomes the BY_KEY dictionary key in JSON
  wrapped-in-xml  True/False — whether this element is enclosed in an XML wrapper

Markup-typed fields (markup-line, markup-multiline):
  XML → JSON  inner XML content is converted to CommonMark via html2text
  JSON → XML  CommonMark is converted to HTML via the markdown library, then
              parsed into ET sub-elements
  Both libraries are project dependencies; conversion degrades to plain text
  only if they cannot be imported.

Unmodeled content (declared via <any/> in the metaschema):
  XML → JSON  unknown child elements are captured in a "_unmodeled" key
  JSON → XML  "_unmodeled" content is re-emitted verbatim
"""
from __future__ import annotations

import html.parser as _html_parser
import json
import re
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, SubElement
import logging

import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.treeprocessors import Treeprocessor

from .oscal_support import get_support, METASCHEMA_MIN_VERSION
from ruf_common.helper import compare_semver

logger = logging.getLogger(__name__)

OSCAL_XML_NAMESPACE = "http://csrc.nist.gov/ns/oscal/1.0"

# ---------------------------------------------------------------------------
# OSCAL markup-line / markup-multiline ↔ CommonMark conversion
# (formerly in oscal_converters.py)
# ---------------------------------------------------------------------------

class _ParameterInsertionProcessor(InlineProcessor):
    """Handles OSCAL ``{{ insert: param, id }}`` syntax → ``<insert>`` element."""

    def handleMatch(self, m, data):
        parts = [p.strip() for p in m.group(1).strip().split(",")]
        if len(parts) != 2:
            return None, None, None
        el = Element("insert")
        el.set("type", parts[0])
        el.set("id-ref", parts[1])
        return el, m.start(0), m.end(0)


class _SubscriptProcessor(InlineProcessor):
    """Handles ``~text~`` → ``<sub>text</sub>``."""

    def handleMatch(self, m, data):
        el = Element("sub")
        el.text = m.group(1)
        return el, m.start(0), m.end(0)


class _SuperscriptProcessor(InlineProcessor):
    """Handles ``^text^`` → ``<sup>text</sup>``."""

    def handleMatch(self, m, data):
        el = Element("sup")
        el.text = m.group(1)
        return el, m.start(0), m.end(0)


class _OscalTableTreeprocessor(Treeprocessor):
    """Flatten table structure to OSCAL-compliant ``<tr>`` children only."""

    def run(self, root):
        for table in root.iter("table"):
            self._flatten(table)

    def _flatten(self, table):
        rows = []
        for child in list(table):
            if child.tag in ("thead", "tbody"):
                rows.extend(child)
                table.remove(child)
            elif child.tag == "tr":
                rows.append(child)
            elif child.tag in ("tfoot", "col", "colgroup", "caption"):
                table.remove(child)
        table.clear()
        for row in rows:
            table.append(row)


class _OscalParameterExtension(Extension):
    """Markdown extension wiring up all OSCAL inline/tree processors."""

    def extendMarkdown(self, md):
        md.inlinePatterns.register(
            _ParameterInsertionProcessor(r"\{\{\s*insert:\s*([^}]+)\}\}", md),
            "oscal_param_insert", 175,
        )
        md.inlinePatterns.register(
            _SubscriptProcessor(r"~([^~]+)~", md),
            "oscal_subscript", 174,
        )
        md.inlinePatterns.register(
            _SuperscriptProcessor(r"\^([^^]+)\^", md),
            "oscal_superscript", 173,
        )
        md.treeprocessors.register(
            _OscalTableTreeprocessor(md), "oscal_table_compliance", 0
        )


def oscal_markdown_to_html(markdown_text: str, multiline: bool = False) -> str:
    """Convert OSCAL CommonMark to an HTML fragment.

    ``multiline=True``  → markup-multiline: block elements preserved, ``<p>`` wrap applied.
    ``multiline=False`` → markup-line: inline only, outer ``<p>`` stripped.
    """
    if not markdown_text:
        return ""

    # OSCAL markdown does not allow raw HTML.  Escape any angle bracket that
    # looks like the start of an HTML/XML tag so the markdown library treats it
    # as literal text rather than inline HTML.
    markdown_text = re.sub(r"<(?=[a-zA-Z/!])", r"&lt;", markdown_text)

    md = markdown.Markdown(
        extensions=["extra", "sane_lists", _OscalParameterExtension()],
        extension_configs={
            "extra": {
                "markdown.extensions.fenced_code": {},
                "markdown.extensions.tables": {},
            }
        },
    )
    html = md.convert(markdown_text)

    if not multiline:
        if html.startswith("<p>") and html.endswith("</p>"):
            html = html[3:-4]
        html = html.replace("\n", " ").strip()
    else:
        has_block = any(
            tag in html
            for tag in ("<p>", "<h1>", "<h2>", "<h3>", "<h4>", "<h5>", "<h6>",
                        "<ul>", "<ol>", "<blockquote>", "<table>")
        )
        if not has_block and html.strip():
            html = f"<p>{html}</p>"

    return html


def oscal_html_to_markdown(html_text: str, multiline: bool = True) -> str:
    """Convert an HTML fragment to OSCAL CommonMark.

    ``multiline=True``  → markup-multiline (block elements converted).
    ``multiline=False`` → markup-line (inline elements only).
    """
    if not html_text:
        return ""

    md = html_text.strip()

    # OSCAL insert tags → {{ insert: type, id-ref }}
    def _replace_insert(match):
        attrs = match.group(1) or ""
        type_m = re.search(r'\btype\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE)
        id_m   = re.search(r'\bid-ref\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE)
        if not type_m or not id_m:
            return match.group(0)
        return f"{{{{ insert: {type_m.group(2).strip()}, {id_m.group(2).strip()} }}}}"

    md = re.sub(
        r"<insert\b([^>]*)\s*(?:/\s*>|>\s*</insert\s*>)",
        _replace_insert, md, flags=re.IGNORECASE,
    )

    if multiline:
        for level in range(1, 7):
            md = re.sub(f"<h{level}>([^<]+)</h{level}>", f'{"#" * level} \\1\n\n', md)

        def _code_block(m):
            return f"\n\n```\n{m.group(1)}\n```\n\n"
        md = re.sub(r"<pre>([^<]*)</pre>", _code_block, md, flags=re.DOTALL)

        def _table(m):
            t = m.group(0)
            hdr = re.search(r"<tr>((?:<th[^>]*>[^<]*</th>)+)</tr>", t)
            if not hdr:
                return t
            cols = re.findall(r"<th[^>]*>([^<]*)</th>", hdr.group(1))
            aligns = [a for a in re.findall(r'<th[^>]*align="([^"]*)"', hdr.group(1))]
            rows = []
            for rm in re.finditer(r"<tr>((?:<td[^>]*>.*?</td>)+)</tr>", t, flags=re.DOTALL):
                rows.append(re.findall(r"<td[^>]*>(.*?)</td>", rm.group(1), flags=re.DOTALL))
            if not cols or not rows:
                return t
            lines = ["| " + " | ".join(cols) + " |"]
            seps = []
            for i in range(len(cols)):
                a = aligns[i] if i < len(aligns) else "left"
                seps.append(":---:" if a == "center" else "---:" if a == "right" else "---")
            lines.append("| " + " | ".join(seps) + " |")
            for row in rows:
                row = (row + [""] * len(cols))[: len(cols)]
                lines.append("| " + " | ".join(row) + " |")
            return "\n\n" + "\n".join(lines) + "\n\n"

        md = re.sub(r"<table>.*?</table>", _table, md, flags=re.DOTALL)
        md = re.sub(r"<blockquote>([^<]+)</blockquote>", r"\n\n> \1\n\n", md)
        md = re.sub(r"<ul><li>([^<]+)</li></ul>", r"\n\n- \1\n", md)
        md = re.sub(r"<ol><li>([^<]+)</li></ol>", r"\n\n1. \1\n", md)
        md = re.sub(r"<p>([^<]+)</p>", r"\1\n\n", md)

    # Inline formatting
    md = re.sub(r'<img\s+alt="([^"]*)"\s+src="([^"]+)"\s+title="([^"]*)"\s*/>', r'![\1](\2 "\3")', md)
    md = re.sub(r'<img\s+alt="([^"]*)"\s+src="([^"]+)"\s*/>', r"![\1](\2)", md)
    md = re.sub(r'<a\s+href="([^"]+)"\s+title="([^"]*)">([^<]+)</a>', r'[\3](\1 "\2")', md)
    md = re.sub(r'<a\s+href="([^"]+)">([^<]+)</a>', r"[\2](\1)", md)
    md = re.sub(r"<strong>([^<]+)</strong>", r"**\1**", md)
    md = re.sub(r"<em>([^<]+)</em>", r"*\1*", md)
    md = re.sub(r"<code>([^<]+)</code>", r"`\1`", md)
    md = re.sub(r"<sup>([^<]+)</sup>", r"^\1^", md)
    md = re.sub(r"<sub>([^<]+)</sub>", r"~\1~", md)
    md = re.sub(r"<[^>]+>", "", md)

    if multiline:
        lines = [ln.strip() for ln in md.split("\n")]
        cleaned: list[str] = []
        for line in lines:
            if line:
                cleaned.append(line)
            elif cleaned and cleaned[-1]:
                cleaned.append("")
        md = re.sub(r"\n\n\n+", "\n\n", "\n".join(cleaned))
    else:
        md = re.sub(r"\s+", " ", md)

    return md.strip()


def convert_markup_line(markdown_text: str) -> str:
    """Convert OSCAL markup-line (inline-only) markdown to an HTML fragment."""
    return oscal_markdown_to_html(markdown_text, multiline=False)


def convert_markup_multiline(markdown_text: str) -> str:
    """Convert OSCAL markup-multiline (block-level) markdown to an HTML fragment."""
    return oscal_markdown_to_html(markdown_text, multiline=True)


def escape_for_json(text: str) -> str:
    """Escape special markdown/JSON characters in a plain-text string."""
    text = text.replace('\\', '\\\\')
    text = text.replace('*', '\\*')
    text = text.replace('`', '\\`')
    text = text.replace('~', '\\~')
    text = text.replace('^', '\\^')
    text = text.replace('"', '\\"')
    return text


# ---------------------------------------------------------------------------

_MARKUP_TYPES = frozenset({"markup-line", "markup-multiline"})
_INT_TYPES    = frozenset({"integer", "non-negative-integer", "positive-integer"})
_FLOAT_TYPES  = frozenset({"decimal"})
_BOOL_TYPES   = frozenset({"boolean"})

_NS_ATTR_RE   = re.compile(r'\s*xmlns(?::\w+)?="[^"]*"')
_NS_PREFIX_RE = re.compile(r"<(/?)[\w]+:(\w+)")

# Known HTML/OSCAL elements: produced by the markdown library or by our insert
# template expansion.  Anything else (e.g. <BREAK>, <CTRL>) is treated as
# escaped text rather than an XML element.
_KNOWN_HTML_ELEMS = frozenset([
    "a", "abbr", "b", "bdi", "bdo", "blockquote", "br", "caption", "cite",
    "code", "col", "colgroup", "dd", "dfn", "div", "dl", "dt",
    "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "kbd", "li", "mark", "ol", "p", "pre",
    "q", "rp", "rt", "ruby", "s", "samp", "small", "span", "strong",
    "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr",
    "u", "ul", "var", "wbr",
    "insert",   # OSCAL inline element
    # Note: "del" and "ins" deliberately excluded — they appear as keyboard
    # key names (<DEL>, <INS>) in OSCAL prose and must be escaped as text.
])
_VOID_HTML_ELEMS = frozenset([
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
])


class _HtmlToET(_html_parser.HTMLParser):
    """
    Parse an HTML fragment into an ElementTree rooted at a synthetic ``_w``
    element.  Known HTML/OSCAL elements become ET child nodes in *namespace*;
    unknown elements (e.g. ``<BREAK>``, ``<CTRL>``) are rendered as escaped
    text (``&lt;BREAK&gt;``) so they survive the XML round-trip unmodified.
    """

    def __init__(self, namespace: str) -> None:
        super().__init__(convert_charrefs=True)
        self.namespace = namespace
        self._root: Element = Element("_w")
        self._stack: list[Element] = [self._root]

    def _current(self) -> Element:
        return self._stack[-1]

    def _append_text(self, text: str) -> None:
        cur = self._current()
        children = list(cur)
        if children:
            last = children[-1]
            last.tail = (last.tail or "") + text
        else:
            cur.text = (cur.text or "") + text

    def _make_elem(self, tag: str, attrs: list) -> Element:
        elem = SubElement(self._current(), f"{{{self.namespace}}}{tag}")
        for k, v in attrs:
            elem.set(k, v if v is not None else "")
        return elem

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tl = tag.lower()
        if tl not in _KNOWN_HTML_ELEMS:
            attr_str = "".join(
                f' {k}="{v}"' if v is not None else f" {k}" for k, v in attrs
            )
            self._append_text(f"<{tag}{attr_str}>")
            return
        elem = self._make_elem(tl, attrs)
        if tl not in _VOID_HTML_ELEMS:
            self._stack.append(elem)

    def handle_endtag(self, tag: str) -> None:
        tl = tag.lower()
        if tl not in _KNOWN_HTML_ELEMS:
            self._append_text(f"</{tag}>")
            return
        if tl in _VOID_HTML_ELEMS:
            return
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag.split("}")[-1] == tl:
                self._stack = self._stack[:i]
                return

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        tl = tag.lower()
        if tl not in _KNOWN_HTML_ELEMS:
            attr_str = "".join(
                f' {k}="{v}"' if v is not None else f" {k}" for k, v in attrs
            )
            self._append_text(f"<{tag}{attr_str}/>")
            return
        self._make_elem(tl, attrs)

    def handle_data(self, data: str) -> None:
        self._append_text(data)

    def get_root(self) -> Element:
        return self._root


def _html_to_et(html_str: str, namespace: str) -> Element:
    """Parse an HTML fragment and return a ``_w`` ET element with the children."""
    parser = _HtmlToET(namespace)
    parser.feed(html_str)
    parser.close()
    return parser.get_root()


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    """Strip XML namespace URI from a tag, returning the local name."""
    return tag.split("}")[-1] if "}" in tag else tag


def _cast(value: str, datatype: str) -> str | int | float | bool:
    """Cast a string value to its typed Python equivalent for JSON output."""
    if datatype in _INT_TYPES:
        try:
            return int(value)
        except (ValueError, TypeError):
            return value
    if datatype in _FLOAT_TYPES:
        try:
            return float(value)
        except (ValueError, TypeError):
            return value
    if datatype in _BOOL_TYPES:
        return value.lower() in ("true", "1", "yes")
    return value


def _markup_to_md(element: Element, datatype: str) -> str:
    """
    Extract the inner HTML content of an XML element and convert it to
    OSCAL-flavoured CommonMark using ``oscal_html_to_markdown``.
    """
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in element:
        raw = ET.tostring(child, encoding="unicode", method="html")
        raw = _NS_ATTR_RE.sub("", raw)
        raw = _NS_PREFIX_RE.sub(r"<\1\2", raw)
        parts.append(raw)
        # NOTE: ET.tostring(child, ...) already includes the child's tail text, so the
        # tail must NOT be appended again here or it would be duplicated.
    html = "".join(parts).strip()
    if not html:
        return ""
    return oscal_html_to_markdown(html, multiline=(datatype == "markup-multiline"))


def _md_to_xml(md_text: str, parent: Element, datatype: str, namespace: str) -> None:
    """
    Convert an OSCAL CommonMark string to XML child content on ``parent``.

    Converts Markdown to an HTML fragment via ``oscal_markdown_to_html``, then
    parses it with ``_HtmlToET`` which handles HTML quirks (void elements,
    unknown tags like ``<BREAK>`` that become escaped text).  Falls back to
    plain text on conversion failure.
    """
    if not md_text:
        return

    multiline = (datatype == "markup-multiline")

    html = oscal_markdown_to_html(md_text, multiline=multiline)
    if html:
        root = _html_to_et(html, namespace)
        parent.text = root.text
        for child in root:
            parent.append(child)
        return

    parent.text = md_text


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------

class OSCALConverter:
    """
    Converts OSCAL content between XML and JSON using a metaschema index.

    Parameters
    ----------
    model_index
        Output of ``MetaschemaParser.build_metaschema_tree()``.  Must contain
        the key ``"nodes"`` with the root assembly node and at minimum
        ``"oscal_model"``, ``"oscal_namespace"``, and ``"json_base_uri"``.
    """

    def __init__(self, model_index: dict) -> None:
        self.model       = model_index.get("oscal_model", "")
        self.version     = model_index.get("oscal_version", "")
        self.namespace   = model_index.get("oscal_namespace") or OSCAL_XML_NAMESPACE
        self.schema_uri  = model_index.get("json_base_uri", "")
        self.root_node: dict = model_index.get("nodes") or {}
        self._defs: dict[str, dict] = {}
        self._index_defs(self.root_node)

    @classmethod
    def from_support(cls, model: str, version: str, support=None) -> "OSCALConverter | None":
        """
        Build a converter by fetching the processed metaschema index from the
        OSCAL support object.

        Parameters
        ----------
        model
            OSCAL model name, e.g. ``"catalog"``, ``"system-security-plan"``.
        version
            OSCAL version string, e.g. ``"v1.2.0"``.
        support
            An ``OSCALSupport`` instance.  If ``None``, the shared support
            singleton is obtained via ``get_support()``.

        Returns ``None`` when the index has not yet been generated for the
        requested version (run ``parse_metaschema`` first).
        """
        if support is None:
            support = get_support()

        # Versions older than METASCHEMA_MIN_VERSION have no resolved metaschema
        # files; use the minimum version's index as the closest approximation.
        index_version = version
        if compare_semver(version, METASCHEMA_MIN_VERSION) < 0:
            logger.warning(
                f"No metaschema index for {version} (resolved metaschema not "
                f"published before {METASCHEMA_MIN_VERSION}). "
                f"Falling back to {METASCHEMA_MIN_VERSION} index."
            )
            index_version = METASCHEMA_MIN_VERSION

        model_index = support.get_metaschema_index(index_version, model)
        if model_index is None:
            logger.error(
                f"No processed metaschema index for {index_version}/{model}. "
                "Run support.update() to populate support assets."
            )
            return None

        return cls(model_index)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def xml_to_json(self, xml_content: str) -> str | None:
        """
        Convert an OSCAL XML document to OSCAL JSON.

        Returns the JSON string, or ``None`` on parse/conversion error.
        """
        try:
            root = ET.fromstring(xml_content.encode("utf-8"))
        except ET.ParseError as exc:
            logger.error(f"XML parse error: {exc}")
            return None

        root_name = _local(root.tag)
        expected  = self.root_node.get("use-name") or self.model
        if root_name != expected:
            logger.warning(f"Root element '{root_name}' does not match expected '{expected}'")

        try:
            body: dict = {}
            if self.schema_uri and self.version:
                body["$schema"] = f"{self.schema_uri}/{self.version}/json/schema"
            body[root_name] = self._elem_to_dict(root, self.root_node)
            return json.dumps(body, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.exception(f"XML→JSON conversion failed: {exc}")
            return None

    def json_to_xml(self, json_content: str) -> str | None:
        """
        Convert an OSCAL JSON document to OSCAL XML.

        Returns the XML string (with declaration), or ``None`` on error.
        """
        try:
            doc = json.loads(json_content)
        except json.JSONDecodeError as exc:
            logger.error(f"JSON parse error: {exc}")
            return None

        doc.pop("$schema", None)
        roots = [k for k in doc if not k.startswith("_")]
        if len(roots) != 1:
            logger.error(f"Expected one root key in JSON, found: {list(doc.keys())}")
            return None

        root_key = roots[0]
        json_obj  = doc[root_key]
        if not isinstance(json_obj, dict):
            logger.error(f"Root JSON value must be an object, got {type(json_obj).__name__}")
            return None

        ET.register_namespace("", self.namespace)
        try:
            root_elem = self._dict_to_elem(json_obj, self.root_node)
            ET.indent(root_elem, space="  ")
            xml_body = ET.tostring(root_elem, encoding="unicode", xml_declaration=False)
            return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_body}\n'
        except Exception as exc:
            logger.exception(f"JSON→XML conversion failed: {exc}")
            return None

    # ------------------------------------------------------------------
    # Definition index (for resolving recursive nodes)
    # ------------------------------------------------------------------

    def _index_defs(self, node: dict | None) -> None:
        """Walk the node tree and record the first occurrence of each named definition."""
        if not node or node.get("structure-type") == "recursive":
            return
        name  = node.get("name", "")
        stype = node.get("structure-type", "")
        if name and stype in ("assembly", "field") and name not in self._defs:
            self._defs[name] = node
        for child in node.get("children") or []:
            if child and child.get("structure-type") == "flag":
                fn = child.get("name", "")
                if fn and fn not in self._defs:
                    self._defs[fn] = child
            else:
                self._index_defs(child)

    def _resolve(self, node: dict) -> dict:
        """Return the full definition node for a recursive stub."""
        if node.get("structure-type") == "recursive":
            return self._defs.get(node.get("name", ""), node)
        return node

    # ------------------------------------------------------------------
    # XML → JSON
    # ------------------------------------------------------------------

    def _elem_to_dict(self, element: Element, node: dict) -> dict | str | int | float | bool:
        """
        Convert one XML element to its JSON-compatible Python value.

        Returns a dict for assemblies and complex fields, or a scalar for
        simple fields (no flags, plain text value).
        """
        node  = self._resolve(node)
        stype = node.get("structure-type", "")
        result: dict = {}

        # 1. Flags: XML attributes → JSON properties (in index-defined order)
        #    Build a local-name lookup of all attributes present on this element
        #    so we can iterate the index sequence rather than attribute order.
        attrib_by_local: dict[str, str] = {_local(k): v for k, v in element.attrib.items()}
        for flag_nd in [c for c in node.get("children") or [] if c and c.get("structure-type") == "flag"]:
            ln = flag_nd.get("use-name", "")
            if ln in attrib_by_local:
                result[ln] = _cast(attrib_by_local[ln], flag_nd.get("datatype", "string"))

        # 2. Field value: XML text/markup content → JSON value
        if stype == "field":
            datatype = node.get("datatype", "string")
            jvk      = node.get("json-value-key") or ""
            jvkf     = node.get("json-value-key-flag") or ""

            text_val = (
                _markup_to_md(element, datatype)
                if datatype in _MARKUP_TYPES
                else (element.text or "").strip()
            )

            if jvk:
                if text_val:
                    typed_val = text_val if datatype in _MARKUP_TYPES else _cast(text_val, datatype)
                    if not result:  # No flags — collapse to plain scalar per OSCAL JSON convention
                        return typed_val
                    result[jvk] = typed_val
            elif jvkf:
                # One flag's value becomes the JSON object key; its text is the value
                key_val = result.pop(jvkf, "")
                if text_val:
                    result[key_val] = text_val if datatype in _MARKUP_TYPES else _cast(text_val, datatype)
            elif text_val:
                if not result:
                    # Simple field with no flags: return plain scalar
                    return text_val if datatype in _MARKUP_TYPES else _cast(text_val, datatype)
                result["STRVALUE"] = text_val if datatype in _MARKUP_TYPES else _cast(text_val, datatype)

        # 3. Children: recurse into child elements
        self._xml_children(element, node, result)
        return result

    def _xml_children(self, element: Element, node: dict, result: dict) -> None:
        """Process all child nodes from the index against element's XML children."""
        # Pre-compute the set of OSCAL XML element names used by wrapped children.
        # This lets _xml_unwrapped_field identify which children carry inline markup
        # (prose) versus structured OSCAL content.
        known_xml_names: set[str] = set()
        for cn in node.get("children") or []:
            if not cn or cn.get("wrapped-in-xml") is False:
                continue
            stype_cn = cn.get("structure-type", "")
            if stype_cn == "choice":
                for alt in cn.get("children") or []:
                    if alt:
                        un = alt.get("use-name", "")
                        ga = alt.get("group-as", "")
                        if un:
                            known_xml_names.add(un)
                        if ga:
                            known_xml_names.add(ga)
            else:
                un = cn.get("use-name", "")
                ga = cn.get("group-as", "")
                if un:
                    known_xml_names.add(un)
                if ga:
                    known_xml_names.add(ga)

        for child_nd in node.get("children") or []:
            if not child_nd:
                continue
            stype = child_nd.get("structure-type", "")

            if child_nd.get("wrapped-in-xml") is False:
                self._xml_unwrapped_field(element, child_nd, result, known_xml_names)
            elif stype == "choice":
                for alt in child_nd.get("children") or []:
                    if alt:
                        self._xml_child(element, alt, result)
            elif stype == "any":
                self._xml_any(element, node, result)
            elif stype == "recursive":
                self._xml_child(element, self._resolve(child_nd), result, cardinality=child_nd)
            else:
                self._xml_child(element, child_nd, result)

    def _xml_unwrapped_field(
        self,
        element: Element,
        child_nd: dict,
        result: dict,
        known_xml_names: set,
    ) -> None:
        """
        Extract a field whose content is inline markup inside the parent element.

        In OSCAL XML, ``markup-multiline`` fields with ``wrapped-in-xml: false``
        (e.g. ``prose`` in ``<part>``, ``<guideline>``) appear as block-level HTML
        children (``<p>``, ``<ul>``, ``<ol>``, etc.) mixed directly inside the parent
        element rather than as a dedicated child element.  This method collects those
        markup children — those whose local tag name is not in *known_xml_names* —
        and converts them to a Markdown string.
        """
        use_name = child_nd.get("use-name", "")
        datatype = child_nd.get("datatype", "string")

        # Build a synthetic element holding only the markup children.
        # ET.append does not remove children from the original element, so sharing
        # the child objects here is safe.
        prose_elem = ET.Element("_prose")
        prose_elem.text = element.text  # text before the first child element
        for child in element:
            if _local(child.tag) not in known_xml_names:
                prose_elem.append(child)

        md_text = (
            _markup_to_md(prose_elem, datatype)
            if datatype in _MARKUP_TYPES
            else (prose_elem.text or "").strip()
        )
        if md_text:
            result[use_name] = md_text

    def _xml_child(
        self,
        parent: Element,
        child_nd: dict,
        result: dict,
        cardinality: dict | None = None,
    ) -> None:
        """
        Locate XML elements matching one index child node and add them to result.

        ``cardinality`` overrides max-occurs when the caller is a resolved
        recursive stub whose reference carries different cardinality than the
        definition itself.
        """
        use_name     = child_nd.get("use-name", "")
        group_as     = child_nd.get("group-as") or ""
        group_in_xml = child_nd.get("group-as-in-xml") or ""
        group_in_json= child_nd.get("group-as-in-json") or ""
        json_key_flag= child_nd.get("json-key") or ""
        max_occurs   = (cardinality or child_nd).get("max-occurs", "1")

        # Locate the XML source elements
        if group_in_xml == "GROUPED" and group_as:
            wrapper = next((e for e in parent if _local(e.tag) == group_as), None)
            if wrapper is None:
                return
            elems = [e for e in wrapper if _local(e.tag) == use_name]
        else:
            elems = [e for e in parent if _local(e.tag) == use_name]

        if not elems:
            return

        json_name = group_as or use_name

        if group_in_json == "BY_KEY" and json_key_flag:
            obj: dict = {}
            for elem in elems:
                key = elem.get(json_key_flag) or _local(elem.tag)
                sub = self._elem_to_dict(elem, child_nd)
                if isinstance(sub, dict):
                    sub.pop(json_key_flag, None)
                obj[key] = sub
            result[json_name] = obj

        elif group_in_json == "SINGLETON_OR_ARRAY":
            converted = [self._elem_to_dict(e, child_nd) for e in elems]
            result[json_name] = converted[0] if len(converted) == 1 else converted

        elif max_occurs == "unbounded" or group_in_json == "ARRAY":
            result[json_name] = [self._elem_to_dict(e, child_nd) for e in elems]

        else:
            result[json_name] = self._elem_to_dict(elems[0], child_nd)

    def _xml_any(self, element: Element, node: dict, result: dict) -> None:
        """Collect child XML elements not described by the model into _unmodeled."""
        known: set[str] = set()
        for cn in node.get("children") or []:
            if not cn or cn.get("structure-type") == "any":
                continue
            if cn.get("structure-type") == "choice":
                for alt in cn.get("children") or []:
                    if alt:
                        known.add(alt.get("use-name", ""))
                        if alt.get("group-as"):
                            known.add(alt["group-as"])
            else:
                known.add(cn.get("use-name", ""))
                if cn.get("group-as"):
                    known.add(cn["group-as"])
        for fn in [c for c in node.get("children") or [] if c and c.get("structure-type") == "flag"]:
            known.add(fn.get("use-name", ""))

        unmodeled: dict = {}
        for child in element:
            ln = _local(child.tag)
            if ln not in known:
                unmodeled.setdefault(ln, [])
                unmodeled[ln].append(ET.tostring(child, encoding="unicode"))
        if unmodeled:
            result["_unmodeled"] = unmodeled

    # ------------------------------------------------------------------
    # JSON → XML
    # ------------------------------------------------------------------

    def _dict_to_elem(
        self,
        json_obj: dict,
        node: dict,
        tag_override: str | None = None,
    ) -> Element:
        """Convert a JSON dict to an XML Element given its index node."""
        node  = self._resolve(node)
        tag   = tag_override or node.get("use-name") or self.model
        stype = node.get("structure-type", "")
        elem  = Element(f"{{{self.namespace}}}{tag}")
        remaining = dict(json_obj)

        # 1. Flags → XML attributes
        for flag_nd in [c for c in node.get("children") or [] if c and c.get("structure-type") == "flag"]:
            fname = flag_nd.get("use-name", "")
            if fname in remaining:
                val = remaining.pop(fname)
                elem.set(fname, "true" if val is True else "false" if val is False else str(val))

        # 2. Field value → XML text/markup content
        if stype == "field":
            datatype = node.get("datatype", "string")
            jvk      = node.get("json-value-key") or ""
            jvkf     = node.get("json-value-key-flag") or ""

            if jvk and jvk in remaining:
                val = remaining.pop(jvk)
                if datatype in _MARKUP_TYPES:
                    _md_to_xml(str(val), elem, datatype, self.namespace)
                else:
                    elem.text = str(val)

            elif jvkf:
                # The first remaining key is the flag value; its value is the text
                for k, v in list(remaining.items()):
                    elem.set(jvkf, k)
                    if datatype in _MARKUP_TYPES:
                        _md_to_xml(str(v), elem, datatype, self.namespace)
                    else:
                        elem.text = str(v)
                    del remaining[k]
                    break

            elif "STRVALUE" in remaining:
                elem.text = str(remaining.pop("STRVALUE"))

        # 3. Children → XML sub-elements (in index order)
        self._json_children(remaining, node, elem)

        if remaining:
            logger.debug(f"Unprocessed JSON keys for <{tag}>: {list(remaining.keys())}")

        return elem

    def _json_children(self, remaining: dict, node: dict, parent: Element) -> None:
        """Emit XML child elements from remaining JSON keys, guided by the index."""
        for child_nd in node.get("children") or []:
            if not child_nd:
                continue
            stype = child_nd.get("structure-type", "")

            if child_nd.get("wrapped-in-xml") is False:
                self._json_unwrapped_field(remaining, child_nd, parent)
            elif stype == "choice":
                for alt in child_nd.get("children") or []:
                    if alt:
                        self._json_child(remaining, alt, parent)
            elif stype == "any":
                self._json_any(remaining, parent)
            elif stype == "recursive":
                self._json_child(remaining, self._resolve(child_nd), parent, cardinality=child_nd)
            else:
                self._json_child(remaining, child_nd, parent)

    def _json_unwrapped_field(
        self,
        remaining: dict,
        child_nd: dict,
        parent: Element,
    ) -> None:
        """
        Emit inline markup content for a field with ``wrapped-in-xml: false``.

        These fields (e.g. ``prose``) store Markdown in JSON but have no dedicated
        XML wrapper element.  The Markdown is converted to block-level HTML elements
        and appended directly inside *parent*.
        """
        use_name = child_nd.get("use-name", "")
        datatype = child_nd.get("datatype", "string")

        if use_name not in remaining:
            return
        md_text = remaining.pop(use_name)
        if not md_text:
            return

        if datatype in _MARKUP_TYPES:
            _md_to_xml(str(md_text), parent, datatype, self.namespace)
        else:
            # Plain-text embedded field: append as text on the parent
            parent.text = (parent.text or "") + str(md_text)

    def _json_child(
        self,
        remaining: dict,
        child_nd: dict,
        parent: Element,
        cardinality: dict | None = None,
    ) -> None:
        """Emit XML element(s) for one index child node from remaining JSON keys."""
        use_name     = child_nd.get("use-name", "")
        group_as     = child_nd.get("group-as") or ""
        group_in_xml = child_nd.get("group-as-in-xml") or ""
        group_in_json= child_nd.get("group-as-in-json") or ""
        json_key_flag= child_nd.get("json-key") or ""
        max_occurs   = (cardinality or child_nd).get("max-occurs", "1")
        ns           = self.namespace
        json_name    = group_as or use_name

        if json_name not in remaining:
            return
        json_val = remaining.pop(json_name)

        def container() -> Element:
            """Return the element to append children to, creating a wrapper if needed."""
            if group_in_xml == "GROUPED" and group_as:
                return SubElement(parent, f"{{{ns}}}{group_as}")
            return parent

        if group_in_json == "BY_KEY" and json_key_flag:
            c = container()
            if isinstance(json_val, dict):
                for key, obj in json_val.items():
                    child_obj = dict(obj) if isinstance(obj, dict) else {"STRVALUE": str(obj)}
                    child_obj[json_key_flag] = key
                    c.append(self._dict_to_elem(child_obj, child_nd, use_name))

        elif max_occurs == "unbounded" or group_in_json in ("ARRAY", "SINGLETON_OR_ARRAY"):
            items = json_val if isinstance(json_val, list) else [json_val]
            c = container()
            datatype = child_nd.get("datatype", "string")
            for item in items:
                if isinstance(item, dict):
                    c.append(self._dict_to_elem(item, child_nd, use_name))
                else:
                    child_elem = Element(f"{{{ns}}}{use_name}")
                    if datatype in _MARKUP_TYPES:
                        _md_to_xml(str(item), child_elem, datatype, self.namespace)
                    else:
                        child_elem.text = str(item)
                    c.append(child_elem)

        else:
            if isinstance(json_val, dict):
                parent.append(self._dict_to_elem(json_val, child_nd, use_name))
            else:
                child_elem = Element(f"{{{ns}}}{use_name}")
                datatype = child_nd.get("datatype", "string")
                if datatype in _MARKUP_TYPES:
                    _md_to_xml(str(json_val), child_elem, datatype, self.namespace)
                else:
                    child_elem.text = str(json_val)
                parent.append(child_elem)

    def _json_any(self, remaining: dict, parent: Element) -> None:
        """Re-emit unmodeled content stored under the _unmodeled key."""
        unmodeled = remaining.pop("_unmodeled", None)
        if not unmodeled:
            return
        for xml_strings in unmodeled.values():
            for xml_str in xml_strings:
                try:
                    parent.append(ET.fromstring(xml_str))
                except ET.ParseError as exc:
                    logger.warning(f"Could not re-parse unmodeled content: {exc}")


# ---------------------------------------------------------------------------
# OSCALPath – XPath-like query engine for OSCAL JSON
# ---------------------------------------------------------------------------

class _PathStep:
    """One step in a parsed XPath-like expression."""
    __slots__ = ("axis", "name", "predicates")

    def __init__(self, axis: str, name: str, predicates: list) -> None:
        self.axis = axis            # "child" | "descendant" | "attribute" |
                                    # "wildcard" | "self" | "text" | "name_func"
        self.name = name            # XML element or attribute name; "" for specials
        self.predicates = predicates  # list of _PathPred


class _PathPred:
    """A predicate clause inside ``[...]``."""
    __slots__ = ("lhs", "op", "rhs", "negated")

    def __init__(self, lhs: list, op: str, rhs: "str | None", negated: bool) -> None:
        self.lhs = lhs          # list of _PathStep (path to compare value)
        self.op = op            # "=" | "!=" | "<" | ">" | "<=" | ">=" | "" (existence)
        self.rhs = rhs          # right-hand side literal, or None for existence test
        self.negated = negated  # True when wrapped in not(...)


def _opath_extract_bracket(path: str, start: int) -> tuple[str, int]:
    """Return (inner_content, end_idx) for the ``[...]`` block starting at *start*."""
    depth = 0
    i = start
    while i < len(path):
        if path[i] == "[":
            depth += 1
        elif path[i] == "]":
            depth -= 1
            if depth == 0:
                return path[start + 1 : i], i + 1
        i += 1
    return path[start + 1 :], len(path)


# Matches: <lhs-path> <op> "<rhs>" or '<rhs>'
_PRED_CMP_RE = re.compile(
    r"^(.+?)\s*(!=|<=|>=|=|<|>)\s*(?:\"([^\"]*)\"|'([^']*)')\s*$",
    re.DOTALL,
)


def _opath_parse_pred(s: str) -> _PathPred:
    """Parse a predicate string (the content between ``[`` and ``]``)."""
    s = s.strip()
    negated = False
    m_not = re.match(r"not\s*\((.+)\)\s*$", s, re.DOTALL)
    if m_not:
        s = m_not.group(1).strip()
        negated = True

    m = _PRED_CMP_RE.match(s)
    if m:
        lhs_path = m.group(1).strip()
        op  = m.group(2)
        rhs = m.group(3) if m.group(3) is not None else m.group(4)
        return _PathPred(_opath_parse(lhs_path), op, rhs, negated)

    # Existence predicate — no operator
    return _PathPred(_opath_parse(s), "", None, negated)


def _opath_parse(path: str) -> list[_PathStep]:
    """
    Parse an XPath-like expression into a list of :class:`_PathStep` objects.

    Supported syntax::

        /*/foo/bar              absolute path (leading / anchors to doc root;
                                /* matches any top-level model object)
        foo/bar                 relative path (from caller-supplied context)
        //foo                   descendant axis — search at any depth
        //foo//bar              chained descendant axes
        @attr                   attribute/flag value
        foo[@id='x']            step with equality predicate
        foo[not(@id)]           step with negated existence predicate
        foo[a/b='x']            step with path-expression predicate
        foo[@a='x'][@b='y']     multiple predicates (all must hold)
        text()                  scalar value of the current node
        *                       wildcard — all direct children
    """
    steps: list[_PathStep] = []
    i = 0
    n = len(path)
    pending_desc = False  # True when the next step uses the descendant axis

    if path.startswith("//"):
        pending_desc = True
        i = 2
    elif path.startswith("/"):
        steps.append(_PathStep("self", "", []))
        i = 1

    while i < n:
        if path[i] == "/":
            if i + 1 < n and path[i + 1] == "/":
                pending_desc = True
                i += 2
            else:
                i += 1
            continue

        axis = "descendant" if pending_desc else "child"
        pending_desc = False

        if path[i] == "@":
            i += 1
            m = re.match(r"[\w\-\.]+", path[i:])
            name = m.group() if m else ""
            if m:
                i += m.end()
            steps.append(_PathStep("attribute", name, []))

        elif path[i] == "*":
            steps.append(_PathStep("wildcard", "", []))
            i += 1

        elif path[i : i + 6] == "text()":
            steps.append(_PathStep("text", "", []))
            i += 6

        elif path[i : i + 6] == "name()":
            steps.append(_PathStep("name_func", "", []))
            i += 6

        else:
            m = re.match(r"[\w\-\.]+", path[i:])
            if not m:
                i += 1
                continue
            name = m.group()
            i += m.end()

            preds: list[_PathPred] = []
            while i < n and path[i] == "[":
                pred_str, i = _opath_extract_bracket(path, i)
                preds.append(_opath_parse_pred(pred_str))

            steps.append(_PathStep(axis, name, preds))

    return steps


class OSCALPath:
    """
    XPath-like query engine for OSCAL JSON data.

    Uses the metaschema index to translate XML path steps into the correct JSON
    navigation — resolving element names to their JSON keys, and handling the
    different container types (ARRAY, BY_KEY, SINGLETON_OR_ARRAY, scalar).

    Parameters
    ----------
    model_index
        Model-specific metaschema index dict (the value at
        ``full_index["oscal_models"][model_name]``).  The same dict accepted
        by :class:`OSCALConverter`.

    Examples
    --------
    ::

        path = OSCALPath(catalog_model_index)

        # Descendant search with attribute predicate
        controls = path.query("//control[@id='ac-2.2']", doc)

        # Absolute path
        title = path.query_one("/*/metadata/title", doc)

        # Relative path from a sub-dict
        ver = path.query_one("oscal-version", doc["catalog"]["metadata"])

        # Path expression inside a predicate
        labelled = path.query("//part[prop[@name='label']]", doc)

        # Multiple predicates
        specific = path.query("//param[@id='ac-1_prm_1'][select]", doc)
    """

    _SKIP_KEYS: frozenset[str] = frozenset({"$schema", "_unmodeled"})

    def __init__(self, model_index: dict) -> None:
        self.root_node: dict = model_index.get("nodes") or {}
        self._defs: dict[str, dict] = {}
        # xml_name → list of spec dicts
        self._name_map: dict[str, list[dict]] = {}
        self._build_index(self.root_node, frozenset())

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def _build_index(self, node: dict | None, visited: frozenset) -> None:
        if not node:
            return
        stype = node.get("structure-type", "")
        if stype == "recursive":
            return

        name = node.get("name", "")
        if name and stype in ("assembly", "field") and name not in self._defs:
            self._defs[name] = node

        node_id = id(node)
        if node_id in visited:
            return
        visited = visited | {node_id}

        xml_name = node.get("use-name") or name
        if xml_name and stype not in ("", "choice", "any"):
            spec = self._make_spec(xml_name, node)
            bucket = self._name_map.setdefault(xml_name, [])
            if not any(s["json_key"] == spec["json_key"] for s in bucket):
                bucket.append(spec)

        for child in node.get("children") or []:
            if not child:
                continue
            if child.get("structure-type") == "choice":
                # Recurse into each alternative — they all live at the same level
                for alt in child.get("children") or []:
                    if alt:
                        self._build_index(self._resolve_def(alt), visited)
            else:
                self._build_index(self._resolve_def(child), visited)

        for flag in [c for c in node.get("children") or [] if c and c.get("structure-type") == "flag"]:
            fn = flag.get("use-name") or flag.get("name", "")
            if fn:
                bucket = self._name_map.setdefault(fn, [])
                spec = {"xml_name": fn, "json_key": fn, "container": "SCALAR",
                        "key_flag": "", "node": flag}
                if not any(s["json_key"] == fn for s in bucket):
                    bucket.append(spec)

    def _make_spec(self, xml_name: str, node: dict) -> dict:
        group_as   = node.get("group-as") or ""
        json_key   = group_as or xml_name
        group_json = node.get("group-as-in-json") or ""
        key_flag   = node.get("json-key") or ""
        max_occurs = node.get("max-occurs", "1")
        stype      = node.get("structure-type", "")

        if group_json == "BY_KEY" and key_flag:
            container = "BY_KEY"
        elif group_json == "ARRAY" or max_occurs == "unbounded":
            container = "ARRAY"
        elif group_json == "SINGLETON_OR_ARRAY":
            container = "SINGLETON_OR_ARRAY"
        elif stype == "flag":
            container = "SCALAR"
        else:
            container = "OBJECT"

        return {
            "xml_name": xml_name,
            "json_key":  json_key,
            "container": container,
            "key_flag":  key_flag,
            "node":      node,
        }

    def _resolve_def(self, node: dict) -> dict:
        if node.get("structure-type") == "recursive":
            return self._defs.get(node.get("name", ""), node)
        return node

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(self, path: str, data) -> list:
        """
        Return a list of all JSON values matching *path* in *data*.

        *data* is normally the full parsed OSCAL JSON document
        (``{"catalog": {...}}``) for absolute paths, or any sub-dict for
        relative paths.  Scalar results (strings, numbers) are returned as-is.
        """
        steps = _opath_parse(path)
        return self._eval_steps(steps, [data])

    def query_one(self, path: str, data, default=None):
        """Return the first matching value, or *default* when nothing matches."""
        results = self.query(path, data)
        return results[0] if results else default

    # ------------------------------------------------------------------
    # Step evaluation
    # ------------------------------------------------------------------

    def _eval_steps(self, steps: list[_PathStep], ctx: list) -> list:
        for step in steps:
            if not ctx:
                break
            ctx = self._eval_step(step, ctx)
        return ctx

    def _eval_step(self, step: _PathStep, ctx: list) -> list:
        axis, name, preds = step.axis, step.name, step.predicates
        out: list = []

        for val in ctx:
            if axis == "self":
                cands = [val]
            elif axis == "child":
                cands = list(self._child(val, name))
            elif axis == "descendant":
                cands = list(self._descendants(val, name))
            elif axis == "attribute":
                cands = list(self._attribute(val, name))
            elif axis == "wildcard":
                cands = list(self._wildcard(val))
            elif axis == "text":
                cands = list(self._text(val))
            elif axis == "name_func":
                # name() on a top-level dict: return the root model key
                if isinstance(val, dict):
                    cands = [k for k in val if not k.startswith("$") and not k.startswith("_")]
                else:
                    cands = []
            else:
                cands = []

            # Apply predicates (all must hold — AND semantics)
            for pred in preds:
                cands = [c for c in cands if self._eval_pred(pred, c)]

            out.extend(cands)

        return out

    # ------------------------------------------------------------------
    # Navigation primitives
    # ------------------------------------------------------------------

    def _child(self, val, name: str):
        """Yield JSON values that are direct children named *name* in XML terms."""
        if not isinstance(val, dict):
            return
        specs = self._name_map.get(name)
        if specs:
            for spec in specs:
                jk = spec["json_key"]
                if jk in val:
                    yield from self._extract(val[jk], spec)
        else:
            # No index entry — try the key directly (flags, $schema, etc.)
            if name in val:
                raw = val[name]
                if isinstance(raw, list):
                    yield from raw
                else:
                    yield raw

    def _descendants(self, val, name: str):
        """Yield all values at any depth that match XML element name *name*."""
        # Direct children first
        yield from self._child(val, name)
        # Recurse
        if isinstance(val, dict):
            for k, v in val.items():
                if k in self._SKIP_KEYS:
                    continue
                if isinstance(v, (dict, list)):
                    yield from self._descendants(v, name)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, (dict, list)):
                    yield from self._descendants(item, name)

    def _attribute(self, val, name: str):
        """Yield the value of attribute/flag *name* from *val*."""
        if isinstance(val, dict) and name in val:
            yield val[name]

    def _wildcard(self, val):
        """Yield all direct children of *val*."""
        if isinstance(val, dict):
            for k, v in val.items():
                if k not in self._SKIP_KEYS:
                    yield v
        elif isinstance(val, list):
            yield from val

    def _text(self, val):
        """Yield the scalar text/value of *val*."""
        if isinstance(val, (str, int, float, bool)):
            yield val
        elif isinstance(val, dict):
            # Fields with flags store their text under STRVALUE
            for key in ("STRVALUE", "value"):
                if key in val:
                    yield val[key]
                    return

    def _extract(self, raw, spec: dict):
        """
        Yield item(s) from a raw JSON value according to the metaschema container
        type recorded in *spec*.

        For BY_KEY groups the dict key is re-injected as a field (using the
        ``json-key`` flag name) so that predicates like ``[@param-id='x']``
        work even though the key was extracted from the item in JSON.
        """
        container = spec["container"]
        key_flag  = spec.get("key_flag", "")

        if container == "ARRAY":
            if isinstance(raw, list):
                yield from raw

        elif container == "BY_KEY":
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(v, dict):
                        # Re-inject the key so attribute predicates can match it
                        yield {key_flag: k, **v} if key_flag else v
                    else:
                        yield {key_flag: k, "value": v} if key_flag else {"value": v}

        elif container == "SINGLETON_OR_ARRAY":
            if isinstance(raw, list):
                yield from raw
            elif raw is not None:
                yield raw

        else:  # OBJECT or SCALAR
            if raw is not None:
                yield raw

    # ------------------------------------------------------------------
    # Predicate evaluation
    # ------------------------------------------------------------------

    def _eval_pred(self, pred: _PathPred, val) -> bool:
        lhs_vals = self._eval_steps(pred.lhs, [val])

        if pred.op:
            result = any(self._compare(v, pred.op, pred.rhs) for v in lhs_vals)
        else:
            result = bool(lhs_vals)  # existence check

        return not result if pred.negated else result

    def _compare(self, val, op: str, rhs: "str | None") -> bool:
        if rhs is None:
            return False
        s = str(val) if not isinstance(val, str) else val
        if op == "=":
            return s == rhs
        if op == "!=":
            return s != rhs
        try:
            a: float | str = float(s)
            b: float | str = float(rhs)
        except (ValueError, TypeError):
            a, b = s, rhs
        if op == "<":
            return a < b
        if op == ">":
            return a > b
        if op == "<=":
            return a <= b
        if op == ">=":
            return a >= b
        return False

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_support(cls, model: str, version: str, support=None) -> "OSCALPath | None":
        """
        Build an :class:`OSCALPath` from the support object's processed index.

        Parameters mirror :meth:`OSCALConverter.from_support`.
        """
        conv = OSCALConverter.from_support(model, version, support)
        if conv is None:
            return None
        return cls({"nodes": conv.root_node,
                    "oscal_model": conv.model,
                    "oscal_namespace": conv.namespace,
                    "oscal_version": conv.version})


# ---------------------------------------------------------------------------
# NativePath – JSON-native path query engine (no metaschema index)
# ---------------------------------------------------------------------------

class NativePath:
    """
    Lightweight path query engine that works directly on JSON key names,
    requiring no metaschema index.

    The path syntax is identical to :class:`OSCALPath`, with one key
    difference: steps use the *JSON* key names exactly as they appear in the
    document rather than the XML element names.  For OSCAL JSON that means
    ``controls`` (not ``control``), ``props`` (not ``prop``), etc.

    **Array transparency** — when navigating to a key whose value is a JSON
    array, the array is automatically iterated so subsequent steps and
    predicates apply to each item individually.  Predicate paths work the
    same way:  ``[props[name='label']]`` navigates into the ``props`` array
    and checks each prop item.

    No instantiation arguments are needed; a module-level singleton
    :data:`native_path` is provided for convenience.

    Examples::

        # Descendant search with predicate
        native_path.query("//controls[id='ac-2.2']", doc)

        # Absolute path
        native_path.query_one("/*/metadata/title", doc)

        # Relative path from a sub-dict
        native_path.query("oscal-version", doc["catalog"]["metadata"])

        # Path expression inside a predicate
        native_path.query("//controls[props[name='label']]", doc)

        # Multiple predicates
        native_path.query("//controls[id='ac-2'][controls]", doc)

        # Negation / inequality
        native_path.query("//props[name='label'][value!='']", doc)

        # Existence predicate
        native_path.query("//params[select]", doc)

        # @ prefix works as a synonym for bare key (for XPath familiarity)
        native_path.query("//controls[@id='ac-2.2']", doc)
    """

    _SKIP_KEYS: frozenset[str] = frozenset({"$schema", "_unmodeled"})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(self, path: str, data) -> list:
        """
        Return a list of all values matching *path* in *data*.

        *data* may be the full document dict (for absolute paths starting
        with ``/``) or any sub-dict / value (for relative paths).
        """
        steps = _opath_parse(path)
        return self._eval_steps(steps, [data])

    def query_one(self, path: str, data, default=None):
        """Return the first matching value, or *default* when nothing matches."""
        results = self.query(path, data)
        return results[0] if results else default

    # ------------------------------------------------------------------
    # Step evaluation
    # ------------------------------------------------------------------

    def _eval_steps(self, steps: list[_PathStep], ctx: list) -> list:
        for step in steps:
            if not ctx:
                break
            ctx = self._eval_step(step, ctx)
        return ctx

    def _eval_step(self, step: _PathStep, ctx: list) -> list:
        axis, name, preds = step.axis, step.name, step.predicates
        out: list = []

        for val in ctx:
            if axis == "self":
                cands = [val]
            elif axis in ("child", "attribute"):
                # @ prefix is a synonym for a bare key in JSON
                cands = list(self._child(val, name))
            elif axis == "descendant":
                cands = list(self._descendants(val, name))
            elif axis == "wildcard":
                cands = list(self._wildcard(val))
            elif axis == "text":
                cands = list(self._text(val))
            elif axis == "name_func":
                if isinstance(val, dict):
                    cands = [k for k in val if not k.startswith("$")]
                else:
                    cands = []
            else:
                cands = []

            for pred in preds:
                cands = [c for c in cands if self._eval_pred(pred, c)]

            out.extend(cands)

        return out

    # ------------------------------------------------------------------
    # Navigation primitives
    # ------------------------------------------------------------------

    def _child(self, val, name: str):
        """
        Navigate to key *name* in *val*.  When the value is a list, yield
        each item so the next step applies to items individually.
        """
        if not isinstance(val, dict):
            return
        if name not in val:
            return
        raw = val[name]
        if isinstance(raw, list):
            yield from raw
        else:
            yield raw

    def _descendants(self, val, name: str):
        """
        Recursively find key *name* at any depth, auto-iterating arrays
        encountered along the way.
        """
        yield from self._child(val, name)

        if isinstance(val, dict):
            for k, v in val.items():
                if k in self._SKIP_KEYS:
                    continue
                if isinstance(v, (dict, list)):
                    yield from self._descendants(v, name)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, (dict, list)):
                    yield from self._descendants(item, name)

    def _wildcard(self, val):
        """Yield all direct children (values of a dict, or items of a list)."""
        if isinstance(val, dict):
            for k, v in val.items():
                if k not in self._SKIP_KEYS:
                    yield v
        elif isinstance(val, list):
            yield from val

    def _text(self, val):
        """Yield *val* itself when it is a scalar."""
        if isinstance(val, (str, int, float, bool)):
            yield val

    # ------------------------------------------------------------------
    # Predicate evaluation
    # ------------------------------------------------------------------

    def _eval_pred(self, pred: _PathPred, val) -> bool:
        lhs_vals = self._eval_steps(pred.lhs, [val])
        if pred.op:
            result = any(self._compare(v, pred.op, pred.rhs) for v in lhs_vals)
        else:
            result = bool(lhs_vals)  # existence check
        return not result if pred.negated else result

    def _compare(self, val, op: str, rhs: "str | None") -> bool:
        if rhs is None:
            return False
        s = str(val) if not isinstance(val, str) else val
        if op == "=":
            return s == rhs
        if op == "!=":
            return s != rhs
        try:
            a: float | str = float(s)
            b: float | str = float(rhs)
        except (ValueError, TypeError):
            a, b = s, rhs
        if op == "<":
            return a < b
        if op == ">":
            return a > b
        if op == "<=":
            return a <= b
        if op == ">=":
            return a >= b
        return False


#: Module-level singleton — use directly without instantiating.
native_path = NativePath()


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------

def xml_to_json(xml_content: str, model_index: dict) -> str | None:
    """Convert OSCAL XML to JSON using the given model index."""
    return OSCALConverter(model_index).xml_to_json(xml_content)


def json_to_xml(json_content: str, model_index: dict) -> str | None:
    """Convert OSCAL JSON to XML using the given model index."""
    return OSCALConverter(model_index).json_to_xml(json_content)


def converter_for(model: str, version: str, support=None) -> "OSCALConverter | None":
    """
    Return an ``OSCALConverter`` loaded from the support object's processed
    metaschema index.  Equivalent to ``OSCALConverter.from_support(...)``.
    """
    return OSCALConverter.from_support(model, version, support)


def _detect_oscal_version(content: str, fmt: str) -> str:
    """
    Extract the OSCAL version string from document content.

    For XML, searches for ``<oscal-version>`` inside ``<metadata>``.
    For JSON, checks the ``$schema`` URL or ``metadata.oscal-version``.
    Returns a version string like ``"v1.2.0"``, or ``""`` if not found.
    """
    if fmt == "xml":
        try:
            root = ET.fromstring(content.encode("utf-8"))
            for elem in root.iter():
                if _local(elem.tag) == "oscal-version" and elem.text:
                    ver = elem.text.strip()
                    return ver if ver.startswith("v") else f"v{ver}"
        except ET.ParseError:
            pass

    elif fmt == "json":
        try:
            doc = json.loads(content)
            schema_url = doc.get("$schema", "")
            m = re.search(r"/(v\d+\.\d+\.\d+)/", schema_url)
            if m:
                return m.group(1)
            for root_val in doc.values():
                if isinstance(root_val, dict):
                    meta = root_val.get("metadata", {})
                    if isinstance(meta, dict):
                        ver = meta.get("oscal-version", "")
                        if ver:
                            return ver if ver.startswith("v") else f"v{ver}"
        except (json.JSONDecodeError, AttributeError):
            pass

    return ""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import argparse
    from pathlib import Path

    _SUPPORTED_FORMATS = {"xml", "json"}

    ap = argparse.ArgumentParser(
        description="Convert an OSCAL file between XML and JSON.",
        epilog="The OSCAL metaschema index must already be built (run parse_metaschema first).",
    )
    ap.add_argument("source", help="Source file (.xml or .json)")
    ap.add_argument("target", help="Target file (.json or .xml)")
    ap.add_argument(
        "--oscal-version", "-v",
        default="",
        metavar="VERSION",
        help="OSCAL version, e.g. v1.2.0 (auto-detected from file if omitted)",
    )
    args = ap.parse_args()

    src_path = Path(args.source)
    tgt_path = Path(args.target)

    if not src_path.exists():
        print(f"ERROR: source file not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    src_fmt = src_path.suffix.lstrip(".").lower()
    tgt_fmt = tgt_path.suffix.lstrip(".").lower()

    if src_fmt not in _SUPPORTED_FORMATS:
        print(f"ERROR: unrecognised source extension '{src_path.suffix}' (expected .xml or .json)", file=sys.stderr)
        sys.exit(1)
    if tgt_fmt not in _SUPPORTED_FORMATS:
        print(f"ERROR: unrecognised target extension '{tgt_path.suffix}' (expected .xml or .json)", file=sys.stderr)
        sys.exit(1)
    if src_fmt == tgt_fmt:
        print(f"ERROR: source and target are both {src_fmt.upper()} — nothing to convert", file=sys.stderr)
        sys.exit(1)

    content = src_path.read_text(encoding="utf-8")

    # Detect model name from document root
    model = ""
    if src_fmt == "xml":
        try:
            _root = ET.fromstring(content.encode("utf-8"))
            model = _local(_root.tag)
        except ET.ParseError as exc:
            print(f"ERROR: could not parse XML: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            _doc = json.loads(content)
            model = next((k for k in _doc if not k.startswith("$") and not k.startswith("_")), "")
        except json.JSONDecodeError as exc:
            print(f"ERROR: could not parse JSON: {exc}", file=sys.stderr)
            sys.exit(1)

    if not model:
        print("ERROR: could not detect OSCAL model from source file", file=sys.stderr)
        sys.exit(1)

    # Detect OSCAL version
    oscal_version = args.oscal_version or _detect_oscal_version(content, src_fmt)
    if not oscal_version:
        print(
            "ERROR: could not detect OSCAL version from source file. "
            "Use --oscal-version to specify it explicitly.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Model:   {model}")
    print(f"Version: {oscal_version}")
    print(f"Convert: {src_fmt.upper()} → {tgt_fmt.upper()}")

    conv = converter_for(model, oscal_version)
    if conv is None:
        print(
            f"ERROR: no metaschema index found for model '{model}' version '{oscal_version}'.\n"
            "Update the support module to add this version.",
            file=sys.stderr,
        )
        sys.exit(1)

    result = conv.xml_to_json(content) if src_fmt == "xml" else conv.json_to_xml(content)

    if result is None:
        print("ERROR: conversion failed — check logs for details", file=sys.stderr)
        sys.exit(1)

    tgt_path.parent.mkdir(parents=True, exist_ok=True)
    tgt_path.write_text(result, encoding="utf-8")
    print(f"Written: {tgt_path}")
