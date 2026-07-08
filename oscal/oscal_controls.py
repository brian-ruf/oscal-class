"""
oscal_controls — OSCAL control-layer model classes.

Provides the editable model classes for the OSCAL control models: ``Catalog``
(defines controls), ``Profile`` (selects and tailors controls into baselines),
and ``Mapping`` (relates controls across frameworks). Each class subclasses
``OSCAL`` from ``oscal_content`` and adds model-specific navigation and
mutation helpers.

Module constants:
    (none exported)
"""
from loguru import logger
from datetime import datetime, timezone
from typing import Any, Optional, cast
from enum import Enum

from .oscal_content import OSCAL, requires, if_update_successful, append_props, append_links

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Dict navigation helpers
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def _find_group(groups: list, group_id: str) -> Optional[dict]:
    """Recursively find a group dict by id within a list of groups."""
    for g in groups or []:
        if g.get("id") == group_id:
            return g
        found = _find_group(g.get("groups", []), group_id)
        if found is not None:
            return found
    return None


def _find_control(container: dict, control_id: str) -> Optional[dict]:
    """Recursively find a control dict by id within a catalog or group dict."""
    for ctrl in container.get("controls", []):
        if ctrl.get("id") == control_id:
            return ctrl
    for grp in container.get("groups", []):
        found = _find_control(grp, control_id)
        if found is not None:
            return found
    return None


def _all_controls(container: dict) -> list:
    """Recursively collect all control dicts from a catalog or group dict."""
    result = []
    for ctrl in container.get("controls", []):
        result.append(ctrl)
    for grp in container.get("groups", []):
        result.extend(_all_controls(grp))
    return result


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class Catalog(OSCAL):
    """Editable OSCAL Catalog model.

    Subclasses ``OSCAL`` and adds methods for creating and navigating controls
    and control groups. Read-only guards apply to mutation methods when the
    instance state is not editable.
    """
    def _init_common(self):
        super()._init_common()

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
        Create a new control under the specified parent group.

        Args:
            parent_id (str, required): ID of the parent group to add the control to.
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
        """
        logger.info(f"Creating new control '{id}' under parent group '{parent_id}'")
        try:
            parent = _find_group(self._catalog_root().get("groups", []), parent_id)
            if parent is None:
                logger.warning(f"CREATE CONTROL: Unable to find parent group with id '{parent_id}'")
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
                empty string) for the catalog top level.
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
                self._catalog_root().setdefault("groups", []).append(group)
            else:
                parent = _find_group(self._catalog_root().get("groups", []), parent_id)
                if parent is None:
                    logger.warning(f"CREATE GROUP: Unable to find parent group with id '{parent_id}'")
                    return None
                parent.setdefault("groups", []).append(group)

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

    def _build_controls_tree(self):
        """Internal method to cache the structure of controls for efficient access.
        Placeholder for caching logic.
        """

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
if __name__ == '__main__':
    print("OSCAL Controls Class Module. This is not intended to be run as a stand-alone module.")
