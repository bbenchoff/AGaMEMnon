import csv
import json
from pathlib import Path

from agamemnon import cli


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_all_request_qualifiers_have_exact_shared_routes_and_types():
    paths = rows("mcu_slave_ahb_request_control_paths.csv")
    cfg = rows("mcu_slave_ahb_request_control_pip_cfg.csv")
    assert len(paths) == 44
    assert len(cfg) == 13
    signals = {row["signal"] for row in paths}
    assert signals == {
        "slave_ahb_hsel", "slave_ahb_hready",
        "slave_ahb_htrans[0]", "slave_ahb_htrans[1]",
        "slave_ahb_hsize[0]", "slave_ahb_hsize[1]", "slave_ahb_hsize[2]",
        "slave_ahb_hburst[0]", "slave_ahb_hburst[1]", "slave_ahb_hburst[2]",
        "slave_ahb_hwrite",
    }
    arch = (ROOT / "agamemnon" / "engine" / "features" / "mcu_ahb.py").read_text(
        encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(
        encoding="utf-8")
    names = [
        "HSEL", "HREADY", "HTRANS0", "HTRANS1", "HSIZE0", "HSIZE1",
        "HSIZE2", "HBURST0", "HBURST1", "HBURST2", "HWRITE",
    ]
    for bit, suffix in enumerate(names, 165):
        name = f"MCU_SLAVE_AHB_{suffix}"
        assert f'{bit}: "{name}"' in arch
        assert f"module {name}" in prims


def test_request_qualifier_smoke_and_evidence_are_narrow():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_request_controls_shared_low_route_smoke.v").read_text(
                 encoding="utf-8")
    assert 'BEL="X14Y12_SLICE0"' in smoke
    assert "INIT(16'h0000)" in smoke
    assert smoke.count(".DOUT(request_low)") == 11
    records = [json.loads(line) for line in (ROOT / "qualification" /
               "mcu_slave_ahb_request_control_route_evidence.jsonl").read_text(
                   encoding="utf-8").splitlines()]
    record = records[0]
    assert record["build"] == "pass"
    assert record["hardware"] == "not-run"
    assert record["source_scope"] == "one-shared-safe-low-source"
    assert record["selector_checks"] == 119
    assert record["exact_fields"] == 13
    assert record["routed_pips"] == 13
    assert record["unmapped_pips"] == 0

    independent = next(row for row in records if row.get("trial_id") ==
                       "fabric-ahb-independent-request-controls-desk-20260826")
    assert independent["build"] == "pass"
    assert independent["hardware"] == "not-run"
    assert independent["source_count"] == 11
    assert independent["route_campaign_builds"] == 13
    assert independent["selector_checks"] == 143
    assert independent["selector_agreements"] == 143
    assert independent["selector_disagreements"] == 0
    assert independent["exact_path_edges"] == 54
    assert independent["exact_fields"] == 39
    assert independent["unmapped_pips"] == 0
    assert independent["predicted_pips"] == 0


def test_request_qualifiers_fail_closed_outside_exact_shared_safe_low():
    arch = (ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" /
            "agrv2k.cc").read_text(encoding="utf-8")
    guard = arch.index("static void guard_fabric_ahb_request_controls")
    pack = arch.index("static void pack_mcu_edge")
    call = arch.index("guard_fabric_ahb_request_controls(ctx);", pack)
    assert guard < pack < call
    assert 'requested->second.as_string() == "X14Y12_SLICE0"' in arch
    assert 'int_or_default(driver->params, ctx->id("INIT"), -1) != 0' in arch
    assert 'int_or_default(driver->params, ctx->id("FF_USED"), 0) != 0' in arch
    assert "shared != nullptr && shared != net" in arch
    assert "mcu-ahb-request-control-independent-ff-oracle" in arch
    assert "request_controls.size() == 11" in arch
    assert "independent_nets.size() == 11" in arch
    assert "independent_drivers.size() == 11" in arch
    assert "is_exact_fabric_ahb_independent_source_at(ctx, ci, bel)" in arch
    assert '"safe-low oracle nor the exact eleven-source independent-FF oracle; dynamic "' in arch
    assert '"request topology is unqualified and fails closed' in arch
    assert "mcu-ahb-request-control-shared-source-oracle" in arch


