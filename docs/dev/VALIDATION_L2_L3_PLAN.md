# Build Plan — Step 2: L2 expansion + L3 engine

Status: planning (2026-10-02). Supersedes the "defer all scoped constraints to L3" stance
with the feasibility analysis in memory (`oscal-l2-l3-feasibility`). Goal: push ~94–97% of
allowed-values and the simpler constraint families into **L2** (`is_valid`), reserving a
small genuinely-XPath remainder for **L3** (`is_fully_compliant` via `validate_full`).

Guiding model (unifies L2 + L3): **every constraint is evaluated at its DEFINITION node,
resolving its forward `target` from there.** L2 uses a native dict evaluator restricted to
forward child paths + `@flag`/`@name` predicates; L3 uses `elementpath` over the XML
projection with the context item set to the same definition node. One context model, two
evaluators differing only in which target shapes they admit.

---

## Phase 0 — Index enrichment (parser; forces a 2.1.0 regen)

Everything downstream needs richer index data. Status below. Index at **2.1.0**; all three
DBs (repo-root `support/`, `tests/support/`, bundled zip) regenerated; full suite green.

0.1 ✅ **DONE — Capture constraint identity.** `id` added to every raw-captured family
    constraint (allowed-values already had `id`); `name` added for `index`/`index-has-key`.
    `handle_constraints`; tested in `test_support_index_version.py::TestConstraintCapture`.

0.2 ⤳ **MOVED to Phase 1** (evaluate at definition node). Not done as an index change — see
    the note after 0.4: inline predicate evaluation in the forward-path evaluator supersedes
    pre-recording a separate definition node + flattened conditions.

