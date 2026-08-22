"""Unit tests for the G5 layer-2 router2 self-check (agamemnon/engine/router2_diagnostics.py).

Pure-Python: no nextpnr, no yosys, no board, no real device database. Feeds the parser real (and
malformed) error strings, and runs the directed reachability search over small synthetic pip
tables with a known-reachable and a known-unreachable pair, including a case that only an
*undirected* search would (wrongly) find -- pinning the exact mistake the 2026-08-20 investigation
flagged and refuted (AG32-Docs docs/GOAL_VENDOR_PARITY.md, "BFS ignored pip directionality").
"""
import csv
import os

import pytest

from agamemnon.engine import router2_diagnostics as D


# ---------------------------------------------------------------------------------------------
# parse_route_arc_failures / parse_last_route_arc_failure
# ---------------------------------------------------------------------------------------------

REAL_INCIDENT_LINE = (
    "ERROR: Failed to route arc 1.0 of net 'dma_breq', from X15Y9_OMUX14 to X0Y5_SinkMUXPseudo199.\n"
)


def test_parses_the_real_incident_line_exactly():
    failures = D.parse_route_arc_failures(REAL_INCIDENT_LINE)
    assert len(failures) == 1
    f = failures[0]
    assert f.arc_index == 1
    assert f.phys_pin == 0
    assert f.net == "dma_breq"
    assert f.src == "X15Y9_OMUX14"
    assert f.dst == "X0Y5_SinkMUXPseudo199"


def test_parses_from_a_realistic_multiline_log_with_surrounding_noise():
    log = (
        "[build] place&route (cap=4, seed=4, fanout off): nextpnr-generic --uarch agrv2k ...\n"
        "Info: Packing constants..\n"
        "Info: Routing..\n"
        + REAL_INCIDENT_LINE +
        "ERROR: place&route failed\n"
    )
    f = D.parse_last_route_arc_failure(log)
    assert f is not None
    assert f.net == "dma_breq"
    assert f.src == "X15Y9_OMUX14"
    assert f.dst == "X0Y5_SinkMUXPseudo199"


def test_last_failure_wins_when_a_log_concatenates_several_attempts():
    log = (
        "Failed to route arc 1.0 of net 'dma_breq', from X15Y9_OMUX14 to X0Y5_SinkMUXPseudo199.\n"
        "Failed to route arc 2.1 of net 'other_net', from X1Y1_A to X2Y2_B.\n"
    )
    f = D.parse_last_route_arc_failure(log)
    assert f.net == "other_net"
    assert f.arc_index == 2
    assert f.phys_pin == 1
    assert f.src == "X1Y1_A"
    assert f.dst == "X2Y2_B"
    assert len(D.parse_route_arc_failures(log)) == 2


def test_dotted_hierarchical_net_name_and_bel_style_wire_names():
    # generic/viaduct/example wire names use "/" (X2/Y2/SLICE0_LUT) and hierarchical net names can
    # contain "." -- the parser must not stop at the first period in either the net name or dst.
    log = ("Failed to route arc 0.0 of net 'mem_ahb_boundary.mcu_htrans1', "
           "from X13/Y12/BufMUX02 to X13/Y12/BufMUX13.\n")
    f = D.parse_last_route_arc_failure(log)
    assert f.net == "mem_ahb_boundary.mcu_htrans1"
    assert f.src == "X13/Y12/BufMUX02"
    assert f.dst == "X13/Y12/BufMUX13"


@pytest.mark.parametrize("malformed", [
    "",
    "Routing complete.\n",
    "Failed to route arc of net 'x', from A to B.\n",            # missing indices
    "Failed to route arc 1.0 of net dma_breq, from A to B.\n",    # missing quotes around net
    "Failed to route arc 1.0 of net 'dma_breq' from A to B.\n",   # missing comma
    "Failed to route arc 1.0 of net 'dma_breq', from A to B\n",   # missing trailing period
    "something Failed to route arc 1.x of net 'dma_breq', from A to B.\n",  # non-numeric arc field
])
def test_malformed_or_absent_messages_do_not_match(malformed):
    assert D.parse_route_arc_failures(malformed) == []
    assert D.parse_last_route_arc_failure(malformed) is None


