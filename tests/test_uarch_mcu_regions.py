"""Native Regions for the witnessed wide-MCU placement envelope."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
WITNESS = ROOT / "agamemnon" / "chipdb" / "mcu_region_witness.csv"


def _between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def test_region_bounds_are_the_retained_16_build_envelope():
    rows = list(csv.DictReader(WITNESS.open(encoding="utf-8", newline="")))
    assert rows == [{
        "scope": "wide_mcu_release",
        "x_min": "14",
        "x_max": "20",
        "y_min": "6",
        "y_max": "12",
        "decoded_builds": "16",
        "max_logic_slices": "171",
        "max_occupied_tiles": "11",
        "max_slices_per_tile": "16",
        "provenance": "retained_four_design_four_seed_full_placement_decode",
    }]


def test_runtime_asset_is_hash_fingerprinted_and_copied_to_the_devdb():
    cli = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    runtime = _between(cli, "runtime_assets = (", "emit_context =")
    assert '"mcu_region_witness.csv"' in runtime
    assert "runtime_asset, hashlib.sha256" in cli
    assert "shutil.copy(src_asset, devdb)" in cli


def test_native_regions_are_connectivity_derived_and_not_named_placements():
    source = UARCH.read_text(encoding="utf-8")
    regions = _between(source, "void constrain_mcu_regions()", "// ---- pack:")

    assert 'std::getenv("AGRV2K_CONDPLACE")' in regions
    assert 'ctx->id("AGRV2K_MCU_ENTRY_ROW")' in regions
    assert 'for (const char *port : {"Q", "F", "COUT"})' in regions
    assert 'for (const char *port_name : {"DIN", "RESETN"})' in regions
    assert "ctx->getBelPinWire(source_bel, port)" in regions
    assert 'boundary_x != 13' in regions
    assert "typed hard-input cone seed(s)" in regions
    assert "MCU_AHB_HSIZE" not in regions
    assert "queue.push_back({next, state.row, state.depth + 1})" in regions
    assert "component.size()" in regions
    assert "mcu_region_witness.max_slices_per_tile" in regions
    assert "ctx->createRectangularRegion" in regions
    assert "ctx->constrainCellToRegion(cell->name, region_name)" in regions
    assert "prior_slice_regions" in regions
    assert "cell->type != slice_type" in regions
    assert "cell->cluster == ClusterId()" in regions
    assert "for (BelId bel : prior->bels)" in regions
    assert "ctx->getBelType(bel) != slice_type" in regions
    assert "broad heuristic MCU Region yields" in regions
    assert "hard endpoint/site/pin legality remains active" in regions
    assert "X14Y" not in regions
    assert "addsub" not in regions.lower()
    assert "regbank" not in regions.lower()


def test_regions_are_created_after_entry_rows_and_before_native_placement():
    source = UARCH.read_text(encoding="utf-8")
    pack = _between(source, "void pack() override", "// parse \"X14Y8_OMUX02\"")
    assert pack.index("pack_entry_anchor();") < pack.index("constrain_mcu_regions();")
    assert pack.index("constrain_mcu_regions();") < pack.index("pack_condplace(")


def test_region_precedence_does_not_add_a_global_condplace_region_skip():
    source = UARCH.read_text(encoding="utf-8")
    condplace = _between(source, "static void pack_condplace(", "struct AgrvImpl")
    assert "ci->region" not in condplace
