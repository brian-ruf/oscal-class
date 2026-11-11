# Getter / Setter Naming Consistency — Plan & Decision Log

**Status:** Tabled until the **5.0.0** major release. No code changes yet.
**Last updated:** 2026-11-11.
**Related:** [METHOD_PATTERNS.md](METHOD_PATTERNS.md) (conventions), [COVERAGE.html](COVERAGE.html)
(current + planned getter/setter surface).

This document captures a design discussion about inconsistent getter naming across the OSCAL
model classes, the options weighed, and the decisions reached so far. It is a parking record
to resume from when we open 5.0.0 — not an approved change.

> **⚑ Pre-5.0.0 batch (do these together, as one breaking release):**
> 1. **Getter-name normalization** — universal `get_<noun>()` (§2–§3).
> 2. **Library-wide provenance migration** — apply the `provenance {uuid, href, imported}`
>    object to the base-class cross-reference getters (roles/parties/locations/resources)
>    and reconcile the three existing representations, retiring `source-document` (§5b).
>
> Both change the public getter surface with deprecation windows, so they must be planned
> and landed **together, ahead of 5.0.0** — not piecemeal. The assessment-layer provenance
> + `additional-versions` work is already done in the final shape, so 5.0.0 only needs the
> base-class back-fill, not a redesign.

---

## 1. The problem

Single-object getters are spelled two different ways across the models:

* **Verbose / explicit** — `.get_<kind>_by_<key>()`, keyed by `uuid` or `id`
  (e.g. `.get_party_by_uuid()`, `.get_role_by_id()`, `.get_control_by_id()`).
* **Short noun** — `.<noun>()`, also keyed by `uuid`/`id`
  (e.g. `.component()`, `.inventory_item()`, `.user()`, `.control()` on SSP/cDef/Profile).

The same concept is sometimes spelled both ways (e.g. `Profile.control()` is documented as a
"thin alias of `get_control_by_id`"), which is what surfaced the inconsistency.

A hard constraint throughout: **normalizing is a breaking change.** Whatever we choose, both
the old and new names must remain valid until the next major version, with a
`DeprecationWarning` emitted when the old name is used.

---

## 2. Options considered

| Option | Shape | Notes |
|---|---|---|
| **A** | short noun — `.control(id)` | Concise; pairs with plural index getters. Reads like an attribute; hides the Optional/failure mode; `.control()` vs `.controls()` differ by one character. |
| **B** | full verbose — `.get_control_by_id(id)` | Explicit, greppable, extensible (`_by_name`); the `get_` prefix signals "lookup that may return None." Wordy. |
| **C** | middle — `.get_control(id)` | Keeps idiomatic `get_`, drops the redundant `_by_<key>` tail. Loses key-type disambiguation at the call site. |
| **D** ← **leaning** | **universal `get_<noun>()`** | Add `get_` to the short ones, drop `_by_uuid`/`_by_id` from the long ones, so *every* single-object getter is `get_<noun>()`. One rule everywhere. |

### The three framing questions

* **Which is more Pythonic?** For keyed, computed, possibly-missing lookups (which these all
  are — they traverse / deep-copy / enrich and return `Optional`), the `get_` prefix is the
  idiomatic signal (cf. `dict.get`, `os.environ.get`, SQLAlchemy `Session.get`). Bare-noun
  methods that take an argument read like attributes and are the less common Python shape.
  The redundant part people dislike is the `_by_<key>` **suffix**, which is separable. Net:
  `get_<noun>()` is a legitimately Pythonic shape here, and **consistency within the project
  is itself a core Pythonic value** (PEP 8) — not because "`get_` everywhere" is a universal
  ideal, but because these specifically are computed, fallible lookups.
* **Is either unacceptable?** Neither. Short-noun carries three real pitfalls — attribute
  shadowing, one-character singular/plural ambiguity, and hiding the Optional contract — so
  it's "acceptable with care." Verbose's only knock is aesthetic ("Java-ish"). Verbose is the
  safe one.
* **Which change has greater impact?** The verbose family is used heavily **internally**
  (enrichment helpers call `get_party_by_uuid`/`get_role_by_id`; resolution calls
  `get_oscal_object`); the short family is the primary **GUI-facing** API (CyberCraft). A
  universal scheme (Option D) touches **both**, so it is the highest-impact option — though
  the impact is mostly *mechanical* (aliases make it non-breaking); the substantive part is
  the forced decisions in §4.

---

## 3. Direction chosen (to revisit at 5.0.0)

**Move toward Option D — a universal `get_<noun>()` for single-object getters** — on the
grounds that it is the most consistent and makes every getter obviously a getter. Deferred to
5.0.0 because of the breakage, with the old names retained as deprecated aliases through the
4.x line.

The earlier "two families" framing (import-cascading **resolver** vs. enriched **detail
getter**) was explored as a reason to *keep* two naming shapes. **This distinction was not
accepted** as significant enough to warrant different names — see the clarifying note in §5.

---

## 4. Decisions still open (resolve when 5.0.0 work begins)

1. **Do plural / collection getters also take `get_`?** (`.roles()` → `.get_roles()`,
   `.components()` → `.get_components()`.) This is the biggest scope lever: converting them
   roughly doubles the breaking surface and would deprecate the collection getters shipped in
   4.1.0; leaving them bare reintroduces a singular-`get_`/plural-bare inconsistency. Current
   lean: **apply `get_` to single-object getters only; leave plural collection getters as bare
   plurals.** (Open.)
