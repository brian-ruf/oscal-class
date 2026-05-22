"""
Functions specific to OSCAL control objects. (Catalog, Profile, and Mapping)
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
    """Class representing an editable OSCAL Catalog object.
    Inherits read-only catalog functionality from CatalogBase and adds
    methods for creating and managing controls and control groups.

    self._state:
        - "editable", "read-only", or "locked"
        - controls whether modifications are allowed
    self.control_tree:
        - A cached structure representing the hierarchy of controls and groups.
        - Contains control IDs, titles, labels, and parent-child relationships.
        - No control details are stored here.
        - Enables fast lookups without needing to query the catalog repeatedly.
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
        Creates a new control under the specified parent group.
        Parameters:
        - parent_id (str): The id of the parent group to add the control to.
        - id (str): The id of the new control.
        - title (str): The title of the new control.
        - params (list): Parameters to add to the control.
        - props (list): Properties to add to the control.
        - links (list): Links to add to the control.
        - label (str): Label prop value.
        - sort_id (str): sort-id prop value.
        - alt_identifier (str): alt-identifier prop value.
        - overview (str): Overview part prose (markdown).
        - statements (list): Statement items — strings or {'id':..., 'prose':...} dicts.
        - guidance (str): Guidance part prose (markdown).
        - example (str): Example part prose (markdown).
        - remarks (str): Remarks prose (markdown).
        Returns the new control dict, or None on failure.
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
        Creates a new catalog group.
        Parameters:
        - parent_id (str): The id of the parent group, or '[root]' for the catalog top level.
        - id (str): The id of the new group.
        - title (str): The title of the new group.
        - props (list): Properties to add to the group.
        - links (list): Links to add to the group.
        - label (str): Label prop value.
        - sort_id (str): sort-id prop value.
        - alt_identifier (str): alt-identifier prop value.
        - overview (str): Overview part prose (markdown).
        - instruction (str): Instruction part prose (markdown).
        - remarks (str): Remarks prose (markdown).
        Returns the new group dict, or None on failure.
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
        """Retrieve a control dict by its ID."""
        return _find_control(self._catalog_root(), control_id)

    # -------------------------------------------------------------------------
    def get_group_by_id(self, group_id: str) -> Optional[dict]:
        """Retrieve a group dict by its ID."""
        return _find_group(self._catalog_root().get("groups", []), group_id)

    # -------------------------------------------------------------------------
    def get_control_list(self) -> list:
        """Return a flat list of all control dicts in the catalog."""
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
        """Retrieve a control by its ID from the resolved catalog."""
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
    UNRESOLVED   = "unresolved"
    RESOLVING    = "resolving"
    RESOLVED     = "resolved"
    BLOCKED      = "blocked"
    EXPIRED      = "expired"

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == '__main__':
    print("OSCAL Controls Class Module. This is not intended to be run as a stand-alone module.")
