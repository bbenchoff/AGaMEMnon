"""A registry of load-bearing CLAIMS, and a guard that keeps policies honest.

This project's gates, refusals and restrictions are not arbitrary -- every
one was added because of a specific, dated piece of evidence.  The recurring
failure is not that the gates are wrong; it is that **nothing tells a gate
when its evidence stops being true**.  The canonical instance: the 2026-08-13
conduction reframe retired the claim that the catalogued dead-edge list was
individually-measured per-edge silicon death, and ``AGAMEMNON_STRICT_GATE``
(``features/routing.py``) justified itself with exactly that retired claim
for eight more days before anyone noticed.  It cost the project roughly two
days of mis-directed work in that one instance alone.

``agamemnon.engine.selector_injectivity.KNOWN_DEFECTS`` is the working
prototype this generalises: a short, dated ledger entry per known problem,
with enforcement so the ledger cannot silently rot in either direction. This
module applies the same shape to CLAIMS -- the factual premises a policy
*rests on* -- rather than to defects a policy *tolerates*.

Mechanism, deliberately small:

* ``CLAIMS`` is a tuple of ``Claim`` records: a stable ``id``, the
  ``statement``, the ``evidence`` for and (where relevant) against it, and a
  ``status`` of ``"live"``, ``"disputed"`` or ``"retired"``.  A retired claim
  must record ``retired_on`` and ``retired_by``.
* A policy cites a claim with a **one-line comment**, anywhere in its
  neighbourhood: ``# CLAIM: <id>`` (or ``// CLAIM: <id>`` in C++).  That is
  the entire integration cost -- no import, no decorator, no runtime check in
  the gate itself.  This is deliberate: Design constraint from the task that
  created this module is "if citing a claim is burdensome, nobody will."
* ``audit()`` / ``enforce()`` scan the known annotated files for that comment
  and resolve every citation against ``CLAIMS``.  A citation to a claim that
  does not exist, or that is ``"retired"``, is an error.  A citation to a
  ``"live"`` or ``"disputed"`` claim is fine -- ``"disputed"`` exists so a
  policy can honestly cite contested ground without either lying (calling it
  settled) or being forced to silence (deleting the citation).
* ``tests/test_gate_claims.py`` is what actually runs the audit; nothing in
  this module is wired into any build path, by design (see below).

Fails closed on a MISSING or RETIRED citation, never on the ABSENCE of one:
a gate with no ``CLAIM:`` comment is simply outside this audit's view, not a
violation. That asymmetry is what makes adoption incremental instead of a
rewrite: only the handful of gates worth annotating carry the cost, and nothing
else in the codebase has to change to keep passing.

Zero functional change: nothing here alters what any gate does.  Whether a
gate's behaviour should change because its claim moved is a decision for a
person, made once, deliberately -- this module only makes the question askable
before it costs another two days.

--------------------------------------------------------------------------
Worked example: a claim that must be SPLIT, not merely re-dated
--------------------------------------------------------------------------

The conduction reframe is also the reason ``status`` is not a single flag on
one claim covering "the dead-edge story".  Two premises were conflated, and
conflating them was wrong in BOTH directions during this module's own
authoring session:

1. "The 14 catalogued rows in ``dead_edges_silicon.csv`` are real, individual,
   per-edge silicon deaths" -- this is what 2026-08-13 retired.  All 14 rows
   were shown to conduct in clean/isolated builds; the file is now
   header-only.  See ``dead-edge-catalogue-2026``.
2. "An edge needs a per-position conduction witness before the router may
   trust it for emission" -- a broader admission POLICY that sits next to the
   catalogue but does not depend on any specific row in it.  This was
   RE-CONFIRMED on silicon on 2026-08-21, the same day this module was
   written: an A/B build on identical RTL showed the tiered admission graph
   (which admits edges with no conduction witness, only a certain codeword)
   reads back WRONG on live silicon where the strict graph reads back
   correct.  See ``per-position-conduction-witness-required``.

The first draft of this task's own brief stated the reframe as one claim and
retired it wholesale -- which would have made ``STRICT_GATE`` cite a "dead"
claim for a reason that is, in fact, still live and independently
re-confirmed.  A registry that cannot represent "retire exactly the part that
died" reproduces the conflation it exists to catch.  ``see_also`` on both
entries below records the split explicitly, for exactly this reason.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass


ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

_VALID_STATUS = ("live", "disputed", "retired")


class ClaimLedgerError(ValueError):
    """A policy cites a claim that does not exist, or that has been retired."""


@dataclass(frozen=True)
class Claim:
    """One factual premise that a gate, refusal or restriction depends on.

    ``status``:
        live      -- believed true today; a policy may rest on it.
        disputed  -- real evidence exists on more than one side and the
                     question is not settled; a policy may still cite it --
                     the citation records the ground as contested, it does
                     not assert the claim is safe.
        retired   -- superseded by later evidence.  No live policy may cite
                     it; ``retired_on``/``retired_by`` are then mandatory.
    """

    id: str
    statement: str
    evidence: str
    status: str
    retired_on: str = ""
    retired_by: str = ""
    see_also: tuple[str, ...] = ()

    def __post_init__(self):
        if self.status not in _VALID_STATUS:
            raise ValueError("%s: status must be one of %s, not %r"
                              % (self.id, _VALID_STATUS, self.status))
        if self.status == "retired" and not (self.retired_on and self.retired_by):
            raise ValueError(
                "%s: a retired claim must record retired_on and retired_by"
                % self.id)
        if not self.statement.strip() or not self.evidence.strip():
            raise ValueError(
                "%s: statement and evidence must not be empty" % self.id)


# --------------------------------------------------------------------------
# The seeded claims.  Every one below was verified against the code and data
# in this repo (and its AG32-Docs evidence) before being recorded here --
# none is a transcription of an unverified summary.
# --------------------------------------------------------------------------

CLAIMS = (
    Claim(
        id="dead-edge-catalogue-2026",
        statement=(
            "The 14 entries once catalogued in chipdb/dead_edges_silicon.csv "
            "are real, individually-measured per-edge silicon deaths -- "
            "specific (src, dst) pips that never conduct at that position, "
            "independent of the design or congestion context that exposed "
            "them."
        ),
        evidence=(
            "REFUTED on board evidence: all 14 catalogued edges were shown "
            "to conduct in clean/isolated builds (vendor-native, "
            "our-natural, and forced-through-the-exact-pip); the original "
            "failures all trace to one large, congested MCU-exit design and "
            "were mis-attributed to individual edges rather than to "
            "aggregate routing congestion. af.exe itself is conduction-blind "
            "and carries no per-edge model, so it never needed to avoid a "
            "'dead' edge -- the vendor designs that were checked simply "
            "never generated the long, congested routing that lands on a "
            "marginal one. AG32-Docs CLAUDE.md, 'The conduction reframe' "
            "(dated 2026-08-13). Verified independently by this task "
            "2026-08-21: AGaMEMnon agamemnon/chipdb/dead_edges_silicon.csv "
            "is 5 bytes, header-only ('edge' with no data rows)."
        ),
        status="retired",
        retired_on="2026-08-13",
        retired_by=(
            "the conduction reframe -- af.exe is conduction-blind and the "
            "catalogue was shown to be a congestion-context artifact, not "
            "per-edge electrical fact; all 14 rows board-proven conducting "
            "and removed"
        ),
        see_also=("per-position-conduction-witness-required",),
    ),
    Claim(
        id="per-position-conduction-witness-required",
        statement=(
            "An edge must carry a per-position conduction witness -- an "
            "observed vendor route, or membership in the silicon/corpus-"
            "mined CONDUCT set -- before the open router may trust it for "
            "emission. Without that witness, a position-agnostic closed-form "
            "guess (e.g. OMUX->IMUX tile-invariance, or the OMUX->RMUX "
            "closed form) can make a design route, emit, and simulate "
            "correctly, and still read back WRONG on live silicon."
        ),
        evidence=(
            "Re-confirmed on silicon 2026-08-21, independently of the "
            "retired catalogue above -- this claim does not depend on any "
            "specific row of dead_edges_silicon.csv. Identical RTL, "
            "identical board, SRAM-only, the only variable the admission "
            "graph: the default tiered graph (15 tier-2 edges admitted -- "
            "exact codeword, no conduction witness at that position -- 206 "
            "pips) read back a constant 0x3, WRONG, 8/8 samples; "
            "--release-strict (zero tier-2 edges, 187 pips) read back "
            "0x00000000, CORRECT, 8/8 samples. Reported to this task by the "
            "concurrent board-diagnosis agent mid-session; NOT "
            "independently reproduced here (no hardware access from this "
            "sandbox) -- recorded as reported, per this module's own rule "
            "not to re-litigate a claim, only to state its status and "
            "evidence honestly."
        ),
        status="live",
        see_also=("dead-edge-catalogue-2026",),
    ),
    Claim(
        id="xbar-conduction-even-slot-shape",
        statement=(
            "Every measured dead (zs, zd) pair in the intra-tile "
            "OMUX->IMUX crossbar involves an odd endpoint, so restricting "
            "ordinary (non-carry, non-pinpacked) cells to even z "
            "{0,2,...,14} is SUFFICIENT to guarantee every intra-tile "
            "crossbar link conducts. The converse does not hold -- most "
            "odd-touching pairs measure live (50 of 74) -- so the "
            "even-only rule is a safe but non-tight sufficient condition, "
            "not a description of exactly which pairs are dead."
        ),
        evidence=(
            "AG32-Docs tools/agamemnon/chipdb/xbar_conduction.csv: 80 "
            "measured (zs,zd) pairs, 6 dead, all 6 touching an odd endpoint "
            "-- (0,1) (0,5) (1,0) (1,5) (2,5) (0,9). AG32-Docs "
            "PLAN_VENDOR_PARITY.md, 'THE EVEN-SLOT REFINEMENT IS "
            "EVIDENCE-BACKED AND STRICTLY BETTER' (2026-08-21) draws the "
            "same conclusion from the same file. "
            "VERIFICATION GAP found by this task (2026-08-21): "
            "xbar_conduction.csv is NOT shipped in "
            "AGaMEMnon/agamemnon/chipdb/ -- confirmed absent by directly "
            "listing that directory; only AG32-Docs/tools/agamemnon/chipdb/ "
            "has it. The rule is not shown wrong by this -- it is shown "
            "UNVERIFIABLE from this repo alone, which is its own instance "
            "of the defect class this ledger exists to surface: a policy "
            "citing evidence that a reader of AGaMEMnon by itself cannot "
            "check."
        ),
        status="live",
    ),
    Claim(
        id="direct-d-four-site-pool-is-hardware-limit",
        statement=(
            "Own-Q ('direct-D') registered feedback is safely usable, in a "
            "general auto-placed design, only at the four silicon-qualified "
            "sites X14Y11_SLICE4..7; using it at any other site is an open, "
            "un-derisked hardware question, so a design needing more "
            "simultaneous own-Q cells must externally buffer the extra ones "
            "rather than widen the pool."
        ),
        evidence=(
            "FOR: agamemnon/engine/qin_pack.py, "
            "externalize_multi_selffb() docstring -- widening the pool "
            "'requires new per-site silicon qualification, which is out of "
            "scope here'; no other site has been silicon-qualified for "
            "direct-D to date. "
            "AGAINST: AG32-Docs tools/wide_boundary_witness/"
            "witness_macro.vqm -- af.exe's own packed netlist for its "
            "409-LUT/202-register, 119.474 MHz build -- contains ZERO "
            "identity/passthrough LUT masks among all 409 cells inspected: "
            "the vendor routes own-Q feedback directly, device-wide, with "
            "no site restriction and no buffering at all. AG32-Docs "
            "PLAN_VENDOR_PARITY.md (2026-08-21) draws the direct "
            "conclusion: 'X14Y11_SLICE4..7 is a coverage boundary, not a "
            "hardware one.' "
            "UNRESOLVED ON OUR OWN SILICON: the 2026-08-21 board campaign "
            "to test additional candidate direct-D sites was INCONCLUSIVE "
            "-- its own positive control failed (a plain 4-bit counter "
            "with zero direct-D content read back the same constant as the "
            "qualified pool), an AHB-readback apparatus fault unrelated to "
            "direct-D itself. AG32-Docs docs/TASK_QUEUE.md Queue J: J1 "
            "(fix the readback) gates J3 (the direct-D campaign) -- so "
            "this claim has real evidence pointing both ways and no clean "
            "board result yet decides it."
        ),
        status="disputed",
    ),
    Claim(
        id="mcu-ahb-request-control-shared-source-oracle",
        statement=(
            "The 11 fabric-master AHB request-control qualifier bits "
            "(HSEL, HREADY, HTRANS[0:1], HSIZE[0:2], HBURST[0:2], HWRITE) "
            "have complete exact routes and typed strict-open bindings -- "
            "but this was established by ONE oracle build in which all 11 "
            "lanes share a SINGLE retained-LUT source "
            "(X14Y12_OMUX02 -> X14Y12_RMUX21 -> X14Y10_RMUX86). It proves a "
            "conflict-free simultaneous ROUTE TREE for one shared driver, "
            "NOT independent sources or bus semantics. No build should "
            "assert HSEL or a non-idle HTRANS from independently-driven "
            "logic until an independently-sourced oracle exists."
        ),
        evidence=(
            "AG32-Docs docs/re/FABRIC_AHB_MASTER_REQUEST_CONTROL_RECOVERY.md, "
            "verbatim: 'Do not infer that the qualifiers can yet be driven "
            "independently.' AGaMEMnon agamemnon/engine/features/mcu_ahb.py, "
            "the comment directly above ``_slave_request_bits``: 'The "
            "oracle uses one retained LUT as a shared source for all 11 "
            "sinks, proving a conflict-free simultaneous route tree without "
            "yet claiming independent sources or bus semantics.' Both "
            "sources agree and both are already honest about the "
            "limitation -- this entry exists so a future caller of this "
            "table cannot silently drop the caveat while the table itself "
            "keeps shipping."
        ),
        status="live",
    ),
    Claim(
        id="fitted-wire-timing-rmux-clkmux-bufmux-2026",
        statement=(
            "The RMUX, ClkMUX and BufMUX worst-case routing-delay charges in "
            "wire_timing_worst.json (1.175, 0.205 and 1.000 ns) are real "
            "over-charges for this design: NNLS-fitted per-family delays "
            "against af.exe's own static timing analysis put them at 0.336, "
            "0.133 and 0.534 ns respectively (3.50x, 1.54x and 1.87x lower). "
            "These three families -- and ONLY these three -- may be routed at "
            "the measured value instead of worst-case; every other family "
            "(collinear, n=1, or zero-observation) must stay on worst-case "
            "because the fit cannot separate or does not cover them."
        ),
        evidence=(
            "AG32-Docs tools/wire_timing_fit/wire_timing_fit_results.json: "
            "NNLS fit over 331 unique attributed hop-pairs from af.exe/Quartus "
            "setup.rpt (11,139 raw inter-cell hops, 93.6% raw / 89.0% unique "
            "attribution rate) joined to route_tx_decoded.txt; R^2=0.995, mean "
            "abs residual 0.018 ns, max abs residual 0.153 ns. Self-validating: "
            "the 21 pure single-OMUX+single-IMUX 2-hop chains measure "
            "0.383-0.401 ns (median 0.401), matching the independently-pinned "
            "wire_timing_exact_safe.json ground truth (0.401 ns) exactly -- the "
            "one family pair with ground truth, and the fit reproduces it. "
            "OMUX/IMUX are collinear (corr=0.99) and SeamMUX/TileClkMUX are "
            "collinear (corr=1.00), so their individual splits are not "
            "identifiable from this data and both pairs are deliberately left "
            "on worst-case; PllClkInMUX and InputMUX have n=1 equation and are "
            "also left on worst-case; 62 further families have zero "
            "observations in this design and are unaffected. SCOPE CAVEAT, "
            "load-bearing: this is ONE af.exe build (AG32-Docs "
            "tools/wide_boundary_witness, witness_macro, scored 119.474 MHz), "
            "ONE part (AGRV2KL48), ONE PVT corner -- evidence, not a "
            "characterisation. AG32-Docs docs/TASK_QUEUE.md Queue J task J2."
        ),
        status="live",
    ),
)

BY_ID = {claim.id: claim for claim in CLAIMS}
if len(BY_ID) != len(CLAIMS):
    raise ValueError("duplicate id in CLAIMS")
for _claim in CLAIMS:
    for _other in _claim.see_also:
        if _other not in BY_ID:
            raise ValueError(
                "%s: see_also references unknown claim %r" % (_claim.id, _other))


# --------------------------------------------------------------------------
# Citation syntax and resolution
# --------------------------------------------------------------------------

CITATION = re.compile(r"CLAIM:\s*([A-Za-z][A-Za-z0-9_-]*)")


def citations_in_text(text):
    """``[(line_no, claim_id), ...]`` for every ``CLAIM: <id>`` in ``text``."""
    found = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in CITATION.finditer(line):
            found.append((line_no, match.group(1)))
    return found


def citations_in_file(path):
    with open(path, encoding="utf-8", errors="replace") as stream:
        return citations_in_text(stream.read())


def check_citation(claim_id):
    """Return the ``Claim`` named ``claim_id``, or raise ``ClaimLedgerError``.

    Fails closed on exactly two conditions: the id is not registered at all
    (unknown/typo'd), or the claim it names is retired. ``"live"`` and
    ``"disputed"`` both pass -- a disputed claim is honestly contested, not
    falsely settled, so citing it is not itself a defect.
    """
    claim = BY_ID.get(claim_id)
    if claim is None:
        raise ClaimLedgerError(
            "cites unknown claim %r -- add it to "
            "agamemnon.engine.gate_claims.CLAIMS, or fix a typo in the "
            "annotation" % claim_id)
    if claim.status == "retired":
        raise ClaimLedgerError(
            "cites claim %r, retired %s (%s): %s"
            % (claim_id, claim.retired_on, claim.retired_by, claim.statement))
    return claim


# The production files known to carry ``CLAIM:`` annotations today. A file
# with no annotation is simply outside this audit -- see the module
# docstring: an unannotated gate is not a violation, only a citation to
# something dead or unknown is. Extend this tuple when a new annotation is
# added elsewhere so the audit's coverage does not silently lag its data.
ANNOTATED_FILES = (
    "agamemnon/engine/features/routing.py",
    "agamemnon/engine/features/mcu_ahb.py",
    "agamemnon/engine/claim_policy.py",
    "agamemnon/engine/uarch/agrv2k/agrv2k.cc",
)


def audit(root=ROOT, files=ANNOTATED_FILES):
    """Every citation in ``files``, and a message for each one that fails.

    Returns ``(citations, errors)``: ``citations`` is
    ``[(file, line, claim_id), ...]`` for every annotation found, whether or
    not it resolves; ``errors`` is one formatted string per citation that
    ``check_citation()`` rejects. A clean tree has ``errors == []``.
    """
    root = os.path.abspath(root)
    citations = []
    errors = []
    for relative in files:
        path = os.path.join(root, relative)
        if not os.path.exists(path):
            continue
        for line_no, claim_id in citations_in_file(path):
            citations.append((relative, line_no, claim_id))
            try:
                check_citation(claim_id)
            except ClaimLedgerError as exc:
                errors.append("%s:%d: %s" % (relative, line_no, exc))
    return citations, errors


def enforce(root=ROOT, files=ANNOTATED_FILES):
    """Fail closed if any annotated policy cites a retired or unknown claim.

    Not wired into any build path today -- this module makes zero functional
    change to any gate; ``tests/test_gate_claims.py`` is what actually runs
    this check. Exposed as a function so a future preflight (or the release
    manifest, alongside ``selector_injectivity.enforce``) can adopt it
    without new plumbing.
    """
    _, errors = audit(root, files)
    if errors:
        raise ClaimLedgerError(
            "a policy cites a claim that is retired or does not exist:\n  "
            + "\n  ".join(errors)
        )
    return True
