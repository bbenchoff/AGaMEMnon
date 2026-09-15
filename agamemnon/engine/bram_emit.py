#!/usr/bin/env python3
"""Open BRAM config emitter + byte-exact validator (Project Agamemnon).

Given a BRAM9K instance (tile x,y; port width; clkmode; port enables; 9216-bit INIT_VAL),
produce the exact (byte,mask) config-bit sets, using the cracked encoding
(findings_bram_crack.md) and the located cell positions in pips_bram_pll.csv:

  INIT_VAL : word w bit b (LSB-first) -> mux=INIT_VAL, sel = w*18 + b; SET iff mem bit == 1.
  CFG_DWSEL_A/_B[4:0] : PORTx_WIDTH verbatim, bit k -> sel k (thermometer width code).
  CFG_CLKMODE[1:0]    : CLKMODE binary, LSB-first (bit k -> sel k).
  CFG_PORTx_{CLKIN,CLKOUT,RSTIN,RSTOUT}_EN : 1-bit active-high at sel 0.

VALIDATION: reproduce the two vendor oracles (oracle_bram/bram.bin x18, bramp.bin x9) and
assert the emitted BRAM-family bit-set EXACTLY equals what af.exe emitted (byte-exact over the
whole BRAM config surface). No vendor bytes are copied — we compute from the params alone.
"""
import os, sys, csv, re, collections
HERE = os.path.dirname(os.path.abspath(__file__)); TOOLS = os.path.dirname(HERE)
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(HERE))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)
from agamemnon.engine import lzw_codec as L
PIPS = os.path.join(HERE, "pips_bram_pll.csv")
RAWLEN = 99936

# Direct ALTA_BRAM9K modes intentionally lowered by the open flow.  The
# vendor backend accepts arbitrary five-bit values, including model-invalid
# encodings, so this boundary must be enforced before any configuration bits
# are emitted.  The model's 10000 x36 candidate is deliberately absent: the
# vendor wrapper implements 32/36-bit memories with two 18-bit halves and a
# separate packed-mode control that has not been recovered here.
SUPPORTED_DIRECT_WIDTH_CODES = frozenset((
    0b00000,  # x18 (also the unused/default port spelling)
    0b01000,  # x9
    0b01100,  # x4
    0b01110,  # x2
    0b01111,  # x1
))
EXPERIMENTAL_DIRECT_WIDTH_CODES = frozenset((0b10000,))

# B4 admits these configuration encodings only.  It does not establish the
# corresponding memory behavior, so the feature layer may enable them only
# behind the explicit experimental-strict policy option.
EXPERIMENTAL_FIELDS = {
    "PACKEDMODE": ("CFG_PACKEDMODE", 1, frozenset((0, 1))),
    "DLYTIME": ("CFG_DLYTIME", 2, frozenset(range(4))),
    "PORTA_OUTREG": ("CFG_SELOUT_A", 1, frozenset((0, 1))),
    "PORTB_OUTREG": ("CFG_SELOUT_B", 1, frozenset((0, 1))),
    "PORTA_WRITETHRU": ("CFG_SEL_WRITHU_A", 1, frozenset((0, 1))),
    "PORTB_WRITETHRU": ("CFG_SEL_WRITHU_B", 1, frozenset((0, 1))),
    # 2'b11 was not an independently admitted row; composition is not
    # inferred from the two admitted one-hot encodings.
    "RSEN_DLY": ("CFG_RSEN_DLY", 2, frozenset((0, 1, 2))),
}


def validate_width_code(width, port, allow_experimental=False):
    """Reject BRAM width encodings outside the deliberately supported subset."""
    allowed = SUPPORTED_DIRECT_WIDTH_CODES | (
        EXPERIMENTAL_DIRECT_WIDTH_CODES if allow_experimental else frozenset()
    )
    if width not in allowed:
        supported = ", ".join(f"{code:05b}" for code in sorted(SUPPORTED_DIRECT_WIDTH_CODES))
        suffix = (
            "; 32/36-bit memories require the unrecovered packed dual-half lowering"
            if width == 0b10000 else ""
        )
        raise ValueError(
            f"unsupported BRAM PORT{port}_WIDTH code {width:05b}; "
            f"supported direct codes are {supported}{suffix}"
        )

def load_cells():
    """(x,y,mux) -> {sel:(byte,mask)} for BRAM-family cells."""
    d = collections.defaultdict(dict)
    for r in csv.DictReader(open(PIPS)):
        d[(int(r["x"]), int(r["y"]), r["mux"])][int(r["sel"])] = (int(r["byte"]), int(r["mask"]))
    return d

