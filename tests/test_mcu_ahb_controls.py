import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
ENGINE = ROOT / "agamemnon" / "engine"


def _rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _bitgen_source():
    return "\n".join((
        (ENGINE / "bitgen.py").read_text(encoding="utf-8"),
        (ENGINE / "features" / "mcu_ahb.py").read_text(encoding="utf-8"),
    ))


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
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    bitgen = _bitgen_source()
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

    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    bitgen = _bitgen_source()
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

    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    promotion = arch.split(
        "# Promote the complete simultaneous vendor corridors", 1
    )[1].split("# Native L48 x9 positive control", 1)[0]
    assert 'if "_alta_slice" in _src or "_alta_slice" in _dst:' in promotion
    assert '"mcu_haddr_full_corridors.csv"' in promotion


def test_entry_buffer_pin_choice_uses_real_slice_bel_pins():
    # A hard-input cone may also reach a BRAM terminal whose IMUX suffix looks
    # like a LUT pin.  Identity-buffer placement must use actual slice BEL
    # pins, or HADDR[4]'s BramTILE IMUX07 falsely selects logic I[3].
    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(
        encoding="utf-8")
    block = uarch.split("void pack_entry_buffers()", 1)[1].split(
        "void pack_entry_anchor()", 1)[0]
    assert 'ctx->getBelType(b) != ctx->id("GENERIC_SLICE")' in block
    assert 'ctx->getBelPinWire(' in block
    assert 'res == "IMUX"' not in block


def test_haddr5_has_a_qualified_logic_ingress_corridor():
    paths = _rows("mcu_haddr5_logic_paths.csv")
    config = _rows("mcu_haddr5_logic_pip_cfg.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        ("X13Y12_BufMUX15", "X14Y12_RMUX28"),
        ("X14Y12_RMUX28", "X14Y12_IMUX02"),
    ]
    assert [(row["cfg_group"], row["set_selectors"]) for row in config] == [
        ("CFG_RMUX4", "42;47"),
        ("CFG_IMUX0", "30;34"),
    ]
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    bitgen = _bitgen_source()
    assert '"mcu_haddr5_logic_paths.csv"' in arch
    assert '"mcu_haddr5_logic_pip_cfg.csv"' in arch
    assert '"mcu_haddr5_logic_pip_cfg.csv"' in bitgen


def test_haddr3_has_a_qualified_logic_ingress_corridor():
    paths = _rows("mcu_haddr3_logic_paths.csv")
    config = _rows("mcu_haddr3_logic_pip_cfg.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        ("X13Y12_BufMUX13", "X14Y12_RMUX23"),
        ("X14Y12_RMUX23", "X14Y12_IMUX03"),
    ]
    assert [(row["cfg_group"], row["set_selectors"]) for row in config] == [
        ("CFG_RMUX3", "52;57"),
        ("CFG_IMUX0", "41;46"),
    ]
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    bitgen = _bitgen_source()
    assert '"mcu_haddr3_logic_paths.csv"' in arch
    assert '"mcu_haddr3_logic_pip_cfg.csv"' in arch
    assert '"mcu_haddr3_logic_pip_cfg.csv"' in bitgen


def test_mcu_clock_alias_is_exposed_as_typed_global_sources():
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    smoke = (ROOT / "examples" / "designs" / "mcu_bus_clock_route_smoke.v").read_text(
        encoding="utf-8")
    for primitive in ("MCU_SYS_CLOCK", "MCU_BUS_CLOCK"):
        assert primitive in arch
        assert primitive in prims
    assert 'name="CLK", wire="GCLK0"' in arch
    assert "MCU_BUS_CLOCK mcu_bus_clock" in smoke


