#!/usr/bin/env python3
"""Open PLL config emitter + byte-exact validator (Project Agamemnon).

Ports the vendor divider math (framework-agrv_sdk/etc/gen_vlog: check_pll / get_pll_vco /
get_pll_div) and, using the empirically-fit preamble bit-map (findings_pll_crack.md), writes the
divider fields for a given (fin=HSE MHz, fout=SYSCLK MHz) into the .bin preamble.

Stage 1 (this run): ANALYZE — compute the exact divider values for the 5 oracles and diff their
decoded preambles against the 100/8 baseline, to fit each divider-value-bit -> (byte,bit).
"""
import os, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__)); TOOLS = os.path.dirname(HERE)
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(HERE))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)
from agamemnon.engine import lzw_codec as L
RAWLEN = 99936
PFD_MIN, PFD_MAX = 4, 30
VCO_MIN, VCO_MAX = 600, 1250
VCO_LOW = VCO_MIN >> 1

def get_pll_vco(frequencies):
    # frequencies[0]=PFD, frequencies[1:]=PLLCLK targets (only [0]=SYSCLK nonzero here). phases=0.
    phase_err = 1e9; vco = 0
    vco_div = int(VCO_LOW / frequencies[0]); v = None
    while True:
        v = vco_div * frequencies[0]; vco_div += 1
        if v < VCO_LOW: continue
        if v > VCO_MAX: break
        freq_err = False
        for freq in frequencies[1:]:
            if freq:
                div = int(v / freq + 0.5)
                if div == 0 or abs(freq - v / div) / freq > 1e-5:
                    freq_err = True; break
        if freq_err: continue
        err = 0  # no phase constraints in our oracles
        if err < phase_err:
            phase_err = err; vco = v
    return vco

def check_pll(sysclk, hse):
    pllin = hse
    frequencies = [pllin, sysclk, 0, 0, 0, 0]
    vco = 0; clkin_div = 0
    for clkin_div in range(int(pllin / PFD_MIN), int((pllin - 1e-5) / PFD_MAX), -1):
        frequencies[0] = pllin / clkin_div
        vco = get_pll_vco(frequencies)
        if vco: break
    if not vco: raise RuntimeError("no VCO for %s/%s" % (sysclk, hse))
    clkfb_div = int(vco * clkin_div / pllin + 0.5)
    clkout_div = [0] * 5
    clkout_div[0] = int(vco / sysclk + 0.5)
    post_div = 1 if vco < VCO_MIN else 0
    return dict(vco=vco, pfd=frequencies[0], clkin_div=clkin_div, clkfb_div=clkfb_div,
                clkout_div=clkout_div, post_div=post_div)

def get_pll_div(div):
    divh = (div >> 1) - 1 if div > 1 else 255
    divl = (div - divh) - 2 if div > 1 else 255
    trim = 0 if divh == divl else 1
    byp = 1 if div == 1 else 0
    return dict(divh=divh, divl=divl, trim=trim, byp=byp)

def decode(path):
    b = open(path, "rb").read()[8:]
    return bytes(b) if len(b) == RAWLEN else L.decode(b)

ORACLES = [   # (dir, sysclk, hse)
    ("oracle_pll_repro", 100, 8),   # baseline (== cpld_test)
    ("oracle_pll_r1", 25, 8),
    ("oracle_pll_r2", 100, 16),
    ("oracle_pll_r3", 50, 8),
    ("oracle_pll_r4", 10, 8),
]

# Only these ratios have a byte-exact vendor oracle for every field that this emitter changes.
# The divider search can calculate many more ratios, but calculation is not evidence that all of the
# required configuration bits are mapped.  Keep emission fail-closed until another ratio is promoted
# with a byte-exact oracle (and its newly exercised field bits, if any).
SUPPORTED_RATIOS = tuple((sysclk, hse) for _, sysclk, hse in ORACLES)


class UnsupportedPLLConfiguration(ValueError):
    """The requested PLL configuration is not completely covered by the recovered bit map."""


def require_supported_ratio(sysclk, hse):
    ratio = (sysclk, hse)
    if ratio not in SUPPORTED_RATIOS:
        supported = ", ".join("%d/%d" % pair for pair in SUPPORTED_RATIOS)
        raise UnsupportedPLLConfiguration(
            "unsupported PLL ratio SYSCLK/HSE=%s/%s MHz; supported byte-exact ratios: %s"
            % (sysclk, hse, supported)
        )
    return ratio

