# Patterns getters must follow in this library

Conventions observed across the existing getters (`Catalog`/`Profile` in
`oscal_controls.py`, `SSP`/`ComponentDefinition` in `oscal_implementation.py`, and the
common cross-reference layer in `oscal_content.py`). New getters are expected to adhere to
them so the API stays uniform across models.

1. **Safe copies only.** Every getter returns a detached `copy.deepcopy`, never a live
   reference into `self._dict` (including list elements). Mutation stays in the enforcing
   methods. (CLAUDE.md "Getters return safe copies".)

2. **Index vs. full split.** Plural getters return a *summarized index* (lightweight:
   identity + a few flattened props + child counts/cross-refs); the singular getter
   returns the *full, enriched* object. Precedent: `SSP.inventory_items()` (index) vs.
   `SSP.inventory_item(uuid)` (full + resolved components + responsibilities);
   `cDef.components()` vs. `cDef.component(uuid)`.

3. **Injected (resolved) content is an added sibling, never a reshape.** Resolvers add
   keys alongside the raw OSCAL fields and leave the originals intact. Precedents:
   - `_resolve_responsibility_entry` → adds `title` (from `role-id`) + `parties` (full
     party objects from `party-uuids`).
   - `SSP.user()` → adds a `roles` sibling next to `role-ids`.
   - `SSP.inventory_item()` → adds a `component` child inside each `implemented-component`.
   - `SSP.leveraged_authorization()` → adds `name`/`short-name` + `component-uuids`.

4. **Invalid references surface, not vanish.** A dangling reference yields a visible
   placeholder (e.g. `SSP.inventory_item` uses
   `{"title": "[Invalid Component Reference]", "type": "unknown"}`), except where the
   established choice is to *omit* unresolved entries (`inventory_items()` index,
   `leveraged_authorization().components`). Pick one policy per getter.

5. **`include_*` flags gate expensive / cross-import injection.** `with_control`,
   `include_components`, `include_resources`, `include_controls` default to the cheap
   path. Precedent throughout `oscal_implementation.py`.

6. **`depth` prunes nested tree children only.** `prune_tree_copy(node, depth,
   child_keys=(...))` returns the node's own content in full and limits only the named
   nested collection (e.g. assessment `task` nests `task` → `child_keys=("tasks",)`).
   `None` = full subtree, `0` = node only, `N` = N levels.

7. **Cross-import cascade is centralized.** `get_*_by_uuid/id` on the base class resolve
   this document first, then depth-first through the import tree (de-duplicated,
   cycle-safe) via `find_in_import_tree` / `_lookup_in_scope`, with `with_source` and
   `local_only` options. Plural `_collect_in_scope` adds a `source-document` origin
   annotation + first-wins de-dup. These already cover `resource`, `role`, `party`,
   `location`, `responsible-party`, `action`, `param`, `control`, `group`, `part` — so
   getters inherit party/role/resource/control resolution for free across a model's import
   chain.
