"""OSCAL Metaschema documentation views.

Generates HTML fragments from the parsed metaschema index for embedding in a
front-end:

* :func:`render_outline` — a clickable, format-flavored tree (XML/JSON/YAML syntax)
  of a model's structure, annotated with data types and cardinality. Every element
  links to its node via a stable reference id.
* :func:`render_detail` — a one-level detail view of a single node (formal name,
  description, format-appropriate representation, data type + regex, constraints,
  and clickable immediate parent/children), addressed by that reference id.

Reference ids are the deterministic ``ref`` UUIDs assigned to every index node by
``metaschema_parser._assign_node_refs`` (surfaced when the index is loaded), so a
link in an outline unambiguously resolves to exactly one node.

All returned HTML is wrapped in a ``<div>`` and never includes ``<html>``/``<body>``,
so it can be dropped straight into a page. Prefer the ``OSCALSupport.view_outline``
and ``OSCALSupport.view_detail`` methods, which resolve the index for you.
"""
from __future__ import annotations

import logging
import sys
from html import escape

from .oscal_datatypes import OSCAL_DATATYPES

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = ("xml", "json", "yaml")

# JSON/YAML scalar types that are rendered without surrounding quotes.
_UNQUOTED_TYPES = {
    "boolean", "integer", "non-negative-integer", "positive-integer", "decimal", "number",
}

_STYLE = (
    "<style>"
    ".ms-outline,.ms-detail{font-family:system-ui,Arial,sans-serif;font-size:14px;color:#1a202c}"
    ".ms-tree{list-style:none;margin:0;padding-left:18px}"
    ".ms-root{padding-left:0}"
    ".ms-item{margin:2px 0}"
    ".ms-node{color:#2b6cb0;text-decoration:none;cursor:pointer}"
    ".ms-node:hover{text-decoration:underline}"
    ".ms-meta{color:#718096;font-size:.85em}"
    ".ms-muted{color:#718096}"
    ".ms-header,.ms-detail-name{font-weight:700}"
    ".ms-detail-name{font-size:1.1em}"
    ".ms-regex{white-space:pre-wrap;word-break:break-all}"
    ".ms-repr{background:#f7fafc;border:1px solid #e2e8f0;padding:8px;border-radius:4px;overflow:auto}"
    ".ms-detail-section{margin-top:12px}"
    ".ms-detail-section h4{margin:0 0 4px;font-size:.75em;letter-spacing:.04em;text-transform:uppercase;color:#718096}"
    ".ms-values,.ms-child-list{margin:4px 0;padding-left:18px}"
    ".ms-error{color:#c53030;font-family:system-ui,Arial,sans-serif}"
    ".ms-dep{color:#c05621;font-size:.85em}"
    "</style>"
)


# ---------------------------------------------------------------------------
# Small structural helpers
# ---------------------------------------------------------------------------
def _normalize_format(oscal_format: str) -> str | None:
    """Return a canonical format string (xml|json|yaml), or None if unrecognized."""
    if not isinstance(oscal_format, str):
        return None
    fmt = oscal_format.strip().lower()
    if fmt == "yml":
        fmt = "yaml"
    return fmt if fmt in SUPPORTED_FORMATS else None


def _json_key(node: dict) -> str:
    """The JSON/YAML key for a node (group-as wins for arrays)."""
    return node.get("group-as") or node.get("use-name") or node.get("name") or "?"


def _xml_name(node: dict) -> str:
    """The XML element/flag name for a node."""
    return node.get("use-name") or node.get("name") or "?"


def _is_array(node: dict) -> bool:
    return str(node.get("max-occurs", "1")) == "unbounded"


def _cardinality(node: dict) -> str:
    """Human-readable ``min..max`` for a node (e.g. ``0..1``, ``1..*``)."""
    mn = str(node.get("min-occurs", "0"))
    mx = str(node.get("max-occurs", "1"))
    table = {
        ("0", "1"): "0..1",
        ("1", "1"): "1..1",
        ("0", "unbounded"): "0..*",
        ("1", "unbounded"): "1..*",
    }
    return table.get((mn, mx), f"{mn}..{mx}")


def _description(node: dict) -> str:
    """Join a node's description (stored as a list of strings) into one string."""
    desc = node.get("description")
    if isinstance(desc, list):
        desc = " ".join(str(d) for d in desc if d)
    return (desc or "").strip()


def _choice_members(choice_node: dict) -> list:
    """Flatten a choice's alternative member nodes (recursing nested choices)."""
    members = []
    for member in choice_node.get("children", []) or []:
        if isinstance(member, dict) and member.get("structure-type") == "choice":
            members.extend(_choice_members(member))
        elif isinstance(member, dict):
            members.append(member)
    return members


