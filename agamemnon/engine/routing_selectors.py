"""Shared fail-closed loading and normalization of routing selector evidence."""
from __future__ import annotations

import os
import re

from . import chipdb_schema


FILENAME = "sel_edge_pairs.agdb"

# The BRAM column. clean_edge carries destinations at exactly (13, 1..4), which
# is precisely bram_emit.CONFIGURABLE_BRAM_TILES, so the column alone names the
# four BramTILEs with no y test. Named here rather than imported to keep this
# module free of a dependency on the BRAM feature.
BRAM_COLUMN = 13
CONFIGURABLE_BRAM_ROWS = range(1, 5)
# Opt-in: a BramTILE destination resolves its tile-relative selector ONLY from
# BramTILE observations (see bram_relative_edges); off by default because it
# ADMITS BRAM-derived keys as well as refusing LogicTile-derived ones.
TILE_TYPED_ENV = "AGAMEMNON_TILE_TYPED_RELATIVE"

# Agreement among observations is not proof of translation invariance. This
# same-tile edge is observed only in column 20 (ten rows, pair 0/8). Applying
# it at X14Y7 fails to deliver reset: a regbank16 image fails 3/3; replacing
# only CFG_RMUX11 block 3 with the physically observed X15Y7_RMUX63 input
# (pair 5/7) passes 3/3. Exactly four payload bits differ, all downstream routes
# and logic unchanged. Do not export that boundary observation to other tiles.
# Physical observations remain usable at their exact coordinates. This rejects
# a nonportable inference, not the existence of every possible encoding of the
# edge. Failing image: 346ec0e81dd599fe1bebe97be2d7dce29925cd0880372e38b25e93709ec85307.
# Passing image: f0e6d77b32bd196ba6cda3802a05658ca8af04118b6b8e219439c26c8e66f49e.
# The north-boundary RMUX07 -> RMUX46 observation is also not portable:
# all supporting destinations are row 3, pair 2/9. At X14Y12 that pair has
# exact evidence for X14Y8_RMUX55, not X14Y11_RMUX07. A waitstate16 address
# feedback route using the translation fails; rerouting its return passes
# all 312 original observations in three silicon runs, with logic/placement
# unchanged (one scratch route also changes). Preserve the exact row-3
# observations, but do not infer the same selector elsewhere.
# Failing image: 73c9826375b7c3261e52e766f9793e457350402d143406dc8de1e66d78b3bf2c.
# Passing image: c6c47be7dcc6865f207a6afa0817d7d58f0d76ba72375615c6e0c32730d95bf4.
NONPORTABLE_RELATIVE_KEYS = frozenset({
    ("RMUX", 69, "RMUX", 15, 0, 0),
    ("RMUX", 46, "RMUX", 7, 0, 1),
    # RMUX27 -> RMUX20 with dy=3 is witnessed only from source row1 to
    # destination row4, at columns13 and21. At X18Y5, its inferred pair2/9
    # has a directed vendor route/image witness for X18Y1_RMUX75 instead
    # of X18Y2_RMUX27. Compact addsub fails with the inferred edge;
    # rerouting only its snapshot net passes the full4096-observation
    # contract3/3. That intervention changes a segment, not just this edge,
    # so it is not a single-edge conduction proof. Withdraw the unsupported
    # translation while preserving exact boundary observations. Passing
    # route-intervention image: 94b619bfdaff0b473bc635e4f6e4b965761cda3da
    # 1410a9ae47f766ee931464c. Fresh ordinary-source qualification is separate.
    ("RMUX", 20, "RMUX", 27, 0, 3),
    # RMUX87 -> RMUX59 has the same boundary-only inference problem:
    # supporting exact destinations are row 3; at X14Y12 pair 2/9 has
    # exact evidence for X14Y8_RMUX39. The original ALU target branch
    # fails DC capture while siblings work; a two-selector route-only
    # bypass repairs all 512 observations in three silicon runs.
    # Withdraw the unsupported translation, retaining exact observations.
    # Restored 2026-09-11: this key was added by 96c73ca on 2026-09-06, which
    # never merged to main -- the branch carrying it was unreferenced and days
    # from gc. The consumer nonportable_translation() is live by default
    # (features/routing.py:2511, ungated), so main has been admitting the
    # translation this withdraws. Brian ratified restoring it in session.
    ("RMUX", 59, "RMUX", 87, 0, 1),
    # RMUX03 -> RMUX14 (dx=1) is observed only at destination column 16.
    # At X20Y12 the inferred pair 5/8 has exact evidence for X16Y12_RMUX51,
    # not X19Y12_RMUX03. A dense SERV reset branch reads high when asserted.
    # An exact-edge bypass to X18Y12_RMUX51 (pair 3/8) restores reset; keeping
    # that bypass and restoring ONLY the original two selector bits breaks
    # the observer again in three alternating board runs. This withdraws
    # an unsupported translation, not its exact column-16 observations.
    # The full design still fails; this is not whole-design qualification.
    # Passing probe: c0ec6df35599291df61119c24f9badc766d3fdcafc372ff78349cd38fedc2375.
    # Failing probe: 45e011f7ded49ee5be4b0c0838a5579ee698c0821bbba8f3376a516edc5e8a87.
    ("RMUX", 14, "RMUX", 3, 1, 0),
    # RMUX50 -> RMUX08 (dy=1) has LogicTile witnesses only at destination
    # row 3. At X17Y10 its inferred pair 2/9 instead has exact evidence for
    # X17Y6_RMUX02. A PC-feedback toggle probe delivers no edges through the
    # translation. An exact-edge bypass ending at X17Y11_RMUX50, pair 3/9,
    # delivers 5 MHz; restoring just the original two selector bits loses
    # that signal again in three alternating board pairs. Preserve all exact
    # observations, including the differently encoded BramTILE instance.
    # Passing probe: 757b716b889cf1f0bf8b31210a3227e7b78703acf1329b956a1b67ea5279a4de.
    # Failing probe: 7ffe30d9ef09093e4802d6aa11786a496638788166ca2d2a6c923536ad15dd2b.
    ("RMUX", 8, "RMUX", 50, 0, 1),
    # Same-tile RMUX69 -> RMUX86 is witnessed only at LogicTile row 3
    # (pair 5/9) and a differently encoded BramTILE. At X17Y10 a seven-cell
    # probe reads high for BOTH source levels. Replacing only the target
    # selector with an exact-route input distinguishes 0/5 MHz in three
    # alternating board pairs; cutting its common source prefix breaks that
    # distinction. None of 21 two-hot words tracks the source in this probe.
    # Withdraw the unsupported translation, retaining exact observations;
    # this is not a claim that every possible encoding is absent everywhere.
    # Passing low probe: beb0125cb76222121549f76c8fc7dda4798c274c60ae6029553048b41e2d49cd.
    # Failing low probe: d683f1c965d65265d4ce0fea9c3e734279b412b03ba5a9fbdcddbd0b023990ef.
    ("RMUX", 86, "RMUX", 69, 0, 0),
    # Same-tile RMUX86 -> RMUX57 is observed at column15 and X2Y3, pair4/8.
    # At X17Y10 that pair has exact evidence for X14Y10_RMUX38. A minimal
    # source0/1 probe reads high for both levels; an exact path from the same
    # RMUX86 into X16Y10_RMUX38 -> RMUX57 restores 0/5 MHz. Restoring only
    # the target's two selector bits reproduces failure in three board pairs.
    # Cutting the common source prefix also breaks the reference. Retain
    # exact observations; withdraw translation beyond their coordinates.
    # Passing low probe: 895f5c6f0df2457768758f77b14353d9adbfaec657bb976ec9a909a670508bbc.
    # Failing low probe: 14b108a87257a188d2093ed0b181a3851e2514514bfd0e33a67d56935af87446.
    ("RMUX", 57, "RMUX", 86, 0, 0),
    # Same-tile RMUX87 -> RMUX68 is observed at row2 and X13Y1, pair1/9.
    # At X15Y9 that pair instead has exact evidence for X15Y6_RMUX39.
    # A source0/1 output probe reads high for both levels; an exact bypass
    # from the SAME RMUX87 restores both levels. Restoring only two target
    # selector bits reproduces failure in three board pairs. Clearing the
    # common RMUX87 source prefix also breaks the reference. Keep exact
    # observations, but do not translate this boundary turnback elsewhere.
    # Passing low probe: 625cb7da2a4e299d33dd9dae8ba5ffa13cf4032ff16a0e73b9cce556ad0692f7.
    # Failing low probe: 9f348c42148f42a5c33d60038f7fc4d8dc06dbf25060ca9788c19d3f0d7f1b89.
    ("RMUX", 68, "RMUX", 87, 0, 0),
    # RMUX92 -> RMUX74 with dy=-1 is witnessed only at destination rows 2/3,
    # pair 6/9. At X19Y11 it does not deliver X19Y12_RMUX92. A local observer
    # independently verifies that source prefix (clearing RMUX92 stops it).
    # With both source branches configured, changing ONLY the two RMUX74
    # selector bits from inferred 6/9 to exact 1/9 restores 5 MHz in three pairs.
    # Keep the exact boundary observations; withdraw their translation.
    # Passing probe: 4cdd9b3800cdec2678ee9b687882b20eed9d661aa9f33ea5137d96c071e3862f.
    # Failing probe: 297893ea5912972ed651864ad2849cc96eaa5cd5049b7b150830f50211154946.
    ("RMUX", 74, "RMUX", 92, 0, -1),
    # RMUX93 -> RMUX87 at dx=1 is observed only at destination columns 3/16,
    # pair 5/8. At X19Y10, the independently controlled X18Y10_RMUX93 source
    # toggles but this inferred selector does not deliver it. With both source
    # branches configured, changing only two RMUX87 bits to exact pair 3/8
    # restores 5 MHz in three alternating SRAM trials. Preserve exact witnesses.
    # Passing probe: b07127aac4883b8aa7bea2cfee2385b5306d68c8befa7b6ce2fd285cc13bfb67.
    # Failing probe: 344e8999fb629bd3b9275554245bdca5f775cbec01da4e682e11055ab6eba745.
    ("RMUX", 87, "RMUX", 93, 1, 0),
    # Same-tile RMUX69 -> RMUX87 is observed only at destination rows 3/4/11,
    # pair 5/9. At X17Y10 a seven-cell source0/1 probe reads high for both.
    # An exact-edge path from the SAME RMUX69 distinguishes 0/5 MHz; restoring
    # only four target-selector bits breaks that distinction in three board
    # pairs. Cutting the common source prefix also breaks the reference.
    # Preserve exact observations without translating this inferred selector.
    # Passing low probe: 01698ef5aca04b3006bf6b163e183070858dafd859aae57bd37d7f825cd3c7d4.
    # Failing low probe: 2650c044e6e0c70e67f406b9a22f0ad4e238a0244f22859ce2e2c871fb080477.
    ("RMUX", 87, "RMUX", 69, 0, 0),
    # RMUX33 -> RMUX39 at dx=1 is observed only at destination columns 3/16,
    # pair 5/8. At X18Y9, an independently observed X17Y9_RMUX33 source
    # carries both levels but this inferred selector reads high for both.
    # With an exact output path and both source branches configured, changing
    # only two RMUX39 bits to exact X19Y9_RMUX33 pair 5/7 restores 0/5 MHz
    # in three alternating board pairs. Cutting the common source breaks it.
    # Passing low probe: 9a9281b2fe58fb7034df430211ab160d591674705aaab6c023d5a13e6ad63b57.
    # Failing low probe: 67ff8e9d10adfc685acc98a07397afb97bcf55eaa7a8f4274a15aa8625e462c6.
    ("RMUX", 39, "RMUX", 33, 1, 0),
    # RMUX69 -> RMUX83 at dy=-1 has exact observations at destination rows
    # 2/3/10, pair 6/9. At X18Y9 it fails to deliver the X18Y10_RMUX69 source.
    # An exact alternate from the SAME source restores both levels; reverting
    # only four RMUX83 bits from exact pair 3/8 to inferred 6/9 breaks the
    # reference in three board pairs. A common-source cut also breaks it.
    # Keep exact observations; neither diagnosis qualifies the full design.
    # Passing low probe: 018509eb5f46bc9624ac28658b186086c968dbbfd981c480cf6b5ca291533204.
    # Failing low probe: e292c2741727342e876c5a9c1f0276a51b91e48a9d9ce0b8ec67fc16dbda1221.
    ("RMUX", 83, "RMUX", 69, 0, -1),
    # RMUX85 -> RMUX65 at dy=-1 is observed at destination rows 2/3/10,
    # pair 6/9. At X18Y9 the independently observed X18Y10_RMUX85 prefix
    # carries both source levels, but this inferred input reads high for both.
    # With both branches from the same logical source configured, reverting
    # only two RMUX65 bits from exact pair 4/9 to inferred 6/9 breaks the
    # reference in three alternating board pairs. Source cuts break controls.
    # Passing low probe: 27c49e28ef9858ec5010e1e14bc10e839769374d778af6fce5048c9ae2a764e0.
    # Failing low probe: 0f90ee793e4816502918fed684b3ff68a28b5babae96d7a8e1f539522d3f9cb0.
    ("RMUX", 65, "RMUX", 85, 0, -1),
    # RMUX61 -> RMUX54 at dx=-1 is observed only at destination column 19,
    # pair 1/8. At X18Y10 an independent LUT-buffer observer confirms that
    # X19Y10_RMUX61 delivers both source levels, but this input reads high
    # for both. With both source branches configured, reverting only four
    # target-selector bits from exact 4/9 to inferred 1/8 breaks the reference
    # in three alternating board pairs. Source cuts break level propagation.
    # Passing low probe: 0e6885ace0c965cdff5d2b62b4f11a546f251561a3c1709c15442ee3fbdae342.
    # Failing low probe: 92ada5eec66c6605eec086393c4c14969f09b6b51c72b86e47f3e904a4fda795.
    ("RMUX", 54, "RMUX", 61, -1, 0),
    # RMUX31 -> RMUX25 at dx=-1 is not translation invariant. The X18Y8
    # instance reads low for both source levels despite an independently
    # controlled source observer. Exact pair 2/9 restores propagation;
    # reverting only four target bits to inferred 1/8 breaks three pairs.
    # Preserve exact observations, including the independently tested X19Y11
    # coordinate recorded in clean_edge. See ROUTING_SELECTOR_WITHDRAWAL.md.
    ("RMUX", 25, "RMUX", 31, -1, 0),
    # Same-tile RMUX49 -> RMUX07 support is confined to columns 2 and 15.
    # At X20Y9, inferred pair 4/8 reads high for both source levels while
    # an independent observer confirms both levels at RMUX49. Exact pair
    # 6/8 restores the downstream path; reverting only two target bits
    # breaks three alternating pairs. Preserve exact observations and the
    # distinct leftward RMUX49 -> RMUX07 connection used by the reference.
    ("RMUX", 7, "RMUX", 49, 0, 0),
})

