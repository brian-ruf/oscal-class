"""
oscal_controls — OSCAL control-layer model classes.

Provides the editable model classes for the OSCAL control models: ``Catalog``
(defines controls), ``Profile`` (selects and tailors controls into baselines),
and ``Mapping`` (relates controls across frameworks). Each class subclasses
``OSCAL`` from ``oscal_content`` and adds model-specific navigation and
mutation helpers. ``ImportResult`` is the structured return value of
``Profile.add_import``.

Module constants:
    MEDIA_TYPES (dict): Maps a lower-case file extension (``.xml``, ``.json``,
        ``.yaml``, ``.yml``) to its OSCAL media type (``application/xml``,
        ``application/json``, ``application/yaml``). Used to infer an ``rlink``
        media type from a referenced file's href.
"""
import os
import re
import copy
import fnmatch
from urllib.parse import urlparse
from dataclasses import dataclass
import logging
from datetime import datetime, timezone
from typing import Any, Optional, cast
from enum import Enum

from .oscal_content import (
    OSCAL, requires, if_update_successful, append_props, append_links, new_uuid,
    register_model, get_props, prune_tree_copy, ImportState, _collect_ids, _OSCAL_NS,
)
from .oscal_datatypes import oscal_date_time_with_timezone

logger = logging.getLogger(__name__)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Best-effort OSCAL media types by file extension (mirrors oscal.fix_references).
MEDIA_TYPES = {
    ".xml":  "application/xml",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml":  "application/yaml",
}


def _infer_media_type(href: str) -> str:
    """Best-effort OSCAL media type from an href's file extension.

    Args:
        href (str, required): The reference href (path or URL).

    Returns:
        str: The matching OSCAL media type, or "" when the extension is unknown.
    """
    ext = os.path.splitext(urlparse(href).path)[1].lower()
    return MEDIA_TYPES.get(ext, "")


@dataclass
class ImportResult:
    """Outcome of a :meth:`Profile.add_import` call.

    Attributes:
        status (str): One of "added", "replaced", "duplicate", or "error". A
            "duplicate" is a blocking condition (``ok`` is False) — the href already
            appears among this document's own imports.
        entry (dict | None): The import entry — the newly added/replaced entry for
            "added"/"replaced", or the conflicting existing import for "duplicate".
        resource (dict | None): The back-matter resource created for the import
            (None for "duplicate"/"error").
        message (str): Human-readable detail, primarily for "duplicate"/"error".
    """
    status: str
    entry: Optional[dict] = None
    resource: Optional[dict] = None
    message: str = ""

    @property
    def ok(self) -> bool:
        """bool: True when an import was actually added or replaced."""
        return self.status in ("added", "replaced")

    @property
    def is_duplicate(self) -> bool:
        """bool: True when the href already matched one of this document's imports."""
        return self.status == "duplicate"

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Dict navigation helpers
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def _find_group(groups: list, group_id: str) -> Optional[dict]:
    """Recursively find a group dict by id within a list of groups.

    Args:
        groups (list, required): The groups to search (and their nested groups).
        group_id (str, required): The ``id`` to find.

    Returns:
        Optional[dict]: The matching group dict, or None.
    """
    for g in groups or []:
        if g.get("id") == group_id:
            return g
        found = _find_group(g.get("groups", []), group_id)
        if found is not None:
            return found
    return None


def _find_control(container: dict, control_id: str) -> Optional[dict]:
    """Recursively find a control dict by id within a catalog, group, or control.

    Descends into nested controls, so control enhancements (controls nested inside
    controls) are found at any depth.

    Args:
        container (dict, required): The catalog root, group, or control to search.
        control_id (str, required): The control ``id`` to find.

    Returns:
        Optional[dict]: The matching control dict, or None.
    """
    for ctrl in container.get("controls", []):
        if ctrl.get("id") == control_id:
            return ctrl
        found = _find_control(ctrl, control_id)   # nested controls (enhancements)
        if found is not None:
            return found
    for grp in container.get("groups", []):
        found = _find_control(grp, control_id)
        if found is not None:
            return found
    return None


def _find_part(container: dict, part_id: str) -> Optional[dict]:
    """Recursively find a part dict by id anywhere under ``container``.

    Searches the container's own ``parts`` (and their nested parts), and descends
    into nested ``controls`` and ``groups`` — so calling this with the catalog root
    finds a part by id anywhere in the catalog.

    Args:
        container (dict, required): The catalog root, group, control, or part to search.
        part_id (str, required): The part ``id`` to find.

    Returns:
        Optional[dict]: The matching part dict, or None.
    """
    for part in container.get("parts", []):
        if part.get("id") == part_id:
            return part
        found = _find_part(part, part_id)
        if found is not None:
            return found
    for ctrl in container.get("controls", []):
        found = _find_part(ctrl, part_id)
        if found is not None:
            return found
    for grp in container.get("groups", []):
        found = _find_part(grp, part_id)
        if found is not None:
            return found
    return None


# Part names that may not contain child parts, per higher-level metaschema rules
# not yet covered by the metaschema index. Enforced as a stopgap; relax (or drive
# from the index) once those constraints are handled.
_LEAF_PART_NAMES = {"guidance"}


def _would_mix(container: dict, adding: str) -> bool:
    """Return True if adding a control/group to ``container`` would mix the two.

    OSCAL organizes a level as either controls or groups, not both. Adding a
    ``"control"`` where groups already exist (or a ``"group"`` where controls
    already exist) would mix them.

    Args:
        container (dict, required): The catalog root, a group, or a control.
        adding (str, required): ``"control"`` or ``"group"``.

    Returns:
        bool: True when the addition would mix controls and groups at that level.
    """
    if adding == "control":
        return bool(container.get("groups"))
    if adding == "group":
        return bool(container.get("controls"))
    return False


def _all_controls(container: dict) -> list:
    """Recursively collect all control dicts, including nested enhancements.

    Args:
        container (dict, required): The catalog root, group, or control to walk.

    Returns:
        list: Every control dict found at any depth.
    """
    result = []
    for ctrl in container.get("controls", []):
        result.append(ctrl)
        result.extend(_all_controls(ctrl))        # nested controls (enhancements)
    for grp in container.get("groups", []):
        result.extend(_all_controls(grp))
    return result


def format_index_errors(errors: list) -> str:
    """Render metaschema-walk errors (from ``_walk_instance``) as a compact one-liner.

    Args:
        errors (list, required): The structured error dicts collected by a walk.

    Returns:
        str: A ``"; "``-joined summary, one clause per error.
    """
    return "; ".join(
        f"{e.get('error-type')} at {e.get('location', '')} "
        f"field={e.get('field', '')} value={e.get('value')!r}"
        for e in errors
    )


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Profile resolution — selection over controls_tree (Phase A)
#
# Selection, organization, and duplicate detection all operate on the lightweight
# ``controls_tree`` (nodes: id/label/title/group/children) of each imported object,
# not its live content. This keeps profile load cheap: only ids and hierarchy are
# read; the heavy control content is fetched lazily at materialize time. These pure
# helpers are unit-testable (and later awaitable) in isolation.
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def _index_tree_controls(nodes: list) -> dict:
    """Map every control node's ``id`` to that node within a controls_tree.

    Args:
        nodes (list, required): A controls_tree node list (each node has ``group`` and
            ``children``).

    Returns:
        dict: ``{control_id: node}`` for control nodes (``group`` is False) at every
            depth, including nested enhancements.
    """
    out: dict[str, dict] = {}

    def walk(ns: list) -> None:
        for n in ns:
            if not n.get("group"):
                out[n.get("id", "")] = n
            walk(n.get("children", []))

    walk(nodes)
    return out


def _tree_descendant_control_ids(node: dict) -> list:
    """Return the ids of every control node beneath ``node`` (all depths)."""
    out: list[str] = []

    def walk(ns: list) -> None:
        for n in ns:
            if not n.get("group"):
                out.append(n.get("id", ""))
            walk(n.get("children", []))

    walk(node.get("children", []))
    return out


def _match_select_entries_tree(entries: list, ctrl_map: dict) -> set:
    """Resolve ``select-control-by-id`` entries to a set of control ids over a tree.

    Mirrors OSCAL selection semantics: ``with-ids`` (exact, honored only when present),
    ``matching`` (glob over ids), and ``with-child-controls`` (``"yes"`` adds every
    descendant control, default ``"no"``).

    Args:
        entries (list, required): The ``select-control-by-id`` dicts (or empty).
        ctrl_map (dict, required): ``{control_id: node}`` from :func:`_index_tree_controls`.

    Returns:
        set: The set of selected control ids.
    """
    all_ids = list(ctrl_map.keys())
    result: set[str] = set()
    for entry in entries or []:
        base: set[str] = set()
        for wid in entry.get("with-ids", []):
            if wid in ctrl_map:
                base.add(wid)
        for match in entry.get("matching", []):
            pattern = match.get("pattern")
            if pattern:
                base.update(i for i in all_ids if fnmatch.fnmatchcase(i, pattern))
        result |= base
        if str(entry.get("with-child-controls", "no")).lower() == "yes":
            for cid in base:
                result.update(_tree_descendant_control_ids(ctrl_map[cid]))
    return result


def _selected_tree_ids(imp: dict, source_tree: list) -> tuple:
    """Compute the in-scope control ids for one import against a source controls_tree.

    Selection starts from ``include-all`` or ``include-controls`` and subtracts
    ``exclude-controls``. Excluding a control that was never included is a guarded
    no-op reported in the warnings.

    Args:
        imp (dict, required): A single profile ``imports`` entry.
        source_tree (list, required): The imported object's controls_tree.

    Returns:
        tuple: ``(selected_ids: set[str], warnings: list[str])``.
    """
    ctrl_map = _index_tree_controls(source_tree)
    warnings: list[str] = []

    if "include-all" in imp:
        included = set(ctrl_map.keys())
    elif "include-controls" in imp:
        included = _match_select_entries_tree(imp.get("include-controls", []), ctrl_map)
    else:
        warnings.append("import selects neither include-all nor include-controls; "
                        "nothing selected.")
        included = set()

    excluded = _match_select_entries_tree(imp.get("exclude-controls", []), ctrl_map)

    not_included = excluded - included
    if not_included:
        warnings.append("exclude-controls names controls that were not included: "
                        f"{sorted(not_included)}")

    return included - excluded, warnings


def _find_tree_node(nodes: list, node_id: str, want_group: bool) -> Optional[dict]:
    """Depth-first search a controls_tree for a node by id and group/control kind."""
    for n in nodes:
        if n.get("id") == node_id and bool(n.get("group")) == want_group:
            return n
        found = _find_tree_node(n.get("children", []), node_id, want_group)
        if found is not None:
            return found
    return None


def _all_tree_control_nodes(nodes: list) -> list:
    """Return every control node (``group`` False) in a controls_tree, at all depths."""
    out: list = []
    for n in nodes:
        if not n.get("group"):
            out.append(n)
        out.extend(_all_tree_control_nodes(n.get("children", [])))
    return out


def _node_source_id(node: dict) -> Optional[str]:
    """Return a node's id in its immediate import source (for matching alter control-ids)."""
    return (node.get("origin") or {}).get("source_id")


def _find_control_node_with_ancestors(nodes: list, control_id: str,
                                      ancestors: tuple = ()) -> tuple:
    """Find a control node by (profile-scope) id, returning it with its control-ancestor
    chain of *source* ids.

    Group ancestors are skipped (they carry no alters); only enclosing control nodes
    (enhancement parents) contribute source ids, since alters/adds from an ancestor
    control can reach into a nested control.

    Returns:
        tuple: ``(node, ancestor_source_ids)``, or ``(None, ())`` when not found.
    """
    for n in nodes:
        is_group = bool(n.get("group"))
        if not is_group and n.get("id") == control_id:
            return n, ancestors
        child_ancestors = ancestors if is_group else ancestors + (_node_source_id(n),)
        found, anc = _find_control_node_with_ancestors(
            n.get("children", []), control_id, child_ancestors)
        if found is not None:
            return found, anc
    return None, ()


def _all_control_nodes_with_ancestors(nodes: list, ancestors: tuple = ()) -> list:
    """Yield ``(control_node, ancestor_source_ids)`` for every control node, all depths."""
    out: list = []
    for n in nodes:
        is_group = bool(n.get("group"))
        if not is_group:
            out.append((n, ancestors))
        child_ancestors = ancestors if is_group else ancestors + (_node_source_id(n),)
        out.extend(_all_control_nodes_with_ancestors(n.get("children", []), child_ancestors))
    return out


def _tree_has_control(node: dict) -> bool:
    """Return True if ``node``'s subtree contains at least one control node."""
    for child in node.get("children", []):
        if not child.get("group") or _tree_has_control(child):
            return True
    return False


def _prune_empty_group_nodes(nodes: list) -> list:
    """Return ``nodes`` with group nodes that contain no control descendant removed."""
    out: list = []
    for n in nodes:
        if n.get("group"):
            n["children"] = _prune_empty_group_nodes(n.get("children", []))
            if _tree_has_control(n):
                out.append(n)
        else:
            out.append(n)
    return out


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Profile resolution — combine / duplicate handling (Phase B)
#
# When the same control (or group) id is selected from more than one import and the
# combine method is not "use-first", every colliding instance after the first is kept
# but its ids are made unique by appending "__<uuid>". These helpers apply that suffix
# and repair intra-node references so each renamed instance stays self-consistent.
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# Matches an OSCAL param insert in markup prose, e.g. "{{ insert: param, ac-1_prm_1 }}",
# capturing (prefix)(param-id)(suffix) with flexible surrounding whitespace.
_PARAM_INSERT_RE = re.compile(r"(\{\{\s*insert:\s*param\s*,\s*)([^\s}]+)(\s*\}\})")


def _rewrite_refs(node, rename: dict, skip_keys: tuple = ()) -> None:
    """Recursively rewrite intra-node references to renamed ids, in place.

    Two reference forms are handled:
      * param inserts in any prose string — ``{{ insert: param, OLD }}`` → ``NEW``
      * fragment references under an ``href`` key — ``"#OLD"`` → ``"#NEW"``

    Only ids present in ``rename`` are touched, so unrelated fragment links (e.g.
    ``href`` values pointing at back-matter resource UUIDs) are left intact.

    Args:
        node: The dict/list/subtree to walk.
        rename (dict, required): ``{old_id: new_id}`` map of renamed ids.
        skip_keys (tuple, optional): Dict keys whose subtrees must not be descended
            into (used to keep a group's rewrite out of its child groups/controls).
    """
    if isinstance(node, dict):
        for key, val in node.items():
            if isinstance(val, str):
                new = _PARAM_INSERT_RE.sub(
                    lambda m: m.group(1) + rename.get(m.group(2), m.group(2)) + m.group(3),
                    val,
                )
                if key == "href" and new.startswith("#") and new[1:] in rename:
                    new = "#" + rename[new[1:]]
                node[key] = new
            elif key not in skip_keys:
                _rewrite_refs(val, rename, skip_keys)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            if isinstance(item, str):
                node[i] = _PARAM_INSERT_RE.sub(
                    lambda m: m.group(1) + rename.get(m.group(2), m.group(2)) + m.group(3),
                    item,
                )
            else:
                _rewrite_refs(item, rename, skip_keys)


def _collect_part_ids(parts: list, suffix: str, rename: dict) -> None:
    """Populate ``rename`` with ``id -> id__suffix`` for every part id, recursively."""
    for part in parts or []:
        pid = part.get("id")
        if pid:
            rename[pid] = f"{pid}__{suffix}"
        _collect_part_ids(part.get("parts"), suffix, rename)