def _choice_required(choice_node: dict) -> bool:
    """True when a choice requires a selection (every member is ``min-occurs=1``)."""
    members = _choice_members(choice_node)
    return bool(members) and all((m.get("min-occurs") or "0") == "1" for m in members)


# ---------------------------------------------------------------------------
# Reference lookup
# ---------------------------------------------------------------------------
def _ref_map(index: dict) -> dict:
    """Build a ``ref`` -> node map for one index (walks the tree once)."""
    root = (index or {}).get("nodes")
    mapping: dict = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        ref = node.get("ref")
        if ref and ref not in mapping:
            mapping[ref] = node
        for child in node.get("children", []) or []:
            walk(child)

    walk(root)
    return mapping


def find_node_by_ref(index: dict, ref: str):
    """Return the node in ``index`` whose reference id is ``ref``, or None."""
    return _ref_map(index).get(ref)


# ---------------------------------------------------------------------------
# Labels / representation
# ---------------------------------------------------------------------------
def _node_label_html(node: dict, fmt: str) -> str:
    """HTML for a node's own token, flavored for the format."""
    stype = node.get("structure-type", "")
    if stype == "choice":
        return "&lt;choice&gt;" if fmt == "xml" else "(choice)"
    if stype == "any":
        return "&lt;any&gt;" if fmt == "xml" else "(any)"
    if stype == "recursive":
        return escape(node.get("use-name") or node.get("name") or "?") + ' <span class="ms-muted">(recursive)</span>'
    if fmt == "xml":
        if stype == "flag":
            return "@" + escape(_xml_name(node))
        return "&lt;" + escape(_xml_name(node)) + "&gt;"
    return escape(_json_key(node))


def _node_label_text(node: dict, fmt: str) -> str:
    """Plain-text token (used inside representation snippets)."""
    stype = node.get("structure-type", "")
    if fmt == "xml":
        if stype == "flag":
            return "@" + _xml_name(node)
        return "<" + _xml_name(node) + ">"
    return _json_key(node)


def _meta_html(node: dict, fmt: str) -> str:
    """The muted annotation after a node: structure-type, data type, cardinality."""
    stype = node.get("structure-type", "")
    if stype == "choice":
        detail = "select one (required)" if _choice_required(node) else "select at most one"
        return escape(f"choice · {detail}")
    bits = [stype] if stype else []
    if stype in ("field", "flag") and node.get("datatype"):
        bits.append(str(node["datatype"]))
    if stype not in ("choice", "any"):
        bits.append("[" + _cardinality(node) + "]")
    return escape(" · ".join(b for b in bits if b))


def _json_placeholder(datatype: str) -> str:
    token = f"‹{datatype}›"
    return token if datatype in _UNQUOTED_TYPES else f'"{token}"'


def _representation(node: dict, fmt: str) -> str:
    """A short, format-appropriate snippet showing how the node appears."""
    stype = node.get("structure-type", "")
    datatype = node.get("datatype") or "string"

    if stype == "choice":
        return "one of: " + " | ".join(_node_label_text(m, fmt) for m in _choice_members(node))
    if stype in ("any", "recursive"):
        return ""

    if fmt == "xml":
        name = _xml_name(node)
        if stype == "flag":
            return f'{name}="‹{datatype}›"'
        if stype == "assembly":
            return f"<{name}>\n  …\n</{name}>"
        return f"<{name}>‹{datatype}›</{name}>"

    key = _json_key(node)
    if fmt == "json":
        if stype == "assembly":
            return f'"{key}": [ … ]' if _is_array(node) else f'"{key}": {{ … }}'
        return f'"{key}": {_json_placeholder(datatype)}'

    # yaml
    if stype == "assembly":
        return f"{key}:\n  - …" if _is_array(node) else f"{key}:\n  …"
    return f"{key}: ‹{datatype}›"


def _ref_link(node: dict, fmt: str) -> str:
    """An anchor that unambiguously references ``node`` (front-end wires the click)."""
    ref = escape(str(node.get("ref", "")))
    return (f'<a class="ms-node" href="#" data-ref="{ref}" data-format="{escape(fmt)}">'
            f"{_node_label_html(node, fmt)}</a>")


# ---------------------------------------------------------------------------
# Public: error fragment
# ---------------------------------------------------------------------------
def error_html(message: str) -> str:
    """Return a ``<div>`` error fragment (front-end-safe)."""
    return f'<div class="ms-error">{escape(str(message))}</div>'


