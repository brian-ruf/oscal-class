"""Library-defined referential-integrity rules (Phase 3).

Some cross-references that OSCAL documents in prose are **not** encoded as machine-checkable
``index-has-key`` constraints in the published metaschema. The clearest example is
``by-component/@component-uuid``: the SSP (and component-definition) metaschema names the
flag and documents that it references a declared component, but defines no constraint tying
it to ``system-implementation/component/@uuid``. So neither a metaschema-driven validator nor
oscal-cli flags a dangling ``component-uuid``.

This module supplies those missing rules as **library-defined** checks, evaluated JSON-natively
alongside the metaschema-derived referential specs. Two kinds live here: per-model *reference*
rules (:func:`evaluate_library_reference_rules`, e.g. ``by-component/@component-uuid`` →
``component``) and a model-agnostic *global identifier uniqueness* check
(:func:`evaluate_global_identifier_uniqueness`) that flags duplicate bare ``id`` / ``uuid``
values within a single document — another invariant OSCAL documents in prose (and in the UUID
datatype) but does not encode as a machine-checkable ``is-unique`` constraint. Every finding
they produce is tagged ``rule-source="library"`` (vs ``"metaschema"``) and carries a standard
severity ``level`` (ERROR/WARNING/INFORMATIONAL), so callers can tell spec-mandated errors from
the library's own additions and filter by severity. These checks report on the separate
``references`` validation dimension and never affect :attr:`OSCAL.is_valid`.

A rule is a dict:
    id          — stable identifier for the rule (appears on the finding as ``rule-id``)
    level       — "ERROR" | "WARNING" | "INFORMATIONAL"
    field       — the JSON flag/field holding the reference value (for the finding's ``field``)
    description — human-readable statement of the invariant
    target      — {"scope": [json-key, …], "collection": <key>, "key": <flag/field>}
                  the set of VALID key values: every ``collection`` object found anywhere under
                  the ``scope`` subtree contributes its ``key`` value.
    ref         — {"scope": [json-key, …], "collection": <key>, "key": <flag/field>}
                  the referencing values that must each exist in the target set.

``scope`` is a path of JSON keys from the model body (e.g. the object under the
``system-security-plan`` root key). An empty scope means the whole body. ``collection`` objects
are gathered recursively, so a reference nested at any depth (e.g. ``by-component`` under either
an ``implemented-requirement`` or one of its ``statement``\\ s) is covered by one rule.
"""
from __future__ import annotations

from typing import Any

# Per-model library reference rules. Seeded with the by-component → component invariant for
# the two models that carry it. FOLLOW-UPS (not yet implemented): implemented-component/
# @component-uuid → component (SSP inventory-items); set-parameter/@param-id → parameter;
# control-id references into the imported profile/catalog (cross-document).
_LIBRARY_REFERENCE_RULES: dict[str, list[dict]] = {
    "system-security-plan": [
        {
            "id": "lib-ssp-by-component-component-uuid",
            "level": "ERROR",
            "field": "component-uuid",
            "description": ("by-component/@component-uuid must reference the @uuid of a "
                            "component declared in system-implementation."),
            "target": {"scope": ["system-implementation"], "collection": "components", "key": "uuid"},
            "ref":    {"scope": ["control-implementation"], "collection": "by-components", "key": "component-uuid"},
        },
    ],
    "component-definition": [
        {
            "id": "lib-cdef-by-component-component-uuid",
            "level": "ERROR",
            "field": "component-uuid",
            "description": ("by-component/@component-uuid must reference the @uuid of a "
                            "component declared in the component-definition."),
            "target": {"scope": [], "collection": "components", "key": "uuid"},
            "ref":    {"scope": [], "collection": "by-components", "key": "component-uuid"},
        },
    ],
}


def library_reference_rules(model: str) -> list[dict]:
    """Return the library reference rules defined for *model* (empty list if none)."""
    return _LIBRARY_REFERENCE_RULES.get(model, [])


