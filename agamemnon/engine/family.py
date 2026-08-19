#!/usr/bin/env python3
"""family.py -- AG32 FAMILY (part-number) awareness for the AGRV2K open toolchain.

``device.py`` models the four AGRV2K *package* variants (Q32/L48/L64/L100): the
front-end pin-legality gate the vendor tools apply.  This module sits one layer
above it and models the seven AG32 *part numbers* the vendor actually ships.
Several parts share one package (three of the seven are LQFP-100) but differ
in flash size, PSRAM, and ADC/DAC channel counts -- the "surround" the family
coverage plan (``AG32-Docs/docs/GOAL_AG32_FAMILY_COVERAGE.md``) talks about.

The premise (do not re-litigate here; see that plan): every part carries the
*same* AGRV2K fabric (2112 LUT4 + 2112 FF, 4 BRAM, 1 PLL, 5 global clocks) and
the *same* RV32IMAFC RISC-V core + boot ROM. Only the package/flash/PSRAM/
analog surround differs per part. A fabric-logic capability qualified on one
part's silicon therefore carries to every other part as build-supported --
but a silicon claim (this exact part, this exact board) never transfers.

Source of truth: ``AG32-Docs/tools/AG32_RefManual.txt`` Section 1.2 ("Features
and peripheral counts"), part table starting near line 751. Transcribed
verbatim below; regenerate by hand against that table if a datasheet
correction ever lands (there is no machine-readable vendor source for this
table, unlike ``device.py``'s CHIP_INFO which mirrors ``gen_vlog``).
"""
from __future__ import annotations

from collections import namedtuple
import os

from agamemnon.engine import device as _device


# One shared statement of the fabric/core every part carries identically. Kept
# as data (not prose duplicated per part) so the "shared, not per-part" claim
# can never accidentally drift between entries.
SHARED_FABRIC = "AGRV2K: 2112 LUT4 + 2112 FF, 4 BRAM9K, 1 PLL, 5 global clocks, 22x13 tile grid"
SHARED_CORE = "RV32IMAFC RISC-V core, max 248 MHz, misa 0x40801125"
SHARED_BOOT_ROM = "Shared mask boot ROM (byte-identical dumps confirmed across two physical boards)"

# Package pin-count suffix -> AGRV2K package/device id (device.py's PACKAGES).
PACKAGE_FOR_SUFFIX = {
    "K": "AGRV2KQ32",   # QFN32
    "C": "AGRV2KL48",   # LQFP48
    "R": "AGRV2KL64",   # LQFP64
    "V": "AGRV2KL100",  # LQFP100
}

FamilyPart = namedtuple("FamilyPart", [
    "part_number",       # e.g. "AG32VF303CCT6"
    "package_name",      # human package name, e.g. "LQFP48"
    "device_id",         # AGRV2K package/device id (device.py), e.g. "AGRV2KL48"
    "flash_bytes",
    "sram_bytes",
    "psram_bytes",        # 0 if none
    "adc_units",
    "adc_channels",
    "dac_units",
    "dac_channels",
    "comparators",
    "max_cpu_hz",
    "has_qualified_board",  # a physical board with recorded evidence exists
    "board_note",
])

_MHZ = 1_000_000
_KIB = 1024
_MIB = 1024 * 1024

