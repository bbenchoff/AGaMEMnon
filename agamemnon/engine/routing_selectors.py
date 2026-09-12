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
