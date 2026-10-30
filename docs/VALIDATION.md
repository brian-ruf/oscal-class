---
# This page is intended to be rendered by Jekyll for GitHub Pages
# (see docs/_config.yml). Links point at *.html (Jekyll builds each .md to .html).
title: Tiered Validation
---

# Tiered Validation

OSCAL content is validated **at load**. `validate()` checks the content against the
metaschema index in a single pass that **fully descends** the document — through
`choice` groupings and recursive self-references (`group/group`, `control` enhancements,
`part/part`, …) — so nested content is checked to the same standard as the top level.

Validation is organized into **three tiers**. The distinction drives everything the
library will let you do with a document:

- **Minimal validity** (`is_minimally_valid`) — the content is *structurally* sound:
  well-formed, correct keys and shape, and every required field/branch present. This is
  the **operational bar**: loading, summary‑tree building, import resolution, and editing
  all gate on it.
- **Valid / L2** (`is_valid`) — minimal validity **plus** the value-quality checks the
  library evaluates natively on the JSON: data types and the **natively-evaluable**
  allowed-values. This tier is designed to meet or exceed the guarantees of the
  NIST-published OSCAL **JSON Schema**.
- **Fully compliant / L3** (`is_fully_compliant`) — L2 **plus** every constraint whose
  Metapath target needs ancestor / descendant / cross-path context, and the other rule
  families (`matches`, `expect`, `is-unique`, `index`, `index-has-key`,
  `has-cardinality`). These are evaluated against the OSCAL **XML** with a real XPath
  engine by `validate_full()`. This is the strictest, full-metaschema bar.

> The tree views are *OSCAL-aligned summaries*; they are never themselves OSCAL-valid
> documents. They build as soon as content is **minimally** valid.

## Phases and tiers

`validate()` runs all phases in one pass and records a per-phase pass/fail in
`validation_status`. Each phase belongs to a tier:

| Phase | `validation_status` key | Error type | Tier |
|---|---|---|---|
| Structure | `structure` | `missing-required` | **Minimal** (structural) |
| Cardinality | `cardinality` | `cardinality` | **Minimal** (structural) |
| Choice | `choice` | `choice` | **Minimal** (structural) |
| Data types | `data-types` | `invalid-type` | **Valid / L2** (value-quality) |
| Allowed values (native) | `allowed-values` | `allowed-values` | **Valid / L2** (value-quality) |
| Allowed values (scoped) + `matches`/`expect`/`is-unique`/… | *(via `validate_full`)* | *(L3)* | **Fully compliant / L3** |

Each allowed-values constraint in the metaschema index carries a `validation-level`
(`valid` or `fully-compliant`). The automatic walk enforces only `valid` (L2) ones; the
`fully-compliant` (L3) ones — and the non-allowed-values rule families — are captured in
the index but deferred to `validate_full()`. A single node's allowed-values are treated
**all-or-nothing**: if any constraint on the node needs non-native (ancestor/cross-path)
context, *all* of its allowed-values are tagged L3, so L2 never rejects a value an L3
sibling constraint would permit.

`well-formed` is set earlier (during load), not by `validate()`. It is the floor:
content that is not well-formed (unparseable, or no identifiable model/OSCAL version)
has neither tier.

**Why this split.** Structural failures can leave the document's hierarchy incomplete or
ambiguous — unsafe to traverse or edit. Value-quality failures (a malformed date, a
value outside an enumeration) do **not** affect the shape of the tree or the reference
graph; the document remains navigable and remediable in place. Minimal validity is
therefore the bar the library can rely on to operate safely while content is brought up
to full validity. The L2/L3 split then separates checks the library can evaluate
*correctly and natively* on the JSON (L2) from those that require resolving Metapath
context against the XML (L3).

> **Resolved: nested `allowed-values` over-reporting.** Earlier versions evaluated *every*
> allowed-values constraint during the single JSON walk, including ones scoped by Metapath
> *ancestor* predicates (e.g. a `statement` part's child may be named `item`, or an
> inventory-item's `vendor-name` prop is valid only when `@type` is software/hardware/
> service). Because the walk could not resolve that context, legitimate published catalogs
> showed thousands of false `allowed-values` errors and `is_valid` was effectively always
> `False` for them. These scoped constraints are now tagged **L3** in the index and
> deferred to `validate_full()`, so **`is_valid` (L2) is clean on published content** and
> the scoped checks are enforced at the fully-compliant tier instead.

## Validity properties

Progressive content state exposes the tiers as properties:

| Property | Value | True when |
|---|---|---|
| `is_well_formed` | `bool` | content parsed and model/version identified |
| `is_minimally_valid` | `bool` | well-formed **and** no *structural* errors (missing-required / cardinality / choice) |
| `is_valid` | `bool` | **L2** validity — every phase passes with native checks (`content_state >= VALID`) |
| `is_fully_compliant` | `bool \| None` | **L3** tri-state: `False` when not `is_valid`; `None` until `validate_full()` runs; `True`/`False` after it |
| `imports_resolved` | `bool` | all imports resolved (`content_state >= IMPORTS_RESOLVED`; implies L2 validity) |

```python
doc = OSCAL.acquire(source)
doc.is_well_formed        # floor
doc.is_minimally_valid    # structural — the operational bar
doc.is_valid              # L2 — meets/exceeds the OSCAL JSON Schema
doc.validate_full()       # run the L3 pass (XML/XPath engine)
doc.is_fully_compliant    # L3 — None until validate_full() has run
```

## What each tier allows or blocks

