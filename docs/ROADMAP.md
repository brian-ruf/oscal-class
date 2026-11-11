---
---

# ROADMAP (_Updated November 1, 2026_)

The sequencing of releases may change in response to client needs and other external factors.

## CURRENT: Version 4.1.0

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

- [ ] POA&M, AP and AR Getters
- [ ] Generate and maintain metaschema-defined indexes
- [ ] Handle metaschema-defined uniqueness constraints

- [ ] **Pre-5.0.0 breaking batch** (plan: `docs/NAMING_CONSISTENCY_PLAN.md`) — land together,
      ahead of 5.0.0: (1) universal `get_<noun>()` getter-name normalization; (2) library-wide
      `provenance {uuid, href, imported}` on the base-class cross-reference getters
      (roles/parties/locations/resources), retiring `source-document`. Assessment-layer
      provenance + `additional-versions` is already done in final shape.


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

### Reproducible SBOMs — Tested-Dependency Lockfile

- [ ] Add a committed constraints/lock file so the per-release SBOM describes a *fixed*
      dependency closure instead of re-resolving on each run.
    - Motivation: `oscal` declares abstract lower-bound dependencies (correct for a library),
      so `pip install oscal` resolves different transitive versions over time and per Python
      version. Today the SBOM step installs into a clean venv and re-resolves fresh, so two
      SBOMs for the *same* `oscal` version — generated weeks apart — can legitimately differ.
      A lockfile pins what we test and what the release-time SBOM reports, without constraining
      downstream `pip install oscal` (pinning belongs at the application layer, e.g. CyberCraft).
    - Requirements:
        - Generate a lockfile (`pip-tools`/`uv`, ideally with hashes) from the runtime closure;
          commit it.
        - Feed it to `scripts/generate_sbom.sh` / the SBOM generator (constraints on the clean
          install) so the CycloneDX document is deterministic for a given `oscal` version.
        - Keep the published `[project.dependencies]` as lower-bound ranges — do **not** pin the
          library's declared deps (that would cause downstream resolution conflicts and block
          automatic security-patch intake).
    - Open design points: `pip-tools` vs `uv` for lock generation; whether to also pin the
      `[dev]` extra for CI reproducibility; refresh cadence (regenerate the lock + re-test before
      each release tag); and multi-Python handling (the 3.9 vs 3.13 closures differ, so a single
      lock may need per-interpreter variants or a documented canonical interpreter).
    - Note for Federal consumers: state plainly that `oscal`'s SBOM is a point-in-time snapshot
      of the tested closure for that release (backed by the lockfile), and that a deployer pins
      for their own environment — consistent with NTIA's SBOM-per-artifact model.

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

