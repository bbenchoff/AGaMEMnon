from pathlib import Path

import pytest

from agamemnon.engine.features import CHIPDB_OWNERS, FEATURES, validate_features
from agamemnon.engine.features.bram import FEATURE as BRAM_FEATURE
from agamemnon.engine.features.carry import FEATURE as CARRY_FEATURE
from agamemnon.engine.features.clocks import (
    FEATURE as CLOCK_FEATURE,
    VP_AGM_007_CLOCK_TILES,
    refuse_silicon_negative_clock_reach,
)
from agamemnon.engine.features.clock_validate import ClockValidationResult
from agamemnon.engine.features.core_logic import FEATURE as CORE_LOGIC_FEATURE
from agamemnon.engine.features.mcu_ahb import (
    CORRIDOR_PIP_CFG_FILES,
    EXACT_PIP_CFG_FILES,
    EXIT_PAIR_FILES,
    FEATURE as MCU_AHB_FEATURE,
)
from agamemnon.engine.features.mcu_gpio import FEATURE as MCU_GPIO_FEATURE
from agamemnon.engine.features.physical_io import (
    BITSTREAM_FILES as PHYSICAL_IO_BITSTREAM_FILES,
    FEATURE as PHYSICAL_IO_FEATURE,
)
from agamemnon.engine.features.protocol import (
    BitstreamContext,
    EmissionPhase,
    FeatureDescriptor,
    WritableRegion,
)
from agamemnon.engine.features.routing import (
    FEATURE as ROUTING_FEATURE,
    RoutingState,
)
from agamemnon.engine.registry import CONSTANTS, options_from


ROOT = Path(__file__).resolve().parents[1]


def test_route_through_is_the_first_declared_feature():
    assert [feature.descriptor.feature_id for feature in FEATURES] == [
        "route_through", "bram", "mcu_ahb", "carry", "physical_io", "clocks",
        "mcu_gpio", "routing", "core_logic",
    ]
    descriptor = FEATURES[0].descriptor
    assert descriptor.phase is EmissionPhase.ROUTING
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files == (
        "route_through_footprints.csv",
        "bram_control_route_through_footprints.csv",
    )
    assert CHIPDB_OWNERS["route_through_footprints.csv"] == "route_through"
    assert (ROOT / "agamemnon" / "chipdb" / descriptor.chipdb_files[0]).is_file()
    assert descriptor.writable_regions == tuple(
        WritableRegion(
            kind="sparse_table", source=filename,
            byte_field="byte", mask_field="write_mask",
        )
        for filename in descriptor.chipdb_files
    )
    assert CHIPDB_OWNERS["bram_resolver.json"] == "bram"
    assert CHIPDB_OWNERS["bram_cell.csv"] == "bram"
    assert CHIPDB_OWNERS["mcu_ahb32_pip_cfg.csv"] == "mcu_ahb"
    assert CHIPDB_OWNERS["slice_cfg.csv"] == "carry"
    assert CHIPDB_OWNERS["pips_io.csv"] == "physical_io"
    assert CHIPDB_OWNERS["clk0_spine.json"] == "clocks"
    assert CHIPDB_OWNERS["mcu_gpio5_loop_pip_cfg.csv"] == "mcu_gpio"
    assert CHIPDB_OWNERS["sel_edge_pairs.agdb"] == "routing"
    for feature in FEATURES:
        for filename in feature.descriptor.chipdb_files:
            assert (ROOT / "agamemnon" / "chipdb" / filename).is_file()


def test_feature_registry_rejects_duplicate_chipdb_ownership():
    class Duplicate:
        descriptor = FeatureDescriptor(
            feature_id="duplicate",
            options=(),
            chipdb_files=("route_through_footprints.csv",),
            writable_regions=(),
            phase=EmissionPhase.ROUTING,
            evidence=("qualification/bram_evidence.jsonl",),
            maturity="diagnostic",
            evidence_tier="decoded",
            architecture="none",
            bitstream="none",
        )

        def add_architecture(self, context):
            return None

        def clear_bitstream(self, context):
            return 0

        def emit_bitstream(self, context):
            return 0

    with pytest.raises(ValueError, match="owned by both"):
        validate_features(FEATURES + (Duplicate(),))