def _apply_part_ids(parts: list, rename: dict) -> None:
    """Apply the ``rename`` map to every part id in place, recursively."""
    for part in parts or []:
        if part.get("id") in rename:
            part["id"] = rename[part["id"]]
        _apply_part_ids(part.get("parts"), rename)


def _suffix_control(control: dict, suffix: str) -> dict:
    """Append ``__<suffix>`` to a control's own ids and repair references, in place.

    Renames the control's own ``id`` and the ids of its ``params`` and ``parts``
    (parts recursively). Nested enhancements (child ``controls``) are deliberately
    NOT renamed — each is evaluated for collision independently — but references to
    the renamed ids ARE repaired throughout the whole subtree so nothing dangles.

    Args:
        control (dict, required): The control node to rename in place.
        suffix (str, required): The unique suffix (typically a UUID) to append.

    Returns:
        dict: The ``{old_id: new_id}`` rename map that was applied.
    """
    rename: dict[str, str] = {}
    cid = control.get("id")
    if cid:
        rename[cid] = f"{cid}__{suffix}"
    for param in control.get("params", []):
        pid = param.get("id")
        if pid:
            rename[pid] = f"{pid}__{suffix}"
    _collect_part_ids(control.get("parts"), suffix, rename)

    if cid:
        control["id"] = rename[cid]
    for param in control.get("params", []):
        if param.get("id") in rename:
            param["id"] = rename[param["id"]]
    _apply_part_ids(control.get("parts"), rename)

    _rewrite_refs(control, rename)
    return rename


def _suffix_group(group: dict, suffix: str) -> dict:
    """Append ``__<suffix>`` to a group's own ids and repair references, in place.

    Per the duplicate-group rule, this renames only the group's own ``id`` and the
    ids of its ``params`` and ``parts`` — never its child groups or controls, which
    are evaluated independently. Reference repair is scoped to the group's own
    intrinsic content (its ``parts``), not its children.

    Args:
        group (dict, required): The group node to rename in place.
        suffix (str, required): The unique suffix (typically a UUID) to append.

    Returns:
        dict: The ``{old_id: new_id}`` rename map that was applied.
    """
    rename: dict[str, str] = {}
    gid = group.get("id")
    if gid:
        rename[gid] = f"{gid}__{suffix}"
    for param in group.get("params", []):
        pid = param.get("id")
        if pid:
            rename[pid] = f"{pid}__{suffix}"
    _collect_part_ids(group.get("parts"), suffix, rename)

    if gid:
        group["id"] = rename[gid]
    for param in group.get("params", []):
        if param.get("id") in rename:
            param["id"] = rename[param["id"]]
    _apply_part_ids(group.get("parts"), rename)

    _rewrite_refs(group, rename, skip_keys=("groups", "controls"))
    return rename


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Profile resolution — structure & populate helpers (Phase C)
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _dedup_exact(items: list) -> list:
    """Return ``items`` with exact-duplicate dicts removed, preserving first order.

    Used to merge metadata ``links``/``props`` carried forward from the profile and
    every imported document without repeating identical entries.

    Args:
        items (list, required): The list of (hashable-once-serialized) dicts.

    Returns:
        list: Deep copies of the unique items, in first-seen order.
    """
    seen: set[str] = set()
    out: list = []
    for item in items:
        try:
            key = repr(sorted(item.items())) if isinstance(item, dict) else repr(item)
        except Exception:
            key = repr(item)
        if key not in seen:
            seen.add(key)
            out.append(copy.deepcopy(item))
    return out


def _newest_timestamp(values: list) -> Optional[str]:
    """Return the chronologically latest RFC-3339 timestamp string from ``values``.

    Parses each value so timestamps with different UTC offsets compare correctly;
    unparseable values are ignored. The original string of the latest instant is
    returned (not a normalized form).

    Args:
        values (list, required): Candidate timestamp strings (None/"" entries ok).

    Returns:
        Optional[str]: The latest timestamp string, or None when none parse.
    """
    best_str: Optional[str] = None
    best_dt = None
    for raw in values:
        if not raw or not isinstance(raw, str):
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if best_dt is None or dt > best_dt:
            best_dt, best_str = dt, raw
    return best_str


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Profile resolution — modify / alter (Phase E)
#
# Pure functions that apply one profile's `modify` directives to a single already-
# fetched control dict: `remove`s, then `add`s, then `set-parameter`s. Every function
# mutates its control/param argument in place and is unit-testable in isolation.
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def _distinct_key(item: dict, kind: str) -> tuple:
    """Return the distinctive identity of a prop/link for set-parameter dedup.

    A prop's identity is (name, effective-ns, class); a link's is (href, rel). An
    absent ``ns`` is normalized to the OSCAL default namespace, so a prop with no
    ``ns`` collides with one explicitly in the default namespace.
    """
    if kind == "prop":
        return (item.get("name"), item.get("ns") or _OSCAL_NS, item.get("class"))
    return (item.get("href"), item.get("rel"))


def _remove_matching(content: dict, remove: dict) -> int:
    """Remove items from a control matching ALL of a ``remove`` directive's selectors.

    Scans the control's ``params``/``props``/``links``/``parts`` (parts recursively,
    including each part's own props/links) and drops every item that matches all of the
    directive's specified ``by-*`` flags. Child controls are not present (fetched at
    depth 0), so removal is scoped to the control's own content.

    Returns:
        int: The number of items removed.
    """
    by_id = remove.get("by-id")
    by_name = remove.get("by-name")
    by_class = remove.get("by-class")
    by_ns = remove.get("by-ns")
    by_item = remove.get("by-item-name")
    removed = 0

    def matches(item: dict, item_type: str) -> bool:
        if by_item is not None and item_type != by_item:
            return False
        if by_id is not None and item.get("id") != by_id:
            return False
        if by_name is not None and item.get("name") != by_name:
            return False
        if by_class is not None and item.get("class") != by_class:
            return False
        if by_ns is not None and (item.get("ns") or _OSCAL_NS) != by_ns:
            return False
        return True

    def prune(container: dict) -> None:
        nonlocal removed
        for key, itype in (("params", "param"), ("props", "prop"),
                           ("links", "link"), ("parts", "part")):
            lst = container.get(key)
            if not isinstance(lst, list):
                continue
            kept = [it for it in lst if not (isinstance(it, dict) and matches(it, itype))]
            if len(kept) != len(lst):
                removed += len(lst) - len(kept)
                if kept:
                    container[key] = kept
                else:
                    container.pop(key, None)
        for part in container.get("parts", []):
            if isinstance(part, dict):
                prune(part)

    prune(content)
    return removed


def _find_anchor(container: dict, target_id: str):
    """Find the element with ``id == target_id`` (a param or part) within a control.

    Returns ``(element, parent, key, index)`` where ``parent[key][index]`` is the
    element, searching ``params`` and ``parts`` recursively; or None when not found.
    """
    for key in ("params", "parts"):
        lst = container.get(key, [])
        for i, item in enumerate(lst):
            if isinstance(item, dict) and item.get("id") == target_id:
                return item, container, key, i
    for part in container.get("parts", []):
        if isinstance(part, dict):
            found = _find_anchor(part, target_id)
            if found is not None:
                return found
    return None


def _add_into(target: dict, add: dict, position: str) -> None:
    """Add a directive's content into ``target``'s own collections (start or end).

    ``title`` replaces the target's title (a control/part may have only one). Each of
    ``params``/``props``/``links``/``parts`` is prepended (``starting``) or appended
    (``ending``) to the target's corresponding collection.
    """
    if "title" in add:
        target["title"] = copy.deepcopy(add["title"])
    for key in ("params", "props", "links", "parts"):
        items = add.get(key)
        if not items:
            continue
        payload = copy.deepcopy(items)
        existing = target.setdefault(key, [])
        if position == "starting":
            target[key] = payload + existing
        else:  # ending
            existing.extend(payload)


def _add_sibling(parent: dict, key: str, index: int, add: dict, position: str) -> None:
    """Insert a directive's same-type content as siblings before/after an anchor.

    Same-type content (matching the anchor's collection ``key``) is inserted into
    ``parent[key]`` at the position relative to the anchor. Any other content types (or
    a ``title``) are applied to the parent element at its end as a best-effort fallback.
    """
    at = index if position == "before" else index + 1
    same = add.get(key)
    if same:
        lst = parent.setdefault(key, [])
        for offset, item in enumerate(copy.deepcopy(same)):
            lst.insert(at + offset, item)
    others = {k: add[k] for k in ("params", "props", "links", "parts")
              if k in add and k != key}
    if "title" in add:
        others["title"] = add["title"]
    if others:
        _add_into(parent, others, "ending")


def _cited_param_ids(content: dict) -> set:
    """Return the ids of all parameters cited via ``{{ insert: param, X }}`` in prose."""
    ids: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for val in node.values():
                walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            for match in _PARAM_INSERT_RE.finditer(node):
                ids.add(match.group(2))

    walk(content)
    return ids


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Profile resolution — out-of-scope cross-reference rewriting
#
# After resolution, a control may still reference (by ``#id``) a control/part that was
# not selected into the baseline. Matching the official resolver, such out-of-scope
# references are rewritten to absolute URIs pointing at the import that still resolves
# them, both in ``href`` values and in prose markdown links.
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

# A markdown link into a document fragment, e.g. "[AC-1](#ac-1)".
_MD_LINK_RE = re.compile(r"\]\(#([^)\s]+)\)")


def _as_file_uri(href: str) -> str:
    """Return ``href`` as a URI (prefix a bare absolute path with ``file:``)."""
    if not href:
        return ""
    if "://" in href or href.startswith("file:"):
        return href
    if href.startswith("/"):
        return "file:" + href
    return href


def _collect_fragment_refs(node, out: set) -> None:
    """Collect every ``#fragment`` referenced by an ``href`` or a prose markdown link."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "href" and isinstance(val, str) and val.startswith("#"):
                out.add(val[1:])
            elif isinstance(val, str):
                for match in _MD_LINK_RE.finditer(val):
                    out.add(match.group(1))
            else:
                _collect_fragment_refs(val, out)
    elif isinstance(node, list):
        for item in node:
            _collect_fragment_refs(item, out)


def _apply_ref_rewrite(node, base_for: dict) -> None:
    """Rewrite ``#id`` refs to ``<base>#id`` in place for ids present in ``base_for``."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "href" and isinstance(val, str) and val.startswith("#") \
                    and val[1:] in base_for:
                node[key] = f"{base_for[val[1:]]}#{val[1:]}"
            elif isinstance(val, str):
                node[key] = _MD_LINK_RE.sub(
                    lambda m: (f"]({base_for[m.group(1)]}#{m.group(1)})"
                               if m.group(1) in base_for else m.group(0)),
                    val,
                )
            else:
                _apply_ref_rewrite(val, base_for)
    elif isinstance(node, list):
        for item in node:
            _apply_ref_rewrite(item, base_for)


def _apply_one_set_parameter(param: dict, setp: dict) -> list:
    """Apply one ``set-parameter`` to a parameter in place, per profile-resolution rules.

    Replace (drop-then-copy): ``class``, ``depends-on``, ``label``, ``usage``,
    ``values``, ``select`` (``values``/``select`` are mutually exclusive — setting one
    clears the other, with a warning). Append: ``constraints``, ``guidelines``. Append
    with same-distinct-id replacement: ``props``, ``links``.

    Returns:
        list: Warning strings (e.g. when a values/select conflict was resolved).
    """
    warnings: list[str] = []
    pid = setp.get("param-id")

    for field in ("class", "depends-on", "label", "usage"):
        if field in setp:
            param[field] = copy.deepcopy(setp[field])

    if "values" in setp:
        param["values"] = copy.deepcopy(setp["values"])
        if "select" in param:
            param.pop("select", None)
            warnings.append(f"set-parameter for '{pid}' set values on a parameter that "
                            "had a select; the select was removed.")
    if "select" in setp:
        param["select"] = copy.deepcopy(setp["select"])
        if "values" in param:
            param.pop("values", None)
            warnings.append(f"set-parameter for '{pid}' set select on a parameter that "
                            "had values; the values were removed.")

    for field in ("constraints", "guidelines"):
        if field in setp:
            param.setdefault(field, []).extend(copy.deepcopy(setp[field]))

    for field, kind in (("props", "prop"), ("links", "link")):
        if field in setp:
            existing = param.setdefault(field, [])
            for new_item in copy.deepcopy(setp[field]):
                dk = _distinct_key(new_item, kind)
                existing[:] = [e for e in existing if _distinct_key(e, kind) != dk]
                existing.append(new_item)
            if not existing:
                param.pop(field, None)

    return warnings
