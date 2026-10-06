"""
oscal_implementation — OSCAL implementation-layer model classes and helpers.

Provides the model classes for the OSCAL implementation models:
``ComponentDefinition`` (reusable control implementations for components) and
``SSP`` (System Security Plan). Both subclass ``OSCAL`` from ``oscal_content``.

Both models expose:
    * an ``implementation_tree`` attribute — a lightweight, UI-oriented view rebuilt on
      validation / mutation / import changes. A cDef's has a single ``components`` key;
      an SSP's adds ``leveraged-authorizations`` and ``controls`` (the imported profile's
      ``controls_tree``).
    * a ``component(uuid)`` getter returning a safe copy of the component annotated with
      resolved responsibilities (role titles + full party objects) and a ``relationships``
      object (forward relationship links plus the reverse relationships discovered by
      scanning every component in scope). ``ComponentDefinition`` adds a ``capability(uuid)``
      getter and ``incorporates-components`` resolution; ``SSP`` adds ``implemented-controls``.

Module-level helpers shared by both classes build the responsible-role annotation
(:func:`_enrich_responsibilities`) and the relationships object
(:func:`_build_component_relationships`). Others build the nested SSP assemblies
(components, implemented requirements, by-component statements, responsible roles) and
are also exposed as ``SSP`` methods where appropriate.

Module constants:
    (none exported; ``_REVERSE_REL_KEY`` / ``_RELATIONSHIP_KEYS`` are private and define
    the known component-relationship ``rel`` values and their reverse-array keys.)
"""
from __future__ import annotations
import copy
import logging
from typing import Any, Optional

from .oscal_content import (OSCAL, requires, if_update_successful, new_uuid, append_props,
                            append_links, register_model, get_props, ImportState,
                            _find_import_candidates)
from .oscal_controls import _apply_set_parameters_to_control

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The ``role-id`` / ``party-uuids`` responsibility construct appears under these keys
# across models — ``responsible-roles`` (on components, capabilities,
# implemented-requirements, statements, by-components, …) and ``responsible-parties`` (on
# inventory-items, metadata, …). Both share the same shape: a ``role-id``, a
# ``party-uuids`` array, plus ``props``/``links``/``remarks``. New models that reuse the
# construct are picked up automatically by the recursive walk in
# :func:`_enrich_responsibilities`.
_RESPONSIBILITY_KEYS = ("responsible-roles", "responsible-parties")


def _resolve_responsibility_entry(doc: OSCAL, entry: dict) -> None:
    """Resolve one responsible-role / responsible-party entry, in place.

    Inserts, as siblings of the lookup fields:

    * ``title`` — the ``metadata.roles`` title for this entry's ``role-id``; and
    * ``parties`` — the full ``metadata.parties`` object (``type``, ``name``,
      ``short-name``, …) for each uuid in ``party-uuids``.

    Both lookups use the in-scope cascade (:meth:`OSCAL.get_role_by_id` /
    :meth:`OSCAL.get_party_by_uuid`): the current document first, then its imported
    documents, so a role or party defined upstream still resolves. An unresolved ``role-id``
    yields an empty ``title``; an unresolved party uuid yields a ``parties`` entry carrying
    only its ``uuid``. ``props``/``links``/``remarks`` are left untouched.
    """
    if not isinstance(entry, dict):
        return
    role_id = entry.get("role-id", "")
    if role_id:
        meta_role = doc.get_role_by_id(role_id)
        entry["title"] = meta_role.get("title", "") if meta_role is not None else ""
    party_uuids = entry.get("party-uuids")
    if party_uuids:
        parties = []
        for party_uuid in party_uuids:
            party = doc.get_party_by_uuid(party_uuid)
            if party is not None:
                resolved = copy.deepcopy(party)
                resolved.setdefault("uuid", party_uuid)
                parties.append(resolved)
            else:
                parties.append({"uuid": party_uuid})
        entry["parties"] = parties


def _enrich_responsibilities(doc: OSCAL, obj: Any) -> Any:
    """Recursively resolve the responsibility construct anywhere within *obj*.

    Walks *obj* and, at every depth, annotates each ``responsible-roles`` /
    ``responsible-parties`` entry via :func:`_resolve_responsibility_entry` (role ``title``
    + full ``parties`` objects). Walking the whole result applies the same enrichment
    uniformly wherever the construct nests — a component, a capability, an
    implemented-requirement, a statement, a by-component, an inventory-item — and to any
    future model that reuses it, without each getter having to know where it lives.

    Mutates *obj* in place (callers pass a safe copy) and returns it.
    """
    if isinstance(obj, dict):
        for key in _RESPONSIBILITY_KEYS:
            for entry in obj.get(key, []) or []:
                _resolve_responsibility_entry(doc, entry)
        for value in obj.values():
            _enrich_responsibilities(doc, value)
    elif isinstance(obj, list):
        for item in obj:
            _enrich_responsibilities(doc, item)
    return obj


# ``rel`` values on a component ``link`` that convey a component-to-component
# relationship: the link's href is a URI fragment (``#<uuid>``) naming another
# component. Each maps to the key used for the *reverse* relationship — the array
# that surfaces on the cited component. This map is the single source of truth for
# the known relationship rels and grows over time; every member is handled
# identically. (Note ``used-by`` is both a forward rel — reverse ``uses`` — and the
# reverse key of ``uses-service``/``uses-network``; both meanings coincide.)
_REVERSE_REL_KEY = {
    "depends-on":   "dependents",
    "validation":   "validates",
    "uses-service": "used-by",
    "uses-network": "used-by",
    "provided-by":  "provides",
    "used-by":      "uses",
}

# Every array key emitted under ``relationships``: the forward rels plus the reverse
# keys (deduplicated, forward order first). Always all present, empty when unused.
_RELATIONSHIP_KEYS = tuple(dict.fromkeys(
    tuple(_REVERSE_REL_KEY) + tuple(_REVERSE_REL_KEY.values())
))