def test_every_chipdb_csv_has_exactly_one_feature_owner():
    csv_names = {
        path.name for path in (ROOT / "agamemnon" / "chipdb").glob("*.csv")
    }
    assert csv_names <= set(CHIPDB_OWNERS)


def test_mcu_ahb_feature_owns_exact_selector_loading():
    descriptor = MCU_AHB_FEATURE.descriptor
    assert descriptor.phase is EmissionPhase.MCU_EDGES
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files[:len(EXACT_PIP_CFG_FILES)] == EXACT_PIP_CFG_FILES
    assert descriptor.writable_regions == tuple(
        WritableRegion(kind="selector_table", source=filename)
        for filename in EXACT_PIP_CFG_FILES + CORRIDOR_PIP_CFG_FILES
    )
    fields = MCU_AHB_FEATURE.load_exact_pip_fields(
        ROOT / "agamemnon" / "chipdb"
    )
    # 257 pre-existing exact request/data fields, the three silicon-qualified
    # HSIZE1 corridor selectors, and seven X13Y12 address/control alternatives.
    assert len(fields) == 267
    metadata = MCU_AHB_FEATURE.load_routing_metadata(
        ROOT / "agamemnon" / "chipdb",
        options_from({}),
        (MCU_GPIO_FEATURE.load_exact_pip_fields(
            ROOT / "agamemnon" / "chipdb"
        ),),
    )
    # The aggregate now includes the exact GPIO5, UART0/1/2, SPI0/1 and I2C0/1
    # boundary compositions in addition to the AHB request/data corridors.
    # UART1 contributes seventeen ordinary selector fields; its two top-pad
    # feeder fields remain owned by physical_io and are not counted here.
    # UART2 contributes fourteen unique ordinary selector fields; its two
    # terminal top-pad feeder fields likewise remain owned by physical_io.
    # X22Y7_InputMUX10{0,1} ->
    # X18Y7_RMUX03 share codeword 31;38 because
    # they are SYNTHETIC ALIASES for one real wire, X22Y7_InputMUX01 -- renamed
    # at promotion by features/mcu_ahb.py so the router cannot swap the two ADC
    # oracle corridors.  Two independent vendor builds harvest the same real
    # wire and the same codeword, so sharing it is correct, not ambiguous.
    # selector_injectivity.SYNTHETIC_SOURCE_ALIASES carries the evidence.
    # The exact 11-source fabric-master request-control composition adds 39
    # recorded fields, 38 of which are new physical keys (one was already
    # present in the aggregate tables). The first dynamic request-payload
    # lane adds four exact HADDR[2] fields from one retained register route.
    # The SRAM-base HADDR[29] branch adds three fields, one identical to the
    # existing HSEL source field, for two additional unique physical keys.
    assert len(metadata.exact_pips) == 896
    site_metadata = MCU_AHB_FEATURE.load_routing_metadata(
        ROOT / "agamemnon" / "chipdb",
        options_from({"AGAMEMNON_BRAM_SITE_READ_PATHS": "1"}),
        (MCU_GPIO_FEATURE.load_exact_pip_fields(
            ROOT / "agamemnon" / "chipdb"
        ),),
    )
    # The optional site profile adds 392 unique fields over the current
    # 896-field release aggregate; overlaps remain deduplicated by exact
    # edge key and the ambiguous CtrlMUX row above is still refused.
    assert len(site_metadata.exact_pips) == 1288
    assert len(metadata.exit_pairs) == 168
    assert all(CHIPDB_OWNERS[name] == "mcu_ahb" for name in CORRIDOR_PIP_CFG_FILES)
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen.py").read_text(
        encoding="utf-8"
    )
    assert "MCU_AHB_FEATURE.load_routing_metadata" in bitgen
    assert '"mcu_ahb32_pip_cfg.csv"' not in bitgen


@pytest.mark.parametrize(
    "missing,load",
    [
        (EXACT_PIP_CFG_FILES[0], "exact"),
        (CORRIDOR_PIP_CFG_FILES[1], "metadata"),
        (EXIT_PAIR_FILES[0], "metadata"),
    ],
)
def test_mcu_ahb_release_tables_fail_closed_when_missing(monkeypatch, missing, load):
    chipdb = ROOT / "agamemnon" / "chipdb"
    original_exists = Path.exists

    def selective_exists(path):
        return False if path.name == missing else original_exists(path)

    monkeypatch.setattr(Path, "exists", selective_exists)
    with pytest.raises(ValueError, match=r"requires chipdb/%s" % missing):
        if load == "exact":
            MCU_AHB_FEATURE.load_exact_pip_fields(chipdb)
        else:
            MCU_AHB_FEATURE.load_routing_metadata(chipdb, options_from({}))


