"""Self-check for nextpnr router2 "Failed to route arc" failures (AG32-Docs TASK_QUEUE.md
queue G, G5 layer 2 -- the durable half of "make AGaMEMnon immune").

WHY THIS EXISTS. On 2026-08-20, router2 reported:

    ERROR: Failed to route arc 1.0 of net 'dma_breq', from X15Y9_OMUX14 to X0Y5_SinkMUXPseudo199.

and a night was spent suspecting the admitted graph, placement density, encoding tables, carry,
and qualification coverage -- all wrong. A directed src->dst BFS over the compiled device graph,
honouring pip direction, proved a completely free path existed in seconds. That particular incident's
root cause (see ``AG32-Docs/NEXTPNR_ROUTER2_BUG.md``) turned out to be a router2-internal reservation
defect: its constant-net reservation pass silently locks a corridor it never actually routes through,
in a way that is invisible to every public availability predicate (``checkPipAvailForNet``,
``getBoundWireNet``).

This module makes the *first* half of that investigation automatic, and only the first half. When a
build's nextpnr invocation reports an unroutable arc, the caller (``agamemnon/cli.py``) feeds this
module the raw log text plus a way to obtain the device graph *that build actually loaded*.

  * If NO legal directed path exists, that is a clean, complete negative: a genuine admission gap in
    the device database, not a router problem. This module says so unmistakably (see
    ``_not_found_message``) -- G7 (2026-08-19) independently verified this verdict against a
    from-scratch BFS with exact agreement, and it is the more actionable of the two outcomes.
  * If a legal directed path DOES exist, that only rules out one thing: the corridor is not missing
    from the admitted graph. It does **not**, by itself, mean router2 is defective -- a task G9
    incident (2026-08-20) showed the same "free path exists" finding can also mean the corridor is
    legitimately bound by another real net's own route (ordinary negotiated-congestion contention
    that this router build failed to rip up and reroute through), which is a different fact than a
    reservation defect and calls for a different response from the user. This module must never
    collapse that distinction -- see ``_found_message``.

Design notes:

  * The BFS is over the *admitted* graph only (same edges nextpnr's Arch was constructed from). It
    does not, and cannot, inspect router2's live pip-occupancy or internal reservation bookkeeping
    (``reserved_net``, ``getBoundPipNet``) -- that requires instrumentation inside the router process
    itself (as the 2026-08-20 investigation did) and cannot be done from outside after the process has
    already exited with a fatal error and no partial-route dump. That is this module's documented
    blind spot, and the positive-verdict message says so explicitly rather than papering over it: a
    free static path is consistent with a reservation defect, with ordinary contention from another
    net, or with a plain router search failure, and this module cannot tell those three apart. Only
    the negative verdict (no path at all) is unambiguous from the static graph alone.
  * The search is strictly directed. An undirected walk invents paths that do not exist -- this was
    a real risk raised and refuted during the 2026-08-20 investigation (see
    "BFS ignored pip directionality" in ``docs/GOAL_VENDOR_PARITY.md``), and is exactly the kind of
    mistake this module exists to make structurally impossible: edges are consumed as ``src -> dst``
    only, never added in both directions.
  * This must never crash a build. Every public entry point catches its own exceptions and returns
    an explanatory string instead of raising.

G13 EXTENSION (2026-08-20, same queue). G2 ran the parity benchmark at all three widths with every
fix in place and the banner above fired ZERO times, because the failures that actually dominate now
are not "Failed to route arc" at all:

  * a RESERVATION COLLISION -- ``ERROR: attempting to reserve sink input path wire 'X14Y8_IMUX17'
    for nets 's_haddr[4]' and '$frontend$289'`` -- the single most common signature at W3/W8. No
    arc, no source/sink pair; the original parser above cannot see it. Handled by
    ``parse_reservation_collisions``/``_collision_message``: this reports which two nets and which
    wire, plus a best-effort, honestly-scoped wire-connectivity fact (``wire_branching``) -- and is
    explicitly NOT asserted to be the ``$PACKER_GND_NET`` defect above; it is the more general,
    currently-unfixed case of two ordinary nets genuinely contending (see that function's docstring
    for exactly what is, and is not, established).
  * a PRE-ROUTING FAILURE -- W32 dies in packing (``entry-anchor negotiation stuck ... fails=60``,
    then ``ERROR: Packing design failed.``) and never reaches routing at all, so the banner above
    stayed silent with no explanation. Handled by ``detect_pre_routing_failure``/
    ``_pre_routing_message``: says plainly that no routing was attempted, so no routing conclusion
    can be drawn -- silence here would be read as "nothing to report", which is the wrong behaviour
    for a diagnostic a user has seen fire before.
"""