def _build_component_relationships(obj: dict, tree_by_uuid: dict,
                                   all_components: list, self_uuid: str) -> dict:
    """Build the ``relationships`` object for a component: forward and reverse links.

    Every key in :data:`_RELATIONSHIP_KEYS` is present, mapping to an array (empty when
    unused). Each entry is ``{"uuid", "title", "type"}`` plus ``asset-type`` when the
    referenced component's tree node carries a non-empty one, resolved from
    *tree_by_uuid* (the flat cDef / SSP ``implementation_tree['components']`` indexed by
    uuid). An unresolved reference still yields an entry with empty ``title``/``type``.
    Within a given array a component appears at most once.

    Forward: for each of *obj*'s own ``links`` whose ``rel`` is a known relationship type
    and whose ``href`` is ``#<uuid>``, the cited target is added under ``rel``.

    Reverse: every component in *all_components* (this component's whole scope — for a
    cDef that spans the import tree) is scanned for a relationship link citing
    ``#self_uuid``; the citing component is added under the reverse key of that rel
    (e.g. another component's ``depends-on`` puts it in this component's ``dependents``).

    Args:
        obj (dict, required): The component dict holding ``links``.
        tree_by_uuid (dict, required): uuid -> tree node ({uuid, title, type, asset-type?}).
        all_components (list, required): Every component/capability dict in scope (with links).
        self_uuid (str, required): The uuid of the component being described.

    Returns:
        dict: ``{key: [entry, ...]}`` for every key in :data:`_RELATIONSHIP_KEYS`.
    """
    relationships: dict[str, list] = {key: [] for key in _RELATIONSHIP_KEYS}
    seen: dict[str, set] = {key: set() for key in _RELATIONSHIP_KEYS}

    def _add(key: str, ref_uuid: str) -> None:
        if ref_uuid in seen[key]:
            return
        seen[key].add(ref_uuid)
        node = tree_by_uuid.get(ref_uuid)
        entry = {
            "uuid":  ref_uuid,
            "title": node.get("title", "") if node else "",
            "type":  node.get("type", "") if node else "",
        }
        asset_type = node.get("asset-type") if node else ""
        if asset_type:
            entry["asset-type"] = asset_type
        relationships[key].append(entry)

    # Forward: this component's own relationship links.
    for link in obj.get("links", []) or []:
        rel = link.get("rel", "")
        href = str(link.get("href", ""))
        if rel in _REVERSE_REL_KEY and href.startswith("#"):
            _add(rel, href[1:])

    # Reverse: any other component citing this one via a relationship link.
    fragment = "#" + self_uuid
    for other in all_components:
        other_uuid = other.get("uuid", "")
        if other_uuid == self_uuid:
            continue
        for link in other.get("links", []) or []:
            rel = link.get("rel", "")
            if rel in _REVERSE_REL_KEY and str(link.get("href", "")) == fragment:
                _add(_REVERSE_REL_KEY[rel], other_uuid)
    return relationships


def _index_controls_tree(controls_tree: list) -> dict:
    """Flatten a catalog/profile ``controls_tree`` into ``{id: node}`` for fast lookup.

    Indexes every node (groups and controls, at all depths) by its ``id`` so a
    ``control-id`` can be resolved to its lightweight ``{id, label, title, ...}`` node
    without walking or materializing the whole document. Built once per source and reused.
    """
    index: dict[str, dict] = {}

    def _walk(nodes: list) -> None:
        for node in nodes or []:
            node_id = node.get("id")
            if node_id and node_id not in index:
                index[node_id] = node
            _walk(node.get("children", []))

    _walk(controls_tree)
    return index


