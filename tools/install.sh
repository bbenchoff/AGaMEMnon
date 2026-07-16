#!/bin/sh
set -eu

VERSION=${1:-0.1.0}
DEST=${2:-"${HOME}/.agamemnon/sdk-${VERSION}"}
ASSET=agamemnon-sdk-linux-x64.tar.gz
BASE="https://github.com/bbenchoff/AGaMEMnon/releases/download/v${VERSION}"
TMP=${TMPDIR:-/tmp}/agamemnon-${VERSION}-$$
mkdir -p "$TMP" "$DEST"
curl -fL "$BASE/$ASSET" -o "$TMP/$ASSET"
curl -fL "$BASE/$ASSET.sha256" -o "$TMP/$ASSET.sha256"
(cd "$TMP" && sha256sum -c "$ASSET.sha256")
tar -xzf "$TMP/$ASSET" -C "$DEST"
echo "Installed verified bundle at $DEST"
echo "Run: . '$DEST/agamemnon-sdk-linux-x64/activate.sh'"
echo "Then install its wheel and run: agamemnon doctor"
