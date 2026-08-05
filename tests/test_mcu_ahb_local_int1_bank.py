import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _iverilog():
    found = shutil.which("iverilog")
    oss = os.environ.get("AGAMEMNON_OSS")
    if not found and oss:
        for name in ("iverilog", "iverilog.exe"):
            candidate = Path(oss) / "bin" / name
            if candidate.is_file():
                return str(candidate)
    return found


def test_local_int1_command_bank_structure_and_evidence():
    source = (ROOT / "qualification" /
              "mcu_ahb_local_int1_bank.v").read_text(encoding="utf-8")
    assert 'BEL = "X14Y12_SLICE0"' in source
    assert 'BEL = "X14Y12_SLICE1"' in source
    assert 'BEL = "X14Y11_SLICE7"' in source
    assert 'BEL = "X15Y11_SLICE4"' in source
    assert 'BEL = "X14Y8_SLICE0"' in source
    assert "INIT(16'h00D8)" in source
    assert "INIT(16'h00DC)" in source
    assert "assign hrdata[0] = 1'b0" in source

    records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_register_bank_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(row for row in records if row["trial_id"] ==
                  "2026-08-05-l48-ahb-local-int1-command-bank-pure-open")
    assert record["verdict"] == "pass"
    assert record["bitstream_sha256"] == (
        "7dbee13f53451e8d047f5c841de4bf2e9bb01eb10dc912a3ae899f2978ee1732"
    )
    assert record["source_wire"] == "X14Y8_OMUX02"
    assert record["observed_wire"] == "X0Y5_SinkMUXPseudo216"
    assert len(record["path_pips"]) == 8
    assert "no state-read claim" in record["notes"]

    cause18 = next(row for row in records if row["trial_id"] ==
                   "2026-08-05-l48-ahb-local-int2-command-bank-pure-open")
    assert cause18["verdict"] == "pass"
    assert cause18["bitstream_sha256"] == (
        "8b602d56c70475a845a0601cf9e5c4658187a932a82fe2ba4defde90a556ab51"
    )
    assert cause18["source_wire"] == "X10Y4_OMUX02"
    assert cause18["observed_wire"] == "X0Y5_SinkMUXPseudo217"
    assert len(cause18["path_pips"]) == 7
    wrapper = (ROOT / "qualification" /
               "mcu_ahb_local_int2_bank.v").read_text(encoding="utf-8")
    assert "`define AGAMEMNON_LOCAL_INT2" in wrapper
    assert 'BEL = "X10Y4_SLICE0"' in source

    cause19 = next(row for row in records if row["trial_id"] ==
                   "2026-08-05-l48-ahb-local-int3-command-bank-pure-open")
    assert cause19["verdict"] == "pass"
    assert cause19["bitstream_sha256"] == (
        "0f33d528d1f314bafc9cede6bbc3ed7347f6bf175848ff10466dd1320d090a07"
    )
    assert cause19["source_wire"] == "X14Y4_OMUX02"
    assert cause19["observed_wire"] == "X0Y5_SinkMUXPseudo218"
    assert len(cause19["path_pips"]) == 8
    wrapper = (ROOT / "qualification" /
               "mcu_ahb_local_int3_bank.v").read_text(encoding="utf-8")
    assert "`define AGAMEMNON_LOCAL_INT3" in wrapper
    assert 'BEL = "X14Y4_SLICE0"' in source

    negative_records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_local_int1_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["trial_id"] for row in negative_records} == {
        "2026-08-05-l48-local-int1-mask-commit-class-negative",
        "2026-08-05-l48-local-int1-forced-mask-discriminator",
        "2026-08-05-l48-local-int1-subset-readback-negative",
        "2026-08-05-l48-local-int1-direct-read-coupled-negative",
    }
    assert all(row["dead_candidate"] is None for row in negative_records)
    assert sum(row["verdict"] == "pass" for row in negative_records) == 1


def test_local_int1_command_bank_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"),
             env.get("PATH", "")]
        )
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    for variant in ("mcu_ahb_local_int1_bank.v",
                    "mcu_ahb_local_int2_bank.v",
                    "mcu_ahb_local_int3_bank.v"):
        output = tmp_path / (variant + ".vvp")
        result = subprocess.run([
            compiler, "-g2012", "-s", "tb_mcu_ahb_local_int1_bank",
            "-o", str(output), str(ROOT / "qualification" / variant),
            str(ROOT / "examples" / "designs" /
                "tb_mcu_ahb_local_int1_bank.v"),
        ], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        run = subprocess.run([runner, str(output)], env=env,
                             capture_output=True, text=True)
        assert run.returncode == 0, run.stdout + run.stderr
        assert "PASS: AHB-backed local_int1 pending/mask/ack/re-arm" in run.stdout