_WIRE = re.compile(r"X(-?\d+)Y(-?\d+)_([A-Za-z]+)(\d+)")


def nonportable_translation(clean_edges, source, destination):
    """Reject a withdrawn translation even when a supplemental path repeats it.

    A path listing is not an independent selector observation. Exact physical
    selector evidence remains authoritative at its own coordinates.
    """
    src, dst = _WIRE.fullmatch(source), _WIRE.fullmatch(destination)
    if src is None or dst is None:
        return False
    sx, sy, sf, si = src.groups()
    dx, dy, df, di = dst.groups()
    sx, sy, si, dx, dy, di = map(int, (sx, sy, si, dx, dy, di))
    relative = (df, di, sf, si, dx - sx, dy - sy)
    exact = (dx, dy, df, di, sf, sx, sy, si)
    return relative in NONPORTABLE_RELATIVE_KEYS and exact not in clean_edges


def load_clean_edges(data_dir):
    path = os.path.join(data_dir, FILENAME)
    datasets, _ = chipdb_schema.load(path, expected=("clean_edge",))
    return datasets["clean_edge"]


def is_bram_destination(dx, dy):
    """The four configurable BramTILEs, (13, 1..4)."""
    return dx == BRAM_COLUMN and dy in CONFIGURABLE_BRAM_ROWS


