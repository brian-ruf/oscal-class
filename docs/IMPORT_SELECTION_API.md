# Profile import-selection API — reference

A hand-off reference for the `Profile` methods that read, preview, and edit an import's
control selection (`include-all` / `include-controls` / `exclude-controls`, and the
`with-child-controls` flag). All methods are on the `Profile` class. `href` is **any tracked
href form** that identifies the import statement (authored href, resolved href, or an
`href_list` item).

## Shared conventions

- **Setters are atomic:** each change is staged, metaschema-validated, and committed only if
  valid. On any failure the live import is unchanged and the method returns `None`.
- **Return value (all setters):** a deep-copied dict of the **rewritten import statement** on
  success, else `None`. The dict contains `href` plus whichever of `include-all` /
  `include-controls` / `exclude-controls` apply.
- **`with_children` family is `Optional[bool]`:** `None` = omit / leave the flag as-is ·
  `True` = `"with-child-controls": "yes"` · `False` = explicit `"with-child-controls": "no"`.
  (The OSCAL flag is a token whose value must be `"yes"`/`"no"` — **not** presence-based;
  passing `None`/`""`/a Python bool into a raw dict is the classic bug.)
- **`ids`:** `list[str]` → the entry's `with-ids`.
- **`matching`:** `list` where each item is an OSCAL `{"pattern": str, "remarks": str}` dict
  (preserved intact) **or** a bare pattern string (shorthand for `{"pattern": s}`).
- **`matching` patterns are greedy globs** (`*` spans dots/digits): `"ac-2*"` matches `ac-2`,
  `ac-2.1`, **and** `ac-20`, `ac-21`. To select a control and its enhancements, use exact
  `ids=["ac-2"]` + `with_children=True`, not `"ac-2*"`.
- **OSCAL choice:** an import has exactly one of `include-all` **or** `include-controls`;
  `exclude-controls` coexists with either. A `select-control-by-id` entry is
  `{with-ids?, matching?, with-child-controls?}`.

---

## Setters

### `set_import_selection(href, include_all=None, include_controls=None, exclude_controls=None, include_with_children=None, exclude_with_children=None)`
Wholesale **replace** of the selection.
- `include_all`: dict (typically `{}`). Mutually exclusive with `include_controls`.
- `include_controls` / `exclude_controls`: `list` of `select-control-by-id` dicts.
- `include_with_children` / `exclude_with_children`: `Optional[bool]` — stamp the flag across
  the supplied include/exclude entries.
- ⚠️ **Args left `None` are dropped from the import.** To keep the other side, re-pass it.
  Prefer the granular methods below for incremental edits.
- **Returns:** rewritten import dict, or `None` (no import, bad type, or neither/both include
  forms).

### `set_import_with_children(href, include=None, exclude=None)`
**Toggle the flag only**, on the existing selection, without rebuilding it. The two sides are
independent.
- `include` / `exclude`: `Optional[bool]` (`None` leaves that side untouched; `True`→`"yes"`;
  `False`→`"no"`).
- Preserves the include form and the exclude side except for the flag you set. Never drops the
  other side.
- **Returns:** rewritten import dict, or `None` (both `None`, or no import). No effect on an
  `include-all` import (no entries to flag) / when there is no `exclude-controls` — logs a
  warning in those cases.

### `add_import_include(href, ids=None, matching=None, with_children=None)`
Append **one** `select-control-by-id` to `include-controls`.
- At least one of `ids` / `matching` is required.
- Converts `include-all` → `include-controls` on first use; drops the empty placeholder entry
  `add_import` seeds; preserves `exclude-controls`.
- **Returns:** rewritten import dict, or `None` (no import, bad arg, neither ids nor matching,
  or rejected).

### `add_import_exclude(href, ids=None, matching=None, with_children=None)`
Same as `add_import_include`, appending to `exclude-controls`; preserves the include form.
- **Returns:** rewritten import dict, or `None`.

### `remove_import_include(href, ids=None, matching=None)`
Remove the `include-controls` entry/entries whose **identity** = (`with-ids` set + `matching`
pattern set). `with-child-controls` and `remarks` are ignored for matching (pass back the same
`ids`/`matching` you rendered).
- Removes **all** entries with that identity. No match ⇒ no-op ⇒ `None`.
- **Refuses** to remove the last effective include selection (atomic; returns `None`) — switch
  to `include-all` via `set_import_selection`, or drop the import via `remove_import`.
- Preserves `exclude-controls`.
- **Returns:** rewritten import dict, or `None`.

### `remove_import_exclude(href, ids=None, matching=None)`
Same identity rule, for `exclude-controls`. When the last exclusion is removed, the
`exclude-controls` key is dropped entirely. Preserves the include form.
- **Returns:** rewritten import dict, or `None` (no import, or no match).

---

## Read-only helpers (support the setter workflow)

### `get_import_selection(href)`
- **Returns:** deep copy containing whichever of `include-all` / `include-controls` /
  `exclude-controls` are present (`{}` if none), or `None` if no import matches.

### `preview_import_selection(href, include_all=None, include_controls=None, exclude_controls=None, include_with_children=None, exclude_with_children=None)`
Dry-run of what a selection **resolves to**, without mutating.
- No selection args → previews the **committed** selection. Any selection arg supplied →
  previews that **hypothetical** selection (same omit-means-absent semantics + the two
  `*_with_children` booleans as in `set_import_selection`).
- **Returns:** `{"selected": [sorted control-id strings], "warnings": [str, …]}`, or `None`
  (no import, or the imported source isn't loaded/resolved). Use this to catch greedy-glob
  surprises *before* committing.

---

## Typical CyberCraft flows

- **Add a control + its enhancements to scope:**
  `add_import_include(href, ids=["ac-2"], with_children=True)`
- **Flip the include children flag without touching selection:**
  `set_import_with_children(href, include=True)`
- **Remove a row the user deleted in the UI:**
  `remove_import_include(href, ids=["ac-2"])` (or `matching=[{"pattern": "ac-*"}]`)
- **Show the user what a pattern will match before saving:**
  `preview_import_selection(href, include_controls=[{"matching":[{"pattern":"ac-2*"}]}])`
  → inspect `["selected"]`
