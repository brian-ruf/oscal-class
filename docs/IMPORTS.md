# Import Resolution

OSCAL documents reference other documents through *import statements*.  A profile imports one or more catalogs; an SSP imports a profile; an assessment plan imports an SSP; and so on.  The library resolves those references automatically when a document is loaded, and exposes the results through `import_list` and `import_tree`.

---

## How imports are resolved

Whenever content reaches `ContentState.VALID`, the library calls `resolve_imports()` automatically.  You can also call it manually at any time to force a fresh resolution pass.

```python
from oscal import OSCAL

ssp = OSCAL.load("my-ssp.xml")

# import_list is already populated after load
for entry in ssp.import_list:
    print(entry["href_original"], entry["status"])
```

---

## Import href forms

Every import statement carries an `href` attribute that is either a **URI fragment** or a **full URI**.

### URI fragment  (`#uuid`)

A fragment-only href like `#051a77c1-b61d-4995-8275-dacfe688d510` refers to a resource in the document's own `back-matter` section by UUID.  The library looks up the resource, then attempts to load the content from each `rlink` in sequence.

```xml
<import href="#051a77c1-b61d-4995-8275-dacfe688d510"/>

<back-matter>
  <resource uuid="051a77c1-b61d-4995-8275-dacfe688d510">
    <title>NIST SP 800-53 Rev 5</title>
    <description><p>NIST control catalog</p></description>
    <rlink href="catalogs/nist-800-53-rev5.xml"/>
    <rlink href="catalogs/nist-800-53-rev5.json"/>
  </resource>
</back-matter>
```

`rlinks` are tried in document order.  The library also automatically tries alternate OSCAL format extensions (`.xml`, `.json`, `.yaml`, `.yml`) for each rlink before moving to the next one.

### Full URI

Any href that is not a bare fragment is treated as a URI pointing directly to the content.

```xml
<!-- Relative local path -->
<import href="catalogs/nist-800-53-rev5.xml"/>

<!-- Absolute local path -->
<import href="/data/oscal/catalogs/nist-800-53-rev5.xml"/>

<!-- Remote URL -->
<import href="https://raw.githubusercontent.com/usnistgov/oscal-content/main/.../catalog.json"/>

<!-- file:// URI -->
<import href="file:///data/oscal/catalogs/nist-800-53-rev5.xml"/>
```

Relative paths are resolved against the directory that contains the importing document (or the current working directory when content was loaded from memory).

---

## Import entry structure

`import_list` is a flat list of dicts, one per import statement.  Successful and failed entries share the same keys:

| Key | Type | Description |
|-----|------|-------------|
| `href_original` | `str` | The raw href from the import statement |
| `href_valid` | `str` | The resolved href that successfully loaded (empty on failure) |
| `status` | `ImportState` | `READY`, `NOT_LOADED`, `INVALID`, or `EXPIRED` |
| `is_valid` | `bool` | `True` when the loaded content passed OSCAL validation |
| `is_local` | `bool \| None` | `True` for local file, `False` for remote |
| `is_remote` | `bool \| None` | Inverse of `is_local` |
| `is_cached` | `bool` | `True` when remote content has a local cache copy |
| `object` | `OSCAL \| None` | The loaded OSCAL document (populated on success) |
| `failure` | `ImportFailure \| None` | Failure detail (populated on failure; `None` on success) |

---

## Failure states

When an import cannot be resolved, `entry["status"]` is `ImportState.INVALID` and `entry["failure"]` is an `ImportFailure` instance.

### `ImportFailureCode` values

#### Fragment / back-matter failures

| Code | Meaning |
|------|---------|
| `FRAGMENT_INVALID_UUID` | The fragment (`#...`) is not a well-formed UUID |
| `RESOURCE_NOT_FOUND` | No `back-matter/resource` with that UUID exists in the document |
| `RESOURCE_NO_VIABLE_CONTENT` | The resource was found but has neither `rlink` nor `base64` elements |

#### Full URI failures

| Code | Meaning |
|------|---------|
| `LOCAL_NOT_FOUND` | The URI resolves to a local path that does not exist or is empty |
| `REMOTE_UNREACHABLE` | The remote host could not be reached (network error, DNS failure, HTTP 5xx) |
| `REMOTE_AUTH_REQUIRED` | The remote host returned HTTP 401 or 403 |
| `REMOTE_UNSUPPORTED` | The URI scheme is recognised but not yet supported (e.g. `s3://`, `gs://`, `az://`) |

#### Content failures

| Code | Meaning |
|------|---------|
| `CONTENT_EMPTY` | The source responded successfully but returned no content |
| `CONTENT_INVALID` | Content was retrieved but failed OSCAL validation |

---

## The `ImportFailure` dataclass