def _overlay_implemented(nodes: list, impl_by_id: dict) -> None:
    """Overlay SSP implementation onto a (copied) ``controls_tree``, in place.

    For every control node (``group`` is false), set ``implemented`` (True when an
    implemented-requirement cites its ``id``) and, when implemented, the requirement's
    ``implemented-requirement-uuid`` so a UI can drill in via :meth:`SSP.control`. Group
    nodes are left unmarked. Recurses control enhancements. *impl_by_id* maps control-id to
    the first implementing requirement.
    """
    for node in nodes or []:
        if not node.get("group"):
            req = impl_by_id.get(node.get("id"))
            node["implemented"] = req is not None
            if req is not None:
                node["implemented-requirement-uuid"] = req.get("uuid", "")
        _overlay_implemented(node.get("children", []) or [], impl_by_id)


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class ComponentDefinition(OSCAL):
    """OSCAL Component Definition (cDef) model.

    Represents reusable component definitions that describe how components
    satisfy controls. Subclasses ``OSCAL``.

    Attributes:
        implementation_tree (dict): A lightweight, UI-oriented view of the component
            definition. Currently a single array-valued key:

            * ``components`` — a flat list of nodes, one per defined component, one per
              capability, followed by the nodes contributed by each imported component
              definition's own ``implementation_tree['components']`` (no import-driven
              nesting). Each node is
              ``{"uuid", "title", "type", "asset-type", "incorporates"}`` where:

              - ``type`` is the defined-component's ``type`` flag, or the literal
                ``"capability"`` for a capability.
              - ``title`` is the component's ``title`` (a capability's ``name``).
              - ``asset-type`` is the value of the ``asset-type`` prop in the OSCAL
                default namespace when present, else ``""``. Checked on both components
                and capabilities (capabilities have no such prop today, but may gain one).
              - ``incorporates`` lists ``{"uuid", "description"}`` for each entry in an
                ``incorporates-components`` collection, when present, else ``[]``.

            The ``components`` key is intentionally named to align with
            :attr:`SSP.implementation_tree`; an SSP's tree adds further top-level keys
            (``leveraged-authorizations``, ``controls``) that have no cDef equivalent.
            Built when the content is valid OSCAL and refreshed on validation and
            whenever the import set changes. See :meth:`_build_implementation_tree`.
    """
    def _init_common(self):
        """Initialize cDef-specific state, then build ``implementation_tree`` if valid."""
        super()._init_common()
        self.implementation_tree: dict[str, list] = {"components": []}
        if self.is_minimally_valid:
            self._build_implementation_tree()

    # -------------------------------------------------------------------------
    def validate(self, format: str = "") -> bool:
        """Validate the component definition, then (re)build ``implementation_tree``.

        OSCAL content is validated at load; the tree is built only when the content is
        valid (an invalid cDef exposes no navigable summary and the tree is emptied). The
        tree itself is a lightweight, OSCAL-aligned **summary** — it is never itself an
        OSCAL-valid document.

        Args:
            format (str, optional): Accepted for API compatibility with the base
                method; does not alter the validation path.

        Returns:
            bool: True when every validation phase passes.
        """
        result = super().validate(format=format)
        if self.is_minimally_valid:
            self._build_implementation_tree()
        else:
            self.implementation_tree = {"components": []}
        return result

    # -------------------------------------------------------------------------
    def _after_imports_changed(self) -> None:
        """Rebuild ``implementation_tree`` after an import was added or removed.

        Extends the base refresh so imported component definitions' nodes are re-merged
        into (or dropped from) this cDef's flat ``components`` list.
        """
        super()._after_imports_changed()
        if self.is_minimally_valid:
            self._build_implementation_tree()

    # -------------------------------------------------------------------------
    def _cdef_root(self) -> dict[str, Any]:
        """Return the component-definition root dict from _dict."""
        if not isinstance(self._dict, dict):
            return {}
        cdef = self._dict.get("component-definition")
        return cdef if isinstance(cdef, dict) else {}

    # -------------------------------------------------------------------------
    def _component_node(self, obj: dict, title: str, node_type: str,
                        source_index_cache: Optional[dict] = None) -> dict[str, Any]:
        """Build a single ``implementation_tree['components']`` node for a component or capability.

        Args:
            obj (dict, required): The component or capability dict to describe.
            title (str, required): The node title (a component's ``title`` or a
                capability's ``name``).
            node_type (str, required): The node ``type`` (a component's ``type`` flag
                or the literal ``"capability"``).
            source_index_cache (dict, optional): Shared cache of per-source
                ``controls_tree`` indexes, threaded through a whole tree build so each
                control-implementation ``source`` is indexed at most once.

        Returns:
            dict: A node ``{"uuid", "title", "type", "asset-type", "incorporates",
                "children"}``, where ``children`` holds this component/capability's
                control-implementation subtree (empty when it has none).
        """
        asset_props = get_props(obj, name="asset-type")
        asset_type = asset_props[0].get("value", "") if asset_props else ""

        incorporates: list[dict[str, Any]] = []
        for inc in obj.get("incorporates-components", []) or []:
            incorporates.append({
                "uuid":        inc.get("component-uuid", ""),
                "description": inc.get("description", ""),
            })

        return {
            "uuid":       obj.get("uuid", ""),
            "title":      title,
            "type":       node_type,
            "asset-type": asset_type,
            "incorporates": incorporates,
            "children":   self._control_implementation_nodes(
                obj, source_index_cache if source_index_cache is not None else {}),
        }

    # -------------------------------------------------------------------------
    def _control_implementation_nodes(self, obj: dict, source_index_cache: dict) -> list:
        """Build the control-implementation child nodes for a component/capability tree node.

        One child per ``control-implementations`` entry, carrying only ``uuid`` and
        ``source`` plus the source's resolved ``title`` / ``version`` / ``published``
        (from the import tree — :meth:`_control_implementation_source`); an unresolvable
        source (missing, or not a catalog/profile) yields ``title`` ``"**Import Error**"``
        and no version/published. Each control-implementation node's own ``children`` are
        one node per ``implemented-requirement``, carrying its ``control-id`` plus the
        control's ``label`` and ``title`` looked up in the source's ``controls_tree``
        index (never materializing the full control). ``source_index_cache`` (keyed by
        source object id) ensures each source is indexed once per build.
        """
        nodes: list[dict[str, Any]] = []
        for ci in obj.get("control-implementations", []) or []:
            source = ci.get("source", "")
            source_obj = self._control_implementation_source(source)
            node: dict[str, Any] = {"uuid": ci.get("uuid", ""), "source": source}

            if source_obj is None:
                node["title"] = "**Import Error**"
                index: dict = {}
            else:
                node["title"]     = source_obj.title
                node["version"]   = source_obj.version
                node["published"] = source_obj.published
                index = source_index_cache.get(id(source_obj))
                if index is None:
                    index = _index_controls_tree(source_obj.controls_tree)
                    source_index_cache[id(source_obj)] = index

            requirements: list[dict[str, Any]] = []
            for req in ci.get("implemented-requirements", []) or []:
                control_id = req.get("control-id", "")
                ctl = index.get(control_id)
                requirements.append({
                    "control-id": control_id,
                    "label": ctl.get("label", "") if ctl else "",
                    "title": ctl.get("title", "") if ctl else "",
                })
            node["children"] = requirements
            nodes.append(node)
        return nodes

    # -------------------------------------------------------------------------
    def _imported_cdef_sources(self) -> list["ComponentDefinition"]:
        """Return the resolved component-definition objects this cDef imports.

        Correlates each ``import-component-definition`` href with its resolved entry in
        :attr:`import_list`, keeping only READY entries whose live object is itself a
        ComponentDefinition. Entries loaded for ``control-implementation`` sources
        (catalogs/profiles) are excluded because they are not matched by an
        import-component-definition href.
        """
        root = self._cdef_root()
        imports = root.get("import-component-definitions", []) or []
        if not imports:
            return []
        if not self.imports_resolved:
            try:
                self.resolve_imports()
            except Exception as error:  # best-effort: unresolved imports contribute nothing
                logger.debug(f"implementation_tree: import resolution deferred ({error}).")

        by_href: dict[Any, dict] = {}
        for entry in self.import_list:
            by_href.setdefault(entry.get("href_original"), entry)

        sources: list[ComponentDefinition] = []
        for idx, imp in enumerate(imports):
            if not isinstance(imp, dict):
                continue
            href = str(imp.get("href", ""))
            entry = by_href.get(href)
            obj = entry.get("object") if entry else None
            status = entry.get("status") if entry else None
            if obj is None or status != ImportState.READY or not isinstance(obj, ComponentDefinition):
                logger.warning(f"implementation_tree: import {idx} ('{href}') not resolved "
                               f"(status={status}); excluded.")
                continue
            sources.append(obj)
        return sources

    # -------------------------------------------------------------------------
    def _build_implementation_tree(self) -> dict[str, list]:
        """(Re)build ``implementation_tree`` — its ``components`` list and their subtrees.

        The ``components`` list holds ``{"uuid", "title", "type", "asset-type",
        "incorporates", "children"}`` nodes: one per defined component, one per capability
        (with ``type`` ``"capability"``), followed by the nodes contributed by each
        imported component definition's own ``implementation_tree['components']``. Each
        node's ``children`` are its control-implementation subtree (control-implementation
        → implemented-requirement nodes; see :meth:`_control_implementation_nodes`).
        Rebuilt from the current ``_dict`` on each call and stored on
        ``self.implementation_tree``.

        Returns:
            dict: The freshly built ``implementation_tree``.
        """
        root = self._cdef_root()
        source_index_cache: dict = {}   # source object id -> its controls_tree index (built once)
        components: list[dict[str, Any]] = []
        for comp in root.get("components", []) or []:
            components.append(self._component_node(
                comp, comp.get("title", ""), comp.get("type", ""), source_index_cache))
        for cap in root.get("capabilities", []) or []:
            components.append(self._component_node(
                cap, cap.get("name", ""), "capability", source_index_cache))
        for source in self._imported_cdef_sources():
            components.extend(copy.deepcopy(source.implementation_tree.get("components", []) or []))
        self.implementation_tree = {"components": components}
        return self.implementation_tree

    # -------------------------------------------------------------------------
    def _all_component_objects(self, _seen: Optional[set] = None) -> list[dict]:
        """Every defined-component and capability dict in scope, with their links.

        Spans this cDef plus every component definition reachable through the import
        tree (depth-first, cycle-guarded), so reverse-relationship discovery in
        :func:`_build_component_relationships` sees the whole graph. Returns live dicts
        (not copies) — used read-only for their ``links``.
        """
        if _seen is None:
            _seen = set()
        if id(self) in _seen:
            return []
        _seen.add(id(self))
        root = self._cdef_root()
        objects = list(root.get("components", []) or []) + list(root.get("capabilities", []) or [])
        for source in self._imported_cdef_sources():
            objects.extend(source._all_component_objects(_seen))
        return objects

    # -------------------------------------------------------------------------
    def _enrich_incorporates(self, obj: dict) -> dict:
        """Resolve an object's ``incorporates-components`` refs against the components tree.

        For every entry in the object's ``incorporates-components`` (when present), the
        referenced ``component-uuid`` is looked up in
        ``implementation_tree['components']`` (which is flat and includes imported
        components). On a hit, the entry gains the referenced node's ``title``, ``type``
        and ``asset-type`` plus ``found=True``. On a miss, the entry gains only
        ``found=False`` and its existing keys (``component-uuid``, ``description``) are
        left untouched. Mutates ``obj`` in place and returns it — callers pass a safe
        copy, so stored content is never altered.

        Args:
            obj (dict, required): A defined-component or capability dict (a copy).

        Returns:
            dict: The same ``obj``, with its incorporates entries annotated.
        """
        tree_by_uuid = {n.get("uuid"): n for n in self.implementation_tree["components"]}
        for entry in obj.get("incorporates-components", []) or []:
            node = tree_by_uuid.get(entry.get("component-uuid"))
            if node is None:
                entry["found"] = False
            else:
                entry["title"]      = node.get("title", "")
                entry["type"]       = node.get("type", "")
                entry["asset-type"] = node.get("asset-type", "")
                entry["found"]      = True
        return obj

    # -------------------------------------------------------------------------
    def _control_implementation_source(self, source_href: str) -> Optional[OSCAL]:
        """The loaded catalog/profile behind a control-implementation ``source``, or None.

        Resolves *source_href* through this cDef's import tree (resolving imports first
        when needed). Returns None when the source is blank, is not present in the import
        tree, did not load (not READY), or resolved to anything other than a ``catalog``
        or ``profile``.
        """
        if not source_href:
            return None
        if not self.imports_resolved:
            try:
                self.resolve_imports()
            except Exception as error:  # best-effort: an unresolved source yields None
                logger.debug(f"control-implementations: import resolution deferred ({error}).")
        # A source cited by more than one control-implementation appears multiple times in
        # import_list — once READY, the rest DUPLICATE (object=None). Take the first READY
        # candidate that loaded to a catalog/profile.
        for entry in _find_import_candidates(self.import_list, source_href):
            obj = entry.get("object")
            if (entry.get("status") == ImportState.READY and obj is not None
                    and getattr(obj, "model", None) in ("catalog", "profile")):
                return obj
        return None

    # -------------------------------------------------------------------------
    def _summarize_control_implementations(self, obj: dict) -> dict:
        """Summarize each ``control-implementations`` entry on a component/capability copy.

        For every control-implementation (when the array is present): the ``source``'s
        ``title`` / ``version`` / ``published`` are inserted, or ``title`` is set to
        ``"**Import Error**"`` when the source is not a resolvable catalog/profile (see
        :meth:`_control_implementation_source`). An ``implemented-requirements-count`` is
        inserted, then the heavyweight ``set-parameters`` and ``implemented-requirements``
        keys are dropped. Mutates ``obj`` in place (a safe copy) and returns it.
        """
        for ci in obj.get("control-implementations", []) or []:
            source_obj = self._control_implementation_source(ci.get("source", ""))
            if source_obj is None:
                ci["title"] = "**Import Error**"
            else:
                ci["title"]     = source_obj.title
                ci["version"]   = source_obj.version
                ci["published"] = source_obj.published
            ci["implemented-requirements-count"] = len(ci.get("implemented-requirements", []) or [])
            ci.pop("set-parameters", None)
            ci.pop("implemented-requirements", None)
        return obj

    # -------------------------------------------------------------------------
    def component(self, uuid: str) -> Optional[dict]:
        """Retrieve a defined component by its ``uuid``, as a safe copy.

        Any ``incorporates-components`` entries on the component are annotated against
        ``implementation_tree['components']`` — see :meth:`_enrich_incorporates`. Any
        ``responsible-roles`` are annotated with the resolved role ``title`` and a
        ``parties`` array of full metadata party objects — see
        :func:`_enrich_responsibilities`. A ``relationships`` object is inserted holding
        both this component's forward relationship links and the reverse relationships
        discovered by scanning every component in scope (the whole import tree) — see
        :func:`_build_component_relationships`. Any ``control-implementations`` are
        summarized (source title/version/date, requirement count, heavy keys dropped) —
        see :meth:`_summarize_control_implementations`.

        Args:
            uuid (str, required): The ``uuid`` of the defined component to retrieve.

        Returns:
            Optional[dict]: A safe copy of the component (incorporates, responsible-roles,
                relationships and control-implementations annotated), or None when no
                component has that uuid.
        """
        for comp in self._cdef_root().get("components", []) or []:
            if comp.get("uuid") == uuid:
                result = self._enrich_incorporates(copy.deepcopy(comp))
                result = _enrich_responsibilities(self, result)
                tree_by_uuid = {n.get("uuid"): n for n in self.implementation_tree["components"]}
                result["relationships"] = _build_component_relationships(
                    result, tree_by_uuid, self._all_component_objects(), uuid)
                self._summarize_control_implementations(result)
                return result
        return None

    # -------------------------------------------------------------------------
    def capability(self, uuid: str) -> Optional[dict]:
        """Retrieve a capability by its ``uuid``, as a safe copy.

        Any ``incorporates-components`` entries on the capability are annotated against
        ``implementation_tree['components']`` — see :meth:`_enrich_incorporates`. Any
        ``responsible-roles`` are annotated with the resolved role ``title`` and a
        ``parties`` array of full metadata party objects — see
        :func:`_enrich_responsibilities`. Any ``control-implementations`` are summarized
        (source title/version/date, requirement count, heavy keys dropped) — see
        :meth:`_summarize_control_implementations`.

        Args:
            uuid (str, required): The ``uuid`` of the capability to retrieve.

        Returns:
            Optional[dict]: A safe copy of the capability (incorporates, responsible-roles
                and control-implementations annotated), or None when no capability has that uuid.
        """
        for cap in self._cdef_root().get("capabilities", []) or []:
            if cap.get("uuid") == uuid:
                result = self._enrich_incorporates(copy.deepcopy(cap))
                _enrich_responsibilities(self, result)
                self._summarize_control_implementations(result)
                return result
        return None

    # -------------------------------------------------------------------------
    def control_implementation(self, uuid: str) -> Optional[dict]:
        """Retrieve a ``control-implementation`` by its ``uuid``, as a safe copy.

        Searches every component and capability in this cDef for a control-implementation
        with the given ``uuid``. All of its ``implemented-requirements`` reference controls
        from the same ``source`` catalog/profile, so that source is resolved once (through
        the import tree — see :meth:`_control_implementation_source`) and reused: for each
        implemented-requirement, the control named by ``control-id`` is fetched **without
        children** (``depth=0``) and inserted under a ``control`` key (``None`` when the
        source is not a resolvable catalog/profile or the control is not found).

        Unlike :meth:`component`/:meth:`capability` (which drop them), this getter keeps
        the ``implemented-requirements`` and ``set-parameters`` intact and augments each
        requirement with its ``control``. Any ``responsible-roles`` on the requirements
        (and nested statements/by-components) are resolved with the role ``title`` and a
        ``parties`` array of full metadata party objects — see
        :func:`_enrich_responsibilities`.

        Args:
            uuid (str, required): The ``uuid`` of the control-implementation.

        Returns:
            Optional[dict]: A safe copy of the control-implementation with each
                implemented-requirement's ``control`` inserted, or None when no
                control-implementation has that uuid.
        """
        root = self._cdef_root()
        holders = (root.get("components", []) or []) + (root.get("capabilities", []) or [])
        for holder in holders:
            for ci in holder.get("control-implementations", []) or []:
                if ci.get("uuid") == uuid:
                    result = copy.deepcopy(ci)
                    # implemented-requirements (and any nested statements/by-components)
                    # carry the responsibility construct — enrich before the catalog
                    # controls are attached below (they have no such construct).
                    _enrich_responsibilities(self, result)
                    source_obj = self._control_implementation_source(result.get("source", ""))
                    for req in result.get("implemented-requirements", []) or []:
                        control_id = req.get("control-id", "")
                        req["control"] = (
                            source_obj.get_control_by_id(control_id, depth=0)
                            if source_obj is not None and control_id else None
                        )
                    return result
        return None

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class SSP(OSCAL):
    """OSCAL System Security Plan (SSP) model.

    Subclasses ``OSCAL`` and adds SSP-specific methods for managing system
    components, implemented requirements, and by-component statements.

    Attributes:
        implementation_tree (dict): A lightweight, UI-oriented view of the SSP's
            implementation surface with three array-valued keys:

            * ``leveraged-authorizations`` — one ``{"uuid", "title"}`` per entry in
              ``system-implementation.leveraged-authorizations``.
            * ``components`` — one node per ``system-implementation.components`` entry:
              ``{"uuid", "title", "type"}`` plus ``asset-type`` (the value of the
              ``asset-type`` prop in the OSCAL default namespace) only when that prop
              is present.
            * ``controls`` — one ``{"control-id", "label", "title"}`` node per
              ``control-implementation.implemented-requirements`` entry (the controls this
              SSP implements), with label/title resolved from the imported profile's
              ``controls_tree`` (empty when the import-profile is absent/unresolved or the
              control-id is not found). Unlike a component-definition, an SSP's
              implemented-requirements live at the root ``control-implementation``.

            All three keys are always present (empty lists by default). Built when the
            SSP is valid OSCAL and refreshed on validation, content mutation, and import
            changes. See :meth:`_build_implementation_tree`.
    """
    def _init_common(self):
        """Initialize SSP-specific state, then build ``implementation_tree`` if valid."""
        super()._init_common()
        self.implementation_tree: dict[str, list] = {
            "leveraged-authorizations": [],
            "components": [],
            "controls": [],
        }
        if self.is_minimally_valid:
            self._build_implementation_tree()

    def _ssp_root(self) -> dict[str, Any]:
        if not isinstance(self._dict, dict):
            return {}
        ssp = self._dict.get("system-security-plan")
        return ssp if isinstance(ssp, dict) else {}

    # -------------------------------------------------------------------------
    def validate(self, format: str = "") -> bool:
        """Validate the SSP, then (re)build ``implementation_tree`` on success.

        Extends :meth:`OSCAL.validate` so the view is refreshed the moment the content
        is found to be valid OSCAL; an invalid SSP exposes an empty tree.

        Args:
            format (str, optional): Accepted for API compatibility with the base
                method; does not alter the validation path.

        Returns:
            bool: True when every validation phase passes.
        """
        result = super().validate(format=format)
        if self.is_minimally_valid:
            self._build_implementation_tree()
        else:
            self.implementation_tree = {
                "leveraged-authorizations": [],
                "components": [],
                "controls": [],
            }
        return result

    # -------------------------------------------------------------------------
    def _on_content_mutated(self) -> None:
        """Rebuild ``implementation_tree`` after any content edit.

        Chains to the base hook (revision stamp) then refreshes the view so edits to
        ``system-implementation`` (components, leveraged authorizations) are reflected.
        """
        super()._on_content_mutated()
        if self.is_minimally_valid:
            self._build_implementation_tree()

    # -------------------------------------------------------------------------
    def _after_imports_changed(self) -> None:
        """Rebuild ``implementation_tree`` after the import-profile set changes."""
        super()._after_imports_changed()
        if self.is_minimally_valid:
            self._build_implementation_tree()

    # -------------------------------------------------------------------------
    def _imported_profile(self) -> Optional[OSCAL]:
        """Return the resolved object behind ``import-profile``, or None.

        Matches ``import-profile/@href`` against :attr:`import_list`, keeping a READY
        entry whose live object exposes a ``controls_tree`` (a Profile — or a Catalog
        imported directly). Resolves imports first when they have not been resolved yet.
        """
        root = self._ssp_root()
        imp = root.get("import-profile")
        if not isinstance(imp, dict) or not imp.get("href"):
            return None
        if not self.imports_resolved:
            try:
                self.resolve_imports()
            except Exception as error:  # best-effort: an unresolved import yields no controls
                logger.debug(f"implementation_tree: import resolution deferred ({error}).")

        href = str(imp.get("href", ""))
        for entry in self.import_list:
            if entry.get("href_original") != href:
                continue
            obj = entry.get("object")
            status = entry.get("status")
            if obj is not None and status == ImportState.READY and hasattr(obj, "controls_tree"):
                return obj
            logger.warning(f"implementation_tree: import-profile ('{href}') not resolved "
                           f"(status={status}); controls left empty.")
            return None
        return None

    # -------------------------------------------------------------------------
    def _build_implementation_tree(self) -> dict[str, list]:
        """(Re)build ``implementation_tree`` from the current ``_dict`` and imports.

        Returns:
            dict: The freshly built ``implementation_tree``.
        """
        root = self._ssp_root()
        sys_impl = root.get("system-implementation", {}) or {}

        leveraged = [
            {"uuid": la.get("uuid", ""), "title": la.get("title", "")}
            for la in sys_impl.get("leveraged-authorizations", []) or []
        ]

        components: list[dict[str, Any]] = []
        for comp in sys_impl.get("components", []) or []:
            node: dict[str, Any] = {
                "uuid":  comp.get("uuid", ""),
                "title": comp.get("title", ""),
                "type":  comp.get("type", ""),
            }
            asset_props = get_props(comp, name="asset-type")
            if asset_props:
                node["asset-type"] = asset_props[0].get("value", "")
            components.append(node)

        # Controls: start from the imported profile's ``controls_tree`` (the SSP's control
        # baseline), then OVERLAY the SSP's implementation. Unlike a component-definition —
        # where control-implementations (and their implemented-requirements) hang off each
        # component/capability — an SSP has a single root ``control-implementation`` whose
        # ``implemented-requirements`` record which baseline controls are implemented. Each
        # control node gains ``implemented`` (bool); an implemented node also gets the
        # implementing requirement's ``implemented-requirement-uuid`` (so a UI can drill in
        # via :meth:`control`). Empty when the import-profile is absent or unresolved.
        profile = self._imported_profile()
        controls = copy.deepcopy(getattr(profile, "controls_tree", []) or []) if profile else []
        ci = root.get("control-implementation", {}) or {}
        impl_by_id: dict[str, dict] = {}
        for req in ci.get("implemented-requirements", []) or []:
            control_id = req.get("control-id", "")
            if control_id:
                impl_by_id.setdefault(control_id, req)   # first requirement per control-id
        _overlay_implemented(controls, impl_by_id)

        self.implementation_tree = {
            "leveraged-authorizations": leveraged,
            "components": components,
            "controls": controls,
        }
        return self.implementation_tree

    # -------------------------------------------------------------------------
    @staticmethod
    def _requirement_cites_component(req: dict, component_uuid: str) -> bool:
        """True when *req* attributes work to *component_uuid* via any by-component.

        Checks the implemented-requirement's own ``by-components`` and every
        ``statements[].by-components`` entry.
        """
        for by_comp in req.get("by-components", []) or []:
            if by_comp.get("component-uuid") == component_uuid:
                return True
        for statement in req.get("statements", []) or []:
            for by_comp in statement.get("by-components", []) or []:
                if by_comp.get("component-uuid") == component_uuid:
                    return True
        return False

    # -------------------------------------------------------------------------
    def _all_component_objects(self) -> list[dict]:
        """Every ``system-implementation.components`` dict, with their links.

        The SSP's own components are the whole relationship scope (an SSP does not merge
        imported components), so reverse-relationship discovery in
        :func:`_build_component_relationships` searches this list. Returns live dicts
        (not copies) — used read-only for their ``links``.
        """
        sys_impl = self._ssp_root().get("system-implementation", {}) or {}
        return list(sys_impl.get("components", []) or [])

    # -------------------------------------------------------------------------
    def _implemented_controls_for(self, component_uuid: str) -> list[str]:
        """Return the control-ids implemented by a component, in document order.

        A control counts when the component's uuid is cited in an implemented
        requirement's ``by-components`` or in one of its ``statements[].by-components``.
        Each control-id appears once.
        """
        ci = self._ssp_root().get("control-implementation", {}) or {}
        controls: list[str] = []
        for req in ci.get("implemented-requirements", []) or []:
            control_id = req.get("control-id", "")
            if control_id and control_id not in controls \
                    and self._requirement_cites_component(req, component_uuid):
                controls.append(control_id)
        return controls

    # -------------------------------------------------------------------------
    def component(self, uuid: str) -> Optional[dict]:
        """Retrieve a system-implementation component by its ``uuid``, as a safe copy.

        The returned copy carries an added ``implemented-controls`` array: every
        ``control-id`` from ``control-implementation.implemented-requirements`` whose
        implementation attributes work to this component — i.e. the component's uuid is
        cited in the requirement's ``by-components`` or in any
        ``statements[].by-components``. Control-ids are de-duplicated and kept in
        document order. Any ``responsible-roles`` are annotated with the resolved role
        ``title`` and a ``parties`` array of full metadata party objects — see
        :func:`_enrich_responsibilities`. A ``relationships`` object is
        inserted holding both this component's forward relationship links and the reverse
        relationships discovered by scanning the SSP's other components — see
        :func:`_build_component_relationships`.

        Args:
            uuid (str, required): The ``uuid`` of the system-implementation component.

        Returns:
            Optional[dict]: A safe copy of the component with ``implemented-controls``
                appended (and responsible-roles and relationships annotated), or None
                when no component has that uuid.
        """
        sys_impl = self._ssp_root().get("system-implementation", {}) or {}
        for comp in sys_impl.get("components", []) or []:
            if comp.get("uuid") == uuid:
                result = copy.deepcopy(comp)
                result["implemented-controls"] = self._implemented_controls_for(uuid)
                result = _enrich_responsibilities(self, result)
                tree_by_uuid = {n.get("uuid"): n for n in self.implementation_tree["components"]}
                result["relationships"] = _build_component_relationships(
                    result, tree_by_uuid, self._all_component_objects(), uuid)
                return result
        return None

    # -------------------------------------------------------------------------
    def control(self, identifier: str, with_control: bool = True,
                depth: Optional[int] = None) -> Optional[dict]:
        """Retrieve an SSP implemented-requirement by control-id or its uuid, as a safe copy.

        Looks up ``control-implementation.implemented-requirements`` for the first entry
        whose ``control-id`` **or** ``uuid`` equals *identifier* (the two never collide —
        one is a token, the other a UUID), and returns a safe copy of it. When
        ``with_control`` is True (default) the full control is fetched from the imported
        profile (by the requirement's ``control-id``) and inserted under a ``control``
        key — ``None`` when the profile is unresolved or the control is not found.

        The ``depth`` parameter follows the library-wide convention used by
        :meth:`Catalog.get_control_by_id` / :meth:`Profile.get_control_by_id` and governs
        how many levels of nested control enhancements the inserted control carries:
        ``None`` (default) the full subtree, ``0`` the control alone (no enhancements),
        ``N`` N levels. It has no effect when ``with_control`` is False.

        (Whether to fetch the control is a separate boolean — ``with_control`` — rather
        than an overloaded ``depth`` sentinel, so ``depth`` keeps the same meaning it has
        everywhere else in the library, where ``0`` already means "node only.")

        Each by-component — both the requirement's own ``by-components`` and each
        ``statements[].by-components`` — is annotated with its cited component's ``title``,
        ``type`` and ``asset-type`` (from ``implementation_tree['components']``) as siblings
        of ``component-uuid``. The responsibility construct is then resolved everywhere it
        nests in the requirement — the requirement's own ``responsible-roles``, each
        statement's, and every by-component's — with the role ``title`` and a ``parties``
        array of full metadata party objects (see :func:`_enrich_responsibilities`).

        When the requirement carries a non-empty ``set-parameters`` array and a control is
        fetched, those settings are applied to the inserted control's parameters (the
        control and its nested enhancements) via the same routine profile resolution uses
        (:func:`~oscal.oscal_controls._apply_set_parameters_to_control`), so the inserted
        control reflects this system's parameter values.

        Args:
            identifier (str, required): A control-id (e.g. ``"ac-2"``) or an
                implemented-requirement ``uuid``.
            with_control (bool, optional): Fetch the control from the imported profile and
                insert it under ``control``. Defaults to True.
            depth (int | None, optional): Enhancement depth of the inserted control
                (``None`` full, ``0`` control only, ``N`` N levels). Ignored when
                ``with_control`` is False.

        Returns:
            Optional[dict]: A safe copy of the implemented-requirement (with a ``control``
                key when ``with_control``), or None when no requirement matches.
        """
        ci = self._ssp_root().get("control-implementation", {}) or {}
        for req in ci.get("implemented-requirements", []) or []:
            if req.get("control-id") == identifier or req.get("uuid") == identifier:
                result = copy.deepcopy(req)
                # Annotate each by-component (requirement-level and statement-level) with its
                # cited component's title/type/asset-type from implementation_tree.
                tree_by_uuid = {n.get("uuid"): n for n in self.implementation_tree["components"]}
                for by_comp in result.get("by-components", []) or []:
                    self._annotate_by_component(by_comp, tree_by_uuid)
                for statement in result.get("statements", []) or []:
                    for by_comp in statement.get("by-components", []) or []:
                        self._annotate_by_component(by_comp, tree_by_uuid)
                # Resolve the responsibility construct everywhere it nests — the requirement
                # itself, each statement, and every by-component — in one recursive pass
                # (before the control is attached below; it carries no such construct).
                _enrich_responsibilities(self, result)
                if with_control:
                    control_id = req.get("control-id", "")
                    profile = self._imported_profile()
                    control = (profile.get_control_by_id(control_id, depth=depth)
                               if profile is not None and control_id else None)
                    if control is not None:
                        self._apply_requirement_set_parameters(control, req)
                    result["control"] = control
                return result
        return None

    # -------------------------------------------------------------------------
    @staticmethod
    def _annotate_by_component(by_comp: dict, tree_by_uuid: dict) -> None:
        """Insert the cited component's title/type/asset-type into a by-component, in place.

        Looks up ``by_comp['component-uuid']`` in *tree_by_uuid* (the
        ``implementation_tree['components']`` nodes indexed by uuid) and adds ``title`` and
        ``type`` as siblings of ``component-uuid`` (empty when the component is not found),
        plus ``asset-type`` when the node carries a non-empty one.
        """
        node = tree_by_uuid.get(by_comp.get("component-uuid"))
        by_comp["title"] = node.get("title", "") if node else ""
        by_comp["type"] = node.get("type", "") if node else ""
        asset_type = node.get("asset-type") if node else ""
        if asset_type:
            by_comp["asset-type"] = asset_type

    # -------------------------------------------------------------------------
    @staticmethod
    def _apply_requirement_set_parameters(control: dict, req: dict) -> None:
        """Apply an implemented-requirement's ``set-parameters`` to the fetched control.

        Groups the requirement's ``set-parameters`` by ``param-id`` and applies them to
        every parameter defined in the control subtree (the control and its nested
        enhancements), in place, via the shared
        :func:`~oscal.oscal_controls._apply_set_parameters_to_control` — the same routine
        profile resolution uses, so SSP and profile set-parameter semantics match.
        No-op when the requirement has no ``set-parameters``.
        """
        set_params = req.get("set-parameters") or []
        if not set_params:
            return
        by_id: dict[str, list] = {}
        for setp in set_params:
            if isinstance(setp, dict) and setp.get("param-id"):
                by_id.setdefault(setp["param-id"], []).append(setp)

        def _apply(node: dict) -> None:
            _apply_set_parameters_to_control(node, by_id)
            for child in node.get("controls", []) or []:
                if isinstance(child, dict):
                    _apply(child)

        _apply(control)

    # -------------------------------------------------------------------------
    def leveraged_authorization(self, uuid: str) -> Optional[dict]:
        """Retrieve a ``system-implementation.leveraged-authorizations`` entry by uuid, as a safe copy.

        The returned copy is annotated with:

        * ``name`` / ``short-name`` — resolved from the leveraged authorization's
          ``party-uuid`` against ``metadata.parties`` (in-scope cascade via
          :meth:`get_party_by_uuid`); ``""`` when the party or field is absent.
        * ``component-uuids`` — the ``uuid`` of every ``system-implementation.components``
          entry carrying a ``leveraged-authorization-uuid`` prop (OSCAL default namespace)
          whose value equals this authorization's ``uuid``. Always present; empty when none.

        Args:
            uuid (str, required): The ``uuid`` of the leveraged authorization.

        Returns:
            Optional[dict]: A safe copy of the leveraged authorization with ``name``,
                ``short-name`` and ``component-uuids`` inserted, or None when no
                authorization has that uuid.
        """
        sys_impl = self._ssp_root().get("system-implementation", {}) or {}
        for la in sys_impl.get("leveraged-authorizations", []) or []:
            if la.get("uuid") != uuid:
                continue
            result = copy.deepcopy(la)
            result["component-uuids"] = []

            party = self.get_party_by_uuid(la.get("party-uuid", "")) if la.get("party-uuid") else None
            result["name"]       = party.get("name", "") if party is not None else ""
            result["short-name"] = party.get("short-name", "") if party is not None else ""

            for comp in sys_impl.get("components", []) or []:
                if any(p.get("value") == uuid
                       for p in get_props(comp, name="leveraged-authorization-uuid")):
                    result["component-uuids"].append(comp.get("uuid", ""))
            return result
        return None

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def append_component(self, component_type: str, component_title: str, component_description: str, op_status: str = "operational", component_uuid: str = "", props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
        """
        Add a component to the SSP's ``system-implementation`` section.

        Args:
            component_type (str, required): The component ``type`` (e.g. "software").
            component_title (str, required): The component title.
            component_description (str, required): The component description.
            op_status (str, optional): Operational ``status.state`` value.
                Defaults to "operational".
            component_uuid (str, optional): UUID for the component. A new UUID is
                generated when empty.
            props (list, optional): Property dicts to add.
            links (list, optional): Link dicts to add.
            remarks (str, optional): Remarks prose (markdown).

        Returns:
            Optional[dict]: The newly created component dict, or None on failure.
        """
        if component_uuid == "":
            component_uuid = new_uuid()
        try:
            component = {
                "uuid": component_uuid,
                "type": component_type,
                "title": component_title,
                "description": component_description,
                "status": {"state": op_status},
            }
            if props:
                append_props(component, props)
            if links:
                append_links(component, links)
            if remarks:
                component["remarks"] = remarks

            ssp = self._ssp_root()
            if "system-implementation" not in ssp:
                logger.error("Failed to find system-implementation section in SSP.")
                return None
            ssp["system-implementation"].setdefault("components", []).append(component)
            logger.debug(f"Adding component: {component_uuid} ({component_type})")
        except Exception as error:
            logger.error(f"Error appending component (type={component_type}) {component_title}: {type(error).__name__} - {error}")
            component = None
        # Return a safe copy — the live component stays in _dict; further edits go through methods.
        return copy.deepcopy(component)

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def append_impl_requirement(self, control_id: str, props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
        """
        Add an implemented-requirement to the SSP's ``control-implementation`` section.

        Args:
            control_id (str, required): The ID of the control being implemented.
            props (list, optional): Property dicts to add.
            links (list, optional): Link dicts to add.
            remarks (str, optional): Remarks prose (markdown).

        Returns:
            Optional[dict]: The newly created implemented-requirement dict (with a
                generated UUID), or None on failure.
        """
        try:
            impl_req = {
                "uuid": new_uuid(),
                "control-id": control_id,
            }
            if props:
                append_props(impl_req, props)
            if links:
                append_links(impl_req, links)
            if remarks:
                impl_req["remarks"] = remarks

            ssp = self._ssp_root()
            if "control-implementation" not in ssp:
                logger.error("Failed to find control-implementation section in SSP.")
                return None
            ssp["control-implementation"].setdefault("implemented-requirements", []).append(impl_req)
            logger.debug(f"Adding implemented-requirement for control: {control_id}")
        except Exception as error:
            logger.error(f"Error appending implemented-requirement for control {control_id}: {type(error).__name__} - {error}")
            impl_req = None
        # Return a safe copy — the live impl-requirement stays in _dict; edits go through methods.
        return copy.deepcopy(impl_req)

    # -------------------------------------------------------------------------
    @requires(is_read_only=False)
    @if_update_successful
    def add_by_component(self, implemented_requirement_uuid: str, component_uuid: str,
                         description: str, by_component_uuid: str = "",
                         implementation_status: str = "implemented",
                         remarks: str = "") -> Optional[dict]:
        """Add a by-component statement to one of the SSP's implemented-requirements.

        The by-component is **built from the supplied scalar fields** — no caller-provided
        dict is stored verbatim — so it is schema-aligned by construction. It is appended
        to the implemented-requirement identified by *implemented_requirement_uuid* and
        returned as a safe copy (the live node stays in ``_dict``; further edits go through
        methods). Through the method decorators this also enforces the read-only guard and
        marks the document unsaved.

        Args:
            implemented_requirement_uuid (str, required): ``uuid`` of the target
                implemented-requirement under ``control-implementation``.
            component_uuid (str, required): UUID of the referenced system component.
            description (str, required): How the component satisfies the requirement.
            by_component_uuid (str, optional): UUID for the by-component; a new one is
                generated when empty.
            implementation_status (str, optional): ``implementation-status.state`` value.
                Defaults to "implemented".
            remarks (str, optional): Remarks prose (markdown).

        Returns:
            Optional[dict]: A safe copy of the new by-component, or None when the SSP has
                no implemented-requirement with that uuid.
        """
        impl_reqs = (self._ssp_root().get("control-implementation", {})
                     .get("implemented-requirements", []))
        target = next((ir for ir in impl_reqs
                       if isinstance(ir, dict)
                       and ir.get("uuid") == implemented_requirement_uuid), None)
        if target is None:
            logger.error("add_by_component: no implemented-requirement with uuid "
                         f"'{implemented_requirement_uuid}'.")
            return None

        by_component: dict[str, Any] = {
            "component-uuid": component_uuid,
            "uuid": by_component_uuid or new_uuid(),
            "description": description,
            "implementation-status": {"state": implementation_status},
        }
        if remarks:
            by_component["remarks"] = remarks

        target.setdefault("by-components", []).append(by_component)
        # Return a safe copy — the live by-component stays in _dict; edits go through methods.
        return copy.deepcopy(by_component)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def append_component(ssp_obj: OSCAL, component_type: str, component_title: str, component_description: str, op_status: str = "operational", component_uuid: str = "", props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
    """
    Add a component to an SSP's ``system-implementation`` section.

    Args:
        ssp_obj (OSCAL, required): The SSP instance to modify.
        component_type (str, required): The component ``type`` (e.g. "software").
        component_title (str, required): The component title.
        component_description (str, required): The component description.
        op_status (str, optional): Operational ``status.state`` value.
            Defaults to "operational".
        component_uuid (str, optional): UUID for the component. A new UUID is
            generated when empty.
        props (list, optional): Property dicts to add.
        links (list, optional): Link dicts to add.
        remarks (str, optional): Remarks prose (markdown).

    Returns:
        Optional[dict]: The newly created component dict, or None on failure.
    """
    # Delegate to the SSP instance method, which performs the mutation and — through its
    # decorators — the read-only guard, dirty-state bookkeeping (``is_unsaved`` /
    # ``last_modified``), and safe-copy return. Kept as a module-level convenience so the
    # two entry points can never drift (previously this duplicated the body and, notably,
    # never marked the document unsaved).
    return ssp_obj.append_component(
        component_type, component_title, component_description,
        op_status=op_status, component_uuid=component_uuid,
        props=props, links=links, remarks=remarks,
    )

# -----------------------------------------------------------------------------
def append_impl_requirement(ssp_obj: OSCAL, control_id: str, props: list = [], links: list = [], remarks: str = "") -> Optional[dict]:
    """
    Add an implemented-requirement to an SSP's ``control-implementation`` section.

    Args:
        ssp_obj (OSCAL, required): The SSP instance to modify.
        control_id (str, required): The ID of the control being implemented.
        props (list, optional): Property dicts to add.
        links (list, optional): Link dicts to add.
        remarks (str, optional): Remarks prose (markdown).

    Returns:
        Optional[dict]: The newly created implemented-requirement dict (with a
            generated UUID), or None on failure.
    """
    # Delegate to the SSP instance method (see append_component above): it handles the
    # mutation plus the read-only guard, dirty-state bookkeeping (``is_unsaved`` /
    # ``last_modified``), and safe-copy return, so the two entry points cannot drift.
    return ssp_obj.append_impl_requirement(
        control_id, props=props, links=links, remarks=remarks,
    )

# -----------------------------------------------------------------------------
def _append_responsible_role(parent: dict, role_id: str, party_uuids: list = [], remarks: str = "") -> dict:
    """Append a responsible-role to *parent* and return a safe copy of it.

    Internal helper (underscore-prefixed): ``responsible-role`` appears in many places —
    SSP/cDef components, AP/AR tasks, and ``local-definitions/components`` of AP/AR/POA&M —
    so this stays a small, model-agnostic builder rather than a method. It is **not** a
    public entry point and does no dirty-state or read-only bookkeeping: the *calling
    method* owns those, mutating live ``_dict`` content only after its own guards. The role
    is built from the supplied scalar fields (schema-aligned by construction — no caller
    dict is stored verbatim) and a **copy** is returned, never the live appended object.

    Args:
        parent (dict, required): The live parent dict to add ``responsible-roles`` to.
        role_id (str, required): The ID of the role being assigned.
        party_uuids (list, optional): UUIDs of the parties fulfilling the role.
        remarks (str, optional): Remarks prose (markdown).

    Returns:
        dict: A safe copy of the newly created responsible-role.
    """
    resp_role: dict[str, Any] = {"role-id": role_id}
    if party_uuids:
        resp_role["party-uuids"] = [str(u) for u in party_uuids]
    if remarks:
        resp_role["remarks"] = remarks

    parent.setdefault("responsible-roles", []).append(resp_role)
    # Never hand back the live appended object — callers get a detached copy.
    return copy.deepcopy(resp_role)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Register model classes so OSCAL factory methods return typed instances.
register_model("component-definition", ComponentDefinition)
register_model("system-security-plan", SSP)
