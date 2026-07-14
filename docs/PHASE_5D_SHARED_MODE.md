# Phase 5d — Shared Mode (multi-process / multi-user workspaces)

Status: **not started.** This document captures the intention for 5d and the
groundwork already in place, so it can be picked up in a later session.

---

## 1. Intention

The `Workspace` (phases 5a–5c) is a set of related OSCAL documents with an
isolated in-memory object graph, a persistent SQLite **project file**, and
**in-memory write locks** for multiple views inside a *single* application
instance.

**Shared mode (5d)** extends this to **multiple processes / users** collaborating
on the *same workspace*, coordinated through the workspace file:

- Locks and content changes are **durable and cross-process**, mediated by the
  workspace SQLite file (later an ANSI SQL server — Postgres, etc. — for scale;
  same schema, different backend).
- Each process keeps its **own** in-memory object graph; the file is the shared
  source of truth for **who holds which write lock** and **what the current
  content/state is**.
- **No shared authoring of raw XML/JSON/YAML OSCAL files.** Collaboration happens
  on the *workspace/project*, never on the underlying files directly.
- Trajectory: single-user desktop → small teams (2–10) now; enterprise scale is
  years away but should not be designed out.

The guiding principle established in 5c: mutation permission is enforced uniformly
through `OSCAL.is_read_only`, and "locked by another actor" is one of its inputs.
Shared mode only needs to make that lock check consult **durable, cross-process**
lock state instead of the current in-process dict.

---

## 2. Groundwork already in place (what 5d can build on)

### Workspace core + isolation (`oscal/oscal_workspace.py`)
- `Workspace` owns an isolated `ObjectRegistry` and injects it into every loaded
  document (root + transitive imports) via a **contextvar** activation
  (`oscal_registry.use_registry`; `get_registry()` is context-aware).
- Root documents are **shared within a workspace, keyed by canonical source
  path/href** (`_source_key` → `_canonicalize_ref`). This is the deliberate,
  edit-stable handle (content UUID churns on every edit, so it is *not* used to
  key open documents). **5d durable locks should key on this same source/doc
  handle**, not `id(doc)`.

### Persistent project file (save/load)
`Workspace.save(path)` / `Workspace.load(path)` persist to one SQLite file,
reusing the shared `filecache` schema (no support-DB schema change). Tables today:
- `filecache` — content blobs (each document serialized as JSON).
- `workspace_meta` — key/value: `title`, `path`, `last_modified`, `remarks`,
  `attributes` (extensible project-specific attributes, JSON).
- `workspace_documents` — per document: `doc_id`, `source`, `is_root`, `model`,
  `oscal_version`, `uuid`, `original_format`, `content_state`, `is_canonical`,
  `is_read_only`, `filecache_uuid` (content), `imports` (edge JSON), `state`
  (derived state JSON).

Reload is **self-contained** (no refetch): documents are rehydrated from stored
content + state and the import tree is rewired.

> There is **no `workspace_locks` table yet** — creating it is the first concrete
> 5d task (see §3).

### Derived-state persistence hook (for indexes)
`OSCAL._export_state()` / `_import_state()` (subclasses override, calling `super`)
serialize derived state into the `workspace_documents.state` column so it need not
be recomputed on reload. Base captures validation results + dirty-state; `Profile`
adds resolution state. **Future indexes plug in here** and will need to sync in
shared mode.

### In-memory write locks (5c) — the API shared mode must make durable
- **Current actor** (who is editing) is a contextvar in `oscal_content`:
  `current_actor()`, `use_actor(actor)`. `Workspace.as_actor(actor)` is the
  convenience wrapper.
- **Lock manager on `Workspace`:** `self._locks: dict[id(doc) -> actor]`, with
  `lock(doc, actor=None)`, `unlock(doc, actor=None)`, `lock_holder(doc)`,
  `is_locked(doc)`. Re-locking by the holder is idempotent; only the holder may
  release; `close()` releases a document's lock.
