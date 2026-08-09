import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agamemnon.engine.wire_timing import (
    ExactWireTimingError,
    aggregate,
    exact_delay_ns,
    load_safe_exact,
    normalize_resource,
    parse_wire_timing,
    select_routing_delay_ns,
)


ROOT = Path(__file__).resolve().parents[1]


SAMPLE = """
WIRE T0
  TIMING
    FROM : *:RMUX:-;
    FANOUT : 2;
    TABLE BEST
      0.1 0.2;
    END_TABLE
    TABLE WORST
      0.31 0.42;
      0.53 0.44;
    END_TABLE
  END_TIMING
END_WIRE
WIRE T4X
  TIMING
    FROM : *:RMUX:-;
    TABLE WORST
      0.70 0.61;
    END_TABLE
  END_TIMING
  TIMING
    FROM : *:OMUXI:-;
    TABLE WORST
      0.22 0.19;
    END_TABLE
  END_TIMING
END_WIRE
"""


def test_parse_takes_maximum_of_every_worst_row():
    parsed = parse_wire_timing(SAMPLE)
    assert parsed == {"T0": {"RMUX": 0.53},
                      "T4X": {"RMUX": 0.70, "OMUXI": 0.22}}


def test_aggregate_is_conservative_across_inputs(tmp_path):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text(SAMPLE, encoding="utf-8")
    second.write_text(SAMPLE.replace("0.70", "0.91").replace("0.22", "0.18"), encoding="utf-8")
    result = aggregate([first, second])
    assert result["source_max_ns"] == {"OMUXI": 0.22, "RMUX": 0.91}
    assert result["fallback_max_ns"] == 0.91
    assert len(result["inputs"]) == 2
    assert all(len(item["sha256"]) == 64 for item in result["inputs"])


def test_rejects_missing_worst_table():
    with pytest.raises(ValueError, match="no TABLE WORST"):
        parse_wire_timing("WIRE T0\nTABLE BEST\n0.1;\nEND_TABLE\n")


