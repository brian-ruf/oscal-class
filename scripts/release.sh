#!/usr/bin/env bash
# release.sh -- orchestrate a full release, end to end, from one command.
#
# This is the single sanctioned entry point for cutting a release. It absorbs what used to
# be a separate tag-release.sh primitive: there is intentionally no standalone tagging
# script, so a release tag is never created outside this orchestration (and its guards).
#
# It does, in order:
#   1. Sanity-check: the given tag must match __version__ in the version file ON THE RELEASE
#      BRANCH (the commit that will actually be tagged -- not your current working branch),
#      mirroring the check publish.yml runs server-side, but failing fast locally.
#   2. TIMING GUARD: wait until the post-merge asset-refresh workflows on the release branch
#      (CI Pipeline's support-DB refresh + Docs' API-doc refresh) have finished and their
#      commits have landed, so the tag lands on the fully-refreshed commit -- not on a
#      pre-refresh commit whose wheel would ship a stale support database. (Requires gh; see
#      --force for the escape hatch. The same staleness is also enforced server-side in
#      publish.yml, which rejects a stale tag outright.)
#   3. Tag + push: checkout the release branch, fast-forward it, tag the settled HEAD, push
#      the tag, and switch back to the branch you started on (even on failure).
#   4. Wait for the "Release" workflow (publish.yml) run for that tag to appear, then watch it
#      to completion -- it builds the wheel/sdist/SBOM and creates the GitHub Release.
#   5. With --publish, dispatch "Publish to PyPI" (pypi.yml) for the tag once the release is
#      built. (That workflow still pauses on the `pypi` environment reviewer gate -- approve
#      it in the Actions tab; that approval stays manual by design.)
#
# Steps 2, 4, 5 require the GitHub CLI (`gh`, authenticated). Without gh the timing guard
# cannot run: the script refuses unless you pass --force (then the server-side guard in
# publish.yml is your only protection), and after tagging you finish in the Actions tab.
#
# Usage:
#   scripts/release.sh <tag> [--publish] [--force] [--yes]
#   e.g. scripts/release.sh v4.3.1 --publish
#
# Flags:
#   --publish   after the Release is built, dispatch the PyPI publish workflow for the tag.
#   --force     skip the timing guard (use only when you have manually confirmed the release
#               branch has fully settled; the server-side guard still applies).
#   --yes       skip the interactive confirmation prompt before tagging.
#
# Configurable via environment variables (defaults shown):
#   RELEASE_BRANCH=main
#   REMOTE=origin
#   VERSION_FILE=oscal/_version.py
#   RELEASE_WORKFLOW=publish.yml      # tag-triggered build + GitHub Release ("Release")
#   PYPI_WORKFLOW=pypi.yml            # manually dispatched PyPI publish ("Publish to PyPI")
#   ASSET_WORKFLOWS="CI Pipeline" "Docs"   # workflow *names* that commit assets to the branch
#   SETTLE_TIMEOUT=1800               # seconds to wait for the branch to settle (30 min)
#   SETTLE_GRACE=15                   # seconds of quiet (no active runs, stable HEAD) to
#                                     #   confirm no asset run is still about to queue
#   START_TIMEOUT=180                 # seconds to wait for the Release run to appear (~3 min)
#   RUN_TIMEOUT=2700                  # seconds to wait for the Release run to finish (45 min)
#   POLL_INTERVAL=5                   # seconds between polls

set -euo pipefail

RELEASE_BRANCH="${RELEASE_BRANCH:-main}"
REMOTE="${REMOTE:-origin}"
VERSION_FILE="${VERSION_FILE:-oscal/_version.py}"
RELEASE_WORKFLOW="${RELEASE_WORKFLOW:-publish.yml}"
PYPI_WORKFLOW="${PYPI_WORKFLOW:-pypi.yml}"
SETTLE_TIMEOUT="${SETTLE_TIMEOUT:-1800}"
SETTLE_GRACE="${SETTLE_GRACE:-15}"
START_TIMEOUT="${START_TIMEOUT:-180}"
RUN_TIMEOUT="${RUN_TIMEOUT:-2700}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
# Workflow names (not filenames) that push asset-refresh commits to the release branch.
ASSET_WORKFLOWS=("CI Pipeline" "Docs")

