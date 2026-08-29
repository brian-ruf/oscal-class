---
---

# The OSCAL Support Module

The OSCAL Support Module acquires, stores, and serves local copies of NIST-published
OSCAL support files used for validation and format conversion.

The support database distributed with this library is pre-populated with all OSCAL
versions available at release time, enabling offline and air-gapped operation.

---

## Designed for Air-Gapped Environments

The module keeps OSCAL support artifacts in a local SQLite database so applications
can validate and convert OSCAL content without a live network dependency.

When needed, you can update support content from an internet-connected machine and
then move the updated database to offline environments.

---

## Database Defaults

| Setting | Default |
|---|---|
| Path | `./support/oscal_support.db` (relative to runtime working directory) |
| Type | `sqlite3` |
| Compression | Support files are compressed in the database for size efficiency |

> **Path note**: `get_support()` resolves the default path relative to the **current
> working directory at runtime**, not the package root. When running `pytest` from the
> repo root the DB is `support/oscal_support.db`; when running scripts from inside
> `tests/` the DB used is `tests/support/oscal_support.db`. Both copies exist in the
> repo.

---

## Primary API

The canonical class name is `OSCALSupport`. Always access it through the module-level
functions rather than instantiating it directly.

```python
from oscal.oscal_support import configure_support, get_support

# Optional explicit configuration — call before loading any OSCAL content
# if you need non-default settings.
configure_support(db_path="/path/to/support.db", init_mode="auto")

# Obtain the shared support singleton (creates it with defaults if needed)
support = get_support()
```

### `configure_support`

```python
configure_support(
    db_path="./support/oscal_support.db",  # path to the SQLite database file
    init_mode="auto",                       # database initialization mode
)
```

Both Pythonic keyword names and legacy positional names are accepted:

| Pythonic | Legacy positional |
|---|---|
| `db_path` | `support_file` |
| `init_mode` | `db_init_mode` |

**`init_mode` values:**

| Value | Behaviour |
|---|---|
| `"auto"` | Extract packaged DB when file is missing or empty; use existing file otherwise |
| `"extract"` | Always try to extract the packaged DB; create an empty DB if extraction fails |
| `"create"` | Always create an empty DB from scratch |

### `get_support`

Returns the shared `OSCALSupport` singleton, creating it with default settings if it
does not yet exist. This is the function called internally by all OSCAL content classes.

---

## Updating Support Content

```python
support = get_support()

# Check for new OSCAL releases and fetch any that are not yet in the DB (default)
support.update()
support.update(mode="new")    # same as default

# Re-fetch all supported versions
support.update(mode="all")

# Re-fetch a specific version only
support.update(mode="v1.0.4")
```

For backward compatibility, `update(fetch="...")` is also accepted as an alias for
`update(mode="...")`.

---

## Core Methods

### `get_asset(version, model, asset_type) → str | None`

Return the stored support file content for the given version, model, and asset type.
Returns `None` if the asset is not found.

```python
content = support.get_asset("v1.1.3", "catalog", "metaschema")
```

Common asset types stored in the database:

| Type | Contents |
|---|---|
| `"metaschema"` | NIST resolved-metaschema XML (build-time input for the parsed index) |
| `"document-model"` | Build-time tag marking which metaschema files define a document root; shares the `metaschema` row's cache file |
| `"processed"` | Parsed metaschema index (JSON) used for validation and conversion |

The **packaged** support database is minimized to only `"processed"` indexes — the
`"metaschema"` inputs and the redundant `"document-model"` tags are pruned after the
indexes are built (the update tool calls `remove_asset` + `vacuum`), and `list_models`
derives the document models from the `"processed"` assets. A minimized database supports
validation and conversion but cannot *rebuild* an index from raw metaschema (needed only
on an incompatible index-schema major); re-acquire the version from NIST if that arises.

### `get_datatype(datatype_name) → dict | None`

