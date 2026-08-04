import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
ENGINE = ROOT / "agamemnon" / "engine"


def _rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_external_ahb_control_tables_are_complete_and_collision_free():
    request = _rows("mcu_ahb_request_controls.csv")
    response = _rows("mcu_ahb_response_controls.csv")
    exits = _rows("mcu_ahb_control_exit_pairs.csv")
    assert len(request) == 10
    assert {(row["signal"], int(row["logical_bit"])) for row in request} == {
        ("mem_ahb_hready", 0),
        ("mem_ahb_htrans", 0),
        ("mem_ahb_htrans", 1),
        *(("mem_ahb_hsize", bit) for bit in range(3)),
        *(("mem_ahb_hburst", bit) for bit in range(3)),
        ("mem_ahb_hwrite", 0),
    }
    assert len({int(row["bel_bit"]) for row in request + response}) == 12
    assert [row["sink_res"] for row in response] == [
        "SinkMUXPseudo00",
        "SinkMUXPseudo01",
    ]
    assert [row["selectors"] for row in response] == ["3;5", "1;5"]
    assert len(exits) == 12
    assert [row["edge_res"] for row in exits] == [f"BBMUXE{bit:02d}" for bit in range(12)]
    assert all(len(row["selectors"].split(";")) == 2 for row in exits)


def test_control_oracle_has_exact_config_for_every_configurable_corridor_edge():
    paths = _rows("mcu_ahb_control_oracle_paths.csv")
    config = _rows("mcu_ahb_control_pip_cfg.csv")
    exact = {(row["src_wire"], row["dst_wire"]) for row in config}
    configurable = {
        (row["src_wire"], row["dst_wire"])
        for row in paths
        if row["dst_wire"].split("_", 1)[1].startswith(("RMUX", "IMUX", "InputMUX"))
    }
    assert exact == configurable
    assert len(config) == 32
    assert sum(row["cell_table"] == "fabric" for row in config) == 22
    assert sum(row["cell_table"] == "mcu" for row in config) == 10
    assert all(row["clear_selectors"] for row in config)
    assert all(len(row["set_selectors"].split(";")) == 2
               for row in config if row["cell_table"] == "fabric")


def test_open_architecture_loads_and_binds_every_control_lane():
    arch = (ENGINE / "arch.py").read_text(encoding="utf-8")
    bitgen = (ENGINE / "bitgen_seq.py").read_text(encoding="utf-8")
    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")

    assert 'mcu_ahb_request_controls.csv' in arch
    assert 'mcu_ahb_response_controls.csv' in arch
    assert '102: "MCU_AHB_HREADY"' in arch
    assert '110: "MCU_AHB_HREADYOUT"' in arch
    assert '"mcu_ahb_response_controls.csv"' in bitgen
    assert '"mcu_ahb_control_pip_cfg.csv"' in bitgen
    assert 'name.find("hwrite")' in uarch
    assert 'name.find("htrans1")' in uarch
    for primitive in ("MCU_AHB_HREADY", "MCU_AHB_HTRANS0", "MCU_AHB_HSIZE0",
                      "MCU_AHB_HBURST0", "MCU_AHB_HREADYOUT", "MCU_AHB_HRESP"):
        assert primitive in prims


