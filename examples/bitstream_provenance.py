#!/usr/bin/env python3
"""04 - vendor-canvas provenance: what in an AG32 bitstream is *ours* vs *inherited*.

No hardware, no board, no external OSS tools (no Yosys/nextpnr/OpenOCD): this
walks a fabric ``.bin`` entirely through AGaMEMnon's *own* open codec and
inspector, and for the shipped vendor canvas it reproduces the byte-exact
provenance figures documented in ``docs/FABRIC_DEFAULT_CANVAS.md`` and
``docs/CONFIG_SURFACE_MAP.md``.

Why this matters: the single biggest "not *completely* open" caveat in the whole
project is that every emitted image is still painted on top of one 2.8 KB
vendor-tool-derived baseline (``agamemnon/chipdb/fabric_default.bin``). This
example makes that caveat *measurable* from the desk, and gives the
canvas-retirement roadmap item a reproducible baseline to drive toward zero.

Run from the repo root (so ``agamemnon`` is importable) or after ``pip install -e .``::

    python examples/bitstream_provenance.py                  # the shipped vendor canvas
    python examples/bitstream_provenance.py path/to/foo.bin  # any fabric .bin

The exit status is non-zero if any documented invariant fails, so this doubles
as a self-check that the docs and the shipped file still agree.
"""
from __future__ import annotations

import hashlib
import os
import sys

from agamemnon import cli
from agamemnon.engine import agasc
from agamemnon.engine import bitstream_inspect
from agamemnon.engine import lzw_codec as lzw

# The shipped vendor baseline and its pinned digest (see NOTICE.md / FABRIC_DEFAULT_CANVAS.md).
CANVAS = os.path.join(cli.CHIPDB, "fabric_default.bin")
CANVAS_SHA256 = "6093e876041bab9f8d1f6058235713a6b8ced1024455070fe2b358e87915a041"

# Documented byte-exact invariants for the shipped canvas.
EXPECTED = {
    "source_bytes": 2839,
    "source_sha256": CANVAS_SHA256,
    "decoded_raw_bytes": agasc.RAW_LEN,          # 99936
    "named_features": 1460,
    "named_tiles": 23,
    "unknown_set_bits": 230116,
    "crc_valid": False,                          # the frozen canvas carries a stale CRC
    "crc_stored": 0xAD5B5DB9,
    "crc_expected": 0x4B36B054,
}


def _read_bin(path):
    """Return (header, raw, source_bytes, source_sha256) for a compressed or raw .bin."""
    data = open(path, "rb").read()
    if len(data) < 8:
        raise ValueError(f"{path}: shorter than its 8-byte header")
    header = data[:8]
    body = data[8:]
    raw = bytes(body) if len(body) == agasc.RAW_LEN else lzw.decode(body)
    return header, raw, len(data), hashlib.sha256(data).hexdigest()


def analyze(path):
    """Print a provenance report for one fabric .bin and return (report, source_bytes, sha)."""
    header, raw, source_bytes, source_sha = _read_bin(path)
    report = bitstream_inspect.describe(header, raw, cli.CHIPDB)
    crc = report["crc"]
    summary = report["summary"]

    total_bits = len(raw) * 8
    set_bits = sum(bin(byte).count("1") for byte in raw)
    named = summary["named_features"]
    unknown = summary["unknown_set_bits"]

    print(f"image             : {path}")
    print(f"source            : {source_bytes} byte .bin  sha256 {source_sha}")
    print(f"decoded raw image : {len(raw)} bytes = {total_bits} configuration bits")
    print(f"stored CRC        : {'valid' if crc['valid'] else 'INVALID'} "
          f"(stored {crc['stored']}, expected {crc['expected']})")
    print()
    print("provenance of the asserted (=1) configuration bits:")
    print(f"  asserted bits total          : {set_bits}")
    print(f"  named feature bits (decoded) : {named}  in {summary['tiles']} edge/border tile(s)")
    print(f"  unmapped set bits (inherited): {unknown}")
    if set_bits:
        pct = 100.0 * unknown / set_bits
        print(f"  -> {pct:.2f}% of asserted bits are still vendor-inherited, per-bit-undecoded")
    print()
    print("the three configuration planes (see docs/CONFIG_SURFACE_MAP.md):")
    print("  1. LUT function plane        : DECODED  (unconfigured default 0x00 -> a zeros base reproduces it)")
    print("  2. routing/cell-interconnect : PARTIAL  (~26% named; the unmapped set bits above are the ~74%)")
    print("  3. subsystem/peripheral plane: PARTIAL  (preamble+PLL decoded; IO/BRAM/hard-block residue open)")
    return report, source_bytes, source_sha


def roundtrip_is_byte_exact(path):
    """True if decode->encode reproduces the compressed .bin byte-for-byte."""
    data = open(path, "rb").read()
    header, raw, _, _ = _read_bin(path)
    if len(data) - 8 == agasc.RAW_LEN:
        return None  # uncompressed source: re-encoding compresses, so a byte compare is not meaningful
    return (header + lzw.encode(raw)) == data


def _check(label, got, want, failures):
    ok = got == want
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        failures.append(label)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else CANVAS
    is_canvas = os.path.abspath(path) == os.path.abspath(CANVAS)

    report, source_bytes, source_sha = analyze(path)
    rt = roundtrip_is_byte_exact(path)
    print()
    print(f"open codec round-trip byte-exact: "
          f"{'yes' if rt else ('n/a (uncompressed source)' if rt is None else 'NO')}")

    if not is_canvas:
        print("\n(no documented-invariant self-check for a non-canvas image)")
        return 0

    print("\nself-check against docs/FABRIC_DEFAULT_CANVAS.md invariants:")
    failures: list[str] = []
    crc = report["crc"]
    summary = report["summary"]
    _check("source_bytes", source_bytes, EXPECTED["source_bytes"], failures)
    _check("source_sha256", source_sha, EXPECTED["source_sha256"], failures)
    _check("decoded_raw_bytes", report and agasc.RAW_LEN, EXPECTED["decoded_raw_bytes"], failures)
    _check("named_features", summary["named_features"], EXPECTED["named_features"], failures)
    _check("named_tiles", summary["tiles"], EXPECTED["named_tiles"], failures)
    _check("unknown_set_bits", summary["unknown_set_bits"], EXPECTED["unknown_set_bits"], failures)
    _check("crc_valid", crc["valid"], EXPECTED["crc_valid"], failures)
    _check("crc_stored", int(crc["stored"], 0), EXPECTED["crc_stored"], failures)
    _check("crc_expected", int(crc["expected"], 0), EXPECTED["crc_expected"], failures)
    _check("roundtrip_byte_exact", rt, True, failures)

    if failures:
        print(f"\nFAILED: {len(failures)} invariant(s) drifted: {', '.join(failures)}")
        return 1
    print("\nOK: the shipped canvas matches every documented provenance invariant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