Return the OSCAL Metaschema definition for a named data type (a safe copy), or
`None` if the name is not a recognized OSCAL data type. The definition includes
the validation patterns (`xml-pattern`, `json-pattern`, `recommended-pattern`),
`base-type`, documentation, and reference links — for example, to validate a
field's input against the regex for its declared data type. The full table is
also available as the `datatypes` attribute.

```python
dt = support.get_datatype("date-time-with-timezone")
regex = dt["json-pattern"]      # hand off to a UI for field-level validation
```

### `list_models(version="all") → list[str]`

Return the list of OSCAL model names available for the given version.

```python
support.list_models("v1.1.3")
# → ["catalog", "profile", "system-security-plan", ...]

support.list_models()          # all models across all versions
support.list_models("all")     # same
```

### `is_valid_model(model, version="all") → bool`

```python
support.is_valid_model("catalog", "v1.1.3")  # True
support.is_valid_model("bogus")              # False
```

### `is_valid_version(version) → bool`

```python
support.is_valid_version("v1.1.3")  # True
support.is_valid_version("v9.9.9")  # False
```

### `latest_version() → str | None`

Return the highest version string in the support database.

```python
support.latest_version()   # e.g. "v1.2.1"
```

### `get_metaschema_index(version, model, index_version=None) → dict | None`

Return the parsed metaschema index for a given version and model. Results are cached
in memory for up to 24 hours, keyed by `(version, model, index_version)`. Returns `None`
when no index has been built for the requested combination.

`index_version` is the **metaschema-index-schema** version to require; it defaults to
`support.active_index_version` (resolved at startup — see *Metaschema Index Versioning*
below). A stored index built against a different **major** index version is rebuilt from
the raw metaschema so it conforms to the current schema; a same-major difference is
treated as backward-compatible and used as-is.

```python
index = support.get_metaschema_index("v1.1.3", "catalog")
```

### `add_asset(version, model, asset_type, content, filename=None) → bool`

Store a new or replacement asset in the support database. `content` may be `str` or
`bytes`. Returns `True` on success.

### `remove_asset(version=None, model=None, asset_type=None) → int`

Remove support assets matching any combination of `version` / `model` / `asset_type`
(the criteria are ANDed; **at least one is required**). Matching `oscal_support` rows are
deleted, and each cached file is removed from `filecache` once it is no longer referenced
by any surviving asset row (a single file can back several rows — e.g. a document model's
`metaschema` and `document-model` share one cache entry). Returns the number of rows
removed.

```python
support.remove_asset(asset_type="metaschema")            # drop all raw metaschema files
support.remove_asset(version="v1.2.3", model="catalog")  # drop one model's assets
```

### `vacuum() → None`

Reclaim free space in the support database (SQLite `VACUUM`); a no-op on other backends.
Useful after a bulk `remove_asset`.

### `load_file(name, binary=False, *, as_bytes=None) → str | bytes | None`

Load a file from the packaged `oscal.data` resources (not from the support database).
Used internally to load template files for `new()`. Results are cached in memory.

```python
content     = support.load_file("catalog.xml")            # str (default)
raw_bytes   = support.load_file("catalog.xml", binary=True)
raw_bytes   = support.load_file("catalog.xml", as_bytes=True)  # compat alias
```

`as_bytes` is a keyword-only compatibility alias for `binary`; either form works.

### `export_support_files(export_path="./support_files") → bool`

Export all support files to the filesystem, organized by version. Useful for
inspection or air-gapped transfer.

### `download_schemas(support_dir, fetch="all") → bool`

Download OSCAL XML and JSON schema files directly from GitHub to the filesystem.
These are stored on disk (not in the support DB) and can be used for external
validation tools.

```python
support.download_schemas("./schemas")            # all versions
support.download_schemas("./schemas", fetch="v1.2.1")  # one version
```

---

## Metaschema Index Versioning