0.3 ⤳ **MOVED to Phase 1.** **Why:** the extracted `conditions` are *flattened* and lose
    step position. Real data proves this is unsafe to partition by type:
    `oscal-control-statement-part-prop-name` has target
    `part[@name=('assessment','assessment-method')]/prop/@name` and yields a
    `flag-in name=(assessment,…)` condition — but that `@name` is on the **intermediate
    `part` step**, while the *governed* leaf flag is also `@name` (the prop's). A type-based
    "flag-* ⇒ context-gate" split would mis-evaluate it. The forward-path evaluator (Phase 1)
    applies each predicate **in place while traversing the target from the definition
    context**, so there is nothing to partition. The flattened `conditions` stay for the
    current walk's backward compat; the new evaluator ignores them.

0.4 ⤳ **Phase 1.2 (co-land with walk wiring).** Reclassifying L2-A/L2-B targets to `valid`
    *before* the union/forward-path walk exists would re-introduce the very false positives
    step-2-part-1 removed (the current per-constraint walk can't evaluate context gates).
    So the classification change MUST ship together with the evaluator.

0.5 ✅ **DONE — Capture `<key-field>`s** (as `key-fields: [target,…]`) for `is-unique` /
    `index` / `index-has-key`. `handle_constraints`; tested.

0.6 ✅ Parser tests added; 2.1.0 regen of all three DBs; full suite 1980 passed.

---

## Phase 1 — L2-A allowed-values with union semantics ✅ DONE (2026-10-02, index 2.2.0)

1.1 ✅ **Union evaluator** in `oscal_content.py` (`_resolve_allowed_values_union`,
    `_find_gate_context`, reusing the prototype `_partition_conditions` /
    `_context_gates_met` / `_target_filters_met`). Rules as specified: in-scope = context
    gates met at the **definition context** + target-filters met at the **leaf**;
    `allow-other` least-restrictive; union of in-scope sets; no-in-scope ⇒ no opinion.
    Context is resolved WITHOUT a recorded def-path: `_find_gate_context` picks the nearest
    enclosing instance that owns the gate flag — which *is* the node `(.)` points at for
    L2-A (the gate flag belongs to the definition context by construction). Exact for L2-A;
    element-`@name` gates (L2-B) can collide and stay L3.

1.2 ✅ **Wired into `_walk_instance`.** Added `ancestor_instances` (threaded root-first);
    the per-flag allowed-values loop now collect-then-decides via the union resolver with
    `chain = [instance] + reversed(ancestor_instances)`.

1.3 ✅ **Classifier** `_target_is_l2_context_gated` + extended
    `_classify_allowed_values_levels` so a node is `valid` when every allowed-values is
    native **or** L2-A. Tests: `test_constraint_level_classifier.py::TestContextGatedL2`,
    `test_l2_allowed_values_union.py` (20), and the real-walk cases in
    `test_content_validation.py::TestScopedInventoryPropNames`
    (software ⇒ `vendor-name` ok; policy ⇒ flagged; bogus ⇒ flagged).

1.4 ✅ Published 800-53 / FedRAMP resolved catalogs stay L2-valid (nested `item` is L2-B,
    still deferred); genuine bogus scoped values now fail at **L2**. Full suite 1990 passed.

## Phase 1b — L2-B element-`@name`-gated allowed-values ✅ DONE (2026-10-02, index 2.3.0)

Reverse-path matcher against the instance ancestor chain (no XML, no def-path recorded):

1b.1 ✅ **Parser** `metaschema_parser._parse_l2b_target` → a reverse-match spec
    `{leaf, segments:[{axis: child|descendant, elem, names}]}` for the restricted grammar
    (element steps with `@name`/`has-oscal-namespace` predicates, child/descendant axes,
    one leaf `@flag`; alternation/functions/absolute/axes → `None`). Cached on each L2-B
    constraint as `l2b-spec` at classify time (the classifier promotes a node to `valid`
    when every allowed-values is native **or** L2-A **or** L2-B).

1b.2 ✅ **Evaluator** `oscal_content._l2b_in_scope(spec, use_name, inst, ancestors)` —
    the governed element (last segment) must match the leaf's element name **and its own
    `@name` predicate** (so `prop[@name='method']/@value` governs only `method` props); the
    earlier segments reverse-match up the ancestor chain honoring child vs descendant axes.
    The walk now threads a `(use_name, instance)` ancestor chain; `_resolve_allowed_values_union`
    routes spec-bearing constraints through `_l2b_in_scope`, flag-gated/native ones through
    `_find_gate_context`.

1b.3 ✅ Verified: published 800-53 + FedRAMP LOW/HIGH resolved catalogs are `is_valid` with
    **zero** allowed-values errors; `item`/`objective` nested parts pass, a bogus nested
    part name is flagged at L2, `vendor-name` still correct. Full suite **2007 passed**.

**Result:** L2 now covers **175/189 (92%)** of allowed-values. The remaining 14 sit on
nodes that also carry a genuinely-L3 constraint (alternation `|` / cross-path), so the
per-node all-or-nothing rule correctly keeps them `fully-compliant` until the L3 engine.

### Gotcha fixed mid-flight
The L2-B `names` were first emitted as Python `set`s → the index JSON dump raised
`set is not JSON serializable` (and, because `regen` clears processed *before* re-parsing,
briefly left v1.1.1 with no processed index). Fixed by emitting sorted **lists**; re-ran a
clean regen. The spec stores lists; membership checks are list-compatible.

---

## Phase 2 — Simple families at L2

2.1 ✅ **matches DONE (2026-10-02, index 2.4.0).** `handle_constraints` captures
    `level`/`regex`/`datatype`; `metaschema_parser._parse_matches_target` resolves the L2
    shapes (`@flag`, `.`, `.[@f=…]`, `.[@f=…]/@g`) to a `match-spec` (child-path `l2b`
    matches stay L3 — need forward JSON traversal). Classifier promotes ERROR-level matches
    with a self/own-flag target + a check to `valid`/`handled`. `oscal_content` evaluates
    them at the definition node (`_eval_node_matches` + `_matches_resolve_value` +
    `_apply_matches`, reusing `_check_datatype` for the datatype half) at two injection
    points: node-level (dicts / fields-with-flags, e.g. `hash`) and the scalar-child branch
    (bare-string fields, e.g. `country`). New error-type **`matches`**, folded into the
    `data-types` phase and added to `IMPORT_NONBLOCKING_ERROR_TYPES`. Verified: published
    800-53/FedRAMP catalogs clean (0 matches errors); bad hash length / bad country / wrong
    `@algorithm` scoping all correct. Full suite **2018 passed**.
2.2 ✅ **has-cardinality DONE (2026-10-02, index 2.5.0).** `_parse_cardinality_target`
    parses the L2 subset — an optional self-gate `.[@f=…]` plus exactly ONE child element
    step `elem[@name=…]` (e.g. `part[@name=('objective',…)]`, `prop[@name='method']`,
    `.[@name='objective']/prop[@name='method']`); two-level paths, alternation, `//`,
    functions stay L3. Classifier promotes ERROR-level ones with a bound to a `card-spec`.
    `oscal_content._eval_node_cardinality` + `_count_cardinality_target` + `_find_child_index`
    count the child collection (JSON key from the def node's child index) vs min/max-occurs.
    New error-type **`has-cardinality`** — non-blocking (value-quality), reported in the
    `cardinality` phase for `is_valid`. These live in the assessment-plan/results models
    (`local-objective`, `activity`, `assessment-part`). Verified: real AWS assessment
    plan/results clean (0 errors); a local-objective with 2 `objective` parts (max=1) is
    flagged. Full suite **2028 passed**.
2.3 ✅ **expect DONE (2026-10-02, index 2.7.0).** A restricted boolean-test AST
    (`_parse_expect` / `_parse_test_bool`: `and`/`or`/`not`/`exists`/child-existence/
    `path = value-set`) + `oscal_content._eval_test_bool` / `_resolve_test_path` /
    `_eval_node_expect`. **Completeness-only** at L2 (per decision): positive requirements
    (`require-statement`, `citation-title`) are promoted; a top-level `not(...)` prohibition
    (`not(@method='merge')`, `not(exists(@depends-on))`) stays L3 — they conflict with legal
    content and `set_merge()`. New error-type **`constraint-violation`** (non-blocking).
    Targets: `.` (always) or `.[PRED]` (child-existence applicability); functions
    (`starts-with`/comparisons) stay L3. Verified: no-statement/non-withdrawn control
    flagged, withdrawn exempt, citation-without-title flagged; published content clean.
2.4 ✅ **New `constraints` phase** (per decision): `matches` / `has-cardinality` /
    `constraint-violation` report under `validation_status["constraints"]` (not folded into
    data-types/cardinality, which stay pure). All three are non-blocking (value-quality).
2.5 ✅ **Mutation gate refinement:** `_validate_subtree` (insert_control/insert_group) now
    rejects only structural + `invalid-type` + `allowed-values`; the constraint families
    (`matches`/`has-cardinality`/`constraint-violation`) are remediable and never block a
    faithful-copy insert or profile resolution (so a statement-less control isn't dropped).
    Synthetic fixtures across profile_resolve / metadata_carry / overlay-chain data /
    catalog roundtrip given statement parts. Full suite **2041 passed**.

**PHASE 2 COMPLETE.** L2 now enforces, beyond the NIST JSON Schema: native + context-/
element-gated allowed-values (L2-A/B), regex/datatype `matches`, `has-cardinality`, and
completeness `expect`.

---

## Phase 3 — Referential integrity + uniqueness (is-unique / index / index-has-key)

3.1 Generalize the existing `_id_index`/`_uuid_index` into a scoped, key-field-driven
    index built during the walk (keyed by the `<key-field>`s from 0.5), per `index`
    definition scope.
3.2 **is-unique (14, all L2):** flag duplicate keys within scope.
3.3 **index-has-key (6 simple, L2):** referential integrity — a reference resolves to an
    index entry (same-document). Complex `href`-fragment ones → L3.
3.4 Tree-wide `//` indexes (`//part`, `//prop`) → L3 (or a dedicated full-tree index pass).

---

## Phase 4 — L3 engine (`validate_full`) — DISCUSS TARGETS FIRST

Only the genuine remainder: ungated `//`, alternation `|`, cross-path, XPath-function
tests, tree-wide indexes.

4.1 Project `_dict` → XML (reuse the converter).
4.2 Evaluate each L3 target/test with **`elementpath`** (`XPath3Parser` + `XPathContext`
    with `item` = the definition node), register a `has-oscal-namespace` custom function.
4.3 Map results → `full_validation_errors`; set the `is_fully_compliant` tri-state.
4.4 Cache the L3 result; invalidate on mutation (and on `validate()` — already resets).
4.5 Precondition discussion (per `oscal-step2-constraint-eval-nuances`): absolute vs
    context-relative targets, XML-oriented paths over JSON-primary data.

---

## Phase 5 — OSCALSupport HTML coverage report ✅ DONE (2026-10-02, brought forward)

`OSCALSupport.coverage_report_html(version)` (+ `_coverage_for_model`) emits a self-contained
HTML report from the index: headline **constraint coverage** (L2-handled vs unhandled, de-duped
by id) plus per-model constraint tables with tier + note, and an L1-structural / L2-datatype
baseline (per node-occurrence, labelled). **L3 is folded into `unhandled`** until that engine
lands (to be re-split later). Generated artifact: `docs/validation_coverage_report.html`.
v1.2.3 snapshot: 532/929 (57%) constraints at L2; 397 unhandled (is-unique 115, matches 66,
index 69, index-has-key 53, expect 34, has-cardinality 32, allowed-values 28). Tests in
`test_support_index_version.py::TestCoverageReport`.

---

## Then: conversion glitches (`oscal-conversion-glitches-todo`).

## Sequencing rationale
Phase 0 is the keystone (regen-gated). Phase 1 is prototyped before wiring because it
touches the hot validation path and previously regressed freeform props. Phases 2–3 are
largely independent and can parallelize after Phase 0. Phase 4 needs a design sign-off.
