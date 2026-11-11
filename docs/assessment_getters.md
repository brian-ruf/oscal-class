# Assessment-Layer Getters — Design Plan (DRAFT for refinement)

Status: **draft for review.** Nothing here is implemented yet. The three assessment
classes (`AssessmentPlan`, `AssessmentResults`, `POAM`) are still bare stubs in
`oscal/oscal_assessment.py`. This document proposes the getter surface, mirroring the
patterns already established for `Catalog`/`Profile` (`oscal_controls.py`), `SSP` /
`ComponentDefinition` (`oscal_implementation.py`), and the common cross-reference layer
(`oscal_content.py`). We will refine this together before writing code.

---

## 1. Patterns these getters must follow

The library-wide getter conventions these proposals adhere to — safe copies, index-vs-full
split, injected-content-as-sibling, invalid-references-surface, `include_*` gating, `depth`
pruning, and the centralized cross-import cascade — are documented separately in
[METHOD_PATTERNS.md](METHOD_PATTERNS.md) ("Patterns getters must follow in this library").
One assessment-specific note on pattern 6 (`depth`): for assessment it applies to **`task`**
(a task nests `task`) via `child_keys=("tasks",)`, as the developer note already in
`oscal_assessment.py` calls out.

---

## 2. The three models (authoritative, from the metaschema index)

Structures below are extracted from `support/v1.2.3/*.json` (the parsed NIST
resolved-metaschema index). Cardinalities shown as `min..max`; `[]` = array.

### 2.1 AssessmentPlan (SAP)
```
assessment-plan
  uuid, metadata, import-ssp{href}
  local-definitions{ component[], inventory-item[], user[], objectives-and-methods[], activity[] }
  terms-and-conditions{ part[] }
  reviewed-controls{ control-selection[1..], control-objective-selection[] }   (1..1, required)
  assessment-subject[]{ type, include-all | include-subject[], exclude-subject[] }
  assessment-assets{ component[], assessment-platform[1..]{ uses-component[] } }
  task[]{ type, timing, dependency[], task[] (nested), associated-activity[], subject[], responsible-role[] }
  back-matter
```

### 2.2 AssessmentResults (SAR)
```
assessment-results
  uuid, metadata, import-ap{href}
  local-definitions{ objectives-and-methods[], activity[] }
  result[1..]{                                     ← observations/risks/findings live HERE, per result
    uuid, title, description, start, end,
    local-definitions{ component[], inventory-item[], user[], assessment-assets, assessment-task[] }
    reviewed-controls{ control-selection[1..], control-objective-selection[] }
    attestation[]{ responsible-party[], part[] }
    assessment-log{ entry[1..]{ logged-by[], related-task[] } }
    observation[]{ method[1..], type[], origin[], subject[], relevant-evidence[]{href}, collected, expires }
    risk[]{ statement, status, origin[], threat-id[], characterization[], mitigating-factor[],
            response[]{ lifecycle, origin[], required-asset[], task[] }, risk-log, related-observation[] }
    finding[]{ origin[], target{ type, target-id, status, implementation-status }, implementation-statement-uuid,
               related-observation[], associated-risk[] }
  }
  back-matter
```

### 2.3 POAM (Plan of Action & Milestones)
```
plan-of-action-and-milestones
  uuid, metadata, import-ssp{href} (0..1, optional), system-id
  local-definitions{ component[], inventory-item[], assessment-assets }
  observation[]      ← TOP-level (not nested under a result)
  risk[]             ← TOP-level
  finding[]          ← TOP-level
  poam-item[1..]{ origin[], related-finding[]{finding-uuid}, related-observation[]{observation-uuid},
                  associated-risk[]{risk-uuid} }
  back-matter
```

**Key structural difference that shapes the API:** in **AR** the assessment objects
(`observation`/`risk`/`finding`) are **nested under each `result`**; in **POA&M** they are
**top-level**. AP has none of them (it has `task`/`activity`/`assessment-subject` instead).

### 2.4 Canonical import chains

