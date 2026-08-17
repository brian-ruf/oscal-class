# OSCAL Class

A class for creation, management, validation, and format conversion of OSCAL content.
All published OSCAL versions, formats, and models can be validated and converted.
Creation and management targets OSCAL 1.2.1 and later.

OSCAL XML, JSON, and YAML formats are fully supported. XML is immediately converted
to the internal JSON-native representation on load; XML output is produced on demand.

---

## Model Classes

Eight model classes inherit from the base `OSCAL` class:

```python
from oscal import (
    OSCAL,               # base class — use when model is unknown
    Catalog,
    Profile,
    Mapping,             # mapping-collection model
    ComponentDefinition,
    SSP,
    AssessmentPlan,
    AssessmentResults,
    POAM,
)
```

All factory methods (`load`, `loads`, `acquire`, `new`) are available on every class.
Use a model-specific class when you know the model in advance; use `OSCAL` when you
don't. The `model` attribute identifies the detected model after loading.

---

## Factory Methods

Never instantiate model classes directly — always use one of these class methods.

### `loads` — in-memory content

Use when you already have OSCAL content in memory (string or dict).

```python
from oscal import Catalog

catalog_dict = {
    "catalog": {
        "uuid": "11111111-1111-1111-1111-111111111111",
        "metadata": {
            "title": "In-Memory Catalog",
            "version": "0.1.0",
            "oscal-version": "1.1.3",
        },
        "groups": [],
    }
}

catalog = Catalog.loads(catalog_dict, href="memory://catalog")
```

`href` is optional and serves as a label identifying the content's origin.
`content` may be a JSON/YAML `str` or a `dict`.

### `load` — local file or file-like object

Use to read from a path on the local filesystem, or any file-like object with `.read()`.

```python
from oscal import Catalog

catalog = Catalog.load("./catalog.xml")         # path string
catalog = Catalog.load(Path("./catalog.xml"))   # pathlib.Path
catalog = Catalog.load(open("catalog.json"))    # file-like object
```

The loaded content is read-only by default for file objects; it is set to read-write
for plain path strings (local paths you own).

### `acquire` — URI / reference resolution

Use for content that must be fetched by URI, or when you want to supply a fallback
source list. Accepts a URI string, a reference dict, an `OscalRef`, or a list of any
of these.

```python
from oscal import OSCAL

# Remote URL
doc = OSCAL.acquire("https://raw.githubusercontent.com/.../catalog.json")

# Local file as a URI
doc = OSCAL.acquire("file:///data/oscal/catalog.xml")

# Reference dict (same shape as back-matter rlinks)
doc = OSCAL.acquire({"href": "https://example.com/catalog.xml"})

# Fallback list — first successful source wins
doc = OSCAL.acquire([
    "https://example.com/catalog.xml",
    {"href": "./local-fallback/catalog.xml"},
])
```

### `new` — create from template

Use to create a fresh OSCAL document from the built-in template for a specific model.
Must be called on a model subclass, not on `OSCAL` directly.

```python
from oscal import Catalog, Profile

catalog = Catalog.new(
    title="My New Catalog",
    version="DRAFT-1.0",
    published="2026-04-26T00:00:00Z",
)

profile = Profile.new(title="My New Profile")
```

---

## Model-Aware Loading

When the model is not known in advance, load with `OSCAL` first, then dispatch:

```python
from oscal import OSCAL, Catalog, Profile, Mapping, ComponentDefinition, SSP
from oscal import AssessmentPlan, AssessmentResults, POAM

MODEL_CLASS_MAP = {
    "catalog":                    Catalog,
    "profile":                    Profile,
    "mapping-collection":         Mapping,
    "component-definition":       ComponentDefinition,
    "system-security-plan":       SSP,
    "assessment-plan":            AssessmentPlan,
    "assessment-results":         AssessmentResults,
    "plan-of-action-and-milestones": POAM,
}


def load_typed(path: str):
    """Return the most specific model class for the content at path."""
    generic = OSCAL.load(path)
    cls = MODEL_CLASS_MAP.get(generic.model)
    return cls.load(path) if cls else generic


obj = load_typed("./example/catalog.xml")
print(type(obj).__name__)  # Catalog
print(obj.model)           # catalog
```

---

## Content States

### `content_state` / `ContentState`

A progressive enum that tracks how far through the validation pipeline the content has
progressed. Each level implies all prior levels passed.

```python
class ContentState(IntEnum):
    NONE             = -1  # No content / uninitialized
    NOT_AVAILABLE    = 0   # Unable to acquire content
    ACQUIRED         = 1   # Content was acquired (non-empty string)
    WELL_FORMED      = 2   # Content is well-formed XML, JSON, or YAML
    VALID            = 3   # Content passes OSCAL schema validation
    IMPORTS_RESOLVED = 4   # All imported OSCAL documents resolved successfully
```

