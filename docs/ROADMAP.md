---
---

# ROADMAP (_Updated November 12, 2026_)

The sequencing of releases may change in response to client needs and other external factors.

## CURRENT: Version 4.2.1

- Profile import-selection authoring API — safer, granular control over an import's `include-controls` / `exclude-controls` and the `with-child-controls` flag:
    - `set_import_with_children()` toggles `with-child-controls` on the existing include/exclude selection independently, without rebuilding it.
    - `add_import_include()` / `add_import_exclude()` append one selection entry at a time (`matching` preserves the OSCAL `{pattern, remarks}` construct); `remove_import_include()` / `remove_import_exclude()` remove a row by its selection identity.
    - `set_import_selection()` gained `include_with_children` / `exclude_with_children` booleans (set the flag from a Python bool — no `"yes"`/`"no"` string footgun).
    - `preview_import_selection()` dry-runs a committed or hypothetical selection, returning the control ids it resolves to (surfaces greedy `matching` globs before committing).
- CI: pinned the Python 3.9 matrix leg to `ubuntu-22.04` (no `setup-python` 3.9 build on Ubuntu ≥24.04). Python 3.9 support is unchanged this release.

## Builds on Version 4.1.0

- Added common getters, which enumerate across all imports by default, or can be constrained to enumerate only for the current OSCAL object: `.resources()`, `.roles()`, `.parties()`, `.locations()`, `.responsible_parties()`, `.actions()`
- Added common getter, `.action()` which fetches a specific metadata action.
- Fixed a bug in `SSP.control()` that prevented control references from being populated when they existed in an imported profile or catalog.

## Builds on Version 4.0.0

- Revised metaschema index
- increased coverage of metaschema validation
- established validation levels (minimally valid, valid, fully compliant)
- SSP-specific getters full coverage
- cDef-specific getters full coverage
- Additional metaschema-defined enforcement  
    - Significantly exceeds validation based on INST-published XML or JSON schema files
    - Greater than 80% of the metaschema constraints now enforced
    - Referential integrity validated
- Three validation levels defined:
    - Minimally Valid: 
        - well-formed, valid syntax
        - sufficient for processing
        - allows for resolving more complex validation issues via the library
        - Some library functions are blocked until validation issues are resolved
    - Valid:
        - Highest level of compliance that can be verified using Python dict/JSON and direct interpretation of the metaschema
        - All metaschema constraints handled except those that require xPath 3 to interpret
    - Fully Compliant (not yet implemented):
        - convert to XML and apply xPath 3 to interpret remaining constraints
- getters span import tree where appropriate



## Up Next:

**Next release — major version bump.** Changes the supported Python range: **drops Python
3.9 and 3.10** (both end-of-life upstream — 3.9 since October 2025, 3.10 since October 2026)
and **adds Python 3.14**. Python 3.15 is deferred until the dependency wheels catch up. New
floor: `requires-python = ">=3.11"`. This release also lands the assessment-layer getters
below (POA&M / AP / AR).

- [ ] POA&M, AP and AR Getters
- [ ] Generate and maintain metaschema-defined indexes
- [ ] Handle metaschema-defined uniqueness constraints


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


### Local Caching Enhancements

- [ ] Automatic cache refresh based on TTL
- [ ] Manually triggered refresh
- [ ] Fallback to cache after expiration when remote content is not available.

### Indexes and Robust Addressibility

- [ ] Generate and maintain extra-metaschema indexes 
- [ ] Enable robust addressibility across project files
  - Easily search for ID/UUID referencess across a project, consistent with OSCAL addressibility scope and requirements


## Future:

### SBOM Packaging — PEP 770 Alignment

- [ ] Embed a CycloneDX SBOM inside the published wheel/sdist per **PEP 770**
      (SBOM documents under `.dist-info/sboms/`, recorded in core metadata) once
      build-backend (setuptools) support has matured.
    - Motivation: today the per-release CycloneDX SBOM is attached to the GitHub Release
      and pointed at from `[project.urls]`. A static `project.urls` link cannot be
      version-specific (the value is baked into each build and setuptools does not allow
      `urls` to be dynamic), so a consumer viewing an *older* version on PyPI is sent to a
      generic releases page rather than that exact version's SBOM. PEP 770 fixes this
      structurally: the SBOM travels *inside* the versioned artifact, so it is always the
      right one for whatever wheel a (e.g. federal) consumer actually downloaded.
    - Requirements:
        - Generate the SBOM as part of the build and place it where PEP 770 specifies, so
          standard tooling discovers it from the installed/downloaded distribution.
        - Keep the existing GitHub-Release CycloneDX asset and `[project.urls]` link as the
          interim mechanism until PEP 770 is in place.
    - Open design points: whether to also embed SPDX; build-backend support status (this is
      the gating factor — do not adopt until setuptools support is solid); and interaction
      with the release workflow that currently builds the SBOM from the installed wheel
      (PEP 770 wants it produced during the build, not post-install).
    - Note: lower urgency for a pure-Python library whose dependencies are fully declared in
      `Requires-Dist` (the wheel is already measurable from metadata); PEP 770 matters most
      when a package bundles undeclared/non-Python components.

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


---

### Farther Out

- [ ] Enhanced URI and APIs Handling for Content Acquisition/Storage
    - Additional API Specifications
    - Credentialed/Access-token Handling
    - S3 and similar cloud-native storage capabiities 

- [ ] Content Library
    - Cached local copy of commonly used OSCAL content, such as the NIST SP 800-53 catalog and FedRAMP profiles.
    - Ability to add/refresh/remove content

- [ ] Complete metaschema-based validation 
  - currently 100% implemented for syntax, cardinality, data types, indexing 
  greater than 85% implemented
  - A few constraints require xPath 3 to interpret. 
  - Plan is to convert to XML and use xPath 3 just for those constraints on demand and separate from the automatic validation

- [ ] Project Storage and Sharing Enhancements
    - Enable multi-user interaction of shared project files
    - Enable storage on shared network drives
    - Enable storage on shared cloud drives (OneDrive, Google Drive)
    - Enablue use of enterprise databases