def test_no_arc_failure_in_text_yields_none_from_diagnose():
    assert D.diagnose_routing_failure("Info: Routing complete.\n", lambda: []) is None


# ---------------------------------------------------------------------------------------------
# directed_reachability
# ---------------------------------------------------------------------------------------------

def test_directed_reachability_finds_a_multi_hop_path():
    edges = [("A", "B"), ("B", "C"), ("C", "D")]
    result = D.directed_reachability(edges, "A", "D")
    assert result.found is True
    assert result.bailed is False
    assert result.path == ["A", "B", "C", "D"]
    assert result.hops == 3


def test_directed_reachability_src_equals_dst_is_trivially_found():
    result = D.directed_reachability([("A", "B")], "A", "A")
    assert result.found is True
    assert result.hops == 0
    assert result.path == ["A"]


def test_directed_reachability_reports_a_clean_negative_when_truly_unreachable():
    # B is a dead end; nothing reaches D.
    edges = [("A", "B"), ("X", "D")]
    result = D.directed_reachability(edges, "A", "D")
    assert result.found is False
    assert result.bailed is False
    assert result.path is None


def test_directed_reachability_respects_direction_undirected_would_wrongly_find_this():
    # A -> B exists; B -> A does not. An undirected walk would treat the edge as traversable both
    # ways and wrongly report A reachable from B. This is exactly the mistake the 2026-08-20
    # investigation flagged and had to refute by hand; pin it here permanently.
    edges = [("A", "B")]
    forward = D.directed_reachability(edges, "A", "B")
    backward = D.directed_reachability(edges, "B", "A")
    assert forward.found is True
    assert backward.found is False
    assert backward.bailed is False


def test_directed_reachability_ignores_a_path_that_only_exists_in_reverse():
    # A longer, unambiguous version of the same property: the only way from D to A is via the
    # reverse of a chain that exists A->B->C->D; walking it backwards must fail.
    edges = [("A", "B"), ("B", "C"), ("C", "D")]
    result = D.directed_reachability(edges, "D", "A")
    assert result.found is False
    assert result.bailed is False


def test_directed_reachability_visited_cap_bails_distinctly_from_not_found():
    # A long chain with no path to an unreachable target: with a tiny cap, the search must say it
    # bailed (inconclusive), never claim a completed negative.
    edges = [(str(i), str(i + 1)) for i in range(1000)]
    result = D.directed_reachability(edges, "0", "unreachable_target", max_visited=5)
    assert result.found is False
    assert result.bailed is True
    assert result.bail_reason is not None
    assert "cap" in result.bail_reason


def test_directed_reachability_timeout_bails_distinctly_from_not_found():
    # A negative budget guarantees the very first periodic check bails deterministically
    # (elapsed time is always >= 0 > any negative timeout), independent of clock resolution --
    # unlike timeout_s=0.0, which can race a fast monotonic clock on some platforms.
    edges = [(str(i), str(i + 1)) for i in range(50_000)]
    result = D.directed_reachability(edges, "0", "unreachable_target", max_visited=10**9, timeout_s=-1.0)
    assert result.found is False
    assert result.bailed is True
    assert "timed out" in result.bail_reason


def test_directed_reachability_survives_a_broken_edge_source():
    def bad_edges():
        yield ("A", "B")
        raise RuntimeError("boom")
    result = D.directed_reachability(bad_edges(), "A", "Z")
    assert result.found is False
    assert result.bailed is True
    assert "boom" in result.bail_reason


def test_directed_reachability_handles_a_cycle_without_looping_forever():
    edges = [("A", "B"), ("B", "A"), ("B", "C")]
    result = D.directed_reachability(edges, "A", "C")
    assert result.found is True
    assert result.path == ["A", "B", "C"]