import csv
import os
import re
import time
from collections import deque
from typing import Callable, Iterable, Iterator, List, NamedTuple, Optional, Tuple

DOC_POINTER = "AG32-Docs/NEXTPNR_ROUTER2_BUG.md"

# nextpnr's exact template (common/route/router2.cc):
#   log_error("Failed to route arc %d.%d of net '%s', from %s to %s.\n", ...)
# Wire names in this codebase's arches never contain whitespace or a literal period (both the
# viaduct uarch's dev_pips.csv wire names and the legacy pre-pack arch.py's "X<x>Y<y>_<res>" names
# are plain underscore-joined tokens) so a non-greedy match up to the first "', from " boundary for
# the net name, and up to the *last* period on the line for the destination wire, is unambiguous.
_ARC_FAILURE_RE = re.compile(
    r"Failed to route arc (?P<arc>\d+)\.(?P<pin>\d+) of net '(?P<net>.*?)', "
    r"from (?P<src>\S+) to (?P<dst>.+?)\.\s*$",
    re.MULTILINE,
)


class RouteArcFailure(NamedTuple):
    """One parsed "Failed to route arc" message."""
    arc_index: int
    phys_pin: int
    net: str
    src: str
    dst: str
    raw: str


def parse_route_arc_failures(log_text: str) -> List[RouteArcFailure]:
    """Parse every "Failed to route arc" message in ``log_text``, in order.

    Returns an empty list (never raises) for text with no match, including malformed/truncated
    variants of the message.
    """
    if not log_text:
        return []
    failures = []
    for m in _ARC_FAILURE_RE.finditer(log_text):
        try:
            failures.append(RouteArcFailure(
                arc_index=int(m.group("arc")),
                phys_pin=int(m.group("pin")),
                net=m.group("net"),
                src=m.group("src"),
                dst=m.group("dst"),
                raw=m.group(0),
            ))
        except (ValueError, IndexError):
            continue
    return failures


def parse_last_route_arc_failure(log_text: str) -> Optional[RouteArcFailure]:
    """The failure that actually terminated the build, if any.

    router2 calls ``log_error`` (which is fatal) the first time an arc exhausts its retry, so in
    practice at most one of these appears per invocation -- but if a caller ever feeds a
    concatenation of several attempts' logs, the last one is the one that mattered.
    """
    failures = parse_route_arc_failures(log_text)
    return failures[-1] if failures else None


# ---------------------------------------------------------------------------------------------
# G13 (AG32-Docs docs/TASK_QUEUE.md queue G): G2 ran the parity benchmark at all three widths with
# every fix in place and the self-check above fired ZERO times, because it recognises only
# "Failed to route arc ... from SRC to DST" -- but the plurality failure at W3/W8 is a reservation
# collision (below) and W32 dies in packing before routing is ever reached (further below). A
# diagnostic that never fires on the common case is not protection; both are handled explicitly
# rather than inferred, so the module's silence stays meaningful for genuinely-uncovered cases.
# ---------------------------------------------------------------------------------------------

# nextpnr's exact templates for BOTH reservation-collision variants (common/route/router2.cc):
#   log_error("attempting to reserve driver output path wire '%s' for nets '%s' and '%s'\n", ...)
#   log_error("attempting to reserve sink input path wire '%s' for nets '%s' and '%s'\n", ...)
# In both cases the FIRST net named already held the reservation on the wire (it is
# ``nets_by_udata.at(wd.reserved_net)`` in router2.cc); the SECOND is the net whose own
# reservation walk reached that same wire next and could not also claim it, aborting the whole
# build. No arc index, source, or sink appears in this message -- unlike "Failed to route arc",
# this fires during router2's up-front reservation pass ("Setting up routing resources..."),
# strictly before any per-arc routing is attempted.
_RESERVE_COLLISION_RE = re.compile(
    r"attempting to reserve (?P<kind>driver output|sink input) path wire "
    r"'(?P<wire>.*?)' for nets '(?P<holder>.*?)' and '(?P<contender>.*?)'\s*$",
    re.MULTILINE,
)


