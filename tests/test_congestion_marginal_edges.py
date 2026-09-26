"""X20Y12 corner-tile congestion-marginal edges (placement bisect, 2026-09-25).

Board evidence: three open-flow narrow-BRAM designs (bmd_sdp9_4_c00, bmd_sp2_c10_o0,
bmd_sp9_c10_o0) failed on silicon (2x-rate / 0-edges) although every pip they used carries a
ring AND corpus positive conduction witness, and the same designs simulate PASS as routed
(agamemnon/engine/verify_netlist.py). Cell placement was found bit-identical between the
failing narrow images and a passing counterpart in the same family (bmd_sdp4_4_c00): the
defect is a specific ROUTE choice, not a relocated BEL. Each failing design's problem net
(the heartbeat counter's hb[0] bit, or the design reset) enters tile X20Y12 through one of
three specific RMUX->IMUX pips, while the passing design's equivalent net enters through a
different pip. route_surgery.py (strict mode: tier-1 graph, the suspect excluded, every other
net's wires held fixed) reports each of the three nets UNROUTABLE without its suspect pip --
not merely rerouted -- confirming there is no alternate feeder once the tile's other RMUX
sources are already claimed by the rest of the design. This is the aggregate-corner-tile-
congestion mechanism: a marginal pip that conducts
cleanly in an isolated ring but is unreliable as the forced sole path for a real, loaded
signal.

These three edges DO carry positive ring/corpus evidence (see
test_silicon_dead_edges_have_absolute_precedence in test_large_flow_helpers.py, which asserts
dead_edges_silicon.csv is disjoint from positive evidence): they must never be added to
dead_edges_silicon.csv, which claims non-conduction, and they must not be baked unconditionally
into the device graph either -- that would retroactively change every byte-exact historical
physical-graph checkpoint special_routes.py pins (a much bigger blast radius than the actual
defect). Instead agamemnon/engine/features/placement_congestion.py inspects the ROUTED netlist
after place & route (wired into cli.py's build at the shared pre-emission checkpoint, both the
legacy and --uarch flows) and refuses the build if it used one of the three pips: the same
"refused or moved" outcome (an honest build error instead of a silently-wrong bitstream, or a
different --seed/--cap finding a route that never needed the marginal pip) without touching the
device graph or any pinned historical identity.

2026-09-25 follow-up (router-cost-penalty pass, AG32-Docs tools/pipwit/scratch/
FF_INIT_20260925.md): a fourth design, bmd_sp1_c10_o0, was found forced across 5/5
independently-seeded placements onto the SAME X20Y12_IMUX19 terminal RMUX65/RMUX77 already
implicate, through three more feeder pips (RMUX59, RMUX29, RMUX71) -- five distinct sources into
one scarce sink. A destination-terminal-wide wildcard rule (penalise/refuse ANY source feeding
that terminal, not just the witnessed ones) was tried and REVERTED: bram_rom_kat's own PASSING
board image routes its reset through X20Y12_RMUX83.X20Y12_IMUX19 successfully, and
bmd_sdp4_4_c00's PASSING image routes hb[0] through X20Y12_RMUX47.X20Y12_IMUX05 successfully --
both terminals have a confirmed-good source alongside their confirmed-bad ones, so this stays an
exact source+destination edge table (six rows now) rather than a per-destination ban.
"""
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "agamemnon" / "chipdb"
sys.path.insert(0, str(ROOT))

from agamemnon.engine.features import placement_congestion as PC  # noqa: E402

EDGE_RE = re.compile(r"(\w+)@(-?\d+),(-?\d+)->(\w+)@(-?\d+),(-?\d+)")

EXPECTED_EDGES = {
    ("RMUX53", "20", "12", "IMUX05", "20", "12"),
    ("RMUX65", "20", "12", "IMUX19", "20", "12"),
    ("RMUX77", "20", "12", "IMUX19", "20", "12"),
    # Added 2026-09-25 (router-cost-penalty follow-up, AG32-Docs
    # tools/pipwit/scratch/FF_INIT_20260925.md): bmd_sp1_c10_o0 forced its reset net onto the
    # same X20Y12_IMUX19 terminal across 5/5 seeds, through three more feeder pips.
    ("RMUX59", "20", "12", "IMUX19", "20", "12"),
    ("RMUX29", "20", "12", "IMUX19", "20", "12"),
    ("RMUX71", "20", "12", "IMUX19", "20", "12"),
}
EXPECTED_PIP_NAMES = {
    "X20Y12_RMUX53.X20Y12_IMUX05",
    "X20Y12_RMUX65.X20Y12_IMUX19",
    "X20Y12_RMUX77.X20Y12_IMUX19",
    "X20Y12_RMUX59.X20Y12_IMUX19",
    "X20Y12_RMUX29.X20Y12_IMUX19",
    "X20Y12_RMUX71.X20Y12_IMUX19",
}


