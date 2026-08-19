---
---

# Querying OSCAL Content

`OSCAL` objects expose two complementary path-based query methods that work on the in-memory JSON representation of an OSCAL document. Both share the same path syntax and return Python lists. The difference is in how path steps are written.

| Method | Step names | Requires index |
|---|---|---|
| `query()` / `query_one()` | OSCAL **XML element names** (`control`, `prop`, `part`) | Yes — metaschema index via support object |
| `json_query()` / `json_query_one()` | **JSON key names** as they appear in the file (`controls`, `props`, `parts`) | No |

> **Results are safe copies.** All four public query methods return detached
> copies of the matched nodes — mutating a result does **not** change the
> document. To make persistent changes, use the model's mutation methods. (The
> live-reference variants `_query()` / `_json_query()` are private and for
> internal use only.)

---

## Path Syntax

Both engines parse the same expression language.

### Axes

| Expression | Meaning |
|---|---|
| `name` | Relative path — navigate to `name` from the current context |
| `/` | Absolute path — anchor to the document root |
| `/*` | Absolute path — wildcard over the root model object (skips the `{"catalog": …}` wrapper) |
| `//name` | Descendant axis — find `name` at any depth below the current context |
| `//name//child` | Chained descendant axes |
| `*` | Wildcard — all direct children |
| `@attr` | Attribute/flag value (in `json_query`, `@key` is a synonym for bare `key`) |
| `text()` | Scalar value of the current node |

### Predicates

Predicates are written in `[…]` brackets immediately after a step name. Multiple predicates on the same step are ANDed together.

| Predicate | Meaning |
|---|---|
| `[@id='ac-2']` | Attribute equality |
| `[@id!='ac-2']` | Attribute inequality |
| `[@priority>3]` | Numeric comparison (`<`, `>`, `<=`, `>=`) |
| `[select]` | Existence — node has a `select` child |
| `[not(@withdrawn)]` | Negated existence |
| `[prop[@name='label']]` | Path expression — has a `prop` child with `name='label'` |
| `[@id='ac-1'][select]` | Multiple predicates — both must hold |

### Quoting

Predicate values may use single or double quotes: `[@id="ac-2"]` and `[@id='ac-2']` are equivalent.

---

## `query()` — XML Element Name Syntax

Uses the metaschema index to translate OSCAL XML element names into their JSON equivalents, resolving array grouping (`controls`, `props`, …) and BY_KEY structures automatically.

```python
# Returns a list; empty list when nothing matches.
results = oscal_obj.query(path)
results = oscal_obj.query(path, context=some_sub_dict)

# Returns the first match, or None (or a supplied default).
value = oscal_obj.query_one(path)
value = oscal_obj.query_one(path, default="")
```

**When to use:** When you think in XML/OSCAL schema terms — the names from the OSCAL specification and its metaschemas.

### Examples

```python
# Find a control by ID anywhere in the document
ctrl = oscal_obj.query_one('//control[@id="ac-2"]')
# → {"id": "ac-2", "title": "Account Management", "params": […], …}

# Fetch the catalog title (absolute path, /* skips the {"catalog": …} wrapper)
title = oscal_obj.query_one('/*/metadata/title')
# → "NIST SP 800-53 Rev 5 …"

# Find all statement parts across the entire document
statements = oscal_obj.query('//part[@name="statement"]')
# → [{"id": "ac-1_smt", "name": "statement", …}, …]  (1016 items in SP 800-53)

# Find controls that have a prop with name="label" and value="AC-2"
ctrls = oscal_obj.query('//control[prop[@name="label"][@value="AC-2"]]')
# → [{"id": "ac-2", …}]

# All controls that have at least one parameter
ctrls = oscal_obj.query('//control[param]')

# Controls whose label starts with "AC" — not directly supported, but you can
# filter the full list in Python after querying
labels = oscal_obj.query('//prop[@name="label"]')

# Relative path — query within an already-fetched object
ctrl = oscal_obj.query_one('//control[@id="ac-2"]')
stmts = oscal_obj.query('part[@name="statement"]', context=ctrl)

# Find parameters that have a select/choice element
params = oscal_obj.query('//param[select]')

# Negation — controls that have NOT been withdrawn
active = oscal_obj.query('//control[not(prop[@name="status"][@value="withdrawn"])]')

# Scalar value via text()
version = oscal_obj.query_one('/*/metadata/oscal-version/text()')
# → "1.1.3"
```

### XML → JSON Name Translation

The engine uses the metaschema index to map XML element names to JSON keys. Common examples for a catalog:

