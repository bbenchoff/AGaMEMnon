"""Router-cost avoidance for the X20Y12 congestion-marginal pips (2026-09-25).

Follow-up to test_congestion_marginal_edges.py's post-route refusal (agamemnon/engine/features/
placement_congestion.py, wired into cli.py at the shared pre-emission checkpoint since ba0ce2b).
A refusal is an honest failure, not a fix: a design that would have routed cleanly through some
other feeder still needs a working image, not just a loud error. This adds a POSITIVE mechanism
alongside the refusal: the agrv2k Viaduct uarch (agamemnon/engine/uarch/agrv2k/agrv2k.cc) now
charges every pip in chipdb/congestion_marginal_edges.csv a large-but-finite router2 cost, so
router2's timing-driven PathFinder search prefers any other legal feeder into the same IMUX
terminal and only falls onto a marginal pip when nothing else exists -- in which case the
post-route refusal above remains the last-resort backstop.

The mechanism is pure C++ (agrv2k.cc) and cannot be unit-exercised without a built nextpnr
binary, which this Python test suite does not have (WSL is the build/board gate; see AG32-Docs
memory ag32-wsl-is-the-test-gate-2026-08-31 and ag32-shared-nextpnr-binary-trap-2026-09-25). These
tests instead pin the *shape* of the mechanism at the source level -- the same style
test_congestion_marginal_edges_do_not_change_the_device_graph already uses for routing.py -- so a
later edit cannot silently drop the penalty, silently make it graph-affecting (which would need a
device-database identity regen), or silently stop shipping the evidence table to the uarch.

Board evidence for the mechanism's real effect: with the penalty active, bmd_sp2_c10_o0's reset
net (previously catalogued as entering X20Y12 via the marginal RMUX77->IMUX19) now enters via
RMUX35->IMUX19 instead, and bmd_sdp9_4_c00's hb[0] net -- independently confirmed via
route_surgery.py (strict mode) to have NO alternate feeder from its exact placement -- still uses
its marginal pip and correctly falls through to the post-route refusal. See
AG32-Docs/tools/pipwit/scratch/ROUTER_PENALTY_20260925.md for the full board record.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
UARCH_SRC = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
CLI_SRC = ROOT / "agamemnon" / "cli.py"


def _uarch_source():
    return UARCH_SRC.read_text(encoding="utf-8")


def _cli_source():
    return CLI_SRC.read_text(encoding="utf-8")


def test_congestion_marginal_edges_csv_is_shipped_to_the_uarch_devdb():
    # agrv2k.cc's `path()` helper resolves against `-o chipdb=<devdb dir>`, a per-build directory
    # emit_uarch_db.py generates fresh -- NOT agamemnon/chipdb/ directly. Any chipdb/*.csv the
    # C++ uarch reads at runtime (mcu_endpoint_capabilities.csv, master_conduction.csv, ...) must
    # be copied into that directory via cli.py's `runtime_assets` tuple, or agrv2k.cc's path()
    # simply won't find it (load_congestion_marginal_wire_pairs() fails open in that case, so a
    # missing entry here silently disables the whole mechanism rather than erroring loudly).
    src = _cli_source()
    start = src.index("runtime_assets = (")
    end = src.index(")", start)
    block = src[start:end]
    assert '"congestion_marginal_edges.csv"' in block, (
        "congestion_marginal_edges.csv must be copied into the emitted devdb directory "
        "(cli.py's runtime_assets tuple) or agrv2k.cc can never see it at runtime")


def test_uarch_loads_the_congestion_marginal_table():
    src = _uarch_source()
    assert "load_congestion_marginal_wire_pairs" in src
    assert 'path("congestion_marginal_edges.csv")' in src
    # Fail-open on an absent table, matching placement_congestion.py's own fail-open contract.
    assert "router avoidance DISABLED" in src


def test_uarch_loader_runs_before_the_dev_pips_csv_pip_loop():
    # The penalty has to be known BEFORE addPip() is called for the matching row, or it would
    # have to retroactively edit an already-registered pip's delay.
    src = _uarch_source()
    load_db_idx = src.index("void load_db()")
    loader_call_idx = src.index("load_congestion_marginal_wire_pairs();", load_db_idx)
    pips_csv_idx = src.index('Csv c(path("dev_pips.csv"));', load_db_idx)
    assert load_db_idx < loader_call_idx < pips_csv_idx, (
        "load_congestion_marginal_wire_pairs() must run before dev_pips.csv is parsed")


def test_penalty_env_var_is_large_but_finite_by_default():
    src = _uarch_source()
    fn_idx = src.index("static double congestion_marginal_penalty_ns()")
    fn_src = src[fn_idx:fn_idx + 700]
    assert "AGRV2K_CONGESTION_PENALTY_NS" in fn_src
    assert "return 25.0;" in fn_src, "default penalty must be a concrete finite value"
    # An explicit escape hatch to fall back to the ordinary witnessed delay (0 == off), and a
    # fail-closed guard against a negative value (which would make the pip artificially CHEAP).
    assert "if (v < 0.0)" in fn_src
    assert "log_error" in fn_src


def test_penalty_charges_the_routed_delay_not_the_lookahead_aggregate():
    # The router2 A*/Dijkstra lookahead (timing_uphill) must stay seeded from the TRUE witnessed
    # delay, not the inflated one, or it stops being an admissible lower bound. Only the concrete
    # per-pip delay actually bound to the PipId (pip_delay_by_index / the delay passed to
    # ctx->addPip) should carry the penalty.
    src = _uarch_source()
    pips_block_idx = src.index('Csv c(path("dev_pips.csv"));')
    block = src[pips_block_idx:pips_block_idx + 4000]
    assert "routed_pip_delay" in block
    assert "congestion_marginal_wire_pairs.count(std::make_pair(c.at(2), c.at(3)))" in block
    # addPip and pip_delay_by_index must use the (possibly penalised) routed delay...
    assert "ctx->addPip(IdStringList(ctx->id(c.at(0))), ctx->id(c.at(1)), si->second,\n                                        di->second, routed_pip_delay, loc);" in block
    assert "pip_delay_by_index[pip.index] = routed_pip_delay;" in block
    # ...while the lookahead aggregate keeps using the un-penalised `pip_delay`.
    assert "aggregate[source_node] = pip_delay;" in block


def test_post_route_refusal_remains_wired_as_the_last_resort():
    # This mechanism is an addition, not a replacement: ba0ce2b's post-route check
    # (test_congestion_marginal_edges.py) must still be wired into cli.py's shared pre-emission
    # checkpoint for the rare design that has no alternative feeder at all.
    src = _cli_source()
    assert "validate_document_congestion_marginal" in src
    assert "_validate_congestion_marginal_document" in src
