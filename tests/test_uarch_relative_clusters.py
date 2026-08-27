"""Structural guards for native relative placement in the AGRV2K backend."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"


def _between(source, start, end):
    return source.split(start, 1)[1].split(end, 1)[0]


def test_carry_footprint_is_a_relative_cluster_not_an_absolute_bel_lock():
    source = SOURCE.read_text(encoding="utf-8")
    carry = _between(source, "static void pack_carries", "static int parse_hk")

    assert "make_relative_cluster(ctx, clustered, true)" in carry
    assert "constr_x" in source
    assert "constr_y" in source
    assert "constr_z" in source
    assert "constr_abs_z" in source
    assert "ctx->bindBel" not in carry


def test_clustered_cells_reach_fixed_endpoints_through_native_legality():
    source = SOURCE.read_text(encoding="utf-8")
    validity = _between(
        source,
        "bool isBelLocationValid(BelId bel, bool explain_invalid) const override",
        "\n    }\n};",
    )

    assert "fixed_endpoint_pins_reachable(ci, bel, explain_invalid)" in validity
    assert "dedicated_carry_pins_reachable(ci, bel, explain_invalid)" in validity
    assert "direct_pip_exists(source, target)" in source
    assert "reachable_from(source)" in source
    assert "reaching(target)" in source
    assert "first_slice_tiles_from(source)" in source
    assert "mcu_entry_corridor_contains(cell, candidate)" in source
    assert "last_slice_tiles_to(target)" in source
    assert "mcu_exit_corridor_contains(cell, candidate)" in source
    assert "mcu_corridor_bounds" in source


def test_post_hoc_placers_leave_native_clusters_to_nextpnr():
    source = SOURCE.read_text(encoding="utf-8")
    mcu_clusters = _between(
        source, "static void pack_mcu_relative_clusters", "static void pack_dense"
    )
    condplace = _between(source, "static void pack_condplace", "struct AgrvImpl")
    exit_anchor = _between(source, "void pack_exit_anchor()", "void pack_entry_buffers()")
    entry_anchor = _between(source, "void pack_entry_anchor()", "void lock_dense_mcu_local_arcs()")

    assert "make_relative_cluster(ctx, shape, false)" in mcu_clusters
    assert "private output producer pair(s)" in mcu_clusters
    assert "live_users != 1" in mcu_clusters
    assert "ctx->bindBel" not in mcu_clusters
    assert "ci->cluster != ClusterId()" in condplace
    assert "drv->cluster != ClusterId()" in exit_anchor
    assert "ci->cluster != ClusterId()" in entry_anchor
