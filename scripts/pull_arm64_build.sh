#!/usr/bin/env bash
set -euo pipefail

REPO="${LART_RELEASE_REPO:-FSLART/data_station}"
TAG="${LART_RELEASE_TAG:-latest-arm64}"  # latest-arm64-dev for the runtime branch build
ASSET="lart-dashboard-arm64.tar.gz"
WS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading ${ASSET} from ${REPO}@${TAG}..."
curl -fsSL "https://github.com/${REPO}/releases/download/${TAG}/${ASSET}" -o "$TMP/${ASSET}"

if ! tar tzf "$TMP/${ASSET}" install/data_station_runtime/share/data_station_runtime/package.xml >/dev/null; then
    echo "Release has no data_station_runtime package; keeping the current install." >&2
    exit 1
fi

echo "Removing old build output..."
rm -rf "$WS_DIR/install" "$WS_DIR/LART_Car_Dashboard_v1/build/ui-build"

echo "Extracting into ${WS_DIR}..."
tar xzf "$TMP/${ASSET}" -C "$WS_DIR"

echo "Done. Run: source $WS_DIR/install/setup.bash"
