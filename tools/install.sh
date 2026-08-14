#!/bin/sh
set -eu

VERSION=${1:-0.3.0}
DEST=${2:-"${HOME}/.agamemnon/sdk-${VERSION}"}
case "$VERSION" in
    [0-9A-Za-z]*) ;;
    *) echo "Invalid SDK version: $VERSION" >&2; exit 1 ;;
esac
case "$VERSION" in
    *[!0-9A-Za-z._-]*) echo "Invalid SDK version: $VERSION" >&2; exit 1 ;;
esac
ASSET=agamemnon-sdk-linux-x64.tar.gz
BASE="https://github.com/bbenchoff/AGaMEMnon/releases/download/v${VERSION}"
TMP=${TMPDIR:-/tmp}/agamemnon-${VERSION}-$$
BUNDLE="$DEST/agamemnon-sdk-linux-x64"

if [ -d "$DEST" ] && [ -n "$(find "$DEST" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo "Install destination is not empty: $DEST" >&2
    exit 1
fi
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP" "$DEST"
curl -fL "$BASE/$ASSET" -o "$TMP/$ASSET"
curl -fL "$BASE/$ASSET.sha256" -o "$TMP/$ASSET.sha256"
(cd "$TMP" && sha256sum -c "$ASSET.sha256")
tar -xzf "$TMP/$ASSET" -C "$DEST"

set -- "$BUNDLE"/packages/agamemnon_ag32-*.whl
[ "$#" -eq 1 ] && [ -f "$1" ] || {
    echo "Expected one AGaMEMnon wheel, found $#" >&2
    exit 1
}
python3 -m venv "$BUNDLE/.venv"
"$BUNDLE/.venv/bin/python" -m pip install \
    --no-index --find-links "$BUNDLE/packages" "$1"

# shellcheck source=/dev/null
AGAMEMNON_SDK_ROOT=$BUNDLE
export AGAMEMNON_SDK_ROOT
. "$BUNDLE/activate.sh"
unset AGAMEMNON_SDK_ROOT
"$BUNDLE/.venv/bin/python" -m agamemnon.cli doctor --no-hardware

echo "Installed verified SDK at $BUNDLE"
echo "For this shell: . '$BUNDLE/activate.sh'"
