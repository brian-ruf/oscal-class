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
| `"metaschema"` | NIST resolved-metaschema XML |
| `"document-model"` | Model root-name registration (internal) |
| `"processed"` | Parsed metaschema index (JSON) used for validation and conversion |

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

### `get_metaschema_index(version, model) → dict | None`

Return the parsed metaschema index for a given version and model. Results are cached
in memory for up to 24 hours. Returns `None` when no index has been built for the
requested combination.

```python
index = support.get_metaschema_index("v1.1.3", "catalog")
```

### `add_asset(version, model, asset_type, content, filename=None) → bool`

Store a new or replacement asset in the support database. `content` may be `str` or
`bytes`. Returns `True` on success.

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