CELLS = load_cells()

# Per-byte write-enable (ByteEnA) is a CFG_KMUX *local-gnd tie* at the BRAM tile, NOT a routed net:
# each nine-selector KMUX lane's position-8 selector ties that lane to local gnd.  Default (no
# selector) = vcc = byte enabled; asserting the pos-8 selector = gnd = that byte's writes are masked.
# Board-proven at X13Y4 (2026-09-15): ByteEnA[0]=KMUX01 lane -> CFG_KMUX sel 17, ByteEnA[1]=KMUX02
# lane -> CFG_KMUX sel 26 (open-flow A/B image_w2ei vs image_w2ei_be0: obs 0xE4->0xFF, low byte held
# at INIT; vendor bytee.bin proved the high-byte tie).  X13Y1..Y3 are the same pos-8 structure from
# bram_cell.csv but not independently board-proven.  Loaded from bram_cell.csv so the offsets cannot
# drift from the device DB.
_BRAM_CELL = os.path.join(TOOLS, "chipdb", "bram_cell.csv")
def _load_byteen_gnd_ties():
    lane_sel = {0: 17, 1: 26}  # ByteEnA[0]->sel17 (low byte), ByteEnA[1]->sel26 (high byte)
    out = collections.defaultdict(dict)
    try:
        rows = list(csv.DictReader(open(_BRAM_CELL)))
    except OSError:
        return {}
    for r in rows:
        if r.get("mux") != "CFG_KMUX":
            continue
        sel = int(r["sel"])
        for lane, s in lane_sel.items():
            if sel == s:
                out[(int(r["x"]), int(r["y"]))][lane] = (int(r["byte"]), int(r["mask"]))
    return {k: v for k, v in out.items() if len(v) == 2}

BYTEEN_GND_TIE = _load_byteen_gnd_ties()
BYTEEN_BOARD_PROVEN_TILES = frozenset({(13, 4)})  # only X13Y4 is silicon-qualified

def byteen_gnd_ties(x, y, mask_low, mask_high):
    """(byte,mask) cells that tie the requested Port-A byte lane(s) to gnd (writes masked).
    Additive: returns only the gnd-tie selector(s) for the masked lane(s); an enabled byte needs no
    selector (vcc is the canvas default).  Raises if the tile has no decoded tie (fail closed)."""
    site = BYTEEN_GND_TIE.get((x, y))
    if site is None:
        raise ValueError(
            "no decoded ByteEn gnd-tie for BramTILE X%dY%d; refusing to emit a byte "
            "mask that would silently leave both bytes writable" % (x, y))
    out = set()
    if mask_low:
        out.add(site[0])
    if mask_high:
        out.add(site[1])
    return out

# Tiles that have decoded configuration cells here.  This is the CONFIG surface
# and it covers all four BramTILEs (plus the PLL tile).  The exact structural
# BEL/cell tables now cover X13Y1..Y4 too, but the production routing graph
# remains silicon-curated and currently exposes only X13Y4 to placement.
ENCODABLE_BRAM_TILES = frozenset((x, y) for (x, y, _mux) in CELLS)

# Configuration families that the open model emits completely.  A placed
# BRAM must clear this owned surface before its asserted bits are applied;
# otherwise zero-valued INIT/control fields silently inherit the canvas.
# Keep unrecovered families (packed mode, delay, write-through, etc.) outside
# this set so they remain fail-closed on the characterized baseline.
OWNED_MUXES = frozenset({
    "INIT_VAL",
    "CFG_DWSEL_A", "CFG_DWSEL_B", "CFG_CLKMODE",
    "CFG_PORTA_CLKIN_EN", "CFG_PORTA_CLKOUT_EN",
    "CFG_PORTA_RSTIN_EN", "CFG_PORTA_RSTOUT_EN",
    "CFG_PORTB_CLKIN_EN", "CFG_PORTB_CLKOUT_EN",
    "CFG_PORTB_RSTIN_EN", "CFG_PORTB_RSTOUT_EN",
})
EXPERIMENTAL_OWNED_MUXES = frozenset(
    contract[0] for contract in EXPERIMENTAL_FIELDS.values()
)

