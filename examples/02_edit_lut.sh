#!/bin/sh
# 02 - edit one LUT's INIT in a placed bitstream and show the single-byte change.
#
# edit-lut rewrites one logic element's 16-bit truth table and re-encodes the .bin,
# touching nothing else. This decodes the original and the patched .bin back to their
# raw fabric images and prints exactly which raw byte(s) changed -- expect one.
#
# Offline: no hardware needed. Run from the repo root (so `agamemnon` is importable),
# or after `pip install -e .`.
set -eu

# Input bitstream. Substitute your own .bin here.
BIN="${BIN:-tests/fixtures/blinky.bin}"

# Logic element to edit and the new 16-bit truth table.
LE="${LE:-20,12,1}"
INIT="${INIT:-0x96e9}"

TMP="$(mktemp -d)"
ORIG_RAW="$TMP/orig.raw"
PATCHED_BIN="$TMP/patched.bin"
PATCHED_RAW="$TMP/patched.raw"
trap 'rm -rf "$TMP"' EXIT

echo "input: $BIN   LE=$LE   INIT=$INIT"

# Edit the LUT (prints "N raw byte(s) changed"), then decode both images and diff them.
python -m agamemnon.cli edit-lut "$BIN" --le "$LE" --init "$INIT" -o "$PATCHED_BIN"
python -m agamemnon.cli decode "$BIN"          -o "$ORIG_RAW"
python -m agamemnon.cli decode "$PATCHED_BIN"  -o "$PATCHED_RAW"

python - "$ORIG_RAW" "$PATCHED_RAW" <<'PY'
import sys
a = open(sys.argv[1], "rb").read()
b = open(sys.argv[2], "rb").read()
diff = [i for i in range(len(a)) if a[i] != b[i]]
print("raw bytes differing: %d" % len(diff))
for i in diff:
    print("  byte %d: 0x%02x -> 0x%02x" % (i, a[i], b[i]))
PY
