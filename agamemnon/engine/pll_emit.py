#!/usr/bin/env python3
"""Open PLL config emitter (Project AGaMEMnon).

Ports the vendor divider math (framework-agrv_sdk/etc/gen_vlog: check_pll / get_pll_vco /
get_pll_div) and, using the empirically-fit preamble bit-map (findings_pll_crack.md), writes the
divider fields for a given (fin=HSE MHz, fout=SYSCLK MHz) into the .bin preamble.

Runtime use (bitgen_seq): emit_fields(sysclk, hse) computes the divider fields; apply_fields()
overlays the mapped bits onto a mutable raw preamble; the default (SYSCLK=100, HSE=8) leaves the
proven baseline blob untouched. The bit-map (MAP) is byte-exact vs the vendor divider math.
"""
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
        err = 0  # no phase constraints
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

# Empirically-fit divider-value-bit -> (byte, bit) map (bit 7 = MSB; mask = 1<<bit).
# Confirmed against the ported divider math (findings_pll_crack.md). Covers the LOW-order divider
# bits the small-divider ratios exercise; higher bits need more sweep points.
MAP = {
    "CLKOUT0_HIGH": [(145, 6), (145, 7), (146, 7)],   # value bits 0,1,2
    "CLKOUT0_LOW":  [(144, 0), (146, 6), (146, 5)],   # value bits 0,1,2
    "CLKOUT0_TRIM": [(145, 0)],
    "CLKIN_HIGH":   [(149, 4)],
    "CLKIN_LOW":    [(150, 3)],
}

def emit_fields(sysclk, hse):
    c = check_pll(sysclk, hse)
    c0 = get_pll_div(c["clkout_div"][0]); ci = get_pll_div(c["clkin_div"])
    return {"CLKOUT0_HIGH": c0["divh"], "CLKOUT0_LOW": c0["divl"], "CLKOUT0_TRIM": c0["trim"],
            "CLKIN_HIGH": ci["divh"], "CLKIN_LOW": ci["divl"]}, c

def apply_fields(raw, fields):
    """Overwrite the mapped divider bits in a mutable raw preamble. Returns list of unmappable
    (field, value) whose value needs more bits than the map covers."""
    unmappable = []
    for field, val in fields.items():
        bits = MAP[field]
        if val >> len(bits):
            unmappable.append((field, val));
        for i, (byte, bit) in enumerate(bits):
            m = 1 << bit
            if (val >> i) & 1: raw[byte] |= m
            else:              raw[byte] &= ~m & 0xFF
    return unmappable

def crc32_bzip2(dd):
    c = 0xFFFFFFFF
    for b in dd:
        c ^= b << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if (c & 0x80000000) else (c << 1) & 0xFFFFFFFF
    return c ^ 0xFFFFFFFF

if __name__ == "__main__":
    import sys as _s
    sysclk = int(_s.argv[1]) if len(_s.argv) > 1 else 100
    hse = int(_s.argv[2]) if len(_s.argv) > 2 else 8
    fields, c = emit_fields(sysclk, hse)
    print("SYSCLK=%d HSE=%d -> vco=%d clkout0_div=%d clkin_div=%d"
          % (sysclk, hse, c["vco"], c["clkout_div"][0], c["clkin_div"]))
    print("  fields:", fields)