| Capability | Requires |
|---|---|
| Load is accepted (object usable) | well-formed |
| Build summary trees (`controls_tree`, `implementation_tree`) | **minimal** validity |
| Resolve imports (`import_list` populated, entries `READY`) | **minimal** validity |
| Be used as an *imported* document by another | the import is **minimally** valid |
| Edit / mutate via model methods (`_can_mutate`) | content loaded + not read-only |
| `is_editable` convenience flag is `True` | **L2** validity + local + not read-only |
| Claim OSCAL JSON-Schema-level validity | **L2** validity (`is_valid`) |
| Claim full metaschema conformance | **L3** (`is_fully_compliant is True` after `validate_full()`) |

**Two gates, one difference that matters.** Mutation methods enforce only `_can_mutate`
(loaded + not read-only); `is_editable` is a stricter *advisory* signal (full validity +
local + not read-only) the methods do not consult. So a minimally-valid (or
remote-loaded) document can be mutated even though `is_editable` is `False`.

> **Convention (guidance, not enforced).** When `_can_mutate` is `True` but `is_editable`
> is `False`, mutations **should be limited to resolving the issues blocking full
> validity** (remediation toward `is_valid`), not general authoring. The library does not
> enforce this — it is the caller's responsibility. See the *"`is_editable` vs. the
mutation guard"* section of [OSCAL Class](CONTENT.html).

A document that is minimally valid but not L2-valid (e.g. a malformed date or a native
allowed-values miss) **builds its trees and resolves its imports** while `is_valid` stays
`False` and `content_state` stays `WELL_FORMED` — the library never *claims* the document
is valid, it just operates on its sound structure.

## `validation_errors` — normalized error list

`validation_errors` is a list of dicts from the most recent `validate()`. Every entry
shares the same core keys:

| Key | Type | Meaning |
|---|---|---|
| `error-type` | `str` | One of the five error types above. |
| `location` | `str` | JSON path to the erroneous item, e.g. `/catalog/groups[0]/controls[0]`. |
| `identifier` | `str \| None` | The `uuid`/`id` of the **nearest enclosing identifiable object** (the item itself when it carries one, else its closest identifiable ancestor). `None` when nothing in scope has an identifier. |
| `field` | `str \| list[str]` | The offending flag/field name (`@name` for a flag; a list for `choice` errors). |
| `value` | `Any` | The offending value — the bad value, `None` for a missing field, or the item count for `cardinality`. |

Plus **error-type-specific detail**:

- `expected` — for `invalid-type` (`{type, pattern, description}`), `allowed-values`
  (`{one-of: [{enum, description}, …]}`), and `choice`
  (`{select-one-of: [...]}` or `{mutually-exclusive: [...]}`).
- `min` / `max` — for `cardinality` (the allowed bounds; `max` is `None` when unbounded).

```python
for err in doc.validation_errors:
    print(err["error-type"], err["location"], err["identifier"], err["value"])
```

## Identifier indexes

The same validation walk builds two identifier indexes (no second traversal):
`_id_index` and `_uuid_index`. Each maps an identifier value to a list of occurrence
records `{"value", "key", "path"}` — where `key` is the containing collection's JSON key
and `path` is the JSON path to the object carrying the identifier. A value appearing in
more than one record is a duplicate (the basis for future uniqueness checking).

## Error-type reference (tier + import gating)

| Error type | Phase | Tier | Blocks trees / imports? | Rationale |
|---|---|---|---|---|
| `missing-required` | structure | Minimal | **Yes** | A required field/flag/branch is absent — structurally incomplete. |
| `cardinality` | cardinality | Minimal | **Yes** | An array is outside its min/max bounds — structural. |
| `choice` | choice | Minimal | **Yes** | A required choice is unselected, or mutually-exclusive branches both present — ambiguous structure. |
| `invalid-type` | data-types | Valid / L2 | No | A leaf value fails its datatype pattern (e.g. malformed date/token); structure/graph intact (URIs are auto-repaired during the walk). |
| `allowed-values` | allowed-values | Valid / L2 (native) · L3 (scoped) | No | A value falls outside an enumeration; advisory for interoperability, often `allow-other`. Native (self/own-flag) constraints are checked at L2; ancestor/cross-path-scoped ones are deferred to L3 (`validate_full`), which is what eliminated the nested false positives. |

The "blocks?" column **is** the structural-vs-value-quality split — the same one that
powers import gating.

## Import gating (derives from the tier)

Import resolution gates on **minimal** validity: after `validate()`, imports resolve
when **no structural (blocking) error remains**. A document whose only errors are
value-quality still populates `import_list` with `READY` entries. The blocking set is
the complement of the non-blocking allow-list:

```python
from oscal.oscal_content import IMPORT_NONBLOCKING_ERROR_TYPES
# frozenset({"allowed-values", "invalid-type"})  — the value-quality (full-tier) types
```

Inspect what, if anything, is holding resolution back:

```python
doc = OSCAL.acquire(url)
if not doc.is_minimally_valid:
    print("Blocked by:", [e["error-type"] for e in doc.import_blocking_errors])
else:
    print("Imports resolved:", len(doc.import_list))
```

An imported document is itself accepted as a usable import (`READY`) when it is
**minimally** valid — so a published catalog/profile with deep `allowed-values` noise is
still importable.

### Tuning the allow-list

The allow-list is a class attribute, overridable per subclass or per instance:

```python
# Stricter: only allowed-values may pass
doc.import_nonblocking_error_types = frozenset({"allowed-values"})

# Looser (not recommended): let structural problems through too
doc.import_nonblocking_error_types = frozenset(
    {"allowed-values", "invalid-type", "cardinality", "choice", "missing-required"}
)
```

Changing it moves the structural/value-quality boundary for *import gating* specifically;
`is_minimally_valid` uses the same boundary, so keep the two consistent.

## See also

- [OSCAL Class](CONTENT.html) — content states, `validate()`, `validation_status`.
- [Import Resolution](IMPORTS.html) — how the import tree is built and resolved.
