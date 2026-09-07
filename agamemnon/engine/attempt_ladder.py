"""Per-attempt log capture and cross-attempt failure summarisation for the AGaMEMnon ``--uarch``
build's cap/seed/fanout escalation loop (AG32-Docs ``docs/TASK_QUEUE.md`` queue G, G10).

WHY THIS EXISTS. ``cli.py``'s ``--uarch`` build path tries up to ~36 cap/seed/fanout combinations
looking for one placement/routing attempt that routes. Historically it kept only the *last*
attempt's captured log (``rlog``) -- every earlier attempt's log was silently overwritten -- and
printed only that final one when the whole ladder failed. Three honest reproductions of the
*identical* design gave three different "Failed to route arc" nets (``s_hreadyout``,
``dut.beat[0]``, ``s_hwdata[2]``) purely because of where the ladder happened to bottom out, not
because the device graph changed (the device database was regenerated twice and confirmed
byte-identical, including row order -- the variability is in synthesis/placement, not the graph).
That made an ordinary escalation failure look nondeterministic, and a queued task (G8) was written
around one specific arc that a later agent then could not reproduce in three attempts.

This module gives ``cli.py``'s loop the two things it was missing:

  1. **Preserve every attempt's log to disk** (`write_attempt_log`), not just the last, under a
     predictable, greppable name -- so any rung of the ladder is available for post-mortem without
     rerunning it.
  2. **Summarise across attempts** (`summarize_ladder` / `format_ladder_summary`) so the terminal
     report says which failure signature *recurred*, and how often, instead of whichever signature
     happened to belong to the final attempt. A net that fails in most attempts is a far stronger
     signal than whichever one happened to be last.

DISCIPLINE. This is a diagnostics change and must not invent signal:
  * A single attempt is reported as a single attempt, plainly -- never dressed up as if it were a
    distribution over more than one data point.
  * If every attempt fails with a *different* signature, that disagreement is itself the finding
    (it is exactly the observation that first exposed the arc instability -- see above) and must be
    stated, not silently resolved by picking one attempt to feature.
  * Nothing here inspects live router state; a signature is derived purely from the attempt's own
    captured text, the same evidence the old single-log printout already had.
"""

import os
from collections import Counter
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import router2_diagnostics as _router2_diag

# Outcome tags recorded per attempt. ABORTED and NONRETRYABLE are fatal for the whole build (the
# caller exits immediately after recording them) but are still logged to disk for post-mortem.
SUCCESS = "ROUTED"
TIMING_FAILED = "ROUTED_TIMING_FAILED"
NOT_ROUTED = "NOT_ROUTED"
ABORTED = "ABORTED"
NONRETRYABLE = "NONRETRYABLE"


class AttemptRecord(NamedTuple):
    """One (cap, seed, fanout) rung of the escalation ladder, as actually run."""
    index: int      # 1-based, in the order attempts actually ran (not the (cap, fo) pair index)
    cap: int
    seed: str
    fanout: int      # 0 == fanout splitting was off for this attempt
    outcome: str      # one of the module-level outcome tags above
    log: str          # the full captured nextpnr stdout+stderr for this attempt (untruncated)


class Signature(NamedTuple):
    """A terminal failure signature, coarse enough to group repeats of "the same" failure."""
    kind: str    # "ARC_FAILURE" | "ABORTED" | "NONRETRYABLE" | "TIMING" | "OTHER"
    key: str     # grouping key -- the net name for ARC_FAILURE, a fixed tag otherwise
    detail: str  # one-line human-readable description


class LadderSummary(NamedTuple):
    total: int
    succeeded: bool
    success_index: Optional[int]
    # Most-common-first; ties keep the order signatures were first seen (stable sort).
    signature_counts: List[Tuple[Signature, int]]
    signature_attempts: Dict[Signature, List[int]]   # signature -> attempt indices bearing it
    representative: Optional[AttemptRecord]           # best attempt to feed the self-check / print
    representative_signature: Optional[Signature]      # THAT attempt's own signature (never assume
                                                          # it equals signature_counts[0] -- when
                                                          # every attempt disagrees, it does not)
    all_distinct: bool                                 # every failing attempt had its own signature


