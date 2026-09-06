"""Packing must not query a missing BRAM BEL for an inactive site profile."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _design(bel):
    bram = dict(type="ALTA_BRAM9K", parameters={},
                attributes={"BEL": bel} if bel else {},
                port_directions={"DataOutA[0]": "output", "Clk0": "input"},
                connections={"DataOutA[0]": [2], "Clk0": [3]})
    sink = dict(type="GENERIC_SLICE", attributes={},
                parameters={"K": "100", "INIT": format(0xAAAA, "016b"), "FF_USED": "0"},
                port_directions={"I": "input", "F": "output", "Q": "output"},
                connections={"I": [2, "x", "x", "x"], "F": [], "Q": []})
    clock = dict(type="MCU_BUS_CLOCK", attributes={}, parameters={},
                 port_directions={"CLK": "output"}, connections={"CLK": [3]})
    return {"modules": {"top": dict(attributes={"top": 1}, ports={},
            cells={"ram": bram, "sink": sink, "clock": clock},
            netnames={"read": dict(bits=[2], attributes={}),
                      "clock": dict(bits=[3], attributes={})})}}


def _pack(tmp_path, bel, site_profile):
    binary = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    devdb = Path(os.environ.get("AGAMEMNON_UARCH_DEVDB", str(
        ROOT / "agamemnon/engine/uarch/agrv2k/devdb_strict")))
    if not binary or not Path(binary).is_file() or not (devdb / "dev_pips.csv").is_file():
        pytest.skip("set the isolated native executable and strict devdb")
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_design(bel)))
    output = tmp_path / "packed.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGAMEMNON_", "AGRV2K_"))}
    # Isolate BEL resolution, not exact site-path replay. The ordinary strict
    # devdb does not admit every optional site-profile route table edge.
    env["AGRV2K_BRAM_PINPACK"] = "1"
    if site_profile:
        env["AGAMEMNON_BRAM_SITE_READ_PATHS"] = "1"
    result = subprocess.run([binary, "--uarch", "agrv2k", "-o", f"chipdb={devdb}",
                             "--json", str(source), "--write", str(output),
                             "--top", "top", "--pack-only"],
                            env=env, capture_output=True, text=True, timeout=60)
    transcript = result.stdout + result.stderr
    (tmp_path / "native.log").write_text(transcript)
    return result, transcript, output


def test_unassigned_bram_output_packs_without_site_profile(tmp_path):
    result, transcript, output = _pack(tmp_path, None, False)
    assert result.returncode == 0, transcript
    assert output.is_file()


@pytest.mark.parametrize("bel", ["X99Y99_BRAM", "X14Y4_SLICE0"])
def test_site_profile_refuses_missing_or_non_bram_bel_by_name(tmp_path, bel):
    result, transcript, output = _pack(tmp_path, bel, True)
    assert result.returncode > 0, transcript  # a diagnostic, not a signal/abort
    assert "invalid requested BRAM BEL" in transcript
    assert "std::out_of_range" not in transcript
    assert not output.exists()


def test_site_profile_uses_the_allocated_default_memory_site(tmp_path):
    result, transcript, output = _pack(tmp_path, None, True)
    assert result.returncode == 0, transcript
    assert "assigned BRAM 'ram' to distinct site X13Y4_BRAM" in transcript
    assert output.is_file()
    assert "std::out_of_range" not in transcript


@pytest.mark.parametrize("bel", [f"X13Y{y}_BRAM" for y in range(1, 5)])
@pytest.mark.parametrize("site_profile", [False, True])
def test_requested_bram_output_packs_at_every_site(tmp_path, bel, site_profile):
    result, transcript, output = _pack(tmp_path, bel, site_profile)
    assert result.returncode == 0, transcript
    assert output.is_file()
