"""
oscal_assessment — OSCAL assessment-layer model classes.

Provides the model classes for the OSCAL assessment models: ``AssessmentPlan``
(Security Assessment Plan / SAP), ``AssessmentResults`` (Security Assessment
Results / SAR), and ``POAM`` (Plan of Action and Milestones). Each subclasses
``OSCAL`` from ``oscal_content`` and inherits its common load/save/validate and
query behavior.

This module also provides the shared, model-agnostic enrichment helpers that the
assessment getters (built incrementally — see ``docs/assessment_getters.md``) use to
inject resolved cross-reference data as added siblings of the raw OSCAL fields, following
the library-wide getter conventions in ``docs/METHOD_PATTERNS.md`` (safe copies; injected
content never reshapes the original; dangling references surface a visible placeholder
rather than vanishing).

Injection convention (step 1): every library-added field uses a ``resolved-`` prefix
(``resolved-title``, ``resolved-role``, ``resolved-status``) so it never collides with a
real OSCAL field (e.g. a ``subject``'s own authored ``title``) and is trivially greppable.
The raw ``*-uuid`` / ``*-id`` / ``role-id`` fields are always left intact.

Module constants:
    (none exported)
"""
from __future__ import annotations
import copy
import logging
from typing import Any, Optional

from .oscal_content import OSCAL, register_model, get_props
from .oscal_implementation import _enrich_responsibilities, _INVENTORY_INDEX_PROPS

logger = logging.getLogger(__name__)


# ===========================================================================
# Shared enrichment helpers (docs/assessment_getters.md §3)
#
# These are module-level functions (like oscal_implementation._enrich_responsibilities)
# so every assessment getter can apply them uniformly wherever the construct nests. Each
# walks a safe copy in place and returns it. They resolve against:
#   * metadata (parties / roles / locations) and the back-matter — via the base-class
#     in-scope cascade (get_party_by_uuid / get_role_by_id / get_location_by_uuid), which
#     already spans the whole import tree; and
#   * this document's own local-definitions (components / inventory-items / users /
#     assessment-platforms / tasks) — via a local index (:func:`index_local_definitions`).
#
# DEFERRED (later build steps): cross-chain resolution of component / inventory-item /
# user / task references that live only in an imported document (AR→AP→SSP). Those need
# the §3.5 container/shadowing machinery; until it exists, such a reference degrades to a
# visible placeholder (per docs/METHOD_PATTERNS.md pattern 4), never a silent drop. The
# opt-in control/target resolution (§3.3 reviewed-controls, §3.4 finding.target) is also
# deferred to the getters that consume it.
# ===========================================================================

# Local-definitions object kinds, keyed by the JSON array name that contains them. A
# whole-document sweep (:func:`index_local_definitions`) collects each by its container
# key, which is unambiguous across all three assessment models (these array names do not
# appear with a conflicting meaning elsewhere in the assessment schemas).
_LOCAL_DEF_CONTAINERS = {
    "components": "uuid",             # local-definitions + assessment-assets components
    "assessment-platforms": "uuid",  # assessment-assets platforms
    "users": "uuid",                 # local-definitions users
    "inventory-items": "uuid",       # local-definitions inventory-items
    "tasks": "uuid",                 # AP tasks / AR per-result tasks / response tasks (+ nested)
}


def _placeholder(ref_type: str) -> str:
    """The visible placeholder label for an unresolved reference of *ref_type*.

    Mirrors the SSP getters' ``"[Invalid Component Reference]"`` convention
    (docs/METHOD_PATTERNS.md pattern 4) so a dangling reference is obvious in the output
    rather than silently absent.
    """
    pretty = (ref_type or "").replace("-", " ").title() or "Unknown"
    return f"[Invalid {pretty} Reference]"


def index_local_definitions(doc: OSCAL) -> dict[str, dict[str, dict]]:
    """Index this document's local-definition objects by uuid, per container kind.

    Sweeps the whole document once and collects every object found under a
    :data:`_LOCAL_DEF_CONTAINERS` array key into a ``{uuid: object}`` map. This covers,
    without per-model branching, every place these objects live across the three
    assessment models — a cDef/SSP-style component under ``local-definitions.components``
    *and* under ``assessment-assets.components``; AR objects nested per ``result``; tasks
    at any nesting depth — because the sweep keys on the containing array name, not a
    fixed path.

    Scope is **this document only** (the ``local`` in local-definitions). Cross-chain
    resolution into an imported AP/SSP is deferred to the §3.5 machinery; an object defined
    only upstream is simply absent here and its reference will resolve to a placeholder.

    De-duplication is first-wins in document order (a uuid seen twice keeps the first).

    Args:
        doc (OSCAL, required): The assessment document to index.

    Returns:
        dict[str, dict[str, dict]]: ``{container_key: {uuid: object}}`` for every key in
            :data:`_LOCAL_DEF_CONTAINERS` (each map possibly empty). Objects are the live
            dicts from ``doc._dict``; callers must not mutate them (the enrich helpers only
            read titles/descriptions from them).
    """
    index: dict[str, dict[str, dict]] = {key: {} for key in _LOCAL_DEF_CONTAINERS}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _LOCAL_DEF_CONTAINERS and isinstance(value, list):
                    bucket = index[key]
                    for item in value:
                        if isinstance(item, dict):
                            uuid = item.get("uuid")
                            if uuid and uuid not in bucket:
                                bucket[uuid] = item
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    root = doc._dict.get(doc.model, {}) if isinstance(doc._dict, dict) else {}
    _walk(root)
    return index


def _local_title(obj: Optional[dict]) -> str:
    """Best human label for a local-definition object: ``title`` else ``description``.

    Components / users / platforms carry a ``title``; an ``inventory-item`` has only a
    ``description`` — so fall back to it, so every resolved reference yields a non-empty
    label when the target exists.
    """
    if not isinstance(obj, dict):
        return ""
    return obj.get("title") or obj.get("description") or ""