# --- argument parsing: <tag> plus optional flags, in any order ----------------------------
TAG=""
PUBLISH=0
FORCE=0
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        --publish) PUBLISH=1 ;;
        --force)   FORCE=1 ;;
        --yes|-y)  ASSUME_YES=1 ;;
        -h|--help)
            echo "Usage: $0 <tag> [--publish] [--force] [--yes]"
            echo "  e.g. $0 v4.3.1 --publish"
            exit 0 ;;
        -*)
            echo "error: unknown option '$arg'" >&2
            echo "Usage: $0 <tag> [--publish] [--force] [--yes]" >&2
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
    echo "Usage: $0 <tag> [--publish] [--force] [--yes]" >&2
    echo "  e.g. $0 v4.3.1 --publish" >&2
    exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "error: not inside a git repository" >&2
    exit 1
fi

ORIGINAL_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
if [ -z "$ORIGINAL_BRANCH" ]; then
    echo "error: not currently on a branch (detached HEAD) -- aborting" >&2
    exit 1
fi

# Refuse with uncommitted changes: avoids any ambiguity about what ends up tagged, and avoids
# carrying local edits across the branch switch below.
if [ -n "$(git status --porcelain)" ]; then
    echo "error: you have uncommitted changes. Commit, stash, or discard them first." >&2
    exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "error: tag '$TAG' already exists locally." >&2
    exit 1
fi

HAVE_GH=0
command -v gh >/dev/null 2>&1 && HAVE_GH=1

# --- 1. sanity-check the tag against the version that will actually be tagged --------------
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

# --- 2. TIMING GUARD: wait for the release branch to settle after the merge ---------------
# After a merge, CI Pipeline (support-DB refresh) and Docs (API-doc refresh) run and push
# `chore:` commits to the release branch. Tagging before those land would tag a pre-refresh
# commit, so the built wheel would ship a stale support database. Wait until no asset
# workflow is queued/in-progress on the branch AND HEAD is stable for a short grace period.
# Count the number of active asset-workflow runs on the release branch.
active_asset_runs() {
    local names_jq total=0 name count
    for name in "${ASSET_WORKFLOWS[@]}"; do
        count="$(gh run list --branch "$RELEASE_BRANCH" --limit 40 \
                    --json status,workflowName \
                    --jq "[.[] | select(.workflowName==\"$name\") | select(.status==\"queued\" or .status==\"in_progress\" or .status==\"requested\" or .status==\"waiting\")] | length" \
                 2>/dev/null || echo 0)"
        total=$((total + count))
    done
    echo "$total"
}

settle_wait() {
    echo "Timing guard: waiting for $REMOTE/$RELEASE_BRANCH to settle (no active ${ASSET_WORKFLOWS[*]} runs)..."
    local deadline=$((SECONDS + SETTLE_TIMEOUT)) active head_before head_after active2
    while [ "$SECONDS" -lt "$deadline" ]; do
        git fetch "$REMOTE" "$RELEASE_BRANCH" --quiet
        active="$(active_asset_runs)"
        if [ "$active" -eq 0 ]; then
            # No active runs right now. Confirm it stays that way AND the tip is stable, to
            # catch a run that is about to queue in the seconds right after a merge.
            head_before="$(git rev-parse "$REMOTE/$RELEASE_BRANCH")"
            sleep "$SETTLE_GRACE"
            git fetch "$REMOTE" "$RELEASE_BRANCH" --quiet
            active2="$(active_asset_runs)"
            head_after="$(git rev-parse "$REMOTE/$RELEASE_BRANCH")"
            if [ "$active2" -eq 0 ] && [ "$head_after" = "$head_before" ]; then
                echo "Branch settled at ${head_after:0:8}; no asset refresh pending."
                return 0
            fi
        fi
        echo "  ...asset refresh still in flight; re-checking in ${POLL_INTERVAL}s."
        sleep "$POLL_INTERVAL"
    done
    echo "error: $REMOTE/$RELEASE_BRANCH did not settle within ${SETTLE_TIMEOUT}s." >&2
    echo "       An asset-refresh run (CI Pipeline / Docs) is still active. Wait for it in the" >&2
    echo "       Actions tab, then re-run; or --force if you have confirmed it is done." >&2
    exit 1
}

if [ "$FORCE" -eq 1 ]; then
    echo "WARNING: --force given; skipping the timing guard. Ensure $RELEASE_BRANCH has fully"
    echo "         settled (support DB + API docs refreshed and committed). The server-side"
    echo "         guard in $RELEASE_WORKFLOW will still reject a stale tag."
elif [ "$HAVE_GH" -eq 1 ]; then
    settle_wait
else
    echo "error: GitHub CLI (gh) not found -- cannot verify $RELEASE_BRANCH has settled after the" >&2
    echo "       merge, so tagging now risks shipping a stale support database. Install/auth gh," >&2
    echo "       or re-run with --force only after confirming the asset-refresh workflows have" >&2
    echo "       finished (the server-side guard in $RELEASE_WORKFLOW still applies)." >&2
    exit 1
fi

# --- 3. tag + push (with its own guards, confirmation, and switch-back) --------------------
if [ "$ASSUME_YES" -eq 1 ]; then
    CONFIRM_NOTE="(--yes: skipping prompt)"
else
    CONFIRM_NOTE=""
fi
echo "-------------------------------------------------------------------"
echo " About to tag a release:"
echo "   Tag           : $TAG"
echo "   Branch        : $RELEASE_BRANCH"
echo "   Remote        : $REMOTE"
echo "   Returning to  : $ORIGINAL_BRANCH"
echo "-------------------------------------------------------------------"
if [ "$ASSUME_YES" -ne 1 ]; then
    read -r -p "Continue? [y/N] " REPLY
    case "$REPLY" in
        [yY]|[yY][eE][sS]) ;;
        *) echo "Aborted -- no changes made."; exit 1 ;;
    esac