2. **Carve-outs.** `*_content` methods (`resource_content`, `link_content`) *acquire bytes*,
   not "get a node," and the derived-view attributes (`controls_tree`, `implementation_tree`,
   `poam_tree`) are attributes, not methods — both stay outside the `get_` rule and must be
   documented as explicit exceptions.
3. **Key-type disambiguation.** Dropping `_by_<key>` is fine while each noun has one natural
   key; if a second lookup key is ever needed (e.g. component by title), reintroduce an
   explicit `get_<noun>_by_<key>()` alongside the default `get_<noun>()`.

---

## 5. Clarifying note — "resolver vs. detail getter" was a miscommunication

> On Cons #2–5: Get objects by `id` or `uuid` is by far the most common type of get, with few
> exceptions. To this end, I didn't intend different parameters or functionality for
> `.get_observation_by_uuid` vs `.observations`. The existence of both is a miscommunication
> and part of what made me raise this topic.

**Interpretation / consequence:** there is intended to be **one** get-by-`id`/`uuid`
operation per object kind — not a raw cross-reference resolver *and* a separate enriched
detail getter with the same noun. Where both currently appear (or were planned) for the same
kind — e.g. the step-1 getters and the planned `.get_component_by_uuid()` versus
`.component()` — they are **the same operation**, not two methods.

**Acted on (2026-11-10):** the three step-1 methods were renamed from
`.get_observation_by_uuid()` / `.get_risk_by_uuid()` / `.get_finding_by_uuid()` to the
short-noun form **`.observation()` / `.risk()` / `.finding()`** (keyed by uuid), matching the
current model-specific detail-getter convention (`.component()`, `.user()`, …). As brand-new,
unreleased methods they were renamed outright — no deprecation alias. The duplicative planned
`.get_<noun>_by_uuid()` entries (component, inventory-item, user, task, activity) were dropped
from `docs/COVERAGE.html`, leaving the single short-noun getter per kind. (The lone exception
kept is `.get_objectives_and_methods_by_control_id()` — a singular lookup keyed by `control-id`
with no short-noun duplicate; its naming is a 5.0.0 concern, not a duplicate to drop.)

At **5.0.0**, under Option D, these short nouns become `.get_<noun>()` along with the rest of
the single-object getters — so the net path is `get_*_by_uuid` → `<noun>` (now) → `get_<noun>`
(5.0.0). The interim short-noun step keeps the new methods consistent with today's surface.

---

## 5b. Provenance — library-wide (locked 2026-11-11)

Separate from the getter-name question, we locked how content that **bubbles up through
the import chain** is attributed:

* **Key / shape:** `provenance = {uuid, href, imported}` — the owning document's root uuid,
  its resolved href, and whether it was reached through an import (`imported` is False only
  for the document the getter was called on). **Always present** (no "absence = local"
  convention).
* **Scope:** applies **everywhere content can be reached via import when not found
  locally** — not just the assessment layer. The same shape is to be used for metadata
  `roles` / `parties` / `locations` / `responsible-parties` / `actions` and back-matter
  `resources`.
* **First-found-wins order:** traversal follows the **imports array order** (a profile may
  import several catalogs/profiles; a cDef several cDefs). Confirmed already true —
  `resolve_imports` builds `import_list` in document order and `find_in_import_tree` /
  `_collect_in_scope` iterate it in that order (regression-pinned in
  `tests/unit/test_scope_collections.py::TestMultiImportOrder`).
* **`additional-versions`:** applies **only to `local-definition` constructs**
  (components / inventory-items), where an importer may supersede an imported definition and
  we retain the superseded version(s) so content is not lost. Roles / parties / locations /
  resources are **strictly first-found-wins** — no version history.

**Done (2026-11-11):** implemented for the assessment-layer `component` / `components` /
`inventory_item` / `inventory_items` getters in the final shape above.

**Sequenced (do as one focused migration, with the 5.0.0 window):** apply the same
`provenance` object to the base-class cross-reference getters and reconcile the **three
representations that exist today** — the singular `with_source` locator (`object_uuid` +
`href`), the plural `_collect_in_scope` annotation (`source-document {uuid, href,
imported}`), and the new `provenance {uuid, href, imported}`. Plan: promote `provenance` as
the one canonical key; keep `source-document` as a deprecated alias through 4.x; and add
`provenance` to the default (non-`with_source`) singular returns. The last part is the
ripple-heavy piece — the singular getters currently return a bare element and are consumed
by the responsibility-enrichment path and many exact-equality tests — so it is deliberately
deferred out of the assessment slice and done as its own change.

## 6. Deprecation mechanics (for when we execute)

* Add each old name as a thin forwarding alias that emits
  `warnings.warn(..., DeprecationWarning, stacklevel=2)` and delegates to the new method —
  safe because, per §5, the pairs are the same operation (the `Profile.control()` → 
  `get_control_by_id()` alias is the existing template).
* Keep both names valid through the **4.x** line; remove the old names in **5.0.0**.
* Migrate all **internal** call sites to the new names so the library does not trip its own
  deprecation warnings.
* Record the new convention and the alias/deprecation table in
  [METHOD_PATTERNS.md](METHOD_PATTERNS.md), and annotate the deprecated spellings in
  [COVERAGE.html](COVERAGE.html).