# ---------------------------------------------------------------------------
# §3.1 origins / actors
# ---------------------------------------------------------------------------
def _enrich_origins(doc: OSCAL, obj: Any, index: dict[str, dict[str, dict]]) -> Any:
    """Resolve every ``origins[].actors[]`` and ``origins[].related-tasks[]`` within *obj*.

    An ``origin`` appears on observations, risks, findings, responses, characterizations
    and log entries; this walks *obj* at every depth and enriches each one it finds.

    On each **actor** (``{type, actor-uuid, role-id?}``) it inserts:
      * ``resolved-title`` — the display label for ``actor-uuid`` by ``type``:
        ``party`` → metadata party name/short-name (in-scope cascade); ``assessment-platform``
        → a local assessment-platform title; ``tool`` → a local component title. A
        reference that does not resolve yields the :func:`_placeholder` label.
      * ``resolved-role`` — the ``metadata.roles`` title for ``role-id`` (in-scope cascade),
        when ``role-id`` is present.

    On each **related-task** (``{task-uuid}``) it inserts ``resolved-title`` — the local
    task's title (placeholder when the task is unknown / defined only upstream).

    Mutates *obj* in place (callers pass a safe copy) and returns it.
    """
    components = index.get("components", {})
    platforms = index.get("assessment-platforms", {})
    tasks = index.get("tasks", {})

    def _resolve_actor(actor: dict) -> None:
        actor_type = actor.get("type", "")
        actor_uuid = actor.get("actor-uuid", "")
        if actor_type == "party":
            party = doc.get_party_by_uuid(actor_uuid) if actor_uuid else None
            actor["resolved-title"] = (party.get("name") or party.get("short-name") or "") \
                if isinstance(party, dict) else _placeholder("party")
        elif actor_type == "assessment-platform":
            plat = platforms.get(actor_uuid)
            actor["resolved-title"] = _local_title(plat) if plat is not None \
                else _placeholder("assessment-platform")
        elif actor_type == "tool":
            comp = components.get(actor_uuid)
            actor["resolved-title"] = _local_title(comp) if comp is not None \
                else _placeholder("tool")
        else:
            actor["resolved-title"] = _placeholder(actor_type or "actor")
        role_id = actor.get("role-id", "")
        if role_id:
            role = doc.get_role_by_id(role_id)
            actor["resolved-role"] = role.get("title", "") if isinstance(role, dict) else ""

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for origin in node.get("origins", []) or []:
                if not isinstance(origin, dict):
                    continue
                for actor in origin.get("actors", []) or []:
                    if isinstance(actor, dict):
                        _resolve_actor(actor)
                for rt in origin.get("related-tasks", []) or []:
                    if isinstance(rt, dict):
                        task = tasks.get(rt.get("task-uuid", ""))
                        rt["resolved-title"] = _local_title(task) if task is not None \
                            else _placeholder("task")
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(obj)
    return obj


