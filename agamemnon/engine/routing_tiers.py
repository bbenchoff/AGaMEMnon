"""Three-tier routing admission and the per-build routing-confidence manifest.

Background
----------
Until 2026-08-20 the router's device graph was admitted through a **binary**
fail-closed gate: an edge survived only if some positive record witnessed it
*at its exact position* (``AGAMEMNON_STRICT_GATE``).  Everything else was
dropped silently and the user was told nothing beyond an aggregate count.

That gate conflates two entirely different questions:

1. **Does this edge conduct?**  Answered by silicon sweeps
   (``master_/ff2_/harvest_conduction.csv``) or by a vendor route that used the
   hop (``corpus_conduction.csv`` / ``source=="observed"``).
2. **Do we know the codeword that programs this mux input?**  Answered by the
   block-clean selector corpus (``sel_edge_pairs.agdb``) -- either an exact
   physical observation of this very edge, or a tile-relative key on which
   *every* physical observation agrees.

Conflating them makes the gate simultaneously too strict and no safer.  Too
strict, because an edge whose codeword is known exactly is refused merely for
never having been watched conduct -- and ``af.exe``, the vendor tool we are
matching, carries no conduction model at all and routes such edges without
hesitation.  No safer, because the genuinely expensive failure in this
project's history is not "an edge that did not conduct"; it is **emitting the
wrong codeword**, which produces a plausible bitstream that config-accepts and
misbehaves (the transposed ``BBMUXE_PAIR`` rows that stalled three campaigns;
the silent selector lookup misses).

So the model splits along the axis that actually predicts harm:

======================  =========================================  ==================
tier                    criterion                                  behaviour
======================  =========================================  ==================
``witnessed``           conduction evidence at the exact position  admit, silent
``encoding-certain``    no conduction witness, but the selector    admit + manifest
                        codeword is certain: an exact observation, a
                        unanimous relative key, or a closed form
                        validated against every observation of its
                        class
``encoding-ambiguous``  selector key conflicts, or no clean-sel    refuse, always
                        evidence -- emission could write a WRONG
                        codeword
======================  =========================================  ==================

Tier 3 stays closed **unconditionally**, including for edges with perfect
conduction evidence: knowing that copper joins A to B is no help if we would
program the mux to select C.

Tier 2 is not a silent widening.  Every tier-2 edge the final route actually
uses is recorded in a per-build *confidence manifest* naming the edge, the
selector evidence that justifies it, and the one row that would promote it to
tier 1.  The vendor gives its users neither the gate nor the disclosure; this
gives them the capability *and* the disclosure, and the manifest doubles as a
work queue for the design-level witnessing rig.

What lives here
---------------
* the tier vocabulary and the selector-certainty predicate
  (:class:`SelectorCertainty`), used by ``features/routing.py`` while it builds
  the RRG;
* the device-database **sidecar** (:data:`SIDECAR`) that records every admitted
  tier-2 pip so a later build step can identify them by pip name alone;
* the manifest builder/renderer consumed by the CLI after place-and-route.

Nothing in this module reads or writes ``agamemnon/chipdb`` -- it is policy and
reporting over evidence other modules already load.
"""

from __future__ import annotations

import collections
import csv
import json
import os

from agamemnon.engine import mesh_template


TIER_WITNESSED = "witnessed"
TIER_ENCODING_CERTAIN = "encoding-certain"
TIER_AMBIGUOUS = "encoding-ambiguous"

TIERS = (TIER_WITNESSED, TIER_ENCODING_CERTAIN, TIER_AMBIGUOUS)

#: Selector-evidence classes that make an edge tier-2 eligible.  Both are
#: *positive observations* recorded in ``sel_edge_pairs.agdb``; neither is a
#: prediction, a majority vote, or a closed form.  They are exactly the two
#: classes bitgen resolves without incrementing its ``predicted`` counter, so
#: an edge admitted on this basis cannot trip the emission-time selector gate.
BASIS_PHYSICAL = "clean-physical"
BASIS_RELATIVE = "unanimous-relative"
#: A third class, and on the evidence the strongest of the three for the
#: codeword question: a tile-invariant closed form that reproduces *every*
#: physical observation of its class in ``sel_edge_pairs.agdb`` with zero
#: counterexamples.  ``tests/test_routing_tiers.py`` re-measures both forms
#: against the shipped corpus on every run, so this claim cannot rot silently.
#: Measured 2026-08-20: intra-tile OMUX[3z+1]->IMUX 65,902/65,902 exact;
#: RMUX<-OMUX 37,552/37,552 exact.  A third closed form used deep in bitgen's
#: fallback chain (intra-tile IMUX<-RMUX) scores 126,180 exact against **51
#: mismatches** and is deliberately NOT admitted here -- that difference is the
#: whole reason this is a measurement and not an assumption.
BASIS_CLOSED_FORM = "byte-exact-closed-form"

