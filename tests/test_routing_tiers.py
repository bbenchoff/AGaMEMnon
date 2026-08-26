"""Three-tier routing admission: the model, and the measurements it rests on.

The interesting tests here are the ones that re-measure a claim rather than
assert a constant. ``AGAMEMNON_ROUTING_ADMISSION=tiered`` admits edges on the
strength of "this closed form reproduces every observation of its class", and
that sentence is only true until the corpus changes. So it is re-derived from
the shipped ``sel_edge_pairs.agdb`` on every run, and a single counterexample
fails the suite rather than quietly widening the graph.
"""
import collections
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from agamemnon.engine import routing_selectors, routing_tiers
from agamemnon.engine.features.routing import (
    BBMUXE_PAIR, BBMUXS_PAIR, _ambiguous_boundary_sources,
    ambiguous_boundary_sources, witnessed_boundary_sources,
)

ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def _family(resource):
    return re.match(r"[A-Za-z]+", resource).group(0)


@pytest.fixture(scope="module")
def clean_edges():
    return routing_selectors.load_clean_edges(str(CHIPDB))


@pytest.fixture(scope="module")
def certainty(clean_edges):
    relative, conflicts = routing_selectors.relative_edges(clean_edges)
    return routing_tiers.SelectorCertainty(clean_edges, relative, conflicts)


# ---------------------------------------------------------------------------
# the measurements the model rests on
# ---------------------------------------------------------------------------

def test_admitted_closed_forms_reproduce_every_observation_of_their_class(clean_edges):
    """Zero counterexamples, or the form is not admissible evidence.

    This is the whole justification for ``byte-exact-closed-form`` being a
    tier-2 basis: not "a closed form exists" but "it agrees with every single
    physical observation we hold". Both forms are index arithmetic over a
    regular fabric, so a mismatch would mean the arithmetic is wrong somewhere,
    and a wrong selector is the failure class this model exists to prevent.
    """
    agree = collections.Counter()
    disagree = []
    for (dx, dy, df, di, sf, sx, sy, si), pair in clean_edges.items():
        predicted = routing_tiers.closed_form_selector(
            df, di, sf, si, dx - sx, dy - sy)
        if predicted is None:
            continue
        if tuple(pair) == tuple(predicted):
            agree[(df, sf)] += 1
        else:
            disagree.append(((dx, dy, df, di, sf, sx, sy, si), tuple(pair), predicted))
    assert not disagree, disagree[:10]
    # Both forms must still be *covered* -- an empty measurement is not a pass.
    assert agree[("IMUX", "OMUX")] > 60000, agree
    assert agree[("RMUX", "OMUX")] > 30000, agree


