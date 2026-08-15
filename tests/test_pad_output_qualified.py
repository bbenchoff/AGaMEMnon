"""The qualified pad-output compositions, and the tables they depend on.

Exactly five top-edge ring pads are qualified -- PIN_18, PIN_16, PIN_15,
PIN_14 and PIN_13 -- and each has
ONE silicon-proven composition: one approach into the pad-feed source, one
source, one pad-tile RMUX, one IOMUX terminal. The architecture admits only
those for the pads listed, because leaving it open is not harmless: the first
production build of the pair reached PIN_16 through RMUX24 where only RMUX8 is
proven, which config-accepts, routes clean, and does not drive.

These tests guard the data, not the silicon. The silicon record is in
qualification/io_evidence.jsonl.
"""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return [row for row in csv.DictReader(
            line for line in stream if not line.lstrip().startswith("#"))]


def test_only_silicon_witnessed_top_edge_pads_are_qualified():
    """Five pads, and the set may only grow with a silicon observation.

    PIN_15 (2026-08-15) is the third, and it arrived with its own two-way
    discrimination: the (19,11)-source build of the same design config-accepted
    with 0 unmapped and read a hard 0 Hz, while the (19,9)-source build toggled.
    Same feeder, same IOMUX slot bits -- only the pad-feed source and its
    codeword differed.
    """
    table = rows("pad_output_qualified_L48.csv")
    assert {row["pin"] for row in table} == {"PIN_18", "PIN_16", "PIN_15", "PIN_14", "PIN_13"}, (
        "the qualified top-edge surface is five pads; adding one needs its own "
        "silicon observation, not just a table row"
    )
    for row in table:
        assert int(row["pad_y"]) == 13
        # Slot z is NOT always 0: PIN_15 is z1, which is what made it the useful
        # third candidate -- a second slot on an already-qualified pad tile.
        assert 0 <= int(row["z"]) <= 3
        assert row["evidence"].startswith("silicon-")


def test_adjacent_slots_of_pad_tile_19_13_are_both_qualified():
    """PIN_16 (z0) and PIN_15 (z1) share a pad tile AND a config tile (18,13).

    They were measured driving together from one image, which is the composition
    most likely to interfere: their CFG_IOMUX slot bits land in neighbouring
    blocks of the same banks, so an approximate park/unpark rule would show here.
    """
    table = {row["pin"]: row for row in rows("pad_output_qualified_L48.csv")}
    pin16, pin15 = table["PIN_16"], table["PIN_15"]
    assert (int(pin16["pad_x"]), int(pin16["pad_y"])) == \
           (int(pin15["pad_x"]), int(pin15["pad_y"])) == (19, 13)
    assert {int(pin16["z"]), int(pin15["z"])} == {0, 1}
    # Different slots must not share a feeder: one RMUX drives one IOMUX index.
    assert int(pin16["feeder_rmux"]) != int(pin15["feeder_rmux"])


def test_pin14_names_its_measured_vendor_output_presentation():
    row = {row["pin"]: row for row in rows("pad_output_qualified_L48.csv")}["PIN_14"]
    assert (int(row["pad_x"]), int(row["pad_y"]), int(row["z"])) == (19, 13, 2)
    assert (row["src_res"], int(row["src_x"]), int(row["src_y"]),
            int(row["feeder_rmux"])) == ("RMUX19", 19, 9, 24)
    assert (row["approach_res"], int(row["approach_x"]), int(row["approach_y"])) \
        == ("RMUX74", 15, 9)
    assert row["vendor_out_slice"] == "14,9,15"


def test_pin13_reuses_the_pin16_feed_but_selects_slot_three():
    table = {row["pin"]: row for row in rows("pad_output_qualified_L48.csv")}
    pin13, pin16 = table["PIN_13"], table["PIN_16"]
    assert (int(pin13["pad_x"]), int(pin13["pad_y"]), int(pin13["z"])) == (19, 13, 3)
    for field in ("feeder_rmux", "src_res", "src_x", "src_y",
                  "approach_res", "approach_x", "approach_y"):
        assert pin13[field] == pin16[field]
    assert pin13["vendor_out_slice"] == "14,9,10"