def test_direct_d_site_has_distinct_f_q_outputs_and_exact_emission():
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    core_logic = (ENGINE / "features" / "core_logic.py").read_text(
        encoding="utf-8")
    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(
        encoding="utf-8")

    assert "(14, 11, 0)" not in arch
    assert "(14, 12, 0)" not in arch
    assert 'OPTIONS.enabled("AGAMEMNON_DIRECT_D")' in arch
    assert 'f_o, q_o = "OMUX%02d" % (3*z + 0), "OMUX%02d" % (3*z + 1)' in arch
    assert "(14, 11, 0)" not in core_logic
    assert "(14, 12, 0)" not in core_logic
    assert 'options.enabled("AGAMEMNON_DIRECT_D")' in core_logic
    assert "(0, 1)" in core_logic
    assert "loc.z >= 4 && loc.z <= 7" in uarch
    assert "loc.x == 14 && loc.y == 12 && loc.z == 0" not in uarch
    assert "if (direct_d_cell && !direct_d_site)" in uarch
    assert "!direct_d_site &&" in uarch
    assert "!strict_allows_odd &&" in uarch


def test_qualified_write_qualifier_footprint_is_complete_and_exact():
    paths = _rows("mcu_ahb_write_qualifier_paths.csv")
    config = _rows("mcu_ahb_write_qualifier_pip_cfg.csv")
    assert len(paths) == 10
    assert len(config) == 10
    assert {(row["signal"], int(row["logical_bit"])) for row in paths} == {
        ("mem_ahb_hwrite", 0), ("mem_ahb_htrans", 1)
    }
    assert {(row["src_wire"], row["dst_wire"]) for row in paths} == {
        (row["src_wire"], row["dst_wire"]) for row in config
    }
    assert {row["dst_wire"] for row in paths if row["dst_wire"].startswith("X14Y12_IMUX")} == {
        "X14Y12_IMUX00", "X14Y12_IMUX01"
    }
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    bitgen = _bitgen_source()
    assert '"mcu_ahb_write_qualifier_paths.csv"' in arch
    # The retained selector table is an extracted fact, not a global sparse
    # overlay: the generic routed-path emitter already produces this footprint.
    assert '"mcu_ahb_write_qualifier_pip_cfg.csv"' not in bitgen


def test_hwdata7_has_a_qualified_complete_consumer_footprint():
    paths = _rows("mcu_hwdata7_logic_paths.csv")
    config = _rows("mcu_hwdata7_logic_pip_cfg.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        (row["src_wire"], row["dst_wire"]) for row in config
    ]
    assert paths[-1]["dst_wire"] == "X14Y11_IMUX01"
    assert [(row["cfg_group"], row["set_selectors"]) for row in config[1:]] == [
        ("CFG_RMUX10", "22;28"),
        ("CFG_RMUX11", "10;19"),
        ("CFG_RMUX14", "53;59"),
        ("CFG_IMUX0", "19;23"),
    ]
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    bitgen = _bitgen_source()
    assert '"mcu_hwdata7_logic_paths.csv"' in arch
    # Loading this table globally changed unrelated retained images.  Keep it
    # available for byte audits until an atomic footprint emitter consumes it.
    assert '"mcu_hwdata7_logic_pip_cfg.csv"' not in bitgen


def test_hwdata0_has_a_qualified_registered_consumer_corridor():
    paths = _rows("mcu_hwdata0_logic_paths.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        ("X13Y10_BufMUX02", "X13Y10_InputMUX02"),
        ("X13Y10_InputMUX02", "X14Y10_RMUX14"),
        ("X14Y10_RMUX14", "X14Y8_RMUX50"),
        ("X14Y8_RMUX50", "X14Y7_RMUX19"),
        ("X14Y7_RMUX19", "X14Y11_RMUX95"),
        ("X14Y11_RMUX95", "X14Y11_IMUX21"),
    ]
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_hwdata0_logic_paths.csv"' in arch