# Transcribed verbatim from AG32_RefManual.txt Sec 1.2 (part table, ~line 751).
# Column order in the datasheet: KCU6, CCT6, VCT6, RCT6, RGT6, VGT6 (407),
# VGT6 (VH407). Flash/SRAM/timers/SPI/I2C/UART/USB/CAN/comparators/max-freq/
# voltage are uniform across the family; only package, flash size, PSRAM, and
# ADC/DAC channel counts vary.
PARTS = {
    "AG32VF303KCU6": FamilyPart(
        part_number="AG32VF303KCU6", package_name="QFN32", device_id="AGRV2KQ32",
        flash_bytes=256 * _KIB, sram_bytes=128 * _KIB, psram_bytes=0,
        adc_units=3, adc_channels=9, dac_units=2, dac_channels=2, comparators=2,
        max_cpu_hz=248 * _MHZ, has_qualified_board=False,
        board_note="No physical unit on hand; recovered package data only.",
    ),
    "AG32VF303CCT6": FamilyPart(
        part_number="AG32VF303CCT6", package_name="LQFP48", device_id="AGRV2KL48",
        flash_bytes=256 * _KIB, sram_bytes=128 * _KIB, psram_bytes=0,
        adc_units=3, adc_channels=10, dac_units=2, dac_channels=2, comparators=2,
        max_cpu_hz=248 * _MHZ, has_qualified_board=True,
        board_note="The silicon-qualified reference dev board (agamemnon/sdk/boards/ag32vf303-l48.toml).",
    ),
    "AG32VF303VCT6": FamilyPart(
        part_number="AG32VF303VCT6", package_name="LQFP100", device_id="AGRV2KL100",
        flash_bytes=256 * _KIB, sram_bytes=128 * _KIB, psram_bytes=0,
        adc_units=3, adc_channels=16, dac_units=2, dac_channels=2, comparators=2,
        max_cpu_hz=248 * _MHZ, has_qualified_board=False,
        board_note="No physical unit on hand; recovered package data only.",
    ),
    "AG32VH303RCT6": FamilyPart(
        part_number="AG32VH303RCT6", package_name="LQFP64", device_id="AGRV2KL64",
        flash_bytes=256 * _KIB, sram_bytes=128 * _KIB, psram_bytes=8 * _MIB,
        adc_units=3, adc_channels=11, dac_units=1, dac_channels=1, comparators=2,
        max_cpu_hz=248 * _MHZ, has_qualified_board=False,
        board_note=(
            "No physical unit on hand. Note: a different LQFP64 part "
            "(AG32VF407RGT6, no PSRAM) has an in-progress desk/silicon bring-up "
            "(qualification/l64_bringup_evidence.jsonl); that evidence is "
            "package-level (AGRV2KL64), not this part, and does not exercise "
            "PSRAM."
        ),
    ),
    "AG32VF407RGT6": FamilyPart(
        part_number="AG32VF407RGT6", package_name="LQFP64", device_id="AGRV2KL64",
        flash_bytes=1024 * _KIB, sram_bytes=128 * _KIB, psram_bytes=0,
        adc_units=3, adc_channels=16, dac_units=2, dac_channels=2, comparators=2,
        max_cpu_hz=248 * _MHZ, has_qualified_board=False,
        board_note=(
            "First physical unit of this package under bring-up; see "
            "qualification/l64_bringup_evidence.jsonl. Pad-free config-accept "
            "and an AHB read/write transaction have been observed on real "
            "silicon, but investigation is open (an AHB read-value mismatch is "
            "unresolved) -- this is evidence-in-progress, not a qualified claim."
        ),
    ),
    "AG32VF407VGT6": FamilyPart(
        part_number="AG32VF407VGT6", package_name="LQFP100", device_id="AGRV2KL100",
        flash_bytes=1024 * _KIB, sram_bytes=128 * _KIB, psram_bytes=0,
        adc_units=3, adc_channels=16, dac_units=2, dac_channels=2, comparators=2,
        max_cpu_hz=248 * _MHZ, has_qualified_board=True,
        board_note=(
            "Brian's second physical board (per AG32-Docs memory); no "
            "AGaMEMnon board profile or qualification evidence has been "
            "recorded for it yet -- has_qualified_board marks hardware "
            "existence, not a silicon qualification record."
        ),
    ),
    "AG32VH407VGT6": FamilyPart(
        part_number="AG32VH407VGT6", package_name="LQFP100", device_id="AGRV2KL100",
        flash_bytes=1024 * _KIB, sram_bytes=128 * _KIB, psram_bytes=8 * _MIB,
        adc_units=3, adc_channels=16, dac_units=1, dac_channels=1, comparators=2,
        max_cpu_hz=248 * _MHZ, has_qualified_board=False,
        board_note="No physical unit on hand; recovered package data only.",
    ),
}

PART_NAMES = tuple(sorted(PARTS))

# The part whose package is the default AGRV2K device (device.DEFAULT_DEVICE).
# Keeping this derived (not hardcoded twice) means a future default-device
# change cannot silently desync from the family table.
DEFAULT_PART = "AG32VF303CCT6"


def get_part(name):
    """Return the :class:`FamilyPart` for a canonical part number."""
    try:
        return PARTS[name]
    except KeyError:
        raise KeyError(
            "Unknown AG32 family part %r (known: %s)" % (name, ", ".join(PART_NAMES))
        ) from None


def parts_for_package(device_id):
    """Return the canonical part numbers that share one AGRV2K package/device id."""
    return tuple(sorted(name for name, part in PARTS.items() if part.device_id == device_id))


