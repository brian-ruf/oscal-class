#!/usr/bin/env bash
# tag-release.sh -- safely tag a release and switch back automatically.
#
# Encapsulates the one workflow that requires being on the release branch
# (default: main): tagging a release. Does checkout -> tag -> push -> switch
# back as one sequence, so "forgot to switch back to the dev branch
# afterward" stops being a failure mode that exists at all.
#
# Generic by design -- copy this file (and tag-release.cmd) into any repo's
# scripts/ folder. Nothing here names a specific repo, remote, or branch
# beyond the configurable defaults below.
#
# Usage:
#   scripts/tag-release.sh <tag>
#   e.g. scripts/tag-release.sh v2.1.0
#
# Configurable via environment variables (defaults shown):
#   RELEASE_BRANCH=main
#   REMOTE=origin

set -euo pipefail

RELEASE_BRANCH="${RELEASE_BRANCH:-main}"
REMOTE="${REMOTE:-origin}"

if [ $# -ne 1 ]; then
    echo "Usage: $0 <tag>" >&2
    echo "  e.g. $0 v2.1.0" >&2
    exit 1
fi
TAG="$1"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "error: not inside a git repository" >&2
    exit 1
fi

ORIGINAL_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
if [ -z "$ORIGINAL_BRANCH" ]; then
    echo "error: not currently on a branch (detached HEAD) -- aborting" >&2
    exit 1
fi

# Refuse with uncommitted changes: avoids any ambiguity about what ends up
# tagged, and avoids carrying local edits across the branch switch below.
if [ -n "$(git status --porcelain)" ]; then
    echo "error: you have uncommitted changes. Commit, stash, or discard them first." >&2
    exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "error: tag '$TAG' already exists locally." >&2
    exit 1
fi

echo "-------------------------------------------------------------------"
echo " About to tag a release:"
echo "   Tag           : $TAG"
echo "   Branch        : $RELEASE_BRANCH"
echo "   Remote        : $REMOTE"
echo "   Returning to  : $ORIGINAL_BRANCH"
echo "-------------------------------------------------------------------"
read -r -p "Continue? [y/N] " REPLY
case "$REPLY" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Aborted -- no changes made."; exit 1 ;;
esac

# Whatever happens from here, try to land back on the branch we started on.
cleanup() {
    git checkout "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git fetch "$REMOTE" --quiet
git checkout "$RELEASE_BRANCH"
git pull --ff-only "$REMOTE" "$RELEASE_BRANCH"

if git ls-remote --exit-code "$REMOTE" "refs/tags/$TAG" >/dev/null 2>&1; then
    echo "error: tag '$TAG' already exists on $REMOTE." >&2
    exit 1
fi

git tag -a "$TAG" -m "Release $TAG"
git push "$REMOTE" "$TAG"

echo "-------------------------------------------------------------------"
echo " Tagged and pushed $TAG from $RELEASE_BRANCH."
echo " Switching back to $ORIGINAL_BRANCH..."
echo "-------------------------------------------------------------------"
# cleanup() above (registered via trap on EXIT) performs the checkout back.
