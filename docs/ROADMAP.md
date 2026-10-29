---

# ROADMAP (_Updated Aug 12, 2026_)

The sequencing of releases may change in response to client needs and other external factors.

## CURRENT: Version 4.0.0 

- Revised metaschema index
- increased coverage of metascha validation
- established validation levels (minimally valid, valid, fully compliant)
- complete SSP getters



### Version 
- MVP cDef Getters


## Up Next:




### Local Caching

- [ ] Automatic cache refresh based on TTL
- [ ] Manually triggered refresh
- [ ] Fallback to cache after expiration when remote content is not available.

## Future:

### Re-base Document Origin (relative-import resolution after local load)

- [ ] Allow a document's origin href to be set/overridden **after** load, re-resolving its
      relative imports against the new base.
    - Motivation: relative imports (and relative `rlink` hrefs in back-matter resources)
      resolve against the document's own location (`href`/`href_original`). When a GUI opens a
      remote file via a path that loses the original URL — e.g. a Windows file-open dialog that
      silently downloads to a local cache (WinINet INetCache), handing the library only the
      local temp copy — the remote base is lost, so relative siblings resolve to the temp
      folder and fail (`LOCAL_NOT_FOUND`). Observed with a FedRAMP 20X profile whose
      back-matter `rlink` is the relative `FedRAMP_2026_OSCAL_catalog.json`.
    - Today's options already cover most cases: `OSCAL.acquire(url)` resolves relative imports
      against the remote base automatically; `OSCAL.load(src, href=url)` / `OSCAL.loads(content,
      href=url)` let a caller supply the true origin at load time; `retry_import()` fixes
      individual failed imports. The gap is a *post-load* re-base (e.g. `set_origin(href)`) that
      re-points all relative imports at once — useful when the origin URL only becomes known
      after the content is already loaded.
    - Deferred (2026-10-14): the immediate CyberCraft case was resolved on the app side by
      routing URL opens through a dialog that passes the URL straight to the library (instead of
      the OS file dialog that auto-downloads to cache). The re-base method is a convenience for
      flows where the app cannot capture the original URL at open time and would otherwise have
      to re-prompt the user for it. Note such a re-base is only meaningful for still-unresolved
      relative imports; absolute and already-resolved imports are unaffected.

### Scope-Collection Getters with Import-Tree Source Attribution

- [ ] Add list-returning getters that collect in-scope back-matter **resources** and metadata
      **roles**, **parties**, and **locations**, with an option to include or exclude imported
      content.
    - Replaces an app-side workaround: CyberCraft currently fetches resources via
      `doc.json_query('/*/back-matter/resources')` and, when "Include Imports" is on, additionally
      walks each imported document (`doc.get_oscal_object(obj_uuid)`) and runs the same query
      against it, concatenating the results. The library should own this traversal rather than
      each caller reimplementing it.
    - Requirements:
        - An `include_imports` option (exclude = this document only; include = cascade the import
          tree, de-duplicated and cycle-safe, like the singular `get_*_by_uuid` getters).
        - When imports are included, **each returned object must carry a clear origin marker**
          identifying the source document it came from (e.g. the owning document's `object_uuid`
          + resolved `href`, as already surfaced by the `with_source` locator form of
          `_lookup_in_scope`). A top-level vs imported distinction must be unambiguous from the
          returned array alone. (Consider whether to tag local-origin objects too, for uniformity.)
        - Return detached safe copies (library getter convention); the origin marker is an added
          sibling/annotation, not part of the OSCAL object's own shape.
    - Open design points for implementation: the exact origin-marker key/shape; de-dup policy
      when the same id/uuid appears in multiple documents (first-wins vs list every occurrence —
      note OSCAL addressibility/scope rules); and whether these share one generic
      scope-collection helper (resources + roles + parties + locations differ only by
      container/key).
    - Relates to the cross-reference getters (`get_resource_by_uuid` / `get_role_by_id` /
      `get_party_by_uuid` / `get_location_by_uuid`), which already cascade the import tree for a
      single match and expose owning-document info via `with_source`.

### Project Approach

- [ ] Project-based Storage
    - Save cluster of related files together
        - AR -> AP -> SSP -> Profile -> [ Profile | Catalog ]
        - POAM -> SSP -> Profile -> [ Profile | Catalog ]
    - SQLite-based
    - Load cluster of related files
    - External attachment packing with project

- [ ] External attachment handling    
    - In SQLite project file
    - As external files relative to SQLite project file

### Indexes and Robust Addressibility

- [ ] Generate and maintain metaschema-defined indexes
- [ ] Generate and maintain extra-metaschema indexes 
- [ ] Handle metaschema-defined uniqueness constraints
- [ ] Enable robust addressibility across project files
  - Easily search for ID/UUID referencess across a project, consistent with OSCAL addressibility scope and requirements

---

### Farther Out

- [ ] Robust URI and APIs Handling for Content Acquisition/Storage
    - Additional API Specifications
    - Credentialed/Access-token Handling
    - S3 and similar cloud-native storage capabiities 

- [ ] Content Library
    - Cached local copy of commonly used OSCAL content, such as the NIST SP 800-53 catalog and FedRAMP profiles.
    - Ability to add/refresh/remove content

- [ ] Preferred Conversion
    - Enable conversion of OSCAL content using pure python and direct interpretation of metaschema
        - Eliminates dependency on XSLT 3.x processing for format converstion

- [ ] Preferred Validation
    - Enable validation of OSCAL content using pure Python and direct interpretation of NIST metaschema 
        - Eliminate dependency on XML/JSON schema files
        - Enables more complex metaschema checks 

- [ ] Project Storage and Sharing Enhancements
    - Enable multi-user interaction of shared project files
    - Enable storage on shared network drives
    - Enable storage on shared cloud drives (OneDrive, Google Drive)
    - Enablue use of enterprise databases


