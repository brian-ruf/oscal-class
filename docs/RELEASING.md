---
title: Releasing
---

# Releasing

The version number is single-sourced in
[`oscal/_version.py`](https://github.com/brian-ruf/oscal-class/blob/main/oscal/_version.py).
`pyproject.toml` declares `dynamic = ["version"]` and reads that literal at build time, and
`oscal/__init__.py` imports it so `oscal.__version__` is correct at runtime without a
reinstall. **Changing the version is a one-line edit to `oscal/_version.py`.**

## Release steps

1. **Bump the version** in `oscal/_version.py` (e.g. `__version__ = "4.1.0"`). Commit.
2. **Tag with a matching `v`-prefixed tag**: `git tag v4.1.0 && git push origin v4.1.0`.
   The tag's digits must equal `_version.py` (the publish workflow enforces this).
3. **Publish a GitHub Release** for that tag. Publishing (not just creating the tag) is what
   triggers `publish.yml`.

## What the workflows do

**On every push to `main`** (`ci.yml`) — before you tag — the `sync-release-assets` job
refreshes the OSCAL support database and the API docs and rebuilds the documentation site,
so those are current ahead of a release.

**When the Release is published** (`publish.yml`):

1. `build` — verifies the release tag matches `oscal/_version.py` (fails fast on a mismatch),
   then builds the sdist and wheel and runs `twine check`.
2. `sbom` — installs the built wheel into a clean runtime-only environment, generates the
   CycloneDX SBOM and regenerates `THIRD-PARTY-LICENSES.md`, and attaches both to the
   Release. See [SBOM](SBOM.html).
3. `publish` — uploads to PyPI via OIDC trusted publishing. It declares
   `needs: [build, sbom]`, so **a version is never published to PyPI unless its SBOM was
   generated and attached first.** Build provenance (PEP 740 attestations) is emitted by the
   publish action and shown on PyPI.

## If the tag and `_version.py` disagree

The `build` job stops the release with an error. Fix whichever is wrong — bump
`oscal/_version.py` to match the tag, or delete and re-create the tag to match the file —
and publish the Release again.
