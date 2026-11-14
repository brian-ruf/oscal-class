# OSCAL Version Monitoring and Support-Data Delivery

**Status:** idea / design notes. Not started — set aside to ship the current release.
**Captured:** 2026-11-13.

**Goal:** the published `oscal` package should include the latest NIST OSCAL release in its
support database as soon as possible after NIST publishes it, while staying transparent to
users (`pip install oscal` is all they do) and working fully offline once installed.

## Background: how the support database works today

- `oscal/data/oscal_support.zip` ships **inside** the `oscal` wheel.
- `python -m oscal.update_support` builds it from the NIST OSCAL GitHub releases:
    - `--all` clears and re-fetches every release (about 15 today and growing; dozens of files each).
    - `--new` (the default) fetches only releases the database doesn't have yet — usually a
      fast "nothing new" check.
- CI (`ci.yml`, `support-data` job) currently runs `--all` on every merge to main, re-runs the
  unit tests, and commits the zip to main if it changed.
- Consequence: new OSCAL data only reaches users when a new **library** release is cut.

## Relationship to the SBOM

- Each release's SBOM is generated from that release's built wheel and attached to that
  (immutable) GitHub Release. Later database changes on main never invalidate an existing SBOM;
  they only affect what the *next* release contains.
- Ordering rule: any database update must happen **before** the build, and the SBOM is
  generated from the built wheel: `DB update → test → build → SBOM → release`.
- The current SBOM (`cyclonedx-py environment`) lists installed packages, not data files, so it
  does not record which OSCAL versions the database contains. Option 4 below fixes that.

## Options considered

### 1. Scheduled database update committed to main

A scheduled workflow checks NIST for new releases, runs `update_support --new`, runs the unit
tests, and commits the zip to main if they pass. The next library release picks it up.

- Cheap and safe; data reaches main quickly.
- Data still reaches **users** only when a library release is cut.

### 2. Scheduled update + automatic library release + automatic PyPI publish — rejected

Extends option 1 to bump the patch version and run the release workflow automatically.

**Rejected (for now)** because the release would build from the current state of main, not the
last release. Anything merged to main but not yet meant for release would ship with the data
update. It also creates version collisions with develop (the bot and a human both claiming the
next patch number) and requires removing the human PyPI approval gate.

If ever revisited, required guardrails:
- main must always be releasable, *or* the job builds from the last release tag plus new data;
- the bot owns the patch number (manual releases bump at least the minor version);
- the job refuses to release if anything other than the zip and `_version.py` changed;
- auto-release only patch-level OSCAL releases (e.g. 1.1.3 → 1.1.4); minor/major OSCAL releases
  (e.g. 1.2.0 added the Control Mapping model) may need code support, so open an issue/PR
  for human review instead;
- open a GitHub issue when the update or tests fail;
- share the `main-asset-commit` concurrency group.

### 3. Database regeneration once per PR

To have the regenerated database reviewed in the PR without rebuilding it on every PR update:

- run the regen job on `pull_request: types: [ready_for_review]` (iterate as a draft PR; mark
  ready once), committing the zip to the PR branch;
- use `--new` normally; use `--all` only when the PR changes `update_support.py` or
  `oscal_support.py`;
- the job must run the unit tests itself (commits pushed with `GITHUB_TOKEN` don't trigger CI);
- pull the PR branch afterwards to avoid binary conflicts on the zip.

### 4. Separate data package — recommended direction

Publish the database as its own PyPI project (e.g. `oscal-support-data`) that `oscal` depends on
(`dependencies = ["oscal-support-data>=2026.11"]`). This is how `tzdata` and `certifi` work.

- **Transparent:** `pip install oscal` installs it automatically; works offline afterwards.
- **Independent releases:** data can be released on its own schedule, including fully
  automatically, without ever building or releasing library code from main. This removes the
  blocker in option 2.
- **User-updatable:** `pip install -U oscal-support-data` gets new data without a library update.
- **Versioning:** date-based (e.g. `2026.11.13`); never collides with library versions.
- **SBOM:** appears as a dependency with its own version, so each library SBOM records which data
  release is in use.

Costs / contract:
- a format-version check at load time (clear error on mismatch) and/or a bounded dependency
  range (e.g. `>=2026.11,<2027`);
- the library must ignore OSCAL versions in the data it does not yet support, so data releases
  can include new OSCAL versions before code support lands;
- bump the library's lower bound when it starts relying on newer data;
- a second PyPI project, release workflow, and version stream.

Options also ruled out: download-on-first-use (breaks offline), install-time hooks (wheels can't
run code at install), an optional extra like `pip install oscal[data]` (a plain install wouldn't
include the data). A later add-on could let users refresh data into a local cache
(`update_support --new`) that the library prefers when present.

## Two PyPI projects from this one repository

Supported by both PyPI and GitHub (common in large projects).

```
class/
  pyproject.toml                       # oscal (library)
  oscal/
  packages/oscal-support-data/
    pyproject.toml                     # oscal-support-data
    oscal_support_data/
      __init__.py                      # path helper only
      oscal_support.zip
```

- The library build must exclude `packages/`; the data package must **not** depend on `oscal`.
- The generator (`update_support`) stays in the repo as tooling, not in the data package.
- Separate workflows: `publish.yml` (library) and `publish-data.yml` (data; scheduled + manual).
- Distinct tag prefixes: `v4.2.5` (library) vs `data-v2026.11.13` (data).
- PyPI trusted publishers are per project (repo + workflow file + environment). Create the new
  project with a "pending publisher"; its first upload creates it.
- GitHub Releases share one list; create data releases with `--latest=false`.
- CI and local dev install both editable (`pip install -e . -e packages/oscal-support-data`) so
  library tests use the repo's data, not PyPI's. Run library tests on data changes too.

## Suggested sequence when picked up

1. Settle the data format contract (format version + how unsupported OSCAL versions are ignored).
2. Split the data into `packages/oscal-support-data` and make `oscal` depend on it.
3. Add `publish-data.yml` (manual first), register the PyPI pending publisher, release once.
4. Add the scheduled check (`update_support --new` → tests → data release), with failure issues.
5. Remove the `support-data` regen from the library's CI.
