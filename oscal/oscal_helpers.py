"""
oscal_helpers — model-agnostic helper functions for OSCAL JSON content.

Pure, stateless helpers that operate on plain OSCAL JSON dicts (and markup
text) without needing an ``OSCAL`` instance. Extracted from ``oscal_content``
to keep that module focused on the ``OSCAL`` base class and its content
lifecycle. Nothing here imports ``oscal_content``; ``oscal_content`` imports and
re-exports these names, so existing ``from .oscal_content import ...`` call sites
continue to work unchanged.

Contents:
    new_uuid / _is_valid_uuid       — UUID generation and validation.
    prune_tree_copy                 — depth-limited safe copy of node subtrees.
    _collect_ids / _find_part_by_id / _find_model_element
                                    — id lookups over catalog-shaped dicts.
    append_prop(s) / get_props      — prop read/write helpers.
    append_link(s)                  — link write helpers.
    oscal_markdown_to_html_tree / _format_table_helper
                                    — OSCAL markup → HTML helpers.
"""
from __future__       import annotations
import copy
import uuid
import logging
from typing           import Optional
from xml.etree        import ElementTree

from .oscal_converter import oscal_markdown_to_html, _html_to_et

logger = logging.getLogger(__name__)

# OSCAL default namespace for props, parts and any other ``ns``-qualified
# elements. Mirrors ``oscal_content._OSCAL_NS`` (deliberately kept in sync;
# this module must not import oscal_content).
_OSCAL_NS = "http://csrc.nist.gov/ns/oscal"


# -------------------------------------------------------------------------
def new_uuid() -> str:
    """Generate a new random (version 4) UUID string.

    Returns:
        str: A newly generated UUID in canonical string form.
    """
    return str(uuid.uuid4())


# -------------------------------------------------------------------------
def _is_valid_uuid(value: str) -> bool:
    """Return True if value is a well-formed UUID string."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


# -------------------------------------------------------------------------
def prune_tree_copy(node: dict | None, depth: int | None = None,
                    child_keys: tuple = ("groups", "controls")) -> dict | None:
    """Return a SAFE COPY of *node* with nested structural children limited to *depth*.

    Shared, model-agnostic helper for the node getters (catalog/profile groups and
    controls; assessment ``tasks`` once implemented). The returned value shares no
    references with *node*, so callers may read, mutate, or serialize it without
    affecting the source document — mutation of live content must go through the
    OSCAL-standard-enforcing methods, never through a getter's return value.

    Only the collections named in *child_keys* are treated as structural children
    subject to depth pruning. The node's own intrinsic content (e.g. ``props``,
    ``links``, ``params``, ``parts``, ``title``) is always copied in full.

        depth = None  -> unlimited: a full deep copy of the entire subtree (the
                         default; mirrors the historical getter behavior).
        depth = 0     -> node only: the *child_keys* collections are omitted.
        depth = N     -> N levels of structural children retained, each recursively
                         pruned at ``depth - 1``.

    Args:
        node (dict | None, required): The group/control/task dict to copy, or None.
        depth (int | None, optional): Structural-child depth limit. Defaults to None.
        child_keys (tuple, optional): Keys treated as structural children. Defaults
            to ("groups", "controls"). Use ("tasks",) for assessment tasks.

    Returns:
        dict | None: A detached copy, or None when *node* is None.

    Raises:
        ValueError: If *depth* is a negative integer.
    """
    if node is None:
        return None
    if depth is None:
        return copy.deepcopy(node)
    if depth < 0:
        raise ValueError(f"depth must be None or a non-negative integer, got {depth}")

    result: dict = {}
    for key, value in node.items():
        if key in child_keys:
            continue                      # pruned / handled below by depth
        result[key] = copy.deepcopy(value)
    if depth > 0:
        for key in child_keys:
            children = node.get(key)
            if isinstance(children, list):
                result[key] = [prune_tree_copy(child, depth - 1, child_keys)
                               for child in children]
    return result


# -------------------------------------------------------------------------
def _collect_ids(node, out: set) -> None:
    """Recursively collect every ``id``/``uuid`` string value into ``out``."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key in ("id", "uuid") and isinstance(val, str):
                out.add(val)
            _collect_ids(val, out)
    elif isinstance(node, list):
        for item in node:
            _collect_ids(item, out)


# -------------------------------------------------------------------------
def _find_part_by_id(parts: list, fragment_id: str) -> dict | None:
    """Recursively find a part by id within a list of parts (and their nested parts)."""
    for part in parts or []:
        if isinstance(part, dict):
            if part.get("id") == fragment_id:
                return part
            found = _find_part_by_id(part.get("parts", []), fragment_id)
            if found is not None:
                return found
    return None