The models never import arbitrarily — there are exactly two chains, and every
cross-document resolution below follows one of them:

```
POA&M → SSP → [ Profile(s) → Catalog  |  Catalog ]
AR    → AP  → SSP → [ Profile(s) → Catalog  |  Catalog ]
```

- **POA&M imports the SSP directly** (`import-ssp`, optional).
- **AR imports only the AP** (`import-ap`); it reaches the SSP (and the controls/subjects
  it cites) **through the AP's own `import-ssp`** — there is no direct AR→SSP link.
- **AP imports the SSP** (`import-ssp`, required).

**Implication for resolution.** A control objective or subject an AR references is 3 hops
away (AR→AP→SSP→profile/catalog is 4). The base-class cascade
(`find_in_import_tree`/`_lookup_in_scope`, pattern #7) already recurses the *entire* import
tree depth-first, so `AR.get_party_by_uuid` / `get_control_by_id` resolve a party or control
defined in the SSP or catalog with no special handling — **provided the whole chain is
loaded/resolved** (`imports_resolved`). This is exactly why the cross-import injections in
§3.3 / §3.4 stay **opt-in**: they can require a multi-hop chain to be present, and should
degrade gracefully (ids only) when it is not.

---

## 3. Recurring cross-reference constructs (the shared resolvers to build)

Four constructs recur across the assessment-common definitions and drive most of the
"inject select data" work. Build each once as a module helper (like
`_enrich_responsibilities`) and apply it uniformly.

### 3.1 `origin` / `actor`  (observation, risk, finding, poam-item, response, log entry)
Raw: `origin[].actor[]{ type: "tool"|"assessment-platform"|"party", actor-uuid, role-id? }`
and `origin[].related-task[]{ task-uuid }`.
**Inject** on each actor: `title`/`name` resolved by `type` —
- `party` → `metadata.parties` via `get_party_by_uuid` (name/short-name),
- `assessment-platform` → `assessment-assets.assessment-platform` title (local),
- `tool` → a `component` title (local-definitions / assessment-assets);
plus `role` title from `role-id` via `get_role_by_id`. On each `related-task`, inject the
task `title`. Proposed helper: `_enrich_origins(doc, obj, task_index, platform_index,
component_index)`.

### 3.2 `subject` / assessment-subject  (AP subjects, task subjects, observation subjects, mitigating-factor, required-asset)
Raw: `{ subject-uuid, type: "component"|"inventory-item"|"location"|"party"|"user" }`,
or the selection form `include-all | include-subject[] | exclude-subject[]`.
**Inject** `title` resolved by `type` from local-definitions (component/inventory-item/user),
metadata (party/location), or the imported SSP's `system-implementation` (cross-import).
Placeholder on miss. Proposed helper: `_resolve_subject(doc, subject, indexes)`.

### 3.3 `reviewed-controls` / `control-selection`  (AP top-level; AR per-result; activity steps)
Raw: `control-selection[]{ include-all | include-control[]{control-id}, exclude-control[] }`
and `control-objective-selection[]`. **Inject** (opt-in, like `SSP.control(with_control=)`):
the resolved control objects fetched through the import chain
(AP: `import-ssp`→SSP→profile→catalog; AR: `import-ap`→AP→…). Default off (just the ids).

### 3.4 `finding.target` + related-X / associated-X  (intra-document references)
- `finding.target{ type: "statement-id"|"objective-id", target-id, status, implementation-status }`
  → resolve `target-id`: a *statement* to the SSP implemented-requirement statement
  (cross-import), an *objective* to the catalog control objective (cross-import). Opt-in.
- `related-observation.observation-uuid`, `associated-risk.risk-uuid`,
  `related-finding.finding-uuid` → **document-local** references; inject a short summary
  (`{uuid, title}`, or title + status for findings/risks) of the target object.

For 3.4's local references we need **intra-document by-uuid resolvers** (see §4).

---

### 3.5 `local-definitions` objects — chain resolution & shadowing  (NEW, applies to all three models)

Unlike the flat metadata/back-matter containers the current cascade handles, several
objects can be **(re)defined at more than one point along the import chain**. All three
assessment models allow `local-definitions.component` (and `inventory-item`, `user`,
`assessment-assets`, `objectives-and-methods`, `activity`); `component`/`inventory-item`/
`user` *also* exist in the SSP's `system-implementation`. So a reference to a component
uuid in an AR may match a definition in the AR itself, the AP, **and** the SSP.

**Resolution rule (nearest-wins, like profile overlay / `_collect_in_scope` first-wins):**

1. Search the chain **left-to-right = this document first, then down the imports**
   (AR → AP → SSP; POA&M → SSP). The **first** occurrence of a given uuid is
   **authoritative**.
2. The authoritative copy always carries a `source-document` annotation
   (`{uuid, href, imported}`, the existing `_collect_in_scope` shape) so the winner's
   origin is explicit — it may come from an imported document.
3. **Optional `include_shadowed=True`** adds a sibling `shadowed: [ … ]` array holding the
   other occurrences (full copies, each with its own `source-document`), in chain order
   (nearest loser first). Default `False` returns only the authoritative object.

**Which kinds reach how far** (nearest-wins shadowing; key field noted — mostly `uuid`,
but `objectives-and-methods` is keyed by `control-id`):

| local-definitions kind | Key | Containers searched, in chain order |
|---|---|---|
| `component` | uuid | assessment `local-definitions.components` (+ AR per-`result` `local-definitions` & `assessment-assets`) → SSP `system-implementation.components` |
| `inventory-item` | uuid | assessment `local-definitions.inventory-items` (+ AR per-result) → SSP `system-implementation.inventory-items` |
| `user` | uuid | assessment `local-definitions.users` (+ AR per-result) → SSP `system-implementation.users` |
| `assessment-assets` (its `component`/`assessment-platform`) | uuid | assessment models only (AR→AP, POA&M) — **no SSP hop** |
| `activity` | uuid | assessment models only (AR→AP) — **no SSP hop** |
| `task` | uuid | AR `results.local-definitions.tasks` (metaschema `assessment-task`) → AP top-level `tasks` — assessment chain only, **no SSP / earlier-model equivalent** |
| `objectives-and-methods` | **control-id** | assessment models only (AR→AP) — **no SSP hop**; *and additionally overlays the control* (see below) |

(Catalogs/profiles have none of these, so the cascade simply finds nothing deeper — no
special stop needed.) **Intra-document order** matters for AR (multiple component
containers): proposed order = top-level `local-definitions`, then each `result` in
document order (its `local-definitions` then its `assessment-assets`). *Confirm.*

**`objectives-and-methods` has TWO resolution dimensions.** Both apply:

1. **Shadowing (AR→AP, keyed by `control-id`)** — exactly like the rows above, but the
   nearest-wins key is `control-id` rather than `uuid`. If both an AR and its AP define an
   `objectives-and-methods` for the same `control-id`, the AR's is authoritative; the AP's
   is a shadowed copy (surfaced via `include_shadowed`). No SSP hop (SSP has none).
2. **Overlay onto the control (reaches profile/catalog)** — the authoritative
   `objectives-and-methods` carries a `control-id` plus augmenting `parts` intended to
   add/augment the control's `assessment-objective` / `assessment-method` parts. So it
   *also* resolves against the **control**, reached down the *control* chain (deeper than
   SSP → profile → catalog) — the same chain used by `reviewed-controls` / `finding.target`
   (§3.3 / §3.4). This overlay is opt-in (`include_controls`), and applies after shadowing
   selects the authoritative entry. *Merge-vs-list-separately of the augmenting parts is an
   open question (§7 Q10).*

**Plural getters** (`components()` …) default to one entry per uuid (nearest-wins), each
annotated with `source-document`; `include_shadowed=True` adds the `shadowed` sibling to
each winner. (Alternative: emit every occurrence flat — rejected as it breaks the index
contract. *Confirm.*)

## 4. New base/shared infrastructure

1. **Origin, subject, control-selection, target resolvers** — §3.1–3.4, as module helpers
   in a new `_assessment_enrich` section (parallel to `_enrich_responsibilities`, which we
   reuse for every `responsible-role`/`responsible-party` that nests inside these models).

2. **Object resolvers.** Two sub-groups by resolution scope:
   - **Intra-document** (`observation`/`risk`/`finding` references stay within the same
     document): `.observation()`, `.risk()`, `.finding()` (each keyed by uuid; **implemented**,
     build step 1). Scope: POA&M → top-level arrays; AR → search every `result`, annotating
     the owning `result` uuid. (A `finding.related-observation` / `associated-risk`, a
     `poam-item.related-finding`, etc. all resolve locally.) These use the short-noun
     detail-getter convention; a `get_*_by_uuid` resolver is **not** a separate method (the
     by-uuid lookup *is* the getter — see docs/NAMING_CONSISTENCY_PLAN.md §5).
   - **Chain-aware, nearest-wins** (shadowing per §3.5): `get_task_by_uuid` — AR
     `results.local-definitions.tasks` → AP top-level `tasks` (+ nested `tasks`); AP →
     top-level `tasks` (+ nested). Shares the §3.5 machinery (+ `include_shadowed`), but
     assessment-chain only. `get_activity_by_uuid` likewise (AR→AP `local-definitions`).
     `get_objectives_and_methods_by_control_id` likewise but **keyed by `control-id`**, and
     then additionally overlays the control (§3.5 dimension 2, opt-in).
   - **Open question:** implement as small per-class methods, or extend the generic
     `_COLLECTION_SPEC`/`_RESOLVE_KINDS` machinery? The intra-document ones are nested
     (AR results, nested tasks) and document-local; the chain-aware ones fit the §3.5 hook.
     Leaning per-class for the intra-document set, shared hook for the chain-aware set. (§7.)

3. **Model-aware container resolution + cross-chain local-definition resolvers** (§3.5).
   The flat `_COLLECTION_SPEC` assumes one container path reused for every doc in the
   chain, which fails here (`local-definitions.component` vs. `system-implementation.components`,
   and AR's several containers). Proposed generalization:
   - A per-class hook, e.g. `_local_def_containers(kind) -> list[(path, key_field)]`, that
     each model overrides to name where *its* objects of `kind` live **and the key field**
     (`uuid` for most, `control-id` for `objectives-and-methods`) — SSP →
     system-implementation; assessment → local-definitions + its result/assets containers.
     The cascade asks each document in the chain for its own containers rather than assuming
     one global path/key.
   - Shared cross-chain resolvers built on it: `get_component_by_uuid(uuid, include_shadowed=False)`,
     `get_inventory_item_by_uuid(...)`, `get_user_by_uuid(...)` — nearest-wins + optional
     `shadowed` (§3.5). The public `.component()`/`.inventory_item()`/`.user()` getters wrap
     these and then apply the SSP-style enrichment.
   - The existing SSP `.component()`/`.inventory_item()`/`.user()` (system-implementation
     only) should be re-expressed in terms of the same hook so one code path serves all
     models (see §7 Q5).

---

## 5. Proposed method inventory

Legend: **I** = index (plural, summarized), **F** = full (singular, enriched). All return
safe copies; plural → `list` (empty when none), singular → `Optional[dict]` (None on miss).

### 5.1 AssessmentPlan

| Method | Params | Injects | Returns |
|---|---|---|---|
| `tasks(depth=None)` **I** | `depth` prunes nested `tasks` | per task: `type`, `title`, timing summary, counts of nested tasks / associated-activities / subjects | `list[{uuid,type,title,timing,subtasks,activities,subjects}]` |
| `task(uuid, depth=None, resolve=True)` **F** | `depth` nested tasks; `resolve` toggles enrichment | nested `tasks` (pruned by depth); each `associated-activity` → full `activity` object (from local-definitions); `subject[]` resolved (§3.2); `dependency[].task-uuid` → task `title`; `responsible-role` enriched (`_enrich_responsibilities`) | full task copy |
| `activities()` **I** / `activity(uuid)` **F** | — | activity: `related-controls` resolved ids; `responsible-role` enriched; `step[]` kept full in F | index / full |
| `objectives_and_methods(include_controls=False, include_shadowed=False)` | `include_controls` fetches the control via the control chain; `include_shadowed` (§3.5, keyed by `control-id`, AR→AP) | nearest-wins by `control-id` + `source-document`; opt-in overlay onto the resolved control's objective/method parts (§3.5 dim. 2) | `list` |
| `reviewed_controls(include_controls=False, depth=None)` | `include_controls` fetches controls via import-ssp chain | selected/excluded control-ids; optional resolved control objects (§3.3) | `dict{control-selections, control-objective-selections, controls?}` |
| `assessment_subjects(resolve=True)` **I/F** | `resolve` | each subject resolved to `{subject-uuid,type,title}`; include-all / include / exclude preserved | `list` |
| `assessment_assets(include_components=False, include_shadowed=False)` | `include_components`, `include_shadowed` (§3.5; assessment-chain only, no SSP hop) | `assessment-platform[]` with `uses-component` → component title/type | `dict{components?, assessment-platforms}` |
| `components(include_shadowed=False)` / `component(uuid, include_shadowed=False)` | `include_shadowed` (§3.5 — resolves down to SSP) | mirror `SSP.component` shape (status, protocols, responsible-role enriched) + `source-document` | index / full |
| `inventory_items(include_shadowed=False)` / `inventory_item(uuid, include_shadowed=False)` | `include_shadowed` (→ SSP) | identical contract to the SSP getters (reuse) + `source-document` | index / full |
| `users(include_shadowed=False)` / `user(uuid, include_shadowed=False)` | `include_shadowed` (→ SSP) | identical to SSP `user` (role resolution) + `source-document` | index / full |
| `import_ssp()` | — | `{href}` + resolved SSP `object_uuid`/title when loaded in the import tree | `Optional[dict]` |

### 5.2 AssessmentResults

Because observations/risks/findings nest under `result`, the cross-result getters take an
optional `result_uuid` (None = across all results, each entry annotated with its
`result-uuid`).

| Method | Params | Injects | Returns |
|---|---|---|---|
| `results()` **I** | — | per result: `uuid,title,start,end`, counts of observations/risks/findings, reviewed-control count | `list` |
| `result(uuid, resolve=True)` **F** | `resolve` | full result; observations/risks/findings enriched (below); `reviewed-controls` ids; `assessment-log`, `attestation` responsibilities enriched | full result copy |
| `observations(result_uuid=None)` **I** | scope | per obs: `uuid,title,methods,types,collected`, subject count, origin actor summary, `result-uuid` | `list` |
| `observation(uuid, result_uuid=None)` **F** | scope | `origin` (§3.1), `subject[]` (§3.2), `relevant-evidence[].href` → back-matter resource stub (`include_resources`?) | full obs copy |
| `risks(result_uuid=None)` **I** | scope | per risk: `uuid,title,status,deadline`, counts of responses/characterizations/related-observations | `list` |
| `risk(uuid, result_uuid=None)` **F** | scope | `origin`; `related-observation.observation-uuid` → observation `{uuid,title}`; `response[]` (origins + nested `task`/`required-asset` subjects resolved); `mitigating-factor.subject[]` resolved | full risk copy |
| `findings(result_uuid=None)` **I** | scope | per finding: `uuid,title`, `target.{type,target-id,status}`, counts of related-observations/associated-risks | `list` |
| `finding(uuid, result_uuid=None, resolve_target=False)` **F** | `resolve_target` | `origin`; `target` (opt-in cross-import resolve, §3.4); `related-observation` → obs `{uuid,title}`; `associated-risk` → risk `{uuid,title,status}`; `implementation-statement-uuid` (opt-in SSP statement) | full finding copy |
| `activities()` / `activity(uuid)` | — | AR top-level `local-definitions.activity` (same as AP); `activity(uuid)` resolves AR→AP (§3.5, no SSP) | index / full |
| `objectives_and_methods(include_controls=False, include_shadowed=False)` | `include_controls`, `include_shadowed` (§3.5, control-id, AR→AP) | AR top-level `local-definitions.objectives-and-methods`; shadowing + control overlay, same as AP | `list` |
| `tasks(result_uuid=None, include_shadowed=False)` / `task(uuid, result_uuid=None, include_shadowed=False)` | result scope, `include_shadowed` (§3.5 → AP, no SSP) | AR per-`result` `local-definitions.tasks` (metaschema `assessment-task`); resolves/shadows against AP `tasks` + `source-document` | index / full |
| `components(result_uuid=None, include_shadowed=False)` / `component(uuid, result_uuid=None, include_shadowed=False)` | result scope, `include_shadowed` (§3.5 → SSP) | AR components live **only** in per-`result` `local-definitions` & `assessment-assets` (none top-level); sweep per §3.5 + `source-document` | index / full |
| `inventory_items(result_uuid=None, …)` / `inventory_item(uuid, …)` | result scope, `include_shadowed` (→ SSP) | per-result only; SSP contract + `source-document` | index / full |
| `users(result_uuid=None, …)` / `user(uuid, …)` | result scope, `include_shadowed` (→ SSP) | per-result only; SSP `user` contract + `source-document` | index / full |
| `import_ap()` | — | `{href}` + resolved AP handle (reaches SSP via the AP) | `Optional[dict]` |

### 5.3 POAM

Top-level objects — no result scoping.

| Method | Params | Injects | Returns |
|---|---|---|---|
| `poam_items()` **I** | — | per item: `uuid,title`, counts of related-findings/observations, associated-risks, origin actor summary | `list` |
| `poam_item(uuid)` **F** | — | `origin` (§3.1); `related-finding.finding-uuid` → finding `{uuid,title,target.status}`; `related-observation` → obs `{uuid,title}`; `associated-risk` → risk `{uuid,title,status}` | full item copy |
| `observations()` / `observation(uuid)` | `include_resources?` | identical contract to AR (top-level scope) | index / full |
| `risks()` / `risk(uuid)` | — | identical contract to AR (top-level scope) | index / full |
| `findings()` / `finding(uuid, resolve_target=False)` | `resolve_target` | identical contract to AR (top-level scope) | index / full |
| `components(include_shadowed=False)` / `component(uuid, include_shadowed=False)` | `include_shadowed` (§3.5 → SSP) | `local-definitions.component` (SSP shape) + `source-document` | index / full |
| `inventory_items(include_shadowed=False)` / `inventory_item(uuid, include_shadowed=False)` | `include_shadowed` (→ SSP) | reuse SSP contract + `source-document` | index / full |
| `assessment_assets(include_components=False, include_shadowed=False)` | `include_shadowed` (assessment-chain only) | same as AP | `dict` |
| `system_id()` | — | `{identifier-type, value}` | `Optional[dict]` |
| `import_ssp()` | — | `{href}` + resolved SSP handle (optional in POA&M) | `Optional[dict]` |

---

## 6. Return-shape examples (for review)

`AR.finding(uuid, resolve_target=True)` →
```jsonc
{
  "uuid": "...", "title": "...", "description": "...",
  "target": { "type": "objective-id", "target-id": "ac-2_obj",
              "status": {"state": "not-satisfied"},
              "implementation-status": {"state": "planned"},
              "objective": { /* resolved control objective, opt-in */ } },
  "origin": [ { "actor": [ {"type":"party","actor-uuid":"...","name":"ACME","role":"assessor"} ] } ],
  "related-observation": [ {"observation-uuid":"...", "title":"TLS probe"} ],
  "associated-risk":     [ {"risk-uuid":"...", "title":"Weak cipher", "status":"open"} ],
  "result-uuid": "..."            // annotation when reached across results
}
```

`POAM.poam_item(uuid)` →
```jsonc
{
  "uuid":"...", "title":"...", "description":"...",
  "origin":[ {"actor":[{"type":"party","actor-uuid":"...","name":"ACME"}]} ],
  "related-finding":     [ {"finding-uuid":"...", "title":"...", "target-status":"not-satisfied"} ],
  "related-observation": [ {"observation-uuid":"...", "title":"..."} ],
  "associated-risk":     [ {"risk-uuid":"...", "title":"...", "status":"open"} ]
}
```

---

## 7. Open design questions (to settle before coding)

1. **Intra-document resolvers vs. generic machinery.** Add per-class
   `get_observation/risk/finding/task_by_uuid`, or extend `_COLLECTION_SPEC`/
   `_RESOLVE_KINDS`? (AR nesting under `result` + nested tasks argue for per-class.)
2. **AR result scoping default.** `result_uuid=None` = across-all-results (annotated) vs.
   requiring a result. Across-all is friendlier for GUI lists; confirm.
3. **Placeholder vs. omit** for each unresolved reference (related-observation,
   actor-uuid, subject-uuid). Consistency vs. the existing split (inventory_item
   placeholders; leveraged_authorization omits).
4. **How far to auto-resolve across imports.** `reviewed-controls`/`finding.target`
   objective resolution needs AP→SSP→profile→catalog (AR adds AP first). Keep all of this
   opt-in (`include_controls`/`resolve_target`) given the cost and the dependence on the
   import tree being resolved. Confirm default-off.
5. **Reuse SSP component/inventory/user getters.** Factor the SSP implementations into
   shared helpers so AP/AR/POA&M local-definitions present identically — or duplicate thin
   wrappers? (Leaning shared helpers.)
6. **`attestation` / `assessment-log` / `risk-log`** — index-only, or dedicated getters?
7. **Counts/summaries in index getters** — which counts are actually useful to a GUI
   (drives column choices). 
8. **Naming**: `tasks`/`task` nest; confirm the `depth` child-key is `"tasks"` (JSON
   plural) per the method-naming memo.
9. **`local-definitions` shadowing (§3.5):**
   - Parameter name — `include_shadowed` vs. `all_definitions` / `include_overridden`?
   - Annotation keys — `source-document` (reuse) for the winner, `shadowed[]` for losers;
     confirm shape and chain ordering (nearest loser first).
   - Plural behavior — one-per-uuid winner + optional `shadowed` sibling (proposed) vs.
     flat every-occurrence list.
   - AR intra-document container order (top-level, then each result's local-definitions
     then assessment-assets) — confirm.
   - Whether to re-express the existing SSP `.component()`/`.inventory_item()`/`.user()`
     on the shared `_local_def_containers` hook now, or leave SSP as-is and only build the
     hook for assessment models (risk: two code paths).
   - Reference resolvers that resolve a component/inventory/user uuid (origins §3.1,
     subjects §3.2) should use the **authoritative** (nearest-wins) definition; confirm
     they ignore shadowed copies.
10. **`objectives-and-methods` overlay presentation.** When `include_controls=True`, do we
    (a) return the local augmenting `parts` *merged into* the resolved control's
    `assessment-objective`/`assessment-method` parts, or (b) return the control's parts and
    the local augmenting parts as separate siblings so the authored augmentation stays
    visible? (Leaning (b) — keep the overlay explicit, consistent with not reshaping.) Also
    confirm the control chain reused here is the same one as `reviewed-controls`/
    `finding.target` (§3.3/§3.4).

---

## 8. Suggested build order

1. Shared enrich helpers (§3.1–3.4) + intra-doc resolvers (§4) with unit tests on fixtures.
2. POA&M getters (simplest — flat, top-level) end-to-end.
3. AR getters (adds result scoping + `result()`), reusing the same enrichers.
4. AP getters (`task` depth/nesting, `reviewed-controls`, subjects, assets).
5. Factor SSP component/inventory/user into shared helpers; wire into AP/AR/POA&M.

Each public method gets a unit test covering: invalid/missing uuid, dangling references
(placeholder/omit policy), round-trip of the raw fields, and `depth`/`include_*` boundaries
(per the testing philosophy in CLAUDE.md).
