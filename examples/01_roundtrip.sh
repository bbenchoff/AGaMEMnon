#!/bin/sh
# 01 — round-trip a fabric .bin through the open LZW codec, asserting byte-exact.
#
# decode: .bin -> 99936-byte raw fabric image
# encode: raw image -> .bin
# assert: re-encoded .bin == original .bin, byte for byte
#
# Offline: no hardware needed. Run from the repo root (so `agamemnon` is importable),
# or after `pip install -e .`.
set -eu

# Input bitstream. Substitute your own .bin here.
BIN="${BIN:-tests/fixtures/blinky.bin}"

# Scratch outputs.
TMP="$(mktemp -d)"
RAW="$TMP/fabric.raw"
REENC="$TMP/fabric.reenc.bin"
trap 'rm -rf "$TMP"' EXIT

echo "input: $BIN"

python -m agamemnon.cli decode "$BIN" -o "$RAW"
python -m agamemnon.cli encode "$RAW" -o "$REENC"

if cmp -s "$BIN" "$REENC"; then
    echo "ROUND-TRIP BYTE-EXACT OK"
else
    echo "ROUND-TRIP MISMATCH"
    echo "  (If your .bin has trailing flash padding past the LZW stream, the re-encoded"
    echo "   file may be shorter. The supplied blinky.bin matches exactly.)"
    cmp "$BIN" "$REENC" || true
    exit 1
fi