def attempt_filename(record: AttemptRecord) -> str:
    """The predictable, greppable on-disk name for one attempt's log."""
    fo = "off" if record.fanout == 0 else str(record.fanout)
    return "attempt_%02d_cap%d_seed%s_maxfo%s.log" % (record.index, record.cap, record.seed, fo)


def attempt_header(record: AttemptRecord) -> str:
    fo = "off" if record.fanout == 0 else str(record.fanout)
    return "# attempt %d cap=%d seed=%s fanout=%s outcome=%s\n" % (
        record.index, record.cap, record.seed, fo, record.outcome)


def write_attempt_log(attempts_dir: str, record: AttemptRecord) -> Optional[str]:
    """Write one attempt's header plus its full captured log under ``attempts_dir``.

    Best-effort: preserving a diagnostic log must never fail the actual build. Returns the path
    written, or ``None`` (after printing a warning) if the write could not be completed.
    """
    path = os.path.join(attempts_dir, attempt_filename(record))
    try:
        os.makedirs(attempts_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(attempt_header(record))
            fh.write("\n")
            fh.write(record.log or "")
        return path
    except OSError as exc:
        print("warning: could not write attempt log %s (%s: %s); continuing" %
              (path, type(exc).__name__, exc))
        return None


def _signature_for(record: AttemptRecord) -> Optional[Signature]:
    """The terminal failure signature for one non-successful attempt, or ``None`` if it routed."""
    if record.outcome == SUCCESS:
        return None
    if record.outcome == ABORTED:
        return Signature("ABORTED", "ABORTED", "nextpnr aborted (assertion/exception)")
    if record.outcome == NONRETRYABLE:
        return Signature("NONRETRYABLE", "NONRETRYABLE",
                          "nextpnr rejected a deterministic hardware constraint")
    # Prefer the parsed arc, regardless of outcome tag: a router2 "Failed to route arc" message is
    # the most specific evidence available and is what G8/G10 are actually about.
    failure = _router2_diag.parse_last_route_arc_failure(record.log)
    if failure is not None:
        return Signature("ARC_FAILURE", failure.net,
                          "net '%s' (%s -> %s)" % (failure.net, failure.src, failure.dst))
    if record.outcome == TIMING_FAILED:
        return Signature("TIMING", "TIMING", "routed, but the timing target was not met")
    if "Placing design failed." in record.log or "Unable to place cell" in record.log:
        return Signature("PLACEMENT", "PLACEMENT",
                         "placement failed before routing; inspect placement legality diagnostics")
    pre_routing = _router2_diag.detect_pre_routing_failure(record.log)
    if pre_routing is not None:
        stage = pre_routing.stage.upper()
        return Signature(stage, stage, "%s failed before routing: %s" % (
            pre_routing.stage, pre_routing.reason or pre_routing.raw))
    return Signature("OTHER", "OTHER", "implementation did not complete (failure stage undetermined)")


def summarize_ladder(records: List[AttemptRecord]) -> Optional[LadderSummary]:
    """Summarise every attempt actually run, most-recurring failure first.

    Returns ``None`` for an empty ``records`` list (nothing ran; never crashes). Never raises for
    any input: a malformed/empty log on any record degrades to an ``OTHER`` signature rather than
    an exception, matching ``router2_diagnostics``'s "never crash a build" contract.
    """
    if not records:
        return None
    succeeded = any(r.outcome == SUCCESS for r in records)
    success_index = next((r.index for r in records if r.outcome == SUCCESS), None)
    failing = [r for r in records if r.outcome != SUCCESS]

    sig_by_index: Dict[int, Signature] = {}
    signature_attempts: Dict[Signature, List[int]] = {}
    counts: "Counter[Signature]" = Counter()
    for r in failing:
        try:
            sig = _signature_for(r)
        except Exception:  # a diagnostic aid must never crash the build it is summarising
            sig = Signature("OTHER", "OTHER", "signature could not be determined")
        sig_by_index[r.index] = sig
        counts[sig] += 1
        signature_attempts.setdefault(sig, []).append(r.index)

    ordered = counts.most_common()  # stable for ties: first-seen order among equal counts
    all_distinct = len(failing) > 1 and bool(ordered) and all(c == 1 for _, c in ordered)

    representative = None
    if ordered:
        top_sig, _top_count = ordered[0]
        if not all_distinct:
            # The LAST attempt bearing the most-common signature: recurring evidence, not
            # whichever rung the ladder happened to stop on.
            for r in reversed(failing):
                if sig_by_index[r.index] == top_sig:
                    representative = r
                    break
        else:
            # No signature recurs -- nothing to prefer over the old "last attempt" contract, so
            # preserve it exactly rather than inventing a preference among equals.
            representative = failing[-1]

    representative_signature = sig_by_index.get(representative.index) if representative else None
    return LadderSummary(len(records), succeeded, success_index, ordered, signature_attempts,
                          representative, representative_signature, all_distinct)


def format_ladder_summary(summary: Optional[LadderSummary], attempts_dir: Optional[str] = None) -> Optional[str]:
    """Human-readable cross-attempt report, or ``None`` when there is nothing worth adding.

    Deliberately returns ``None`` (rather than a degenerate one-line block) whenever the ladder
    ran zero or one attempts, or succeeded outright: a single data point is not a distribution, and
    the caller's existing single-attempt printout already says everything there is to say. When
    more than one attempt failed, states plainly whether a signature recurred (and how strongly) or
    whether every attempt disagreed -- the latter is itself the finding, not a formatting failure.
    """
    if summary is None or summary.total == 0:
        return None
    if summary.total == 1:
        if summary.representative is None:
            return None  # the sole attempt succeeded; nothing to summarise
        return ("[build] escalation ladder: 1 attempt ran (no escalation was attempted) -- "
                "not enough attempts to identify a recurring failure signature.")
    if not summary.signature_counts:
        return None  # every attempt succeeded (should not reach here in practice, but stay safe)

    lines = ["[build] escalation ladder: %d attempts, 0 routed to completion" % summary.total]
    if summary.all_distinct:
        lines.append(
            "[build] every failing attempt had a DIFFERENT terminal signature (%d distinct across "
            "%d attempts) -- no single arc recurs. This disagreement is itself the finding: the "
            "ladder's failure is unstable across cap/seed/fanout, not one reproducible arc."
            % (len(summary.signature_counts), summary.total))
    else:
        lines.append("[build] terminal failure signatures (most common first):")
        for sig, count in summary.signature_counts:
            idxs = summary.signature_attempts.get(sig, [])
            lines.append("    %dx  %s  (attempts %s)" %
                          (count, sig.detail, ", ".join(str(i) for i in idxs)))
    if summary.representative is not None and summary.representative_signature is not None:
        r = summary.representative
        rep_sig = summary.representative_signature
        rep_count = dict(summary.signature_counts).get(rep_sig, 1)
        failing_total = summary.total - (1 if summary.succeeded else 0)
        # ALWAYS describe the representative attempt using ITS OWN signature (never
        # signature_counts[0]) -- when every attempt disagrees, the most-common entry by
        # insertion order is not necessarily the one the representative (the last attempt) bears.
        qualifier = ("recurs %d/%d failing attempts" % (rep_count, failing_total)
                     if not summary.all_distinct else "last of %d disagreeing attempts" % summary.total)
        lines.append(
            "[build] most representative failure (%s): %s, attempt %d (cap=%d seed=%s fanout=%s)"
            % (qualifier, rep_sig.detail, r.index, r.cap, r.seed,
               "off" if r.fanout == 0 else str(r.fanout)))
    if attempts_dir:
        lines.append("[build] per-attempt logs: %s" % attempts_dir)
    return "\n".join(lines)
