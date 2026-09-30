"""Post-route refusal for board-confirmed corner-tile congestion-marginal pips.

Placement and route qualification, 2026-09-25.
Three open-flow narrow-BRAM designs failed on silicon (2x LED rate / 0 edges) although every
pip they used carries a positive ring and corpus conduction witness and the designs simulate
PASS as routed. Cell placement was found bit-identical between each failing image and a passing
counterpart in the same family: the defect is not a relocated BEL, it is a specific ROUTE. Each
failing design's problem net (the free-running heartbeat counter's `hb[0]` bit, or the design
`reset`) reached tile X20Y12 through one of three specific RMUX->IMUX pips
(``agamemnon/chipdb/congestion_marginal_edges.csv``), while a passing counterpart in the same
family reached the equivalent terminal through a different, non-suspect feeder.
``route_surgery.py`` (strict mode: tier-1 graph, the suspect pip excluded, every other net's
wires held fixed) reported each of the three nets UNROUTABLE without its suspect pip, confirming
there is no alternate route once the rest of the design's routing has already claimed the corner
tile's other legal feeders into the same IMUX terminal. This is aggregate route congestion
at the BRAM-family corner tile, rather than evidence that an isolated edge never conducts.

These pips are NOT convicted as silicon-dead (``dead_edges_silicon.csv``): they conduct cleanly
in an isolated ring or a small corpus design. They are unreliable specifically when a real,
congested design forces them to be the sole remaining carrier for a loaded signal. Removing them
from the device graph unconditionally would retroactively change every historical physical-graph
checkpoint this repo pins byte-exact (``agamemnon/engine/special_routes.py``), which is much more
invasive than the actual defect calls for. Instead this module inspects the ROUTED netlist after
place & route and refuses the build outright if it used one of the three pips -- the same
"refused or moved" outcome (an honest build error instead of a silently-wrong bitstream, or a
different --seed/--cap finding a route that never needed the marginal pip) without touching the
device graph at all.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

CSV_NAME = "congestion_marginal_edges.csv"

_EDGE_RE = re.compile(r"(\w+)@(-?\d+),(-?\d+)->(\w+)@(-?\d+),(-?\d+)")


class CongestionMarginalError(RuntimeError):
    pass


def congestion_marginal_pip_sources(chipdb_root):
    """Refused pips as ``{routed-JSON PIP name: evidence source}``.

    Several evidence classes share the table: ``board_congestion_*`` (board-confirmed X20Y12
    congestion-marginal feeders), ``unproven_shape_*`` (pip shapes that no board-PASS open image
    or qualified fixture has ever used), ``board_pair_*`` (pips isolated by a same-placement
    pass/fail board comparison), and ``afexe_absent_*`` / ``afexe_absent_board_*`` (routing pips
    that af.exe's own bitgen does not know at that position; the board variant was also bisected
    to on silicon), and ``afexe_codeword_conflict_*`` (hops whose selector the vendor bitgen gives
    to another source or writes differently).
    """
    path = Path(chipdb_root) / CSV_NAME
    sources = {}
    if not path.exists():
        return sources
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            edge = (row.get("edge") or "").strip()
            match = _EDGE_RE.fullmatch(edge)
            if not match:
                raise ValueError("malformed congestion-marginal edge in %s: %r" % (path, row))
            src, sx, sy, dst, dx, dy = match.groups()
            sources["X%sY%s_%s.X%sY%s_%s" % (sx, sy, src, dx, dy, dst)] = (row.get("source") or "").strip()
    return sources


def congestion_marginal_pip_names(chipdb_root):
    """Board-confirmed congestion-marginal pips as routed-JSON PIP names.

    ``congestion_marginal_edges.csv`` spells an edge ``SRC@sx,sy->DST@dx,dy`` (the same
    convention as ``dead_edges_silicon.csv``); a routed netlist's ``ROUTING`` attribute spells
    the same pip ``X<sx>Y<sy>_SRC.X<dx>Y<dy>_DST``. Converts once so callers compare strings, not
    coordinates.
    """
    path = Path(chipdb_root) / CSV_NAME
    names = set()
    if not path.exists():
        return names
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            edge = (row.get("edge") or "").strip()
            match = _EDGE_RE.fullmatch(edge)
            if not match:
                raise ValueError("malformed congestion-marginal edge in %s: %r" % (path, row))
            src, sx, sy, dst, dx, dy = match.groups()
            names.add("X%sY%s_%s.X%sY%s_%s" % (sx, sy, src, dx, dy, dst))
    return names


def _routed_pips(routing_attribute):
    """The PIP tokens of a canonical wire/PIP/strength ``ROUTING`` triple string."""
    if not isinstance(routing_attribute, str) or not routing_attribute:
        return ()
    parts = routing_attribute.split(";")
    if len(parts) % 3:
        return ()
    return tuple(pip for pip in parts[1::3] if pip)


def validate_module_congestion_marginal(module, chipdb_root):
    """Refuse a routed ``modules['top']`` that used a board-confirmed congestion-marginal pip.

    Silent on a document with no ``netnames`` or an empty/missing evidence table (fail-open on
    absent data, matching the other typed post-route validators here) -- the point is to catch a
    KNOWN board-negative pip, not to invent new ones.
    """
    banned = congestion_marginal_pip_sources(chipdb_root)
    if not banned:
        return
    netnames = module.get("netnames") if isinstance(module, dict) else None
    if not isinstance(netnames, dict):
        return
    hits = []
    for name, net in netnames.items():
        if not isinstance(net, dict):
            continue
        attrs = net.get("attributes")
        if not isinstance(attrs, dict):
            continue
        for pip in _routed_pips(attrs.get("ROUTING")):
            if pip in banned:
                hits.append((name, pip))
    if not hits:
        return
    shown = hits[:8]
    detail = "; ".join("net %r uses %s" % (name, pip) for name, pip in shown)
    more = "" if len(hits) <= len(shown) else " (+%d more)" % (len(hits) - len(shown))
    classes = {banned[pip].rsplit("_", 1)[0] for _, pip in hits}
    reasons = []
    if "board_congestion" in classes:
        reasons.append(
            "board-confirmed congestion-marginal pip(s) conduct in isolation (ring/corpus "
            "witnessed) but failed on silicon as the forced sole route into a scarce corner-tile "
            "IMUX terminal (2x-rate / 0-edges, twice-confirmed; see "
            "qualification/x20y12_congestion_marginal_evidence.jsonl)")
    if "unproven_shape" in classes:
        reasons.append(
            "never-proven pip shape(s): no board-passing open image or qualified fixture uses "
            "this source/destination mux pair and offset anywhere on the device, and every "
            "silicon-failing default image of the 2026-09-29 stronger holdouts used one "
            "(see qualification/unproven_shape_refusal_20260929.json)")
    if "board_pair" in classes:
        reasons.append(
            "pip(s) isolated by a same-placement pass/fail board comparison "
            "(see qualification/unproven_shape_refusal_20260929.json)")
    if "afexe_absent_board" in classes:
        reasons.append(
            "pip(s) unknown to the vendor router and board-proven wrong: af.exe's bitgen writes "
            "nothing for this hop, and a board bisection isolated it as the single cause of "
            "silently wrong images (see qualification/afexe_absent_refusal_20260929.json)")
    if "afexe_absent" in classes:
        reasons.append(
            "pip(s) unknown to the vendor router: af.exe's bitgen writes nothing for this hop at "
            "this position, so our selector codeword has no confirmed source "
            "(see qualification/afexe_absent_refusal_20260929.json)")
    if "afexe_codeword_conflict" in classes:
        reasons.append(
            "pip(s) whose emitted selector the vendor bitgen assigns to a different source or "
            "writes differently, so the route would not connect as modelled "
            "(see qualification/afexe_absent_refusal_20260929.json)")
    if not reasons:
        reasons.append("pip(s) listed in agamemnon/chipdb/congestion_marginal_edges.csv")
    raise CongestionMarginalError(
        "routed design uses %d refused pip use(s): %s%s -- %s. Refusing to emit a bitstream "
        "that may read back wrong on real hardware. Retry with a different --seed/--cap so the "
        "placer/router is not forced through this pip, or investigate why no alternative route "
        "was available." % (len(hits), detail, more, "; ".join(reasons))
    )


def validate_document_congestion_marginal(document, chipdb_root):
    modules = document.get("modules") if isinstance(document, dict) else None
    module = modules.get("top") if isinstance(modules, dict) else None
    if not isinstance(module, dict):
        raise CongestionMarginalError(
            "routed document requires exact modules['top'] for the congestion-marginal check"
        )
    validate_module_congestion_marginal(module, chipdb_root)
