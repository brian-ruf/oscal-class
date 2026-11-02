---
title: Software Bill of Materials (SBOM)
---

# Software Bill of Materials (SBOM)

`oscal` publishes a Software Bill of Materials (SBOM) for every released version to support
supply-chain security review, including U.S. Federal requirements derived from EO 14028, the
NTIA "Minimum Elements for an SBOM," and CISA/NIST SP 800-218 (SSDF) guidance.

> **Link note:** This page is rendered to HTML and served from the documentation site at
> `https://brian-ruf.github.io/oscal-class/`. The SBOM and the license manifest are **not**
> part of that site — they live in GitHub Releases and in the repository tree. All links
> below are therefore absolute GitHub URLs; relative links would not resolve from the docs
> site.

## What is produced

Each release produces two companion artifacts:

1. **CycloneDX SBOM** — `oscal-<version>.cdx.json`, in CycloneDX JSON. It lists the package
   and its full resolved runtime dependency closure with names, versions, package URLs
   (PURLs), hashes, licenses, and the dependency-relationship graph (the NTIA minimum
   elements). CycloneDX and SPDX are both accepted by U.S. Federal consumers; `oscal` emits
   CycloneDX, and an SPDX view is additionally available for free via the GitHub Dependency
   Graph "Export SBOM" feature.
2. **Third-party license manifest** — `THIRD-PARTY-LICENSES.md`, a human-readable list of
   every bundled third-party component and its full license text.

## How and when it is generated

Generation is fully automated in the release workflow (`publish.yml`), triggered when a
GitHub Release is **published**. The `sbom` job:

1. Takes the exact wheel built earlier in the same run (it does not re-resolve).
2. Installs that wheel into a clean, runtime-only virtual environment (no dev/test tools),
   so the SBOM reflects precisely what ships.
3. Generates the CycloneDX document with
   [`cyclonedx-py`](https://github.com/CycloneDX/cyclonedx-python) in `environment` mode
   (which captures dependency relationships).
4. Regenerates `THIRD-PARTY-LICENSES.md` from that same closure using
   [`scripts/generate_thirdparty_licenses.py`](https://github.com/brian-ruf/oscal-class/blob/main/scripts/generate_thirdparty_licenses.py).
5. Attaches both files to the GitHub Release.

Publishing to PyPI is gated on this job: the `publish` job declares `needs: [build, sbom]`,
so a version is never released to PyPI unless its SBOM was generated and attached.

## Where to find it

- **Per-version SBOM (`oscal-<version>.cdx.json`)** — attached as an asset to the matching
  GitHub Release. Browse all releases at
  <https://github.com/brian-ruf/oscal-class/releases> and open the release whose tag is
  `v<version>` (e.g. `v4.1.0`). The SBOM is **not** committed to the repository; it is a
  per-release artifact that travels with the versioned Release.
- **Third-party license manifest** — committed in the repository root and regenerated at
  each release:
  <https://github.com/brian-ruf/oscal-class/blob/main/THIRD-PARTY-LICENSES.md>.
- **From PyPI** — the project's `SBOM` project-URL (shown in the PyPI sidebar) links to the
  GitHub Releases list. Because PyPI `project.urls` values are static per build and cannot be
  version-specific, the link points at the releases list; select the matching tag to reach
  that version's SBOM.

## Regenerating locally

The license manifest can be regenerated from an environment that has `oscal`'s runtime
dependencies installed:

```bash
python scripts/generate_thirdparty_licenses.py -o THIRD-PARTY-LICENSES.md
```

Run in a clean runtime-only environment (e.g. a fresh venv with `pip install .`) so that
only the shipping dependencies are reported. The release workflow does exactly this against
the built wheel, which is the authoritative source.

## Roadmap

In-artifact SBOM embedding per **PEP 770** (SBOM carried inside the wheel under
`.dist-info/sboms/`, so it is always version-exact for whatever artifact a consumer
downloaded) is tracked in the project [ROADMAP](ROADMAP.html) and will be adopted once
build-backend support matures.
