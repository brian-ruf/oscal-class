# Profile Processing

An OSCAL **profile** selects and tailors controls from one or more imported catalogs
and/or profiles into a new baseline or overlay. Resolving a profile applies its
processing directives — which controls are in scope, how they are organized, and how
their parameters and content are modified — to produce a single **resolved catalog**.

This library processes profiles in two phases so you only expend processing for what you use:

1. **`controls_tree` (built at load, cheap).** A lightweight tree of the in-scope
   groups and controls — ids, hierarchy, and each node's origin — with the profile's
   `import` / `include` / `exclude` / `merge` / `combine` directives already applied.
   This is the source of truth for *scope and organization*. 
     - No control content is copied.
     - Profile alterations are applied to individual controls as they are feteched. 
2. **`resolve()` (on demand, heavy).** Walks the `controls_tree`, fetches the real
   content for each node, applies `modify` (removes → adds → set-parameters), and
   materializes a brand-new `Catalog` in `profile.catalog`.

Because the `controls_tree` is always available, you can read individual controls and
groups **without resolving the whole profile** (just-in-time), or resolve once and work
with the full `Catalog`.

Each imported profile is represented by its own Profile object. Each Profile object handles its own control import and alterations processing, and makes the result available to downstream imports, ensuring complex import trees are handled cleanly. 

