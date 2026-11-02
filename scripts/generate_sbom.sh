#!/usr/bin/env bash
#
# Generate oscal's release artifacts:
#   - oscal-<version>.cdx.json   CycloneDX SBOM of the wheel's runtime closure
#   - THIRD-PARTY-LICENSES.md     license manifest for that same closure
#
# Runs anywhere (locally or in CI) so the release pipeline can be exercised WITHOUT
# cutting a release. The publish workflow calls this with the already-built wheel.
#
# Usage:
#   scripts/generate_sbom.sh [path/to/oscal-<ver>.whl]
#
#   - With a wheel argument (CI): describes exactly that artifact.
#   - With no argument (local): builds a wheel first, then describes it.
#   - OUTDIR env var controls where outputs land (default: repo root / cwd).
#
# Why two throwaway venvs: the SBOM must describe ONLY what ships, so the wheel is
# installed into a clean runtime-only venv, while cyclonedx-bom is installed into a
# SEPARATE tool venv and merely introspects the first — keeping its own dependencies
# out of the SBOM. Nothing is installed into your active environment.
set -euo pipefail

# Resolve an explicit wheel path to absolute BEFORE changing directory, so the script
# works no matter where it is invoked from.
WHEEL="${1:-}"
if [ -n "$WHEEL" ]; then
  WHEEL="$(cd "$(dirname "$WHEEL")" && pwd)/$(basename "$WHEEL")"
fi

cd "$(dirname "$0")/.."                     # repo root

VERSION="$(python3 -c "import re,pathlib;print(re.search(r'__version__\s*=\s*\"([^\"]+)\"',pathlib.Path('oscal/_version.py').read_text()).group(1))")"
OUTDIR="${OUTDIR:-$PWD}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if [ -z "$WHEEL" ]; then
  echo "No wheel given; building one..."
  python3 -m venv "$work/build"
  "$work/build/bin/pip" install --quiet --upgrade pip build
  "$work/build/bin/python" -m build --wheel --outdir "$work/dist" >/dev/null
  WHEEL="$(ls "$work"/dist/*.whl | head -1)"
fi
echo "Describing wheel: $WHEEL"

# Clean runtime-only environment == exactly what a consumer installs.
python3 -m venv "$work/rt"
"$work/rt/bin/pip" install --quiet --upgrade pip
"$work/rt/bin/pip" install --quiet "$WHEEL"
# Remove venv bootstrap tooling so it is not reported as an oscal dependency in the SBOM
# (keeps the SBOM aligned with THIRD-PARTY-LICENSES.md, which already excludes these).
"$work/rt/bin/pip" uninstall -y pip setuptools wheel >/dev/null 2>&1 || true

# Separate tool environment for cyclonedx (kept out of the SBOM).
python3 -m venv "$work/tool"
"$work/tool/bin/pip" install --quiet cyclonedx-bom
"$work/tool/bin/cyclonedx-py" environment "$work/rt/bin/python" \
  --output-format JSON \
  --output-file "$OUTDIR/oscal-${VERSION}.cdx.json"

# License manifest from the same runtime closure (stdlib-only script).
"$work/rt/bin/python" scripts/generate_thirdparty_licenses.py \
  -o "$OUTDIR/THIRD-PARTY-LICENSES.md"

echo "Wrote:"
echo "  $OUTDIR/oscal-${VERSION}.cdx.json"
echo "  $OUTDIR/THIRD-PARTY-LICENSES.md"
