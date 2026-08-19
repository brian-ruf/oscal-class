---
---

# Getting Started

The `oscal` library simplifies working with OSCAL content while providing fine-grained
control when you need it. It handles loading, validation, format conversion, and content
manipulation for all published OSCAL versions and models.

---

## Installation

```bash
pip install oscal
```

Or add to `pyproject.toml` / `requirements.txt`:

```
oscal
```

For the latest unreleased code from the development branch:

```
git+https://github.com/brian-ruf/oscal-class.git@develop#egg=oscal
```

---

## Importing

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

---

## Loading Content

Three factory methods cover every loading scenario. Never instantiate model classes
directly — always use one of these.

### `load` — from a local file

```python
from oscal import Catalog

catalog = Catalog.load("./catalog.xml")
```

Accepts a path string, `pathlib.Path`, or any file-like object with `.read()`. XML,
JSON, and YAML are all supported; the format is detected automatically.

### `loads` — from in-memory content

```python
from oscal import Catalog

json_str = '{"catalog": {"uuid": "...", "metadata": {...}}}'
catalog  = Catalog.loads(json_str, href="memory://my-catalog")

# Also accepts a dict directly
catalog = Catalog.loads(catalog_dict)
```

`href` is optional and serves as a label for the source location.

### `acquire` — by URI or reference

```python
from oscal import OSCAL

# Remote URL
doc = OSCAL.acquire("https://raw.githubusercontent.com/.../catalog.json")

# Local file as a URI
doc = OSCAL.acquire("file:///data/oscal/catalog.xml")

# Reference dict (mirrors the OSCAL back-matter rlink shape)
doc = OSCAL.acquire({"href": "./catalog.xml"})

# Fallback list — first successful source wins
doc = OSCAL.acquire([
    "https://primary.example.com/catalog.xml",
    "./local-fallback/catalog.xml",
])
```

### `new` — create from a template

Must be called on a specific model class, not on `OSCAL` directly.

```python
from oscal import Catalog

catalog = Catalog.new(
    title="My Control Catalog",
    version="1.0.0",
    published="2026-06-01T00:00:00Z",
)
```

---

## Checking the Load Result

All factory methods return an object even when loading fails — check the state before
using the content. The object is truthy when content is valid:

```python
catalog = Catalog.load("./catalog.xml")

if not catalog:
    print(f"Load failed. Content state: {catalog.content_state.name}")
else:
    print(f"Loaded: {catalog.title} ({catalog.model} {catalog.oscal_version})")
```

For finer-grained checks:

| Property | True when |
|---|---|
| `catalog.is_acquired` | Content was retrieved (non-empty) |
| `catalog.is_well_formed` | Content parsed successfully |
| `catalog.is_valid` | Content passed OSCAL schema validation |
| `catalog.imports_resolved` | All imported documents loaded |

### Inspecting validation errors

```python
if not catalog.is_valid:
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

---

## When the Model is Unknown

Use the base `OSCAL` class to load content of unknown model, then dispatch to the
typed class:

```python
from oscal import OSCAL, Catalog, Profile, SSP
# ... (import all model classes)

MODEL_CLASS_MAP = {
    "catalog":                       Catalog,
    "profile":                       Profile,
    "system-security-plan":          SSP,
    # ... add remaining models
}

def load_typed(path: str):
    generic = OSCAL.load(path)
    cls = MODEL_CLASS_MAP.get(generic.model)
    return cls.load(path) if cls else generic

doc = load_typed("./unknown-document.xml")
print(type(doc).__name__, doc.model)
```

---

## Saving Content

### `dump` — to a file

```python
# Explicit path and format
catalog.dump("catalog.json", format="json", pretty_print=True)
catalog.dump("catalog.xml",  format="xml",  pretty_print=True)
catalog.dump("catalog.yaml", format="yaml")

# No arguments — saves to the original path in the original format
catalog.dump()
```

Conversion between formats happens automatically; no additional setup is required.

### `dumps` — to a string

```python
json_str = catalog.dumps(format="json", pretty_print=True)
xml_str  = catalog.dumps(format="xml")
yaml_str = catalog.dumps(format="yaml")
```

### Convenience properties

```python
catalog.json   # → JSON string
catalog.xml    # → XML string
catalog.yaml   # → YAML string
```

---

## Querying Content

Two path-based query methods work on the internal JSON representation. Both return
Python lists.

```python
# query() — uses OSCAL XML element names (control, prop, part, ...)
ctrl  = catalog.query_one('//control[@id="ac-2"]')
title = catalog.query_one('/*/metadata/title')
props = catalog.query('//control[@id="ac-2"]/prop[@name="label"]')

# json_query() — uses JSON key names (controls, props, parts, ...)
ctrl  = catalog.json_query_one('//controls[id="ac-2"]')
title = catalog.json_query_one('/*/metadata/title')
```

`query_one` / `json_query_one` return the first match or `None`. See
[QUERY_CONTENT.md](QUERY_CONTENT.md) for the full path syntax.

---

## Mutating Content

Content loaded from a local path is read-write by default. Content loaded remotely or
from file-like objects is read-only.

```python
if catalog.is_editable:
    catalog.set_metadata({"title": "Updated Title", "version": "1.1.0"})
    catalog.dump()   # save back to the original file
```

> **Getters and mutator returns are safe copies.** Read accessors (e.g.
> `get_control_by_id`, `get_group_by_id`, query methods) and creation/mutation
> methods (`create_control`, `create_control_group`, `add_part`, `set_title`,
> `set_label`, …) all return a **detached copy** of the affected node. Editing that
> copy does not change the document — make persistent changes by calling another
> mutation method. The private `_dict` attribute is the only live-access hatch.

See [CONTENT.md](CONTENT.md) for `append_child`, `append_resource`, and other
mutation methods.

---

## End-to-End Example

```python
from oscal import Catalog

# 1. Create a new catalog
catalog = Catalog.new("Quick Start Catalog", version="1.0.0")

# 2. Add a control group and controls (Catalog-specific methods)
catalog.create_control_group(
    parent_id="",
    id="ac",
    title="Access Control",
    props=[{"name": "label", "value": "AC"}],
)
catalog.create_control(
    parent_id="ac",
    id="ac-1",
    title="Access Control Policy",
    props=[{"name": "label", "value": "AC-1"}],
    statements=["Develop and disseminate an access control policy."],
)

# 3. Save to multiple formats
catalog.dump("my-catalog.json", format="json", pretty_print=True)
catalog.dump("my-catalog.xml",  format="xml",  pretty_print=True)

# 4. Load back and verify
loaded = Catalog.load("my-catalog.json")
print(loaded.title)          # "Quick Start Catalog"
print(loaded.is_valid)       # True

# 5. Query content
ctrl = loaded.query_one('//control[@id="ac-1"]')
print(ctrl["title"])         # "Access Control Policy"
```

---

## Further Reading

| Document | Contents |
|---|---|
| [CONTENT.md](CONTENT.md) | Complete class API: all factory methods, states, properties, mutation, and import handling |
| [QUERY_CONTENT.md](QUERY_CONTENT.md) | Full path syntax for `query()` and `json_query()` |
| [IMPORTS.md](IMPORTS.md) | Import resolution, failure codes, and retry patterns |
| [CONVERTERS.md](CONVERTERS.md) | Format conversion internals (`OSCALConverter`) |
| [SUPPORT_MODULE.md](SUPPORT_MODULE.md) | Support database: configuration, updating, and API |
| [LOGGING.md](LOGGING.md) | Enabling Loguru logging within the library |