def test_disabled_bram_site_read_table_is_explicitly_optional(monkeypatch):
    chipdb = ROOT / "agamemnon" / "chipdb"
    original_exists = Path.exists

    def selective_exists(path):
        if path.name == "bram_site_read_pip_cfg.csv":
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", selective_exists)
    MCU_AHB_FEATURE.load_routing_metadata(chipdb, options_from({}))
    with pytest.raises(ValueError, match="requires chipdb/bram_site_read_pip_cfg.csv"):
        MCU_AHB_FEATURE.load_routing_metadata(
            chipdb, options_from({"AGAMEMNON_BRAM_SITE_READ_PATHS": "1"})
        )


def test_bram_and_routing_features_load_their_shared_selector_cells():
    cell_map, mux_groups = ROUTING_FEATURE.load_cell_map()
    original_count = len(cell_map)
    assert BRAM_FEATURE.load_selector_cells(
        ROOT / "agamemnon" / "chipdb", cell_map
    ) == 8548
    assert len(cell_map) > original_count
    assert mux_groups
    assert len(ROUTING_FEATURE.load_mcu_cells(
        ROOT / "agamemnon" / "chipdb"
    )) == 4440


@pytest.mark.parametrize("width", ["00000", "01111"])
def test_initialized_bram_porta_escape_modes_fail_closed(width):
    module = {"cells": {"rom": {
        "type": "ALTA_BRAM9K",
        "attributes": {"NEXTPNR_BEL": "X13Y4_BRAM0"},
        "parameters": {"PORTA_WIDTH": width, "INIT_VAL": "10010110"},
        "connections": {"DataOutA": [17], "AddressA": [18]},
    }}}
    # DataOutA bit 17 needs a second reference to be observably read.
    module["cells"]["sink"] = {
        "type": "GENERIC_SLICE", "parameters": {},
        "connections": {"I[0]": [17]},
    }
    with pytest.raises(SystemExit, match="VP-AGM-006"):
        BRAM_FEATURE.prepare(
            module, ROOT / "agamemnon" / "chipdb", options_from({})
        )


def test_bram_transit_routing_loads_without_a_bram_cell():
    state = BRAM_FEATURE.prepare(
        {"cells": {}}, ROOT / "agamemnon" / "chipdb", options_from({})
    )
    route_sets = []
    assert not state.cells
    assert BRAM_FEATURE.resolve_route(
        state,
        (14, 4, "RMUX", 20),
        (13, 4, "RMUX", 81),
        {},
        {},
        route_sets,
        [],
    ) is True
    assert route_sets == [(73069, 64), (73185, 16)]


def test_bram_release_selector_cells_fail_closed(monkeypatch):
    original_exists = Path.exists

    def selective_exists(path):
        return False if path.name == "bram_cell.csv" else original_exists(path)

    monkeypatch.setattr(Path, "exists", selective_exists)
    with pytest.raises(ValueError, match="bram requires chipdb/bram_cell.csv"):
        BRAM_FEATURE.load_selector_cells(
            ROOT / "agamemnon" / "chipdb", {}
        )


