"""Verify that an emitted image contains the route the router actually produced.

Nothing else in the toolchain checks this. Emission walks the routed netlist,
resolves each pip's selector codeword and sets those bits. If a resolution
silently returns the wrong codeword, or two nets are assigned the same node and
the second overwrites the first, the resulting image is well-formed, passes CRC,
and is WRONG. Every existing gate reasons about the routing GRAPH, before
emission, so none of them can see it.

This reasons about the ARTIFACT. A route is only selector codewords, and every
RMUX/IMUX node's codeword bits are named in ``pips_full.csv``, so the route can
be read back out of the bitstream and compared against the netlist that produced
it.

    MISSING    a pip the router chose whose destination node does not select its
               source in the image. The net is silently broken.
    MALFORMED  a node whose codeword is not 2-hot; the mux selects something
               undefined.

Anything the selector tables cannot resolve is reported separately and NOT
counted as a failure. Refusing a build over an edge this audit cannot adjudicate
would be inferring, which is the thing it exists to prevent.

WHY THIS IS SAFE TO SHIP WHERE OTHER GATES WERE NOT. It can only refuse a build,
never admit one, and its blast radius on a correctly emitted design is exactly
ZERO -- a faithful image passes by construction. It was validated against two
independent faithful images (both PASS at 0) and one deliberately corrupted
image (FAIL, naming the victim net).

SCOPE, stated so it is not overread. This catches emission being unfaithful to
the router's intent. It does NOT tell you whether a route WORKS: an image can be
faithfully emitted and still dead on silicon, and such an image passes this audit
correctly.

Default off. Enable with ``AGAMEMNON_VERIFY_EMISSION=1``.
"""
from __future__ import annotations

import collections
import csv
import os
import re

RES = re.compile(r"([A-Za-z]+)(\d+)")

# A codeword occupies `size` selector slots per node, `per` nodes per cfg instance.
FAMILIES = {"RMUX": (10, 6), "IMUX": (12, 4)}


def node_bits(chipdb_root, offset=8):
    """(x, y, family, index) -> {local_sel: (image_byte, mask)}.

    ``offset`` is the preamble the config body sits behind in the emitted image.
    """
    nodes = collections.defaultdict(dict)
    path = os.path.join(str(chipdb_root), "pips_full.csv")
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mux = row["mux"]
            for family, (size, per) in FAMILIES.items():
                prefix = "CFG_" + family
                if not mux.startswith(prefix):
                    continue
                instance = int(mux[len(prefix):])
                which, local = divmod(int(row["sel"]), size)
                key = (int(row["x"]), int(row["y"]), family, instance * per + which)
                nodes[key][local] = (int(row["byte"]) + offset, int(row["mask"]))
                break
    return dict(nodes)


def read_codewords(image, nodes):
    """Every node carrying a legal 2-hot codeword in this image."""
    found = {}
    for key, sels in nodes.items():
        on = tuple(sorted(s for s, (byte, mask) in sels.items() if image[byte] & mask))
        if len(on) == 2:
            found[key] = on
    return found


def expected_codeword(src, dst, clean, relative):
    """Codeword the destination must carry to select this source, or None.

    The tile-relative table keys on ``dst - src``. Writing ``src - dst`` returns a
    PLAUSIBLE WRONG codeword rather than a miss, because the table holds both
    signs for symmetric displacements -- an inverted sign here reads as a fleet of
    emission defects rather than as a lookup bug, in faithful images too.
    """
    exact = (dst[0], dst[1], dst[2], dst[3], src[2], src[0], src[1], src[3])
    if exact in clean:
        return clean[exact]
    return relative.get((dst[2], dst[3], src[2], src[3],
                         dst[0] - src[0], dst[1] - src[1]))


def audit(image, pips, nodes, clean, relative, tiles=None):
    """Returns (missing, unresolvable, malformed).

    ``tiles`` restricts the check to tile coordinates whose selector grouping is
    known. The 10/12-slot grouping above is a LogicTile property; BRAM, IO and
    boundary tiles group differently, and checking them with this grouping
    manufactures false failures.
    """
    def in_scope(node):
        return tiles is None or (node[0], node[1]) in tiles

    codewords = read_codewords(image, nodes)
    wanted = collections.defaultdict(set)
    for src, dst in pips:
        if dst[2] in FAMILIES and in_scope(dst):
            wanted[dst].add(src)

    missing, unresolvable = [], []
    for dst, sources in wanted.items():
        acceptable = {expected_codeword(s, dst, clean, relative) for s in sources}
        if acceptable == {None}:
            unresolvable.append((dst, sorted(sources)))
            continue
        got = codewords.get(dst)
        if got not in acceptable:
            missing.append((dst, sorted(sources), got,
                            sorted(c for c in acceptable if c)))

    malformed = []
    for key, sels in nodes.items():
        if not in_scope(key):
            continue
        on = [s for s, (byte, mask) in sels.items() if image[byte] & mask]
        if len(on) not in (0, 2):
            malformed.append((key, tuple(sorted(on))))
    return missing, unresolvable, malformed


def enabled(options=None):
    if options is not None:
        return options.enabled("AGAMEMNON_VERIFY_EMISSION")
    return os.environ.get("AGAMEMNON_VERIFY_EMISSION") == "1"


def describe(missing, unresolvable, malformed, limit=10):
    lines = [
        "emission audit: %d MISSING, %d MALFORMED, %d unresolvable (not counted)"
        % (len(missing), len(malformed), len(unresolvable))
    ]
    for dst, sources, got, want in missing[:limit]:
        lines.append(
            "  MISSING X%dY%d_%s%02d: image=%s, router chose %s (expects %s)"
            % (dst[0], dst[1], dst[2], dst[3], got,
               ", ".join("X%dY%d_%s%02d" % s for s in sources), want))
    for key, on in malformed[:limit]:
        lines.append("  MALFORMED X%dY%d_%s%02d: %d sels set %s"
                     % (key[0], key[1], key[2], key[3], len(on), on))
    return "\n".join(lines)