# ---------------------------------------------------------------------------------------------
# iter_pip_edges_csv / uarch_pip_edges_provider
# ---------------------------------------------------------------------------------------------

def _write_dev_pips_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "type", "src", "dst", "delay_ns", "x", "y", "z"])
        for src, dst in rows:
            w.writerow(["%s.%s" % (src, dst), "PIP", src, dst, "0.1", "0", "0", "0"])


def test_iter_pip_edges_csv_reads_the_dev_pips_schema(tmp_path):
    csv_path = tmp_path / "dev_pips.csv"
    _write_dev_pips_csv(csv_path, [("X0Y0_A", "X0Y0_B"), ("X0Y0_B", "X0Y1_C")])
    edges = list(D.iter_pip_edges_csv(str(csv_path)))
    assert edges == [("X0Y0_A", "X0Y0_B"), ("X0Y0_B", "X0Y1_C")]


def test_uarch_pip_edges_provider_reads_the_exact_devdb_directory(tmp_path):
    devdb = tmp_path / "devdb_strict"
    devdb.mkdir()
    _write_dev_pips_csv(devdb / "dev_pips.csv", [("SRC", "MID"), ("MID", "DST")])
    provider = D.uarch_pip_edges_provider(str(devdb))
    assert list(provider()) == [("SRC", "MID"), ("MID", "DST")]


def test_uarch_pip_edges_provider_raises_clearly_when_devdb_is_missing(tmp_path):
    provider = D.uarch_pip_edges_provider(str(tmp_path / "does_not_exist"))
    with pytest.raises(FileNotFoundError):
        provider()


# ---------------------------------------------------------------------------------------------
# diagnose_routing_failure (end-to-end over the parser + BFS + message formatting)
# ---------------------------------------------------------------------------------------------

def test_diagnose_reports_a_legal_path_exists_when_a_free_path_exists():
    edges = [("X15Y9_OMUX14", "MID1"), ("MID1", "MID2"), ("MID2", "X0Y5_SinkMUXPseudo199")]
    message = D.diagnose_routing_failure(REAL_INCIDENT_LINE, lambda: edges)
    assert message is not None
    assert "A LEGAL PATH EXISTS" in message
    assert "NOT A DEVICE-DATA GAP" in message
    assert "3-hop" in message
    assert "dma_breq" in message
    assert D.DOC_POINTER in message


def test_found_message_does_not_overclaim_a_router_defect():
    # Regression test for the G9 overclaim (AG32-Docs docs/TASK_QUEUE.md queue G): a task G9
    # incident on 2026-08-20 showed a free static path can also mean the wire is legitimately
    # bound by another real net's own route (ordinary contention), not a router-internal
    # reservation defect -- and the two call for different user responses. This check only
    # inspects the static admitted graph, never router2's live occupancy/reservation state, so it
    # must never assert that the router itself is defective -- only that a device-data gap is
    # ruled out, with the remaining possibilities enumerated rather than collapsed into one.
    edges = [("X15Y9_OMUX14", "MID1"), ("MID1", "MID2"), ("MID2", "X0Y5_SinkMUXPseudo199")]
    message = D.diagnose_routing_failure(REAL_INCIDENT_LINE, lambda: edges)
    assert message is not None

    # must not assert the historical overclaim, in any of its forms
    assert "ROUTER DEFECT" not in message
    assert "DESIGN OR DEVICE-DATA PROBLEM" not in message
    assert "the router is the suspect" not in message
    assert "Do not assume a router defect from this message alone" in message

    # must state its own blind spot in the output itself
    lowered = message.lower()
    assert "live pip occupancy" in lowered
    assert "reservation" in lowered
    assert "reserved_net" in message

    # must enumerate the three remaining possibilities rather than asserting one
    assert "reservation defect" in lowered
    assert "contention" in lowered
    assert "router search failure" in lowered or "search simply did not" in lowered

    # must point at the known mechanism doc as one candidate, not as the diagnosis
    assert D.DOC_POINTER in message
    assert "one known mechanism" in lowered