The parsed metaschema index (the `"processed"` asset consumed by validation and
conversion) has its own **semantic version**, independent of the OSCAL version it
describes. It is exposed as the module constant `METASCHEMA_INDEX_VERSION` (current:
`1.0.0`).

- **MAJOR** bumps mean the index *structure* changed incompatibly — a library built for
  an older major cannot safely consume such an index and will rebuild it.
- **MINOR/PATCH** bumps are backward-compatible additions.

Every index this library builds is stamped with `METASCHEMA_INDEX_VERSION`, and each
`oscal_versions` row records the index version its stored indexes were built with in the
`index_version` column. This lets a library and a shared support database detect and
reconcile index-schema mismatches — the recurring source of "works from here, fails from
there" support-database problems.

### Startup resolution — `resolve_index_version()`

On startup the support layer:

1. Runs a lightweight schema migration (adds the `index_version` column to an older
   database and backfills existing rows to `1.0.0`, since indexes built by this codebase
   already conform to the current schema).
2. Reads the distinct `index_version` values recorded in `oscal_versions` and keeps those
   in the compatible range `[METASCHEMA_INDEX_VERSION, next-major)`.
3. Assigns the **lowest** in-range value to `support.active_index_version` (the most
   conservative compatible schema), which is then used for every `get_metaschema_index`
   lookup.
4. If **no** compatible index version is present, it merges the library's **bundled**
   database (which ships indexes built at this library's index version) into the local
   one and retries — logging a warning.

### Self-healing version acquisition — `ensure_version(version)`

Whenever content declares an OSCAL version that is not present locally, the library
acquires or substitutes it, and records the outcome on the loaded object
(`doc.version_support` — see below):

1. Already present → use it (`"exact"`).
2. Merge that version from the **bundled** database if present (offline; logged INFO).
3. Otherwise **fetch it from NIST GitHub** (logged INFO on success).
4. If still unavailable → substitute the **closest available version within the same
   OSCAL major** (logged WARN; `"closest-match"`).
5. If nothing usable exists → `"unavailable"` (logged ERROR).

This means users on different library versions can safely share one support database: a
missing OSCAL version is healed from the bundle rather than corrupting the shared DB.

### Loaded-object status — `VersionSupport`

Every loaded OSCAL object carries a non-progressive version-support qualifier alongside
its `content_state`:

| `doc.version_support` | Meaning |
|---|---|
| `VersionSupport.EXACT` | The declared OSCAL version's support was available (or was acquired); validated/converted against that exact version. |
| `VersionSupport.CLOSEST_MATCH` | The declared version was unavailable; the closest same-major version was substituted. `doc.requested_oscal_version` and `doc.resolved_oscal_version` differ. |
| `VersionSupport.UNSUPPORTED` | The declared version/model could not be supported at all; the document cannot advance past `ACQUIRED`. |

```python
doc = OSCAL.loads(content)
if doc.version_support is VersionSupport.CLOSEST_MATCH:
    print(f"Validated {doc.requested_oscal_version} against {doc.resolved_oscal_version}")
```

---

## Compatibility Aliases

| Current name | Deprecated alias |
|---|---|
| `OSCALSupport` | `OSCAL_support` |
| `configure_support(...)` | `setup_support(...)` |
| `get_asset(...)` | `asset(...)` |
| `list_models(...)` | `enumerate_models(...)` |
| `is_valid_model(...)` | `is_model_valid(...)` |
| `latest_version()` | `get_latest_version()` |
| `load_file(..., binary=True)` | `load_file(..., as_bytes=True)` |

---

## Packaging Update Utility

The repository includes an internal maintenance script that re-fetches support assets
and rebuilds the distributable support DB:

```bash
python oscal/update_support.py --new   # fetch any new OSCAL versions
python oscal/update_support.py --all   # re-fetch all versions
```

This script is intended for library maintainers, not library consumers.

---

## Future Direction

The support layer currently targets SQLite while using ANSI SQL-oriented patterns
intended to ease future support for additional relational backends.