class ReservationCollision(NamedTuple):
    """One parsed "attempting to reserve ... path wire" message.

    ``holder_net`` already held the reservation on ``wire`` (from its own earlier reservation
    walk); ``contender_net`` is the net whose own walk reached ``wire`` next and could not also
    claim it, which is what actually aborted the build. This is deliberately NOT assumed to be the
    ``$PACKER_GND_NET`` defect documented in ``AG32-Docs/NEXTPNR_ROUTER2_BUG.md`` -- that is one
    specific, already-fixed mechanism (a synthetic constant net locking a corridor it never
    actually routes through). G2's evidence is that this message's plurality occurrence is the
    general, currently-unfixed case: two ordinary, semantically-real nets genuinely contending for
    one wire. See ``_collision_message``, which keeps that distinction explicit in the output.
    """
    kind: str          # "driver output" or "sink input"
    wire: str
    holder_net: str
    contender_net: str
    raw: str


def parse_reservation_collisions(log_text: str) -> List[ReservationCollision]:
    """Parse every "attempting to reserve ... path wire" message in ``log_text``, in order.

    Returns an empty list (never raises) for text with no match, including malformed/truncated
    variants of the message.
    """
    if not log_text:
        return []
    collisions = []
    for m in _RESERVE_COLLISION_RE.finditer(log_text):
        collisions.append(ReservationCollision(
            kind=m.group("kind"),
            wire=m.group("wire"),
            holder_net=m.group("holder"),
            contender_net=m.group("contender"),
            raw=m.group(0),
        ))
    return collisions


def parse_last_reservation_collision(log_text: str) -> Optional[ReservationCollision]:
    """The collision that actually terminated the build, if any.

    Same "last one is the one that mattered" reasoning as ``parse_last_route_arc_failure``: this
    is also a fatal ``log_error``, so at most one appears per real invocation, but a caller feeding
    a concatenation of several attempts' logs gets the last (most recent) one.
    """
    collisions = parse_reservation_collisions(log_text)
    return collisions[-1] if collisions else None


# nextpnr's three fixed pre-routing terminal-stage messages (common/kernel/command.cc), each a
# hard, argument-free ``log_error`` emitted only when that stage's own step returned failure --
# strictly before "Running router2..." (router2.cc), which only prints once routing itself starts.
# A log with one of these and no arc-failure/collision message means routing was never attempted
# at all (e.g. a packer stuck in entry-anchor negotiation, as seen at W32 in the G2 run).
_TERMINAL_STAGE_RE = re.compile(r"(?P<stage>Loading|Packing|Placing) design failed\.")


class PreRoutingFailure(NamedTuple):
    """A build that terminated before nextpnr ever reached routing."""
    stage: str                  # "loading", "packing", or "placing"
    reason: Optional[str]       # nearest preceding "ERROR:" line on its own line, if any (may be None)
    raw: str


