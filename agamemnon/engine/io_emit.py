#!/usr/bin/env python3
"""Open IOTILE ring-pad OUTPUT config emitter + byte-exact validator (Project Agamemnon).

Given the set of ring-pad outputs in a routed design — each = (padtile_x, padtile_y, z, R) where z is
the pad slot (0..3) and R is the pad-tile RMUX index feeding the pad (multiple of 4) — produce the
CFG_IOMUX config bits at the N-1 config tile (padtile_x-1, padtile_y). Encoding: findings_io_crack.md.

  source-select (per pad): CFG_IOMUX0  lo = 7*z + (R//4 & 3),  hi = 7*z + 4 + (R//4 >> 2)
  pad-enable (per active-z SET): CFG_IOMUX{bank} sel = 7*block + 6, from ENABLE table.

VALIDATION: reproduce the full CFG_IOMUX0..3 pattern at a used pad's N-1 tile and compare byte-exact
to the vendor bitstream (cpld_native led/led2 @ (20,13); rrg_11 4-pad @ (16,13)).
"""
import os, sys, csv, collections
HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(os.path.dirname(HERE), "chipdb")
if "AGAMEMNON_DATA" in os.environ: DATA = os.environ["AGAMEMNON_DATA"]
# TOOLS = the AG32-Docs tools/ dir (engine_work -> agamemnon -> tools). validate() oracles live under it.
TOOLS = os.path.dirname(os.path.dirname(HERE))
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(HERE))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)
from agamemnon.engine import lzw_codec as L
RAWLEN = 99936

# pad-ENABLE table: active-z SET -> {iomux_bank: [block indices]}; sel = 7*block + 6.
ENABLE = {
    # z0-ALONE: corrected 2026-07-03 from the PIN_18-only vendor oracle (vendor_pin18only, silicon-
    # guaranteed toggle). Was missing CFG_IOMUX1 block 3 + CFG_IOMUX2 block 1 -> IOMUX under-enabled
    # -> open z0 pad output config-accepted but stayed STATIC. See PADOUT_DIAGNOSIS.md.
    # Rechecked against the minimal vendor PIN_10 -> PIN_16 combinational oracle (2026-07-12).
    # A lone z0 output enables every block in banks 1 and 2 as well; omitting bank1/block2
    # (sel 20) and bank2/block0 (sel 6) produces a valid, routed image whose pad is static.
    frozenset({0}):       {0: [1, 2, 3, 5], 1: [0, 1, 2, 3, 4, 5], 2: [0, 1, 2, 3, 4, 5], 3: [0, 1, 2, 3, 4, 5]},
    frozenset({1, 2}):    {2: [5], 3: [0, 3, 4]},
    frozenset({1, 2, 3}): {2: [5], 3: [0, 1, 3, 4, 5]},
    frozenset({0, 1, 2, 3}): {2: [4, 5], 3: [0, 1, 2, 3, 4, 5]},
    # additional active-z SETs harvested from the vendor pintest builds (top-row pads):
    frozenset({2, 3}):    {0: [0, 1, 4, 5], 1: [2, 3], 2: [0, 1, 4, 5], 3: [0, 1, 2, 3, 4, 5]},
    frozenset({0, 3}):    {0: [1, 2, 5], 1: [0, 3, 4], 2: [1, 2, 4, 5], 3: [0, 1, 2, 3, 4, 5]},
}

