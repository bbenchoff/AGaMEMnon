#!/usr/bin/env bash
# build.sh — build nextpnr-generic with the AGaMEMnon `agrv2k` Viaduct uarch overlaid in.
#
# Target toolchain: native Linux GCC/Clang or MSYS2 / mingw-w64. Produces a
# host-native nextpnr-generic executable for the AGaMEMnon flow.
#
# Model (see ../README.md): nextpnr is a PINNED upstream checkout; our uarch is an OVERLAY.
# This script copies agrv2k.cc into <nextpnr>/generic/viaduct/agrv2k/ and adds ONE line to
# <nextpnr>/generic/CMakeLists.txt. It never edits upstream logic; re-running is idempotent.
#
# Prerequisites (install once in the MINGW64 shell):
#   pacman -S --needed mingw-w64-x86_64-cmake mingw-w64-x86_64-ninja mingw-w64-x86_64-gcc \
#                      mingw-w64-x86_64-boost mingw-w64-x86_64-eigen3 git
#
# Usage:
#   ./build.sh                 # clone nextpnr (if absent) into ../../../third_party/nextpnr, then build
#   NEXTPNR=/path ./build.sh   # use an existing nextpnr checkout at $NEXTPNR
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # .../agamemnon/engine/uarch/agrv2k
AGAM_ROOT="$(cd "$HERE/../../../.." && pwd)"                   # repo root (AGaMEMnon/)
NEXTPNR="${NEXTPNR:-$AGAM_ROOT/third_party/nextpnr}"
# PINNED to the known-good upstream commit the agrv2k uarch was built + silicon-validated against
# (YosysHQ/nextpnr @ 2026-06-19). Override with NEXTPNR_PIN=<commit> to try another; empty to float.
NEXTPNR_REMOTE="https://github.com/YosysHQ/nextpnr.git"
NEXTPNR_PIN="${NEXTPNR_PIN:-2b560ad0ccc6e7e93ad8bd6cb0f88f925bbb314b}"   # reproducible build; set empty to float

echo "== agrv2k build =="
echo "   uarch source : $HERE"
echo "   nextpnr tree : $NEXTPNR${NEXTPNR_PIN:+ (pin: $NEXTPNR_PIN)}"

# preflight: toolchain must be on PATH. In MSYS2 use the shell matching your installed packages:
#   MINGW64 for mingw-w64-x86_64-*, UCRT64 for mingw-w64-ucrt-x86_64-*.
for t in cmake git; do
    command -v "$t" >/dev/null || { echo "!! '$t' not on PATH — wrong MSYS2 shell, or deps not installed"; exit 1; }
done
command -v g++ >/dev/null || command -v gcc >/dev/null || { echo "!! no C/C++ compiler on PATH"; exit 1; }

# 1. acquire nextpnr (plain clone for now; convert to a git submodule of AGaMEMnon when we commit)
if [ ! -d "$NEXTPNR/.git" ]; then
    echo "-- cloning nextpnr ..."
    mkdir -p "$(dirname "$NEXTPNR")"
    git clone "$NEXTPNR_REMOTE" "$NEXTPNR"
fi
if [ -n "$NEXTPNR_PIN" ]; then
    # Rebuilding an already pinned checkout is intentionally offline-safe.
    # A copied worktree may retain a host-local origin that is not meaningful
    # inside WSL; fetching it is unnecessary when HEAD is already exact.
    current="$(git -C "$NEXTPNR" rev-parse HEAD 2>/dev/null || true)"
    if [ "$current" != "$NEXTPNR_PIN" ]; then
        git -C "$NEXTPNR" fetch --quiet origin "$NEXTPNR_PIN"
        git -C "$NEXTPNR" checkout --detach "$NEXTPNR_PIN"
    fi
    actual="$(git -C "$NEXTPNR" rev-parse HEAD)"
    [ "$actual" = "$NEXTPNR_PIN" ] \
        || { echo "!! expected nextpnr $NEXTPNR_PIN, got $actual"; exit 1; }
fi
echo "-- nextpnr @ $(git -C "$NEXTPNR" rev-parse --short HEAD) ($(git -C "$NEXTPNR" rev-parse --abbrev-ref HEAD))"
git -C "$NEXTPNR" submodule update --init --recursive

# 2. expose Viaduct routing-delay hooks while preserving generic fallbacks.
# The pinned upstream API forwards estimateDelay but not getWireDelay/getPipDelay;
# keep this as a small reviewable patch rather than an untracked source edit.
TIMING_PATCH="$HERE/nextpnr-viaduct-timing.patch"
if git -C "$NEXTPNR" apply --reverse --check "$TIMING_PATCH" >/dev/null 2>&1; then
    echo "-- Viaduct timing hook patch already applied"
elif git -C "$NEXTPNR" apply --check "$TIMING_PATCH"; then
    git -C "$NEXTPNR" apply "$TIMING_PATCH"
    echo "-- applied Viaduct timing hook patch"
else
    echo "!! nextpnr tree does not match the pinned timing-hook patch"
    exit 1
fi

# 3. overlay our uarch source
DEST="$NEXTPNR/generic/viaduct/agrv2k"
mkdir -p "$DEST"
cp "$HERE/agrv2k.cc" "$DEST/agrv2k.cc"
echo "-- overlaid agrv2k.cc -> $DEST"

# 4. patch generic/CMakeLists.txt SOURCES list (idempotent: add our .cc after the example entry)
CML="$NEXTPNR/generic/CMakeLists.txt"
if grep -q "viaduct/agrv2k/agrv2k.cc" "$CML"; then
    echo "-- CMakeLists already patched"
else
    # insert our source line right after the example uarch source
    sed -i 's#\(\s*\)viaduct/example/example.cc#&\n\1viaduct/agrv2k/agrv2k.cc#' "$CML"
    grep -q "viaduct/agrv2k/agrv2k.cc" "$CML" \
        || { echo "!! failed to patch $CML (the 'viaduct/example/example.cc' line was not found)"; exit 1; }
    echo "-- patched $CML"
fi

# 5. configure + build (generic arch; Python/GUI off to minimise deps)
BUILD="$NEXTPNR/build"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
GEN=(); command -v ninja >/dev/null 2>&1 && GEN=(-G Ninja)
# USE_IPO=OFF disables nextpnr's LTO. Its top-level CMakeLists gates -flto behind USE_IPO, and LTO is
# broken on this mingw/GCC 16 toolchain (cc1plus "out of memory" on heavy TUs despite free RAM + a
# bbasm link error: symbols in discarded sections). Non-LTO -O3 builds fine.
cmake -S "$NEXTPNR" -B "$BUILD" "${GEN[@]}" \
    -DARCH=generic -DCMAKE_BUILD_TYPE=Release -DBUILD_PYTHON=OFF -DBUILD_GUI=OFF \
    -DUSE_IPO=OFF
echo "-- building with -j $JOBS (LTO off; throttle with JOBS=N ./build.sh)"
cmake --build "$BUILD" -j "$JOBS"

BIN="$BUILD/nextpnr-generic.exe"; [ -f "$BIN" ] || BIN="$BUILD/nextpnr-generic"
echo
echo "== done =="
echo "   binary: $BIN"
echo "   verify uarch registered:  \"$BIN\" --uarch '?'   (should list 'agrv2k')"
echo "   graph-load smoke test:"
echo "     \"$BIN\" --uarch agrv2k -o chipdb=<dir with dev_*.csv> --json <design>.json --write <routed>.json"