#: Written into the emitted device-database directory next to ``dev_pips.csv``.
SIDECAR = "routing_tier_manifest.csv"
SIDECAR_META = "routing_tier_manifest.json"

SIDECAR_FIELDS = (
    "pip", "tier", "basis",
    "src_x", "src_y", "src_res", "dst_x", "dst_y", "dst_res",
    "sel_lo", "sel_hi", "support", "witness_positions",
)

#: Environment variable through which ``emit_uarch_db.py`` tells the
#: architecture generator where to drop the sidecar.  It is deliberately *not*
#: part of the device-database cache fingerprint: it names an output location,
#: not an input, and folding a path into the fingerprint would invalidate every
#: cache whenever the build directory moved.
SIDECAR_ENV = "AGAMEMNON_TIER_SIDECAR"


#: ``(dx, dy)`` deltas over which the RMUX<-OMUX closed form has actually been
#: observed.  The form is index arithmetic that would happily produce an answer
#: for any delta, but every one of the 37,552 confirming observations is a
#: same-tile or one-tile-east hop, so tier 2 does not extrapolate past them.
_RMUX_FROM_OMUX_DELTAS = frozenset({(0, 0), (1, 0)})


def closed_form_selector(dst_fam, dst_idx, src_fam, src_idx, dx, dy):
    """LOCAL ``(lo, hi)`` from a byte-exact closed form, or None.

    Only the two forms validated at 100% against the shipped clean-sel corpus
    are implemented.  Both are pure index arithmetic over the regular fabric --
    a switchbox and a connection box, exactly as in any other FPGA -- which is
    why they generalise to positions the corpus never sampled while a majority
    vote over observations does not.
    """
    if (dst_fam == "IMUX" and src_fam == "OMUX" and dx == 0 and dy == 0
            and (src_idx - 1) % 3 == 0):
        # Connection box: source slice z = (src-1)//3, dest slice d = dst//4.
        return mesh_template._xbar_omux_imux_local(src_idx, dst_idx)
    if dst_fam == "RMUX" and src_fam == "OMUX" and (dx, dy) in _RMUX_FROM_OMUX_DELTAS:
        return ((src_idx // 3) % 4, 7)
    return None


def closed_form_is_legal_fanin(dst_fam, dst_idx, pair):
    """Cross-check a closed-form codeword against the decoded tile template.

    This is a weak guard in practice -- the template's fan-in for RMUX and IMUX
    instances is currently complete (every sel in the block is listed), so it
    rejects nothing today.  It is retained because it is the only check that
    comes from a *different* source file than the corpus the form was fitted
    to, and it would fire immediately if either the form or the template moved.
    Do not read a pass here as independent confirmation.
    """
    if dst_fam not in mesh_template.BS:
        return False
    instance, group_offset = mesh_template.instance_of(dst_fam, dst_idx)
    block = group_offset * mesh_template.BS[dst_fam]
    legal = mesh_template.legal_sels(dst_fam, instance)
    if not legal:
        return False
    return all(block + local in legal for local in pair)


class SelectorCertainty:
    """Decides whether an edge's selector codeword is *unambiguously known*.

    Constructed from the two tables ``features/routing.py`` already loads for
    ``AGAMEMNON_CLEAN_SEL_GATE``:

    ``clean_edge``
        exact physical ``(dx, dy, dfam, didx, sfam, sx, sy, sidx) -> (lo, hi)``
        observations, each already required to be conflict-free within its
        destination node's independent selector block.
    ``relative_edge``
        tile-relative keys promoted only when *every* physical occurrence
        agrees.  ``routing_selectors.relative_edges`` deletes a key outright on
        the first disagreement, so a surviving key is unanimous by
        construction; the rejected keys are the ``rel-key-CONFLICT`` class the
        campaign notes name, and they are never tier-2 eligible.

    Support counts and sample witness positions come from ``clean_edge`` and
    are reported in the manifest so a reader can judge *how much* agreement
    stands behind a relative key rather than taking "unanimous" on faith.
    A key with a single supporting observation is unanimous in the same formal
    sense as one with 158, and the manifest must not hide that difference.
    """

    def __init__(self, clean_edge, relative_edge, relative_conflicts=(),
                 allow_closed_form=True):
        self.clean_edge = clean_edge or {}
        self.relative_edge = relative_edge or {}
        self.relative_conflicts = frozenset(relative_conflicts or ())
        self._allow_closed_form = bool(allow_closed_form)
        self._support = collections.Counter()
        self._positions = collections.defaultdict(list)
        for (dx, dy, df, di, sf, sx, sy, si) in self.clean_edge:
            key = (df, di, sf, si, dx - sx, dy - sy)
            self._support[key] += 1
            if len(self._positions[key]) < 4:
                self._positions[key].append("X%dY%d" % (dx, dy))
        # How many physical observations each closed form is confirmed by, so
        # the manifest can state the strength of the claim rather than the bare
        # word "closed form".
        self.closed_form_support = collections.Counter()
        for (dx, dy, df, di, sf, sx, sy, si) in self.clean_edge:
            if closed_form_selector(df, di, sf, si, dx - sx, dy - sy) is not None:
                self.closed_form_support[(df, sf)] += 1

    def closed_form(self, df, di, sf, si, dx, dy):
        if not self._allow_closed_form:
            return None
        pair = closed_form_selector(df, di, sf, si, dx, dy)
        if pair is None or not closed_form_is_legal_fanin(df, di, pair):
            return None
        return pair

    @staticmethod
    def edge_key(row, family):
        """``(dx, dy, dfam, didx, sfam, sx, sy, sidx)`` for a chipdb edge row."""
        df, sf = family(row["dst_res"]), family(row["src_res"])
        try:
            return (int(row["dst_x"]), int(row["dst_y"]), df,
                    int(row["dst_res"][len(df):]), sf,
                    int(row["src_x"]), int(row["src_y"]),
                    int(row["src_res"][len(sf):]))
        except (TypeError, ValueError):
            return None

    def classify(self, row, family):
        """Return the selector basis for ``row`` or None if it is ambiguous.

        None means tier 3.  It covers three genuinely different situations that
        share one correct response -- refuse:

        * the relative key exists but **conflicts** across positions;
        * no clean-sel observation of this shape exists at all;
        * the edge is not a mesh RMUX/IMUX hop, so this table says nothing
          about it.  A table that is silent about an edge has not certified it,
          and the whole point of tier 2 is that admission rests on a positive
          record rather than on the absence of a negative one.
        """
        key = self.edge_key(row, family)
        if key is None:
            return None
        dx, dy, df, di, sf, sx, sy, si = key
        if df not in ("RMUX", "IMUX") or sf not in ("RMUX", "OMUX"):
            return None
        pair = self.clean_edge.get(key)
        if pair is not None:
            return {
                "basis": BASIS_PHYSICAL,
                "sel": tuple(pair),
                "support": 1,
                "positions": ["X%dY%d" % (dx, dy)],
            }
        relative_key = (df, di, sf, si, dx - sx, dy - sy)
        pair = self.relative_edge.get(relative_key)
        if pair is not None:
            return {
                "basis": BASIS_RELATIVE,
                "sel": tuple(pair),
                "support": int(self._support.get(relative_key, 0)),
                "positions": list(self._positions.get(relative_key, ())),
            }
        if relative_key in self.relative_conflicts:
            # Explicitly do NOT fall through to the closed form here. A key the
            # corpus disagrees with itself about is the one place a tidy formula
            # is most tempting and least trustworthy: the observations say the
            # answer is position-dependent, so a position-independent form
            # cannot be the whole story for it.
            return None
        pair = self.closed_form(df, di, sf, si, dx - sx, dy - sy)
        if pair is None:
            return None
        return {
            "basis": BASIS_CLOSED_FORM,
            "sel": tuple(pair),
            "support": self.closed_form_support.get((df, sf), 0),
            "positions": [],
        }


# ---------------------------------------------------------------------------
# device-database sidecar
# ---------------------------------------------------------------------------

class ClaimRecordingPipSet(set):
    """A ``seen_pips`` set that remembers which pip names were asked about.

    Every architecture block that supplies a pip of its own guards it with
    ``if name in seen_pip: continue`` before adding, so a membership query IS a
    block declaring "I would have supplied this edge". That makes the query the
    exact signal the tier model needs and costs the other features nothing: a
    hand-maintained list of which blocks own which pips would be wrong the first
    time someone added a block, and wrong silently.

    Why it matters: those blocks run in every admission model. Under
    release-strict the pip arrives from the block; under the tiered model the
    mesh loop may have claimed the same name first. Without this the manifest
    would list edges that a release-strict build uses too, and its central
    promise -- "this is what --release-strict would refuse" -- would be false.
    """

    def __init__(self, existing=()):
        super().__init__(existing)
        self.claimed = set()

    def __contains__(self, item):
        self.claimed.add(item)
        return super().__contains__(item)


def sidecar_directory():
    """The emitted device-database directory, or None when not emitting one."""
    target = os.environ.get(SIDECAR_ENV)
    return target or None


def write_sidecar(directory, rows, meta):
    """Record every admitted tier-2 pip beside the device database.

    Keyed by pip name because that is the only identifier the routed netlist
    carries; the join at report time is therefore exact rather than
    reconstructed from coordinates.
    """
    if not directory:
        return 0
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, SIDECAR)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SIDECAR_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    with open(os.path.join(directory, SIDECAR_META), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return len(rows)


def load_sidecar(directory):
    """Return ``{pip_name: record}`` for the tier-2 edges in a device database.

    An absent sidecar means the database was built release-strict (no tier-2
    admission happened), which is a legitimate state and not an error.
    """
    if not directory:
        return {}
    path = os.path.join(directory, SIDECAR)
    if not os.path.isfile(path):
        return {}
    table = {}
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            table[row["pip"]] = row
    return table


def load_sidecar_meta(directory):
    if not directory:
        return {}
    path = os.path.join(directory, SIDECAR_META)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# per-build confidence manifest
# ---------------------------------------------------------------------------

def routed_pips(module):
    """``{pip_name: sorted[net names]}`` for one routed nextpnr module.

    nextpnr writes each net's route as a ``;``-separated triple stream
    ``wire;pip;delay``; the pip field is empty for the driving wire.  Reading
    the pip names directly (rather than re-deriving them from wire pairs) keeps
    this identical to what bitgen encodes.
    """
    used = collections.defaultdict(set)
    for net_name, net in (module.get("netnames") or {}).items():
        route = (net.get("attributes") or {}).get("ROUTING")
        if not route:
            continue
        fields = route.split(";")
        for index in range(1, len(fields), 3):
            pip = fields[index].strip()
            if pip:
                used[pip].add(net_name)
    return {pip: sorted(nets) for pip, nets in used.items()}


def _promotion(record):
    """The concrete evidence that would move one tier-2 edge to tier 1.

    Deliberately spelled as a row a person or a rig can actually produce, not
    as advice.  ``corpus_conduction.csv`` is listed first because it is the
    cheapest: re-mining any vendor ``route.tx`` that happens to use the hop
    yields exactly this row, and it is how the neighbouring ``X14Y10_RMUX86``
    feeds entered the trusted set in the first place.
    """
    row = "%s,%s,%s,%s,%s,%s" % (
        record["src_res"], record["src_x"], record["src_y"],
        record["dst_res"], record["dst_x"], record["dst_y"],
    )
    return {
        "status": "no conduction witness at this position",
        "cheapest": {
            "file": "agamemnon/chipdb/corpus_conduction.csv",
            "row": row + ",corpus_route",
            "how": "mine a vendor route.tx that uses this hop (tools/mine_corpus.py)",
        },
        "alternatives": [
            {
                "file": "agamemnon/chipdb/harvest_conduction.csv",
                "row": row + ",silicon_harvest",
                "how": "design-level witnessing rig: a self-checking design whose "
                       "routed JSON binds this pip and whose lane reads back correct",
            },
            {
                "file": "agamemnon/chipdb/master_conduction.csv",
                "row": row + ",silicon",
                "how": "directed FF->dout conduction sweep at this exact position",
            },
            {
                "file": "agamemnon/chipdb/routing_selector_admission.json",
                "row": "reviewed experimental admission row for this exact edge",
                "how": "explicit human review; records approval, not measurement",
            },
        ],
    }


def build_manifest(*, routed_module, sidecar, sidecar_meta, design, output,
                   device, devdb, admission_model, extra=None):
    """Assemble the confidence manifest for one completed build."""
    used = routed_pips(routed_module)
    tier2 = []
    net_index = collections.Counter()
    for pip in sorted(used):
        record = sidecar.get(pip)
        if record is None:
            continue
        nets = used[pip]
        for net in nets:
            net_index[net] += 1
        support = int(record.get("support") or 0)
        positions = [p for p in (record.get("witness_positions") or "").split("|") if p]
        tier2.append({
            "pip": pip,
            "source": {"x": int(record["src_x"]), "y": int(record["src_y"]),
                       "resource": record["src_res"]},
            "destination": {"x": int(record["dst_x"]), "y": int(record["dst_y"]),
                            "resource": record["dst_res"]},
            "programmed_at_tile": "X%sY%s" % (record["dst_x"], record["dst_y"]),
            "selector": {
                "basis": record["basis"],
                "codeword": [int(record["sel_lo"]), int(record["sel_hi"])],
                "agreeing_physical_observations": support,
                "observed_at": positions,
                "conflicting_observations": 0,
            },
            "used_by_nets": nets,
            "promotion": _promotion(record),
        })

    queue = sorted(
        tier2,
        key=lambda item: (-len(item["used_by_nets"]),
                          item["selector"]["agreeing_physical_observations"],
                          item["pip"]),
    )
    total = len(used)
    manifest = {
        "schema": 1,
        "kind": "agamemnon-routing-confidence",
        "design": design,
        "output": output,
        "device": device,
        "device_database": os.path.basename(devdb or ""),
        "admission_model": admission_model,
        "tier_definitions": {
            TIER_WITNESSED:
                "conduction evidence at this exact position (vendor route hop, "
                "silicon sweep, or reviewed admission row)",
            TIER_ENCODING_CERTAIN:
                "no conduction witness here, but the selector codeword is a "
                "conflict-free physical observation or a unanimous tile-relative "
                "key -- the emitted bits are exact, the electrical behaviour is "
                "unverified at this position",
            TIER_AMBIGUOUS:
                "refused unconditionally: the selector key conflicts across "
                "positions or has no clean-sel evidence, so emission could write "
                "a codeword that selects a different mux input",
        },
        "summary": {
            "routed_pips": total,
            "tier_2_pips_used": len(tier2),
            "tier_1_or_unclassified_pips": total - len(tier2),
            "nets_touching_tier_2": len(net_index),
            "release_strict_clean": not tier2,
            "tier_2_available_in_graph": int(sidecar_meta.get("tier_2_admitted", 0) or 0),
            "tier_3_refused_in_graph": int(sidecar_meta.get("tier_3_refused", 0) or 0),
        },
        "verdict": _verdict(tier2, net_index, admission_model),
        "tier_2_edges": tier2,
        "promotion_queue": [
            {
                "pip": item["pip"],
                "nets": len(item["used_by_nets"]),
                "basis": item["selector"]["basis"],
                "add_row": item["promotion"]["cheapest"]["row"],
                "to_file": item["promotion"]["cheapest"]["file"],
            }
            for item in queue
        ],
    }
    if extra:
        manifest.update(extra)
    return manifest


def _verdict(tier2, net_index, admission_model):
    if admission_model == "release-strict":
        return ("release-strict: tier-2 admission was disabled, so every routed "
                "edge carries conduction evidence at its exact position.")
    if not tier2:
        return ("This build is release-strict clean: the tiered graph was "
                "available but the router did not need a single "
                "encoding-certain edge. Rebuilding with --release-strict "
                "would produce the same route.")
    return (
        "%d routed edge(s) across %d net(s) are encoding-certain but not "
        "conduction-witnessed at their position. Their selector codewords are "
        "exact; what is unproven is that the wire conducts *here*. This build "
        "would be refused by --release-strict. Each entry below names the one "
        "row that would promote it." % (len(tier2), len(net_index))
    )


def render_summary(manifest, path=None):
    """Short, actionable stdout block.  The JSON carries the detail."""
    summary = manifest["summary"]
    lines = []
    if manifest["admission_model"] == "release-strict":
        lines.append("[confidence] release-strict: all %d routed edge(s) are "
                     "position-witnessed (tier 1)" % summary["routed_pips"])
        return lines
    if summary["release_strict_clean"]:
        lines.append("[confidence] tiered admission: all %d routed edge(s) are "
                     "position-witnessed (tier 1) -- release-strict clean"
                     % summary["routed_pips"])
        return lines
    lines.append(
        "[confidence] %d of %d routed edge(s) are tier-2 encoding-certain "
        "(exact codeword, no conduction witness at that position), touching "
        "%d net(s)" % (summary["tier_2_pips_used"], summary["routed_pips"],
                       summary["nets_touching_tier_2"]))
    for item in manifest["promotion_queue"][:5]:
        lines.append("[confidence]   %s  (%d net(s), %s)"
                     % (item["pip"], item["nets"], item["basis"]))
    remaining = len(manifest["promotion_queue"]) - 5
    if remaining > 0:
        lines.append("[confidence]   ... and %d more" % remaining)
    if path:
        lines.append("[confidence] manifest -> %s" % path)
    lines.append("[confidence] rebuild with --release-strict to refuse these "
                 "edges instead of reporting them")
    return lines


def write_manifest(path, manifest):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return path
