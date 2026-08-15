import csv
import json
from pathlib import Path

from agamemnon.engine.verify_netlist import hrdata_bit_for_bel


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def test_hrdata_lane_table_is_complete_unique_and_collision_free():
    rows = list(csv.DictReader((CHIPDB / "mcu_hrdata_lanes.csv").open()))
    logical = [int(r["logical_bit"]) for r in rows]
    bels = [int(r["bel_bit"]) for r in rows]

    assert logical == list(range(32))
    assert len(bels) == len(set(bels)) == 32
    assert not ({20, 21, 22} & set(bels))
    assert [r["sink_res"] for r in rows] == [f"SinkMUXPseudo{k:02d}" for k in range(2, 34)]
    assert all(len(r["selectors"].split(";")) == 2 for r in rows)


def test_hrdata_lane_endpoints_exist_in_the_physical_wire_table():
    rows = list(csv.DictReader((CHIPDB / "mcu_hrdata_lanes.csv").open()))
    wires = {(int(r["x"]), int(r["y"]), r["resource"])
             for r in csv.DictReader((CHIPDB / "wires.csv").open())}

    for r in rows:
        assert (int(r["src_x"]), int(r["src_y"]), r["src_res"]) in wires
        assert (int(r["edge_x"]), int(r["edge_y"]), r["edge_res"]) in wires
        assert (0, 5, r["sink_res"]) in wires


def test_verify_netlist_translates_every_internal_bel_to_ahb_bit():
    rows = list(csv.DictReader((CHIPDB / "mcu_hrdata_lanes.csv").open()))
    for r in rows:
        bel = f"X10Y5_MCU_DOUT{r['bel_bit']}"
        assert hrdata_bit_for_bel(bel) == int(r["logical_bit"])

    assert hrdata_bit_for_bel("X10Y5_MCU_DOUT20") is None
    assert hrdata_bit_for_bel("X10Y5_MCU_DOUT99") is None


def test_all_hard_bus_lane_tables_are_complete():
    hwdata = list(csv.DictReader((CHIPDB / "mcu_hwdata_lanes.csv").open()))
    haddr = list(csv.DictReader((CHIPDB / "mcu_haddr_lanes.csv").open()))
    addr_exit = list(csv.DictReader((CHIPDB / "mcu_hrdata_addr_lanes.csv").open()))

    assert [int(row["logical_bit"]) for row in hwdata] == list(range(32))
    assert [int(row["logical_bit"]) for row in haddr] == list(range(2, 28))
    assert [int(row["logical_bit"]) for row in addr_exit] == list(range(32))
    assert all(len(row["selectors"].split(";")) == 2 for row in addr_exit)


def test_exact_ahb_corridor_fields_are_well_formed_and_nonconflicting():
    tables = []
    for name, expected in (("mcu_ahb32_pip_cfg.csv", 111),
                           ("mcu_ahb32_addr_pip_cfg.csv", 65)):
        rows = list(csv.DictReader((CHIPDB / name).open()))
        assert len(rows) == expected
        tables.append(rows)
        for row in rows:
            clear = [int(value) for value in row["clear_selectors"].split(";") if value]
            selected = [int(value) for value in row["set_selectors"].split(";") if value]
            if row["cell_table"] == "fabric":
                assert len(clear) in (10, 12)
                assert len(selected) == 2
                assert set(selected) <= set(clear)
            else:
                assert row["cell_table"] == "mcu"
                assert clear == [0]
                assert selected in ([], [0])

    observed = {}
    for row in tables[0] + tables[1]:
        key = row["src_wire"], row["dst_wire"]
        value = (row["cell_table"], row["cfg_group"], row["clear_selectors"],
                 row["set_selectors"])
        assert key not in observed or observed[key] == value
        observed[key] = value