All processing follows the NIST
[OSCAL Profile Resolution](https://pages.nist.gov/OSCAL/learn/concepts/processing/profile-resolution/)
specification.

---

## At a glance

| Method | Returns | Needs `resolve()` first? |
| --- | --- | --- |
| `get_control_by_id(id, depth=None)` | control `dict` \| `None` | No — materialized just-in-time |
| `get_group_by_id(id, depth=None)` | group `dict` \| `None` | No — materialized just-in-time |
| `get_control_list()` | `list[dict]` | No — materialized just-in-time |
| `get_parameter_by_id(id)` | param `dict` \| `None` | No — materialized just-in-time |
| `resolve()` | `ResolutionStatus` | — builds `profile.catalog` |
| `catalog` (attribute) | `Catalog` \| `None` | `None` until `resolve()` |
| `dumps_catalog(format, pretty_print)` | `str` | Yes |
| `dump_catalog(filename, format, pretty_print)` | `bool` | Yes |
| `resolve_and_dumps_catalog(format, pretty_print)` | `str` | resolves for you |
| `resolve_and_dump_catalog(filename, format, pretty_print)` | `bool` | resolves for you |

---

## Loading a profile

```python
from oscal import OSCAL, Profile

# OSCAL.load() returns a typed instance (a Profile for a profile document)
profile = OSCAL.load("high-baseline-privacy-profile.json")

# ...or load as the specific model
profile = Profile.load("high-baseline-privacy-profile.json")

profile.resolution_status     # ResolutionStatus.UNRESOLVED
profile.catalog               # None — not resolved yet
len(profile.controls_tree)    # the in-scope top-level groups/controls
```

Loading builds the `controls_tree` (applying the profile's scope and merge directives)
but does **not** resolve to a catalog.

---

## Any number or depth of imports (profiles and catalogs)

A profile may import catalogs, other profiles, or a mix — to any depth. The library
resolves the whole import graph automatically; you do **not** need to pre-resolve
imported profiles. Each imported profile contributes its own load-time `controls_tree`,
and content is fetched through each source's own accessors, recursing to the underlying
catalogs.

```
combined-profile.json           (imports two profiles)
├── baseline-profile.json       (imports a catalog + an overlay catalog)
│   ├── base-catalog.json
│   └── overlay-catalog.json
└── overlay-profile.json        (imports the same catalog + overlay catalog)
    ├── base-catalog.json
    └── overlay-catalog.json
```

```python
top = OSCAL.load("combined-profile.json")

# The full chain is already reflected in the scope — no manual pre-resolution needed.
ids = {c["id"] for c in top.get_control_list()}
```

Duplicate control references across imports are handled by the profile's `combine`
directive:

- **`use-first`** — the first occurrence is kept; later identical duplicates are dropped.
  A *new* enhancement of a duplicated parent control is still kept (merged under the kept
  parent), and same-id groups are merged into a single group.
- **`keep`** — later duplicates are retained with a `__<uuid>`-suffixed id.

Import-related notes:

- If two different documents share a root **UUID** (a common hand-authoring mistake),
  the library detects it — comparing `title` / `oscal-version` / `last-modified` /
  `version` — and reassigns the later one a fresh UUID to continue, with a warning. Fix
  the source content to use unique UUIDs.
- An unreachable import blocks resolution; `resolve()` returns
  `ResolutionStatus.BLOCKED`.

---

## Just-in-time (JIT) access

You can read individual controls and groups straight from an **unresolved** profile.
The library materializes just the requested content on demand from the source (applying
this profile's `modify` directives), without building the whole catalog.

```python
profile = OSCAL.load("high-baseline-privacy-profile.json")
assert profile.catalog is None            # still unresolved

ac_1 = profile.get_control_by_id("ac-1")  # materialized on demand, fully tailored
ac_1["id"]                                # "ac-1"

assert profile.catalog is None            # a JIT read did NOT trigger a full resolve
```

JIT is ideal for browsing, previewing, or pulling a handful of controls (e.g. building a
navigation UI, or importing a few controls into an SSP) without the cost of a full
resolution. The returned dict is a **detached safe copy** — mutating it does not change
the profile.

---

## Full resolution to a catalog

When you need the complete tailored catalog, call `resolve()`. It builds a fresh
`Catalog` in `profile.catalog` and returns a status.

```python
from oscal.oscal_controls import ResolutionStatus

status = profile.resolve()
if status == ResolutionStatus.RESOLVED:
    catalog = profile.catalog                 # a fully-resolved Catalog instance
    print(len(catalog), "controls")
    print(catalog.is_valid)
elif status == ResolutionStatus.BLOCKED:
    print("An import could not be resolved.")
```

`resolve()` always rebuilds `profile.catalog` from scratch. Resolve once and reuse
`profile.catalog` (or the profile's getters) for many reads.

### Serializing the resolved catalog

```python
# Serialize to a string / file (require the profile to be resolved first)
profile.resolve()
json_text = profile.dumps_catalog(format="json", pretty_print=True)
profile.dump_catalog(filename="resolved-catalog.json", format="json")

# One-shot: resolve then serialize in a single call
json_text = profile.resolve_and_dumps_catalog(format="json", pretty_print=True)
profile.resolve_and_dump_catalog(filename="resolved-catalog.xml", format="xml")
```

Use `resolve_and_dump*` for the common one-shot case. Use `resolve()` +
`dump_catalog` / `dumps_catalog` when you want finer control — for example to resolve
once and write several formats, or to control *when* the heavy resolution runs. The
pure `dump*` methods never resolve on their own; if the profile is unresolved they warn
and return an empty string / `False`.

---

## Acquire groups and controls just like a Catalog

A resolved-or-not profile exposes the same read accessors as a `Catalog`, with identical
signatures and return shapes — so code that navigates a catalog works unchanged against
a profile.

```python
def summarize(source):
    """Works for both a Catalog and a Profile."""
    ac = source.get_group_by_id("ac")             # the Access Control family
    ac_1 = source.get_control_by_id("ac-1")       # a single control (safe copy)
    ac_1_shallow = source.get_control_by_id("ac-1", depth=0)   # without enhancements
    every = source.get_control_list()             # flat list of all controls
    return ac, ac_1, ac_1_shallow, every

summarize(Catalog.load("nist-800-53.json"))
summarize(Profile.load("high-baseline-privacy-profile.json"))   # same calls, same shapes
```

- `get_control_by_id(id, depth=None)` — a control as a detached copy. `depth` prunes only
  nested enhancements (`None` = full subtree, `0` = none, `N` = N levels).
- `get_group_by_id(id, depth=None)` — a group as a detached copy. `depth` prunes only
  nested groups/controls.
- `get_control_list()` — a flat list of every control (enhancements included).
- `get_parameter_by_id(id)` — a parameter, wherever it is defined in scope.

When the profile is **resolved**, these read from `profile.catalog`. When it is
**unresolved**, they materialize the same result on demand from the source — so the two
paths agree. Because they return safe copies, edits are made through the profile's
directive methods (below) and re-resolved, not by mutating a returned dict.

---

## Changing scope and directives

Scope and organization come from the profile's own directives. After changing them, the
`controls_tree` rebuilds automatically; call `resolve()` again for a fresh catalog.

```python
profile = Profile.new("My Baseline")
profile.set_metadata({"title": "My Baseline"})

# Add imports (each backed by a back-matter resource)
profile.add_import("nist-800-53.json", include_all=True)

# Choose how imported controls are organized:
profile.set_merge(as_is=True, combine="use-first")   # preserve source grouping
# profile.set_merge(flat=True)                        # flatten (no groups)

controls = profile.get_control_list()   # reflects the new scope immediately (JIT)
profile.resolve()                       # (re)build profile.catalog
```

Directive summary:

- **`import` / `include-controls` / `exclude-controls`** — which controls are in scope
  (`with-ids`, `matching` glob patterns, `with-child-controls`).
- **`merge`** — organization: `as-is` (preserve grouping) or `flat` (no groups).
  `custom` grouping is not yet implemented and falls back to `as-is`.
- **`combine`** — duplicate handling: `use-first` or `keep` (default).
- **`modify`** — per-control tailoring: `alters` (removes → adds) and `set-parameters`,
  applied during resolution and JIT reads alike.

---

## Resolution status

`profile.resolution_status` is a `ResolutionStatus`:

| Value | Meaning |
| --- | --- |
| `UNRESOLVED` | Loaded; `controls_tree` built, `catalog` is `None`. |
| `RESOLVING` | Resolution in progress. |
| `RESOLVED` | `profile.catalog` is populated. |
| `BLOCKED` | Resolution could not complete (e.g. an import is unreachable). |

---

## Notes and current limitations

- **`resolve()` fully rebuilds** the resolved catalog each call. Content-based
  change-detection (skip re-resolution when nothing changed) is planned alongside the
  library-wide caching/TTL work; see `docs/ROADMAP.md`.
- **`custom` merge** is deferred (falls back to `as-is`).
- **Out-of-scope cross-references** (a control referencing another control not in the
  baseline) are rewritten to absolute source URIs, matching the reference resolver.