| Path step (XML name) | JSON key | Container |
|---|---|---|
| `control` | `controls` | array |
| `group` | `groups` | array |
| `param` | `params` | array |
| `prop` | `props` | array |
| `part` | `parts` | array |
| `link` | `links` | array |
| `metadata` | `metadata` | object |
| `set-parameter` | `set-parameters` | BY_KEY (keyed by `param-id`) |

Attribute/flag names are the same in XML and JSON (e.g., `@id`, `@name`, `@value`).

---

## `json_query()` — JSON Key Name Syntax

Works directly on JSON key names with no index lookup. Arrays are iterated transparently: navigating to a key whose value is a list automatically yields each item.

```python
# Returns a list; empty list when nothing matches.
results = oscal_obj.json_query(path)
results = oscal_obj.json_query(path, context=some_sub_dict)

# Returns the first match, or None (or a supplied default).
value = oscal_obj.json_query_one(path)
value = oscal_obj.json_query_one(path, default="")
```

**When to use:** When you already know the JSON structure, when working with non-catalog models without an index, or when the query is simpler to express in JSON terms.

### Root Key Awareness

OSCAL JSON always has a root wrapper key matching the model name:

```json
{ "catalog": { "metadata": {…}, "groups": […] } }
```

Relative paths start from this wrapper. Use `/*` or the model name explicitly to reach the content:

```python
# These are equivalent for a catalog:
oscal_obj.json_query_one('/*/metadata/title')
oscal_obj.json_query_one('catalog/metadata/title')

# Descendant axis skips the wrapper automatically:
oscal_obj.json_query_one('//title')   # finds first title at any depth
```

### Examples

```python
# Find a control by ID anywhere in the document
ctrl = oscal_obj.json_query_one('//controls[id="ac-2"]')
# → {"id": "ac-2", "title": "Account Management", …}

# Catalog title — include the root key or use /*
title = oscal_obj.json_query_one('catalog/metadata/title')
title = oscal_obj.json_query_one('/*/metadata/title')

# All statement parts
statements = oscal_obj.json_query('//parts[name="statement"]')

# Controls with a prop named "label" equal to "AC-2"
ctrls = oscal_obj.json_query('//controls[props[name="label"][value="AC-2"]]')

# Parameters that have a select object
params = oscal_obj.json_query('//params[select]')

# Controls with no params (negated existence)
bare = oscal_obj.json_query('//controls[not(params)]')

# Relative path — query within a fetched object
ctrl = oscal_obj.json_query_one('//controls[id="ac-2"]')
parts = oscal_obj.json_query('parts', context=ctrl)

# Numeric comparison — links with rel="reference"
links = oscal_obj.json_query('//links[rel="reference"]')

# @ prefix is accepted as a synonym for a bare key
oscal_obj.json_query('//controls[@id="ac-2"]')   # same as [id="ac-2"]

# Chained descendant axes
oscal_obj.json_query('//controls//parts[name="item"]')
```

---

## Choosing Between `query` and `json_query`

Use `query` (XML names) when:
- Writing queries that mirror how OSCAL content is described in the specification or metaschema documentation.
- The index is available (i.e., the document loaded cleanly with a recognized model and version).
- You want portable queries that work regardless of whether the source was XML or JSON.

Use `json_query` (JSON names) when:
- You're already looking at the raw JSON structure and prefer to use the key names you see.
- Working with a document type or version where the metaschema index may not be available.
- The query is simpler or more readable with JSON key names.

Both methods return the same Python values (dicts, strings, lists, numbers) from the same underlying `_dict`.

---

## Return Values

All query methods return Python objects from the parsed JSON:

- **An assembly** (control, group, param, …) → `dict`
- **A field** (title, remarks, …) → `str`
- **A flag** (id, name, value, …) → `str` (or `int`/`bool` for typed flags)
- **No match** → `[]` for `query`/`json_query`, `None` (or the supplied default) for `query_one`/`json_query_one`

---

## Using the Engines Directly

Both engines can also be used without an `OSCAL` object:

```python
from oscal.oscal_converter import OSCALPath, NativePath, native_path

# NativePath — module-level singleton, no setup needed
doc = json.loads(open("catalog.json").read())
ctrl = native_path.query_one('//controls[id="ac-2"]', doc)

# OSCALPath — requires a model index from the support object
engine = OSCALPath.from_support("catalog", "v1.1.3", support_obj)
ctrl = engine.query_one('//control[@id="ac-2"]', doc)
```