def test_protocol_valid_hardware_evidence_covers_read_and_every_write_lane():
    read = [json.loads(line) for line in
            (ROOT / "qualification" / "mcu_ahb32_read_evidence.jsonl").read_text().splitlines()]
    writes = [json.loads(line) for line in
              (ROOT / "qualification" / "mcu_ahb32_write_evidence.jsonl").read_text().splitlines()]

    assert len(read) == 1 and read[0]["build"] == read[0]["hardware"] == "pass"
    assert "exact=64/64" in read[0]["hardware_output"]
    groups = [row for row in writes if "group" in row]
    interpretations = [row for row in writes if "trial_id" in row]
    assert [row["group"] for row in groups] == list(range(8))
    assert [lane for row in groups for lane in row["lanes"]] == list(range(32))
    assert all(row["build"] == row["hardware"] == "pass" for row in groups)
    assert all("exact=64/64" in row["hardware_output"] for row in groups)
    # Records in this ledger that are NOT per-group qualification rows are pinned
    # by name, so a new one cannot quietly look like lane coverage. The 16-lane
    # capture trials are explicitly not 32-lane coverage. The final exact
    # checkpoint proves one simultaneous 16-lane posted-capture composition,
    # while the per-group assertions above remain the 32-lane coverage claim.
    assert {row["trial_id"] for row in interpretations} == {
        "2026-08-04-ahb-write-qualifier-x14y12-slice0-footprint",
        "mcu-ahb-16-lane-shared-capture-14of16-20260815",
        "boundary-selector-is-source-dependent-20260815",
        "mcu-ahb-16-lane-shared-capture-15of16-codeword-fix-20260815",
        "mcu-ahb-16-lane-posted-capture-exact-20260815",
    }

    capture16 = next(row for row in interpretations
                     if row["trial_id"] ==
                     "mcu-ahb-16-lane-posted-capture-exact-20260815")
    assert capture16["result"] == "pass"
    assert "every lane 0..15" in capture16["observed"]
    assert "not a 16-bit register bank" in capture16["scope"]
    assert capture16["routed"] == \
        "qualification/mcu_ahb_posted_capture16_routed.json"


def test_posted_capture16_silicon_route_is_in_the_conducting_graph():
    rows = list(csv.DictReader((CHIPDB / "master_conduction.csv").open()))
    observed = {
        (row["src_res"], int(row["src_x"]), int(row["src_y"]),
         row["dst_res"], int(row["dst_x"]), int(row["dst_y"]), row["source"])
        for row in rows
    }
    expected = {
        ("RMUX21", 14, 5, "RMUX92", 14, 4, "posted-capture16-silicon"),
        ("RMUX56", 17, 12, "RMUX26", 14, 12, "posted-capture16-silicon"),
        ("RMUX87", 19, 11, "RMUX69", 19, 10, "posted-capture16-silicon"),
        ("OMUX23", 14, 11, "OMUX21", 14, 11, "posted-capture16-silicon"),
    }
    assert expected <= observed


def test_posted_capture16_lane9_records_its_alternate_q_presentation():
    checkpoint = json.loads(
        (ROOT / "qualification" / "mcu_ahb_posted_capture16_routed.json").read_text()
    )["modules"]["top"]
    route = checkpoint["netnames"]["cap[9]"]["attributes"]["ROUTING"]
    # The retained image presents registered Q on both the ordinary +2 OMUX
    # and the +0 mesh OMUX.  The manually relocated checkpoint originally
    # omitted this internal bridge, so a fresh router could not connect the
    # placed cell to the otherwise complete lane-9 route.
    assert "X14Y11_OMUX23.X14Y11_OMUX21" in route

    arch = (ROOT / "agamemnon" / "engine" / "features" / "mcu_ahb.py").read_text()
    assert "(14, 11, 7)" in arch

    clock_route = checkpoint["netnames"]["hclk"]["attributes"]["ROUTING"]
    assert "GCLK0.X14Y11_ClkMUX07" in clock_route
    assert "GCLK0.X15Y12_ClkMUX04" not in clock_route