# ---------------------------------------------------------------------------
# §3.2 subjects (reference form)
# ---------------------------------------------------------------------------
def _enrich_subjects(doc: OSCAL, obj: Any, index: dict[str, dict[str, dict]]) -> Any:
    """Resolve every subject *reference* within *obj* (anything carrying ``subject-uuid``).

    The reference form of a subject — ``{subject-uuid, type, title?}`` — appears as an
    observation subject, an ``include-subject`` / ``exclude-subject``, a mitigating-factor
    subject and a required-asset subject. (The *selection* form, ``include-all`` /
    ``include-subjects`` / ``exclude-subjects`` on an ``assessment-subject`` or task, has no
    ``subject-uuid`` of its own and is left untouched; its inner include/exclude entries are
    reached by the walk.)

    Inserts ``resolved-title`` — the display label for ``subject-uuid`` by ``type``:
      * ``component`` / ``inventory-item`` / ``user`` → this document's local-definitions
        (local index);
      * ``party`` → metadata party name, ``location`` → metadata location title (in-scope
        cascade, spans imports).
    An unresolved reference yields the :func:`_placeholder` label. The subject's own
    authored ``title`` (a real OSCAL field) is never overwritten — the resolved value is a
    separate ``resolved-title`` sibling.

    Mutates *obj* in place (callers pass a safe copy) and returns it.
    """
    components = index.get("components", {})
    inventory = index.get("inventory-items", {})
    users = index.get("users", {})

    def _resolve(subject: dict) -> None:
        stype = subject.get("type", "")
        suuid = subject.get("subject-uuid", "")
        if stype == "component":
            subject["resolved-title"] = _local_title(components.get(suuid)) \
                or _placeholder("component")
        elif stype == "inventory-item":
            subject["resolved-title"] = _local_title(inventory.get(suuid)) \
                or _placeholder("inventory-item")
        elif stype == "user":
            subject["resolved-title"] = _local_title(users.get(suuid)) \
                or _placeholder("user")
        elif stype == "party":
            party = doc.get_party_by_uuid(suuid) if suuid else None
            subject["resolved-title"] = (party.get("name") or party.get("short-name") or "") \
                if isinstance(party, dict) else _placeholder("party")
        elif stype == "location":
            loc = doc.get_location_by_uuid(suuid) if suuid else None
            subject["resolved-title"] = loc.get("title", "") if isinstance(loc, dict) \
                else _placeholder("location")
        else:
            subject["resolved-title"] = _placeholder(stype or "subject")

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if "subject-uuid" in node:
                _resolve(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(obj)
    return obj


# ---------------------------------------------------------------------------
# §3.4 intra-document cross references (related / associated)
# ---------------------------------------------------------------------------
def _enrich_related_references(doc: OSCAL, obj: Any) -> Any:
    """Resolve document-local ``related-*`` / ``related-risks`` references within *obj*.

    These are intra-document pointers between assessment objects; each gets a short
    resolved summary inserted as a sibling of its raw ``*-uuid`` field:

      * ``related-observations[].observation-uuid`` → ``resolved-title`` (the observation's
        title, which is optional in OSCAL — empty string when untitled).
      * ``related-risks[].risk-uuid`` (the JSON key for an *associated-risk*) →
        ``resolved-title`` + ``resolved-status`` (the risk's ``status`` string).
      * ``related-findings[].finding-uuid`` → ``resolved-title`` + ``resolved-status`` (the
        finding's ``target.status.state``).

    Resolution uses this document's own intra-document getters
    (:meth:`_AssessmentObjectsMixin.observation` etc.). A reference that does not resolve
    yields the :func:`_placeholder` label and an empty status.

    Mutates *obj* in place (callers pass a safe copy) and returns it.
    """
    get_obs = getattr(doc, "observation", None)
    get_risk = getattr(doc, "risk", None)
    get_finding = getattr(doc, "finding", None)

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for ref in node.get("related-observations", []) or []:
                if isinstance(ref, dict) and callable(get_obs):
                    obs = get_obs(ref.get("observation-uuid", ""))
                    ref["resolved-title"] = obs.get("title", "") if obs is not None \
                        else _placeholder("observation")
            for ref in node.get("related-risks", []) or []:
                if isinstance(ref, dict) and callable(get_risk):
                    risk = get_risk(ref.get("risk-uuid", ""))
                    if risk is not None:
                        ref["resolved-title"] = risk.get("title", "")
                        ref["resolved-status"] = risk.get("status", "")
                    else:
                        ref["resolved-title"] = _placeholder("risk")
                        ref["resolved-status"] = ""
            for ref in node.get("related-findings", []) or []:
                if isinstance(ref, dict) and callable(get_finding):
                    finding = get_finding(ref.get("finding-uuid", ""))
                    if finding is not None:
                        ref["resolved-title"] = finding.get("title", "")
                        target = finding.get("target", {}) or {}
                        status = target.get("status", {}) or {}
                        ref["resolved-status"] = status.get("state", "")
                    else:
                        ref["resolved-title"] = _placeholder("finding")
                        ref["resolved-status"] = ""
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(obj)
    return obj


# ===========================================================================
# Intra-document object resolvers (docs/assessment_getters.md §4)
#
# observation / risk / finding references stay within the same document. This mixin
# provides by-uuid resolvers for them, shared by AssessmentResults (objects nested under
# each `result`) and POAM (objects at the top level). AssessmentPlan has none of these
# objects and does NOT inherit the mixin.
# ===========================================================================
class _AssessmentObjectsMixin:
    """By-uuid getters for a document's own observations, risks and findings.

    The three objects are keyed by ``uuid`` and live at different paths per model:

    * **AssessmentResults** — under each ``results[]`` entry
      (``results[].observations`` / ``.risks`` / ``.findings``). A match is annotated with
      a ``result-uuid`` sibling naming the owning result.
    * **POAM** — top-level (``observations`` / ``risks`` / ``findings``); no result scope,
      so no ``result-uuid`` annotation.

    Each getter returns a detached safe copy (docs/METHOD_PATTERNS.md pattern 1) or None.
    The short ``.observation()`` / ``.risk()`` / ``.finding()`` names match the library's
    current model-specific detail-getter convention (``.component()``, ``.user()``, …); the
    library-wide ``get_<noun>()`` normalization is tracked separately for 5.0.0 (see
    docs/NAMING_CONSISTENCY_PLAN.md).
    """

    def _iter_assessment_objects(self, plural_key: str):
        """Yield ``(object, result_uuid)`` for every object under *plural_key* in scope.

        ``result_uuid`` is the owning result's uuid for an AssessmentResults document, or
        None for a POAM (top-level) document. Objects are the live dicts; callers copy.
        """
        root = self._dict.get(self.model, {}) if isinstance(self._dict, dict) else {}
        if not isinstance(root, dict):
            return
        if self.model == "assessment-results":
            for result in root.get("results", []) or []:
                if not isinstance(result, dict):
                    continue
                result_uuid = result.get("uuid", "")
                for obj in result.get(plural_key, []) or []:
                    if isinstance(obj, dict):
                        yield obj, result_uuid
        else:  # plan-of-action-and-milestones: top-level arrays
            for obj in root.get(plural_key, []) or []:
                if isinstance(obj, dict):
                    yield obj, None

    def _get_assessment_object(self, plural_key: str, uuid: str) -> Optional[dict]:
        """Return a safe copy of the first object under *plural_key* whose uuid matches.

        For an AssessmentResults match, a ``result-uuid`` sibling is inserted naming the
        owning result. Returns None when *uuid* is empty or no object matches.
        """
        if not uuid:
            return None
        for obj, result_uuid in self._iter_assessment_objects(plural_key):
            if obj.get("uuid") == uuid:
                result = copy.deepcopy(obj)
                if result_uuid is not None:
                    result["result-uuid"] = result_uuid
                return result
        return None

    # -- cross-reference injection ------------------------------------------
    # observation / risk / finding inject the objects their `related-*` arrays cite, so a
    # caller gets the cited observations/risks inline. OSCAL is designed so these references
    # cannot form a cycle, but a `_seen` path-guard protects against a malformed document:
    # a uuid already being expanded on the current path is returned without re-expansion.

    #: Subject-reference `type` -> the accessor used to resolve the cited object. Each maps
    #: a `subjects[].subject-uuid` to a getter; the resolved object is inserted under a key
    #: named for the type (e.g. a `component` subject gains a `component` child).
    _SUBJECT_RESOLVERS = {
        "component":      "component",            # _LocalDefinitionGettersMixin (cross-chain)
        "inventory-item": "inventory_item",       # _LocalDefinitionGettersMixin (cross-chain)
        "location":       "get_location_by_uuid",  # base OSCAL (in-scope cascade)
        "party":          "get_party_by_uuid",     # base OSCAL (in-scope cascade)
        "user":           "user",                  # _LocalDefinitionGettersMixin (cross-chain)
        "resource":       "get_resource_by_uuid",  # base OSCAL (in-scope cascade)
    }

    def _attach_subjects(self, obj: dict) -> None:
        """Resolve each ``subjects[]`` reference and insert the cited object in place.

        For every reference-form subject (one carrying a ``subject-uuid``), the ``type``
        selects the accessor (:data:`_SUBJECT_RESOLVERS`); the resolved object is inserted
        under a key named for the type (``component`` / ``inventory-item`` / ``location`` /
        ``party`` / ``user`` / ``resource``). An unresolved reference yields a visible
        placeholder, so a dangling subject is obvious.
        """
        for subj in obj.get("subjects", []) or []:
            if not isinstance(subj, dict) or not subj.get("subject-uuid"):
                continue
            stype = subj.get("type", "")
            accessor = self._SUBJECT_RESOLVERS.get(stype)
            resolved = None
            if accessor is not None:
                getter = getattr(self, accessor, None)
                if callable(getter):
                    resolved = getter(subj["subject-uuid"])
            subj[stype or "subject"] = resolved if resolved is not None else {
                "title": f"[Invalid {(stype or 'subject').replace('-', ' ').title()} Reference]"}

    def _attach_evidence_resources(self, obj: dict) -> None:
        """For each ``relevant-evidence`` whose ``href`` is a ``#uuid`` fragment resolving to
        a back-matter resource (locally or via imports), insert that resource under
        ``resource``. A full-URI href (external evidence) is left untouched.
        """
        for ev in obj.get("relevant-evidence", []) or []:
            if not isinstance(ev, dict):
                continue
            href = str(ev.get("href", "")).strip()
            if href.startswith("#"):
                resource = self.get_resource_by_uuid(href[1:])
                if resource is not None:
                    ev["resource"] = resource

    #: Actor `type` -> accessor + the key the resolved object is inserted under.
    _ACTOR_RESOLVERS = {
        "tool":                ("component", "tool"),
        "assessment-platform": ("assessment_platform", "assessment-platform"),
        "party":               ("get_party_by_uuid", "party"),
    }

    def actor(self, actors: list) -> list:
        """Return a copy of an ``actors[]`` array with each actor's cited object injected.

        A helper for populating any object that carries an ``actors[]`` array (an
        ``origin``). For each actor, ``type`` selects the lookup for ``actor-uuid``
        (:data:`_ACTOR_RESOLVERS`): ``tool`` → :meth:`component`, ``assessment-platform`` →
        :meth:`assessment_platform`, ``party`` → :meth:`get_party_by_uuid`. The resolved
        object is inserted under a key named for the type (``tool`` / ``assessment-platform``
        / ``party``); an unresolved reference adds nothing. The input array is not mutated.
        """
        result = copy.deepcopy(actors) if actors else []
        for actor in result:
            if not isinstance(actor, dict):
                continue
            spec = self._ACTOR_RESOLVERS.get(actor.get("type", ""))
            auuid = actor.get("actor-uuid", "")
            if spec is None or not auuid:
                continue
            accessor, key = spec
            getter = getattr(self, accessor, None)
            if callable(getter):
                resolved = getter(auuid)
                if resolved is not None:
                    actor[key] = resolved
        return result

    def _populate_actors(self, node) -> None:
        """Recursively replace every ``actors`` array anywhere in *node* with the populated
        copy from :meth:`actor` (so each ``origin`` throughout the object hierarchy carries
        resolved actor detail). The replaced array is not descended into further.
        """
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if key == "actors" and isinstance(value, list):
                    node[key] = self.actor(value)
                else:
                    self._populate_actors(value)
        elif isinstance(node, list):
            for item in node:
                self._populate_actors(item)

    def observation(self, uuid: str, _seen: "frozenset | None" = None) -> Optional[dict]:
        """Return this document's ``observation`` with the given uuid, as a safe copy, or None.

        Searches every ``result`` (AssessmentResults) or the top-level ``observations``
        (POAM); an AssessmentResults match carries a ``result-uuid`` sibling. Each
        ``subjects[]`` reference is resolved to its cited object by ``type`` (see
        :meth:`_attach_subjects`); each ``relevant-evidence`` fragment href is resolved to its
        back-matter ``resource`` (see :meth:`_attach_evidence_resources`); and every
        ``origins[].actors[]`` array in the hierarchy is populated via :meth:`actor`.
        ``_seen`` is the internal cycle-guard path. See :class:`_AssessmentObjectsMixin`.
        """
        base = self._get_assessment_object("observations", uuid)
        if base is None:
            return None
        self._attach_subjects(base)
        self._attach_evidence_resources(base)
        self._populate_actors(base)
        return base

    def risk(self, uuid: str, _seen: "frozenset | None" = None) -> Optional[dict]:
        """Return this document's ``risk`` with the given uuid, as a safe copy, or None.

        Searches every ``result`` (AssessmentResults) or the top-level ``risks`` (POAM); an
        AssessmentResults match carries a ``result-uuid`` sibling. An ``observations`` array
        is inserted, populated via :meth:`observation` for each
        ``related-observations[].observation-uuid``. ``_seen`` is the internal cycle-guard
        path (a uuid already being expanded is returned without re-injection). See
        :class:`_AssessmentObjectsMixin`.
        """
        base = self._get_assessment_object("risks", uuid)
        if base is None:
            return None
        seen = _seen or frozenset()
        if uuid in seen:
            return base                                   # cycle guard: no re-expansion
        child = seen | {uuid}
        # Populate the risk's own origins' actors first (every origins[].actors[] in its
        # hierarchy) before injecting observations (which are already actor-populated).
        self._populate_actors(base)
        base["observations"] = [
            o for ref in base.get("related-observations", []) or []
            if isinstance(ref, dict) and ref.get("observation-uuid")
            and (o := self.observation(ref["observation-uuid"], child)) is not None
        ]
        return base

    def finding(self, uuid: str, _seen: "frozenset | None" = None) -> Optional[dict]:
        """Return this document's ``finding`` with the given uuid, as a safe copy, or None.

        Searches every ``result`` (AssessmentResults) or the top-level ``findings`` (POAM);
        an AssessmentResults match carries a ``result-uuid`` sibling. Two arrays are
        inserted: ``observations`` (via :meth:`observation` for each
        ``related-observations[].observation-uuid``) and ``risks`` (via :meth:`risk` for each
        ``related-risks[].risk-uuid`` — the associated-risk references); every
        ``origins[].actors[]`` array in the finding's own hierarchy is populated via
        :meth:`actor`. ``_seen`` is the internal cycle-guard path. See
        :class:`_AssessmentObjectsMixin`.
        """
        base = self._get_assessment_object("findings", uuid)
        if base is None:
            return None
        seen = _seen or frozenset()
        if uuid in seen:
            return base                                   # cycle guard: no re-expansion
        child = seen | {uuid}
        # Populate the finding's own origins' actors before injecting the cited
        # observations / risks (which are already actor-populated by their own getters).
        self._populate_actors(base)
        base["observations"] = [
            o for ref in base.get("related-observations", []) or []
            if isinstance(ref, dict) and ref.get("observation-uuid")
            and (o := self.observation(ref["observation-uuid"], child)) is not None
        ]
        base["risks"] = [
            r for ref in base.get("related-risks", []) or []
            if isinstance(ref, dict) and ref.get("risk-uuid")
            and (r := self.risk(ref["risk-uuid"], child)) is not None
        ]
        return base


# ===========================================================================
# Local-definition getters — components & inventory-items, across the import chain
#
# Shared by all three assessment models. Unlike the intra-document getters above, these
# resolve DOWN THE IMPORT CHAIN by default — AR → AP → SSP, POA&M → SSP, AP → SSP —
# stopping at the SSP (``system-implementation`` is where these objects ultimately live;
# catalogs/profiles have none). The return shapes mirror the SSP getters.
# ===========================================================================
class _LocalDefinitionGettersMixin:
    """Cross-chain getters for local-definition ``components`` and ``inventory-items``.

    Resolution model (shared by every method):

    * **Scope** — this document first, then each imported document depth-first,
      **stopping at the SSP** (descent does not continue into the SSP's own
      profile/catalog imports, which have no components or inventory-items). The walk is
      cycle-safe and resolves imports on demand.
    * **``local_only``** (default ``False``) — when ``True``, search only THIS document and
      do not traverse imports. Matches the ``local_only`` parameter on the base-class
      cross-reference getters.
    * **Provenance** — every returned object carries a ``provenance`` object
      ``{uuid, href, imported}`` — the owning document's root uuid, its resolved href, and
      whether it was reached through an import (``imported`` is False only for this
      document). It annotates the object it sits on: the base result, each
      ``additional-versions`` entry, and each plural-index entry all carry their own. This
      is the library-wide provenance shape (see docs/NAMING_CONSISTENCY_PLAN.md).
    * **De-duplication** — the plural getters and the base of the singular getters take the
      **first-found** instance of a uuid (this document before its imports, imports in array
      order), matching the base-class first-wins collection getters.
    * **Per-owner shape** — a component is returned in its owning document's shape: an
      SSP-owned component keeps the full :meth:`SSP.component` shape
      (``implemented-controls`` / ``relationships``), while an assessment-owned component is
      responsibilities-only. This is what makes the supersession below non-lossy.
    * **``additional-versions`` (local-definition constructs only)** — two cases:
      (1) a singular getter called with ``include_all=True`` makes the first-found object
      the base and appends the other instances of that uuid down the chain; (2) an embedded
      ``component`` inside an :meth:`inventory_item` that is **superseded** by a nearer
      definition always retains the superseded version(s) here (regardless of
      ``include_all``), so content only the deeper copy carries is never lost. The array is
      flat (nearest-first) and each entry keeps its own shape + ``provenance``. Roles /
      parties / locations / resources do **not** use ``additional-versions`` — they are
      strictly first-found-wins.

    The objects searched are gathered from wherever they live in each document — an
    assessment model's ``local-definitions`` (and ``assessment-assets``, and AR per-result
    containers) and the SSP's ``system-implementation`` — via
    :func:`index_local_definitions`, which keys on the container name rather than a fixed
    path.
    """
    _SSP_MODEL = "system-security-plan"

    # -------------------------------------------------------------------------
    def _chain_documents(self, local_only: bool) -> list:
        """Return the documents to search: self first, then the import chain to the SSP.

        Depth-first and cycle-safe; descent stops at an SSP. Imports are resolved on demand.
        ``local_only`` returns ``[self]`` and neither resolves nor walks imports.
        """
        if local_only:
            return [self]
        ordered: list = []
        seen: set = set()

        def _visit(doc) -> None:
            if id(doc) in seen:
                return
            seen.add(id(doc))
            ordered.append(doc)
            if getattr(doc, "model", "") == self._SSP_MODEL:
                return                              # do not descend past the SSP
            if not getattr(doc, "imports_resolved", True):
                try:
                    doc.resolve_imports()
                except Exception as error:          # best-effort; an unresolved hop is skipped
                    logger.debug(f"local-definition getter: import resolution deferred ({error}).")
            for entry in getattr(doc, "import_list", []) or []:
                obj = entry.get("object")
                if obj is not None:
                    _visit(obj)

        _visit(self)
        return ordered

    # -------------------------------------------------------------------------
    def _chain_objects(self, container_key: str, local_only: bool) -> list:
        """Return ``(object, owner_doc)`` for every object under *container_key* across the
        chain, in document order (self first). Not de-duplicated — callers apply first-wins.
        *owner_doc* is the live OSCAL document the object came from (used for provenance and
        for per-owner enrichment)."""
        out: list = []
        for doc in self._chain_documents(local_only):
            index = index_local_definitions(doc).get(container_key, {})
            for obj in index.values():
                out.append((obj, doc))
        return out

    # -------------------------------------------------------------------------
    def _provenance(self, owner) -> dict:
        """Build the ``provenance`` object for an object found in *owner*.

        ``{uuid, href, imported}`` — the owning document's root uuid, its resolved href, and
        whether it was reached through an import relative to the document the getter was
        called on (``imported`` is False only for *self*). This is the library-wide
        provenance shape (see docs/NAMING_CONSISTENCY_PLAN.md)."""
        return {
            "uuid": getattr(owner, "uuid", "") or "",
            "href": getattr(owner, "href", "") or getattr(owner, "href_original", "") or "",
            "imported": owner is not self,
        }

    def _component_version(self, raw: dict, owner) -> dict:
        """Produce one component *version* in its owning document's own shape + provenance.

        A component owned by the **SSP** is returned via :meth:`SSP.component` — its full
        shape, including the SSP-derived ``implemented-controls`` and ``relationships``. A
        component owned by an **assessment** document is a safe copy with its
        ``responsible-roles`` enriched (resolved in that document's own scope); it has no
        ``implemented-controls`` / ``relationships`` (no ``control-implementation`` there).
        Either way the ``provenance`` object is stamped on it.
        """
        if getattr(owner, "model", "") == self._SSP_MODEL:
            version = owner.component(raw.get("uuid", ""))
            if version is None:                         # defensive; raw came from owner's index
                version = copy.deepcopy(raw)
        else:
            version = copy.deepcopy(raw)
            _enrich_responsibilities(owner, version)
        version["provenance"] = self._provenance(owner)
        return version

    def _collect_component_versions(self, uuid: str, local_only: bool) -> list:
        """Every version of component *uuid* across the chain, nearest-first (each enriched
        in its owner's shape, each with its own ``provenance``). Empty when none match."""
        return [self._component_version(obj, owner)
                for obj, owner in self._chain_objects("components", local_only)
                if obj.get("uuid") == uuid]

    def _resolve_implemented_component(self, comp_uuid: str, local_only: bool) -> dict:
        """Resolve one ``implemented-component`` reference to the embedded ``component``.

        The nearest version is the base; when the same uuid also exists further down the
        chain (i.e. the importer supersedes an imported definition) the superseded
        version(s) are retained — flattened, nearest-first — in an ``additional-versions``
        array on the base, so content that only the deeper (e.g. SSP) copy carries
        (``implemented-controls`` / ``relationships``) is never lost. An unresolved
        reference yields a visible placeholder.
        """
        versions = self._collect_component_versions(comp_uuid, local_only)
        if not versions:
            return {"title": "[Invalid Component Reference]", "type": "unknown"}
        base = versions[0]
        if len(versions) > 1:
            base["additional-versions"] = versions[1:]
        return base

    # -------------------------------------------------------------------------
    def component(self, uuid: str, local_only: bool = False,
                  include_all: bool = False) -> Optional[dict]:
        """Return a local-definition ``component`` by uuid, as a safe copy, or None.

        Searches this document then the import chain to the SSP (see
        :class:`_LocalDefinitionGettersMixin`), **first-found-wins**. The returned object is
        in its owning document's shape — an assessment-owned component is a safe copy with
        ``responsible-roles`` enriched (no ``implemented-controls`` / ``relationships``); an
        SSP-owned component carries the full :meth:`SSP.component` shape — plus a
        ``provenance`` object. With ``include_all``, the first-found instance is the base and
        gains an ``additional-versions`` array of the other instances down the chain (each in
        its own shape, each with its own ``provenance``).
        """
        if not uuid:
            return None
        versions = self._collect_component_versions(uuid, local_only)
        if not versions:
            return None
        base = versions[0]
        if include_all:
            base["additional-versions"] = versions[1:]
        return base

    def components(self, local_only: bool = False) -> list:
        """Return a lightweight index of local-definition ``components`` across the chain.

        One ``{"uuid", "title", "type", "provenance"}`` entry per component (plus
        ``asset-type`` when the OSCAL-default-namespace prop is present), mirroring
        :meth:`SSP.inventory_items` / :meth:`ComponentDefinition.components`. First-wins by
        uuid across the chain; ``local_only`` restricts to this document. For full detail
        use :meth:`component`.
        """
        seen: set = set()
        out: list = []
        for obj, owner in self._chain_objects("components", local_only):
            uuid = obj.get("uuid", "")
            if uuid and uuid in seen:
                continue
            if uuid:
                seen.add(uuid)
            entry: dict = {"uuid": uuid, "title": obj.get("title", ""),
                           "type": obj.get("type", "")}
            asset = get_props(obj, name="asset-type")
            if asset:
                entry["asset-type"] = asset[0].get("value", "")
            entry["provenance"] = self._provenance(owner)
            out.append(entry)
        return out

    def inventory_item(self, uuid: str, local_only: bool = False,
                       include_all: bool = False) -> Optional[dict]:
        """Return a local-definition ``inventory-item`` by uuid, as a safe copy, or None.

        Searches this document then the import chain to the SSP, **first-found-wins**. Same
        return shape as :meth:`SSP.inventory_item` — responsibilities enriched and each
        ``implemented-components`` entry's ``component-uuid`` resolved to a ``component``
        child (via :meth:`component`'s chain resolution, so a superseded imported component
        is retained under ``additional-versions``; an unresolved reference yields a visible
        placeholder) — plus a ``provenance`` object. With ``include_all``, the first-found
        instance is the base and gains an ``additional-versions`` array of the other
        inventory-item instances down the chain.
        """
        if not uuid:
            return None
        versions = [self._inventory_item_object(item, owner, local_only)
                    for item, owner in self._chain_objects("inventory-items", local_only)
                    if item.get("uuid") == uuid]
        if not versions:
            return None
        base = versions[0]
        if include_all:
            base["additional-versions"] = versions[1:]
        return base

    def _inventory_item_object(self, raw: dict, owner, local_only: bool) -> dict:
        """One inventory-item in :meth:`SSP.inventory_item` shape + ``provenance``.

        Responsibilities are enriched (in *owner*'s scope) before the ``component`` children
        are attached, so the per-owner enrichment on each embedded component is preserved.
        """
        result = copy.deepcopy(raw)
        _enrich_responsibilities(owner, result)
        for ic in result.get("implemented-components", []) or []:
            if not isinstance(ic, dict):
                continue
            ic["component"] = self._resolve_implemented_component(
                ic.get("component-uuid", ""), local_only)
        result["provenance"] = self._provenance(owner)
        return result

    def inventory_items(self, local_only: bool = False) -> list:
        """Return a simplified index of local-definition ``inventory-items`` across the chain.

        Same per-entry shape as :meth:`SSP.inventory_items` (``uuid``, ``description``, the
        recognized OSCAL-default-namespace props flattened, and resolved
        ``implemented-components`` ``{component-uuid, title, type}``) plus a ``provenance``
        object. First-wins by uuid across the chain; ``local_only`` restricts to this
        document. For full detail use :meth:`inventory_item`.
        """
        # First-wins raw component map (uuid -> raw) for resolving implemented-component
        # titles/types on the index, in chain order.
        comp_first: dict = {}
        for obj, _owner in self._chain_objects("components", local_only):
            cu = obj.get("uuid")
            if cu and cu not in comp_first:
                comp_first[cu] = obj
        seen: set = set()
        out: list = []
        for item, owner in self._chain_objects("inventory-items", local_only):
            uuid = item.get("uuid", "")
            if uuid and uuid in seen:
                continue
            if uuid:
                seen.add(uuid)
            entry: dict = {"uuid": uuid, "description": item.get("description", "")}
            for name in _INVENTORY_INDEX_PROPS:
                values = [p.get("value", "") for p in get_props(item, name=name)]
                if values:
                    entry[name] = values[0] if len(values) == 1 else values
            implemented = []
            for ic in item.get("implemented-components", []) or []:
                if not isinstance(ic, dict):
                    continue
                comp = comp_first.get(ic.get("component-uuid"))
                if comp is not None:
                    implemented.append({"component-uuid": ic.get("component-uuid", ""),
                                        "title": comp.get("title", ""),
                                        "type": comp.get("type", "")})
            if implemented:
                entry["implemented-components"] = implemented
            entry["provenance"] = self._provenance(owner)
            out.append(entry)
        return out

    # -------------------------------------------------------------------------
    def _user_version(self, raw: dict, owner) -> dict:
        """One user in :meth:`SSP.user` shape + ``provenance``.

        When the user carries ``role-ids``, a sibling ``roles`` array of
        ``{id, title, short-name}`` is added, each resolved from ``metadata.roles`` in the
        owning document's scope (an unresolved role-id yields empty title/short-name). The
        raw ``role-ids`` list is left intact.
        """
        version = copy.deepcopy(raw)
        role_ids = version.get("role-ids")
        if role_ids:
            roles = []
            for rid in role_ids:
                role = owner.get_role_by_id(rid)
                roles.append({"id": role.get("id", rid) if isinstance(role, dict) else rid,
                              "title": role.get("title", "") if isinstance(role, dict) else "",
                              "short-name": role.get("short-name", "") if isinstance(role, dict) else ""})
            version["roles"] = roles
        version["provenance"] = self._provenance(owner)
        return version

    def user(self, uuid: str, local_only: bool = False,
             include_all: bool = False) -> Optional[dict]:
        """Return a local-definition ``user`` by uuid, as a safe copy, or None.

        Searches this document then the import chain to the SSP, **first-found-wins**. Same
        return shape as :meth:`SSP.user` (a resolved ``roles`` sibling when ``role-ids`` is
        present) plus a ``provenance`` object. With ``include_all``, the first-found instance
        is the base and gains an ``additional-versions`` array.
        """
        if not uuid:
            return None
        versions = [self._user_version(obj, owner)
                    for obj, owner in self._chain_objects("users", local_only)
                    if obj.get("uuid") == uuid]
        if not versions:
            return None
        base = versions[0]
        if include_all:
            base["additional-versions"] = versions[1:]
        return base

    def users(self, local_only: bool = False) -> list:
        """Return a lightweight index of local-definition ``users`` across the chain.

        One ``{"uuid", "title", "short-name", "provenance"}`` entry per user; first-wins by
        uuid; ``local_only`` restricts to this document. For full detail (resolved roles) use
        :meth:`user`.
        """
        seen: set = set()
        out: list = []
        for obj, owner in self._chain_objects("users", local_only):
            uuid = obj.get("uuid", "")
            if uuid and uuid in seen:
                continue
            if uuid:
                seen.add(uuid)
            out.append({"uuid": uuid, "title": obj.get("title", ""),
                        "short-name": obj.get("short-name", ""),
                        "provenance": self._provenance(owner)})
        return out

    # -------------------------------------------------------------------------
    def _assessment_platform_version(self, raw: dict, owner) -> dict:
        """One assessment-platform (whole object) + injected ``components`` + ``provenance``.

        Each ``uses-components[].component-uuid`` is resolved with the standard component
        lookup (:meth:`component`, so local-definition and imported components both resolve)
        and the resolved objects are collected in a ``components`` array. Unresolved
        references are skipped.
        """
        version = copy.deepcopy(raw)
        components = []
        for uc in version.get("uses-components", []) or []:
            if not isinstance(uc, dict):
                continue
            cu = uc.get("component-uuid", "")
            comp = self.component(cu) if cu else None
            if comp is not None:
                components.append(comp)
        version["components"] = components
        version["provenance"] = self._provenance(owner)
        return version

    def assessment_platform(self, uuid: str, local_only: bool = False,
                            include_all: bool = False) -> Optional[dict]:
        """Return an ``assessment-platform`` by uuid (whole object), as a safe copy, or None.

        Lives in ``assessment-assets.assessment-platforms`` — top-level for an
        AssessmentPlan, per-``result`` for AssessmentResults, under ``local-definitions`` for
        a POA&M. Searches this document then the import chain, first-found-wins. The returned
        object is the full platform plus an injected ``components`` array (one resolved
        component per ``uses-components[].component-uuid``) and a ``provenance`` object. With
        ``include_all``, the first-found instance is the base and gains an
        ``additional-versions`` array.
        """
        if not uuid:
            return None
        versions = [self._assessment_platform_version(obj, owner)
                    for obj, owner in self._chain_objects("assessment-platforms", local_only)
                    if obj.get("uuid") == uuid]
        if not versions:
            return None
        base = versions[0]
        if include_all:
            base["additional-versions"] = versions[1:]
        return base

    def assessment_platforms(self, local_only: bool = False) -> list:
        """Return a lightweight index of ``assessment-platforms`` across the chain.

        One ``{"uuid", "title", "provenance"}`` entry per platform; first-wins by uuid;
        ``local_only`` restricts to this document. For full detail (with resolved
        ``components``) use :meth:`assessment_platform`.
        """
        seen: set = set()
        out: list = []
        for obj, owner in self._chain_objects("assessment-platforms", local_only):
            uuid = obj.get("uuid", "")
            if uuid and uuid in seen:
                continue
            if uuid:
                seen.add(uuid)
            out.append({"uuid": uuid, "title": obj.get("title", ""),
                        "provenance": self._provenance(owner)})
        return out

    # -- subject-selection enrichment (assessment-subject / task subjects) ---
    #: subject `type` -> (single getter, plural getter). component/inventory-item/user use
    #: the cross-chain local-definition getters; location/party use the base metadata
    #: getters confined to the assessment chain + the SSP (``stop_at_ssp``).
    _SUBJECT_TYPE_GETTERS = {
        "component":      ("component", "components"),
        "inventory-item": ("inventory_item", "inventory_items"),
        "location":       ("get_location_by_uuid", "locations"),
        "party":          ("get_party_by_uuid", "parties"),
        "user":           ("user", "users"),
    }

    #: Inventory-item title fallback: OSCAL-default-namespace prop names, in priority order,
    #: used when an inventory-item has no implemented-component to borrow a title from.
    _INVENTORY_TITLE_PROPS = (
        "label", "fqdn", "uri", "netbios-name", "software-name", "os-name", "asset-tag",
        "asset-id", "model", "hardware-model", "function", "asset-type", "serial-number",
        "mac-address", "ipv4-address", "ipv6-address", "network-id", "vlan-id",
        "baseline-configuration-name",
    )

    def _resolve_subject_by_type(self, stype: str, single: str, uuid: str):
        """Resolve one subject object by ``type`` + uuid via the appropriate single getter.

        Location / party use the base getters confined to the assessment chain + SSP
        (``stop_at_ssp=True``); the others use the cross-chain local-definition getters.
        """
        getter = getattr(self, single, None)
        if not callable(getter) or not uuid:
            return None
        if stype in ("location", "party"):
            return getter(uuid, stop_at_ssp=True)
        return getter(uuid)

    def _subject_title(self, stype: str, obj) -> str:
        """Best display title for a resolved subject object, by type."""
        if not isinstance(obj, dict):
            return ""
        if stype == "party":
            return obj.get("name") or obj.get("short-name") or ""
        if stype == "inventory-item":
            # title of the first resolved implemented-component, else the first present
            # prop in the priority order.
            for ic in obj.get("implemented-components", []) or []:
                comp = ic.get("component") if isinstance(ic, dict) else None
                title = comp.get("title", "") if isinstance(comp, dict) else ""
                if title and not title.startswith("[Invalid"):
                    return title
            for name in self._INVENTORY_TITLE_PROPS:
                props = get_props(obj, name=name)
                if props:
                    return props[0].get("value", "")
            return ""
        return obj.get("title") or ""           # component, user, location

    def _enrich_include_subject(self, inc: dict, stype: str) -> None:
        """Resolve one include-subject (by ``subject-uuid`` + *stype*) and annotate it in
        place: insert ``title``, and for a component also the component's ``type`` and its
        ``asset-type`` prop value (OSCAL default namespace) when present.
        """
        single = self._SUBJECT_TYPE_GETTERS[stype][0]
        obj = self._resolve_subject_by_type(stype, single, inc.get("subject-uuid", ""))
        inc["title"] = self._subject_title(stype, obj)
        if stype == "component" and isinstance(obj, dict):
            inc["type"] = obj.get("type", "")
            asset = get_props(obj, name="asset-type")
            if asset:
                inc["asset-type"] = asset[0].get("value", "")

    def _subject_all_uuids(self, stype: str, plural: str) -> list:
        """Every subject uuid of *stype* in scope (for an ``include-all`` expansion)."""
        if stype == "party":
            items = self.parties(include_imports=True, stop_at_ssp=True)
        elif stype == "location":
            items = self.locations(include_imports=True, stop_at_ssp=True)
        else:
            getter = getattr(self, plural, None)
            items = getter() if callable(getter) else []
        return [i.get("uuid", "") for i in items if isinstance(i, dict) and i.get("uuid")]

    def subjects(self, subjects: list) -> list:
        """Return a copy of a selection-form ``subjects[]`` array with resolved subject detail.

        A helper for the *selection* form of subjects (an ``assessment-subject`` / task
        ``subjects`` entry: ``{type, include-all | include-subjects[], exclude-subjects[]}``),
        distinct from the reference form on an observation. For each entry, ``type`` selects
        the getters (:data:`_SUBJECT_TYPE_GETTERS`):

        * when ``include-subjects[]`` is present, each entry's ``subject-uuid`` is resolved
          and annotated in place with a ``title`` (``name`` for a party, the SSP-style title
          for an inventory-item, else ``title``); a ``component`` subject also gains its
          ``type`` and ``asset-type``;
        * when ``include-all`` is present, the matching plural getter enumerates every
          subject of that type in scope and an ``include-subjects`` array is materialized from
          them in the same annotated shape.

        Location / party lookups are confined to the assessment chain + the SSP
        (``stop_at_ssp``). The input array is not mutated. ``exclude-subjects`` is left as-is.
        """
        result = copy.deepcopy(subjects) if subjects else []
        for subj in result:
            if not isinstance(subj, dict):
                continue
            stype = subj.get("type", "")
            if stype not in self._SUBJECT_TYPE_GETTERS:
                continue
            if subj.get("include-subjects"):
                for inc in subj["include-subjects"]:
                    if isinstance(inc, dict):
                        self._enrich_include_subject(inc, stype)
            elif "include-all" in subj:
                plural = self._SUBJECT_TYPE_GETTERS[stype][1]
                materialized = []
                for uuid in self._subject_all_uuids(stype, plural):
                    inc = {"subject-uuid": uuid, "type": stype}
                    self._enrich_include_subject(inc, stype)
                    materialized.append(inc)
                subj["include-subjects"] = materialized
        return result


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# DEVELOPER NOTE — assessment getters are being built incrementally.
# ---------------------------------------------------------------------------
# See docs/assessment_getters.md for the full plan and docs/METHOD_PATTERNS.md for the
# conventions. Built so far (step 1): the shared enrichment helpers above and the
# intra-document object resolvers (_AssessmentObjectsMixin). Still to come: the index/full
# public getters per model, the §3.5 local-definitions shadowing/chain machinery, and the
# opt-in cross-import control/target resolution.
#
# When TASK getters are implemented, mirror the catalog/profile control-getter pattern for
# payload/ownership (see oscal_controls.get_control_by_id): tasks nest (a task may contain
# child `tasks`), so a `depth: Optional[int] = None` parameter prunes ONLY the nested
# `tasks` collection via prune_tree_copy(..., child_keys=("tasks",)); the task node's own
# intrinsic content is always returned in full. All getters return SAFE COPIES.
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class AssessmentPlan(_LocalDefinitionGettersMixin, OSCAL):
    """OSCAL Assessment Plan (AP / SAP) model.

    Represents an assessment plan that defines the scope, assets, activities,
    and tasks for a security assessment. Subclasses ``OSCAL``; local-definition
    component / inventory-item getters come from :class:`_LocalDefinitionGettersMixin`.
    """
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class AssessmentResults(_AssessmentObjectsMixin, _LocalDefinitionGettersMixin, OSCAL):
    """OSCAL Assessment Results (AR / SAR) model.

    Represents the findings, observations, and risks produced by executing an
    assessment plan. Subclasses ``OSCAL``; observations/risks/findings are nested under
    each ``result`` (see :class:`_AssessmentObjectsMixin`).
    """
    def _init_common(self):
        super()._init_common()        # run OSCAL's common init first

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
_EMPTY_POAM_TREE: dict[str, list] = {
    "poam-items": [], "observations": [], "findings": [], "risks": [],
}


class POAM(_AssessmentObjectsMixin, _LocalDefinitionGettersMixin, OSCAL):
    """OSCAL Plan of Action and Milestones (POA&M) model.

    Represents tracked security findings and their planned remediation milestones.
    Subclasses ``OSCAL``; observations/risks/findings are top-level (see
    :class:`_AssessmentObjectsMixin`).

    Attributes:
        poam_tree (dict): A lightweight, UI-oriented view of the POA&M's cross-reference
            surface — the POA&M analog of ``SSP.implementation_tree`` /
            ``Catalog.controls_tree`` — with four array-valued keys, each always present
            (empty by default):

            * ``poam-items`` — one ``{"uuid", "title", "related-findings",
              "related-observations", "related-risks"}`` node per ``poam-items`` entry.
              The three ``related-*`` values are flat lists of the referenced **uuid
              strings** (the ``finding-uuid`` / ``observation-uuid`` / ``risk-uuid`` values
              pulled out of their wrapper objects).
            * ``observations`` — one ``{"uuid", "title", "methods", "types"}`` node per
              top-level ``observations`` entry (``methods`` / ``types`` copied as-is).
            * ``findings`` — one ``{"uuid", "title", "related-observations",
              "related-risks"}`` node per top-level ``findings`` entry (the two
              ``related-*`` values are flat uuid-string lists, as above).
            * ``risks`` — one ``{"uuid", "title", "related-observations"}`` node per
              top-level ``risks`` entry (uuid-string list).

            Built from this document's own content only (no import dependency) when the
            POA&M is minimally valid, and refreshed on validation and content mutation. See
            :meth:`_build_poam_tree`.
    """
    def _init_common(self):
        """Initialize POA&M-specific state, then build ``poam_tree`` if valid."""
        super()._init_common()        # run OSCAL's common init first
        self.poam_tree: dict[str, list] = copy.deepcopy(_EMPTY_POAM_TREE)
        if self.is_minimally_valid:
            self._build_poam_tree()

    # -------------------------------------------------------------------------
    def _poam_root(self) -> dict[str, Any]:
        """Return the ``plan-of-action-and-milestones`` root object, or ``{}``."""
        if not isinstance(self._dict, dict):
            return {}
        root = self._dict.get("plan-of-action-and-milestones")
        return root if isinstance(root, dict) else {}

    # -------------------------------------------------------------------------
    def validate(self, format: str = "") -> bool:
        """Validate the POA&M, then (re)build ``poam_tree`` on success.

        Extends :meth:`OSCAL.validate` so the view is refreshed the moment the content is
        found to be valid OSCAL; an invalid POA&M exposes an empty tree.

        Args:
            format (str, optional): Accepted for API compatibility with the base method;
                does not alter the validation path.

        Returns:
            bool: True when every validation phase passes.
        """
        result = super().validate(format=format)
        if self.is_minimally_valid:
            self._build_poam_tree()
        else:
            self.poam_tree = copy.deepcopy(_EMPTY_POAM_TREE)
        return result

    # -------------------------------------------------------------------------
    def _on_content_mutated(self) -> None:
        """Rebuild ``poam_tree`` after any content edit.

        Chains to the base hook (revision stamp) then refreshes the view so edits to the
        poam-items / observations / findings / risks arrays are reflected.
        """
        super()._on_content_mutated()
        if self.is_minimally_valid:
            self._build_poam_tree()

    # -------------------------------------------------------------------------
    @staticmethod
    def _ref_uuids(entries: Any, key: str) -> list:
        """Flatten a list of reference objects to the list of their *key* uuid values.

        E.g. ``related-findings`` (``[{"finding-uuid": "…", "remarks": "…"}, …]``) with
        ``key="finding-uuid"`` becomes ``["…", …]`` — the wrapper object and its other
        fields are dropped, per the ``poam_tree`` contract. Entries missing/blank on *key*
        are skipped.
        """
        return [e.get(key) for e in (entries or [])
                if isinstance(e, dict) and e.get(key)]

    # -------------------------------------------------------------------------
    def _build_poam_tree(self) -> dict[str, list]:
        """(Re)build :attr:`poam_tree` from the current ``_dict``.

        The whole tree is freshly constructed (new dicts, new lists of immutable
        uuid/method/type strings), so it shares no state with ``_dict`` — callers may read
        it freely without risk of mutating the document.

        Returns:
            dict: The freshly built ``poam_tree``.
        """
        root = self._poam_root()

        poam_items = [
            {
                "uuid": item.get("uuid", ""),
                "title": item.get("title", ""),
                "related-findings": self._ref_uuids(item.get("related-findings"), "finding-uuid"),
                "related-observations": self._ref_uuids(item.get("related-observations"), "observation-uuid"),
                "related-risks": self._ref_uuids(item.get("related-risks"), "risk-uuid"),
            }
            for item in root.get("poam-items", []) or [] if isinstance(item, dict)
        ]
        observations = [
            {
                "uuid": obs.get("uuid", ""),
                "title": obs.get("title", ""),
                "methods": list(obs.get("methods", []) or []),
                "types": list(obs.get("types", []) or []),
            }
            for obs in root.get("observations", []) or [] if isinstance(obs, dict)
        ]
        findings = [
            {
                "uuid": fnd.get("uuid", ""),
                "title": fnd.get("title", ""),
                "related-observations": self._ref_uuids(fnd.get("related-observations"), "observation-uuid"),
                "related-risks": self._ref_uuids(fnd.get("related-risks"), "risk-uuid"),
            }
            for fnd in root.get("findings", []) or [] if isinstance(fnd, dict)
        ]
        risks = [
            {
                "uuid": rsk.get("uuid", ""),
                "title": rsk.get("title", ""),
                "related-observations": self._ref_uuids(rsk.get("related-observations"), "observation-uuid"),
            }
            for rsk in root.get("risks", []) or [] if isinstance(rsk, dict)
        ]

        self.poam_tree = {
            "poam-items": poam_items, "observations": observations,
            "findings": findings, "risks": risks,
        }
        return self.poam_tree

    # -------------------------------------------------------------------------
    def poam_item(self, uuid: str, _seen: "frozenset | None" = None) -> Optional[dict]:
        """Return a top-level ``poam-item`` by uuid, as a safe copy, or None.

        Applies the same cross-reference handling as :meth:`finding`: every
        ``origins[].actors[]`` array in the item's hierarchy is populated via
        :meth:`actor`, and three arrays are inserted from the item's reference lists —
        ``findings`` (via :meth:`finding` for each ``related-findings[].finding-uuid``),
        ``observations`` (via :meth:`observation` for each
        ``related-observations[].observation-uuid``), and ``risks`` (via :meth:`risk` for
        each ``related-risks[].risk-uuid``). Each injected object is itself fully resolved
        (a finding carries its own observations/risks, actors are populated throughout).
        ``_seen`` is the internal cycle-guard path passed to the child getters.
        """
        if not uuid:
            return None
        base = None
        for item in self._poam_root().get("poam-items", []) or []:
            if isinstance(item, dict) and item.get("uuid") == uuid:
                base = copy.deepcopy(item)
                break
        if base is None:
            return None
        self._populate_actors(base)
        seen = _seen or frozenset()
        base["findings"] = [
            f for ref in base.get("related-findings", []) or []
            if isinstance(ref, dict) and ref.get("finding-uuid")
            and (f := self.finding(ref["finding-uuid"], seen)) is not None
        ]
        base["observations"] = [
            o for ref in base.get("related-observations", []) or []
            if isinstance(ref, dict) and ref.get("observation-uuid")
            and (o := self.observation(ref["observation-uuid"], seen)) is not None
        ]
        base["risks"] = [
            r for ref in base.get("related-risks", []) or []
            if isinstance(ref, dict) and ref.get("risk-uuid")
            and (r := self.risk(ref["risk-uuid"], seen)) is not None
        ]
        return base

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Register model classes so OSCAL factory methods return typed instances.
register_model("assessment-plan", AssessmentPlan)
register_model("assessment-results", AssessmentResults)
register_model("plan-of-action-and-milestones", POAM)
