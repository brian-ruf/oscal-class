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
from urllib.parse import urlparse
from dataclasses import dataclass
import logging
from datetime import datetime, timezone
from typing import Any, Optional, cast
from enum import Enum

from .oscal_content import (
    OSCAL, requires, if_update_successful, append_props, append_links, new_uuid,
    register_model, get_props, _OSCAL_NS,
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


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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
            return control

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
            return group

        except Exception as error:
            logger.error(f"Error creating group '{id}': {type(error).__name__} - {error}")
            return None

    # -------------------------------------------------------------------------
    def get_control_by_id(self, control_id: str) -> Optional[dict]:
        """Retrieve a control dict by its ID, searching all groups recursively.

        Args:
            control_id (str, required): The ``id`` of the control to find.

        Returns:
            Optional[dict]: The matching control dict, or None if not found.
        """
        return _find_control(self._catalog_root(), control_id)

    # -------------------------------------------------------------------------
    def get_group_by_id(self, group_id: str) -> Optional[dict]:
        """Retrieve a group dict by its ID, searching nested groups recursively.

        Args:
            group_id (str, required): The ``id`` of the group to find.

        Returns:
            Optional[dict]: The matching group dict, or None if not found.
        """
        return _find_group(self._catalog_root().get("groups", []), group_id)

    # -------------------------------------------------------------------------
    def get_control_list(self) -> list:
        """Return a flat list of every control dict in the catalog, at all levels.

        Returns:
            list: All control dicts found across the catalog and its groups.
        """
        return _all_controls(self._catalog_root())

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
            return part

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
        return part

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
        return obj

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
        return obj

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
    """
    Class representing an OSCAL Profile object.
    Inherits common OSCAL functionality and adds profile-specific methods
    for managing imports and control selections.
    """
    def _init_common(self):
        super()._init_common()
        self.catalog: Catalog = cast(Catalog, Catalog.new("catalog"))

        self.resolution_state = "unresolved"
        self.resolution_status = ResolutionStatus.UNRESOLVED
        self.resolved_datetime = datetime.now(timezone.utc)
        self.resolution_ttl = 0
        self.controls_tree = []

        self._build_controls_tree()

    # -------------------------------------------------------------------------
    def _build_controls_tree(self):
        """Internal method to cache the structure of controls for efficient access.
        Placeholder for caching logic.
        """

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

        logger.info(f"add_import: {status} import '{href}' as resource {resource_uuid}.")
        return ImportResult(status, entry=import_entry, resource=resource)

    # -------------------------------------------------------------------------
    def control(self, control_id: str, with_history: bool = False) -> Optional[dict]:
        """Retrieve a control by its ID from the resolved catalog.

        The profile must be resolved first; returns None with a warning otherwise.

        Args:
            control_id (str, required): The ``id`` of the control to retrieve.
            with_history (bool, optional): Reserved for including tailoring history.
                Defaults to False.

        Returns:
            Optional[dict]: The control dict, or None if unresolved or not found.
        """
        if self.resolution_status != ResolutionStatus.RESOLVED:
            logger.warning(f"Attempting to access control '{control_id}' before profile is resolved.")
            return None
        return self.catalog.get_control_by_id(control_id)

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
        return merge

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