def tile_typed_enabled(environ=None):
    environ = os.environ if environ is None else environ
    return environ.get(TILE_TYPED_ENV) == "1"


def bram_relative_edges(clean_edges, min_tiles=2):
    """Unanimous tile-relative selectors derived from BramTILE destinations only.

    The reverse of the withdrawal in relative_edges(): a BramTILE may not USE a
    LogicTile-derived key either, because 20.1% of such translations were wrong
    on held-out BRAM observations. This table is the BRAM-scoped replacement.
    It is stricter than the LogicTile table in one way: the same key must be
    observed at ``min_tiles`` distinct BramTILEs and agree, because the BRAM
    resolver reconciliation found 60 keys that vary per tile -- one tile's
    observation is exact evidence at its own coordinate (clean_edge) and no
    evidence for the other three. Nonportable keys stay withdrawn.

    Measured 2026-09-11 with bitgen's real precedence (features/bram.py claims
    every BramTILE pip first: exact X13Y4 bits, then the bram_resolver L0/L1/L2
    levels; only the remainder reaches clean_edge and then this table): over
    4,021 workbench routed netlists, 10,119 BramTILE-destination pips, ZERO
    reach the relative table. So this is an admission-side guard (the arch
    gate can still admit a BramTILE edge through a LogicTile key), not a
    change to any emitted codeword. The "321 differ" figure in the commit
    that introduced it was a precedence-blind table lookup and is withdrawn.
    """
    relative, tiles, conflicts = {}, {}, set()
    for (dx, dy, df, di, sf, sx, sy, si), pair in clean_edges.items():
        if not is_bram_destination(dx, dy):
            continue
        key = (df, di, sf, si, dx - sx, dy - sy)
        pair = tuple(pair)
        if key in relative and relative[key] != pair:
            conflicts.add(key)
        else:
            relative[key] = pair
        tiles.setdefault(key, set()).add((dx, dy))
    conflicts.update(NONPORTABLE_RELATIVE_KEYS.intersection(relative))
    for key in conflicts:
        relative.pop(key, None)
    for key in list(relative):
        if len(tiles.get(key, ())) < min_tiles:
            relative.pop(key)
    return relative, frozenset(conflicts)


