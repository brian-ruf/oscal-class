#!/usr/bin/env bash
# release.sh -- orchestrate a full release on top of tag-release.sh.
#
# This is the repo-specific wrapper that `tag-release.sh` (deliberately generic) is NOT:
# it knows this project's version file and GitHub workflows, and chains the whole release
# so a maintainer runs one command instead of babysitting the Actions tab.
#
# It does, in order:
#   1. Sanity-check: the given tag must match __version__ in the version file ON THE RELEASE
#      BRANCH (the commit that will actually be tagged -- not your current working branch),
#      mirroring the check publish.yml runs server-side, but failing fast locally.
#   2. Tag + push via tag-release.sh (which handles checkout/pull/push/switch-back + guards).
#   3. Wait for the "Release" workflow (publish.yml) run for that tag to appear, then watch it
#      to completion -- it builds the wheel/sdist/SBOM and creates the GitHub Release.
#   4. With --publish, dispatch "Publish to PyPI" (pypi.yml) for the tag once the release is
#      built. (That workflow still pauses on the `pypi` environment reviewer gate -- approve
#      it in the Actions tab; that approval stays manual by design.)
#
# Steps 3-4 require the GitHub CLI (`gh`, authenticated). Without it, the tag is still pushed
# (step 2) and you finish in the Actions tab manually.
#
# Usage:
#   scripts/release.sh <tag> [--publish]
#   e.g. scripts/release.sh v4.2.1 --publish
#
# Configurable via environment variables (defaults shown):
#   RELEASE_BRANCH=main
#   REMOTE=origin
#   VERSION_FILE=oscal/_version.py
#   RELEASE_WORKFLOW=publish.yml      # tag-triggered build + GitHub Release
#   PYPI_WORKFLOW=pypi.yml            # manually dispatched PyPI publish
#   START_TIMEOUT=180                 # seconds to wait for the Release run to appear (~3 min)
#   RUN_TIMEOUT=2700                  # seconds to wait for the Release run to finish (45 min;
#                                     #   the pipeline has been running a little under 15)
#   POLL_INTERVAL=5                   # seconds between polls while the run is appearing

set -euo pipefail

RELEASE_BRANCH="${RELEASE_BRANCH:-main}"
REMOTE="${REMOTE:-origin}"
VERSION_FILE="${VERSION_FILE:-oscal/_version.py}"
RELEASE_WORKFLOW="${RELEASE_WORKFLOW:-publish.yml}"
PYPI_WORKFLOW="${PYPI_WORKFLOW:-pypi.yml}"
START_TIMEOUT="${START_TIMEOUT:-180}"
RUN_TIMEOUT="${RUN_TIMEOUT:-2700}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

# --- argument parsing: <tag> plus optional --publish, in any order ---------
TAG=""
PUBLISH=0
for arg in "$@"; do
    case "$arg" in
        --publish) PUBLISH=1 ;;
        -h|--help)
            echo "Usage: $0 <tag> [--publish]"
            echo "  e.g. $0 v4.2.1 --publish"
            exit 0 ;;
        -*)
            echo "error: unknown option '$arg'" >&2
            echo "Usage: $0 <tag> [--publish]" >&2
            exit 1 ;;
        *)
            if [ -n "$TAG" ]; then
                echo "error: more than one tag given ('$TAG' and '$arg')" >&2
                exit 1
            fi
            TAG="$arg" ;;
    esac
done
if [ -z "$TAG" ]; then
    echo "Usage: $0 <tag> [--publish]" >&2
    echo "  e.g. $0 v4.2.1 --publish" >&2
    exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "error: not inside a git repository" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -x "$SCRIPT_DIR/tag-release.sh" ]; then
    echo "error: $SCRIPT_DIR/tag-release.sh not found or not executable." >&2
    exit 1
fi

# --- 1. sanity-check the tag against the version that will actually be tagged -----------
# Read __version__ from the version file on the RELEASE branch (not the current checkout):
# the tag lands on $RELEASE_BRANCH, so that is the version publish.yml will compare against.
git fetch "$REMOTE" "$RELEASE_BRANCH" --quiet
if ! VERSION_LINE=$(git show "$REMOTE/$RELEASE_BRANCH:$VERSION_FILE" 2>/dev/null); then
    echo "error: could not read '$VERSION_FILE' from $REMOTE/$RELEASE_BRANCH." >&2
    exit 1