def test_request_qualifier_independent_ff_oracle_is_exact():
    arch = (ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" /
            "agrv2k.cc").read_text(encoding="utf-8")
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_request_controls_independent_ff_route_smoke.v").read_text(
                 encoding="utf-8")
    expected = {
        "HSEL": "X14Y7_SLICE14",
        "HREADY": "X14Y10_SLICE9",
        "HTRANS0": "X14Y7_SLICE11",
        "HTRANS1": "X16Y7_SLICE12",
        "HSIZE0": "X16Y10_SLICE14",
        "HSIZE1": "X17Y8_SLICE0",
        "HSIZE2": "X14Y10_SLICE10",
        "HBURST0": "X14Y7_SLICE12",
        "HBURST1": "X14Y10_SLICE14",
        "HBURST2": "X17Y8_SLICE2",
        "HWRITE": "X17Y8_SLICE12",
    }
    for control, bel in expected.items():
        assert f'MCU_SLAVE_AHB_{control}' in smoke
        assert f'return "{bel}";' in arch
        assert f'BEL="{bel}"' in smoke
    assert smoke.count(".FF_USED(1)") == 11
    assert smoke.count(".Q(control[") == 11

    paths = rows("mcu_slave_ahb_request_control_independent_paths.csv")
    cfg = rows("mcu_slave_ahb_request_control_independent_pip_cfg.csv")
    assert len(paths) == 54
    assert len(cfg) == 39
    assert {row["signal"] for row in paths} == {
        "slave_ahb_hsel", "slave_ahb_hready",
        "slave_ahb_htrans[0]", "slave_ahb_htrans[1]",
        "slave_ahb_hsize[0]", "slave_ahb_hsize[1]", "slave_ahb_hsize[2]",
        "slave_ahb_hburst[0]", "slave_ahb_hburst[1]", "slave_ahb_hburst[2]",
        "slave_ahb_hwrite",
    }
    configurable = {
        (row["src_wire"], row["dst_wire"])
        for row in paths
        if "_SinkMUXPseudo" not in row["dst_wire"]
        and "_OMUX" not in row["dst_wire"]
    }
    assert configurable == {(row["src_wire"], row["dst_wire"]) for row in cfg}
    assert sum("_OMUX" in row["dst_wire"] for row in paths) == 4
    assert {row["evidence"] for row in paths + cfg} == {
        "retained-independent-ff-request-controls"
    }
    assert "void lock_fabric_ahb_independent_controls()" in arch
    assert "mcu_slave_ahb_request_control_independent_paths.csv" in arch
    assert "mcu_slave_ahb_request_control_independent_pip_cfg.csv" in (
        ROOT / "agamemnon" / "engine" / "features" / "mcu_ahb.py"
    ).read_text(encoding="utf-8")
    assert "locked_nets != 11" in arch
    assert "lock_fabric_ahb_independent_controls();" in arch
    cli_source = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    assert '"mcu_slave_ahb_request_control_independent_paths.csv"' in cli_source


def test_request_control_policy_refusal_is_not_retried_as_routing():
    refusal = (
        "ERROR: agrv2k: fabric AHB master request controls match neither the "
        "exact shared safe-low oracle nor the exact eleven-source independent-FF "
        "oracle; dynamic request topology is unqualified and fails closed\n"
        "ERROR: Packing design failed.\n"
    )
    assert cli._nonretryable_uarch_failure(refusal)
    assert not cli._nonretryable_uarch_failure(
        "ERROR: Failed to route arc 1.0 of net 'ordinary_net'\n")
