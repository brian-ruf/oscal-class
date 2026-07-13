# OSCAL Format Converters

All conversion logic lives in `oscal_converter.py`:

| Functionality | API |
|---|---|
| XML ↔ JSON format conversion | `OSCALConverter` class |
| OSCAL markup-line / markup-multiline ↔ CommonMark | `oscal_markdown_to_html`, `oscal_html_to_markdown` |

When using the OSCAL content classes (`Catalog`, `Profile`, etc.), both converters are
invoked automatically — you do not need to call them directly. This document covers
their APIs for cases where direct access is useful.

---

## XML ↔ JSON Conversion (`oscal_converter.py`)

Format conversion is pure Python, driven by the parsed NIST resolved-metaschema index
stored in the support database. No external XSLT processor is required.

### `OSCALConverter` class

The primary API. Build an instance from the support database using `from_support()`,
then call `xml_to_json()` or `json_to_xml()` on the instance.

#### `OSCALConverter.from_support(model, version, support=None)`

```python
from oscal.oscal_converter import OSCALConverter

converter = OSCALConverter.from_support("catalog", "v1.1.3")
```

Parameters:

| Parameter | Type | Description |
|---|---|---|
| `model` | `str` | OSCAL model name, e.g. `"catalog"`, `"system-security-plan"` |
| `version` | `str` | OSCAL version string, e.g. `"v1.1.3"` |
| `support` | `OSCALSupport \| None` | Support singleton; uses `get_support()` if `None` |

Returns an `OSCALConverter` instance, or `None` when no metaschema index exists for
the requested version and model. Run `support.update()` to populate missing indexes.

For versions older than `v1.1.1` (before NIST published resolved metaschema files),
`from_support` automatically falls back to the `v1.1.1` index as the closest
approximation and logs a warning.

#### `xml_to_json(xml_content) → str | None`

Convert an OSCAL XML document string to OSCAL JSON.

```python
with open("catalog.xml") as f:
    xml_str = f.read()

converter = OSCALConverter.from_support("catalog", "v1.1.3")
json_str  = converter.xml_to_json(xml_str)

if json_str:
    with open("catalog.json", "w") as f:
        f.write(json_str)
```

Returns the JSON string on success, or `None` on parse/conversion error.

**Markup fields**: OSCAL `markup-line` and `markup-multiline` XML content is
automatically converted to CommonMark during this step (via `oscal_converters.py`).

#### `json_to_xml(json_content) → str | None`

Convert an OSCAL JSON document string to OSCAL XML.

```python
with open("catalog.json") as f:
    json_str = f.read()

converter = OSCALConverter.from_support("catalog", "v1.1.3")
xml_str   = converter.json_to_xml(json_str)
```

Returns the XML string (with `<?xml ...?>` declaration) on success, or `None` on error.

**Markup fields**: CommonMark content in JSON `markup-line` and `markup-multiline`
fields is automatically converted to OSCAL-conformant XML child elements.

---

### Constructing from a model index directly

If you already have a parsed model index dict (e.g. from `support.get_metaschema_index()`),
you can construct a converter directly:

```python
from oscal.oscal_support import get_support
from oscal.oscal_converter import OSCALConverter

support = get_support()
index   = support.get_metaschema_index("v1.1.3", "catalog")
converter = OSCALConverter(index)
```

---

### Module-level convenience functions

Three module-level functions are available for one-off conversions:

```python
from oscal.oscal_converter import xml_to_json, json_to_xml, converter_for

# One-off conversion — builds a temporary converter instance each call
json_str = xml_to_json(xml_str, model_index)
xml_str  = json_to_xml(json_str, model_index)

# Obtain a reusable converter (equivalent to OSCALConverter.from_support)
converter = converter_for("catalog", "v1.1.3")
```

`xml_to_json` and `json_to_xml` each accept a `model_index` dict (from
`support.get_metaschema_index()`). Use `converter_for` when you need a reusable
converter without the class syntax.

---

### All-in-one pattern (recommended)

The simplest way to convert files is to load with an OSCAL content class, then `dump()`
in the target format. This handles version detection, model identification, and
converter selection automatically:

```python
from oscal import OSCAL

# Load any supported format (XML, JSON, or YAML)
doc = OSCAL.load("catalog.xml")

# Save in a different format — conversion happens automatically
doc.dump("catalog.json", format="json", pretty_print=True)
doc.dump("catalog.yaml", format="yaml")
```

---

## Markup Conversion

OSCAL `markup-line` and `markup-multiline` fields use OSCAL-flavoured CommonMark in
JSON/YAML and equivalent HTML/XML mixed-content in XML. These functions handle the
conversion between them.

These are called automatically by `OSCALConverter` during XML↔JSON conversion. Call
them directly only when working with OSCAL markup strings outside of format conversion.

### `oscal_markdown_to_html(markdown_text, multiline=False) → str`

Convert an OSCAL CommonMark string to an HTML fragment.

```python
from oscal.oscal_converters import oscal_markdown_to_html

# markup-line (inline only, no block elements)
html = oscal_markdown_to_html("This is **bold** and `code`.", multiline=False)

# markup-multiline (block elements preserved)
html = oscal_markdown_to_html("# Heading\n\nParagraph text.", multiline=True)
```

| `multiline` | Behaviour |
|---|---|
| `False` (default) | Inline elements only; outer `<p>` tags stripped |
| `True` | Block elements preserved; bare text wrapped in `<p>` |

Raw HTML/XML tags in the source (e.g. `<BREAK>`) are escaped as `&lt;BREAK&gt;` so
they survive the round-trip unmodified.

### `oscal_html_to_markdown(html_text, multiline=True) → str`

Convert an HTML fragment to OSCAL CommonMark.

```python
from oscal.oscal_converters import oscal_html_to_markdown

md = oscal_html_to_markdown("<p>This is <strong>bold</strong>.</p>", multiline=True)
```

OSCAL `<insert>` elements are converted to `{{ insert: type, id-ref }}` syntax.

---

## References

- **OSCAL Project**: https://pages.nist.gov/OSCAL/
- **OSCAL GitHub**: https://github.com/usnistgov/OSCAL
- **NIST Metaschema**: https://pages.nist.gov/metaschema/