fi
PKG="$(printf '%s\n' "$VERSION_LINE" | grep -oP '__version__\s*=\s*"\K[^"]+' || true)"
if [ -z "$PKG" ]; then
    echo "error: could not find __version__ in '$VERSION_FILE' on $REMOTE/$RELEASE_BRANCH." >&2
    exit 1
fi
if [ "$TAG" != "v$PKG" ]; then
    echo "error: tag '$TAG' does not match $REMOTE/$RELEASE_BRANCH $VERSION_FILE (__version__ = $PKG)." >&2
    echo "       Merge the version bump to $RELEASE_BRANCH first, or pass tag 'v$PKG'." >&2
    exit 1
fi
echo "Version check OK: $TAG matches $REMOTE/$RELEASE_BRANCH $VERSION_FILE (__version__ = $PKG)."

# --- 2. tag + push (tag-release.sh runs its own guards + confirmation prompt) ------------
"$SCRIPT_DIR/tag-release.sh" "$TAG"

# Steps 3-4 need gh. Without it, the tag is pushed; finish manually in the Actions tab.
if ! command -v gh >/dev/null 2>&1; then
    echo "note: GitHub CLI (gh) not found -- tag pushed, but cannot watch the Release run or"
    echo "      dispatch PyPI from here. Do it in the Actions tab:"
    echo "        - wait for '$RELEASE_WORKFLOW' to finish"
    echo "        - run '$PYPI_WORKFLOW' with tag=$TAG"
    exit 0
fi

TAG_SHA="$(git rev-parse "refs/tags/$TAG^{commit}")"

# --- 3a. wait for the Release run to appear (it starts within seconds of the tag push) ---
echo "Waiting up to ${START_TIMEOUT}s for the '$RELEASE_WORKFLOW' run on $TAG to start..."
run_id=""
deadline=$((SECONDS + START_TIMEOUT))
while [ "$SECONDS" -lt "$deadline" ]; do
    run_id="$(gh run list --workflow="$RELEASE_WORKFLOW" --limit 30 \
                --json databaseId,headSha,event \
                --jq "[.[] | select(.headSha==\"$TAG_SHA\" and .event==\"push\")][0].databaseId" \
              2>/dev/null || true)"
    if [ -n "$run_id" ] && [ "$run_id" != "null" ]; then
        break
    fi
    sleep "$POLL_INTERVAL"
done
if [ -z "$run_id" ] || [ "$run_id" = "null" ]; then
    echo "error: no '$RELEASE_WORKFLOW' run for $TAG (commit ${TAG_SHA:0:8}) appeared within ${START_TIMEOUT}s." >&2
    echo "       The tag is pushed -- check the Actions tab; the workflow may be disabled or slow to queue." >&2
    exit 1
fi

# --- 3b. watch the Release run to completion --------------------------------------------
echo "Watching Release run $run_id (timeout ${RUN_TIMEOUT}s)..."
if ! timeout "$RUN_TIMEOUT" gh run watch "$run_id" --exit-status; then
    echo "error: '$RELEASE_WORKFLOW' run $run_id failed or did not finish within ${RUN_TIMEOUT}s." >&2
    echo "       Do NOT publish to PyPI until the release is built. Inspect: gh run view $run_id --log" >&2
    exit 1
fi
echo "Release built: the $TAG GitHub Release now has the wheel, sdist, and SBOM attached."

# --- 4. optionally dispatch the PyPI publish --------------------------------------------
if [ "$PUBLISH" -eq 1 ]; then
    echo "Dispatching '$PYPI_WORKFLOW' for $TAG..."
    gh workflow run "$PYPI_WORKFLOW" -f tag="$TAG"
    echo "Dispatched. Approve the 'pypi' environment gate in the Actions tab to complete the upload."
else
    echo "Done. To publish to PyPI: gh workflow run $PYPI_WORKFLOW -f tag=$TAG   (or re-run with --publish)"
fi