Boolean properties are provided for the most common checks:

| Property | True when |
|---|---|
| `.is_acquired` | `content_state >= ACQUIRED` |
| `.is_well_formed` | `content_state >= WELL_FORMED` |
| `.is_valid` | `content_state >= VALID` |
| `.imports_resolved` | `content_state >= IMPORTS_RESOLVED` |

`__bool__` returns `True` when `is_valid` is `True`, so objects can be used directly
in conditionals:

```python
catalog = Catalog.load("catalog.xml")
if catalog:
    print(catalog.title)      # safe to access
else:
    print("Load failed")
```

### `validation_status` and `validation_errors`

After loading, `validation_status` records per-phase results and `validation_errors`
holds structured error dicts from the most recent `validate()` call:

```python
print(catalog.validation_status)
# {
#   "well-formed":    True,
#   "structure":      True,
#   "data-types":     True,
#   "allowed-values": False,
#   "cardinality":    True,
# }

for err in catalog.validation_errors:
    print(err["error-type"], err["location"], err["field"], err["value"])
```

### `validate()` — re-run validation

Call to re-validate after mutating content:

```python
catalog.set_metadata({"title": "Updated Title"})
catalog.validate()
```

---

## Origin and Mutability States

| Property | Type | Description |
|---|---|---|
| `.is_local` | `bool` | `True` for local file source, `False` for remote |
| `.is_remote` | `bool` | Inverse of `is_local` |
| `.is_cached` | `bool` | `True` when remote content has a local cache copy |
| `.is_read_only` | `bool` | `True` when the content must not be mutated |
| `.is_unsaved` | `bool` | `True` when mutations have not been written to disk |
| `.is_editable` | `bool` | `True` when `is_valid`, `is_local`, and not `is_read_only` |
| `.is_fresh` | `bool` | `True` when content is local or cached within its TTL |
| `.is_stale` | `bool` | `True` when remote cached content has exceeded its TTL |
| `.origin_state` | `OriginState` | `LOCAL`, `REMOTE_UNCACHED`, `REMOTE_FRESH`, or `REMOTE_STALE` |
| `.loaded` | `datetime` | Timestamp of when content was acquired |
| `.ttl` | `int` | Cache time-to-live in seconds (0 = never expire) |

---

## Content Summary Attributes

These are populated after a successful load:

| Attribute | Description |
|---|---|
| `.model` | OSCAL model name (e.g. `"catalog"`, `"system-security-plan"`) |
| `.oscal_version` | OSCAL version from the content metadata (e.g. `"v1.1.3"`) |
| `.title` | Document title from metadata |
| `.version` | Document version from metadata |
| `.published` | Publication date from metadata |
| `.last_modified` | Last-modified date from metadata |
| `.remarks` | Remarks from metadata |
| `.original_format` | Format the content was loaded from (`"xml"`, `"json"`, `"yaml"`) |
| `.href` | Working href (may differ from `href_original` after redirect/retry) |
| `.href_original` | Original href as provided at load time |

---

## Serialization

### `dump` — write to file

```python
# Save to a specific path and format
catalog.dump("catalog.json", format="json", pretty_print=True)
catalog.dump("catalog.xml",  format="xml",  pretty_print=True)
catalog.dump("catalog.yaml", format="yaml", pretty_print=True)

# Save to the original location in the original format
catalog.dump()
```

Returns `True` on success. If `filename` or `format` are omitted, `dump()` falls back
to the original source location and format.

### `dumps` — serialize to string

```python
json_str  = catalog.dumps(format="json", pretty_print=True)
xml_str   = catalog.dumps(format="xml",  pretty_print=True)
yaml_str  = catalog.dumps(format="yaml")
```

### Convenience properties

```python
catalog.json   # → JSON string (always pretty-printed)
catalog.xml    # → XML string  (builds XML from dict on demand)
catalog.yaml   # → YAML string (always pretty-printed)
```

---

## Querying Content

Two complementary path-based query methods work on the internal JSON representation.
Both return Python lists. See [QUERY_CONTENT.md](QUERY_CONTENT.md) for the full path
syntax reference.

| Method | Step names | Notes |
|---|---|---|
| `query(path)` / `query_one(path)` | OSCAL **XML element names** (`control`, `prop`, `part`) | Requires metaschema index |
| `json_query(path)` / `json_query_one(path)` | **JSON key names** (`controls`, `props`, `parts`) | No index required |

```python
# query() — XML element name syntax
ctrl  = catalog.query_one('//control[@id="ac-2"]')
title = catalog.query_one('/*/metadata/title')

# json_query() — JSON key name syntax
ctrl  = catalog.json_query_one('//controls[id="ac-2"]')
title = catalog.json_query_one('/*/metadata/title')

# Both accept an optional context dict to scope the search
parts = catalog.query('part[@name="statement"]', context=ctrl)
```