```python
@dataclass
class ImportFailure:
    code: ImportFailureCode      # Specific failure reason
    href_original: str           # Raw href from the import statement

    # Fragment / back-matter context (populated when href starts with "#")
    resource_uuid: str        # UUID from the fragment
    resource_title: str       # Title from the back-matter resource (if found)
    resource_description: str # Description from the back-matter resource (if found)
    rlinks_tried: list[str]   # All hrefs that were attempted before giving up

    # URI context (populated for full-URI failures)
    uri: str                  # The specific URI that caused the final failure

    message: str              # Human-readable detail
```

The `is_fragment_ref` property returns `True` when `href_original` starts with `#`, making it easy to branch on failure type without inspecting the code:

```python
for entry in doc.failed_imports:
    f = entry["failure"]
    if f.is_fragment_ref:
        print(f"Back-matter resource {f.resource_uuid} ({f.resource_title}): {f.code.value}")
    else:
        print(f"URI {f.uri}: {f.code.value}")
```

---

## Inspecting failures

### `failed_imports` property

Returns only the `import_list` entries that have a non-`None` `failure` field:

```python
profile = OSCAL.load("my-profile.xml")

if profile.failed_imports:
    print(f"{len(profile.failed_imports)} import(s) could not be resolved:")
    for entry in profile.failed_imports:
        f = entry["failure"]
        print(f"  [{f.code.value}] {entry['href_original']} — {f.message}")
```

### Branching by failure code

```python
from oscal.oscal_content import ImportFailureCode

for entry in profile.failed_imports:
    f = entry["failure"]

    match f.code:
        case ImportFailureCode.FRAGMENT_INVALID_UUID:
            print(f"Bad UUID in import href: {entry['href_original']}")

        case ImportFailureCode.RESOURCE_NOT_FOUND:
            print(f"No back-matter resource with UUID {f.resource_uuid}")

        case ImportFailureCode.RESOURCE_NO_VIABLE_CONTENT:
            print(f"Resource '{f.resource_title}' ({f.resource_uuid}) has no rlinks or base64")

        case ImportFailureCode.LOCAL_NOT_FOUND:
            print(f"File not found: {f.uri}")

        case ImportFailureCode.REMOTE_AUTH_REQUIRED:
            print(f"Authentication required: {f.uri}")

        case ImportFailureCode.REMOTE_UNREACHABLE:
            print(f"Remote host unreachable: {f.uri}")

        case ImportFailureCode.REMOTE_UNSUPPORTED:
            print(f"Unsupported URI scheme: {f.uri}")
```

---

## Retry (overview)

When an import fails, the calling module can supply a replacement source and call `resolve_imports()` again.  The retry source can be any of the following:

- **A URI fragment** — `#uuid` pointing to an alternative back-matter resource you have added to the document
- **A full URI** — an alternate local path or remote URL where the content is available
- **Inline content** — the raw XML, JSON, or YAML string of the imported document

Full retry API details are covered in **[IMPORTING_CONTROLS.md](IMPORTING_CONTROLS.md)**.

---

## Example: profile with back-matter imports

```python
from oscal import OSCAL
from oscal.oscal_content import ImportFailureCode

profile = OSCAL.load("my-profile.xml")

# All imports already resolved — check for failures
if not profile.failed_imports:
    print("All imports resolved successfully.")
else:
    for entry in profile.failed_imports:
        f = entry["failure"]

        if f.code == ImportFailureCode.LOCAL_NOT_FOUND:
            # The rlink pointed to a file that was moved; provide the new path
            print(f"Suggest alternate path for: {f.href_original}")

        elif f.code == ImportFailureCode.RESOURCE_NOT_FOUND:
            # The document references a resource UUID that is not in back-matter
            print(f"Missing resource UUID: {f.resource_uuid}")

        elif f.code == ImportFailureCode.REMOTE_AUTH_REQUIRED:
            # Need credentials — provide authenticated content directly
            print(f"Auth needed for: {f.uri}")
```

---

## Example: building a simple failure report

```python
from oscal import OSCAL

def import_report(path: str) -> str:
    doc = OSCAL.load(path)
    lines = [f"Import report: {doc.title} ({doc.model})"]
    lines.append(f"  Total imports : {len(doc.import_list)}")
    lines.append(f"  Resolved      : {sum(1 for e in doc.import_list if e['failure'] is None)}")
    lines.append(f"  Failed        : {len(doc.failed_imports)}")

    for entry in doc.failed_imports:
        f = entry["failure"]
        lines.append(f"\n  ✗ {entry['href_original']}")
        lines.append(f"      code    : {f.code.value}")
        lines.append(f"      message : {f.message}")
        if f.is_fragment_ref and f.resource_title:
            lines.append(f"      resource: {f.resource_title} ({f.resource_uuid})")
        elif f.uri:
            lines.append(f"      uri     : {f.uri}")
        if f.rlinks_tried:
            lines.append(f"      tried   : {', '.join(f.rlinks_tried)}")

    return "\n".join(lines)

print(import_report("profiles/fedramp-high.xml"))
```