def test_not_found_message_wording_is_unchanged_by_the_g9_rewrite():
    # G7 (2026-08-19) independently verified this verdict is precisely correct; the G9 rewrite
    # must not touch it.
    edges = [("X15Y9_OMUX14", "DEAD_END"), ("UNRELATED", "X0Y5_SinkMUXPseudo199")]
    message = D.diagnose_routing_failure(REAL_INCIDENT_LINE, lambda: edges)
    assert message is not None
    assert "NO ADMITTED PATH" in message
    assert "LIKELY A GENUINE DEVICE-DATA GAP" in message
    assert "admission gap" in message.lower()


def test_diagnose_reports_genuine_negative_when_no_path_exists():
    edges = [("X15Y9_OMUX14", "DEAD_END"), ("UNRELATED", "X0Y5_SinkMUXPseudo199")]
    message = D.diagnose_routing_failure(REAL_INCIDENT_LINE, lambda: edges)
    assert message is not None
    assert "NO ADMITTED PATH" in message
    assert "admission gap" in message.lower()
    assert "X15Y9_OMUX14" in message and "X0Y5_SinkMUXPseudo199" in message


def test_diagnose_reports_inconclusive_when_the_search_bails():
    # The chain must actually start at the failing arc's real source, or the search would
    # terminate immediately (src has no outgoing edges) with a clean, non-bailed negative instead
    # of exercising the cap.
    edges = [("X15Y9_OMUX14", "n0")] + [("n%d" % i, "n%d" % (i + 1)) for i in range(1000)]
    message = D.diagnose_routing_failure(REAL_INCIDENT_LINE, lambda: edges, max_visited=3)
    assert message is not None
    assert "INCONCLUSIVE" in message
    assert "NOT evidence" in message


def test_diagnose_reports_inconclusive_when_the_graph_cannot_be_loaded():
    def broken_provider():
        raise FileNotFoundError("/no/such/devdb/dev_pips.csv")
    message = D.diagnose_routing_failure(REAL_INCIDENT_LINE, broken_provider)
    assert message is not None
    assert "INCONCLUSIVE" in message
    assert "could not load" in message


def test_diagnose_never_raises_even_if_the_provider_is_pathological():
    def evil_provider():
        return object()  # not iterable
    message = D.diagnose_routing_failure(REAL_INCIDENT_LINE, evil_provider)
    assert message is not None  # must degrade to a message, never propagate an exception


def test_diagnose_long_path_is_truncated_in_the_message():
    n = 30
    edges = [(str(i), str(i + 1)) for i in range(n)]
    log = "Failed to route arc 0.0 of net 'w', from 0 to %d.\n" % n
    message = D.diagnose_routing_failure(log, lambda: edges)
    assert "A LEGAL PATH EXISTS" in message
    assert "..." in message
    assert "%d-hop" % n in message


# ---------------------------------------------------------------------------------------------
# legacy_pip_edges_provider (reuses the real archgen builder; no board, no nextpnr subprocess)
# ---------------------------------------------------------------------------------------------

def test_legacy_pip_edges_provider_reuses_archgen_build(monkeypatch):
    """Does not exercise the real (large) AGRV2K graph -- stubs archgen.build so this stays a
    fast, deterministic unit test -- but proves the provider calls the real production entry point
    (agamemnon.engine.archgen.build) with the exact env given, not a re-implementation of it, and
    extracts (src, dst) pairs from the RecordingCtx the same way emit_uarch_db.py does.
    """
    calls = {}

    def fake_build(ctx, Loc, environ=None):
        calls["environ"] = environ
        ctx.addWire(name="X0Y0_A", type="A", x=0, y=0)
        ctx.addWire(name="X0Y0_B", type="B", x=0, y=0)
        ctx.addPip(name="p0", type="PIP", srcWire="X0Y0_A", dstWire="X0Y0_B", delay=0.1, loc=Loc(0, 0, 0))

    import agamemnon.engine.archgen as archgen
    monkeypatch.setattr(archgen, "build", fake_build)

    # arch_path only needs to exist on disk (checked via os.path before archgen.build is called);
    # its content is irrelevant since archgen.build itself is stubbed above.
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as fh:
        fh.write(b"# stub arch.py\n")
        real_arch_path = fh.name
    try:
        provider = D.legacy_pip_edges_provider(real_arch_path, "/fake/data", {"AGAMEMNON_FOO": "1"})
        edges = list(provider())
    finally:
        os.remove(real_arch_path)
    assert edges == [("X0Y0_A", "X0Y0_B")]
    assert calls["environ"]["AGAMEMNON_FOO"] == "1"
    assert calls["environ"]["AGAMEMNON_DATA"] == "/fake/data"


