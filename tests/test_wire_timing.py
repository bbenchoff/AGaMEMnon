import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agamemnon.engine.wire_timing import aggregate, parse_wire_timing


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
        sys.executable, str(ROOT / "agamemnon" / "engine" / "emit_uarch_db.py"),
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
    source = (ROOT / "agamemnon" / "engine" / "arch.py").read_text(encoding="utf-8")
    assert 'base_ns = _wire_delay_ns(r["src_res"]) if _wt_source else 0.1' in source
    assert "base_ns += _soft_penalty_ns" in source
    assert "return d_exp" not in source