def test_uarch_constraint_fix_is_kept_in_sync_with_nextpnr_overlay():
    source = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    overlay = (ROOT / "third_party" / "nextpnr" / "generic" / "viaduct" /
               "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    assert source == overlay
    assert 'ci->attrs.count(ctx->id("BEL"))' in source
    assert 'items[i].drv->attrs.erase(ctx->id("BEL"))' in source


def test_all_external_ahb_address_lanes_are_exposed_with_exact_missing_paths():
    original = _rows("mcu_haddr_lanes.csv")
    missing = _rows("mcu_haddr_missing_lanes.csv")
    paths = _rows("mcu_haddr_missing_paths.csv")
    config = _rows("mcu_haddr_missing_pip_cfg.csv")
    exits = _rows("mcu_haddr_missing_exit_pairs.csv")
    assert {int(row["logical_bit"]) for row in original + missing} == set(range(32))
    assert [int(row["bel_bit"]) for row in missing] == list(range(112, 118))
    assert {int(row["logical_bit"]) for row in paths} == {0, 1, 28, 29, 30, 31}
    assert len(config) == 15
    assert len(exits) == 6

    arch = (ENGINE / "arch.py").read_text(encoding="utf-8")
    bitgen = (ENGINE / "bitgen_seq.py").read_text(encoding="utf-8")
    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    assert '"mcu_haddr_missing_lanes.csv"' in arch
    assert '"mcu_haddr_missing_paths.csv"' in arch
    assert '"mcu_haddr_missing_pip_cfg.csv"' in bitgen
    assert '"mcu_haddr_missing_exit_pairs.csv"' in bitgen
    assert "return 112 + k" in uarch
    smoke = (ROOT / "examples" / "designs" / "ahb_haddr_missing_route_smoke.v").read_text(
        encoding="utf-8")
    for bit in (0, 1, 28, 29, 30, 31):
        assert f"mcu_haddr{bit}" in smoke
        assert f"mcu_h{bit} " in smoke


def test_vendor_lut_buffers_are_not_promoted_as_free_routing_pips():
    # The simultaneous vendor corridors contain real identity LUTs. They are
    # useful route oracles, but their IMUX->cell->OMUX arcs require a placed LUT
    # and INIT bits. Treating those arcs as pips produced three stuck-high
    # HRDATA lanes in the first constant-slave silicon trial.
    corridor_rows = (
        _rows("mcu_ahb32_corridors.csv") +
        _rows("mcu_haddr_full_corridors.csv")
    )
    assert any("_alta_slice" in row["src_wire"] or
               "_alta_slice" in row["dst_wire"] for row in corridor_rows)

    arch = (ENGINE / "arch.py").read_text(encoding="utf-8")
    promotion = arch.split(
        "# Promote the complete simultaneous vendor corridors", 1
    )[1].split("# Native L48 x9 positive control", 1)[0]
    assert 'if "_alta_slice" in _src or "_alta_slice" in _dst:' in promotion
    assert '"mcu_haddr_full_corridors.csv"' in promotion


def test_mcu_clock_alias_is_exposed_as_typed_global_sources():
    arch = (ENGINE / "arch.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    smoke = (ROOT / "examples" / "designs" / "mcu_bus_clock_route_smoke.v").read_text(
        encoding="utf-8")
    for primitive in ("MCU_SYS_CLOCK", "MCU_BUS_CLOCK"):
        assert primitive in arch
        assert primitive in prims
    assert 'name="CLK", wire="GCLK0"' in arch
    assert "MCU_BUS_CLOCK mcu_bus_clock" in smoke


def test_direct_d_site_has_distinct_f_q_outputs_and_exact_emission():
    arch = (ENGINE / "arch.py").read_text(encoding="utf-8")
    bitgen = (ENGINE / "bitgen_seq.py").read_text(encoding="utf-8")
    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(
        encoding="utf-8")

    assert "_DIRECT_D_SITES = {(14, 11, 6), (14, 11, 7)}" in arch
    assert 'f_o, q_o = "OMUX%02d" % (3*z + 0), "OMUX%02d" % (3*z + 1)' in arch
    assert "_direct_d_sites = {(14, 11, 6), (14, 11, 7)}" in bitgen
    assert "(x, y, z) in _direct_d_sites" in bitgen
    assert "_sels = ((0, 1)" in bitgen
    assert "bool direct_d_site = loc.x == 14 && loc.y == 11 && (loc.z == 6 || loc.z == 7)" in uarch
    assert "if (direct_d_cell && !direct_d_site)" in uarch
    assert "!direct_d_site && !strict_allows_odd" in uarch


def test_exit_matching_uses_actual_driver_port_and_honors_source_bel():
    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(
        encoding="utf-8")
    block = uarch.split("void pack_exit_anchor()", 1)[1].split(
        "void pack_exit_buffers()", 1)[0]
    assert "IdString source_port" in block
    assert "net->driver.port" in block
    assert "ctx->getBelPinWire(b, net->driver.port)" in block
    assert "ctx->getBelPinWire(b, items[ii].source_port)" in block
    assert 'auto requested_bel = drv->attrs.find(ctx->id("BEL"))' in block
    assert "ctx->getBelName(b).str(ctx) != requested_bel->second.as_string()" in block


def test_mcu_resetn_is_exposed_on_an_exact_fabric_corridor():
    arch = (ENGINE / "arch.py").read_text(encoding="utf-8")
    bitgen = (ENGINE / "bitgen_seq.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    path = _rows("mcu_resetn_fabric_path.csv")
    config = _rows("mcu_resetn_fabric_pip_cfg.csv")
    assert len(path) == len(config) == 4
    assert path[0]["src_wire"] == "X13Y5_BufMUX19"
    assert path[-1]["dst_wire"] == "X9Y4_IMUX03"
    assert '120: "MCU_RESETN"' in arch
    assert '"mcu_resetn_fabric_path.csv"' in arch
    assert '"mcu_resetn_fabric_pip_cfg.csv"' in bitgen
    assert "module MCU_RESETN" in prims
    smoke = (ROOT / "examples" / "designs" / "mcu_resetn_route_smoke.v").read_text(
        encoding="utf-8")
    assert "MCU_RESETN mcu_resetn" in smoke


def test_all_local_interrupt_lanes_are_exposed_on_exact_vendor_corridors():
    arch = (ENGINE / "arch.py").read_text(encoding="utf-8")
    bitgen = (ENGINE / "bitgen_seq.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    assert '"mcu_local_int%d_path.csv"' in arch
    for bit in range(4):
        path = _rows(f"mcu_local_int{bit}_path.csv")
        config = _rows(f"mcu_local_int{bit}_pip_cfg.csv")
        assert len(path) >= 7
        assert len(config) == len(path) - 1
        assert path[-2]["dst_wire"] == f"X1Y5_BBMUXS0{bit}"
        assert path[-1]["dst_wire"] == f"X0Y5_SinkMUXPseudo{215 + bit}"
        assert config[-1]["set_selectors"] == ("3;6", "2;6", "2;4", "3;5")[bit]
        assert f'{121 + bit}: "MCU_LOCAL_INT{bit}"' in arch
        assert f'"mcu_local_int{bit}_pip_cfg.csv"' in bitgen
        assert f"module MCU_LOCAL_INT{bit}" in prims
        smoke = (ROOT / "examples" / "designs" /
                 f"mcu_local_int{bit}_route_smoke.v").read_text(encoding="utf-8")
        assert f"MCU_LOCAL_INT{bit} mcu_local_int{bit}" in smoke
    all_low = (ROOT / "examples" / "designs" /
               "mcu_local_int_all_low_route_smoke.v").read_text(encoding="utf-8")
    assert "16'h0000" in all_low
    assert all_low.count(".DOUT(local_irq_low)") == 4