def test_legacy_pip_edges_provider_raises_clearly_when_arch_py_is_missing():
    provider = D.legacy_pip_edges_provider("/no/such/arch.py", "/fake/data", {})
    with pytest.raises(FileNotFoundError):
        provider()


# ---------------------------------------------------------------------------------------------
# G13 (AG32-Docs docs/TASK_QUEUE.md queue G): G2 measured G5/G9's banner firing ZERO times across
# all three parity-benchmark widths, because the failures that actually dominate are not
# "Failed to route arc" at all -- a reservation collision (below) and a pre-routing packing
# failure (further below). These strings are taken VERBATIM from the real captured build logs
# (AGaMEMnon/.tmp/parity_witness/g2_w3/build.log, g2_w8/attempts/attempt_10_*.log, and
# g2_w32/build.log) that motivated G13, not invented examples.
# ---------------------------------------------------------------------------------------------

REAL_COLLISION_LINE = (
    "ERROR: attempting to reserve sink input path wire 'X14Y8_IMUX17' for nets 's_haddr[4]' "
    "and '$frontend$289'\n"
)

# Verbatim from g2_w3/build.log:146 -- a hierarchical, backslash- and colon-bearing net name
# ($abc$550$flatten\dut.$not$...) generated by yosys' abc pass. A raw string avoids Python
# interpreting the backslash as an escape.
REAL_COLLISION_LINE_HIERARCHICAL_NET = (
    r"ERROR: attempting to reserve sink input path wire 'X14Y8_IMUX17' for nets "
    r"'$abc$550$flatten\dut.$not$.tmp/parity_witness/witness_macro_scaled.v:113$60_Y_new_inv' "
    r"and '$frontend$144'" "\n"
)

# Verbatim from g2_w32/build.log:97-101 -- the W32 packing-stage death that never reaches routing.
REAL_PRE_ROUTING_BLOCK = (
    "Info: agrv2k: STUCK detail: reanchors_left=0 ebudget=2665 assigned=232/2112 root=X13Y12_BufMUX02\n"
    "Info: agrv2k: STUCK contested wire idx 12939 owner-entry "
    "'$abc$2546$auto$blifparse.cc:557:parse_blif$2853_LC' root X13Y12_BufMUX13\n"
    "ERROR: agrv2k: entry-anchor negotiation stuck at MCU input consumer "
    "'$abc$2546$auto$blifparse.cc:557:parse_blif$2548_LC' (no remaining candidates on any side, fails=60)\n"
    "ERROR: Packing design failed.\n"
)


# ---------------------------------------------------------------------------------------------
# parse_reservation_collisions / parse_last_reservation_collision
# ---------------------------------------------------------------------------------------------

def test_parses_the_real_reservation_collision_line_exactly():
    collisions = D.parse_reservation_collisions(REAL_COLLISION_LINE)
    assert len(collisions) == 1
    c = collisions[0]
    assert c.kind == "sink input"
    assert c.wire == "X14Y8_IMUX17"
    assert c.holder_net == "s_haddr[4]"
    assert c.contender_net == "$frontend$289"