def test_each_qualified_pad_names_one_complete_composition():
    for row in rows("pad_output_qualified_L48.csv"):
        for column in ("feeder_rmux", "src_res", "src_x", "src_y",
                       "approach_res", "approach_x", "approach_y", "pico_gp"):
            assert row[column], "%s has no %s" % (row["pin"], column)
        # The pad-feed source sits on the y=9 row of the pad's own column, and
        # the approach comes from elsewhere -- that shape is what both measured
        # routes have in common.
        assert int(row["src_y"]) == 9
        assert (int(row["approach_x"]), int(row["approach_y"])) != \
            (int(row["src_x"]), int(row["src_y"]))


def test_the_measured_compositions_are_the_ones_that_drove():
    table = {row["pin"]: row for row in rows("pad_output_qualified_L48.csv")}
    pin18, pin16 = table["PIN_18"], table["PIN_16"]
    assert (pin18["src_res"], int(pin18["src_x"]), int(pin18["src_y"]),
            int(pin18["feeder_rmux"])) == ("RMUX69", 18, 9, 28)
    assert (pin18["approach_res"], int(pin18["approach_x"]), int(pin18["approach_y"])) \
        == ("RMUX15", 14, 9)
    assert (pin16["src_res"], int(pin16["src_x"]), int(pin16["src_y"]),
            int(pin16["feeder_rmux"])) == ("RMUX55", 19, 9, 8)
    assert (pin16["approach_res"], int(pin16["approach_x"]), int(pin16["approach_y"])) \
        == ("RMUX61", 15, 9)


def test_the_hop_table_is_keyed_on_the_source():
    """A codeword harvested from one source must not be applied to another."""
    table = rows("iomux_hop_vendor.csv")
    assert any(row.get("src_res") for row in table), \
        "iomux_hop_vendor.csv lost its source columns"
    keyed = [row for row in table if row.get("src_res")]
    seen = set()
    for row in keyed:
        key = (row["pad_x"], row["pad_y"], row["z"], row["feeder_R"],
               row["src_res"], row["src_x"], row["src_y"])
        assert key not in seen, "duplicate source-keyed hop row: %r" % (key,)
        seen.add(key)


def test_padfeed_rows_have_no_conflicting_duplicate_keys():
    """One (pad, slot, source, feeder) may not carry two different codewords."""
    seen = {}
    for row in rows("padfeed_L48_top.csv"):
        key = (row["padtile_x"], row["padtile_y"], row["iomux_z"],
               row["src_res"], row["src_x"], row["src_y"], row["padfeed_rmux"])
        codeword = (row["codeword_sels"], row["codeword_bytes"], row["codeword_masks"])
        if key in seen:
            assert seen[key] == codeword, (
                "padfeed_L48_top.csv has conflicting codewords for %r: %r vs %r"
                % (key, seen[key], codeword))
        seen[key] = codeword


def test_the_qualified_pins_resolve_to_the_qualified_pad_tiles():
    """The L48 bond map must agree with the composition table, or --pcf binds
    the port to a pad whose composition is not the qualified one."""
    bond = {row["pin"]: row for row in rows("bondmap_L48.csv")}
    for row in rows("pad_output_qualified_L48.csv"):
        entry = bond[row["pin"]]
        assert (int(entry["x"]), int(entry["y"]), int(entry["z"])) == (
            int(row["pad_x"]), int(row["pad_y"]), int(row["z"])), (
            "%s bonds to (%s,%s,%s) but the qualified composition names (%s,%s,%s)"
            % (row["pin"], entry["x"], entry["y"], entry["z"],
               row["pad_x"], row["pad_y"], row["z"]))
        assert entry["edge"] == "TOP"