def test_carry_feature_owns_slice_selectors_and_emission():
    descriptor = CARRY_FEATURE.descriptor
    assert descriptor.phase is EmissionPhase.LOGIC
    assert descriptor.maturity == "release"
    # slice_cfg.csv is the emitting table; carry_seam_corpus.csv is declared so
    # the chipdb has an owner for it, but it is reference data only (the
    # vendor-observed seam geometry) and must NOT gain a writable region.
    assert descriptor.chipdb_files == ("slice_cfg.csv", "carry_seam_corpus.csv")
    assert descriptor.writable_regions == (WritableRegion(
        kind="selector_table",
        source="slice_cfg.csv",
        byte_field="byte",
        mask_field="mask",
    ),)
    assert CARRY_FEATURE.descriptor.chipdb_files[0] == "slice_cfg.csv"

    fields = CARRY_FEATURE.load_slice_config(ROOT / "agamemnon" / "chipdb")
    module = {
        "ports": {},
        "cells": {
            "ordinary_vcc": {
                "type": "GENERIC_SLICE",
                "attributes": {"NEXTPNR_BEL": "X1Y1_SLICE0"},
                "parameters": {"K": "100", "FF_USED": "0", "INIT": "1" * 16},
                "port_directions": {"F": "output", "I": "input"},
                "connections": {"F": [20], "I": ["0", "0", "0", "0"]},
            },
            "seed": {
                "type": "GENERIC_SLICE",
                "attributes": {"NEXTPNR_BEL": "X20Y12_SLICE0"},
                "parameters": {"K": "100", "FF_USED": "0", "INIT": "0" * 16},
                "port_directions": {"COUT": "output", "I": "input"},
                "connections": {"COUT": [10], "I": ["0", "0", "0", "0"]},
            },
            "bit0": {
                "type": "GENERIC_SLICE",
                "attributes": {"NEXTPNR_BEL": "X20Y12_SLICE1"},
                "parameters": {
                    "K": "100", "FF_USED": "0", "INIT": "1001011011101000",
                    "BYPASSEN": "1",
                },
                "port_directions": {
                    "CIN": "input", "COUT": "output", "F": "output", "I": "input",
                },
                "connections": {
                    "CIN": [10], "COUT": [11], "F": [12],
                    "I": ["0", "0", "0", 20],
                },
            },
        },
        "netnames": {
            "ordinary_d_source": {"bits": [20]},
            "carry_link": {
                "bits": [10],
                "attributes": {
                    "ROUTING": (
                        "X20Y12_CARRYIN01;"
                        "X20Y12_CARRYOUT00.X20Y12_CARRYIN01;1;"
                        "X20Y12_CARRYOUT00;;1"
                    ),
                },
            },
            "carry_tail": {"bits": [11]},
            "sum": {"bits": [12]},
        },
    }
    state = CARRY_FEATURE.prepare(module, fields)
    assert len(state.clears) == 8
    assert state.sets == [
        fields[(20, 12, "CFG_LUTCMUX[1]")],
        fields[(20, 12, "CFG_LUTCMUX[3]")],
        fields[(20, 12, "CFG_BYPASSEN[1]")],
    ]
    image = bytearray([0xFF]) * (max(byte for byte, _ in state.clears) + 1)
    context = BitstreamContext(
        image=image,
        module=module,
        chipdb_root=ROOT / "agamemnon" / "chipdb",
        options=None,
        state=state,
    )
    assert CARRY_FEATURE.clear_bitstream(context) == 8
    assert CARRY_FEATURE.emit_bitstream(context) == 3
    for byte, mask in set(state.clears) - set(state.sets):
        assert image[byte] & mask == 0
    for byte, mask in state.sets:
        assert image[byte] & mask == mask
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen.py").read_text(
        encoding="utf-8"
    )
    assert "CARRY_FEATURE.load_slice_config" in bitgen
    assert '("carry", CARRY_FEATURE)' in bitgen
    assert "feature.clear_bitstream(context)" in bitgen
    assert "CARRY_FEATURE.emit_bitstream" in bitgen


def test_carry_slice_selectors_fail_closed_when_missing(monkeypatch):
    original_exists = Path.exists

    def selective_exists(path):
        return False if path.name == "slice_cfg.csv" else original_exists(path)

    monkeypatch.setattr(Path, "exists", selective_exists)
    with pytest.raises(ValueError, match="carry requires chipdb/slice_cfg.csv"):
        CARRY_FEATURE.load_slice_config(ROOT / "agamemnon" / "chipdb")