def test_parses_the_real_collision_line_with_a_hierarchical_backslashed_net_name():
    c = D.parse_last_reservation_collision(REAL_COLLISION_LINE_HIERARCHICAL_NET)
    assert c is not None
    assert c.wire == "X14Y8_IMUX17"
    assert c.holder_net == (
        r"$abc$550$flatten\dut.$not$.tmp/parity_witness/witness_macro_scaled.v:113$60_Y_new_inv"
    )
    assert c.contender_net == "$frontend$144"


def test_parses_the_driver_output_variant_of_the_collision_message():
    line = "ERROR: attempting to reserve driver output path wire 'X0Y5_A' for nets 'netA' and 'netB'\n"
    c = D.parse_last_reservation_collision(line)
    assert c is not None
    assert c.kind == "driver output"
    assert c.holder_net == "netA"
    assert c.contender_net == "netB"


@pytest.mark.parametrize("malformed", [
    "",
    "Routing complete.\n",
    # missing quotes around the wire
    "attempting to reserve sink input path wire X14Y8_IMUX17 for nets 's_haddr[4]' and '$frontend$289'\n",
    # missing quotes around the first (holder) net
    "attempting to reserve sink input path wire 'X14Y8_IMUX17' for nets s_haddr[4] and '$frontend$289'\n",
    # truncated: contender net's closing quote never arrives
    "attempting to reserve sink input path wire 'X14Y8_IMUX17' for nets 's_haddr[4]' and '$frontend$289\n",
    # wrong "kind" keyword (neither "driver output" nor "sink input")
    "attempting to reserve output path wire 'X14Y8_IMUX17' for nets 's_haddr[4]' and '$frontend$289'\n",
])
def test_malformed_or_absent_collision_messages_do_not_match(malformed):
    assert D.parse_reservation_collisions(malformed) == []
    assert D.parse_last_reservation_collision(malformed) is None


def test_last_collision_wins_when_a_log_concatenates_several():
    log = (
        "ERROR: attempting to reserve sink input path wire 'A' for nets 'n1' and 'n2'\n"
        "ERROR: attempting to reserve sink input path wire 'B' for nets 'n3' and 'n4'\n"
    )
    c = D.parse_last_reservation_collision(log)
    assert c.wire == "B"
    assert c.holder_net == "n3"
    assert c.contender_net == "n4"
    assert len(D.parse_reservation_collisions(log)) == 2


# ---------------------------------------------------------------------------------------------
# wire_branching
# ---------------------------------------------------------------------------------------------

def test_wire_branching_counts_distinct_uphill_and_downhill_neighbors():
    edges = [("A", "W"), ("B", "W"), ("A", "W"), ("W", "C"), ("W", "D"), ("W", "C")]
    b = D.wire_branching(edges, "W")
    assert b.present is True
    assert b.uphill == 2      # A, B -- A counted once despite the duplicate edge
    assert b.downhill == 2    # C, D
    assert b.bailed is False


def test_wire_branching_reports_an_absent_wire_honestly():
    edges = [("A", "B"), ("B", "C")]
    b = D.wire_branching(edges, "NOT_THERE")
    assert b.present is False
    assert b.uphill == 0
    assert b.downhill == 0
    assert b.bailed is False


def test_wire_branching_bails_on_a_broken_edge_source():
    def bad_edges():
        yield ("A", "W")
        raise RuntimeError("boom")
    b = D.wire_branching(bad_edges(), "W")
    assert b.bailed is True
    assert "boom" in b.bail_reason


def test_wire_branching_respects_the_edge_scan_cap():
    edges = [(str(i), "W") for i in range(1000)]
    b = D.wire_branching(edges, "W", max_edges=10)
    assert b.bailed is True
    assert "cap" in b.bail_reason


# ---------------------------------------------------------------------------------------------
# detect_pre_routing_failure
# ---------------------------------------------------------------------------------------------

def test_detects_the_real_w32_packing_failure_block_verbatim():
    f = D.detect_pre_routing_failure(REAL_PRE_ROUTING_BLOCK)
    assert f is not None
    assert f.stage == "packing"
    assert f.reason is not None
    assert "entry-anchor negotiation stuck" in f.reason
    assert f.raw == "Packing design failed."