def test_hwdata1_has_a_qualified_registered_consumer_corridor():
    paths = _rows("mcu_hwdata1_logic_paths.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        ("X13Y10_BufMUX03", "X13Y10_InputMUX03"),
        ("X13Y10_InputMUX03", "X14Y10_RMUX47"),
        ("X14Y10_RMUX47", "X14Y10_IMUX13"),
    ]
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_hwdata1_logic_paths.csv"' in arch


def test_hwdata2_has_a_qualified_registered_consumer_corridor():
    paths = _rows("mcu_hwdata2_logic_paths.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        ("X13Y10_BufMUX04", "X13Y10_InputMUX04"),
        ("X13Y10_InputMUX04", "X15Y10_RMUX32"),
        ("X15Y10_RMUX32", "X15Y12_RMUX43"),
        ("X15Y12_RMUX43", "X14Y12_RMUX73"),
        ("X14Y12_RMUX73", "X14Y11_RMUX22"),
        ("X14Y11_RMUX22", "X14Y11_IMUX16"),
        ("X14Y11_OMUX14", "X14Y11_RMUX32"),
        ("X14Y11_RMUX32", "X14Y12_RMUX33"),
        ("X14Y12_RMUX33", "X13Y12_BBMUXE04"),
        ("X13Y12_BBMUXE04", "X0Y5_SinkMUXPseudo04"),
    ]
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_hwdata2_logic_paths.csv"' in arch


def test_hwdata3_has_a_qualified_registered_consumer_corridor():
    paths = _rows("mcu_hwdata3_logic_paths.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        ("X13Y10_BufMUX05", "X13Y10_InputMUX05"),
        ("X13Y10_InputMUX05", "X15Y10_RMUX44"),
        ("X15Y10_RMUX44", "X15Y9_RMUX85"),
        ("X15Y9_RMUX85", "X15Y12_RMUX71"),
        ("X15Y12_RMUX71", "X15Y12_IMUX01"),
        ("X15Y12_OMUX02", "X15Y12_RMUX13"),
        ("X15Y12_RMUX13", "X14Y12_RMUX49"),
        ("X14Y12_RMUX49", "X13Y12_BBMUXE05"),
        ("X13Y12_BBMUXE05", "X0Y5_SinkMUXPseudo05"),
    ]
    assert {row["evidence"] for row in paths} == {"ahb-write-group0-silicon"}
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_hwdata3_logic_paths.csv"' in arch


def test_three_bit_atom_retains_its_final_read_footprint():
    rows = _rows("mcu_scratch3_final_paths.csv")
    by_net = {}
    for row in rows:
        by_net.setdefault(row["net"], []).append(
            (row["src_wire"], row["dst_wire"]))
    assert by_net["scratch2_read"][-1][1] == "X14Y11_IMUX08"
    assert by_net["haddr2_read"][-1][1] == "X14Y11_IMUX09"
    assert by_net["hrdata2"][-1][1] == "X0Y5_SinkMUXPseudo04"
    assert {row["evidence"] for row in rows} == {
        "2026-08-04-l48-scratch3-posted-address-tag-pure-open"}
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_scratch3_final_paths.csv"' in arch


def test_four_bit_atom_retains_its_complete_lane_three_footprint():
    rows = _rows("mcu_scratch4_final_paths.csv")
    by_net = {}
    for row in rows:
        by_net.setdefault(row["net"], []).append(
            (row["src_wire"], row["dst_wire"]))
    assert by_net["hrdata3"][-1][1] == "X0Y5_SinkMUXPseudo05"
    assert by_net["haddr2_read3"][-1][1] == "X14Y11_IMUX13"
    assert by_net["hwdata3_alt"][-1][1] == "X15Y12_IMUX01"
    assert by_net["scratch3_read"][-1][1] == "X14Y11_IMUX12"
    assert by_net["commit_storage3"][-1][1] == "X15Y12_IMUX00"
    assert {row["evidence"] for row in rows} == {
        "2026-08-04-l48-scratch4-posted-address-tag-pure-open",
        "2026-08-04-l48-scratch4-haddr2-read-gate",
        "2026-08-04-l48-scratch4-hwdata3-alt-corridor",
        "2026-08-04-l48-scratch4-storage-to-read-gate",
        "2026-08-04-l48-scratch4-commit-to-storage",
    }
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_scratch4_final_paths.csv"' in arch