def test_physical_io_feature_owns_pad_selectors_and_emission():
    descriptor = PHYSICAL_IO_FEATURE.descriptor
    assert descriptor.phase is EmissionPhase.IO
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files[:len(PHYSICAL_IO_BITSTREAM_FILES)] == \
        PHYSICAL_IO_BITSTREAM_FILES
    assert descriptor.writable_regions[0] == WritableRegion(
        kind="cell_map",
        source="pips_io.csv",
        byte_field="byte",
        mask_field="mask",
    )

    module = {"cells": {}, "netnames": {
        "left_pad": {"attributes": {
            "ROUTING": "X0Y4_RMUX30.X0Y4_IOMUX00"
        }}
    }}
    state = PHYSICAL_IO_FEATURE.prepare(
        module, ROOT / "agamemnon" / "chipdb", {}, archival_legacy=True
    )
    assert "X0Y4_RMUX30.X0Y4_IOMUX00" in state.pips
    assert (0, 4, 0) in state.io_pad_hops
    assert state.sets
    assert state.clears
    assert state.padfeed_exact
    assert state.pad_input_edge
    last_byte = max(byte for byte, _ in state.sets + state.clears)
    image = bytearray([0xFF]) * (last_byte + 1)
    context = BitstreamContext(
        image=image,
        module=module,
        chipdb_root=ROOT / "agamemnon" / "chipdb",
        options=None,
        state=state,
    )
    assert PHYSICAL_IO_FEATURE.clear_bitstream(context) == len(state.clears)
    assert PHYSICAL_IO_FEATURE.emit_bitstream(context) == len(state.sets)
    for byte, mask in state.sets:
        assert image[byte] & mask == mask

    state.pad_input_used.add(((17, 13, 7, 17, 12, 61), ((1, 2),), ((2, 4),)))
    pad_image = bytearray([0xFF, 0x00, 0xFF])
    pad_context = BitstreamContext(
        image=pad_image,
        module=module,
        chipdb_root=ROOT / "agamemnon" / "chipdb",
        options=None,
        state=state,
    )
    assert PHYSICAL_IO_FEATURE.emit_pad_inputs(pad_context) == 2
    assert pad_image[1] & 2
    assert not pad_image[2] & 4

    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen.py").read_text(
        encoding="utf-8"
    )
    assert "PHYSICAL_IO_FEATURE.prepare" in bitgen
    assert '("physical_io", PHYSICAL_IO_FEATURE)' in bitgen
    assert "feature.clear_bitstream(context)" in bitgen
    assert "PHYSICAL_IO_FEATURE.emit_bitstream" in bitgen
    assert "PHYSICAL_IO_FEATURE.emit_pad_inputs" in bitgen


def test_physical_io_release_tables_fail_closed(monkeypatch):
    chipdb = ROOT / "agamemnon" / "chipdb"
    original_exists = Path.exists

    def selective_exists(path):
        return False if path.name == "padfeed_L48_top.csv" else original_exists(path)

    monkeypatch.setattr(Path, "exists", selective_exists)
    with pytest.raises(ValueError, match="physical_io requires chipdb/padfeed_L48_top.csv"):
        PHYSICAL_IO_FEATURE.prepare(
            {"cells": {}}, chipdb, {}, False, options_from({})
        )


def test_physical_io_node_corridors_fail_closed(monkeypatch):
    chipdb = ROOT / "agamemnon" / "chipdb"
    missing = "pad_oe_L48_left_corridors.csv"
    original_exists = Path.exists

    def selective_exists(path):
        return False if path.name == missing else original_exists(path)

    monkeypatch.setattr(Path, "exists", selective_exists)
    with pytest.raises(ValueError, match=r"node pinout requires chipdb/%s" % missing):
        PHYSICAL_IO_FEATURE.load_exact_pip_fields(chipdb)


def test_clock_feature_owns_distribution_and_global_emission():
    descriptor = CLOCK_FEATURE.descriptor
    assert descriptor.phase is EmissionPhase.CLOCKS
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files == (
        "clock_source_profiles_l48.csv",
        "clock_legacy_extra_leaves.json",
        "clock_reach_silicon_negative.csv",
        "clk0_spine.json",
        "logictile_clksel0.json",
        "logictile_asyncmux3.json",
    )
    options = options_from({})
    selector_cells = {(10, 4, "CFG_SEAMMUX", 5): (69603, 128)}
    state = CLOCK_FEATURE.prepare(
        {(10, 4)}, [(1, 1)], [], selector_cells,
        ROOT / "agamemnon" / "chipdb", options,
        ClockValidationResult(
            owner_bit=1,
            source_profile="HSE_CLKIN",
            source_class="HSE",
            clocked_tiles=frozenset({(10, 4)}),
            active_slice_leaves=frozenset({"X10Y4_ClkMUX00"}),
            bram_edges=frozenset(),
            quarantined_extra_leaves=frozenset(),
            quarantined_bitstream_sha256=None,
            catalog_sha256="0" * 64,
            topology_sha256="0" * 64,
        ),
    )
    assert state.registered
    assert (69603, 128) in state.sets
    image = bytearray(99936)
    context = BitstreamContext(
        image=image,
        module={},
        chipdb_root=ROOT / "agamemnon" / "chipdb",
        options=options,
        state=state,
    )
    assert CLOCK_FEATURE.emit_bitstream(context) == len(state.sets)
    assert CLOCK_FEATURE.emit_global(context) == 165
    assert image[71737] & 0x04
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen.py").read_text(
        encoding="utf-8"
    )
    assert "CLOCK_FEATURE.prepare" in bitgen
    assert "CLOCK_FEATURE.emit_bitstream" in bitgen
    assert "CLOCK_FEATURE.emit_global" in bitgen