def test_detects_a_bare_placing_design_failed_with_no_preceding_reason():
    f = D.detect_pre_routing_failure("Info: something\nERROR: Placing design failed.\n")
    assert f is not None
    assert f.stage == "placing"
    assert f.reason is None


def test_detects_loading_design_failed():
    f = D.detect_pre_routing_failure("ERROR: Loading design failed.\n")
    assert f is not None
    assert f.stage == "loading"


@pytest.mark.parametrize("text", [
    "",
    "Info: Routing complete.\n",
    "ERROR: Failed to route arc 1.0 of net 'x', from A to B.\n",
    "ERROR: Packing design fail\n",       # truncated mid-word
    "ERROR: packing design failed.\n",    # wrong case -- not nextpnr's literal string
])
def test_no_pre_routing_marker_returns_none(text):
    assert D.detect_pre_routing_failure(text) is None


def test_pre_routing_reason_does_not_reach_past_an_unrelated_line():
    # The nearest preceding non-blank line is unrelated ("Info: something"), not an ERROR line --
    # must not skip past it (or reach further back) and misattribute a distant error as "the reason".
    log = "ERROR: some unrelated earlier error\nInfo: something\nERROR: Packing design failed.\n"
    f = D.detect_pre_routing_failure(log)
    assert f is not None
    assert f.reason is None


# ---------------------------------------------------------------------------------------------
# diagnose_routing_failure: reservation collision (G13)
# ---------------------------------------------------------------------------------------------

def test_diagnose_reports_a_reservation_collision():
    message = D.diagnose_routing_failure(REAL_COLLISION_LINE, lambda: [])
    assert message is not None
    assert "RESERVATION COLLISION" in message
    assert "X14Y8_IMUX17" in message
    assert "s_haddr[4]" in message
    assert "$frontend$289" in message
    assert D.DOC_POINTER in message


def test_collision_message_does_not_claim_the_known_packer_gnd_net_defect():
    # Regression test (G13): G2's evidence is that the reservation-collision signature is the
    # GENERAL case (two ordinary nets), not the specific $PACKER_GND_NET mechanism documented in
    # AG32-Docs/NEXTPNR_ROUTER2_BUG.md -- the two must stay distinct. This message must never read
    # as "this incident is confirmed to be that defect".
    message = D.diagnose_routing_failure(REAL_COLLISION_LINE, lambda: [])
    assert message is not None
    lowered = message.lower()
    assert "$packer_gnd_net" in lowered              # cited as related background...
    assert "not confirmed to be that defect" in lowered   # ...but explicitly disclaimed
    assert "this is the $packer_gnd_net defect" not in lowered
    assert "related background" in lowered
    assert "general" in lowered and "unfixed" in lowered
    assert D.DOC_POINTER in message


def test_collision_message_reports_wire_branching_when_the_graph_is_available():
    edges = [("A", "X14Y8_IMUX17"), ("X14Y8_IMUX17", "B"), ("X14Y8_IMUX17", "C")]
    message = D.diagnose_routing_failure(REAL_COLLISION_LINE, lambda: edges)
    assert message is not None
    assert "1 distinct uphill neighbor" in message
    assert "2 distinct downhill neighbor" in message
    assert "NOT a per-net path check" in message


def test_collision_message_degrades_gracefully_when_the_graph_cannot_be_loaded():
    def broken_provider():
        raise FileNotFoundError("/no/such/devdb/dev_pips.csv")
    message = D.diagnose_routing_failure(REAL_COLLISION_LINE, broken_provider)
    assert message is not None
    assert "RESERVATION COLLISION" in message
    assert "could not load" in message


def test_collision_message_notes_an_absent_wire_honestly():
    message = D.diagnose_routing_failure(REAL_COLLISION_LINE, lambda: [("A", "B")])
    assert message is not None
    assert "does not appear as a pip endpoint" in message


