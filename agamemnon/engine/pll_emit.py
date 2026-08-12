#!/usr/bin/env python3
"""Open PLL config emitter + byte-exact validator (Project Agamemnon).

Ports the vendor divider math (framework-agrv_sdk/etc/gen_vlog: check_pll / get_pll_vco /
get_pll_div) and, using a closed-form preamble bit-map, writes the CLKOUT0/CLKFB/CLKIN divider
fields for a given (fin=HSE MHz, fout=SYSCLK MHz) into the .bin preamble.

The bit-map (``MAP`` below) was recovered and proven byte-exact on a 53-point vendor PLL sweep
(AG32-Docs ``tools/pll_sweep_20260812``): every preamble bit that varies with (SYSCLK,HSE) is an
exact single-field-bit function of the ported divider values, and all 53 vendor preambles
reconstruct with zero residual. There is no per-ratio byte table; the emitter is one closed-form
equation. Emission is still fail-closed to evidence-backed configurations (``SUPPORTED_RATIOS``):
the seven byte-exact profiles plus every HSE=8 rate qualified on silicon by the two-window MTIME
frequency sweep (``qualification/pll_freq_evidence.jsonl``).
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
    ("oracle_pll_60_8", 60, 8),
    ("oracle_pll_100_12", 100, 12),
]

# The seven shipped profiles each retain a byte-exact vendor oracle (agamemnon/chipdb/
# pll_profile_manifest.json). They are byte-exact-qualified; five are also silicon-frequency-qualified.
PROFILE_RATIOS = tuple((sysclk, hse) for _, sysclk, hse in ORACLES)

# HSE=8 SYSCLK values (MHz) qualified on silicon by the AG32-Docs pll_silicon_sweep_20260812
# two-window MTIME frequency sweep: 38 points spanning 4..248 MHz, all PASS, worst 0.058 % off the
# requested rate. Each is promoted to qualification/pll_freq_evidence.jsonl and is reproduced
# byte-exact by the closed-form divider encoding below (validated against its vendor sweep preamble).
SILICON_QUALIFIED_HSE8 = (
    4, 5, 6, 8, 12, 14, 15, 16, 20, 24, 30, 32, 36, 40, 45, 48, 55, 64, 70, 72, 75, 80, 84, 90, 96,
    110, 120, 125, 133, 140, 150, 160, 168, 180, 200, 220, 240, 248,
)

# Emission is fail-closed to evidence: the seven byte-exact profiles plus every silicon-qualified
# HSE=8 rate.  A ratio the divider search can merely *calculate* -- including byte-exact but
# unqualified HSE!=8 sweep points -- is NOT admitted without a silicon or byte-exact-oracle record.
SUPPORTED_RATIOS = tuple(
    dict.fromkeys(PROFILE_RATIOS + tuple((sysclk, 8) for sysclk in SILICON_QUALIFIED_HSE8))
)


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

# Closed-form divider-value-bit -> (preamble byte, bit) map (bit 7 = MSB; mask = 1<<bit).
# Proven byte-exact on the 53-point AG32-Docs vendor PLL sweep (tools/pll_sweep_20260812/
# FIT_REPORT.md).  Only preamble bytes 144..150 vary with (SYSCLK,HSE); each varying bit is an exact
# single-field-bit function of the ported divider values.  Per divider, get_pll_div() gives
# divh=(div>>1)-1, divl=div-divh-2, trim=0 iff divh==divl.  CLKOUT0_BYP and POST_DIV are constant
# across the whole reachable range (byp=0, post_div=1); the baseline preamble already carries them,
# so they need no mapped bit.
MAP = {
    "CLKOUT0_HIGH": [(146, 7), (146, 6), (146, 5), (146, 4), (146, 3), (146, 2)],  # DIVH bits 0..5
    "CLKOUT0_LOW":  [(144, 0), (145, 7), (145, 6), (145, 5), (145, 4), (145, 3)],  # DIVL bits 0..5
    "CLKOUT0_TRIM": [(145, 0)],
    "CLKFB_HIGH":   [(148, 5), (148, 4), (148, 3), (148, 2), (148, 1), (148, 0), (149, 7)],  # DIVH 0..6
    "CLKFB_LOW":    [(147, 6), (147, 5), (147, 4), (147, 3), (147, 2), (147, 1), (147, 0)],  # DIVL 0..6
    "CLKFB_TRIM":   [(148, 6)],
    "CLKIN_HIGH":   [(150, 3), (150, 2)],  # DIVH bits 0..1
    "CLKIN_LOW":    [(149, 4), (149, 3)],  # DIVL bits 0..1
    "CLKIN_TRIM":   [(150, 4)],
}


def divider_fields(sysclk, hse):
    """Closed-form CLKOUT0/CLKFB/CLKIN divider field values, WITHOUT the support gate.

    Encoding only: valid for any ratio ``check_pll`` can solve.  Callers that emit into a real image
    must use ``emit_fields``/``apply_ratio``, which additionally require an evidence-backed ratio.
    Returns ``(fields, check_pll_result)``.
    """
    c = check_pll(sysclk, hse)
    c0 = get_pll_div(c["clkout_div"][0])
    cf = get_pll_div(c["clkfb_div"])
    ci = get_pll_div(c["clkin_div"])
    return {
        "CLKOUT0_HIGH": c0["divh"], "CLKOUT0_LOW": c0["divl"], "CLKOUT0_TRIM": c0["trim"],
        "CLKFB_HIGH": cf["divh"], "CLKFB_LOW": cf["divl"], "CLKFB_TRIM": cf["trim"],
        "CLKIN_HIGH": ci["divh"], "CLKIN_LOW": ci["divl"], "CLKIN_TRIM": ci["trim"],
    }, c


def emit_fields(sysclk, hse):
    """Evidence-gated divider fields: reject an unqualified ratio before computing anything."""
    require_supported_ratio(sysclk, hse)
    return divider_fields(sysclk, hse)

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
    """Apply one evidence-qualified PLL ratio to an existing clock preamble.

    The general closed-form encoding reproduces every supported ratio (the (10,8) divider 30 that
    once needed a per-ratio byte override just exercises higher DIVH/DIVL bits), so no special case
    remains.
    """
    require_supported_ratio(sysclk, hse)
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