def test_hwdata4_all_terminals_are_retained_and_i1_is_the_bank_consumer():
    rows = _rows("mcu_hwdata4_logic_paths.csv")
    by_terminal = {}
    for row in rows:
        by_terminal.setdefault(row["terminal"], []).append(
            (row["src_wire"], row["dst_wire"]))
    assert set(by_terminal) == {"i0", "i1", "i2", "i3"}
    assert by_terminal["i0"][-1][1] == "X15Y12_IMUX08"
    assert by_terminal["i1"][-1][1] == "X15Y12_IMUX09"
    assert by_terminal["i2"][-1][1] == "X15Y12_IMUX10"
    assert by_terminal["i3"][-1][1] == "X15Y12_IMUX11"
    consumers = _rows("mcu_logic_consumer_footprints.csv")
    consumer = next(row for row in consumers
                    if row["signal_token"] == "mcu_hwdata4")
    assert consumer["target_bel"] == "X15Y12_SLICE2"
    assert consumer["target_pin"] == "1"
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_hwdata4_logic_paths.csv"' in arch


def test_five_bit_atom_retains_its_complete_lane_four_footprint():
    rows = _rows("mcu_scratch5_final_paths.csv")
    by_net = {}
    for row in rows:
        by_net.setdefault(row["net"], []).append(
            (row["src_wire"], row["dst_wire"]))
    assert by_net["hrdata4"][-1][1] == "X0Y5_SinkMUXPseudo06"
    assert by_net["haddr2_read4"][-1][1] == "X14Y11_IMUX05"
    assert by_net["scratch4_read"][-1][1] == "X14Y11_IMUX04"
    assert by_net["commit_storage4"][-1][1] == "X15Y12_IMUX08"
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_scratch5_final_paths.csv"' in arch


def test_hwdata5_terminal_family_and_hwdata0_storage_relocation_are_retained():
    rows = _rows("mcu_hwdata5_logic_paths.csv")
    terminals = {}
    for row in rows:
        terminals.setdefault(row["terminal"], []).append(
            (row["src_wire"], row["dst_wire"]))
    assert set(terminals) == {"i0", "i1", "i2", "i3"}
    assert terminals["i1"][-1][1] == "X14Y11_IMUX21"
    assert terminals["i3"][-1][1] == "X14Y11_IMUX23"
    storage0 = _rows("mcu_hwdata0_storage_paths.csv")
    assert storage0[-1]["dst_wire"] == "X14Y11_IMUX29"
    consumers = _rows("mcu_logic_consumer_footprints.csv")
    consumer = next(row for row in consumers
                    if row["signal_token"] == "mcu_hwdata5")
    assert consumer["target_bel"] == "X14Y11_SLICE5"
    assert int(consumer["target_pin"]) == 1
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_hwdata0_storage_paths.csv"' in arch
    assert '"mcu_hwdata5_logic_paths.csv"' in arch


def test_haddr2_posted_tag_corridor_is_retained_from_the_qualified_atom():
    paths = _rows("mcu_haddr2_logic_paths.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in paths] == [
        ("X13Y12_BufMUX12", "X14Y12_RMUX14"),
        ("X14Y12_RMUX14", "X14Y11_RMUX57"),
        ("X14Y11_RMUX57", "X14Y10_RMUX39"),
        ("X14Y10_RMUX39", "X14Y12_RMUX58"),
        ("X14Y12_RMUX58", "X14Y12_IMUX00"),
    ]
    rows = _rows("mcu_logic_consumer_footprints.csv")
    row = next(row for row in rows if row["signal_token"] == "mcu_haddr2")
    assert row["target_bel"] == "X14Y12_SLICE0"
    assert row["target_pin"] == "0"
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_haddr2_logic_paths.csv"' in arch


