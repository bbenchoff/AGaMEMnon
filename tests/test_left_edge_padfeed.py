import csv
from pathlib import Path

from agamemnon.engine import routing_selectors


ROOT = Path(__file__).parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def _rows(name):
    with (CHIPDB / name).open(newline="") as stream:
        return list(csv.DictReader(stream))


def test_l48_left_bank_uses_vendor_observed_feeders():
    rows = _rows("padfeed_L48_left.csv")
    observed = {
        int(row["iomux_z"]): (
            int(row["padfeed_rmux"]),
            int(row["src_x"]),
            int(row["src_y"]),
            int(row["src_res"].removeprefix("RMUX")),
            tuple(int(value) for value in row["codeword_sels"].split(",") if value),
        )
        for row in rows
    }
    assert observed == {
        0: (30, 4, 4, 20, ()),
        1: (6, 4, 4, 79, ()),
        2: (18, 4, 4, 13, ()),
        3: (0, 4, 4, 26, (3, 5)),
    }


def test_l48_left_bank_corridors_match_silicon_positive_pintest2_sources():
    rows = _rows("padout_L48_left_corridors.csv")
    endpoints = {}
    for row in rows:
        z = int(row["iomux_z"])
        endpoints.setdefault(z, [row["src_wire"], row["dst_wire"]])[1] = row["dst_wire"]
    assert endpoints == {
        0: ["X14Y11_OMUX12", "X0Y4_IOMUX00"],
        1: ["X14Y11_OMUX15", "X0Y4_IOMUX01"],
        2: ["X14Y11_OMUX20", "X0Y4_IOMUX02"],
        3: ["X14Y11_OMUX23", "X0Y4_IOMUX03"],
    }


def test_general_pad_inventory_matches_left_bank_feeders():
    pads = {
        int(row["iomux"]): int(row["rmux"])
        for row in _rows("io_pads.csv")
        if (int(row["x"]), int(row["y"])) == (0, 4) and int(row["iomux"]) < 4
    }
    exact = {
        int(row["iomux_z"]): int(row["padfeed_rmux"])
        for row in _rows("padfeed_L48_left.csv")
    }
    assert pads == exact


def test_left_outputs_keep_silicon_isolated_pad_tile_companion_pairs():
    rows = _rows("padfeed_L48_left.csv")
    pin25 = next(row for row in rows if int(row["iomux_z"]) == 0)
    assert pin25["companion_cfg"] == "CFG_RMUX3"
    assert pin25["companion_sels"] == "45,46"
    pin26 = next(row for row in rows if int(row["iomux_z"]) == 1)
    assert pin26["companion_cfg"] == "CFG_RMUX0"
    assert pin26["companion_sels"] == "45,47"
    pin27 = next(row for row in rows if int(row["iomux_z"]) == 2)
    assert pin27["companion_cfg"] == "CFG_RMUX2"
    assert pin27["companion_sels"] == "17,18"


def test_pin25_rrg_encoding_uses_the_canonical_special_padfeed_owner():
    padfeed = next(
        row for row in _rows("padfeed_L48_left.csv")
        if int(row["iomux_z"]) == 0
    )
    edge = next(
        row for row in _rows("rrg_edges_full.csv")
        if (
            row["src_tile"], int(row["src_x"]), int(row["src_y"]), row["src_res"],
            row["dst_tile"], int(row["dst_x"]), int(row["dst_y"]), row["dst_res"],
        ) == (
            "LogicTILE", 4, 4, "RMUX20",
            "IOTILE", 0, 4, "RMUX30",
        )
    )

    assert edge["cfg"] == "%s[%s]" % (
        padfeed["companion_cfg"], padfeed["companion_sels"]
    )

    # This cross-owned package edge is emitted by the physical-I/O padfeed
    # path.  A generic clean-edge row would derive CFG_RMUX5 from RMUX30 and
    # silently lose the reviewed CFG_RMUX3 owner, so its absence is required.
    clean_edges = routing_selectors.load_clean_edges(str(CHIPDB))
    assert (0, 4, "RMUX", 30, "RMUX", 4, 4, 20) not in clean_edges