def test_diagnose_never_raises_on_a_pathological_provider_for_a_collision():
    def evil_provider():
        return object()  # not iterable
    message = D.diagnose_routing_failure(REAL_COLLISION_LINE, evil_provider)
    assert message is not None  # must degrade to a message, never propagate an exception
    assert "RESERVATION COLLISION" in message


def test_diagnose_reports_the_real_hierarchical_net_collision():
    message = D.diagnose_routing_failure(REAL_COLLISION_LINE_HIERARCHICAL_NET, lambda: [])
    assert message is not None
    assert "RESERVATION COLLISION" in message
    assert "X14Y8_IMUX17" in message
    assert "$frontend$144" in message


# ---------------------------------------------------------------------------------------------
# diagnose_routing_failure: pre-routing failure (G13)
# ---------------------------------------------------------------------------------------------

def test_diagnose_reports_no_routing_attempted_for_the_real_w32_packing_failure():
    def must_not_be_called():
        raise AssertionError("pip_edges_provider must not be called for a pre-routing failure")
    message = D.diagnose_routing_failure(REAL_PRE_ROUTING_BLOCK, must_not_be_called)
    assert message is not None
    assert "NO ROUTING WAS ATTEMPTED" in message
    assert "NO ROUTING CONCLUSION CAN BE DRAWN" in message
    assert "packing" in message.lower()
    assert "entry-anchor negotiation stuck" in message


def test_diagnose_pre_routing_is_no_longer_silent_for_the_g2_w32_case():
    # This is exactly the G2 complaint: before G13 this returned None (silent) for a W32-style
    # packing failure even though the build genuinely failed. It must not be silent any more.
    log = "[build] some preamble\n" + REAL_PRE_ROUTING_BLOCK + "2 warnings, 2 errors\n"
    message = D.diagnose_routing_failure(log, lambda: [])
    assert message is not None


def test_diagnose_pre_routing_for_a_bare_placing_failure_with_no_extra_reason():
    message = D.diagnose_routing_failure("ERROR: Placing design failed.\n", lambda: [])
    assert message is not None
    assert "NO ROUTING WAS ATTEMPTED" in message
    assert "placing" in message.lower()


# ---------------------------------------------------------------------------------------------
# diagnose_routing_failure: cross-signature precedence + preserved existing behaviour (part C)
# ---------------------------------------------------------------------------------------------

def test_diagnose_picks_whichever_signature_occurs_last_in_a_concatenated_log():
    log_a = (
        "ERROR: Failed to route arc 1.0 of net 'x', from A to B.\n"
        "ERROR: Packing design failed.\n"
    )
    message_a = D.diagnose_routing_failure(log_a, lambda: [])
    assert message_a is not None
    assert "NO ROUTING WAS ATTEMPTED" in message_a

    log_b = (
        "ERROR: Packing design failed.\n"
        "ERROR: Failed to route arc 1.0 of net 'x', from A to B.\n"
    )
    message_b = D.diagnose_routing_failure(log_b, lambda: [("A", "B")])
    assert message_b is not None
    assert "A LEGAL PATH EXISTS" in message_b


def test_g13_extension_does_not_disturb_the_unchanged_arc_failure_path():
    # Preserve what G7/G9 already verified: a plain arc failure with no collision/pre-routing text
    # anywhere in the log still produces the exact same class of verdict as before G13.
    edges = [("X15Y9_OMUX14", "MID1"), ("MID1", "MID2"), ("MID2", "X0Y5_SinkMUXPseudo199")]
    message = D.diagnose_routing_failure(REAL_INCIDENT_LINE, lambda: edges)
    assert message is not None
    assert "A LEGAL PATH EXISTS" in message
    assert "RESERVATION COLLISION" not in message
    assert "NO ROUTING WAS ATTEMPTED" not in message


def test_g13_extension_still_returns_none_for_a_clean_successful_log():
    assert D.diagnose_routing_failure("Info: Routing complete.\n", lambda: []) is None