def test_pipelined_write_token_has_a_coherent_paired_footprint():
    rows = _rows("mcu_ahb_pipelined_token_paths.csv")
    by_signal = {}
    for row in rows:
        by_signal.setdefault(row["signal"], []).append((row["src_wire"], row["dst_wire"]))
    assert by_signal["mem_ahb_hwrite"][-1][1] == "X14Y12_IMUX01"
    assert by_signal["mem_ahb_htrans"][-1][1] == "X14Y12_IMUX00"
    assert all(row["evidence"] == "ahb-pipelined-token-pair-silicon" for row in rows)
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_ahb_pipelined_token_paths.csv"' in arch


def test_pipelined_scratch_internal_paths_are_complete_and_evidence_scoped():
    rows = _rows("mcu_ahb_pipelined_internal_paths.csv")
    by_net = {}
    for row in rows:
        by_net.setdefault(row["net"], []).append((row["src_wire"], row["dst_wire"]))
    assert by_net["write_data_q"][-1][1] == "X14Y11_IMUX29"
    assert by_net["write_pending_q"][-1][1] == "X14Y11_IMUX24"
    assert by_net["write_commit_q"] == [("X14Y11_OMUX19", "X14Y11_IMUX28")]
    assert by_net["scratch_feedback"] == [("X14Y11_OMUX22", "X14Y11_IMUX31")]
    assert by_net["scratch_readback"][-1][1] == "X0Y5_SinkMUXPseudo02"
    assert by_net["hreadyout_constant"][-1][1] == "X0Y5_SinkMUXPseudo00"
    assert by_net["hresp_constant"][-1][1] == "X0Y5_SinkMUXPseudo01"
    assert {row["evidence"] for row in rows} <= {
        "ahb-pipelined-data-projection-silicon",
        "ahb-pipelined-token-toggle-silicon",
        "ahb-pipelined-protocol-transfer-silicon",
        "direct-d-x14y11-slice7-silicon",
    }
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_ahb_pipelined_internal_paths.csv"' in arch


def test_mcu_consumer_pin_permutation_is_exact_footprint_only():
    rows = _rows("mcu_logic_consumer_footprints.csv")
    assert {(row["signal_token"], row["target_bel"], int(row["target_pin"])) for row in rows} == {
        ("mcu_hwrite", "X14Y12_SLICE0", 0),
        ("mcu_htrans1", "X14Y12_SLICE0", 1),
        ("mcu_haddr2", "X14Y12_SLICE0", 0),
        ("mcu_hwdata0", "X14Y11_SLICE5", 1),
        ("mcu_hwdata1", "X14Y10_SLICE3", 1),
        ("mcu_hwdata2", "X14Y11_SLICE4", 0),
        ("mcu_hwdata3", "X15Y12_SLICE0", 1),
        ("mcu_hwdata4", "X15Y12_SLICE2", 1),
        ("mcu_hwdata5", "X14Y11_SLICE5", 1),
        ("mcu_hwdata7", "X14Y11_SLICE0", 1),
    }
    cli = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    assert '"mcu_logic_consumer_footprints.csv"' in cli
    assert 'path("mcu_logic_consumer_footprints.csv")' in uarch


def test_mcu_entry_anchor_accepts_only_an_idempotent_prior_bel_binding():
    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(
        encoding="utf-8")
    block = uarch.split("int bound = 0;\n        for (size_t ei = 0; ei < entries.size(); ++ei)", 1)[1]
    block = block.split("void lock_registered_mcu_inputs()", 1)[0]
    assert "if (cell->bel == BelId())" in block
    assert "else if (cell->bel != b)" in block
    assert "was bound to a BEL other than its corridor-trialed assignment" in block
    assert "cell->attrs.erase(requested)" in block
    assert "explicit BEL disagrees with its corridor-trialed assignment" in block
    assert "if (e.pins.size() != 1)" in uarch
    assert "entry_users != 1" in uarch
    assert "e.forced_bel = rule.bel" in uarch


