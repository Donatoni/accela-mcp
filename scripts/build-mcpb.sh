#!/usr/bin/env bash
# Builds the .mcpb bundle into dist/.
#
# The bundle is a ZIP containing manifest.json + the project source so that
# `uv run` can resolve dependencies on the user's machine on first launch.
# We assemble a clean staging directory and pack from there to keep noise
# (.git, tests, caches) out of the artifact.
#
# Requirements:
#   - bash, cp, find, sed, jq (most macOS / Linux already have these)
#   - npx (Node) on PATH for `@anthropic-ai/mcpb`
#
# Usage:
#   ./scripts/build-mcpb.sh
# Output:
#   dist/accela-mcp-<version>.mcpb

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${ROOT}/dist"
WORK="${DIST}/mcpb-build"

# Pull version from pyproject.toml so the bundle and PyPI release stay aligned.
VERSION="$(grep -E '^version = ' "${ROOT}/pyproject.toml" | head -1 | sed -E 's/version = "(.*)"/\1/')"
if [ -z "${VERSION}" ]; then
    echo "error: could not parse version from pyproject.toml" >&2
    exit 1
fi

# Verify manifest.json version matches pyproject.toml version. We could
# rewrite the manifest at build time, but failing loud is safer — mismatched
# versions in the install dialog vs the package have surprised users before.
MANIFEST_VERSION="$(grep -E '^\s*"version":' "${ROOT}/manifest.json" | head -1 | sed -E 's/.*"version": "(.*)",?/\1/')"
if [ "${VERSION}" != "${MANIFEST_VERSION}" ]; then
    echo "error: pyproject.toml version (${VERSION}) does not match manifest.json version (${MANIFEST_VERSION})." >&2
    echo "       Update both before building." >&2
    exit 1
fi

echo "==> Cleaning ${WORK}"
rm -rf "${WORK}"
mkdir -p "${WORK}" "${DIST}"

echo "==> Staging bundle contents"
cp "${ROOT}/manifest.json"  "${WORK}/manifest.json"
cp "${ROOT}/pyproject.toml" "${WORK}/pyproject.toml"
cp "${ROOT}/README.md"      "${WORK}/README.md"
cp "${ROOT}/LICENSE"        "${WORK}/LICENSE"
if [ -f "${ROOT}/uv.lock" ]; then
    cp "${ROOT}/uv.lock" "${WORK}/uv.lock"
fi

# Source tree — copy only what's needed at runtime.
cp -R "${ROOT}/src" "${WORK}/src"

# Bundle-only assets: launcher + icon.
cp -R "${ROOT}/bundle/server" "${WORK}/server"
if [ -f "${ROOT}/bundle/icon.png" ]; then
    cp "${ROOT}/bundle/icon.png" "${WORK}/icon.png"
fi

# Strip __pycache__ and .pyc files from the staged copy so they don't leak
# into the artifact.
find "${WORK}" -type d -name __pycache__ -exec rm -rf {} +
find "${WORK}" -type f -name '*.pyc' -delete

OUTPUT="${DIST}/accela-mcp-${VERSION}.mcpb"
echo "==> Packing ${OUTPUT}"
(
    cd "${WORK}"
    npx -y -p @anthropic-ai/mcpb mcpb pack . "${OUTPUT}"
)

echo "==> Built: ${OUTPUT}"
ls -lh "${OUTPUT}"