# The eight port-enable names ``emit`` understands.  They are spelled into a mux
# name with ``"CFG_%s" % en``, so a caller typo (``PORTA_WE_EN``, ``PORTA_CLK_EN``)
# used to build a mux that is not in the table and be dropped without a word --
# the caller asked for a clock enable and got the canvas default.
PORT_ENABLE_NAMES = frozenset(
    "%s_%s_EN" % (port, signal)
    for port in ("PORTA", "PORTB")
    for signal in ("CLKIN", "CLKOUT", "RSTIN", "RSTOUT")
)

# Tiles that carry the COMPLETE required BRAM configuration surface.  This is
# deliberately not ENCODABLE_BRAM_TILES: that set is derived from every row of
# pips_bram_pll.csv and therefore also contains the PLL tile (22,5), which has
# a PLL_WORD and no BRAM field at all.
CONFIGURABLE_BRAM_TILES = frozenset(
    tile for tile in {(x, y) for (x, y, _mux) in CELLS}
    if all((tile[0], tile[1], mux) in CELLS for mux in OWNED_MUXES)
)


def owned_surface(x, y, experimental=False):
    """All byte/mask positions modeled completely for one BRAM tile."""
    muxes = OWNED_MUXES | (EXPERIMENTAL_OWNED_MUXES if experimental else frozenset())
    return {
        bm
        for (cx, cy, mux), sels in CELLS.items()
        if (cx, cy) == (x, y) and mux in muxes
        for bm in sels.values()
    }

def emit(x, y, width, clkmode, init_val, enables, width_b=0,
         experimental=None, allow_experimental=False):
    """-> set of (byte,mask) to OR into raw. enables: dict of PORTA/B_{CLKIN,CLKOUT,RSTIN,RSTOUT}_EN->0/1.
    width/width_b = PORTA/B_WIDTH 5-bit thermometer codes (0=x18, 0b01000=x9).
    init_val = 9216-bit int."""
    experimental = {} if experimental is None else dict(experimental)
    unknown = set(experimental) - set(EXPERIMENTAL_FIELDS)
    if unknown:
        raise ValueError("unsupported experimental BRAM field(s): %s" %
                         ", ".join(sorted(unknown)))
    values = {name: int(experimental.get(name, 0)) for name in EXPERIMENTAL_FIELDS}
    requested = sorted(name for name, value in values.items() if value)
    experimental_rows = requested + [
        name for name, value in (
            ("PORTA_WIDTH=10000", width in EXPERIMENTAL_DIRECT_WIDTH_CODES),
            ("PORTB_WIDTH=10000", width_b in EXPERIMENTAL_DIRECT_WIDTH_CODES),
        ) if value
    ]
    if experimental_rows and not allow_experimental:
        raise ValueError(
            "experimental BRAM config requires AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG"
        )
    validate_width_code(width, "A", allow_experimental)
    validate_width_code(width_b, "B", allow_experimental)
    if len(experimental_rows) > 1:
        raise ValueError(
            "at most one B4 experimental config row may be selected per BRAM cell: %s" %
            ", ".join(experimental_rows)
        )
    if allow_experimental and (x != 13 or y not in {1, 2, 3, 4}):
        raise ValueError("experimental BRAM config is scoped to BramTILE X13Y1..Y4")
    for name, (_, _, legal) in EXPERIMENTAL_FIELDS.items():
        if values[name] not in legal:
            raise ValueError("unsupported experimental BRAM %s value %r" %
                             (name, values[name]))
    # The REQUIRED surface needs its own tile gate.  Without one, emit() for a
    # tile that has no decoded cells returned an empty set: a placed BRAM with no
    # INIT, no width, no clock mode and no port enable.  owned_surface() is empty
    # for the same tile, so the clear phase is a no-op too and nothing anywhere
    # is asymmetric enough to notice -- the image config-accepts (FCB 0x000f0002)
    # and the memory reads whatever the canvas left behind.  Only the
    # experimental path was scoped, and only when it was in use.
    if (x, y) not in CONFIGURABLE_BRAM_TILES:
        raise ValueError(
            "BramTILE X%dY%d has no decoded configuration surface in "
            "pips_bram_pll.csv (tiles with a complete surface: %s); refusing to "
            "emit a BRAM whose INIT/width/clock/enable fields would all be "
            "silently absent" % (x, y, sorted(CONFIGURABLE_BRAM_TILES))
        )
    unknown_enables = sorted(set(enables) - PORT_ENABLE_NAMES)
    if unknown_enables:
        raise ValueError(
            "unsupported BRAM port-enable field(s) %s; supported: %s"
            % (", ".join(unknown_enables), ", ".join(sorted(PORT_ENABLE_NAMES)))
        )
    out = []
    def put(mux, sel):
        # Fail closed. A dropped cell here is a field the caller asked for and
        # did not get, with no diagnostic at any verbosity -- the same shape as
        # the experimental check below, which was added for exactly this reason
        # but only covered the experimental fields.
        bm = CELLS.get((x, y, mux), {}).get(sel)
        if bm is None:
            raise ValueError(
                "BRAM %s sel %d has no decoded cell at BramTILE X%dY%d "
                "(pips_bram_pll.csv); refusing to emit a config that would "
                "silently leave the default in place" % (mux, sel, x, y)
            )
        out.append(bm)
    # INIT_VAL: sel = bit index; set iff that bit of init_val is 1
    for k in range(9216):
        if (init_val >> k) & 1: put("INIT_VAL", k)
    # DWSEL_A = PORTA_WIDTH bits (thermometer), bit k -> sel k
    for k in range(5):
        if (width >> k) & 1: put("CFG_DWSEL_A", k)
        if (width_b >> k) & 1: put("CFG_DWSEL_B", k)
    # CLKMODE binary LSB-first
    for k in range(2):
        if (clkmode >> k) & 1: put("CFG_CLKMODE", k)
    # port enables: 1-bit at sel 0
    for en, v in enables.items():
        if v: put("CFG_%s" % en, 0)
    if allow_experimental:
        for name, (mux, width_bits, _) in EXPERIMENTAL_FIELDS.items():
            for bit in range(width_bits):
                if values[name] >> bit & 1:
                    # Required, not best-effort: put() drops a missing cell
                    # silently, which for a config field means the caller asked
                    # for a mode and got the default with no indication.
                    if CELLS.get((x, y, mux), {}).get(bit) is None:
                        raise ValueError(
                            "experimental BRAM %s bit %d has no decoded cell at "
                            "BramTILE X%dY%d (%s); refusing to emit a config "
                            "that would silently leave the default in place"
                            % (name, bit, x, y, mux)
                        )
                    put(mux, bit)
    return set(out)