- **Enforcement is uniform:** `OSCAL.is_read_only` returns
  `self._is_read_only or self.is_canonical or self._locked_by_other()`, and
  `_locked_by_other()` consults `self._workspace.lock_holder(self)` vs
  `current_actor()`. Because *both* mutation gates (`_can_mutate` and
  `@requires(is_read_only=False)`) check `is_read_only`, locks are honored by every
  mutation path with no per-method wiring.
- **Back-reference:** every workspace document has `doc._workspace` set (by
  `_bind` and `_rehydrate`), which is how `_locked_by_other()` finds the lock
  manager.

**Key insight for 5d:** the lock manager is accessed only via
`ws.lock_holder(self)` (duck-typed on `self._workspace`). Shared mode can swap in a
lock manager that reads/writes the file **without touching `oscal_content`** —
`_locked_by_other()` already delegates to the workspace.

---

## 3. What remains for 5d

1. **Durable lock table.** Add a `workspace_locks` table to the project file:
   `target` (stable document key — source href / `doc_id`), `holder` (actor/session),
   `acquired` (timestamp), `heartbeat` (for stale-lock reclamation), optional
   `granularity`/`path` for future sub-document locks. Do **not** modify the shared
   `filecache` schema; this is a new table in the workspace DB only.

2. **Cross-process lock acquisition.** `lock()/unlock()` must read/write the lock
   table in an **atomic transaction** so two processes can't both acquire. Re-key
   locks from `id(doc)` to the **stable document key** (source/`doc_id`) so a lock
   set by process A is recognizable by process B.

3. **Honor foreign locks.** `_locked_by_other()` (via the workspace lock manager)
   must consult the durable table, not just the in-memory dict, when the workspace
   is in shared mode.

4. **Content sync.** When one process edits and persists a document, others must
   detect the change (e.g. a `revision`/`last_modified` column per document, or a
   change log) and **reload the affected documents** into their own in-memory
   graph. Decide the notification mechanism (poll the DB on an interval vs. an
   external signal). Optimistic-concurrency check on save (compare stored
   `last_modified`/version before overwrite) to catch conflicts.

5. **Presence & stale locks.** Heartbeat/expiry so a crashed process's locks can
   be reclaimed; optional "who is here / who holds what" for a UI.

6. **Actor/session identity across processes.** Define how actors are assigned and
   authenticated in a multi-user setting (currently an opaque string via
   `use_actor`).

7. **ANSI SQL backend.** The `ruf_common.database` layer already abstracts the
   backend (`Database(type, target)`), mirroring the support DB's "local SQLite now,
   scale later" path. 5d should keep the schema backend-neutral.

---

## 4. Design notes / decisions carried forward

- **Cache stays global.** The remote-content disk cache (`oscal_cache`,
  `local_cache.db`) is a machine-level resource shared across workspaces and
  processes — not per-workspace. Unaffected by 5d.
- **Registry stays per-process / per-workspace.** Each process has its own live
  objects; the file is the coordination point, not a shared object store.
- **Lock granularity** is whole-document for now. Element-level locking is a
  possible later refinement (the `workspace_locks` table can carry a `path`).
- **Keying:** in-memory locks use `id(doc)` (safe because roots are shared objects
  within one process). Durable/cross-process locks **must** use the stable source /
  `doc_id` key.

---

## 5. Where things live (code pointers)

| Concern | Location |
| --- | --- |
| Workspace, save/load, lock manager | `oscal/oscal_workspace.py` |
| Registry + contextvar injection | `oscal/oscal_registry.py` (`get_registry`, `use_registry`) |
| Current actor + `is_read_only` enforcement | `oscal/oscal_content.py` (`current_actor`, `use_actor`, `is_read_only`, `_locked_by_other`, `_can_mutate`) |
| Derived-state hooks | `oscal/oscal_content.py` (`_export_state`/`_import_state`); `Profile` override in `oscal/oscal_controls.py` |
| Disk cache (global) | `oscal/oscal_cache.py` |
| Tests | `tests/unit/test_workspace.py` (core, save/load, typed instances, state, **locks**) |

A future session can start at §3 item 1 (durable lock table) and item 2
(cross-process acquisition), since `_locked_by_other()` already routes lock checks
through the workspace — only the lock manager's storage needs to change.