# ---------------------------------------------------------------------------
# Public: outline
# ---------------------------------------------------------------------------
def _outline_item(node: dict, fmt: str) -> str:
    if not isinstance(node, dict):
        return ""
    stype = escape(node.get("structure-type", ""))
    parts = [f'<li class="ms-item ms-{stype}">', _ref_link(node, fmt)]
    meta = _meta_html(node, fmt)
    if meta:
        parts.append(f' <span class="ms-meta">{meta}</span>')
    children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
    if children:
        parts.append('<ul class="ms-tree">')
        parts.extend(_outline_item(c, fmt) for c in children)
        parts.append("</ul>")
    parts.append("</li>")
    return "".join(parts)


def render_outline(index: dict, oscal_format: str, version: str = "", model: str = "") -> str:
    """Return an HTML ``<div>`` outline tree for a model in the given format.

    Each element is a clickable link carrying its node ``ref`` (and the format), so a
    front-end can request the corresponding detail view. The tree is flavored for the
    format — XML shows ``<element>``/``@flag`` tokens, JSON/YAML show their keys — and
    every node is annotated with its structure type, data type, and cardinality.
    ``choice`` groups are shown explicitly with their mutual-exclusivity/required note.

    Args:
        index (dict, required): A parsed metaschema index (from
            ``OSCALSupport.get_metaschema_index``).
        oscal_format (str, required): ``"xml"``, ``"json"``, or ``"yaml"``.
        version (str, optional): OSCAL version, for the header/data attributes.
        model (str, optional): OSCAL model name, for the header/data attributes.

    Returns:
        str: A ``<div class="ms-outline">`` fragment (or a ``<div class="ms-error">``).
    """
    fmt = _normalize_format(oscal_format)
    if fmt is None:
        return error_html(f"Unknown format '{oscal_format}'. Use one of: {', '.join(SUPPORTED_FORMATS)}.")
    root = (index or {}).get("nodes")
    if not isinstance(root, dict):
        return error_html("Cannot build outline: the metaschema index has no nodes.")

    ver = version or index.get("oscal_version", "")
    mdl = model or index.get("oscal_model", "")
    schema = index.get("schema_name") or mdl
    header = f"{schema} — {fmt.upper()} outline (OSCAL {ver})"
    return (
        f'<div class="ms-outline" data-format="{escape(fmt)}" '
        f'data-oscal-version="{escape(str(ver))}" data-model="{escape(str(mdl))}">'
        f"{_STYLE}"
        f'<div class="ms-header">{escape(header)}</div>'
        f'<ul class="ms-tree ms-root">{_outline_item(root, fmt)}</ul>'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Public: detail
# ---------------------------------------------------------------------------
def _datatype_section(node: dict, fmt: str) -> str:
    if node.get("structure-type") not in ("field", "flag"):
        return ""
    datatype = node.get("datatype")
    if not datatype:
        return ""
    info = OSCAL_DATATYPES.get(datatype, {})
    base = info.get("base-type")
    pattern = info.get("json-pattern") if fmt in ("json", "yaml") else info.get("xml-pattern")
    pattern = pattern or info.get("recommended-pattern")
    doc = info.get("documentation")

    rows = [f'<div><strong>Type:</strong> <code>{escape(str(datatype))}</code>'
            + (f' (base <code>{escape(str(base))}</code>)' if base and base != datatype else "")
            + "</div>"]
    if doc:
        rows.append(f'<div class="ms-muted">{escape(str(doc))}</div>')
    if pattern:
        rows.append(f'<div><strong>Pattern:</strong> <code class="ms-regex">{escape(str(pattern))}</code></div>')
    return '<div class="ms-detail-section"><h4>Data type</h4>' + "".join(rows) + "</div>"


def _constraints_section(node: dict) -> str:
    constraints = [c for c in (node.get("constraints") or []) if isinstance(c, dict) and c.get("type")]
    if not constraints:
        return ""
    out = ['<div class="ms-detail-section"><h4>Constraints</h4>']
    for constraint in constraints:
        ctype = constraint.get("type")
        if ctype == "allowed-values":
            openness = "others permitted" if constraint.get("allow-other") else "closed set"
            out.append(f'<div><strong>Allowed values</strong> <span class="ms-muted">({openness})</span>'
                       '<ul class="ms-values">')
            for value in constraint.get("values", []):
                val = escape(str(value.get("value", "")))
                vdesc = _description({"description": value.get("description")})
                dep = ' <span class="ms-dep">(deprecated)</span>' if value.get("deprecated") else ""
                tail = f' — <span class="ms-muted">{escape(vdesc)}</span>' if vdesc else ""
                out.append(f"<li><code>{val}</code>{dep}{tail}</li>")
            out.append("</ul></div>")
        else:
            target = escape(str(constraint.get("target", "")))
            message = escape(str(constraint.get("message", "") or ""))
            tail = f" target <code>{target}</code>" if target else ""
            tail += f' — <span class="ms-muted">{message}</span>' if message else ""
            out.append(f"<div><strong>{escape(str(ctype))}</strong>{tail}</div>")
    out.append("</div>")
    return "".join(out)


def render_detail(index: dict, ref: str, oscal_format: str) -> str:
    """Return an HTML ``<div>`` detail view of a single node, addressed by ``ref``.

    Includes the node's formal name and description, a format-appropriate
    representation, its data type (with the associated regex where available),
    constraints, and its immediate parent and children (one level deep). The parent
    (unless the node is the root) and every child are clickable using their own
    reference ids so the caller can drill in.

    Args:
        index (dict, required): A parsed metaschema index.
        ref (str, required): The reference id of the node to describe.
        oscal_format (str, required): ``"xml"``, ``"json"``, or ``"yaml"``.

    Returns:
        str: A ``<div class="ms-detail">`` fragment (or a ``<div class="ms-error">``).
    """
    fmt = _normalize_format(oscal_format)
    if fmt is None:
        return error_html(f"Unknown format '{oscal_format}'. Use one of: {', '.join(SUPPORTED_FORMATS)}.")

    mapping = _ref_map(index)
    node = mapping.get(ref)
    if node is None:
        return error_html(f"No metaschema node found for reference '{ref}'.")

    name = node.get("use-name") or node.get("name") or ""
    formal = node.get("formal-name") or name or node.get("structure-type", "node")
    desc = _description(node)

    parts = [
        f'<div class="ms-detail" data-format="{escape(fmt)}" data-ref="{escape(str(ref))}">',
        _STYLE,
        f'<div class="ms-detail-header"><span class="ms-detail-name">{escape(str(formal))}</span> '
        f'<span class="ms-meta">{_meta_html(node, fmt)}</span></div>',
    ]
    if name:
        parts.append(f'<div><code>{escape(str(name))}</code></div>')
    if desc:
        parts.append(f'<div class="ms-detail-desc">{escape(desc)}</div>')

    representation = _representation(node, fmt)
    if representation:
        parts.append('<div class="ms-detail-section"><h4>Representation (' + escape(fmt.upper())
                     + ')</h4><pre class="ms-repr">' + escape(representation) + "</pre></div>")

    parts.append(_datatype_section(node, fmt))
    parts.append(_constraints_section(node))

    # Immediate parent (clickable unless root)
    parent_ref = node.get("parent-ref")
    parts.append('<div class="ms-detail-section"><h4>Parent</h4>')
    parent = mapping.get(parent_ref) if parent_ref else None
    if parent is not None:
        parts.append(_ref_link(parent, fmt) + f' <span class="ms-meta">{_meta_html(parent, fmt)}</span>')
    else:
        parts.append('<span class="ms-muted">(root — no parent)</span>')
    parts.append("</div>")

    # Immediate children (one level, each clickable)
    children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
    parts.append('<div class="ms-detail-section"><h4>Children</h4>')
    if children:
        parts.append('<ul class="ms-child-list">')
        for child in children:
            parts.append(f'<li>{_ref_link(child, fmt)} <span class="ms-meta">{_meta_html(child, fmt)}</span></li>')
        parts.append("</ul>")
    else:
        parts.append('<span class="ms-muted">(no children)</span>')
    parts.append("</div></div>")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Manual entry point: write standalone outline pages for one version's models.
# Run with:  python -m oscal.metaschema_gen_docs [version]
# ---------------------------------------------------------------------------
def _standalone_page(title: str, fragment: str) -> str:
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
            f"<title>{escape(title)}</title></head><body>{fragment}</body></html>")


def _main(oscal_version: str) -> int:
    from .oscal_support import get_support

    support = get_support()
    if oscal_version not in support.versions:
        logger.error("Version %s not available. Have: %s", oscal_version, ", ".join(support.versions))
        return 1

    for model in support.list_models(oscal_version):
        index = support.get_metaschema_index(oscal_version, model)
        if index is None:
            logger.warning("No index for %s/%s; skipping.", oscal_version, model)
            continue
        for fmt in SUPPORTED_FORMATS:
            html_fragment = render_outline(index, fmt, version=oscal_version, model=model)
            out_path = f"{oscal_version}_{model}_{fmt}_outline.html"
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write(_standalone_page(f"{model} {fmt} outline", html_fragment))
            logger.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s - %(message)s",
    )
    version_arg = sys.argv[1] if len(sys.argv) > 1 else "v1.1.3"
    sys.exit(_main(version_arg))
