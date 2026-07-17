#!/bin/sh
# 03 - flash a fabric .bin to a real AG32 / AGRV2K board and verify, restorably.
#
# =============================================================================================
#  !!  HARDWARE RECIPE -- THIS WRITES THE BOARD'S LOGIC FLASH.  !!
#
#  Nothing in this script runs automatically. Every hardware step below is COMMENTED OUT.
#  Read it, understand each step, then uncomment and run the steps yourself one at a time.
#
#  What it touches and why it is safe:
#    * The fabric .bin lives in the shared SPI flash at 0x80008100. Writing the logic region
#      does NOT touch the MCU code at 0x80000000.
#    * `flash --addr ... --backup` first dumps the WHOLE 256 KB flash to a restore file, then
#      erases only the sector(s) the .bin spans, programs it, and reads it back byte-exact.
#    * To undo, re-flash the whole chip from that full-flash backup (Step 3).
#    * The open flasher drives the flash controller at 0x40001000 directly -- no vendor `agrv`
#      OpenOCD driver, no "Supra" install.
#
#  This is the exact path validated on silicon (2026-06-30): an open LUT edit flashed,
#  read back with exactly one raw byte changed, then restored.
# =============================================================================================
#
# Requires: AG32 board + a CMSIS-DAP probe (the AGM DAP-Link), and an OpenOCD built with
# `riscv -dap` support. Resolution (all optional -- defaults to `openocd` on PATH + the shipped
# agamemnon/openocd/agrv2k.cfg):
#   export AGAMEMNON_OPENOCD="C:/path/to/openocd"    # only if not on PATH / not riscv -dap capable
# Run from the repo root (so `agamemnon` is importable), or after `pip install -e .`.

set -eu

# The fabric .bin to flash. Substitute your own.
BIN="tests/fixtures/blinky.bin"

# The fabric flash address (factory layout). MCU code lives at 0x80000000.
ADDR="0x80008100"

# Where to save the full-chip backup (used both as a safety snapshot and as the restore source).
FULL_BACKUP="full_flash_backup.bin"      # 256 KB whole-chip snapshot

echo "This is a documented recipe. Open the file and run the steps below by hand."
echo "Nothing destructive runs automatically."

# ---------------------------------------------------------------------------------------------
# Step 1 - PROBE (read-only): confirm the board + transport. Expect DEVICE_ID = 0x40200001.
# ---------------------------------------------------------------------------------------------
# python -m agamemnon.cli probe

# ---------------------------------------------------------------------------------------------
# Step 2 - FLASH (writes the logic region, restorably): program "$BIN" at $ADDR.
#          --backup dumps the ENTIRE 256 KB flash to "$FULL_BACKUP" first (so you always have a
#          restore point), then erases the spanned sector(s), programs, and verifies byte-exact.
#          Keep "$FULL_BACKUP" -- step 3 uses it to undo this.
# ---------------------------------------------------------------------------------------------
# python -m agamemnon.cli flash "$BIN" --addr "$ADDR" --backup "$FULL_BACKUP"

# ---------------------------------------------------------------------------------------------
# Step 3 - RESTORE (writes flash back): undo step 2 by re-flashing the whole chip from the
#          full-flash backup. Verifies byte-exact. After this the board is exactly as it was.
# ---------------------------------------------------------------------------------------------
# python -m agamemnon.cli flash "$FULL_BACKUP" --addr 0x80000000