def test_pipelined_wait_hreadyout_corridor_is_exact_silicon_path():
    rows = _rows("mcu_ahb_pipelined_wait_paths.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in rows] == [
        ("X14Y11_OMUX18", "X15Y11_RMUX37"),
        ("X15Y11_RMUX37", "X15Y8_RMUX54"),
        ("X15Y8_RMUX54", "X14Y8_IMUX17"),
        ("X14Y8_IMUX17", "X14Y8_RMUX69"),
        ("X14Y8_RMUX69", "X14Y12_RMUX86"),
        ("X14Y12_RMUX86", "X13Y12_BBMUXE00"),
        ("X13Y12_BBMUXE00", "X0Y5_SinkMUXPseudo00"),
    ]
    assert {row["evidence"] for row in rows} == {
        "silicon-scratch1-wait-2026-08-04"
    }
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert '"mcu_ahb_pipelined_wait_paths.csv"' in arch


def test_scratch1_two_cycle_wait_commits_on_ready_edge():
    # Physical equations encoded by slice6 INIT=0x3130, an ordinary delayed
    # INIT=0x5555, and scratch INIT=0xef40. Start from the settled idle state,
    # present one write address, then the held data phase. Scratch must change
    # only on the edge that returns HREADYOUT high; the two-cycle-high apply
    # level must not overwrite it on the following edge.
    controller_q, apply_q, scratch, data_q = 1, 0, 0, 0

    def step(pending, hwdata):
        nonlocal controller_q, apply_q, scratch, data_q
        ready_f = apply_q or (controller_q and not pending)
        apply_d = not controller_q
        old_controller, old_apply, old_data = controller_q, apply_q, data_q
        controller_q, apply_q, data_q = int(ready_f), int(apply_d), hwdata
        if old_apply and not old_controller:
            scratch = old_data
        return int(ready_f), scratch

    assert step(1, 0) == (0, 0)  # enter capture wait
    assert step(0, 1) == (0, 0)  # HWDATA captured, raise apply state
    assert step(0, 1) == (1, 1)  # completion edge commits captured data
    assert step(0, 0) == (1, 1)  # apply drains without a second commit


def test_pipelined_apply_candidate_graph_is_experiment_gated():
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    assert 'os.environ.get("AGAMEMNON_PIPELINED_APPLY_EXPERIMENT")' in arch
    rows = _rows("mcu_ahb_pipelined_apply_candidate_paths.csv")
    assert [(row["src_wire"], row["dst_wire"]) for row in rows] == [
        ("X14Y11_OMUX19", "X14Y11_IMUX56"),
        ("X14Y11_OMUX43", "X14Y11_IMUX26"),
    ]
    assert {row["evidence"] for row in rows} == {
        "candidate-corpus-template-not-qualified"
    }


def test_long_period_bus_clock_oracle_is_original_and_bounded():
    source = (ROOT / "qualification" / "mcu_bus_clock_lfsr16.v").read_text(
        encoding="utf-8")
    assert "x^16 + x^14 + x^13 + x^11 + 1" in source
    assert "state <= {state[14:0]" in source
    for bit in range(16):
        assert "MCU_DOUT mcu_h%d" % bit in source

    reset_source = (
        ROOT / "qualification" / "mcu_bus_clock_lfsr16_gpio_reset.v"
    ).read_text(encoding="utf-8")
    assert "MCU_BUS_CLOCK mcu_bus_clock" in reset_source
    assert "MCU mcu_reset_control" in reset_source
    assert "if (reset_request)" in reset_source
    assert "state <= 16'h0000" in reset_source


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
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    bitgen = _bitgen_source()
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
    arch = (ENGINE / "archgen.py").read_text(encoding="utf-8")
    bitgen = _bitgen_source()
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