`query_one` and `json_query_one` return the first match or `None` (accepts an optional
`default` argument).

> **Safe-copy ownership.** Public getters and query methods return **detached copies**,
> never live references into the internal `_dict` — this includes query results and the
> node getters (`get_control_by_id`, `get_group_by_id`, `get_control_list`, and
> `Profile.control`). Mutating a returned value does not change the document; all
> mutation must go through the mutation methods below (which enforce the OSCAL standard).
> The private `_dict` attribute is the only sanctioned live-access escape hatch. The
> node getters also take an optional `depth` argument that prunes nested child
> groups/controls (`None` = full subtree, `0` = node only, `N` = N levels).

---

## Mutating Content

All mutation methods require `is_editable` to be `True` (content is valid, local, and
not read-only). They return `None` and log an error when the guard fails. Methods that
return the created node return a **safe copy** of it — edit further via another method
call, not by mutating the return value.

### `set_metadata`

Set scalar metadata fields:

```python
catalog.set_metadata({
    "title":   "Updated Catalog",
    "version": "1.1.0",
})
```

Complex metadata fields (`roles`, `parties`, `locations`, etc.) are not yet supported
and will log a warning if passed.

### `append_child`

Append a dict to any list within the document:

```python
catalog.append_child("back-matter/resources", {
    "uuid":  "aaaaaaaa-0000-4000-a000-000000000001",
    "title": "My Reference",
    "rlinks": [{"href": "https://example.com/ref.html"}],
})
```

The path is slash-separated, relative to the model root. The leaf key is created as an
empty list if it does not yet exist.

### `append_resource`

Convenience wrapper for adding back-matter resources:

```python
catalog.append_resource(
    title="NIST SP 800-53 Rev 5",
    rlinks=[{"href": "catalogs/nist-800-53-rev5.xml"}],
)
```

---

## Import Handling

Imports are resolved automatically when content reaches `ContentState.VALID`. Results
are available via `import_list`. See [IMPORTS.md](IMPORTS.md) for full details.

### `import_list`

Flat list of dicts, one per import statement found in the document:

```python
{
    "href_original": "<href as written in the document>",
    "href_valid":    "<resolved href that loaded successfully>",
    "status":        ImportState.READY,   # READY | NOT_LOADED | INVALID | EXPIRED
    "is_valid":      True,
    "is_local":      False,
    "is_remote":     True,
    "is_cached":     False,
    "object":        <OSCAL object or None>,
    "failure":       None,  # ImportFailure instance on failure
}
```

### `import_tree`

Lazily-built recursive tree of the full import chain. Returns a root node dict with an
`"imports"` key holding the same structure recursively. Rebuilt on first access after
any change; call `rebuild_import_tree()` to force a fresh traversal.

### `failed_imports`

Returns only the entries from `import_list` that have a non-`None` `failure` field:

```python
for entry in doc.failed_imports:
    f = entry["failure"]
    print(f"[{f.code.value}] {entry['href_original']} — {f.message}")
```

### `resolve_imports(base_path="")`

Re-runs import discovery and loading. Called automatically on valid content; call
manually to force a fresh pass or after calling `retry_import`.

### `retry_import(failed_href, replacement_href)`

Retry a single failed import using an alternate source:

```python
doc.retry_import(
    failed_href="https://old-server.example.com/catalog.xml",
    replacement_href="./local-catalog.xml",
)
```

### `walk_imports(visitor_fn, scope="successful")`

Depth-first walk of the import tree. `visitor_fn(entry, depth)` is called for each
entry. `scope` is `"successful"` (default), `"failed"`, or `"all"`.

---

## Deprecated / Legacy Methods

The following methods exist for backward compatibility but are not the preferred API.
They may be removed in a future major release.

### `open(source, *, href=None)`

A universal constructor that inspects the source type and delegates to `load()` or
`acquire()`. Prefer using `load()` or `acquire()` directly, which are more explicit
about their behaviour:

| `open()` routes to… | When source is… |
|---|---|
| `load()` | A `str` path (no URI scheme), `pathlib.Path`, or file-like object |
| `acquire()` | A URI string with a scheme (`http://`, `file://`, etc.), `OscalRef`, dict, or list |

```python
# Legacy — avoid in new code
obj = OSCAL.open("catalog.xml")             # delegates to load()
obj = OSCAL.open("https://example.com/…")  # delegates to acquire()

# Preferred equivalents
obj = OSCAL.load("catalog.xml")
obj = OSCAL.acquire("https://example.com/…")
```

### `from_string(content, *, href=None)`

An explicit alias for `loads()`. Use `loads()` directly:

```python
# Legacy
obj = OSCAL.from_string(json_str)

# Preferred
obj = OSCAL.loads(json_str)
```

### `retry_imports(failed_href, replacement_href)`

Plural alias for `retry_import()`. Use `retry_import()` directly.