def relative_table_for(logic, bram, dx, dy, typed):
    """The relative table a destination may consult: BRAM-scoped when tile-typed
    keying is on and the destination is a BramTILE, otherwise the LogicTile table."""
    return bram if (typed and is_bram_destination(dx, dy)) else logic


def relative_edges(clean_edges):
    """Return unanimous tile-relative selectors and rejected relative keys.

    A relative key is promoted only if every known physical occurrence agrees.
    Conflicting pairs and experimentally nonportable translations are rejected.
    This does not remove the original coordinate-specific observations.

    BRAM-column destinations do not define a relative key. A relative key is a
    claim about tile geometry, and ``emission_audit.logic_tiles`` already
    records that the selector grouping this translation rests on is a LogicTile
    property which "BRAM (x=13), the IO borders (x=0, 22) and the seams group
    differently". Letting a BramTILE observation define a key exports that
    grouping to the 132 LogicTiles, where it is not evidence.

    MEASURED 2026-09-11, held out: build the relative table from LogicTile
    destinations only, then predict the 6,445 BRAM-column physical
    observations it never saw. Of the 3,564 it makes a prediction for:

        prediction correct   2,846   79.9%
        prediction WRONG       718   20.1%

    One in five translated codewords across that tile-type boundary is wrong,
    and a wrong codeword is not a refusal -- it selects a different real input
    which, undriven, reads 1. Worst case is dst RMUX <- src IMUX at 430 wrong
    against 109 right. So the translation is withdrawn in the direction this
    function controls: a BramTILE may still USE a LogicTile-derived key (that
    remains unproven and is tracked separately), but it may no longer DEFINE
    one for the rest of the device.

    BLAST RADIUS over all 5,517 routed netlists in the workbench: 878 relative
    keys withdrawn, 60 edges in 37 builds lose their selector (0.67%), zero
    edges newly admitted, and zero emitted codewords change. The affected
    builds are workbench experiments, several already named
    ``batch_20260821_invalidated_pre_release_strict_fix``; no qualified or
    shipped artifact is among them.
    """
    relative = {}
    conflicts = set()
    for (dx, dy, df, di, sf, sx, sy, si), pair in clean_edges.items():
        if dx == BRAM_COLUMN:
            continue
        key = (df, di, sf, si, dx - sx, dy - sy)
        pair = tuple(pair)
        if key in relative and relative[key] != pair:
            conflicts.add(key)
        else:
            relative[key] = pair
    conflicts.update(NONPORTABLE_RELATIVE_KEYS.intersection(relative))
    for key in conflicts:
        relative.pop(key, None)
    return relative, frozenset(conflicts)