def emit_sels(outputs):
    """outputs: list of (z, R). -> {mux: set(sel)} for the N-1 config tile.

    The ENABLE lookup FAILS CLOSED on an unlisted active-z set. It used to be
    ``ENABLE.get(active, {})``, which emitted no enable bits at all: the build
    succeeded, bitgen reported nothing wrong, and the pin was simply dead. The
    pattern has to be exactly right and it is proven exact in BOTH directions --
    io_emit's own history records that OMITTING bits leaves the pad static, and
    2026-08-15 silicon shows that ADDING them does too. Taking the working
    PIN_18 image and setting the six extra enable bits that would make its tile
    match a uniform all-blocks pattern still config-accepts (FCB 0x000f0002) and
    the pad stops toggling: 460 kHz on Pico GP8 -> 0 edges. So there is no safe
    superset to fall back on, and guessing is worse than refusing.
    """
    sels = collections.defaultdict(set)
    for (z, R) in outputs:
        idx = R // 4
        sels["CFG_IOMUX0"].add(7 * z + (idx & 3))
        sels["CFG_IOMUX0"].add(7 * z + 4 + (idx >> 2))
    active = frozenset(z for (z, R) in outputs)
    if active and active not in ENABLE:
        raise SystemExit(
            "ring-pad output slot set %s has no harvested CFG_IOMUX enable "
            "pattern; only %s are characterized. Emitting the source-select "
            "alone gives a config-accepted image with a STATIC pin, so this "
            "fails closed instead. Harvest the pattern for this slot set from a "
            "vendor build before driving these pads together."
            % (sorted(active), sorted(sorted(entry) for entry in ENABLE))
        )
    for bank, blocks in ENABLE[active].items() if active else ():
        for b in blocks:
            sels["CFG_IOMUX%d" % bank].add(7 * b + 6)
    return sels

def load_io_cells():
    cells = collections.defaultdict(dict)   # (x,y,mux)->{sel:(byte,mask)}
    for r in csv.DictReader(open(os.path.join(DATA, "pips_io.csv"))):
        if r["kind"] == "mux" and r["mux"].startswith("CFG_IOMUX"):
            cells[(int(r["x"]), int(r["y"]), r["mux"])][int(r["sel"])] = (int(r["byte"]), int(r["mask"]))
    return cells

CELLS = load_io_cells()

def emit_bits(nx, ny, outputs):
    """-> set of (byte,mask) at N-1 tile (nx,ny).

    Fails closed on a missing cell for the same reason ``slot_config_bits`` does:
    a subset of the pad codeword is a config-accepted image with a static pin.
    """
    out = set()
    for mux, ss in emit_sels(outputs).items():
        for s in ss:
            bm = CELLS.get((nx, ny, mux), {}).get(s)
            if bm is None:
                raise SystemExit(
                    "ring-pad %s sel %d has no cell at the (%d,%d) config tile; "
                    "refusing to emit a partial pad configuration"
                    % (mux, s, nx, ny)
                )
            out.add(bm)
    return out


BLOCKS_PER_BANK = 6
PARK_OFFSET = 6


def slot_config(outputs):
    """A ring-pad output's CFG_IOMUX config as (set, clear) of (bank, sel).

    This supersedes the ENABLE lookup. The lookup was fifteen possible pad-slot
    sets with six characterized, and it treated the bits as a per-set pattern to
    be memorised. They are not: the tile parks every IOMUX index at
    ``7 * block + PARK_OFFSET``, and driving one index simply UNPARKS it and
    writes its two source-select bits. A pad slot z occupies TWO indices, z and
    z + 4, and index i lives at ``bank, block = divmod(i, 6)`` -- which is why
    the old flat ``7 * z + ...`` form silently ran off the end of bank 0 for
    z >= 6 on the wider left-edge tiles.

    Evidence. Fifteen af.exe oracles, one per non-empty subset of {0,1,2,3} on
    IOTILE (19,13), reproduce this rule EXACTLY -- 15/15, every set bit and every
    clear bit, against a no-pad control build from the same flow
    (chipdb/pad_iomux_slotset_L48.csv). Our own from-scratch base frame is
    byte-identical to that control at the config tile, all 24 park bits set and
    nothing else, so the deltas apply directly. Silicon closes it in both
    directions on the known-good PIN_18 image: re-parking a DRIVEN block kills
    the pad (460,856 Hz -> 0 edges) while unparking an UNUSED one is harmless
    (461,555 Hz, unchanged), so the bits are per-block and independent.

    Two forms of the same rule are in play and they are not interchangeable.
    ``index_config`` is the VENDOR form: af.exe drives both indices of a slot and
    gives each its own feeder, so each gets source-select bits. ``slot_config``
    is the open form the silicon-proven PIN_18 image uses: source-select for the
    data index only, park cleared for both. Keeping them separate matters --
    validating one against the other's ground truth is how a plausible rule gets
    "confirmed" against the wrong thing.

    outputs: iterable of (z, R). Returns (set_bits, clear_bits).
    """
    sets, clears = index_config({z: rmux for z, rmux in outputs})
    for z, _rmux in outputs:
        bank, block = divmod(z + 4, BLOCKS_PER_BANK)
        clears.add((bank, 7 * block + PARK_OFFSET))
    return sets, clears