def _subtree(body: Any, scope: list[str]) -> Any:
    """Descend *body* through the ``scope`` JSON keys; return the subtree or None."""
    node = body
    for key in scope:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _collect_under_key(obj: Any, key: str, out: list, path: str) -> None:
    """Recursively collect ``(item, path)`` for every dict stored (directly or as a list
    element) under JSON *key* anywhere within *obj*."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}/{k}"
            if k == key:
                if isinstance(v, list):
                    for i, it in enumerate(v):
                        if isinstance(it, dict):
                            out.append((it, f"{child_path}[{i}]"))
                elif isinstance(v, dict):
                    out.append((v, child_path))
            _collect_under_key(v, key, out, child_path)
    elif isinstance(obj, list):
        for i, it in enumerate(obj):
            _collect_under_key(it, key, out, f"{path}[{i}]")


def evaluate_library_reference_rules(model: str, body: dict, base_location: str) -> list[dict]:
    """Evaluate *model*'s library reference rules against the model body (``_dict[model]``).

    Returns a list of normalized findings, each ``error-type="unresolved-reference"`` with
    ``rule-source="library"``, the rule's ``level``/``rule-id``, and the offending value +
    location. Only references whose value is a non-empty string and that is absent from the
    target key set are reported (a missing/blank reference is left to structural validation).
    """
    findings: list[dict] = []
    if not isinstance(body, dict):
        return findings
    for rule in library_reference_rules(model):
        tgt, ref = rule["target"], rule["ref"]
        # Build the set of valid key values.
        tgt_scope = _subtree(body, tgt["scope"])
        valid: set = set()
        if tgt_scope is not None:
            items: list = []
            _collect_under_key(tgt_scope, tgt["collection"], items, "")
            for it, _ in items:
                v = it.get(tgt["key"])
                if isinstance(v, str) and v:
                    valid.add(v)
        # Check each referencing value.
        ref_scope = _subtree(body, ref["scope"])
        if ref_scope is None:
            continue
        refs: list = []
        scope_prefix = base_location + ("/" + "/".join(ref["scope"]) if ref["scope"] else "")
        _collect_under_key(ref_scope, ref["collection"], refs, scope_prefix)
        for it, loc in refs:
            value = it.get(ref["key"])
            if not isinstance(value, str) or not value:
                continue
            if value not in valid:
                findings.append({
                    "error-type": "unresolved-reference",
                    "level": rule["level"],
                    "rule-source": "library",
                    "rule-id": rule["id"],
                    "location": loc,
                    "field": ref["key"],
                    "value": value,
                    "identifier": value,
                    "detail": rule["description"],
                })
    return findings


# The bare identifier flags whose value must be unique within a single document. Scoped
# *reference* flags (``party-uuid``, ``component-uuid``, ``role-id``, ``control-id``,
# ``param-id``, …) are intentionally excluded — they repeat legitimately and may recur
# across imported files. Each field is pooled on its own (an ``id`` never collides with a
# ``uuid``).
_GLOBAL_UNIQUE_FIELDS = ("id", "uuid")


def evaluate_global_identifier_uniqueness(body: Any, base_location: str) -> list[dict]:
    """Flag duplicate ``id`` / ``uuid`` values within a single document body.

    OSCAL expects every ``@id`` and every ``@uuid`` to be unique within a document, but the
    published metaschema does not encode that as an ``is-unique`` / ``index`` constraint, so
    no metaschema-driven validator (this library or oscal-cli) catches a collision. This
    library-defined check fills that gap, evaluated JSON-natively as a ``references``-tier
    finding (``rule-source="library"``) that never gates :attr:`OSCAL.is_valid`.

    Only the bare ``id`` and ``uuid`` flags are considered, each pooled separately; the
    scoped reference flags in :data:`_GLOBAL_UNIQUE_FIELDS`'s exclusion note are not. Scope
    is **this one document only**: *body* is a single file's model instance, so the same
    party / resource / component appearing in more than one file of an import collection is
    expected and never reported — only a repeat within the same file is.

    Each occurrence after the first emits one ``duplicate-key`` finding (``level="ERROR"``)
    locating the repeat and naming where the value was first seen.

    Args:
        body (Any, required): The model instance (``_dict[model]``) to scan.
        base_location (str, required): Location prefix for findings (e.g. ``/catalog``).

    Returns:
        list[dict]: One normalized finding per duplicate occurrence (empty when all unique).
    """
    findings: list[dict] = []
    if not isinstance(body, dict):
        return findings
    seen: dict[str, dict[str, str]] = {field: {} for field in _GLOBAL_UNIQUE_FIELDS}

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}/{key}"
                if key in _GLOBAL_UNIQUE_FIELDS and isinstance(value, str) and value:
                    first = seen[key].get(value)
                    if first is None:
                        seen[key][value] = child
                    else:
                        findings.append({
                            "error-type":  "duplicate-key",
                            "level":       "ERROR",
                            "rule-source": "library",
                            "rule-id":     f"lib-global-unique-{key}",
                            "location":    child,
                            "field":       key,
                            "value":       value,
                            "identifier":  value,
                            "detail":      (f"duplicate {key} '{value}' (first seen at "
                                            f"{first}); every {key} must be unique within a "
                                            "single OSCAL document."),
                        })
                _walk(value, child)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")

    _walk(body, base_location)
    return findings