fi

# Whatever happens from here, try to land back on the branch we started on.
cleanup() {
    git checkout "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git checkout "$RELEASE_BRANCH"
git pull --ff-only "$REMOTE" "$RELEASE_BRANCH"

if git ls-remote --exit-code "$REMOTE" "refs/tags/$TAG" >/dev/null 2>&1; then
    echo "error: tag '$TAG' already exists on $REMOTE." >&2
    exit 1
fi

git tag -a "$TAG" -m "Release $TAG"
git push "$REMOTE" "$TAG"
echo "Tagged and pushed $TAG from $RELEASE_BRANCH."

# Steps 4-5 need gh. Without it, the tag is pushed; finish manually in the Actions tab.
if [ "$HAVE_GH" -ne 1 ]; then
    echo "note: GitHub CLI (gh) not found -- tag pushed, but cannot watch the Release run or"
    echo "      dispatch PyPI from here. Do it in the Actions tab:"
    echo "        - wait for '$RELEASE_WORKFLOW' to finish"
    echo "        - run '$PYPI_WORKFLOW' with tag=$TAG"
    exit 0
fi

TAG_SHA="$(git rev-parse "refs/tags/$TAG^{commit}")"

# --- 4a. wait for the Release run to appear (it starts within seconds of the tag push) ----
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

# --- 4b. watch the Release run to completion ----------------------------------------------
echo "Watching Release run $run_id (timeout ${RUN_TIMEOUT}s)..."
if ! timeout "$RUN_TIMEOUT" gh run watch "$run_id" --exit-status; then
    echo "error: '$RELEASE_WORKFLOW' run $run_id failed or did not finish within ${RUN_TIMEOUT}s." >&2
    echo "       Do NOT publish to PyPI until the release is built. Inspect: gh run view $run_id --log" >&2
    exit 1
fi
echo "Release built: the $TAG GitHub Release now has the wheel, sdist, and SBOM attached."

# --- 5. optionally dispatch the PyPI publish ----------------------------------------------
if [ "$PUBLISH" -eq 1 ]; then
    echo "Dispatching '$PYPI_WORKFLOW' for $TAG..."
    gh workflow run "$PYPI_WORKFLOW" -f tag="$TAG"
    echo "Dispatched. Approve the 'pypi' environment gate in the Actions tab to complete the upload."
else
    echo "Done. To publish to PyPI: gh workflow run $PYPI_WORKFLOW -f tag=$TAG   (or re-run with --publish)"
fi