def test_checked_table_and_emitted_device_use_vendor_worst_delays(tmp_path):
    table = json.loads((ROOT / "agamemnon" / "chipdb" / "wire_timing_worst.json").read_text(
        encoding="utf-8"))
    assert len(table["inputs"]) == 7
    assert table["source_max_ns"]["RMUX"] == 1.175
    assert table["fallback_max_ns"] == 2.978
    assert all(len(item["sha256"]) == 64 for item in table["inputs"])

    output = tmp_path / "devdb"
    command = [
        sys.executable, "-I", str(ROOT / "agamemnon" / "engine" / "emit_uarch_db.py"),
        "--arch", str(ROOT / "agamemnon" / "engine" / "arch.py"),
        "--data", str(ROOT / "agamemnon" / "chipdb"), "--out", str(output),
        "--env", "AGAMEMNON_CONDUCTION_GATE=1", "--env", "AGAMEMNON_STRICT_GATE=1",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = list(csv.DictReader((output / "dev_pips.csv").open(encoding="utf-8", newline="")))
    rmux = next(row for row in rows if row["type"] == "ROUTE" and "_RMUX" in row["src"])
    omux = next(row for row in rows if row["type"] == "ROUTE" and "_OMUX" in row["src"])
    assert float(rmux["delay_ns"]) == table["source_max_ns"]["RMUX"]
    assert float(omux["delay_ns"]) == max(table["source_max_ns"][key]
                                                for key in ("OMUXI", "OMUXL", "OMUXR"))


def test_soft_preference_adds_to_the_characterized_base_delay():
    """An untrusted edge must never become cheaper merely because soft gating is enabled."""
    source = (ROOT / "agamemnon" / "engine" / "features" /
              "routing.py").read_text(encoding="utf-8")
    assert "base_ns = wire_timing.select_routing_delay_ns(" in source
    assert "base_ns += _soft_penalty_ns" in source
    assert source.index("base_ns = wire_timing.select_routing_delay_ns(") < source.index(
        "base_ns += _soft_penalty_ns")
    assert "return d_exp" not in source


def test_certified_exact_table_is_hash_pinned_normalized_and_narrow():
    chipdb = ROOT / "agamemnon" / "chipdb"
    worst = json.loads((chipdb / "wire_timing_worst.json").read_text(encoding="utf-8"))
    omux_bound = max(worst["source_max_ns"][name] for name in ("OMUXI", "OMUXL", "OMUXR"))
    exact = load_safe_exact(chipdb, omux_bound)
    manifest = json.loads((chipdb / "wire_timing_exact_safe_manifest.json").read_text(
        encoding="utf-8"))

    assert len(exact) == 542
    assert normalize_resource("OMUX1") == "OMUX01"
    assert exact_delay_ns(exact, "OMUX1", "IMUX0") == 0.401
    assert exact_delay_ns(exact, "RMUX1", "IMUX0") is None
    assert all(src.startswith("OMUX") and dst.startswith("IMUX")
               for src, dst in exact)
    certification = manifest["certification"]
    assert certification["direct_pattern_records"] == 1152
    assert certification["direct_pattern_unique_pairs"] == 576
    assert certification["public_matched_pairs"] == 542
    assert certification["public_strict_release_concrete_route_pips"] == 9375
    assert certification["under_conservative"] is False
    assert len(certification["unmatched_annotated_pairs"]) == 34
    assert manifest["excluded"]["four_node_records"] == 896
    assert "no proven per-pip decomposition" in manifest["excluded"]["reason"]
    assert not any("RMUX" in src or "RMUX" in dst for src, dst in exact)

    coverage = manifest["strict_l48_release_coverage"]
    assert coverage["source_families"] == 20
    assert coverage["total_pips"] == 242901
    assert coverage["ordinary_route_pips"] == 235915
    assert coverage["exact_bound_route_pips"] == 9375
    assert coverage["conservative_fallback_route_pips"] == 226540
    assert coverage["non_route_pips_unchanged"] == 6986
    assert len(coverage["families"]) == 20
    for family in coverage["families"]:
        assert (family["exact_bound_route_pips"] +
                family["conservative_fallback_route_pips"] ==
                family["ordinary_route_pips"])
        assert (family["ordinary_route_pips"] + family["non_route_pips_unchanged"] ==
                family["total_strict_release_pips"])


def test_hash_pinned_exact_json_is_forced_to_lf_on_every_checkout():
    paths = [
        "agamemnon/chipdb/wire_timing_exact_safe.json",
        "agamemnon/chipdb/wire_timing_exact_safe_manifest.json",
    ]
    result = subprocess.run(
        ["git", "check-attr", "eol", "--", *paths],
        cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count(": eol: lf") == 2


def test_exact_absence_and_unsafe_table_fail_to_conservative_behavior(tmp_path):
    with pytest.raises(ExactWireTimingError, match="unavailable or malformed"):
        load_safe_exact(tmp_path, 0.661)

    assert select_routing_delay_ns({}, "OMUX01", "IMUX00", 0.661) == 0.661
    routing = (ROOT / "agamemnon" / "engine" / "features" / "routing.py").read_text(
        encoding="utf-8")
    assert "except wire_timing.ExactWireTimingError" in routing
    assert "conservative fallback active" in routing
    assert 'if _wt_source and DEV.name == "AGRV2KL48"' in routing
    assert "exact local wire timing is L48-scoped" in routing


def test_exact_and_fallback_receive_the_same_clamped_margin():
    exact = {("OMUX01", "IMUX00"): 0.401}
    assert select_routing_delay_ns(exact, "OMUX1", "IMUX0", 0.661, 1.5) == pytest.approx(0.6015)
    assert select_routing_delay_ns(exact, "OMUX1", "IMUX2", 0.661, 1.5) == pytest.approx(0.9915)
    assert select_routing_delay_ns(exact, "OMUX1", "IMUX0", 0.661, 0.5) == pytest.approx(0.401)


def test_emitted_strict_release_devdb_binds_only_certified_route_pips(tmp_path):
    chipdb = ROOT / "agamemnon" / "chipdb"
    worst = json.loads((chipdb / "wire_timing_worst.json").read_text(encoding="utf-8"))
    omux_bound = max(worst["source_max_ns"][name] for name in ("OMUXI", "OMUXL", "OMUXR"))
    exact = load_safe_exact(chipdb, omux_bound)
    output = tmp_path / "devdb"
    command = [
        sys.executable, "-I", str(ROOT / "agamemnon" / "engine" / "emit_uarch_db.py"),
        "--arch", str(ROOT / "agamemnon" / "engine" / "arch.py"),
        "--data", str(chipdb), "--out", str(output),
        "--env", "AGAMEMNON_CONDUCTION_GATE=1", "--env", "AGAMEMNON_STRICT_GATE=1",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = list(csv.DictReader((output / "dev_pips.csv").open(encoding="utf-8", newline="")))

    bound = []
    for row in rows:
        source = row["src"].rsplit("_", 1)[-1]
        destination = row["dst"].rsplit("_", 1)[-1]
        if row["type"] == "ROUTE" and exact_delay_ns(exact, source, destination) is not None:
            bound.append(row)
    assert len(bound) == 9375
    assert {float(row["delay_ns"]) for row in bound} == {0.401}

    feedback = [row for row in rows if row["type"] == "DIRECT_D_FB"]
    assert len(feedback) == 2112
    assert {float(row["delay_ns"]) for row in feedback} == {0.01}