class Catalog(OSCAL):
    """Editable OSCAL Catalog model.

    Subclasses ``OSCAL`` and adds methods for creating, editing, navigating, and
    removing controls and control groups. Read-only guards apply to mutation methods
    when the instance state is not editable.

    Attributes:
        controls_tree (list[dict]): A lightweight, nested view of the catalog's
            group/control hierarchy for UI tree navigation. Each node is
            ``{"id", "label", "title", "group", "children"}`` where ``group`` is True
            for groups and False for controls, and ``children`` holds nested groups
            and controls (control enhancements included). Built when the catalog is
            found to be valid OSCAL and refreshed on every structural or
            title/label change. See :meth:`_build_controls_tree`.
    """
    def _init_common(self):
        """Initialize Catalog-specific state, then build ``controls_tree`` if valid.

        Always establishes ``controls_tree`` as an attribute (empty by default) so it
        is present even before content is valid; when the instance already holds valid
        catalog content (e.g. after a base ``OSCAL`` load is re-classed to ``Catalog``,
        or ``Catalog.new``), the tree is built immediately.
        """
        super()._init_common()
        self.controls_tree: list[dict[str, Any]] = []
        if self.is_valid:
            self._build_controls_tree()

    # -------------------------------------------------------------------------
    def validate(self, format: str = "") -> bool:
        """Validate the catalog, then (re)build ``controls_tree`` on success.

        Extends :meth:`OSCAL.validate` so the navigation tree is refreshed the
        moment the catalog is converted and found to be valid OSCAL. When the
        content is not valid the tree is emptied — an invalid catalog exposes no
        navigable hierarchy.

        Args:
            format (str, optional): Accepted for API compatibility with the base
                method; does not alter the validation path.

        Returns:
            bool: True when every validation phase passes.
        """
        result = super().validate(format=format)
        if self.is_valid:
            self._build_controls_tree()
        else:
            self.controls_tree = []
        return result

    # -------------------------------------------------------------------------
    def _catalog_root(self) -> dict[str, Any]:
        """Return the catalog root dict from _dict."""
        if not isinstance(self._dict, dict):
            return {}
        catalog = self._dict.get("catalog")
        return catalog if isinstance(catalog, dict) else {}

    # -------------------------------------------------------------------------
    def __len__(self):
        """Return the total number of controls in the catalog at all levels."""
        return len(_all_controls(self._catalog_root()))

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def create_control(self, parent_id: str, id: str, title: str = "", params: list = [], props: list = [], links: list = [], label: str = "", sort_id: str = "", alt_identifier: str = "", overview: str = "", statements: list = [], guidance: str = "", example: str = "", objectives: list = [], objects: list = [], methods: list = [], remarks: str = "") -> Optional[dict]:
        """
        Create a new control under the specified parent group or control.

        Args:
            parent_id (str, required): ID of the parent to add the control to —
                ``'[root]'`` (or an empty string) for the catalog top level, a group
                id, or a control id. Nesting a control under a control models a
                control enhancement (e.g. ``ac-2.1`` under ``ac-2``). The add fails if
                it would mix controls and groups at the same level (not allowed in OSCAL).
            id (str, required): ID of the new control.
            title (str, optional): Title of the new control. Defaults to the label,
                or the id, when empty.
            params (list, optional): Parameters to add. Items may be parameter id
                strings or full parameter dicts.
            props (list, optional): Additional property dicts to add.
            links (list, optional): Link dicts to add.
            label (str, optional): Value for the inline ``label`` property.
            sort_id (str, optional): Value for the inline ``sort-id`` property.
            alt_identifier (str, optional): Value for the inline ``alt-identifier`` property.
            overview (str, optional): Prose (markdown) for the ``overview`` part.
            statements (list, optional): Statement items — strings or
                ``{'id':..., 'prose':...}`` dicts.
            guidance (str, optional): Prose (markdown) for the ``guidance`` part.
            example (str, optional): Prose (markdown) for the ``example`` part.
            objectives (list, optional): Assessment objective items.
            objects (list, optional): Assessment object items.
            methods (list, optional): Assessment method items.
            remarks (str, optional): Remarks prose (markdown).

        Returns:
            Optional[dict]: The newly created control dict, or None on failure.

        Note:
            Refreshes ``controls_tree`` when a control is successfully added.
        """
        logger.info(f"Creating new control '{id}' under parent '{parent_id}'")
        try:
            # The parent may be the catalog root, a group, or a control
            # (control-under-control = enhancement).
            if parent_id in ("", "[root]"):
                parent = self._catalog_root()
            else:
                parent = _find_group(self._catalog_root().get("groups", []), parent_id)
                if parent is None:
                    parent = _find_control(self._catalog_root(), parent_id)
            if parent is None:
                logger.warning(f"CREATE CONTROL: Unable to find parent group or control with id '{parent_id}'")
                return None

            # OSCAL does not allow controls and groups mixed at the same level.
            if _would_mix(parent, "control"):
                logger.warning(
                    f"CREATE CONTROL: '{parent_id or '[root]'}' already contains groups; "
                    "controls and groups cannot be mixed at the same level."
                )
                return None

            control: dict[str, Any] = {"id": id}

            if title == "":
                title = label if label else id
            control["title"] = title

            # Inline props for label / sort-id / alt-identifier
            inline_props = []
            if label:
                inline_props.append({"name": "label", "value": label})
            if sort_id:
                inline_props.append({"name": "sort-id", "value": sort_id})
            if alt_identifier:
                inline_props.append({"name": "alt-identifier", "value": alt_identifier})

            all_props = inline_props + list(props)
            if all_props:
                append_props(control, all_props)
            if links:
                append_links(control, links)

            if params:
                control["params"] = [{"id": p} if isinstance(p, str) else p for p in params]

            # Parts
            parts: list[dict[str, Any]] = []
            if overview:
                parts.append({"name": "overview", "prose": overview})

            if statements:
                if len(statements) == 1 and isinstance(statements[0], str):
                    parts.append({"name": "statement", "id": f"{id}_smt", "prose": statements[0]})
                else:
                    smt_parts: list[dict[str, Any]] = []
                    for i, item in enumerate(statements, 1):
                        if isinstance(item, str):
                            smt_parts.append({"name": "item", "prose": item})
                        else:
                            part = {"name": "item", "prose": item.get("prose", "")}
                            if item.get("id"):
                                part["id"] = f"{id}_smt_{i:02d}"
                            smt_parts.append(part)
                    parts.append({"name": "statement", "id": f"{id}_smt", "parts": smt_parts})

            if guidance:
                parts.append({"name": "guidance", "prose": guidance})
            if example:
                parts.append({"name": "example", "prose": example})

            if parts:
                control["parts"] = parts

            if remarks:
                control["remarks"] = remarks

            parent.setdefault("controls", []).append(control)
            self._build_controls_tree()
            # Return a safe copy — the live control stays in _dict; edits go through methods.
            return copy.deepcopy(control)

        except Exception as error:
            logger.error(f"Error creating control '{id}': {type(error).__name__} - {error}")
            return None

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def create_control_group(self, parent_id: str, id: str, title: str = "", params: list = [], props: list = [], links: list = [], label: str = "", sort_id: str = "", alt_identifier: str = "", overview: str = "", instruction: str = "", remarks: str = "") -> Optional[dict]:
        """
        Create a new catalog group.

        Args:
            parent_id (str, required): ID of the parent group, or ``'[root]'`` (or an
                empty string) for the catalog top level. The add fails if it would mix
                controls and groups at the same level (not allowed in OSCAL).
            id (str, required): ID of the new group.
            title (str, optional): Title of the new group.
            params (list, optional): Parameters to add to the group.
            props (list, optional): Additional property dicts to add.
            links (list, optional): Link dicts to add.
            label (str, optional): Value for the inline ``label`` property.
            sort_id (str, optional): Value for the inline ``sort-id`` property.
            alt_identifier (str, optional): Value for the inline ``alt-identifier`` property.
            overview (str, optional): Prose (markdown) for the ``overview`` part.
            instruction (str, optional): Prose (markdown) for the ``instruction`` part.
            remarks (str, optional): Remarks prose (markdown).

        Returns:
            Optional[dict]: The newly created group dict, or None on failure.

        Note:
            Refreshes ``controls_tree`` when a group is successfully added.
        """
        if parent_id == "":
            parent_id = "[root]"
        try:
            group: dict[str, Any] = {"id": id}

            if title:
                group["title"] = title

            inline_props = []
            if label:
                inline_props.append({"name": "label", "value": label})
            if sort_id:
                inline_props.append({"name": "sort-id", "value": sort_id})
            if alt_identifier:
                inline_props.append({"name": "alt-identifier", "value": alt_identifier})

            all_props = inline_props + list(props)
            if all_props:
                append_props(group, all_props)
            if links:
                append_links(group, links)

            parts: list[dict[str, Any]] = []
            if overview:
                parts.append({"name": "overview", "prose": overview})
            if instruction:
                parts.append({"name": "instruction", "prose": instruction})
            if parts:
                group["parts"] = parts

            if remarks:
                group["remarks"] = remarks

            if parent_id == "[root]":
                target = self._catalog_root()
            else:
                target = _find_group(self._catalog_root().get("groups", []), parent_id)
                if target is None:
                    logger.warning(f"CREATE GROUP: Unable to find parent group with id '{parent_id}'")
                    return None

            # OSCAL does not allow controls and groups mixed at the same level.
            if _would_mix(target, "group"):
                logger.warning(
                    f"CREATE GROUP: '{parent_id}' already contains controls; "
                    "controls and groups cannot be mixed at the same level."
                )
                return None

            target.setdefault("groups", []).append(group)
            self._build_controls_tree()
            # Return a safe copy — the live group stays in _dict; edits go through methods.
            return copy.deepcopy(group)

        except Exception as error:
            logger.error(f"Error creating group '{id}': {type(error).__name__} - {error}")
            return None

    # -------------------------------------------------------------------------
    def _model_index_node(self, node_name: str) -> Optional[dict]:
        """Return the metaschema index node for a direct child of the model root.

        Used to validate a whole incoming subtree (e.g. a ``control`` or ``group``)
        against just the relevant portion of the metaschema, mirroring how
        :meth:`validate` walks the full document.

        Args:
            node_name (str, required): The child element (use-)name, e.g. ``"control"``
                or ``"group"``.

        Returns:
            Optional[dict]: The matching index node, or None when the index (or that
                node) is unavailable — callers then skip validation, as :meth:`validate`
                does when the index is missing.
        """
        index = self._support.get_metaschema_index(self.oscal_version, self.model)
        if not index:
            return None
        root = index.get("nodes")
        if not isinstance(root, dict):
            return None
        for child in root.get("children", []):
            if (child.get("use-name") or child.get("name")) == node_name:
                return child
        return None

    # -------------------------------------------------------------------------
    def _validate_subtree(self, instance: dict, node_name: str) -> list:
        """Validate an incoming subtree against its model-child metaschema node.

        Args:
            instance (dict, required): The control/group dict to validate.
            node_name (str, required): The metaschema node name (``"control"`` /
                ``"group"``).

        Returns:
            list: Structured error dicts (empty when valid, or when the index is
                unavailable so validation is skipped).
        """
        node = self._model_index_node(node_name)
        if node is None:
            return []
        errors: list[dict] = []
        self._walk_instance(instance, node, errors, f"/{self.model}/{node_name}")
        return errors

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def insert_control(self, parent_id: str, control: dict, validate: bool = True) -> Optional[dict]:
        """Insert a pre-formed control subtree whole under a parent, as a safe copy.

        Unlike :meth:`create_control` (which authors a control from discrete parts),
        this inserts an already-formed control dict — including its nested enhancements,
        parts, props, params, and links — without reshaping it. It is the faithful-copy
        path used by profile resolution (and, later, alter directives) to move a control
        from a source catalog into a resolved one.

        The incoming dict is deep-copied before insertion, so the caller's object is not
        aliased into the catalog (getters still return detached copies).

        Args:
            parent_id (str, required): ID of the parent to add the control to —
                ``'[root]'`` (or an empty string) for the catalog top level, a group id,
                or a control id (control-under-control models an enhancement). The add
                fails if it would mix controls and groups at the same level.
            control (dict, required): The control subtree to insert. Must be a dict with
                a non-empty ``id``.
            validate (bool, optional): When True (default), the control is validated
                against the ``control`` metaschema node first; on any error the insert is
                rejected and the catalog is left unchanged.

        Returns:
            Optional[dict]: A safe copy of the inserted control, or None on failure —
                bad input, parent not found, an id collision with an existing control, a
                controls/groups mix, or failed validation.
        """
        if not isinstance(control, dict) or not control.get("id"):
            logger.error("insert_control: 'control' must be a dict with a non-empty 'id'.")
            return None
        cid = control["id"]

        if parent_id in ("", "[root]"):
            parent = self._catalog_root()
        else:
            parent = _find_group(self._catalog_root().get("groups", []), parent_id)
            if parent is None:
                parent = _find_control(self._catalog_root(), parent_id)
        if parent is None:
            logger.warning(f"insert_control: parent group or control '{parent_id}' not found.")
            return None

        if _would_mix(parent, "control"):
            logger.warning(
                f"insert_control: '{parent_id or '[root]'}' already contains groups; "
                "controls and groups cannot be mixed at the same level."
            )
            return None

        if _find_control(self._catalog_root(), cid) is not None:
            logger.warning(f"insert_control: control id '{cid}' already exists in the catalog.")
            return None

        node = copy.deepcopy(control)
        if validate:
            errors = self._validate_subtree(node, "control")
            if errors:
                logger.error(f"insert_control: '{cid}' failed metaschema validation: "
                             f"{format_index_errors(errors)}")
                return None

        parent.setdefault("controls", []).append(node)
        self._build_controls_tree()
        # Return a safe copy — the live control stays in _dict; edits go through methods.
        return copy.deepcopy(node)

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def insert_group(self, parent_id: str, group: dict, shallow: bool = True,
                     validate: bool = True) -> Optional[dict]:
        """Insert a group node under a parent, as a safe copy.

        Companion to :meth:`insert_control` for faithful-copy workflows. By default the
        insert is *shallow*: the group's intrinsic content (title, params, props, links,
        parts) is inserted but its child ``groups``/``controls`` are dropped, to be filled
        in afterward via :meth:`insert_control`/:meth:`insert_group`. This lets callers
        (e.g. profile resolution) build a group hierarchy incrementally while keeping
        empty-group pruning and duplicate handling under their own control.

        Args:
            parent_id (str, required): ID of the parent group, or ``'[root]'`` (or an
                empty string) for the catalog top level. The add fails if it would mix
                controls and groups at the same level.
            group (dict, required): The group node to insert. Must be a dict with a
                non-empty ``id``.
            shallow (bool, optional): When True (default), drop the group's child
                ``groups`` and ``controls`` before insertion. When False, insert the
                group subtree whole.
            validate (bool, optional): When True (default), validate the (possibly
                shallow) group against the ``group`` metaschema node first; on any error
                the insert is rejected and the catalog is left unchanged.

        Returns:
            Optional[dict]: A safe copy of the inserted group, or None on failure — bad
                input, parent not found, an id collision with an existing group, a
                controls/groups mix, or failed validation.
        """
        if not isinstance(group, dict) or not group.get("id"):
            logger.error("insert_group: 'group' must be a dict with a non-empty 'id'.")
            return None
        gid = group["id"]

        if parent_id in ("", "[root]"):
            parent = self._catalog_root()
        else:
            parent = _find_group(self._catalog_root().get("groups", []), parent_id)
        if parent is None:
            logger.warning(f"insert_group: parent group '{parent_id}' not found.")
            return None

        if _would_mix(parent, "group"):
            logger.warning(
                f"insert_group: '{parent_id or '[root]'}' already contains controls; "
                "controls and groups cannot be mixed at the same level."
            )
            return None

        if _find_group(self._catalog_root().get("groups", []), gid) is not None:
            logger.warning(f"insert_group: group id '{gid}' already exists in the catalog.")
            return None

        node = copy.deepcopy(group)
        if shallow:
            node.pop("groups", None)
            node.pop("controls", None)
        if validate:
            errors = self._validate_subtree(node, "group")
            if errors:
                logger.error(f"insert_group: '{gid}' failed metaschema validation: "
                             f"{format_index_errors(errors)}")
                return None

        parent.setdefault("groups", []).append(node)
        self._build_controls_tree()
        # Return a safe copy — the live group stays in _dict; edits go through methods.
        return copy.deepcopy(node)

    # -------------------------------------------------------------------------
    def get_control_by_id(self, control_id: str, depth: Optional[int] = None) -> Optional[dict]:
        """Retrieve a control by its ID as a safe copy, searching all groups recursively.

        The returned dict is a detached copy — mutating it does NOT change the catalog;
        use the catalog's mutation methods to make persistent changes. The control's own
        content (``parts``, ``props``, ``links``, ``params`` …) is always returned in full;
        ``depth`` limits only nested child controls (enhancements).

        Args:
            control_id (str, required): The ``id`` of the control to find.
            depth (int | None, optional): Nested-enhancement depth. ``None`` (default)
                returns the full subtree; ``0`` omits enhancements; ``N`` keeps N levels.

        Returns:
            Optional[dict]: A safe copy of the matching control, or None if not found.
        """
        control = _find_control(self._catalog_root(), control_id)
        return prune_tree_copy(control, depth, child_keys=("controls",))

    # -------------------------------------------------------------------------
    def get_group_by_id(self, group_id: str, depth: Optional[int] = None) -> Optional[dict]:
        """Retrieve a group by its ID as a safe copy, searching nested groups recursively.

        The returned dict is a detached copy — mutating it does NOT change the catalog;
        use the catalog's mutation methods to make persistent changes. The group's own
        content (``props``, ``links`` …) is always returned in full; ``depth`` limits only
        nested child groups and controls.

        Args:
            group_id (str, required): The ``id`` of the group to find.
            depth (int | None, optional): Nested group/control depth. ``None`` (default)
                returns the full subtree; ``0`` omits child groups/controls; ``N`` keeps
                N levels.

        Returns:
            Optional[dict]: A safe copy of the matching group, or None if not found.
        """
        group = _find_group(self._catalog_root().get("groups", []), group_id)
        return prune_tree_copy(group, depth, child_keys=("groups", "controls"))

    # -------------------------------------------------------------------------
    def get_control_list(self) -> list:
        """Return a flat list of every control in the catalog, at all levels, as safe copies.

        The returned list is detached from the document: each control is a copy, so
        mutating any element does NOT change the catalog. A single deep copy of the whole
        list preserves internal identity relationships (an enhancement nested inside its
        parent is the same object as its own standalone entry). Use the catalog's mutation
        methods to make persistent changes.

        Returns:
            list: Safe copies of all controls found across the catalog and its groups.
        """
        return copy.deepcopy(_all_controls(self._catalog_root()))

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def add_part(self, parent_id: str, name: str, title: str = "", prose: str = "",
                 ns: str = "", part_class: str = "", part_id: str = "",
                 props: list = [], links: list = [], parts: list = []) -> Optional[dict]:
        """
        Add a part to an existing control, group, or part.

        Parts are valid on controls and groups (and nest inside other parts), so
        ``parent_id`` may identify any of those by id. There is no limit on how many
        parts of a given ``name`` a level may hold (e.g. multiple ``guidance`` parts).

        Args:
            parent_id (str, required): ID of the control, group, or part to add to.
            name (str, required): The part ``name`` token (e.g. "overview",
                "guidance", "example", "assessment-objective").
            title (str, optional): Part title (markup-line).
            prose (str, optional): Part prose (markup-multiline / markdown).
            ns (str, optional): Part namespace URI.
            part_class (str, optional): Part ``class`` value.
            part_id (str, optional): ID for the new part (needed to target it later,
                e.g. to nest a child part or set its title).
            props (list, optional): Property dicts to add.
            links (list, optional): Link dicts to add.
            parts (list, optional): Pre-built child part dicts to nest.

        Returns:
            Optional[dict]: The newly created part dict, or None on failure — including
                when the part would violate a "leaf part" rule (e.g. a ``guidance``
                part cannot contain child parts).
        """
        if not name:
            logger.error("add_part: 'name' is required.")
            return None
        # Leaf parts (e.g. guidance) may not contain child parts.
        if name in _LEAF_PART_NAMES and parts:
            logger.warning(f"ADD PART: a '{name}' part may not contain child parts.")
            return None
        try:
            root = self._catalog_root()
            parent = _find_group(root.get("groups", []), parent_id)
            if parent is None:
                parent = _find_control(root, parent_id)
            if parent is None:
                parent = _find_part(root, parent_id)
            if parent is None:
                logger.warning(f"ADD PART: Unable to find control, group, or part with id '{parent_id}'")
                return None

            # A leaf part (e.g. guidance) may not have child parts added to it.
            if parent.get("name") in _LEAF_PART_NAMES:
                logger.warning(f"ADD PART: cannot add a child part to a '{parent.get('name')}' part.")
                return None

            part: dict[str, Any] = {}
            if part_id:
                part["id"] = part_id
            part["name"] = name
            if ns:
                part["ns"] = ns
            if part_class:
                part["class"] = part_class
            if title:
                part["title"] = title
            if props:
                append_props(part, props)
            if prose:
                part["prose"] = prose
            if links:
                append_links(part, links)
            if parts:
                part["parts"] = list(parts)

            parent.setdefault("parts", []).append(part)
            # Return a safe copy — the live part stays in _dict; edits go through methods.
            return copy.deepcopy(part)

        except Exception as error:
            logger.error(f"Error adding part '{name}' to '{parent_id}': {type(error).__name__} - {error}")
            return None

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def set_part_title(self, part_id: str, title: str = "") -> Optional[dict]:
        """
        Set or remove the title of an existing part.

        Args:
            part_id (str, required): ID of the part to modify. The part must carry an
                ``id`` to be targetable.
            title (str, optional): The new title. When empty, the part's ``title`` is
                removed.

        Returns:
            Optional[dict]: The modified part dict, or None if no part with that id
                is found.
        """
        part = _find_part(self._catalog_root(), part_id)
        if part is None:
            logger.warning(f"SET PART TITLE: no part found with id '{part_id}'")
            return None
        if title:
            part["title"] = title
        else:
            part.pop("title", None)
        # Return a safe copy — the live part stays in _dict; edits go through methods.
        return copy.deepcopy(part)

    # -------------------------------------------------------------------------
    def _find_group_or_control(self, id: str) -> Optional[dict]:
        """Return the group or control dict with the given id, or None.

        Groups are searched first, then controls (at any depth, including control
        enhancements). Within a valid catalog ids are unique across groups and
        controls, so at most one object matches.

        Args:
            id (str, required): The id to find.

        Returns:
            Optional[dict]: The matching group or control dict, or None.
        """
        root = self._catalog_root()
        obj = _find_group(root.get("groups", []), id)
        if obj is None:
            obj = _find_control(root, id)
        return obj

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def set_title(self, id: str, title: str) -> Optional[dict]:
        """Set the title of a control or group, found by id.

        Refreshes ``controls_tree`` on success, since a node's ``title`` is drawn
        from the object's title.

        Args:
            id (str, required): The id of the control or group to modify.
            title (str, required): The new title. Must be non-empty — a control's
                title is required by OSCAL, so blanking it is rejected.

        Returns:
            Optional[dict]: The modified control/group dict, or None if no such id
                exists or ``title`` is empty.
        """
        if not title:
            logger.warning("SET TITLE: a non-empty title is required.")
            return None
        obj = self._find_group_or_control(id)
        if obj is None:
            logger.warning(f"SET TITLE: no control or group found with id '{id}'")
            return None
        obj["title"] = title
        self._build_controls_tree()
        # Return a safe copy — the live node stays in _dict; edits go through methods.
        return copy.deepcopy(obj)

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def set_label(self, id: str, label: str, class_: str = "", group: str = "") -> Optional[dict]:
        """Set (or clear) the ``label`` property of a control or group, found by id.

        The targeted property is the ``label`` prop in the default OSCAL namespace
        whose ``class``/``group`` qualifiers match the arguments: by default the one
        with **no** class and **no** group — the same property the navigation tree
        reads. Supplying ``class_`` and/or ``group`` targets (or creates) the label
        carrying exactly those qualifiers instead.

        Behaviour:
          * A matching prop exists  → its value is updated (the first, if several).
          * No matching prop exists → one is created with the given qualifiers.
          * ``label`` is empty       → every matching prop is removed.

        Refreshes ``controls_tree`` on success.

        Args:
            id (str, required): The id of the control or group to modify.
            label (str, required): The new label value; an empty string removes the
                matching label property.
            class_ (str, optional): The prop ``class`` to target/create.
            group (str, optional): The prop ``group`` to target/create.

        Returns:
            Optional[dict]: The modified control/group dict, or None if no such id
                exists.
        """
        obj = self._find_group_or_control(id)
        if obj is None:
            logger.warning(f"SET LABEL: no control or group found with id '{id}'")
            return None

        def _matches(p: dict) -> bool:
            # Default OSCAL namespace only (absent @ns == default), matching the
            # tree's own label lookup. An unspecified qualifier must be absent on the
            # prop; a specified one must be equal.
            if p.get("name") != "label":
                return False
            if (p.get("ns") or _OSCAL_NS) != _OSCAL_NS:
                return False
            if p.get("class") != (class_ or None):
                return False
            if p.get("group") != (group or None):
                return False
            return True

        props = obj.get("props", [])
        if label == "":
            remaining = [p for p in props if not _matches(p)]
            if remaining:
                obj["props"] = remaining
            else:
                obj.pop("props", None)
        else:
            existing = [p for p in props if _matches(p)]
            if existing:
                existing[0]["value"] = label
            else:
                new_prop: dict[str, Any] = {"name": "label", "value": label}
                if class_:
                    new_prop["class"] = class_
                if group:
                    new_prop["group"] = group
                append_props(obj, [new_prop])
        self._build_controls_tree()
        # Return a safe copy — the live node stays in _dict; edits go through methods.
        return copy.deepcopy(obj)

    # -------------------------------------------------------------------------
    def _find_parent_and_obj(self, id: str) -> tuple:
        """Locate a group/control by id along with the container that holds it.

        Args:
            id (str, required): The group or control id to find.

        Returns:
            tuple: ``(container, kind, obj)`` where ``container[kind]`` (``kind`` is
            ``"groups"`` or ``"controls"``) is the list holding ``obj``; or
            ``(None, None, None)`` when no group/control has that id.
        """
        root = self._catalog_root()
        stack = [root]
        while stack:
            container = stack.pop()
            for kind in ("groups", "controls"):
                for child in container.get(kind, []):
                    if child.get("id") == id:
                        return container, kind, child
                    stack.append(child)
        return None, None, None

    # -------------------------------------------------------------------------
    @staticmethod
    def _part_ids(part: dict) -> list:
        """Return the id of ``part`` and of every part nested within it (ids only)."""
        ids: list[str] = []
        if part.get("id"):
            ids.append(part["id"])
        for sub in part.get("parts", []):
            ids.extend(Catalog._part_ids(sub))
        return ids

    # -------------------------------------------------------------------------
    @staticmethod
    def _subtree_ids(obj: dict) -> list:
        """Return every referable id removed along with ``obj``.

        Includes ``obj``'s own id, the ids of all nested groups and controls
        (control enhancements) at any depth, and the ids of all parts at any depth.
        """
        ids: list[str] = []
        if obj.get("id"):
            ids.append(obj["id"])
        for part in obj.get("parts", []):
            ids.extend(Catalog._part_ids(part))
        for kind in ("groups", "controls"):
            for child in obj.get(kind, []):
                ids.extend(Catalog._subtree_ids(child))
        return ids

    # -------------------------------------------------------------------------
    @staticmethod
    def _immediate_child_ids(obj: dict) -> list:
        """Return the ids of ``obj``'s *immediate* children — direct groups, controls,
        and parts only (not deeper descendants).

        A part with no id is represented by ``"(part:<name>)"`` so it is still
        visible in a cascade-block report.
        """
        ids: list[str] = []
        for kind in ("groups", "controls"):
            for child in obj.get(kind, []):
                ids.append(child.get("id", ""))
        for part in obj.get("parts", []):
            ids.append(part.get("id") or f"(part:{part.get('name', '')})")
        return ids

    # -------------------------------------------------------------------------
    @staticmethod
    def _scan_dangling_refs(node: dict, targets: set, owner_id: str = "[root]") -> list:
        """Collect links in ``node`` (recursively) whose href points at a removed id.

        Args:
            node (dict, required): A catalog root, group, control, or part to scan.
            targets (set, required): The set of ``"#<id>"`` href values now dangling.
            owner_id (str, optional): Id of the nearest enclosing group/control/part.

        Returns:
            list: ``{"in", "href", "rel"}`` dicts, one per dangling link found.
        """
        found: list[dict] = []
        my_id = node.get("id", owner_id)
        for link in node.get("links", []):
            if link.get("href") in targets:
                found.append({"in": my_id, "href": link.get("href"), "rel": link.get("rel", "")})
        for kind in ("groups", "controls", "parts"):
            for child in node.get(kind, []):
                found.extend(Catalog._scan_dangling_refs(child, targets, my_id))
        return found

    # -------------------------------------------------------------------------
    def _external_referenced_ids(self, skip_obj: dict, id_list: list) -> list:
        """Return which of ``id_list`` are referenced from *outside* ``skip_obj``.

        Scans the catalog's group/control/part links for hrefs of the form
        ``#<id>`` targeting one of the ids that would be removed, ignoring links that
        live inside the ``skip_obj`` subtree (those would be removed too and so can't
        dangle). Result preserves ``id_list`` order.
        """
        target_set = set(id_list)
        referenced: set = set()

        def walk(node: dict) -> None:
            if node is skip_obj:
                return  # do not look inside the branch being removed
            for link in node.get("links", []):
                href = link.get("href", "")
                if href.startswith("#") and href[1:] in target_set:
                    referenced.add(href[1:])
            for kind in ("groups", "controls", "parts"):
                for child in node.get(kind, []):
                    walk(child)

        walk(self._catalog_root())
        return [i for i in id_list if i in referenced]

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    def remove(self, id: str, cascade: bool = False, ignore_references: bool = False) -> Optional[dict]:
        """Remove a control or group (found by id) from the catalog.

        Two independent locks guard the delete; either can block it, and the return
        value makes the reason explicit:

          * **cascade** — when ``cascade`` is False, a node with *immediate* children
            (direct groups, controls, or parts) is not removed. The block report
            lists those immediate child ids under ``"children"``. Set ``cascade=True``
            to remove the node together with everything beneath it.
          * **referential integrity** — when ``ignore_references`` is False, the node
            is not removed if any id in its subtree (the node, nested groups/controls,
            or any part) is referenced by a link elsewhere in the catalog. The block
            report lists those referenced ids under ``"referenced_ids"``. Set
            ``ignore_references=True`` to delete anyway; the now-dangling references
            are then returned under ``"dangling_refs"``.

        Both conditions are evaluated; if both block, ``"blocked_by"`` contains both
        reasons and both detail lists are present. Nothing is modified when blocked.

        References in *other* documents (profiles, SSPs, mappings) cannot be seen or
        fixed from here; on a successful delete a warning notes they may now break.
        Refreshes ``controls_tree`` on success.

        Args:
            id (str, required): The id of the control or group to remove.
            cascade (bool, optional): Permit removing a node that has immediate
                children. Defaults to False.
            ignore_references (bool, optional): Permit removing a node that is
                referenced elsewhere in the catalog. Defaults to False.

        Returns:
            Optional[dict]:
                * ``None`` when no control/group has that id.
                * On block: ``{"removed": False, "blocked_by": [...],
                  "children": [...]?, "referenced_ids": [...]?}``.
                * On success: ``{"removed": True, "removed_ids": [...],
                  "dangling_refs": [...]}``.
        """
        container, kind, obj = self._find_parent_and_obj(id)
        if obj is None:
            logger.warning(f"REMOVE: no control or group found with id '{id}'")
            return None

        would_remove = self._subtree_ids(obj)

        blocked_by: list[str] = []
        block: dict[str, Any] = {"removed": False}

        # Cascade lock — immediate children (groups, controls, or parts).
        immediate_children = self._immediate_child_ids(obj)
        if immediate_children and not cascade:
            blocked_by.append("cascade")
            block["children"] = immediate_children

        # Referential-integrity lock — removed ids referenced from outside the subtree.
        referenced_ids = self._external_referenced_ids(obj, would_remove)
        if referenced_ids and not ignore_references:
            blocked_by.append("referential-integrity")
            block["referenced_ids"] = referenced_ids

        if blocked_by:
            block["blocked_by"] = blocked_by
            logger.info(f"REMOVE: '{id}' blocked by {blocked_by}.")
            return block

        # --- perform the removal ---
        container[kind].remove(obj)
        # OSCAL keeps empty arrays out of content; drop the list if it is now empty.
        if not container[kind]:
            container.pop(kind, None)

        targets = {f"#{rid}" for rid in would_remove}
        dangling_refs = self._scan_dangling_refs(self._catalog_root(), targets)

        self._build_controls_tree()
        self.is_unsaved = True
        self.last_modified = oscal_date_time_with_timezone()

        logger.warning(
            f"REMOVE: removed {len(would_remove)} object(s) [{', '.join(would_remove)}]; "
            "references in other documents (profiles, SSPs, mappings) to these ids "
            "may now be broken."
        )
        return {"removed": True, "removed_ids": would_remove, "dangling_refs": dangling_refs}

    # -------------------------------------------------------------------------
    def _tree_node(self, obj: dict, is_group: bool) -> dict[str, Any]:
        """Build a single ``controls_tree`` node for a group or control dict.

        The ``label`` is taken from the object's ``label`` property in the default
        OSCAL namespace with no ``class`` and no ``group`` specified; when more than
        one such property exists, the first (best match) is used. Children are the
        object's nested groups followed by its nested controls (control enhancements
        are controls nested inside controls), recursively.

        Args:
            obj (dict, required): The group or control dict to describe.
            is_group (bool, required): True when ``obj`` is a group, False for a control.

        Returns:
            dict: A node ``{"id", "label", "title", "group", "children"}``.
        """
        label_props = get_props(obj, name="label")
        label = label_props[0].get("value", "") if label_props else ""

        children: list[dict[str, Any]] = []
        for grp in obj.get("groups", []):
            children.append(self._tree_node(grp, is_group=True))
        for ctrl in obj.get("controls", []):
            children.append(self._tree_node(ctrl, is_group=False))

        return {
            "id":       obj.get("id", ""),
            "label":    label,
            "title":    obj.get("title", ""),
            "group":    is_group,
            "children": children,
        }

    # -------------------------------------------------------------------------
    def _build_controls_tree(self) -> list[dict[str, Any]]:
        """(Re)build ``controls_tree``, a light view of the catalog hierarchy.

        Produces a nested list of ``{"id", "label", "title", "group", "children"}``
        nodes mirroring the catalog's groups and controls, intended for tree
        navigation in a UI. Rebuilt from the current ``_dict`` on each call, so it
        is safe to call after any structural change. Also stored on
        ``self.controls_tree``.

        Returns:
            list: The freshly built ``controls_tree``.
        """
        root = self._catalog_root()
        tree: list[dict[str, Any]] = []
        for grp in root.get("groups", []):
            tree.append(self._tree_node(grp, is_group=True))
        for ctrl in root.get("controls", []):
            tree.append(self._tree_node(ctrl, is_group=False))
        self.controls_tree = tree
        return tree

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class Profile(OSCAL):
    """Editable OSCAL Profile model with tree-driven, lazy resolution.

    A profile selects and tailors controls from one or more imported catalogs/profiles.
    Resolution is split into a cheap load-time step and an on-demand heavy step:

    * **controls_tree (source of truth).** On load — and after any import/directive
      change — :meth:`_build_controls_tree` reads each imported object's own
      ``controls_tree`` and applies the profile's directives to produce this profile's
      ``controls_tree``: the authoritative scope and organization. It is lightweight
      (ids + hierarchy + an ``origin`` back to each node's immediate source); no control
      content is copied. Directives applied here: ``import``/``include``/``exclude``
      selection, ``merge`` (``as-is`` or ``flat``; ``custom`` is deferred and falls back
      to ``as-is``), and ``combine`` duplicate handling (``keep`` renames the node id,
      ``use-first`` drops later duplicates). When an ``as-is`` merge would place controls
      and groups together at the root, root controls are wrapped in a synthetic
      "ROOT CONTROLS" group.

    * **resolve() (heavy, cacheable).** :meth:`resolve` walks the tree and materializes a
      brand-new ``Catalog`` in :attr:`catalog`, fetching real content per node, applying
      ``modify`` directives (removes → adds → set-parameters) and full internal id
      renaming for duplicates, hoisting externally-defined cited parameters to the root,
      carrying forward referenced back-matter resources, and rewriting out-of-scope
      references to their source URIs. ``catalog`` is ``None`` until ``resolve`` is called.

    * **Read-only Catalog surface.** :meth:`get_control_by_id`, :meth:`get_group_by_id`,
      and :meth:`get_control_list` return safe copies from :attr:`catalog` when resolved,
      or materialize them on demand from the source (through the same code path, so the
      two agree) when unresolved. Content is changed via the profile's own directive
      methods and re-resolved, not by editing returned copies.

    Key attributes:
        catalog (Catalog | None): The resolved catalog, or None until :meth:`resolve`.
        controls_tree (list[dict]): Scope/organization nodes
            ``{id, label, title, group, origin, children}``.
        duplicates (dict): Controls/groups renamed or dropped by ``combine``, keyed by
            original id (see :meth:`_record_duplicate`).
        resolution_status (ResolutionStatus): UNRESOLVED / RESOLVING / RESOLVED / BLOCKED.
    """
    def _init_common(self):
        super()._init_common()
        # The resolved catalog is built lazily by resolve(); None until then.
        self.catalog: Optional[Catalog] = None

        self.resolution_state = "unresolved"
        self.resolution_status = ResolutionStatus.UNRESOLVED
        self.resolved_datetime = datetime.now(timezone.utc)
        self.resolution_ttl = 0
        # controls_tree is the source of truth for control/group scope & organization.
        # Each node is {id, label, title, group, origin, children}; ``origin`` links the
        # node to its immediate import source: {object_uuid, source_id, import_index}.
        self.controls_tree: list[dict[str, Any]] = []
        # Duplicate controls/groups discovered while building controls_tree (combine).
        # Shape: {"controls": {orig_id: [{new_id, uuid, import_index} | {dropped, import_index}]},
        #         "groups":   {orig_id: [ ... ]}}
        self.duplicates: dict[str, dict[str, list]] = {"controls": {}, "groups": {}}
        # Set whenever imports/directives change; the tree is rebuilt on next access.
        self._tree_dirty: bool = True
        # Cached index of this profile's modify directives (alters by control-id,
        # set-parameters by param-id); rebuilt lazily and cleared with the tree.
        self._modify_idx: Optional[dict] = None

        # Best-effort build at load; guarded so content-not-ready never breaks init.
        try:
            self._ensure_controls_tree()
        except Exception as error:  # pragma: no cover - defensive
            logger.debug(f"Profile._init_common: deferred controls_tree build ({error}).")

    # -------------------------------------------------------------------------
    def _ensure_controls_tree(self) -> None:
        """Rebuild :attr:`controls_tree` if it is stale (imports/directives changed)."""
        if self._tree_dirty:
            self._build_controls_tree()

    # -------------------------------------------------------------------------
    def _build_controls_tree(self):
        """Build the profile's controls_tree from its imports' controls_trees.

        Reads each imported object's controls_tree (a Catalog's, or an imported
        Profile's own load-time tree), applies the profile's select/exclude and merge
        directives, resolves duplicate ids (renaming only the node id — internal-id
        mutation is deferred to :meth:`resolve`), tags every node with an ``origin``,
        and prunes empty groups. Populates :attr:`controls_tree` and :attr:`duplicates`.

        For ``as-is`` merges, if the result would place controls and groups together at
        the root (which OSCAL forbids), the root controls are wrapped in a synthetic
        "ROOT CONTROLS" group via :meth:`_wrap_root_controls`.

        Best-effort: if content or imports are not yet available the tree is left empty
        and ``_tree_dirty`` stays set so it rebuilds on the next access.
        """
        self.duplicates = {"controls": {}, "groups": {}}
        self._modify_idx = None
        if not isinstance(self._dict, dict) or self.model not in self._dict:
            self.controls_tree = []
            return
        root = self._dict.get(self.model, {})
        if not root.get("imports"):
            self.controls_tree = []
            self._tree_dirty = False
            return
        if not self.imports_resolved:
            self.resolve_imports()

        sources, blocking = self._resolution_sources()
        for idx, href, status in blocking:
            logger.warning(f"controls_tree: import {idx} ('{href}') not resolved "
                           f"(status={status}); excluded from scope.")

        mode, combine = self._merge_mode()
        # A synthetic "ROOT CONTROLS" wrapper is only relevant to as-is: flat has no
        # groups (so no root mix), and custom defines its own structure.
        wrap_root = (mode == "as-is")
        if mode == "custom":
            logger.warning("controls_tree: 'custom' merge is not yet implemented; "
                           "falling back to 'as-is'.")
            mode = "as-is"
            wrap_root = False

        # id -> placed node, shared across imports so duplicates merge/rename correctly.
        ctrl_nodes: dict[str, dict] = {}
        group_nodes: dict[str, dict] = {}
        result: list[dict[str, Any]] = []

        for idx, (imp, source_obj) in enumerate(sources):
            src_tree = getattr(source_obj, "controls_tree", None) or []
            if not src_tree:
                logger.warning(f"controls_tree: import {idx} source has no controls_tree; "
                               "it contributes nothing.")
                continue
            selected, warnings = _selected_tree_ids(imp, src_tree)
            for w in warnings:
                logger.warning(f"controls_tree: import {idx}: {w}")
            self._place_tree_import(result, src_tree, selected, source_obj.uuid,
                                    mode, combine, idx, ctrl_nodes, group_nodes)

        result = _prune_empty_group_nodes(result)
        if wrap_root:
            result = self._wrap_root_controls(result)
        self.controls_tree = result
        self._tree_dirty = False

    # -------------------------------------------------------------------------
    def _wrap_root_controls(self, tree: list) -> list:
        """Wrap root-level controls in a synthetic group when groups also sit at root.

        OSCAL forbids controls and groups at the same level. Profile resolution can
        legitimately place both at the catalog root (one import contributing top-level
        controls, another contributing groups) — an under-specified case in the
        spec. This resolves it by moving every root-level control into a new group,
        inserted first, with a fresh uuid, the title "ROOT CONTROLS", and ``sort-id``
        "0" / ``label`` "/" props (so it sorts and labels ahead of the real families).
        """
        groups = [n for n in tree if n.get("group")]
        controls = [n for n in tree if not n.get("group")]
        if not (groups and controls):
            return tree
        # A group id is a TokenDatatype and cannot start with a digit, so a raw UUID is
        # not valid — prefix it with '_' to keep it unique and token-valid.
        gid = "_" + new_uuid()
        wrapper = {
            "id": gid,
            "label": "/",
            "title": "ROOT CONTROLS",
            "group": True,
            "origin": None,
            # Full intrinsic content for a synthetic group with no import source.
            "intrinsic": {
                "id": gid,
                "title": "ROOT CONTROLS",
                "props": [{"name": "sort-id", "value": "0"},
                          {"name": "label", "value": "/"}],
            },
            "children": controls,
        }
        return [wrapper] + groups

    # -------------------------------------------------------------------------
    def _export_state(self) -> dict:
        """Extend the base state snapshot with the profile's resolution state.

        Returns:
            dict: Base derived state plus resolution status/state/ttl and the
                cached controls tree.
        """
        state = super()._export_state()
        rs = self.resolution_status
        state["resolution_state"]  = self.resolution_state
        state["resolution_status"] = rs.value if hasattr(rs, "value") else str(rs)
        state["resolution_ttl"]    = self.resolution_ttl
        state["controls_tree"]     = self.controls_tree
        return state

    # -------------------------------------------------------------------------
    def _import_state(self, state: dict) -> None:
        """Restore base state plus the profile's resolution state.

        Args:
            state (dict, required): The persisted state dict.
        """
        super()._import_state(state)
        if not state:
            return
        self.resolution_state = state.get("resolution_state", self.resolution_state)
        raw_status = state.get("resolution_status")
        if raw_status is not None:
            try:
                self.resolution_status = ResolutionStatus(raw_status)
            except ValueError:
                pass
        self.resolution_ttl = state.get("resolution_ttl", self.resolution_ttl)
        self.controls_tree = state.get("controls_tree", self.controls_tree)

    # -------------------------------------------------------------------------
    def _find_duplicate_import(self, href: str) -> Optional[dict]:
        """Return this profile's own import entry that already targets ``href``.

        Only this document's direct imports are considered — duplicate imports
        farther down the import tree are out of scope and intentionally ignored.
        Each existing import is compared by its resolved target: fragment imports
        (``href="#uuid"``) are followed through back-matter to their ``rlink``
        target(s); direct imports are compared by their resolved href.

        Args:
            href (str, required): The candidate import target (a file href, not a
                ``#uuid`` fragment).

        Returns:
            Optional[dict]: The conflicting existing import entry, or None.
        """
        resolved_new = self._resolve_import_href(href)
        root = self._dict.get(self.model, {}) if isinstance(self._dict, dict) else {}
        resources = root.get("back-matter", {}).get("resources", [])
        res_by_uuid = {r.get("uuid"): r for r in resources if isinstance(r, dict)}

        for imp in root.get("imports", []):
            if not isinstance(imp, dict):
                continue
            imp_href = str(imp.get("href", "")).strip()
            targets: list[str] = []
            if imp_href.startswith("#"):
                res = res_by_uuid.get(imp_href[1:])
                if res:
                    for rlink in res.get("rlinks", []):
                        rl_href = rlink.get("href", "")
                        if rl_href:
                            targets.append(self._resolve_import_href(rl_href))
            elif imp_href:
                targets.append(self._resolve_import_href(imp_href))

            if resolved_new in targets:
                return imp
        return None

    # -------------------------------------------------------------------------
    def add_import(self, href: str, title: str = "", description: str = "", remarks: str = "", include_all: bool = False) -> ImportResult:
        """
        Add an import to the profile, backed by a new back-matter resource.

        Steps:
            1. If ``href`` already appears among this profile's own imports, block it
               and report a "duplicate" (an error condition). Duplicate imports
               farther down the import tree are acceptable and out of scope.
            2. Create a back-matter ``resource`` (with an ``rlink`` to ``href`` and a
               best-effort ``media-type`` inferred from the href's file extension).
            3. Add an ``imports`` entry that references the resource by UUID fragment
               (``href="#<resource-uuid>"``). An existing empty placeholder import
               (href ``""`` or ``"#"``) is replaced in place; otherwise the entry is
               appended.
            4. Refresh the import tree (:meth:`resolve_imports`). The natural import
               process loads the referenced content and reports success or failure;
               an unreachable or invalid href simply resolves to ``INVALID`` in the
               tree, and the caller decides whether that is acceptable.

        Args:
            href (str, required): Reference to the imported OSCAL file (XML, JSON, or
                YAML). Used as the resource ``rlink`` href.
            title (str, optional): Title for the created back-matter resource.
            description (str, optional): Description for the created resource.
            remarks (str, optional): Remarks (markdown) for the created resource.
            include_all (bool, optional): When True, the import selects all controls
                via ``include-all``. Defaults to False.

        Returns:
            ImportResult: The outcome — ``status`` of "added", "replaced",
                "duplicate", or "error", with the relevant ``entry`` and ``resource``.
        """
        if not href:
            logger.error("add_import: 'href' is required.")
            return ImportResult("error", message="'href' is required.")

        if not self._can_mutate("add_import"):
            return ImportResult("error", message="content is read-only or unavailable.")

        # 1. Block duplicates among this profile's own imports.
        existing = self._find_duplicate_import(href)
        if existing is not None:
            logger.error(f"add_import: '{href}' is already imported by this profile.")
            return ImportResult("duplicate", entry=existing, message=f"'{href}' is already imported.")

        # 2. Create the back-matter resource.
        resource_uuid = new_uuid()
        rlink: dict[str, Any] = {"href": href}
        media_type = _infer_media_type(href)
        if media_type:
            rlink["media-type"] = media_type
        else:
            logger.debug(f"add_import: could not infer media-type for '{href}'.")

        resource: dict[str, Any] = {"uuid": resource_uuid}
        if title:
            resource["title"] = title
        if description:
            resource["description"] = description
        resource["rlinks"] = [rlink]
        if remarks:
            resource["remarks"] = remarks

        if not self.put("back-matter/resources", resource, mode="insert"):
            logger.error(f"add_import: failed to add back-matter resource for '{href}'.")
            return ImportResult("error", message="failed to add back-matter resource.")

        # 3. Build the import entry; replace an empty placeholder if one exists.
        import_entry: dict[str, Any] = {"href": f"#{resource_uuid}"}
        if include_all:
            import_entry["include-all"] = {}

        imports = self._dict.get(self.model, {}).get("imports", [])
        placeholder_idx = next(
            (i for i, imp in enumerate(imports)
             if isinstance(imp, dict) and str(imp.get("href", "")).strip() in ("", "#")),
            None,
        )
        if placeholder_idx is not None:
            if not self.put(f"imports/{placeholder_idx}", import_entry, mode="replace"):
                logger.error(f"add_import: failed to replace placeholder import for '{href}'.")
                return ImportResult("error", message="failed to replace placeholder import.")
            status = "replaced"
        else:
            if not self.put("imports", import_entry, mode="insert"):
                logger.error(f"add_import: failed to add import entry for '{href}'.")
                return ImportResult("error", message="failed to add import entry.")
            status = "added"

        # 4. Refresh the import tree; the natural load reports success/failure.
        self.resolve_imports()

        # 5. Imports changed — the controls_tree (scope/organization) is now stale.
        self._tree_dirty = True
        self._ensure_controls_tree()

        logger.info(f"add_import: {status} import '{href}' as resource {resource_uuid}.")
        return ImportResult(status, entry=import_entry, resource=resource)

    # -------------------------------------------------------------------------
    def control(self, control_id: str, with_history: bool = False,
                depth: Optional[int] = None) -> Optional[dict]:
        """Retrieve a control by its ID, as a safe copy (thin alias of
        :meth:`get_control_by_id`).

        Works whether or not the profile is resolved: resolved fetches from
        ``self.catalog``; unresolved materializes on demand from the source via the
        profile's controls_tree.

        Args:
            control_id (str, required): The ``id`` of the control to retrieve.
            with_history (bool, optional): Reserved for including tailoring history.
                Defaults to False.
            depth (int | None, optional): Nested-enhancement depth. ``None`` (default)
                returns the full subtree; ``0`` omits enhancements; ``N`` keeps N levels.

        Returns:
            Optional[dict]: A safe copy of the control, or None if not found.
        """
        return self.get_control_by_id(control_id, depth=depth)

    # -------------------------------------------------------------------------
    @staticmethod
    def _find_child_node(node: dict, name: str) -> Optional[dict]:
        """Find a child metaschema index node by (use-)name.

        Descends into ``choice`` groupings, since mutually-exclusive members such as
        ``flat``/``as-is``/``custom`` live inside a choice node rather than directly
        under their parent.

        Args:
            node (dict, required): The index node whose children to search.
            name (str, required): The element (use-)name to find.

        Returns:
            Optional[dict]: The matching child node, or None.
        """
        for child in node.get("children", []):
            if (child.get("use-name") or child.get("name")) == name:
                return child
            if child.get("structure-type") == "choice":
                found = Profile._find_child_node(child, name)
                if found is not None:
                    return found
        return None

    # -------------------------------------------------------------------------
    def _merge_index_nodes(self) -> tuple:
        """Return ``(combine_node, custom_node)`` from the profile metaschema index.

        Returns ``(None, None)`` when the index (or the ``merge`` node) is
        unavailable, so callers degrade to setting the directives without metaschema
        validation — mirroring how :meth:`validate` treats a missing index.

        Returns:
            tuple: ``(combine_node, custom_node)``; either element may be None.
        """
        index = self._support.get_metaschema_index(self.oscal_version, self.model)
        if not index:
            return None, None
        root = index.get("nodes")
        if not isinstance(root, dict):
            return None, None
        merge_node = self._find_child_node(root, "merge")
        if merge_node is None:
            return None, None
        return (self._find_child_node(merge_node, "combine"),
                self._find_child_node(merge_node, "custom"))

    # -------------------------------------------------------------------------
    @staticmethod
    def _format_index_errors(errors: list) -> str:
        """Render metaschema-walk errors as a compact one-line summary."""
        return "; ".join(
            f"{e.get('error-type')} at {e.get('location', '')} "
            f"field={e.get('field', '')} value={e.get('value')!r}"
            for e in errors
        )

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def set_merge(self, flat: bool = False, as_is: Optional[bool] = None,
                  custom: Optional[dict] = None, combine: Optional[str] = None) -> Optional[dict]:
        """Set the profile's ``merge`` directives (``combine`` plus flat/as-is/custom).

        The ``merge`` assembly instructs how imported controls are organized after
        profile resolution. Exactly one of ``flat``, ``as_is``, or ``custom`` must be
        chosen — they are mutually exclusive — while ``combine`` is optional and may
        accompany any of those choices.

        The ``custom`` object is accepted whole and validated against the ``custom``
        portion of the profile metaschema index; if it fails validation the profile is
        left unchanged. Fine-grained management of ``custom`` internals (its ``groups``
        and ``insert-controls``) is intentionally deferred to future methods, as custom
        merges are uncommon.

        Args:
            flat (bool, optional): When True, select the ``flat`` directive (resolved
                controls are flattened, without groups). Defaults to False.
            as_is (bool, optional): When set, select the ``as-is`` directive with this
                boolean value (True keeps the source organization). Defaults to None
                (not selected).
            custom (dict, optional): When set, select the ``custom`` directive using
                this object. Validated against the metaschema index. Defaults to None
                (not selected).
            combine (str, optional): The ``combine`` method — one of ``"use-first"``,
                ``"merge"``, or ``"keep"``. When None, no ``combine`` is written.

        Returns:
            Optional[dict]: The ``merge`` dict written to the profile, or None on
                failure — when not exactly one of flat/as-is/custom is given, an
                argument has the wrong type, ``combine`` is not a valid method, or the
                ``custom`` object fails metaschema validation.
        """
        if not isinstance(self._dict, dict):
            logger.error("set_merge: profile content is not available.")
            return None

        # Exactly one of flat / as-is / custom (mutually exclusive, one required).
        chosen = []
        if flat:
            chosen.append("flat")
        if as_is is not None:
            chosen.append("as-is")
        if custom is not None:
            chosen.append("custom")
        if len(chosen) != 1:
            logger.error(
                "set_merge: exactly one of 'flat', 'as_is', or 'custom' must be "
                f"provided; got {chosen or 'none'}."
            )
            return None

        if as_is is not None and not isinstance(as_is, bool):
            logger.error("set_merge: 'as_is' must be a bool.")
            return None
        if custom is not None and not isinstance(custom, dict):
            logger.error("set_merge: 'custom' must be a dict.")
            return None
        if combine is not None and (not isinstance(combine, str) or not combine):
            logger.error("set_merge: 'combine' must be a non-empty method string.")
            return None

        # Validate combine method and the custom object against the metaschema index.
        combine_node, custom_node = self._merge_index_nodes()

        if combine is not None and combine_node is not None:
            errors: list[dict] = []
            self._walk_instance({"method": combine}, combine_node, errors, "/profile/merge/combine")
            if errors:
                logger.error(f"set_merge: invalid 'combine' method '{combine}': "
                             f"{self._format_index_errors(errors)}")
                return None

        if custom is not None and custom_node is not None:
            errors = []
            self._walk_instance(custom, custom_node, errors, "/profile/merge/custom")
            if errors:
                logger.error("set_merge: 'custom' failed metaschema validation: "
                             f"{self._format_index_errors(errors)}")
                return None

        # Build merge in canonical order: combine first, then the chosen directive.
        merge: dict[str, Any] = {}
        if combine is not None:
            merge["combine"] = {"method": combine}
        if flat:
            merge["flat"] = {}
        elif as_is is not None:
            merge["as-is"] = as_is
        else:
            merge["custom"] = custom

        self._dict.setdefault(self.model, {})["merge"] = merge
        # Merge directive changed — the controls_tree (organization) is now stale.
        self._tree_dirty = True
        self._ensure_controls_tree()
        # Return a safe copy — the live merge node stays in _dict; edits go through methods.
        return copy.deepcopy(merge)

    # =========================================================================
    # controls_tree construction (placement) — builds the profile's own tree
    # =========================================================================
    def _place_tree_import(self, result: list, src_tree: list, selected: set,
                           source_uuid: str, mode: str, combine: str, import_index: int,
                           ctrl_nodes: dict, group_nodes: dict) -> None:
        """Place one import's selected control nodes into the profile ``result`` tree.

        Operates purely on lightweight controls_tree nodes. Under ``as-is`` each control
        keeps its source group ancestry (groups created lazily, so empties never appear);
        under ``flat`` controls go at the root. Duplicates follow the ``combine`` directive:

          * ``use-first`` — the first instance is kept; a later duplicate control is dropped
            but its NEW descendant enhancements are merged into the kept control, and a
            later duplicate group's controls are merged into the kept group.
          * ``keep`` — a later duplicate control/group is renamed (``__<uuid>``); its
            children stay with it, except any child that itself collides is handled
            independently.

        ``ctrl_nodes``/``group_nodes`` map placed id → node and are shared across imports,
        so merges and renames see everything placed so far. Every emitted node is tagged
        with an ``origin`` back to its immediate source. Internal id renaming for ``keep``
        duplicates is deferred to :meth:`resolve`.
        """
        import_group_map: dict[str, dict] = {}   # per-import: source gid -> group node used

        def make_node(src_node: dict, new_id: str, is_group: bool) -> dict:
            return {
                "id": new_id,
                "label": src_node.get("label", ""),
                "title": src_node.get("title", ""),
                "group": is_group,
                "origin": {"object_uuid": source_uuid,
                           "source_id": src_node.get("id"),
                           "import_index": import_index},
                "children": [],
            }

        def resolve_group(gsrc: dict, parent_children: list) -> list:
            """Return the child-list to descend into for one source group in the path."""
            gid = gsrc.get("id")
            if not gid:
                logger.warning("controls_tree: source group without id skipped; "
                               "its controls bubble up to the nearest parent.")
                return parent_children
            if combine == "use-first":
                # Merge: all controls funnel into the single kept group with this id.
                existing = group_nodes.get(gid)
                if existing is not None:
                    return existing["children"]
                gnode = make_node(gsrc, gid, True)
                parent_children.append(gnode)
                group_nodes[gid] = gnode
                return gnode["children"]
            # keep: reuse this import's instance, else rename a new instance on collision.
            reused = import_group_map.get(gid)
            if reused is not None:
                return reused["children"]
            if gid in group_nodes:
                uid = new_uuid()
                new_gid = f"{gid}__{uid}"
                self._record_duplicate("groups", gid, new_gid, import_index, uuid=uid)
            else:
                new_gid = gid
            gnode = make_node(gsrc, new_gid, True)
            parent_children.append(gnode)
            group_nodes[new_gid] = gnode
            import_group_map[gid] = gnode
            return gnode["children"]

        def ensure_group(group_path: list) -> list:
            if mode != "as-is":
                return result
            parent_children = result
            for gsrc in group_path:
                parent_children = resolve_group(gsrc, parent_children)
            return parent_children

        def place_control(src_node: dict, dest_children: list) -> None:
            cid = src_node.get("id")
            existing = ctrl_nodes.get(cid)
            if existing is not None:
                if combine == "use-first":
                    # Drop this duplicate, but keep any NEW enhancements it introduces.
                    self._record_duplicate("controls", cid, None, import_index, dropped=True)
                    attach_enhancements(src_node, existing)
                    return
                # keep: rename this instance; its children ride along (colliding ones
                # are handled independently when attached).
                uid = new_uuid()
                new_id = f"{cid}__{uid}"
                self._record_duplicate("controls", cid, new_id, import_index, uuid=uid)
                node = make_node(src_node, new_id, False)
                dest_children.append(node)
                ctrl_nodes[new_id] = node
                attach_enhancements(src_node, node)
                return
            node = make_node(src_node, cid, False)
            dest_children.append(node)
            ctrl_nodes[cid] = node
            attach_enhancements(src_node, node)

        def attach_enhancements(src_node: dict, node: dict) -> None:
            for child in src_node.get("children", []):
                if child.get("group"):
                    continue
                if child.get("id") in selected:
                    place_control(child, node["children"])
                else:
                    promote(child, node["children"])

        def promote(src_node: dict, dest_children: list) -> None:
            for child in src_node.get("children", []):
                if child.get("group"):
                    continue
                if child.get("id") in selected:
                    place_control(child, dest_children)
                else:
                    promote(child, dest_children)

        def promote_top(src_node: dict, group_path: list) -> None:
            for child in src_node.get("children", []):
                if child.get("group"):
                    continue
                if child.get("id") in selected:
                    place_control(child, ensure_group(group_path))
                else:
                    promote_top(child, group_path)

        def walk(nodes: list, group_path: list) -> None:
            for n in nodes:
                if n.get("group"):
                    walk(n.get("children", []), group_path + [n])
                elif n.get("id") in selected:
                    place_control(n, ensure_group(group_path))
                else:
                    promote_top(n, group_path)

        walk(src_tree, [])

    # =========================================================================
    # Profile resolution: materialize the resolved catalog in self.catalog
    # =========================================================================
    def resolve(self) -> "ResolutionStatus":
        """Materialize the profile's controls_tree into a fresh ``self.catalog``.

        Resolution is the (future-cacheable) heavy step: it walks the profile's
        controls_tree — the authoritative scope/organization built at load — and for each
        node fetches the real control/group content from its origin source, applies this
        profile's ``modify`` directives (removes → adds → set-parameters), applies full
        internal ``__<uuid>`` id renaming for duplicates, then inserts it into a brand-new
        ``Catalog``. Any previously resolved catalog is discarded and replaced. After
        placement it: hoists cited-but-externally-defined parameters to the catalog root
        (:meth:`_insert_shared_params`), assembles metadata, carries forward referenced
        back-matter resources (:meth:`_carry_backmatter`), rewrites references to
        out-of-scope ids to their source URIs (:meth:`_rewrite_out_of_scope_refs`), and
        validates.

        Because content is fetched through each source's own getters, imported *profiles*
        need not be pre-resolved — their load-time controls_tree and lazy getters suffice.

        Returns:
            ResolutionStatus: ``RESOLVED`` on success, or ``BLOCKED`` when content is
                missing or an import could not be resolved.
        """
        if not isinstance(self._dict, dict):
            logger.error("resolve: profile content is not available.")
            self.resolution_status = ResolutionStatus.BLOCKED
            self.resolution_state = "blocked"
            return self.resolution_status

        self.resolution_status = ResolutionStatus.RESOLVING
        self.resolution_state = "resolving"
        self._ensure_controls_tree()

        sources, blocking = self._resolution_sources()
        if blocking:
            for idx, href, status in blocking:
                logger.error(f"resolve: import {idx} ('{href}') is not resolved "
                             f"(status={status}); cannot resolve profile.")
            self.resolution_status = ResolutionStatus.BLOCKED
            self.resolution_state = "blocked"
            return self.resolution_status

        target = cast(Catalog, Catalog.new(self._profile_title()))
        shared_params: list = []   # cited-but-externally-defined params, hoisted to root
        for node in self.controls_tree:
            self._materialize_into_catalog(target, node, "[root]", shared_params)
        self._insert_shared_params(target, shared_params)

        self._assemble_metadata(target, sources)
        self._carry_backmatter(target)
        self._rewrite_out_of_scope_refs(target)

        target.validate()
        if not target.is_valid:
            logger.warning("resolve: resolved catalog did not pass validation; "
                           "inspect Profile.catalog.validation_errors.")

        self.catalog = target
        self.resolution_status = ResolutionStatus.RESOLVED
        self.resolution_state = "resolved"
        self.resolved_datetime = datetime.now(timezone.utc)
        logger.info(f"resolve: produced catalog with {len(target)} controls.")
        return self.resolution_status

    # -------------------------------------------------------------------------
    def _materialize_into_catalog(self, target: "Catalog", node: dict, parent_id: str,
                                  shared_params: list) -> None:
        """Insert one controls_tree node (and its subtree) into ``target``."""
        if node.get("group"):
            intrinsic = self._fetch_group_intrinsic(node)
            if target.insert_group(parent_id, intrinsic, shallow=True, validate=False) is None:
                logger.warning(f"resolve: could not place group '{node.get('id')}' "
                               f"under '{parent_id}'; skipping its subtree.")
                return
            for child in node.get("children", []):
                self._materialize_into_catalog(target, child, node["id"], shared_params)
        else:
            content = self._materialize_control_node(node, depth=None, shared_sink=shared_params)
            if content is None:
                logger.warning(f"resolve: could not fetch content for control "
                               f"'{node.get('id')}'; skipping.")
                return
            if target.insert_control(parent_id, content, validate=False) is None:
                logger.warning(f"resolve: could not place control "
                               f"'{content.get('id')}' under '{parent_id}'.")

    # -------------------------------------------------------------------------
    def _insert_shared_params(self, target: "Catalog", shared_params: list) -> None:
        """Insert cited-but-externally-defined parameters at the catalog root (deduped)."""
        if not shared_params:
            return
        root = target._dict.setdefault("catalog", {})
        existing = {p.get("id") for p in root.get("params", []) if isinstance(p, dict)}
        added = 0
        for param in shared_params:
            pid = param.get("id")
            if pid and pid not in existing:
                root.setdefault("params", []).append(param)
                existing.add(pid)
                added += 1
        if added:
            logger.info(f"resolve: hoisted {added} externally-defined parameter(s) to the "
                        "catalog root.")

    # -------------------------------------------------------------------------
    def _profile_title(self) -> str:
        """Return the profile's metadata title (fallback ``'Resolved Profile'``)."""
        meta = self._dict.get(self.model, {}).get("metadata", {}) if isinstance(self._dict, dict) else {}
        return meta.get("title") or "Resolved Profile"

    # -------------------------------------------------------------------------
    def _merge_mode(self) -> tuple:
        """Return ``(mode, combine_method)`` from the profile's ``merge`` directive.

        ``mode`` is one of ``"as-is"``, ``"flat"``, or ``"custom"``; absent ``merge``
        defaults to ``"as-is"``. ``combine_method`` defaults to ``"keep"`` when no
        ``combine`` is present.
        """
        root = self._dict.get(self.model, {}) if isinstance(self._dict, dict) else {}
        merge = root.get("merge") or {}
        combine = (merge.get("combine") or {}).get("method") or "keep"
        if "flat" in merge:
            mode = "flat"
        elif "custom" in merge:
            mode = "custom"
        elif "as-is" in merge:
            mode = "as-is" if merge.get("as-is") else "flat"
        else:
            mode = "as-is"
        return mode, combine

    # -------------------------------------------------------------------------
    def _resolution_sources(self) -> tuple:
        """Correlate this profile's ``imports`` with their resolved source objects.

        Each import is matched to its import-list entry by ``href_original`` (unique
        within a profile). A usable source is a READY entry whose live object exposes a
        ``controls_tree`` (a Catalog, or an imported Profile — which need not be resolved,
        since its load-time tree and lazy getters are consumed directly).

        Returns:
            tuple: ``(sources, blocking)`` where ``sources`` is a list of
                ``(import_dict, source_object)`` in document order, and ``blocking`` is a
                list of ``(index, href, status)`` for imports that could not be resolved.
        """
        root = self._dict.get(self.model, {}) if isinstance(self._dict, dict) else {}
        imports = root.get("imports", [])
        by_href = {e.get("href_original"): e for e in self.import_list}

        sources: list = []
        blocking: list = []
        for i, imp in enumerate(imports):
            if not isinstance(imp, dict):
                continue
            href = str(imp.get("href", ""))
            entry = by_href.get(href)
            obj = entry.get("object") if entry else None
            status = entry.get("status") if entry else None
            if obj is None or status != ImportState.READY or not hasattr(obj, "controls_tree"):
                blocking.append((i, href, status))
                continue
            sources.append((imp, obj))
        return sources, blocking

    # -------------------------------------------------------------------------
    def _record_duplicate(self, kind: str, orig_id: str, new_id: Optional[str],
                          import_index: int, uuid: Optional[str] = None,
                          dropped: bool = False) -> None:
        """Append a duplicate record for a control/group id to :attr:`duplicates`."""
        entry: dict[str, Any] = {"import_index": import_index}
        if dropped:
            entry["dropped"] = True
        else:
            entry["new_id"] = new_id
            entry["uuid"] = uuid
        self.duplicates[kind].setdefault(orig_id, []).append(entry)

    # -------------------------------------------------------------------------
    def _rename_uuid_for(self, kind: str, node_id: str) -> Optional[str]:
        """Return the ``__<uuid>`` suffix recorded for a renamed duplicate node id."""
        for records in self.duplicates.get(kind, {}).values():
            for rec in records:
                if rec.get("new_id") == node_id:
                    return rec.get("uuid")
        return None

    # -------------------------------------------------------------------------
    def _fetch_group_intrinsic(self, node: dict) -> dict:
        """Fetch a group's intrinsic content (no children) from its origin source.

        Applies the ``__<uuid>`` id/params/parts rename when the node is a duplicate, so
        the returned group id matches the controls_tree node id.
        """
        # Synthetic groups (e.g. the ROOT CONTROLS wrapper) carry their own content.
        if node.get("intrinsic") is not None:
            return copy.deepcopy(node["intrinsic"])
        origin = node.get("origin") or {}
        source = self.get_oscal_object(origin.get("object_uuid"))
        group = None
        if source is not None:
            group = source.get_group_by_id(origin.get("source_id"), depth=0)
        if group is None:
            group = {"id": origin.get("source_id") or node.get("id"),
                     "title": node.get("title", "") or node.get("id", "")}
        uid = self._rename_uuid_for("groups", node.get("id"))
        if uid:
            _suffix_group(group, uid)
        else:
            group["id"] = node.get("id")
        return group

    # -------------------------------------------------------------------------
    def _materialize_control_node(self, node: dict, depth: Optional[int] = None,
                                  ancestors: tuple = (),
                                  shared_sink: Optional[list] = None) -> Optional[dict]:
        """Build a full control dict from a controls_tree control node.

        Fetches the control's intrinsic content from its origin source (recursing through
        imported profiles as needed), applies THIS profile's ``modify`` directives to it
        (removes → adds → set-parameters, keyed on source-scope ids), applies the
        duplicate ``__<uuid>`` rename, and nests its in-scope enhancement children per
        ``depth``. This single method backs BOTH resolution and the unresolved read path,
        so the two always agree.

        Modify is applied on source-scope ids *before* the duplicate rename, since a
        profile author's ``control-id``/``param-id`` references are to the imported
        source, not to our internal de-duplication renaming. ``ancestors`` carries the
        source ids of enclosing control nodes so that an ancestor's ``by-id`` alter can
        reach into this nested control. Parameters cited here but defined elsewhere are
        brought into scope via :meth:`_resolve_cited_params`.

        Args:
            node (dict, required): A control node from the profile's controls_tree.
            depth (int | None, optional): Enhancement depth — ``None`` full, ``0`` none,
                ``N`` keeps N levels.
            ancestors (tuple, optional): Source ids of enclosing control nodes.
            shared_sink (list | None, optional): When a list (resolve), cited-but-
                externally-defined parameters are collected into it for hoisting to the
                catalog root; when None (JIT), they are embedded in the control instead.

        Returns:
            Optional[dict]: The materialized control, or None when the source content
                cannot be fetched.
        """
        origin = node.get("origin", {})
        source = self.get_oscal_object(origin.get("object_uuid"))
        if source is None:
            return None
        content = source.get_control_by_id(origin.get("source_id"), depth=0)
        if content is None:
            return None

        # This profile's modify directives — on natural (source-scope) ids.
        self._apply_modify(content, origin.get("source_id"), ancestors)
        # Parameters cited here but defined elsewhere are also in scope.
        self._resolve_cited_params(content, shared_sink)

        uid = self._rename_uuid_for("controls", node.get("id"))
        if uid:
            _suffix_control(content, uid)

        content.pop("controls", None)
        if depth != 0:
            child_depth = None if depth is None else depth - 1
            child_ancestors = ancestors + (origin.get("source_id"),)
            kids: list = []
            for child in node.get("children", []):
                if child.get("group"):
                    continue
                materialized = self._materialize_control_node(child, child_depth,
                                                              child_ancestors, shared_sink)
                if materialized is not None:
                    kids.append(materialized)
            if kids:
                content["controls"] = kids
        return content

    # -------------------------------------------------------------------------
    def _modify_index(self) -> dict:
        """Return this profile's modify directives indexed for lookup (cached).

        Keys: ``ordered_alters`` (the ``alters`` list in document order),
        ``alter_control_ids`` (the set of control-ids that have an alter), and
        ``set_params`` (``{param-id: [set-parameter, ...]}`` in document order).
        """
        if self._modify_idx is None:
            modify = self._dict.get(self.model, {}).get("modify", {}) \
                if isinstance(self._dict, dict) else {}
            ordered_alters = [a for a in modify.get("alters", []) if isinstance(a, dict)]
            set_params: dict[str, list] = {}
            for setp in modify.get("set-parameters", []):
                pid = setp.get("param-id") if isinstance(setp, dict) else None
                if pid:
                    set_params.setdefault(pid, []).append(setp)
            self._modify_idx = {
                "ordered_alters": ordered_alters,
                "alter_control_ids": {a.get("control-id") for a in ordered_alters},
                "set_params": set_params,
            }
        return self._modify_idx

    # -------------------------------------------------------------------------
    def _apply_modify(self, content: dict, control_id: str, ancestors: tuple) -> None:
        """Apply this profile's ``modify`` to one control in place: removes → adds → set-parameters.

        Applicable alters are the control's own plus any enclosing-control ancestors'.
        Each ``remove``/``add`` is routed by its ``by-id``: a directive with ``by-id``
        applies wherever that id lives (so an ancestor's alter reaches into this nested
        control); a directive without ``by-id`` applies only to its own control. All
        removes run before any adds. ``set-parameters`` are matched to this control's
        defined parameters.
        """
        mi = self._modify_index()
        applicable_ids = {control_id, *ancestors}
        if mi["alter_control_ids"] & applicable_ids:
            alters = [a for a in mi["ordered_alters"] if a.get("control-id") in applicable_ids]
            for alter in alters:
                own = alter.get("control-id") == control_id
                for remove in alter.get("removes", []):
                    self._apply_remove(content, remove, own)
            for alter in alters:
                own = alter.get("control-id") == control_id
                for add in alter.get("adds", []):
                    self._apply_add(content, add, own)
        self._apply_set_parameters(content)

    # -------------------------------------------------------------------------
    def _apply_remove(self, content: dict, remove: dict, own: bool) -> None:
        """Apply one ``remove`` directive to a control (routing by ``by-id`` presence)."""
        has_by_id = remove.get("by-id") is not None
        if not has_by_id and not own:
            return  # a no-by-id ancestor directive targets the ancestor, not this control
        if not any(remove.get(k) is not None
                   for k in ("by-id", "by-name", "by-class", "by-item-name", "by-ns")):
            logger.warning("modify: remove directive has no by-* selector; skipped.")
            return
        _remove_matching(content, remove)

    # -------------------------------------------------------------------------
    def _apply_add(self, content: dict, add: dict, own: bool) -> None:
        """Apply one ``add`` directive to a control (routing by ``by-id`` presence/target)."""
        by_id = add.get("by-id")
        position = add.get("position")
        # No by-id, or by-id naming the control itself: the control is the anchor.
        if by_id is None or by_id == content.get("id"):
            if by_id is None and not own:
                return  # a no-by-id ancestor add targets the ancestor, not this control
            if position not in ("starting", "ending"):
                logger.warning(f"modify: add targeting the control root must use position "
                               f"starting/ending (got '{position}'); skipped.")
                return
            _add_into(content, add, position)
            return
        anchor = _find_anchor(content, by_id)
        if anchor is None:
            return  # by-id target is not in this control (it belongs to another)
        element, parent, key, index = anchor
        if position in ("starting", "ending"):
            _add_into(element, add, position)
        elif position in ("before", "after"):
            _add_sibling(parent, key, index, add, position)
        else:
            logger.warning(f"modify: add has invalid position '{position}'; skipped.")

    # -------------------------------------------------------------------------
    def _apply_set_parameters(self, content: dict) -> None:
        """Apply this profile's ``set-parameters`` to a control's defined parameters.

        Each parameter defined in the control receives every matching ``set-parameter``
        (by ``param-id``), in profile order. Parameters cited but not defined in the
        control are handled separately by :meth:`_resolve_cited_params`.
        """
        set_params = self._modify_index()["set_params"]
        if not set_params:
            return
        for param in content.get("params", []):
            if not isinstance(param, dict):
                continue
            for setp in set_params.get(param.get("id"), []):
                for warning in _apply_one_set_parameter(param, setp):
                    logger.warning(f"modify: {warning}")

    # -------------------------------------------------------------------------
    def _resolve_cited_params(self, content: dict, shared_sink: Optional[list]) -> None:
        """Bring parameters cited in a control but defined outside it into scope.

        When a control cites (``{{ insert: param, X }}``) a parameter ``X`` not defined
        within it, ``X`` is also in scope: it is acquired from the import tree, this
        profile's ``set-parameters`` are applied to it, and it is included — embedded in
        the control under just-in-time access (``shared_sink`` is None) or collected for
        insertion at the resolved catalog root under :meth:`resolve` (``shared_sink`` is a
        list). A cited parameter may itself cite others, so the closure is followed.
        """
        defined = {p.get("id") for p in content.get("params", []) if isinstance(p, dict)}
        seen = set(defined)
        queue = [c for c in _cited_param_ids(content) if c not in seen]
        set_params = self._modify_index()["set_params"]
        acquired: list = []
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            param = self.get_parameter_by_id(pid)
            if param is None:
                logger.warning(f"resolve/modify: parameter '{pid}' is cited in control "
                               f"'{content.get('id')}' but could not be found in scope.")
                continue
            for setp in set_params.get(pid, []):
                for warning in _apply_one_set_parameter(param, setp):
                    logger.warning(f"modify: {warning}")
            acquired.append(param)
            for cited in _cited_param_ids(param):
                if cited not in seen:
                    queue.append(cited)
        if not acquired:
            return
        if shared_sink is not None:
            shared_sink.extend(acquired)          # resolve: hoist to catalog root
        else:
            content.setdefault("params", []).extend(acquired)   # JIT: embed in control

    # -------------------------------------------------------------------------
    def _materialize_group_node(self, node: dict, depth: Optional[int] = None) -> dict:
        """Build a full group dict (with in-scope children per ``depth``) from a node."""
        group = self._fetch_group_intrinsic(node)
        group.pop("groups", None)
        group.pop("controls", None)
        if depth != 0:
            child_depth = None if depth is None else depth - 1
            child_groups: list = []
            child_controls: list = []
            for child in node.get("children", []):
                if child.get("group"):
                    materialized = self._materialize_group_node(child, child_depth)
                    child_groups.append(materialized)
                else:
                    materialized = self._materialize_control_node(child, child_depth)
                    if materialized is not None:
                        child_controls.append(materialized)
            if child_groups:
                group["groups"] = child_groups
            if child_controls:
                group["controls"] = child_controls
        return group

    # -------------------------------------------------------------------------
    def _all_import_objects(self) -> list:
        """Return every live object reachable through the import tree (dedup by identity)."""
        seen: set[int] = set()
        out: list = []

        def visit(obj) -> None:
            if obj is None or id(obj) in seen:
                return
            seen.add(id(obj))
            out.append(obj)
            for entry in getattr(obj, "import_list", []):
                visit(entry.get("object"))

        for entry in self.import_list:
            visit(entry.get("object"))
        return out

    # -------------------------------------------------------------------------
    def _assemble_metadata(self, target: "Catalog", sources: list) -> None:
        """Populate the resolved catalog's metadata from the profile and its sources.

        Sets a fresh document uuid; title/version/oscal-version from the profile;
        ``last-modified`` as the newest across the profile and all import-tree documents;
        and carries forward (exact-deduplicated) ``links`` and ``props`` from the profile
        and its immediate source documents' metadata.
        """
        prof_meta = self._dict.get(self.model, {}).get("metadata", {})
        immediate_metas = [obj._dict.get(obj.model, {}).get("metadata", {})
                           for _imp, obj in sources]
        all_metas = [o._dict.get(o.model, {}).get("metadata", {})
                     for o in self._all_import_objects()]

        newest = _newest_timestamp(
            [prof_meta.get("last-modified")]
            + [m.get("last-modified") for m in all_metas]
        )
        oscal_version = prof_meta.get("oscal-version") or self.oscal_version.lstrip("v")

        fields: dict[str, Any] = {
            "title": prof_meta.get("title", self._profile_title()),
            "version": prof_meta.get("version", ""),
            "oscal-version": oscal_version,
        }
        if newest:
            fields["last-modified"] = newest
        target.set_metadata(fields)

        cat_root = target._dict.setdefault("catalog", {})
        cat_root["uuid"] = new_uuid()
        # Keep the instance oscal-version aligned so validation uses the right index.
        target.oscal_version = self.oscal_version

        meta_obj = cat_root.setdefault("metadata", {})
        links = _dedup_exact([ln for m in [prof_meta, *immediate_metas] for ln in m.get("links", [])])
        props = _dedup_exact([p for m in [prof_meta, *immediate_metas] for p in m.get("props", [])])
        if links:
            meta_obj["links"] = links
        if props:
            meta_obj["props"] = props

    # -------------------------------------------------------------------------
    def _carry_backmatter(self, target: "Catalog") -> None:
        """Copy back-matter resources referenced by the resolved catalog, preserving uuids.

        Scans every ``href`` of the form ``#<uuid>`` in the resolved catalog and copies
        the matching resource (by uuid) from the profile's or ANY import-tree document's
        back-matter — transitive, because a control's citation resource lives in the
        original catalog even when reached through an intermediate profile. Non-uuid
        fragment refs are ignored; uuid refs with no matching resource are warned about.
        """
        cat_root = target._dict.get("catalog", {})
        referenced: set[str] = set()

        def collect(node) -> None:
            if isinstance(node, dict):
                for key, val in node.items():
                    if key == "href" and isinstance(val, str) and val.startswith("#") \
                            and _UUID_RE.match(val[1:]):
                        referenced.add(val[1:])
                    else:
                        collect(val)
            elif isinstance(node, list):
                for item in node:
                    collect(item)

        collect(cat_root)
        if not referenced:
            return

        res_by_uuid: dict[str, dict] = {}
        holders = [self._dict.get(self.model, {})] + \
                  [o._dict.get(o.model, {}) for o in self._all_import_objects()]
        for holder in holders:
            for res in holder.get("back-matter", {}).get("resources", []):
                u = res.get("uuid")
                if u and u not in res_by_uuid:
                    res_by_uuid[u] = res

        wanted = [copy.deepcopy(res_by_uuid[u]) for u in referenced if u in res_by_uuid]
        missing = sorted(u for u in referenced if u not in res_by_uuid)
        if missing:
            logger.warning(f"resolve: {len(missing)} referenced back-matter resource(s) "
                           f"not found; e.g. {missing[:3]}.")
        if wanted:
            bm = cat_root.setdefault("back-matter", {})
            bm.setdefault("resources", []).extend(wanted)

    # -------------------------------------------------------------------------
    def _rewrite_out_of_scope_refs(self, target: "Catalog") -> None:
        """Rewrite references to out-of-scope ids to absolute source URIs.

        Any ``#id`` reference in the resolved catalog (an ``href`` value or a prose
        markdown link) whose id is not present in the resolved catalog is rewritten to
        ``<source-uri>#id``, where the source is the import that still resolves it — the
        behavior of the official resolver for controls dropped from the baseline. In-scope
        references (including carried back-matter resources) are left untouched.
        """
        cat_root = target._dict.get("catalog", {})
        in_scope: set[str] = set()
        _collect_ids(cat_root, in_scope)

        refs: set[str] = set()
        _collect_fragment_refs(cat_root, refs)
        out_of_scope = {r for r in refs if r not in in_scope}
        if not out_of_scope:
            return

        ready = [(e.get("href_valid"), e.get("object")) for e in self.import_list
                 if e.get("status") == ImportState.READY and e.get("object") is not None]
        scopes = [(href, obj.reachable_ids()) for href, obj in ready]

        base_for: dict[str, str] = {}
        for frag in out_of_scope:
            for href, ids in scopes:
                if frag in ids:
                    base_for[frag] = _as_file_uri(href)
                    break
        if base_for:
            _apply_ref_rewrite(cat_root, base_for)
            logger.info(f"resolve: rewrote {len(base_for)} out-of-scope reference(s) "
                        "to their source document.")

    # =========================================================================
    # Read-only Catalog surface (resolved -> .catalog; unresolved -> lazy from tree)
    # =========================================================================
    def get_control_by_id(self, control_id: str, depth: Optional[int] = None) -> Optional[dict]:
        """Retrieve a control as a safe copy — from the resolved catalog if resolved,
        otherwise materialized on demand from the source via the profile's controls_tree.

        Both paths return the same shape (the control with its in-scope enhancements
        nested per ``depth``, this profile's ``modify`` directives applied). When
        unresolved, the control is materialized from its origin source on each call.

        Args:
            control_id (str, required): The control id (as it appears in this profile's
                scope — a duplicate's suffixed id is valid).
            depth (int | None, optional): Enhancement depth (``None`` full).

        Returns:
            Optional[dict]: A safe copy of the control, or None when absent.
        """
        if self.resolution_status == ResolutionStatus.RESOLVED and self.catalog is not None:
            return self.catalog.get_control_by_id(control_id, depth=depth)
        self._ensure_controls_tree()
        node, ancestors = _find_control_node_with_ancestors(self.controls_tree, control_id)
        if node is None:
            return None
        return self._materialize_control_node(node, depth=depth, ancestors=ancestors)

    # -------------------------------------------------------------------------
    def get_group_by_id(self, group_id: str, depth: Optional[int] = None) -> Optional[dict]:
        """Retrieve a group as a safe copy — from the resolved catalog if resolved,
        otherwise materialized on demand from the source via the profile's controls_tree.

        Args:
            group_id (str, required): The group id (as it appears in this profile's scope).
            depth (int | None, optional): Nested group/control depth (``None`` full).

        Returns:
            Optional[dict]: A safe copy of the group, or None when absent.
        """
        if self.resolution_status == ResolutionStatus.RESOLVED and self.catalog is not None:
            return self.catalog.get_group_by_id(group_id, depth=depth)
        self._ensure_controls_tree()
        node = _find_tree_node(self.controls_tree, group_id, want_group=True)
        if node is None:
            return None
        return self._materialize_group_node(node, depth=depth)

    # -------------------------------------------------------------------------
    def get_parameter_by_id(self, param_id: str) -> Optional[dict]:
        """Return a parameter as a safe copy — from the resolved catalog if resolved,
        otherwise located in the import tree (its source, unmutated).
        """
        if self.resolution_status == ResolutionStatus.RESOLVED and self.catalog is not None:
            return self.catalog.get_parameter_by_id(param_id)
        return super().get_parameter_by_id(param_id)

    # -------------------------------------------------------------------------
    def get_control_list(self) -> list:
        """Return safe copies of every in-scope control, at all levels.

        Resolved: pass-through to :meth:`Catalog.get_control_list`. Unresolved: each
        control node in the profile's controls_tree is materialized standalone (depth 0),
        mirroring the flat, enhancement-inclusive list a catalog returns.
        """
        if self.resolution_status == ResolutionStatus.RESOLVED and self.catalog is not None:
            return self.catalog.get_control_list()
        self._ensure_controls_tree()
        out: list = []
        for node, ancestors in _all_control_nodes_with_ancestors(self.controls_tree):
            materialized = self._materialize_control_node(node, depth=0, ancestors=ancestors)
            if materialized is not None:
                out.append(materialized)
        return out

    # -------------------------------------------------------------------------
    def _resolved(self, what: str) -> bool:
        """Return True if resolved; otherwise warn about accessing ``what`` and return False."""
        if self.resolution_status != ResolutionStatus.RESOLVED or self.catalog is None:
            logger.warning(f"Attempting to access {what} before the profile is resolved; "
                           "call Profile.resolve() first.")
            return False
        return True

    # -------------------------------------------------------------------------
    def _parent_id_of(self, node_id: str) -> str:
        """Return the id of the container holding ``node_id`` in the resolved catalog.

        Yields ``"[root]"`` for a top-level node (the catalog root has no id).
        """
        container, _kind, _obj = self.catalog._find_parent_and_obj(node_id)
        if not isinstance(container, dict):
            return "[root]"
        return container.get("id") or "[root]"

    # -------------------------------------------------------------------------
    def resolve_duplicate(self, control_id: str, keep: Optional[str] = None,
                          parent_id: Optional[str] = None,
                          replacement: Optional[dict] = None) -> Optional[dict]:
        """Manually collapse duplicate instances of a control in the resolved catalog.

        Requires a resolved catalog. Merging logic is out of scope (handled by the
        caller, e.g. a GUI); this keeps, relocates, or wholesale-replaces:

          * ``replacement`` given — remove every live variant (the original id and each
            tracked ``new_id``) and insert ``replacement`` (validated) under ``parent_id``
            (or the original variant's current parent).
          * ``keep`` given (or defaulted to ``control_id``) — remove every variant except
            ``keep``; if ``parent_id`` is given, relocate the kept control there.

        Args:
            control_id (str, required): The ORIGINAL (unsuffixed) control id.
            keep (str, optional): Which variant id to retain. Defaults to ``control_id``.
            parent_id (str, optional): Where to place the survivor. Defaults to in place.
            replacement (dict, optional): A full control dict superseding all variants.

        Returns:
            Optional[dict]: A safe copy of the surviving control, or None on failure.
        """
        if not self._resolved(f"duplicate control '{control_id}'"):
            return None

        records = self.duplicates.get("controls", {}).get(control_id, [])
        variants: list[str] = []
        if self.catalog.get_control_by_id(control_id) is not None:
            variants.append(control_id)
        for rec in records:
            nid = rec.get("new_id")
            if nid and nid not in variants and self.catalog.get_control_by_id(nid) is not None:
                variants.append(nid)
        if not variants:
            logger.warning(f"resolve_duplicate: no live variants found for '{control_id}'.")
            return None

        if replacement is not None:
            if not isinstance(replacement, dict) or not replacement.get("id"):
                logger.error("resolve_duplicate: 'replacement' must be a control dict with an 'id'.")
                return None
            target_parent = parent_id if parent_id is not None else self._parent_id_of(variants[0])
            for vid in variants:
                self.catalog.remove(vid, cascade=True, ignore_references=True)
            result = self.catalog.insert_control(target_parent, replacement, validate=True)
            if result is None:
                logger.error("resolve_duplicate: replacement failed to insert; "
                             "variants were removed.")
            self.duplicates.get("controls", {}).pop(control_id, None)
            return result

        keeper = keep if keep is not None else control_id
        if keeper not in variants:
            logger.error(f"resolve_duplicate: keep id '{keeper}' is not among live "
                         f"variants {variants}.")
            return None
        for vid in variants:
            if vid != keeper:
                self.catalog.remove(vid, cascade=True, ignore_references=True)

        if parent_id is not None and self._parent_id_of(keeper) != parent_id:
            subtree = self.catalog.get_control_by_id(keeper)
            self.catalog.remove(keeper, cascade=True, ignore_references=True)
            result = self.catalog.insert_control(parent_id, subtree, validate=False)
        else:
            result = self.catalog.get_control_by_id(keeper)

        self.duplicates.get("controls", {}).pop(control_id, None)
        return result

    # -------------------------------------------------------------------------
    def resolve_duplicate_group(self, group_id: str, keep: Optional[str] = None,
                                parent_id: Optional[str] = None,
                                replacement: Optional[dict] = None) -> Optional[dict]:
        """Manually collapse duplicate instances of a group in the resolved catalog.

        The group analogue of :meth:`resolve_duplicate`. NOTE: removing a group removes
        its contained controls too (cascade), so prefer resolving duplicate *controls*
        first when both are tracked.

        Args:
            group_id (str, required): The ORIGINAL (unsuffixed) group id.
            keep (str, optional): Which variant group id to retain. Defaults to ``group_id``.
            parent_id (str, optional): Where to place the survivor. Defaults to in place.
            replacement (dict, optional): A full group dict superseding all variants.

        Returns:
            Optional[dict]: A safe copy of the surviving group, or None on failure.
        """
        if not self._resolved(f"duplicate group '{group_id}'"):
            return None

        records = self.duplicates.get("groups", {}).get(group_id, [])
        variants: list[str] = []
        if self.catalog.get_group_by_id(group_id) is not None:
            variants.append(group_id)
        for rec in records:
            nid = rec.get("new_id")
            if nid and nid not in variants and self.catalog.get_group_by_id(nid) is not None:
                variants.append(nid)
        if not variants:
            logger.warning(f"resolve_duplicate_group: no live variants found for '{group_id}'.")
            return None

        if replacement is not None:
            if not isinstance(replacement, dict) or not replacement.get("id"):
                logger.error("resolve_duplicate_group: 'replacement' must be a group dict with an 'id'.")
                return None
            target_parent = parent_id if parent_id is not None else self._parent_id_of(variants[0])
            for vid in variants:
                self.catalog.remove(vid, cascade=True, ignore_references=True)
            result = self.catalog.insert_group(target_parent, replacement,
                                                shallow=False, validate=True)
            if result is None:
                logger.error("resolve_duplicate_group: replacement failed to insert; "
                             "variants were removed.")
            self.duplicates.get("groups", {}).pop(group_id, None)
            return result

        keeper = keep if keep is not None else group_id
        if keeper not in variants:
            logger.error(f"resolve_duplicate_group: keep id '{keeper}' is not among live "
                         f"variants {variants}.")
            return None
        for vid in variants:
            if vid != keeper:
                self.catalog.remove(vid, cascade=True, ignore_references=True)

        if parent_id is not None and self._parent_id_of(keeper) != parent_id:
            subtree = self.catalog.get_group_by_id(keeper)
            self.catalog.remove(keeper, cascade=True, ignore_references=True)
            result = self.catalog.insert_group(parent_id, subtree, shallow=False, validate=False)
        else:
            result = self.catalog.get_group_by_id(keeper)

        self.duplicates.get("groups", {}).pop(group_id, None)
        return result

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class Mapping(OSCAL):
    """
    Class representing an OSCAL Mapping object.
    Inherits common OSCAL functionality and adds mapping-specific methods
    for managing mappings between controls and other objects.
    """
    def _init_common(self):
        super()._init_common()

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

class ResolutionStatus(str, Enum):
    """Lifecycle state of a Profile's control resolution.

    Members:
        UNRESOLVED (str): "unresolved" — imports have not yet been resolved.
        RESOLVING (str): "resolving" — resolution is in progress.
        RESOLVED (str): "resolved" — the resolved catalog is available.
        BLOCKED (str): "blocked" — resolution could not complete (e.g. missing import).
        EXPIRED (str): "expired" — a previously resolved catalog is stale.
    """
    UNRESOLVED   = "unresolved"
    RESOLVING    = "resolving"
    RESOLVED     = "resolved"
    BLOCKED      = "blocked"
    EXPIRED      = "expired"

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Register model classes so OSCAL factory methods return typed instances.
register_model("catalog", Catalog)
register_model("profile", Profile)
register_model("mapping-collection", Mapping)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':
    print("OSCAL Controls Class Module. This is not intended to be run as a stand-alone module.")