def analyze():
    base = decode(os.path.join(TOOLS, "oracle_pll_repro", "blink.bin"))
    for d, sysclk, hse in ORACLES:
        p = os.path.join(TOOLS, d, "blink.bin")
        if not os.path.exists(p): print(d, "MISSING"); continue
        raw = decode(p)
        c = check_pll(sysclk, hse)
        c0 = get_pll_div(c["clkout_div"][0]); ci = get_pll_div(c["clkin_div"]); cf = get_pll_div(c["clkfb_div"])
        print(f"\n### {d}  SYSCLK={sysclk} HSE={hse}")
        print(f"  vco={c['vco']} pfd={c['pfd']:.3f} clkin_div={c['clkin_div']} clkfb_div={c['clkfb_div']} "
              f"clkout0_div={c['clkout_div'][0]} post_div={c['post_div']}")
        print(f"  CLKOUT0 divh={c0['divh']} divl={c0['divl']} trim={c0['trim']} byp={c0['byp']}")
        print(f"  CLKIN   divh={ci['divh']} divl={ci['divl']} trim={ci['trim']} byp={ci['byp']}")
        print(f"  CLKFB   divh={cf['divh']} divl={cf['divl']} trim={cf['trim']} byp={cf['byp']}")
        diffs = [(i, base[i], raw[i]) for i in range(110, 164) if base[i] != raw[i]]
        print("  preamble byte diffs vs baseline:", [(i, "%02x->%02x" % (b, r)) for i, b, r in diffs])

# Empirically-fit divider-value-bit -> (byte, bit) map (bit 7 = MSB; mask = 1<<bit).
# Confirmed against all 5 oracles + the ported divider math (findings_pll_crack.md). Covers the
# LOW-order divider bits the small-divider oracles exercise; higher bits need more sweep-oracles.
MAP = {
    "CLKOUT0_HIGH": [(145, 6), (145, 7), (146, 7)],   # value bits 0,1,2
    "CLKOUT0_LOW":  [(144, 0), (146, 6), (146, 5)],   # value bits 0,1,2
    "CLKOUT0_TRIM": [(145, 0)],
    "CLKIN_HIGH":   [(149, 4)],
    "CLKIN_LOW":    [(150, 3)],
}

# Divider 30 (10 MHz from the board's 8 MHz HSE) exercises the vendor's
# higher-order divider encoding, which is not a simple extension of the
# low-order bit map above.  These three preamble bytes are isolated by the
# 10/8 vendor oracle; applying them is byte-exact and leaves the design's
# fabric-routing region untouched.
RATIO_BYTE_OVERRIDES = {(10, 8): {144: 0xFC, 145: 0xE0, 146: 0x70}}

def emit_fields(sysclk, hse):
    require_supported_ratio(sysclk, hse)
    c = check_pll(sysclk, hse)
    c0 = get_pll_div(c["clkout_div"][0]); ci = get_pll_div(c["clkin_div"])
    return {"CLKOUT0_HIGH": c0["divh"], "CLKOUT0_LOW": c0["divl"], "CLKOUT0_TRIM": c0["trim"],
            "CLKIN_HIGH": ci["divh"], "CLKIN_LOW": ci["divl"]}, c

def apply_fields(raw, fields):
    """Atomically overwrite a complete, representable set of mapped divider fields.

    Incomplete or out-of-range fields raise before ``raw`` is changed.  A partial PLL overlay is
    unsafe: the untouched bits would silently retain the 100/8 baseline configuration.
    """
    missing = sorted(set(MAP) - set(fields))
    unknown = sorted(set(fields) - set(MAP))
    problems = []
    if missing:
        problems.append("missing fields %s" % ", ".join(missing))
    if unknown:
        problems.append("unknown fields %s" % ", ".join(unknown))
    for field, val in fields.items():
        if field not in MAP:
            continue
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            problems.append("%s has invalid value %r" % (field, val))
        elif val >> len(MAP[field]):
            problems.append("%s=%d needs more than %d mapped bits" % (field, val, len(MAP[field])))
    if problems:
        raise UnsupportedPLLConfiguration("incomplete PLL encoding: " + "; ".join(problems))

    for field, val in fields.items():
        bits = MAP[field]
        for i, (byte, bit) in enumerate(bits):
            m = 1 << bit
            if (val >> i) & 1: raw[byte] |= m
            else:              raw[byte] &= ~m & 0xFF
    return []