# -------------------------------------------------------------------------
def _find_model_element(container: dict, fragment_id: str, kinds) -> dict | None:
    """Find a control/group/param/part by id within a catalog-shaped container.

    Searches ``container`` (a catalog root, group, or control) for a matching group,
    control, param, or part — descending through nested groups and controls. Returns a
    result dict ``{"element", "kind", "id"}`` (safe copy) or None.
    """
    if "group" in kinds:
        for grp in container.get("groups", []):
            if isinstance(grp, dict) and grp.get("id") == fragment_id:
                return {"element": copy.deepcopy(grp), "kind": "group", "id": fragment_id}
    if "control" in kinds:
        for ctrl in container.get("controls", []):
            if isinstance(ctrl, dict) and ctrl.get("id") == fragment_id:
                return {"element": copy.deepcopy(ctrl), "kind": "control", "id": fragment_id}
    if "param" in kinds:
        for param in container.get("params", []):
            if isinstance(param, dict) and param.get("id") == fragment_id:
                return {"element": copy.deepcopy(param), "kind": "param", "id": fragment_id}
    if "part" in kinds:
        part = _find_part_by_id(container.get("parts", []), fragment_id)
        if part is not None:
            return {"element": copy.deepcopy(part), "kind": "part", "id": fragment_id}
    for grp in container.get("groups", []):
        if isinstance(grp, dict):
            found = _find_model_element(grp, fragment_id, kinds)
            if found is not None:
                return found
    for ctrl in container.get("controls", []):
        if isinstance(ctrl, dict):
            found = _find_model_element(ctrl, fragment_id, kinds)
            if found is not None:
                return found
    return None


# -------------------------------------------------------------------------
def append_props(parent_obj: dict, props: list) -> None:
    """
    Append multiple prop dicts to ``parent_obj["props"]``.

    Args:
        parent_obj (dict, required): OSCAL JSON object that will receive the props.
        props (list, required): Property dicts, each with at minimum "name" and "value".

    Returns:
        None
    """
    for prop in props:
        append_prop(parent_obj, prop)


# -------------------------------------------------------------------------
def append_prop(parent_obj: dict, prop: dict) -> dict:
    """
    Append a single prop dict to ``parent_obj["props"]``.

    Args:
        parent_obj (dict, required): OSCAL JSON object that will receive the prop.
        prop (dict, required): Property dict. Required keys: "name", "value".
            Optional keys: "uuid", "ns", "class", "group", "remarks".

    Returns:
        dict: The appended prop entry (filtered to recognized keys).
    """
    entry: dict = {}
    for key in ("uuid", "name", "ns", "value", "class", "group", "remarks"):
        if key in prop:
            entry[key] = prop[key]
    parent_obj.setdefault("props", []).append(entry)
    return entry


# -------------------------------------------------------------------------
def get_props(parent_obj: dict, name: str | None = None, uuid: str | None = None,
              ns: str = _OSCAL_NS, class_: str | None = None,
              group: str | None = None) -> list:
    """
    Retrieve matching prop dicts from ``parent_obj["props"]``.

    Either ``name`` or ``uuid`` must be supplied. The return value is always a
    list — empty when nothing matches (or when the required parameters are
    missing) — never ``None``.

    An absent ``ns`` on a prop is treated as the OSCAL default namespace
    (``_OSCAL_NS``), matching the way ``ns`` defaults on this function's own
    ``ns`` parameter. Correct default-``ns`` handling is essential: a prop with
    no ``ns`` is considered to be in the OSCAL namespace.

    Matching behaviour:
      * ``uuid`` supplied: every prop whose ``uuid`` equals ``uuid`` is
        returned. If any descriptor parameter (``name``, a non-default ``ns``,
        ``class_`` or ``group``) is also supplied and does not match a returned
        prop, a warning is logged, but the prop is still returned.
      * ``uuid`` not supplied: ``name`` is required. Props are matched on
        ``name`` **and** effective ``ns``. When ``class_`` and/or ``group`` are
        supplied they must also match. When ``class_``/``group`` are *not*
        supplied, all name+ns matches are returned, ordered best match first:
        props carrying fewer of the un-queried qualifiers (``class``/``group``)
        sort ahead of more-specific props. Document order is preserved among
        equally specific matches.

    Args:
        parent_obj (dict, required): OSCAL JSON object holding a ``props`` list.
        name (str, optional): Prop ``name`` to match. Required if ``uuid`` is
            not given.
        uuid (str, optional): Prop ``uuid`` to match. Required if ``name`` is
            not given.
        ns (str, optional): Namespace to match; defaults to ``_OSCAL_NS``.
        class_ (str, optional): Prop ``class`` to match. Maps to the ``"class"``
            key (``class`` is a reserved word in Python).
        group (str, optional): Prop ``group`` to match.

    Returns:
        list: Matching prop dicts (possibly empty), ordered best match first.
    """
    if uuid is None and name is None:
        logger.warning("get_props() requires either 'name' or 'uuid'; neither "
                       "was provided. Returning an empty list.")
        return []

    props = parent_obj.get("props", []) or []

    def _eff_ns(prop: dict) -> str:
        # Absent @ns defaults to the OSCAL namespace per OSCAL specification.
        return prop.get("ns") or _OSCAL_NS

    # -- uuid mode: uuid identifies the prop; other params only validate ------
    if uuid is not None:
        matches = [p for p in props if p.get("uuid") == uuid]
        descriptors_given = (name is not None or class_ is not None
                             or group is not None or ns != _OSCAL_NS)
        if descriptors_given:
            for p in matches:
                mismatched = []
                if name is not None and p.get("name") != name:
                    mismatched.append("name")
                if _eff_ns(p) != ns:
                    mismatched.append("ns")
                if class_ is not None and p.get("class") != class_:
                    mismatched.append("class")
                if group is not None and p.get("group") != group:
                    mismatched.append("group")
                if mismatched:
                    logger.warning(f"get_props() matched prop uuid={uuid!r} but "
                                   f"the following supplied parameter(s) did not "
                                   f"match the prop: {', '.join(mismatched)}.")
        return matches

    # -- name mode: match on name + effective ns (+ class/group if given) -----
    results = [p for p in props
               if p.get("name") == name and _eff_ns(p) == ns
               and (class_ is None or p.get("class") == class_)
               and (group is None or p.get("group") == group)]

    # Order best match first: props carrying fewer of the un-queried
    # qualifiers (class/group) are the closer match. Stable sort keeps
    # document order among equally specific props.
    unqueried = [q for q, given in (("class", class_), ("group", group))
                 if given is None]
    if unqueried:
        results.sort(key=lambda p: sum(1 for q in unqueried
                                       if p.get(q) not in (None, "")))
    return results


