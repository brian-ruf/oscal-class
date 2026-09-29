---
# This page is intended to be rendered by Jekyll for GitHub Pages
# (see docs/_config.yml). Links point at *.html (Jekyll builds each .md to .html).
title: Validation & Import Gating
---

# Validation & Import Gating

`validate()` checks OSCAL content against the metaschema index in five phases and
records the outcome on the document. This guide enumerates the validation **error
types**, the normalized shape of each error, and which errors block **import
resolution** versus which are allowed through.

## Validation phases

`validate()` runs all five phases in a single pass (a complete picture in one call),
recording a per-phase pass/fail in `validation_status`:

| Phase | `validation_status` key | Error type produced |
|---|---|---|
| Structure | `structure` | `missing-required` |
| Data types | `data-types` | `invalid-type` |
| Allowed values | `allowed-values` | `allowed-values` |
| Cardinality | `cardinality` | `cardinality` |
| Choice | `choice` | `choice` |

`well-formed` is set earlier (during load), not by `validate()`.

## `validation_errors` — normalized error list

`validation_errors` is a list of dicts from the most recent `validate()`. Every entry
shares the same core keys:

| Key | Type | Meaning |
|---|---|---|
| `error-type` | `str` | One of the five types above. |
| `location` | `str` | JSON path to the erroneous item, e.g. `/system-security-plan/system-implementation/inventory-items[0]/props[0]`. |
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

## Error type reference & import-gating recommendation

An import that fails in a GUI while the imported URL is manually reachable is usually a
document that was marked **invalid**, because import resolution historically required a
strictly-valid document. Some errors describe surface-level value problems that do not
affect the document's navigable structure, so they should **not** block following the
document's references. Others leave the tree ambiguous or incomplete and **should**.

| Error type | Phase | Blocks import? | Rationale |
|---|---|---|---|
| `missing-required` | structure | **Yes (block)** | A required field/flag is absent — the tree is structurally incomplete and may be unsafe to traverse. |
| `cardinality` | cardinality | **Yes (block)** | Wrong number of items in an array — structural; downstream assumptions about shape may not hold. |
| `choice` | choice | **Yes (block)** | Mutually-exclusive members both present (or a required choice missing) — the intended structure is ambiguous. |
| `invalid-type` | data-types | **No (allow)** | A leaf value fails its datatype pattern (e.g. a malformed date/token). The document's structure and reference graph are intact; URI-shaped values are already auto-repaired during the walk. |
| `allowed-values` | allowed-values | **No (allow)** | A value falls outside an enumerated set. Enumerations are advisory for interoperability, frequently carry `allow-other` semantics, admit legitimate vendor extensions, and are the most common source of *false* positives (e.g. metaschema constraints whose `target` scoping is only partially modeled). Never structural. |

This split is the default **non-blocking allow-list**:

```python
from oscal.oscal_content import IMPORT_NONBLOCKING_ERROR_TYPES
# frozenset({"allowed-values", "invalid-type"})
```

## How import gating works

After `validate()`, imports are resolved when **no blocking error remains** — that is,
when the document is valid *or* when every error is on the non-blocking allow-list:

- `is_valid` → `True`: content_state reaches `VALID`, then imports resolve normally
  (advancing to `IMPORTS_RESOLVED`).
- Not valid, but **only** non-blocking errors: `import_list` is still populated so the
  document's references can be followed, while `content_state` stays `WELL_FORMED`
  (`is_valid` remains `False`, `imports_resolved` remains `False`). The document is not
  claimed to be valid — its imports are simply made available.
- A single blocking error present: imports are **not** resolved automatically. (You can
  still call `resolve_imports()` explicitly.)

Inspect what is blocking with the `import_blocking_errors` property:

```python
doc = OSCAL.acquire(url)
if not doc.is_valid:
    if doc.import_blocking_errors:
        print("Imports blocked by:", [e["error-type"] for e in doc.import_blocking_errors])
    else:
        print("Only non-blocking errors — imports resolved:", len(doc.import_list))
```

## Tuning the allow-list

The allow-list is a class attribute, overridable per subclass or per instance:

```python
# Stricter: only allowed-values may pass
doc.import_nonblocking_error_types = frozenset({"allowed-values"})

# Looser (not recommended): let anything through
doc.import_nonblocking_error_types = frozenset(
    {"allowed-values", "invalid-type", "cardinality", "choice", "missing-required"}
)
```

The rationale for the default split is recorded in the
`oscal_import_nonblocking_errors` memory note; change both together if the policy
changes.