def part_from_env(environ=None):
    """Return the FamilyPart selected by env AGAMEMNON_PART (default DEFAULT_PART)."""
    environ = os.environ if environ is None else environ
    return get_part(environ.get("AGAMEMNON_PART") or DEFAULT_PART)


def validate_family_registry():
    """Cross-check the family table against device.py; raise on any mismatch.

    This is the fail-closed guard against the table drifting from the package
    data it depends on: every part must name a real AGRV2K package, and every
    package device.py knows about must be reachable by at least one part.
    """
    if set(PARTS) != set(PART_NAMES):
        raise ValueError("PART_NAMES must exactly match PARTS")
    seen_devices = set()
    for name, part in PARTS.items():
        if part.part_number != name:
            raise ValueError("part_number must match its PARTS key for %s" % name)
        if part.device_id not in _device.PACKAGES:
            raise ValueError("%s: unknown AGRV2K device_id %r" % (name, part.device_id))
        expected_pkg = {
            "AGRV2KQ32": "QFN32", "AGRV2KL48": "LQFP48",
            "AGRV2KL64": "LQFP64", "AGRV2KL100": "LQFP100",
        }[part.device_id]
        if part.package_name != expected_pkg:
            raise ValueError(
                "%s: package_name %r does not match device_id %r (expected %r)"
                % (name, part.package_name, part.device_id, expected_pkg)
            )
        if part.flash_bytes <= 0 or part.sram_bytes <= 0:
            raise ValueError("%s: flash/SRAM size must be positive" % name)
        if part.psram_bytes < 0:
            raise ValueError("%s: psram_bytes must not be negative" % name)
        if part.adc_units <= 0 or part.adc_channels <= 0:
            raise ValueError("%s: ADC unit/channel counts must be positive" % name)
        if part.dac_units <= 0 or part.dac_channels <= 0:
            raise ValueError("%s: DAC unit/channel counts must be positive" % name)
        seen_devices.add(part.device_id)
    missing = set(_device.PACKAGES) - seen_devices
    if missing:
        raise ValueError("no family part names AGRV2K package(s): %s" % ", ".join(sorted(missing)))
    if PARTS[DEFAULT_PART].device_id != _device.DEFAULT_DEVICE:
        raise ValueError(
            "DEFAULT_PART's package %r must match device.DEFAULT_DEVICE %r"
            % (PARTS[DEFAULT_PART].device_id, _device.DEFAULT_DEVICE)
        )


validate_family_registry()


def manifest():
    """Return a stable, machine-readable snapshot of the family registry."""
    return {
        "schema": 1,
        "default_part": DEFAULT_PART,
        "shared": {
            "fabric": SHARED_FABRIC,
            "core": SHARED_CORE,
            "boot_rom": SHARED_BOOT_ROM,
        },
        "parts": [
            {
                "part_number": part.part_number,
                "package_name": part.package_name,
                "device_id": part.device_id,
                "package_pin_count": _device.get_device(part.device_id).package_pin_count,
                "bond_map_file": _device.BOND_MAP_FILES[part.device_id],
                "bond_map_qualification": _device.BOND_MAP_QUALIFICATION[part.device_id],
                "flash_bytes": part.flash_bytes,
                "sram_bytes": part.sram_bytes,
                "psram_bytes": part.psram_bytes,
                "adc_units": part.adc_units,
                "adc_channels": part.adc_channels,
                "dac_units": part.dac_units,
                "dac_channels": part.dac_channels,
                "comparators": part.comparators,
                "max_cpu_hz": part.max_cpu_hz,
                "has_qualified_board": part.has_qualified_board,
                "board_note": part.board_note,
            }
            for name, part in sorted(PARTS.items())
        ],
    }


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="AG32 family part registry.")
    ap.add_argument("-p", "--part", default=DEFAULT_PART)
    ap.add_argument("-l", "--list", action="store_true", help="List all family parts")
    ap.add_argument("--json", action="store_true", help="Emit the manifest as JSON")
    a = ap.parse_args()
    if a.json:
        print(json.dumps(manifest(), indent=2, sort_keys=True))
    elif a.list:
        for name in PART_NAMES:
            part = PARTS[name]
            print("  %-16s %-8s device=%-11s flash=%4dK psram=%dM adc=%d/%d dac=%d/%d board=%s"
                  % (part.part_number, part.package_name, part.device_id,
                     part.flash_bytes // _KIB, part.psram_bytes // _MIB,
                     part.adc_units, part.adc_channels, part.dac_units, part.dac_channels,
                     "yes" if part.has_qualified_board else "no"))
    else:
        print(get_part(a.part))