def test_clock_feature_refuses_exact_vp_agm_007_constellation_only():
    failing = options_from({"AGAMEMNON_SYSCLK": "100", "AGAMEMNON_HSE": "8"})
    with pytest.raises(SystemExit, match="VP-AGM-007"):
        refuse_silicon_negative_clock_reach(
            VP_AGM_007_CLOCK_TILES | {(14, 10)}, failing
        )

    refuse_silicon_negative_clock_reach(
        VP_AGM_007_CLOCK_TILES - {(20, 12)}, failing
    )
    refuse_silicon_negative_clock_reach(
        VP_AGM_007_CLOCK_TILES,
        options_from({"AGAMEMNON_SYSCLK": "50", "AGAMEMNON_HSE": "8"}),
    )


def test_mcu_gpio_feature_owns_exact_fields_and_inactive_defaults():
    descriptor = MCU_GPIO_FEATURE.descriptor
    assert descriptor.phase is EmissionPhase.MCU_EDGES
    fields = MCU_GPIO_FEATURE.load_exact_pip_fields(ROOT / "agamemnon" / "chipdb")
    # Exact GPIO5 plus the retained UART0/1/2, SPI0/1 and I2C0/1 hard-boundary
    # compositions. UART1 adds seventeen ordinary selector fields; its two
    # source-dependent top-pad feeders are owned by physical_io. UART2 adds
    # fourteen unique ordinary selector fields; its two terminal feeders are
    # likewise owned by physical_io.
    assert len(fields) == 198
    module = {"cells": {"source": {"type": "MCU_GPIO5_OUT_DATA0"}}}
    mcu_cells = {
        (9, 5, "BBMUXS%d" % mux, 8): (100 + mux, 1)
        for mux in (0, 1, 3, 4, 5, 6, 7)
    }
    state = MCU_GPIO_FEATURE.prepare(module, mcu_cells)
    assert len(state.sets) == 7
    image = bytearray(120)
    context = BitstreamContext(
        image=image, module=module,
        chipdb_root=ROOT / "agamemnon" / "chipdb",
        options=None, state=state,
    )
    assert MCU_GPIO_FEATURE.emit_bitstream(context) == 7
    assert all(image[100 + mux] == 1 for mux in (0, 1, 3, 4, 5, 6, 7))


def test_mcu_gpio_release_selector_tables_fail_closed(monkeypatch):
    chipdb = ROOT / "agamemnon" / "chipdb"
    missing = "mcu_gpio5_loop_pip_cfg.csv"
    original_exists = Path.exists

    def selective_exists(path):
        return False if path.name == missing else original_exists(path)

    monkeypatch.setattr(Path, "exists", selective_exists)
    with pytest.raises(ValueError, match=r"mcu_gpio requires chipdb/%s" % missing):
        MCU_GPIO_FEATURE.load_exact_pip_fields(chipdb)


def test_routing_release_selector_table_fails_closed(monkeypatch):
    original_exists = Path.exists

    def selective_exists(path):
        return False if path.name == "sel_edge_pairs.agdb" else original_exists(path)

    monkeypatch.setattr(Path, "exists", selective_exists)
    with pytest.raises(ValueError, match="routing requires chipdb/sel_edge_pairs.agdb"):
        ROUTING_FEATURE.load_selector_tables(
            ROOT / "agamemnon" / "chipdb", options_from({})
        )


