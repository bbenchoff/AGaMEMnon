import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agamemnon.engine.wire_timing import (
    MEASURED_FAMILIES,
    ExactWireTimingError,
    MeasuredWireTimingError,
    aggregate,
    exact_delay_ns,
    load_measured_families,
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

    measured = json.loads((ROOT / "agamemnon" / "chipdb" / "wire_timing_measured.json").read_text(
        encoding="utf-8"))
    assert measured["families_ns"]["RMUX"] == 0.336

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
    # J2 (AG32-Docs docs/TASK_QUEUE.md Queue J): RMUX is one of the three
    # families (RMUX/ClkMUX/BufMUX) with a fitted, below-worst-case measured
    # delay, so the emitted device now charges the measured value for RMUX,
    # not the worst-case table value asserted above. OMUX has no measured
    # entry (collinear with IMUX -- see wire_timing_measured.json's
    # provenance -- so the split is not identifiable) and still uses
    # worst-case exactly as before.
    assert float(rmux["delay_ns"]) == measured["families_ns"]["RMUX"]
    assert float(rmux["delay_ns"]) < table["source_max_ns"]["RMUX"]
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


# ---------------------------------------------------------------------------
# J2 (AG32-Docs docs/TASK_QUEUE.md Queue J): measured per-family delays for
# RMUX/ClkMUX/BufMUX, fitted against af.exe's own STA and landed as a
# separate table consulted before wire_timing_worst.json -- see
# agamemnon/chipdb/wire_timing_measured.json's "provenance" block and
# agamemnon.engine.gate_claims CLAIMS["fitted-wire-timing-rmux-clkmux-bufmux-2026"].
# ---------------------------------------------------------------------------


def test_measured_table_is_scoped_to_exactly_the_evidenced_families():
    assert MEASURED_FAMILIES == ("RMUX", "ClkMUX", "BufMUX")


def test_measured_table_matches_the_fitted_evidence_and_beats_worst_case():
    chipdb = ROOT / "agamemnon" / "chipdb"
    worst = json.loads((chipdb / "wire_timing_worst.json").read_text(encoding="utf-8"))
    measured_raw = json.loads((chipdb / "wire_timing_measured.json").read_text(encoding="utf-8"))
    assert measured_raw["schema"] == 1
    assert measured_raw["units"] == "nanoseconds"
    assert measured_raw["families_ns"] == {"RMUX": 0.336, "ClkMUX": 0.133, "BufMUX": 0.534}

    measured = load_measured_families(chipdb, worst["source_max_ns"])
    assert measured == {"RMUX": 0.336, "ClkMUX": 0.133, "BufMUX": 0.534}
    for family, value in measured.items():
        assert value < worst["source_max_ns"][family]


def test_measured_table_absence_and_bad_schema_fail_to_conservative_behavior(tmp_path):
    with pytest.raises(MeasuredWireTimingError, match="unavailable or malformed"):
        load_measured_families(tmp_path, {"RMUX": 1.175})

    bad_schema = tmp_path / "wire_timing_measured.json"
    bad_schema.write_text(json.dumps({"schema": 2, "units": "nanoseconds",
                                       "families_ns": {"RMUX": 0.336}}), encoding="utf-8")
    with pytest.raises(MeasuredWireTimingError, match="unsupported measured wire timing schema"):
        load_measured_families(tmp_path, {"RMUX": 1.175})

    bad_units = tmp_path / "wire_timing_measured.json"
    bad_units.write_text(json.dumps({"schema": 1, "units": "picoseconds",
                                      "families_ns": {"RMUX": 336}}), encoding="utf-8")
    with pytest.raises(MeasuredWireTimingError, match="not nanoseconds"):
        load_measured_families(tmp_path, {"RMUX": 1.175})


def test_measured_table_refuses_a_non_improving_or_invalid_value(tmp_path):
    path = tmp_path / "wire_timing_measured.json"

    # Not below the worst-case charge for the same family: refused, not
    # silently accepted as if it were an improvement.
    path.write_text(json.dumps({"schema": 1, "units": "nanoseconds",
                                 "families_ns": {"RMUX": 1.175}}), encoding="utf-8")
    with pytest.raises(MeasuredWireTimingError, match="not below its worst-case"):
        load_measured_families(tmp_path, {"RMUX": 1.175})

    # Non-positive or non-finite: refused outright.
    for bad_value in (0.0, -0.336, float("inf"), float("nan")):
        path.write_text(json.dumps({"schema": 1, "units": "nanoseconds",
                                     "families_ns": {"RMUX": bad_value}}), encoding="utf-8")
        with pytest.raises(MeasuredWireTimingError, match="not a positive finite number"):
            load_measured_families(tmp_path, {"RMUX": 1.175})


def test_measured_table_ignores_families_outside_the_evidenced_allowlist(tmp_path):
    """A data-only edit cannot widen which families this table can override."""
    path = tmp_path / "wire_timing_measured.json"
    path.write_text(json.dumps({
        "schema": 1, "units": "nanoseconds",
        "families_ns": {"RMUX": 0.336, "OMUX": 0.1, "SomeUnvettedFamily": 0.01},
    }), encoding="utf-8")
    measured = load_measured_families(tmp_path, {"RMUX": 1.175, "OMUX": 0.661})
    assert measured == {"RMUX": 0.336}


def test_wire_delay_ns_prefers_measured_over_worst_case_for_landed_families():
    routing = (ROOT / "agamemnon" / "engine" / "features" / "routing.py").read_text(
        encoding="utf-8")
    assert "CLAIM: fitted-wire-timing-rmux-clkmux-bufmux-2026" in routing
    assert "if family in _wt_measured:" in routing
    assert routing.index("if family in _wt_measured:") < routing.index(
        "if family in _wt_source:")