def _preceding_error_line(log_text: str, pos: int) -> Optional[str]:
    """The line immediately before the one containing ``pos``, IF that line is itself an "ERROR:"
    line -- otherwise ``None``.

    Best-effort surfacing of text nextpnr (or an arch's own ``pack()``/``place()`` hook) already
    printed for exactly this failure -- e.g. a uarch's own detailed ``log_error`` call immediately
    before the generic "Packing design failed." wrapper -- never a fabricated explanation. Stops
    at the nearest preceding non-blank line and returns ``None`` if that line is not an ERROR
    line, rather than skipping further back and risking misattributing an unrelated error.
    """
    line_start = log_text.rfind("\n", 0, pos) + 1  # 0 if pos's line is the first line
    head = log_text[:line_start]
    for line in reversed(head.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("ERROR:"):
            return stripped
        break
    return None


def detect_pre_routing_failure(log_text: str) -> Optional[PreRoutingFailure]:
    """Detect that nextpnr terminated before routing was ever attempted.

    Recognises nextpnr's own three fixed terminal-stage messages (see ``_TERMINAL_STAGE_RE``) --
    a text-literal match, not a heuristic inferred from the *absence* of a routing marker. A log
    with none of these three exact strings is NOT classified here, even if it also lacks
    "Running router2..." (e.g. a truncated log, or a failure this module has not been taught about
    yet): silence in that case is a known, documented gap, not a suppressed positive -- inventing
    an absence-based heuristic risks misfiring on an unrelated or successful log (see module
    docstring, and AG32-Docs docs/TASK_QUEUE.md queue G, G13).

    Returns ``None`` for text with no match. Never raises.
    """
    if not log_text:
        return None
    last = None
    for m in _TERMINAL_STAGE_RE.finditer(log_text):
        last = m
    if last is None:
        return None
    return PreRoutingFailure(
        stage=last.group("stage").lower(),
        reason=_preceding_error_line(log_text, last.start()),
        raw=last.group(0),
    )


class PathSearchResult(NamedTuple):
    found: bool
    path: Optional[List[str]]
    hops: Optional[int]
    visited: int
    bailed: bool
    bail_reason: Optional[str]


def directed_reachability(
    edges: Iterable[Tuple[str, str]],
    src: str,
    dst: str,
    *,
    max_visited: int = 200_000,
    timeout_s: float = 20.0,
) -> PathSearchResult:
    """Strictly-directed BFS for a src->dst path over ``edges`` (an iterable of ``(src, dst)`` pairs).

    Directed: an edge ``(a, b)`` only ever lets the search move a -> b, never b -> a. This is the
    property a real undirected-graph mistake would silently violate (see module docstring).

    Bounded two ways, both checked while consuming ``edges`` (which may itself be an expensive
    generator, e.g. a from-scratch device-graph rebuild) and while walking the queue:
      * ``max_visited`` -- a hard cap on distinct nodes ever marked visited.
      * ``timeout_s`` -- a wall-clock budget for the whole call.
    Hitting either bound ends the search with ``bailed=True`` and a specific ``bail_reason``; this
    is a DIFFERENT outcome from ``found=False, bailed=False`` (a genuine, complete negative -- the
    search exhausted every reachable node and dst was not among them). Callers must not conflate
    the two: a bailed search proves nothing about absence.
    """
    start = time.monotonic()
    adjacency = {}
    visited = {src}
    checked = 0
    bailed = False
    bail_reason = None

    def _time_left():
        return (time.monotonic() - start) <= timeout_s

    if src == dst:
        return PathSearchResult(True, [src], 0, 1, False, None)

    try:
        for i, (s, d) in enumerate(edges):
            if i % 20_000 == 0 and not _time_left():
                bailed = True
                bail_reason = ("timed out after %.1fs while loading the device graph "
                                "(%d edges read)" % (timeout_s, i))
                break
            adjacency.setdefault(s, []).append(d)
    except Exception as exc:  # defensive: a bad edge source must not crash the caller's build
        return PathSearchResult(False, None, None, 0, True,
                                 "device graph could not be read (%s: %s)" % (type(exc).__name__, exc))

    if not bailed:
        parent = {}
        queue = deque([src])
        while queue:
            checked += 1
            if checked % 2_000 == 0 and not _time_left():
                bailed = True
                bail_reason = ("timed out after %.1fs (visited %d nodes)" % (timeout_s, len(visited)))
                break
            node = queue.popleft()
            for nxt in adjacency.get(node, ()):
                if nxt in visited:
                    continue
                if nxt == dst:
                    parent[nxt] = node
                    path = _reconstruct_path(parent, src, dst)
                    return PathSearchResult(True, path, len(path) - 1, len(visited) + 1, False, None)
                if len(visited) >= max_visited:
                    bailed = True
                    bail_reason = ("hit the %d-node visited cap before finding %r or exhausting "
                                    "the graph" % (max_visited, dst))
                    break
                visited.add(nxt)
                parent[nxt] = node
                queue.append(nxt)
            if bailed:
                break

    return PathSearchResult(False, None, None, len(visited), bailed, bail_reason)


def _reconstruct_path(parent, src, dst):
    path = [dst]
    cursor = dst
    while cursor != src:
        cursor = parent[cursor]
        path.append(cursor)
    path.reverse()
    return path


class WireBranching(NamedTuple):
    """Structural (NOT per-net) connectivity of one wire in the admitted pip graph.

    Counts DISTINCT immediate neighbors, not paths: ``uphill`` is how many different wires have a
    pip directly INTO ``wire``; ``downhill`` is how many have a pip directly OUT of it. This is
    the only fact this module can honestly compute for a reservation-collision wire (see
    ``ReservationCollision``): that message carries the contested wire and both nets' names, but
    NEITHER net's own source or sink wire, so no from-outside check over the static graph alone
    can confirm which net (if either) genuinely had no alternative route through this exact wire
    -- that would need each net's own placed source/sink identity, which the log text does not
    carry. ``_collision_message`` reports this with that limitation stated, not papered over.
    """
    wire: str
    present: bool
    uphill: int
    downhill: int
    bailed: bool
    bail_reason: Optional[str]


def wire_branching(
    edges: Iterable[Tuple[str, str]],
    wire: str,
    *,
    max_edges: int = 2_000_000,
    timeout_s: float = 20.0,
) -> WireBranching:
    """Single pass over ``edges`` counting ``wire``'s distinct uphill/downhill neighbors.

    Bounded the same two ways as ``directed_reachability`` (a hard ``max_edges`` scan cap and a
    wall-clock ``timeout_s`` budget) and just as defensive about a broken edge source -- this must
    never raise into a caller's build. A bailed scan reports partial (lower-bound-only) counts via
    ``bailed=True``; callers must not treat those counts as complete.
    """
    start = time.monotonic()
    uphill = set()
    downhill = set()
    present = False
    bailed = False
    bail_reason = None
    count = 0
    try:
        for s, d in edges:
            count += 1
            if count % 20_000 == 0 and (time.monotonic() - start) > timeout_s:
                bailed = True
                bail_reason = "timed out after %.1fs (%d edges scanned)" % (timeout_s, count)
                break
            if count > max_edges:
                bailed = True
                bail_reason = "hit the %d-edge scan cap before exhausting the graph" % max_edges
                break
            if d == wire:
                uphill.add(s)
                present = True
            if s == wire:
                downhill.add(d)
                present = True
    except Exception as exc:  # defensive: a bad edge source must not crash the caller's build
        return WireBranching(wire, False, 0, 0, True,
                              "device graph could not be read (%s: %s)" % (type(exc).__name__, exc))
    return WireBranching(wire, present, len(uphill), len(downhill), bailed, bail_reason)


def iter_pip_edges_csv(csv_path: str) -> Iterator[Tuple[str, str]]:
    """Stream ``(src, dst)`` pairs from a ``dev_*.csv``-style pip table.

    Matches the viaduct uarch's ``dev_pips.csv`` schema (``emit_uarch_db.py``):
    ``name,type,src,dst,delay_ns,x,y,z``. Streams row-by-row rather than materializing a list, since
    real device databases run into the hundreds of thousands of rows.
    """
    with open(csv_path, "r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            yield row["src"], row["dst"]


def uarch_pip_edges_provider(devdb_dir: str) -> Callable[[], Iterable[Tuple[str, str]]]:
    """Build a lazy edge provider for the viaduct uarch flow's already-emitted device database.

    ``devdb_dir`` is exactly the directory ``agamemnon/cli.py`` passed to nextpnr as
    ``chipdb=<devdb_dir>`` for the failing attempt -- so ``dev_pips.csv`` there is *the* graph
    nextpnr loaded, not a reconstruction of it (it was fingerprinted and validated by
    ``_validate_uarch_devdb`` before this exact build attempt ran).
    """
    pip_csv = os.path.join(devdb_dir, "dev_pips.csv")

    def _load():
        if not os.path.isfile(pip_csv):
            raise FileNotFoundError(pip_csv)
        return iter_pip_edges_csv(pip_csv)

    return _load


def legacy_pip_edges_provider(arch_path: str, data_dir: str, env: dict) -> Callable[[], Iterable[Tuple[str, str]]]:
    """Build a lazy edge provider for the legacy ``--pre-pack arch.py`` flow.

    That flow has no on-disk pip snapshot: nextpnr's embedded Python interpreter calls
    ``archgen.build(ctx, Loc, environ)`` directly and the resulting graph lives only inside that
    process. The *only* faithful way to reproduce "the same device database the build actually
    loaded" (rather than assuming ``rrg_edges_full.csv`` is it -- it is pre-admission-gating raw
    material, not the loaded graph; ``features/routing.py`` and friends filter and add to it) is to
    call the exact same ``archgen.build`` entry point again with the exact same env, recording every
    ``addPip`` call. This reuses ``emit_uarch_db.RecordingCtx``/``Loc`` -- the identical mechanism
    already used, in production, to snapshot this same builder for the uarch flow -- rather than
    reimplementing it.
    """

    def _load():
        # ``arch_path`` (engine/arch.py) is a fixed two-line shim:
        #     from agamemnon.engine.archgen import build
        #     if "ctx" in globals() and "Loc" in globals(): build(ctx, Loc)
        # which forwards no explicit environ, so executing it would fall back to the live
        # process-global os.environ -- not necessarily the exact env this failing attempt used
        # (e.g. a research-unsafe or direct-D overlay applied only to the child process's env).
        # Call archgen.build directly instead: same graph-construction code path, explicit env,
        # no os.environ mutation. Verified by reading arch_path's source that this is equivalent
        # for every arch.py currently shipped in this repo.
        from agamemnon.engine import archgen
        from agamemnon.engine.emit_uarch_db import Loc, RecordingCtx

        if not os.path.isfile(arch_path):
            raise FileNotFoundError(arch_path)
        ctx = RecordingCtx()
        merged_env = dict(env)
        merged_env.setdefault("AGAMEMNON_DATA", data_dir)
        archgen.build(ctx, Loc, environ=merged_env)
        return ((row[2], row[3]) for row in ctx.pips)

    return _load


def _bail_message(failure: RouteArcFailure, reason: str) -> str:
    return (
        "\n"
        "==== ROUTER SELF-CHECK: INCONCLUSIVE ====\n"
        "nextpnr reported arc %d.%d of net '%s' unroutable (%s -> %s), and this build's independent\n"
        "reachability check could not reach a verdict: %s\n"
        "This is NOT evidence the corridor is missing -- the search simply did not finish. See %s.\n"
        "==========================================\n"
    ) % (failure.arc_index, failure.phys_pin, failure.net, failure.src, failure.dst, reason, DOC_POINTER)


def _found_message(failure: RouteArcFailure, result: PathSearchResult, graph_source: str) -> str:
    path = result.path or []
    MAX_SHOWN = 12
    if len(path) > MAX_SHOWN:
        shown = " -> ".join(path[:4]) + " -> ... -> " + " -> ".join(path[-4:])
    else:
        shown = " -> ".join(path)
    return (
        "\n"
        "==== ROUTER SELF-CHECK: A LEGAL PATH EXISTS -- NOT A DEVICE-DATA GAP ====\n"
        "nextpnr reported arc %d.%d of net '%s' unroutable, from %s to %s.\n"
        "An independent, strictly-directed reachability search over %s\n"
        "found a COMPLETE, LEGAL %d-hop path between exactly that source and sink:\n"
        "    %s\n"
        "This rules out one thing, definitively: the corridor is not missing from the admitted\n"
        "device graph, so this is NOT a device-data/admission gap. Do not chase the device database\n"
        "for this failure.\n"
        "\n"
        "It does NOT by itself identify why router2 failed to use this path. This check inspected\n"
        "only the static admitted graph -- it did not, and cannot from outside the router process,\n"
        "inspect router2's live pip occupancy or its internal reservation bookkeeping\n"
        "(reserved_net / getBoundPipNet). That blind spot leaves three distinct possibilities open:\n"
        "  1. a reservation defect -- a wire permanently locked by a net that never actually routes\n"
        "     through it (see %s for one known mechanism of this kind, in this codebase);\n"
        "  2. ordinary negotiated-congestion contention -- a wire legitimately bound to another real\n"
        "     net for that net's own route, which this router invocation failed to rip up and\n"
        "     reroute around;\n"
        "  3. a router search failure -- the path is free and the router's search simply did not\n"
        "     explore it.\n"
        "These call for different responses (file/patch the reservation defect; relax placement or\n"
        "add contention-relief for congestion; report a search-coverage bug for the third) and this\n"
        "check cannot tell them apart. Do not assume a router defect from this message alone.\n"
        "================================================================================\n"
    ) % (failure.arc_index, failure.phys_pin, failure.net, failure.src, failure.dst,
         graph_source, result.hops, shown, DOC_POINTER)


def _not_found_message(failure: RouteArcFailure, result: PathSearchResult, graph_source: str) -> str:
    return (
        "\n"
        "==== ROUTER SELF-CHECK: NO ADMITTED PATH -- LIKELY A GENUINE DEVICE-DATA GAP ====\n"
        "nextpnr reported arc %d.%d of net '%s' unroutable, from %s to %s.\n"
        "An independent, strictly-directed reachability search over %s\n"
        "exhausted every node reachable from %s (%d nodes visited) and never reached %s.\n"
        "No legal admitted path exists between this exact source and sink. This looks like a real\n"
        "admission gap in the device database, not a router defect -- the corridor may need to be\n"
        "harvested/qualified rather than assumed present.\n"
        "==================================================================================\n"
    ) % (failure.arc_index, failure.phys_pin, failure.net, failure.src, failure.dst,
         graph_source, failure.src, result.visited, failure.dst)


def _collision_branching_block(wire: str, pip_edges_provider, graph_source: str) -> str:
    """Best-effort, honestly-scoped structural context for a contested wire (see ``wire_branching``).

    Never raises -- degrades to an explanatory line if the graph cannot be loaded or the scan does
    not finish, the same way the arc-failure path degrades via ``_bail_message``.
    """
    try:
        edges = pip_edges_provider()
    except Exception as exc:
        return ("\nCould not compute wire-connectivity context: could not load %s (%s: %s).\n"
                % (graph_source, type(exc).__name__, exc))
    try:
        branching = wire_branching(edges, wire)
    except Exception as exc:  # extra belt-and-braces; wire_branching already catches internally
        return "\nCould not compute wire-connectivity context (%s: %s).\n" % (type(exc).__name__, exc)
    if branching.bailed:
        return ("\nWire-connectivity scan of '%s' in %s did not finish (%s); no local-connectivity "
                 "context available.\n") % (wire, graph_source, branching.bail_reason)
    if not branching.present:
        return ("\nNote: wire '%s' does not appear as a pip endpoint anywhere in %s -- no "
                 "local-connectivity context available.\n") % (wire, graph_source)
    return (
        "\n"
        "Local connectivity of '%s' in %s -- NOT a per-net path check (this message carries no\n"
        "source/sink wire for either net, so this module cannot verify which net, if either,\n"
        "genuinely had no alternative through this exact wire):\n"
        "    %d distinct uphill neighbor(s)   (wires with a pip directly into '%s')\n"
        "    %d distinct downhill neighbor(s) (wires with a pip directly out of '%s')\n"
        "A count of 1 on either side means every admitted path through this wire funnels through\n"
        "that single neighbor with no alternative -- consistent with genuine contention. A higher\n"
        "count does not prove either net could have avoided this wire, but it does mean the\n"
        "admitted graph itself is not the bottleneck.\n"
    ) % (wire, graph_source, branching.uphill, wire, branching.downhill, wire)


def _collision_message(collision: ReservationCollision, pip_edges_provider, graph_source: str) -> str:
    branching_block = _collision_branching_block(collision.wire, pip_edges_provider, graph_source)
    return (
        "\n"
        "==== ROUTER SELF-CHECK: RESERVATION COLLISION (not an unroutable-arc failure) ====\n"
        "nextpnr's router2 aborted during its up-front reservation pass, before attempting to route\n"
        "any specific arc. Two ordinary nets both required the same wire during a %s-path\n"
        "reservation walk:\n"
        "    wire:                            %s\n"
        "    already reserved by net:         '%s'\n"
        "    could not also reserve for net:  '%s'\n"
        "router2 reserves a likely corridor for a net BEFORE routing starts and never renegotiates\n"
        "that reservation; when a second net's own reservation walk needs the same wire, router2\n"
        "aborts the whole build rather than contending for it during ordinary routing.\n"
        "\n"
        "RELATED BACKGROUND, not the diagnosis here: %s documents one *specific* known mechanism of\n"
        "this general class, where a synthetic constant net ($PACKER_GND_NET/$PACKER_VCC_NET) locks\n"
        "a corridor it never actually routes through. Neither '%s' nor '%s' is a packer constant\n"
        "net, so this is NOT confirmed to be that defect. This is the more general, currently-\n"
        "unfixed case: two ordinary, semantically-real nets genuinely contending for one wire,\n"
        "decided by net-creation order with no renegotiation. Whether one net's need for this wire\n"
        "was spurious (an over-eager reservation-walk heuristic) or both genuinely have no\n"
        "alternative is NOT established by this message alone.\n"
        "%s"
        "===================================================================================\n"
    ) % (collision.kind, collision.wire, collision.holder_net, collision.contender_net,
         DOC_POINTER, collision.holder_net, collision.contender_net, branching_block)


def _pre_routing_message(failure: PreRoutingFailure) -> str:
    reason_line = ("nextpnr's own reported reason: %s\n" % failure.reason) if failure.reason else ""
    return (
        "\n"
        "==== ROUTER SELF-CHECK: NO ROUTING WAS ATTEMPTED ====\n"
        "This build failed during %s -- nextpnr reported \"%s\" -- before it ever reached the\n"
        "routing stage (no \"Running router2...\" was reached). NO ROUTING CONCLUSION CAN BE DRAWN\n"
        "from this failure: the reachability self-check this module otherwise performs only applies\n"
        "to a reported routing failure (an unroutable arc or a reservation collision), and it did\n"
        "not run here because there was nothing routing-related to check.\n"
        "%s"
        "======================================================\n"
    ) % (failure.stage, failure.raw, reason_line)


def diagnose_routing_failure(
    log_text: str,
    pip_edges_provider: Callable[[], Iterable[Tuple[str, str]]],
    *,
    graph_source: str = "the device database this build loaded",
    max_visited: int = 200_000,
    timeout_s: float = 20.0,
) -> Optional[str]:
    """The Layer-2 self-check entry point.

    Looks for whichever failure signature actually terminated the build and reports on it:

      * a "Failed to route arc" message (an unroutable arc) -- runs the original directed
        reachability search and reports one of the three verdicts below, UNCHANGED since G9;
      * an "attempting to reserve ... path wire" message (a reservation collision, G13) -- reports
        which two nets and which wire collided, plus best-effort wire-connectivity context (see
        ``_collision_message``);
      * one of nextpnr's "Loading/Packing/Placing design failed." messages (a pre-routing failure,
        G13) -- reports plainly that no routing was attempted, so no routing conclusion follows
        (see ``_pre_routing_message``).

    If ``log_text`` matches more than one of these -- e.g. a caller concatenates several attempts'
    logs -- the one whose matched text occurs LAST in ``log_text`` wins: the same "last one is the
    one that mattered" reasoning ``parse_last_route_arc_failure`` already used, generalised across
    all three signatures. In a single real nextpnr invocation these are mutually exclusive
    (``log_error`` aborts the process the first time any of them fires), so in practice at most
    one is ever present and this ordering is moot.

    ``pip_edges_provider()`` is called lazily and at most once, and only for the two signatures
    that are actually about routing resources (arc failure, reservation collision); a pre-routing
    failure never calls it, since no routing was attempted and the device graph has nothing to add.

    Returns ``None`` if none of the three signatures is present (nothing to add). Otherwise always
    returns a human-readable diagnostic string; never raises.
    """
    try:
        if not log_text:
            return None

        arc_failure = parse_last_route_arc_failure(log_text)
        collision = parse_last_reservation_collision(log_text)
        pre_routing = detect_pre_routing_failure(log_text)

        candidates = []
        if arc_failure is not None:
            candidates.append((log_text.rfind(arc_failure.raw), "arc", arc_failure))
        if collision is not None:
            candidates.append((log_text.rfind(collision.raw), "collision", collision))
        if pre_routing is not None:
            candidates.append((log_text.rfind(pre_routing.raw), "pre_routing", pre_routing))
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[0])
        _, kind, failure = candidates[-1]

        if kind == "pre_routing":
            return _pre_routing_message(failure)

        if kind == "collision":
            return _collision_message(failure, pip_edges_provider, graph_source)

        # kind == "arc": original G5/G9 logic, byte-for-byte unchanged.
        try:
            edges = pip_edges_provider()
        except Exception as exc:
            return _bail_message(
                failure,
                "could not load %s (%s: %s)" % (graph_source, type(exc).__name__, exc),
            )
        result = directed_reachability(edges, failure.src, failure.dst,
                                        max_visited=max_visited, timeout_s=timeout_s)
        if result.bailed:
            return _bail_message(failure, result.bail_reason or "search bailed for an unknown reason")
        if result.found:
            return _found_message(failure, result, graph_source)
        return _not_found_message(failure, result, graph_source)
    except Exception as exc:  # a diagnostic aid must never mask or crash the real build failure
        return ("\n[router2 self-check] internal error while diagnosing the routing failure "
                "(%s: %s); ignoring and reporting the original nextpnr error only.\n"
                % (type(exc).__name__, exc))