def test_routing_feature_owns_resolution_and_physical_writes():
    descriptor = ROUTING_FEATURE.descriptor
    assert descriptor.phase is EmissionPhase.ROUTING
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files == (
        "pips_full.csv", "pips_mcuedge.csv", "sel_map.json",
        "sel_edge_pairs.agdb", "sel_tables.agdb", "train_lut.agdb",
        "selector_conflict_atlas.agdb", "research_knowledge_manifest.json",
        "routing_selector_admission.json",
        "rrg_edges_full.csv", "rrg_omux_imux_full.csv",
        "rrg_rmux_imux_full.csv", "dead_edges_silicon.csv",
        "exit_feeder_whitelist.csv", "master_conduction.csv",
        "ff2_conduction.csv", "harvest_conduction.csv",
        "corpus_conduction.csv", "ff_feedback_map.csv",
        "wire_timing_worst.json", "wire_timing_exact_safe.json",
        "wire_timing_exact_safe_manifest.json", "wire_timing_measured.json",
        "wires.csv", "pip_usage.csv", "mcu_region_witness.csv",
        "soft_ripple_region_witness.csv",
        "bbmuxe_fanin.csv", "logictile_config_template.csv",
        "border_edge_partial_cells.csv",
    )
    tables = ROUTING_FEATURE.load_selector_tables(
        ROOT / "agamemnon" / "chipdb", options_from({})
    )
    assert tables.clean_edge
    assert tables.relative_edge

    state = RoutingState(sets=[(3, 0x10)], clears=[(2, 0x04)])
    image = bytearray([0xFF]) * 5
    context = BitstreamContext(
        image=image,
        module={},
        chipdb_root=ROOT / "agamemnon" / "chipdb",
        options=options_from({}),
        state=state,
    )
    assert ROUTING_FEATURE.clear_bitstream(context) == 1
    assert ROUTING_FEATURE.emit_bitstream(context) == 1
    assert image[2] == 0xFB
    assert image[3] == 0xFF

    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen.py").read_text(
        encoding="utf-8"
    )
    assert "ROUTING_FEATURE.prepare" in bitgen
    assert '("routing", ROUTING_FEATURE)' in bitgen
    assert "feature.clear_bitstream(context)" in bitgen
    assert "ROUTING_FEATURE.emit_bitstream" in bitgen
    assert "route_sets" not in bitgen
    assert "route_clears" not in bitgen


def test_core_logic_feature_owns_lut_and_register_emission():
    descriptor = CORE_LOGIC_FEATURE.descriptor
    assert descriptor.phase is EmissionPhase.LOGIC
    assert descriptor.maturity == "release"
    assert descriptor.chipdb_files == (
        "mcu_endpoint_capabilities.csv",
        "mcu_endpoint_capability_manifest.json",
    )

    module = {"cells": {"slice": {
        "type": "GENERIC_SLICE",
        "attributes": {
            "NEXTPNR_BEL": "X1Y4_SLICE0",
            "AGRV2K_REGISTER_INPUT_MODE": "LUT_COMPUTE_TO_FF",
        },
        "parameters": {"INIT": "0000000000000000", "FF_USED": "1"},
        "connections": {"CLK": [2], "Q": [3], "F": [], "I": []},
    }}, "netnames": {
        "clock": {"bits": [2]}, "q": {"bits": [3]},
    }}
    selector_cells = {
        (1, 4, "CFG_OMUX0", selection): (80000 + selection, 1)
        for selection in range(3)
    }
    state = CORE_LOGIC_FEATURE.prepare(
        module, selector_cells, options_from({}), CONSTANTS,
    )
    assert state.slices == [(1, 4, 0)]
    assert state.clocked_tiles == {(1, 4)}
    assert state.register_sets == [(80002, 1)]
    assert len(state.lut_sets) == 16

    image = bytearray([0xFF]) * 90000
    context = BitstreamContext(
        image=image, module=module,
        chipdb_root=ROOT / "agamemnon" / "chipdb",
        options=options_from({}), state=state,
    )
    assert CORE_LOGIC_FEATURE.clear_bitstream(context) == 19
    assert CORE_LOGIC_FEATURE.emit_bitstream(context) == 16
    assert CORE_LOGIC_FEATURE.emit_register_modes(context) == 1
    assert image[80002] & 1

    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen.py").read_text(
        encoding="utf-8"
    )
    assert "CORE_LOGIC_FEATURE.prepare" in bitgen
    assert '("core_logic", CORE_LOGIC_FEATURE)' in bitgen
    assert "feature.clear_bitstream(context)" in bitgen
    assert "CORE_LOGIC_FEATURE.emit_bitstream" in bitgen
    assert "CORE_LOGIC_FEATURE.emit_register_modes" in bitgen
    assert "lut_sets" not in bitgen
    assert "reg_sets" not in bitgen