def _rows(name):
    with (DATA / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _edges(name):
    """Edge tuples from either schema this chipdb uses: a single quoted "edge" column
    (dead_edges_silicon.csv, congestion_marginal_edges.csv) or split src/dst columns
    (ring_witness_conduction.csv, corpus_conduction.csv)."""
    rows = _rows(name)
    if rows and "edge" in rows[0]:
        return {EDGE_RE.fullmatch(row["edge"]).groups() for row in rows}
    return {(row["src_res"], row["src_x"], row["src_y"],
             row["dst_res"], row["dst_x"], row["dst_y"]) for row in rows}


def _net(routing):
    return {"attributes": {"ROUTING": routing}}


def test_congestion_marginal_edges_file_has_the_board_confirmed_pips():
    rows = _rows("congestion_marginal_edges.csv")
    assert len(rows) == 6
    edges = set()
    for row in rows:
        match = EDGE_RE.fullmatch(row["edge"])
        assert match, row
        edges.add(match.groups())
        assert row["tile"] == "X20Y12", row
        assert row["source"] == "board_congestion_20260925", row
        assert row["evidence"], row
        assert row["note"], row
    assert edges == EXPECTED_EDGES


def test_congestion_marginal_edges_are_not_conflated_with_silicon_dead():
    # The defining distinction (routing.py's own comment, and the disjointness invariant
    # test_silicon_dead_edges_have_absolute_precedence relies on): these pips conduct. Putting
    # them in dead_edges_silicon.csv would falsely claim non-conduction and would break that
    # invariant, since both files carry ring and/or corpus positive witnesses for all three.
    dead = _edges("dead_edges_silicon.csv")
    congestion = _edges("congestion_marginal_edges.csv")
    assert not (dead & congestion), "a congestion-marginal edge must not also be in dead_edges_silicon.csv"
    ring = _edges("ring_witness_conduction.csv") if (DATA / "ring_witness_conduction.csv").exists() else set()
    corpus = _edges("corpus_conduction.csv") if (DATA / "corpus_conduction.csv").exists() else set()
    positive = ring | corpus
    assert congestion & positive == congestion, (
        "every congestion-marginal edge is expected to carry positive ring/corpus evidence -- "
        "that is what makes this a distinct claim from dead_edges_silicon.csv")


def test_congestion_marginal_edges_do_not_change_the_device_graph():
    # The whole point of the post-route validator design (over an EDGE_BLACKLIST graph edit) is
    # that adding this evidence table never touches dev_pips.csv or any pinned historical
    # physical-graph identity. routing.py declares the file for chipdb-file ownership (the "every
    # chipdb CSV has exactly one feature owner" hygiene invariant) but must never load it into
    # EDGE_BLACKLIST or any other graph-affecting structure.
    src = (ROOT / "agamemnon" / "engine" / "features" / "routing.py").read_text(encoding="utf-8")
    assert '"congestion_marginal_edges.csv"' in src, "must be declared for chipdb-file ownership"
    # Never actually opened/parsed here -- only dead_edges_silicon.csv and the opt-in
    # afexe_absent_edges.csv/afexe_column_dead.csv are read into the device graph.
    assert 'os.path.join(DATA, "congestion_marginal_edges.csv")' not in src
    assert src.count('"congestion_marginal_edges.csv"') == 1, (
        "expected exactly one mention: the chipdb_files ownership declaration")


def test_pip_names_convert_edge_csv_to_routed_json_spelling():
    assert PC.congestion_marginal_pip_names(DATA) == EXPECTED_PIP_NAMES


def test_clean_module_passes():
    module = {
        "netnames": {
            "safe_net": _net("W0;X20Y12_RMUX47.X20Y12_IMUX05;1;W1;;1"),
        }
    }
    PC.validate_module_congestion_marginal(module, DATA)  # no raise


def test_module_using_a_banned_pip_is_refused():
    module = {
        "netnames": {
            "hb[0]": _net("W0;X17Y12_RMUX15.X20Y12_RMUX53;1;W1;X20Y12_RMUX53.X20Y12_IMUX05;1;W2;;1"),
        }
    }
    try:
        PC.validate_module_congestion_marginal(module, DATA)
    except PC.CongestionMarginalError as exc:
        assert "hb[0]" in str(exc)
        assert "X20Y12_RMUX53.X20Y12_IMUX05" in str(exc)
    else:
        raise AssertionError("expected a CongestionMarginalError")


def test_all_banned_pips_are_individually_caught():
    for pip in sorted(EXPECTED_PIP_NAMES):
        module = {"netnames": {"n": _net("W0;%s;1;W1;;1" % pip)}}
        try:
            PC.validate_module_congestion_marginal(module, DATA)
        except PC.CongestionMarginalError:
            pass
        else:
            raise AssertionError("%s should have been refused" % pip)


def test_known_good_sources_into_the_same_terminals_are_not_banned():
    # Guards the 2026-09-25 decision to keep this an exact-edge table rather than a
    # destination-terminal-wide ban: these two pips are confirmed-GOOD by a passing board image
    # (bram_rom_kat and bmd_sdp4_4_c00 respectively) into the SAME two scarce terminals
    # (X20Y12_IMUX19, X20Y12_IMUX05) the six banned rows above also feed. A future change that
    # reintroduces destination-keyed matching must not silently start refusing these.
    for pip in ("X20Y12_RMUX83.X20Y12_IMUX19", "X20Y12_RMUX47.X20Y12_IMUX05"):
        assert pip not in EXPECTED_PIP_NAMES, pip
        module = {"netnames": {"safe_net": _net("W0;%s;1;W1;;1" % pip)}}
        PC.validate_module_congestion_marginal(module, DATA)  # no raise


def test_document_wrapper_requires_modules_top():
    try:
        PC.validate_document_congestion_marginal({"modules": {}}, DATA)
    except PC.CongestionMarginalError:
        pass
    else:
        raise AssertionError("expected a CongestionMarginalError for a missing modules['top']")


def test_cli_wires_the_check_into_the_shared_pre_emission_checkpoint():
    src = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert "validate_document_congestion_marginal" in src
    assert "_validate_congestion_marginal_document" in src
    # Beside the MCU-endpoint check at the same "pre-emission" checkpoint (shared by both the
    # legacy and --uarch build flows), not buried in only one flow's branch.
    mcu_idx = src.index('_validate_mcu_endpoint_document(\n            final_snapshot.document, "pre-emission"')
    congestion_idx = src.index(
        '_validate_congestion_marginal_document(\n            final_snapshot.document, "pre-emission"')
    assert 0 < congestion_idx - mcu_idx < 400
