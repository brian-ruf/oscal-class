---
title: Releasing
---

# Releasing

The version number is single-sourced in
[`oscal/_version.py`](https://github.com/brian-ruf/oscal-class/blob/main/oscal/_version.py).
`pyproject.toml` declares `dynamic = ["version"]` and reads that literal at build time, and
`oscal/__init__.py` imports it so `oscal.__version__` is correct at runtime without a
reinstall. **Changing the version is a one-line edit to `oscal/_version.py`.**

Releasing is a two-stage, decoupled flow: pushing a version tag builds the immutable GitHub
Release (with its SBOM) automatically, and a **separate, manually dispatched** step publishes
those exact artifacts to PyPI. The PyPI step is split out on purpose so a failed upload can be
re-run without burning a version.

## Release steps

1. **Bump the version** in `oscal/_version.py` (e.g. `__version__ = "4.1.0"`). Commit it to
   `develop` as part of the normal PR flow.
2. **Merge to `main`.** On the push to `main`, CI (`ci.yml`) refreshes the OSCAL support
   database and commits it, and `docs.yml` regenerates the API docs and redeploys the site —
   so the release is cut from a `main` whose generated assets are already current. **These
   refresh commits take a few minutes to land; the tag must not be created until they do**
   (see [the timing guard](#the-release-timing-guard) below).
3. **Run the release script**, which does the rest end to end:

   ```
   scripts/release.sh v4.1.0 --publish      # Linux/macOS
   scripts\release.cmd v4.1.0 --publish     # Windows
   ```

   It (a) verifies the tag matches `_version.py` on `main`, (b) **waits for `main` to settle**
   after the merge, (c) tags the settled `HEAD` and pushes the tag — which triggers the
   `publish.yml` ("Release") workflow to build the wheel/sdist/SBOM and **create the GitHub
   Release itself** (do not create the Release by hand) — then (d) with `--publish`, dispatches
   the `pypi.yml` ("Publish to PyPI") workflow for the tag. Omit `--publish` to stop after the
   GitHub Release and publish to PyPI later. `release.{sh,cmd}` is the **only** supported way
   to create a release tag: the former standalone `tag-release` helper was absorbed into it so
   a tag is never created outside these guards.

The PyPI step is gated by the `pypi` environment's required reviewer and restricted to the
repository owner — approve it in the Actions tab — and is re-runnable if an upload fails.

### Manual equivalent

If you cannot run the script (no `gh`, or a one-off recovery), the underlying steps are:

```
git tag v4.1.0 && git push origin v4.1.0            # triggers publish.yml
gh workflow run pypi.yml -f tag=v4.1.0              # after the Release is built
```

Done this way **you** are responsible for the timing: only tag once `main`'s post-merge
support-DB/API-doc refresh commits have landed. The server-side guard (below) will reject the
build if you tag too early.

## The release-timing guard

The wheel ships `oscal/data/oscal_support.zip`, and `publish.yml` builds from the **exact
tagged commit**. After a merge to `main`, `ci.yml` and `docs.yml` push `chore:` refresh
commits a few minutes later. Tagging before those land would build a wheel with a **stale
support database**. Two layers prevent this:

- **Client-side** — `release.{sh,cmd}` poll until no `CI Pipeline` or `Docs` run is active on
  `main` and its `HEAD` is stable, then tag that settled commit. (Needs `gh`; `--force`
  overrides it for emergencies, leaving only the server-side guard.)
- **Server-side** — `publish.yml`'s `build` job waits for those workflows to finish, then
  **refuses to build** if `main` has asset-refresh commits newer than the tagged commit. This
  backstops *every* path — the script, a manual `git tag`, or `--force`. If it fires: delete
  the tag, let `main` settle, and re-tag (the script does this automatically).

## What the workflows do

Four workflows cover CI and release. The first two keep `main`'s generated assets current;
the last two perform the release.

**`ci.yml` — on every push/PR to `develop` or `main`.** Lint and the full test matrix run on
`develop` and on feature/fork PRs. On a push to `main` (a merge) those are skipped — the code
was already validated in the PR — and the `support-data` job runs instead: it rebuilds the
OSCAL support database, **re-runs the unit tests against the freshly built database**, and
commits the refreshed `oscal/data/oscal_support.zip` **only if the tests pass**. A non-gating
`sbom-smoke` job exercises SBOM generation on every push/PR so the release-time path stays
validated without cutting a release.

**`docs.yml` — on every push to `main` (and manual dispatch).** Regenerates `docs/api.html`
and `docs/api-llm.html`, commits them if changed, builds the Jekyll site, and deploys it to
GitHub Pages. It shares a `main-asset-commit` concurrency group with `ci.yml`'s
`support-data` job so the two main-committing jobs never push concurrently.

**`publish.yml` ("Release") — on a version-tag push (`v*`), or manual dispatch against an
existing tag.** Creates the immutable GitHub Release; it does **not** publish to PyPI.

1. `build` — verifies the release tag matches `oscal/_version.py` (fails fast on a mismatch),
   then builds the sdist and wheel and runs `twine check`.
2. `sbom` — generates the CycloneDX SBOM and `THIRD-PARTY-LICENSES.md` from the built wheel
   (`scripts/generate_sbom.sh dist/*.whl`). See [SBOM](SBOM.html).
3. `github-release` — declares `needs: [build, sbom]`, so the Release is assembled only after
   the SBOM exists. Because releases are immutable, it creates the Release as a **draft**,
   uploads the wheel, sdist, SBOM, and license manifest, then **seals it** (publishes). The
   wheel + sdist are attached so the PyPI step publishes the exact same artifacts. If
   `build`/`sbom` fail, the tag is left reusable.

   *Fallback:* if the tag push does not auto-trigger the workflow, dispatch it manually
   (`gh workflow run publish.yml -f tag=vX.Y.Z`) against the existing tag.

**`pypi.yml` ("Publish to PyPI") — manual dispatch only.** Downloads the wheel + sdist
attached to the GitHub Release for the given tag and uploads them to PyPI via OIDC trusted
publishing (`pypa/gh-action-pypi-publish`, with `skip-existing`). Build provenance (PEP 740
attestations) is emitted by that action and shown on PyPI. Access is gated three ways:
`workflow_dispatch` requires repo write access, the `pypi` environment's required reviewer is
the real approval gate, and a job-level `if` restricts runs to the repository owner.

> **Note:** PyPI trusted publishing is scoped to the workflow **filename**. The PyPI
> project's trusted publisher must reference `pypi.yml` and the `pypi` environment, or OIDC
> publishing is rejected.

## If the tag and `_version.py` disagree

The Release workflow's `build` job stops with an error. Fix whichever is wrong — bump
`oscal/_version.py` to match the tag, or delete and re-create the tag to match the file — and
re-run the release (push the corrected tag, or dispatch `publish.yml` against it).