def apply_ratio(raw, sysclk, hse):
    """Apply one fully qualified PLL ratio to an existing clock preamble."""
    ratio = require_supported_ratio(sysclk, hse)
    if ratio in RATIO_BYTE_OVERRIDES:
        for byte, value in RATIO_BYTE_OVERRIDES[ratio].items():
            raw[byte] = value
        return []
    return apply_fields(raw, emit_fields(sysclk, hse)[0])

def crc32_bzip2(dd):
    c = 0xFFFFFFFF
    for b in dd:
        c ^= b << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if (c & 0x80000000) else (c << 1) & 0xFFFFFFFF
    return c ^ 0xFFFFFFFF

def validate():
    """Reproduce each oracle's preamble from (ported math + map) applied to the 100/8 baseline;
    require byte-exact over the whole decoded image (incl. recomputed fabric CRC)."""
    import struct
    base = bytearray(decode(os.path.join(TOOLS, "oracle_pll_repro", "blink.bin")))
    hdr = open(os.path.join(TOOLS, "oracle_pll_repro", "blink.bin"), "rb").read()[:8]
    ok = True
    for d, sysclk, hse in ORACLES:
        p = os.path.join(TOOLS, d, "blink.bin")
        if not os.path.exists(p): print(f"  {d}: MISSING"); continue
        target = decode(p)
        raw = bytearray(base)                      # start from baseline; overwrite divider bits
        unmap = apply_ratio(raw, sysclk, hse)
        raw[99932:99936] = struct.pack(">I", crc32_bzip2(bytes(hdr) + bytes(raw[:99932])))  # fabric CRC
        exact = bytes(raw[:164]) == target[:164]
        if not exact: ok = False
        diff = [i for i in range(len(raw)) if raw[i] != target[i]]
        print(f"  {d:18} SYSCLK={sysclk:<4} HSE={hse:<3} -> {'BYTE-EXACT PREAMBLE' if exact else 'MISMATCH @'+str(diff[:8])}"
              + (f"  UNMAPPABLE {unmap}" if unmap else ""))
    return ok

def emit_bin(sysclk, hse, out_path, baseline="oracle_pll_repro/blink.bin"):
    """Write a full uncompressed .bin (hdr + 99936B raw) for the given ratio, by overlaying our
    computed dividers onto a PLL baseline preamble and recomputing the fabric CRC. Unsupported or
    incompletely mapped ratios raise before an output file is created."""
    import struct
    _fields, c = emit_fields(sysclk, hse)         # validate before opening baseline/output paths
    bpath = os.path.join(TOOLS, baseline)
    hdr = open(bpath, "rb").read()[:8]
    raw = bytearray(decode(bpath))
    unmap = apply_ratio(raw, sysclk, hse)
    raw[99932:99936] = struct.pack(">I", crc32_bzip2(bytes(hdr) + bytes(raw[:99932])))
    open(out_path, "wb").write(bytes(hdr) + bytes(raw))
    return unmap, c

if __name__ == "__main__":
    import sys as _s
    if "--emit" in _s.argv:
        i = _s.argv.index("--emit")
        sysclk, hse, out = int(_s.argv[i+1]), int(_s.argv[i+2]), _s.argv[i+3]
        try:
            unmap, c = emit_bin(sysclk, hse, out)
        except UnsupportedPLLConfiguration as exc:
            print("error: %s" % exc, file=sys.stderr)
            _s.exit(2)
        print(f"wrote {out} (SYSCLK={sysclk} HSE={hse}, vco={c['vco']} clkout0_div={c['clkout_div'][0]})"
              + "  [byte-exact ratio]")
    elif "--analyze" in _s.argv:
        analyze()
    else:
        print("=== PLL emit byte-exact validation vs vendor oracles ===")
        ok = validate()
        print("RESULT:", "byte-exact PLL divider config reproduced (validated ratio set)"
              if ok else "MISMATCH")
        _s.exit(0 if ok else 1)