# -----------------------------------------------------------------------------
def append_links(parent_obj: dict, links: list) -> None:
    """
    Append multiple link dicts to ``parent_obj["links"]``.

    Args:
        parent_obj (dict, required): OSCAL JSON object that will receive the links.
        links (list, required): Link dicts, each with at minimum an "href" key.

    Returns:
        None
    """
    for link in links:
        append_link(parent_obj, link)


# -----------------------------------------------------------------------------
def append_link(parent_obj: dict, link: dict) -> dict:
    """
    Append a single link dict to ``parent_obj["links"]``.

    Args:
        parent_obj (dict, required): OSCAL JSON object that will receive the link.
        link (dict, required): Link dict. Required key: "href".
            Optional keys: "rel", "media-type", "resource-fragment", "text".

    Returns:
        dict: The appended link entry (filtered to recognized keys).
    """
    entry: dict = {}
    for key in ("href", "rel", "media-type", "resource-fragment", "text"):
        if key in link:
            entry[key] = link[key]
    parent_obj.setdefault("links", []).append(entry)
    return entry


# -----------------------------------------------------------------------------
def oscal_markdown_to_html_tree(markdown_text: str, multiline: bool = True) -> Optional[ElementTree.Element]:
    """
    Convert OSCAL markdown text to an HTML ElementTree element.

    Calls ``oscal_markdown_to_html`` to format the markdown into HTML consistent
    with the OSCAL XML specification for markup-line / markup-multiline, then parses
    the resulting string into an XML element suitable for appending into a parent
    XML object.

    Args:
        markdown_text (str, required): The markdown text to convert.
        multiline (bool, optional): If True, handle markup-multiline (block elements);
            if False, handle markup-line (inline elements only). Defaults to True.

    Returns:
        Optional[ElementTree.Element]: The parsed XML element, or None if conversion fails.
    """
    html_str = oscal_markdown_to_html(markdown_text, multiline=multiline)
    if html_str:
        return _html_to_et(html_str, "")
    return None


# -------------------------------------------------------------------------
def _format_table_helper(table_lines: list) -> str:
    """Helper function to format markdown table to HTML"""
    if len(table_lines) < 2:
        return ""

    # Parse header row
    header_cells = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]

    # Parse alignment row
    alignment_row = table_lines[1]
    alignments = []
    for cell in alignment_row.split('|')[1:-1]:
        cell = cell.strip()
        if cell.startswith(':') and cell.endswith(':'):
            alignments.append('center')
        elif cell.endswith(':'):
            alignments.append('right')
        else:
            alignments.append('left')

    # Ensure we have alignments for all columns
    while len(alignments) < len(header_cells):
        alignments.append('left')

    # Build HTML table
    html = ['<table>']

    # Header row
    header_html = '  <tr>'
    for i, cell in enumerate(header_cells):
        align = alignments[i] if i < len(alignments) else 'left'
        header_html += f'<th align="{align}">{cell}</th>'
    header_html += '</tr>'
    html.append(header_html)

    # Data rows
    for line in table_lines[2:]:
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.split('|')[1:-1]]
        row_html = '  <tr>'
        for i, cell in enumerate(cells):
            align = alignments[i] if i < len(alignments) else 'left'
            row_html += f'<td align="{align}">{cell}</td>'
        row_html += '</tr>'
        html.append(row_html)

    html.append('</table>')
    return '\n'.join(html)