def test_the_unadmitted_crossbar_closed_form_is_the_reason_this_is_measured():
    """bitgen's intra-tile IMUX<-RMUX closed form does NOT qualify, and must not.

    It is the control that gives the test above meaning. If every closed form
    in the engine agreed with the corpus, "validated byte-exact" would be an
    empty phrase; this one disagrees on tens of edges, so the distinction is
    real and the tier-2 basis is a filter rather than a rubber stamp.
    """
    clean = routing_selectors.load_clean_edges(str(CHIPDB))
    mismatches = 0
    for (dx, dy, df, di, sf, sx, sy, si), pair in clean.items():
        if df != "IMUX" or sf != "RMUX" or (dx, dy) != (sx, sy):
            continue
        index = (si // 6 + 11) % 27
        if tuple(pair) != (index % 9, 9 + index // 9):
            mismatches += 1
    assert mismatches > 0
    assert routing_tiers.closed_form_selector("IMUX", 0, "RMUX", 0, 0, 0) is None


def test_conflicting_relative_keys_are_never_rescued_by_a_closed_form(clean_edges):
    """A key the corpus disagrees with itself about stays refused.

    This is the ``rel-key-CONFLICT`` class. It is exactly where a tidy formula
    is most tempting and least trustworthy: the observations say the answer is
    position-dependent, so a position-independent form cannot be the whole
    story for it.
    """
    relative, conflicts = routing_selectors.relative_edges(clean_edges)
    assert conflicts, "no conflicting keys in the corpus -- the guard is untested"
    permissive = routing_tiers.SelectorCertainty(
        {}, {}, conflicts, allow_closed_form=True)
    rescued = []
    for (df, di, sf, si, ddx, ddy) in list(conflicts):
        if routing_tiers.closed_form_selector(df, di, sf, si, ddx, ddy) is None:
            continue
        row = {"dst_x": "5", "dst_y": "5", "dst_res": "%s%d" % (df, di),
               "src_x": str(5 - ddx), "src_y": str(5 - ddy),
               "src_res": "%s%d" % (sf, si)}
        if permissive.classify(row, _family) is not None:
            rescued.append((df, di, sf, si, ddx, ddy))
    assert not rescued, rescued[:10]


# ---------------------------------------------------------------------------
# the tier vocabulary
# ---------------------------------------------------------------------------

def test_certainty_prefers_the_most_specific_basis_available(certainty, clean_edges):
    key = next(iter(k for k in clean_edges
                    if k[2] == "RMUX" and k[4] == "RMUX"))
    dx, dy, df, di, sf, sx, sy, si = key
    row = {"dst_x": str(dx), "dst_y": str(dy), "dst_res": "%s%d" % (df, di),
           "src_x": str(sx), "src_y": str(sy), "src_res": "%s%d" % (sf, si)}
    basis = certainty.classify(row, _family)
    assert basis["basis"] == routing_tiers.BASIS_PHYSICAL
    assert tuple(basis["sel"]) == tuple(clean_edges[key])


def test_a_shape_the_tables_are_silent_about_is_refused(certainty):
    """Silence is not certification.

    ``BufMUX -> RMUX`` has no clean-sel model at all, so tier 2 must not admit
    it even though nothing negative is recorded about it either. The whole
    point is that admission rests on a positive record.
    """
    row = {"dst_x": "5", "dst_y": "5", "dst_res": "RMUX00",
           "src_x": "5", "src_y": "5", "src_res": "BufMUX03"}
    assert certainty.classify(row, _family) is None


def test_closed_form_is_not_extrapolated_past_its_observed_geometry():
    """RMUX <- OMUX is confirmed only for same-tile and one-east hops."""
    assert routing_tiers.closed_form_selector("RMUX", 5, "OMUX", 6, 0, 0) == (2, 7)
    assert routing_tiers.closed_form_selector("RMUX", 5, "OMUX", 6, 1, 0) == (2, 7)
    assert routing_tiers.closed_form_selector("RMUX", 5, "OMUX", 6, 0, 1) is None
    assert routing_tiers.closed_form_selector("RMUX", 5, "OMUX", 6, -1, 0) is None


def test_tables_only_mode_withholds_the_closed_forms(clean_edges):
    tables_only = routing_tiers.SelectorCertainty({}, {}, (), allow_closed_form=False)
    full = routing_tiers.SelectorCertainty({}, {}, (), allow_closed_form=True)
    row = {"dst_x": "5", "dst_y": "5", "dst_res": "IMUX00",
           "src_x": "5", "src_y": "5", "src_res": "OMUX01"}
    assert tables_only.classify(row, _family) is None
    assert full.classify(row, _family)["basis"] == routing_tiers.BASIS_CLOSED_FORM


# ---------------------------------------------------------------------------
# tier 3: the boundary-terminal codeword collision
# ---------------------------------------------------------------------------

def test_the_boundary_fallback_refuses_the_source_no_observation_backs():
    """Source index alone cannot name a boundary input; two families share it.

    ``BBMUXE_PAIR`` carries 14 sources over 12 codewords because the harvest it
    came from aggregated BBMUXE and BBMUXS with the family discarded: 25 and 92
    are SOUTH feeders misfiled east (AG32-Docs tools/bbmuxe_injectivity/, which
    validates the family-keyed tables 439/439 byte-exact across twelve vendor
    builds). Neither codeword is wrong; the key was. Consulting them for an east
    route would still write the word that selects a different input of that mux,
    so the guess is withdrawn for exactly the sources no observation backs.
    """
    witnessed = witnessed_boundary_sources(str(CHIPDB), "BBMUXE")
    assert len(witnessed) == 12
    assert len({tuple(BBMUXE_PAIR[index]) for index in witnessed}) == 12
    refused = ambiguous_boundary_sources(str(CHIPDB))
    assert refused["BBMUXE"] == frozenset({25, 92})
    assert refused["BBMUXS"] == frozenset()
    # ...and both misfiled indices are genuine SOUTH feeders carrying the same
    # codeword there. That is the corroboration that they are misfiled rather
    # than mistyped, and it is checkable from shipped code alone.
    assert BBMUXS_PAIR[25] == BBMUXE_PAIR[25]
    assert BBMUXS_PAIR[92] == BBMUXE_PAIR[92]


def test_the_south_bank_is_complete_and_injective():
    """The two feeders whose absence was refusing encodable routes.

    75 and 85 were missing from ``BBMUXS_PAIR``, so any route entering the south
    boundary through them failed for want of a codeword derivable two ways: the
    +24 offset law from shipped witnessed east rows, and an independent vendor
    bitstream recovery. With them the bank is twelve feeders over twelve words.
    """
    assert len(BBMUXS_PAIR) == 12
    assert len({tuple(v) for v in BBMUXS_PAIR.values()}) == 12
    assert BBMUXS_PAIR[75] == (2, 4) and BBMUXS_PAIR[85] == (2, 5)
    for index, codeword in BBMUXS_PAIR.items():
        assert tuple(codeword) == tuple(BBMUXE_PAIR[(index + 24) % 96]), index


def test_the_ambiguity_guard_is_derived_and_arbitrated_by_evidence():
    # no collision -> nothing refused
    assert _ambiguous_boundary_sources({1: (0, 4), 2: (0, 5)}) == frozenset()
    # collision with no witness on either side -> nobody can arbitrate
    assert _ambiguous_boundary_sources({1: (0, 4), 2: (0, 4)}) == frozenset({1, 2})
    # exactly one witnessed member keeps the word; the unbacked ones lose it
    assert _ambiguous_boundary_sources(
        {1: (0, 4), 2: (0, 4), 3: (0, 4)}, witnessed={2}) == frozenset({1, 3})
    # two witnessed members with one word is a real contradiction: refuse all
    assert _ambiguous_boundary_sources(
        {1: (0, 4), 2: (0, 4)}, witnessed={1, 2}) == frozenset({1, 2})
    # the conservative default matters: a caller without the tables refuses more
    assert _ambiguous_boundary_sources({1: (0, 4), 2: (0, 4)}) == frozenset({1, 2})


def test_a_witnessed_feeder_keeps_its_fallback_so_retained_artifacts_rebuild():
    """RMUX49 is in a colliding pair AND is witnessed twelve times over.

    An earlier cut of this guard refused both members of every colliding group
    and broke ``qualification/dual_carry3_routed.json``, which routes
    ``X14Y12_RMUX49 -> X13Y12_BBMUXE05`` through exactly this fallback. Refusing
    a well-evidenced codeword to punish an unevidenced one is not caution, it is
    a different way of being wrong.
    """
    refused = ambiguous_boundary_sources(str(CHIPDB))["BBMUXE"]
    assert 49 not in refused and 20 not in refused
    assert 25 in refused and 92 in refused


def test_no_shipped_boundary_edge_currently_depends_on_the_withdrawn_fallback():
    """The guard's blast radius today is zero, and that is worth pinning.

    A guard that costs nothing now but fires the day someone routes one of these
    entrances is the useful kind. If this ever fails, a real design has started
    depending on a codeword that names another input, and the right response is
    to land the family-keyed tables, not to relax the guard.
    """
    from agamemnon.engine.features.routing import exact_boundary_edges
    exact = exact_boundary_edges(str(CHIPDB), "BBMUXE")
    refused = ambiguous_boundary_sources(str(CHIPDB))["BBMUXE"]
    offenders = []
    with (CHIPDB / "rrg_edges_full.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("source") != "observed":
                continue
            if not row["dst_res"].startswith("BBMUXE"):
                continue
            match = re.fullmatch(r"RMUX0*([0-9]+)", row["src_res"])
            if not match or int(match.group(1)) not in refused:
                continue
            edge = "X%sY%s_%s.X%sY%s_%s" % (
                row["src_x"], row["src_y"], row["src_res"],
                row["dst_x"], row["dst_y"], row["dst_res"])
            if edge not in exact:
                offenders.append(edge)
    assert not offenders, offenders[:10]


# ---------------------------------------------------------------------------
# sidecar + manifest
# ---------------------------------------------------------------------------

def _sidecar_row(pip="X14Y9_RMUX13.X14Y10_RMUX49"):
    return {
        "pip": pip, "tier": routing_tiers.TIER_ENCODING_CERTAIN,
        "basis": routing_tiers.BASIS_RELATIVE,
        "src_x": "14", "src_y": "9", "src_res": "RMUX13",
        "dst_x": "14", "dst_y": "10", "dst_res": "RMUX49",
        "sel_lo": "2", "sel_hi": "7", "support": "37",
        "witness_positions": "X1Y1|X2Y3",
    }


def test_sidecar_round_trips(tmp_path):
    routing_tiers.write_sidecar(str(tmp_path), [_sidecar_row()], {"schema": 1})
    loaded = routing_tiers.load_sidecar(str(tmp_path))
    assert set(loaded) == {"X14Y9_RMUX13.X14Y10_RMUX49"}
    assert loaded["X14Y9_RMUX13.X14Y10_RMUX49"]["basis"] == routing_tiers.BASIS_RELATIVE
    assert routing_tiers.load_sidecar_meta(str(tmp_path))["schema"] == 1


def test_a_missing_sidecar_is_a_release_strict_database_not_an_error(tmp_path):
    assert routing_tiers.load_sidecar(str(tmp_path)) == {}
    assert routing_tiers.load_sidecar(None) == {}


def test_routed_pips_are_read_from_the_nextpnr_routing_attribute():
    module = {"netnames": {
        "n": {"attributes": {"ROUTING":
              "X14Y12_OMUX02;;1;X13Y10_BBMUXE00;X14Y10_RMUX49.X13Y10_BBMUXE00;5;"
              "X14Y10_RMUX49;X14Y9_RMUX13.X14Y10_RMUX49;5"}},
        "unrouted": {"attributes": {}},
    }}
    assert routing_tiers.routed_pips(module) == {
        "X14Y10_RMUX49.X13Y10_BBMUXE00": ["n"],
        "X14Y9_RMUX13.X14Y10_RMUX49": ["n"],
    }


def test_manifest_names_the_edge_the_evidence_and_the_promoting_row():
    module = {"netnames": {"s_hsel": {"attributes": {"ROUTING":
        "X14Y9_RMUX13;;1;X14Y10_RMUX49;X14Y9_RMUX13.X14Y10_RMUX49;5"}}}}
    manifest = routing_tiers.build_manifest(
        routed_module=module,
        sidecar={_sidecar_row()["pip"]: _sidecar_row()},
        sidecar_meta={"tier_2_admitted": 80348, "tier_3_refused": 4967},
        design="witness.v", output="/tmp/witness.bin", device="AGRV2KL48",
        devdb="/x/devdb_tiered", admission_model="tiered",
    )
    assert manifest["summary"]["tier_2_pips_used"] == 1
    assert manifest["summary"]["release_strict_clean"] is False
    edge = manifest["tier_2_edges"][0]
    assert edge["used_by_nets"] == ["s_hsel"]
    assert edge["selector"]["agreeing_physical_observations"] == 37
    assert edge["selector"]["codeword"] == [2, 7]
    # The promotion row must be a row, not a suggestion.
    row = edge["promotion"]["cheapest"]["row"]
    assert row == "RMUX13,14,9,RMUX49,14,10,corpus_route"
    header = (CHIPDB / "corpus_conduction.csv").read_text(
        encoding="utf-8").splitlines()[0]
    assert len(row.split(",")) == len(header.split(","))
    assert manifest["promotion_queue"][0]["pip"] == edge["pip"]


def test_a_build_that_needed_no_tier_two_edge_says_so():
    manifest = routing_tiers.build_manifest(
        routed_module={"netnames": {"n": {"attributes": {"ROUTING":
            "X1Y1_OMUX01;;1;X1Y1_IMUX00;X1Y1_OMUX01.X1Y1_IMUX00;5"}}}},
        sidecar={}, sidecar_meta={},
        design="d.v", output="d.bin", device="AGRV2KL48",
        devdb="devdb_tiered", admission_model="tiered",
    )
    assert manifest["summary"]["release_strict_clean"] is True
    assert "release-strict clean" in manifest["verdict"]
    assert any("release-strict clean" in line
               for line in routing_tiers.render_summary(manifest))


# ---------------------------------------------------------------------------
# end-to-end: the emitted device graphs
# ---------------------------------------------------------------------------

_STRICT_ENV = (
    "AGAMEMNON_CONDUCTION_GATE=1", "AGAMEMNON_HW_CARRY=1", "AGAMEMNON_LEDPADS=1",
    "AGAMEMNON_STRICT_GATE=1", "AGAMEMNON_XBAR_CONDUCT=1", "AGAMEMNON_CLEAN_SEL_GATE=1",
)


def _emit(out, extra=()):
    command = [sys.executable, str(ROOT / "agamemnon" / "engine" / "emit_uarch_db.py"),
               "--arch", str(ROOT / "agamemnon" / "engine" / "arch.py"),
               "--data", str(CHIPDB), "--out", str(out)]
    for item in tuple(_STRICT_ENV) + tuple(extra):
        command += ["--env", item]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    return result.stdout


@pytest.fixture(scope="module")
def emitted_graphs(tmp_path_factory):
    """Emit the strict and tiered device graphs once for the whole module.

    Each emission is ~30 s, so the end-to-end assertions share one pair rather
    than paying for it per test.
    """
    base = tmp_path_factory.mktemp("devdb")
    strict, tiered = base / "strict", base / "tiered"
    _emit(strict)
    _emit(tiered, ("AGAMEMNON_ROUTING_ADMISSION=tiered",))
    return strict, tiered


def test_release_strict_graph_is_unchanged_and_tiered_is_a_strict_superset(emitted_graphs):
    """The two properties that make the default flip safe to make.

    Byte-identity of the release-strict graph is the regression guard; superset
    is what lets "nothing that routes today stops routing" be a structural fact
    rather than a hope.
    """
    strict, tiered = emitted_graphs

    shipped = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"
    if (shipped / "dev_pips.csv").exists():
        assert (strict / "dev_pips.csv").read_bytes() == (shipped / "dev_pips.csv").read_bytes()
    assert not (strict / routing_tiers.SIDECAR).exists()

    def names(path):
        with (path / "dev_pips.csv").open(newline="", encoding="utf-8") as stream:
            return {row["name"] for row in csv.DictReader(stream)}
    strict_names, tiered_names = names(strict), names(tiered)
    assert not strict_names - tiered_names
    assert len(tiered_names) > len(strict_names)

    sidecar = routing_tiers.load_sidecar(str(tiered))
    assert set(sidecar) == tiered_names - strict_names
    assert all(row["tier"] == routing_tiers.TIER_ENCODING_CERTAIN
               for row in sidecar.values())
    meta = routing_tiers.load_sidecar_meta(str(tiered))
    assert meta["tier_2_admitted"] == len(sidecar)
    assert meta["tier_3_refused"] > 0, "a model that refuses nothing is not a gate"


def test_exact_request_control_paths_reach_prior_tiered_only_wires(emitted_graphs):
    """The two former tiered-only campaign wires are now exact release edges.

    The retained 11-source fabric-master request-control composition directly
    witnesses one uphill edge into each wire.  Keep the tiered graph a superset,
    but no longer describe these exact paths as evidence that only the broader
    model buys reachability.
    """
    strict, tiered = emitted_graphs

    def uphill(path):
        counts = collections.Counter()
        with (path / "dev_pips.csv").open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                counts[row["dst"]] += 1
        return counts
    before, after = uphill(strict), uphill(tiered)
    for wire in ("X14Y10_RMUX49", "X14Y10_RMUX20"):
        assert before[wire] == 1
        assert after[wire] >= before[wire], wire
    assert all(after[wire] >= before[wire] for wire in before)


def test_admission_option_rejects_an_unknown_model(tmp_path):
    command = [sys.executable, str(ROOT / "agamemnon" / "engine" / "emit_uarch_db.py"),
               "--arch", str(ROOT / "agamemnon" / "engine" / "arch.py"),
               "--data", str(CHIPDB), "--out", str(tmp_path / "db"),
               "--env", "AGAMEMNON_ROUTING_ADMISSION=lenient"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    assert result.returncode != 0
    assert "AGAMEMNON_ROUTING_ADMISSION" in result.stdout + result.stderr


def test_tiered_without_the_gates_it_is_defined_against_is_refused(tmp_path):
    command = [sys.executable, str(ROOT / "agamemnon" / "engine" / "emit_uarch_db.py"),
               "--arch", str(ROOT / "agamemnon" / "engine" / "arch.py"),
               "--data", str(CHIPDB), "--out", str(tmp_path / "db"),
               "--env", "AGAMEMNON_ROUTING_ADMISSION=tiered"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    assert result.returncode != 0
    assert "AGAMEMNON_STRICT_GATE" in result.stdout + result.stderr


def test_docs_describe_the_model_the_registry_points_at():
    from agamemnon.engine.registry import OPTIONS
    spec = OPTIONS["AGAMEMNON_ROUTING_ADMISSION"]
    assert spec.default == "release-strict"
    doc = (ROOT / spec.evidence).read_text(encoding="utf-8")
    for token in ("release-strict", "tiered", "tiered-tables",
                  routing_tiers.BASIS_PHYSICAL, routing_tiers.BASIS_RELATIVE,
                  routing_tiers.BASIS_CLOSED_FORM):
        assert token in doc, token


def test_cli_exposes_release_strict_and_defaults_to_tiered():
    source = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert '"--release-strict", action="store_true"' in source
    assert 'default_devdb = "devdb_tiered_pcf" if a.pcf else "devdb_tiered"' in source
    # release-strict must not perturb the existing cache fingerprint, or the
    # first strict build after this change silently rebuilds the database that
    # every retained artifact was produced against.
    assert 'if admission != "release-strict":' in source
    # A hash-bound qualified profile is built against the graph it was
    # qualified on, not against whatever the ambient default happens to be.
    assert 'if a.qualified_checkpoint or getattr(a, "qualified_bram_write", None):' in source
    assert "        release_strict = True" in source


def test_the_diagnostic_line_every_replay_script_parses_is_unchanged_when_idle():
    """Five audit scripts, two replay tests and the SERV gate match this line.

    Adding an always-present "closed-form" field broke four of them at once
    while conveying nothing (the count is zero on every current build). The
    field is emitted only when non-zero.
    """
    source = (ROOT / "agamemnon" / "engine" / "features" / "routing.py").read_text(
        encoding="utf-8")
    assert '"%d legacy-abs, %s%d predicted), %d unmapped -> %d bits"' in source
    assert ('_closed_form_note = ("%d closed-form, " % closed_form_count) '
            "if closed_form_count else """) in source
