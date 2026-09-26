"""Observed-value consistency must not be reported as silicon qualification."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest

from agamemnon import cli
from agamemnon.engine import verify_netlist


FIXTURE = Path(__file__).parent / "fixtures/counter_ahb_routed.json"


def test_empty_observations_do_not_pass_by_vacuous_set_inclusion(capsys):
    assert not verify_netlist.verify(FIXTURE, [], cycles=32)
    assert "NO_OBSERVATIONS" in capsys.readouterr().out


@pytest.mark.parametrize("observed", ["", ",", " , , "])
def test_cli_rejects_empty_measurements(observed, capsys):
    args = argparse.Namespace(input=str(FIXTURE), observed=observed, cycles=32,
                              stimulus=None, trace=None)
    with pytest.raises(SystemExit) as exc:
        cli.cmd_verify(args)
    assert exc.value.code == 1
    assert "NO_OBSERVATIONS" in capsys.readouterr().out


def test_stuck_value_can_match_the_set_without_proving_hardware(capsys):
    assert verify_netlist.verify(FIXTURE, [0] * 32, cycles=32)
    output = capsys.readouterr().out
    assert "CONSISTENT_WITH_MODEL" in output
    assert "25% (1/4)" in output
    assert "missing=[1, 2, 3]" in output
    assert "sequence, timing and hardware correctness are unqualified" in output
    assert "CORRECT (silicon" not in output
    assert "aliasing if nonempty" not in output


def test_matching_values_do_not_override_a_bad_read_lane_binding(tmp_path, capsys):
    doc = json.loads(FIXTURE.read_text())
    doc["modules"]["top"]["cells"]["mcu_h0"]["attributes"]["NEXTPNR_BEL"] = "X10Y5_MCU_DOUT11"
    routed = tmp_path / "wrong_lane.json"
    routed.write_text(json.dumps(doc))
    assert not verify_netlist.verify(routed, [0], cycles=32)
    output = capsys.readouterr().out
    assert "SCRAMBLED" in output and "VERDICT: MISMATCH" in output


@pytest.mark.parametrize("observed,expected", [("0,1,2,3", 0), ("7", 1)])
def test_module_entrypoint_propagates_the_comparison_result(observed, expected):
    result = subprocess.run([sys.executable, "-m", "agamemnon.engine.verify_netlist",
                             str(FIXTURE), observed, "32"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == expected, result.stdout + result.stderr
    assert ("CONSISTENT_WITH_MODEL" if expected == 0 else "MISMATCH") in result.stdout
