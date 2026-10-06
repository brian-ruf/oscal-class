# Design: harden the support-DB staleness self-heal

Status: proposed (2026-10-05). No code changed yet — this is the write-up for review.

## Symptom

A runtime support DB (`./support/oscal_support.db`, resolved relative to the **runtime CWD**)
that predates the step-2 tiering work is silently trusted and served under the current
index label, so the validator runs with **pre-tiering processed indexes** (no
`validation-level` / `l2b-spec` / `match-spec` / …). Against a resolved FedRAMP HIGH
catalog this produces **1941 false `allowed-values` errors** on nested scoped `part/@name`
values (e.g. `item`), even though HEAD + the fresh 2.7.0 bundle validates it with **0**
errors. A venv rebuild does not fix it because the DB is a runtime artifact, not part of
the installed package.

Reproduced in-repo: stripping `validation-level`/`l2b-spec` from the in-memory v1.1.3
catalog index yields exactly 1941 `allowed-values` errors — the number CyberCraft reports.

## Root-cause chain (all confirmed in `oscal_support.py`)

1. **Fabricated currency.** The schema migration backfills
   `UPDATE oscal_versions SET index_version = '{METASCHEMA_INDEX_VERSION}' WHERE index_version IS NULL`
   (≈L782-785; and the merge path ≈L646-650). A pre-versioning DB (NULL rows, stale
   content) is stamped the **current** version uniformly — a lie about the content.
2. **resolve trusts it.** `resolve_index_version` keeps versions in `[current, next-major)`;
   the fabricated-current rows qualify, so no heal is triggered.
3. **Reconcile skips it.** `get_metaschema_index` only rebuilds when the *stored processed
   JSON* embeds an `index_version` of a **different major**. Pre-versioning JSON embeds
   **no** `index_version`, so `stored_iv` is falsy → rebuild skipped → stale content served.
   It also *trusts same-major-older* — but our minor bumps (2.1→2.7) ADDED
   consumer-required data (`l2b-spec`, `match-spec`, `card-spec`, `expect-spec`,
   `validation-level`), so "same major is backward compatible" is false for this library.
4. **auto reuses stale.** `auto` init re-extracts the bundled DB only when the file is
   absent/empty; a non-empty stale DB is reused as-is.
5. **Heal can't replace.** `_merge_from_bundled_db` uses `INSERT OR IGNORE` — it only ADDS
   missing versions; it never replaces an existing (stale) version's rows. So even if heal
   fired, a stale `v1.1.3` would survive.

Any one of these alone would be recoverable; together they make a stale DB undetectable and
unfixable short of manually deleting the file.

## Principle

`oscal_versions.index_version` must reflect **the parser that built the stored content**,
never the running library. The consumer must refuse to run on content older than its own
index schema, and the self-heal must be able to **replace** stale content, not just add
missing versions.

## Fix (four small, independent changes)

### 1. Truthful backfill (stop fabricating currency)
Replace the blanket `WHERE index_version IS NULL → current` backfills (migration + merge)
with a per-version derivation from the stored content:

- Add `_embedded_index_version(version) -> str | None`: read any one processed index for
  that version, `json.loads`, return its embedded `index_version` (the parser already
  stamps `metaschema_tree["index_version"]` at build) or `None`.
- Backfill each NULL row to that embedded value when present, else to a **sentinel
  `"0.0.0"`** meaning "pre-versioning / unknown — treat as incompatible". Never to current.

Effect: a pre-versioning DB now reads as `0.0.0` (out of `[current, next-major)`), so
resolve's existing heal path fires.

### 2. Reconcile on missing/older embedded version
In `get_metaschema_index`, treat the stored index as incompatible when its embedded
`index_version` is **missing** OR `compare_semver(stored_iv, resolved_iv) < 0` (older,
including older-same-major) — not only on a different major. On incompatibility: rebuild
from raw metaschema if present; otherwise **refresh this version/model from the bundled DB**
(see #3) and re-read. Guarantees stale/pre-versioning content is never served.

### 3. Heal that REPLACES
Add `_refresh_versions_from_bundle(versions)`: for each version, DELETE its
`oscal_support` + referenced `filecache` + `oscal_versions` rows, then insert the bundle's
rows (reuse the existing ATTACH/`_common_columns` copy, but preceded by a scoped delete).
`resolve_index_version` (when no in-range candidate) and `get_metaschema_index` (on
incompatibility) call this instead of the add-only merge. Keep `INSERT OR IGNORE` merge for
the genuine "add missing version" case.

### 4. auto-init staleness guard (belt-and-suspenders)
After opening an existing DB in `auto` mode, if `resolve_index_version` lands on the
fallback (no in-range candidate) or any version resolves to the `0.0.0` sentinel,
proactively `_refresh_versions_from_bundle(stale_versions)`. With #1 making versions
truthful and #3 making the refresh effective, this needs no manual DB deletion.

## Tests (new `tests/unit/test_support_db_staleness.py`)

- **Pre-versioning DB heals:** build a fixture from the bundled 2.7.0 DB with v1.1.3 catalog
  processed JSON stripped of `index_version`/`validation-level`/`l2b-spec` and its
  `oscal_versions.index_version` set NULL. Open with `OSCALSupport(auto)`. Assert: resolves
  to current via refresh; `get_metaschema_index('v1.1.3','catalog')` now carries
  `validation-level`/`l2b-spec`; loading the FedRAMP HIGH resolved catalog → **0** errors.
- **Older-same-major heals:** stamp v1.1.3 `index_version='2.2.0'` with pre-l2b content →
  `get_metaschema_index` detects `stored < current` → refresh → 0 errors.
- **No needless work:** a current 2.7.0 DB is left untouched (no refresh, no rebuild) — guard
  with a spy/counter on `_refresh_versions_from_bundle`.
- **Add-missing still add-only:** merging a version absent locally doesn't clobber unrelated
  present versions.

## Back-compat / rollout

- Existing deployments with stale runtime DBs **auto-refresh the affected versions from the
  bundle on next load** — no manual delete, no re-fetch, offline-safe (bundle is packaged).
- `"0.0.0"` is an internal sentinel, never surfaced as a real OSCAL/index version.
- Cost: one scoped delete+copy per stale version per process; negligible.
- The immediate operator remedy (delete the stale `./support/oscal_support.db` +
  `local_cache.db`) remains valid but becomes unnecessary once this lands.

## Out of scope (note for later)

- The CWD-relative default DB path (`./support/oscal_support.db`) means different working
  directories get different DBs. Not changed here, but worth considering a user-cache
  location (e.g. platformdirs) so one refreshed DB serves all CWDs.