def test_core_logic_and_carry_own_their_architecture_contributions():
    archgen = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(
        encoding="utf-8"
    )
    core_logic = (
        ROOT / "agamemnon" / "engine" / "features" / "core_logic.py"
    ).read_text(encoding="utf-8")
    carry = (
        ROOT / "agamemnon" / "engine" / "features" / "carry.py"
    ).read_text(encoding="utf-8")
    assert "CORE_LOGIC_FEATURE.add_architecture" in archgen
    assert "CARRY_FEATURE.add_architecture" in archgen
    assert 'type="GENERIC_SLICE"' not in archgen
    assert 'type="GENERIC_SLICE"' in core_logic
    assert "CARRY_SEAM" not in archgen
    assert "CARRY_SEAM" in carry
    assert "remains in arch.py" not in CORE_LOGIC_FEATURE.descriptor.architecture
    assert "remains in arch.py" not in CARRY_FEATURE.descriptor.architecture


def test_physical_io_and_clocks_own_their_architecture_contributions():
    archgen = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(
        encoding="utf-8"
    )
    physical_io = (
        ROOT / "agamemnon" / "engine" / "features" / "physical_io.py"
    ).read_text(encoding="utf-8")
    clocks = (
        ROOT / "agamemnon" / "engine" / "features" / "clocks.py"
    ).read_text(encoding="utf-8")
    assert "PHYSICAL_IO_FEATURE.add_architecture" in archgen
    assert "CLOCK_FEATURE.add_architecture" in archgen
    assert 'type="GENERIC_IOB"' not in archgen
    assert 'type="GENERIC_IOB"' in physical_io
    assert 'type="GCLK%d_SPINE"' not in archgen
    assert 'type="GCLK%d_SPINE"' in clocks
    assert "remains in arch.py" not in PHYSICAL_IO_FEATURE.descriptor.architecture
    assert "remain in arch.py" not in CLOCK_FEATURE.descriptor.architecture


def test_routing_feature_owns_general_architecture_construction():
    archgen = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(
        encoding="utf-8"
    )
    routing = (
        ROOT / "agamemnon" / "engine" / "features" / "routing.py"
    ).read_text(encoding="utf-8")
    assert "ROUTING_FEATURE.add_architecture" in archgen
    assert '"rrg_edges_full.csv"' not in archgen
    assert '"rrg_edges_full.csv"' in routing
    assert "def _wire_delay" not in archgen
    assert "def _wire_delay" in routing
    assert "General routing graph construction remains" not in \
        ROUTING_FEATURE.descriptor.architecture


def test_hard_boundary_features_own_their_architecture_contributions():
    archgen = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(
        encoding="utf-8"
    )
    mcu_ahb = (
        ROOT / "agamemnon" / "engine" / "features" / "mcu_ahb.py"
    ).read_text(encoding="utf-8")
    mcu_gpio = (
        ROOT / "agamemnon" / "engine" / "features" / "mcu_gpio.py"
    ).read_text(encoding="utf-8")
    bram = (
        ROOT / "agamemnon" / "engine" / "features" / "bram.py"
    ).read_text(encoding="utf-8")
    assert "MCU_AHB_FEATURE.add_architecture" in archgen
    assert "MCU_AHB_FEATURE.add_bels" in archgen
    assert "BRAM_FEATURE.add_architecture" in archgen
    assert '"pips_mcuedge_routing.csv"' not in archgen
    assert '"pips_mcuedge_routing.csv"' in mcu_ahb
    assert '"mcu_gpio5_loop_paths.csv"' in mcu_gpio
    assert '"bram9k_edges.csv"' not in archgen
    assert '"bram9k_edges.csv"' in bram
    assert 'type="ALTA_BRAM9K"' in bram
    assert "remain in the arch driver" not in BRAM_FEATURE.descriptor.architecture