def observed_bram_bits(raw, x, y):
    """Every BRAM-family cell at (x,y) currently SET in raw -> set of (byte,mask)."""
    s = set()
    for (cx, cy, mux), sels in CELLS.items():
        if (cx, cy) != (x, y): continue
        for sel, (b, m) in sels.items():
            if b < len(raw) and (raw[b] & m): s.add((b, m))
    return s

def decode(path):
    b = open(path, "rb").read()[8:]
    return bytes(b) if len(b) == RAWLEN else L.decode(b)

def parse_initval(macro_path):
    txt = open(macro_path).read()
    m = re.search(r"INIT_VAL\s*=\s*9216'h([0-9a-fA-F]+)", txt)
    return int(m.group(1), 16)

def validate():
    ok = True
    # oracle #1: x18, CLKMODE indep(0), no enables
    iv = parse_initval(os.path.join(TOOLS, "oracle_bram", "bram_macro.v"))
    for name, width, clkmode, en in [
        ("bram.bin", 0b00000, 0b00, {}),
        ("bramp.bin", 0b01000, 0b10, {"PORTA_CLKIN_EN":1,"PORTA_CLKOUT_EN":1,"PORTA_RSTIN_EN":1,"PORTA_RSTOUT_EN":1}),
    ]:
        raw = decode(os.path.join(TOOLS, "oracle_bram", name))
        # find active tile = the one with INIT_VAL bits set
        per = collections.Counter()
        for (cx, cy, mux), sels in CELLS.items():
            if mux == "INIT_VAL":
                for sel, (b, m) in sels.items():
                    if b < len(raw) and raw[b] & m: per[(cx, cy)] += 1
        tile = max(per, key=per.get)
        emitted = emit(tile[0], tile[1], width, clkmode, iv, en)
        obs = observed_bram_bits(raw, tile[0], tile[1])
        extra = emitted - obs; missing = obs - emitted
        status = "PASS" if not extra and not missing else "FAIL"
        if status == "FAIL": ok = False
        print(f"  {name:10} tile{tile} width={width:05b} clkmode={clkmode:02b}: "
              f"emitted {len(emitted)} bits, observed {len(obs)}  -> {status}"
              + (f"  (+{len(extra)} extra, -{len(missing)} missing)" if status=="FAIL" else ""))
    return ok

if __name__ == "__main__":
    print("=== BRAM emit byte-exact validation vs vendor oracles ===")
    ok = validate()
    print("RESULT:", "byte-exact BRAM config reproduced" if ok else "MISMATCH")
    sys.exit(0 if ok else 1)