def index_config(feeders):
    """The rule in its measured form: {iomux_index: feeder_rmux} -> (set, clear).

    This is what the fifteen af.exe slot-set oracles reproduce exactly, index by
    index, and it is the form to use when every driven index's feeder is known.
    """
    sets, clears = set(), set()
    for index, rmux in feeders.items():
        bank, block = divmod(index, BLOCKS_PER_BANK)
        choice = rmux // 4
        clears.add((bank, 7 * block + PARK_OFFSET))
        sets.add((bank, 7 * block + (choice & 3)))
        sets.add((bank, 7 * block + 4 + (choice >> 2)))
    return sets, clears


def slot_config_bits(nx, ny, outputs):
    """slot_config() resolved to (byte, mask) cells at the N-1 tile (nx, ny)."""
    sets, clears = slot_config(outputs)

    def resolve(pairs):
        out = set()
        for bank, sel in pairs:
            cell = CELLS.get((nx, ny, "CFG_IOMUX%d" % bank), {}).get(sel)
            if cell is None:
                raise SystemExit(
                    "ring-pad CFG_IOMUX%d sel %d has no cell at the (%d,%d) "
                    "config tile; refusing to emit a partial pad configuration"
                    % (bank, sel, nx, ny)
                )
            out.add(cell)
        return out

    return resolve(sets), resolve(clears)

def decode(path):
    b = open(path, "rb").read()[8:]
    return bytes(b) if len(b) == RAWLEN else L.decode(b)

def observed(raw, nx, ny):
    """all CFG_IOMUX0..3 bits SET at (nx,ny)."""
    s = set()
    for (x, y, mux), sels in CELLS.items():
        if (x, y) == (nx, ny) and mux in ("CFG_IOMUX0","CFG_IOMUX1","CFG_IOMUX2","CFG_IOMUX3"):
            for sel, (b, m) in sels.items():
                if b < len(raw) and (raw[b] & m): s.add((b, m))
    return s

def validate():
    # (bin, pad_tile_x, pad_tile_y, outputs=[(z,R)])  -- R,z from each design's route.tx (agent-extracted)
    cases = [
        ("cpld_native/blinky.bin", 20, 13, [(1, 20), (2, 28)]),   # led2 z1<-RMUX20, led z2<-RMUX28
        ("lab/rrg_11/blinky.bin",  16, 13, [(0, 8), (1, 28), (2, 20), (3, 0)]),
    ]
    ok = True
    for binrel, px, py, outs in cases:
        p = os.path.join(TOOLS, binrel)
        if not os.path.exists(p): print(f"  {binrel}: MISSING"); continue
        raw = decode(p)
        nx, ny = px - 1, py
        em = emit_bits(nx, ny, outs)
        ob = observed(raw, nx, ny)
        extra = em - ob; miss = ob - em
        status = "BYTE-EXACT" if not extra and not miss else "MISMATCH"
        if status != "BYTE-EXACT": ok = False
        print(f"  {binrel:26} pad({px},{py}) N-1({nx},{ny}) outs={outs}: "
              f"emit {len(em)} / obs {len(ob)} -> {status}"
              + (f" (+{len(extra)} -{len(miss)})" if status!="BYTE-EXACT" else ""))
    return ok

if __name__ == "__main__":
    print("=== IO ring-pad output-driver emit byte-exact validation ===")
    ok = validate()
    print("RESULT:", "byte-exact IO pad-output config reproduced" if ok else "MISMATCH")
    sys.exit(0 if ok else 1)
